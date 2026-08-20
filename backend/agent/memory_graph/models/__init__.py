from memory_graph.db.audit_db import Base, JSONField  # noqa: F401

# 导入 ORM 模型，确保注册到 metadata（Celery 任务 / 建表依赖）
from . import memory_model  # noqa: F401
from . import memory_correction_model  # noqa: F401
from . import counter_model  # noqa: F401
