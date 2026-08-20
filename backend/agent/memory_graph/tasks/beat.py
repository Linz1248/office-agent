"""定时/批量 Celery 任务：全量巩固 / 反思 / 社区聚类，及单用户反思（增量触发）。

用户列表取自 Neo4j 图谱中出现过的 distinct user_id（与 office-agent 用户体系解耦）。
"""
import asyncio

from memory_graph.celery_app import celery_app
from memory_graph.db import neo4j
from memory_graph.logger import get_logger
from memory_graph.runtime import ensure_initialized, get_clients

logger = get_logger(__name__)


async def _all_user_ids() -> list[str]:
    driver = neo4j.get_driver()
    async with driver.session() as s:
        result = await s.run("MATCH (e:Entity) RETURN DISTINCT e.user_id AS uid")
        return [rec["uid"] for rec in [r async for r in result] if rec["uid"]]


async def _run_consolidation() -> int:
    from memory_graph.core.consolidation.consolidator import ConsolidationEngine

    await ensure_initialized()
    chat_client, _ = get_clients()
    count = 0
    try:
        user_ids = await _all_user_ids()
    except Exception as e:
        logger.warning("巩固：获取用户列表失败: %s", e)
        return 0
    for uid in user_ids:
        try:
            await ConsolidationEngine(chat_client=chat_client).run(str(uid))
            count += 1
        except Exception as e:
            logger.warning("用户 %s 记忆巩固失败: %s", uid, e)
    await neo4j.close()
    logger.info("记忆巩固批量完成: %d 个用户", count)
    return count


@celery_app.task(name="memory_graph.tasks.beat.consolidate_memory")
def consolidate_memory() -> int:
    return asyncio.run(_run_consolidation())


async def _run_reflection() -> int:
    from memory_graph.core.reflection.reflector import ReflectionEngine

    await ensure_initialized()
    chat_client, embed_client = get_clients()
    count = 0
    try:
        user_ids = await _all_user_ids()
    except Exception as e:
        logger.warning("反思：获取用户列表失败: %s", e)
        return 0
    for uid in user_ids:
        try:
            await ReflectionEngine(
                chat_client=chat_client, embed_client=embed_client
            ).run(str(uid))
            count += 1
        except Exception as e:
            logger.warning("用户 %s 反思失败: %s", uid, e)
    await neo4j.close()
    logger.info("反思批量完成: %d 个用户", count)
    return count


@celery_app.task(name="memory_graph.tasks.beat.reflect_memory")
def reflect_memory() -> int:
    return asyncio.run(_run_reflection())


async def _run_clustering() -> int:
    from memory_graph.core.clustering.label_propagation import LabelPropagationEngine

    await ensure_initialized()
    chat_client, _ = get_clients()
    count = 0
    try:
        user_ids = await _all_user_ids()
    except Exception as e:
        logger.warning("聚类：获取用户列表失败: %s", e)
        return 0
    for uid in user_ids:
        try:
            await LabelPropagationEngine(chat_client=chat_client).full_clustering(str(uid))
            count += 1
        except Exception as e:
            logger.warning("用户 %s 全量聚类失败: %s", uid, e)
    await neo4j.close()
    logger.info("全量社区聚类完成: %d 个用户", count)
    return count


@celery_app.task(name="memory_graph.tasks.beat.cluster_communities")
def cluster_communities() -> int:
    return asyncio.run(_run_clustering())


async def _run_reflection_for_user(user_id: str) -> dict:
    from memory_graph.core.reflection.reflector import ReflectionEngine

    await ensure_initialized()
    chat_client, embed_client = get_clients()
    try:
        engine = ReflectionEngine(chat_client=chat_client, embed_client=embed_client)
        return await engine.run(user_id)
    finally:
        await neo4j.close()


@celery_app.task(name="memory_graph.tasks.beat.reflect_user")
def reflect_user_task(user_id: str) -> dict:
    """单用户反思（萃取攒够 N 条后增量触发）。"""
    return asyncio.run(_run_reflection_for_user(user_id))
