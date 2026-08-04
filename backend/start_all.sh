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
# 按 Ctrl+C 停止全部服务。日志位于 ./logs/。

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

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
  echo "        pid=$pid  log=$LOG_DIR/$name.log"
}

cleanup() {
  echo
  echo "[停止] 正在终止所有服务..."
  for i in "${!PIDS[@]}"; do
    if kill "${PIDS[$i]}" 2>/dev/null; then
      echo "        停止 ${NAMES[$i]} (pid=${PIDS[$i]})"
    fi
  done
  # 兜底：清理可能残留的子进程
  for pid in "${PIDS[@]}"; do
    pkill -P "$pid" 2>/dev/null || true
  done
  echo "[停止] 已终止。"
}
trap cleanup EXIT INT TERM

# ── 原有服务 ──────────────────────────────────────────────────
start_service multimodel       "$RETRIEVE_ENV" "$ROOT/multimodel"       "$MULTIMODEL_PORT"
start_service document_extract "$AGENT_ENV"    "$ROOT/document_extract" "$DOC_EXTRACT_PORT"
start_service document_compare "$AGENT_ENV"    "$ROOT/document_compare" "$DOC_COMPARE_PORT"

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
echo " 按 Ctrl+C 停止全部"
echo "============================================================"
echo

# 等待任一服务退出，则停止全部
wait -n 2>/dev/null || wait
echo "[警告] 有服务已退出，正在停止全部..." >&2
