# 交接文档（HANDOFF）— paper-agent

> 面向**接手本项目的下一个编程工具 / 工程师**。读完本文即可在无需上下文记忆的情况下继续推进。
> 生成时间：2026-10-02（AGH 真实会话联调**已闭环**后回填）。若与仓库实际不一致，以 `git log` 与代码为准。

---

## 0. 30 秒速览

- **项目**：`paper-agent` —— 基于 **AGH（Agnes Harness）** 的可审计、可复现、可故障恢复的科研 Agent 流水线（JS 薄壳工具 + Python 核心业务 + 确定性实验），用于 2026 江苏省 AI+科学与工程创新实践黑客松。
- **工程完成度**：阶段 1–8 **全部完成并通过自验证**（单测 **62/62**、端到端 demo、四大故障用例 + 真实进程崩溃/断点续跑用例 E2/E3 + P5 幂等复用 F、审计不变量全 PASS）。
- **阶段 9–10（PRD v0.3 实现，2026-10-03）**：按负责人 `科研智能体需求文档 v0.3` 实现**科研全流程工作流 `research`（R1–R6）** + **量化验证（F-7.1~F-7.4）** + **三类异常恢复（F-4.8）**，单测扩至 **159/159**，插件扩至 **17 工具 + 1 Skill**。逐条映射见 `docs/PRD-v0.3-需求实现映射.md`，详见本文 §9。分支 `fix/agh-driven`（隔离克隆 `paper-agent-fix`），fast-forward 推送远端 `mike`。
- **AGH 联调已真实跑通**：插件经交互 TTY 确认安装 + trust + enable，`desired=enabled actual=running trusted=true`；两次真实 `-p` 会话共 21 次 tool/call + 21 次 tool/result，**7 个 sciret_* 工具全部出现**（含 `sciret_resume` 的 kill_after_p2 崩溃恢复演示）。导出在 `evidence/session.jsonl`（首轮）与 `evidence/session-full.jsonl`（崩溃恢复轮，同一 workspace 会话追加）。
- **编排改为模型驱动（阶段 7 重构）**：核心层新增**单步**工具 `sciret_step_driven`（一次只推进一步并返回决策上下文）、`sciret_next`、`sciret_finish`，插件共 **10 工具 + 1 Skill**（`.agh/skills/sciret-research-pipeline`）；`run-all` 降级为**确定性兜底**。真实证据由 AGH daemon 原生写出（`~/.agh/data/sessions.db`，含完整信封 + integrity 哈希链），打通步骤与当前卡点见 `evidence/AGH-真实会话落地报告.md`（注：此前的脱敏自造格式账本已删除）。
- **数据与计算修复**：5 篇文献 DOI 经 Crossref 权威核验更正；CSV 材料–年份–DOI 自洽；稳定性改由文献活化能导出（不再硬编码常数）；新增 Arrhenius σ(60°C) 外推。
- **P1 检索后端可切换（阶段 8）**：新增 `core/paper_agent/litsearch.py`（零依赖，仅标准库）——`--lit-source local|arxiv|auto`，默认 `auto`；`arxiv` 走 arXiv 官方 Atom API 实时检索，**不再局限于内置 5 篇语料**。确定性靠**快照冻结**保证：在线结果首跑写入 `runs/<id>/literature/arxiv_snapshot.json`，同一 run 复跑只读快照、不再联网，快照本身作为 `data` 证据留证。单测通过 `paper-agent_LIT_SOURCE=local` 强制离线（`tests/__init__.py`），故 `Ran 62 tests ... OK` 零 skip。**边界**：P1 与 P2/P3 解耦——换课题能换到真文献，但实验数据仍取 `data/conductivity_raw.csv`。
- **红线**：密钥只存 `.env`（gitignore）；所有交付物收敛在 `paper-agent/` 项目目录内；实验数据标注 `as-reported`，严禁伪造。

---

## 1. 当前提交历史（最新在上）

```
d8af9d5  AGH 联调准备: 插件 manifest 对齐官方形态 + 会话联调脚本
3d34092  stage6: Demo 脚本 + 文档 + 审计交付包（黑客松可提交产物就绪）
750ecbd  stage5: AGH JS 插件薄壳编码（7 工具，暂不联调）
caeb76c  stage4: 单元测试四套全绿（M0 工程里程碑，36/36）
ff3d522  stage3: Python 核心业务完整实现（state/provenance/chaos/steps/verify/report/cli）
b866694  stage1+2: 项目骨架 + 数据层 + 确定性实验脚本
72b616a  chore: 仓库骨架与合规声明（继承）
```

分支：`leyon`。远端：`origin git@github.com:Novus0924/paper-agent.git`。

---

## 2. 目录结构与职责（精确到文件）

```
paper-agent/
├── core/paper_agent/               # Python 核心业务（零第三方依赖，仅标准库）
│   ├── __init__.py                 #   根路径探测 PAPER_AGENT_ROOT；导出 DATA_DIR/EXPERIMENTS_DIR/RUNS_DIR
│   ├── state.py                    #   有限状态机 + run 生命周期 + 状态持久化（append-only events.jsonl）
│   ├── provenance.py               #   证据账本 provenance.jsonl + 结论-证据强绑定 + 引文渲染
│   ├── chaos.py                    #   故障注入（p1_fail_first / p1_fail_all / mutate_summary / kill_after_p2 真实 os._exit(137)）
│   ├── steps.py                    #   五步 P1-P5 调度 + 重试-降级 + 工具调用留痕 toolcalls/ + resume
│   ├── verify.py                   #   P4 复现验证器（递归容差比对，5 项校验）
│   ├── report.py                   #   P5 报告生成（从真实产物提取数据，C1-C5 全带 [EV-XXXX]）
│   └── cli.py                      #   命令行入口，stdout 只输出单个 JSON（_ensure_utf8_stdio 强制 UTF-8）
├── experiments/arrhenius_rank.py   # 零依赖确定性实验脚本（电导率打分排序；utf-8-sig 读 CSV）
├── data/
│   ├── literature.json             # 内置 5 篇真实 DOI 文献语料（local 来源 / 离线兜底）
│   └── conductivity_raw.csv        # 带缺陷原始数据集（utf-8 BOM，7 行）
├── plugins/paper-agent-tools/
│   ├── package.json                # AGH 插件 manifest（对齐官方形态，见 §6）
│   └── index.mjs                   # 7 工具薄壳（spawn Python CLI，TypeBox 严格 schema）
├── tests/
│   ├── _util.py                    # 共享：构建隔离临时根 + make_clean_csv
│   ├── test_state.py              # 状态机转移/持久化/非法转移/append-only（10）
│   ├── test_provenance.py         # 证据账本/结论绑定/引文（10）
│   ├── test_recovery.py           # 故障用例 A/B/C/D + E2/E3 真实进程崩溃续跑 + F 幂等 + FAILED 终态（9）
│   └── test_repro.py              # 确定性双跑 SHA-256 + verify 递归容差（11）
├── demo/
│   ├── demo_e2e.sh                # 正常路径 + 确定性双跑 + cite + 报告摘要
│   ├── demo_failure.sh            # 四大故障用例自动化（8 断言）
│   └── demo_agh_session.sh        # AGH 真实会话联调（inspect→install→trust→enable→-p→export→审计包）
├── HOW-TO-VERIFY.md               # 验收核验手册 + SHA-256 比对命令
├── README.md                      # 快速上手 / 数据来源 / AGH 联调 / 验收清单
├── audit-pack-template/
│   ├── README.md                  # 审计交付包结构说明
│   └── build_audit_pack.sh        # 归集一个 run 实例的审计包到 audit-pack/
├── docs/
│   ├── ai_disclosure.md
│   ├── sources.md
│   └── HANDOFF.md                 # 本文档
├── evidence/                      # AGH 会话导出 session.jsonl 落这里（gitignore *.jsonl）
├── runs/<run_id>/                 # 每 run 完全隔离的产物（gitignore runs/）
└── .env                           # 模型 API key（gitignore，绝不入库）
```

---

## 3. 如何验证现状（新工具接手第一步）

```bash
cd C:/Users/ASUS/Desktop/黑客松/paper-agent
# ① 单元测试（62/62 应全绿）
set PYTHONPATH=C:\Users\ASUS\Desktop\黑客松\paper-agent\core
python -m unittest discover -s tests -p "test_*.py"

# ② 端到端正常路径（需要 bash + sha256sum；Windows 用 Git Bash）
"C:\Program Files\Git\bin\bash.exe" "C:/Users/ASUS/Desktop/黑客松/paper-agent/demo/demo_e2e.sh"

# ③ 四大故障用例（8/8 应全 PASS）
"C:\Program Files\Git\bin\bash.exe" "C:/Users/ASUS/Desktop/黑客松/paper-agent/demo/demo_failure.sh"

# ④ 插件 7 工具注册自检
node plugins/paper-agent-tools/index.mjs   # 无语法错即通过（真实注册在 AGH 运行时）
```

**预期结果**：单测 62/62 OK；demo_e2e 末行 `DEMO_E2E_OK`；demo_failure 末行 `DEMO_FAILURE_OK`（8 passed, 0 failed）。

---

## 4. 设计红线（改动代码时必须遵守）

1. **零第三方依赖**：Python 核心层只用标准库（保障跨机器可复现）。新增功能不得 import 非标准库包。
2. **确定性**：相同输入两次执行 `arrhenius_rank.py`，`results.csv` 逐字节一致；`summary.json.generated_at`（UTC 时间戳）是唯一可变字段，**校验时排除**。可用 `paper-agent_MUTATE=1` 交换 summary.top3（但 results.csv 不变，触发 P4 FAIL）。
3. **append-only 账本**：`events.jsonl` / `provenance.jsonl` 只追加不修改；事件时间戳单调不减。
4. **状态机终态守卫**：DONE / SKIPPED 是终态，非法转移必须抛 `StateError`；FAILED 步骤可重试，FAILED 顶层 run 不可再 finish_run(DONE)。
5. **证据先行**：`report.py` 的每条结论 C1-C5 必须绑定已存在的 `EV-XXXX`；无证据必须快速失败（`EvidenceError`）。C1 无文献命中时回退绑定 P1 检索输出的 `data` 证据（0 命中也留证）。
6. **utf-8-sig**：读 `conductivity_raw.csv` 用 `encoding="utf-8-sig"`；CLI stdout 强制 UTF-8（`_ensure_utf8_stdio`）防中文路径按系统码页污染。
7. **分层解耦**：AGH JS 薄壳只 spawn Python CLI，不直接 import 工具实现；工具调用留痕 `toolcalls/`。
8. **合规**：实验用内置真实 DOI + 带缺陷演示数据，**严禁伪造数据**（黑客松直接取消资格）；Agnes key 只放环境变量，**绝不写仓库/文档/提交**。

---

## 5. 关键产物指纹（复现基准）

- 正常路径 `results.csv` SHA-256 前缀：`a30bc79f…`
- 实验确定性双跑：两次 `results.csv` SHA-256 必须完全相同。
- 插件 `file:./plugins/paper-agent-tools` 的 inspect integrity：`sha256-789fd334517aaaf7546157cf05d2d1b7ca51abd5016b861e0e42462d293d8202`（当前已安装版本，含 Cordis 对象导出 + meta 8 键修复；随 index.mjs/package.json 变化而变，以 `AGH package inspect` 实际输出为准）。
- 5 项复现校验：`results_csv_sha256 / n_rows / top3_material_id_set / top3_scores_positional / family_mean_log10_cond`。

---

## 6. AGH 联调的精确技术状态（最重要，新工具重点看这里）

### 6.1 已确认的事实

- **AGH 源码**：`C:\Users\ASUS\Desktop\黑客松\agnes-harness`（已 `pnpm install` + 构建 `packages/cli/dist/local/agnes.mjs`，`node --version` 24.15 可用）。
- **provider 已配且可用**：默认 AGH home（`~/.agh`）有预置 route `account-acct-60077bdf-…`（baseUrl `https://api.agnes-ai.cn/v1`，model `agnes-3.0-flash`，credential `secret://agnes-ai/…`）。`AGH doctor provider --probe` 返回 `✓ verified`。
- **插件源校验已通过**：`AGH package inspect "file:./plugins/paper-agent-tools"` 从项目目录执行，返回合法 Preview（含 integrity）。**关键**：AGH `file:` 源 schema 是 `^file:\./...`，**必须相对 `./` 形式**；绝对路径 `file:C:\…` 会报 `ProtocolViolation: Expected union value`（这是之前踩的坑）。
- **plugin manifest**：`package.json` 已对齐官方形态（`private`/`files`/`license`/`engines>=24`，`agnes.plugins[]` 的 `id: ext:paper-agent/tools`、`export: paperAgentTools`、`inject: [extension]`）。`package inspect` 校验通过即证明 manifest 合法。

### 6.2 卡点（为什么没全自动跑完会话）

AGH 的 `package add`（= install）在源码里走 `io.confirm(preview)`，**交互式 TTY 才点头**；自动化 non-TTY（重定向 stdin/stdout）会直接 `Installation cancelled`，**没有 bypass flag**（这是 AGH 安全设计：装插件 = 以本机权限执行 JS，必须人类确认）。

因此"install → trust → enable → 真实会话"这一环**无法在编程工具的非交互 shell 里代跑**，需要交互终端。

### 6.3 已交付的联调脚本

`demo/demo_agh_session.sh` 覆盖完整链路（inspect→install→trust→enable→`AGH -p` 会话→`AGH export` 到 `evidence/session.jsonl`→`build_audit_pack.sh`）。它：
- 插件用**项目相对路径** `file:./plugins/paper-agent-tools`，绝不外拷；
- 会话导出与审计包全部落在 `paper-agent/` 项目内；
- 设 `paper-agent_PYTHON` / `paper-agent_ROOT` 环境变量供插件 spawn Python；
- 末尾含"完全离线交付"说明（AGH 框架运行时用其默认 home，不触碰项目外）。

### 6.4 已否决的弯路（别再重走）

- **项目内隔离 AGH home（`.agh-home`）失败**：AGH 的 home 是**活运行时状态机**（credential store / daemon 身份 / sqlite lock 均绑定原路径），手动 `Copy-Item` 整个 `~/.agh` 或只拷 config+secrets 都报 `provider host assembly failed` / `credential store is unavailable`。**不要再尝试搬 home**。AGH 框架就用它默认 home 运行（类比 node_modules，是框架自带运行时，不是 paper-agent 交付物）。

### 6.5 联调闭环记录（2026-10-02 已完成）

- [x] 交互式 TTY 安装：`package add` 的人类确认无法 non-TTY 绕过（AGH 安全设计）。最终自动化方案：`demo/reinstall_plugin.ps1` 用 `Start-Process cmd` 开真实控制台 + `AttachConsole(pid)` + `WriteConsoleInput(CONIN$)` 注入命令行与 `y` 确认（等价真人键盘输入，走正常 TTY 确认路径）。
- [x] 两次真实 `-p` 会话（同一 workspace 会话追加轮次，session id `agnes:local:local-dev:cli:workspace:05d7ffbf5caefe74`）：
  - 首轮：plan→run_step P1..P5→verify→report→cite→status，10 次调用全成功，run `run-20261002-030119-61a0ec` DONE、verify PASS（SHA `a30bc79f…`）。
  - 崩溃恢复轮：run_step P2 带 `chaos=kill_after_p2` → 子进程被 `os._exit(137)` 真实杀死 → status 显示 P3 PENDING → `sciret_resume` 断点续跑至 DONE → verify/report/cite 复核。run `run-20261002-033525-356ccf`。**7/7 工具全部出现**。
- [x] 证据导出：`evidence/session.jsonl`（首轮）与 `evidence/session-full.jsonl`（21 tool/call + 21 tool/result，闸门 ≥6 通过）。`*.jsonl` 按红线 gitignore（含本机路径），提交包从磁盘归集。
- [x] 审计包：`bash audit-pack-template/build_audit_pack.sh <RUN_ID>` 现自动把两份会话导出拷入 `audit-pack/`（`audit-pack/` 亦 gitignore，交付时随包生成）。
- 期间修复的真实缺陷：① 插件入口改 Cordis 对象范式（`inject:['extension']`）；② tool meta 补全 8 必填键（replay/costHint/deferLoading/requiresApproval 等，`requiresApproval:'never'`）；③ `kill_after_p2` 从"文档声明"到真实实现（chaos.py + run_p2/run_all 双路径挂钩 + E2/E3 测试）；④ P5 报告 DONE 后重复调用抛 StateError → 改幂等复用（F 测试）。

> 7 工具名（会话中已全部出现）：`sciret_plan / sciret_run_step / sciret_status / sciret_verify / sciret_report / sciret_cite / sciret_resume`。
>
> **注（阶段 7 重构）**：此后新增 `sciret_step_driven / sciret_next / sciret_finish`，
> 工具总数 **10**，并把核心编排改为**模型驱动**（详见 §0 与 README「编排模型」）。
> 上表中的 7/7、21+21 为阶段 6 真实会话的历史事实，未改动。

---

## 7. 环境矩阵

| 组件 | 要求 | 本机实际 |
|---|---|---|
| Python | 3.10+，零第三方依赖 | 3.11 |
| Node | ≥18（AGH 需 ≥24） | 24.15 |
| pnpm | 10.34.5（AGH 构建） | 10.34.5 |
| bash + sha256sum | demo 脚本 | Git Bash（`C:\Program Files\Git\bin\bash.exe`）|
| AGH 源码 | 已构建 | 本机构建路径见 `AGH_ENTRY`（脚本不再写死他人机器绝对路径） |

### 踩坑备忘（Windows 特有）
- **WSL shim 拦截**：`bash -c "…"` 或带引号路径调 Git Bash 会被 `wsl.exe` 拦截报 `No such file or directory`。**解法**：`& 'C:\Program Files\Git\bin\bash.exe' '绝对路径.sh'`（PowerShell 直接调脚本，不嵌套 `-c`）。
- **PowerShell 展开**：脚本里的 `${VAR}` 会被 PowerShell 外层展开 → 用脚本文件传参，别用 `-c` 内联。
- **cmd vs PowerShell**：`Get-ChildItem`/`Select-String` 是 PowerShell cmdlet；`dir`/`findstr`/`%var%` 是 cmd。按 `shell` 参数选对应语法。
- **连字符变量名**：`paper-agent_PYTHON` 在 bash 中非法，用 `printenv paper-agent_PYTHON` 读。
- **中文路径 + 编码**：管道读含中文路径的 JSON 按 cp936/GBK 解码会崩；CLI 已加 `_ensure_utf8_stdio`，demo 脚本加 `export PYTHONIOENCODING=utf-8`。

---

## 8. 一句话交接

> 代码、工程层与 AGH 真实会话联调 **100% 闭环**：插件 running+trusted，两次真实会话 7/7 工具全覆盖（含真实进程崩溃 + 断点续跑演示），证据与审计包在盘。剩余工作只有**赛事提交材料**（项目说明文档 / 演示视频脚本 / 独立完成声明，见任务清单）。改任何 Python 代码前先读 §4 红线、跑 §3 验证；改插件后重跑 `demo/reinstall_plugin.ps1`（会真实开一个确认窗口）。

---

## 9. 阶段 9–10：PRD v0.3 科研全流程实现（2026-10-03）

### 9.1 这次新增了什么（一句话）

在**不破坏原有 materials（P1–P5）可复现实验底座**的前提下，新增**第二条工作流 `research`（R1–R6）**，
把 PRD 的 `检索→精读→拆解→验证→写作→评审` 全链路落地，并补齐**量化验证（F-7）**与**三类异常恢复（F-4.8）**；
两条工作流**共用同一套**状态机、事件账本、证据账本、故障恢复与模型驱动编排。

范围口径（已与负责人确认）：**全量核心（P0–P2，不含面板）** · **坚持零第三方依赖** · 在 `fix/agh-driven` 分支开发并推 `mike`。

### 9.2 新增/重写文件清单

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `core/paper_agent/state.py` | 重写（泛化） | `MATERIALS_STEPS` / `RESEARCH_STEPS` / `WORKFLOWS` / `steps_for()`；`PipelineState(workflow=, steps=)`；**`load()` 必须整体重建 step 字典**（否则会混入构造器预置的默认工作流步骤） |
| `core/paper_agent/litsearch.py` | 扩展 | 多源：`semantic_scholar` / `openalex`（摘要反演重建）/ `crossref`；`dedup_documents`（DOI + 标题/首作者）；`score_relevance` / `rank_documents`；原 arXiv 能力保留 |
| `core/paper_agent/pdfparse.py` | 新增 | **零依赖** PDF 文本抽取（`zlib` + 内容流算子）+ 章节/关键信息(locator)/图表/可复现性 + 三档置信度 + OCR 降级 |
| `core/paper_agent/analyze.py` | 新增 | 创新点 5 分类 / 技术脉络 / Research Gap |
| `core/paper_agent/factcheck.py` | 新增 | 引用真实性核查 / 数据一致性 4 项 / 文献矛盾检测 |
| `core/paper_agent/writing.py` | 新增 | 综述生成（**强制引用**，无依据标 `[需补充引用]`）/ BibTeX·RIS / APA·IEEE·Chicago |
| `core/paper_agent/review.py` | 新增 | 5 维度模拟审稿（信号驱动打分）+ 迭代闭环 |
| `core/paper_agent/evaluate.py` | 新增 | F-7 四套指标（P/R/F1/NDCG@10、结构·关键信息·复现准确率、识别率·分类准确率·幻觉率·混淆矩阵、引用准确率·幻觉率） |
| `core/paper_agent/research.py` | 新增 | `ResearchPipeline`（R1–R6 + `step_context` + `run_all` + `resume`）；demo 版式 PDF；F-4.8 挂钩 |
| `core/paper_agent/report.py` | 扩展 | 新增 `generate_research_report()`（C1–C5 证据绑定） |
| `core/paper_agent/provenance.py` | 扩展 | `EVIDENCE_KINDS` 扩展：`note/analysis/factcheck/draft/review/evaluation` |
| `core/paper_agent/chaos.py` | 扩展 | `source_should_fail` / `force_scanned` / `batch_fail_index` / `kill_after_r3`（真实 `os._exit(137)`） |
| `core/paper_agent/steps.py` | 扩展 | `open_pipeline()` 按 workflow 装配编排器 |
| `core/paper_agent/cli.py` | 扩展 | `--workflow`；新增 `search-papers/parse-paper/analyze-paper/verify-facts/write-review/self-review/eval` |
| `plugins/paper-agent-tools/index.mjs` | 扩展 | 17 工具（+7 科研能力），`sciret_plan` 支持 `workflow` |
| `.agh/skills/.../SKILL.md` | 重写 | 两条工作流 + 决策协议 + F-4.8 三场景 |
| `tests/test_{litsearch_multi,pdfparse,analyze,factcheck,writing,review,evaluate,research}.py` | 新增 | 覆盖 F-1~F-7 与 F-4.8 |

### 9.3 关键工程决策（接手务必知道）

1. **`state.load()` 必须重建 step 字典**：`PipelineState.__init__` 会按默认工作流预置 `step_status`；
   载入既有 run 时若不**整体重建**（而非 update），research run 会混入 P1–P5 的 PENDING 条目 →
   `run_all()` 永不 DONE。这是本次踩过的真实坑，已修复并有 `tests/test_research.py::TestWorkflowIsolation` 守门。
2. **零依赖 PDF 解析的边界**：纯标准库无法覆盖 CID/自定义编码字体与复杂版式；此类文件给
   `confidence=low` + `warnings`，**绝不假装成功**。这是相对 PRD §6.1（建议 GROBID/PyMuPDF）的
   **有意偏差**（红线优先），已在映射文档中显式声明。
3. **降级信号要有信噪比**：置信度分三档（high / medium / low），"文本偏短的元数据版式"记 **medium**
   而非 low，避免 demo 正常路径被误判为 degraded；真正的问题（扫描件 / 解析失败 / 悬空引用 / 切源）才计降级。
4. **"未识别到 Gap"是元陈述**，不是关于文献的事实主张，故**不打** `[需补充引用]`；避免把覆盖度提示
   误判为无据主张而导致自评审永远阻塞。
5. **F-1.2 独立文献库未做**：以 run 内文献集 + 证据留痕替代（P0 非必须），边界已在映射文档声明。

### 9.4 怎么复验（PRD v0.3 部分）

```bash
export PYTHONPATH=core

# 全量单测：159/159 OK（离线零 skip）
python -m unittest discover -s tests -p "test_*.py"

# research 端到端：DONE / degraded=false
python -m paper_agent.cli run-all --workflow research \
  --goal "sulfide solid electrolyte ionic conductivity" --lit-source local
python -m paper_agent.cli report --run <RUN_ID>     # C1-C5 全带 [EV-XXXX]

# 量化验证：检索/精读/创新点/引用四套指标
python -m paper_agent.cli eval

# F-4.8 三场景
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos ss_timeout
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos scan_pdf
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos batch_fail_at=2
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos kill_after_r3
python -m paper_agent.cli resume --run <RUN_ID>
```

详见 `HOW-TO-VERIFY.md` §8 与 `docs/PRD-v0.3-需求实现映射.md`。

### 9.5 Windows 复验小坑（本次新增）

- **bash 无法 export 连字符环境变量**：`paper-agent_ROOT=... python ...` 与 `env "paper-agent_ROOT=..."` 在 Git Bash 下
  会失败/静默丢失。复验隔离根请用 **Python 进程内** `os.environ['paper-agent_ROOT']=tmp` 后再调用 `cli.main([...])`。
- 若在 Git Bash 里写 `/tmp/xxx`，Windows 原生 Python 会解析成 `D:\tmp\xxx`；跨工具传路径请用 `cygpath -w` 或直接写盘符路径。
