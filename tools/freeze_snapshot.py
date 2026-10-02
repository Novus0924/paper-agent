#!/usr/bin/env python3
"""freeze_snapshot.py — 把一轮"检索 + 判断"的结果冻结成输入快照（redesign D6）。

冻结之后，复算 / 验证 / 出报告全部只针对该快照；复现契约覆盖"冻结之后"。

两种文献腿模式
--------------
- ``--literature bootstrap``（默认，**离线**）：文献腿 = 数据集的原始论文 DOI 集合。
  用于离线复现与回归，不联网。
- ``--literature network``（**联网**）：文献腿 = Crossref / OpenAlex 的真实检索结果
  （``core/paper_agent/litsearch.py``），可带 ``--query`` 指定检索式。

关于判断的生产者（诚实声明）
--------------------------------
本工具当前使用**规则式**判断（``producer=bootstrap_rule_v1``），
目的是在模型接入之前打通"快照 → 主线 → 报告"的完整链路，
并把判断留痕、被排除项、判据 4 闸门、异常打断等机制**先用真实数据验证一遍**。
规则与别名表全部写在源码里，可见、可复核、可反驳。
模型接入后只需替换 ``produce_judgments()``，**同一位置、同一数据契约**。

异常驱动打断（D7）
------------------
冻结前跑四条异常规则（零命中 / 两腿无交集 / 命中率反常 / 自相矛盾）。
**检出异常则流程停下并返回退出码 3**，须人工复核后用 ``--ack <code>`` 显式确认，
确认动作会记入快照清单。注意：**低对接率不是异常**（实测两腿交集天然很小）。

用法::

    # 离线（默认）
    python tools/freeze_snapshot.py --goal "sulfide solid electrolyte ionic conductivity ranking"

    # 联网文献腿 + 显式检索式
    python tools/freeze_snapshot.py --goal "..." --literature network \
        --query "argyrodite ionic conductivity" --rows 20

    # 人工复核后确认某异常
    python tools/freeze_snapshot.py --goal "..." --ack no_leg_overlap
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
from paper_agent import anomaly as anomaly_mod  # noqa: E402
from paper_agent import litsearch  # noqa: E402

PRODUCER = "bootstrap_rule_v1"
JUDGE_IMPL = "rule"

STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
        "are", "with", "as", "at", "by", "from", "it", "its", "ranking",
        "rank", "best", "top", "which", "what"}

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
        for c in FAMILY_ALIASES.get(t, (t,)):
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


def build_literature(mode: str, goal: str, rows: list[dict],
                     queries: list[str] | None, n_rows: int,
                     sources_pick) -> tuple[dict, dict | None]:
    """构造文献腿。返回 (literature, search_result_or_None)。"""
    if mode == "bootstrap":
        dois = sorted({r["source_doi"] for r in rows if r["source_doi"]})
        return {
            "goal": goal,
            "source": "obelix_bootstrap",
            "note": ("bootstrap 文献腿：仅为数据集内原始论文 DOI 集合；"
                     "联网文献腿请用 --literature network"),
            "n_hits": len(dois),
            "hits": [{"doi": d, "source": "obelix_bootstrap"} for d in dois],
        }, None

    qs = list(queries or []) or [" ".join(tokenize(goal)) or goal.strip()]
    res = litsearch.search(qs, sources=sources_pick, rows=n_rows,
                           mailto=litsearch.mailto_from_env())
    return {
        "goal": goal,
        "source": "network:" + "+".join(res["sources"]),
        "note": "联网文献腿：Crossref / OpenAlex 元数据检索结果（未做相关性判断）",
        "queries": res["queries"],
        "n_hits": res["n_unique"],
        "errors": res["errors"],
        "hits": res["records"],
    }, res


def main(argv):
    ap = argparse.ArgumentParser(prog="freeze_snapshot")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--input", default="", help="OBELiX CSV 路径（默认仓库内快照）")
    ap.add_argument("--literature", choices=("bootstrap", "network"),
                    default="bootstrap")
    ap.add_argument("--query", action="append", default=[],
                    help="联网模式的检索式（可重复；缺省按 goal 规则式拆词）")
    ap.add_argument("--sources", default="crossref,openalex")
    ap.add_argument("--rows", type=int, default=20, help="联网模式每个检索式条数")
    ap.add_argument("--ack", action="append", default=[],
                    help=f"显式确认异常码（可重复）：{', '.join(anomaly_mod.ANOMALY_CODES)}")
    ap.add_argument("--root", default="",
                    help="快照写入的根目录（默认仓库根；测试时可指向临时目录）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv[1:])

    repo_root = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".."))
    root = os.path.abspath(args.root) if args.root else repo_root
    src = args.input or os.path.join(repo_root, "data", "external", "obelix",
                                     "all.csv")

    # ---- 数据腿 ----
    rows, meta = sources.read_obelix(src)
    base = sources.summarize(rows)

    # ---- 文献腿（可选联网）----
    srcs = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    literature, search_res = build_literature(
        args.literature, args.goal, rows, args.query, args.rows, srcs)

    # ---- 判断（当前为规则式 bootstrap）----
    families = sorted({r["family"] for r in rows if r["family"]})
    judgments, scope = produce_judgments(args.goal, families)
    for r in rows:
        r["in_scope"] = scope.get(r["family"], "excluded")

    # ---- 双腿对接 + 异常检测（D7）----
    join = anomaly_mod.join_legs(literature.get("hits", []), rows)
    lr_for_rules = search_res or {"n_unique": len(literature.get("hits", [])),
                                  "errors": literature.get("errors", [])}
    anomalies = anomaly_mod.detect(lr_for_rules, join, judgments)
    pending = anomaly_mod.require_ack(anomalies, args.ack)
    if pending:
        print(anomaly_mod.format_report(anomalies, join))
        print(json.dumps({
            "ok": False, "stopped": True, "reason": "unacknowledged_anomalies",
            "anomalies": [a["code"] for a in pending],
            "ack_hint": [a["ack_hint"] for a in pending],
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 3

    # ---- 冻结 ----
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
        }] + ([{"name": "crossref", "url": "https://api.crossref.org"},
               {"name": "openalex", "url": "https://api.openalex.org"}]
              if args.literature == "network" else []),
        producer=PRODUCER,
        stats={
            "goal": args.goal,
            "judge_impl": JUDGE_IMPL,
            "literature_mode": args.literature,
            "n_rows": base["n_rows"],
            "value_status": base["value_status"],
            "family_empty": base["family_empty"],
            "n_families": len(families),
            "in_scope_families": sum(1 for v in scope.values() if v == "relevant"),
            "in_scope_rows": sum(1 for r in rows if r["in_scope"] == "relevant"),
            "judgments": len(judgments),
            "leg_join": {k: join[k] for k in
                         ("n_literature_dois", "n_data_dois", "n_matched",
                          "join_rate_of_literature", "join_rate_of_data",
                          "n_literature_supporting_info_dois")},
            "anomalies_detected": [a["code"] for a in anomalies],
            "anomalies_acknowledged": sorted(set(args.ack)),
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
