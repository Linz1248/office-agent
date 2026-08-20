"""记忆图谱可拔插模块：将 Comet 的图式长期记忆系统移植为 office-agent 的 AgentScope 中间件。

对外门面（与 office-agent 现有 ``kb`` 模块的接入面保持一致）：
  - ``init_memory_graph(chat_model, embedding_model)``  在 lifespan 中初始化
  - ``close_memory_graph()``                             关闭连接
  - ``is_ready()``                                       是否就绪（未就绪则旁路）
  - ``set_memory_context(user_id)``                      按请求解析当前用户（ContextVar）
  - ``MemoryGraphMiddleware``                            注入 Agent 的中间件
  - ``router``                                           FastAPI 路由（/memories/*）
  - ``dispatch_extraction(user_id, text, source, ...)``  派发萃取（Celery / asyncio 回退）
"""
from __future__ import annotations

from .config import settings
from .logger import get_logger

__all__ = [
    "settings",
    "get_logger",
    "init_memory_graph",
    "close_memory_graph",
    "is_ready",
    "set_memory_context",
    "current_user_id",
    "MemoryGraphMiddleware",
    "router",
    "dispatch_extraction",
    "set_auth_dependency",
]

# 延迟导入的符号，避免在 import 阶段就拉起 neo4j/sqlalchemy 等重依赖（允许模块在
# 依赖缺失时仍可被 import，仅 is_ready() 返回 False）。
def __getattr__(name):  # PEP 562
    if name == "init_memory_graph":
        from .runtime import init_memory_graph
        return init_memory_graph
    if name == "close_memory_graph":
        from .runtime import close_memory_graph
        return close_memory_graph
    if name == "is_ready":
        from .runtime import is_ready
        return is_ready
    if name == "set_memory_context":
        from .runtime import set_memory_context
        return set_memory_context
    if name == "current_user_id":
        from .runtime import current_user_id
        return current_user_id
    if name == "MemoryGraphMiddleware":
        from .middleware import MemoryGraphMiddleware
        return MemoryGraphMiddleware
    if name == "router":
        from .api.memory_controller import router
        return router
    if name == "dispatch_extraction":
        from .runtime import dispatch_extraction
        return dispatch_extraction
    if name == "set_auth_dependency":
        from .api.memory_controller import set_auth_dependency
        return set_auth_dependency
    raise AttributeError(f"module 'memory_graph' has no attribute {name!r}")
