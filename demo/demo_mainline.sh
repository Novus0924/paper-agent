#!/usr/bin/env bash
# demo/demo_mainline.sh — 真实数据主线的离线回放演示（无需联网 / 无需 key / 无第三方依赖）
#
# 演示内容（对应 docs/redesign-decisions.md 的判据 1 / 4 / 5）：
#   [1] 快照强校验：逐文件重算 SHA-256 + 聚合内容哈希
#   [2] 真实数据全链路：599 行进 → 562 行可用 → 实测电导率排序 → P4 PASS
#   [3] 确定性：两次独立运行的 results.csv 逐字节一致
#   [4] 判据 4：删掉快照的判断记录 → 报告不再可生成（run FAILED）；恢复后重新通过
#   [5] 判断留痕：被排除项与理由可查（含被排除的家族）
#   [6] 证据回查：fact 级与 judgment 级各回查一条
#
# 用法：bash demo/demo_mainline.sh
# 说明：需要 bash + sha256sum（Windows 用 Git Bash）；快照已在仓库内，无需联网。

set -uo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/core"
export PAPER_AGENT_ROOT="$PWD"
export PYTHONIOENCODING="utf-8"
# 本脚本演示**快照主线**：显式不设置 PAPER_AGENT_SNAPSHOT（默认取最新快照）
unset PAPER_AGENT_SNAPSHOT || true

PY="$(printenv paper-agent_PYTHON || echo python)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok(){ echo "  [PASS] $1"; pass=$((pass+1)); }
bad(){ echo "  [FAIL] $1"; fail=$((fail+1)); }

jfield(){
  "$PY" - "$1" "$2" <<'PY'
import sys, json, builtins
d = json.load(open(sys.argv[1], encoding="utf-8"))
g = {"__builtins__": builtins, "d": d, "len": len}
print(eval(sys.argv[2], g, g))
PY
}

SNAP_DIR="$(ls -d snapshots/snap-* 2>/dev/null | sort | tail -1)"
SNAP_ID="$(basename "${SNAP_DIR:-missing}")"
echo "==> 使用快照: $SNAP_ID"

# ---------- [1] 快照强校验 ----------
echo "==> [1/6] 快照强校验（逐文件 SHA-256 + 聚合内容哈希）"
"$PY" - "$SNAP_ID" <<'PY' > "$T/verify.json"
import sys, json
sys.path.insert(0, "core")
from paper_agent import snapshot as S
snap = S.Snapshot(".", sys.argv[1])
m = snap.load()
ok, problems = snap.verify()
print(json.dumps({"ok": ok, "problems": problems,
                  "content_sha256": m.get("content_sha256"),
                  "producer": m.get("producer"),
                  "judgments": m.get("judgment_batch", {}).get("count")},
                 ensure_ascii=False))
PY
cat "$T/verify.json"
[ "$(jfield "$T/verify.json" "1 if d['ok'] else 0")" = "1" ] \
  && ok "快照校验通过（内容哈希 $(jfield "$T/verify.json" "d['content_sha256'][:16]")…）" \
  || bad "快照校验失败"

# ---------- [2] 真实数据全链路 ----------
echo "==> [2/6] 真实数据全链路（599 → 562 → 排序 → 复现验证）"
"$PY" -m paper_agent.cli run-all \
      --goal "sulfide solid electrolyte ionic conductivity ranking" \
      > "$T/run1.json" 2>"$T/run1.err"
R1="$(jfield "$T/run1.json" "d.get('run_id','')")"
echo "  RUN1=$R1"
[ "$(jfield "$T/run1.json" "1 if d['run_status']=='DONE' and d['degraded']==False else 0")" = "1" ] \
  && ok "run DONE 且 degraded=False" || bad "run 未 DONE"
[ "$(jfield "$T/run1.json" "1 if d['results']['P4_verify']['status']=='PASS' else 0")" = "1" ] \
  && ok "P4 复现验证 PASS（5 项校验）" || bad "P4 未 PASS"
[ "$(jfield "$T/run1.json" "d['results']['P2_clean_data'].get('input_rows')")" = "599" ] \
  && ok "P2 输入 599 行（真实数据集全量）" || bad "P2 输入行数异常"
[ "$(jfield "$T/run1.json" "d['results']['P2_clean_data'].get('output_rows')")" = "562" ] \
  && ok "P2 输出 562 行可用（37 行上界值已排除并留证）" || bad "P2 输出行数异常"
[ "$(jfield "$T/run1.json" "d['results']['P2_clean_data'].get('excluded_rows')")" = "37" ] \
  && ok "排除 37 行上界值（excluded_rows.json 留证）" || bad "排除行数异常"
[ "$(jfield "$T/run1.json" "1 if d['results']['P1_lit_search'].get('n_hits')==223 else 0")" = "1" ] \
  && ok "文献腿 223 个真实 DOI" || bad "文献腿 DOI 数异常"

# ---------- [3] 确定性 ----------
echo "==> [3/6] 确定性：两次独立运行的 results.csv 必须逐字节一致"
"$PY" -m paper_agent.cli run-all \
      --goal "sulfide solid electrolyte ionic conductivity ranking" \
      > "$T/run2.json" 2>/dev/null
R2="$(jfield "$T/run2.json" "d.get('run_id','')")"
echo "  RUN2=$R2"
A="$(sha256sum "$PAPER_AGENT_ROOT/runs/$R1/experiment/results/results.csv" | cut -d' ' -f1)"
B="$(sha256sum "$PAPER_AGENT_ROOT/runs/$R2/experiment/results/results.csv" | cut -d' ' -f1)"
echo "  A=$A"
echo "  B=$B"
[ "$A" = "$B" ] && ok "两次运行逐字节一致（562 行排序结果）" \
                || bad "两次运行结果不一致"

# ---------- [4] 判据 4：判断记录是报告生成的硬前置 ----------
echo "==> [4/6] 判据 4：删掉快照判断记录后，报告必须无法生成"
cp "$SNAP_DIR/judgments.jsonl" "$T/judgments.bak"
rm "$SNAP_DIR/judgments.jsonl"
"$PY" -m paper_agent.cli run-all --goal "sulfide solid electrolyte ranking" \
      > "$T/blocked.json" 2>/dev/null
[ "$(jfield "$T/blocked.json" "1 if d['run_status']=='FAILED' else 0")" = "1" ] \
  && ok "删除判断记录 → run FAILED（P1 拒绝继续）" \
  || bad "删除判断记录后竟然还能跑通"
cp "$T/judgments.bak" "$SNAP_DIR/judgments.jsonl"
"$PY" - "$SNAP_ID" <<'PY' > "$T/restored.json"
import sys, json
sys.path.insert(0, "core")
from paper_agent import snapshot as S
ok, problems = S.Snapshot(".", sys.argv[1]).verify()
print(json.dumps({"ok": ok, "problems": problems}, ensure_ascii=False))
PY
[ "$(jfield "$T/restored.json" "1 if d['ok'] else 0")" = "1" ] \
  && ok "恢复判断记录 → 快照校验重新通过" || bad "恢复后校验仍失败"

# ---------- [5] 判断留痕与可反驳性 ----------
echo "==> [5/6] 判断留痕：被排除项与理由可查（筛选可被反驳）"
"$PY" - "$R1" <<'PY' > "$T/judge.json"
import sys, json
sys.path.insert(0, "core")
from paper_agent.provenance import ProvenanceLedger
prov = ProvenanceLedger(f"runs/{sys.argv[1]}", sys.argv[1])
js = prov.judgments()
ex = prov.excluded_judgments()
sample = next((r for r in ex if r["kind"] == "relevance"), None)
print(json.dumps({
    "n_judgments": len(js),
    "n_excluded": len(ex),
    "n_fact": len(prov.facts()),
    "sample_subject": (sample or {}).get("meta", {}).get("subject", ""),
    "sample_reason": (sample or {}).get("meta", {}).get("rationale", ""),
}, ensure_ascii=False))
PY
cat "$T/judge.json"
NJ="$(jfield "$T/judge.json" "d['n_judgments']")"
NE="$(jfield "$T/judge.json" "d['n_excluded']")"
[ "$NJ" -ge 40 ] && ok "判断记录 $NJ 条（含被排除项 $NE 条）" || bad "判断记录数异常"
[ -n "$(jfield "$T/judge.json" "d['sample_reason']")" ] \
  && ok "被排除项带理由：$(jfield "$T/judge.json" "d['sample_subject']") → $(jfield "$T/judge.json" "d['sample_reason']")" \
  || bad "被排除项缺少理由"

# ---------- [6] 证据回查 ----------
echo "==> [6/6] 证据回查（fact 级 / judgment 级）"
# 不硬编码 EV 号：单一编号空间里 fact 与 judgment 交错，动态取首个各一条
"$PY" - "$R1" <<'PY' > "$T/evs.json"
import sys, json
sys.path.insert(0, "core")
from paper_agent.provenance import ProvenanceLedger
prov = ProvenanceLedger(f"runs/{sys.argv[1]}", sys.argv[1])
print(json.dumps({"fact": prov.facts()[0]["ev_id"],
                  "judgment": prov.judgments()[0]["ev_id"]}, ensure_ascii=False))
PY
FACT_EV="$(jfield "$T/evs.json" "d['fact']")"
JUDGE_EV="$(jfield "$T/evs.json" "d['judgment']")"
"$PY" -m paper_agent.cli cite --run "$R1" --ev "$FACT_EV" > "$T/cite1.json" 2>/dev/null
"$PY" -m paper_agent.cli cite --run "$R1" --ev "$JUDGE_EV" > "$T/cite2.json" 2>/dev/null
echo "  fact     ($FACT_EV): $(jfield "$T/cite1.json" "d['citation']")"
echo "  judgment ($JUDGE_EV): $(jfield "$T/cite2.json" "d['citation']")"
[ "$(jfield "$T/cite1.json" "1 if 'judgment' not in d['citation'] and ('sha256=' in d['citation']) else 0")" = "1" ] \
  && ok "fact 级证据可回查（含文件哈希）" || bad "fact 级回查异常"
[ "$(jfield "$T/cite2.json" "1 if 'judgment' in d['citation'] else 0")" = "1" ] \
  && ok "judgment 级证据可回查（含对象与理由）" || bad "judgment 级回查异常"

echo "----------------------------------------"
echo "DEMO_MAINLINE: $pass passed, $fail failed"
if [ "$fail" = "0" ]; then echo "DEMO_MAINLINE_OK"; else echo "DEMO_MAINLINE_FAIL"; exit 1; fi
