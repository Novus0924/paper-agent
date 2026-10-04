#!/usr/bin/env python3
"""search_literature.py — 联网文献腿命令行入口（redesign-decisions.md D3）。

只调 Crossref / OpenAlex 的**元数据接口**，不抓论文全文（版权红线）。

用法::

    # 用目标句子直接检索（关键词由规则式拆词产生）
    python tools/search_literature.py --goal "sulfide solid electrolyte ionic conductivity"

    # 指定检索式与来源
    python tools/search_literature.py --query "argyrodite ionic conductivity" \
        --query "Li6PS5Cl conductivity" --sources crossref,openalex --rows 10

    # 写出结果 JSON（供冻结流程消费）
    python tools/search_literature.py --goal "..." --out /tmp/lit.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

from paper_agent import litsearch as L  # noqa: E402

STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
        "are", "with", "as", "at", "by", "from", "it", "its", "ranking",
        "rank", "best", "top", "which", "what"}


def queries_from_goal(goal: str) -> list[str]:
    """规则式拆词：去停用词后取关键词，拼成 1 个宽检索式 + 若干窄检索式。

    这是**规则式基线**；模型接入后由模型生成检索式（同一数据契约）。
    """
    toks = [t for t in re.findall(r"[a-z0-9]+", goal.lower())
            if t not in STOP and len(t) > 2]
    if not toks:
        return [goal.strip()] if goal.strip() else []
    out = [" ".join(toks)]
    if len(toks) > 2:
        out.append(" ".join(toks[:2]))
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="search_literature")
    ap.add_argument("--goal", default="", help="科研目标；按规则式拆词生成检索式")
    ap.add_argument("--query", action="append", default=[],
                    help="显式检索式（可重复）；与 --goal 二选一或并用")
    ap.add_argument("--sources", default="crossref,openalex")
    ap.add_argument("--rows", type=int, default=10)
    ap.add_argument("--out", default="")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv[1:])

    queries = list(args.query) or queries_from_goal(args.goal)
    if not queries:
        print(json.dumps({"ok": False, "error": "need --goal or --query"},
                         ensure_ascii=False))
        return 2
    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    bad = [s for s in sources if s not in L.SOURCES]
    if bad:
        print(json.dumps({"ok": False, "error": f"unknown sources: {bad}",
                          "allowed": list(L.SOURCES)}, ensure_ascii=False))
        return 2

    res = L.search(queries, sources=sources, rows=args.rows,
                   mailto=L.mailto_from_env())
    out = {
        "ok": True,
        "queries": res["queries"],
        "sources": res["sources"],
        "n_raw": res["n_raw"],
        "n_unique": res["n_unique"],
        "errors": res["errors"],
        "hits": res["records"],
    }
    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    if not args.quiet:
        print(json.dumps({k: out[k] for k in
                          ("ok", "queries", "n_raw", "n_unique", "errors")},
                         ensure_ascii=False, indent=2, sort_keys=True))
        for r in res["records"][:10]:
            au = r["authors"][0] if r["authors"] else "?"
            print(f"  {r['doi']:40s} {str(r['year']):5s} {au:16s} "
                  f"{(r['title'] or '')[:56]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
