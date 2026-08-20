"""LLM JSON 输出的健壮解析。"""
import json
from typing import Any

import json_repair

from memory_graph.logger import get_logger

logger = get_logger(__name__)


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    return t.strip()


def parse_json_object(answer: str) -> dict[str, Any]:
    if not answer or not answer.strip():
        return {}
    text = _strip_fence(answer)
    start = text.find("{")
    end = text.rfind("}")
    snippet = text[start : end + 1] if (start != -1 and end > start) else text

    try:
        data = json.loads(snippet, strict=False)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    try:
        repaired = json_repair.repair_json(snippet, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
    except Exception as e:  # noqa: BLE001
        logger.warning("json_repair 修复失败: %s", e)

    return {}


def parse_json_list(answer: str) -> list[Any]:
    if not answer or not answer.strip():
        return []
    text = _strip_fence(answer)
    start = text.find("[")
    end = text.rfind("]")
    snippet = text[start : end + 1] if (start != -1 and end > start) else text

    try:
        data = json.loads(snippet, strict=False)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    try:
        repaired = json_repair.repair_json(snippet, return_objects=True)
        if isinstance(repaired, list):
            return repaired
    except Exception as e:  # noqa: BLE001
        logger.warning("json_repair 修复失败: %s", e)

    return []


__all__ = ["parse_json_object", "parse_json_list"]
