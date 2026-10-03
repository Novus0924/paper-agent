"""review.py — 模拟自评审（PRD F-6.1）。

以**审稿人视角**对综述/论文草稿做结构化评审，输出会议审稿模板：

    Summary / Strengths / Weaknesses / Detailed Comments / Score

五个维度：贡献度 / 技术正确性 / 实验充分性 / 写作清晰度 / 相关工作覆盖度。

零依赖、**确定性**：每个维度分数由**可测量的信号**按固定规则计算
（引用一致性率、未支撑句数、悬空引用、文献覆盖、数值证据密度……），
不是拍脑袋。同时提供「评审 → 修改 → 再评审」的**迭代闭环**，
直到阻塞性问题清零或达到迭代上限。
"""
from __future__ import annotations

import re

DIMENSIONS = ["贡献度", "技术正确性", "实验充分性", "写作清晰度", "相关工作覆盖度"]

# 判定为"阻塞性"（必须修复）的问题类型
BLOCKING_TAGS = {"dangling_citation", "no_citation_ratio", "no_evidence"}


def _clamp(x: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def _score_contribution(n_docs: int, n_innovations: int) -> tuple[float, str]:
    if n_innovations == 0:
        return 2.0, "未识别到明确创新点，贡献度存疑"
    base = 5.0 + min(3.0, n_innovations * 0.5) + min(2.0, n_docs * 0.2)
    return _clamp(base), f"识别 {n_innovations} 个创新点 / 覆盖 {n_docs} 篇文献"


def _score_correctness(cite_rate: float, has_factcheck: bool) -> tuple[float, str]:
    if not has_factcheck:
        return 5.0, "缺少事实验证输入，技术正确性无法充分评估"
    return _clamp(3.0 + cite_rate * 7.0), f"引用一致性率 {cite_rate:.1%}"


def _score_experiments(n_numeric: int, has_ablation: bool) -> tuple[float, str]:
    base = 3.0 + min(5.0, n_numeric * 0.5) + (2.0 if has_ablation else 0.0)
    return _clamp(base), f"含数值证据 {n_numeric} 处；消融实验 {'有' if has_ablation else '无'}"


def _score_clarity(unsupported: int, dangling: int, n_sentences: int) -> tuple[float, str]:
    bad = unsupported + dangling * 2
    base = 10.0 - (bad / max(1, n_sentences)) * 10.0
    return _clamp(base), f"未支撑句 {unsupported} 处；悬空引用 {dangling} 处"


def _score_related_work(n_docs: int, year_span: int) -> tuple[float, str]:
    base = 2.0 + min(6.0, n_docs * 0.6) + min(2.0, year_span * 0.2)
    return _clamp(base), f"纳入 {n_docs} 篇，年份跨度 {year_span} 年"


def _count_statements(md: str) -> int:
    """统计草稿中的**实质性陈述条数**（用于清晰度归一）。

    不能只数 ``- `` 开头的行：纯散文草稿会得到 0，导致
    ``bad / max(1, n_sentences)`` 分母退化为 1，清晰度分数虚高。
    这里同时计入：列表项、以及按句子切分后的正文句（长度 ≥ 20）。
    """
    bullets = sum(1 for ln in md.split("\n") if ln.strip().startswith(("- ", "* ")))
    body = "\n".join(ln for ln in md.split("\n")
                     if ln.strip() and not ln.strip().startswith(("#", "- ", "* ", ">")))
    sents = [s for s in re.split(r"(?<=[.!?。！？])\s+", body) if len(s.strip()) >= 20]
    return max(1, bullets + len(sents))


def self_review(draft_markdown: str, docs: list[dict] | None = None,
                analyses: list[dict] | None = None,
                factcheck: dict | None = None,
                gaps: dict | None = None) -> dict:
    """对草稿做一次模拟评审。返回结构化审稿意见。"""
    docs = docs or []
    analyses = analyses or []
    md = draft_markdown or ""

    n_docs = len(docs)
    n_innovations = sum(a.get("n_innovations", 0) for a in analyses)
    cite_rate = float((factcheck or {}).get("consistency_rate", 0.0))
    has_factcheck = bool(factcheck is not None and (factcheck or {}).get("n", 0))

    # 可测量信号
    unsupported = len(re.findall(r"\[需补充引用\]", md))
    refs = re.findall(r"\[([^\]\n]+)\]", md)
    known = {d.get(k) for d in docs for k in ("doc_id", "doi", "url") if d.get(k)}
    dangling = [r for r in refs if not r.startswith(("需补充引用", "GAP", "IN-")) and r not in known]
    # 量化证据：百分数 / "percent(age)" / "N倍|Nx|N times" / 科学计数 / 4 位年份
    n_numeric = (len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|percent|pct)", md, re.I))
                 + len(re.findall(r"\d+(?:\.\d+)?\s*(?:倍|x\b|times)", md, re.I))
                 + len(re.findall(r"\d(?:\.\d+)?[eE][+-]?\d+", md))
                 + len(re.findall(r"\b\d{4}\b", md)) // 3)
    has_ablation = "消融" in md or "ablation" in md.lower()
    years = [int(d.get("year") or 0) for d in docs if d.get("year")]
    year_span = (max(years) - min(years)) if years else 0
    n_sentences = _count_statements(md)

    scores: dict[str, float] = {}
    rationales: dict[str, str] = {}
    for dim, fn in (
        ("贡献度", lambda: _score_contribution(n_docs, n_innovations)),
        ("技术正确性", lambda: _score_correctness(cite_rate, bool(has_factcheck))),
        ("实验充分性", lambda: _score_experiments(n_numeric, has_ablation)),
        ("写作清晰度", lambda: _score_clarity(unsupported, len(dangling), n_sentences)),
        ("相关工作覆盖度", lambda: _score_related_work(n_docs, year_span)),
    ):
        s, r = fn()
        scores[dim] = round(float(s), 2)
        rationales[dim] = r

    overall = round(sum(scores.values()) / len(scores), 2)

    # 问题清单
    issues: list[dict] = []
    if dangling:
        issues.append({"tag": "dangling_citation", "severity": "blocking",
                       "detail": f"存在悬空引用（文献集合中不存在）：{dangling[:5]}"})
    if unsupported > 0:
        issues.append({"tag": "no_citation_ratio", "severity": "blocking",
                       "detail": f"{unsupported} 处陈述标注 [需补充引用]，必须补证或删除"})
    if n_numeric == 0:
        issues.append({"tag": "no_evidence", "severity": "blocking",
                       "detail": "正文缺乏量化结果，实验充分性不足"})
    if n_docs < 3:
        issues.append({"tag": "thin_related_work", "severity": "major",
                       "detail": f"仅纳入 {n_docs} 篇文献，相关工作覆盖不足"})
    if not has_factcheck:
        issues.append({"tag": "no_factcheck", "severity": "major",
                       "detail": "未提供事实验证结果，技术正确性无法核验"})
    if year_span and year_span < 3:
        issues.append({"tag": "narrow_time_span", "severity": "minor",
                       "detail": f"文献年份跨度仅 {year_span} 年，脉络可能不全"})

    strengths = []
    if scores["相关工作覆盖度"] >= 7:
        strengths.append("相关工作覆盖较充分，" + rationales["相关工作覆盖度"])
    if n_innovations > 0:
        strengths.append("创新点归纳明确，" + rationales["贡献度"])
    if cite_rate >= 0.8:
        strengths.append("引用可溯源，" + rationales["技术正确性"])
    if not strengths:
        strengths.append("（当前草稿尚未形成明显优点，建议先补齐证据与引用）")

    weaknesses = [f"[{i['severity']}] {i['detail']}" for i in issues] or ["未发现明显问题"]

    blocking = [i for i in issues if i["severity"] == "blocking"]
    verdict = ("Reject/Accept? → 需大修（Major Revision）" if blocking else
               "Minor Revision" if any(i["severity"] == "major" for i in issues) else
               "Accept（P0 草稿级）")

    summary = (f"本文围绕草稿组织 {n_sentences} 条陈述，纳入文献 {n_docs} 篇、"
               f"创新点 {n_innovations} 个，综合评分 {overall}/10。{verdict}")
    return {
        "summary": summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "detailed_comments": issues,
        "scores": scores,
        "overall": overall,
        "verdict": verdict,
        "blocking_issues": blocking,
        "n_blocking": len(blocking),
        "signals": {
            "n_docs": n_docs, "n_innovations": n_innovations,
            "cite_rate": cite_rate, "unsupported": unsupported,
            "n_dangling": len(dangling), "n_numeric": n_numeric,
            "year_span": year_span, "n_statements": n_sentences,
        },
    }


def revision_actions(review: dict) -> list[str]:
    """把审稿意见转成可执行的修改动作清单（供迭代闭环使用）。"""
    actions = []
    for i in review.get("detailed_comments", []):
        tag = i.get("tag")
        if tag == "dangling_citation":
            actions.append("删除或修正文献集合中不存在的悬空引用")
        elif tag == "no_citation_ratio":
            actions.append("为 [需补充引用] 的陈述补上真实引用，无法补证则删除该句")
        elif tag == "no_evidence":
            actions.append("补充量化实验/结果数字，或明确标注为定性综述")
        elif tag == "thin_related_work":
            actions.append("扩展检索以纳入更多相关工作（≥3 篇）")
        elif tag == "no_factcheck":
            actions.append("运行事实验证（引用核查 + 数据一致性）后再评审")
        elif tag == "narrow_time_span":
            actions.append("补充更早期/更近期工作以拉长时间脉络")
    return actions


def review_loop(draft_markdown: str, docs, analyses=None, factcheck=None,
                gaps=None, revise=None, max_iters: int = 3) -> dict:
    """迭代闭环：评审 → （可选）修改 → 再评审，直到阻塞性问题清零。

    ``revise(review, draft) -> (new_draft, new_factcheck)`` 为可选修改回调；
    不提供回调时，仅评估当前草稿是否达标（单轮）。
    """
    history: list[dict] = []
    draft = draft_markdown
    fc = factcheck
    for it in range(1, max_iters + 1):
        rev = self_review(draft, docs, analyses, fc, gaps)
        rev["iteration"] = it
        rev["actions"] = revision_actions(rev)
        history.append({"iteration": it, "overall": rev["overall"],
                        "n_blocking": rev["n_blocking"], "verdict": rev["verdict"]})
        if rev["n_blocking"] == 0 or revise is None:
            return {"final": rev, "history": history, "converged": rev["n_blocking"] == 0,
                    "iterations": it}
        new_draft, new_fc = revise(rev, draft)
        if new_draft == draft and (new_fc is fc or new_fc == fc):
            return {"final": rev, "history": history, "converged": False,
                    "iterations": it, "note": "修改回调未产生变化，提前停止"}
        draft, fc = new_draft, new_fc
    final = self_review(draft, docs, analyses, fc, gaps)
    final["iteration"] = max_iters
    final["actions"] = revision_actions(final)
    return {"final": final, "history": history,
            "converged": final["n_blocking"] == 0, "iterations": max_iters}


def render_review_md(review: dict) -> str:
    lines = ["# 模拟审稿意见（Reviewer Report）", ""]
    lines.append(f"## Summary\n{review['summary']}")
    lines.append("")
    lines.append("## Strengths")
    for s in review["strengths"]:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("## Weaknesses")
    for w in review["weaknesses"]:
        lines.append(f"- {w}")
    lines.append("")
    lines.append("## Detailed Comments")
    for i in review.get("detailed_comments", []):
        lines.append(f"- [{i['severity']}] ({i['tag']}) {i['detail']}")
    lines.append("")
    lines.append("## Score")
    for dim in DIMENSIONS:
        lines.append(f"- {dim}: {review['scores'][dim]}/10")
    lines.append(f"- **Overall: {review['overall']}/10 —— {review['verdict']}**")
    return "\n".join(lines)


__all__ = ["DIMENSIONS", "self_review", "revision_actions", "review_loop",
           "render_review_md"]
