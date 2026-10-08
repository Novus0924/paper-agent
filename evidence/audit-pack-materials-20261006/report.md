# paper-agent 科研报告 — run-20261006-104602-8b9c9a

- 目标: sulfide solid electrolyte ionic conductivity ranking
- 文献检索来源: local（配置 lit_source=local）
- 顶层状态: DONE
- 状态依据: 由步骤终态推断（全部步骤已完成）
- 生成: 2026-10-06T10:46:04Z

## 流水线状态总表

| 步骤 | 状态 | 尝试次数 |
| --- | --- | --- |
| P1_lit_search | DONE | 1 |
| P2_clean_data | DONE | 1 |
| P3_run_experiment | DONE | 1 |
| P4_verify | DONE | 1 |
| P5_report | DONE | 1 |



## 科研结论（证据绑定）

- **C1 文献检索**：文献检索（来源=local）命中 5 篇相关文献（degraded=False），引用集合: 10.1038/nmat3066, 10.1038/nenergy.2016.30, 10.1016/0167-2738(92)90421-F, 10.1002/anie.200800627, 10.1002/anie.200701144。 `[EV-0002; EV-0003; EV-0004; EV-0005; EV-0006]`
- **C2 数据清洗**：数据清洗将 7 行原始样本归一为 6 行有效数据；清洗动作: dedup×1, impute_median×1, unit_normalize×1。 `[EV-0008; EV-0009]`
- **C3 实验 top3**：实验 top3 材料: #1 M002 (Li9.54Si1.74P1.44S11.7Cl0.3) score=0.900000, #2 M001 (LGPS) score=0.822067, #3 M003 (LLZO) score=0.637443；家族 log10 电导率均值: argyrodite=-3.356547, garnet=-3.610924, sulfide=-1.761439, thin_film=-5.698970。 `[EV-0010]`
- **C4 复现验证**：复现验证 PASS（5/5 项校验通过）: results_csv_sha256=PASS / n_rows=PASS / top3_material_id_set=PASS / top3_scores_positional=PASS / family_mean_log10_cond=PASS `[EV-0012]`
- **C5 图表说明**：图表 fig1_conductivity.svg 覆盖 6 个样本，对数坐标横向条形图按 family 着色。 `[EV-0011]`

## 证据索引表

| EV | 类型 | 引用 | SHA-256(前16) | 生产步骤 |
| --- | --- | --- | --- | --- |
| EV-0001 | query_generation | sulfide solid electrolyte ionic conductivity ranking |  | P1_lit_search |
| EV-0002 | literature | 10.1038/nmat3066 |  | P1_lit_search |
| EV-0003 | literature | 10.1038/nenergy.2016.30 |  | P1_lit_search |
| EV-0004 | literature | 10.1016/0167-2738(92)90421-F |  | P1_lit_search |
| EV-0005 | literature | 10.1002/anie.200800627 |  | P1_lit_search |
| EV-0006 | literature | 10.1002/anie.200701144 |  | P1_lit_search |
| EV-0007 | data | literature\literature_hits.json | 0fb7a3b2f128608a | P1_lit_search |
| EV-0008 | data | C:/Users/ASUS/Desktop/黑客松/paper-agent\runs\run-20261006-104602-8b9c9a\clean\conductivity_clean.csv | 6e3b75a806a26495 | P2_clean_data |
| EV-0009 | data | C:/Users/ASUS/Desktop/黑客松/paper-agent\runs\run-20261006-104602-8b9c9a\clean\cleaning_report.json | ccdb6c639cbe0aa2 | P2_clean_data |
| EV-0010 | experiment | experiment\results\results.csv | e17a61b7ef27ee36 | P3_run_experiment |
| EV-0011 | figure | experiment\figures\fig1_conductivity.svg | fe4614625dedddeb | P3_run_experiment |
| EV-0012 | verification | C:/Users/ASUS/Desktop/黑客松/paper-agent\runs\run-20261006-104602-8b9c9a\verification\verification.json | 57df6c9c3244b440 | P4_verify |
| EV-0013 | report | report.md |  | P5_report |

## 复现命令

```bash
# 复现本 run 的完整流水线（断点续跑语义，已 DONE 步骤直接复用）
# 1) 全新 run（等价 plan + run-all）
cd C:\Users\ASUS\Desktop\黑客松\paper-agent
PYTHONPATH=core python -m paper_agent.cli run-all --goal "<goal>" --lit-source local
#    --lit-source arxiv  实时检索 arXiv（结果快照冻结，保确定性）
#    --lit-source auto   先试 arXiv，不可用时自动回落到本地语料

# 2) 对已存在 run run-20261006-104602-8b9c9a 断点续跑 / 验证 / 出报告
PYTHONPATH=core python -m paper_agent.cli resume --run run-20261006-104602-8b9c9a
PYTHONPATH=core python -m paper_agent.cli verify --run run-20261006-104602-8b9c9a
PYTHONPATH=core python -m paper_agent.cli report --run run-20261006-104602-8b9c9a
PYTHONPATH=core python -m paper_agent.cli cite --run run-20261006-104602-8b9c9a --ev <EV-XXXX>

# 3) 实验脚本独立复跑（确定性核验，两次 SHA-256 应一致）
python experiments/arrhenius_rank.py --input runs/run-20261006-104602-8b9c9a/clean/conductivity_clean.csv --outdir runs/run-20261006-104602-8b9c9a/verification/rerun --seed 0
sha256sum runs/run-20261006-104602-8b9c9a/experiment/results/results.csv runs/run-20261006-104602-8b9c9a/verification/rerun/results/results.csv

```

> 数据红线：所有数值均为 as-reported 工程演示；正式科研使用务必核对原始论文原文。
