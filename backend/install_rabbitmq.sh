#!/usr/bin/env bash
# RabbitMQ 基础设施：无 Docker / 无 systemd 的原生部署（Celery broker）。
#
# 用法（在 backend/ 目录下执行）：
#   ./install_rabbitmq.sh install   # 安装：apt rabbitmq-server（含 erlang 依赖）
#   ./install_rabbitmq.sh start     # 启动节点 + 建用户/vhost + 授权 + 探测就绪
#   ./install_rabbitmq.sh stop      # 停止节点
#   ./install_rabbitmq.sh status    # 就绪探测（退出码 0=就绪）
#   ./install_rabbitmq.sh restart   # stop 后 start
#
# 服务器为容器化环境（PID 1 非 systemd），故用 `rabbitmq-server -detached`
# 裸启动，不用 systemctl。apt 发行版包 rabbitmq-server（Ubuntu 22.04 为 3.9.27，
# 自带 erlang 24 依赖）Celery 兼容，无需追最新 4.x。
#
# 与记忆图谱共用：broker URL 见 .env 的 MEMORY_GRAPH_CELERY_BROKER_URL，默认
#   amqp://officeagent:officeagent@localhost:5672/officeagent
# result backend 仍用 Redis（MEMORY_GRAPH_CELERY_RESULT_BACKEND）。
#
# 环境变量（可选）：
#   RABBITMQ_USER        用户名，默认 officeagent
#   RABBITMQ_PASSWORD    密码，默认 officeagent
#   RABBITMQ_VHOST       vhost，默认 officeagent
#   RABBITMQ_PORT        AMQP 端口（就绪探测用），默认 5672
#   RABBITMQ_READY_TIMEOUT  就绪探测超时（秒），默认 60

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RABBITMQ_USER="${RABBITMQ_USER:-officeagent}"
RABBITMQ_PASSWORD="${RABBITMQ_PASSWORD:-officeagent}"
RABBITMQ_VHOST="${RABBITMQ_VHOST:-officeagent}"
RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"
RABBITMQ_READY_TIMEOUT="${RABBITMQ_READY_TIMEOUT:-60}"

# ── 工具探测 ─────────────────────────────────────────────────
need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

rabbitmq_ready() {
  # 优先 rabbitmqctl status：要求节点应用完全就绪（不仅是 Erlang 节点存活），
  # 避免 ping 通过但应用未起时 init_auth 过早跑而报"节点未就绪"。
  # 次选 ping，末选端口探测（仅无 ctl 工具时）。
  if need_cmd rabbitmqctl; then
    rabbitmqctl -q status >/dev/null 2>&1
  elif need_cmd rabbitmq-diagnostics; then
    rabbitmq-diagnostics -q ping >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$RABBITMQ_PORT") 2>/dev/null && exec 3>&- 3<&- 2>/dev/null
  fi
}

wait_ready() {
  local waited=0
  while [ "$waited" -lt "$RABBITMQ_READY_TIMEOUT" ]; do
    if rabbitmq_ready; then
      echo "[RabbitMQ] 已就绪 (amqp://127.0.0.1:$RABBITMQ_PORT，等待 ${waited}s)"
      return 0
    fi
    sleep 1
    waited=$((waited+1))
  done
  echo "[警告] RabbitMQ 在 ${RABBITMQ_READY_TIMEOUT}s 内未就绪。" >&2
  return 1
}

# ── 初始化用户/vhost/权限（幂等：节点就绪后按存在性创建）──────────
init_auth() {
  # 二次确认节点真就绪（防 detached 启动时 5672 短暂开放后崩溃的假就绪）
  rabbitmqctl -q status >/dev/null 2>&1 || { echo "[错误] 节点未就绪，无法初始化。" >&2; return 1; }
  # 用户：先查再建（add_user 报错无法区分"已存在"与"节点故障"）
  if rabbitmqctl list_users 2>/dev/null | awk '{print $1}' | grep -qx "$RABBITMQ_USER"; then
    echo "[RabbitMQ] 用户 $RABBITMQ_USER 已存在。"
  else
    rabbitmqctl add_user "$RABBITMQ_USER" "$RABBITMQ_PASSWORD" >/dev/null 2>&1 \
      || { echo "[错误] add_user 失败。" >&2; return 1; }
  fi
  # vhost
  if rabbitmqctl list_vhosts 2>/dev/null | grep -qx "$RABBITMQ_VHOST"; then
    echo "[RabbitMQ] vhost $RABBITMQ_VHOST 已存在。"
  else
    rabbitmqctl add_vhost "$RABBITMQ_VHOST" >/dev/null 2>&1 \
      || { echo "[错误] add_vhost 失败。" >&2; return 1; }
  fi
  # 授权：configure/write/read 全放行
  rabbitmqctl set_permissions -p "$RABBITMQ_VHOST" "$RABBITMQ_USER" \
    ".*" ".*" ".*" >/dev/null 2>&1 \
    || { echo "[错误] set_permissions 失败。" >&2; return 1; }
  # 管理台插件（15672，失败不阻断 broker）
  rabbitmq-plugins enable rabbitmq_management >/dev/null 2>&1 \
    || echo "[RabbitMQ] 管理台插件启用跳过（可选，不影响 broker）。"
  echo "[RabbitMQ] 用户/vhost/权限就绪：$RABBITMQ_USER @ $RABBITMQ_VHOST"
}

cmd="${1:-install}"

case "$cmd" in
  install)
    if need_cmd rabbitmq-server && need_cmd rabbitmqctl; then
      echo "[安装] RabbitMQ 已安装：$(rabbitmq-server --version 2>&1 | tail -1)"
    else
      echo "[安装] apt 安装 rabbitmq-server（含 erlang 依赖）..."
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y rabbitmq-server || {
        echo "[错误] apt 安装失败。请检查网络/apt 源。" >&2
        exit 1
      }
    fi
    echo "[安装] 完成。启动: ./install_rabbitmq.sh start"
    ;;

  start)
    need_cmd rabbitmq-server || { echo "[错误] 未安装 RabbitMQ。先执行: ./install_rabbitmq.sh install" >&2; exit 1; }
    # 已在运行则跳过启动
    if rabbitmq_ready; then
      echo "[RabbitMQ] 已在运行，跳过启动。"
    else
      # 清理可能残留的旧节点 pid（detached 启动遇到已存在节点会失败）
      echo "[RabbitMQ] 启动节点（detached）..."
      rabbitmq-server -detached >/dev/null 2>&1
    fi
    wait_ready || { echo "[错误] RabbitMQ 启动后未就绪。" >&2; exit 1; }
    init_auth
    ;;

  stop)
    need_cmd rabbitmqctl || { echo "[错误] 未安装 RabbitMQ。" >&2; exit 1; }
    if rabbitmq_ready; then
      echo "[RabbitMQ] 停止节点..."
      rabbitmqctl shutdown >/dev/null 2>&1
      # 兜底：等节点退出
      local_wait=0
      while [ "$local_wait" -lt 20 ]; do
        rabbitmq_ready || break
        sleep 1
        local_wait=$((local_wait+1))
      done
      rabbitmq_ready && { echo "[RabbitMQ] shutdown 未生效，pkill 兜底。" >&2; pkill -f "beam.smp.*rabbit" 2>/dev/null || true; }
    else
      echo "[RabbitMQ] 未运行。"
    fi
    ;;

  status)
    if rabbitmq_ready; then
      echo "[RabbitMQ] 就绪。"
      need_cmd rabbitmqctl && rabbitmqctl -q list_vhosts 2>/dev/null | sed 's/^/    vhost: /'
      exit 0
    else
      echo "[RabbitMQ] 未就绪。" >&2
      exit 1
    fi
    ;;

  restart)
    "$0" stop || true
    "$0" start
    ;;

  *)
    echo "用法: $0 [install|start|stop|status|restart]" >&2
    exit 1
    ;;
esac
