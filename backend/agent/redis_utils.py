"""通用 Redis 工具模块（缓存 / 分布式锁 / 限流），供 agent 全服务复用。

broker 让位 RabbitMQ 后，Redis 退回"易失、高频、可重建"层，各司其职：
  - db0：memory_graph 反思计数（``memory_graph/db/redis.py``，已存在）
  - db2：Celery result backend
  - db3：本模块的缓存层（飞书 token / 嵌入 / 抽取幂等等易失数据）

连接地址默认 ``redis://localhost:6379/3``，可用 ``REDIS_CACHE_URL`` 覆盖。

设计原则：**优雅降级**。Redis 不可用时所有操作返回降级值且不抛异常——
缓存 miss、锁直接放行、限流默认放行——保证业务不因 Redis 故障阻断。
参考 ``memory_graph/runtime.py`` 的"优先 Redis 回退"模式。
"""
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from redis import asyncio as aioredis

logger = logging.getLogger(__name__)

_CACHE_URL = os.getenv("REDIS_CACHE_URL", "redis://localhost:6379/3")

_pool: aioredis.ConnectionPool | None = None
_client: aioredis.Redis | None = None

# 释放锁的 Lua 脚本：仅当 key 的值等于 ident 才删除，防锁超时后被他人误删。
_UNLOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


def get_cache_client() -> aioredis.Redis | None:
    """惰性获取 db3 缓存客户端；redis-py 未装或初始化失败时返回 None（降级）。"""
    global _pool, _client
    if _client is None:
        try:
            _pool = aioredis.ConnectionPool.from_url(
                _CACHE_URL,
                decode_responses=True,
                max_connections=20,
                health_check_interval=30,
            )
            _client = aioredis.Redis(connection_pool=_pool)
        except Exception as e:  # 导入失败/地址非法等
            logger.info("redis_utils 缓存客户端初始化失败（降级）：%s", e)
            _client = None
    return _client


async def close() -> None:
    """关闭连接池（进程退出时调用）。未连过则为 no-op。"""
    global _pool, _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
    if _pool is not None:
        try:
            await _pool.disconnect()
        except Exception:
            pass
        _pool = None


# ── 缓存（JSON + TTL）──
async def cache_get_json(key: str) -> Any | None:
    """读取并反序列化；Redis 不可用或未命中返回 None。"""
    client = get_cache_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.info("缓存读取失败（降级 miss）key=%s: %s", key, e)
        return None


async def cache_set_json(key: str, value: Any, ttl: int) -> bool:
    """序列化并写入（带 TTL 秒）；Redis 不可用返回 False。"""
    client = get_cache_client()
    if client is None:
        return False
    try:
        await client.set(key, json.dumps(value, ensure_ascii=False), ex=int(ttl))
        return True
    except Exception as e:
        logger.info("缓存写入失败（降级跳过）key=%s: %s", key, e)
        return False


# ── 分布式锁（SET NX EX + Lua 校验解锁）──
@asynccontextmanager
async def distributed_lock(key: str, ttl: int = 60, ident: str | None = None):
    """获取分布式锁；Redis 不可用或锁被占时降级为直接放行（不阻断业务）。

    用法::

        async with distributed_lock("kb:set_shared:user:doc", ttl=60):
            ...

    降级语义：锁本质是并发优化，Redis 故障时不该让业务停摆——退回"乐观并发"
    （等同改造前行为），仅记日志。ttl 须大于临界区预期耗时，否则锁超时自动释放
    后他人可进入；Lua 解锁防超时后误删他人持有的锁。
    """
    lock_ident = ident or uuid.uuid4().hex
    client = get_cache_client()
    acquired = False
    if client is not None:
        try:
            acquired = bool(await client.set(key, lock_ident, nx=True, ex=int(ttl)))
            if not acquired:
                logger.info("分布式锁被占，降级放行 key=%s", key)
        except Exception as e:
            logger.info("分布式锁获取异常，降级放行 key=%s: %s", key, e)
    # client is None 或未取到 → acquired=False → 直接进入临界区（降级）
    try:
        yield
    finally:
        if acquired and client is not None:
            try:
                await client.eval(_UNLOCK_SCRIPT, 1, key, lock_ident)
            except Exception as e:
                logger.info("分布式锁释放异常 key=%s: %s", key, e)


# ── 限流（滑动窗口，预留能力，本方案不在业务强制启用）──
async def rate_limit(key: str, max_count: int, window_s: int) -> bool:
    """滑动窗口限流：返回 True=放行，False=超限；Redis 不可用默认放行。

    用 ZSET 记录窗口内请求时间戳，先清过期成员再加当前成员，count 超限即拒。
    """
    client = get_cache_client()
    if client is None:
        return True
    try:
        now = await client.time()
        now_ms = int(now[0]) * 1000 + int(now[1]) // 1000
        member = f"{now_ms}:{uuid.uuid4().hex}"
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, now_ms - window_s * 1000)
        pipe.zadd(key, {member: now_ms})
        pipe.zcard(key)
        pipe.expire(key, window_s)
        results = await pipe.execute()
        count = results[2] if len(results) > 2 else 0
        return count <= max_count
    except Exception as e:
        logger.info("限流异常，降级放行 key=%s: %s", key, e)
        return True
