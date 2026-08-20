"""审计库连接（SQLAlchemy 2.0 async）：默认 SQLite，可选 PostgreSQL。

承载记忆来源原文 / 萃取审计 / 人工纠错 / 反思计数等小表，与 office-agent
全栈 SQLite 的惯例一致，零额外服务（无 Docker 部署的默认形态）。
需要 PostgreSQL 时设 ``MEMORY_GRAPH_AUDIT_BACKEND=postgres``（连接池参数与
Comet 原版一致）；JSON 字段用 ``JSON().with_variant(JSONB, 'postgresql')``
双兼容。Celery 任务用 ``create_task_engine()``（NullPool）避免事件循环绑定。
"""
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import JSON, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from memory_graph.config import settings

# JSON 字段：SQLite 存 JSON 文本，PostgreSQL 用 JSONB（与 Comet 原版一致）
JSONField = JSON().with_variant(JSONB(), "postgresql")


def _sqlite_path() -> Path:
    """SQLite 文件路径：默认放 agent 服务目录（与 kb.db / sessions.db 同级）。"""
    if settings.audit_sqlite_path:
        return Path(settings.audit_sqlite_path)
    # 本文件位于 <agent>/memory_graph/db/audit_db.py -> parents[2] 即 agent 目录
    return Path(__file__).resolve().parents[2] / "memory_graph.db"


def _build_url() -> str:
    if settings.audit_backend == "postgres":
        return settings.postgres_url
    return f"sqlite+aiosqlite:///{_sqlite_path()}"


def _create_engine(**kwargs):
    url = _build_url()
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.db_echo, future=True, **kwargs)
    return create_async_engine(
        url,
        echo=settings.db_echo,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
        connect_args={
            "server_settings": {
                "timezone": "UTC",
                "statement_timeout": str(settings.db_statement_timeout_ms),
            }
        },
        **kwargs,
    )


engine = _create_engine()
if _build_url().startswith("sqlite"):
    _sqlite_path().parent.mkdir(parents=True, exist_ok=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def ping() -> bool:
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def create_task_engine():
    """为 Celery 任务创建独立引擎（NullPool，绑定当前事件循环，用完即弃）。"""
    from sqlalchemy.pool import NullPool

    return _create_engine(poolclass=NullPool)


async def close() -> None:
    await engine.dispose()
