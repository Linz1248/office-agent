"""原子陈述抽取：把一段文本切成带类型/时间属性的原子陈述句。"""
from memory_graph.core.extraction.models import (
    ExtractedStatement,
    StatementExtractionResult,
)
from memory_graph.core.json_utils import parse_json_object
from memory_graph.core.prompt_renderer import render_prompt
from memory_graph.logger import get_logger

logger = get_logger(__name__)


async def extract_statements(client, content: str, context: str | None = None) -> list[ExtractedStatement]:
    """从一段文本抽取原子陈述句。``client`` 为 ``llm_bridge.AgentScopeLLMClient``。"""
    prompt = render_prompt("extract_statement.jinja2", content=content, context=context)
    try:
        answer = await client.chat(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=2048
        )
        data = parse_json_object(answer)
        result = StatementExtractionResult.model_validate(data)
        return [s for s in result.statements if s.statement and s.statement.strip()]
    except Exception as e:
        logger.warning("陈述抽取失败（忽略该块）: %r", e)
        return []


__all__ = ["extract_statements"]
