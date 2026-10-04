#!/usr/bin/env python3
"""compare_judges.py — 反判据：模型判断是否真的改变结果（redesign 判据 2 的反面）。

把规则式基线与模型判断在同一目标上跑一遍，对比两个可观测面：
**生成的检索式** 与 **判定出的研究范围**。

判定：
- 两者完全一致 → ``model_is_decoration``（**退出码 5**，可接进 CI 当失败处理）
- 任一不同     → ``model_matters``（退出码 0）

模型客户端来源（按顺序尝试）：
1. ``--responses <json>``：注入预设响应（离线演示与回归用，无需模型）
2. ``--judge-b rule``：与规则式自比（自检，必然 decoration）
3. 环境变量 ``PAPER_AGENT_LLM_BASE_URL`` / ``_MODEL`` / ``_API_KEY``
   （标准 OpenAI 兼容端点；见 core/paper_agent/llm.py 顶部关于 AGH 的实测说明）

用法::

    python tools/compare_judges.py --goal "sulfide solid electrolyte ionic conductivity"
    python tools/compare_judges.py --goal "..." --responses /tmp/model_responses.json
    python tools/compare_judges.py --goal "..." --judge-b rule      # 自检

``--responses`` 文件格式::

    {"queries": ["sulfide solid electrolyte ionic conductivity"],
     "families": {"LGPS": "relevant", "NASITON": "excluded"}}
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

from paper_agent import judge as judge_mod  # noqa: E402
from paper_agent import llm as llm_mod  # noqa: E402
from paper_agent import sources  # noqa: E402


def client_from_responses(path: str):
    """用预设响应构造假客户端：按 prompt 内容分流（检索式 / 相关性）。"""
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    queries = spec.get("queries") or []
    fam_verdicts = spec.get("families") or {}

    def fn(prompt: str) -> str:
        if "检索式" in prompt:
            return json.dumps(queries, ensure_ascii=False)
        # 相关性 prompt：把出现的族逐个给出裁决，未指定的一律 excluded
        out = []
        for line in prompt.splitlines():
            line = line.strip()
            if line.startswith("- "):
                fam = line[2:].strip()
                key = "" if fam == "(empty)" else fam
                out.append({"family": fam,
                            "verdict": fam_verdicts.get(key, "excluded"),
                            "reason": f"预设响应：{fam_verdicts.get(key, 'excluded')}"})
        return json.dumps(out, ensure_ascii=False)

    return llm_mod.CallableClient(fn, name="preset-responses")


def main(argv):
    ap = argparse.ArgumentParser(prog="compare_judges")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--input", default="", help="OBELiX CSV（默认仓库内快照）")
    ap.add_argument("--judge-b", choices=("model", "rule"), default="model")
    ap.add_argument("--responses", default="", help="预设模型响应 JSON（离线）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv[1:])

    repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    src = args.input or os.path.join(repo, "data", "external", "obelix", "all.csv")
    rows, _ = sources.read_obelix(src)
    families = sorted({r["family"] for r in rows if r["family"]})

    judge_a = judge_mod.RuleJudge()

    if args.judge_b == "rule":
        judge_b, label_b = judge_mod.RuleJudge(), "rule(自检)"
    elif args.responses:
        client = client_from_responses(args.responses)
        judge_b, label_b = judge_mod.ModelJudge(client, model_name="preset"), "model(预设)"
    else:
        client = llm_mod.auto_client()
        if client is None:
            print(json.dumps({
                "ok": False,
                "reason": "no_model_client",
                "hint": ("设置 PAPER_AGENT_LLM_BASE_URL / PAPER_AGENT_LLM_MODEL "
                         "指向 OpenAI 兼容端点，或用 --responses 提供预设响应跑离线对比"),
                "env_expected": [llm_mod.ENV_BASE_URL, llm_mod.ENV_MODEL,
                                 llm_mod.ENV_API_KEY],
            }, ensure_ascii=False, indent=2, sort_keys=True))
            return 4
        judge_b, label_b = judge_mod.ModelJudge(client, model_name=client.name), "model"

    try:
        out = judge_mod.compare_judges(args.goal, families,
                                       judge_a, judge_b, "rule", label_b)
    except judge_mod.JudgeError as e:
        print(json.dumps({"ok": False, "reason": "judge_error", "error": str(e)},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 6

    out["ok"] = True
    out["n_families"] = len(families)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    print("=" * 68)
    print(f"反判据对比：规则式基线 vs {label_b}")
    print("=" * 68)
    print(f"目标：{args.goal}")
    print(f"待判对象：{len(families)} 个化学族")
    print(f"\n生成检索式：")
    print(f"  rule : {out['a']['queries']}")
    print(f"  {label_b:5s}: {out['b']['queries']}")
    print(f"  一致：{out['queries_identical']}")
    print(f"\n判定范围：rule 相关 {out['a']['n_relevant']} 个，"
          f"{label_b} 相关 {out['b']['n_relevant']} 个，"
          f"裁决不同 {out['n_flips']} 个")
    for f in out["flips"][:10]:
        print(f"    {f['family'] or '(empty)':28s} "
              f"{out['labels']['a']}={f['a']:9s} → {out['labels']['b']}={f['b']}")
    if out["n_flips"] > 10:
        print(f"    …（共 {out['n_flips']} 项不同，完整清单见 --json-out）")
    print(f"\n判定：{out['verdict']}")
    if out["model_changes_outcome"]:
        print("  模型判断确实改变了分析范围/检索式 —— 模型不是装饰品。")
    else:
        print("  ⚠ 换回固定规则后结论不变 —— 按反判据，模型是装饰品，本次改造未达标。")
    return 0 if out["model_changes_outcome"] else 5


if __name__ == "__main__":
    sys.exit(main(sys.argv))
