"""cli.py — 命令行统一入口（文档 §4.7）。

子命令:
  plan --goal "..." [--chaos MODE]
  status --run RUN_ID [--chaos MODE]
  run-step --run RUN_ID --step SID [--chaos MODE]
  run-all --run RUN_ID [--chaos MODE]
  resume --run RUN_ID [--chaos MODE]
  verify --run RUN_ID [--chaos MODE]
  report --run RUN_ID [--chaos MODE]
  cite --run RUN_ID [--ev EV-XXXX] [--chaos MODE]

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

from . import PAPER_AGENT_ROOT, DATA_DIR
from .state import (
    PipelineState, StepStatus, RunStatus,
    create_state, load_state, new_run_id, STEP_IDS,
)
from .steps import Pipeline
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

    p = mk("status")
    p.add_argument("--run", required=True)

    p = mk("run-step")
    p.add_argument("--run", required=True)
    p.add_argument("--step", required=True)

    p = mk("run-all")
    p.add_argument("--run", default="", help="existing run_id; omit to plan a new one")
    p.add_argument("--goal", default="", help="required when --run omitted")

    p = mk("resume")
    p.add_argument("--run", required=True)

    p = mk("verify")
    p.add_argument("--run", required=True)

    p = mk("report")
    p.add_argument("--run", required=True)

    p = mk("cite")
    p.add_argument("--run", required=True)
    p.add_argument("--ev", default="", help="EV-XXXX; omit to list all evidence")

    return ap


def _root() -> str:
    return os.environ.get("paper-agent_ROOT") or PAPER_AGENT_ROOT


# ---------- handlers ----------

def cmd_plan(args) -> int:
    rid = new_run_id()
    st = create_state(rid, _root(), args.goal)
    return _emit({"ok": True, "cmd": "plan", "run_id": rid,
                  "run_status": st.run_status.value,
                  "steps": {s: st.step_status[s].value for s in STEP_IDS}})


def cmd_status(args) -> int:
    st = load_state(args.run, _root())
    return _emit({"ok": True, "cmd": "status", "run_id": st.run_id,
                  "run_status": st.run_status.value,
                  "steps": {s: st.step_status[s].value for s in STEP_IDS},
                  "attempts": st.attempts, "degraded": st.degraded})


def _pipeline(run_id: str, chaos_mode: str) -> Pipeline:
    return Pipeline(_root(), run_id, chaos_mode=chaos_mode)


def cmd_run_step(args) -> int:
    pipe = _pipeline(args.run, args.chaos)
    res = pipe.run_step(args.step)
    res["ok"] = not res.get("failed", False)
    res["cmd"] = "run-step"
    res["run_id"] = args.run
    code = 0 if res["ok"] else 1
    return _emit_fail(res, code) if code else _emit(res)


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
        out = run_pipeline(root, args.goal, chaos_mode=args.chaos)
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
    res = pipe.run_p4()
    res["cmd"] = "verify"
    res["run_id"] = args.run
    res["ok"] = res.get("status") == "PASS"
    code = 0 if res["ok"] else 1
    return _emit_fail(res, code) if code else _emit(res)


def cmd_report(args) -> int:
    pipe = _pipeline(args.run, args.chaos)
    res = pipe.run_p5()
    res["cmd"] = "report"
    res["run_id"] = args.run
    res["ok"] = "report" in res
    code = 0 if res["ok"] else 1
    return _emit_fail(res, code) if code else _emit(res)


def cmd_cite(args) -> int:
    from .provenance import ProvenanceLedger
    run_dir = os.path.join(_root(), "runs", args.run)
    prov = ProvenanceLedger(run_dir, args.run)
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
    "run-all": cmd_run_all,
    "resume": cmd_resume,
    "verify": cmd_verify,
    "report": cmd_report,
    "cite": cmd_cite,
}


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
