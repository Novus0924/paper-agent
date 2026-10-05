#!/usr/bin/env bash
# build_audit_pack.sh <RUN_ID> — 归集一个 run 实例的审计交付包
# 用法：bash audit-pack-template/build_audit_pack.sh <RUN_ID> [OUT_DIR]
set -euo pipefail

RUN_ID="${1:?usage: build_audit_pack.sh <RUN_ID> [OUT_DIR]}"
cd "$(dirname "$0")/.."
OUT="${2:-audit-pack}"

if [ ! -d "runs/$RUN_ID" ]; then
  echo "error: runs/$RUN_ID not found" >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"

copy(){ [ -f "$1" ] && cp "$1" "$OUT/$(basename "$1")" || echo "  (skip) missing $1"; }

copy "runs/$RUN_ID/state.json"
copy "runs/$RUN_ID/events.jsonl"
copy "runs/$RUN_ID/provenance.jsonl"
copy "runs/$RUN_ID/conclusions.jsonl"
# ⚠️ verification/verification.json 只有 **materials** 工作流会产出；
#    research 的 R4_verify 结果落在 toolcalls/ 与 events.jsonl 里。
#    所以传 research 的 run id 时这行会 (skip)，属正常，不是脚本坏了。
copy "runs/$RUN_ID/verification/verification.json"
copy "runs/$RUN_ID/report.md"
copy "HOW-TO-VERIFY.md"

# AGH 会话记录（导出于 evidence/；真实 daemon 会话的 tool/call+tool/result 全量账本）
#
# ⚠️ 不要硬编码文件名：证据文件按会话 id 命名（session-<id>.jsonl），
#    换一次导出就换名。硬编码会让审计包**静默漏掉证据**——
#    2026-10-05 就踩过：脚本里写的 session.jsonl / session-full.jsonl
#    早已不存在，新导出的 session-6139563e.jsonl 拷不进来。
#    改为通配 + 有则拷、无则明确提示。
FOUND_SESSION=0
for f in evidence/session-*.jsonl; do
  if [ -f "$f" ]; then
    cp "$f" "$OUT/$(basename "$f")" && echo "  (session) $f"
    FOUND_SESSION=1
  fi
done
if [ "$FOUND_SESSION" -eq 0 ]; then
  echo "  ⚠️ 警告：evidence/session-*.jsonl 一个都没有，审计包将缺少 AGH 会话证据。"
  echo "     生成方式见 evidence/README.md「复现方法」（export 不需要 TTY，会话 id 可查 sqlite）。"
fi
# 复核脚本一并带上，便于收件人核对证据真伪
[ -f "evidence/verify_export.py" ] && cp "evidence/verify_export.py" "$OUT/" && echo "  (tool) evidence/verify_export.py"

echo "AUDIT_PACK_OK -> $OUT/"
ls -1 "$OUT"
