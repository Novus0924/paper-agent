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
import statistics
import sys
import time

STABILITY_TABLE = {"sulfide": 0.60, "argyrodite": 0.70, "garnet": 0.90, "thin_film": 0.80}
BASE_YEAR = 1992
SPAN = 24
WEIGHTS = {"cond": 0.6, "stab": 0.25, "rec": 0.15}
FAMILY_COLOR = {"sulfide": "#d62728", "argyrodite": "#2ca02c", "garnet": "#1f77b4", "thin_film": "#ff7f0e"}

# ---- 文献驱动的稳定性代理（取代原先硬编码常量）----
#
# 旧实现的 stability 是四个凭空写死的常量（garnet 固定 0.90），导致排名被
# 人为拍的系数主导，且与 P1 检索到的文献完全脱节。
# 现改为：由**文献报出的活化能 Ea** 反推稳定性代理。
#
# 物理依据：界面副反应速率 ~ exp(-Ea/kT)，即 Ea 越高，离子迁移与界面反应
# 越难被激活，宏观上表现为化学/热稳定性越好。故稳定性代理定义为
# Ea 在样本内的 min-max 归一（Ea 越高 → 代理值越高）。
#
# 这样 stability 就真正由数据（文献导出的活化能）决定，而非人工拍定；
# 且 Ea 缺失时按 material family 中位数插补（与 P2 清洗策略一致），
# 保证算法对缺失值鲁棒且结果可复现。
FAMILY_STABILITY_FALLBACK = dict(STABILITY_TABLE)  # 全家族 Ea 缺失时的兜底


def _stability_proxy(rows):
    """由文献活化能导出稳定性代理，返回 (proxy_list, source_label, ea_values)。

    返回的 proxy 与 rows 等长且顺序一致；缺失 Ea 用同 family 中位数插补。
    """
    # 1) 按 family 收集有效 Ea，取中位数（与 P2 清洗的插补口径一致）
    fam_vals = {}
    for r in rows:
        try:
            fam_vals.setdefault(r["family"], []).append(float(r["activation_energy_eV"]))
        except (ValueError, TypeError):
            pass
    fam_median = {fam: statistics.median(v) for fam, v in fam_vals.items() if v}

    # 2) 逐行取 Ea（缺失则用 family 中位数插补）
    ea_all = []
    imputed = 0
    for r in rows:
        raw = r.get("activation_energy_eV", "")
        try:
            ea_all.append(float(raw))
        except (ValueError, TypeError):
            med = fam_median.get(r["family"])
            if med is not None:
                ea_all.append(med)
                imputed += 1
            else:
                ea_all.append(None)

    # 3) 全部 Ea 都拿不到 → 回退到家族常量表（保证兼容，且显式标注来源）
    valid = [e for e in ea_all if e is not None]
    if not valid:
        return ([FAMILY_STABILITY_FALLBACK.get(r["family"], 0.5) for r in rows],
                "family_table_fallback", ea_all)

    # 4) min-max 归一：Ea 越高 → 稳定性代理越高
    lo, hi = min(valid), max(valid)
    rng = hi - lo
    proxy = []
    for e in ea_all:
        if e is None or rng == 0:
            proxy.append(0.5)
        else:
            proxy.append((e - lo) / rng)
    return proxy, f"activation_energy_minmax(imputed={imputed})", ea_all



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
    # 稳定性代理由文献活化能导出（不再是硬编码家族常量）
    stab_proxy, stab_source, ea_all = _stability_proxy(rows)
    scored = []
    for i, r in enumerate(rows):
        cond_norm = norm[i]
        stab = stab_proxy[i]
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
                "activation_energy_eV": ea_all[i],
            }
        )
    # tie-break: score desc, then formula lex, then material_id for total order
    scored.sort(key=lambda s: (-s["score"], s["formula"], s["material_id"]))
    for rank, s in enumerate(scored, start=1):
        s["rank"] = rank
    return scored, stab_source


# ---- 真实 Arrhenius 外推（脚本名 arrhenius_rank 应有的物理内核）----
#
# σ(T) = σ_ref * exp( -Ea/k * (1/T - 1/T_ref) )
# 用文献报出的室温 σ 与活化能 Ea，外推到工作温度，看排序是否变化。
# 这是真正"用上文献参数"的一步：Ea 全部来自 CSV 的 activation_energy_eV。
K_BOLTZ_EV = 8.617333262e-5  # eV/K
T_REF_K = 298.15             # 室温参考 25°C
T_WORK_C = 60.0              # 工作温度假设 60°C


def _arrhenius_extrapolate(rows):
    """把每个材料的室温电导率外推到工作温度，返回 {material_id: sigma_at_T}。

    Ea 缺失的行不做外推（值为 None），保证可复现且不引入假数据。
    """
    t_work = T_WORK_C + 273.15
    out = {}
    for r in rows:
        try:
            ea = float(r["activation_energy_eV"])
        except (ValueError, TypeError):
            out[r["material_id"]] = None
            continue
        sigma_ref = r["conductivity_Scm"]
        exponent = -(ea / K_BOLTZ_EV) * (1.0 / t_work - 1.0 / T_REF_K)
        out[r["material_id"]] = sigma_ref * math.exp(exponent)
    return out



def _results_csv(scored):
    buf = io.StringIO()
    cols = ["rank", "material_id", "formula", "family", "year", "cond_Scm",
            "log10_cond", "cond_norm", "stability", "recency", "score",
            "activation_energy_eV", "source_doi"]
    buf.write(",".join(cols) + "\n")
    for s in scored:
        ea = s.get("activation_energy_eV")
        ea_s = f"{ea:.6f}" if isinstance(ea, (int, float)) else ""
        buf.write(
            f"{s['rank']},{s['material_id']},{s['formula']},{s['family']},{s['year']},"
            f"{s['cond_Scm']:.6e},{s['log10_cond']:.6e},{s['cond_norm']:.6f},"
            f"{s['stability']:.6f},{s['recency']:.6f},{s['score']:.6f},"
            f"{ea_s},{s['source_doi']}\n"
        )
    return buf.getvalue()


def _family_mean(scored):
    groups = {}
    for s in scored:
        groups.setdefault(s["family"], []).append(s["log10_cond"])
    return {fam: sum(v) / len(v) for fam, v in sorted(groups.items())}


def _summary(scored, input_sha, script_sha, seed, mutate, stab_source, extrapolated):
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
        # ---- 文献驱动的计算溯源：说明 stability 从哪来，可被审计 ----
        "stability_source": stab_source,
        "weights": dict(WEIGHTS),
        "arrhenius": {
            "t_ref_C": T_REF_K - 273.15,
            "t_work_C": T_WORK_C,
            "k_boltz_eV": K_BOLTZ_EV,
            "sigma_at_t_work": extrapolated,
        },
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

    scored, stab_source = _compute(rows)
    csv_text = _results_csv(scored)
    mutate = os.environ.get("paper-agent_MUTATE") == "1"
    extrapolated = _arrhenius_extrapolate(rows)
    summary = _summary(scored, input_sha, script_sha, seed, mutate,
                       stab_source, extrapolated)
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
