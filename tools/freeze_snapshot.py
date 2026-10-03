#!/usr/bin/env python3
"""freeze_snapshot.py — 冻结输入快照（redesign-decisions.md D6/D7）。

三段式流程（实现位于 ``core/paper_agent/freezing.py``，与本脚本共用同一份逻辑）：

    prepare  → 取两腿数据 + 落盘 pending（待判对象 + 规则式参考）
       ↓       会话里的大模型据此推理（或直接用规则式参考）
    commit   → 用裁决生成判断批次 → 异常检测 → 冻结快照

三种用法::

    # 1) 一步到位（规则式裁决，离线，默认）
    python tools/freeze_snapshot.py --goal "sulfide solid electrolyte ionic conductivity ranking"

    # 2) 联网文献腿
    python tools/freeze_snapshot.py --goal "..." --literature network --rows 25

    # 3) 配合模型裁决（AGH 会话内判断走这条）
    python tools/freeze_snapshot.py --goal "..." --prepare          # 输出待判对象
    #   …由模型推理出裁决 JSON（{"queries":[...],"families":{族:verdict}}）…
    python tools/freeze_snapshot.py --commit <pending_id> --verdicts verdicts.json \
        --judged-by model --model-name agnes-3.0-flash

异常驱动打断（D7）：检出未确认异常 → **不写快照**，返回退出码 3，
须人工复核后用 ``--ack <code>`` 显式确认（确认动作记入快照清单）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

from paper_agent import anomaly as anomaly_mod  # noqa: E402
from paper_agent import freezing  # noqa: E402
from paper_agent import litsearch  # noqa: E402


def _emit(obj: dict, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    return code


def main(argv):
    ap = argparse.ArgumentParser(prog="freeze_snapshot")
    ap.add_argument("--goal", default="")
    ap.add_argument("--input", default="", help="OBELiX CSV（默认仓库内快照）")
    ap.add_argument("--literature", choices=("bootstrap", "network"),
                    default="bootstrap")
    ap.add_argument("--query", action="append", default=[],
                    help="联网模式的检索式（可重复；缺省按 goal 规则式拆词）")
    ap.add_argument("--sources", default="crossref,openalex")
    ap.add_argument("--rows", type=int, default=20)
    ap.add_argument("--prepare", action="store_true",
                    help="只做 prepare：输出待判对象与规则式参考裁决")
    ap.add_argument("--commit", default="", metavar="PENDING_ID",
                    help="用裁决提交（配合 --verdicts）")
    ap.add_argument("--verdicts", default="",
                    help="裁决 JSON 文件：{\"queries\":[...],\"families\":{族:verdict}}")
    ap.add_argument("--judged-by", choices=("rule", "model"), default="model")
    ap.add_argument("--model-name", default="")
    ap.add_argument("--ack", action="append", default=[],
                    help=f"显式确认异常码（可重复）：{', '.join(anomaly_mod.ANOMALY_CODES)}")
    ap.add_argument("--root", default="", help="快照写入根目录（默认仓库根）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv[1:])

    repo = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".."))
    root = os.path.abspath(args.root) if args.root else repo
    srcs = tuple(s.strip() for s in args.sources.split(",") if s.strip())

    from paper_agent import sources as sources_mod
    try:
        return _dispatch(args, root, srcs)
    except sources_mod.SchemaError as e:
        return _emit({"ok": False, "cmd": "freeze",
                      "reason": "input_schema_mismatch", "error": str(e)}, 2)
    except freezing.FreezeError as e:
        return _emit({"ok": False, "cmd": "freeze",
                      "reason": "freeze_error", "error": str(e)}, 2)


def _dispatch(args, root: str, srcs: tuple) -> int:
    # ---- commit 模式 ----
    if args.commit:
        if not args.verdicts:
            return _emit({"ok": False,
                          "error": "--commit requires --verdicts"}, 2)
        with open(args.verdicts, "r", encoding="utf-8") as f:
            spec = json.load(f)
        raw = json.dumps(spec, ensure_ascii=False) if args.judged_by == "model" else ""
        out = freezing.commit(root, args.commit, spec,
                              judged_by=args.judged_by,
                              model_name=args.model_name, raw_response=raw,
                              ack=args.ack)
        if out.get("stopped"):
            print(out.pop("report", ""))
            out["ack_hint"] = [f"--ack {c}" for c in out.get("anomalies", [])]
            return _emit(out, 3)
        return _emit(out, 0 if out.get("ok") else 1)

    # ---- prepare 模式 ----
    if args.prepare:
        if not args.goal:
            return _emit({"ok": False, "error": "--prepare requires --goal"}, 2)
        prep = freezing.prepare(root, args.goal, args.input, args.literature,
                                args.query, args.rows, srcs)
        return _emit({
            "ok": True,
            "pending_id": prep["pending_id"],
            "pending_path": prep["pending_path"],
            "goal": prep["goal"],
            "literature_mode": prep["literature_mode"],
            "n_families": prep["n_families"],
            "families": prep["families"],
            "rule_queries": prep["rule_queries"],
            "rule_scope": prep["rule_scope"],
            "n_literature_hits": prep["n_literature_hits"],
            "literature_errors": prep["literature_errors"],
            "data_summary": prep["data_summary"],
            "next": ("产出裁决 JSON（{\"queries\":[...],\"families\":{族:verdict}}）后："
                     f"--commit {prep['pending_id']} --verdicts <file> --judged-by model"),
        })

    # ---- 一步到位（规则式）----
    if not args.goal:
        return _emit({"ok": False,
                      "error": "need --goal (or use --prepare / --commit)"}, 2)
    out = freezing.freeze_rule_based(root, args.goal, args.input,
                                     args.literature, args.query, args.rows,
                                     srcs, args.ack)
    if out.get("stopped"):
        print(out.pop("report", ""))
        out["ack_hint"] = [f"--ack {c}" for c in out.get("anomalies", [])]
        return _emit(out, 3)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    return _emit(out, 0 if out.get("ok") else 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
