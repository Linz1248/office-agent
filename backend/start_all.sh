#!/usr/bin/env bash
# 一键启动 office-agent 后端：3 个原有服务 + MCP Server + Agent Service + API 网关。
#
# 用法：
#   ./start_all.sh                  # 默认端口：网关 8080，内部 8000/9090/9900/9091/9093
#   GATEWAY_PORT=9000 ./start_all.sh
#
# 环境变量（均可选）：
#   GATEWAY_PORT / MULTIMODEL_PORT / DOC_EXTRACT_PORT / DOC_COMPARE_PORT
#   OFFICE_MCP_PORT / AGENT_PORT
#   RETRIEVE_ENV / AGENT_ENV / GATEWAY_ENV / OFFICE_AGENT_ENV   (conda 环境名)
#   DEEPSEEK_API_KEY          (DeepSeek API 密钥)
#   LLM_PROVIDER              (模型提供商: deepseek/openai/dashscope/ollama)
#   SERVICE_ACCOUNT_PASSWORD  (document_extract 服务账号密码)
#
# PID 文件写入 run/，可用 ./stop_all.sh 随时停止；按 Ctrl+C 亦停止全部。
# 日志位于 ./logs/。

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
RUN_DIR="$ROOT/run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

# 自动加载项目根目录的 .env 文件
ENV_FILE="$(cd "$ROOT/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  echo "[配置] 已加载 .env 文件"
fi

GATEWAY_PORT="${GATEWAY_PORT:-8080}"
MULTIMODEL_PORT="${MULTIMODEL_PORT:-8000}"
DOC_EXTRACT_PORT="${DOC_EXTRACT_PORT:-9090}"
DOC_COMPARE_PORT="${DOC_COMPARE_PORT:-9900}"
OFFICE_MCP_PORT="${OFFICE_MCP_PORT:-9091}"
AGENT_PORT="${AGENT_PORT:-9093}"

RETRIEVE_ENV="${RETRIEVE_ENV:-retrieve}"
AGENT_ENV="${AGENT_ENV:-agent}"
GATEWAY_ENV="${GATEWAY_ENV:-retrieve}"          # 网关仅需 fastapi/uvicorn/httpx
OFFICE_AGENT_ENV="${OFFICE_AGENT_ENV:-office-agent}"  # MCP Server + Agent Service

# 定位 conda
if ! command -v conda >/dev/null 2>&1; then
  echo "[错误] 未找到 conda，请先初始化 conda 并确保其在 PATH 中。" >&2
  exit 1
fi
CONDA_BASE="$(conda info --base)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"

# ── 防重复启动 ─────────────────────────────────────────────────
# 上一轮 PID 文件仍存活说明后端已在运行，拒绝再次启动避免端口冲突/进程堆积
for pidfile in "$RUN_DIR"/*.pid; do
  [ -e "$pidfile" ] || continue
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "[错误] 检测到服务仍在运行（pid=$pid，PID 文件 $pidfile）。" >&2
    echo "        如需重启，请先执行 ./stop_all.sh" >&2
    exit 1
  fi
  # 进程已不存在，清理陈旧 PID 文件
  rm -f "$pidfile"
done

PIDS=()
NAMES=()

# 启动 uvicorn 服务（用于原有服务和 Agent Service）
start_service() {
  local name="$1" env="$2" dir="$3" port="$4"
  echo "[启动] $name  (env=$env, port=$port)"
  (
    cd "$dir"
    conda activate "$env"
    exec uvicorn main:app --host 0.0.0.0 --port "$port"
  ) >"$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  NAMES+=("$name")
  echo "$pid" >"$RUN_DIR/$name.pid"
  echo "        pid=$pid  log=$LOG_DIR/$name.log"
}

# 启动 Python 脚本服务（用于 MCP Server）
start_script_service() {
  local name="$1" env="$2" dir="$3" port="$4"
  echo "[启动] $name  (env=$env, port=$port)"
  (
    cd "$dir"
    conda activate "$env"
    exec python server.py
  ) >"$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  NAMES+=("$name")
  echo "$pid" >"$RUN_DIR/$name.pid"
  echo "        pid=$pid  log=$LOG_DIR/$name.log"
}

# 启动记忆图谱 Celery worker（仅在 MEMORY_GRAPH_CELERY_ENABLED=true 时）。
# solo 池：单进程跑任务，规避 prefork fork+asyncio+Neo4j 驱动跨进程继承的坑，
# 适合 office-agent 单实例低并发；MEMORY_WORKER_BEAT=1（默认）同时起定时调度
# （每日巩固/反思/聚类）。仅当 Celery 启用才起，否则中间件走进程内 asyncio 兜底。
start_memory_worker() {
  local name="memory_worker" env="$OFFICE_AGENT_ENV" dir="$ROOT/agent"
  local beat_arg=""
  [ "${MEMORY_WORKER_BEAT:-1}" = "1" ] && beat_arg="--beat"
  echo "[启动] $name  (env=$env, pool=solo, queue=memory,beat${beat_arg:+，带 beat 调度})"
  (
    cd "$dir"
    conda activate "$env"
    # worker 入口（celery 控制台）不会把 agent/ 加入 sys.path，导致任务运行时
    # llm_bridge 无法 import 同级顶层模块 llm_config。显式注入 PYTHONPATH。
    export PYTHONPATH="$dir:${PYTHONPATH:-}"
    exec celery -A memory_graph.celery_app worker \
      --pool=solo --concurrency=1 \
      -Q memory,beat -l info $beat_arg
  ) >"$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  NAMES+=("$name")
  echo "$pid" >"$RUN_DIR/$name.pid"
  echo "        pid=$pid  log=$LOG_DIR/$name.log"
}

cleanup() {
  # 防止 trap 触发时重复执行
  [ "${CLEANUP_DONE:-0}" = "1" ] && return
  CLEANUP_DONE=1
  echo
  echo "[停止] 正在终止所有服务..."
  # 逆序停止：网关先下线，再停依赖它的内部服务
  for ((i=${#PIDS[@]}-1; i>=0; i--)); do
    local pid="${PIDS[$i]}" name="${NAMES[$i]}"
    if kill "$pid" 2>/dev/null; then
      echo "        停止 $name (pid=$pid)"
    fi
  done
  # 等待退出，最多 5s，超时强杀（兜底清理 uvicorn 子进程）
  local waited=0
  while [ "$waited" -lt 50 ]; do
    local alive=0
    for pid in "${PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 0.1
    waited=$((waited+1))
  done
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      pkill -P "$pid" 2>/dev/null || true
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  rm -f "$RUN_DIR"/*.pid
  echo "[停止] 已终止。"
  echo "[提示] Neo4j（记忆图谱）未随 Ctrl+C 停止；如需停止请执行 ./stop_all.sh 或 ./install_memory_infra.sh stop"
}
trap cleanup EXIT INT TERM HUP

# ── 原有服务 ──────────────────────────────────────────────────
start_service multimodel       "$RETRIEVE_ENV" "$ROOT/multimodel"       "$MULTIMODEL_PORT"
start_service document_extract "$AGENT_ENV"    "$ROOT/document_extract" "$DOC_EXTRACT_PORT"
start_service document_compare "$AGENT_ENV"    "$ROOT/document_compare" "$DOC_COMPARE_PORT"

# ── 记忆图谱基础设施（Neo4j，无 Docker 原生部署）───────────────
# best-effort 拉起：未安装时提示跳过（记忆模块自动降级旁路，不影响其他服务）；
# 已在运行时 neo4j start 幂等无害。
if [ -x "$ROOT/install_memory_infra.sh" ]; then
  "$ROOT/install_memory_infra.sh" start >/dev/null 2>&1 \
    && echo "[记忆图谱] Neo4j 已启动" \
    || echo "[记忆图谱] Neo4j 未就绪（记忆功能降级；首次请执行 backend/install_memory_infra.sh install）"
fi

# ── 记忆图谱 Celery worker（启用 Celery 时随栈启动）─────────
if [ "${MEMORY_GRAPH_CELERY_ENABLED:-false}" = "true" ]; then
  start_memory_worker
  sleep 1
fi

# ── 新增服务 ──────────────────────────────────────────────────
# 略作等待，让原有服务端口先绑定
sleep 1
start_script_service office_mcp "$OFFICE_AGENT_ENV" "$ROOT/office_mcp" "$OFFICE_MCP_PORT"

# MCP Server 启动后再启动 Agent Service
sleep 1
start_service agent             "$OFFICE_AGENT_ENV" "$ROOT/agent"      "$AGENT_PORT"

# ── 网关 ──────────────────────────────────────────────────────
sleep 1
start_service gateway          "$GATEWAY_ENV"  "$ROOT/gateway"          "$GATEWAY_PORT"

echo
echo "============================================================"
echo " office-agent 后端已启动（统一入口）"
echo "   网关:        http://localhost:${GATEWAY_PORT}"
echo "   /multimodel  -> multimodel       (内部 ${MULTIMODEL_PORT})"
echo "   /extract     -> document_extract (内部 ${DOC_EXTRACT_PORT})"
echo "   /compare     -> document_compare (内部 ${DOC_COMPARE_PORT})"
echo "   /agent       -> agent service    (内部 ${AGENT_PORT})"
echo " MCP Server:     http://localhost:${OFFICE_MCP_PORT}/mcp"
echo " 日志目录: ${LOG_DIR}/"
echo " 停止方式: Ctrl+C 或 ./stop_all.sh"
echo "============================================================"
echo

# 等待任一服务退出，则停止全部
wait -n 2>/dev/null || wait
echo "[警告] 有服务已退出，正在停止全部..." >&2
