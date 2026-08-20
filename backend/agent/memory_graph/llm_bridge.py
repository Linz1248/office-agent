"""AgentScope 模型适配器：把 office-agent 的 AgentScope chat / embedding 模型
适配成 Comet 萃取流水线所用的 ``LLMClient`` 接口（``chat`` / ``embed`` / ``embed_one``）。

这是与 AgentScope SDK 的官方集成方式（与 ReMe / Mem0 中间件“注入 AgentScope 模型”
一致）：复用 office-agent 已有 ``llm_config`` 配置的 chat 模型与 KB 用的 Ollama
embedding 模型，无需另配 provider key，避免冗余。
"""
from __future__ import annotations

import asyncio

from memory_graph.config import settings
from memory_graph.logger import get_logger

logger = get_logger(__name__)


def _block_text(block) -> str:
    """从 ChatResponse.content 的某个 block 取文本。"""
    text = getattr(block, "text", None)
    if isinstance(text, str):
        return text
    # 个别 block 可能用 content 字段
    content = getattr(block, "content", None)
    return str(content) if content else ""


class AgentScopeLLMClient:
    """把 AgentScope chat / embedding 模型包成 Comet 萃取流水线的 client 接口。"""

    def __init__(self, chat_model=None, embedding_model=None):
        self._chat_model = chat_model
        self._embedding_model = embedding_model

    async def chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 2048
    ) -> str:
        """非流式对话，返回完整文本。temperature/max_tokens 由构造模型决定（忽略）。"""
        if self._chat_model is None:
            raise RuntimeError("AgentScopeLLMClient 未注入 chat 模型")
        from agentscope.message import Msg, TextBlock

        msgs = []
        for m in messages or []:
            role = str(m.get("role") or "user")
            content = m.get("content") or ""
            # AgentScope 2.0 的 Msg.content 必须是内容块列表，不能直接传 str
            msgs.append(
                Msg(name=role, role=role, content=[TextBlock(text=content)])
            )
        # 非流式：await 单个 ChatResponse
        response = await self._chat_model(msgs)
        blocks = getattr(response, "content", None) or []
        return "".join(_block_text(b) for b in blocks)

    async def embed(self, texts: list[str], dimensions: int | None = None) -> list[list[float]]:
        """批量向量化。返回与输入等长的向量列表。dimensions 由构造模型决定（忽略）。"""
        if self._embedding_model is None:
            raise RuntimeError("AgentScopeLLMClient 未注入 embedding 模型")
        if not texts:
            return []
        response = await self._embedding_model(list(texts))
        embeddings = getattr(response, "embeddings", None)
        if embeddings is None:
            return []
        return [list(v) for v in embeddings]

    async def embed_one(self, text: str, dimensions: int | None = None) -> list[float]:
        vecs = await self.embed([text], dimensions=dimensions)
        return vecs[0]


def _build_default_embedding_model():
    """从 memory_graph 配置构建默认 embedding 模型（Ollama）。"""
    from agentscope.credential import OllamaCredential
    from agentscope.embedding import OllamaEmbeddingModel

    return OllamaEmbeddingModel(
        credential=OllamaCredential(host=settings.embedding_ollama_host),
        model=settings.embedding_model,
        dimensions=settings.embedding_dims,
    )


def _build_default_chat_model():
    """复用 office-agent 的 llm_config 构建非流式 sidecar chat 模型。

    优先使用 office-agent 专门的低温度萃取模型 ``get_memory_graph_chat_model``（见
    llm_config.py 接入补丁），缺失则回退 ``get_memory_model``。
    """
    try:
        from llm_config import get_memory_model  # office-agent 模块

        try:
            from llm_config import get_memory_graph_chat_model  # noqa: F401

            return get_memory_graph_chat_model()
        except ImportError:
            return get_memory_model()
    except Exception as e:  # pragma: no cover - 启动期诊断
        logger.warning("构建默认 chat 模型失败: %s", e)
        return None


def build_default_clients() -> tuple[AgentScopeLLMClient, AgentScopeLLMClient]:
    """构造默认 (chat_client, embed_client)。任一失败返回 None 占位。"""
    chat_model = None
    embed_model = None
    try:
        chat_model = _build_default_chat_model()
    except Exception as e:
        logger.warning("默认 chat 模型构建失败: %s", e)
    try:
        embed_model = _build_default_embedding_model()
    except Exception as e:
        logger.warning("默认 embedding 模型构建失败: %s", e)
    chat_client = AgentScopeLLMClient(chat_model=chat_model)
    embed_client = AgentScopeLLMClient(embedding_model=embed_model)
    return chat_client, embed_client


__all__ = ["AgentScopeLLMClient", "build_default_clients"]
