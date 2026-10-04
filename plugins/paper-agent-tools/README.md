# paper-agent-tools（AGH 插件）

把 `paper-agent` 的科研流水线接入 **Agnes Harness（AGH）** 的薄壳插件。
**20 个 `sciret_*` 工具**（科研全流程 17 + 可信增强 3），每个都只是 spawn Python CLI
（`python -m paper_agent.cli <子命令>`），不含业务逻辑——业务全在
`<repo>/core/paper_agent/`（零第三方依赖）。

> 详细安装步骤与每步预期输出见仓库内的 [`docs/AGH-SESSION-RUNBOOK.md`](../../docs/AGH-SESSION-RUNBOOK.md)。
> 安装/排障全流程见仓库根的插件安装指南（含两大高频坑：`file:` 是**拷贝**安装、环境变量只在 daemon 启动时注入）。

### 装完先自检（不需要 AGH / daemon / TTY）

```bash
cd <repo>
node tools/verify-plugin-offline.mjs   # 13 项：工具面 / meta 8 键 / schema / 零依赖（离线、秒级）
node tools/verify-plugin-e2e.mjs       #  6 项：真跑 plan→status→cite + H1 边界拦截
```

两个脚本都是 `0=通过 / 1=失败`，可接 CI。**两个都过 ⇒ 插件与 Python 核心没问题，
故障在 AGH 侧**（环境变量注入 / daemon cwd / trust+enable）。

---

## 工具一览

### 驱动型（主导路径：编排权在模型侧）

| 工具 | 作用 | 写操作 |
|---|---|---|
| `sciret_step_driven` | 执行**一步**并返回决策上下文（result / remaining_steps / next_tool_candidates），由模型决定下一步 | 是 |
| `sciret_next` | 只读：查看剩余步骤与推荐的下一步工具候选 | 否 |
| `sciret_finish` | 收敛 run 状态（RUNNING → DONE/FAILED）；有未终态步骤时拒绝 | 是 |

### 流水线（对应五步状态机）

| 工具 | 作用 | 写操作 |
|---|---|---|
| `sciret_plan` | 新建隔离 run 实例（5 步状态机 + append-only 双账本），返回 run_id | 是 |
| `sciret_run_step` | 执行单步 `P1..P5`（终态步骤幂等复用） | 是 |
| `sciret_status` | 只读：run/步骤状态、尝试次数、degraded 标志 | 否 |
| `sciret_verify` | P4 复现验证：隔离目录重跑实验 + 5 项容差校验 | 是（写 verification/） |
| `sciret_report` | P5 报告生成：从真实产物构建 `report.md`，结论绑定证据 ID | 是 |
| `sciret_cite` | 只读：回查证据（文献给 DOI/作者/年份，产物给 sha256 前缀） | 否 |
| `sciret_resume` | 断点续跑：只执行 PENDING/FAILED，复用 DONE/SKIPPED | 是 |

### 科研全流程单点工具（research 工作流 R1–R6）

| 工具 | 作用 | 写操作 |
|---|---|---|
| `sciret_search_papers` | 多源检索 arXiv / Semantic Scholar / OpenAlex / CrossRef（DOI 精确 + 标题/首作者模糊去重，单源超时跳过不阻塞） | 否 |
| `sciret_parse_paper` | PDF 精读（扫描件走 OCR 路径，失败归类） | 否 |
| `sciret_analyze` | 创新点拆解 + Research Gap（每条创新点带 locator） | 否 |
| `sciret_factcheck` | 事实验证：引用一致性率与文献间矛盾 | 否 |
| `sciret_write_review` | 综述草稿（强制引用，无依据句标 `[需补充引用]`） | 是 |
| `sciret_self_review` | 自评审：各维度分数与 verdict | 是 |
| `sciret_eval` | 量化验证：检索 Recall/Precision/NDCG@10、精读、创新点、引用可信度 | 是 |

### 检索与判断（判断由**会话内的模型**给出）

| 工具 | 作用 | 写操作 |
|---|---|---|
| `sciret_search` | 联网检索 Crossref / OpenAlex **元数据**（不抓全文） | 否 |
| `sciret_freeze_prepare` | 取两腿数据 + **待判对象**（材料化学族 + 规则式参考裁决），落盘 pending | 是（写 pending） |
| `sciret_freeze_commit` | 提交**模型的裁决** → 异常检测 → 冻结输入快照 | 是（写快照） |

---

## 设计约束

1. **薄壳**：JS 只做参数拼装与子进程调用；一切校验、留痕、异常处理都在 Python 侧。
2. **stdout 契约**：CLI 每次只向 stdout 输出**一个 JSON**；插件据此判断成功/失败。
3. **项目根自动推导**：`projectRoot()` 优先读 `PAPER_AGENT_ROOT` /
   `paper-agent_ROOT`；两者都没有时，才由本文件位置上溯两级
   （`plugins/paper-agent-tools` → 仓库根）。
   ⚠️ **这条兜底只在"原地运行"时成立**（例如 `tools/verify-plugin-*.mjs` 直接 import 本文件）。
   AGH 用 `package add "file:..."` 安装时是**拷进 profile 目录**运行的，此时上溯两级得到的是
   AGH 的 profile 而非你的仓库 —— **所以装进 AGH 后必须注入 `paper-agent_ROOT`**，
   否则会报 `ModuleNotFoundError: No module named 'paper_agent'`（详见安装指南"机制①"）。
4. **Python 解释器**：`pythonCandidates()` 依次尝试
   `PAPER_AGENT_PYTHON` → `paper-agent_PYTHON` → `python` / `python3` / `py`；
   全部失败时返回带 `hint` 的结构化错误，而不是让工具静默不可用。
5. **不碰密钥**：模型凭据由 AGH 的 provider 持有，插件不读、不写、不传递。

---

## 故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 会话里报 `ModuleNotFoundError: No module named 'paper_agent'` | 装进 AGH 是**拷贝**运行，兜底推导指向 profile 而非仓库 | `daemon stop` → 带 `paper-agent_ROOT`（仓库绝对路径）从仓库根重启 → **新开会话** |
| `cannot launch python (tried: …)` | PATH 上没有 python | 设 `PAPER_AGENT_PYTHON` 指向 Python 3.10+ 绝对路径后**重启 daemon** |
| `non-JSON stdout: …` | Python 侧异常 | 手动跑同一条 CLI 命令看 stderr；或先跑 `tools/verify-plugin-e2e.mjs` 定位 |
| `input_schema_mismatch` | 喂进来的数据列名对不上 | 换用 OBELiX schema，或为新领域写适配器 |
| 工具全部失败且 root 相关报错 | 仓库结构被改（如 `core/` 移位） | 检查 `<repo>/core/paper_agent/cli.py` 是否存在 |
| `Package ... source could not be accepted` | daemon 的工作目录不是仓库根 | 在仓库根执行命令；必要时 `daemon stop` 后从仓库根重启 |
| 自检脚本报 `EBUSY: spawnSync …` | 受限环境把**同步**建进程判 EBUSY | 用仓库自带脚本（已全部改用异步 `spawn`）；勿自加 `spawnSync`/`execFileSync` |
