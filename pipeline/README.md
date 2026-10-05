# 流水线说明

> ⚠️ **本目录不含流水线实现代码**，只有这份说明。
> 实际实现分布在下面两个位置（2026-10-05 核实）：
>
> | 环节 | 实际位置 |
> |---|---|
> | 步骤编排与状态机 | `core/paper_agent/steps.py`（+ `state.py` / `cli.py`） |
> | 真实运行的实验脚本 | `experiments/arrhenius_rank.py` |
>
> 本目录保留下来是因为它标明了"五步"这条主线；**不要在这里找代码**。

## materials 五步

1. **研究问题** → `sciret_plan` 建 run（`steps.py` 读 `state.json` 的 `steps_order`）
2. **arXiv / Semantic Scholar 检索** → `P1_lit_search` → `core/paper_agent/litsearch.py` + `sources.py`
3. **结构化抽取** → `P2_clean_data` → `clean/` 产物
4. **真实运行实验** → `P3_run_experiment` → `steps.py:374` 的 `_spawn_experiment()`
   拉起 `experiments/arrhenius_rank.py` 子进程
5. **图表 + 结论汇总** → `P4_verify` / `P5_report` → `verify.py` / `report.py`

## 依赖：零第三方

第 4 步的实验脚本是 **`arrhenius_rank.py`，纯标准库、零第三方依赖**：

- 输入 CSV（`material_id, formula, family, conductivity_Scm, year`）
- 输出 `results/results.csv`（数值定长格式化，**逐字节稳定**）、
  `results/summary.json`、`figures/fig1_conductivity.svg`（纯标准库画 SVG）
- 确定性契约：无未初始化随机源；`seed` 仅作输入回显；
  排序 tie-break 为 `score` 降序 + `formula` 字典序；仅 `generated_at` 是可变时间戳，复现校验时排除

> **历史漂移已修正**：本文件早前写的是"生成并真实运行 **sklearn** 小实验"，
> 与项目**零第三方依赖**的红线冲突，且与实际代码不符——
> 全仓库没有任何 `import sklearn / numpy / pandas`，也没有 `requirements.txt` / `pyproject.toml`。
> 统计与评估（`core/paper_agent/evaluate.py` 的 F-7.1~F-7.4）同样是**纯函数、零依赖**。

## 故障注入开关（真实机制）

`experiments/arrhenius_rank.py` 支持环境变量 `paper-agent_MUTATE=1`：
交换 `summary` 里的 top1/top2 条目（**不改动 `results.csv`**），
用于触发 P4 复现验证的 **FAIL** 用例。

这是 chaos 实验的**实际入口**。注意它与插件 schema 里那个
`chaos` 参数（如 `kill_after_p2`）**不是同一回事**：
后者只是 `tool_describe` 返回的参数说明文本，详见 `evidence/README.md` 的「已知瑕疵」。

## 两条工作流

- `materials`：`P1_lit_search` → `P2_clean_data` → `P3_run_experiment` → `P4_verify` → `P5_report`
- `research`：`R1_search` → `R2_read` → `R3_analyze` → `R4_verify` → `R5_write` → `R6_review`

两者都是**确定性状态机**，不由 LLM 编排——这是本项目的核心架构选择
（理由见 `docs/对接方案.md` §3.1）。
