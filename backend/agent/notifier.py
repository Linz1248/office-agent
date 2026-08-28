"""应用内实时事件总线（进程内 pub/sub，单 worker uvicorn 下安全）。

设计要点：
  - 按 user_id 维护订阅者集合，每条事件带 ``type`` 字段，前端在单条 SSE 连接上
    按 type 分发；新功能推送只需 ``publish(user_id, "feature_x", {...})`` 一行，
    无需新建 SSE 端点、无需新连接。
  - ``publish`` 用 ``put_nowait``（同步、不 await），可在任意同步/异步上下文调用；
    队列满即丢，由各业务既有 REST 拉取兜底补齐（持久 outbox 模式）。
  - 无订阅者时是空操作，零开销。
  - 多 worker / 多副本部署时把 publish/subscribe 换成 Redis pub/sub 即可，
    调用方（``notifier.publish``）签名不变。
"""
import asyncio
import json

# user_id -> 该用户所有在线 SSE 订阅者的队列集合
_subscribers: dict[str, set[asyncio.Queue]] = {}

# 单订阅者队列上限：超出即丢实时帧（DB/REST 仍是数据真相源，丢的只是实时提醒）
_QUEUE_MAX = 64


def subscribe(user_id: str) -> asyncio.Queue:
    """订阅当前用户的事件流，返回该连接专属的队列；连接关闭时需 unsubscribe。"""
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.setdefault(user_id, set()).add(q)
    return q


def unsubscribe(user_id: str, q: asyncio.Queue) -> None:
    """移除订阅；幂等（重复调用或未知队列均安全）。"""
    _subscribers.get(user_id, set()).discard(q)
    if not _subscribers.get(user_id):
        _subscribers.pop(user_id, None)


def publish(user_id: str, event_type: str, payload: dict | None = None) -> None:
    """向该用户所有在线 SSE 订阅者推一条 ``{type, **payload}``；队列满则丢。"""
    msg = {"type": event_type, **(payload or {})}
    for q in list(_subscribers.get(user_id, ())):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            # 慢消费者丢这条实时帧，由各业务自带的 REST 拉取兜底补齐
            pass


def sse_frame(data: dict) -> str:
    """格式化 SSE data: 帧。与 main._sse 同形，独立模块不跨文件引私有函数。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


__all__ = ["subscribe", "unsubscribe", "publish", "sse_frame"]
