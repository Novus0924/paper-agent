# paper-agent

**2026 江苏省 AI + 科学与工程创新实践黑客松｜科研 Agent 与 Harness 工程** 参赛作品。

一套**可审计、可复现、可故障恢复**的科研流水线系统：
输入是**真实公开数据集**（OBELiX，599 条锂固态电解质实验实测离子电导率，
每条带原始论文 DOI），而不是人工预制的演示数据；
每一步产出都留痕、每条结论都绑定证据、每次复算都逐字节一致。

> **五步流水线**：文献腿 → 数据清洗 → 实验执行 → 复现验证 → 报告汇总
> 全链路做到：**任务状态可观测 · 每条结论可溯源至 DOI 或带 SHA-256 的产物文件 ·
> 失败可重试 / 降级 / 断点续跑 · 判断与结论严格分级**。

---

## 改造状态（2026-10-02）

本仓库正在从"演示原型"改造为"真实数据流水线"。**已完成的决定与理由见
[`docs/redesign-decisions.md`](docs/redesign-decisions.md)**（含被否决方案、差异清单、
红线修订、验收判据）。当前进度：

| 能力 | 状态 |
|---|---|
| 真实数据集接入（OBELiX 599 行，DOI 100% 覆盖） | ✅ 已完成 |
| 冻结输入快照（强校验 + 判断批次自包含） | ✅ 已完成 |
| 三级信任模型（事实 / 判断 / 结论） | ✅ 已完成 |
| 真实数据清洗（上界值留证 / 缺失归类 / 重复标注） | ✅ 已完成 |
| 离线主线端到端（无需联网 / key / 第三方库） | ✅ 已完成 |
| **模型驱动的检索与相关性判断** | ⬜ 第二批（当前为可见规则式 bootstrap） |
| **联网文献腿（标题/作者等元数据）** | ⬜ 第二批 |

> 诚实声明：当前仓库内的"判断"由**可见规则**产生（`producer=bootstrap_rule_v1`，
> 规则全部写在 `tools/freeze_snapshot.py` 源码里），
> 目的是先把"判断留痕 → 报告闸门 → 被排除项可反驳"这套机制用真实数据验证一遍。
> 模型接入后替换的是**同一个函数位置**，数据契约不变。详见 `docs/ai_disclosure.md`。

## 双轨设计

| | **主线（稳定轨）** | **增强线（惊艳轨）** |
|---|---|---|
| 依赖 | 无（不需要 AGH / key / 网络 / 第三方库） | AGH + 模型 key + 网络 |
| 输入 | 冻结快照（`snapshots/`，已入库） | 现场检索 |
| 展示 | **可信性**：一键跑通、逐字节复现、证据可回查 | **智能性**：真实检索与判断（第二批） |
| 演示 | `demo/demo_mainline.sh` | 待第二批 |

两条轨**共用同一套 Python 核心与同一套证据账本**，区别只在"输入是快照还是现搜"。

## 目录结构

```
paper-agent/
├── README.md                     # 本文件
├── HOW-TO-VERIFY.md              # 验收核验手册（逐条命令 + 哈希比对）
├── docs/
│   ├── redesign-decisions.md     # 改造决定记录（权威设计文档）
│   ├── ai_disclosure.md          # AI 使用边界声明（三级模型口径）
│   ├── sources.md                # 数据来源声明
│   └── diagrams/                 # 3 张竖版流程图（SVG）
├── core/paper_agent/             # Python 核心（零第三方依赖）
│   ├── state.py                  #   有限状态机 + run 生命周期
│   ├── provenance.py             #   三级证据账本（fact / judgment / conclusion）
│   ├── snapshot.py               #   冻结输入快照（强校验 + 判断批次自包含）
│   ├── sources.py                #   外部数据源适配（列名归一 / 值分类）
│   ├── chaos.py                  #   故障注入
│   ├── steps.py                  #   五步调度（快照主路径 + legacy 回退路径）
│   ├── verify.py                 #   P4 复现验证器（递归容差比对）
│   ├── report.py                 #   P5 报告生成（判据 4 硬前置）
│   └── cli.py                    #   命令行入口（stdout 单 JSON）
├── experiments/arrhenius_rank.py # 零依赖确定性实验（双 schema 自适应）
├── tools/
│   ├── freeze_snapshot.py        # 把一轮检索+判断冻结成输入快照
│   └── probe_obelix.py           # 数据源技术探针（只读、可离线复跑）
├── data/
│   ├── external/obelix/all.csv   # OBELiX 数据快照（599 行，CC-BY-4.0）
│   ├── literature.json           # legacy 演示语料（降级路径，不参与主线）
│   └── conductivity_raw.csv      # legacy 演示数据（降级路径，不参与主线）
├── snapshots/<snapshot_id>/      # 冻结输入快照（已入库，供离线主线使用）
├── runs/<run_id>/                # 运行实例产物（gitignore；每个 run 完全隔离）
├── demo/
│   ├── demo_mainline.sh          # ★ 真实数据主线（离线回放 + 判据 4 实测）
│   ├── demo_e2e.sh               # legacy 路径端到端 + 确定性核验
│   └── demo_failure.sh           # legacy 路径四大故障恢复用例
├── tests/                        # unittest 套件（6 文件，88 用例）
├── plugins/paper-agent-tools/    # AGH 扩展：7 工具（JS 薄壳）
└── audit-pack-template/          # 审计交付包模板
```

## 环境要求

- **Python 核心层**：Python 3.10+，**零第三方依赖**（仅标准库），跨机器可复现。
- **Demo 脚本**：`bash` + `sha256sum`（Windows 用 Git Bash）。
- **AGH 增强线**（可选，第二批用）：Node ≥24 + 模型 API Key。

## 快速上手

```bash
cd paper-agent
export PYTHONPATH="$PWD/core"          # Windows: set PYTHONPATH=%cd%\core

# 一键验收（推荐先跑这条）
bash demo/demo_mainline.sh             # 真实数据主线：14 项断言，末尾 DEMO_MAINLINE_OK
```

手动逐步：

```bash
# 1) 跑完整五步（自动使用最新快照；无需联网）
python -m paper_agent.cli run-all --goal "sulfide solid electrolyte ionic conductivity ranking"

# 2) 查看状态 / 验证 / 报告
python -m paper_agent.cli status  --run <RUN_ID>
python -m paper_agent.cli verify  --run <RUN_ID>
python -m paper_agent.cli report  --run <RUN_ID>     # → runs/<RUN_ID>/report.md

# 3) 回查证据（fact 级含哈希，judgment 级含对象与理由）
python -m paper_agent.cli cite --run <RUN_ID> --ev EV-0001
python -m paper_agent.cli cite --run <RUN_ID>                 # 列出全部
```

重新生成一份快照（需要 `data/external/obelix/all.csv`，无需联网）：

```bash
python tools/freeze_snapshot.py --goal "sulfide solid electrolyte ionic conductivity ranking"
```

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
- [x] **判据 4** 判断是硬前置：删除快照判断记录 → 流水线失败、报告无法生成
- [x] **判据 5** 干净机器一条命令跑通主线：无第三方库、无网络、无 key
- [x] 确定性：两次独立运行 `results.csv` SHA-256 逐字节一致（562 行排序结果）
- [x] 三级账本：`link_conclusion` 拒绝非 fact 级证据（代码级强制）
- [x] legacy 路径无回归：`demo_e2e` OK、`demo_failure` 8/0
- [x] 单测 **88/88** 全绿
- [ ] **判据 2** 判断真的改变结果（两个不同问题产出不同检索式与集合）——第二批随模型接入实测
- [ ] **判据 3** 异常驱动打断（零命中 / DOI 对不上 / 命中率反常）——第二批
- [ ] 反判据：换回规则式判断，若结论几乎不变则说明模型是装饰品——第二批

## 合规红线

- 数值只来自公开数据集与本地确定性计算；**严禁伪造数据**，模型不得生成数值进入计算链路。
- **不做论文全文批量抓取**（版权红线）。
- 密钥只放环境变量 / `.env`（gitignore），**绝不入库**。
- 开发纪律：每个任务结束 commit；主线测试不联网。

## AGH 增强线（第二批）

插件 `plugins/paper-agent-tools` 提供 7 个 `sciret_*` 工具；
安装需交互式 TTY 人工确认（AGH 安全设计，无 bypass）：

```bash
AGH="node <agnes-harness>/packages/cli/dist/local/agnes.mjs"
$AGH package inspect "file:./plugins/paper-agent-tools"   # 需相对 ./ 形式
$AGH package add  "file:./plugins/paper-agent-tools"      # 需人工输入 y
$AGH package trust paper-agent-tools <integrity> <capabilityHash>
$AGH package enable paper-agent-tools
$AGH -p --cwd . "用 sciret_* 完成硫化物电解质电导率排序流水线"
```

> 首批真实 AGH 会话联调记录（在内置演示语料时期完成）：21 tool/call + 21 tool/result，
> 7 个工具全覆盖，导出见 `evidence/`。
