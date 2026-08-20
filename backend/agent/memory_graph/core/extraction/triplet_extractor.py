"""三元组萃取：从单条陈述抽取实体与 (主语, 谓词, 宾语) 三元组。"""
import asyncio

from memory_graph.core.extraction.models import (
    ExtractedStatement,
    TripletExtractionResult,
)
from memory_graph.core.json_utils import parse_json_object
from memory_graph.core.ontology import ENTITY_TYPES, PREDICATES
from memory_graph.core.prompt_renderer import render_prompt
from memory_graph.logger import get_logger

logger = get_logger(__name__)


def _norm_time(value: str | None) -> str:
    if not value or str(value).strip().upper() in {"NULL", "NONE", ""}:
        return "NULL"
    return str(value)


async def extract_triplets(
    client,
    statement: ExtractedStatement,
    context: str | None = None,
    dialog_at: str | None = None,
) -> TripletExtractionResult:
    if statement.has_unsolved_reference:
        return TripletExtractionResult()
    prompt = render_prompt(
        "extract_triplet.jinja2",
        statement=statement.statement,
        context=context,
        entity_types=ENTITY_TYPES,
        predicates=PREDICATES,
        valid_at="NULL",
        invalid_at="NULL",
        dialog_at=_norm_time(dialog_at),
    )
    try:
        answer = await client.chat(
            [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=2048
        )
        data = parse_json_object(answer)
        return TripletExtractionResult.model_validate(data)
    except Exception as e:
        logger.warning("三元组萃取失败（忽略该句）: %r", e)
        return TripletExtractionResult()


async def extract_triplets_batch(
    client,
    statements: list[ExtractedStatement],
    context: str | None = None,
    dialog_at: str | None = None,
    concurrency: int = 4,
) -> list[TripletExtractionResult]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(stmt: ExtractedStatement) -> TripletExtractionResult:
        async with sem:
            return await extract_triplets(client, stmt, context, dialog_at)

    return await asyncio.gather(*[_one(s) for s in statements])


__all__ = ["extract_triplets", "extract_triplets_batch"]
