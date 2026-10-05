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
├── core/paper_agent/            # Python 核心业务（25 模块，零第三方依赖）
│   ├── __init__.py              #   根路径探测 PAPER_AGENT_ROOT
│   ├── util.py                  #   共享 IO/哈希工具（全项目唯一实现）
│   ├── security_scan.py         #   安全防御：run_id 白名单校验 + 提示注入检测
│   ├── state.py                 #   有限状态机 + run 生命周期 + 状态持久化（双工作流）
│   ├── provenance.py            #   三级证据账本（fact/judgment）+ 哈希链防篡改 + 结论绑定
│   ├── chaos.py                 #   故障注入（重试/降级/校验失败/进程崩溃场景）
│   ├── steps.py                 #   materials 五步 P1-P5 调度 + 重试‑降级 + 工具留痕
│   ├── research.py              #   research 六步 R1-R6 科研流水线（检索→精读→拆解→验证→写作→评审）
│   ├── litsearch.py             #   多源学术检索（arXiv/S2/OpenAlex/CrossRef）+ 注入标记
│   ├── pdfparse.py              #   零依赖 PDF 解析（文本层/OCR 降级，失败原因留痕）
│   ├── analyze.py               #   创新点拆解 / 技术脉络 / Research Gap
│   ├── factcheck.py             #   事实验证（引用/数据一致性/矛盾检测）
│   ├── writing.py / review.py   #   综述写作 + 模拟自评审
│   ├── evaluate.py              #   F-7 量化评估（P/R/NDCG + 基线对比 + 混淆矩阵）
│   ├── judge.py                 #   可插拔判断器（RuleJudge / ModelJudge + 反判据对比）
│   ├── freezing.py / snapshot.py / sources.py / anomaly.py / llm.py
│   │                            #   冻结快照三段式 / 快照留证 / 检索源 / 领域异常 / LLM 传输
│   ├── materials_snapshot.py    #   novus 冻结快照版 materials 流水线（可切换保留）
│   ├── verify.py                #   P4 复现验证器（递归容差比对）
│   ├── report.py                #   P5 报告生成（账本完整性运行时门禁 + 双工作流章节）
│   └── cli.py                   #   命令行统一入口（19 子命令），JSON 标准化输出
├── experiments/
│   └── arrhenius_rank.py        # 零依赖确定性实验脚本（电导率打分排序；自包含不经 util）
├── data/
│   ├── literature.json          # 内置真实 DOI 文献语料库（5 篇）
│   └── conductivity_raw.csv     # 带缺陷原始实验数据集（utf-8 BOM）
├── runs/<run_id>/               # 运行实例产物（gitignore 忽略；每个 run 完全隔离）
├── demo/
│   ├── install_plugin.sh          # ★ AGH 插件一键安装（幂等；首选入口）
│   ├── README.md                  # demo 脚本索引
│   ├── demo_e2e.sh               # 端到端正常流程 + 确定性核验
│   ├── demo_failure.sh            # 四大故障恢复验收用例自动化
│   ├── demo_trust.sh              # 信任机制现场演示（账本篡改/伪造验证双拦截）
│   ├── demo_agh_session.sh        # AGH 真实会话联调（装好插件后用）
│   ├── reinstall_plugin.ps1       # Windows 自动化重装（参数化；需 -Agh <agnes.mjs>）
│   └── run_agh_install.cmd        # 纯 cmd 最小安装（需 agnes.mjs 路径参数）
├── tools/                        # 无需 TTY 的插件自检脚本（offline / e2e，见 docs/AGH插件安装指南.md）
├── tests/                        # unittest/pytest 套件（9 文件，152 用例，默认离线）
└── audit-pack-template/          # 审计交付包模板
```

## 环境要求

- **Python 核心层**：Python 3.10+，**零第三方依赖**（仅标准库），保障跨机器可复现。
- **AGH 插件层**：Node **≥ 24**（AGH 运行底座硬要求，与插件 `package.json` 的 `engines` 一致）；AGH 源码构建与真实会话联调需要比赛发放的模型 API Key。
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
bash demo/demo_trust.sh <RUN_ID>  # 信任机制现场演示：账本篡改与伪造验证双双被拦截
```

## 数据来源声明

- `data/literature.json` 内置 5 篇公开真实 DOI 文献（Kamaya LGPS / Kato 硫化物全
  固态电池研究论文 / Murugan LLZO / Bates LiPON / Deiseroth Li6PS5X argyrodite），
  标题、作者与 DOI 均可在线解析核对。
- **所有数值均标注 `as‑reported`**，用于黑客松工程演示；**正式科研使用务必核对原始
  论文原文**。严禁伪造实验数据（黑客松直接取消参赛资格行为）。

## 复现指引（确定性契约）

相同输入两次执行实验脚本，`results.csv` 逐字节一致；核验命令见
[HOW‑TO‑VERIFY.md](HOW‑TO‑VERIFY.md)。唯一可变字段 `summary.json.generated_at`
（UTC 时间戳）在校验环节被排除，不参与哈希比对。

## AGH 联调（已真实跑通，2026-10-02）

> 📦 **从零安装插件**：克隆本仓库后想快速把插件装进 AGH，请先看
> [docs/AGH插件安装指南.md](docs/AGH插件安装指南.md)（含全部已知坑位与故障排查表；
> 仓库 `tools/` 下另有两个无需 TTY 的插件自检脚本）。
> 💬 **装好之后怎么用**：会话提示词模板见 [docs/使用提示词模板.md](docs/使用提示词模板.md)。

实际链路（与 AGH 构建产物的真实 CLI 对齐）：

```bash
# ★ 首选：一键安装（幂等，可重复运行；自动探测路径/重启 daemon/提取两个哈希，
#   仅「安装确认」一步需要你在真实终端里敲 y）：
bash demo/install_plugin.sh [agnes.mjs 绝对路径]
bash demo/install_plugin.sh --check      # 只做只读预检

# 等价手动链路（install_plugin.sh 内部即此流程）：
AGH="node <agnes-harness>/packages/cli/dist/local/agnes.mjs"  # 必须从项目根、相对 ./ 形式
$AGH package inspect "file:./plugins/paper-agent-tools"
# package add 需交互式 TTY 人类确认（AGH 安全设计，无 bypass）
$AGH package add "file:./plugins/paper-agent-tools"
# capabilityHash 不在 inspect 输出里，从审计日志取：~/.agh/profiles/*/.agnes-package-audit.jsonl
$AGH package trust paper-agent-tools <integrity> <capabilityHash>
$AGH package enable paper-agent-tools                     # desired=enabled actual=running
$AGH -p --cwd "$PWD" "用 sciret_* 完成…流水线"             # 需真实终端（无头环境会挂起）
$AGH export <SESSION_ID> --format agnes -o evidence/session-full.jsonl
```

联调闸门：会话导出至少 ≥6 条 `tool/call` / `tool/result` 结构化交互记录；
历史联调实测 **21 + 21 条，7 个 `sciret_*` 工具全部出现**（含 `sciret_resume` 的
`kill_after_p2` 真实进程崩溃 + 断点续跑演示）。

**证据文件状态（如实声明）**：`evidence/` 目录当前仅含 README，上述会话导出
`session.jsonl` / `session-full.jsonl` 未随本仓库快照交付；按上方命令在真实 daemon
会话后重新导出即可再生成（或按 `demo/demo_agh_session.sh` 全流程重放），导出后经
`audit-pack-template/build_audit_pack.sh` 归集。评审时若 `evidence/` 缺该文件，
以 `demo/` 三脚本与本 README 其余命令的现场重放为准。

## 验收核对清单

- [x] `run-all` 正常路径：五步全部 DONE，degraded=false，verification PASS
- [x] 实验确定性：两次执行 results.csv SHA-256 完全相同
- [x] 用例 A `p1_fail_first`：重试 1 次，最终 DONE，degraded=false
- [x] 用例 B `p1_fail_all`：3 次重试耗尽触发降级；DONE，degraded=true，events 含 degrade
- [x] 用例 C：P2 完成后 resume，只运行剩余步骤，已 DONE 步骤直接复用
- [x] 用例 D `mutate_summary`：verification=FAIL，P4 FAILED，顶层 run FAILED；5 项校验可查
- [x] 用例 E2/E3 `kill_after_p2`：子进程真实被 `os._exit(137)` 杀死（run-all 与 run-step 双路径），账本完整，resume 续跑到 DONE
- [x] P5 报告终态幂等复用（重复调用不抛 StateError）
- [x] report.md 每条结论携带 `[EV-XXXX]` 证据标记；`sciret_cite` 可回查 DOI / SHA-256
- [x] 单元测试全部通过（152/152，含 14 项安全防御专项测试与 1 项 P5 幂等门禁回归测试）
- [x] 信任机制现场演示脚本 `demo/demo_trust.sh`：账本篡改 → 报告拒绝；伪造 verification →
  P4 闸门拒绝（`TRUST_DEMO_OK`，退出码 0）
- [x] AGH 工具面覆盖双工作流：`sciret_plan` 支持 `--workflow research`，
  `sciret_run_step` 支持 R1_search..R6_review 六步单步驱动
- [x] 评审要点逐条证据映射：`docs/评审要点与证据对照映射.md`（含已知缺口诚实声明）
- [x] AGH 联调方法与闸门就绪（`demo/demo_agh_session.sh` + 插件 7 工具）；会话导出
  证据未随本仓库快照交付，再生成方式见上方「证据文件状态」声明

## 合规红线

- 实验：内置真实 DOI + 带缺陷演示数据集上的真实运行；不做论文全文批量抓取。
- Agnes Key 只放环境变量，**绝不写入仓库**。
- 开发纪律：每个任务结束 commit；测试不联网。
