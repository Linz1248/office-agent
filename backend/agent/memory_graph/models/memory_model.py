"""Memory ORM —— PostgreSQL memories 表（记忆原文与溯源）。

与 Comet 的差异：office-agent 用户体系在 document_extract 的 SQLite 中，不在本库，
故 ``user_id`` 为 String（用户名）且不外键；``source_message_id`` 亦为 String 以兼容
office-agent 的数值消息 id。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from memory_graph.db.audit_db import Base, JSONField

# 记忆来源
MEMORY_SOURCE_AUTO = "auto"  # 对话自动萃取
MEMORY_SOURCE_MANUAL = "manual"  # 主动记住

# 萃取状态
MEMORY_STATUS_PENDING = "pending"
MEMORY_STATUS_EXTRACTING = "extracting"
MEMORY_STATUS_DONE = "done"
MEMORY_STATUS_FAILED = "failed"


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default=MEMORY_SOURCE_MANUAL)
    source_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=MEMORY_STATUS_PENDING, index=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    graph_dialogue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    graph_stats: Mapped[dict | None] = mapped_column(JSONField, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
