#!/usr/bin/env bash
# demo/demo_research.sh — 科研全流程（R1..R6）一键演示 + 判断留痕硬前置演示
# 用法：cd 到项目根目录后执行  bash demo/demo_research.sh
# 说明：需要 bash + sha256sum（Windows 用 Git Bash / WSL）；--lit-source local 全程离线

set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/core"
export PAPER_AGENT_ROOT="$PWD"
# 强制 Python stdin/stdout/stderr 为 UTF-8，避免管道读 JSON 时按系统码页(cp936)解码中文路径失败
export PYTHONIOENCODING="utf-8"
PY="$(printenv paper-agent_PYTHON || echo python)"
TMPJSON="$(mktemp)"
trap 'rm -f "$TMPJSON"' EXIT

echo "==> [1/4] plan + run-all（research 工作流 R1..R6，离线 local 语料）"
PLAN_JSON=$("$PY" -m paper_agent.cli plan --workflow research --lit-source local \
    --goal "solid-state electrolyte ionic conductivity review")
echo "$PLAN_JSON"
RUN_ID=$(printf '%s' "$PLAN_JSON" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['run_id'])")
echo "RUN_ID=$RUN_ID"

"$PY" -m paper_agent.cli run-all --run "$RUN_ID" > "$TMPJSON"
"$PY" - "$TMPJSON" <<'PY'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["ok"] is True, f"run-all not DONE: {d['run_status']}"
assert d["degraded"] is False, "unexpected degraded on local path"
print("  R1..R6 DONE, degraded=False  ->", d["run_id"])
PY

echo "==> [2/4] 判断留痕审计（query_generation / relevance）"
"$PY" - "$RUN_ID" <<'PY'
import sys, json, os
run_id = sys.argv[1]
path = os.path.join(os.environ["PAPER_AGENT_ROOT"], "runs", run_id, "provenance.jsonl")
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
js = [r for r in recs if r.get("tier") == "judgment"]
assert js, "ledger has no judgment records (judging traceability broken)"
qg = [j for j in js if j["kind"] == "query_generation"]
rel = [j for j in js if j["kind"] == "relevance"]
exc = [j for j in rel if j["meta"].get("verdict") == "excluded"]
assert qg and qg[0]["meta"]["verdict"] == "generated", "R1 query judgment missing"
for j in rel:
    assert j["meta"].get("rationale"), "relevance judgment without rationale (not reviewable)"
print(f"  query_generation = {len(qg)}  (subject: {qg[0]['ref']})")
print(f"  relevance total  = {len(rel)}  selected={len(rel)-len(exc)}  excluded={len(exc)}")
for j in exc:
    print(f"    [excluded] {j['ref']}  <-  {j['meta']['rationale']}")
print("  JUDGMENT AUDIT: PASS")
PY

echo "==> [3/4] 判据4 硬前置演示：删除判断记录 → 报告生成必须失败"
TAMPER_ID="${RUN_ID}-tampered"
TAMPER_DIR="$PAPER_AGENT_ROOT/runs/$TAMPER_ID"
rm -rf "$TAMPER_DIR"
cp -r "$PAPER_AGENT_ROOT/runs/$RUN_ID" "$TAMPER_DIR"
"$PY" - "$TAMPER_DIR" <<'PY'
import sys, json, os
d = sys.argv[1]
path = os.path.join(d, "provenance.jsonl")
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
kept = [r for r in recs if r.get("tier") != "judgment"]
with open(path, "w", encoding="utf-8", newline="") as f:
    for r in kept:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
print(f"  stripped {len(recs)-len(kept)} judgment records from copy run {os.path.basename(d)}")
PY
RC=0
"$PY" -m paper_agent.cli report --run "$TAMPER_ID" > "$TMPJSON" 2>&1 || RC=$?
if [ "$RC" -eq 0 ]; then
    echo "  JUDGE-GATE: FAIL — report generated without judgments!"; exit 1
fi
echo "  report exit=$RC (refused, as required)"
"$PY" - "$TMPJSON" <<'PY'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d.get("ok") is False, "expected ok=false on refused report"
print("  refused reason:", d.get("error", "")[:120])
PY
rm -rf "$TAMPER_DIR"
echo "  JUDGE-GATE: PASS (tampered copy cleaned)"

echo "==> [4/4] 报告摘要"
"$PY" - "$PAPER_AGENT_ROOT/runs/$RUN_ID/report.md" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
lines = text.splitlines()
# 只打印头部与结论段，避免刷屏
for ln in lines:
    if ln.startswith("## 科研结论"):
        idx = lines.index(ln)
        print("\n".join(lines[:idx + 8])); print("  ...（证据索引表与复现命令见完整报告）")
        break
else:
    print(text[:800])
PY
echo "DEMO_RESEARCH_OK  RUN=$RUN_ID"
