"""记忆图谱模块运行时：生命周期 / 多租户上下文 / 萃取派发 / 反思计数。

与 office-agent 的 ``kb`` 模块接入面保持一致：``init`` / ``is_ready`` /
``set_memory_context`` / ``close``，外加 ``dispatch_extraction``（中间件写回用）。

降级策略（确保项目正确运行）：
  - Neo4j / 审计库 / embedding 任一不可用 -> ``is_ready()=False``，模块整体旁路，
    智能体其余能力不受影响。
  - 反思增量计数优先 Redis（``INCRBY``，Comet 做法）；Redis 不可用时回退审计库
    SQLite 表，确保计数在任何部署形态下都不丢、不阻断萃取。
  - 萃取派发默认进程内 asyncio 后台任务（零外部依赖）；``celery_enabled=True``
    且 Redis broker 可用时走 Celery 队列（高并发/多实例部署）。
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar

from memory_graph.config import settings
from memory_graph.db.audit_db import Base, SessionLocal, close as close_audit_db
from memory_graph.db.audit_db import engine as audit_engine
from memory_graph.db.neo4j import close as close_neo4j
from memory_graph.logger import get_logger
from memory_graph.models import counter_model  # noqa: F401 注册 metadata
from memory_graph.models import memory_correction_model  # noqa: F401
from memory_graph.models import memory_model  # noqa: F401
from memory_graph.models.counter_model import MemoryCounter
from memory_graph.models.memory_model import (
    MEMORY_STATUS_DONE,
    MEMORY_STATUS_EXTRACTING,
    MEMORY_STATUS_FAILED,
    MEMORY_STATUS_PENDING,
    Memory,
)
from memory_graph.repositories.memory_repository import MemoryRepository

logger = get_logger(__name__)

# ── 模块状态 ──
_init_done = False
_ready = False
_chat_client = None
_embed_client = None
_retry_task: asyncio.Task | None = None
_keepalive_task: asyncio.Task | None = None
_RETRY_INTERVAL = 30  # 初始化失败后的自愈重试间隔（秒）

# ── 多租户上下文（与 kb.py 同模式）──
_current_user: ContextVar[str] = ContextVar("memory_graph_current_user", default="")


def set_memory_context(user_id: str) -> None:
    _current_user.set(user_id or "")


def current_user_id() -> str:
    return _current_user.get()


def is_ready() -> bool:
    return _ready


def get_clients():
    """返回 (chat_client, embed_client)。未就绪时为 (None, None)。"""
    return _chat_client, _embed_client


async def init_memory_graph(chat_model=None, embedding_model=None) -> bool:
    """初始化模块：构建客户端、建图 schema、建审计库表。

    可由 ``main.py`` lifespan 调用并显式注入 AgentScope 模型；不传则在进程内按
    默认配置构建（Celery worker 也会走这条路径）。任一致命依赖不可用时优雅降级。
    """
    global _init_done, _ready, _chat_client, _embed_client
    if _init_done:
        return _ready
    _init_done = True

    from memory_graph.llm_bridge import AgentScopeLLMClient, build_default_clients

    # 1. 客户端：显式注入优先，否则默认构建
    if chat_model is not None:
        _chat_client = AgentScopeLLMClient(chat_model=chat_model)
    if embedding_model is not None:
        _embed_client = AgentScopeLLMClient(embedding_model=embedding_model)
    if _chat_client is None or _embed_client is None:
        default_chat, default_embed = build_default_clients()
        if _chat_client is None:
            _chat_client = default_chat
        if _embed_client is None:
            _embed_client = default_embed

    # 2. 总开关
    if not settings.enabled:
        logger.info("记忆图谱模块已禁用（MEMORY_GRAPH_ENABLED=False）")
        _ready = False
        return False

    # 3. Neo4j schema
    try:
        from memory_graph.core.graph_schema import ensure_graph_schema

        await ensure_graph_schema()
    except Exception as e:
        logger.warning(
            "记忆图谱 Neo4j 初始化失败，模块降级并后台自愈重试（其余能力正常）: %s", e
        )
        _ready = False
        _start_retry_loop()
        return False

    # 4. 审计库表（幂等；SQLite/PG 双兼容）
    try:
        async with audit_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.warning("记忆图谱审计库建表失败，模块降级并后台自愈重试: %s", e)
        _ready = False
        _start_retry_loop()
        return False

    _ready = True
    # Redis 探测（反思计数后端；不可用则回退 SQLite，不阻断就绪）
    try:
        from memory_graph.db.redis import ping as ping_redis

        if await ping_redis():
            logger.info("记忆图谱 Redis 计数后端已连接: %s", settings.redis_url)
        else:
            logger.info("记忆图谱 Redis 不可达，反思计数回退 SQLite")
    except Exception:
        logger.info("记忆图谱 Redis 探测失败，反思计数回退 SQLite")
    logger.info(
        "记忆图谱模块就绪: neo4j=%s audit=%s dims=%d mode=%s celery=%s",
        settings.neo4j_uri, settings.audit_backend, settings.embedding_dims,
        settings.control_mode, settings.celery_enabled,
    )
    # 启动嵌入模型保活：冷加载 ~16s 会撞召回超时，故启动即后台预热 + 周期保活
    _start_keepalive()
    return _ready


async def ensure_initialized() -> bool:
    """幂等确保已初始化（Celery 任务入口用）。"""
    if not _init_done:
        return await init_memory_graph()
    return _ready


def _start_retry_loop() -> None:
    """初始化失败时启动后台自愈：周期性重试 schema + 建表，成功后置 _ready=True。

    覆盖两类场景：冷启动竞态（agent 先于 Neo4j 就绪）与运行期 Neo4j 重启。
    """
    global _retry_task
    if _retry_task is not None and not _retry_task.done():
        return

    async def _loop() -> None:
        global _ready
        while not _ready:
            await asyncio.sleep(_RETRY_INTERVAL)
            try:
                from memory_graph.core.graph_schema import ensure_graph_schema

                await ensure_graph_schema()
                async with audit_engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                _ready = True
                logger.info("记忆图谱自愈成功：模块已就绪")
            except Exception as e:
                logger.info("记忆图谱自愈重试未成功（%ss 后再试）: %s", _RETRY_INTERVAL, e)

    try:
        _retry_task = asyncio.create_task(_loop())
    except RuntimeError:
        logger.warning("无运行中的事件循环，跳过自愈重试（进程退出场景）")


async def _keepalive_loop() -> None:
    """嵌入模型保活：启动即预热一次（冷加载 ~16s 在后台进行，不阻塞就绪），
    之后每 ``embed_keepalive_interval`` 秒嵌一短串，重置 Ollama 空闲计时器，
    避免模型被卸载导致下次首召回冷加载撞 active_recall 超时。
    """
    _, embed_client = get_clients()
    if embed_client is None:
        return
    while True:
        try:
            await embed_client.embed_one("keepalive")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.info("[memory_graph] 嵌入模型保活失败（忽略，下轮重试）: %s", e)
        await asyncio.sleep(settings.embed_keepalive_interval)


def _start_keepalive() -> None:
    global _keepalive_task
    if _keepalive_task is not None and not _keepalive_task.done():
        return
    try:
        _keepalive_task = asyncio.create_task(_keepalive_loop())
        logger.info(
            "[memory_graph] 嵌入模型保活已启动（每 %.0fs 预热，防冷加载撞召回超时）",
            settings.embed_keepalive_interval,
        )
    except RuntimeError:
        logger.warning("无运行中的事件循环，跳过嵌入模型保活（进程退出场景）")


async def close_memory_graph() -> None:
    """关闭连接（应用退出时调用）。"""
    global _ready, _init_done, _chat_client, _embed_client, _retry_task, _keepalive_task
    _ready = False
    _init_done = False
    _chat_client = None
    _embed_client = None
    if _retry_task is not None and not _retry_task.done():
        _retry_task.cancel()
    _retry_task = None
    if _keepalive_task is not None and not _keepalive_task.done():
        _keepalive_task.cancel()
    _keepalive_task = None
    try:
        await close_neo4j()
    except Exception:
        pass
    try:
        await close_audit_db()
    except Exception:
        pass
    # Redis（反思计数后端，Celery broker）；惰性关闭，未创建过则 no-op
    try:
        from memory_graph.db.redis import close as close_redis

        await close_redis()
    except Exception:
        pass


# ── 反思增量计数 ──
# 优先 Redis（Comet 做法：INCRBY/SET/GET，进程外高吞吐计数器）；Redis 不可用时
# 回退审计库 SQLite 表（mg_counters），保证计数在任何部署形态下都不丢、不阻断萃取。

_REFLECT_KEY = "reflect:pending:{user_id}"


def _redis_client():
    """惰性获取 Redis 客户端；redis-py 未装或导入失败时返回 None（走 SQLite 回退）。"""
    try:
        from memory_graph.db.redis import get_redis

        return get_redis()
    except Exception:
        return None


async def _bump_counter_sqlite(key: str, n: int) -> int:
    async with SessionLocal() as session:
        row = await session.get(MemoryCounter, key)
        total = (row.value if row is not None else 0) + int(n)
        if row is not None:
            row.value = total
        else:
            session.add(MemoryCounter(key=key, value=total))
        await session.commit()
    return total


async def _reset_counter_sqlite(key: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(MemoryCounter, key)
        if row is not None:
            row.value = 0
            await session.commit()


async def _get_counter_sqlite(key: str) -> int:
    async with SessionLocal() as session:
        row = await session.get(MemoryCounter, key)
        return row.value if row is not None else 0


async def bump_reflection_counter(user_id: str, n: int) -> int:
    """累计某用户新增实体数，返回累计值。失败返回 -1（不阻断萃取）。

    优先 Redis ``INCRBY``；Redis 不可用回退审计库 SQLite 表。
    """
    key = _REFLECT_KEY.format(user_id=user_id)
    redis = _redis_client()
    if redis is not None:
        try:
            return int(await redis.incrby(key, int(n)))
        except Exception as e:
            logger.info("反思计数 Redis 不可用，回退 SQLite: %s", e)
    try:
        return await _bump_counter_sqlite(key, n)
    except Exception as e:
        logger.warning("反思计数失败（忽略）: %s", e)
        return -1


async def reset_reflection_counter(user_id: str) -> None:
    key = _REFLECT_KEY.format(user_id=user_id)
    redis = _redis_client()
    if redis is not None:
        try:
            await redis.set(key, 0)
            return
        except Exception as e:
            logger.info("反思计数 Redis 重置失败，回退 SQLite: %s", e)
    try:
        await _reset_counter_sqlite(key)
    except Exception as e:
        logger.warning("反思计数重置失败（忽略）: %s", e)


async def get_reflection_counter(user_id: str) -> int:
    key = _REFLECT_KEY.format(user_id=user_id)
    redis = _redis_client()
    if redis is not None:
        try:
            v = await redis.get(key)
            return int(v) if v else 0
        except Exception as e:
            logger.info("反思计数 Redis 读取失败，回退 SQLite: %s", e)
    try:
        return await _get_counter_sqlite(key)
    except Exception:
        return 0


def dispatch_reflection(user_id: str) -> None:
    """派发单用户反思：Celery 可用走队列，否则进程内 fire-and-forget。"""
    if settings.celery_enabled:
        try:
            from memory_graph.tasks.beat import reflect_user_task

            reflect_user_task.delay(user_id)
            return
        except Exception as e:
            logger.info("反思 Celery 派发失败，进程内兜底: %s", e)
    try:
        asyncio.create_task(_run_reflection_in_process(user_id))
    except Exception as e:
        logger.warning("派发进程内反思失败: %s", e)


async def _run_reflection_in_process(user_id: str) -> None:
    """进程内执行单用户反思（Celery 不可用时的兜底）。"""
    await ensure_initialized()
    chat_client, embed_client = get_clients()
    if chat_client is None:
        logger.warning("进程内反思跳过：客户端未就绪")
        return
    from memory_graph.core.reflection.reflector import ReflectionEngine

    try:
        engine = ReflectionEngine(chat_client=chat_client, embed_client=embed_client)
        stats = await engine.run(user_id)
        logger.info("进程内反思完成: user=%s %s", user_id, stats)
    except Exception as e:
        logger.warning("进程内反思失败（忽略）: user=%s err=%s", user_id, e)


async def dispatch_extraction(
    user_id: str,
    text: str,
    source: str = "auto",
    source_message_id: str | None = None,
) -> str | None:
    """派发一次萃取：建 memories 审计行 -> Celery / 进程内后台执行。

    由 ``MemoryGraphMiddleware.on_reply`` 在回复结束后调用（写回）。返回 memory id
    （用于溯源），失败返回 None。绝不阻塞回复。
    """
    if not _ready or not (text or "").strip():
        return None
    user_id = str(user_id)

    memory_id: str | None = None
    try:
        async with SessionLocal() as session:
            repo = MemoryRepository(session)
            mem = await repo.create(
                Memory(
                    user_id=user_id,
                    raw_text=text,
                    source=source,
                    source_message_id=source_message_id,
                    status=MEMORY_STATUS_PENDING,
                )
            )
            memory_id = mem.id
    except Exception as e:
        logger.warning("记忆审计行写入失败（仍尝试进程内萃取）: %s", e)

    # 优先 Celery（显式启用时）
    if memory_id and settings.celery_enabled:
        try:
            from memory_graph.tasks.memory import extract_memory_task

            extract_memory_task.delay(memory_id)
            return memory_id
        except Exception as e:
            logger.info("Celery 不可用，回退进程内萃取: %s", e)

    # 回退：进程内 fire-and-forget
    try:
        asyncio.create_task(
            _extract_in_process(memory_id, user_id, text, source, source_message_id)
        )
    except Exception as e:
        logger.warning("派发进程内萃取失败: %s", e)
    return memory_id


async def _extract_in_process(
    memory_id: str | None,
    user_id: str,
    text: str,
    source: str,
    source_message_id: str | None,
) -> None:
    """进程内执行萃取（Celery 不可用时的兜底）。"""
    await ensure_initialized()
    chat_client, embed_client = get_clients()
    if chat_client is None or embed_client is None:
        logger.warning("进程内萃取跳过：客户端未就绪")
        return
    from memory_graph.core.extraction.orchestrator import run_extraction

    if memory_id:
        await _update_memory(memory_id, status=MEMORY_STATUS_EXTRACTING)
    try:
        stats = await run_extraction(
            chat_client=chat_client,
            embed_client=embed_client,
            user_id=user_id,
            text=text,
            source=source,
            source_message_id=source_message_id,
        )
        if memory_id:
            await _update_memory(
                memory_id,
                status=MEMORY_STATUS_DONE,
                graph_dialogue_id=stats.dialogue_id or None,
                graph_stats=stats.to_dict(),
                error_msg=None,
            )
        logger.info("进程内萃取完成: memory=%s %s", memory_id, stats.to_dict())
    except Exception as e:
        logger.error("进程内萃取失败: %s: %s", memory_id, e, exc_info=True)
        if memory_id:
            await _update_memory(
                memory_id, status=MEMORY_STATUS_FAILED, error_msg=str(e)[:500]
            )


async def _update_memory(memory_id: str, **fields) -> None:
    """更新 memories 行的指定字段。"""
    try:
        async with SessionLocal() as session:
            repo = MemoryRepository(session)
            mem = await repo.get_by_id(memory_id)
            if mem is None:
                return
            for k, v in fields.items():
                setattr(mem, k, v)
            await repo.save(mem)
    except Exception as e:
        logger.warning("更新 memory 行失败 %s: %s", memory_id, e)
