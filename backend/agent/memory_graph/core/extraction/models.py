"""萃取流水线的中间数据模型（LLM 结构化输出 + 流水线传递）。"""
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_float(v: object, default: float | None) -> float | None:
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default
    return default


class ExtractedStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statement: str
    statement_type: str = "FACT"
    temporal_type: str = "STATIC"
    has_unsolved_reference: bool = False
    importance: float = 0.5
    confidence: float = 0.8
    has_emotional_state: bool = False
    emotion_type: str | None = None
    emotion_intensity: float | None = None
    emotion_keywords: list[str] = Field(default_factory=list)

    @field_validator("importance", mode="before")
    @classmethod
    def _v_importance(cls, v):
        return _to_float(v, 0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.8)

    @field_validator("emotion_intensity", mode="before")
    @classmethod
    def _v_emotion_intensity(cls, v):
        return _to_float(v, None)


class StatementExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statements: list[ExtractedStatement] = Field(default_factory=list)


class ExtractedEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    description: str = ""
    event_time: str | None = None
    participants: list[str] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entity_idx: int = -1
    name: str
    type: str = "其他"
    description: str = ""
    importance: float = 0.5
    confidence: float = 0.8

    @field_validator("importance", mode="before")
    @classmethod
    def _v_importance(cls, v):
        return _to_float(v, 0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.8)


class ExtractedTriplet(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject_name: str
    subject_id: int = -1
    predicate: str = "关联于"
    predicate_surface: str = ""
    object_name: str
    object_id: int = -1
    value: str | None = None
    valid_at: str | None = None
    invalid_at: str | None = None
    importance: float = 0.5
    confidence: float = 0.8

    @field_validator("importance", mode="before")
    @classmethod
    def _v_importance(cls, v):
        return _to_float(v, 0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.8)


class TripletExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entities: list[ExtractedEntity] = Field(default_factory=list)
    triplets: list[ExtractedTriplet] = Field(default_factory=list)
    events: list[ExtractedEvent] = Field(default_factory=list)

    @field_validator("entities", "triplets", "events", mode="before")
    @classmethod
    def _drop_malformed(cls, v, info):
        if not isinstance(v, list):
            return []
        field = info.field_name
        out = []
        for it in v:
            if not isinstance(it, dict):
                continue
            if field == "entities":
                if not str(it.get("name") or "").strip():
                    continue
            elif field == "triplets":
                if not (str(it.get("subject_name") or "").strip()
                        and str(it.get("object_name") or "").strip()):
                    continue
            elif field == "events":
                if not str(it.get("title") or "").strip():
                    continue
            out.append(it)
        return out


class DedupDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    same_entity: bool = False
    canonical_idx: int = 0
    confidence: float = 0.0
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.0)


__all__ = [
    "ExtractedStatement",
    "StatementExtractionResult",
    "ExtractedEvent",
    "ExtractedEntity",
    "ExtractedTriplet",
    "TripletExtractionResult",
    "DedupDecision",
]
