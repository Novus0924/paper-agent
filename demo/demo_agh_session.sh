#!/usr/bin/env bash
# demo/demo_agh_session.sh — AGH 真实会话联调（触发 7 个科研工具，导出 session.jsonl）
#
# 运行环境：
#   - AGH 源码已构建：packages/cli/dist/local/agnes.mjs（见 docs/guide/install.md）
#   - provider 已配置且可用（doctor provider --probe ✓）
#   - 需要交互式 TTY（AGH 安装走安全确认，non-TTY 会取消）
#
# 红线边界（遵守"只操作项目目录"）：
#   - paper-agent 交付物全部收敛在本项目内：
#       * 插件源码  file:./plugins/paper-agent-tools  （相对路径，绝不外拷）
#       * 会话导出  evidence/session.jsonl           （-o 指到项目内）
#       * 审计包    audit-pack/                       （build_audit_pack.sh 归集）
#   - AGH 框架自身运行时使用其默认 home（~/.agh）：这是框架自带的运行时状态
#     （类比 node_modules / Python site-packages），不属于 paper-agent 的交付物。
#     若需彻底不触碰 ~/.agh，见文末"完全离线交付"说明。

set -uo pipefail
cd "$(dirname "$0")/.."

# AGH 入口（源码构建产物；可用 AGH_ENTRY 覆盖）
AGH_ENTRY="${AGH_ENTRY:-C:\Users\ASUS\Desktop\黑客松\agnes-harness\packages\cli\dist\local\agnes.mjs}"
AGH_ENTRY="${AGH_ENTRY//\\//}"   # Windows 反斜杠 → 正斜杠
AGH() { node "$AGH_ENTRY" "$@"; }

# 工具调用时插件 spawn Python 用的环境变量（paper-agent 核心在项目内）
export "paper-agent_PYTHON=python"
export "paper-agent_ROOT=$PWD"

echo "==> [1/6] inspect 插件源（只读校验，验证 file:./ 源合法并取 integrity）"
AGH package inspect "file:./plugins/paper-agent-tools"

echo "==> [2/6] 安装插件（交互确认 y；写 AGH home 的 package store）"
AGH install "file:./plugins/paper-agent-tools"
# 若安装后 desired=installed-disabled，进入下一步

echo "==> [3/6] 信任插件（从 inspect/preview 取 integrity 与 capabilityHash 填入）"
# trust <package-id> <integrity> <capabilityHash>
#   integrity       = 上一步 preview 的 integrity（形如 sha256-...）
#   capabilityHash  = preview 的 capabilityHash（64 位十六进制）
# 例如：
# AGH package trust "paper-agent-tools" "<INTEGRITY>" "<CAPABILITY_HASH>"
read -r -p "输入 INTEGRITY（preview 的 integrity）: " INTEGRITY
read -r -p "输入 CAPABILITY_HASH（preview 的 capabilityHash）: " CAP_HASH
[ -n "${INTEGRITY:-}" ] && AGH package trust "paper-agent-tools" "$INTEGRITY" "$CAP_HASH" \
  || echo "  (跳过 trust)"

echo "==> [4/6] 启用插件（daemon 加载并注册 7 工具）"
AGH package enable "paper-agent-tools"

echo "==> [5/6] 发起科研会话（触发 sciret_plan/run_step/verify/report/cite/resume/status）"
AGH -p --cwd "$PWD" \
  "请使用科研流水线工具：sciret_plan 规划一个'硫化物固态电解质电导率排序'任务并返回 run_id；" \
  "然后 sciret_run_step 依次执行 P1 到 P5；sciret_verify 复现验证；sciret_report 生成报告；" \
  "sciret_cite 回查一条文献证据；sciret_status 查看最终状态。全程用工具完成并给出结论。"
# 记 SESSION_ID（agnes -p 结束会打印 session id；或用 sessions 列表取最新）
read -r -p "输入 SESSION_ID： " SESSION_ID

echo "==> [6/6] 导出会话到项目内 + 归集审计包"
AGH export "$SESSION_ID" --format agnes -o "$PWD/evidence/session.jsonl"
# 取最新 run id（会话内 sciret_plan 产生；或从 runs/ 取最新目录）
RUN_ID="$(ls -1 "$PWD/runs" 2>/dev/null | sort | tail -1)"
[ -n "${RUN_ID:-}" ] && bash audit-pack-template/build_audit_pack.sh "$RUN_ID" || echo "  (无 run 产物，跳过审计包)"

# 验收：session.jsonl 至少 6 条 tool_use / tool_result
echo "--- 验收 ---"
COUNT=$(grep -c '"tool_use"\|"tool_result"' "$PWD/evidence/session.jsonl" 2>/dev/null || echo 0)
echo "tool_use/tool_result 记录数: $COUNT  (验收要求 >=6)"
[ "$COUNT" -ge 6 ] && echo "AGH_SESSION_OK" || echo "AGH_SESSION_BELOW_THRESHOLD"

# ---------------------------------------------------------------------------
# 完全离线交付（不触碰 AGH home）：
#   本脚本第 2/4 步（install/enable）与第 5 步（-p 会话）需要 AGH 框架运行时
#   与其默认 home（~/.agh）参与——这是 AGH 的安全设计（安装需交互确认）+ 框架
#   运行时状态（daemon/credential store），无法收敛到单一项目目录。
#   若验收环境不允许写 ~/.agh，则交付策略为：
#     1) paper-agent 全部代码/单测/demo/审计脚本（已在本仓）
#     2) 本脚本 demo_agh_session.sh（可在具备 AGH 运行时的目标环境执行）
#     3) evidence/session.jsonl 由目标环境生成后回填至 evidence/ 再打包
# ---------------------------------------------------------------------------
