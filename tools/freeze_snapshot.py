#!/usr/bin/env python3
"""freeze_snapshot.py — 把一轮"检索 + 判断"的结果冻结成输入快照（redesign D6）。

冻结之后，复算 / 验证 / 出报告全部只针对该快照；复现契约覆盖"冻结之后"。

关于判断的生产者（诚实声明）
--------------------------------------------------
本工具当前使用**规则式**判断产出判断批次（``producer=bootstrap_rule_v1``），
目的是在模型接入（第二批）之前先行打通"快照 → 主线 → 报告"的完整链路，
并把判断留痕、被排除项、判据 4 闸门等机制**先用真实数据验证一遍**。

规则与别名表全部写在源码里，可见、可复核、可被反驳。模型接入后，
只需把 ``produce_judgments()`` 换成模型调用，**同一位置、同一数据契约**——
届时可以用"反判据"检验模型的判断是否真的改变结果（对比规则式基线）。

用法::

    python tools/freeze_snapshot.py --goal "sulfide solid electrolyte ionic conductivity ranking"
    python tools/freeze_snapshot.py --goal "..." --input data/external/obelix/all.csv
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

from paper_agent import sources  # noqa: E402
from paper_agent import snapshot as snapshot_mod  # noqa: E402

PRODUCER = "bootstrap_rule_v1"

STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
        "are", "with", "as", "at", "by", "from", "it", "its", "ranking",
        "rank", "best", "top"}

#: bootstrap 规则式的化学同义词表（可复核、可反驳；模型接入后由模型替代）
FAMILY_ALIASES = {
    "sulfide": ("sulfide", "sulfides", "thio", "argyrodit", "lgps"),
    "sulphide": ("sulfide", "sulfides", "thio", "argyrodit", "lgps"),
    "oxide": ("oxide", "oxides", "garnet", "perovskit", "nasicon", "lisicon",
              "phosphate", "molybdate", "hexaoxometalate"),
    "halide": ("halide", "halides", "chloride", "chlorides", "bromide",
               "iodide"),
    "garnet": ("garnet",),
    "nasicon": ("nasicon",),
    "argyrodite": ("argyrodit",),
    "perovskite": ("perovskit",),
    "hydride": ("hydride", "hydrides"),
    "nitride": ("nitride", "nitrides"),
    "phosphate": ("phosphate", "phosphates"),
    "polymer": ("polymer",),
}


def tokenize(goal: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", goal.lower())
    return [t for t in toks if t not in STOP and len(t) > 2]


def family_verdict(family: str, tokens: list[str]) -> tuple[str, str]:
    """返回 (verdict, rationale)。规则式：家族名匹配任一关键词/同义词即相关。"""
    fam = (family or "").lower()
    if not fam:
        return "excluded", "源数据家族字段为空，无法判定主题归属"
    for t in tokens:
        cands = FAMILY_ALIASES.get(t, (t,))
        for c in cands:
            if c in fam:
                return "relevant", f"家族名含关键词 {t!r} 的同义词 {c!r}"
    return "excluded", f"家族名未匹配目标关键词（{', '.join(tokens)}）"


def produce_judgments(goal: str, families: list[str]) -> tuple[list[dict], dict[str, str]]:
    """产出判断批次 + 家族 → 是否在范围内 的映射（模型接入后替换本函数）。"""
    tokens = tokenize(goal)
    judgments: list[dict] = [{
        "tier": "judgment", "kind": "query_generation",
        "producer_step": "P1_lit_search", "ref": goal,
        "meta": {
            "subject": goal, "verdict": "generated",
            "rationale": f"规则式拆词（{PRODUCER}，非模型判断）：去停用词后取关键词",
            "queries": tokens,
        },
    }]
    scope: dict[str, str] = {}
    for fam in sorted(families):
        verdict, rationale = family_verdict(fam, tokens)
        scope[fam] = verdict
        judgments.append({
            "tier": "judgment", "kind": "relevance",
            "producer_step": "P1_lit_search", "ref": fam or "(empty)",
            "meta": {"subject": fam or "(empty)", "verdict": verdict,
                     "rationale": rationale, "axis": "material_family"},
        })
    return judgments, scope


def main(argv):
    ap = argparse.ArgumentParser(prog="freeze_snapshot")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--input", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv[1:])

    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    src = args.input or os.path.join(root, "data", "external", "obelix", "all.csv")

    rows, meta = sources.read_obelix(src)
    base = sources.summarize(rows)

    families = sorted({r["family"] for r in rows if r["family"]})
    judgments, scope = produce_judgments(args.goal, families)

    # 判断的可见效果：把"是否在目标范围内"写回数据行
    for r in rows:
        r["in_scope"] = scope.get(r["family"], "excluded")

    # 文献腿（bootstrap）：数据集的原始论文 DOI 集合
    dois = sorted({r["source_doi"] for r in rows if r["source_doi"]})
    literature = {
        "goal": args.goal,
        "source": "obelix_bootstrap",
        "note": ("bootstrap 文献腿：仅为数据集内原始论文 DOI 集合；"
                 "标题/作者等元数据由第二批的联网文献腿补齐"),
        "n_hits": len(dois),
        "hits": [{"doi": d, "source": "obelix_bootstrap"} for d in dois],
    }

    sid = snapshot_mod.new_snapshot_id()
    snap = snapshot_mod.Snapshot(root, sid)
    manifest = snap.write(
        materials_csv=sources.to_materials_csv(rows),
        literature=literature,
        judgments=judgments,
        sources=[{
            "name": "obelix",
            "url": "https://github.com/NRC-Mila/OBELiX",
            "license": "CC-BY-4.0",
            "citation": "Therrien et al., arXiv:2502.14234",
        }],
        producer=PRODUCER,
        stats={
            "goal": args.goal,
            "n_rows": base["n_rows"],
            "value_status": base["value_status"],
            "family_empty": base["family_empty"],
            "n_families": len(families),
            "in_scope_families": sum(1 for v in scope.values() if v == "relevant"),
            "in_scope_rows": sum(1 for r in rows if r["in_scope"] == "relevant"),
            "judgments": len(judgments),
        },
    )

    ok, problems = snap.verify()
    out = {
        "ok": ok,
        "snapshot_id": sid,
        "path": snap.dir,
        "content_sha256": manifest["content_sha256"],
        "stats": manifest["stats"],
        "verify_problems": problems,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
