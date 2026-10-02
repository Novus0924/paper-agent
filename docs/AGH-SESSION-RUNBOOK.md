# AGH 会话内主路径 · 操作手册

**为什么必须你自己跑**：AGH 安装包走**交互式 TTY 人工确认**（`package add` 没有
bypass flag——这是它的安全设计：装插件等于以本机权限执行 JS）。任何自动化工具
都替代不了你在真实终端里按一次 `y`。

本手册里 【实测】= 我在本机真跑过、输出是真的；【预期】= 按 AGH 设计与形态推断，
实际文字可能略有差异，以你屏幕上看到的为准。

---

## 第 0 步 · 准备（两条命令，缺一不可）

### 0.1 设置 Python 解释器（**本机必做**）

```bash
export PAPER_AGENT_PYTHON="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"
```

**为什么必须**：【实测】本机 PATH 上 **没有任何 python 命令**
（`python` / `python3` / `py` 全部不在），而插件要靠它启动 Python 核心。
不设的话 10 个工具会全部报：
`cannot launch python (tried: python, python3, py): spawn py ENOENT`。

> 变量名有连字符版本 `paper-agent_PYTHON` 也支持，但**部分 shell 无法 export 连字符名**，
> 所以统一用下划线版本。

### 0.2 从**项目根目录**启动 daemon（**关键坑**）

```bash
cd /d/workBubbyStore/hks/paper-agent     # 必须先切到项目根
AGH="node D:/agnes-harness-main/packages/cli/dist/local/agnes.mjs"

$AGH daemon stop        # 若已在跑
$AGH daemon start
$AGH daemon status
```

【实测】预期输出（后一条）：

```
{"running":true,"owner":{"pid":35752,...},"socketReachable":true}
```

**为什么必须从项目根启动**：【实测】包源码 `file:./plugins/paper-agent-tools` 是
**相对路径**，由 daemon 解析——daemon 在别处启动时 `package inspect` 会直接失败：

```
agnes: package inspect The package source could not be accepted.
```

### 0.3 确认 Node ≥ 24 与 provider 可用

```bash
node --version                      # 【实测】要求 ≥ 24
$AGH doctor provider --probe         # 【实测】预期 ✓ verified
```

【实测】`--probe` 成功时输出：

```
✓ provider
    selected provider route and model inference verified
```

失败就先解决 provider（`AGH doctor provider` 会告诉你配了哪条 route）。

---

## 第 1 步 · inspect（只读，先看清单）

```bash
cd /d/workBubbyStore/hks/paper-agent
$AGH package inspect "file:./plugins/paper-agent-tools"
```

【实测】输出：

```
Preview paper-agent-tools@0.1.0
integrity sha256-42c2a7dd5137790dec55da29b5b8f0ef9b8985a49a527fc2629a41208f201c2b
contributions none
warnings Package provenance has not been independently verified.
Installation will remain disabled and untrusted.
```

要点：

- **必须用相对 `./` 形式**；绝对路径 `file:D:\...` 会被 AGH 的 schema 拒绝
  （`ProtocolViolation: Expected union value`）。
- 上面的 `integrity` 是**我这次实测的值**；你一旦改动 `index.mjs` 或 `package.json`，
  它会变——**以你自己的输出为准**。
- 这里**没有 `capabilityHash`**：AGH 只在 packages 声明了 contributions 时才计算并
  显示它，本插件 `contributions none` 故省略。所以下一步 walk the `add` 输出。

---

## 第 2 步 · install（**必须在真实终端手动确认**）

```bash
$AGH package add "file:./plugins/paper-agent-tools"
```

【预期】AGH 会打印 preview 摘要，然后**停下来等你确认**（形如 `Proceed? [y/N]`）。
**这一步请在你自己的终端窗口里执行**，不要经由自动化工具。

- 确认时输入 `y` 回车。
- **请把确认提示里出现的 `integrity` 与 `capabilityHash` 抄下来**（下一步 trust 要用）。
  若提示里确实没有 `capabilityHash`，先执行第 3 步的 `package status`，
  它的输出里通常带有 `capabilityHash` 字段。
- 【预期】不确认（直接回车或 n）会输出 `Installation cancelled`，属正常行为，
  不是故障。

---

## 第 3 步 · trust（把上面的两个值填进去）

```bash
$AGH package trust paper-agent-tools <INTEGRITY> <CAPABILITY_HASH>
```

- `<INTEGRITY>`：形如 `sha256-42c2a7dd...`（长 71 字符）
- `<CAPABILITY_HASH>`：**64 位十六进制**

【实测】用法确认（不传参时的提示）：

```
usage: agh package trust <id> <integrity> <capabilityHash>
```

若提示 integrity 或 capabilityHash 不匹配，通常是插件文件在你 inspect 之后又被改过
——回到第 1 步重新 inspect 取新值。

---

## 第 4 步 · enable 并确认状态

```bash
$AGH package enable paper-agent-tools
$AGH package status
```

【实测】`package status` 的输出格式（下面是官方内置插件的真实输出，你的插件会多一行）：

```
@agnes/mcp-helper@0.1.0 desired=enabled actual=starting trusted=true
@agnes/plugin-helper@0.1.1 desired=enabled actual=starting trusted=true
@agnes/skill-helper@0.1.1 desired=enabled actual=starting trusted=true
```

【预期】你的插件应出现：

```
paper-agent-tools@0.1.0 desired=enabled actual=running trusted=true
```

**判定标准**：`desired=enabled` + `actual=running` + `trusted=true` 三者齐备。
若 `actual` 是 `failed` 或 `restart-required`，看 `AGH doctor extensions`。

---

## 第 5 步 · 跑会话（两条路线，建议都跑）

先确认工作目录就是项目根，且 `PAPER_AGENT_PYTHON` 仍在当前 shell 里。

### 5A 回归路线：验证既有 5 步流水线（7 个工具）

```bash
$AGH -p --cwd "$PWD" "请使用科研流水线工具完成任务：先用 sciret_plan 规划一个『硫化物固态电解质电导率排序』任务并返回 run_id；然后用 sciret_run_step 依次执行 P1 到 P5；再用 sciret_verify 做复现验证；用 sciret_report 生成报告；用 sciret_cite 回查任意一条证据；最后用 sciret_status 查看最终状态。全程用工具完成，并给出中文结论。"
```

【预期】

- 打印模式会话依次调用 `sciret_plan` → `sciret_run_step` × 5 → `sciret_verify`
  → `sciret_report` → `sciret_cite` → `sciret_status`
- 结束时打印 session id（下一步要用；也可用 `$AGH sessions list --cwd "$PWD"` 取最新）
- **闸门**：本会话至少产生 6 条 `tool/call` + `tool/result`

### 5B 新能力路线：验证检索 / 判断 / 冻结（3 个新工具）

```bash
$AGH -p --cwd "$PWD" "请严格按以下步骤使用工具，并如实汇报每一步的返回：
1) 用 sciret_search 检索『argyrodite Li6PS5Cl ionic conductivity』，rows 传 5，列出你实际看到的论文标题与 DOI；
2) 用 sciret_freeze_prepare 取本任务的待判对象（literature 参数用 bootstrap）；
3) 针对返回的每一个材料化学族，依据目标『硫化物固态电解质电导率排序』自行判断 relevant 或 excluded，并为每个族写一句中文理由；
4) 用 sciret_freeze_commit 提交你的全部裁决（model_name 填你自己的模型标识），提交前请确认你覆盖了返回的每一个族；
5) 如果第 4 步因异常而停下，请把异常报告原文完整贴出来，不要自行添加 ack 参数确认。"
```

【预期】

- `sciret_search` 返回真实论文（DOI + 标题 + 年份），**不抓全文**
- `sciret_freeze_prepare` 返回 `pending_id`、`families`（本机实测 42 个化学族）、
  `rule_queries`、`rule_scope`
- 模型据 `families` 自行推理，产出裁决 JSON，调 `sciret_freeze_commit`
- 成功时返回 `ok=true` + 新 `snapshot_id`，清单里 `judged_by=model`、
  `model=<模型标识>`
- **若停下**（退出码 3），返回里会有 `anomalies` 与 `ack_hint`——这是设计行为，
  见第 7 步

> 想让第 5B 步体现"真实联网检索"，把 `literature` 参数改成 `network`
> （需网络，只调 Crossref/OpenAlex 元数据接口）。

---

## 第 6 步 · 导出会话证据

```bash
# 会话 id 用上一步打印的（或用下面这条取最新）
$AGH sessions list --cwd "$PWD"

$AGH export <SESSION_ID> --format agnes -o evidence/session-$(date +%Y%m%d).jsonl
```

【实测】计数验证（赛事闸门要求 ≥6 条工具交互）：

```bash
grep -c '"tool/call"'   evidence/session-*.jsonl
grep -c '"tool/result"' evidence/session-*.jsonl
```

【实测（历史记录）】2026-10-02 原作者的两次真实会话合计 **21 tool/call + 21
tool/result**，7 个工具全覆盖；本次改造后插件为 10 工具，计数只会更高。

---

## 第 7 步 · 核对产物

```bash
# 新增的快照（5B 产生）
ls -d snapshots/snap-* | tail -3

# 查看它的清单：judged_by 应为 model，anomalies_* 记录了异常与确认情况
cat "$(ls -d snapshots/snap-* | tail -1)/manifest.json"
```

【预期】清单里关注这几个字段：

| 字段 | 期望 |
|---|---|
| `producer` | `model_judge/<模型名>` |
| `stats.judged_by` | `model` |
| `stats.model` | 你的模型标识 |
| `stats.judgments` | 43（1 条检索式 + 42 条族级裁决） |
| `stats.anomalies_detected` | `[]` 或异常码列表 |
| `stats.anomalies_acknowledged` | 你确认过的异常码（未确认则为 `[]`） |

再跑一次主线确认新快照可用：

```bash
bash demo/demo_mainline.sh      # 【实测】期望末行 DEMO_MAINLINE_OK
```

---

## 故障对照表（都是本机实测踩到的）

| 现象 | 原因 | 处理 |
|---|---|---|
| `package inspect ... source could not be accepted` | daemon **不是从项目根启动**的，`./` 解析失败 | `cd` 到项目根 → `daemon stop` → `daemon start` → 重试 |
| 工具返回 `cannot launch python (tried: python, python3, py)` | 本机 PATH 上没有 python | 设置 `PAPER_AGENT_PYTHON` 为绝对路径后**重启 daemon** |
| 工具返回 `non-JSON stdout: ...` | Python 侧报错但没按契约输出 JSON | 直接手动跑同一条 CLI 命令看 stderr（命令形如 `python -m paper_agent.cli status --run <id>`） |
| `package add` 直接输出 `Installation cancelled` | 非交互环境/没输 `y` | 在真实终端里重跑并输入 `y` |
| `package trust` 报 integrity 不匹配 | 插件文件在 inspect 之后被改过 | 重新 inspect 取新 integrity 与 capabilityHash |
| `actual=failed` / `restart-required` | 插件加载失败 | `$AGH doctor extensions` 看详情；确认 `index.mjs` 语法正确（`node --check`） |
| `$AGH -p` 长时间无输出并卡住 | **已知限制**：打印模式在非交互环境下会挂起（实测 daemon 就绪后仍 150s 无输出） | 必须在**真实交互终端**里跑；不要用管道/重定向包住它 |
| provider 报未验证 | 没有可用 provider 或凭据 | `$AGH doctor provider`（看 route）→ 配好后 `--probe` 复验 |

---

## 跑完之后

把这三样发我，我可以接着往下做（例如把模型判断的结果纳入验收、或修任何暴露出的问题）：

1. 第 4 步 `package status` 里你插件那一行
2. 第 6 步的 `tool/call` 计数
3. 第 7 步 `manifest.json` 里的 `stats`（或直接贴 5B 的返回）

如果 5B 半途停下（异常闸门触发），**把异常报告原文贴给我**——那说明闸门在正常工作，
我们一起看是真异常还是规则需要调整。
