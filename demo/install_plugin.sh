#!/usr/bin/env bash
# demo/install_plugin.sh — 把 paper-agent-tools 一键装进 AGH（幂等，可重复运行）
#
# 用法（必须在【真实终端】里跑；Git Bash / macOS / Linux 通用）：
#   bash demo/install_plugin.sh [agnes.mjs 绝对路径]
#   bash demo/install_plugin.sh --check       # 只做环境预检（只读），不安装
#   bash demo/install_plugin.sh --reinstall   # 已装时强制重装（插件源码更新后用）
#
# 本脚本自动完成（无需手工填任何 magic value）：
#   1. 按脚本自身位置定位仓库根（零硬编码路径）
#   2. 探测 AGH 入口（参数 > 环境变量 AGH_ENTRY > 常见克隆位置）
#   3. 探测 node（校验 >= 24）与 python（校验 >= 3.10）
#   4. 用正确环境变量在仓库根重启 daemon（保证 file:./ 解析正确）
#   5. package inspect 自动提取 integrity；从 AGH 审计日志自动提取 capabilityHash
#   6. 安装（真实终端里人工敲 y —— AGH 安全设计，无 bypass）→ trust → enable
#   7. 验证 desired=enabled actual=running trusted=true，并跑插件链路冒烟测试
#
# 背景知识（为什么要这样设计）见 docs/AGH插件安装指南.md 第 1 节「三个机制」。

set -uo pipefail

# ---------- 参数解析 ----------
MODE="install"            # install | check
FORCE=0                   # --reinstall
AGH_ARG=""
for a in "$@"; do
  case "$a" in
    --check)     MODE="check" ;;
    --reinstall) FORCE=1 ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    *)           AGH_ARG="$a" ;;
  esac
done

# ---------- 0) 仓库根：按脚本自身位置定位（无硬编码路径） ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PKG_ID="paper-agent-tools"
PKG_SRC="file:./plugins/paper-agent-tools"

say()  { printf '%s\n' "$*"; }
die()  { printf '❌ %s\n' "$*" >&2; exit 1; }
require_tty() {  # AGH 安装确认只在真实终端有效（无 bypass）
  if ! { [ -t 0 ] && [ -t 1 ]; }; then
    say "❌ 检测到非交互环境（stdin/stdout 不是 TTY），已中止。"
    say "   AGH 的安装确认只在真实终端里接受（安全设计，无任何 bypass）。"
    say "   请在 Windows Terminal / PowerShell / Git Bash / macOS 终端里直接运行："
    say "     bash demo/install_plugin.sh"
    say "   （不要通过管道、重定向或自动化工具运行。）"
    exit 1
  fi
}

# ---------- 2) AGH 入口探测 ----------
to_win_path() {  # MSYS/Git Bash 下把 /d/... 转成 D:/...（node 只认后者）；非 MSYS 原样返回
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

AGH_ENTRY="${AGH_ARG:-${AGH_ENTRY:-}}"
if [ -z "$AGH_ENTRY" ]; then
  for c in \
    "$ROOT/../agnes-harness/packages/cli/dist/local/agnes.mjs" \
    "$HOME/agnes-harness/packages/cli/dist/local/agnes.mjs" \
    "$HOME/agnes-harness-main/packages/cli/dist/local/agnes.mjs" \
    "/c/agnes-harness-main/packages/cli/dist/local/agnes.mjs" \
    "/d/agnes-harness-main/packages/cli/dist/local/agnes.mjs"
  do
    if [ -f "$c" ]; then AGH_ENTRY="$c"; break; fi
  done
fi
[ -n "$AGH_ENTRY" ] || die "找不到 AGH 入口 agnes.mjs。
   三种给法任选其一：
     1) bash demo/install_plugin.sh <agnes.mjs 绝对路径>
     2) export AGH_ENTRY=<agnes.mjs 绝对路径> 后再运行本脚本
     3) 把 agnes-harness 克隆到本仓库旁边（../agnes-harness）或家目录下
   （AGH 是运行底座，需自行从源码构建出 packages/cli/dist/local/agnes.mjs）"
AGH_ENTRY_N="$(to_win_path "$AGH_ENTRY")"
[ -f "$AGH_ENTRY" ] || die "AGH 入口不存在：$AGH_ENTRY"

# ---------- 3) node 探测（必须 >= 24，AGH 硬要求） ----------
NODE_BIN=""
for c in "${AGH_NODE:-}" "$(command -v node 2>/dev/null || true)" \
         "/c/Program Files/nodejs/node.exe"; do
  [ -n "$c" ] || continue
  v="$("$c" -v 2>/dev/null || true)"
  [ -n "$v" ] || continue
  major="${v#v}"; major="${major%%.*}"
  if [ "$major" -ge 24 ] 2>/dev/null; then NODE_BIN="$c"; break; fi
  say "  （跳过 node 候选 $c：版本 $v < 24）"
done
[ -n "$NODE_BIN" ] || die "找不到 node >= 24。
   AGH 运行底座要求 node >= 24（package.json engines 同此要求）。
   请安装 Node 24+ 或用 AGH_NODE=<node 绝对路径> 指定。"

# ---------- 4) python 探测（必须 >= 3.10；零第三方依赖，无需 pip install） ----------
PY_N=""
for c in "$(printenv 'paper-agent_PYTHON' 2>/dev/null || true)" \
         "$(command -v python3 2>/dev/null || true)" \
         "$(command -v python 2>/dev/null || true)"; do
  [ -n "$c" ] || continue
  if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY_N="$(to_win_path "$c")"; break
  fi
done
[ -n "$PY_N" ] || die "找不到 python >= 3.10（python3 或 python 均可）。
   Python 核心零第三方依赖，装好解释器即可，无需 pip install 任何东西。"

ROOT_N="$(to_win_path "$ROOT")"

# ---------- 5) 环境变量策略 + AGH 自检（防个别 Git Bash 的 env→node 静默失败） ----------
HAVE_ROOT="$(printenv 'paper-agent_ROOT' 2>/dev/null || true)"
HAVE_PY="$(printenv 'paper-agent_PYTHON' 2>/dev/null || true)"
if [ -n "$HAVE_ROOT" ] && [ -n "$HAVE_PY" ]; then
  ENV_MODE="继承（直接调 node）"
  run_agh() { "$NODE_BIN" "$AGH_ENTRY_N" "$@"; }
else
  # bash 的 export 写不了带连字符的变量名，只能用 env 前缀注入
  ENV_MODE="env 前缀注入"
  run_agh() {
    env "paper-agent_PYTHON=$PY_N" "paper-agent_ROOT=$ROOT_N" \
        "$NODE_BIN" "$AGH_ENTRY_N" "$@"
  }
fi

say "==> [预检] node    = $("$NODE_BIN" -v 2>&1)（$NODE_BIN）"
say "==> [预检] python  = $PY_N"
say "==> [预检] 仓库根  = $ROOT"
say "==> [预检] AGH 入口 = $AGH_ENTRY_N"
say "==> [预检] 环境变量 = $ENV_MODE"

SELFTEST="$(run_agh --version 2>&1)"
if [ -z "$SELFTEST" ]; then
  die "AGH 入口无任何输出（预期应打印 agh x.x.x ...）。
   这是个别 Git Bash 的 env→node 链路静默失败。解决办法：
   1) PowerShell 执行以下两行把变量持久化到用户账户（路径按你机器改）：
        [Environment]::SetEnvironmentVariable('paper-agent_ROOT',   '<仓库绝对路径>', 'User')
        [Environment]::SetEnvironmentVariable('paper-agent_PYTHON', '<python 绝对路径>', 'User')
   2) 关掉当前终端，【新开一个】再运行 bash demo/install_plugin.sh"
fi
say "==> [预检] AGH 自检 = $SELFTEST"

# ---------- 6) 进入仓库根（daemon 的工作目录决定 file:./ 的解析基准） ----------
cd "$ROOT" || die "无法进入仓库根 $ROOT"

# daemon 状态（只读；daemon 未运行时 AGH 可能自动拉起——这里带着正确环境，无害）
DAEMON_ST="$(run_agh daemon status 2>&1 || true)"
if printf '%s' "$DAEMON_ST" | grep -q '"running" *: *true'; then
  say "==> [预检] daemon  = 已在运行"
else
  say "==> [预检] daemon  = 未运行"
fi

# ---------- --check 模式：到此为止（只读预检），再补一个 inspect 后退出 ----------
if [ "$MODE" = "check" ]; then
  say ""
  say "==> [预检] package inspect（只读）"
  PREVIEW="$(run_agh package inspect "$PKG_SRC" 2>&1)" \
    || { printf '%s\n' "$PREVIEW"; die "inspect 失败：若报 The package source could not be accepted，多为 daemon 工作目录不在仓库根（本脚本已自动 cd，若仍失败请重启本脚本）。"; }
  printf '%s\n' "$PREVIEW"
  say ""
  say "✅ 预检通过：环境就绪，可以安装了 —— bash demo/install_plugin.sh"
  exit 0
fi

# ---------- 7) 安装（幂等：已装好则跳过；--reinstall 强制重来） ----------
STATUS_NOW="$(run_agh package status 2>&1 || true)"
LINE_NOW="$(printf '%s' "$STATUS_NOW" | grep "$PKG_ID" || true)"

if [ -n "$LINE_NOW" ] && [ "$FORCE" -eq 0 ] \
   && printf '%s' "$LINE_NOW" | grep -q 'actual=running' \
   && printf '%s' "$LINE_NOW" | grep -q 'trusted=true'; then
  say ""
  say "✅ 插件已安装且运行中，无需重装："
  say "   $LINE_NOW"
  say "   （若改了插件源码想更新，运行：bash demo/install_plugin.sh --reinstall）"
else
  if [ "$FORCE" -eq 1 ]; then
    say "==> [--reinstall] 先移除旧版本（disable → remove）"
    run_agh package disable "$PKG_ID" >/dev/null 2>&1 || true
    for i in 1 2 3 4 5 6 7 8 9 10; do
      run_agh package remove "$PKG_ID" >/dev/null 2>&1 && break
      sleep 2
    done
  fi

  # daemon：stop 后带正确环境在仓库根重启（环境变量只在启动那一刻注入）
  say "==> [1/5] 重启 daemon（带上环境变量；在仓库根启动）"
  say "        （若你开着 AGH Web 页面 serve，它会被一并停掉，属预期）"
  run_agh daemon stop >/dev/null 2>&1 || true
  sleep 1
  run_agh daemon start >/dev/null 2>&1 || true
  DOK=""
  for i in $(seq 1 30); do
    if run_agh daemon status 2>/dev/null | grep -q '"running" *: *true'; then DOK=1; break; fi
    sleep 1
  done
  [ -n "$DOK" ] || die "daemon 启动失败（30 秒内未进入 running 状态）。
   请手动运行 run_agh daemon status 看报错；常见原因：node 版本 < 24、端口占用。"

  # inspect：取 integrity
  say "==> [2/5] 预检插件源（自动提取 integrity）"
  PREVIEW="$(run_agh package inspect "$PKG_SRC" 2>&1)" \
    || { printf '%s\n' "$PREVIEW"; die "inspect 失败：若报 The package source could not be accepted，多为 daemon 工作目录不在仓库根。"; }
  INTEGRITY="$(printf '%s' "$PREVIEW" | grep -o 'sha256-[0-9a-f]\{64\}' | head -1 || true)"
  [ -n "$INTEGRITY" ] || { printf '%s\n' "$PREVIEW"; die "inspect 输出里没找到 integrity（sha256-...）。请把上面完整输出反馈给维护者。"; }
  say "        integrity = $INTEGRITY"

  # 安装：真实终端里人工确认
  if [ -n "$LINE_NOW" ] && [ "$FORCE" -eq 0 ]; then
    say "==> [3/5] 检测到已安装但未完全启用/信任，跳过 add，直接补 trust + enable"
  else
    require_tty   # ← package add 需要真实终端确认（幂等无操作路径不经过这里）
    say "==> [3/5] 安装插件 —— AGH 将请求确认，请输入 y 后回车"
    run_agh package add "$PKG_SRC" || die "安装未完成。
   若输出 Installation cancelled.：说明确认环节被判为「未确认」——
   本脚本必须在真实终端里运行（不能管道/重定向/自动化），且确认时需输入 y。"
  fi

  # capabilityHash：从 AGH 审计日志自动提取（inspect 不输出它）
  say "==> [4/5] 从审计日志提取 capabilityHash（自动）"
  CAP_HASH="$("$PY_N" - <<'PYEOF'
import glob, json, os
hits = []
for path in glob.glob(os.path.expanduser('~/.agh/profiles/*/.agnes-package-audit.jsonl')):
    try:
        with open(path, encoding='utf-8') as f:
            events = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        continue
    for e in events:
        if e.get('id') == 'paper-agent-tools' and e.get('operation') == 'install':
            nxt = (e.get('capabilityDiff') or {}).get('next')
            if isinstance(nxt, str) and nxt:
                hits.append(nxt)
print(hits[-1] if hits else '')
PYEOF
)"
  [ -n "$CAP_HASH" ] || die "审计日志里没找到 capabilityHash。
   日志位置：~/.agh/profiles/<profile>/.agnes-package-audit.jsonl（install 事件的 capabilityDiff.next）。
   若该文件不存在，说明上面的 package add 实际没有安装成功，请把过程输出发给维护者。"
  say "        capabilityHash = $CAP_HASH"

  # trust + enable
  say "==> [5/5] trust + enable"
  run_agh package trust "$PKG_ID" "$INTEGRITY" "$CAP_HASH" \
    || die "trust 失败。参数：integrity=$INTEGRITY capabilityHash=$CAP_HASH
   若 capabilityHash 报不匹配：审计日志里的 install 事件可能早于本次安装，重跑本脚本通常可自愈。"
  run_agh package enable "$PKG_ID" || die "enable 失败，请把上面输出发给维护者。"
fi

# ---------- 8) 终验：desired=enabled actual=running trusted=true ----------
sleep 2
FINAL="$(run_agh package status 2>&1 || true)"
FLINE="$(printf '%s' "$FINAL" | grep "$PKG_ID" || true)"
printf '%s\n' "$FINAL"
if printf '%s' "$FLINE" | grep -q 'actual=running' && printf '%s' "$FLINE" | grep -q 'trusted=true'; then
  say "✅ package status 验证通过（actual=running trusted=true）"
else
  die "状态未达预期（需要 actual=running 且 trusted=true）。
   若 actual=starting：daemon 可能还在加载，等 10 秒后重跑本脚本（幂等，安全）。
   若 trusted=false：trust 参数问题，重跑本脚本。"
fi

# ---------- 9) 冒烟测试：插件 → Python CLI 链路 ----------
say ""
say "==> 插件链路冒烟测试（tools/verify-plugin-offline.mjs，无需 TTY）"
SMOKE="$(if [ -n "$HAVE_ROOT" ] && [ -n "$HAVE_PY" ]; then
  "$NODE_BIN" tools/verify-plugin-offline.mjs 2>&1
else
  env "paper-agent_PYTHON=$PY_N" "paper-agent_ROOT=$ROOT_N" \
      "$NODE_BIN" tools/verify-plugin-offline.mjs 2>&1
fi)"
printf '%s\n' "$SMOKE"
if printf '%s' "$SMOKE" | grep -q 'meta 8 键校验 = PASS'; then
  say ""
  say "✅ 安装完成！下一步：打开 AGH 会话（Web 或 TUI），按 docs/使用提示词模板.md 提问即可。"
  say "   例：用 sciret_plan 以 research 工作流规划\"大语言模型幻觉缓解方法\"并返回 run_id，"
  say "       然后 sciret_run_step 依次执行 R1_search 到 R6_review。"
  exit 0
else
  die "冒烟测试未通过（插件 → Python 链路异常）。
   最常见原因：daemon 没带 paper-agent_ROOT / paper-agent_PYTHON 启动。
   修复：重跑本脚本（它会用正确环境重启 daemon）。"
fi
