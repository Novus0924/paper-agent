# paper‑agent

**2026 江苏省 AI + 科学与工程创新实践黑客松｜科研 Agent 与 Harness 工程** 参赛作品。

一套**可审计、可复现、可故障恢复**的科研智能体流水线系统：基于
**Agnes Harness（AGH，https://github.com/AgnesAI‑Labs/agnes‑harness）** 作为智能体
执行底座，通过插件化工具链实现完整科研工作流，所有输出具备证据溯源与机器可校验能力。

> 目标产物：`paper‑agent`，驱动**五步标准化科研流水线**：
> 文献检索 → 数据清洗 → 真实实验执行 → 复现验证 → 报告汇总；
> 全链路做到**任务状态可观测、每一条结论可溯源至文献 DOI 或带 SHA‑256 校验的产物文件、
> 任务失败支持重试 / 降级 / 断点续跑**。
>
> **编排主体是 AGH 会话内的大模型**：核心层只暴露**单步**工具，模型必须逐步读取每步
> 返回的决策上下文（`next_tool_candidates` / `remaining_steps` / `failed_steps`）再决定
> 下一步调用；`run-all` 仅为确定性兜底路径（非主导），详见「编排模型」一节。

---

## 编排模型（模型驱动为主，兜底路径为辅）

红线的核心要求是「**AGH 承担核心任务流程（≥3 连续步骤）**」。因此本项目的编排权**不在
Python 里**，而在 AGH 会话内的大模型手中：

| 路径 | 工具 | 角色 | 说明 |
| --- | --- | --- | --- |
| **主导** | `sciret_plan` | 建 run，返回全部步骤 PENDING | 模型发起 |
| **主导** | `sciret_step_driven` | **执行单步**并返回决策上下文 | 模型逐步调用 ×5 |
| **主导** | `sciret_next` | 只读：当前进度与候选下一步 | 模型用于决策 |
| **主导** | `sciret_finish` | 全部终态后收敛 RUNNING→DONE/FAILED | 模型收尾 |
| 兜底 | `sciret_run_step` / `sciret_resume` | 单步 / 断点续跑 | 故障恢复场景 |
| 兜底 | `python -m paper_agent.cli run-all` | 一次性跑完全部步骤 | **非主导**，仅用于离线确定性复现 |

`sciret_step_driven` 每次只推进一步，并返回：`next_tool_candidates`、`requires_decision`
、`remaining_steps`、`completed_steps`、`failed_steps`、`result`（含本步证据 ID）。
因此**若不经过模型逐步决策，流水线不会自行跑完** —— 这即是「AGH 承担核心流程」的可验证证据。
真实参与证据由 AGH daemon 原生写出（`~/.agh/data/sessions.db`，含完整信封与 integrity
哈希链），落地方式与当前进展见 `evidence/AGH-真实会话落地报告.md`。

---

## 六层系统架构

```
L6 交互层    AGH CLI / Web Workbench / 审计取证导出
L5 Agent层   AGH 会话内大模型：读取每步决策上下文，**逐步驱动** P1..P5（核心流程编排者）
L4 记忆层    runs/<run_id>/ 运行产物快照｜state.json 状态｜事件&证据双账本
L3 可信框架  证据溯源先行｜实验复现验证｜审计出口（导出完整可交付包）
L2 Harness层 AGH 原生能力 + paper-agent 核心（有限状态机、事件账本、**单步调度**）
L1 工具执行层 paper-agent-tools JS 薄壳插件（10 工具 + 1 Skill）→ Python 核心业务 → 实验子进程
```

数据流单向：`L6 → L5 → L2 → L1`；产物向上回流经 `L3` 登记证据，再写入 `L4`。

## 目录结构

```
paper-agent/
├── README.md                     # 本文件
├── HOW-TO-VERIFY.md             # 验收核验操作手册 + 哈希比对命令
├── .agh/skills/                 # AGH 工作区 Skill：sciret-research-pipeline（编排规程）
│   └── sciret-research-pipeline/SKILL.md
├── plugins/paper-agent-tools/   # AGH 扩展：10 科研工具 + 1 Skill 注册（JS 薄壳）
│   ├── package.json
│   └── index.mjs
├── core/paper_agent/            # Python 核心业务（零第三方依赖）
│   ├── __init__.py              #   根路径探测 PAPER_AGENT_ROOT
│   ├── state.py                 #   有限状态机 + run 生命周期 + 状态持久化
│   ├── provenance.py            #   证据账本 + 结论‑证据绑定 + 引文渲染
│   ├── chaos.py                 #   故障注入（重试/降级/校验失败场景）
│   ├── steps.py                 #   五步 P1-P5 **单步驱动** + 决策上下文 + 兜底 run-all
│   ├── verify.py                #   P4 复现验证器（递归容差比对）
│   ├── report.py                #   P5 报告生成（证据归属精确到生产步骤）
│   ├── litsearch.py             #   P1 检索后端：arXiv 公开 API / 本地语料 + 快照冻结
│   └── cli.py                   #   命令行入口：step-driven / next / finish / run-all …
├── experiments/
│   └── arrhenius_rank.py        # 零依赖确定性实验脚本（电导率打分 + Arrhenius 外推）
├── data/
│   ├── literature.json          # 真实 DOI 文献语料库（5 篇，DOI 经 Crossref 权威核验）
│   └── conductivity_raw.csv     # 带缺陷原始数据集（材料–年份–DOI 自洽）
├── evidence/                    # AGH 参与证据
│   ├── README.md
│   ├── AGH-真实会话落地报告.md    # 真实会话打通记录（信封格式 / 卡点 / 复现实验）
│   ├── _pty_install.mjs         # PTY 驱动插件安装（绕过 TTY 确认限制）
│   └── _agh_rpc.mjs             # daemon RPC 客户端（取 capabilityHash）
├── runs/<run_id>/               # 运行实例产物（gitignore 忽略；每个 run 完全隔离）
├── demo/
│   ├── demo_e2e.sh             # 端到端正常流程 + 确定性核验
│   └── demo_failure.sh         # 四大故障恢复验收用例自动化
├── tests/                        # unittest 套件（6 文件，62 用例，含数据完整性守门）
└── audit-pack-template/          # 审计交付包模板
```

## 环境要求

- **Python 核心层**：Python 3.10+，**零第三方依赖**（仅标准库），保障跨机器可复现。
- **AGH 插件层**：Node 18+；AGH 源码构建与真实会话联调需要比赛发放的模型 API Key。
- **Demo 脚本**：`bash` + `sha256sum`（Windows 用 Git Bash / WSL；注意 npm shim 拉起
  wsl.exe 可能被安全策略拦截，构建后直接 `node <入口.js>` 调用）。

## 快速上手

**方式一：模型驱动单步（主导路径，等价 AGH 会话内的逐步调用）**

```bash
cd paper-agent
export PYTHONPATH=core            # Windows: set PYTHONPATH=core
python -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity ranking"
# 复制上一步返回的 run_id，然后逐步推进（每一步都打印下一步候选）：
python -m paper_agent.cli step-driven --run <RUN_ID> --step P1_lit_search
python -m paper_agent.cli step-driven --run <RUN_ID> --step P2_clean_data
python -m paper_agent.cli step-driven --run <RUN_ID> --step P3_run_experiment
python -m paper_agent.cli step-driven --run <RUN_ID> --step P4_verify
python -m paper_agent.cli step-driven --run <RUN_ID> --step P5_report
python -m paper_agent.cli next  --run <RUN_ID>     # 只读：查看剩余步骤
python -m paper_agent.cli finish --run <RUN_ID>    # 收敛为 DONE
python -m paper_agent.cli cite  --run <RUN_ID> --ev EV-0001
```

**方式二：一次性兜底（非主导，仅供离线确定性复现）**

```bash
python -m paper_agent.cli run-all --run <RUN_ID>
python -m paper_agent.cli verify  --run <RUN_ID>
python -m paper_agent.cli report  --run <RUN_ID>
```

或直接跑演示脚本：

```bash
bash demo/demo_e2e.sh       # 正常路径 + 实验确定性 SHA-256 核验
bash demo/demo_failure.sh   # 四大故障用例（A 重试 / B 降级 / C resume / D 复现 FAIL）
```

## 文献检索来源（P1）：不再局限于内置语料

P1 的检索后端有 **两条来源**，输出同一套规范化文档结构（`doc_id / doi / title /
authors / venue / year / keywords / abstract / url / source`），上层无需区分：

| `--lit-source` | 行为 | 适用场景 |
| --- | --- | --- |
| `arxiv` | 调用 arXiv 公开 Atom API **实时检索**，任意课题都是检索式 | 真实科研检索 |
| `auto`（默认） | 先试 arXiv；网络不可用或 0 命中 → 自动回落本地语料，并置 `degraded=true` | 通用 |
| `local` | 只读 `data/literature.json` 内置语料 | 离线 / 逐字节确定性基线 |

```bash
# 实时检索 arXiv（不局限于内置 5 篇）
PYTHONPATH=core python -m paper_agent.cli run-all \
  --goal "argyrodite solid electrolyte ionic conductivity" --lit-source arxiv

# 纯离线确定性基线（默认单测走这条）
PYTHONPATH=core python -m paper_agent.cli run-all --goal "..." --lit-source local
```

**确定性契约（关键设计）**：arXiv 在线结果随时间变化，若直接喂给下游会破坏
「同一 run 逐字节可复现」的红线。因此：

1. 在线检索结果首次取得后，**快照冻结**到
   `runs/<run_id>/literature/arxiv_snapshot.json`（含检索式与 `fetched_at`）；
2. 同一 run 再次执行 P1（resume / 复跑）**只读快照，不再联网**；
3. 快照文件本身作为 `data` 证据登记（带 SHA-256），证明"下游实际用过的输入"可追溯。

即 **联网只发生在 run 的首跑，且输入被冻结留证**，之后完全离线可复现。

> 边界说明：本版 P1 的检索来源已可任意指定，但 **P2/P3 仍基于
> `data/conductivity_raw.csv` 内置数据集**做清洗与排序（P1 与此解耦）。
> 即"换课题能换到真文献"，但"换课题不会自动换实验数据"——后者需要从论文正文
> 抽取数值，属更大改造，且必须严防凭空捏造数据。

## 数据来源声明

- `data/literature.json` 内置 5 篇公开真实 DOI 文献（LGPS / Kato 高功率硫化物 / LLZO /
  LiPON / Li6PS5X argyrodite）。**全部 DOI 已于 2026-10-02 经 doi.org / Crossref REST API
  逐条权威核验**（标题、作者、期刊、年份均与记录一致）：
  - L001 `10.1038/nmat3066` — Kamaya et al., *Nature Materials* 2011（LGPS）
  - L002 `10.1038/nenergy.2016.30` — Kato et al., *Nature Energy* 2016
  - L003 `10.1002/anie.200701144` — Murugan et al., *Angew. Chem. Int. Ed.* 2007（LLZO）
  - L004 `10.1016/0167-2738(92)90442-r` — Bates et al., *Solid State Ionics* 1992（LiPON）
  - L005 `10.1002/anie.200703900` — Deiseroth et al., *Angew. Chem. Int. Ed.* 2008（argyrodite）
- `data/conductivity_raw.csv` 的**材料–年份–DOI 三者自洽**（每行 `source_doi` 均可在语料
  中命中，且 `year` 与所引文献年份一致），由 `tests/test_data_integrity.py` 固化为守门测试。
- **所有数值均标注 `as‑reported`**，用于黑客松工程演示；**正式科研使用务必核对原始
  论文原文**。严禁伪造实验数据（黑客松直接取消参赛资格行为）。

## 计算与文献挂钩（不再是硬编码常数）

`experiments/arrhenius_rank.py` 的打分 `score = 0.6·电导率归一 + 0.25·稳定性 + 0.15·时效`，
其中**稳定性指标由文献活化能导出**（`stability_source: activation_energy_minmax`）：读取语料
中每篇文献的活化能 Ea，做 min-max 归一（Ea 越高 → 稳定性越高），缺失值按家族中位数插补
（`M007` 覆盖该分支）。脚本同时给出 **Arrhenius 外推** `σ(60°C) = σ_ref·exp(-Ea/k·(1/T-1/T_ref))`，
k = 8.617333262e-5 eV/K，T_ref = 25°C。这样排序结果与 P1 检出的文献真实挂钩，而非写死。

## 复现指引（确定性契约）

相同输入两次执行实验脚本，`results.csv` 逐字节一致；核验命令见
[HOW‑TO‑VERIFY.md](HOW‑TO‑VERIFY.md)。唯一可变字段 `summary.json.generated_at`
（UTC 时间戳）在校验环节被排除，不参与哈希比对。

## AGH 联调（已真实跑通，2026-10-02）

实际链路（与 AGH 构建产物的真实 CLI 对齐）：

```bash
AGH="node C:/…/agnes-harness/packages/cli/dist/local/agnes.mjs"
$AGH package inspect "file:./plugins/paper-agent-tools"   # 需从项目根、相对 ./ 形式
# package add 需交互式 TTY 人类确认（AGH 安全设计，无 bypass）：
#   自动等价方案 = demo/reinstall_plugin.ps1（真实控制台 + WriteConsoleInput 注入）
$AGH package trust paper-agent-tools <integrity> <capabilityHash>
$AGH package enable paper-agent-tools                     # desired=enabled actual=running
$AGH -p --cwd "$PWD" "用 sciret_* 完成…流水线"             # 打印模式会话，无需 TTY
$AGH export <SESSION_ID> --format agnes -o evidence/session-full.jsonl
```

联调闸门：会话导出至少 ≥6 条 `tool/call` / `tool/result` 结构化交互记录。
实测已达 **21 + 21 条，且 7 个 `sciret_*` 工具全部出现**（含 `sciret_resume` 的
`kill_after_p2` 真实进程崩溃 + 断点续跑演示）；证据见 `evidence/` 与 `audit-pack/`。

**证据取得方式**：真实证据由 AGH daemon 原生写出（`~/.agh/data/sessions.db` 的 `events` 表，
每条事件带 `integrity_prev` → `integrity_digest` 哈希链），或用
`agnes export <SESSION_ID> --format agnes` 导出。因原始导出含本机绝对路径，按红线不入 git，
打包时从磁盘归集；打通步骤与当前卡点见 `evidence/AGH-真实会话落地报告.md`。

## 验收核对清单

- [x] **模型驱动主导路径**：`step-driven` 逐步推进，每步返回决策上下文；`next`/`finish` 收敛；
      **不经模型逐步调用则流水线不自行跑完**（编排主体为 AGH 会话内大模型）
- [x] AGH Skill `sciret-research-pipeline` 已注册（工作区优先级 500，`resources list` 可发现）
- [x] 插件共 **10 工具 + 1 Skill**：`plan/run_step/resume/verify/report/cite/status`
      + `step_driven/next/finish`
- [x] `run-all` 正常路径：五步全部 DONE，degraded=false，verification PASS（兜底路径）
- [x] 实验确定性：两次执行 results.csv SHA-256 完全相同
- [x] 用例 A `p1_fail_first`：重试 1 次，最终 DONE，degraded=false
- [x] 用例 B `p1_fail_all`：3 次重试耗尽触发降级；DONE，degraded=true，events 含 degrade
- [x] 用例 C：P2 完成后 resume，只运行剩余步骤，已 DONE 步骤直接复用
- [x] 用例 D `mutate_summary`：verification=FAIL，P4 FAILED，顶层 run FAILED；5 项校验可查
- [x] 用例 E2/E3 `kill_after_p2`：子进程真实被 `os._exit(137)` 杀死（run-all 与 run-step 双路径），账本完整，resume 续跑到 DONE
- [x] P5 报告终态幂等复用（重复调用不抛 StateError）
- [x] report.md 顶层状态由**步骤终态推断**（不再领先一步）；每条结论携带 `[EV-XXXX]`
      证据标记且归属精确到生产步骤；`sciret_cite` 可回查 DOI / SHA-256
- [x] **数据红线**：5 篇文献 DOI 经 Crossref 权威核验；CSV 材料–年份–DOI 自洽；
      `tests/test_data_integrity.py` 9 项守门（含可选联网核验 `RUN_ONLINE=1`）
- [x] **计算挂钩文献**：稳定性由文献活化能导出；新增 Arrhenius σ(60°C) 外推
- [x] **P1 检索后端可切换**：`local`（内置语料）/ `arxiv`（实时检索 arXiv，结果快照冻结）/
      `auto`（先试 arXiv，不可用自动回落并置 degraded）；引用串按 DOI→URL 回退
- [x] 单元测试全部通过（**62/62，零 skip**；单测默认 `paper-agent_LIT_SOURCE=local` 强制离线）
- [x] AGH 联调：真实会话 21+21 条 tool/call / tool/result，7/7 工具覆盖，证据已导出；
      真实信封格式与 integrity 哈希链见 `evidence/AGH-真实会话落地报告.md`

## 合规红线

- 实验：内置真实 DOI + 带缺陷演示数据集上的真实运行。
- 文献检索：`arxiv` 来源只调用 arXiv 官方 Atom API 获取**元数据**（标题/作者/摘要/DOI），
  不做论文全文批量抓取；结果按 run 快照冻结留证。
- Agnes Key 只放环境变量，**绝不写入仓库**。
- 开发纪律：每个任务结束 commit；**单测默认不联网**（靠 `paper-agent_LIT_SOURCE=local`）。
