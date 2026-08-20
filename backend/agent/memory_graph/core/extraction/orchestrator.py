"""记忆萃取编排：把一段来源文本完整处理并写入图谱。

流程：分块 → 陈述抽取 → 三元组萃取 → 实体 name 向量化
→ 批内去重 → 与图谱已有实体二层融合 → 组装四层溯源图模型 → 写 Neo4j
→ 增量社区聚类 → 反思增量触发。
"""
from datetime import datetime

from memory_graph.core.extraction import dedup, embedder, triplet_extractor
from memory_graph.core.extraction.models import ExtractedEvent, ExtractedTriplet
from memory_graph.core.graph_models import (
    SOURCE_MANUAL,
    ChunkNode,
    DialogueNode,
    EntityNode,
    EventNode,
    InvolvesEdge,
    MentionEdge,
    RelationEdge,
    StatementNode,
)
from memory_graph.core.ontology import normalize_entity_type, normalize_predicate
from memory_graph.core.preprocessing import chunker, statement_extractor
from memory_graph.logger import get_logger
from memory_graph.repositories.neo4j.memory_graph_repository import MemoryGraphRepository

logger = get_logger(__name__)


class ExtractionStats:
    def __init__(self):
        self.dialogue_id: str = ""
        self.chunk_count = 0
        self.statement_count = 0
        self.entity_count = 0
        self.relation_count = 0
        self.event_count = 0
        self.entity_ids: list[str] = []

    def to_dict(self) -> dict:
        return {
            "dialogue_id": self.dialogue_id,
            "chunks": self.chunk_count,
            "statements": self.statement_count,
            "entities": self.entity_count,
            "relations": self.relation_count,
            "events": self.event_count,
            "entity_ids": self.entity_ids,
        }


def _parse_dt(value: str | None) -> datetime | None:
    if not value or str(value).strip().upper() in {"NULL", "NONE", ""}:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def run_extraction(
    *,
    chat_client,
    embed_client,
    user_id: str,
    text: str,
    source: str = SOURCE_MANUAL,
    source_message_id: str | None = None,
    dialog_at: datetime | None = None,
) -> ExtractionStats:
    """对一段文本执行完整萃取并写入图谱。"""
    stats = ExtractionStats()
    user_id = str(user_id)
    dialog_at = dialog_at or datetime.now()

    text = (text or "").strip()
    if not text:
        return stats

    dialogue = DialogueNode(
        user_id=user_id, content=text, source=source,
        source_message_id=source_message_id, dialog_at=dialog_at,
    )
    stats.dialogue_id = dialogue.id

    chunk_texts = chunker.split_chunks(text)
    chunks: list[ChunkNode] = [
        ChunkNode(user_id=user_id, dialog_id=dialogue.id, content=ct, sequence=i)
        for i, ct in enumerate(chunk_texts)
    ]
    stats.chunk_count = len(chunks)

    statements: list[StatementNode] = []
    entity_pool: list[EntityNode] = []
    mentions: list[MentionEdge] = []
    pending_triplets: list[tuple[str, ExtractedTriplet, dict[int, EntityNode]]] = []
    pending_events: list[tuple[ExtractedEvent, dict[str, EntityNode]]] = []

    dialog_at_str = dialog_at.isoformat()

    for chunk in chunks:
        extracted_stmts = await statement_extractor.extract_statements(
            chat_client, chunk.content, context=text if len(chunks) > 1 else None
        )
        if not extracted_stmts:
            continue
        triplet_results = await triplet_extractor.extract_triplets_batch(
            chat_client, extracted_stmts, context=chunk.content, dialog_at=dialog_at_str
        )
        chunk_name_map: dict[str, EntityNode] = {}
        for stmt, tres in zip(extracted_stmts, triplet_results):
            stmt_node = StatementNode(
                user_id=user_id, chunk_id=chunk.id, statement=stmt.statement,
                stmt_type=stmt.statement_type, temporal_type=stmt.temporal_type,
                dialog_at=dialog_at,
                importance=stmt.importance, confidence=stmt.confidence,
                has_emotional_state=stmt.has_emotional_state,
                emotion_type=stmt.emotion_type,
                emotion_intensity=stmt.emotion_intensity,
                emotion_keywords=stmt.emotion_keywords,
            )
            statements.append(stmt_node)
            idx_map: dict[int, EntityNode] = {}
            for ent in tres.entities:
                node = EntityNode(
                    user_id=user_id, name=ent.name.strip(),
                    type=normalize_entity_type(ent.type),
                    description=ent.description or "",
                    importance=ent.importance, confidence=ent.confidence,
                )
                idx_map[ent.entity_idx] = node
                entity_pool.append(node)
                chunk_name_map[node.name] = node
                mentions.append(MentionEdge(
                    user_id=user_id, statement_id=stmt_node.id, entity_id=node.id
                ))
            for trip in tres.triplets:
                pending_triplets.append((stmt_node.id, trip, idx_map))
            for ev in tres.events:
                pending_events.append((ev, chunk_name_map))

    stats.statement_count = len(statements)
    if not entity_pool:
        await _persist(
            dialogue=dialogue, chunks=chunks, statements=statements,
            entities=[], mentions=mentions, relations=[], events=[], involves=[],
        )
        return stats

    vectors = await embedder.embed_texts(embed_client, [e.name for e in entity_pool])
    for ent, vec in zip(entity_pool, vectors):
        ent.name_embedding = vec

    deduped, redirect1 = await dedup.dedup_within_batch(chat_client, entity_pool)
    repo = MemoryGraphRepository()
    final_entities, redirect2 = await dedup.merge_with_graph(
        chat_client, repo, user_id, deduped
    )

    def resolve(eid: str) -> str:
        eid = redirect1.get(eid, eid)
        eid = redirect2.get(eid, eid)
        return eid

    final_by_id = {e.id: e for e in final_entities}
    stats.entity_count = len(final_entities)
    stats.entity_ids = list(final_by_id.keys())

    for m in mentions:
        m.entity_id = resolve(m.entity_id)
    mentions = [m for m in mentions if m.entity_id in final_by_id]

    relations: list[RelationEdge] = []
    for stmt_id, trip, idx_map in pending_triplets:
        subj = idx_map.get(trip.subject_id)
        obj = idx_map.get(trip.object_id)
        if not subj or not obj:
            continue
        sid = resolve(subj.id)
        oid = resolve(obj.id)
        if sid not in final_by_id or oid not in final_by_id or sid == oid:
            continue
        relations.append(RelationEdge(
            user_id=user_id, source_id=sid, target_id=oid,
            predicate=normalize_predicate(trip.predicate),
            predicate_surface=trip.predicate_surface or "",
            source_text="", statement_id=stmt_id, value=trip.value,
            valid_at=_parse_dt(trip.valid_at), invalid_at=_parse_dt(trip.invalid_at),
            importance=trip.importance, confidence=trip.confidence,
        ))
    stats.relation_count = len(relations)

    events: list[EventNode] = []
    involves: list[InvolvesEdge] = []
    for ev, name_map in pending_events:
        title = (ev.title or "").strip()
        if not title:
            continue
        event_node = EventNode(
            user_id=user_id, title=title,
            description=ev.description or "",
            event_time=_parse_dt(ev.event_time),
        )
        linked: set[str] = set()
        for pname in ev.participants:
            ent = name_map.get((pname or "").strip())
            if not ent:
                continue
            eid = resolve(ent.id)
            if eid in final_by_id and eid not in linked:
                linked.add(eid)
                involves.append(InvolvesEdge(
                    user_id=user_id, event_id=event_node.id, entity_id=eid
                ))
        events.append(event_node)
    stats.event_count = len(events)

    await _persist(
        dialogue=dialogue, chunks=chunks, statements=statements,
        entities=final_entities, mentions=mentions, relations=relations,
        events=events, involves=involves,
    )

    try:
        from memory_graph.core.clustering.label_propagation import LabelPropagationEngine

        engine = LabelPropagationEngine(chat_client=chat_client)
        await engine.run(user_id, new_entity_ids=stats.entity_ids)
    except Exception as e:
        logger.warning("增量社区聚类失败（忽略）: %s", e)

    try:
        await _maybe_trigger_reflection(user_id, len(stats.entity_ids or []))
    except Exception as e:
        logger.warning("反思增量触发失败（忽略）: %s", e)

    logger.info("记忆萃取完成: %s", stats.to_dict())
    return stats


async def _maybe_trigger_reflection(user_id: str, new_count: int) -> None:
    """累计新增实体数达阈值则派发一次单用户反思（失败不影响萃取）。

    计数走 runtime.bump_reflection_counter（优先 Redis INCRBY，回退 SQLite）；
    派发优先 Celery（显式启用时），否则进程内 asyncio 兜底。
    """
    if new_count <= 0:
        return
    from memory_graph.config import settings
    from memory_graph.runtime import (
        bump_reflection_counter,
        dispatch_reflection,
        reset_reflection_counter,
    )

    total = await bump_reflection_counter(user_id, new_count)
    if total < 0:
        return  # 计数失败，跳过触发（不阻断萃取）
    if total >= settings.reflection_trigger_threshold:
        await reset_reflection_counter(user_id)
        dispatch_reflection(user_id)
        logger.info("反思增量触发: user=%s 累计新增=%d", user_id, total)


async def _persist(
    *,
    dialogue: DialogueNode,
    chunks: list[ChunkNode],
    statements: list[StatementNode],
    entities: list[EntityNode],
    mentions: list[MentionEdge],
    relations: list[RelationEdge],
    events: list[EventNode],
    involves: list[InvolvesEdge],
) -> None:
    repo = MemoryGraphRepository()
    await repo.save_graph(
        dialogues=[dialogue], chunks=chunks, statements=statements,
        entities=entities, events=events, mentions=mentions,
        relations=relations, involves=involves,
    )


__all__ = ["run_extraction", "ExtractionStats"]
