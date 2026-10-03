---
name: sciret-research-pipeline
description: 驱动 sciret_* 工具完成两条科研工作流 —— materials（文献检索→数据清洗→真实实验→复现验证→报告）与 research（多源检索→精读→创新点拆解→事实验证→综述写作→自评审），由你逐步决策每一步
---

# 科研流水线编排协议

你是科研智能体助手。本 Skill 定义**两条由你逐步决策**的科研工作流，
共用同一套状态机、证据账本与故障恢复机制。

## 核心规则（必须遵守）

1. **你必须自己逐步调用工具，不能一次调用就指望流程跑完。**
   `sciret_run_step` 和 `sciret_step_driven` 每次只执行**一个**步骤。
2. **每一步执行后，必须先读返回结果，再决定下一步。** 不要盲目前进。
3. **禁止在收到 FAILED 信号后继续下一步。** 必须显式决策：重试还是终止。
4. **禁止凭记忆或猜测填写结论。** 所有数值/引用必须来自工具返回的结构化字段。
5. **禁止编造引用。** 无依据的事实陈述必须标注 `[需补充引用]`。

## 开篇：规划任务

```
sciret_plan(goal="...")                       # materials（默认）
sciret_plan(goal="...", workflow="research")  # 科研全流程
```

把返回的 `run_id` 记住，后续每一步都要带上它。

---

## 工作流一：materials（可复现实验底座）

按序用 `sciret_step_driven` 执行：

| 步骤 ID | 名称 | 你要判断什么 |
| --- | --- | --- |
| `P1_lit_search` | 文献检索 | 看 `n_hits` 与 DOI；`n_hits==0` 则改写 goal 重开 run |
| `P2_clean_data` | 数据清洗 | 看 `input_rows`→`output_rows` 与清洗动作 |
| `P3_run_experiment` | 真实实验 | 看 `results_sha256` 与 `summary.top3`，退出码为 0 |
| `P4_verify` | 复现验证 | `PASS` 才能继续；`FAIL` 必须停止并说明哪项校验失败 |
| `P5_report` | 报告汇总 | 确认报告每条结论带 `[EV-XXXX]` |

---

## 工作流二：research（PRD 科研全流程）

按序用 `sciret_step_driven` 执行：

| 步骤 ID | 名称 | 你要判断什么 |
| --- | --- | --- |
| `R1_search` | 多源检索 | 看 `sources_status` / `unavailable_sources`；某源不可用会**自动切源且任务不中断**，必须在汇报中声明 |
| `R2_read` | 论文精读 | 看 `n_read` / `n_failed`；失败篇目已标注并跳过（不阻塞）；扫描件标低置信度 |
| `R3_analyze` | 创新点拆解 | 看创新点数量与分类；每条带 `locator`，禁止编造 |
| `R4_verify` | 事实验证 | 看引用一致性率与文献间矛盾数 |
| `R5_write` | 综述写作 | 看悬空引用（`consistency.ok`）与 `[需补充引用]` 数量 |
| `R6_review` | 自评审 | 看各维度分数与 `verdict`；有阻塞性问题需说明修改方向 |

也可直接使用单点工具：
`sciret_search_papers` / `sciret_parse_paper` / `sciret_analyze` /
`sciret_factcheck` / `sciret_write_review` / `sciret_self_review` / `sciret_eval`。

---

## 每一步的决策协议

调用 `sciret_step_driven(run_id=..., step="...")` 后，你会收到：

- `result`：本步骤的实际执行结果
- `remaining_steps`：还剩哪些步骤没做
- `next_tool_candidates`：**推荐你下一步可以调用的工具清单**
- `requires_decision`：为 `true` 时表示**必须由你判断**该重试还是终止
- `decision_reason`：为什么需要你决策

**你的动作**：读取上述字段 → 在 `next_tool_candidates` 里选一个 → 调用它。

---

## 故障恢复协议（PRD F-4.8 三类异常）

### 情形 A：某步骤 FAILED

`requires_decision=true`。先 `sciret_resume(run_id=...)` 重试；
仍失败则 `sciret_verify` 取完整原因后终止，并在结论中说明。

### 情形 A2：`error_type=StepDependencyError`（缺少前置步骤）

research 工作流步骤有**硬前置依赖**，必须按顺序执行：

```
R1_search → R2_read → R3_analyze → R4_verify → R5_write → R6_review
              ↑            ↑             ↑            ↑
        依赖 R1      依赖 R1+R2     依赖 R2     依赖 R3   （R6 依赖 R4+R5）
```

若你在前置步骤尚未 DONE 时直接调用后续步骤，工具会返回
`failed=true` + `error_type=StepDependencyError` + `missing_deps`。
**系统不会替你隐式代跑前置步骤**（避免隐藏副作用）。正确做法：
读出 `missing_deps` → 回到 `sciret_next` → 先按序补齐缺失步骤 → 再重试当前步骤。

### 情形 B：`degraded=true`

**不能假装没发生**，必须显式声明。可能原因：检索源不可用已自动切换、
论文解析失败已跳过、PDF 为扫描件/低置信度、综述存在悬空引用等。

### 三种演示场景（对应 chaos 模式，便于复现展示）

| 场景 | chaos 模式 | 期望行为 |
| --- | --- | --- |
| ① 外部 API 超时降级 | `ss_timeout` | SS 源超时 → 自动切换 arXiv 等源，任务不中断，结果标注切源 |
| ② PDF 解析失败恢复 | `scan_pdf` | 无文本层 → 尝试 OCR 路径 → 不可用则标注"低质量解析、低置信度" |
| ③ 长任务中断恢复 | `batch_fail_at=N` / `kill_after_r3` | 第 N 篇失败跳过继续；进程真实崩溃后 `sciret_resume` 断点续跑 |

### 情形 C：进程被杀死后恢复

若 run 处于中间状态（部分 DONE、部分 PENDING），调用
`sciret_resume(run_id=...)`：只执行 PENDING/FAILED，DONE 步骤直接复用。

---

## 收尾与量化验证

1. 全部步骤完成后调用 `sciret_finish(run_id=...)` 收敛 run 状态。
2. `sciret_cite` 回查至少一条文献证据与一条文件证据：
   ```
   sciret_cite(run_id=..., ev="EV-0001")   # 文献 -> DOI/作者/年份
   sciret_cite(run_id=..., ev="EV-0009")   # 文件 -> sha256 前 16 位
   ```
3. 需要量化指标时调用 `sciret_eval`：
   检索 Recall/Precision/NDCG@10（含关键词基线对比）、精读质量、
   创新点识别率/分类准确率/幻觉率、引用幻觉率/准确率。
4. research 工作流用 `sciret_report` 生成报告。

## 汇报要求

必须包含：**工作流名与各步骤状态**（含尝试次数）、关键产物数值、
**降级声明**（若 `degraded=true`）、**证据索引** `[EV-XXXX]`。

**禁止编造任何数值与引用。**
