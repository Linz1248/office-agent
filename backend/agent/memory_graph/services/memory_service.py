"""记忆业务服务：主动记住、列表/详情/删除、检索、画像、审查纠错、社区、巩固、反思。

与 Comet 的差异：
  - ``user_id`` 为 String（office-agent 用户名）。
  - chat/embed 客户端由 ``runtime.get_clients()`` 全局提供（复用 AgentScope 模型），
    不再按用户从 DB 解析 provider 配置。
  - 校验失败直接抛 ``HTTPException``（office-agent 风格），不再用 Comet 的 BizError。
"""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from memory_graph.logger import get_logger
from memory_graph.models.memory_model import (
    MEMORY_SOURCE_MANUAL,
    MEMORY_STATUS_PENDING,
    Memory,
)
from memory_graph.repositories.memory_repository import MemoryRepository
from memory_graph.runtime import get_clients

logger = get_logger(__name__)


class MemoryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MemoryRepository(session)

    async def remember(self, user_id: str, text: str) -> Memory:
        """主动记住：落库 + 派发异步萃取任务。

        ``dispatch_extraction`` 内部即建审计行并派发（Celery / 进程内），故此处不再
        重复建行，仅按返回 id 取回 Memory 返回。模块未就绪时仍落一条 pending 行供展示。
        """
        text = (text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="记忆内容不能为空")
        from memory_graph.runtime import dispatch_extraction

        memory_id = await dispatch_extraction(user_id, text, source=MEMORY_SOURCE_MANUAL)
        if memory_id:
            memory = await self.repo.get_by_id(memory_id)
            if memory is not None:
                logger.info("主动记住已提交萃取: memory=%s", memory.id)
                return memory
        # 模块未就绪（dispatch 返回 None）：仅落一条 pending 行供列表展示
        memory = Memory(
            user_id=user_id,
            raw_text=text,
            source=MEMORY_SOURCE_MANUAL,
            status=MEMORY_STATUS_PENDING,
        )
        memory = await self.repo.create(memory)
        logger.info("主动记住已登记（模块未就绪，暂未萃取）: memory=%s", memory.id)
        return memory

    async def get_detail(self, user_id: str, memory_id: str) -> Memory:
        memory = await self.repo.get_by_id(memory_id)
        if not memory or memory.user_id != user_id:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return memory

    async def list_memories(
        self, user_id: str, page: int, page_size: int
    ) -> tuple[list[Memory], int]:
        return await self.repo.list_by_user(user_id, page, page_size)

    async def delete(self, user_id: str, memory_id: str) -> None:
        memory = await self.get_detail(user_id, memory_id)
        await self.repo.delete(memory)

    async def search(self, user_id: str, query: str, top_k: int = 10) -> list[dict]:
        """记忆检索：图谱混合检索（向量+全文+邻居遍历）。"""
        from memory_graph.core.retrieval.searcher import search_memory

        _, embed_client = get_clients()
        if embed_client is None:
            return []
        return await search_memory(
            embed_client=embed_client, user_id=user_id, query=query, top_k=top_k
        )

    async def get_profile(self, user_id: str) -> dict:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        repo = MemoryGraphRepository()
        uid = str(user_id)
        entities = await repo.list_all_entities(uid)
        counts = await repo.entity_type_counts(uid)

        groups: dict[str, list[dict]] = {}
        for e in entities:
            item = {
                "id": e.get("id"), "name": e.get("name"), "type": e.get("type"),
                "description": e.get("description") or "",
                "aliases": e.get("aliases") or [],
                "relations": e.get("relations") or [],
                "importance": e.get("importance", 0.5),
                "confidence": e.get("confidence", 0.8),
                "memory_layer": e.get("memory_layer") or "short_term",
                "access_count": e.get("access_count", 0),
                "mention_count": e.get("mention_count", 1),
                "core_facts": e.get("core_facts") or [],
                "traits": e.get("traits") or [],
            }
            groups.setdefault(item["type"], []).append(item)

        return {
            "total": len(entities),
            "type_counts": {c["type"]: c["cnt"] for c in counts},
            "groups": [{"type": t, "entities": items} for t, items in groups.items()],
        }

    async def delete_entity(self, user_id: str, entity_id: str) -> None:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        await MemoryGraphRepository().delete_entity(str(user_id), entity_id)

    # ── 人类反馈闭环 ──

    async def review_overview(self, user_id: str, days: int = 30) -> dict:
        from datetime import datetime as _dt, timedelta, timezone as _tz

        from memory_graph.repositories.memory_correction_repository import (
            MemoryCorrectionRepository,
        )
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        uid = str(user_id)
        repo = MemoryGraphRepository()
        entities = await repo.list_all_entities(uid)
        type_dist: dict[str, int] = {}
        conf_buckets = [0] * 5
        long_term = 0
        verified = 0
        since = _dt.now(_tz.utc) - timedelta(days=days)
        since_date = since.date()
        daily_new: dict[str, int] = {}
        for e in entities:
            t = e.get("type") or "其他"
            type_dist[t] = type_dist.get(t, 0) + 1
            conf = float(e.get("confidence", 0.8) or 0.8)
            idx = min(4, max(0, int(conf * 5)))
            conf_buckets[idx] += 1
            if e.get("memory_layer") == "long_term":
                long_term += 1
            if e.get("human_verified"):
                verified += 1
            ca = e.get("created_at")
            if ca:
                try:
                    d = ca.to_native().date() if hasattr(ca, "to_native") else ca.date()
                    if d >= since_date:
                        key = d.isoformat()
                        daily_new[key] = daily_new.get(key, 0) + 1
                except Exception:  # noqa: BLE001
                    pass
        trend = [{"date": d, "count": daily_new.get(d, 0)} for d in sorted(daily_new.keys())]
        try:
            correction_counts = await MemoryCorrectionRepository(self.session).count_by_action(user_id)
        except Exception:  # noqa: BLE001
            correction_counts = {}
        total_relations = sum(len(e.get("relations") or []) for e in entities)
        pending = sum(
            1 for e in entities
            if not e.get("human_verified")
            and float(e.get("confidence", 0.8) or 0.8) < 0.75
        )
        return {
            "total_entities": len(entities),
            "total_relations": total_relations,
            "long_term": long_term,
            "verified": verified,
            "pending": pending,
            "type_distribution": [
                {"type": t, "count": c}
                for t, c in sorted(type_dist.items(), key=lambda x: x[1], reverse=True)
            ],
            "confidence_buckets": [
                {"range": "0~0.2", "count": conf_buckets[0]},
                {"range": "0.2~0.4", "count": conf_buckets[1]},
                {"range": "0.4~0.6", "count": conf_buckets[2]},
                {"range": "0.6~0.8", "count": conf_buckets[3]},
                {"range": "0.8~1.0", "count": conf_buckets[4]},
            ],
            "trend": trend,
            "correction_counts": correction_counts,
            "days": days,
        }

    async def list_review_entities(
        self, user_id: str, *, max_confidence: float = 0.75,
        type_: str | None = None, include_verified: bool = False, limit: int = 50,
    ) -> list[dict]:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        entities = await MemoryGraphRepository().list_all_entities(str(user_id))
        out: list[dict] = []
        for e in entities:
            conf = float(e.get("confidence", 0.8) or 0.8)
            if conf > max_confidence:
                continue
            if not include_verified and e.get("human_verified"):
                continue
            if type_ and e.get("type") != type_:
                continue
            out.append({
                "id": e.get("id"), "name": e.get("name"), "type": e.get("type"),
                "description": e.get("description"),
                "aliases": e.get("aliases") or [],
                "confidence": round(conf, 3),
                "memory_layer": e.get("memory_layer") or "short_term",
                "human_verified": bool(e.get("human_verified")),
                "relations": [
                    {"predicate": r.get("predicate"), "object_name": r.get("object_name"),
                     "object_type": r.get("object_type"), "confidence": r.get("confidence")}
                    for r in (e.get("relations") or [])[:5]
                ],
            })
        out.sort(key=lambda x: x["confidence"])
        return out[:limit]

    async def confirm_entity(self, user_id: str, entity_id: str, reason: str | None = None) -> dict:
        from memory_graph.repositories.memory_correction_repository import (
            MemoryCorrectionRepository,
        )
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        uid = str(user_id)
        repo = MemoryGraphRepository()
        before = await repo.entity_snapshot(uid, entity_id) or {}
        await repo.human_verify_entity(uid, entity_id)
        try:
            await MemoryCorrectionRepository(self.session).record(
                user_id=user_id, entity_id=entity_id, action="confirm",
                before=_serializable(before),
                after={"human_verified": True, "confidence": 1.0},
                reason=reason or "用户确认",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("memory_corrections 写入失败(不影响 Neo4j 已生效): %s", e)
        return {"ok": True, "entity_id": entity_id}

    async def correct_entity_with_reason(
        self, user_id: str, entity_id: str, *, name: str | None = None,
        type_: str | None = None, description: str | None = None,
        aliases: list[str] | None = None, reason: str | None = None,
    ) -> dict:
        from memory_graph.repositories.memory_correction_repository import (
            MemoryCorrectionRepository,
        )
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        uid = str(user_id)
        repo = MemoryGraphRepository()
        before = await repo.entity_snapshot(uid, entity_id) or {}
        result = await repo.correct_entity(
            uid, entity_id, name=name, type_=type_, description=description, aliases=aliases,
        )
        after = {
            "name": result.get("name") if result else name,
            "type": result.get("type") if result else type_,
            "description": description, "aliases": aliases,
            "human_verified": True, "confidence": 1.0,
        }
        try:
            await MemoryCorrectionRepository(self.session).record(
                user_id=user_id, entity_id=entity_id, action="correct",
                before=_serializable(before),
                after={k: v for k, v in after.items() if v is not None},
                reason=reason or "用户修正",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("memory_corrections 写入失败: %s", e)
        return {"ok": True, "entity_id": entity_id, "name": after["name"]}

    async def delete_entity_with_reason(
        self, user_id: str, entity_id: str, reason: str | None = None
    ) -> dict:
        from memory_graph.repositories.memory_correction_repository import (
            MemoryCorrectionRepository,
        )
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        uid = str(user_id)
        repo = MemoryGraphRepository()
        before = await repo.entity_snapshot(uid, entity_id) or {}
        try:
            await MemoryCorrectionRepository(self.session).record(
                user_id=user_id, entity_id=entity_id, action="delete",
                before=_serializable(before), reason=reason or "用户删除",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("delete 落库失败,放弃删除: %s", e)
            return {"ok": False, "error": "落库失败,已取消删除"}
        await repo.delete_entity(uid, entity_id)
        return {"ok": True, "entity_id": entity_id}

    async def list_communities(self, user_id: str) -> list[dict]:
        from memory_graph.repositories.neo4j.community_repository import CommunityRepository

        return await CommunityRepository().list_communities(str(user_id))

    async def community_members(self, user_id: str, community_id: str) -> list[dict]:
        from memory_graph.repositories.neo4j.community_repository import CommunityRepository

        members = await CommunityRepository().get_members(str(user_id), community_id)
        return [
            {"id": m.get("id"), "name": m.get("name"), "type": m.get("type"),
             "description": m.get("description") or "", "aliases": m.get("aliases") or []}
            for m in members
        ]

    async def recluster(self, user_id: str) -> None:
        from memory_graph.core.clustering.label_propagation import LabelPropagationEngine

        await self.merge_duplicates(user_id)
        chat_client, _ = get_clients()
        await LabelPropagationEngine(chat_client=chat_client).full_clustering(str(user_id))

    async def merge_duplicates(self, user_id: str) -> int:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        return await MemoryGraphRepository().merge_duplicate_entities(str(user_id))

    async def consolidate(self, user_id: str) -> dict:
        from memory_graph.core.consolidation.consolidator import ConsolidationEngine

        chat_client, _ = get_clients()
        return await ConsolidationEngine(chat_client=chat_client).run(str(user_id))

    async def reflect(self, user_id: str) -> dict:
        from memory_graph.core.reflection.reflector import ReflectionEngine

        chat_client, embed_client = get_clients()
        return await ReflectionEngine(
            chat_client=chat_client, embed_client=embed_client
        ).run(str(user_id))

    async def list_insights(self, user_id: str) -> list[dict]:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        rows = await MemoryGraphRepository().list_insights(str(user_id))
        return [
            {"id": r.get("id"), "theme": r.get("theme") or "",
             "content": r.get("content") or "",
             "importance": r.get("importance", 0.6),
             "confidence": r.get("confidence", 0.7),
             "source_count": r.get("source_count", 0),
             "created_at": r.get("created_at"), "updated_at": r.get("updated_at")}
            for r in rows
        ]

    async def delete_insight(self, user_id: str, insight_id: str) -> None:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        await MemoryGraphRepository().delete_insight(str(user_id), insight_id)

    async def get_graph(self, user_id: str) -> dict:
        from memory_graph.repositories.neo4j.community_repository import CommunityRepository
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        uid = str(user_id)
        repo = MemoryGraphRepository()
        raw_nodes = await repo.graph_full_nodes(uid)
        raw_edges = await repo.graph_full_edges(uid)
        communities = await CommunityRepository().list_communities(uid)

        def _disp_name(kind: str, name: str | None) -> str:
            text = (name or "").strip().replace("\n", " ")
            if kind in ("Entity", "Event"):
                return text
            return text[:24] + ("…" if len(text) > 24 else "")

        nodes = [
            {
                "id": n.get("id"), "kind": n.get("kind") or "Entity",
                "name": _disp_name(n.get("kind") or "Entity", n.get("name")),
                "type": n.get("type"), "description": n.get("description") or "",
                "community_id": n.get("community_id"),
                "importance": n.get("importance", 0.5),
                "memory_layer": n.get("memory_layer") or "short_term",
                "access_count": n.get("access_count", 0),
                "mention_count": n.get("mention_count", 1),
                "aliases": n.get("aliases") or [],
                "core_facts": n.get("core_facts") or [],
                "traits": n.get("traits") or [],
            }
            for n in raw_nodes
        ]
        edges = [
            {"source": e.get("source"), "target": e.get("target"),
             "rel": e.get("rel") or "", "predicate": e.get("predicate") or "",
             "predicate_surface": e.get("predicate_surface") or ""}
            for e in raw_edges if e.get("source") and e.get("target")
        ]
        return {"nodes": nodes, "edges": edges, "communities": communities}

    async def get_entity_subgraph(self, user_id: str, entity_id: str) -> dict:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        raw_nodes, raw_edges = await MemoryGraphRepository().entity_subgraph(
            str(user_id), entity_id
        )
        nodes = [
            {"id": n.get("id"), "name": n.get("name"), "type": n.get("type"),
             "description": n.get("description") or "", "community_id": n.get("community_id")}
            for n in raw_nodes
        ]
        edges = [
            {"source": e.get("source"), "target": e.get("target"),
             "predicate": e.get("predicate") or "",
             "predicate_surface": e.get("predicate_surface") or ""}
            for e in raw_edges if e.get("source") and e.get("target")
        ]
        return {"center": entity_id, "nodes": nodes, "edges": edges}

    async def get_timeline(self, user_id: str) -> list[dict]:
        from memory_graph.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        rows = await MemoryGraphRepository().event_timeline(str(user_id))
        return [
            {"id": r.get("id"), "title": r.get("title"),
             "description": r.get("description") or "",
             "event_time": r.get("event_time"), "created_at": r.get("created_at"),
             "participants": r.get("participants") or []}
            for r in rows
        ]

    @staticmethod
    def to_out_dict(memory: Memory) -> dict:
        return {
            "id": str(memory.id),
            "raw_text": memory.raw_text,
            "source": memory.source,
            "status": memory.status,
            "error_msg": memory.error_msg,
            "graph_stats": memory.graph_stats,
            "created_at": memory.created_at.isoformat() if memory.created_at else None,
        }


def _serializable(snapshot: dict) -> dict:
    """Neo4j DateTime / Date 等转字符串，保证 JSONB 写入不炸。"""
    out: dict = {}
    for k, v in (snapshot or {}).items():
        if hasattr(v, "to_native"):
            try:
                out[k] = v.to_native().isoformat()
            except Exception:  # noqa: BLE001
                out[k] = str(v)
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list):
            out[k] = [x if isinstance(x, (str, int, float, bool)) else str(x) for x in v]
        else:
            out[k] = str(v)
    return out
