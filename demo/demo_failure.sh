#!/usr/bin/env bash
# demo/demo_failure.sh — 四大故障恢复验收用例自动化
# 用法：cd 到项目根目录后执行  bash demo/demo_failure.sh
# 用例：A p1_fail_first / B p1_fail_all / C P2后中断resume / D mutate_summary

set -uo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/core"
export PAPER_AGENT_ROOT="$PWD"
# 强制 Python 输入输出 UTF-8，避免 Git Bash 管道按系统码页解码中文路径 JSON 失败
export PYTHONIOENCODING="utf-8"
PY="$(printenv paper-agent_PYTHON || echo python)"

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# 状态提取：把 CLI 输出写入临时 JSON 文件，再用显式 UTF-8 读文件（管道方式在
# Git Bash 下会被系统码页污染，故改用文件方式，与 demo_e2e.sh 一致且已验证）。
#   jfield <file> <python-expr-on-d>  → 打印表达式结果（表达式可引用顶层键 d）
jfield(){
  "$PY" - "$1" "$2" <<'PY'
import sys, json, builtins
d = json.load(open(sys.argv[1], encoding="utf-8"))
g = {"__builtins__": builtins, "d": d, "len": len}
print(eval(sys.argv[2], g, g))
PY
}

pass=0; fail=0
ok(){ echo "  [PASS] $1"; pass=$((pass+1)); }
bad(){ echo "  [FAIL] $1"; fail=$((fail+1)); }

# ---------- 用例 A：p1_fail_first → 重试 1 次成功，DONE，degraded=False ----------
echo "==> 用例 A  chaos=p1_fail_first"
"$PY" -m paper_agent.cli run-all --goal "sulfide solid electrolyte conductivity" \
      --chaos p1_fail_first > "$T/A.json" 2> "$T/A.err"
A_RID="$(jfield "$T/A.json" "d['run_id']")"
A_OK="$(jfield "$T/A.json" "1 if d['run_status']=='DONE' and d['degraded']==False else 0")"
A_RETRYCNT="$(grep -c '"type": "retry"' "$PAPER_AGENT_ROOT/runs/$A_RID/events.jsonl" 2>/dev/null || echo 0)"
[ "$A_OK" = "1" ] && ok "A: run DONE & degraded=False" || bad "A: expected DONE/!degraded, got $A_OK"
[ "$A_RETRYCNT" = "1" ] && ok "A: exactly 1 retry recorded" || bad "A: expected 1 retry, got $A_RETRYCNT"

# ---------- 用例 B：p1_fail_all → 耗尽降级，DONE，degraded=True，含 degrade 事件 ----------
echo "==> 用例 B  chaos=p1_fail_all"
"$PY" -m paper_agent.cli run-all --goal "garnet solid electrolyte" \
      --chaos p1_fail_all > "$T/B.json" 2> "$T/B.err"
B_RID="$(jfield "$T/B.json" "d['run_id']")"
B_OK="$(jfield "$T/B.json" "1 if d['run_status']=='DONE' and d['degraded']==True else 0")"
B_DEG="$(grep -c '"type": "degrade"' "$PAPER_AGENT_ROOT/runs/$B_RID/events.jsonl" 2>/dev/null || echo 0)"
[ "$B_OK" = "1" ] && ok "B: run DONE & degraded=True" || bad "B: expected DONE/degraded, got $B_OK"
[ "$B_DEG" -ge 1 ] && ok "B: degrade event present" || bad "B: no degrade event"

# ---------- 用例 C：P2 后中断，resume 只跑剩余，已 DONE 步骤复用 ----------
echo "==> 用例 C  P2 后中断 resume"
"$PY" -m paper_agent.cli plan --goal "argyrodite conductivity ranking" > "$T/Cplan.json" 2>/dev/null
C_RID="$(jfield "$T/Cplan.json" "d['run_id']")"
"$PY" -m paper_agent.cli run-step --run "$C_RID" --step P1_lit_search > /dev/null 2>&1
"$PY" -m paper_agent.cli run-step --run "$C_RID" --step P2_clean_data > /dev/null 2>&1
# 模拟 P2 后进程被杀：P3/P4/P5 仍 PENDING；resume 只跑剩余
"$PY" -m paper_agent.cli resume --run "$C_RID" > "$T/C.json" 2> "$T/C.err"
C_OK="$(jfield "$T/C.json" "1 if d['run_status']=='DONE' else 0")"
C_REUSE="$(jfield "$T/C.json" "1 if d['results']['P1_lit_search'].get('reused') and d['results']['P2_clean_data'].get('reused') else 0")"
[ "$C_OK" = "1" ] && ok "C: resume completes remaining steps to DONE" || bad "C: resume not DONE"
[ "$C_REUSE" = "1" ] && ok "C: P1/P2 (DONE) reused, only P3-P5 executed" || bad "C: P1/P2 not reused"

# ---------- 用例 D：mutate_summary → P4 FAIL，run FAILED，5 项校验可查 ----------
echo "==> 用例 D  chaos=mutate_summary"
"$PY" -m paper_agent.cli run-all --goal "sulfide ranking" \
      --chaos mutate_summary > "$T/D.json" 2> "$T/D.err"
D_OK="$(jfield "$T/D.json" "1 if d['run_status']=='FAILED' and d['results']['P4_verify']['status']=='FAIL' else 0")"
D_CHECKS="$(jfield "$T/D.json" "len(d['results']['P4_verify']['checks'])")"
[ "$D_OK" = "1" ] && ok "D: P4 FAIL & top run FAILED" || bad "D: expected P4 FAIL / run FAILED"
[ "$D_CHECKS" = "5" ] && ok "D: all 5 verification checks viewable" || bad "D: expected 5 checks, got $D_CHECKS"

echo "----------------------------------------"
echo "DEMO_FAILURE: $pass passed, $fail failed"
if [ "$fail" = "0" ]; then echo "DEMO_FAILURE_OK"; else echo "DEMO_FAILURE_FAIL"; exit 1; fi
