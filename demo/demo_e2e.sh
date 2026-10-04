#!/usr/bin/env bash
# demo/demo_e2e.sh — 端到端正常流程演示 + 实验确定性核验
# 用法：cd 到项目根目录后执行  bash demo/demo_e2e.sh
# 说明：需要 bash + sha256sum（Windows 用 Git Bash / WSL）

set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/core"
export PAPER_AGENT_ROOT="$PWD"
# 强制 Python stdin/stdout/stderr 为 UTF-8，避免管道读 JSON 时按系统码页(cp936)解码中文路径失败
export PYTHONIOENCODING="utf-8"
# 本脚本演示 **legacy 路径**（内置演示语料 + 7 行演示数据）——显式禁用快照保证确定性。
# 真实数据主线（快照消费）见 demo/demo_mainline.sh。
export PAPER_AGENT_SNAPSHOT="none"
PY="$(printenv paper-agent_PYTHON || echo python)"
# P1 检索来源：默认 local（离线、逐字节可复现）。
# 想看实时 arXiv 检索：LIT_SOURCE=arxiv bash demo/demo_e2e.sh
LIT_SOURCE="${LIT_SOURCE:-local}"
TMPJSON="$(mktemp)"
trap 'rm -f "$TMPJSON"' EXIT

echo "==> [1/4] plan + run-all 正常路径（lit-source=$LIT_SOURCE）"
PLAN_JSON=$("$PY" -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity ranking" --lit-source "$LIT_SOURCE")
echo "$PLAN_JSON"
RUN_ID=$(printf '%s' "$PLAN_JSON" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['run_id'])")
echo "RUN_ID=$RUN_ID"

"$PY" -m paper_agent.cli run-all --run "$RUN_ID" > "$TMPJSON"
"$PY" - "$TMPJSON" <<'PY'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["ok"] is True, f"run-all not DONE: {d['run_status']}"
assert d["degraded"] is False, "unexpected degraded on normal path"
assert d["results"]["P4_verify"]["status"] == "PASS", "P4 must PASS"
print("  run-all DONE, degraded=False, P4 PASS  ->", d["run_id"])
PY

echo "==> [2/4] 实验确定性：两次独立运行 SHA-256 必须一致"
IN="$PAPER_AGENT_ROOT/runs/$RUN_ID/clean/conductivity_clean.csv"
"$PY" experiments/arrhenius_rank.py --input "$IN" --outdir "$PAPER_AGENT_ROOT/runs/$RUN_ID/verify_a" --seed 0 >/dev/null
"$PY" experiments/arrhenius_rank.py --input "$IN" --outdir "$PAPER_AGENT_ROOT/runs/$RUN_ID/verify_b" --seed 0 >/dev/null
HA=$(sha256sum "$PAPER_AGENT_ROOT/runs/$RUN_ID/verify_a/results/results.csv" | cut -d' ' -f1)
HB=$(sha256sum "$PAPER_AGENT_ROOT/runs/$RUN_ID/verify_b/results/results.csv" | cut -d' ' -f1)
echo "  A=$HA"
echo "  B=$HB"
[ "$HA" = "$HB" ] && echo "  DETERMINISTIC: PASS" || { echo "  DETERMINISTIC: FAIL"; exit 1; }

echo "==> [3/4] 结论‑证据回查（cite）"
"$PY" -m paper_agent.cli cite --run "$RUN_ID" --ev EV-0001
"$PY" -m paper_agent.cli cite --run "$RUN_ID" --ev EV-0009

echo "==> [4/4] 报告摘要"
"$PY" -c "import sys;print(open(sys.argv[1], encoding='utf-8').read())" \
    "$PAPER_AGENT_ROOT/runs/$RUN_ID/report.md"
echo "DEMO_E2E_OK  RUN=$RUN_ID"
