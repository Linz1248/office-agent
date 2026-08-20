"""记忆图谱 AgentScope 中间件 + memory_search 工具。

遵循 AgentScope 2.0 长期记忆中间件规范（与官方 ReMe / Mem0 一致）：
  - ``on_reasoning``：首个推理步前做主动召回（向量+全文+1跳邻居+洞察），以
    ``HintBlock`` 注入上下文（``static_control`` / ``both`` 模式）。
  - ``on_reply``：回复结束后派发萃取（写回，``source=auto``）。
  - ``on_system_prompt``：``agent_control`` / ``both`` 模式下追加 memory_search 使用提示。
  - ``list_tools``：返回 ``MemorySearch`` 工具（``agent_control`` / ``both``）。

多租户：通过 ``runtime.set_memory_context(user_id)`` 由 /chat 设置，本中间件按请求解析。
"""
from __future__ import annotations

from typing import Any

from agentscope.middleware import MiddlewareBase
from agentscope.message import HintBlock, TextBlock, ToolResultState
from agentscope.tool import ToolBase, ToolChunk

from memory_graph.config import settings
from memory_graph.logger import get_logger
from memory_graph.runtime import current_user_id, dispatch_extraction, get_clients, is_ready

logger = get_logger(__name__)


def _msg_text(msg) -> str:
    """从 Msg.content（block 列表或字符串）取文本。"""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for b in content:
            text = getattr(b, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _latest_user_query(agent) -> str:
    """从 agent.state.context 取最近一条用户消息文本作为召回 query。"""
    context = getattr(getattr(agent, "state", None), "context", None) or []
    for msg in reversed(context):
        role = getattr(msg, "role", "") or getattr(msg, "name", "")
        if role == "user" and _msg_text(msg).strip():
            return _msg_text(msg).strip()
    return ""


class MemorySearch(ToolBase):
    """在记忆图谱中检索与当前问题相关的用户记忆事实。

    Agent 自主决定是否调用：用户问题涉及历史偏好/身份/关系/事件时检索；普通通用
    问答无需调用。当前用户由 contextvar 解析（/chat 注入），故本工具可全局共享注册。
    """

    name = "memory_search"
    description = (
        "在用户的长期记忆图谱中检索与问题相关的记忆事实（用户偏好、身份、关系、"
        "事件、历史决策等）。当用户的问题涉及过去的对话、个人偏好、身份背景、"
        "项目历史等需要回忆的内容时调用此工具。检索结果作为上下文参考，据此作答。"
        "不涉及历史记忆的通用问题无需调用。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索用的自然语言问题或关键词。",
            },
            "top_k": {
                "type": "integer",
                "description": "返回的最相关记忆数量，默认 10。",
                "default": 10,
            },
        },
        "required": ["query"],
    }
    is_external_tool = False
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(self, tool_input: dict, context):
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="memory_search 仅做只读检索，无副作用。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        user_id = current_user_id()
        if not user_id or not is_ready():
            return ToolChunk(
                content=[TextBlock(text="长期记忆未就绪或当前用户未知，无法检索。")],
                state=ToolResultState.SUCCESS, is_last=True,
            )
        query = (kwargs.get("query") or "").strip()
        if not query:
            return ToolChunk(
                content=[TextBlock(text="检索词为空。")],
                state=ToolResultState.SUCCESS, is_last=True,
            )
        top_k = int(kwargs.get("top_k") or 10)
        try:
            from memory_graph.core.retrieval.searcher import (
                format_memory_context,
                search_memory,
            )

            _, embed_client = get_clients()
            if embed_client is None:
                return ToolChunk(
                    content=[TextBlock(text="记忆检索未就绪（嵌入模型未配置）。")],
                    state=ToolResultState.SUCCESS, is_last=True,
                )
            hits = await search_memory(
                embed_client=embed_client, user_id=user_id,
                query=query, top_k=top_k,
            )
            text = format_memory_context(hits)
        except Exception as e:
            logger.warning("memory_search 检索失败: %s", e)
            return ToolChunk(
                content=[TextBlock(text=f"检索失败：{e}")],
                state=ToolResultState.ERROR, is_last=True,
            )
        return ToolChunk(
            content=[TextBlock(text=text or "未检索到相关记忆。")],
            state=ToolResultState.SUCCESS, is_last=True,
        )


class MemoryGraphMiddleware(MiddlewareBase):
    """记忆图谱长期记忆中间件。"""

    def __init__(self, mode: str | None = None, top_k: int | None = None) -> None:
        self.mode = mode or settings.control_mode
        self.top_k = top_k or settings.active_recall_entity_top_k
        self._static = self.mode in ("static_control", "both")
        self._agent = self.mode in ("agent_control", "both")

    async def on_reasoning(self, agent, input_kwargs, next_handler):
        """首个推理步前注入主动召回的记忆背景（static 模式）。"""
        hint = None
        user_id = current_user_id()
        if (
            self._static
            and getattr(agent.state, "cur_iter", 0) == 0
            and is_ready()
            and user_id
        ):
            query = _latest_user_query(agent)
            if query:
                try:
                    from memory_graph.core.retrieval.active_recall import recall_context

                    _, embed_client = get_clients()
                    if embed_client is not None:
                        text = await recall_context(
                            embed_client=embed_client, user_id=user_id, query=query
                        )
                        if text:
                            hint = HintBlock(hint=text, source="memory")
                            agent.state.append_context(agent.name, [hint])
                except Exception as e:
                    logger.warning("主动召回失败（忽略）: %s", e)

        try:
            async for evt in next_handler(**input_kwargs):
                yield evt
        finally:
            if hint is not None:
                for msg in reversed(getattr(agent.state, "context", []) or []):
                    if getattr(msg, "id", None) != agent.state.reply_id:
                        continue
                    msg.content = [b for b in (msg.content or []) if getattr(b, "id", None) != hint.id]
                    break

    async def on_reply(self, agent, input_kwargs, next_handler):
        """回复结束后派发萃取（写回 source=auto）。"""
        async for item in next_handler(**input_kwargs):
            yield item
        # 写回：取本轮用户输入文本
        try:
            user_id = current_user_id()
            inputs = input_kwargs.get("inputs")
            text = ""
            if isinstance(inputs, list):
                for m in reversed(inputs):
                    if (getattr(m, "role", "") or getattr(m, "name", "")) == "user":
                        text = _msg_text(m)
                        break
            elif inputs is not None:
                text = _msg_text(inputs)
            if user_id and (text or "").strip() and is_ready():
                await dispatch_extraction(user_id, text.strip(), source="auto")
        except Exception as e:
            logger.warning("记忆写回失败（忽略）: %s", e)

    async def on_system_prompt(self, agent, current_prompt: str) -> str:
        if self._agent:
            return (
                current_prompt
                + "\n\n## 长期记忆工具\n你拥有 memory_search 工具，可在用户的长期记忆图谱中"
                "检索历史偏好、身份、关系与事件。当用户问题涉及过去的对话或个人背景时调用它"
                "获取相关记忆作为参考；通用问题无需调用。"
                "检索结果仅供你参考作答，禁止在回复中提及记忆、检索结果或其来源。"
            )
        return current_prompt

    async def list_tools(self) -> list[ToolBase]:
        if self._agent:
            return [MemorySearch()]
        return []


__all__ = ["MemoryGraphMiddleware", "MemorySearch"]
