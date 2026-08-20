"""记忆图谱 Celery 应用：memory 队列（萃取）+ beat 队列（巩固/反思/聚类）。

与 agent 服务同处 ``backend/agent/`` 目录运行，可复用 ``llm_config`` 与 ``config``。
不启动 worker 时，中间件会回退进程内 asyncio 萃取，系统仍可运行。
"""
# Worker 入口（celery -A memory_graph.celery_app）不会把 agent/ 加入 sys.path，
# 故同级的顶层模块（llm_config / config）不可导入。此处显式注入，保证任务运行时
# llm_bridge 能 import llm_config 构建 chat 模型。
import sys
from pathlib import Path

_AGENT_DIR = str(Path(__file__).resolve().parents[1])  # backend/agent/
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from celery import Celery  # noqa: E402
from celery.schedules import crontab  # noqa: E402

from memory_graph.config import settings  # noqa: E402

celery_app = Celery(
    "memory_graph",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "memory_graph.tasks.memory",
        "memory_graph.tasks.beat",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_default_queue="memory",
    task_routes={
        "memory_graph.tasks.memory.*": {"queue": "memory"},
        "memory_graph.tasks.beat.*": {"queue": "beat"},
    },
    beat_schedule={
        "consolidate-memory": {
            "task": "memory_graph.tasks.beat.consolidate_memory",
            "schedule": crontab(hour=4, minute=0),
        },
        "reflect-memory": {
            "task": "memory_graph.tasks.beat.reflect_memory",
            "schedule": crontab(hour=4, minute=30),
        },
        "cluster-communities": {
            "task": "memory_graph.tasks.beat.cluster_communities",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
