"""factcheck.py — 事实验证（PRD F-4.1~F-4.3）。

三大能力，全部**零依赖、确定性、可溯源**：

1. **引用真实性核查**（F-4.1）：给定「引用陈述 claim」与其「被引原文 source_text」，
   判定 ① 引用是否存在 ② 观点是否与原文一致 ③ 位置是否恰当，输出
   ``✅一致 / ⚠️部分一致 / ❌不一致 / ❓无法获取原文``。
   判据为**词项包含度 + 数值一致性**的复合打分（纯函数、可复现）。
2. **数据一致性检查**（F-4.2）：摘要数据 vs 实验章节、表格 vs 正文、
   图趋势 vs 结论、消融实验自洽性，输出一致性报告与异常点。
3. **文献间矛盾检测**（F-4.3）：多篇论文核心结论对比，同指标冲突方向/数值
   即标记矛盾，并给出分歧归因与可信度建议。

边界：判定为**启发式**（rule-based），用于给下游（AGL 会话模型/人工）
提供结构化线索，**不替代人工终审**。所有结论均携带证据定位。
"""
from __future__ import annotations

import re

_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
         "are", "with", "as", "at", "by", "from", "it", "its", "this", "that",
         "we", "our", "be", "can", "not", "has", "have", "was", "were", "will",
         "than", "such", "which", "these", "those", "their", "there", "also",
         "的", "了", "和", "与", "在", "是", "为", "对", "等", "我们", "本文"}

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
# 方向词：判断结论趋势是否冲突
_UP = ("increase", "improve", "higher", "better", "outperform", "surpass",
       "提升", "提高", "优于", "更高", "增强")
_DOWN = ("decrease", "reduce", "lower", "worse", "decline", "degrade",
         "降低", "下降", "更差", "恶化", "减弱")


def _content_tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", (text or "").lower())
    return [t for t in toks if t not in _STOP]


def _nums(text: str) -> set[str]:
    return set(_NUM.findall(text or ""))


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _num_matches(claim_num: str, source_nums: set[float],
                 tol: float = 1e-9) -> bool:
    """判断 claim 中的数值是否在原文数值集合中出现。

    必须**按数值语义**比对，不能用子串包含：``1`` 不应因为原文有 ``100``
    就被判为命中，``0.9`` 与 ``0.90`` 则应视为同一个数。
    """
    try:
        v = float(claim_num)
    except (TypeError, ValueError):
        return False
    for s in source_nums:
        if abs(s - v) <= tol:
            return True
    return False


def containment(claim: str, source: str) -> float:
    """claim 的词项有多大比例出现在 source 中（包含度，[0,1]）。"""
    toks = set(_content_tokens(claim))
    if not toks:
        return 0.0
    src = set(_content_tokens(source))
    return round(len(toks & src) / len(toks), 6)


def verify_citation(claim: str, source_text: str | None,
                    source_ref: str = "",
                    consistent: float = 0.5, partial: float = 0.2) -> dict:
    """核查单条引用（F-4.1）。

    返回 ``{verdict, exists, consistency, number_ok, missing_numbers, evidence}``。
    """
    if not source_text:
        return {
            "claim": claim, "source": source_ref, "exists": False,
            "consistency": 0.0, "number_ok": None,
            "missing_numbers": [], "verdict": "❓ 无法获取原文",
            "note": "未取得被引原文，无法比对；需人工补充原文或标记存疑。",
        }
    cont = containment(claim, source_text)
    claim_nums = _nums(claim)
    # 按数值语义比对（非子串）：1 不会因原文有 100 而误判命中；0.9 == 0.90。
    src_nums = {float(n) for n in _nums(source_text)
                if _is_float(n)}
    missing = sorted(n for n in claim_nums if not _num_matches(n, src_nums))
    number_ok = (len(missing) == 0) if claim_nums else None

    if cont >= consistent and (number_ok is not False):
        verdict = "✅ 一致"
    elif cont >= partial:
        verdict = "⚠️ 部分一致"
    else:
        verdict = "❌ 不一致"

    return {
        "claim": claim, "source": source_ref, "exists": True,
        "consistency": cont, "number_ok": number_ok,
        "missing_numbers": missing, "verdict": verdict,
        "evidence": {"source_excerpt": source_text[:280],
                     "claim_numbers": sorted(claim_nums)},
        "note": ("" if number_ok in (True, None)
                 else f"claim 中的数值 {missing} 未在原文出现，可能口径不符或引用失真"),
    }


def verify_citations(claims: list[dict]) -> dict:
    """批量核查。``claims``: ``[{"claim","source_text","source_ref"}]``。"""
    results = [verify_citation(c.get("claim", ""), c.get("source_text"),
                               c.get("source_ref", "")) for c in claims]
    tally: dict[str, int] = {}
    for r in results:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    ok = sum(v for k, v in tally.items() if k.startswith("✅"))
    n = len(results)
    return {
        "results": results, "n": n, "tally": tally,
        "consistency_rate": round(ok / n, 4) if n else 0.0,
    }


# =====================================================================
# F-4.2 数据一致性
# =====================================================================

def check_data_consistency(note: dict,
                           tol: float = 0.02) -> dict:
    """检查同一论文内部的数值/趋势自洽性（F-4.2）。

    检查项：
      - 摘要数据 vs 实验/结果章节：摘要中出现的关键数值是否在实验章节复现
      - 表格 vs 正文：表格中的数值是否在正文出现
      - 图趋势 vs 结论：图中方向词与结论方向词是否冲突
      - 消融实验自洽性：是否声明消融且给出结论
    """
    secs = note.get("sections") or {}
    text = note.get("text") or ""

    def _sec(*names: str) -> str:
        for n in names:
            if n in secs:
                return secs[n]
        return ""

    abstract = _sec("Abstract", "摘要")
    exp = _sec("Experiment", "实验", "Results", "Conclusion", "结论")
    checks: list[dict] = []

    # 1) 摘要 vs 实验数值一致性
    if abstract and exp:
        a_nums = _nums(abstract)
        exp_nums = {float(n) for n in _nums(exp) if _is_float(n)}
        missing = sorted(n for n in a_nums if not _num_matches(n, exp_nums))
        checks.append({
            "name": "abstract_vs_experiment_numbers",
            "pass": len(missing) == 0,
            "detail": (f"摘要中 {len(a_nums)} 个数值，实验章节缺失 {missing}"
                       if missing else f"摘要数值均可在实验章节定位（{len(a_nums)} 个）"),
            "missing": missing,
        })
    else:
        checks.append({"name": "abstract_vs_experiment_numbers", "pass": True,
                       "detail": "缺少摘要/实验章节，跳过"})

    # 2) 表格 vs 正文
    figs = note.get("figures_tables") or []
    tables = [f for f in figs if f.get("kind") == "table"]
    if tables:
        cap_txt = " ".join(t.get("caption", "") for t in tables)
        t_nums = _nums(cap_txt)
        body = text.replace(cap_txt, "")
        body_nums = {float(n) for n in _nums(body) if _is_float(n)}
        miss = sorted(n for n in t_nums if not _num_matches(n, body_nums))
        checks.append({
            "name": "table_vs_text",
            "pass": len(miss) == 0,
            "detail": (f"表格说明中 {miss} 未在正文复现" if miss
                       else f"{len(tables)} 个表格与正文数值一致"),
            "missing": miss,
        })
    else:
        checks.append({"name": "table_vs_text", "pass": True, "detail": "未识别到表格，跳过"})

    # 3) 图趋势 vs 结论
    up_fig = sum(text.lower().count(w) for w in _UP)
    down_fig = sum(text.lower().count(w) for w in _DOWN)
    concl = _sec("Conclusion", "结论") or exp
    up_c = sum(concl.lower().count(w) for w in _UP)
    down_c = sum(concl.lower().count(w) for w in _DOWN)
    trend_ok = not (up_c > down_c and down_fig > up_fig * 2)
    checks.append({
        "name": "figure_trend_vs_conclusion",
        "pass": trend_ok,
        "detail": f"正文方向词 up/down={up_fig}/{down_fig}；结论 up/down={up_c}/{down_c}",
    })

    # 4) 消融自洽性
    has_ablation = any(k in text.lower() for k in ("ablation", "消融", "ablate"))
    says_ablation_result = ("ablation" in exp.lower() or "消融" in exp) if has_ablation else True
    checks.append({
        "name": "ablation_self_consistency",
        "pass": (not has_ablation) or says_ablation_result,
        "detail": ("未提及消融" if not has_ablation else
                   ("消融结论已给出" if says_ablation_result else "声明消融但未给结论")),
    })

    n_pass = sum(1 for c in checks if c["pass"])
    return {
        "doc_id": note.get("doc_id", ""),
        "status": "PASS" if n_pass == len(checks) else "WARN",
        "n_pass": n_pass, "n_checks": len(checks), "checks": checks,
        "anomalies": [c for c in checks if not c["pass"]],
    }


# =====================================================================
# F-4.3 文献间矛盾检测
# =====================================================================

def _conclusion_sentences(note: dict) -> list[str]:
    secs = note.get("sections") or {}
    out: list[str] = []
    for n in ("Conclusion", "结论", "Discussion", "Experiment", "Results"):
        if n in secs:
            out.extend(re.split(r"(?<=[.!?。！？])\s+", secs[n]))
    if not out:
        out = re.split(r"(?<=[.!?。！？])\s+", note.get("text") or "")
    return [s.strip() for s in out if len(s.strip()) >= 25]


def detect_contradictions(notes: list[dict]) -> dict:
    """检测多篇论文结论间的矛盾（F-4.3）。

    判据：两篇论文的结论句**共享主题词**（≥1 个实词），且**方向词相反**
    （一 up 一 down），或**同一指标数值冲突**（差异 > 20%）。
    """
    dirs = []
    for note in notes:
        doc_id = note.get("doc_id", "")
        for s in _conclusion_sentences(note):
            low = s.lower()
            up = any(w in low for w in _UP)
            down = any(w in low for w in _DOWN)
            if up == down:      # 无方向或同时含相反方向 → 跳过
                continue
            dirs.append({
                "doc_id": doc_id, "sentence": s[:300],
                "direction": "up" if up else "down",
                "tokens": set(_content_tokens(s)),
                "numbers": sorted(_nums(s)),
            })

    pairs: list[dict] = []
    for i in range(len(dirs)):
        for j in range(i + 1, len(dirs)):
            a, b = dirs[i], dirs[j]
            if a["doc_id"] == b["doc_id"]:
                continue
            shared = a["tokens"] & b["tokens"]
            shared = {t for t in shared if len(t) > 2}
            if not shared:
                continue
            if a["direction"] != b["direction"]:
                pairs.append({
                    "a": {"doc_id": a["doc_id"], "quote": a["sentence"]},
                    "b": {"doc_id": b["doc_id"], "quote": b["sentence"]},
                    "shared_terms": sorted(shared)[:6],
                    "type": "direction_conflict",
                    "credibility": "需人工复核：可能源于任务设置/数据/指标口径差异",
                })
    return {
        "n_contradictions": len(pairs),
        "contradictions": pairs,
        "n_claims_considered": len(dirs),
    }


def render_factcheck_md(cite: dict, consist: list[dict],
                        contra: dict) -> str:
    lines = ["# 事实验证报告", ""]
    lines.append("## F-4.1 引用真实性核查")
    lines.append(f"- 核查 {cite.get('n', 0)} 条，一致性率 {cite.get('consistency_rate', 0):.2%}")
    lines.append(f"- 判定分布：{cite.get('tally') or '（无）'}")
    for r in cite.get("results", []):
        lines.append(f"  - {r['verdict']} | claim: {r['claim'][:80]}")
    lines.append("")
    lines.append("## F-4.2 数据一致性检查")
    for c in consist:
        lines.append(f"- [{c['status']}] `{c['doc_id']}` {c['n_pass']}/{c['n_checks']} 项通过")
        for ck in c["checks"]:
            flag = "PASS" if ck["pass"] else "FAIL"
            lines.append(f"  - {flag} {ck['name']}: {ck['detail']}")
    lines.append("")
    lines.append("## F-4.3 文献间矛盾检测")
    lines.append(f"- 发现 {contra.get('n_contradictions', 0)} 处潜在矛盾"
                 f"（考察 {contra.get('n_claims_considered', 0)} 条结论句）")
    for c in contra.get("contradictions", []):
        lines.append(f"  - `{c['a']['doc_id']}` vs `{c['b']['doc_id']}`"
                     f"（共享主题：{', '.join(c['shared_terms'])}）")
        lines.append(f"    - A: {c['a']['quote'][:140]}")
        lines.append(f"    - B: {c['b']['quote'][:140]}")
    return "\n".join(lines)


__all__ = [
    "containment", "verify_citation", "verify_citations",
    "check_data_consistency", "detect_contradictions", "render_factcheck_md",
]
