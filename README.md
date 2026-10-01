# paper‑agent

**2026 江苏省 AI + 科学与工程创新实践黑客松｜科研 Agent 与 Harness 工程** 参赛作品。

一套**可审计、可复现、可故障恢复**的科研智能体流水线系统：基于
**Agnes Harness（AGH，https://github.com/AgnesAI‑Labs/agnes‑harness）** 作为智能体
执行底座，通过插件化工具链实现完整科研工作流，所有输出具备证据溯源与机器可校验能力。

> 目标产物：`paper‑agent`，驱动**五步标准化科研流水线**：
> 文献检索 → 数据清洗 → 真实实验执行 → 复现验证 → 报告汇总；
> 全链路做到**任务状态可观测、每一条结论可溯源至文献 DOI 或带 SHA‑256 校验的产物文件、
> 任务失败支持重试 / 降级 / 断点续跑**。

---

## 六层系统架构

```
L6 交互层    AGH CLI / Web Workbench / 审计取证导出
L5 Agent层   AGH 会话内科研规划协议｜系统提示驱动大模型编排调用工具
L4 记忆层    runs/<run_id>/ 运行产物快照｜state.json 状态｜事件&证据双账本
L3 可信框架  证据溯源先行｜实验复现验证｜审计出口（导出完整可交付包）
L2 Harness层 AGH 原生能力 + paper-agent 核心（有限状态机、事件账本、步骤调度）
L1 工具执行层 paper-agent-tools JS 薄壳插件 → Python 核心业务逻辑 → 实验子进程
```

数据流单向：`L6 → L5 → L2 → L1`；产物向上回流经 `L3` 登记证据，再写入 `L4`。

## 目录结构

```
paper-agent/
├── README.md                     # 本文件
├── HOW-TO-VERIFY.md             # 验收核验操作手册 + 哈希比对命令
├── plugins/paper-agent-tools/   # AGH 扩展：7 科研工具（JS 薄壳）
│   ├── package.json
│   └── index.mjs
├── core/paper_agent/            # Python 核心业务（零第三方依赖）
│   ├── __init__.py              #   根路径探测 PAPER_AGENT_ROOT
│   ├── state.py                 #   有限状态机 + run 生命周期 + 状态持久化
│   ├── provenance.py            #   证据账本 + 结论‑证据绑定 + 引文渲染
│   ├── chaos.py                 #   故障注入（重试/降级/校验失败场景）
│   ├── steps.py                 #   五步 P1-P5 调度 + 重试‑降级 + 工具调用留痕
│   ├── verify.py                #   P4 复现验证器（递归容差比对）
│   ├── report.py                #   P5 报告生成（从真实产物提取数据）
│   └── cli.py                   #   命令行统一入口，JSON 标准化输出
├── experiments/
│   └── arrhenius_rank.py        # 零依赖确定性实验脚本（电导率打分排序）
├── data/
│   ├── literature.json          # 内置真实 DOI 文献语料库（5 篇）
│   └── conductivity_raw.csv     # 带缺陷原始实验数据集（utf-8 BOM）
├── runs/<run_id>/               # 运行实例产物（gitignore 忽略；每个 run 完全隔离）
├── demo/
│   ├── demo_e2e.sh             # 端到端正常流程 + 确定性核验
│   └── demo_failure.sh         # 四大故障恢复验收用例自动化
├── tests/                        # unittest 套件（4 文件，36 用例）
└── audit-pack-template/          # 审计交付包模板
```

## 环境要求

- **Python 核心层**：Python 3.10+，**零第三方依赖**（仅标准库），保障跨机器可复现。
- **AGH 插件层**：Node 18+；AGH 源码构建与真实会话联调需要比赛发放的模型 API Key。
- **Demo 脚本**：`bash` + `sha256sum`（Windows 用 Git Bash / WSL；注意 npm shim 拉起
  wsl.exe 可能被安全策略拦截，构建后直接 `node <入口.js>` 调用）。

## 快速上手

```bash
cd paper-agent
export PYTHONPATH=core            # Windows: set PYTHONPATH=core
python -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity ranking"
python -m paper_agent.cli run-all --run <RUN_ID>
python -m paper_agent.cli verify --run <RUN_ID>
python -m paper_agent.cli report --run <RUN_ID>
python -m paper_agent.cli cite --run <RUN_ID> --ev EV-0001
```

或直接跑演示脚本：

```bash
bash demo/demo_e2e.sh       # 正常路径 + 实验确定性 SHA-256 核验
bash demo/demo_failure.sh   # 四大故障用例（A 重试 / B 降级 / C resume / D 复现 FAIL）
```

## 数据来源声明

- `data/literature.json` 内置 5 篇公开真实 DOI 文献（LGPS / Kato 综述 / LLZO /
  LiPON / Li6PS5X argyrodite），DOI 可在线解析。
- **所有数值均标注 `as‑reported`**，用于黑客松工程演示；**正式科研使用务必核对原始
  论文原文**。严禁伪造实验数据（黑客松直接取消参赛资格行为）。

## 复现指引（确定性契约）

相同输入两次执行实验脚本，`results.csv` 逐字节一致；核验命令见
[HOW‑TO‑VERIFY.md](HOW‑TO‑VERIFY.md)。唯一可变字段 `summary.json.generated_at`
（UTC 时间戳）在校验环节被排除，不参与哈希比对。

## AGH 联调（拿到 API Key 后执行）

```bash
pnpm install --frozen-lockfile
pnpm --filter @agnes/cli build:local
node packages/cli/dist/local/agnes.mjs serve
agnes plugins install file:./plugins/paper-agent-tools
agnes plugins trust ext:paper-agent/tools
agnes plugins enable ext:paper-agent/tools
agnes -p "你的科研目标 prompt"
agnes export SESSION_ID --format agnes -o session.jsonl
```

联调闸门：`session.jsonl` 至少包含 ≥6 条连续 `tool_use` / `tool_result` 结构化交互记录。

## 验收核对清单

- [x] `run-all` 正常路径：五步全部 DONE，degraded=false，verification PASS
- [x] 实验确定性：两次执行 results.csv SHA-256 完全相同
- [x] 用例 A `p1_fail_first`：重试 1 次，最终 DONE，degraded=false
- [x] 用例 B `p1_fail_all`：3 次重试耗尽触发降级；DONE，degraded=true，events 含 degrade
- [x] 用例 C：P2 完成后 resume，只运行剩余步骤，已 DONE 步骤直接复用
- [x] 用例 D `mutate_summary`：verification=FAIL，P4 FAILED，顶层 run FAILED；5 项校验可查
- [x] report.md 每条结论携带 `[EV-XXXX]` 证据标记；`sciret_cite` 可回查 DOI / SHA-256
- [x] 单元测试四文件全部通过（36/36）
- [ ] AGH 联调：`session.jsonl` ≥6 条连续 tool_use/tool_result（拿到密钥后）

## 合规红线

- 实验：内置真实 DOI + 带缺陷演示数据集上的真实运行；不做论文全文批量抓取。
- Agnes Key 只放环境变量，**绝不写入仓库**。
- 开发纪律：每个任务结束 commit；测试不联网。
