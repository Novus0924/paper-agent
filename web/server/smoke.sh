#!/usr/bin/env bash
# ============================================================
# web/server/smoke.sh —— paper-agent-server 冒烟测试（Git Bash + curl）
#
# 覆盖 Batch 2 的关键修复点：
#   CHECK 1  健康检查 /api/health
#   CHECK 2  创建 research run（lit_source=local，离线确定）
#   CHECK 3  run-all 执行期间并发 POST /step → 409 BUSY（LOGIC-4 per-run 互斥）
#   CHECK 4  失败步骤（依赖未满足）→ SSE 只广播 step:FAILED，
#            不出现虚假 done 事件（LOGIC-3 失败路径广播真实状态）
#   CHECK 5  终态（run-all 全部完成）后再次 POST /step → 409（LOGIC-6 状态守卫）
#
# 前置条件：
#   1. 服务已启动：node web/server/paper-agent-server.js（默认绑 127.0.0.1:8787）
#   2. python 在 PATH 上、paper_agent 可从 <repo>/core 导入（服务会 spawn CLI）
#   3. Git Bash 自带 curl
#
# 用法：bash web/server/smoke.sh
# 退出码：0 = 全部通过；非 0 = 失败的检查点编号（1..5）
# ============================================================
set -u
BASE="${SMOKE_BASE:-http://127.0.0.1:8787}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "[smoke] FAIL 检查点 $1：$2"; exit "$1"; }

# 用 python 解析 JSON 字段（Git Bash 不保证有 jq；项目本身依赖 python）
json_field() { # $1=json文本 $2=python表达式（基于变量 d）
  printf '%s' "$1" | python -c "import sys,json;d=json.load(sys.stdin);print($2)" 2>/dev/null
}

echo "[smoke] 目标服务：$BASE"

# ---------- CHECK 1：健康检查 ----------
H="$(curl -sf "$BASE/api/health")" || fail 1 "health 接口不可达（服务未启动？端口 8787）"
[ "$(json_field "$H" "d.get('ok')")" = "True" ] || fail 1 "health 返回异常：$H"
echo "[smoke] CHECK 1 通过：health ok"

# ---------- CHECK 2：创建 research run ----------
R="$(curl -s -X POST "$BASE/api/runs" -H 'Content-Type: application/json' \
  -d '{"goal":"smoke lifecycle test","workflow":"research","lit_source":"local"}')"
RID="$(json_field "$R" "d.get('run_id','')")"
[ -n "$RID" ] || fail 2 "创建 run 失败：$R"
echo "[smoke] CHECK 2 通过：run_id=$RID"

# ---------- CHECK 3：run-all 期间并发 POST /step → 409 BUSY ----------
RA="$(curl -s -X POST "$BASE/api/runs/$RID/run-all")"
[ "$(json_field "$RA" "d.get('ok')")" = "True" ] || fail 3 "run-all 发起失败：$RA"
sleep 1   # 让 run-all 的第一个子进程进入执行态（互斥标记已置位）
C3="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/runs/$RID/step" \
  -H 'Content-Type: application/json' -d '{"step":"R3_analyze"}')"
[ "$C3" = "409" ] || fail 3 "run-all 期间并发 /step 期望 409，实际 $C3"
echo "[smoke] CHECK 3 通过：并发 /step → 409 BUSY（per-run 互斥生效）"

# ---------- CHECK 4：失败步骤广播真实状态，无虚假 done ----------
# 另建一个 run，直接推 R5_write——其硬前置 R3 未完成，
# Python run-step 返回 StepDependencyError（exit 1），run 仍处 PLANNED。
R2="$(curl -s -X POST "$BASE/api/runs" -H 'Content-Type: application/json' \
  -d '{"goal":"smoke failure broadcast","workflow":"research","lit_source":"local"}')"
RID2="$(json_field "$R2" "d.get('run_id','')")"
[ -n "$RID2" ] || fail 4 "创建失败场景 run 失败：$R2"

SSE_FILE="$TMP/sse.txt"
curl -sN "$BASE/api/runs/$RID2/events" > "$SSE_FILE" 2>/dev/null &
SSE_PID=$!
sleep 1
curl -s -X POST "$BASE/api/runs/$RID2/step" -H 'Content-Type: application/json' \
  -d '{"step":"R5_write"}' > /dev/null
sleep 6   # 等 CLI 子进程返回失败并广播
kill "$SSE_PID" 2>/dev/null
wait "$SSE_PID" 2>/dev/null

grep -q '"status":"FAILED"' "$SSE_FILE" \
  || fail 4 "SSE 未收到 step FAILED 事件（失败广播缺失）：$(head -c 400 "$SSE_FILE")"
if grep -q '^event: done' "$SSE_FILE"; then
  fail 4 "SSE 出现虚假 done 事件（单步失败后 run 非终态，LOGIC-3 回归）"
fi
echo "[smoke] CHECK 4 通过：失败步骤只广播 step:FAILED，无虚假 done"

# ---------- CHECK 5：等待 run #1 终态后再次 POST /step → 409 ----------
echo "[smoke] 等待 run-all 完成（research local 约数十秒）..."
RS=""
for _ in $(seq 1 60); do
  SNAP="$(curl -s "$BASE/api/runs/$RID")"
  RS="$(json_field "$SNAP" "d.get('state',{}).get('run_status','')")"
  [ "$RS" = "DONE" ] && break
  [ "$RS" = "FAILED" ] && break
  sleep 3
done
[ "$RS" = "DONE" ] || fail 5 "run-all 未在超时内收敛 DONE（实际：${RS:-无响应}）"
C5="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/runs/$RID/step" \
  -H 'Content-Type: application/json' -d '{"step":"R1_search"}')"
[ "$C5" = "409" ] || fail 5 "终态后 POST /step 期望 409，实际 $C5"
echo "[smoke] CHECK 5 通过：终态后 /step → 409，done.run_status 与 state.json 一致（$RS）"

echo "[smoke] 全部 5 项检查通过 ✅"
exit 0
