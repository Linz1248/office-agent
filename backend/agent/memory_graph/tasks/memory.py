"""记忆萃取 Celery 任务：取 memories 原文 → 萃取流水线 → 写 Neo4j → 回写状态。

任务为同步入口，内部用 asyncio.run 跑异步；每个任务用任务级 PG 引擎（NullPool）
与任务级 Neo4j 驱动，避免事件循环绑定问题。
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import memory_graph.models  # noqa: F401  注册 ORM metadata
from memory_graph.celery_app import celery_app
from memory_graph.core.extraction.orchestrator import run_extraction
from memory_graph.db import neo4j
from memory_graph.db.audit_db import create_task_engine
from memory_graph.logger import get_logger
from memory_graph.models.memory_model import (
    MEMORY_STATUS_DONE,
    MEMORY_STATUS_EXTRACTING,
    MEMORY_STATUS_FAILED,
)
from memory_graph.repositories.memory_repository import MemoryRepository
from memory_graph.runtime import ensure_initialized, get_clients

logger = get_logger(__name__)


async def _run(memory_id: str) -> None:
    await ensure_initialized()
    chat_client, embed_client = get_clients()
    if chat_client is None or embed_client is None:
        logger.warning("萃取任务跳过：客户端未就绪 memory=%s", memory_id)
        return
    engine_db = create_task_engine()
    session_maker = async_sessionmaker(engine_db, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_maker() as session:
            await _extract(session, memory_id, chat_client, embed_client)
    finally:
        await engine_db.dispose()
        await neo4j.close()


async def _extract(session: AsyncSession, memory_id: str, chat_client, embed_client) -> None:
    repo = MemoryRepository(session)
    memory = await repo.get_by_id(memory_id)
    if not memory:
        logger.warning("萃取任务：记忆不存在 %s", memory_id)
        return
    try:
        memory.status = MEMORY_STATUS_EXTRACTING
        await repo.save(memory)

        stats = await run_extraction(
            chat_client=chat_client,
            embed_client=embed_client,
            user_id=str(memory.user_id),
            text=memory.raw_text,
            source=memory.source,
            source_message_id=memory.source_message_id,
        )

        memory.status = MEMORY_STATUS_DONE
        memory.graph_dialogue_id = stats.dialogue_id or None
        memory.graph_stats = stats.to_dict()
        memory.error_msg = None
        await repo.save(memory)
        logger.info("记忆萃取完成: %s %s", memory_id, stats.to_dict())
    except Exception as e:
        logger.error("记忆萃取失败: %s: %s", memory_id, e, exc_info=True)
        memory.status = MEMORY_STATUS_FAILED
        memory.error_msg = str(e)[:500]
        await repo.save(memory)


@celery_app.task(name="memory_graph.tasks.memory.extract_memory")
def extract_memory_task(memory_id: str) -> str:
    """记忆萃取的 Celery 任务入口。"""
    asyncio.run(_run(memory_id))
    return memory_id
