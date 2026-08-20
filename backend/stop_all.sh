#!/usr/bin/env bash
# 停止 office-agent 后端全部服务。
#
# 用法：
#   ./stop_all.sh           # 正常停止（优雅退出，超时强杀）
#   ./stop_all.sh -f        # 强制停止（跳过等待，直接 KILL）
#
# 停止策略（最佳实践）：
#   1. 读取 run/*.pid（由 start_all.sh 写入）逐个停止；
#   2. PID 归属校验：仅当目标进程命令行匹配本项目特征时才发信号，防止 PID 复用误杀；
#   3. 先 TERM 优雅退出 -> 等待至多 5s -> 超时 KILL，并清理 uvicorn 子进程；
#   4. 兜底扫描：PID 文件丢失/损坏时，按可执行路径精确匹配残留进程；
#   5. 最后校验端口已释放。

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/run"

FORCE=0
[ "${1:-}" = "-f" ] && FORCE=1

# 判断 pid 对应进程是否属于本项目（双重校验，防 PID 复用/误杀）：
#   1. 进程工作目录必须在本项目内（各服务均由 start_all.sh 在项目目录下启动）
#   2. 命令行必须是本项目的服务形态（python uvicorn / python server.py）
owns_pid() {
  local pid="$1" cwd args
  # 排除脚本自身与父进程
  [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ] && return 1
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || return 1
  case "$cwd" in
    "$ROOT"|"$ROOT"/*) ;;
    *) return 1 ;;
  esac
  args="$(ps -o args= -p "$pid" 2>/dev/null)" || return 1
  case "$args" in
    *python*"uvicorn main:app"*|*python*"server.py") return 0 ;;
    *celery*"worker"*|*python*-m*celery*) return 0 ;;  # 记忆图谱 Celery worker
  esac
  return 1
}

# 对单个 pid 执行 停止流程，成功停止返回 0
stop_pid() {
  local pid="$1" label="$2"
  kill -0 "$pid" 2>/dev/null || return 1

  if [ "$FORCE" = "1" ]; then
    pkill -9 -P "$pid" 2>/dev/null
    kill -9 "$pid" 2>/dev/null
    echo "        已强制停止 $label (pid=$pid)"
    return 0
  fi

  kill -TERM "$pid" 2>/dev/null
  # 等待至多 5s
  local waited=0
  while [ "$waited" -lt 50 ] && kill -0 "$pid" 2>/dev/null; do
    sleep 0.1
    waited=$((waited+1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    pkill -9 -P "$pid" 2>/dev/null
    kill -9 "$pid" 2>/dev/null
    echo "        超时强杀 $label (pid=$pid)"
  else
    echo "        已停止 $label (pid=$pid)"
  fi
  return 0
}

stopped=0

echo "[停止] office-agent 后端..."

# ── 1. 按 PID 文件停止 ─────────────────────────────────────────
for pidfile in "$RUN_DIR"/*.pid; do
  [ -e "$pidfile" ] || continue
  name="$(basename "$pidfile" .pid)"
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  rm -f "$pidfile"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "        跳过 $name（进程不存在）"
    continue
  fi
  if ! owns_pid "$pid"; then
    echo "        跳过 $name (pid=$pid，非本项目进程，疑似 PID 复用)"
    continue
  fi
  stop_pid "$pid" "$name"
  stopped=$((stopped+1))
done

# ── 2. 兜底扫描残留进程 ────────────────────────────────────────
# PID 文件丢失/损坏时，按项目路径兜底扫描（owns_pid 已排除脚本自身）
cleaned=0
for pid in $(pgrep -f "$ROOT" 2>/dev/null || true); do
  owns_pid "$pid" || continue
  [ "$cleaned" -eq 0 ] && echo "[兜底] 发现 PID 文件之外的残留进程，尝试清理..."
  stop_pid "$pid" "残留进程"
  cleaned=$((cleaned+1))
  stopped=$((stopped+1))
done

# ── 3. 记忆图谱基础设施（Neo4j，随 start_all.sh best-effort 拉起的配套停止）──
if [ -x "$ROOT/install_memory_infra.sh" ]; then
  if "$ROOT/install_memory_infra.sh" stop >/dev/null 2>&1; then
    echo "[记忆图谱] Neo4j 已停止"
  else
    echo "[记忆图谱] Neo4j 停止失败或未安装（不影响后端服务停止）"
  fi
fi

# ── 4. 端口校验 ────────────────────────────────────────────────
port_busy() {
  ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1$"
}

GATEWAY_PORT="${GATEWAY_PORT:-8080}"
MULTIMODEL_PORT="${MULTIMODEL_PORT:-8000}"
DOC_EXTRACT_PORT="${DOC_EXTRACT_PORT:-9090}"
DOC_COMPARE_PORT="${DOC_COMPARE_PORT:-9900}"
OFFICE_MCP_PORT="${OFFICE_MCP_PORT:-9091}"
AGENT_PORT="${AGENT_PORT:-9093}"

busy_ports=""
for p in "$GATEWAY_PORT" "$MULTIMODEL_PORT" "$DOC_EXTRACT_PORT" "$DOC_COMPARE_PORT" "$OFFICE_MCP_PORT" "$AGENT_PORT"; do
  port_busy "$p" && busy_ports="$busy_ports $p"
done

echo "[停止] 完成（共停止 $stopped 个进程）。"
if [ -n "$busy_ports" ]; then
  echo "[警告] 以下端口仍被占用（可能被其他程序使用）:$busy_ports" >&2
  exit 1
fi
