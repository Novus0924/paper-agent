"""litsearch.py — P1 文献检索后端（零第三方依赖，仅标准库）。

提供两条检索路径，输出**同一套规范化文档结构**，上层无需区分来源：

- ``arxiv``：调用 arXiv 公开 Atom API（``export.arxiv.org/api/query``）实时检索
  真实论文，**不局限于内置语料**。任意课题（goal）都可以作为检索式。
- ``local``：读取 ``data/literature.json`` 内置语料（离线兜底 / 确定性基线）。

确定性契约（重要）
------------------
arXiv 检索是**在线、随时间变化**的：今天搜到的结果和明天可能不同。若直接把它
当作下游输入，会破坏本项目「同一 run 逐字节可复现」的红线。因此约定：

1. 在线检索结果首次取得后，**快照冻结**到
   ``runs/<run_id>/literature/arxiv_snapshot.json``；
2. 同一 run 再次执行 P1（resume / 复跑）**只读快照，不再联网**；
3. 快照文件作为 data 证据登记（带 SHA-256），保证「用过的输入」可追溯。

即：**联网只发生在 run 的首跑，且输入被冻结留证**，之后完全离线可复现。

用法::

    from paper_agent import litsearch
    docs, query = litsearch.search_arxiv("sulfide solid electrolyte conductivity")
    docs = litsearch.load_local_corpus(root)
    hits = litsearch.filter_by_relevance(docs, goal)
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# arXiv 公开检索端点（无需 API Key）
ARXIV_API = "https://export.arxiv.org/api/query"

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

# 检索式里的停用词（小写）
_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to",
         "is", "are", "with", "as", "at", "by", "from", "it", "its",
         "this", "that", "using", "based", "via", "study", "review",
         "analysis", "ranking", "rank", "search", "find"}

MAX_TERMS = 5          # 检索式最多取几个关键词（过多会过度收窄）
DEFAULT_MAX_RESULTS = 10


def tokenize(text: str) -> list[str]:
    """切词并去停用词，保持出现顺序且去重（用于构造检索式）。"""
    raw = re.findall(r"[a-z0-9]+", (text or "").lower())
    out: list[str] = []
    for t in raw:
        if t in _STOP or len(t) < 2:
            continue
        if t not in out:
            out.append(t)
    return out


def build_arxiv_query(goal: str, max_terms: int = MAX_TERMS,
                      join: str = " AND ") -> str:
    """把自然语言 goal 转成 arXiv 的 search_query 语法。

    arXiv 的字段前缀 ``all:`` 表示全字段（标题/摘要/作者/注释）检索。
    多关键词默认用 AND 连接；AND 命中为空时上层会退回 OR（见 search_arxiv）。
    """
    toks = tokenize(goal)[:max_terms]
    if not toks:
        return "all:science"
    return join.join(f"all:{t}" for t in toks)


def _text(node: ET.Element, tag: str, default: str = "") -> str:
    el = node.find(tag)
    if el is None or el.text is None:
        return default
    return " ".join(el.text.split())


def _short_id(raw_id: str) -> str:
    """``http://arxiv.org/abs/2401.12345v2`` -> ``2401.12345``（去版本号）。"""
    short = (raw_id or "").rstrip("/").split("/")[-1]
    base, sep, ver = short.rpartition("v")
    if sep and ver.isdigit() and base:
        return base
    return short


def parse_arxiv_atom(xml_bytes) -> list[dict]:
    """解析 arXiv Atom 响应为规范化文档列表。

    纯函数（不做网络访问），便于离线单测：喂一段固定 XML 即可校验解析逻辑。
    """
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    root = ET.fromstring(xml_bytes)

    docs: list[dict] = []
    for entry in root.findall(_ATOM + "entry"):
        raw_id = _text(entry, _ATOM + "id")
        short = _short_id(raw_id)
        published = _text(entry, _ATOM + "published")
        year = int(published[:4]) if published[:4].isdigit() else 0

        authors = [_text(a, _ATOM + "name")
                   for a in entry.findall(_ATOM + "author")]
        authors = [a for a in authors if a]

        cats = [c.get("term", "") for c in entry.findall(_ATOM + "category")]
        primary = entry.find(_ARXIV + "primary_category")
        if primary is not None and primary.get("term"):
            cats = [primary.get("term")] + [c for c in cats if c != primary.get("term")]
        cats = [c for c in cats if c]

        docs.append({
            "doc_id": f"arXiv:{short}" if short else "arXiv:unknown",
            "doi": _text(entry, _ARXIV + "doi"),
            "title": _text(entry, _ATOM + "title"),
            "authors": authors,
            "venue": _text(entry, _ARXIV + "journal_ref") or "arXiv preprint",
            "year": year,
            "keywords": cats,
            "abstract": _text(entry, _ATOM + "summary"),
            "url": f"https://arxiv.org/abs/{short}" if short else raw_id,
            "source": "arxiv",
        })
    return docs


def _fetch(query: str, max_results: int, timeout: float) -> list[dict]:
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    req = urllib.request.Request(
        f"{ARXIV_API}?{params}",
        headers={"User-Agent": "paper-agent/1.0 (research hackathon demo)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return parse_arxiv_atom(data)


def search_arxiv(goal: str, max_results: int = DEFAULT_MAX_RESULTS,
                 timeout: float = 25.0) -> tuple[list[dict], str]:
    """实时检索 arXiv，返回 ``(规范化文档列表, 实际使用的检索式)``。

    若 AND 检索式 0 命中，自动退回 OR 检索式再试一次（提升召回）。
    网络异常直接向上抛出，由调用方决定是否降级到本地语料。
    """
    query = build_arxiv_query(goal, join=" AND ")
    docs = _fetch(query, max_results, timeout)
    if not docs:
        alt = build_arxiv_query(goal, join=" OR ")
        if alt != query:
            docs = _fetch(alt, max_results, timeout)
            query = alt
    return docs, query


def load_local_corpus(root: str) -> list[dict]:
    """读取内置语料并补齐与 arXiv 一致的字段（source / url）。"""
    path = os.path.join(root, "data", "literature.json")
    with open(path, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    docs = []
    for d in corpus.get("documents", []):
        doc = dict(d)
        doc["source"] = "local"
        if not doc.get("url"):
            doc["url"] = (f"https://doi.org/{doc['doi']}"
                          if doc.get("doi") else "")
        docs.append(doc)
    return docs


def filter_by_relevance(docs: list[dict], goal: str) -> list[dict]:
    """按 goal 关键词命中数过滤并排序（本地语料用；arXiv 侧已由 API 排序）。

    tie-break：命中数降序，同分按 doc_id 字典序 —— 保证结果稳定可复现。
    """
    toks = tokenize(goal)
    scored = []
    for d in docs:
        hay = " ".join(
            [d.get("title", "")] + list(d.get("keywords", []))
            + [d.get("abstract", ""), d.get("venue", "")]
        ).lower()
        score = sum(1 for t in set(toks) if t in hay)
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: (-x[0], x[1].get("doc_id", "")))
    return [d for _, d in scored]


def ref_of(doc: dict) -> str:
    """证据引用串：优先 DOI，其次 arXiv 链接，最后 doc_id。"""
    return (doc.get("doi") or doc.get("url")
            or doc.get("doc_id") or "").strip()
