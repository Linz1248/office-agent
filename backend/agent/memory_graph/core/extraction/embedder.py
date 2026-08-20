"""实体/陈述向量化：批量给文本生成 name_embedding，供去重初筛与检索召回。"""
from memory_graph.logger import get_logger

logger = get_logger(__name__)


async def embed_texts(client, texts: list[str]) -> list[list[float] | None]:
    """批量向量化。失败返回与输入等长的 None 列表（不阻断写图）。"""
    if not texts:
        return []
    try:
        return await client.embed(texts)  # type: ignore[return-value]
    except Exception as e:
        logger.warning("实体向量化失败（降级为无向量）: %s", e)
        return [None] * len(texts)


__all__ = ["embed_texts"]
