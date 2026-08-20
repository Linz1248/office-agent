"""记忆图谱模块配置：全部从环境变量读取，自包含、可拔插。

与 office-agent 既有 ``config.py`` 的扁平风格不同，本模块用 pydantic-settings 集中管理，
便于在不改动主配置的前提下整体启停。

无 Docker 部署（默认）：
  - 审计库默认 SQLite（不使用 PG，零额外服务）；
  - 反思增量计数优先 Redis（``INCRBY``），Redis 不可用回退 SQLite；Redis 为可选
    外部服务（已安装并启动即可用于计数；``celery_enabled=true`` 时兼作 broker）；
  - 萃取派发默认进程内 asyncio（零额外进程），``celery_enabled=true`` 时走 Celery；
  - 唯一必需的外部服务是 Neo4j（原生 tarball 部署，见 backend/install_memory_infra.sh）。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMORY_GRAPH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 总开关：置 False 则 is_ready() 永远返回 False，模块整体旁路 ──
    enabled: bool = True

    # ── Neo4j ──
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "officeagent"
    neo4j_max_pool_size: int = 50
    neo4j_connection_timeout: int = 30

    # ── 审计库（来源原文 / 萃取审计 / 人工纠错 / 反思计数）──
    # 默认 SQLite（office-agent 全栈惯例，零额外服务）；可选 postgres。
    # 选 postgres 时使用下方 postgres_* 连接参数。
    audit_backend: str = "sqlite"  # sqlite | postgres
    audit_sqlite_path: str = ""  # 留空则默认 <agent服务目录>/memory_graph.db
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "officeagent"
    postgres_password: str = "officeagent"
    postgres_db: str = "officeagent"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_statement_timeout_ms: int = 60000
    db_echo: bool = False

    # ── Redis / Celery ──
    # redis_url：反思增量计数后端（优先于 SQLite）。Redis 已安装启动即可用，
    #   不可用时自动回退 SQLite，不阻断萃取。
    # celery_enabled：是否走 Celery 队列派发萃取/反思（broker=Redis）。默认 False
    #   走进程内 asyncio（零额外进程）；置 True 需启动 backend/run_memory_worker.sh。
    celery_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Embedding：维度须与所用 embedding 模型输出维度一致 ──
    # 默认复用 office-agent 知识库的 Ollama qwen3-embedding:8b（4096 维）
    embedding_provider: str = "ollama"
    embedding_ollama_host: str = "http://localhost:11434"
    embedding_model: str = "qwen3-embedding:8b"
    embedding_dims: int = 4096

    # ── 检索门控 ──
    global_search_min_vector_score: float = 0.45
    memory_search_min_vector_score: float = 0.45

    # ── 巩固（短期->长期，只升不降）──
    consolidate_min_access: int = 2
    consolidate_min_importance: float = 0.7
    consolidate_min_mention: int = 3
    consolidate_min_age_hours: int = 24
    consolidate_profile_top_k: int = 5

    # ── 反思 ──
    reflection_top_k: int = 25
    reflection_stmt_per_entity: int = 4
    reflection_min_insights: int = 3
    reflection_max_insights: int = 6
    reflection_min_entities: int = 5
    reflection_trigger_threshold: int = 20

    # ── 主动召回 ──
    active_recall_entity_top_k: int = 5
    active_recall_insight_top_k: int = 2
    active_recall_min_score: float = 0.5
    active_recall_min_confidence: float = 0.6
    active_recall_uncertain_confidence: float = 0.75
    active_recall_max_chars: int = 600

    # ── 中间件控制模式：static_control / agent_control / both ──
    control_mode: str = "both"

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
