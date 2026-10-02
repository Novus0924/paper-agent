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
copy "runs/$RUN_ID/verification/verification.json"
copy "runs/$RUN_ID/report.md"
copy "HOW-TO-VERIFY.md"

# AGH 会话记录（导出于 evidence/；真实 daemon 会话的 tool/call+tool/result 全量账本）
for f in evidence/session.jsonl evidence/session-full.jsonl; do
  [ -f "$f" ] && cp "$f" "$OUT/$(basename "$f")" && echo "  (session) $f"
done
[ -f "session.jsonl" ] && cp "session.jsonl" "$OUT/agh-session.jsonl"

echo "AUDIT_PACK_OK -> $OUT/"
ls -1 "$OUT"
