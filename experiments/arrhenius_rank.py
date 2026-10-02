#!/usr/bin/env python3
"""arrhenius_rank — 零依赖确定性实验脚本。

固态电解质电导率打分排序（演示代理模型，非真实物理）。

调用：
    python experiments/arrhenius_rank.py --input <csv> --outdir <dir> --seed 0

输入 CSV 列（需含）：material_id, formula, family, conductivity_Scm, year
输出（相对 outdir）：
    results/results.csv   —— 数值定长格式化，逐字节稳定
    results/summary.json  —— 统计 + 环境元组；generated_at 为唯一可变时间戳
    figures/fig1_conductivity.svg —— 纯标准库 SVG 横向条形图

确定性契约：
    - 无未初始化随机源；seed 仅作输入回显
    - 排序 tie-break：score 降序，同分按 formula 字典序
    - 仅 generated_at 为可变时间戳，复现校验时排除

故障开关：环境变量 paper-agent_MUTATE=1 时，交换 summary top1/top2 条目，
用于触发 P4 复现验证 FAIL 用例（不改变 results.csv）。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import platform
import sys
import time

STABILITY = {"sulfide": 0.60, "argyrodite": 0.70, "garnet": 0.90, "thin_film": 0.80}
BASE_YEAR = 1992
SPAN = 24
WEIGHTS = {"cond": 0.6, "stab": 0.25, "rec": 0.15}
FAMILY_COLOR = {"sulfide": "#d62728", "argyrodite": "#2ca02c", "garnet": "#1f77b4", "thin_film": "#ff7f0e"}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_rows(input_path: str):
    rows = []
    with open(input_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit("input csv empty")
        names = [c.strip() for c in reader.fieldnames]
        for raw in reader:
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if not row.get("material_id"):
                continue
            try:
                cond = float(row["conductivity_Scm"])
                year = int(row["year"])
            except (KeyError, ValueError, TypeError):
                continue
            rows.append(
                {
                    "material_id": row["material_id"],
                    "formula": row.get("formula", ""),
                    "family": row.get("family", ""),
                    "conductivity_Scm": cond,
                    "year": year,
                    "activation_energy_eV": row.get("activation_energy_eV", ""),
                    "source_doi": row.get("source_doi", ""),
                }
            )
    return rows


def _minmax(vals):
    lo = min(vals)
    hi = max(vals)
    rng = hi - lo
    if rng == 0:
        return [0.5 for _ in vals]
    return [(v - lo) / rng for v in vals]


def _compute(rows):
    log10 = [math.log10(r["conductivity_Scm"]) for r in rows]
    norm = _minmax(log10)
    scored = []
    for i, r in enumerate(rows):
        cond_norm = norm[i]
        stab = STABILITY.get(r["family"], 0.5)
        recency = (r["year"] - BASE_YEAR) / SPAN
        score = WEIGHTS["cond"] * cond_norm + WEIGHTS["stab"] * stab + WEIGHTS["rec"] * recency
        scored.append(
            {
                "material_id": r["material_id"],
                "formula": r["formula"],
                "family": r["family"],
                "year": r["year"],
                "cond_Scm": r["conductivity_Scm"],
                "log10_cond": log10[i],
                "cond_norm": cond_norm,
                "stability": stab,
                "recency": recency,
                "score": score,
                "source_doi": r["source_doi"],
            }
        )
    # tie-break: score desc, then formula lex, then material_id for total order
    scored.sort(key=lambda s: (-s["score"], s["formula"], s["material_id"]))
    for rank, s in enumerate(scored, start=1):
        s["rank"] = rank
    return scored


def _results_csv(scored):
    buf = io.StringIO()
    cols = ["rank", "material_id", "formula", "family", "year", "cond_Scm", "log10_cond", "cond_norm", "stability", "recency", "score"]
    buf.write(",".join(cols) + "\n")
    for s in scored:
        buf.write(
            f"{s['rank']},{s['material_id']},{s['formula']},{s['family']},{s['year']},"
            f"{s['cond_Scm']:.6e},{s['log10_cond']:.6e},{s['cond_norm']:.6f},"
            f"{s['stability']:.6f},{s['recency']:.6f},{s['score']:.6f}\n"
        )
    return buf.getvalue()


def _family_mean(scored):
    groups = {}
    for s in scored:
        groups.setdefault(s["family"], []).append(s["log10_cond"])
    return {fam: sum(v) / len(v) for fam, v in sorted(groups.items())}


def _summary(scored, input_sha, script_sha, seed, mutate):
    top3 = scored[:3]
    top3_view = [
        {"rank": t["rank"], "material_id": t["material_id"], "formula": t["formula"], "score": round(t["score"], 9)}
        for t in top3
    ]
    if mutate and len(top3_view) >= 2:
        top3_view[0], top3_view[1] = top3_view[1], top3_view[0]
    summary = {
        "n_rows": len(scored),
        "top3": top3_view,
        "family_mean_log10_cond": _family_mean(scored),
        "seed": seed,
        "env": [
            platform.python_version(),
            platform.platform(),
            input_sha,
            script_sha,
        ],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return summary


def _svg(scored):
    width = 720
    top = 60
    row_h = 44
    label_w = 220
    value_w = 90
    n = len(scored)
    height = top + n * row_h + 40
    # log10 scale across all values
    vals = [s["log10_cond"] for s in scored]
    lo = min(vals)
    hi = max(vals)
    rng = (hi - lo) or 1.0

    def bar_x(v):
        frac = (v - lo) / rng
        plot_w = width - label_w - value_w - 20
        return label_w + int(frac * plot_w)

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="monospace">')
    out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(f'<text x="10" y="24" font-size="16" font-weight="bold">log10 ionic conductivity by material</text>')
    y = top
    for s in scored:
        color = FAMILY_COLOR.get(s["family"], "#7f7f7f")
        x0 = bar_x(lo)
        x1 = bar_x(s["log10_cond"])
        if x1 < x0:
            x0, x1 = x1, x0
        out.append(f'<text x="10" y="{y + row_h / 2}" font-size="12">{s["material_id"]} {s["formula"]} ({s["family"]})</text>')
        out.append(f'<rect x="{x0}" y="{y + 6}" width="{max(1, x1 - x0)}" height="{row_h - 12}" fill="{color}"/>')
        out.append(f'<text x="{x1 + 4}" y="{y + row_h / 2}" font-size="11">{s["log10_cond"]:.3f}</text>')
        y += row_h
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv):
    args = argv[1:]
    input_path = None
    outdir = None
    seed = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--input":
            i += 1
            input_path = args[i]
        elif a == "--outdir":
            i += 1
            outdir = args[i]
        elif a == "--seed":
            i += 1
            seed = int(args[i])
        i += 1
    if not input_path or not outdir:
        print("usage: arrhenius_rank.py --input <csv> --outdir <dir> [--seed 0]", file=sys.stderr)
        return 2

    rows = _read_rows(input_path)
    if not rows:
        print("no valid rows", file=sys.stderr)
        return 1

    input_sha = _sha256_file(input_path)
    script_sha = _sha256_text(open(os.path.abspath(__file__), "r", encoding="utf-8").read())

    scored = _compute(rows)
    csv_text = _results_csv(scored)
    mutate = os.environ.get("paper-agent_MUTATE") == "1"
    summary = _summary(scored, input_sha, script_sha, seed, mutate)
    svg = _svg(scored)

    results_dir = os.path.join(outdir, "results")
    figures_dir = os.path.join(outdir, "figures")
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(figures_dir, exist_ok=True)

    with open(os.path.join(results_dir, "results.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    with open(os.path.join(results_dir, "summary.json"), "w", encoding="utf-8", newline="") as f:
        json.dump(summary, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    with open(os.path.join(figures_dir, "fig1_conductivity.svg"), "w", encoding="utf-8", newline="") as f:
        f.write(svg)

    print(json.dumps({"ok": True, "n_rows": len(rows), "results_sha256": _sha256_text(csv_text), "top3": [t["material_id"] for t in summary["top3"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
