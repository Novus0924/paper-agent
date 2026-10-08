#!/usr/bin/env bash
# demo-kit/lib/report.sh — 共享体检打印与汇总（被 health-check / bootstrap source）
# ============================================================
# 统一 ✓/⚠/✗ 前缀 + 人话修复指引 + 末尾汇总行（规划 B2-1）。
# 所有函数都保证返回 0（即便 detail/fix 为空），以便在 `set -e` 下安全调用。
# 零第三方依赖。

[ -n "${PA_REPORT_SOURCED:-}" ] && return 0
PA_REPORT_SOURCED=1

# 计数器（调用方在开头重置：pa_reset_counts）
PA_N_TOTAL=0
PA_N_OK=0
PA_N_WARN=0
PA_N_FAIL=0

pa_reset_counts() { PA_N_TOTAL=0; PA_N_OK=0; PA_N_WARN=0; PA_N_FAIL=0; }

pa_banner() { printf '== %s ==\n' "$*"; }

# check_ok <name> [detail]
check_ok() {
  local name="$1" detail="${2:-}"
  PA_N_TOTAL=$((PA_N_TOTAL + 1)); PA_N_OK=$((PA_N_OK + 1))
  printf '  \342\234\223 %s\n' "$name"
  if [ -n "$detail" ]; then printf '      %s\n' "$detail"; fi
  return 0
}

# check_warn <name> [detail] [fix]
check_warn() {
  local name="$1" detail="${2:-}" fix="${3:-}"
  PA_N_TOTAL=$((PA_N_TOTAL + 1)); PA_N_WARN=$((PA_N_WARN + 1))
  printf '  \342\232\240\357\270\217 %s\n' "$name"
  if [ -n "$detail" ]; then printf '      %s\n' "$detail"; fi
  if [ -n "$fix" ]; then printf '      \342\236\241\357\270\217 修复：%s\n' "$fix"; fi
  return 0
}

# check_fail <name> [detail] [fix]
check_fail() {
  local name="$1" detail="${2:-}" fix="${3:-}"
  PA_N_TOTAL=$((PA_N_TOTAL + 1)); PA_N_FAIL=$((PA_N_FAIL + 1))
  printf '  \342\234\227 %s\n' "$name"
  if [ -n "$detail" ]; then printf '      %s\n' "$detail"; fi
  if [ -n "$fix" ]; then printf '      \342\236\241\357\270\217 修复：%s\n' "$fix"; fi
  return 0
}

# 汇总行 + 通过退出码语义：0=全绿 / 2=有⚠ / 1=有✗（规划 B2-2）
pa_summary() {
  printf '\n-- 汇总：%d 项，✓%d  ⚠%d  ✗%d --\n' \
    "$PA_N_TOTAL" "$PA_N_OK" "$PA_N_WARN" "$PA_N_FAIL"
  if [ "$PA_N_FAIL" -gt 0 ]; then
    printf '结论：存在阻断项（✗），请按上方「修复」处理后重跑。\n'
    return 1
  fi
  if [ "$PA_N_WARN" -gt 0 ]; then
    printf '结论：无阻断项，但存在警告（⚠）——多数情况可继续（演示/自检会自行规避）。\n'
    return 2
  fi
  printf '结论：环境健康，可直接演示。\n'
  return 0
}
