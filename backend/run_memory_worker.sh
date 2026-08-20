#!/usr/bin/env bash
# 启动记忆图谱 Celery worker（可选组件）。
#
# 仅当 .env 设 MEMORY_GRAPH_CELERY_ENABLED=true（高并发/多实例需队列）时才需要；
# 默认无 Docker 部署不需要本 worker：萃取由中间件派发进程内 asyncio 后台任务完成。
# 启用队列还需 Redis（broker/backend），连接见 .env 的 MEMORY_GRAPH_CELERY_BROKER_URL。
#
# 用法：在 backend/ 目录下执行
#   ./run_memory_worker.sh                 # 仅 worker
#   BEAT=1 ./run_memory_worker.sh          # 同时起 beat 调度（每日巩固/反思/聚类）
#
# 必须从 backend/agent/ 目录运行，以便复用 office-agent 的 llm_config / config。

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$ROOT/agent"

# 加载项目根 .env
ENV_FILE="$(cd "$ROOT/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

ENV_NAME="${AGENT_ENV:-office-agent}"
if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base)"
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  conda activate "$ENV_NAME"
fi

cd "$AGENT_DIR"

# worker 入口（celery 控制台）不会把 agent/ 加入 sys.path，导致任务运行时
# llm_bridge 无法 import 同级顶层模块 llm_config。显式注入 PYTHONPATH。
export PYTHONPATH="$AGENT_DIR:${PYTHONPATH:-}"

if [ "${BEAT:-0}" = "1" ]; then
  # 同时起 worker + beat（前台）
  celery -A memory_graph.celery_app worker -Q memory,beat -l info --beat
else
  celery -A memory_graph.celery_app worker -Q memory,beat -l info
fi
