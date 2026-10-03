"""writing.py — 论文写作（PRD F-5.1~F-5.3）。

零第三方依赖、**强制引用溯源**：

- **文献综述生成**（F-5.1）：规划章节 → 按章节分配论文 → 逐节写作 →
  全文一致性检查。**每一处事实陈述都必须携带引用**；无法归因的内容
  一律标注 ``[需补充引用]``，**坚决不编造引用**。
- **引用管理**（F-5.3）：BibTeX / RIS 生成、APA/IEEE/Chicago 格式转换、
  引用去重、缺失字段提醒。

说明：本模块在**无 LLM** 的前提下，采用「元数据 + 摘要首句」的**抽取式**写法：
只把文献里真实存在的信息组织成综述骨架，并对每句标注 source doc_id。
真正的文风润色由 AGH 会话内的大模型在 write-skill 引导下完成。
"""
from __future__ import annotations

import re

_SECTION_PLAN = [
    ("Introduction", "研究背景与问题动机"),
    ("Related Work", "相关工作与代表性方法"),
    ("Method Landscape", "方法技术脉络"),
    ("Open Problems", "现存局限与开放问题"),
    ("Conclusion", "小结与展望"),
]


# =====================================================================
# 元数据 → 引用字符串
# =====================================================================

def _first_author_last(doc: dict) -> str:
    authors = doc.get("authors") or []
    if not authors:
        return "Unknown"
    parts = re.split(r"[\s,]+", authors[0].strip())
    return parts[-1] if parts else "Unknown"


def _authors_apa(doc: dict) -> str:
    authors = doc.get("authors") or []
    if not authors:
        return "Unknown"
    out = []
    for a in authors[:3]:
        parts = re.split(r"[\s,]+", a.strip())
        if not parts:
            continue
        last = parts[-1]
        initials = "".join(p[0].upper() + "." for p in parts[:-1])
        out.append(f"{last}, {initials}".strip())
    if len(authors) > 3:
        out.append("et al.")
    return ", ".join(out)


def _authors_ieee(doc: dict) -> str:
    authors = doc.get("authors") or []
    if not authors:
        return "Unknown"
    out = []
    for a in authors[:6]:
        parts = re.split(r"[\s,]+", a.strip())
        if not parts:
            continue
        last = parts[-1]
        initials = " ".join(p[0].upper() + "." for p in parts[:-1])
        out.append(f"{initials} {last}".strip())
    if len(authors) > 6:
        out.append("et al.")
    return ", ".join(out)


def format_citation(doc: dict, style: str = "APA") -> str:
    """APA / IEEE / Chicago 三种引用格式（F-5.3）。"""
    style = (style or "APA").upper()
    title = doc.get("title", "") or "(untitled)"
    venue = doc.get("venue", "") or "unknown venue"
    year = doc.get("year", 0) or "n.d."
    doi = doc.get("doi", "")
    url = doc.get("url", "")
    if style == "IEEE":
        s = f'{_authors_ieee(doc)}, "{title}," {venue}, {year}.'
    elif style == "CHICAGO":
        s = f'{_authors_apa(doc)}. "{title}." {venue} ({year}).'
    else:  # APA
        s = f"{_authors_apa(doc)} ({year}). {title}. {venue}."
    if doi:
        s += f" https://doi.org/{doi}"
    elif url:
        s += f" {url}"
    return s


def bibtex_key(doc: dict) -> str:
    last = re.sub(r"[^A-Za-z]", "", _first_author_last(doc)) or "anon"
    year = str(doc.get("year", "") or "")
    word = re.sub(r"[^A-Za-z]", "", (doc.get("title", "") or "x").split()[0] if doc.get("title") else "x")
    return f"{last}{year}{word}".lower()


def _bibtex_type(doc: dict) -> str:
    venue = (doc.get("venue") or "").lower()
    if any(k in venue for k in ("conference", "proceedings", "workshop", "symposium", "neurips", "icml", "cvpr", "acl")):
        return "inproceedings"
    if venue and venue not in ("arxiv preprint", "unknown venue"):
        return "article"
    return "misc"


def missing_fields(doc: dict) -> list[str]:
    """缺失字段提醒（F-5.3）。"""
    need = {"title": "title", "authors": "authors", "year": "year",
            "venue": "venue", "doi": "doi"}
    miss = []
    for k, label in need.items():
        v = doc.get(k)
        if not v or (k == "authors" and not v):
            miss.append(label)
    return miss


def generate_bibtex(docs: list[dict]) -> dict:
    """生成 BibTeX 条目（+ 缺失字段提醒 + 重复键消解）。"""
    entries: list[str] = []
    used: dict[str, int] = {}
    warnings: list[dict] = []
    for d in docs:
        key = bibtex_key(d)
        if key in used:
            used[key] += 1
            key = f"{key}{chr(ord('a') + used[key] - 1)}"
        else:
            used[key] = 1
        etype = _bibtex_type(d)
        fields = {
            "title": d.get("title", ""),
            "author": " and ".join(d.get("authors") or []),
            "year": str(d.get("year", "") or ""),
            "journal" if etype == "article" else "booktitle": d.get("venue", ""),
            "doi": d.get("doi", ""),
            "url": d.get("url", ""),
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        entries.append(f"@{etype}{{{key},\n{body}\n}}")
        mf = missing_fields(d)
        if mf:
            warnings.append({"doc_id": d.get("doc_id", ""), "missing": mf})
    return {"bibtex": "\n\n".join(entries), "n_entries": len(entries),
            "warnings": warnings}


def generate_ris(docs: list[dict]) -> str:
    """RIS 格式导出（F-5.3 兼容格式）。"""
    blocks = []
    for d in docs:
        lines = ["TY  - JOUR" if _bibtex_type(d) == "article" else "TY  - CONF"]
        for a in d.get("authors") or []:
            lines.append(f"AU  - {a}")
        lines.append(f"TI  - {d.get('title', '')}")
        lines.append(f"PY  - {d.get('year', '')}")
        lines.append(f"JO  - {d.get('venue', '')}")
        if d.get("doi"):
            lines.append(f"DO  - {d['doi']}")
        if d.get("url"):
            lines.append(f"UR  - {d['url']}")
        lines.append("ER  - ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def dedup_citations(docs: list[dict]) -> dict:
    """引用去重：DOI 优先，其次标题归一。返回 {documents, removed}。"""
    from .litsearch import dedup_documents
    out = dedup_documents(docs)
    return {"documents": out, "removed": max(0, len(docs) - len(out))}


# =====================================================================
# F-5.1 综述生成（抽取式，强制引用）
# =====================================================================

def _first_sentence(text: str, maxlen: int = 220) -> str:
    parts = re.split(r"(?<=[.!?。！？])\s+", (text or "").strip())
    for p in parts:
        if len(p) >= 20:
            return p[:maxlen]
    return (text or "")[:maxlen]


def _grounded_line(doc: dict) -> str:
    """从一篇文献生成一句**有据可查**的陈述（带 doc_id 引用标记）。"""
    year = doc.get("year", "")
    venue = doc.get("venue", "")
    claim = _first_sentence(doc.get("abstract", ""))
    if not claim:
        claim = doc.get("title", "")
    tag = doc.get("doc_id") or doc.get("doi") or doc.get("url") or "UNKNOWN"
    return f"{claim} [{tag}]（{venue}, {year}）"


def generate_review(topic: str, docs: list[dict],
                    analyses: list[dict] | None = None,
                    gaps: dict | None = None) -> dict:
    """生成综述草稿（F-5.1）。

    返回 ``{topic, sections:[{name, purpose, content, citations}], markdown,
    unsupported:[...], n_citations, consistency}``。

    - 每个章节只使用**真实文献**内容，句子级附带 ``[doc_id]`` 引用标记
    - 需要但无文献支撑的过渡句 → ``[需补充引用]``（计入 ``unsupported``）
    """
    docs = docs or []
    analyses = analyses or []
    sections: list[dict] = []
    unsupported: list[str] = []
    cite_ids: set[str] = set()

    def _tag(d: dict) -> str:
        return d.get("doc_id") or d.get("doi") or d.get("url") or "UNKNOWN"

    # 1) Introduction
    intro = [f"本综述围绕「{topic}」展开，共纳入 {len(docs)} 篇文献（来自多源检索与去重后）。"]
    unsupported.append(intro[0])
    for d in docs[:3]:
        intro.append(_grounded_line(d))
        cite_ids.add(_tag(d))
    sections.append({"name": "Introduction", "purpose": _SECTION_PLAN[0][1],
                     "content": intro, "citations": [_tag(d) for d in docs[:3]]})

    # 2) Related Work —— 按 venue/年份分组陈述
    rw = []
    for d in sorted(docs, key=lambda x: (-int(x.get("citations") or 0), x.get("doc_id", ""))):
        rw.append(_grounded_line(d))
        cite_ids.add(_tag(d))
    if not rw:
        rw.append("[需补充引用] 尚未检索到相关文献。")
        unsupported.append(rw[0])
    sections.append({"name": "Related Work", "purpose": _SECTION_PLAN[1][1],
                     "content": rw, "citations": sorted(cite_ids)})

    # 3) Method Landscape —— 借助创新点分析
    ml = []
    for a in analyses:
        for c in (a.get("innovations") or [])[:2]:
            ml.append(f"{c['statement']} [{a.get('target', 'UNKNOWN')}]")
    if not ml:
        ml.append("[需补充引用] 缺乏精读/创新点分析输入，无法归纳方法脉络。")
        unsupported.append(ml[0])
    sections.append({"name": "Method Landscape", "purpose": _SECTION_PLAN[2][1],
                     "content": ml, "citations": [a.get("target", "") for a in analyses if a.get("target")]})

    # 4) Open Problems —— 借助 gap 分析
    op = []
    for g in (gaps or {}).get("gaps", []):
        ev = "；".join(f"{e['doc_id']}" for e in g.get("evidence", [])[:3])
        op.append(f"[{g['id']}] {g['problem']}（证据：{ev}）")
    if not op:
        # 「未识别到开放问题」是**运行覆盖度提示**，不是关于文献的事实陈述，
        # 因此不使用 [需补充引用] 标记（避免把元陈述误判为无据主张）。
        op.append("（自动草稿提示）本次运行未从已读论文中聚类出候选研究空白；"
                  "该提示受检索与精读覆盖度限制，非文献事实陈述。")
    sections.append({"name": "Open Problems", "purpose": _SECTION_PLAN[3][1],
                     "content": op, "citations": list(cite_ids)})

    # 5) Conclusion
    concl = [f"综上，「{topic}」方向已有 {len(docs)} 篇相关工作被纳入分析，"
             f"识别出 {len((gaps or {}).get('gaps', []))} 个候选研究空白。"]
    unsupported.append(concl[0])
    sections.append({"name": "Conclusion", "purpose": _SECTION_PLAN[4][1],
                     "content": concl, "citations": []})

    md = _render_review_md(topic, sections)
    consistency = check_review_consistency(md, docs)
    return {
        "topic": topic,
        "sections": sections,
        "markdown": md,
        "unsupported": unsupported,
        "n_citations": len(cite_ids),
        "consistency": consistency,
    }


def check_review_consistency(markdown: str, docs: list[dict]) -> dict:
    """全文一致性检查：所有 ``[doc_id]`` 引用是否都能在文献集合中找到。"""
    known = set()
    for d in docs:
        for k in ("doc_id", "doi", "url"):
            if d.get(k):
                known.add(d[k])
    refs = set(re.findall(r"\[([^\]\n]+)\]", markdown))
    refs = {r for r in refs if not r.startswith(("需补充引用", "GAP", "IN-"))}
    dangling = sorted(r for r in refs if r not in known)
    return {"n_refs": len(refs), "dangling": dangling,
            "ok": len(dangling) == 0}


def _render_review_md(topic: str, sections: list[dict]) -> str:
    lines = [f"# 文献综述（草稿）— {topic}", "",
             "> 本文为**抽取式自动草稿**：每句事实陈述均以方括号标注来源文献 ID；",
             "> 标注「需补充引用」的句子需要人工补证或删除。禁止编造引用。", ""]
    for s in sections:
        lines.append(f"## {s['name']}（{s['purpose']}）")
        for sent in s["content"]:
            lines.append(f"- {sent}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "format_citation", "bibtex_key", "missing_fields", "generate_bibtex",
    "generate_ris", "dedup_citations", "generate_review",
    "check_review_consistency",
]
