#!/usr/bin/env bash
# demo-kit/demo-script.sh — 3 分钟现场演示总控
# ============================================================
# 用法：
#   bash demo-kit/demo-script.sh            # 默认 --offline（假数据/回放，剥离一切外部实时依赖）
#   bash demo-kit/demo-script.sh --live     # 叠加真后端（加分模式，仅断网时不可用）
#   bash demo-kit/demo-script.sh --stop     # 停止服务
#
# 目标：现场演示**零隐性依赖** —— 默认走假数据/回放：
#   · 不起 AGH 实时会话（避免模型/代理/TTY 确认的不确定性）
#   · 不起真后端（避免网络检索的不确定性）
#   · 只起本地静态服务 → 打开即可演示
# 会话回放数据：fixtures/session-replay.jsonl（从真实 AGH 会话裁剪，覆盖 7 工具）。
#
# 退出码：0=已就绪 / 非 0=阻断（透传 bootstrap 退出码）。
# 兼容：Git Bash / WSL / macOS / Linux。零第三方依赖。

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/env.sh
source "$KIT_DIR/lib/env.sh"

usage() { sed -n '2,16p' "$0"; }

MODE="offline"
DO_STOP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --offline) MODE="offline" ;;
    --live)    MODE="live" ;;
    --stop)    DO_STOP=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf '未知参数：%s\n\n' "$1" >&2; usage; exit 1 ;;
  esac
  shift
done

FIXTURE="$KIT_DIR/fixtures/session-replay.jsonl"

# ---- 回放数据自检（每行必须可 JSON.parse；供演示时"心里有数"）----
fixture_report() {
  if [ ! -f "$FIXTURE" ]; then
    printf '  ⚠️ 回放数据缺失：%s\n' "$FIXTURE"; return 0
  fi
  env "PYTHONPATH=$PA_REPO_ROOT/core" "$PA_PY" - "$FIXTURE" <<'PY'
import json, sys
bad = 0; n = 0; tools = set()
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    n += 1
    try:
        d = json.loads(line)
    except Exception:
        bad += 1
        continue
    if d.get("type") == "tool/call":
        tools.add((d.get("data") or {}).get("name"))
print("  ✓ 回放数据 %d 行，JSON 解析失败 %d，覆盖工具：%s"
      % (n, bad, ", ".join(sorted(t for t in tools if t))))
PY
}

# ---- --stop ----
if [ "$DO_STOP" = 1 ]; then
  bash "$KIT_DIR/bootstrap.sh" --stop
  exit $?
fi

# ---- 起服务（复用 bootstrap，保证"先自检→再起服务"同一口径）----
if [ "$MODE" = "offline" ]; then
  bash "$KIT_DIR/bootstrap.sh" --mode mock
  RC=$?
else
  bash "$KIT_DIR/bootstrap.sh" --mode live
  RC=$?
fi
[ "$RC" = 0 ] || exit "$RC"

printf '\n'
printf '════════════════════════════════════════════════════════════\n'
printf ' paper-agent 2.0 · 3 分钟演示主线（%s）\n' "$MODE"
printf '════════════════════════════════════════════════════════════\n'
printf ' 点击路径（自上而下走一遍）：\n'
printf '   ① 总览        —— 任务列表 / 信任卡（哈希链已登记）\n'
printf '   ② 新建任务    —— 填目标 → 选工作流(local 源) → 预览系统提示词 → 创建\n'
printf '   ③ 监控        —— 步骤条实时推进；工具卡逐条出现；SSE 实时事件\n'
printf '   ④ 证据        —— provenance 账本 / 结论—证据回查 / tier·kind 标签\n'
printf '   ⑤ 报告        —— 生成报告正文并可导出\n'
printf '   ⑥ 文献        —— 检索结果 / 证据图\n'
printf '   ⑦ 环境体检    —— 即 health-check 的界面化（✓/⚠/✗）\n'
printf '   ⑧ AGH 集成    —— 用回放数据演示 7 工具调用（替代实时会话）\n'
printf '   ⑨ 故障演练    —— chaos 用例：失败→重试→降级 的人话叙事\n'
printf '\n'
printf ' 讲点（务必点到）：\n'
printf '   · 工具名一律为真实 sciret_run_step / sciret_verify / sciret_report（无幻觉名）\n'
printf '   · 降级(degraded)是【橙色·任务未中断】，不是失败——这是特色不是 bug\n'
printf '   · 证据链哈希在生成报告时被校验；篡改会被当场拒绝\n'
printf '   · 结论每条都标来源编号（EV-xxxx），可一键回查\n'
printf '\n'
printf ' 会话回放：\n'
fixture_report
printf '   · 路径：%s\n' "$FIXTURE"
printf '   · 在「AGH 集成」视图选择该文件即可回放（无需 AGH 实时会话）\n'
printf '\n'
printf ' 断网也能演示：offline 模式不触网；live 模式才需要网络。\n'
printf ' 停止服务：bash demo-kit/demo-script.sh --stop\n'
printf '════════════════════════════════════════════════════════════\n'
exit 0
