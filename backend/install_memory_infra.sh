#!/usr/bin/env bash
# 记忆图谱基础设施：无 Docker 的原生 Neo4j 部署（本机实战验证过的路径）。
#
# 用法（在 backend/ 目录下执行）：
#   ./install_memory_infra.sh install   # 安装：JDK(按需) + Neo4j + 初始密码 + 内存调优
#   ./install_memory_infra.sh start     # 启动 Neo4j 并等待就绪（供 start_all.sh 调用）
#   ./install_memory_infra.sh stop      # 停止 Neo4j
#   ./install_memory_infra.sh status    # 查看状态
#   ./install_memory_infra.sh restart   # 重启并等待就绪
#
# 安装位置：
#   - root 用户：装到 /opt/office-agent-memory/{neo4j,jdk}，用专用系统用户 neo4j 运行
#     （Neo4j 拒绝 root 运行；/opt 布局保证专用用户可访问，不依赖 /root 权限）。
#   - 非 root 用户：装到 backend/infra/，以当前用户运行。
#
# Neo4j 获取顺序（服务器封锁 dist.neo4j.org 时自动回退）：
#   ① 本地 NEO4J_TARBALL ② tarball 下载（dist → neo4j.com → 华为云）
#   ③ yum.neo4j.com 社区版 RPM + memory_graph/rpm_extract.py 重组为 tarball 布局
#      （rpm_extract.py 为纯标准库解包器，无需 rpm/rpm2cpio 等系统工具）。
#
# JDK 获取顺序（Neo4j 5.x 需 Java 17/21）：
#   ① 系统 java(>=17) ② 已装目录 ③ 本地 JDK_TARBALL
#   ④ Adoptium 21 tarball（清华 tuna 镜像 → 官方 API）。仅 install 会下载 JDK；
#   start/stop/status/restart 只探测，绝不触发下载。
#
# 环境变量（可选）：
#   NEO4J_VERSION    Neo4j 版本，默认 5.26.29（与当前 RPM 仓库一致）
#   NEO4J_TARBALL    本地 Neo4j tarball；JDK_TARBALL 本地 JDK 21 tarball
#   NEO4J_PASSWORD   初始密码，默认 officeagent（与 MEMORY_GRAPH_NEO4J_PASSWORD 一致）
#   NEO4J_PORT       Bolt 端口（就绪探测用），默认 7687
#   NEO4J_READY_TIMEOUT  等待就绪的秒数，默认 90
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$ROOT/infra"
NEO4J_VERSION="${NEO4J_VERSION:-5.26.29}"
NEO4J_TARBALL="${NEO4J_TARBALL:-}"
JDK_TARBALL="${JDK_TARBALL:-}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-officeagent}"
NEO4J_PORT="${NEO4J_PORT:-7687}"
READY_TIMEOUT="${NEO4J_READY_TIMEOUT:-90}"

# ── 安装位置与运行用户 ──
if [ "$(id -u)" = "0" ]; then
  BASE_DIR="/opt/office-agent-memory"
  NEO4J_HOME="$BASE_DIR/neo4j"
  JDK_DIR="$BASE_DIR/jdk"
  RUN_AS="neo4j"
else
  BASE_DIR="$INFRA_DIR"
  NEO4J_HOME="$BASE_DIR/neo4j-community-$NEO4J_VERSION"
  JDK_DIR="$BASE_DIR/jdk"
  RUN_AS=""
fi

# 以运行用户执行命令（root 时切到 neo4j 用户）。
# JAVA_HOME 仅在独立 JDK 目录存在时才注入；否则用系统 PATH 上的 java。
run_as_user() {
  local env_args=(NEO4J_HOME="$NEO4J_HOME")
  if [ -x "$JDK_DIR/bin/java" ]; then
    env_args+=(JAVA_HOME="$JDK_DIR" PATH="$JDK_DIR/bin:$PATH")
  fi
  if [ -n "$RUN_AS" ]; then
    if command -v runuser >/dev/null 2>&1; then
      runuser -u "$RUN_AS" -- env "${env_args[@]}" "$@"
    else
      su -s /bin/bash "$RUN_AS" -c "env $(printf '%q ' "${env_args[@]}") $(printf '%q ' "$@")"
    fi
  else
    env "${env_args[@]}" "$@"
  fi
}

java_major() {
  "${JAVA_BIN:-java}" -version 2>&1 | head -1 | sed -E 's/.*version "([0-9]+).*/\1/' | grep -E '^[0-9]+$' || echo 0
}

# ── 只探测可用 Java（不下载）：start/stop/status/restart 用 ──
locate_java() {
  if command -v java >/dev/null 2>&1; then
    JAVA_BIN="$(command -v java)"
    [ "$(java_major)" -ge 17 ] && return 0
  fi
  [ -x "$JDK_DIR/bin/java" ] && return 0
  echo "[错误] 未找到可用的 Java 17/21（系统 java 与 $JDK_DIR 均不可用）。" >&2
  echo "        请先执行: ./install_memory_infra.sh install" >&2
  return 1
}

# ── 确保可用 Java（必要时下载安装）：仅 install 用 ──
resolve_java() {
  locate_java && return 0
  local JDK_FILE="OpenJDK21U-jdk_x64_linux_hotspot_${JDK_VERSION:-21.0.12_8}.tar.gz"
  local TARBALL="$JDK_TARBALL"
  if [ -z "$TARBALL" ] || [ ! -f "$TARBALL" ]; then
    TARBALL="$INFRA_DIR/$JDK_FILE"
  fi
  if [ ! -f "$TARBALL" ]; then
    mkdir -p "$INFRA_DIR"
    local URLS=(
      "https://mirrors.tuna.tsinghua.edu.cn/Adoptium/21/jdk/x64/linux/$JDK_FILE"
      "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse"
    )
    echo "[安装] 下载 JDK 21（多源回退）..."
    local ok=0 u
    for u in "${URLS[@]}"; do
      echo "[安装] 尝试: $u"
      if curl -fL --retry 2 --connect-timeout 15 -o "$TARBALL" "$u"; then ok=1; break; fi
      rm -f "$TARBALL"
    done
    [ "$ok" = "1" ] || { echo "[错误] JDK 下载失败。请用 JDK_TARBALL=<路径> 指定本地 JDK 21 tarball。" >&2; return 1; }
  else
    echo "[安装] 使用已缓存的 JDK tarball: $TARBALL"
  fi
  echo "[安装] 解压 JDK 到 $JDK_DIR ..."
  mkdir -p "$JDK_DIR"
  tar -xzf "$TARBALL" -C "$JDK_DIR" --strip-components=1 || return 1
  [ -x "$JDK_DIR/bin/java" ] || { echo "[错误] JDK 解压后未找到 bin/java。" >&2; return 1; }
  echo "[安装] JDK 就绪: $("$JDK_DIR/bin/java" -version 2>&1 | head -1)"
}

# ── 从 tarball 布局的目录安装到 NEO4J_HOME ──
install_from_layout() {
  local src="$1"
  # 防御：NEO4J_HOME 必须是安全路径（非空、非根、不以 / 结尾误删）
  [ -n "$NEO4J_HOME" ] && [ "$NEO4J_HOME" != "/" ] && [ "$NEO4J_HOME" != "/opt" ] \
    || { echo "[错误] 安装路径异常: $NEO4J_HOME" >&2; return 1; }
  mkdir -p "$(dirname "$NEO4J_HOME")"
  if [ "$(realpath "$src")" != "$(realpath "$NEO4J_HOME")" ]; then
    rm -rf "$NEO4J_HOME"
    cp -r "$src" "$NEO4J_HOME"
  fi
  normalize_conf
}

# ── 把 RPM 遗留的绝对路径配置改为相对路径（tarball 布局兼容）──
normalize_conf() {
  local CONF="$NEO4J_HOME/conf/neo4j.conf"
  set_conf() {
    grep -qE "^$1=" "$CONF" 2>/dev/null && sed -i -E "s|^$1=.*|$1=$2|" "$CONF" || echo "$1=$2" >> "$CONF"
  }
  set_conf server.directories.data data
  set_conf server.directories.logs logs
  set_conf server.directories.run run
  set_conf server.directories.plugins plugins
  set_conf server.directories.lib lib
  set_conf server.directories.import import
  set_conf server.logs.config conf/server-logs.xml
  set_conf server.logs.user.config conf/user-logs.xml
  set_conf server.memory.heap.initial_size 512m
  set_conf server.memory.heap.max_size 1G
  set_conf server.memory.pagecache.size 512m
  mkdir -p "$NEO4J_HOME"/{data,logs,run,import}
  chmod +x "$NEO4J_HOME"/bin/* 2>/dev/null || true
}

# ── 等待 Neo4j Bolt 就绪（start/restart 后调用，防 agent 服务冷启动竞态）──
wait_ready() {
  local waited=0
  while [ "$waited" -lt "$READY_TIMEOUT" ]; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$NEO4J_PORT") 2>/dev/null; then
      exec 3>&- 3<&- 2>/dev/null || true
      echo "[记忆图谱] Neo4j 已就绪 (bolt://127.0.0.1:$NEO4J_PORT，等待 ${waited}s)"
      return 0
    fi
    sleep 1
    waited=$((waited+1))
  done
  echo "[警告] Neo4j 在 ${READY_TIMEOUT}s 内未就绪（查看 $NEO4J_HOME/logs/neo4j.log）。" >&2
  return 1
}

cmd="${1:-install}"

case "$cmd" in
  install)
    resolve_java || exit 1

    if [ ! -x "$NEO4J_HOME/bin/neo4j" ]; then
      NAME="neo4j-community-$NEO4J_VERSION-unix.tar.gz"
      # ① 本地 tarball
      if [ -n "$NEO4J_TARBALL" ] && [ -f "$NEO4J_TARBALL" ]; then
        echo "[安装] 使用本地 tarball: $NEO4J_TARBALL"
        TMP="$(mktemp -d)"
        tar -xzf "$NEO4J_TARBALL" -C "$TMP" || exit 1
        install_from_layout "$TMP/neo4j-community-"* || exit 1
        rm -rf "$TMP"
      else
        # ② tarball 下载（带缓存校验）
        TARBALL="$INFRA_DIR/$NAME"
        mkdir -p "$INFRA_DIR"
        ok=0
        if [ -s "$TARBALL" ] && tar -tzf "$TARBALL" >/dev/null 2>&1; then
          echo "[安装] 使用已缓存的 tarball: $TARBALL"
          ok=1
        else
          rm -f "$TARBALL"
          for u in \
            "https://dist.neo4j.org/$NAME" \
            "https://neo4j.com/artifact.php?name=$NAME" \
            "https://mirrors.huaweicloud.com/neo4j/$NAME"; do
            echo "[安装] 尝试下载: $u"
            if curl -fL --retry 2 --connect-timeout 15 -o "$TARBALL" "$u"; then ok=1; break; fi
            rm -f "$TARBALL"
          done
        fi
        if [ "$ok" = "1" ]; then
          TMP="$(mktemp -d)"
          tar -xzf "$TARBALL" -C "$TMP" || exit 1
          install_from_layout "$TMP/neo4j-community-"* || exit 1
          rm -rf "$TMP"
        else
          # ③ RPM 回退：yum.neo4j.com + 纯标准库解包器重组为 tarball 布局
          RPM_FILE="$INFRA_DIR/neo4j-community-$NEO4J_VERSION-1.noarch.rpm"
          if [ ! -s "$RPM_FILE" ]; then
            echo "[安装] tarball 源均不可达，回退 RPM 方式: yum.neo4j.com"
            curl -fL --retry 2 --connect-timeout 15 -o "$RPM_FILE" \
              "https://yum.neo4j.com/stable/5/neo4j-$NEO4J_VERSION-1.noarch.rpm" || {
              echo "[错误] RPM 下载失败。请手动下载 tarball 并用 NEO4J_TARBALL=<路径> 指定。" >&2
              exit 1
            }
          else
            echo "[安装] 使用已缓存的 RPM: $RPM_FILE"
          fi
          echo "[安装] 用 rpm_extract.py 解包并重组布局 ..."
          python3 "$ROOT/agent/memory_graph/rpm_extract.py" "$RPM_FILE" "$NEO4J_HOME" || exit 1
          normalize_conf
        fi
      fi
    else
      echo "[安装] Neo4j 已存在: $NEO4J_HOME"
      normalize_conf
    fi

    # 运行用户与属主
    if [ -n "$RUN_AS" ]; then
      id -u "$RUN_AS" >/dev/null 2>&1 || useradd -r -s /bin/false "$RUN_AS"
      chown -R "$RUN_AS:$RUN_AS" "$NEO4J_HOME"
      chown -R root:root "$NEO4J_HOME/bin" "$NEO4J_HOME/lib"
      chown -R root:root "$JDK_DIR" 2>/dev/null || true
      chmod 755 "$BASE_DIR" "$NEO4J_HOME"
    fi

    # 初始密码（仅首次有效；已初始化过的库报错可忽略）
    run_as_user "$NEO4J_HOME/bin/neo4j-admin" dbms set-initial-password "$NEO4J_PASSWORD" 2>/dev/null \
      || echo "[提示] 初始密码设置跳过（可能已设置过）。如密码不同请改 .env 的 MEMORY_GRAPH_NEO4J_PASSWORD。"

    echo "[安装] 完成。启动: ./install_memory_infra.sh start"
    ;;

  start|stop|status|restart)
    [ -x "$NEO4J_HOME/bin/neo4j" ] || { echo "[错误] 未安装 Neo4j。先执行: ./install_memory_infra.sh install" >&2; exit 1; }
    locate_java || exit 1
    run_as_user "$NEO4J_HOME/bin/neo4j" "$cmd" || {
      # neo4j start 对「已在运行」返回非零并打印提示——视为成功状态
      case "$cmd" in
        start|restart) : ;;
        *) exit 1 ;;
      esac
    }
    # start/restart 后等待 Bolt 就绪（冷启动约 10-30s；首次初始化更久）
    case "$cmd" in
      start|restart) wait_ready ;;
    esac
    ;;

  *)
    echo "用法: $0 [install|start|stop|status|restart]" >&2
    exit 1
    ;;
esac
