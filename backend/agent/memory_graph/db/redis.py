"""Redis 异步客户端（反思计数后端 + 可选 Celery broker）。

反思增量计数优先走本客户端（``INCRBY``，Comet 做法），不可用时回退审计库 SQLite；
``MEMORY_GRAPH_CELERY_ENABLED=true`` 时还作为 Celery broker/backend。
连接池惰性创建，未连过则 ``close()`` 为 no-op。
"""
from redis import asyncio as aioredis

from memory_graph.config import settings

_pool: aioredis.ConnectionPool | None = None
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _pool, _client
    if _client is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            health_check_interval=30,
        )
        _client = aioredis.Redis(connection_pool=_pool)
    return _client


async def ping() -> bool:
    try:
        return await get_redis().ping()
    except Exception:
        return False


async def close() -> None:
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
