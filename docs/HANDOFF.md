# 交接文档（HANDOFF）— paper-agent

> 面向**接手本项目的下一个编程工具 / 工程师**。读完本文即可在无需上下文记忆的情况下继续推进。
> 生成时间：2026-10-02（对应 HEAD `d8af9d5`）。若与仓库实际不一致，以 `git log` 与代码为准。

---

## 0. 30 秒速览

- **项目**：`paper-agent` —— 基于 **AGH（Agnes Harness）** 的可审计、可复现、可故障恢复的科研 Agent 流水线（JS 薄壳工具 + Python 核心业务 + 确定性实验），用于 2026 江苏省 AI+科学与工程创新实践黑客松。
- **工程完成度**：阶段 1–6 **全部完成并通过自验证**（单测 36/36、端到端 demo、四大故障用例 8/8、审计不变量全 PASS）。
- **唯一未闭环**：**AGH 真实会话联调**卡在"安装插件需交互式 TTY 确认"这一环（AGH 安全设计，自动化 non-TTY 会取消）。已备好可一键执行的 `demo/demo_agh_session.sh`，需在有 AGH 运行时的目标环境执行后回填 `evidence/session.jsonl`。
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
│   ├── chaos.py                    #   故障注入（p1_fail_first / p1_fail_all / mutate_summary / kill_after_p2）
│   ├── steps.py                    #   五步 P1-P5 调度 + 重试-降级 + 工具调用留痕 toolcalls/ + resume
│   ├── verify.py                   #   P4 复现验证器（递归容差比对，5 项校验）
│   ├── report.py                   #   P5 报告生成（从真实产物提取数据，C1-C5 全带 [EV-XXXX]）
│   └── cli.py                      #   命令行入口，stdout 只输出单个 JSON（_ensure_utf8_stdio 强制 UTF-8）
├── experiments/arrhenius_rank.py   # 零依赖确定性实验脚本（电导率打分排序；utf-8-sig 读 CSV）
├── data/
│   ├── literature.json             # 内置 5 篇真实 DOI 文献语料
│   └── conductivity_raw.csv        # 带缺陷原始数据集（utf-8 BOM，7 行）
├── plugins/paper-agent-tools/
│   ├── package.json                # AGH 插件 manifest（对齐官方形态，见 §6）
│   └── index.mjs                   # 7 工具薄壳（spawn Python CLI，TypeBox 严格 schema）
├── tests/
│   ├── _util.py                    # 共享：构建隔离临时根 + make_clean_csv
│   ├── test_state.py              # 状态机转移/持久化/非法转移/append-only（10）
│   ├── test_provenance.py         # 证据账本/结论绑定/引文（10）
│   ├── test_recovery.py           # 四大故障用例 A/B/C/D + FAILED 终态（5）
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
# ① 单元测试（36/36 应全绿）
set PYTHONPATH=C:\Users\ASUS\Desktop\黑客松\paper-agent\core
python -m unittest discover -s tests -p "test_*.py"

# ② 端到端正常路径（需要 bash + sha256sum；Windows 用 Git Bash）
"C:\Program Files\Git\bin\bash.exe" "C:/Users/ASUS/Desktop/黑客松/paper-agent/demo/demo_e2e.sh"

# ③ 四大故障用例（8/8 应全 PASS）
"C:\Program Files\Git\bin\bash.exe" "C:/Users/ASUS/Desktop/黑客松/paper-agent/demo/demo_failure.sh"

# ④ 插件 7 工具注册自检
node plugins/paper-agent-tools/index.mjs   # 无语法错即通过（真实注册在 AGH 运行时）
```

**预期结果**：单测 36/36 OK；demo_e2e 末行 `DEMO_E2E_OK`；demo_failure 末行 `DEMO_FAILURE_OK`（8 passed, 0 failed）。

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
- 插件 `file:./plugins/paper-agent-tools` 的 inspect integrity：`sha256-d228e6136472fd3f30b2d72178c49c461b0edea546a7605dc6f975acab75c4a1`（随 index.mjs/package.json 变化而变；以 `AGH package inspect` 实际输出为准）。
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

### 6.5 待办（新工具或人类执行）

- [ ] 在**交互终端**执行 `demo/demo_agh_session.sh`（或手动 `AGH install`+`trust`+`enable`），完成 7 工具真实调用。
- [ ] 导出 `evidence/session.jsonl`，核验 `grep -c '"tool_use"\|"tool_result"' evidence/session.jsonl` **≥ 6 条连续**。
- [ ] `build_audit_pack.sh <RUN_ID>` 归集审计包（自动补 `agh-session.jsonl`）。
- [ ] 把 AGH 联调产物 commit（**不含 `.env`**）。

> 7 工具名（会话中应全部出现）：`sciret_plan / sciret_run_step / sciret_status / sciret_verify / sciret_report / sciret_cite / sciret_resume`。

---

## 7. 环境矩阵

| 组件 | 要求 | 本机实际 |
|---|---|---|
| Python | 3.10+，零第三方依赖 | 3.11 |
| Node | ≥18（AGH 需 ≥24） | 24.15 |
| pnpm | 10.34.5（AGH 构建） | 10.34.5 |
| bash + sha256sum | demo 脚本 | Git Bash（`C:\Program Files\Git\bin\bash.exe`）|
| AGH 源码 | 已构建 | `C:\Users\ASUS\Desktop\黑客松\agnes-harness` |

### 踩坑备忘（Windows 特有）
- **WSL shim 拦截**：`bash -c "…"` 或带引号路径调 Git Bash 会被 `wsl.exe` 拦截报 `No such file or directory`。**解法**：`& 'C:\Program Files\Git\bin\bash.exe' '绝对路径.sh'`（PowerShell 直接调脚本，不嵌套 `-c`）。
- **PowerShell 展开**：脚本里的 `${VAR}` 会被 PowerShell 外层展开 → 用脚本文件传参，别用 `-c` 内联。
- **cmd vs PowerShell**：`Get-ChildItem`/`Select-String` 是 PowerShell cmdlet；`dir`/`findstr`/`%var%` 是 cmd。按 `shell` 参数选对应语法。
- **连字符变量名**：`paper-agent_PYTHON` 在 bash 中非法，用 `printenv paper-agent_PYTHON` 读。
- **中文路径 + 编码**：管道读含中文路径的 JSON 按 cp936/GBK 解码会崩；CLI 已加 `_ensure_utf8_stdio`，demo 脚本加 `export PYTHONIOENCODING=utf-8`。

---

## 8. 一句话交接

> 代码与工程层 100% 完成且自验证全绿；**唯一剩余是 AGH 真实会话联调，卡在交互式安装确认**——直接在新环境跑 `demo/demo_agh_session.sh`，把 `evidence/session.jsonl` 与审计包回填并 commit（勿含 `.env`）即可收工。改任何 Python 代码前先读 §4 红线、跑 §3 验证。
