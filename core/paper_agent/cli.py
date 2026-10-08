"""cli.py — 命令行统一入口（文档 §4.7）。

**主导路径（AGH 会话内）**：由大模型逐步驱动，Python 每次只执行一个步骤
  plan --goal "..." [--chaos MODE]
  next --run RUN_ID                  # 只读：看下一步候选
  step-driven --run ID --step SID    # ★ 执行单步 + 返回决策上下文
  finish --run RUN_ID                # 模型确认终态后收尾
  status --run RUN_ID

**确定性兜底路径（单测 / 离线演示）**：
  run-step --run RUN_ID --step SID
  run-all --run RUN_ID
  resume --run RUN_ID

**可信框架**：
  verify --run RUN_ID / report --run RUN_ID / cite --run RUN_ID [--ev EV-XXXX]

**证据查询层（Batch 4 / 只读）**：
  query [--kw KW] [--doi DOI] [--tier TIER] [--kind KIND] [--source SRC]
        [--run RUN_ID]... [--graph RUN_ID] [--aggregate] [--verify-all]

**环境自检（B2-0）**：
  doctor                             # 单行 JSON：Python/项目根/runs/环境变量/端口/AGH 线索

约定:
- stdout 严格只输出单个 JSON 对象（UTF-8）
- 业务异常 → 非 0 退出码
- 全局参数 --chaos 通过 argparse parents 继承到所有子命令
- 项目根路径由环境变量 paper-agent_ROOT 或自动探测
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import PAPER_AGENT_ROOT, DATA_DIR, _is_valid_root
from .state import (
    PipelineState, StepStatus, RunStatus,
    create_state, load_state, new_run_id, STEP_IDS,
    DEFAULT_WORKFLOW, WORKFLOWS,
)
from .steps import Pipeline, open_pipeline
from .chaos import clear_chaos_mode


def _ensure_utf8_stdio() -> None:
    """强制 stdout/stderr 为 UTF-8，避免重定向/管道时中文路径被系统码页编码污染。

    设计红线 #2/#3：CLI 的 stdout 必须是机器可解析的单 JSON 对象；
    中文 run 路径若按 cp936/GBK 输出，下游按 UTF-8 读会解码失败。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _emit(obj: dict) -> int:
    """stdout 只输出单个 JSON。返回 0。"""
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str))
    return 0


def _emit_fail(obj: dict, code: int) -> int:
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str))
    return code


def _add_global_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--chaos", default="", dest="chaos",
                  help="chaos mode: p1_fail_first|p1_fail_all|mutate_summary|""")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="paper_agent.cli", add_help=False)
    ap.add_argument("--help", action="help", help="show this help")

    sub = ap.add_subparsers(dest="cmd", required=True)

    def mk(name, **kw):
        p = sub.add_parser(name, **kw)
        _add_global_args(p)
        return p

    p = mk("plan")
    p.add_argument("--goal", required=True)
    p.add_argument("--workflow", default="", choices=["", "materials", "research"],
                   help="工作流：materials(默认，材料可复现实验) | research(科研全流程 P0-P2)")
    p.add_argument("--lit-source", default="", dest="lit_source",
                   choices=["", "local", "arxiv", "auto"],
                   help="P1 检索来源：local(离线) | arxiv(实时) | auto(先试 arxiv 再降级)")

    p = mk("status")
    p.add_argument("--run", required=True)

    p = mk("run-step")
    p.add_argument("--run", required=True)
    p.add_argument("--step", required=True)

    # 模型驱动路径：返回决策上下文（供 AGH 会话内大模型判断下一步）
    p = mk("step-driven")
    p.add_argument("--run", required=True)
    p.add_argument("--step", required=True)

    # 模型确认终态后收尾
    p = mk("finish")
    p.add_argument("--run", required=True)

    # 只读：查询下一步候选（不执行任何步骤）
    p = mk("next")
    p.add_argument("--run", required=True)

    p = mk("run-all")
    p.add_argument("--run", default="", help="existing run_id; omit to plan a new one")
    p.add_argument("--goal", default="", help="required when --run omitted")
    p.add_argument("--workflow", default="", choices=["", "materials", "research"],
                   help="新 run 的工作流：materials(默认) | research")
    p.add_argument("--lit-source", default="", dest="lit_source",
                   choices=["", "local", "arxiv", "auto"],
                   help="新 run 的 P1 检索来源：local | arxiv | auto")

    p = mk("resume")
    p.add_argument("--run", required=True)

    p = mk("verify")
    p.add_argument("--run", required=True)

    p = mk("report")
    p.add_argument("--run", required=True)

    p = mk("cite")
    p.add_argument("--run", required=True)
    p.add_argument("--ev", default="", help="EV-XXXX; omit to list all evidence")

    # 环境自检（B2-0）：stdout 输出单行 JSON，供 demo-kit/health-check.sh 复用，
    # 避免"自检逻辑散落 Bash 与 Python 两处"。
    mk("doctor")

    # 证据查询层（Batch 4 / B4-2）：跨 run 检索 / 引文图 / 聚合 / 全库链校验。
    # 实现真源在 query.py（纯只读，零依赖）；runs 目录默认 <root>/runs，
    # web 后端调用时显式钉死为本服务自己的 RUNS_DIR（防穿越）。
    p = mk("query")
    p.add_argument("--runs", default="", dest="runs_dir",
                   help="runs 目录（默认 <项目根>/runs）")
    p.add_argument("--kw", default="", help="关键词：命中 ev_id/ref/kind/producer_step/meta.title 等")
    p.add_argument("--doi", default="", help="DOI 精确匹配（ref 或 meta.doi）")
    p.add_argument("--tier", default="", help="fact | judgment（兼容旧记录默认 fact）")
    p.add_argument("--kind", default="", help="证据种类，如 literature/data/note")
    p.add_argument("--source", default="", help="检索来源（meta.sources 成员）")
    p.add_argument("--run", action="append", default=[], metavar="RUN_ID",
                   help="限定 run_id（可重复；--graph 时即目标 run）")
    p.add_argument("--graph", default="", metavar="RUN_ID",
                   help="输出该 run 的 结论-证据-文献 三层关系图")
    p.add_argument("--aggregate", action="store_true", help="跨 run 聚合")
    p.add_argument("--verify-all", action="store_true", dest="verify_all",
                   help="全库哈希链校验（复用 provenance.verify_chain）")
    p.add_argument("--limit", type=int, default=200, help="检索结果上限（默认 200）")

    # ---- 科研全流程单点工具（research 工作流的能力入口）----
    p = mk("search-papers")
    p.add_argument("--goal", required=True)
    p.add_argument("--sources", default="",
                   help="逗号分隔：arxiv,semantic_scholar,openalex,crossref；缺省全部")
    p.add_argument("--max", type=int, default=10, dest="max_results")
    p.add_argument("--local", action="store_true", help="改用内置语料（离线）")

    p = mk("parse-paper")
    p.add_argument("--source", required=True, help="本地 PDF 路径 / arXiv ID / DOI")
    p.add_argument("--allow-network", action="store_true", dest="allow_network")
    p.add_argument("--out-dir", default="", dest="out_dir")

    p = mk("analyze-paper")
    p.add_argument("--note", default="", help="精读笔记 json 路径")
    p.add_argument("--run", default="", help="从某 run 的已精读笔记批量分析")
    p.add_argument("--out-dir", default="", dest="out_dir")

    p = mk("verify-facts")
    p.add_argument("--run", default="")
    p.add_argument("--claims-file", default="", dest="claims_file")

    p = mk("write-review")
    p.add_argument("--topic", default="")
    p.add_argument("--run", default="")
    p.add_argument("--docs-file", default="", dest="docs_file")
    p.add_argument("--out-dir", default="", dest="out_dir")

    p = mk("self-review")
    p.add_argument("--run", default="")
    p.add_argument("--draft", default="")
    p.add_argument("--docs-file", default="", dest="docs_file")

    p = mk("eval")
    p.add_argument("--run", default="")
    p.add_argument("--out-dir", default="", dest="out_dir")

    # ---- 可信冻结快照（novus 增强，可插拔）----
    p = mk("freeze")
    p.add_argument("--goal", default="")
    p.add_argument("--input", default="", help="OBELiX CSV（默认仓库内快照）")
    p.add_argument("--literature", choices=("bootstrap", "network"),
                   default="bootstrap")
    p.add_argument("--query", action="append", default=[])
    p.add_argument("--sources", default="crossref,openalex")
    p.add_argument("--rows", type=int, default=20)
    p.add_argument("--prepare", action="store_true",
                   help="只输出待判对象与规则式参考裁决（不写快照）")
    p.add_argument("--commit", default="", metavar="PENDING_ID",
                   help="用裁决提交（配合 --verdicts）")
    p.add_argument("--verdicts", default="",
                   help='裁决 JSON：{"queries":[...],"families":{族:verdict}}')
    p.add_argument("--judged-by", choices=("rule", "model"), default="model")
    p.add_argument("--model-name", default="")
    p.add_argument("--ack", action="append", default=[])
    p.add_argument("--root", default="", help="快照写入根目录（默认项目根）")

    return ap


def _root() -> str:
    """解析项目根：override 仅在合法时采用，否则用（已回退的）PAPER_AGENT_ROOT。

    与 ``paper_agent._detect_root`` 同一口径，保证命令用的根**永远合法**；
    环境变量失效时不会把操作导向错误目录（只会在别处显式播报该问题）。
    """
    override = os.environ.get("paper-agent_ROOT")
    if override and _is_valid_root(override):
        return os.path.abspath(override)
    return PAPER_AGENT_ROOT


# ---------- handlers ----------

def cmd_plan(args) -> int:
    rid = new_run_id()
    st = create_state(rid, _root(), args.goal,
                      lit_source=(args.lit_source or None),
                      workflow=getattr(args, "workflow", "") or DEFAULT_WORKFLOW)
    return _emit({"ok": True, "cmd": "plan", "run_id": rid,
                  "run_status": st.run_status.value,
                  "workflow": st.workflow,
                  "lit_source": st.lit_source,
                  "steps": {s: st.step_status[s].value for s in st.step_ids}})


def cmd_status(args) -> int:
    st = load_state(args.run, _root())
    return _emit({"ok": True, "cmd": "status", "run_id": st.run_id,
                  "run_status": st.run_status.value,
                  "workflow": st.workflow,
                  "steps": {s: st.step_status[s].value for s in st.step_ids},
                  "attempts": st.attempts, "degraded": st.degraded})


def _pipeline(run_id: str, chaos_mode: str):
    """按 run 的 workflow 装配对应编排器（materials / research）。"""
    return open_pipeline(_root(), run_id, chaos_mode=chaos_mode)


def cmd_run_step(args) -> int:
    pipe = _pipeline(args.run, args.chaos)
    res = pipe.run_step(args.step)
    res["ok"] = not res.get("failed", False)
    res["cmd"] = "run-step"
    res["run_id"] = args.run
    code = 0 if res["ok"] else 1
    return _emit_fail(res, code) if code else _emit(res)


def cmd_step_driven(args) -> int:
    """模型驱动路径：执行单步并返回决策上下文。

    Python 不替模型决定下一步，只如实汇报结果 + 候选 + 需要模型判断的信号。
    """
    pipe = _pipeline(args.run, args.chaos)
    ctx = pipe.run_step_driven(args.step)
    ctx["ok"] = True
    ctx["cmd"] = "step-driven"
    ctx["run_id"] = args.run
    return _emit(ctx)


def cmd_next(args) -> int:
    """只读：返回当前 run 的下一步候选与状态摘要（不执行任何步骤）。"""
    pipe = _pipeline(args.run, args.chaos)
    st = pipe.state
    plan = st.pending_or_failed()
    ctx = {
        "ok": True,
        "cmd": "next",
        "run_id": args.run,
        "run_status": st.run_status.value,
        "workflow": st.workflow,
        "steps": {s: st.step_status[s].value for s in st.step_ids},
        "attempts": st.attempts,
        "degraded": st.degraded,
        "remaining_steps": plan,
        "next_tool_candidates": [f"sciret_run_step(step='{s}')" for s in plan],
    }
    return _emit(ctx)


def cmd_finish(args) -> int:
    """模型确认流水线已到终态后调用，收敛 run_status。"""
    pipe = _pipeline(args.run, args.chaos)
    out = pipe.finish_if_terminal()
    out["cmd"] = "finish"
    out["run_id"] = args.run
    out["ok"] = out.get("run_status") in ("DONE", "FAILED") and "error" not in out
    code = 0 if out["ok"] else 1
    return _emit_fail(out, code) if code else _emit(out)


def cmd_run_all(args) -> int:
    root = _root()
    if args.run:
        # resume 语义：复用已有 run
        pipe = _pipeline(args.run, args.chaos)
        out = pipe.run_all()
        out["run_id"] = args.run
    else:
        if not args.goal:
            return _emit_fail({"ok": False, "cmd": "run-all",
                               "error": "--goal required when --run omitted"}, 2)
        from .steps import run_pipeline
        out = run_pipeline(root, args.goal, chaos_mode=args.chaos,
                           lit_source=(args.lit_source or None),
                           workflow=getattr(args, "workflow", "") or DEFAULT_WORKFLOW)
    out["ok"] = out["run_status"] == "DONE"
    out["cmd"] = "run-all"
    code = 0 if out["ok"] else 1
    return _emit_fail(out, code) if code else _emit(out)


def cmd_resume(args) -> int:
    pipe = _pipeline(args.run, args.chaos)
    out = pipe.resume()
    out["ok"] = out["run_status"] == "DONE"
    out["cmd"] = "resume"
    out["run_id"] = args.run
    code = 0 if out["ok"] else 1
    return _emit_fail(out, code) if code else _emit(out)


def cmd_verify(args) -> int:
    pipe = _pipeline(args.run, args.chaos)
    if getattr(pipe.state, "workflow", "materials") == "research":
        res = pipe.run_r4()          # research：R4 事实验证
        res["status"] = "DONE"
        res["ok"] = True
    else:
        res = pipe.run_p4()          # materials：P4 复现验证
        res["ok"] = res.get("status") == "PASS"
    res["cmd"] = "verify"
    res["run_id"] = args.run
    code = 0 if res["ok"] else 1
    return _emit_fail(res, code) if code else _emit(res)


def cmd_report(args) -> int:
    pipe = _pipeline(args.run, args.chaos)
    if getattr(pipe.state, "workflow", "materials") == "research":
        res = {"report": pipe.run_report()}
    else:
        res = pipe.run_p5()
    res["cmd"] = "report"
    res["run_id"] = args.run
    res["ok"] = "report" in res
    code = 0 if res["ok"] else 1
    return _emit_fail(res, code) if code else _emit(res)


def cmd_cite(args) -> int:
    from .provenance import ProvenanceLedger
    run_dir = os.path.join(_root(), "runs", args.run)
    prov = ProvenanceLedger(run_dir, args.run, root=_root())
    if args.ev:
        text = prov.cite(args.ev)
        return _emit({"ok": True, "cmd": "cite", "ev": args.ev, "citation": text})
    listing = [
        {"ev": e["ev_id"], "kind": e["kind"], "ref": e["ref"],
         "sha16": (e.get("sha256") or "")[:16]}
        for e in prov.all_evidence()
    ]
    return _emit({"ok": True, "cmd": "cite", "run_id": args.run,
                  "evidence": listing})


_HANDLERS = {
    "plan": cmd_plan,
    "status": cmd_status,
    "run-step": cmd_run_step,
    "step-driven": cmd_step_driven,
    "next": cmd_next,
    "finish": cmd_finish,
    "run-all": cmd_run_all,
    "resume": cmd_resume,
    "verify": cmd_verify,
    "report": cmd_report,
    "cite": cmd_cite,
}


# ---------- 科研全流程单点工具（research）----------

def _read_json_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_file(path: str, obj) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return path


def cmd_search_papers(args) -> int:
    """统一多源检索（PRD F-1.1），不建 run，直接返回结果。"""
    from . import litsearch
    sources = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    if args.local:
        docs = litsearch.filter_by_relevance(
            litsearch.load_local_corpus(_root()), args.goal)
        return _emit({"ok": True, "cmd": "search-papers", "source": "local",
                      "query": args.goal, "n_documents": len(docs),
                      "documents": docs})
    res = litsearch.search_papers(args.goal, sources=sources,
                                  max_results=args.max_results)
    res.update({"ok": not res["degraded"], "cmd": "search-papers"})
    return _emit(res)


def cmd_parse_paper(args) -> int:
    """论文精读（PRD F-2.1）。"""
    from . import pdfparse
    note = pdfparse.parse_paper(args.source, allow_network=args.allow_network,
                               out_dir=(args.out_dir or None))
    out = dict(note)
    out.pop("text", None)   # stdout 不塞全文，保持精简
    out["text_chars"] = len(note.get("text") or "")
    if args.out_dir:
        _write_json_file(os.path.join(args.out_dir, "note.json"), note)
        md_path = os.path.join(args.out_dir, "note.md")
        os.makedirs(args.out_dir, exist_ok=True)
        with open(md_path, "w", encoding="utf-8", newline="") as f:
            f.write(pdfparse.render_note(note))
        out["note_json"] = os.path.join(args.out_dir, "note.json")
        out["note_md"] = md_path
    out.update({"ok": note.get("status") in ("ok", "scanned"), "cmd": "parse-paper"})
    return _emit(out)


def cmd_analyze_paper(args) -> int:
    """创新点拆解 / Gap（PRD F-3.x）。"""
    from . import analyze
    notes = []
    if args.run:
        notes_dir = os.path.join(_root(), "runs", args.run, "reading", "notes")
        if os.path.isdir(notes_dir):
            for fn in sorted(os.listdir(notes_dir)):
                if fn.endswith(".json"):
                    notes.append(_read_json_file(os.path.join(notes_dir, fn)))
    elif args.note:
        notes.append(_read_json_file(args.note))
    else:
        return _emit_fail({"ok": False, "cmd": "analyze-paper",
                          "error": "--note or --run required"}, 2)

    targets = [analyze.extract_innovations(n) for n in notes]
    gaps = analyze.research_gap(notes)
    result = {"ok": True, "cmd": "analyze-paper",
              "n_notes": len(notes),
              "n_innovations": sum(t["n_innovations"] for t in targets),
              "categories_summary": _merge_cats(targets),
              "targets": targets, "gaps": gaps}
    if args.out_dir:
        _write_json_file(os.path.join(args.out_dir, "innovations.json"),
                         {"targets": targets})
        _write_json_file(os.path.join(args.out_dir, "gaps.json"), gaps)
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "innovations.md"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("\n\n".join(analyze.render_innovation_md(t) for t in targets))
    return _emit(result)


def _merge_cats(targets: list[dict]) -> dict:
    out: dict[str, int] = {}
    for t in targets:
        for k, v in (t.get("categories_summary") or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def cmd_verify_facts(args) -> int:
    """事实验证（PRD F-4.x）。"""
    from . import factcheck
    if args.run:
        pipe = _pipeline(args.run, args.chaos)
        res = pipe.run_r4()
        res.update({"ok": True, "cmd": "verify-facts", "run_id": args.run})
        return _emit(res)
    if args.claims_file:
        claims = _read_json_file(args.claims_file)
        res = factcheck.verify_citations(claims)
        res.update({"ok": True, "cmd": "verify-facts"})
        return _emit(res)
    return _emit_fail({"ok": False, "cmd": "verify-facts",
                       "error": "--run or --claims-file required"}, 2)


def cmd_write_review(args) -> int:
    """综述写作（PRD F-5.1/F-5.3）。"""
    from . import writing
    if args.run:
        pipe = _pipeline(args.run, args.chaos)
        res = pipe.run_r5()
        res.update({"ok": True, "cmd": "write-review", "run_id": args.run})
        res.pop("ris", None)
        return _emit(res)
    if not (args.topic and args.docs_file):
        return _emit_fail({"ok": False, "cmd": "write-review",
                          "error": "--topic and --docs-file required without --run"}, 2)
    docs = _read_json_file(args.docs_file)
    if isinstance(docs, dict):
        docs = docs.get("hits") or docs.get("documents") or []
    rv = writing.generate_review(args.topic, docs)
    bib = writing.generate_bibtex(docs)
    out = {"ok": True, "cmd": "write-review", "topic": args.topic,
           "n_citations": rv["n_citations"], "unsupported": rv["unsupported"],
           "consistency": rv["consistency"], "bibtex_entries": bib["n_entries"],
           "review_markdown": rv["markdown"], "bibtex": bib["bibtex"]}
    if args.out_dir:
        _write_json_file(os.path.join(args.out_dir, "review.json"), rv)
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "review.md"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(rv["markdown"])
        with open(os.path.join(args.out_dir, "references.bib"), "w",
                  encoding="utf-8", newline="") as f:
            f.write(bib["bibtex"])
    return _emit(out)


def cmd_self_review(args) -> int:
    """模拟自评审（PRD F-6.1）。"""
    from . import review as review_mod
    if args.run:
        pipe = _pipeline(args.run, args.chaos)
        res = pipe.run_r6()
        res.update({"ok": True, "cmd": "self-review", "run_id": args.run})
        return _emit(res)
    if not (args.draft and args.docs_file):
        return _emit_fail({"ok": False, "cmd": "self-review",
                          "error": "--draft and --docs-file required without --run"}, 2)
    draft = open(args.draft, "r", encoding="utf-8").read()
    docs = _read_json_file(args.docs_file)
    if isinstance(docs, dict):
        docs = docs.get("hits") or docs.get("documents") or []
    loop = review_mod.review_loop(draft, docs, max_iters=3)
    out = dict(loop["final"])
    out.update({"ok": True, "cmd": "self-review", "history": loop["history"],
                "converged": loop["converged"]})
    return _emit(out)


def cmd_eval(args) -> int:
    """量化验证（PRD F-7.1~7.4）。"""
    from . import evaluate
    reports = evaluate.run_all(_root(), include_demo=True)
    out = {"ok": True, "cmd": "eval", "reports": reports}
    target = args.out_dir or ""
    if args.run:
        target = os.path.join(_root(), "runs", args.run, "evaluation")
    if target:
        os.makedirs(target, exist_ok=True)
        _write_json_file(os.path.join(target, "eval_report.json"), reports)
        md_path = os.path.join(target, "eval_report.md")
        with open(md_path, "w", encoding="utf-8", newline="") as f:
            f.write(evaluate.render_eval_md(reports))
        out["eval_json"] = os.path.join(target, "eval_report.json")
        out["eval_md"] = md_path
        if args.run:
            from .provenance import ProvenanceLedger
            prov = ProvenanceLedger(os.path.join(_root(), "runs", args.run), args.run, root=_root())
            prov.append_evidence(kind="evaluation",
                                 ref=os.path.join("evaluation", "eval_report.json"),
                                 producer_step="R6_review",
                                 file_path=os.path.join(target, "eval_report.json"),
                                 meta={"workflow": "research"})
    return _emit(out)


_HANDLERS["search-papers"] = cmd_search_papers
_HANDLERS["parse-paper"] = cmd_parse_paper
_HANDLERS["analyze-paper"] = cmd_analyze_paper
_HANDLERS["verify-facts"] = cmd_verify_facts
_HANDLERS["write-review"] = cmd_write_review
_HANDLERS["self-review"] = cmd_self_review
_HANDLERS["eval"] = cmd_eval


# ---------- 可信冻结快照（novus 增强，可插拔）----------

def cmd_freeze(args) -> int:
    """冻结输入快照：--prepare（待判对象）/ --commit（提交裁决）/ 缺省（规则式一步到位）。

    freezing / sources 惰性导入，避免未使用冻结能力时也强依赖其依赖链。
    """
    from . import freezing
    from . import sources as sources_mod
    root = os.path.abspath(args.root) if args.root else _root()
    srcs = tuple(s.strip() for s in args.sources.split(",") if s.strip())

    try:
        return _freeze_dispatch(args, root, srcs, freezing)
    except sources_mod.SchemaError as e:
        return _emit_fail({"ok": False, "cmd": "freeze",
                           "reason": "input_schema_mismatch",
                           "error": str(e)}, 2)
    except freezing.FreezeError as e:
        return _emit_fail({"ok": False, "cmd": "freeze",
                           "reason": "freeze_error", "error": str(e)}, 2)


def _freeze_dispatch(args, root: str, srcs: tuple, freezing) -> int:
    if args.commit:
        if not args.verdicts:
            return _emit_fail({"ok": False, "cmd": "freeze",
                               "error": "--commit requires --verdicts"}, 2)
        with open(args.verdicts, "r", encoding="utf-8") as f:
            spec = json.load(f)
        raw = (json.dumps(spec, ensure_ascii=False)
               if args.judged_by == "model" else "")
        out = freezing.commit(root, args.commit, spec,
                             judged_by=args.judged_by,
                             model_name=args.model_name, raw_response=raw,
                             ack=args.ack)
        out["cmd"] = "freeze"
        code = 3 if out.get("stopped") else (0 if out.get("ok") else 1)
        return _emit_fail(out, code) if code else _emit(out)

    if args.prepare:
        if not args.goal:
            return _emit_fail({"ok": False, "cmd": "freeze",
                               "error": "--prepare requires --goal"}, 2)
        prep = freezing.prepare(root, args.goal, args.input, args.literature,
                                args.query, args.rows, srcs)
        return _emit({
            "ok": True, "cmd": "freeze", "mode": "prepare",
            "pending_id": prep["pending_id"],
            "goal": prep["goal"],
            "literature_mode": prep["literature_mode"],
            "n_families": prep["n_families"],
            "families": prep["families"],
            "rule_queries": prep["rule_queries"],
            "rule_scope": prep["rule_scope"],
            "n_literature_hits": prep["n_literature_hits"],
            "literature_errors": prep["literature_errors"],
            "data_summary": prep["data_summary"],
        })

    if not args.goal:
        return _emit_fail({"ok": False, "cmd": "freeze",
                           "error": "--goal required (or use --prepare / --commit)"}, 2)
    out = freezing.freeze_rule_based(root, args.goal, args.input,
                                     args.literature, args.query, args.rows,
                                     srcs, args.ack)
    out["cmd"] = "freeze"
    code = 3 if out.get("stopped") else (0 if out.get("ok") else 1)
    return _emit_fail(out, code) if code else _emit(out)


_HANDLERS["freeze"] = cmd_freeze


# ---------- doctor：环境自检（B2-0，供 demo-kit/health-check.sh 复用）----------
#
# 设计：一次把"环境体检"跑完，输出**单行 JSON**；每项失败都带 human-readable
# 的 fix 字段（人话修复指引）。health-check.sh 直接解析本输出做展示，避免自检
# 逻辑在 Bash 与 Python 两处各写一份而漂移。退出码：0=健康 / 2=有警告 / 1=阻断。

_PY_MIN = (3, 10)


def _port_in_use(port: int) -> bool:
    """本机 127.0.0.1:<port> 是否已被占用（纯 stdlib，跨平台，不依赖 netstat/lsof）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return False          # bind 成功 → 端口空闲
    except OSError:
        return True           # bind 失败 → 已被占用
    finally:
        try:
            s.close()
        except OSError:
            pass


def _find_agh_entry(root: str) -> str:
    """探测 AGH 入口 agnes.mjs（只做线索发现，不保证可用；找不到返回 ""）。"""
    cands = []
    env = os.environ.get("AGH_ENTRY")
    if env:
        cands.append(env)
    bases = [
        os.path.join(root, os.pardir, "agnes-harness"),
        os.path.join(os.path.expanduser("~"), "agnes-harness"),
        os.path.join(os.path.expanduser("~"), "agnes-harness-main"),
        "/c/agnes-harness-main", "/d/agnes-harness-main",
    ]
    cands += [os.path.join(b, "packages", "cli", "dist", "local", "agnes.mjs") for b in bases]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    # 兜底：构建产物目录名可能是 local / local-dev-verify / 其它 → 直接 glob dist/*/agnes.mjs
    import glob
    for b in bases:
        for hit in sorted(glob.glob(os.path.join(b, "packages", "cli", "dist", "*", "agnes.mjs"))):
            if os.path.isfile(hit):
                return os.path.abspath(hit)
    return ""


def _has_agh_audit() -> bool:
    """是否已存在 AGH 安装审计日志（plugin 曾装过的线索）。"""
    import glob
    pat = os.path.join(os.path.expanduser("~"), ".agh", "profiles", "*",
                       ".agnes-package-audit.jsonl")
    return bool(glob.glob(pat))


def _runs_status(root: str) -> dict:
    """检查 runs/ 是否存在、是否可写（真写一个探针文件再删）。"""
    runs = os.path.join(root, "runs")
    info = {"dir": runs, "exists": os.path.isdir(runs), "writable": False}
    try:
        os.makedirs(runs, exist_ok=True)
        probe = os.path.join(runs, ".doctor-write-probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        info["writable"] = True
    except OSError:
        info["writable"] = False
    return info


def cmd_doctor(args) -> int:
    """环境自检（B2-0）：Python / 项目根 / runs 可写 / 环境变量 / 端口 / AGH 线索。

    stdout 只输出单个 JSON 对象（沿用 CLI 约定）。退出码 0=健康 / 2=有警告 / 1=阻断。
    """
    root = _root()
    fails = 0
    warns = 0
    hints: list[str] = []

    # 1) Python 解释器（>= 3.10）
    ver = "%d.%d.%d" % sys.version_info[:3]
    py_ok = sys.version_info >= _PY_MIN
    python_ck = {
        "value": ver, "path": sys.executable, "need": ">=%d.%d" % _PY_MIN, "ok": py_ok,
        "fix": "" if py_ok else
        ("需 Python >= %d.%d（当前 %s）。安装后设 paper-agent_PYTHON=<python 绝对路径>，"
         "并在启动 daemon 的终端里重启 daemon。" % (_PY_MIN + (ver,))),
    }
    if not py_ok:
        fails += 1
        hints.append(python_ck["fix"])

    # 2) 项目根（存在 + 含 core/paper_agent）
    root_ok = _is_valid_root(root)
    root_ck = {
        "value": root, "marker": os.path.join("core", "paper_agent"), "ok": root_ok,
        "fix": "" if root_ok else
        ("项目根非法：该目录下应存在 core/paper_agent/。若用 paper-agent_ROOT 指定，"
         "请改指真正的仓库根后重启 daemon。"),
    }
    if not root_ok:
        fails += 1
        hints.append(root_ck["fix"])

    # 3) runs/ 可写
    rs = _runs_status(root)
    runs_ok = bool(rs["writable"])
    runs_ck = {
        "dir": rs["dir"], "exists": rs["exists"], "writable": rs["writable"], "ok": runs_ok,
        "fix": "" if runs_ok else
        "runs/ 不可写：检查目录权限，或把 paper-agent_ROOT 指向有写权限的仓库根。",
    }
    if not runs_ok:
        fails += 1
        hints.append(runs_ck["fix"])

    # 4) 环境变量契约（本进程实际看到的值）
    raw_root = os.environ.get("paper-agent_ROOT", "")
    raw_py = os.environ.get("paper-agent_PYTHON", "")
    root_var_valid = (raw_root == "") or _is_valid_root(raw_root)
    env_ck = {
        "paper-agent_ROOT": {"set": bool(raw_root), "value": raw_root,
                             "valid": root_var_valid},
        "paper-agent_PYTHON": {"set": bool(raw_py), "value": raw_py},
        "ok": root_var_valid,
        "fix": "" if root_var_valid else
        ('paper-agent_ROOT 指向非法目录：请在启动 daemon 的终端里重新注入正确路径'
         '（env "paper-agent_ROOT=<仓库绝对路径>" ...）后重启 daemon。'),
    }
    if not root_var_valid:
        warns += 1
        hints.append(env_ck["fix"])

    # 5) 端口 8787 / 5173（占用属警告，可顺延，不阻断）
    ports_detail = {}
    ports_ok = True
    for port in (8787, 5173):
        free = not _port_in_use(port)
        ports_detail[str(port)] = {"free": free}
        if not free:
            ports_ok = False
    ports_ck = {
        "checked": [8787, 5173], "detail": ports_detail, "ok": ports_ok,
        "fix": "" if ports_ok else
        "端口被占用：Git Bash 下 taskkill //PID <pid> //F，或设 PORT 顺延到空闲端口。",
    }
    if not ports_ok:
        warns += 1
        hints.append(ports_ck["fix"])

    # 6) AGH 插件线索（可选；缺失降级为警告，不让 demo-kit 强依赖 AGH）
    agh_entry = _find_agh_entry(root)
    agh_ck = {
        "entry": agh_entry, "audit_log": _has_agh_audit(), "optional": True,
        "ok": bool(agh_entry),
        "fix": "" if agh_entry else
        "未检测到 AGH（可选）：demo-kit 不依赖 AGH；如需集成见 docs/AGH插件安装指南.md。",
    }
    if not agh_entry:
        warns += 1

    level = "fail" if fails else ("warn" if warns else "ok")
    code = 1 if fails else (2 if warns else 0)
    out = {
        "ok": fails == 0, "cmd": "doctor", "level": level,
        "python": python_ck, "project_root": root_ck, "runs": runs_ck,
        "env": env_ck, "ports": ports_ck, "agh": agh_ck,
        "summary": {"fail": fails, "warn": warns, "level": level},
        "hints": hints,
    }
    return _emit_fail(out, code)


_HANDLERS["doctor"] = cmd_doctor


# ---------- query：证据查询层（Batch 4 / B4-2）----------

def cmd_query(args) -> int:
    """证据查询（只读）。模式：search（默认）/ --graph / --aggregate / --verify-all。

    退出码：0=正常（verify-all 全通过）；1=verify-all 检出坏链；
    2=参数非法（如 run_id 穿越企图）。
    """
    from . import query as query_mod
    runs_dir = (os.path.abspath(args.runs_dir) if args.runs_dir
                else os.path.join(_root(), "runs"))
    try:
        if args.graph:
            g = query_mod.citation_graph(runs_dir, args.graph)
            g.update({"ok": True, "cmd": "query", "mode": "graph"})
            return _emit(g)
        if args.aggregate:
            agg = query_mod.aggregate_runs(runs_dir)
            agg.update({"ok": True, "cmd": "query", "mode": "aggregate"})
            return _emit(agg)
        if args.verify_all:
            v = query_mod.verify_all_chains(runs_dir, run_ids=args.run or None)
            v["cmd"] = "query"
            v["mode"] = "verify-all"
            code = 0 if v.get("ok") else 1
            return _emit_fail(v, code) if code else _emit(v)
        items = query_mod.query_runs(
            runs_dir, kw=(args.kw or None), doi=(args.doi or None),
            tier=(args.tier or None), kind=(args.kind or None),
            source=(args.source or None), run_ids=(args.run or None),
            limit=args.limit)
        return _emit({"ok": True, "cmd": "query", "mode": "search",
                      "runs_dir": runs_dir, "count": len(items),
                      "items": items})
    except query_mod.QueryError as e:
        return _emit_fail({"ok": False, "cmd": "query", "error": str(e)}, 2)


_HANDLERS["query"] = cmd_query


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.chaos:
        from .chaos import set_chaos_mode
        set_chaos_mode(args.chaos)
    try:
        return _HANDLERS[args.cmd](args)
    except KeyError as e:
        return _emit_fail({"ok": False, "error": f"unknown step: {e}"}, 2)
    except Exception as e:  # 业务异常 → 非 0 退出码
        return _emit_fail({"ok": False, "cmd": args.cmd,
                          "error": f"{type(e).__name__}: {e}"}, 1)
    finally:
        clear_chaos_mode()


if __name__ == "__main__":
    sys.exit(main())
