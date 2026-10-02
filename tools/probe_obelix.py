#!/usr/bin/env python3
"""probe_obelix.py — 技术探针：验证 OBELiX 数据集可用性与 DOI 可解析性。

设计约束（对齐 docs/redesign-decisions.md §7 第 0 步）：
- 零第三方依赖，仅标准库
- 本地分析永远可跑（离线）；DOI 抽查需联网，用 --doi-sample N 显式开启
- 只读，不修改任何输入文件
- 列名自适应：OBELiX 官方 CSV 用人类可读表头（"Ionic conductivity (S cm-1)"），
  第三方镜像可能用 snake_case（ionic_conductivity_s_per_cm），两者都要能读

用法:
    python tools/probe_obelix.py --input data/external/obelix/all.csv
    python tools/probe_obelix.py --input data/external/obelix/all.csv --doi-sample 10
    python tools/probe_obelix.py --input ... --doi-sample 10 --json-out tools/probe-report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 列名候选（按优先级）；用规范化后的表头做匹配
CANON = {
    "id": ["id"],
    "composition": ["reducedcomposition", "reduced_composition"],
    "true_composition": ["truecomposition", "true_composition"],
    "cond_main": ["ionicconductivityscm1", "ionic_conductivity_s_per_cm",
                  "ionicconductivityscm"],
    "cond_total": ["ictotal", "ic_total", "ic_total_s_per_cm"],
    "cond_bulk": ["icbulk", "ic_bulk", "ic_bulk_s_per_cm"],
    "space_group": ["spacegroup", "space_group"],
    "family": ["family"],
    "doi": ["doi", "source_doi"],
    "close_match": ["closematch", "close_match"],
    "close_match_doi": ["closematchdoi", "close_match_doi"],
    "split": ["split"],
    "has_cif": ["cifid", "has_cif", "cif_id"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def resolve_columns(fields: list[str]) -> dict[str, str | None]:
    normed = {_norm(f): f for f in fields}
    out: dict[str, str | None] = {}
    for key, cands in CANON.items():
        found = None
        for c in cands:
            if _norm(c) in normed:
                found = normed[_norm(c)]
                break
        out[key] = found
    return out


def _num(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pick(row: dict, col: str | None) -> str:
    if not col:
        return ""
    return (row.get(col) or "").strip()


def analyze(rows: list[dict], fields: list[str]) -> dict:
    cols = resolve_columns(fields)
    n = len(rows)

    fmt_counter: dict[str, int] = {}
    upper, empty, ok_main, ok_total, ok_bulk = 0, 0, 0, 0, 0
    src = {"main": 0, "ic_total": 0, "ic_bulk": 0, "none": 0}
    vals = []
    for r in rows:
        v_main = _pick(r, cols["cond_main"])
        v_tot = _pick(r, cols["cond_total"])
        v_bulk = _pick(r, cols["cond_bulk"])

        # 记录原始写法形态，便于评估清洗规则
        if v_main == "":
            fmt_counter["(空)"] = fmt_counter.get("(空)", 0) + 1
            empty += 1
        elif v_main.startswith("<"):
            fmt_counter["上界记法 <"] = fmt_counter.get("上界记法 <", 0) + 1
            upper += 1
        elif "e" in v_main.lower():
            fmt_counter["科学计数法"] = fmt_counter.get("科学计数法", 0) + 1
        else:
            fmt_counter["纯小数"] = fmt_counter.get("纯小数", 0) + 1

        a, b, c = _num(v_main), _num(v_tot), _num(v_bulk)
        ok_main += 1 if (a is not None and not v_main.startswith("<")) else 0
        ok_total += 1 if b is not None else 0
        ok_bulk += 1 if c is not None else 0

        # 可用值来源优先级：主列（非上界） > IC(Total) > IC(Bulk)
        if a is not None and not v_main.startswith("<"):
            src["main"] += 1
            vals.append((a, _pick(r, cols["composition"]), _pick(r, cols["doi"]),
                         _pick(r, cols["id"])))
        elif b is not None:
            src["ic_total"] += 1
            vals.append((b, _pick(r, cols["composition"]), _pick(r, cols["doi"]),
                         _pick(r, cols["id"])))
        elif c is not None:
            src["ic_bulk"] += 1
            vals.append((c, _pick(r, cols["composition"]), _pick(r, cols["doi"]),
                         _pick(r, cols["id"])))
        else:
            src["none"] += 1

    dois = [_pick(r, cols["doi"]) for r in rows]
    uniq = {d for d in dois if d}
    close_dois = [_pick(r, cols["close_match_doi"]) for r in rows]

    def dist(key: str) -> dict:
        bucket: dict[str, int] = {}
        for r in rows:
            v = _pick(r, cols[key]) or "(空)"
            bucket[v] = bucket.get(v, 0) + 1
        return dict(sorted(bucket.items(), key=lambda x: -x[1]))

    fam = dist("family")
    vals.sort(key=lambda x: -x[0])

    return {
        "n_rows": n,
        "resolved_columns": {k: v for k, v in cols.items()},
        "unresolved_columns": [k for k, v in cols.items() if not v],
        "conductivity": {
            "raw_format_distribution": fmt_counter,
            "raw_upper_bound_notation": upper,
            "raw_empty_or_missing": empty,
            "parsed_main_ok": ok_main,
            "parsed_ic_total_ok": ok_total,
            "parsed_ic_bulk_ok": ok_bulk,
            "usable_numeric_rows": len(vals),
            "usable_ratio": round(len(vals) / n, 4) if n else 0.0,
            "value_source_preference": src,
        },
        "doi": {
            "rows_with_doi": sum(1 for d in dois if d),
            "doi_coverage": round(sum(1 for d in dois if d) / n, 4) if n else 0.0,
            "unique_doi": len(uniq),
            "rows_with_close_match_doi": sum(1 for d in close_dois if d),
        },
        "field_distribution": {
            "family_unique": len(fam),
            "family_top20": dict(list(fam.items())[:20]),
            "space_group_unique": len(dist("space_group")),
            "close_match": dist("close_match") if cols["close_match"] else {},
            "has_cif": dist("has_cif") if cols["has_cif"] else {},
            "split": dist("split") if cols["split"] else {},
        },
        "top10_by_conductivity": [
            {"composition": c, "S_per_cm": v, "doi": d, "id": i}
            for v, c, d, i in vals[:10]
        ],
    }


def doi_probe(rows: list[dict], fields: list[str], sample: int,
              sleep_s: float = 1.0) -> dict:
    cols = resolve_columns(fields)
    dois, seen = [], set()
    for r in rows:
        d = _pick(r, cols["doi"])
        if d and d not in seen:
            seen.add(d)
            dois.append(d)
    if sample and len(dois) > sample:
        step = len(dois) / sample
        picked = [dois[int(i * step)] for i in range(sample)]
    else:
        picked = dois[:sample]

    out = []
    for d in picked:
        rec = {"doi": d}
        for name, url in (
            ("crossref", "https://api.crossref.org/works/" + urllib.parse.quote(d)),
            ("openalex", "https://api.openalex.org/works/doi:" + urllib.parse.quote(d)),
        ):
            req = urllib.request.Request(url, headers={
                "User-Agent": "paper-agent-probe/0.1 (mailto:probe@example.org)",
                "Accept": "application/json",
            })
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    body = resp.read(4000)
                rec[name] = {"http": resp.status,
                             "ms": int((time.time() - t0) * 1000),
                             "bytes": len(body)}
            except urllib.error.HTTPError as e:
                rec[name] = {"http": e.code, "ms": int((time.time() - t0) * 1000)}
            except Exception as e:
                rec[name] = {"error": f"{type(e).__name__}: {e}"}
            time.sleep(sleep_s)
        out.append(rec)

    return {
        "sampled": len(out),
        "crossref_resolved": sum(1 for r in out if r.get("crossref", {}).get("http") == 200),
        "openalex_resolved": sum(1 for r in out if r.get("openalex", {}).get("http") == 200),
        "details": out,
    }


def main(argv):
    ap = argparse.ArgumentParser(prog="probe_obelix")
    ap.add_argument("--input", required=True)
    ap.add_argument("--doi-sample", type=int, default=0,
                    help="抽样 N 个 DOI 验证可解析性（需联网；0 = 跳过）")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv[1:])

    if not os.path.exists(args.input):
        print(json.dumps({"ok": False, "error": f"input not found: {args.input}"},
                         ensure_ascii=False))
        return 1

    with open(args.input, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = [f for f in (reader.fieldnames or [])]
        rows = [{k: (v if v is not None else "") for k, v in r.items()} for r in reader]

    report = {"ok": True, "input": args.input, **analyze(rows, fields)}
    if args.doi_sample:
        report["doi_resolution"] = doi_probe(rows, fields, args.doi_sample, args.sleep)

    if args.json_out:
        d = os.path.dirname(os.path.abspath(args.json_out))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8", newline="") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    c, dd = report["conductivity"], report["doi"]
    summary = {
        "n_rows": report["n_rows"],
        "unresolved_columns": report["unresolved_columns"],
        "usable_numeric_rows": c["usable_numeric_rows"],
        "usable_ratio": c["usable_ratio"],
        "upper_bound_notation": c["raw_upper_bound_notation"],
        "raw_empty": c["raw_empty_or_missing"],
        "raw_format_distribution": c["raw_format_distribution"],
        "value_source_preference": c["value_source_preference"],
        "doi_coverage": dd["doi_coverage"],
        "unique_doi": dd["unique_doi"],
        "family_unique": report["field_distribution"]["family_unique"],
        "family_top20": report["field_distribution"]["family_top20"],
    }
    if "doi_resolution" in report:
        r = report["doi_resolution"]
        summary["doi_resolution"] = {"sampled": r["sampled"],
                                     "crossref_resolved": r["crossref_resolved"],
                                     "openalex_resolved": r["openalex_resolved"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
