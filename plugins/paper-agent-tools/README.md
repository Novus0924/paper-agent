# paper-agent-tools（AGH 插件）

把 `paper-agent` 的科研流水线接入 **Agnes Harness（AGH）** 的薄壳插件。
**10 个 `sciret_*` 工具**，每个都只是 spawn Python CLI（`python -m paper_agent.cli <子命令>`），
不含业务逻辑——业务全在 `<repo>/core/paper_agent/`（零第三方依赖）。

> 详细安装步骤与每步预期输出见仓库内的 [`docs/AGH-SESSION-RUNBOOK.md`](../../docs/AGH-SESSION-RUNBOOK.md)。

---

## 工具一览

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

### 检索与判断（第二批；判断由**会话内的模型**给出）

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
   `paper-agent_ROOT`，否则由本文件位置上溯两级（`plugins/paper-agent-tools` → 仓库根），
   因此**不设环境变量也能正确定位** `core/`。
4. **Python 解释器**：`pythonCandidates()` 依次尝试
   `PAPER_AGENT_PYTHON` → `paper-agent_PYTHON` → `python` / `python3` / `py`；
   全部失败时返回带 `hint` 的结构化错误，而不是让工具静默不可用。
5. **不碰密钥**：模型凭据由 AGH 的 provider 持有，插件不读、不写、不传递。

---

## 故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `cannot launch python (tried: …)` | PATH 上没有 python | 设 `PAPER_AGENT_PYTHON` 指向 Python 3.10+ 绝对路径后**重启 daemon** |
| `non-JSON stdout: …` | Python 侧异常 | 手动跑同一条 CLI 命令看 stderr |
| `input_schema_mismatch` | 喂进来的数据列名对不上 | 换用 OBELiX schema，或为新领域写适配器 |
| 工具全部失败且 root 相关报错 | 仓库结构被改（如 `core/` 移位） | 检查 `<repo>/core/paper_agent/cli.py` 是否存在 |
| `Package ... source could not be accepted` | daemon 的工作目录不是仓库根 | 在仓库根执行命令；必要时 `daemon stop` 后从仓库根重启 |
