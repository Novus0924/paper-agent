"""litsearch.py — 联网文献腿（redesign-decisions.md D3 文献腿）。

职责边界（严格）：
- 只做"检索式 → 论文元数据"的搬运与归一，**不做相关性判断**（判断属 judgment 级，
  由判断器产生并留痕；见 D4 / D5）。
- **不抓论文全文**（版权红线）：只调 Crossref / OpenAlex 的**元数据接口**。
- 零第三方依赖，仅标准库。

可测性设计：HTTP 传输层通过 ``transport`` 参数注入。
- 默认 ``http_get_json`` 走真实网络；
- 单元测试注入假传输层，**无需联网**即可覆盖解析、去重、重试与错误处理。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CROSSREF = "crossref"
OPENALEX = "openalex"
SOURCES = (CROSSREF, OPENALEX)

DEFAULT_MAILTO = "paper-agent@example.org"
DEFAULT_TIMEOUT = 25
DEFAULT_RETRIES = 2
BACKOFF = [1, 2]


class SearchError(RuntimeError):
    """检索失败（网络异常 / 接口错误 / 响应无法解析）。"""


# ---------- 统一记录 ----------

def make_record(doi: str, title: str, authors: list[str], year,
                venue: str, source: str, query: str = "") -> dict:
    return {
        "doi": (doi or "").strip().lower(),
        "title": (title or "").strip(),
        "authors": list(authors or []),
        "year": year,
        "venue": (venue or "").strip(),
        "source": source,
        "query": query,
    }


def _year_from_date_parts(dp) -> int | None:
    try:
        y = dp["date-parts"][0][0]
        return int(y)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def parse_crossref_item(item: dict, query: str = "") -> dict | None:
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


def parse_openalex_item(item: dict, query: str = "") -> dict | None:
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


# ---------- URL 构造 ----------

def build_url(source: str, query: str, rows: int, mailto: str,
              timeout: int = DEFAULT_TIMEOUT) -> str:
    q = urllib.parse.quote(query)
    if source == CROSSREF:
        return (f"https://api.crossref.org/works?query={q}"
                f"&rows={int(rows)}&select=DOI,title,author,issued,container-title"
                f"&mailto={urllib.parse.quote(mailto)}")
    if source == OPENALEX:
        return (f"https://api.openalex.org/works?search={q}"
                f"&per-page={int(rows)}&mailto={urllib.parse.quote(mailto)}")
    raise SearchError(f"unknown source: {source}")


# ---------- 传输层 ----------

def http_get_json(url: str, timeout: int = DEFAULT_TIMEOUT,
                  mailto: str = DEFAULT_MAILTO) -> dict:
    """默认传输层：真实 HTTP GET，返回解析后的 JSON。

    尊重 http(s)_proxy 环境变量（urllib 默认行为）。
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": f"paper-agent/0.2 (mailto:{mailto})",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _items_of(source: str, payload: dict) -> list[dict]:
    if source == CROSSREF:
        return list(((payload or {}).get("message") or {}).get("items") or [])
    if source == OPENALEX:
        return list((payload or {}).get("results") or [])
    raise SearchError(f"unknown source: {source}")


# ---------- 检索 ----------

def search_one(query: str, source: str = CROSSREF, rows: int = 20,
               transport=None, mailto: str = DEFAULT_MAILTO,
               timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES,
               sleep=time.sleep) -> list[dict]:
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


def merge_records(records: list[dict]) -> list[dict]:
    """按 DOI（无 DOI 时按小写标题）去重合并；多来源命中同一论文时保留字段更全者。

    输出记录统一带 ``sources`` / ``queries`` 两个列表字段（便于对接与审计）。
    """
    by_key: dict[str, dict] = {}
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
        # 合并：作者/期刊取更全的，年份取有值者，来源与检索式集合求并
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


def search(queries: list[str], sources: tuple = (CROSSREF,),
           rows: int = 20, transport=None, mailto: str = DEFAULT_MAILTO,
           timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES,
           sleep_s: float = 0.5, sleep=time.sleep) -> dict:
    """多检索式 × 多来源检索，返回 {"records": [...], "per_query": {...}, "errors": [...]}。

    单个检索式/来源失败**不中断整体**，错误记入 errors（由异常检测层决定是否打断）。
    """
    all_records: list[dict] = []
    per_query: dict[str, dict] = {}
    errors: list[dict] = []
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
