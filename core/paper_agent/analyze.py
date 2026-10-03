"""analyze.py — 创新点拆解 / 技术脉络 / Research Gap（PRD F-3.1~F-3.3）。

零第三方依赖、**确定性、可溯源**。本模块不做「凭空的创造性判断」，而是：

- 从**已精读的结构化笔记**中抽取候选创新陈述（含原文 locator），
- 按 PRD 的五类做**关键词证据驱动**的分类（方法/理论/数据/应用/工程），
- 对每个创新点补齐四要素：是什么 / 解决何问题 / 技术手段 / 效果提升，
- 结合相关文献构建**对比矩阵**，按时间线梳理**领域技术脉络**，
- 聚合局限性/未来工作，做**Research Gap 识别**（含重要性·证据·可行性）。

每条结论都带 ``locator``（章节 + 字符偏移），可直接回查原文；
**不编造任何未在原文出现的创新点**（幻觉率评估见 evaluate.py）。
"""
from __future__ import annotations

import re

# ---- 五类创新的判别词（英/中）----
_CATEGORY_KW: dict[str, tuple[str, ...]] = {
    "方法创新": ("we propose", "we present", "we introduce", "our method",
                 "our approach", "we design", "new architecture", "novel method",
                 "framework", "algorithm", "model architecture",
                 "reports the", "demonstrates", "introduces the", "characterizes",
                 "本文提出", "我们提出", "提出一种", "新方法", "新框架", "新架构"),
    "理论创新": ("theorem", "proof", "theoretical", "bound", "convergence",
                 "we prove", "lemma", "corollary", "guarantee",
                 "定理", "证明", "理论", "收敛性", "界"),
    "数据创新": ("dataset", "datasets", "benchmark", "corpus", "we collect",
                 "we annotate", "new benchmark", "data collection",
                 "数据集", "语料", "标注", "基准"),
    "应用创新": ("we apply", "applied to", "real-world", "deploy", "in practice",
                 "application of", "case study", "clinical", "industry",
                 "应用", "落地", "实际场景", "真实场景"),
    "工程创新": ("system", "implementation", "efficiency", "speedup", "throughput",
                 "scalab", "latency", "memory", "we implement", "open-source",
                 "工程", "效率", "加速", "吞吐", "部署", "实现"),
}

# 候选创新陈述的触发词
_NOVELTY_KW = ("we propose", "we present", "we introduce", "we design", "we develop",
               "our method", "our approach", "novel", "for the first time",
               "we show that", "reports the", "demonstrates", "introduces the",
               "characterizes", "本文提出", "我们提出", "首次", "提出一种", "新")

# 问题/空白
_PROBLEM_KW = ("however", "but ", "traditional", "previous", "existing", "prior work",
               "lack", "cannot", "fail to", "suffer", "limitation", "challeng",
               "然而", "但是", "传统", "已有", "现有", "难以", "无法", "存在")
# 效果
_EFFECT_KW = ("improve", "outperform", "achieve", "reduce", "increase", "faster",
              "better", "surpass", "state-of-the-art", "sota", "gain", "reduction",
              "提升", "降低", "优于", "超过", "提高", "效果")

_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|x|倍|个百分点|times|points)?")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 20]


def _locator(section: str, text: str, sent: str) -> dict:
    return {"section": section, "offset": text.find(sent[:40]) if sent[:40] else -1}


def classify_innovation(statement: str) -> list[str]:
    """对一条创新陈述做五类归档（可多标签）。无命中则归为「方法创新」（默认类）。"""
    low = statement.lower()
    cats = [c for c, kws in _CATEGORY_KW.items() if any(k in low for k in kws)]
    return cats or ["方法创新"]


def _pick(sents: list[str], kws: tuple[str, ...], limit: int = 2) -> str:
    hits = [s for s in sents if any(k in s.lower() for k in kws)]
    return (hits[0] if hits else "")[:400]


def extract_innovations(note: dict) -> dict:
    """从结构化精读笔记中抽取创新点卡片（PRD F-3.1）。

    ``note`` 来自 :func:`paper_agent.pdfparse.parse_paper`。输出::

        {target, innovations:[{id,statement,categories,what,problem,
          technique,effect,locator,confidence}], n_innovations, categories_summary}
    """
    sections = note.get("sections") or {}
    full_text = note.get("text") or ""
    # 优先从 Method / Abstract / Conclusion 找创新陈述
    prio = [s for s in ("Abstract", "Method", "结论", "Conclusion", "摘要", "方法")
            if s in sections]
    pool_sections = prio or list(sections.keys())
    sents: list[tuple[str, str]] = []            # (section, sentence)
    for sec in pool_sections:
        for s in _sentences(sections.get(sec, "")):
            sents.append((sec, s))
    if not sents:
        for s in _sentences(full_text):
            sents.append(("Body", s))

    cards: list[dict] = []
    for sec, sent in sents:
        low = sent.lower()
        if not any(k in low for k in _NOVELTY_KW):
            continue
        if len(cards) >= 8:
            break
        cats = classify_innovation(sent)
        window = [s for _, s in sents if s != sent][:6]
        cards.append({
            "id": f"IN-{len(cards) + 1}",
            "statement": sent[:400],
            "categories": cats,
            "what": sent[:400],
            "problem": _pick(window, _PROBLEM_KW) or "（原文未显式陈述问题，需人工复核）",
            "technique": _pick([sent] + window, _CATEGORY_KW["方法创新"]) or sent[:200],
            "effect": _pick([sent] + window, _EFFECT_KW)
                      or ("含数值效果：" + " ".join(_NUM_RE.findall(sent))[:120]
                          if _NUM_RE.search(sent) else "（原文未给出量化效果）"),
            "locator": _locator(sec, full_text, sent),
            "confidence": "high" if any(k in low for k in ("we propose", "本文提出", "我们提出")) else "medium",
        })

    summary: dict[str, int] = {}
    for c in cards:
        for cat in c["categories"]:
            summary[cat] = summary.get(cat, 0) + 1
    return {
        "target": note.get("doc_id", ""),
        "title": note.get("title", ""),
        "innovations": cards,
        "n_innovations": len(cards),
        "categories_summary": summary,
    }


def build_comparison_matrix(target: dict, related: list[dict]) -> dict:
    """目标论文 + 相关文献的对比矩阵（PRD F-3.1「对比增强」）。

    ``target`` / ``related`` 为已抽取创新点的结果 dict（``extract_innovations`` 产物）。
    列固定，便于渲染为 Markdown 表格。
    """
    cols = ["item", "year", "venue", "citations", "primary_innovation", "categories"]
    rows: list[dict] = []

    def _row(doc_meta: dict, analysis: dict, label: str) -> dict:
        inno = analysis.get("innovations") or []
        primary = inno[0]["statement"][:160] if inno else "（未识别）"
        cats = sorted({c for i in inno for c in i["categories"]})
        return {
            "item": label,
            "doc_id": doc_meta.get("doc_id", ""),
            "year": doc_meta.get("year", 0),
            "venue": doc_meta.get("venue", ""),
            "citations": doc_meta.get("citations", 0),
            "primary_innovation": primary,
            "categories": "、".join(cats) if cats else "（未识别）",
        }

    rows.append(_row(target.get("_meta", {}), target, "TARGET: " + (target.get("title") or "target")))
    for i, r in enumerate(related, 1):
        rows.append(_row(r.get("_meta", {}), r, f"REF-{i}: " + (r.get("title") or r.get("doc_id", ""))))
    return {"columns": cols, "rows": rows, "n_rows": len(rows)}


def technology_timeline(items: list[dict]) -> dict:
    """按年份梳理技术脉络（PRD F-3.2）。

    ``items``: ``[{"doc_id","title","year","venue","contribution","limitation"}]``
    """
    nodes = sorted(items, key=lambda x: (int(x.get("year") or 0), x.get("doc_id", "")))
    years = [int(n.get("year") or 0) for n in nodes if n.get("year")]
    return {
        "nodes": nodes,
        "n_nodes": len(nodes),
        "year_range": [min(years), max(years)] if years else [0, 0],
    }


def research_gap(notes: list[dict], top_k: int = 5) -> dict:
    """Research Gap 识别（PRD F-3.3）。

    汇总各论文的 limitation/future-work 句 → 按关键词聚类 → 频次降序输出，
    每条 gap 带证据（doc_id + 原文 quote + locator）、重要性、可行性评估。
    """
    clusters: dict[str, dict] = {}
    for note in notes:
        doc_id = note.get("doc_id", "")
        secs = note.get("sections") or {}
        pool = []
        for name in ("Limitations", "Conclusion", "讨论", "结论", "Future Work", "局限", "Discussion"):
            if name in secs:
                pool.extend(_sentences(secs[name]))
        if not pool:
            pool = _sentences(note.get("text") or "")
        for s in pool:
            low = s.lower()
            if not any(k in low for k in _PROBLEM_KW):
                continue
            key = _cluster_key(s)
            if not key:
                continue
            c = clusters.setdefault(key, {"problem": s[:300], "evidence": [],
                                          "doc_ids": set(), "frequency": 0})
            if doc_id not in c["doc_ids"]:
                c["doc_ids"].add(doc_id)
                c["frequency"] += 1
            if len(c["evidence"]) < 4:
                c["evidence"].append({
                    "doc_id": doc_id, "quote": s[:300],
                    "locator": {"section": "Limitations/FutureWork",
                                "offset": (note.get("text") or "").find(s[:40])},
                })

    gaps = []
    for key, c in clusters.items():
        freq = c["frequency"]
        gaps.append({
            "id": "", "topic": key,
            "problem": c["problem"],
            "frequency": freq,
            "importance": "高" if freq >= 2 else "中",
            "feasibility": "高" if len(c["problem"]) > 40 else "中",
            "evidence": c["evidence"],
        })
    gaps.sort(key=lambda g: (-g["frequency"], g["topic"]))
    gaps = gaps[:top_k]
    for i, g in enumerate(gaps, 1):
        g["id"] = f"GAP-{i}"
    return {"gaps": gaps, "n_gaps": len(gaps)}


_GAP_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
             "are", "with", "as", "at", "by", "from", "it", "its", "this", "that",
             "we", "our", "can", "not", "be", "has", "have", "however", "but",
             "limitation", "limited", "future", "work", "also", "more", "such",
             "由于", "但是", "然而", "存在", "难以"}


def _cluster_key(sentence: str) -> str:
    """用句中的**显著实词**构造稳定聚类键，避免重复 gap。

    关键：必须**与词序无关**。旧实现取 ``sorted(set(toks))[:5]``（字母序前 5 个），
    会让「existing methods are slow training」与「slow training in existing methods」
    得到不同的键，同一课题的空白永远聚不到一起，F-3.3 形同虚设。

    这里改为：取按词长降序（长词更具区分度）+ 字母序稳定的 top-5 实词集合，
    再做字母序归一，保证同义句（共享这 5 个显著词）落到同一键。
    """
    toks = [t for t in re.findall(r"[a-z0-9]+", sentence.lower())
            if t not in _GAP_STOP and len(t) > 2]
    if not toks:
        # 中文等无空格语言：回退用 2 字滑窗做粗聚类键
        cjk = re.findall(r"[\u4e00-\u9fff]{2,}", sentence)
        return "+".join(sorted(set(cjk))[:5])
    # 词频优先（出现越多越可能是主题词），其次词长，最后字母序 → 完全确定
    freq: dict[str, int] = {}
    for t in toks:
        freq[t] = freq.get(t, 0) + 1
    ranked = sorted(freq, key=lambda t: (-freq[t], -len(t), t))[:5]
    return "+".join(sorted(ranked))


# =====================================================================
# Markdown 渲染
# =====================================================================

def render_innovation_md(result: dict, matrix: dict | None = None) -> str:
    lines = [f"# 创新点拆解 — {result.get('title') or result.get('target')}", ""]
    lines.append(f"- 识别创新点: **{result.get('n_innovations', 0)}** 个")
    lines.append(f"- 分类统计: {result.get('categories_summary') or '（无）'}")
    lines.append("")
    for c in result.get("innovations", []):
        lines.append(f"## {c['id']}（{'/'.join(c['categories'])}）")
        lines.append(f"- **是什么**：{c['what']}")
        lines.append(f"- **解决何问题**：{c['problem']}")
        lines.append(f"- **技术手段**：{c['technique']}")
        lines.append(f"- **效果提升**：{c['effect']}")
        loc = c.get("locator") or {}
        lines.append(f"- 溯源：`[{loc.get('section', '?')}@off={loc.get('offset', -1)}]` "
                     f"（confidence={c['confidence']}）")
        lines.append("")
    if matrix:
        lines.append("## 对比矩阵")
        lines.append("| " + " | ".join(matrix["columns"]) + " |")
        lines.append("| " + " | ".join("---" for _ in matrix["columns"]) + " |")
        for r in matrix["rows"]:
            lines.append("| " + " | ".join(str(r.get(c, "")).replace("|", "\\|")
                                           for c in matrix["columns"]) + " |")
        lines.append("")
    return "\n".join(lines)


def render_gap_md(gaps: dict) -> str:
    lines = ["# Research Gap 识别", ""]
    lines.append(f"- 候选空白: **{gaps.get('n_gaps', 0)}** 个（按证据频次排序）")
    lines.append("")
    for g in gaps.get("gaps", []):
        lines.append(f"## {g['id']} 重要性={g['importance']} 可行性={g['feasibility']} 频次={g['frequency']}")
        lines.append(f"- 未解决问题：{g['problem']}")
        for e in g["evidence"]:
            lines.append(f"  - 证据 `{e['doc_id']}`：{e['quote']}")
        lines.append("")
    return "\n".join(lines)


def render_timeline_md(tl: dict) -> str:
    lines = ["# 领域技术脉络", ""]
    if tl.get("year_range"):
        lines.append(f"- 年份区间: {tl['year_range'][0]}–{tl['year_range'][1]}（{tl.get('n_nodes', 0)} 个节点）")
    lines.append("")
    for n in tl.get("nodes", []):
        lines.append(f"- **{n.get('year', '?')}** `{n.get('doc_id', '')}` "
                     f"{n.get('contribution', '')} — 局限：{n.get('limitation', '（未标注）')}")
    return "\n".join(lines)


__all__ = [
    "classify_innovation", "extract_innovations", "build_comparison_matrix",
    "technology_timeline", "research_gap",
    "render_innovation_md", "render_gap_md", "render_timeline_md",
]
