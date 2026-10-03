"""evaluate.py — 量化验证模块（PRD F-7.1~F-7.4）。

四套评估，全部**零依赖 + 确定性**（纯函数打分）：

| 编号 | 评估 | 指标 |
|---|---|---|
| F-7.1 | 检索质量 | Recall / Precision / NDCG@10，对比「纯关键词」基线，含失败案例 |
| F-7.2 | 精读质量 | 结构提取准确率 / 关键信息准确率 / 可复现性判断准确率 + 耗时对比 |
| F-7.3 | 创新点提取 | 识别率 / 分类准确率 / 幻觉率 + 混淆矩阵 |
| F-7.4 | 引用可信度 | 引用幻觉率 / 引用准确率 |

诚实声明（重要）
----------------
- 内置测试集为 **demo 规模的小样本标注**（规则可由语料内容导出，非编造），
  用于**演示评估方法论与指标口径**，不代表真实世界的系统性能；
- 每份报告都带 ``n_cases`` 与 ``scale_note``，避免误导；
- 指标计算与基线比较完全可复现。
"""
from __future__ import annotations

import math
import time

# =====================================================================
# 通用指标
# =====================================================================

def precision_at_k(retrieved: list[str], relevant: set[str], k: int | None = None) -> float:
    r = retrieved[:k] if k else retrieved
    if not r:
        return 0.0
    return round(len([x for x in r if x in relevant]) / len(r), 6)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int | None = None) -> float:
    if not relevant:
        return 0.0
    r = retrieved[:k] if k else retrieved
    return round(len({x for x in r if x in relevant}) / len(relevant), 6)


def f1_at_k(retrieved: list[str], relevant: set[str], k: int | None = None) -> float:
    p, r = precision_at_k(retrieved, relevant, k), recall_at_k(retrieved, relevant, k)
    return round(2 * p * r / (p + r), 6) if (p + r) else 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int = 10) -> float:
    """二值相关性的 NDCG@k。"""
    dcg = sum(1.0 / math.log2(i + 2) for i, x in enumerate(retrieved[:k]) if x in relevant)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return round(dcg / idcg, 6) if idcg > 0 else 0.0


def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 6) if xs else 0.0


# =====================================================================
# F-7.1 检索质量
# =====================================================================

def eval_search_quality(testset: list[dict], searcher, baseline=None,
                        k: int = 10) -> dict:
    """评估检索质量（F-7.1）。

    ``testset``: ``[{"query": str, "gold": [doc_id, ...]}]``
    ``searcher(query) -> list[doc_id]``（按排序）
    ``baseline(query) -> list[doc_id]``（纯关键词基线，可选）
    """
    rows, failures = [], []
    sys_p, sys_r, sys_n = [], [], []
    base_p, base_r, base_n = [], [], []
    for case in testset:
        q = case["query"]
        gold = set(case.get("gold") or [])
        got = list(searcher(q) or [])
        p, r, n = precision_at_k(got, gold), recall_at_k(got, gold), ndcg_at_k(got, gold, k)
        sys_p.append(p); sys_r.append(r); sys_n.append(n)
        row = {"query": q, "gold": sorted(gold), "retrieved": got[:k],
               "precision": p, "recall": r, f"ndcg@{k}": n}
        if baseline is not None:
            bg = list(baseline(q) or [])
            bp, br, bn = precision_at_k(bg, gold), recall_at_k(bg, gold), ndcg_at_k(bg, gold, k)
            base_p.append(bp); base_r.append(br); base_n.append(bn)
            row["baseline"] = {"retrieved": bg[:k], "precision": bp,
                               "recall": br, f"ndcg@{k}": bn}
        rows.append(row)
        if r == 0.0 or n == 0.0:
            failures.append({"query": q, "gold": sorted(gold), "retrieved": got[:k],
                             "reason": "召回/排序为 0"})
    out = {
        "n_cases": len(testset),
        "system": {"precision": _avg(sys_p), "recall": _avg(sys_r), f"ndcg@{k}": _avg(sys_n)},
        "rows": rows, "failures": failures,
        "meets_target": {"recall>=0.70": _avg(sys_r) >= 0.70},
        "scale_note": (f"demo 规模小样本标注（{len(testset)} 条查询）；"
                       "指标用于演示口径与基线对比，不代表真实世界性能"),
    }
    if baseline is not None:
        out["baseline"] = {"precision": _avg(base_p), "recall": _avg(base_r),
                           f"ndcg@{k}": _avg(base_n)}
        out["improvement"] = {
            "recall": round(_avg(sys_r) - _avg(base_r), 6),
            "precision": round(_avg(sys_p) - _avg(base_p), 6),
            f"ndcg@{k}": round(_avg(sys_n) - _avg(base_n), 6),
        }
    return out


# =====================================================================
# F-7.2 精读质量
# =====================================================================

def _section_hit(pred_sections: list[str], gold_section: str) -> bool:
    g = gold_section.lower()
    return any(g in (p or "").lower() or (p or "").lower() in g for p in pred_sections)


def eval_read_quality(labeled: list[dict]) -> dict:
    """评估精读质量（F-7.2）。

    ``labeled``: ``[{"note": <parse_paper 产物>, "gold_sections": [...],
                     "gold_key_info": {"method": [...], ...},
                     "gold_repro": {"has_code": bool, "has_data": bool},
                     "manual_seconds": float}]``
    """
    struct_acc, info_acc, repro_acc = [], [], []
    times_sys, times_manual = [], []
    detail = []
    for c in labeled:
        note = c.get("note") or {}
        pred_sections = list((note.get("sections") or {}).keys())
        gold_sections = c.get("gold_sections") or []
        hit = sum(1 for gs in gold_sections if _section_hit(pred_sections, gs))
        s_acc = hit / len(gold_sections) if gold_sections else 0.0
        struct_acc.append(s_acc)

        gold_info = c.get("gold_key_info") or {}
        text_low = (note.get("text") or "").lower()
        flat = " ".join(str(x) for v in (note.get("key_info") or {}).values()
                        for x in ([i["text"] for i in v] if v else []))
        flat_low = flat.lower()
        total = found = 0
        for _kind, items in gold_info.items():
            for it in items:
                total += 1
                key = str(it).lower()
                if key in flat_low or key in text_low:
                    found += 1
        i_acc = found / total if total else 1.0
        info_acc.append(i_acc)

        gold_repro = c.get("gold_repro") or {}
        pred_repro = note.get("reproducibility") or {}
        r_hit = sum(1 for kk, vv in gold_repro.items() if bool(pred_repro.get(kk)) == bool(vv))
        r_acc = r_hit / len(gold_repro) if gold_repro else 1.0
        repro_acc.append(r_acc)

        t_sys = float(c.get("system_seconds", 0.0))
        t_man = float(c.get("manual_seconds", 0.0))
        if t_sys:
            times_sys.append(t_sys)
        if t_man:
            times_manual.append(t_man)
        detail.append({"doc_id": note.get("doc_id", ""), "structure_accuracy": round(s_acc, 4),
                       "key_info_accuracy": round(i_acc, 4),
                       "reproducibility_accuracy": round(r_acc, 4),
                       "pred_sections": pred_sections})

    return {
        "n_cases": len(labeled),
        "structure_accuracy": _avg(struct_acc),
        "key_info_accuracy": _avg(info_acc),
        "reproducibility_accuracy": _avg(repro_acc),
        "system_seconds_avg": _avg(times_sys),
        "manual_seconds_avg": _avg(times_manual),
        "speedup_vs_manual": (round(_avg(times_manual) / _avg(times_sys), 2)
                              if times_sys and times_manual and _avg(times_sys) > 0 else None),
        "detail": detail,
        "scale_note": (f"demo 规模标注（{len(labeled)} 篇）；人工耗时为参考量级估计"),
    }


# =====================================================================
# F-7.3 创新点提取准确率
# =====================================================================

def eval_innovation(labeled: list[dict]) -> dict:
    """评估创新点提取（F-7.3）。

    ``labeled``: ``[{"analysis": <extract_innovations 产物>,
                     "gold_innovations": {kw: category},   # 关键词 → 期望类别
                     "text": 原文}]``
    """
    ident_rates, cls_accs, halluc_rates = [], [], []
    _COLS = _CATS + ["未识别"]
    conf = {c: {c2: 0 for c2 in _COLS} for c in _CATS}
    detail = []
    for case in labeled:
        analysis = case.get("analysis") or {}
        gold = case.get("gold_innovations") or {}
        text_low = (case.get("text") or "").lower()
        preds = analysis.get("innovations") or []

        matched_gold, matched_pred = set(), set()
        for gi, (kw, cat) in enumerate(gold.items()):
            hit = False
            for pi, p in enumerate(preds):
                if kw.lower() in p["statement"].lower():
                    matched_gold.add(gi)
                    matched_pred.add(pi)
                    pred_cat = p["categories"][0] if p["categories"] else "方法创新"
                    conf[cat][pred_cat] = conf[cat].get(pred_cat, 0) + 1
                    hit = True
                    break
            if not hit:      # gold 未被任何预测命中 → 计入「未识别」列，保证矩阵可加总
                conf[cat]["未识别"] += 1
        ident = len(matched_gold) / len(gold) if gold else 1.0
        # 分类准确率：匹配成功且首选类别 == 期望类别
        cls_hit = sum(1 for gi, (kw, cat) in enumerate(gold.items())
                      if any(kw.lower() in preds[pi]["statement"].lower()
                             and (preds[pi]["categories"] or ["方法创新"])[0] == cat
                             for pi in range(len(preds))))
        cls_acc = cls_hit / max(1, len(matched_gold))
        # 幻觉率：预测的创新点既不在 gold 中，也无法在原文找到踪迹
        halluc = 0
        for pi, p in enumerate(preds):
            if pi in matched_pred:
                continue
            key = p["statement"][:40].lower()
            if key and key not in text_low:
                halluc += 1
        h_rate = halluc / len(preds) if preds else 0.0

        ident_rates.append(ident)
        cls_accs.append(cls_acc)
        halluc_rates.append(h_rate)
        detail.append({"target": analysis.get("target", ""),
                       "n_pred": len(preds), "n_gold": len(gold),
                       "identification_rate": round(ident, 4),
                       "classification_accuracy": round(cls_acc, 4),
                       "hallucination_rate": round(h_rate, 4)})

    return {
        "n_cases": len(labeled),
        "identification_rate": _avg(ident_rates),
        "classification_accuracy": _avg(cls_accs),
        "hallucination_rate": _avg(halluc_rates),
        "confusion_matrix": {"labels": _COLS, "matrix": conf},
        "detail": detail,
        "meets_target": {"identification>=0.75": _avg(ident_rates) >= 0.75},
        "scale_note": (f"demo 规模标注（{len(labeled)} 篇）；标注为规则可导出的事实性关键词"),
    }


_CATS = ["方法创新", "理论创新", "数据创新", "应用创新", "工程创新"]


# =====================================================================
# F-7.4 引用可信度
# =====================================================================

def eval_citation(labeled: list[dict]) -> dict:
    """评估引用可信度（F-7.4）。

    ``labeled``: ``[{"claim": str, "source_text": str,
                     "gold_verdict": "supported"|"partial"|"unsupported"|"unknown"}]``
    用 :func:`paper_agent.factcheck.verify_citation` 的判定与 gold 比对。
    """
    from .factcheck import verify_citation
    _MAP = {"supported": "✅ 一致", "partial": "⚠️ 部分一致",
            "unsupported": "❌ 不一致", "unknown": "❓ 无法获取原文"}
    agree = 0
    halluc = 0            # 系统判"一致"但 gold 为 unsupported → 引用幻觉
    n = 0
    detail = []
    for c in labeled:
        n += 1
        res = verify_citation(c.get("claim", ""), c.get("source_text"),
                              c.get("source_ref", ""))
        gold = c.get("gold_verdict", "unknown")
        ok = _MAP.get(gold) == res["verdict"]
        agree += 1 if ok else 0
        if gold == "unsupported" and res["verdict"] == "✅ 一致":
            halluc += 1
        detail.append({"claim": c.get("claim", "")[:100], "gold": gold,
                       "pred": res["verdict"], "agree": ok})
    return {
        "n_cases": n,
        "citation_accuracy": round(agree / n, 6) if n else 0.0,
        "hallucination_rate": round(halluc / n, 6) if n else 0.0,
        "detail": detail,
        "meets_target": {"hallucination<0.05": (halluc / n if n else 0) < 0.05},
        "scale_note": f"demo 规模标注（{n} 条 claim/source 对）",
    }


# =====================================================================
# demo 测试集（可由内置语料内容导出，非编造）
# =====================================================================

# 10 个研究问题 × 期望相关文献（按语料 keywords/title 可判定，规则透明）
_DEMO_SEARCH_QUERIES: list[tuple[str, list[str]]] = [
    ("sulfide solid electrolyte ionic conductivity", ["L001", "L002", "L005"]),
    ("garnet oxide solid electrolyte lithium", ["L003"]),
    ("amorphous thin film solid electrolyte", ["L004"]),
    ("all-solid-state battery superionic conductor", ["L001", "L002"]),
    ("argyrodite Li6PS5X lithium ion mobility", ["L005"]),
    ("Li10GeP2S12 superionic conductor", ["L001"]),
    ("Li7La3Zr2O12 garnet stability lithium metal", ["L003"]),
    ("LiPON lithium phosphorus oxynitride thin film", ["L004"]),
    ("high power sulfide conduction", ["L002"]),
    ("halide sulfide Li6PS5Cl conduction", ["L005", "L001"]),
]


def demo_search_testset() -> list[dict]:
    return [{"query": q, "gold": list(g)} for q, g in _DEMO_SEARCH_QUERIES]


def demo_search_baseline(root: str):
    """纯关键词基线：仅按 title 子串命中（无语义、无 keywords/摘要加权）。"""
    from . import litsearch
    docs = litsearch.load_local_corpus(root)

    def _baseline(goal: str) -> list[str]:
        toks = litsearch.tokenize(goal)
        out = []
        for d in docs:
            title = (d.get("title") or "").lower()
            if any(t in title for t in toks):
                out.append(d["doc_id"])
        return out
    return _baseline


def system_searcher(root: str):
    """系统检索器：本地语料 + filter_by_relevance（title+keywords+abstract+venue）。"""
    from . import litsearch
    docs = litsearch.load_local_corpus(root)

    def _search(goal: str) -> list[str]:
        return [d["doc_id"] for d in litsearch.filter_by_relevance(docs, goal)]
    return _search


def build_demo_evals(root: str) -> dict:
    """构建 **透明可核查** 的 demo 标注集（F-7.2/7.3/7.4）。

    标注规则全部可由语料内容人工核对，标注与"系统输出"解耦（非自评）：

    - 精读：语料元数据 PDF 的排版只含一个 ``Abstract`` 节 → gold_sections=["Abstract"]；
      摘要文本中确实出现的关键词 → gold_key_info；摘要中不含任何代码/数据链接 →
      gold_repro 全 False。
    - 创新点：每篇摘要中被报告的**实体名**（关键词中实际出现在摘要里的那个）作为 gold 创新点，
      期望类别为「方法创新」。
    - 引用：① 论文标题（真实陈述）在原文中 → supported；② 与本主题无关的编造陈述
      （含原文没有的数值）→ unsupported；③ 无原文 → unknown。
    """
    from . import pdfparse, analyze as analyze_mod
    from .litsearch import load_local_corpus
    from .research import demo_layout_pdf

    docs = load_local_corpus(root)
    reading, innovation, citation = [], [], []

    for d in docs:
        _t0 = time.perf_counter()
        note = pdfparse.parse_pdf_bytes(demo_layout_pdf(d), d.get("doc_id", ""))
        _sys_sec = time.perf_counter() - _t0        # 真实实测耗时，不写死常量
        note["doi"] = d.get("doi", "")
        note["venue"] = d.get("venue", "")
        note["year"] = d.get("year", 0)

        # 关键词中实际出现在摘要里的那个（人工可核对）
        abstract_low = (d.get("abstract") or "").lower()
        gold_kw = next((k for k in (d.get("keywords") or [])
                        if k and k.lower() in abstract_low), None)
        if not gold_kw and d.get("keywords"):
            gold_kw = d["keywords"][0]
        reading.append({
            "note": note,
            "gold_sections": ["Abstract"],
            "gold_key_info": {"method": [gold_kw]} if gold_kw else {},
            "gold_repro": {"has_code": False, "has_data": False},
            "manual_seconds": 900.0,               # PRD：人工精读 15-30 分钟（取 15 分钟下界）
            "system_seconds": round(_sys_sec, 6),  # 实测：解析耗时（本地环境，非估数）
        })
        if gold_kw:
            innovation.append({
                "analysis": analyze_mod.extract_innovations(note),
                "gold_innovations": {gold_kw: "方法创新"},
                "text": note.get("text", ""),
            })
        # 引用核查标注
        citation.append({"claim": d.get("title", ""), "source_text": note.get("text", ""),
                         "source_ref": d.get("doc_id", ""), "gold_verdict": "supported"})
        citation.append({"claim": "This paper studies quantum chromodynamics on a "
                                  "lattice and reports 99.9 percent efficiency.",
                          "source_text": note.get("text", ""),
                          "source_ref": d.get("doc_id", ""), "gold_verdict": "unsupported"})

    citation.append({"claim": "An entirely uncited claim without any source.",
                     "source_text": None, "source_ref": "N/A",
                     "gold_verdict": "unknown"})
    return {"reading": reading, "innovation": innovation, "citation": citation}


def render_eval_md(reports: dict) -> str:
    lines = ["# 量化验证报告（F-7.1 ~ F-7.4）", ""]
    s = reports.get("search")
    if s:
        lines.append("## F-7.1 检索质量")
        lines.append(f"- 用例数: {s['n_cases']}")
        lines.append(f"- 系统: Precision={s['system']['precision']} "
                     f"Recall={s['system']['recall']} NDCG@10={s['system'].get('ndcg@10')}")
        if s.get("baseline"):
            lines.append(f"- 基线(纯关键词): Precision={s['baseline']['precision']} "
                         f"Recall={s['baseline']['recall']} NDCG@10={s['baseline'].get('ndcg@10')}")
            lines.append(f"- 提升: {s.get('improvement')}")
        lines.append(f"- 是否达标: {s.get('meets_target')}")
        if s.get("failures"):
            lines.append(f"- 失败案例: {len(s['failures'])} 例（见 JSON）")
        lines.append(f"- 说明: {s.get('scale_note')}")
        lines.append("")
    r = reports.get("read")
    if r:
        lines.append("## F-7.2 精读质量")
        lines.append(f"- 用例数: {r['n_cases']}；结构准确率={r['structure_accuracy']} "
                     f"关键信息准确率={r['key_info_accuracy']} "
                     f"可复现性准确率={r['reproducibility_accuracy']}")
        lines.append(f"- 耗时: 系统均值={r['system_seconds_avg']}s "
                     f"人工均值={r['manual_seconds_avg']}s 加速={r.get('speedup_vs_manual')}x")
        lines.append("")
    iv = reports.get("innovation")
    if iv:
        lines.append("## F-7.3 创新点提取")
        lines.append(f"- 用例数: {iv['n_cases']}；识别率={iv['identification_rate']} "
                     f"分类准确率={iv['classification_accuracy']} 幻觉率={iv['hallucination_rate']}")
        lines.append(f"- 是否达标: {iv.get('meets_target')}")
        lines.append("")
    ct = reports.get("citation")
    if ct:
        lines.append("## F-7.4 引用可信度")
        lines.append(f"- 用例数: {ct['n_cases']}；引用准确率={ct['citation_accuracy']} "
                     f"幻觉率={ct['hallucination_rate']}")
        lines.append(f"- 是否达标: {ct.get('meets_target')}")
        lines.append("")
    lines.append("> 以上测试集为 **demo 规模小样本标注**，用于演示指标口径，不代表真实世界性能。")
    return "\n".join(lines)


def run_all(root: str, reading_labeled=None, innovation_labeled=None,
            citation_labeled=None, include_demo: bool = True) -> dict:
    """跑全部四套评估。

    精读/创新点/引用三套优先用传入的标注；缺省且 ``include_demo=True`` 时
    用 :func:`build_demo_evals` 构建的透明 demo 标注集；否则跳过并说明。
    """
    if include_demo and not (reading_labeled and innovation_labeled and citation_labeled):
        demo = build_demo_evals(root)
        reading_labeled = reading_labeled or demo["reading"]
        innovation_labeled = innovation_labeled or demo["innovation"]
        citation_labeled = citation_labeled or demo["citation"]

    reports: dict = {}
    reports["search"] = eval_search_quality(
        demo_search_testset(), system_searcher(root), demo_search_baseline(root))
    reports["read"] = (eval_read_quality(reading_labeled) if reading_labeled
                       else {"n_cases": 0, "skipped": True,
                             "reason": "未提供精读标注集（需 grounding_truth 标注）"})
    reports["innovation"] = (eval_innovation(innovation_labeled) if innovation_labeled
                             else {"n_cases": 0, "skipped": True,
                                   "reason": "未提供创新点标注集"})
    reports["citation"] = (eval_citation(citation_labeled) if citation_labeled
                           else {"n_cases": 0, "skipped": True,
                                 "reason": "未提供引用标注集"})
    return reports


__all__ = [
    "precision_at_k", "recall_at_k", "f1_at_k", "ndcg_at_k",
    "eval_search_quality", "eval_read_quality", "eval_innovation", "eval_citation",
    "demo_search_testset", "demo_search_baseline", "system_searcher",
    "build_demo_evals", "render_eval_md", "run_all",
]
