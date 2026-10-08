#!/usr/bin/env bash
# demo-kit/lib/env.sh — 共享环境探测库（被 health-check / bootstrap / demo-script source）
# ============================================================
# 设计目标：把三脚本共用的"仓库根 / Python / Node / 端口"探测逻辑收敛到一处，
# 消除口径漂移（规划 B2-1）。
#
# 铁律（P0-2 环境变量口径）：
#   bash 的 `export` 写不了带连字符的变量名（`paper-agent_ROOT`），对 Python 是空操作。
#   ⇒ 一律用 `env "paper-agent_ROOT=..." ...` 前缀注入；本库提供 `pa_py` 统一入口。
#   禁止在此库或调用方出现 `export PAPER_AGENT_ROOT`。
#
# 兼容：Git Bash / WSL / macOS / Linux（只用 POSIX 工具 + netstat/lsof 双平台探测）。
# 零第三方依赖。

# 防重复 source
[ -n "${PA_ENV_SOURCED:-}" ] && return 0
PA_ENV_SOURCED=1

# ---------- 路径解析：本文件位于 <repo>/demo-kit/lib/env.sh ----------
PA_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_KIT_DIR="$(cd "$PA_LIB_DIR/.." && pwd)"
PA_REPO_ROOT="$(cd "$PA_KIT_DIR/.." && pwd)"

# ---------- 端口常量（与既有 web/ 对齐）----------
PA_WEB_PORT="${PA_WEB_PORT:-5173}"   # 静态前端
PA_API_PORT="${PA_API_PORT:-8787}"   # 真实后端（HTTP+SSE）
PA_FAKE_PORT="${PA_FAKE_PORT:-8788}" # 假后端（内存 mock）

# ---------- 演示资产路径 ----------
PA_WEB_DIR="$PA_REPO_ROOT/web"               # 旧前端 + 真/假后端（live/fake 模式）
# 零构建高完成度原型（mock 模式主展示面）。本工作区里 `演示原型/` 是 paper-agent 的
# **同级目录**（workspace 根），故先看仓库内、再看仓库的上一级，兼容两种布局。
PA_PROTOTYPE_DIR="$PA_REPO_ROOT/演示原型"
if [ ! -d "$PA_PROTOTYPE_DIR" ] && [ -d "$PA_REPO_ROOT/../演示原型" ]; then
  PA_PROTOTYPE_DIR="$(cd "$PA_REPO_ROOT/.." && pwd)/演示原型"
fi

# ---------- 最小版本要求 ----------
PA_PY_MIN="3.10"
PA_NODE_MIN="18"       # demo-kit 自身（静态服务/假后端）所需；node 18+ 即可
PA_AGH_NODE_MIN="24"   # 仅 AGH 运行底座硬要求（demo-kit 不依赖 AGH）

# MSYS 路径转 Windows 原生路径（node 只认后者）；非 MSYS 原样返回
pa_to_win() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# ---------- 解释器探测 ----------
# pa_detect_python：env paper-agent_PYTHON → python3 → python（返回满足 >=3.10 的第一个）
pa_detect_python() {
  local c
  for c in "$(printenv 'paper-agent_PYTHON' 2>/dev/null || true)" \
           "$(command -v python3 2>/dev/null || true)" \
           "$(command -v python 2>/dev/null || true)"; do
    [ -n "$c" ] || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      printf '%s' "$(pa_to_win "$c")"; return 0
    fi
  done
  return 1
}

# pa_detect_node：env AGH_NODE → node（返回满足 >=24 的第一个；demo-kit 不强制）
pa_detect_node() {
  local c v major
  for c in "${AGH_NODE:-}" "$(command -v node 2>/dev/null || true)" \
           "/c/Program Files/nodejs/node.exe"; do
    [ -n "$c" ] || continue
    v="$("$c" -v 2>/dev/null || true)"
    [ -n "$v" ] || continue
    major="${v#v}"; major="${major%%.*}"
    if [ "$major" -ge "$PA_NODE_MIN" ] 2>/dev/null; then printf '%s' "$c"; return 0; fi
  done
  return 1
}

# 探测结果（供调用方直接用；失败为空串）
PA_PY="$(pa_detect_python || true)"
PA_NODE="$(pa_detect_node || true)"

# ---------- 统一 Python 调用入口（带连字符变量用 env 前缀注入）----------
# 用法：pa_py -m paper_agent.cli doctor
pa_py() {
  env "PYTHONPATH=$PA_REPO_ROOT/core" \
      "paper-agent_ROOT=$PA_REPO_ROOT" "paper-agent_PYTHON=$PA_PY" "$PA_PY" "$@"
}

# 不带注入的裸调用（仅设 PYTHONPATH；供需要"看真实环境"的探测使用）
pa_py_raw() {
  env "PYTHONPATH=$PA_REPO_ROOT/core" "$PA_PY" "$@"
}

# ---------- 端口探测（netstat / lsof 双平台；只按 IPv4 判定）----------
# 说明：demo-kit 的服务只绑 IPv4 127.0.0.1，故这里只匹配 127.0.0.1/0.0.0.0，
# 显式排除 [::1] 这类 IPv6 监听——否则会被无关的 IPv6 进程误判为"端口被占用"。
# pa_port_used <port>  → 0=被占用，1=空闲
pa_port_used() {
  local port="$1"
  if command -v netstat >/dev/null 2>&1; then
    if [ "$(netstat -ano 2>/dev/null | grep -E "(127\.0\.0\.1|0\.0\.0\.0):${port}[[:space:]]+.*LISTENING" | grep -c .)" -gt 0 ]; then
      return 0
    fi
    return 1
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  return 1
}

# pa_port_owner <port> → 打印占用者 PID（IPv4；拿不到则空）
pa_port_owner() {
  local port="$1"
  if command -v netstat >/dev/null 2>&1; then
    netstat -ano 2>/dev/null | grep -E "(127\.0\.0\.1|0\.0\.0\.0):${port}[[:space:]]+.*LISTENING" \
      | awk '{print $NF}' | grep -E '^[0-9]+$' | head -1
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}' | head -1
  fi
}

# ---------- 本地探测用的 curl（绕开系统代理）----------
# 本机若设了 http_proxy/https_proxy（企业代理/沙箱），curl 到 127.0.0.1 也会走代理
# → 502 Bad Gateway。故本地探测一律 --noproxy '*'。
pa_curl() { curl --noproxy '*' "$@"; }

# ---------- 版本比较 <have> >= <need> ----------
pa_version_ge() {
  local have="${1#v}" need="${2#v}" i x y
  local IFS='.'
  local -a a b
  read -r -a a <<<"$have"
  read -r -a b <<<"$need"
  for i in 0 1 2; do
    x="${a[$i]:-0}"; y="${b[$i]:-0}"
    x="${x//[!0-9]/}"; y="${y//[!0-9]/}"
    x="${x:-0}"; y="${y:-0}"
    if [ "$x" -gt "$y" ]; then return 0; fi
    if [ "$x" -lt "$y" ]; then return 1; fi
  done
  return 0
}

# ---------- JSON 取值：pa_jget <jsonfile> <python-expr on d> ----------
pa_jget() {
  "$PA_PY" - "$1" "$2" <<'PY'
import sys, json, builtins
with open(sys.argv[1], encoding="utf-8") as f:
    d = json.load(f)
g = {"__builtins__": builtins, "d": d, "len": len, "str": str, "bool": bool}
print(eval(sys.argv[2], g))
PY
}
