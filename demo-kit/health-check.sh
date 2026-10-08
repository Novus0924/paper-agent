#!/usr/bin/env bash
# demo-kit/health-check.sh — 环境自检（一条命令跑完"环境体检"）
# ============================================================
# 用法：
#   bash demo-kit/health-check.sh                 # 人类可读（✓/⚠/✗ + 修复指引）
#   bash demo-kit/health-check.sh --json          # 机器可读（供 bootstrap / CI 复用）
#   bash demo-kit/health-check.sh --quiet         # 静默，仅用退出码
#   bash demo-kit/health-check.sh --only ports    # 只跑某一项
#
# 检查项（6）：python / root / runs / env / ports / agh
#   python·root·runs·ports 取自 `python -m paper_agent.cli doctor` 的 JSON
#   （单一真源，避免自检逻辑散落 Bash 与 Python 两处）；env·agh 在 Bash 层补齐：
#     - env：需看"原始环境变量"，用 printenv 直接读（用于检出失效的持久化变量 ENV-1）；
#     - agh：需解析 `package status` 的 desired/actual/trusted。
#
# 退出码：0=全绿 / 2=有⚠（可继续）/ 1=有✗（阻断）。
#
# 兼容：Git Bash / WSL / macOS / Linux。零第三方依赖。
# 约束：不依赖 AGH——未装 AGH 时该项降级为 ⚠ 而非 ✗。

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/env.sh
source "$KIT_DIR/lib/env.sh"
# shellcheck source=lib/report.sh
source "$KIT_DIR/lib/report.sh"

usage() { sed -n '2,17p' "$0"; }

JSON=0
QUIET=0
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --json)  JSON=1 ;;
    --quiet) QUIET=1 ;;
    --only)  ONLY="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf '未知参数：%s\n\n' "$1" >&2; usage; exit 1 ;;
  esac
  shift
done

want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

PA_RUNDIR="$KIT_DIR/.run"
mkdir -p "$PA_RUNDIR"
DOC="$PA_RUNDIR/doctor.json"
DOC_ERR="$PA_RUNDIR/doctor.err"
HEALTH_JSON="$PA_RUNDIR/health.json"

pa_reset_counts

# ── 0) Python 缺失 → 直接阻断 ──
if [ -z "$PA_PY" ]; then
  if [ "$JSON" = 1 ]; then
    printf '{"ok":false,"level":"fail","summary":{"warn":0,"fail":1},"checks":{"python":{"ok":false}}}\n'
  elif [ "$QUIET" != 1 ]; then
    pa_banner "paper-agent 环境自检（demo-kit）"
  fi
  [ "$QUIET" = 1 ] || [ "$JSON" = 1 ] || {
    check_fail "Python 解释器" "未找到满足 >= $PA_PY_MIN 的 python/python3" \
      "安装 Python >= $PA_PY_MIN，并设 paper-agent_PYTHON=<python 绝对路径>。"
    pa_summary || true
  }
  exit 1
fi

# ── 1) 采集 doctor JSON（注入正确环境，保证 doctor 一定能跑）──
pa_py -m paper_agent.cli doctor > "$DOC" 2> "$DOC_ERR"
DOCTOR_RC=$?

if [ "$QUIET" != 1 ] && [ "$JSON" != 1 ]; then
  pa_banner "paper-agent 环境自检（demo-kit）"
  printf '仓库根：%s\n' "$PA_REPO_ROOT"
  printf 'Python ：%s\n\n' "$PA_PY"
fi

if ! "$PA_PY" -c 'import json,sys; json.load(open(sys.argv[1],encoding="utf-8"))' "$DOC" 2>/dev/null; then
  if [ "$JSON" = 1 ]; then
    printf '{"ok":false,"level":"fail","summary":{"warn":0,"fail":1},"checks":{"doctor":{"ok":false,"exit_code":%s}}}\n' "$DOCTOR_RC"
  elif [ "$QUIET" != 1 ]; then
    check_fail "环境自检（doctor）" "doctor 退出码 $DOCTOR_RC，未产出合法 JSON；见 $DOC_ERR" \
      "常见原因：paper-agent_ROOT 指向非法目录导致导入期报错。"
    pa_summary || true
  fi
  exit 1
fi

# ── 2) 取值（doctor 真源）──
PY_OK="$(pa_jget "$DOC" "d['python']['ok']")"
PY_VER="$(pa_jget "$DOC" "d['python']['value']")"
PY_PATH="$(pa_jget "$DOC" "d['python']['path']")"
PY_FIX="$(pa_jget "$DOC" "d['python']['fix']")"
ROOT_OK="$(pa_jget "$DOC" "d['project_root']['ok']")"
ROOT_VAL="$(pa_jget "$DOC" "d['project_root']['value']")"
ROOT_FIX="$(pa_jget "$DOC" "d['project_root']['fix']")"
RUNS_OK="$(pa_jget "$DOC" "d['runs']['writable']")"
RUNS_DIR="$(pa_jget "$DOC" "d['runs']['dir']")"
RUNS_FIX="$(pa_jget "$DOC" "d['runs']['fix']")"
PORTS_OK="$(pa_jget "$DOC" "d['ports']['ok']")"
PORTS_DET="$(pa_jget "$DOC" "'  '.join('%s=%s'%(k,'free' if v['free'] else 'USED') for k,v in sorted(d['ports']['detail'].items()))")"
PORTS_FIX="$(pa_jget "$DOC" "d['ports']['fix']")"
AGH_ENTRY="$(pa_jget "$DOC" "d['agh'].get('entry','')")"
AGH_AUDIT="$(pa_jget "$DOC" "d['agh'].get('audit_log')")"

# env 契约（Bash 层，读原始变量）
RAW_ROOT="$(printenv 'paper-agent_ROOT' 2>/dev/null || true)"
RAW_PY="$(printenv 'paper-agent_PYTHON' 2>/dev/null || true)"
ENV_OK=1
if [ -z "$RAW_ROOT" ]; then
  ENV_DETAIL="paper-agent_ROOT 未设置 → CLI 自动探测为仓库根（可用）。"
elif [ ! -d "$RAW_ROOT/core/paper_agent" ]; then
  ENV_OK=0
  ENV_DETAIL="paper-agent_ROOT=$RAW_ROOT —— 目录不存在或缺少 core/paper_agent（失效变量）。"
elif [ "$(pa_to_win "$RAW_ROOT")" != "$(pa_to_win "$PA_REPO_ROOT")" ]; then
  ENV_OK=0
  ENV_DETAIL="paper-agent_ROOT=$RAW_ROOT —— 有效但≠当前仓库根（$PA_REPO_ROOT）。"
else
  ENV_DETAIL="paper-agent_ROOT=$RAW_ROOT —— 生效且等于仓库根。"
fi
ENV_FIX="启动 daemon 的终端里重新注入：env \"paper-agent_ROOT=$(pa_to_win "$PA_REPO_ROOT")\" ... 后重启 daemon；或清掉失效的用户变量。"

# AGH（找到入口且 node>=24 才尝试 package status；只读、带回退、不阻断）
AGH_OK=0
AGH_LINE=""
AGH_DETAIL=""
AGH_FIX="未检测到 AGH（可选）：demo-kit 不依赖 AGH；如需集成见 docs/AGH插件安装指南.md。"
NODE_V="$([ -n "$PA_NODE" ] && "$PA_NODE" -v 2>/dev/null || echo 0)"
if [ -z "$AGH_ENTRY" ]; then
  AGH_DETAIL="未检测到 AGH 入口 agnes.mjs（audit_log=${AGH_AUDIT}）。"
elif [ -z "$PA_NODE" ]; then
  AGH_DETAIL="找到 AGH 入口，但未找到 node（>= $PA_NODE_MIN）。"
  AGH_FIX="安装 Node >= $PA_NODE_MIN，或用 AGH_NODE=<node 绝对路径> 指定。"
elif ! pa_version_ge "$NODE_V" "$PA_AGH_NODE_MIN"; then
  AGH_DETAIL="找到 AGH 入口，但 node $NODE_V < $PA_AGH_NODE_MIN（AGH 硬要求），跳过插件状态查询。"
  AGH_FIX="安装 Node >= $PA_AGH_NODE_MIN，或用 AGH_NODE=<node 绝对路径> 指定后重跑。"
else
  AGH_OUT="$(cd "$PA_REPO_ROOT" && env "paper-agent_PYTHON=$PA_PY" "paper-agent_ROOT=$(pa_to_win "$PA_REPO_ROOT")" \
      timeout 25 "$PA_NODE" "$(pa_to_win "$AGH_ENTRY")" package status 2>&1 || true)"
  AGH_LINE="$(printf '%s' "$AGH_OUT" | grep 'paper-agent-tools' | head -1 || true)"
  if printf '%s' "$AGH_LINE" | grep -q 'actual=running' && printf '%s' "$AGH_LINE" | grep -q 'trusted=true'; then
    AGH_OK=1
    AGH_DETAIL="AGH 已安装且就绪：$AGH_LINE"
    AGH_FIX=""
  elif [ -n "$AGH_LINE" ]; then
    AGH_DETAIL="AGH 已装但未完全就绪：$AGH_LINE"
    AGH_FIX="运行 bash demo/install_plugin.sh 补齐 trust+enable（幂等）。"
  else
    AGH_DETAIL="找到 AGH 入口但未装 paper-agent-tools（$AGH_ENTRY）。"
    AGH_FIX="安装：bash demo/install_plugin.sh（真实终端内）。"
  fi
fi

# ── 3) 输出 ──
if [ "$JSON" = 1 ]; then
  PA_ENV_OK="$ENV_OK" PA_ENV_DETAIL="$ENV_DETAIL" PA_ENV_FIX="$ENV_FIX" \
  PA_RAW_ROOT="$RAW_ROOT" PA_RAW_PY="$RAW_PY" \
  PA_AGH_OK="$AGH_OK" PA_AGH_LINE="$AGH_LINE" \
    "$PA_PY" - "$DOC" > "$HEALTH_JSON" <<'PY'
import json, os, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
env_ok = os.environ["PA_ENV_OK"] == "1"
agh_ok = os.environ["PA_AGH_OK"] == "1"
checks = {
    "python": {"ok": doc["python"]["ok"], "value": doc["python"]["value"],
               "path": doc["python"]["path"], "fix": doc["python"]["fix"]},
    "root":   {"ok": doc["project_root"]["ok"], "value": doc["project_root"]["value"],
               "fix": doc["project_root"]["fix"]},
    "runs":   {"ok": doc["runs"]["writable"], "dir": doc["runs"]["dir"],
               "fix": doc["runs"]["fix"]},
    "env":    {"ok": env_ok, "detail": os.environ["PA_ENV_DETAIL"],
               "paper-agent_ROOT": {"raw": os.environ.get("PA_RAW_ROOT", "")},
               "paper-agent_PYTHON": {"raw": os.environ.get("PA_RAW_PY", "")},
               "fix": os.environ["PA_ENV_FIX"]},
    "ports":  {"ok": doc["ports"]["ok"], "detail": doc["ports"]["detail"],
               "fix": doc["ports"]["fix"]},
    "agh":    {"ok": agh_ok, "optional": True, "entry": doc["agh"].get("entry", ""),
               "audit_log": doc["agh"].get("audit_log"),
               "status_line": os.environ.get("PA_AGH_LINE", ""),
               "fix": "" if agh_ok else "AGH 缺失属可选、不阻断；集成见 docs/AGH插件安装指南.md。"},
}
blocking = ("python", "root", "runs")
n_fail = sum(1 for k in blocking if not checks[k]["ok"])
n_warn = sum(1 for k, c in checks.items() if not c["ok"] and k not in blocking)
level = "fail" if n_fail else ("warn" if n_warn else "ok")
out = {"ok": n_fail == 0, "level": level,
       "summary": {"ok": sum(1 for c in checks.values() if c["ok"]),
                   "warn": n_warn, "fail": n_fail},
       "checks": checks}
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
sys.exit(0 if n_fail == 0 and n_warn == 0 else (1 if n_fail else 2))
PY
  RC=$?
  [ "$QUIET" != 1 ] && cat "$HEALTH_JSON"
  [ "$QUIET" != 1 ] && printf '\n'
  exit "$RC"
fi

if [ "$QUIET" != 1 ]; then
  if want python; then
    if [ "$PY_OK" = "True" ]; then check_ok "Python 解释器" "$PY_VER（$PY_PATH）"
    else check_fail "Python 解释器" "版本 $PY_VER" "$PY_FIX"; fi
  fi
  if want root; then
    if [ "$ROOT_OK" = "True" ]; then check_ok "项目根" "$ROOT_VAL（含 core/paper_agent）"
    else check_fail "项目根" "$ROOT_VAL" "$ROOT_FIX"; fi
  fi
  if want runs; then
    if [ "$RUNS_OK" = "True" ]; then check_ok "runs/ 可写" "$RUNS_DIR"
    else check_fail "runs/ 可写" "$RUNS_DIR" "$RUNS_FIX"; fi
  fi
  if want env; then
    if [ "$ENV_OK" = "1" ]; then check_ok "环境变量契约" "$ENV_DETAIL"
    else check_warn "环境变量契约" "$ENV_DETAIL" "$ENV_FIX"; fi
  fi
  if want ports; then
    if [ "$PORTS_OK" = "True" ]; then check_ok "端口 8787/5173" "$PORTS_DET"
    else check_warn "端口 8787/5173" "$PORTS_DET" "$PORTS_FIX"; fi
  fi
  if want agh; then
    if [ "$AGH_OK" = "1" ]; then check_ok "AGH 插件状态" "$AGH_DETAIL"
    else check_warn "AGH 插件状态" "$AGH_DETAIL" "$AGH_FIX"; fi
  fi
  pa_summary || true
fi

# ── 4) 退出码（考虑 --only：只计入选中的检查）──
BLOCK=0; WARN=0
want python && [ "$PY_OK" != "True" ] && BLOCK=1
want root   && [ "$ROOT_OK" != "True" ] && BLOCK=1
want runs   && [ "$RUNS_OK" != "True" ] && BLOCK=1
want env    && [ "$ENV_OK" != "1" ] && WARN=1
want ports  && [ "$PORTS_OK" != "True" ] && WARN=1
want agh    && [ "$AGH_OK" != "1" ] && WARN=1
if [ "$BLOCK" = 1 ]; then exit 1; fi
if [ "$WARN" = 1 ]; then exit 2; fi
exit 0
