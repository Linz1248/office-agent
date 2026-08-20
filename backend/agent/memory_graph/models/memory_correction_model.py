"""MemoryCorrection ORM —— PostgreSQL memory_corrections 表（人工纠错审计/可回滚）。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from memory_graph.db.audit_db import Base, JSONField

ACTION_CONFIRM = "confirm"
ACTION_CORRECT = "correct"
ACTION_DELETE = "delete"


class MemoryCorrection(Base):
    __tablename__ = "memory_corrections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)
    before: Mapped[dict] = mapped_column(JSONField, default=dict)
    after: Mapped[dict | None] = mapped_column(JSONField, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_dialogue_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
