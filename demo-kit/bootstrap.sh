#!/usr/bin/env bash
# demo-kit/bootstrap.sh — 一键启动可演示环境
# ============================================================
# 用法：
#   bash demo-kit/bootstrap.sh                 # 默认 --mode mock（零后端，最可靠）
#   bash demo-kit/bootstrap.sh --mode live     # 真实后端 8787 + 静态前端 5173
#   bash demo-kit/bootstrap.sh --mode fake     # 假后端 8788 + 静态前端 5173
#   bash demo-kit/bootstrap.sh --port 5199     # 顺延静态端口
#   bash demo-kit/bootstrap.sh --no-check      # 跳过自检
#   bash demo-kit/bootstrap.sh --stop          # 停止本套件启动的服务
#
# 三种 mode 与 web/README.md 的三种联调方式对齐：
#   mock → 只起静态服务，指向 `演示原型/`（零构建高完成度原型；不碰 AGH、不碰真后端）
#   fake → 起 web/mock/server.js（内存假后端）+ 静态服务指向 web/
#   live → 起 web/server/paper-agent-server.js（真跑 Python）+ 静态服务指向 web/
#
# 退出码：0=已起 / 1=阻断（自检有 ✗ 或端口占用等）。
# 兼容：Git Bash / WSL / macOS / Linux。零第三方依赖。

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/env.sh
source "$KIT_DIR/lib/env.sh"

usage() { sed -n '2,20p' "$0"; }

MODE="mock"
WEB_PORT="$PA_WEB_PORT"
DO_CHECK=1
DO_STOP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mode)     MODE="${2:-}"; shift ;;
    --port)     WEB_PORT="${2:-}"; shift ;;
    --no-check) DO_CHECK=0 ;;
    --stop)     DO_STOP=1 ;;
    -h|--help)  usage; exit 0 ;;
    *) printf '未知参数：%s\n\n' "$1" >&2; usage; exit 1 ;;
  esac
  shift
done

PA_RUNDIR="$KIT_DIR/.run"
mkdir -p "$PA_RUNDIR"
PIDS="$PA_RUNDIR/pids"

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

# ---------- --stop：停止本套件启动的服务 ----------
if [ "$DO_STOP" = 1 ]; then
  if [ ! -f "$PIDS" ]; then say "没有本套件启动的服务记录（$PIDS 不存在）。"; exit 0; fi
  while read -r name pid; do
    [ -n "${pid:-}" ] || continue
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      say "已停止 $name（pid $pid）"
    else
      say "$name（pid $pid）已不在运行"
    fi
  done < "$PIDS"
  rm -f "$PIDS"
  say "完成。"
  exit 0
fi

# ---------- 0) 前置：node 必备 ----------
[ -n "$PA_NODE" ] || die "未找到 node >= $PA_NODE_MIN（demo-kit 的静态服务/假后端用 node 启动）。
   安装 Node，或用 AGH_NODE=<node 绝对路径> 指定。"

case "$MODE" in
  mock|live|fake) : ;;
  *) die "未知 --mode：$MODE（可选 mock|live|fake）" ;;
esac

# ---------- 1) 先自检（可跳过）----------
if [ "$DO_CHECK" = 1 ]; then
  say "== [1/3] 环境自检（health-check.sh）=="
  bash "$KIT_DIR/health-check.sh" || RC=$?
  RC="${RC:-0}"
  if [ "$RC" = 1 ]; then
    die "自检存在阻断项（✗）。请按上方修复指引处理后重跑：bash demo-kit/health-check.sh"
  elif [ "$RC" = 2 ]; then
    say "（自检有 ⚠ 警告，非阻断，继续启动…）"
  fi
else
  say "== [1/3] 跳过自检（--no-check）=="
fi

# ---------- 2) 端口占用处理 ----------
if pa_port_used "$WEB_PORT"; then
  owner="$(pa_port_owner "$WEB_PORT" || true)"
  die "静态端口 $WEB_PORT 已被占用（PID ${owner:-未知}）。
   处置：① 顺延：bash demo-kit/bootstrap.sh --port $((WEB_PORT + 1))
        ② 结束占用者（Git Bash）：taskkill //PID ${owner:-<pid>} //F
        ③ 若是本套件此前启动的：bash demo-kit/bootstrap.sh --stop"
fi

start_bg() {  # <name> <logfile> <cmd...>  → 启动后台服务并登记 pid
  local name="$1" log="$2"; shift 2
  nohup "$@" > "$log" 2>&1 &
  local pid=$!
  printf '%s %s\n' "$name" "$pid" >> "$PIDS"
  printf '   · %-14s pid=%-7s log=%s\n' "$name" "$pid" "$log"
}

wait_http() {  # <url> <expect_field|> <timeout_s>
  local url="$1" field="${2:-}" secs="${3:-20}" i=0
  while [ "$i" -lt "$secs" ]; do
    if [ -n "$field" ]; then
      if pa_curl -sf "$url" 2>/dev/null | grep -q "$field"; then return 0; fi
    else
      if pa_curl -sf -o /dev/null "$url" 2>/dev/null; then return 0; fi
    fi
    i=$((i + 1)); sleep 1
  done
  return 1
}

# 清理旧的 pid 记录（本轮启动的登记到一起）
: > "$PIDS" 2>/dev/null || true

say ""
say "== [2/3] 启动服务（mode=$MODE）=="

case "$MODE" in
  mock)
    [ -d "$PA_PROTOTYPE_DIR" ] || die "找不到演示原型目录：$PA_PROTOTYPE_DIR"
    start_bg "serve(演示原型)" "$PA_RUNDIR/serve.log" \
      env "PA_SERVE_ROOT=$(pa_to_win "$PA_PROTOTYPE_DIR")" "PORT=$WEB_PORT" \
      "$PA_NODE" "$KIT_DIR/lib/serve.mjs"
    URL="http://127.0.0.1:$WEB_PORT/"
    READY_URL="$URL"
    READY_FIELD=""
    ;;
  fake)
    start_bg "mock-server" "$PA_RUNDIR/fake.log" \
      env "PORT=$PA_FAKE_PORT" "$PA_NODE" "$PA_WEB_DIR/mock/server.js"
    start_bg "serve(web)" "$PA_RUNDIR/serve.log" \
      env "PA_SERVE_ROOT=$(pa_to_win "$PA_WEB_DIR")" "PORT=$WEB_PORT" \
      "$PA_NODE" "$KIT_DIR/lib/serve.mjs"
    URL="http://127.0.0.1:$WEB_PORT/?mock=0&base=http://127.0.0.1:$PA_FAKE_PORT"
    READY_URL="http://127.0.0.1:$WEB_PORT/index.html"
    READY_FIELD=""
    ;;
  live)
    start_bg "real-backend" "$PA_RUNDIR/live.log" \
      env "PORT=$PA_API_PORT" "PAPER_AGENT_ROOT=$(pa_to_win "$PA_REPO_ROOT")" \
      "$PA_NODE" "$PA_WEB_DIR/server/paper-agent-server.js"
    start_bg "serve(web)" "$PA_RUNDIR/serve.log" \
      env "PA_SERVE_ROOT=$(pa_to_win "$PA_WEB_DIR")" "PORT=$WEB_PORT" \
      "$PA_NODE" "$KIT_DIR/lib/serve.mjs"
    URL="http://127.0.0.1:$WEB_PORT/?mock=0&base=http://127.0.0.1:$PA_API_PORT"
    READY_URL="http://127.0.0.1:$PA_API_PORT/api/health"
    READY_FIELD="runs_count"
    ;;
esac

# ---------- 3) 就绪探测 + 打印 URL ----------
say ""
say "== [3/3] 就绪探测 =="
OK=1
if [ "$MODE" = "live" ]; then
  wait_http "http://127.0.0.1:$PA_API_PORT/api/health" "runs_count" 25 \
    && say "   ✓ 真实后端 /api/health 可达（runs_count）" \
    || { say "   ✗ 真实后端未就绪，见 $PA_RUNDIR/live.log"; OK=0; }
fi
if [ "$MODE" = "fake" ]; then
  wait_http "http://127.0.0.1:$PA_FAKE_PORT/api/runs" "runs" 15 \
    && say "   ✓ 假后端 /api/runs 可达" \
    || { say "   ✗ 假后端未就绪，见 $PA_RUNDIR/fake.log"; OK=0; }
fi
wait_http "$READY_URL" "$READY_FIELD" 20 \
  && say "   ✓ 静态前端可达" \
  || { say "   ✗ 静态前端未就绪，见 $PA_RUNDIR/serve.log"; OK=0; }

say ""
if [ "$OK" = 1 ]; then
  say "─────────────────────────────────────────────"
  say "✅ 已启动（mode=$MODE）。打开："
  say "   $URL"
  say "─────────────────────────────────────────────"
  say "停止：bash demo-kit/bootstrap.sh --stop"
else
  die "部分服务未就绪。请查看 $PA_RUNDIR/*.log，或先 --stop 再重试。"
fi
exit 0
