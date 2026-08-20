"""记忆主动召回：对话每轮用当前问题检索相关记忆 + 洞察，拼成背景块注入。

带余弦门控节流；整体加超时保护，召回是锦上添花，超时即放弃注入。
"""
import asyncio

from memory_graph.config import settings
from memory_graph.core.retrieval.searcher import search_memory
from memory_graph.logger import get_logger
from memory_graph.repositories.neo4j.memory_graph_repository import MemoryGraphRepository

logger = get_logger(__name__)

_RECALL_TIMEOUT = 3.5


def _confidence(value: object, default: float = 0.8) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _uncertain_prefix(confidence: object) -> str:
    return "待确认：" if _confidence(confidence) < settings.active_recall_uncertain_confidence else ""


async def recall_context(*, embed_client, user_id: str, query: str) -> str:
    """召回与当前问题相关的记忆事实 + 洞察，拼成背景块。无命中/超时返回空串。"""
    query = (query or "").strip()
    if not query:
        return ""
    try:
        return await asyncio.wait_for(
            _do_recall(embed_client, user_id, query), timeout=_RECALL_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.info("主动召回超时（>%.1fs），跳过注入: user=%s", _RECALL_TIMEOUT, user_id)
        return ""
    except Exception as e:
        logger.warning("主动召回失败（忽略）: user=%s err=%s", user_id, e)
        return ""


async def _do_recall(embed_client, user_id: str, query: str) -> str:
    uid = str(user_id)
    try:
        qvec = await embed_client.embed_one(query)
    except Exception as e:
        logger.warning("主动召回-向量化失败（忽略）: %s", e)
        return ""

    repo = MemoryGraphRepository()

    async def _recall_insights() -> list[str]:
        try:
            rows = await repo.search_insights_by_vector(
                uid, qvec, settings.active_recall_insight_top_k
            )
            return [
                (r.get("content") or "").strip()
                for r in rows if (r.get("content") or "").strip()
            ]
        except Exception as e:
            logger.warning("主动召回-洞察失败（忽略）: %s", e)
            return []

    async def _recall_entities() -> list[str]:
        lines: list[str] = []
        try:
            hits = await search_memory(
                embed_client=embed_client, user_id=user_id, query=query,
                top_k=settings.active_recall_entity_top_k,
                min_vector_score=settings.active_recall_min_score,
                min_confidence=settings.active_recall_min_confidence,
                use_reliability_score=True, query_vector=qvec,
            )
            for h in hits:
                name = h.get("name") or ""
                desc = (h.get("description") or "").strip()
                prefix = _uncertain_prefix(h.get("confidence"))
                lines.append(f"- {prefix}{name}：{desc}" if desc else f"- {prefix}{name}")
                for rel in h.get("relations", [])[:2]:
                    obj = rel.get("object_name") or ""
                    if obj:
                        rel_prefix = _uncertain_prefix(rel.get("confidence"))
                        lines.append(f"  · {rel_prefix}{name} {rel.get('predicate', '')} {obj}")
        except Exception as e:
            logger.warning("主动召回-记忆失败（忽略）: %s", e)
        return lines

    insight_lines, memory_lines = await asyncio.gather(_recall_insights(), _recall_entities())

    if not insight_lines and not memory_lines:
        return ""

    parts: list[str] = [
        "<memory-context>",
        "以下是关于用户的背景信息，仅供你参考作答。",
        '禁止在回复中提及这些信息的存在、来源或记忆系统，不要说"根据记忆""我记得"等，直接自然地融入回答即可。',
        "待确认的内容不要当作确定事实，回答时应表达不确定或向用户确认。",
    ]
    if insight_lines:
        parts.append("用户洞察：" + "；".join(insight_lines))
    if memory_lines:
        parts.append("用户记忆：")
        parts.extend(memory_lines)
    parts.append("</memory-context>")
    block = "\n".join(parts)

    if len(block) > settings.active_recall_max_chars:
        block = block[: settings.active_recall_max_chars] + "…"
    logger.info("主动召回命中: user=%s 洞察=%d 记忆行=%d",
                user_id, len(insight_lines), len(memory_lines))
    return block


__all__ = ["recall_context"]
