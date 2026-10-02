"""report.py — P5 报告生成（文档 §4.7）。

红线：禁止硬编码任何数值，全部从 run 目录真实产物读取。
生成 5 条标准科研结论 C1-C5，每条 link_conclusion 绑定对应 EV 证据；
输出 report.md：流水线状态总表、降级声明块、证据索引表、复现 shell 命令。
"""
from __future__ import annotations

import json
import os

from .state import PipelineState
from .provenance import ProvenanceLedger


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ev_ids_by_kind(prov: ProvenanceLedger, kind: str) -> list[str]:
    return [e["ev_id"] for e in prov.all_evidence() if e["kind"] == kind]


def _state_table(state: PipelineState) -> str:
    lines = ["| 步骤 | 状态 | 尝试次数 |", "| --- | --- | --- |"]
    for sid in ("P1_lit_search", "P2_clean_data", "P3_run_experiment",
                "P4_verify", "P5_report"):
        lines.append(f"| {sid} | {state.step_status[sid].value} | {state.attempts.get(sid, 0)} |")
    return "\n".join(lines)


def _repro_commands(root: str, run_id: str) -> str:
    base = os.path.abspath(root)
    return (
        f"# 复现本 run 的完整流水线（断点续跑语义，已 DONE 步骤直接复用）\n"
        f"# 1) 全新 run（等价 plan + run-all）\n"
        f"cd {base}\n"
        f"PYTHONPATH=core python -m paper_agent.cli run-all --goal \"<goal>\"\n"
        f"\n"
        f"# 2) 对已存在 run {run_id} 断点续跑 / 验证 / 出报告\n"
        f"PYTHONPATH=core python -m paper_agent.cli resume --run {run_id}\n"
        f"PYTHONPATH=core python -m paper_agent.cli verify --run {run_id}\n"
        f"PYTHONPATH=core python -m paper_agent.cli report --run {run_id}\n"
        f"PYTHONPATH=core python -m paper_agent.cli cite --run {run_id} --ev <EV-XXXX>\n"
        f"\n"
        f"# 3) 实验脚本独立复跑（确定性核验，两次 SHA-256 应一致）\n"
        f"python experiments/arrhenius_rank.py --input runs/{run_id}/clean/conductivity_clean.csv --outdir runs/{run_id}/verification/rerun --seed 0\n"
        f"sha256sum runs/{run_id}/experiment/results/results.csv runs/{run_id}/verification/rerun/results/results.csv\n"
    )


def generate_report(
    root: str, run_id: str, state: PipelineState, prov: ProvenanceLedger,
) -> str:
    run_dir = os.path.join(root, "runs", run_id)

    # ---- 读取真实产物 ----
    lit = _read_json(os.path.join(run_dir, "literature", "literature_hits.json"))
    clean_rep = _read_json(os.path.join(run_dir, "clean", "cleaning_report.json"))
    summary = _read_json(os.path.join(run_dir, "experiment", "results", "summary.json"))
    verif = _read_json(os.path.join(run_dir, "verification", "verification.json"))

    top3 = summary.get("top3", [])
    top3_txt = ", ".join(
        f"#{t['rank']} {t['material_id']} ({t['formula']}) score={t['score']:.6f}"
        for t in top3
    ) or "（无）"
    family_mean = summary.get("family_mean_log10_cond", {})
    fam_txt = ", ".join(f"{k}={v:.6f}" for k, v in sorted(family_mean.items())) or "（无）"

    n_checks = len(verif.get("checks", []))
    check_lines = "\n".join(
        f"  - {c['name']}: {'PASS' if c.get('pass') else 'FAIL'}"
        for c in verif.get("checks", [])
    )
    doiset = ", ".join(d["doi"] for d in lit.get("hits", [])) or "（无）"
    actions_by = {}
    for a in clean_rep.get("actions", []):
        actions_by[a["action"]] = actions_by.get(a["action"], 0) + 1
    act_txt = ", ".join(f"{k}×{v}" for k, v in sorted(actions_by.items())) or "无清洗动作"

    # ---- 五条结论（全部绑定真实证据 ID）----
    ev_lit = _ev_ids_by_kind(prov, "literature")
    ev_data = _ev_ids_by_kind(prov, "data")
    ev_exp = _ev_ids_by_kind(prov, "experiment")
    ev_ver = _ev_ids_by_kind(prov, "verification")
    ev_fig = _ev_ids_by_kind(prov, "figure")
    # C1 证据锚点：有文献命中则绑 literature，否则回退到 P1 检索输出 data 证据
    p1_data_ev = [e["ev_id"] for e in prov.all_evidence()
                  if e["kind"] == "data" and e["producer_step"] == "P1_lit_search"]
    c1_ev = ev_lit if ev_lit else p1_data_ev

    c1_text = (f"文献检索命中 {lit['n_hits']} 篇相关文献"
               f"（degraded={lit.get('degraded', False)}），DOI 集合: {doiset}。"
               if lit["n_hits"] > 0 else
               f"文献检索 0 命中（degraded={lit.get('degraded', False)}），"
               f"检索输出已留证，请复核 goal 关键词。")
    c2_text = (f"数据清洗将 {clean_rep['input_rows']} 行原始样本归一为 "
               f"{clean_rep['output_rows']} 行有效数据；清洗动作: {act_txt}。")
    c3_text = (f"实验 top3 材料: {top3_txt}；家族 log10 电导率均值: {fam_txt}。")
    c4_text = (f"复现验证 {verif['status']}（{n_checks} 项校验）:\n{check_lines}")
    c5_text = (f"图表 fig1_conductivity.svg 覆盖 {summary.get('n_rows', 0)} 个样本，"
               f"对数坐标横向条形图按 family 着色。")

    prov.link_conclusion("C1", c1_text, c1_ev)
    prov.link_conclusion("C2", c2_text, ev_data)
    prov.link_conclusion("C3", c3_text, ev_exp)
    prov.link_conclusion("C4", c4_text, ev_ver)
    prov.link_conclusion("C5", c5_text, ev_fig)

    # ---- 证据索引表 ----
    ev_rows = ["| EV | 类型 | 引用 | SHA-256(前16) | 生产步骤 |",
               "| --- | --- | --- | --- | --- |"]
    for e in prov.all_evidence():
        ev_rows.append(
            f"| {e['ev_id']} | {e['kind']} | {e['ref']} | "
            f"{(e.get('sha256') or '')[:16]} | {e['producer_step']} |")
    ev_table = "\n".join(ev_rows)

    # ---- 降级声明块 ----
    degraded_block = ""
    if state.degraded:
        degraded_block = (
            "> **降级声明**：本 run 存在步骤降级（degraded=true）。"
            "P1 文献检索在重试耗尽后降级为返回全部本地语料，"
            "相关结论的证据绑定基于全量语料而非关键词命中，请人工复核。"
        )

    report_md = f"""# paper-agent 科研报告 — {run_id}

- 目标: {state.goal or '（未设置）'}
- 顶层状态: {state.run_status.value}
- 生成: {state.updated_at}

## 流水线状态总表

{_state_table(state)}

{degraded_block}

## 科研结论（证据绑定）

- **C1 文献检索**：{c1_text} `[{ '; '.join(c1_ev) }]`
- **C2 数据清洗**：{c2_text} `[{ '; '.join(ev_data) }]`
- **C3 实验 top3**：{c3_text} `[{ '; '.join(ev_exp) }]`
- **C4 复现验证**：{c4_text} `[{ '; '.join(ev_ver) }]`
- **C5 图表说明**：{c5_text} `[{ '; '.join(ev_fig) }]`

## 证据索引表

{ev_table}

## 复现命令

```bash
{_repro_commands(root, run_id)}
```

> 数据红线：所有数值均为 as-reported 工程演示；正式科研使用务必核对原始论文原文。
"""
    rpath = os.path.join(run_dir, "report.md")
    with open(rpath, "w", encoding="utf-8", newline="") as f:
        f.write(report_md)
    return rpath
