#!/usr/bin/env bash
# demo/demo_trust.sh — 信任机制现场演示：账本篡改检测 + 伪造验证拦截
#
# 用法：bash demo/demo_trust.sh <已完成的真实 RUN_ID>
#   例：bash demo/demo_trust.sh run-20261003-135418-5d3b7e
#
# 演示内容（全程只操作 runs/run-trust-demo 副本，不污染真实 run）：
#   [1] 基线：干净副本正常出报告（信任基线成立）
#   [2] 攻击 A：篡改 provenance.jsonl 中一条证据记录（不重算链哈希）
#       → 期望：报告生成被拒绝（verify_chain 链式哈希重放检出）
#   [3] 攻击 B：恢复账本后伪造 verification.json（伪 PASS 短路攻击）
#       → 期望：P4 完整性闸门拒绝复用缓存（sha256 与账本登记不符）
#
# 退出码：全部拦截成功 → 0；任一攻击未被拦截 → 1（演示失败）

set -euo pipefail
cd "$(dirname "$0")/.."

ROOT="$PWD"
export PYTHONPATH="$ROOT/core"
# ⚠️ PAPER_AGENT_ROOT 仅供脚本内部拼路径；Python 读的是带连字符的 paper-agent_ROOT
#    —— bash 的 export 写不了带连字符的变量名（对 Python 是空操作），
#    故统一用下面的 env 前缀注入（P0-2，与 demo/install_plugin.sh 一致）。
export PAPER_AGENT_ROOT="$ROOT"
export PYTHONIOENCODING="utf-8"
PY="$(printenv paper-agent_PYTHON || echo python)"
py() { env "paper-agent_ROOT=$ROOT" "paper-agent_PYTHON=$PY" "$PY" "$@"; }

SRC_RUN="${1:?usage: demo_trust.sh <RUN_ID>}"
DEMO_RUN="run-trust-demo"
RUN_DIR="runs/$DEMO_RUN"

cleanup() { rm -rf "$RUN_DIR"; }
trap cleanup EXIT

echo "==> [0/3] 从真实 run 复制演示副本: $SRC_RUN -> $DEMO_RUN"
[ -d "runs/$SRC_RUN" ] || { echo "error: source run not found: $SRC_RUN" >&2; exit 1; }
rm -rf "$RUN_DIR"
cp -r "runs/$SRC_RUN" "$RUN_DIR"

echo "==> [1/3] 基线：干净副本正常出报告"
py -m paper_agent.cli report --run "$DEMO_RUN" > /dev/null
echo "  PASS: report generated on clean copy (trust baseline)"

echo "==> [2/3] 攻击 A：篡改 provenance.jsonl 第一条证据记录（不重算链哈希）"
py - "$RUN_DIR/provenance.jsonl" <<'PYTAMPER'
import json, sys
p = sys.argv[1]
with open(p, encoding="utf-8") as f:
    lines = [l for l in f.read().splitlines() if l.strip()]
rec = json.loads(lines[0])
rec["ref"] = "tampered-by-demo"
lines[0] = json.dumps(rec, ensure_ascii=False)
with open(p, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("  tampered record 1 ref ->", rec["ref"])
PYTAMPER

if py -m paper_agent.cli report --run "$DEMO_RUN" > runs_err.txt 2>&1; then
  echo "  FAIL: tampered ledger accepted, report still generated!" >&2
  exit 1
fi
grep -q "provenance ledger tampered" runs_err.txt || {
  echo "  FAIL: refused but unexpected error:" >&2; cat runs_err.txt >&2; exit 1; }
echo "  PASS: report refused -> $(head -c 200 runs_err.txt)"
rm -f runs_err.txt

echo "==> [3/3] 攻击 B：恢复账本后伪造 verification.json（伪 PASS 短路）"
rm -rf "$RUN_DIR" && cp -r "runs/$SRC_RUN" "$RUN_DIR"
py - "$RUN_DIR/verification/verification.json" <<'PYFORGE'
import json, sys
p = sys.argv[1]
with open(p, encoding="utf-8") as f:
    d = json.load(f)
d["status"] = "PASS"          # 伪造者想要的结果
d["forged_by_demo"] = True    # 任何改动都会破坏 sha256 与账本登记的一致性
with open(p, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print("  forged verification.json (status=PASS, extra field)")
PYFORGE

if py -m paper_agent.cli verify --run "$DEMO_RUN" > runs_err.txt 2>&1; then
  echo "  FAIL: forged verification accepted, P4 still PASS!" >&2
  exit 1
fi
grep -q "verification.json sha256 mismatch" runs_err.txt || {
  echo "  FAIL: refused but unexpected error:" >&2; cat runs_err.txt >&2; exit 1; }
echo "  PASS: P4 gate refused -> $(head -c 200 runs_err.txt)"
rm -f runs_err.txt

echo "TRUST_DEMO_OK  both attacks detected and blocked (exit 0)"
