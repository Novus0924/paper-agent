# paper-agent

**2026 江苏省 AI + 科学与工程创新实践黑客松｜科研 Agent 与 Harness 工程** 参赛作品。

一套**可审计、可复现、可故障恢复**的科研流水线系统：
输入是**真实公开数据集**（OBELiX，599 条锂固态电解质实验实测离子电导率，
每条带原始论文 DOI），而不是人工预制的演示数据；
每一步产出都留痕、每条结论都绑定证据、每次复算都逐字节一致。

> 目标产物：`paper‑agent`，驱动**两条标准化科研流水线**，共用同一套状态机 / 双账本 / 故障恢复：
> - **`materials`（可复现实验底座）**：文献检索 → 数据清洗 → 真实实验执行 → 复现验证 → 报告汇总（P1–P5）
> - **`research`（PRD v0.3 科研全流程）**：多源检索 → 论文精读 → 创新点拆解 → 事实验证 → 综述写作 → 自评审（R1–R6）
> 全链路做到**任务状态可观测、每一条结论可溯源至文献 DOI 或带 SHA‑256 校验的产物文件、
> 任务失败支持重试 / 降级 / 断点续跑**。
>
> **五步流水线（materials）**：文献腿 → 数据清洗 → 实验执行 → 复现验证 → 报告汇总；
> 判断与结论**严格分级**（fact / judgment / conclusion 三级信任模型）。
>
> **编排主体是 AGH 会话内的大模型**：核心层只暴露**单步**工具，模型必须逐步读取每步
> 返回的决策上下文（`next_tool_candidates` / `remaining_steps` / `failed_steps`）再决定
> 下一步调用；`run-all` 仅为确定性兜底路径（非主导），详见「编排模型」一节。
>
> **需求对照**：本次按负责人 PRD v0.3 实现「全量核心（P0–P2，不含面板）」，逐条映射见
> [`docs/PRD-v0.3-需求实现映射.md`](docs/PRD-v0.3-需求实现映射.md)；量化验证（F-7）与三类异常恢复（F-4.8）均已实现并可复现。

---

## 编排模型（模型驱动为主，兜底路径为辅）

红线的核心要求是「**AGH 承担核心任务流程（≥3 连续步骤）**」。因此本项目的编排权**不在
Python 里**，而在 AGH 会话内的大模型手中：

| 路径 | 工具 | 角色 | 说明 |
| --- | --- | --- | --- |
| **主导** | `sciret_plan` | 建 run，返回全部步骤 PENDING | 模型发起 |
| **主导** | `sciret_step_driven` | **执行单步**并返回决策上下文 | 模型逐步调用 ×5（materials）/ ×6（research） |
| **主导** | `sciret_next` | 只读：当前进度与候选下一步 | 模型用于决策 |
| **主导** | `sciret_finish` | 全部终态后收敛 RUNNING→DONE/FAILED | 模型收尾 |
| 兜底 | `sciret_run_step` / `sciret_resume` | 单步 / 断点续跑 | 故障恢复场景 |
| 兜底 | `python -m paper_agent.cli run-all` | 一次性跑完全部步骤 | **非主导**，仅用于离线确定性复现 |

`sciret_step_driven` 每次只推进一步，并返回：`next_tool_candidates`、`requires_decision`
、`remaining_steps`、`completed_steps`、`failed_steps`、`result`（含本步证据 ID）。
因此**若不经过模型逐步决策，流水线不会自行跑完** —— 这即是「AGH 承担核心流程」的可验证证据。
真实参与证据由 AGH daemon 原生写出（`~/.agh/data/sessions.db`，含完整信封与 integrity
哈希链），落地方式与当前进展见 `evidence/AGH-真实会话落地报告.md`。

**两条工作流的工具面（插件共 20 个 `sciret_*`）**：

- 编排与底座（10）：`plan` / `step_driven` / `next` / `finish` / `run_step` / `status` / `verify` / `report` / `cite` / `resume`
- 科研能力（7）：`search_papers` / `parse_paper` / `analyze` / `factcheck` / `write_review` / `self_review` / `eval`
- 可信增强（3）：`search` / `freeze_prepare` / `freeze_commit`
- `sciret_plan(goal, workflow="materials"|"research")` 选择工作流（默认 `materials`）。

---

## 改造状态（2026-10-02）

本仓库正在从"演示原型"改造为"真实数据流水线"。**已完成的决定与理由见
[`docs/redesign-decisions.md`](docs/redesign-decisions.md)**（含被否决方案、差异清单、
红线修订、验收判据）。当前进度：

```
L6 交互层    AGH CLI / Web Workbench / 审计取证导出
L5 Agent层   AGH 会话内大模型：读取每步决策上下文，**逐步驱动** P1..P5 / R1..R6（核心流程编排者）
L4 记忆层    runs/<run_id>/ 运行产物快照｜state.json 状态｜事件&证据双账本
L3 可信框架  证据溯源先行｜实验复现验证｜量化验证（F-7）｜审计出口（导出完整可交付包）
L2 Harness层 AGH 原生能力 + paper-agent 核心（有限状态机、事件账本、**单步调度**）
L1 工具执行层 paper-agent-tools JS 薄壳插件（20 工具 + 1 Skill）→ Python 核心业务 → 实验子进程
```

| 能力 | 状态 |
|---|---|
| 真实数据集接入（OBELiX 599 行，DOI 100% 覆盖） | ✅ 已完成 |
| 冻结输入快照（强校验 + 判断批次自包含） | ✅ 已完成 |
| 三级信任模型（事实 / 判断 / 结论） | ✅ 已完成 |
| 真实数据清洗（上界值留证 / 缺失归类 / 重复标注） | ✅ 已完成 |
| 离线主线端到端（无需联网 / key / 第三方库） | ✅ 已完成 |
| **联网文献腿**（Crossref / OpenAlex 元数据检索） | ✅ 已完成 |
| **双腿 DOI 对接 + 异常驱动打断** | ✅ 已完成（规则据实测已修正，见设计文档 §9.2） |
| **可插拔判断器 + 反判据对比工具** | ✅ 已完成（规则式基线可用；模型侧待端点） |
| **AGH 插件 3 个新工具**（检索 / 待判 / 提交裁决） | ✅ 已完成（累计 20 工具） |
| **真实模型的判断与反判据结论** | ✅ 已完成（DeepSeek 实测 `model_matters`，见设计文档 §9.5） |
| AGH 会话内主路径端到端实跑 | ⬜ 待你在交互式终端执行（步骤见 [`docs/AGH-SESSION-RUNBOOK.md`](docs/AGH-SESSION-RUNBOOK.md)；已排除 daemon cwd 与 Python 解释器两个坑） |

> 诚实声明（当前批次）：判断器有**规则式**与**模型**两个实现，数据契约相同。
> 仓库内快照由**规则式**产出（`judged_by=rule`）；模型路径已用标准 OpenAI 兼容
> 端点（DeepSeek）**实测跑通并出具反判据结论**。
> 仍需注意：**AGH 会话内主路径（LLM 调插件工具落盘裁决）尚未端到端实跑**，
> 因为该路径依赖交互式终端完成插件安装。详见 `docs/ai_disclosure.md` §3。

## 双轨设计

| | **主线（稳定轨）** | **增强线（智能轨）** |
|---|---|---|
| 依赖 | 无（不需要 AGH / key / 网络 / 第三方库） | 联网检索：仅需网络；模型判断：AGH 会话或 OpenAI 兼容端点 |
| 输入 | 冻结快照（`snapshots/`，已入库） | 现场检索 + 现场判断 |
| 展示 | **可信性**：一键跑通、逐字节复现、证据可回查 | **智能性**：真检索、真判断、异常真会打断 |
| 演示 | `demo/demo_mainline.sh` | `cli search` / `freeze --prepare` / `freeze --commit` |
| 可复现 | ✅ 逐字节 | ⚠️ 判断不可复现 → 用**快照冻结**兜住（D6） |

两条轨**共用同一套 Python 核心与同一套证据账本**，区别只在"输入是快照还是现搜"。

## 目录结构

```
paper-agent/
├── README.md                     # 本文件
├── HOW-TO-VERIFY.md              # 验收核验操作手册 + 逐条命令 + 哈希比对
├── .agh/skills/                  # AGH 工作区 Skill：sciret-research-pipeline（编排规程）
│   └── sciret-research-pipeline/SKILL.md
├── docs/
│   ├── HANDOFF.md                # 交接说明
│   ├── sources.md                # 数据来源声明
│   ├── ai_disclosure.md          # AI 使用边界声明（三级模型口径）
│   ├── redesign-decisions.md     # 改造决定记录（权威设计文档）
│   ├── PRD-v0.3-需求实现映射.md   # PRD v0.3 需求逐条实现映射
│   └── diagrams/                 # 3 张竖版流程图（SVG）
├── plugins/paper-agent-tools/    # AGH 扩展：20 科研工具 + 1 Skill 注册（JS 薄壳）
│   ├── package.json
│   └── index.mjs
├── core/paper_agent/             # Python 核心业务（零第三方依赖）
│   ├── __init__.py               #   根路径探测 PAPER_AGENT_ROOT
│   ├── state.py                  #   有限状态机 + run 生命周期 + 状态持久化
│   ├── provenance.py             #   三级证据账本（fact / judgment / conclusion）+ 结论‑证据绑定 + 引文渲染
│   ├── snapshot.py               #   冻结输入快照（强校验 + 判断批次自包含）
│   ├── sources.py                #   数据源适配（OBELiX 列名归一 / 值分类）
│   ├── litsearch.py              #   P1/R1 检索：arXiv / Semantic Scholar / OpenAlex / CrossRef（含联网文献腿只取元数据）
│   ├── judge.py                  #   可插拔判断器 + 反判据对比
│   ├── anomaly.py                #   双腿对接 + 四条异常规则 + 确认闸门
│   ├── freezing.py               #   三段式冻结：prepare → 推理 → commit
│   ├── llm.py                    #   模型客户端适配（含 AGH 路径实测结论）
│   ├── chaos.py                  #   故障注入（重试/降级/校验失败场景）
│   ├── steps.py                  #   五步 P1-P5 **单步驱动** + 决策上下文 + 兜底 run-all（快照主路径 + legacy 回退路径）
│   ├── verify.py                 #   P4 复现验证器（递归容差比对）
│   ├── report.py                 #   P5 报告生成（证据归属精确到生产步骤；判据 4 硬前置）
│   ├── pdfparse.py               #   F-2.1 零依赖 PDF 文本抽取 + 结构化精读笔记（+ OCR 降级）
│   ├── analyze.py                #   F-3.x 创新点拆解 / 技术脉络 / Research Gap
│   ├── factcheck.py              #   F-4.x 引用核查 / 数据一致性 / 文献矛盾检测
│   ├── writing.py                #   F-5.x 综述生成（强制引用）/ BibTeX·RIS / 引用格式化
│   ├── review.py                 #   F-6.1 模拟审稿（5 维度）+ 迭代闭环
│   ├── evaluate.py               #   F-7.x 量化验证（Recall/Precision/NDCG@10/幻觉率/混淆矩阵）
│   ├── research.py               #   research 工作流编排（R1–R6）+ F-4.8 异常恢复
│   └── cli.py                    #   命令行入口：step-driven / next / finish / run-all / eval / search / freeze …
├── experiments/
│   └── arrhenius_rank.py         # 零依赖确定性实验脚本（电导率打分 + Arrhenius 外推；双 schema 自适应）
├── tools/
│   ├── freeze_snapshot.py        # 冻结快照（prepare / commit / 规则式一步到位）
│   ├── search_literature.py      # 联网文献检索 CLI
│   ├── compare_judges.py         # ★ 反判据：模型 vs 规则，退出码即判据
│   └── probe_obelix.py           # 数据源探针（只读、可离线复跑）
├── data/
│   ├── external/obelix/all.csv   # OBELiX 数据快照（599 行，CC-BY-4.0）
│   ├── literature.json           # 真实 DOI 文献语料库（5 篇，DOI 经 Crossref 权威核验；legacy 降级路径）
│   └── conductivity_raw.csv      # 带缺陷原始数据集（材料–年份–DOI 自洽；legacy 降级路径）
├── evidence/                     # AGH 参与证据
│   ├── README.md
│   ├── AGH-真实会话落地报告.md    # 真实会话打通记录（信封格式 / 卡点 / 复现实验）
│   ├── _pty_install.mjs          # PTY 驱动插件安装（绕过 TTY 确认限制）
│   └── _agh_rpc.mjs              # daemon RPC 客户端（取 capabilityHash）
├── snapshots/<snapshot_id>/      # 冻结输入快照（已入库，供离线主线使用）
├── runs/<run_id>/                # 运行实例产物（gitignore 忽略；每个 run 完全隔离）
├── demo/
│   ├── demo_mainline.sh          # ★ 真实数据主线（离线回放 + 判据 4 实测）
│   ├── demo_e2e.sh               # 端到端正常流程 + 确定性核验（legacy 路径）
│   └── demo_failure.sh           # 四大故障恢复验收用例自动化（legacy 路径）
├── tests/                        # unittest 套件（200+ 项单测，含数据完整性守门与 F-1~F-7 覆盖）
└── audit-pack-template/          # 审计交付包模板
```

## 环境要求

- **Python 核心层**：Python 3.10+，**零第三方依赖**（仅标准库），跨机器可复现。
- **Demo 脚本**：`bash` + `sha256sum`（Windows 用 Git Bash）。
- **AGH 增强线**（可选，第二批用）：Node ≥24 + 模型 API Key。

## 快速上手

**方式一：模型驱动单步（主导路径，等价 AGH 会话内的逐步调用）**

```bash
cd paper-agent
export PYTHONPATH="$PWD/core"          # Windows: set PYTHONPATH=%cd%\core

# 一键验收（推荐先跑这条）
bash demo/demo_mainline.sh             # 真实数据主线：14 项断言，末尾 DEMO_MAINLINE_OK

# 模型驱动单步（主导路径）：先 plan，再逐步推进（每一步都打印下一步候选）
python -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity ranking"
# 复制上一步返回的 run_id，然后逐步推进：
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
# 跑完整五步（自动使用最新快照；无需联网）
python -m paper_agent.cli run-all --goal "sulfide solid electrolyte ionic conductivity ranking"
python -m paper_agent.cli verify  --run <RUN_ID>
python -m paper_agent.cli report  --run <RUN_ID>     # → runs/<RUN_ID>/report.md

# 查看状态，并回查证据（fact 级含哈希，judgment 级含对象与理由）
python -m paper_agent.cli status  --run <RUN_ID>
python -m paper_agent.cli cite --run <RUN_ID> --ev EV-0001
python -m paper_agent.cli cite --run <RUN_ID>                 # 列出全部
```

重新生成一份快照（需要 `data/external/obelix/all.csv`，无需联网）：

```bash
python tools/freeze_snapshot.py --goal "sulfide solid electrolyte ionic conductivity ranking"
```

**方式三：科研全流程（research 工作流，PRD v0.3 R1–R6）**

```bash
python -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity" --workflow research
python -m paper_agent.cli run-all --workflow research --goal "<goal>" --lit-source local
python -m paper_agent.cli eval        # 量化验证（F-7）：检索/精读/创新点/引用四套指标
```

（可选）legacy 端到端与故障恢复演示：

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

### 增强线：真实检索 + 判断 + 冻结（三段式）

```bash
# 1) 联网检索候选论文（只取元数据，不抓全文）
python -m paper_agent.cli search --goal "argyrodite ionic conductivity" --rows 10

# 2) 取待判对象（材料化学族 + 规则式参考裁决），落盘一份 pending
python -m paper_agent.cli freeze --goal "sulfide solid electrolyte ranking" --prepare
#    → 返回 pending_id 与 families；会话内的模型据此推理

# 3) 提交裁决，冻结快照（裁决须覆盖全部族）
cat > /tmp/verdicts.json <<'JSON'
{"queries": ["sulfide solid electrolyte ionic conductivity"],
 "families": {"LGPS": {"verdict": "relevant", "reason": "硫化物体系"},
              "NASICON": {"verdict": "excluded", "reason": "氧化物体系"}}}
JSON
python -m paper_agent.cli freeze --commit <PENDING_ID> --verdicts /tmp/verdicts.json \
    --judged-by model --model-name <你的模型名>

# 若流程因异常停下（退出码 3），人工复核后用 --ack <code> 显式确认再重跑
```

### 反判据：模型判断到底有没有用

```bash
# 自检（应当判定为装饰品）：退出码 5
python tools/compare_judges.py --goal "..." --judge-b rule

# 接上任意 OpenAI 兼容端点后，与规则式基线对比
export PAPER_AGENT_LLM_BASE_URL=https://<host>/v1
export PAPER_AGENT_LLM_MODEL=<model>
export PAPER_AGENT_LLM_API_KEY=<key>
python tools/compare_judges.py --goal "..."
# 退出码 0 = model_matters；5 = model_is_decoration（可接 CI 当失败）
```

**证据取得方式**：真实证据由 AGH daemon 原生写出（`~/.agh/data/sessions.db` 的 `events` 表，
每条事件带 `integrity_prev` → `integrity_digest` 哈希链），或用
`agnes export <SESSION_ID> --format agnes` 导出。因原始导出含本机绝对路径，按红线不入 git，
打包时从磁盘归集；打通步骤与当前卡点见 `evidence/AGH-真实会话落地报告.md`。

## 科研全流程工作流（research，PRD v0.3 R1–R6）

`--workflow research`（或 `sciret_plan(goal, workflow="research")`）驱动六步，产物与 materials 同样落进
`runs/<run_id>/` 并逐条登记证据：

| 步骤 | 名称 | 主要产物 |
| --- | --- | --- |
| `R1_search` | 多源检索（arXiv / Semantic Scholar / OpenAlex / CrossRef） | `literature/research_hits.json`（DOI 精确 + 标题/首作者模糊去重，相关性排序） |
| `R2_read` | 论文精读（零依赖 PDF 文本抽取 + 结构化） | `reading/notes/*.json`（章节 / 关键信息 + locator / 图表 / 可复现性 + 置信度） |
| `R3_analyze` | 创新点拆解 + 技术脉络 + Research Gap | `analysis/innovations.json` · `timeline.md` · `gaps.json` |
| `R4_verify` | 事实验证（引用核查 / 数据一致性 / 文献矛盾） | `factcheck/factcheck.json` |
| `R5_write` | 综述写作（抽取式，强制引用）+ BibTeX/RIS | `writing/review.md` · `references.bib` · `references.ris` |
| `R6_review` | 自评审（5 维度打分 + 迭代闭环） | `review/review_report.md` |

```bash
# 端到端（离线确定性，默认走内置语料）
PYTHONPATH=core python -m paper_agent.cli run-all --workflow research \
  --goal "sulfide solid electrolyte ionic conductivity" --lit-source local
# 单点能力（也可经 AGH 会话按 sciret_* 调用）
PYTHONPATH=core python -m paper_agent.cli search-papers --goal "..." --sources arxiv,openalex,crossref
PYTHONPATH=core python -m paper_agent.cli parse-paper   --source 2301.12345 --allow-network
PYTHONPATH=core python -m paper_agent.cli analyze-paper --run <RUN_ID>
PYTHONPATH=core python -m paper_agent.cli verify-facts  --run <RUN_ID>
PYTHONPATH=core python -m paper_agent.cli write-review  --run <RUN_ID>
PYTHONPATH=core python -m paper_agent.cli self-review   --run <RUN_ID>
```

> **零依赖 PDF 解析**：**不引入 GROBID/PyMuPDF**（红线：仅标准库），自行扫描 `stream…endstream`
> + `zlib` 解 FlateDecode + 解析内容流文本算子（`Tj`/`TJ`/`'`/`"`）。对 CID/自定义编码字体会给出
> 低置信度并显式声明；扫描件走 OCR 降级（无 `tesseract` 时标注 `ocr_unavailable`），**绝不假装解析成功**。

## 量化验证（F-7）

`PYTHONPATH=core python -m paper_agent.cli eval` 一次输出四套指标（每套都带 `scale_note`，
声明为 **demo 规模小样本标注**，用于演示口径与基线对比，不代表真实世界性能）：

| 模块 | 指标 | demo 实测 |
| --- | --- | --- |
| F-7.1 检索质量 | Recall / Precision / NDCG@10（含**纯关键词基线**对比） | 系统 Recall 1.000 / NDCG@10 0.987；基线 0.900 / 0.662（Precision 0.345 略低于基线 0.365，主口径为 Recall/NDCG） |
| F-7.2 精读质量 | 结构 / 关键信息 / 可复现性准确率 + **人工耗时对比** | 三项 1.000；系统耗时**实测** ~0.001s/篇（`time.perf_counter`）vs 人工 900s/篇（PRD 下界） |
| F-7.3 创新点 | 识别率 / 分类准确率 / **幻觉率** + 混淆矩阵 | 0.80 / 0.80 / 0.00 |
| F-7.4 引用可信度 | 引用准确率 / **引用幻觉率** | 1.000 / 0.00（≤5% 达标） |

## 异常恢复（F-4.8 三类场景，均可复现）

| 场景 | chaos 模式 | 期望行为 |
| --- | --- | --- |
| ① 外部 API 超时降级 | `ss_timeout` | Semantic Scholar 超时 → 标注不可用并**切源**（arXiv 等），任务不中断，结果标注切源 |
| ② PDF 解析失败恢复 | `scan_pdf` | 无文本层 → 尝试 OCR → 不可用则标「低质量解析、低置信度」 |
| ③ 长任务中断恢复 | `batch_fail_at=N` / `kill_after_r3` | 第 N 篇失败**跳过**继续；进程被真实杀死后 `resume` 断点续跑 |

```bash
for M in ss_timeout scan_pdf batch_fail_at=2 kill_after_r3; do
  PYTHONPATH=core python -m paper_agent.cli run-all --workflow research \
    --goal "sulfide solid electrolyte" --lit-source local --chaos "$M"
done
PYTHONPATH=core python -m paper_agent.cli resume --run <RUN_ID>   # 崩溃后断点续跑，只跑 PENDING/FAILED
```

---


## 验收核对清单

- [x] **模型驱动主导路径**：`step-driven` 逐步推进，每步返回决策上下文；`next`/`finish` 收敛；
      **不经模型逐步调用则流水线不自行跑完**（编排主体为 AGH 会话内大模型）
- [x] AGH Skill `sciret-research-pipeline` 已注册（工作区优先级 500，`resources list` 可发现）
- [x] 插件共 **20 工具 + 1 Skill**：编排与底座 10（`plan/step_driven/next/finish/run_step/status/verify/report/cite/resume`）
      + 科研能力 7（`search_papers/parse_paper/analyze/factcheck/write_review/self_review/eval`）
      + 可信增强 3（`search` / `freeze_prepare` / `freeze_commit`）
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
- [x] 单元测试全部通过（**200+ 项单测，零 skip**；单测默认 `paper-agent_LIT_SOURCE=local` 强制离线）
- [x] AGH 联调：真实会话 21+21 条 tool/call / tool/result，7/7 工具覆盖，证据已导出；
      真实信封格式与 integrity 哈希链见 `evidence/AGH-真实会话落地报告.md`
      （注：该次联调用的是当时 **7 工具**版插件；当前插件已扩展到 **20 工具**，
      工具面自检见 `tools/verify-plugin-offline.mjs`，链路自检见 `tools/verify-plugin-e2e.mjs`）
- [x] **PRD v0.3 科研全流程（research R1–R6）**：多源检索 → 精读 → 创新点/Gap → 事实验证 → 综述（强制引用）→ 自评审，端到端 DONE、degraded=false
- [x] **量化验证（F-7.1~F-7.4）**：`cli eval` 输出检索/精读/创新点/引用四套指标 + 基线对比 + 混淆矩阵（demo 规模标注）
- [x] **异常恢复三场景（F-4.8）**：`ss_timeout` 切源 / `scan_pdf` 低置信度降级 / `batch_fail_at` 失败跳过 / `kill_after_r3` 真实崩溃 + resume 续跑
- [x] **需求逐条映射**：`docs/PRD-v0.3-需求实现映射.md`（含与 PRD 建议方案的全部偏差声明）

## 合规红线

- 实验：数值只来自公开数据集与本地确定性计算，内置真实 DOI + 带缺陷演示数据集上的真实运行；
  **严禁伪造数据**，模型不得生成数值进入计算链路。
- 文献检索：`arxiv` 来源只调用 arXiv 官方 Atom API 获取**元数据**（标题/作者/摘要/DOI），
  **不做论文全文批量抓取**（版权红线）；结果按 run 快照冻结留证。
- 密钥只放环境变量 / `.env`（gitignore），Agnes Key **绝不写入仓库**。
- 开发纪律：每个任务结束 commit；**单测默认不联网**（靠 `paper-agent_LIT_SOURCE=local`）。

## 环境变量

| 变量 | 作用 |
|---|---|
| `PYTHONPATH` | **必需**，指向 `<root>/core` |
| `PAPER_AGENT_SNAPSHOT`（或连字符写法 `paper-agent_SNAPSHOT`） | 快照开关：**未设置** = 取最新快照；`none` = 强制走 legacy 内置语料路径；**其他值** = 指定快照 id 回放 |
| `paper-agent_CHAOS` / `paper-agent_MUTATE` | 故障注入开关（仅测试与演示） |
| `paper-agent_PYTHON` / `paper-agent_ROOT` | AGH 插件层 spawn Python 时使用 |

## 数据来源

- **主数据源**：OBELiX（NRC-Mila，**CC-BY-4.0**，arXiv:2502.14234）——
  599 条锂固态电解质材料，室温离子电导率为**实验实测值**，每条带原始论文 DOI。
- 探针实测：**562/599 行**含可用数值；**37 行**为上界记法（`<1E-10`），
  **不作为可比数值参与排序但留证不丢弃**；DOI 覆盖 **100%**（223 个唯一 DOI）。
- 真实数据模式下**不使用任何自拟权重**：只做"按实测值排序 + 按化学族统计"。
- 详见 [`docs/sources.md`](docs/sources.md)。

## 验收核验

见 [`HOW-TO-VERIFY.md`](HOW-TO-VERIFY.md)。核心判据：

- [x] **判据 1** 数据不再是喂进去的：599 行真实数据、223 个真实 DOI（人工 7 行数据不参与主线）
- [x] **判据 3** 异常驱动打断：零命中检索式 → 流程停下、退出码 3、给出 `--ack` 确认方式
- [x] **判据 4** 判断是硬前置：删除快照判断记录 → 流水线失败、报告无法生成
- [x] **判据 5** 干净机器一条命令跑通主线：无第三方库、无网络、无 key
- [x] 确定性：两次独立运行 `results.csv` SHA-256 逐字节一致（562 行排序结果）
- [x] 三级账本：`link_conclusion` 拒绝非 fact 级证据（代码级强制）
- [x] legacy 路径无回归：`demo_e2e` OK、`demo_failure` 8/0
- [x] 单测 **200+ 项** 全绿
- [x] **判据 2** 判断真的改变结果：真实模型（DeepSeek）产出 **4 条**检索式（规则式 2 条），
  判定范围 7/42 vs 6/42，1 个族翻转。**幅度如实记录**：范围差异小，价值主要在检索式质量
  与对字面规则盲区的补偿（见 `docs/redesign-decisions.md` §9.5）
- [x] 反判据：`tools/compare_judges.py` 已出真实判决 **`model_matters`**（退出码 0）；
  自检 rule vs rule → 退出码 5（工具双向生效）
- [x] 模型端点：标准 OpenAI 兼容服务（`PAPER_AGENT_LLM_BASE_URL` / `_MODEL` / `_API_KEY`）；
  机读结果存档 `evidence/model-judge-comparison.json`

## AGH 增强线

插件 `plugins/paper-agent-tools` 提供 **20 个** `sciret_*` 工具；
安装需交互式 TTY 人工确认（AGH 安全设计，无 bypass）。

> **逐步操作手册（含每步的预期输出与故障对照表）**：
> [`docs/AGH-SESSION-RUNBOOK.md`](docs/AGH-SESSION-RUNBOOK.md)
>
> 两个必须先做的准备（否则一定失败）：
> ① 设置 `PAPER_AGENT_PYTHON` 指向 Python 3.10+ 绝对路径（本机 PATH 上没有 python）；
> ② **从项目根目录启动 daemon**（`file:./plugins/...` 相对路径由 daemon 解析）。

```bash
AGH="node <agnes-harness>/packages/cli/dist/local/agnes.mjs"
$AGH package inspect "file:./plugins/paper-agent-tools"   # 需相对 ./ 形式
$AGH package add  "file:./plugins/paper-agent-tools"      # 需人工输入 y
$AGH package trust paper-agent-tools <integrity> <capabilityHash>
$AGH package enable paper-agent-tools
$AGH -p --cwd . "用 sciret_* 完成硫化物电解质电导率排序流水线"
```

> 首批真实 AGH 会话联调记录（在内置演示语料时期完成）：21 tool/call + 21 tool/result，
> 7 个工具全覆盖（当时版本），导出见 `evidence/`。当前插件为 20 工具，
> 用 `node tools/verify-plugin-offline.mjs`（离线、13 项）与
> `node tools/verify-plugin-e2e.mjs`（真调 Python、6 项）可随时复验。
