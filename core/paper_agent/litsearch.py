"""litsearch.py — P1 多源学术检索后端（零第三方依赖，仅标准库）。

对外提供**两条能力**：

1. ``search_arxiv`` / ``load_local_corpus``（既有）—— P1 材料工作流的检索来源，
   支持 arXiv 实时检索 + 本地语料兜底 + 快照冻结（确定性契约）。
2. ``search_papers``（v0.3 新增）—— PRD F-1.1 的**统一多源入口**：
   在 arXiv / Semantic Scholar / OpenAlex / CrossRef 之间路由，
   做 DOI 精确去重 + 标题·首作者模糊去重、单源超时跳过、相关性排序，
   输出统一规范化文档结构。

规范化文档字段（所有来源一致）::

    doc_id / doi / title / authors / venue / year / keywords /
    abstract / url / source / sources / citations

确定性契约
----------
在线检索是**随时间变化**的。上层（P1）在首次取得在线结果后会**快照冻结**，
同一 run 复跑只读快照、不再联网（见 steps.py::_p1_search）。
本模块的解析函数（``parse_*``）均为**纯函数**，便于离线单测；
``search_papers`` 支持注入 ``backends``，测试可完全离线。

用法::

    from paper_agent import litsearch
    docs, query = litsearch.search_arxiv("sulfide solid electrolyte conductivity")
    out = litsearch.search_papers("graph neural network for molecule property",
                                  sources=["arxiv", "openalex"])
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# ---- 公开检索端点（均无需 API Key；Semantic Scholar 匿名亦可访问）----
ARXIV_API = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_API = "https://api.openalex.org/works"
CROSSREF_API = "https://api.crossref.org/works"
UNPAYWALL_API = "https://api.unpaywall.org/v2"

# 统一多源入口支持的数据源（可扩展：新增后端只需实现 fetch + parse 并登记）
ALL_SOURCES = ("arxiv", "semantic_scholar", "openalex", "crossref")
SOURCE_LABELS = {
    "arxiv": "arXiv",
    "semantic_scholar": "Semantic Scholar",
    "openalex": "OpenAlex",
    "crossref": "CrossRef",
    "local": "内置语料",
}

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

# 检索式里的停用词（小写）
_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to",
         "is", "are", "with", "as", "at", "by", "from", "it", "its",
         "this", "that", "using", "based", "via", "study", "review",
         "analysis", "ranking", "rank", "search", "find"}

MAX_TERMS = 5          # 检索式最多取几个关键词（过多会过度收窄）
DEFAULT_MAX_RESULTS = 10
DEFAULT_TIMEOUT = 25.0
_UA = "paper-agent/1.1 (research hackathon demo; mailto:noreply@example.com)"


# =====================================================================
# 通用工具
# =====================================================================

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


def _clean(text) -> str:
    """折叠空白；None / 非字符串安全处理。"""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        text = " ".join(str(x) for x in text if x)
    return " ".join(str(text).split())


def _year_of(value) -> int:
    """从各种形态提取 4 位年份（int / '2024-01-02' / [2024]）。"""
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)) and value:
        return _year_of(value[0])
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else 0


def _authors(seq) -> list[str]:
    out = []
    for a in seq or []:
        if isinstance(a, str):
            name = _clean(a)
        elif isinstance(a, dict):
            name = _clean(a.get("name") or a.get("display_name")
                          or (a.get("author", {}) or {}).get("display_name")
                          or " ".join(x for x in [a.get("given"), a.get("family")] if x))
        else:
            name = ""
        if name:
            out.append(name)
    return out


def _fetch_json(url: str, timeout: float,
                headers: dict | None = None) -> dict:
    """GET 一个 JSON 端点并解析。网络异常向上抛出，由调用方决定降级。"""
    hdr = {"User-Agent": _UA}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def ref_of(doc: dict) -> str:
    """证据引用串：优先 DOI，其次 URL，最后 doc_id。"""
    return (doc.get("doi") or doc.get("url")
            or doc.get("doc_id") or "").strip()


# =====================================================================
# arXiv（Atom XML）
# =====================================================================

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
    """解析 arXiv Atom 响应为规范化文档列表（纯函数，无网络）。"""
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
            "citations": 0,
        })
    return docs


def _fetch_arxiv(goal: str, max_results: int, timeout: float) -> tuple[list[dict], str]:
    query = build_arxiv_query(goal, join=" AND ")
    params = urllib.parse.urlencode({
        "search_query": query, "start": 0, "max_results": max_results,
        "sortBy": "relevance", "sortOrder": "descending",
    })
    req = urllib.request.Request(f"{ARXIV_API}?{params}",
                                 headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    docs = parse_arxiv_atom(data)
    if not docs:
        alt = build_arxiv_query(goal, join=" OR ")
        if alt != query:
            params = urllib.parse.urlencode({
                "search_query": alt, "start": 0, "max_results": max_results,
                "sortBy": "relevance", "sortOrder": "descending"})
            req = urllib.request.Request(f"{ARXIV_API}?{params}",
                                         headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                docs = parse_arxiv_atom(resp.read())
            query = alt
    return docs, query


def search_arxiv(goal: str, max_results: int = DEFAULT_MAX_RESULTS,
                 timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], str]:
    """实时检索 arXiv，返回 ``(规范化文档列表, 实际使用的检索式)``。"""
    return _fetch_arxiv(goal, max_results, timeout)


# =====================================================================
# Semantic Scholar（JSON，含引用图谱）
# =====================================================================

_SS_FIELDS = ("title,abstract,year,venue,authors,externalIds,"
              "citationCount,url,fieldsOfStudy,publicationTypes")


def parse_semantic_scholar(payload) -> list[dict]:
    """解析 Semantic Scholar Graph API 响应（纯函数）。"""
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    docs: list[dict] = []
    for it in (payload or {}).get("data", []) or []:
        ext = it.get("externalIds") or {}
        doi = _clean(ext.get("DOI"))
        arxiv = _clean(ext.get("ArXiv"))
        url = _clean(it.get("url"))
        if not url and arxiv:
            url = f"https://arxiv.org/abs/{arxiv}"
        if not url and doi:
            url = f"https://doi.org/{doi}"
        docs.append({
            "doc_id": f"SS:{_clean(it.get('paperId'))}" or "SS:unknown",
            "doi": doi,
            "title": _clean(it.get("title")),
            "authors": _authors(it.get("authors")),
            "venue": _clean(it.get("venue")) or "unknown venue",
            "year": _year_of(it.get("year")),
            "keywords": [_clean(k) for k in (it.get("fieldsOfStudy") or []) if k],
            "abstract": _clean(it.get("abstract")),
            "url": url,
            "source": "semantic_scholar",
            "citations": int(it.get("citationCount") or 0),
        })
    return docs


def _fetch_semantic_scholar(goal: str, max_results: int,
                            timeout: float) -> tuple[list[dict], str]:
    params = urllib.parse.urlencode({
        "query": goal, "limit": max(1, min(max_results, 100)), "fields": _SS_FIELDS})
    payload = _fetch_json(f"{SEMANTIC_SCHOLAR_API}?{params}", timeout)
    return parse_semantic_scholar(payload), goal


def search_semantic_scholar(goal: str, max_results: int = DEFAULT_MAX_RESULTS,
                            timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], str]:
    """检索 Semantic Scholar（引用图谱 + 全领域）。"""
    return _fetch_semantic_scholar(goal, max_results, timeout)


# =====================================================================
# OpenAlex（JSON，开放元数据）
# =====================================================================

def _openalex_abstract(inv: dict | None) -> str:
    """OpenAlex 的 abstract_inverted_index → 正常顺序文本。"""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((int(i), word))
    positions.sort()
    return " ".join(w for _, w in positions)


def parse_openalex(payload) -> list[dict]:
    """解析 OpenAlex /works 响应（纯函数）。"""
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    docs: list[dict] = []
    for it in (payload or {}).get("results", []) or []:
        doi = _clean(it.get("doi")).replace("https://doi.org/", "")
        loc = it.get("primary_location") or {}
        src = (loc.get("source") or {}) if isinstance(loc, dict) else {}
        url = _clean(loc.get("landing_page_url")) if isinstance(loc, dict) else ""
        if not url and doi:
            url = f"https://doi.org/{doi}"
        docs.append({
            "doc_id": f"OpenAlex:{_clean(it.get('id')).rstrip('/').split('/')[-1]}",
            "doi": doi,
            "title": _clean(it.get("title") or it.get("display_name")),
            "authors": _authors(it.get("authorships")),
            "venue": _clean(src.get("display_name")) or "unknown venue",
            "year": _year_of(it.get("publication_year")),
            "keywords": [_clean(c.get("display_name"))
                         for c in (it.get("concepts") or []) if c.get("display_name")],
            "abstract": _openalex_abstract(it.get("abstract_inverted_index")),
            "url": url,
            "source": "openalex",
            "citations": int(it.get("cited_by_count") or 0),
        })
    return docs


def _fetch_openalex(goal: str, max_results: int,
                    timeout: float) -> tuple[list[dict], str]:
    params = urllib.parse.urlencode({
        "search": goal, "per-page": max(1, min(max_results, 200)), "mailto": "noreply@example.com"})
    payload = _fetch_json(f"{OPENALEX_API}?{params}", timeout)
    return parse_openalex(payload), goal


def search_openalex(goal: str, max_results: int = DEFAULT_MAX_RESULTS,
                    timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], str]:
    """检索 OpenAlex（全领域开放元数据）。"""
    return _fetch_openalex(goal, max_results, timeout)


# =====================================================================
# CrossRef（JSON，DOI 权威元数据）
# =====================================================================

def parse_crossref(payload) -> list[dict]:
    """解析 CrossRef /works 响应（纯函数）。"""
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    items = ((payload or {}).get("message") or {}).get("items", []) or []
    docs: list[dict] = []
    for it in items:
        doi = _clean(it.get("DOI"))
        issued = (it.get("issued") or {}).get("date-parts") or [[0]]
        docs.append({
            "doc_id": f"CrossRef:{doi}" if doi else "CrossRef:unknown",
            "doi": doi,
            "title": _clean(it.get("title")),
            "authors": _authors(it.get("author")),
            "venue": _clean(it.get("container-title")) or "unknown venue",
            "year": _year_of(issued),
            "keywords": [_clean(s) for s in (it.get("subject") or []) if s],
            "abstract": _clean(it.get("abstract")),
            "url": _clean(it.get("URL")) or (f"https://doi.org/{doi}" if doi else ""),
            "source": "crossref",
            "citations": int(it.get("is-referenced-by-count") or 0),
        })
    return docs


def _fetch_crossref(goal: str, max_results: int,
                    timeout: float) -> tuple[list[dict], str]:
    params = urllib.parse.urlencode({
        "query": goal, "rows": max(1, min(max_results, 100)), "mailto": "noreply@example.com"})
    payload = _fetch_json(f"{CROSSREF_API}?{params}", timeout)
    return parse_crossref(payload), goal


def search_crossref(goal: str, max_results: int = DEFAULT_MAX_RESULTS,
                    timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], str]:
    """检索 CrossRef（DOI 元数据校验源）。"""
    return _fetch_crossref(goal, max_results, timeout)


# =====================================================================
# 统一多源入口：search_papers（F-1.1）
# =====================================================================

# 默认后端表：便于测试注入伪后端（完全离线、确定性）
DEFAULT_BACKENDS = {
    "arxiv": _fetch_arxiv,
    "semantic_scholar": _fetch_semantic_scholar,
    "openalex": _fetch_openalex,
    "crossref": _fetch_crossref,
}


def _dedup_key(doc: dict):
    doi = (doc.get("doi") or "").strip().lower()
    if doi:
        return ("doi", doi)
    title = re.sub(r"[^a-z0-9]+", "", (doc.get("title") or "").lower())
    authors = doc.get("authors") or []
    first = ""
    if authors:
        parts = re.split(r"[\s,]+", authors[0].strip())
        if parts:
            first = re.sub(r"[^a-z]+", "", parts[-1].lower())
    return ("ta", title, first)


def dedup_documents(docs: list[dict]) -> list[dict]:
    """DOI 精确去重 + 标题·首作者模糊去重；重复项合并来源与字段。

    合并策略：逐字段取首个非空值，``sources`` 累积全部命中源，
    ``citations`` 取最大值 —— 结果与输入顺序绑定，稳定可复现。
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for d in docs:
        key = _dedup_key(d)
        if key not in merged:
            rec = dict(d)
            rec["sources"] = [d.get("source", "")] if d.get("source") else []
            merged[key] = rec
            order.append(key)
            continue
        rec = merged[key]
        for field in ("doi", "title", "venue", "abstract", "url", "doc_id"):
            if not rec.get(field) and d.get(field):
                rec[field] = d[field]
        if not rec.get("authors") and d.get("authors"):
            rec["authors"] = d["authors"]
        if not rec.get("year") and d.get("year"):
            rec["year"] = d["year"]
        if not rec.get("keywords") and d.get("keywords"):
            rec["keywords"] = d["keywords"]
        rec["citations"] = max(int(rec.get("citations") or 0),
                               int(d.get("citations") or 0))
        src = d.get("source", "")
        if src and src not in rec["sources"]:
            rec["sources"].append(src)
    return [merged[k] for k in order]


def score_relevance(doc: dict, goal: str) -> float:
    """相关性评分：goal 关键词在 title/abstract/keywords 中的加权命中比例。

    - 标题命中权重 3、关键词 2、摘要 1（标题匹配最能代表相关性）
    - 归一化为 [0,1]，便于与基线对比；纯函数、确定性
    """
    toks = set(tokenize(goal))
    if not toks:
        return 0.0
    title = (doc.get("title") or "").lower()
    kws = " ".join(doc.get("keywords") or []).lower()
    abstract = (doc.get("abstract") or "").lower()
    hits = 0.0
    for t in toks:
        if t in title:
            hits += 3
        elif t in kws:
            hits += 2
        elif t in abstract:
            hits += 1
    return round(hits / (3 * len(toks)), 6)


def rank_documents(docs: list[dict], goal: str) -> list[dict]:
    """按 (相关性降序, 被引数降序, doc_id 升序) 稳定排序。"""
    scored = []
    for d in docs:
        d = dict(d)
        d["relevance"] = score_relevance(d, goal)
        scored.append(d)
    scored.sort(key=lambda d: (-d["relevance"], -int(d.get("citations") or 0),
                               d.get("doc_id", "")))
    return scored


def search_papers(goal: str, sources: list[str] | None = None,
                  max_results: int = DEFAULT_MAX_RESULTS,
                  timeout: float = DEFAULT_TIMEOUT,
                  backends: dict | None = None) -> dict:
    """统一多源检索（PRD F-1.1）。

    - ``sources`` 缺省取全部 ``ALL_SOURCES``；未知源名忽略并记入 ``skipped_sources``
    - 单源超时/异常 → 跳过该源，记入 ``unavailable_sources``，**不阻塞返回**
    - DOI 精确去重 + 标题·首作者模糊去重（``dedup_documents``）
    - 统一相关性排序，截断到 ``max_results``
    - ``backends`` 可注入伪后端（测试完全离线）

    返回::

        {documents, n_documents, n_raw, sources_status, unavailable_sources,
         skipped_sources, queries, degraded}
    """
    backends = backends if backends is not None else DEFAULT_BACKENDS
    srcs = [s for s in (sources or list(ALL_SOURCES)) if s in backends]
    skipped = [s for s in (sources or []) if s not in backends]

    raw: list[dict] = []
    status: dict[str, str] = {}
    queries: dict[str, str] = {}
    unavailable: list[str] = []

    for src in srcs:
        try:
            docs, query = backends[src](goal, max_results, timeout)
            raw.extend(docs)
            status[src] = f"ok:{len(docs)}"
            queries[src] = query
        except Exception as e:  # noqa: BLE001 —— 单源失败必须降级而非中断
            status[src] = f"unavailable:{type(e).__name__}"
            unavailable.append(src)

    deduped = dedup_documents(raw)
    ranked = rank_documents(deduped, goal)
    docs = ranked[:max_results] if max_results > 0 else ranked

    # 无任何源可用 → 视为整体降级
    degraded = (len(srcs) > 0 and len(unavailable) == len(srcs))
    return {
        "query": goal,
        "sources": srcs,
        "sources_status": status,
        "unavailable_sources": unavailable,
        "skipped_sources": skipped,
        "queries": queries,
        "n_raw": len(raw),
        "n_documents": len(docs),
        "documents": docs,
        "degraded": degraded,
    }


# =====================================================================
# 本地语料（离线兜底 / 确定性基线）
# =====================================================================

def load_local_corpus(root: str) -> list[dict]:
    """读取内置语料并补齐与远端一致的字段（source / url / citations）。"""
    path = os.path.join(root, "data", "literature.json")
    with open(path, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    docs = []
    for d in corpus.get("documents", []):
        doc = dict(d)
        doc["source"] = "local"
        doc.setdefault("sources", ["local"])
        doc.setdefault("citations", 0)
        if not doc.get("url"):
            doc["url"] = (f"https://doi.org/{doc['doi']}"
                          if doc.get("doi") else "")
        docs.append(doc)
    return docs


def filter_by_relevance(docs: list[dict], goal: str) -> list[dict]:
    """按 goal 关键词命中数过滤并排序（本地语料用；远端侧已由 API 排序）。

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


# =====================================================================
# 联网文献腿（novus 可信冻结快照用；与 mike 多源检索互不冲突）
# 仅被 freezing.py 的 network 模式消费；bootstrap 默认模式不触网。
# 复用本模块已导入的 urllib / json / os / re / time。
# =====================================================================

CROSSREF = "crossref"
OPENALEX = "openalex"
SOURCES = (CROSSREF, OPENALEX)

DEFAULT_MAILTO = "paper-agent@example.org"
DEFAULT_RETRIES = 2
BACKOFF = [1, 2]


class SearchError(RuntimeError):
    """检索失败（网络异常 / 接口错误 / 响应无法解析）。"""


def make_record(doi, title, authors, year, venue, source, query=""):
    return {
        "doi": (doi or "").strip().lower(),
        "title": (title or "").strip(),
        "authors": list(authors or []),
        "year": year,
        "venue": (venue or "").strip(),
        "source": source,
        "query": query,
    }


def _year_from_date_parts(dp):
    try:
        y = dp["date-parts"][0][0]
        return int(y)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def parse_crossref_item(item, query=""):
    """Crossref /works 单条 → 统一记录。缺 DOI 或标题则丢弃。"""
    doi = item.get("DOI") or ""
    titles = item.get("title") or []
    title = titles[0] if titles else ""
    if not doi and not title:
        return None
    authors = []
    for a in item.get("author") or []:
        name = " ".join(x for x in (a.get("given"), a.get("family")) if x).strip()
        if not name:
            name = (a.get("name") or "").strip()
        if name:
            authors.append(name)
    venues = item.get("container-title") or []
    return make_record(
        doi=doi, title=title, authors=authors,
        year=_year_from_date_parts(item.get("issued")),
        venue=venues[0] if venues else "",
        source=CROSSREF, query=query,
    )


def parse_openalex_item(item, query=""):
    """OpenAlex /works 单条 → 统一记录。DOI 带 https://doi.org/ 前缀需剥掉。"""
    raw_doi = item.get("doi") or ""
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", raw_doi, flags=re.I)
    title = item.get("display_name") or item.get("title") or ""
    if not doi and not title:
        return None
    authors = []
    for a in item.get("authorships") or []:
        name = ((a.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    venue = (((item.get("primary_location") or {}).get("source") or {})
             .get("display_name") or "")
    year = item.get("publication_year")
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None
    return make_record(doi=doi, title=title, authors=authors, year=year,
                       venue=venue, source=OPENALEX, query=query)


def build_url(source, query, rows, mailto, timeout=DEFAULT_TIMEOUT) -> str:
    q = urllib.parse.quote(query)
    if source == CROSSREF:
        return (f"https://api.crossref.org/works?query={q}"
                f"&rows={int(rows)}&select=DOI,title,author,issued,container-title"
                f"&mailto={urllib.parse.quote(mailto)}")
    if source == OPENALEX:
        return (f"https://api.openalex.org/works?search={q}"
                f"&per-page={int(rows)}&mailto={urllib.parse.quote(mailto)}")
    raise SearchError(f"unknown source: {source}")


def http_get_json(url, timeout=DEFAULT_TIMEOUT, mailto=DEFAULT_MAILTO) -> dict:
    """默认传输层：真实 HTTP GET，返回解析后的 JSON。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": f"paper-agent/0.2 (mailto:{mailto})",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _items_of(source, payload) -> list[dict]:
    if source == CROSSREF:
        return list(((payload or {}).get("message") or {}).get("items") or [])
    if source == OPENALEX:
        return list((payload or {}).get("results") or [])
    raise SearchError(f"unknown source: {source}")


def search_one(query, source=CROSSREF, rows=20, transport=None, mailto=DEFAULT_MAILTO,
               timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES, sleep=time.sleep):
    """单个检索式在单个来源上检索，返回统一记录列表。失败抛 SearchError。"""
    transport = transport or http_get_json
    url = build_url(source, query, rows, mailto, timeout)
    parse = parse_crossref_item if source == CROSSREF else parse_openalex_item
    last_err = None
    for attempt in range(retries + 1):
        try:
            payload = transport(url)
            out = []
            for it in _items_of(source, payload):
                rec = parse(it, query)
                if rec:
                    out.append(rec)
            return out
        except SearchError:
            raise
        except Exception as e:  # 网络/解析异常 → 有限重试
            last_err = e
            if attempt < retries:
                sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
    raise SearchError(f"{source} search failed for {query!r}: "
                      f"{type(last_err).__name__}: {last_err}")


def merge_records(records):
    """按 DOI（无 DOI 时按小写标题）去重合并；多来源命中同一论文时保留字段更全者。"""
    by_key = {}
    for r in records:
        key = r["doi"] or ("title:" + r["title"].lower())
        if not key or key == "title:":
            continue
        cur = by_key.get(key)
        if cur is None:
            base = dict(r)
            base["sources"] = sorted({s for s in [r.get("source", "")] if s})
            base["queries"] = sorted({q for q in [r.get("query", "")] if q})
            by_key[key] = base
            continue
        merged = dict(cur)
        if len(r.get("authors") or []) > len(merged.get("authors") or []):
            merged["authors"] = r["authors"]
        for f in ("title", "venue"):
            if len(r.get(f) or "") > len(merged.get(f) or ""):
                merged[f] = r[f]
        if merged.get("year") is None and r.get("year") is not None:
            merged["year"] = r["year"]
        srcs = set(merged.get("sources") or []) | {r.get("source", "")}
        merged["sources"] = sorted(s for s in srcs if s)
        merged["source"] = merged["sources"][0] if merged["sources"] else ""
        qs = set(merged.get("queries") or []) | {r.get("query", "")}
        merged["queries"] = sorted(q for q in qs if q)
        by_key[key] = merged
    return [by_key[k] for k in sorted(by_key)]


def search(queries, sources=SOURCES, rows=20, transport=None, mailto=DEFAULT_MAILTO,
           timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES, sleep_s=0.5, sleep=time.sleep):
    """多检索式 × 多来源检索，返回 {"records": [...], "per_query": {...}, "errors": [...]}。

    单个检索式/来源失败**不中断整体**，错误记入 errors（由异常检测层决定是否打断）。
    """
    all_records = []
    per_query = {}
    errors = []
    for q in queries:
        n = 0
        for src in sources:
            try:
                recs = search_one(q, src, rows, transport, mailto, timeout,
                                  retries, sleep)
                all_records.extend(recs)
                n += len(recs)
            except SearchError as e:
                errors.append({"query": q, "source": src, "error": str(e)})
            if sleep_s:
                sleep(sleep_s)
        per_query[q] = {"n_raw": n}
    merged = merge_records(all_records)
    for q, info in per_query.items():
        info["n_in_merged"] = sum(
            1 for r in merged if q in (r.get("queries") or []))
    return {
        "queries": list(queries),
        "sources": list(sources),
        "n_raw": len(all_records),
        "n_unique": len(merged),
        "records": merged,
        "per_query": per_query,
        "errors": errors,
    }


def mailto_from_env() -> str:
    return os.environ.get("PAPER_AGENT_MAILTO", DEFAULT_MAILTO)


__all__ = [
    "ARXIV_API", "SEMANTIC_SCHOLAR_API", "OPENALEX_API", "CROSSREF_API",
    "ALL_SOURCES", "SOURCE_LABELS", "DEFAULT_BACKENDS",
    "tokenize", "build_arxiv_query", "parse_arxiv_atom", "search_arxiv",
    "parse_semantic_scholar", "search_semantic_scholar",
    "parse_openalex", "search_openalex",
    "parse_crossref", "search_crossref",
    "dedup_documents", "score_relevance", "rank_documents", "search_papers",
    "load_local_corpus", "filter_by_relevance", "ref_of",
    "CROSSREF", "OPENALEX", "SOURCES", "DEFAULT_MAILTO", "DEFAULT_RETRIES",
    "BACKOFF", "SearchError", "make_record", "parse_crossref_item",
    "parse_openalex_item", "build_url", "http_get_json", "_items_of",
    "search_one", "merge_records", "search", "mailto_from_env",
]
