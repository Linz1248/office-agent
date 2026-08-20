"""反思增量计数表（替代 Comet 的 Redis 计数器，无 Redis 也能触发反思）。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from memory_graph.db.audit_db import Base


class MemoryCounter(Base):
    """简单 KV 计数器：目前仅用于 reflect:pending:{user_id} 累计新增实体数。"""

    __tablename__ = "mg_counters"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
