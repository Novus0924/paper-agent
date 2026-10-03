"""report.py — P5 报告生成（文档 §4.7）。

红线：禁止硬编码任何数值，全部从 run 目录真实产物读取。
生成 5 条标准科研结论 C1-C5，每条 link_conclusion 绑定对应 EV 证据；
输出 report.md：流水线状态总表、降级声明块、证据索引表、复现 shell 命令。
"""
from __future__ import annotations

import json
import os

from .state import PipelineState, RunStatus, StepStatus
from .provenance import ProvenanceLedger


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ev_ids_by_kind(prov: ProvenanceLedger, kind: str,
                    producer_step: str | None = None) -> list[str]:
    """按 kind 取证据 ID；给 producer_step 时进一步限定生产步骤。

    限定 producer_step 是为了避免"按 kind 全量取"导致的证据归属错位
    （旧缺陷：C2 数据清洗结论绑定了 P1_lit_search 产出的 evidence）。
    """
    out = []
    for e in prov.all_evidence():
        if e["kind"] != kind:
            continue
        if producer_step is not None and e["producer_step"] != producer_step:
            continue
        out.append(e["ev_id"])
    return out


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
        f"PYTHONPATH=core python -m paper_agent.cli run-all --goal \"<goal>\" --lit-source local\n"
        f"#    --lit-source arxiv  实时检索 arXiv（结果快照冻结，保确定性）\n"
        f"#    --lit-source auto   先试 arXiv，不可用时自动回落到本地语料\n"
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
    n_pass = sum(1 for c in verif.get("checks", []) if c.get("pass"))
    # 校验明细改为"行内摘要"：旧实现用多行文本会撑断 markdown 列表项，
    # 导致本行的 [EV-XXXX] 标记被推到后续行，人眼看起来像 C4 没绑证据。
    check_lines = " / ".join(
        f"{c['name']}={'PASS' if c.get('pass') else 'FAIL'}"
        for c in verif.get("checks", [])
    )
    # 检索来源可能是 arXiv（部分条目无 DOI），故引用串按 DOI → URL → doc_id 回退
    refs = [str(d.get("doi") or d.get("url") or d.get("doc_id") or "")
            for d in lit.get("hits", [])]
    refset = ", ".join(r for r in refs if r) or "（无）"
    lit_source = lit.get("source", "local")
    lit_query = lit.get("query", "")
    actions_by = {}
    for a in clean_rep.get("actions", []):
        actions_by[a["action"]] = actions_by.get(a["action"], 0) + 1
    act_txt = ", ".join(f"{k}×{v}" for k, v in sorted(actions_by.items())) or "无清洗动作"

    # ---- 五条结论（全部绑定真实证据 ID，按 producer_step 精确归属）----
    ev_lit = _ev_ids_by_kind(prov, "literature", "P1_lit_search")
    ev_data = _ev_ids_by_kind(prov, "data", "P2_clean_data")
    ev_exp = _ev_ids_by_kind(prov, "experiment", "P3_run_experiment")
    ev_ver = _ev_ids_by_kind(prov, "verification", "P4_verify")
    ev_fig = _ev_ids_by_kind(prov, "figure", "P3_run_experiment")
    # C1 证据锚点：有文献命中则绑 literature，否则回退到 P1 检索输出 data 证据
    p1_data_ev = _ev_ids_by_kind(prov, "data", "P1_lit_search")
    c1_ev = ev_lit if ev_lit else p1_data_ev

    c1_text = (f"文献检索（来源={lit_source}"
               f"{'，检索式=' + lit_query if lit_query else ''}）命中 {lit['n_hits']} 篇相关文献"
               f"（degraded={lit.get('degraded', False)}），引用集合: {refset}。"
               if lit["n_hits"] > 0 else
               f"文献检索（来源={lit_source}）0 命中（degraded={lit.get('degraded', False)}），"
               f"检索输出已留证，请复核 goal 关键词。")
    c2_text = (f"数据清洗将 {clean_rep['input_rows']} 行原始样本归一为 "
               f"{clean_rep['output_rows']} 行有效数据；清洗动作: {act_txt}。")
    c3_text = (f"实验 top3 材料: {top3_txt}；家族 log10 电导率均值: {fam_txt}。")
    c4_text = (f"复现验证 {verif['status']}（{n_pass}/{n_checks} 项校验通过）: {check_lines}")
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
            "或在联网检索不可用时回落本地语料；"
            "相关结论的证据绑定基于兜底来源而非在线命中，请人工复核。"
        )

    # ---- 终态预测：报告里的"顶层状态"必须是本 run 的真实归宿 ----
    #
    # 时序说明：P5 报告生成时 run_status 仍为 RUNNING —— 因为 run 级收尾
    # （PLANNED→RUNNING→DONE/FAILED）由编排层在全部步骤结束后才做。若此处直接
    # 写 state.run_status，报告会永远自称 RUNNING（旧实现缺陷）。
    # 故按本 run 的步骤终态**推断**最终归宿，并显式标注推断依据。
    all_steps = list(state.step_status.values())
    if any(st is StepStatus.FAILED for st in all_steps):
        final_status = RunStatus.FAILED.value
        final_note = "由步骤终态推断（存在 FAILED 步骤）"
    elif all(st in (StepStatus.DONE, StepStatus.SKIPPED) for st in all_steps):
        final_status = RunStatus.DONE.value
        final_note = "由步骤终态推断（全部步骤已完成）"
    else:
        final_status = state.run_status.value
        final_note = "尚有步骤未完成，此处为生成时刻的实时状态"

    report_md = f"""# paper-agent 科研报告 — {run_id}

- 目标: {state.goal or '（未设置）'}
- 文献检索来源: {lit_source}（配置 lit_source={getattr(state, 'lit_source', 'auto')}）
- 顶层状态: {final_status}
- 状态依据: {final_note}
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


# =====================================================================
# 科研全流程报告（research 工作流 R1..R6）
# =====================================================================

_RESEARCH_STEPS = ("R1_search", "R2_read", "R3_analyze",
                   "R4_verify", "R5_write", "R6_review")


def _rd(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_research_report(root: str, run_id: str, state: PipelineState,
                             prov: ProvenanceLedger) -> str:
    """生成科研全流程报告（research 工作流），每条结论绑定真实证据 ID。"""
    run_dir = os.path.join(root, "runs", run_id)

    hits = _rd(os.path.join(run_dir, "literature", "research_hits.json"))
    read = _rd(os.path.join(run_dir, "reading", "reading_report.json"))
    innov = _rd(os.path.join(run_dir, "analysis", "innovations.json"))
    gaps = _rd(os.path.join(run_dir, "analysis", "gaps.json"))
    fc = _rd(os.path.join(run_dir, "factcheck", "factcheck.json"))
    revj = _rd(os.path.join(run_dir, "review", "review.json"))

    n_hits = hits.get("n_hits", 0)
    unavail = hits.get("unavailable_sources", []) or []
    src_status = hits.get("sources_status", {}) or {}
    n_read = read.get("n_read", 0)
    n_failed = read.get("n_failed", 0)
    n_innov = innov.get("n_total", 0)
    n_gaps = gaps.get("n_gaps", 0)
    cite = (fc.get("citations") or {})
    cite_rate = cite.get("consistency_rate", 0.0)
    n_contra = (fc.get("contradictions") or {}).get("n_contradictions", 0)
    final = revj.get("final", {}) if isinstance(revj, dict) else {}

    # 状态总表
    lines = ["| 步骤 | 状态 | 尝试次数 |", "| --- | --- | --- |"]
    for sid in _RESEARCH_STEPS:
        lines.append(f"| {sid} | {state.step_status[sid].value} | {state.attempts.get(sid, 0)} |")
    state_table = "\n".join(lines)

    def _evs(kind: str, step: str) -> list[str]:
        return [e["ev_id"] for e in prov.all_evidence()
                if e["kind"] == kind and e["producer_step"] == step]

    c1 = (f"多源检索（来源={hits.get('source', 'n/a')}）命中 {n_hits} 篇；"
          f"各源状态：{src_status}；不可用源：{unavail or '无'}"
          + ("（已自动切换源，任务未中断）" if unavail else "") + "。")
    c2 = (f"论文精读 {n_read} 篇成功、{n_failed} 篇失败（失败已跳过并标注，不阻塞流程）；"
          f"扫描件/低置信度 {read.get('scanned_or_low_conf', 0)} 篇。")
    c3 = f"创新点拆解共识别 {n_innov} 个创新点，识别 Research Gap {n_gaps} 个。"
    c4 = (f"事实验证：引用/观点一致性率 {cite_rate:.2%}，"
          f"检出文献间潜在矛盾 {n_contra} 处。")
    c5 = (f"综述草稿含引用标记；自评审综合分 "
          f"{final.get('overall', 'n/a')}/10，结论 {final.get('verdict', 'n/a')}。")

    ev_lit = _evs("literature", "R1_search")
    ev_note = _evs("note", "R2_read")
    ev_ana = _evs("analysis", "R3_analyze")
    ev_fc = _evs("factcheck", "R4_verify")
    ev_draft = _evs("draft", "R5_write")
    ev_rev = _evs("review", "R6_review")
    ev_r1_file = _evs("data", "R1_search")

    prov.link_conclusion("C1", c1, ev_lit or ev_r1_file)
    prov.link_conclusion("C2", c2, ev_note or ev_r1_file)
    prov.link_conclusion("C3", c3, ev_ana or ev_r1_file)
    prov.link_conclusion("C4", c4, ev_fc or ev_r1_file)
    prov.link_conclusion("C5", c5, ev_draft or ev_rev or ev_r1_file)

    ev_rows = ["| EV | 类型 | 引用 | SHA-256(前16) | 生产步骤 |",
               "| --- | --- | --- | --- | --- |"]
    for e in prov.all_evidence():
        ev_rows.append(f"| {e['ev_id']} | {e['kind']} | {e['ref']} | "
                       f"{(e.get('sha256') or '')[:16]} | {e['producer_step']} |")
    ev_table = "\n".join(ev_rows)

    degraded_block = ""
    if state.degraded:
        degraded_block = (
            "> **降级声明**：本 run 发生降级（degraded=true）。可能原因包括："
            "某检索源不可用已自动切换、论文解析失败已跳过、PDF 为扫描件/低置信度、"
            "综述存在悬空引用等。相关结论须结合降级说明人工复核。")

    all_steps = list(state.step_status.values())
    if any(st is StepStatus.FAILED for st in all_steps):
        final_status = RunStatus.FAILED.value
    elif all(st in (StepStatus.DONE, StepStatus.SKIPPED) for st in all_steps):
        final_status = RunStatus.DONE.value
    else:
        final_status = state.run_status.value

    repro = (
        f"cd {os.path.abspath(root)}\n"
        f"PYTHONPATH=core python -m paper_agent.cli run-all --workflow research "
        f"--goal \"<goal>\" --lit-source local\n"
        f"PYTHONPATH=core python -m paper_agent.cli resume --run {run_id}\n"
        f"PYTHONPATH=core python -m paper_agent.cli report --run {run_id}\n"
        f"# 异常恢复场景（PRD F-4.8）：\n"
        f"#   场景1 API超时降级  : --chaos ss_timeout\n"
        f"#   场景2 扫描件解析降级: --chaos scan_pdf\n"
        f"#   场景3 批量失败跳过  : --chaos batch_fail_at=2\n"
        f"#   长任务崩溃+续跑    : --chaos kill_after_r3 然后 resume\n"
    )

    report_md = f"""# paper-agent 科研报告（research 工作流）— {run_id}

- 研究问题: {state.goal or '（未设置）'}
- 工作流: research（R1 检索 → R2 精读 → R3 创新点 → R4 验证 → R5 写作 → R6 评审）
- 顶层状态: {final_status}
- 检索来源配置: lit_source={getattr(state, 'lit_source', 'auto')}
- 生成: {state.updated_at}

## 工作流状态总表

{state_table}

{degraded_block}

## 科研结论（证据绑定）

- **C1 多源检索**：{c1} `[{'; '.join(ev_lit or ev_r1_file)}]`
- **C2 论文精读**：{c2} `[{'; '.join(ev_note or ev_r1_file)}]`
- **C3 创新点/Gap**：{c3} `[{'; '.join(ev_ana or ev_r1_file)}]`
- **C4 事实验证**：{c4} `[{'; '.join(ev_fc or ev_r1_file)}]`
- **C5 写作/自评审**：{c5} `[{'; '.join(ev_draft or ev_rev or ev_r1_file)}]`

## 证据索引表

{ev_table}

## 复现命令

```bash
{repro}
```

> 数据红线：所有结论均来自真实检索元数据与本地解析产物；检索测试集为 demo 规模小样本标注，
> 用于演示指标口径，不代表真实世界性能。严禁伪造数据。
"""
    rpath = os.path.join(run_dir, "report.md")
    with open(rpath, "w", encoding="utf-8", newline="") as f:
        f.write(report_md)
    return rpath
