"""Neo4j 记忆图谱 schema：唯一约束 + 向量索引 + 全文索引。

应用启动时调用 ensure_graph_schema() 幂等创建。中文全文检索用 cjk 分词器，
向量索引维度与 embedding 配置一致（余弦相似度）。
"""
from memory_graph.config import settings
from memory_graph.core.graph_models import (
    LABEL_CHUNK,
    LABEL_COMMUNITY,
    LABEL_DIALOGUE,
    LABEL_ENTITY,
    LABEL_EVENT,
    LABEL_INSIGHT,
    LABEL_STATEMENT,
)
from memory_graph.db.neo4j import get_driver
from memory_graph.logger import get_logger

logger = get_logger(__name__)

VECTOR_DIMS = settings.embedding_dims

_CONSTRAINTS = [
    f"CREATE CONSTRAINT dialogue_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_DIALOGUE}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_CHUNK}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT statement_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_STATEMENT}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT event_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_EVENT}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT community_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_COMMUNITY}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT insight_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_INSIGHT}) REQUIRE n.id IS UNIQUE",
]

_PROPERTY_INDEXES = [
    f"CREATE INDEX entity_user_idx IF NOT EXISTS FOR (n:{LABEL_ENTITY}) ON (n.user_id)",
    f"CREATE INDEX event_user_idx IF NOT EXISTS FOR (n:{LABEL_EVENT}) ON (n.user_id)",
    f"CREATE INDEX statement_user_idx IF NOT EXISTS FOR (n:{LABEL_STATEMENT}) ON (n.user_id)",
    f"CREATE INDEX entity_name_idx IF NOT EXISTS FOR (n:{LABEL_ENTITY}) ON (n.name)",
    f"CREATE INDEX entity_layer_idx IF NOT EXISTS FOR (n:{LABEL_ENTITY}) ON (n.memory_layer)",
    f"CREATE INDEX statement_layer_idx IF NOT EXISTS FOR (n:{LABEL_STATEMENT}) ON (n.memory_layer)",
    f"CREATE INDEX insight_user_idx IF NOT EXISTS FOR (n:{LABEL_INSIGHT}) ON (n.user_id)",
    f"CREATE INDEX insight_theme_idx IF NOT EXISTS FOR (n:{LABEL_INSIGHT}) ON (n.theme)",
]

_FULLTEXT_INDEXES = [
    f"CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) ON EACH [n.name, n.description, n.aliases] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
    f"CREATE FULLTEXT INDEX statement_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_STATEMENT}) ON EACH [n.statement] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
    f"CREATE FULLTEXT INDEX event_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_EVENT}) ON EACH [n.title, n.description] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
    f"CREATE FULLTEXT INDEX insight_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_INSIGHT}) ON EACH [n.content, n.theme] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
]

def _vector_indexes(dims: int) -> list[str]:
    return [
        (
            f"CREATE VECTOR INDEX entity_embedding_index IF NOT EXISTS "
            f"FOR (n:{LABEL_ENTITY}) ON n.name_embedding "
            f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {dims}, "
            f"`vector.similarity_function`: 'cosine' }} }}"
        ),
        (
            f"CREATE VECTOR INDEX statement_embedding_index IF NOT EXISTS "
            f"FOR (n:{LABEL_STATEMENT}) ON n.embedding "
            f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {dims}, "
            f"`vector.similarity_function`: 'cosine' }} }}"
        ),
        (
            f"CREATE VECTOR INDEX event_embedding_index IF NOT EXISTS "
            f"FOR (n:{LABEL_EVENT}) ON n.embedding "
            f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {dims}, "
            f"`vector.similarity_function`: 'cosine' }} }}"
        ),
        (
            f"CREATE VECTOR INDEX insight_embedding_index IF NOT EXISTS "
            f"FOR (n:{LABEL_INSIGHT}) ON n.embedding "
            f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {dims}, "
            f"`vector.similarity_function`: 'cosine' }} }}"
        ),
    ]


async def ensure_graph_schema() -> None:
    """幂等创建记忆图谱的约束与索引。应用启动时调用。

    Neo4j 不可达时抛异常（让 init 走降级/自愈路径，避免「就绪误报」）；
    单条语句失败仅告警跳过（容忍旧版 Neo4j 不支持个别索引特性）。
    """
    driver = get_driver()
    # 连接性检查：不可达必须失败，而不是被下面逐条 try/except 静默吞掉
    await driver.verify_connectivity()
    # 维度在调用时读取，保证与运行时 embedding 配置一致（允许 env 覆盖）
    statements = (
        _CONSTRAINTS + _PROPERTY_INDEXES + _FULLTEXT_INDEXES + _vector_indexes(settings.embedding_dims)
    )
    async with driver.session() as session:
        for cypher in statements:
            try:
                await session.run(cypher)
            except Exception as e:
                logger.warning("创建图 schema 语句失败（跳过）: %s | %s", cypher[:60], e)
    logger.info("记忆图谱 schema 初始化完成 (dims=%d)", settings.embedding_dims)


__all__ = ["ensure_graph_schema", "VECTOR_DIMS"]
