"""steps.py — 五步流水线调度（文档 §4.5 + §4.6 + §4.7）。

分层解耦：本模块是 L2 Harness 之上的科研编排层，
- 仅通过 subprocess 调用实验脚本（L1 工具执行层），不 import 工具内部
- 通过状态机接口转移状态，证据账本落证，事件账本留痕
- 工具调用原始入参出参落盘 runs/<run_id>/toolcalls/<HHMMSS>_<step>.json
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

from .state import (
    PipelineState, StepStatus, RunStatus, create_state, load_state, new_run_id,
)
from .provenance import ProvenanceLedger
from . import chaos
from .chaos import TransientError
from . import verify as verify_mod

MAX_ATTEMPTS = 3
BACKOFF = [1, 2]  # seconds
P3_TIMEOUT = 60

# P1 停用词（小写）
_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to",
         "is", "are", "with", "as", "at", "by", "from", "it", "its"}


def _now_hhmmss() -> str:
    return time.strftime("%H%M%S", time.gmtime())


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if t not in _STOP]


class Pipeline:
    """一次 run 的流水线编排器。"""

    def __init__(self, root: str, run_id: str, chaos_mode: str = ""):
        self.root = root
        self.run_id = run_id
        self.state = load_state(run_id, root)
        self.prov = ProvenanceLedger(os.path.join(root, "runs", run_id), run_id)
        if chaos_mode:
            chaos.set_chaos_mode(chaos_mode)

    # ---------- 工具调用留痕 ----------

    def _toolcall(self, step: str, fn: str, input_obj: dict, output_obj: dict) -> None:
        tc_dir = os.path.join(self.root, "runs", self.run_id, "toolcalls")
        os.makedirs(tc_dir, exist_ok=True)
        stamp = _now_hhmmss()
        # 同一秒多次调用则递增后缀，避免覆盖
        base = f"{stamp}_{step}"
        path = os.path.join(tc_dir, f"{base}.json")
        i = 2
        while os.path.exists(path):
            path = os.path.join(tc_dir, f"{base}_{i}.json")
            i += 1
        _write_json(path, {
            "step": step,
            "tool": fn,
            "invoked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "input": input_obj,
            "output": output_obj,
        })
        return path

    # ---------- P1 文献检索 ----------

    def _p1_search(self, goal: str, full_corpus: bool) -> dict:
        lit_path = os.path.join(self.root, "data", "literature.json")
        with open(lit_path, "r", encoding="utf-8") as f:
            corpus = json.load(f)
        docs = corpus.get("documents", [])
        if full_corpus:
            hits = [d for d in docs]
        else:
            toks = _tokenize(goal)
            scored = []
            for d in docs:
                hay = " ".join(
                    [d.get("title", "")] + d.get("keywords", [])
                    + [d.get("abstract", ""), d.get("venue", "")]
                ).lower()
                score = sum(1 for t in set(toks) if t in hay)
                if score > 0:
                    scored.append((score, d))
            # 排序 key (-score, doc_id)
            scored.sort(key=lambda x: (-x[0], x[1]["doc_id"]))
            hits = [d for _, d in scored]

        out_path = os.path.join(self.root, "runs", self.run_id, "literature",
                                "literature_hits.json")
        _write_json(out_path, {
            "goal": goal,
            "n_hits": len(hits),
            "degraded": full_corpus,
            "hits": [
                {"doc_id": d["doc_id"], "doi": d["doi"], "title": d["title"],
                 "venue": d["venue"], "year": d["year"],
                 "matched": full_corpus}
                for d in hits
            ],
        })
        # 登记 literature 证据（ref=DOI）
        ev_ids = []
        for d in hits:
            ev = self.prov.append_evidence(
                kind="literature", ref=d["doi"],
                producer_step="P1_lit_search",
                meta={"doc_id": d["doc_id"], "title": d.get("title", ""),
                      "year": d.get("year")},
            )
            ev_ids.append(ev)
        # 无论 0 命中与否，始终登记检索输出文件为 data 证据，
        # 作为 C1 结论的证据锚点（证据先行：0 命中也留证）。
        hits_file_ev = self.prov.append_evidence(
            kind="data",
            ref=os.path.join("literature", "literature_hits.json"),
            producer_step="P1_lit_search",
            file_path=out_path,
            meta={"n_hits": len(hits), "degraded": full_corpus},
        )
        return {"n_hits": len(hits), "degraded": full_corpus,
                "output": out_path, "evidence": ev_ids,
                "hits_file_ev": hits_file_ev}

    def run_p1(self) -> dict:
        sid = "P1_lit_search"
        goal = self.state.goal
        self.state.mark_step_running(sid)
        result = None
        attempt = 1
        degraded = False
        while True:
            try:
                chaos.CH.p1_maybe_raise(attempt)
                result = self._p1_search(goal, full_corpus=False)
                break
            except TransientError as e:
                if attempt >= MAX_ATTEMPTS:
                    # P1 重试耗尽 → 降级：返回全部本地语料；记录 degrade 事件
                    degraded = True
                    self.state.mark_degraded(
                        sid, note=f"exhausted {attempt} attempts: {e}")
                    result = self._p1_search(goal, full_corpus=True)
                    break
                self.state.retry_attempt(sid, str(e))
                attempt += 1
                time.sleep(BACKOFF[min(attempt - 2, len(BACKOFF) - 1)])
        self._toolcall("P1_lit_search", "sciret_run_step",
                       {"goal": goal, "attempt": attempt, "degraded": degraded},
                       {"n_hits": result["n_hits"]})
        self.state.mark_step_done(sid, {"n_hits": result["n_hits"],
                                        "degraded": degraded})
        return result

    # ---------- P2 数据清洗 ----------

    def run_p2(self) -> dict:
        sid = "P2_clean_data"
        self.state.mark_step_running(sid)
        raw_path = os.path.join(self.root, "data", "conductivity_raw.csv")
        with open(raw_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        in_n = len(rows)

        actions: list[dict] = []

        # 1) 精确字符串去重（整行完全一致）
        seen: set[tuple] = set()
        dedup: list[dict] = []
        for r in rows:
            key = tuple((k, (v or "").strip()) for k, v in r.items())
            if key in seen:
                actions.append({"action": "dedup", "material_id": r.get("material_id"),
                                "note": "exact duplicate row removed"})
                continue
            seen.add(key)
            dedup.append({k: (v or "").strip() for k, v in r.items()})

        # 2) 单位归一 mS/cm -> S/cm
        for r in dedup:
            unit = r.get("unit_raw", "").lower()
            raw = r.get("conductivity_raw", "")
            try:
                val = float(raw)
            except ValueError:
                val = float("nan")
            if unit == "ms/cm":
                s_cm = val / 1000.0
                r["conductivity_Scm"] = f"{s_cm:.6e}"
                actions.append({"action": "unit_normalize",
                                "material_id": r.get("material_id"),
                                "from": raw, "unit": unit,
                                "to_s_cm": f"{s_cm:.6e}"})
            elif unit == "s/cm":
                r["conductivity_Scm"] = f"{val:.6e}"
            else:
                r["conductivity_Scm"] = ""

        # 3) activation_energy_eV 缺失 → 按 family 中位数插补
        fam_vals: dict[str, list[float]] = {}
        for r in dedup:
            fam = r.get("family", "")
            aev = r.get("activation_energy_eV", "")
            try:
                fam_vals.setdefault(fam, []).append(float(aev))
            except ValueError:
                pass
        fam_med = {k: statistics.median(v) for k, v in fam_vals.items()}
        for r in dedup:
            fam = r.get("family", "")
            aev = r.get("activation_energy_eV", "")
            try:
                float(aev)
            except ValueError:
                median = fam_med.get(fam)
                if median is not None:
                    r["activation_energy_eV"] = f"{median:.4f}"
                    actions.append({"action": "impute_median",
                                    "material_id": r.get("material_id"),
                                    "family": fam, "value": f"{median:.4f}"})
                else:
                    r["activation_energy_eV"] = ""

        # 过滤出有效行（有 conductivity_Scm 数值）
        out_rows = [r for r in dedup if r.get("conductivity_Scm", "").strip()]
        clean_fields = ["material_id", "formula", "family", "conductivity_Scm",
                        "activation_energy_eV", "year", "source_doi", "notes"]
        clean_path = os.path.join(self.root, "runs", self.run_id, "clean",
                                  "conductivity_clean.csv")
        clean_rows = [{k: r.get(k, "") for k in clean_fields} for r in out_rows]
        _write_csv(clean_path, clean_fields, clean_rows)

        report = {
            "input_rows": in_n,
            "output_rows": len(clean_rows),
            "actions": actions,
            "unit_map": {"mS/cm": "S/cm / 1000", "S/cm": "S/cm"},
        }
        rep_path = os.path.join(self.root, "runs", self.run_id, "clean",
                                "cleaning_report.json")
        _write_json(rep_path, report)

        ev_data = self.prov.append_evidence(
            kind="data", ref=clean_path, producer_step="P2_clean_data",
            file_path=clean_path,
            meta={"input_rows": in_n, "output_rows": len(clean_rows)},
        )
        ev_rep = self.prov.append_evidence(
            kind="data", ref=rep_path, producer_step="P2_clean_data",
            file_path=rep_path, meta={"action_count": len(actions)},
        )
        self._toolcall("P2_clean_data", "sciret_run_step",
                       {"input": raw_path, "output_rows": len(clean_rows)},
                       {"clean": clean_path, "report": rep_path})
        self.state.mark_step_done(sid, {"output_rows": len(clean_rows),
                                        "actions": len(actions)})
        return {"clean": clean_path, "report": rep_path,
                "input_rows": in_n, "output_rows": len(clean_rows),
                "evidence": [ev_data, ev_rep]}

    # ---------- P3 实验子进程 ----------

    def _spawn_experiment(self, input_csv: str, outdir: str, extra_env: dict | None = None) -> int:
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        script = os.path.join(self.root, "experiments", "arrhenius_rank.py")
        proc = subprocess.run(
            [sys.executable, script, "--input", input_csv,
             "--outdir", outdir, "--seed", "0"],
            capture_output=True, text=True, timeout=P3_TIMEOUT, env=env,
        )
        return proc.returncode

    def run_p3(self) -> dict:
        sid = "P3_run_experiment"
        self.state.mark_step_running(sid)
        clean_csv = os.path.join(self.root, "runs", self.run_id, "clean",
                                 "conductivity_clean.csv")
        exp_dir = os.path.join(self.root, "runs", self.run_id, "experiment")
        rc = self._spawn_experiment(clean_csv, exp_dir)
        if rc != 0:
            self.state.mark_step_failed(sid, f"experiment exit code {rc}")
            return {"failed": True, "rc": rc}

        # 校验三个关键产物存在
        required = [
            os.path.join(exp_dir, "results", "results.csv"),
            os.path.join(exp_dir, "results", "summary.json"),
            os.path.join(exp_dir, "figures", "fig1_conductivity.svg"),
        ]
        for p in required:
            if not os.path.exists(p):
                self.state.mark_step_failed(sid, f"missing artifact {p}")
                return {"failed": True, "missing": p}

        ev_exp = self.prov.append_evidence(
            kind="experiment",
            ref=os.path.join("experiment", "results", "results.csv"),
            producer_step="P3_run_experiment",
            file_path=required[0],
            meta={"sha256": _sha256_file(required[0])},
        )
        ev_fig = self.prov.append_evidence(
            kind="figure",
            ref=os.path.join("experiment", "figures", "fig1_conductivity.svg"),
            producer_step="P3_run_experiment",
            file_path=required[2],
            meta={"sha256": _sha256_file(required[2])},
        )
        with open(required[1], "r", encoding="utf-8") as f:
            summary = json.load(f)
        self._toolcall("P3_run_experiment", "sciret_run_step",
                       {"input": clean_csv, "outdir": exp_dir, "seed": 0},
                       {"rc": rc, "top3": [t["material_id"] for t in summary.get("top3", [])],
                        "results_sha256": _sha256_file(required[0])})
        self.state.mark_step_done(sid, {"rc": rc,
                                        "results_sha256": _sha256_file(required[0])})
        return {"failed": False, "exp_dir": exp_dir,
                "results_sha256": _sha256_file(required[0]),
                "summary": summary,
                "evidence": [ev_exp, ev_fig]}

    # ---------- P4 复现验证（幂等）----------

    def run_p4(self) -> dict:
        sid = "P4_verify"
        # 幂等守卫：已 DONE 直接复用，不重复执行
        if self.state.step_status[sid] is StepStatus.DONE:
            vpath = os.path.join(self.root, "runs", self.run_id,
                                 "verification", "verification.json")
            with open(vpath, "r", encoding="utf-8") as f:
                doc = json.load(f)
            return doc

        self.state.mark_step_running(sid)
        exp_dir = os.path.join(self.root, "runs", self.run_id, "experiment")
        rerun_dir = os.path.join(self.root, "runs", self.run_id,
                                 "verification", "rerun")
        clean_csv = os.path.join(self.root, "runs", self.run_id, "clean",
                                 "conductivity_clean.csv")

        # 原 P3 实验的 summary（作为 expected）
        orig_summary_path = os.path.join(exp_dir, "results", "summary.json")
        orig_results_path = os.path.join(exp_dir, "results", "results.csv")
        expected_sha = _sha256_file(orig_results_path)
        with open(orig_summary_path, "r", encoding="utf-8") as f:
            expected_summary = json.load(f)

        # 复跑到隔离目录；chaos 仅在此处注入 MUTATE
        rerun_env = chaos.CH.p4_rerun_env()
        rc = self._spawn_experiment(clean_csv, rerun_dir, extra_env=rerun_env or None)
        rerun_summary_path = os.path.join(rerun_dir, "results", "summary.json")
        rerun_results_path = os.path.join(rerun_dir, "results", "results.csv")
        if rc != 0:
            status, checks = "FAIL", [{
                "name": "rerun_process", "pass": False,
                "expected": "exit 0", "actual": f"exit {rc}"}]
        else:
            with open(rerun_summary_path, "r", encoding="utf-8") as f:
                actual_summary = json.load(f)
            actual_sha = _sha256_file(rerun_results_path)
            status, checks = verify_mod.build_checks(
                expected_sha, actual_sha, expected_summary, actual_summary)
            _ = actual_sha

        vpath = verify_mod.write_verification(
            os.path.join(self.root, "runs", self.run_id),
            status, checks,
            _sha256_file(rerun_results_path) if os.path.exists(rerun_results_path) else "")

        ev_v = self.prov.append_evidence(
            kind="verification", ref=vpath, producer_step="P4_verify",
            file_path=vpath,
            meta={"status": status,
                  "rerun_env": rerun_env},
        )
        self._toolcall("P4_verify", "sciret_verify",
                       {"expected_sha": expected_sha,
                        "rerun_env": rerun_env},
                       {"status": status, "checks": checks})
        if status == "PASS":
            self.state.mark_step_done(sid, {"status": "PASS"})
            return {"status": "PASS", "checks": checks, "evidence": [ev_v]}
        # FAIL: P4 步骤 FAILED，顶层 run FAILED
        self.state.mark_step_failed(sid, f"verification {status}: {checks}")
        return {"status": "FAIL", "checks": checks, "evidence": [ev_v],
                "failed": True}

    # ---------- P5 报告 ----------

    def run_p5(self) -> dict:
        sid = "P5_report"
        if self.state.step_status[sid] is StepStatus.DONE:
            rpath = os.path.join(self.root, "runs", self.run_id, "report.md")
            self.state.mark_step_done(sid, {"idempotent_reuse": True})
            return {"report": rpath}
        self.state.mark_step_running(sid)
        from . import report as report_mod
        rpath = report_mod.generate_report(self.root, self.run_id,
                                           self.state, self.prov)
        ev_r = self.prov.append_evidence(
            kind="report", ref=rpath, producer_step="P5_report",
            file_path=rpath, meta={"conclusions": 5})
        self._toolcall("P5_report", "sciret_report", {"run_id": self.run_id},
                       {"report": rpath})
        self.state.mark_step_done(sid, {"report": rpath})
        return {"report": rpath, "evidence": [ev_r]}

    # ---------- 调度 ----------

    STEP_FN = {
        "P1_lit_search": "run_p1",
        "P2_clean_data": "run_p2",
        "P3_run_experiment": "run_p3",
        "P4_verify": "run_p4",
        "P5_report": "run_p5",
    }

    def _ensure_running(self) -> None:
        """确保 run 处于 RUNNING；PLANNED→RUNNING 合法；已 RUNNING 则跳过。"""
        if self.state.run_status is RunStatus.PLANNED:
            self.state.start_run()
        # 若已是 RUNNING / DONE / FAILED（resume 场景），不再转移

    def run_step(self, step: str) -> dict:
        if step not in self.STEP_FN:
            raise KeyError(f"unknown step {step}")
        # resume 语义：只执行 PENDING/FAILED；DONE/SKIPPED 复用
        st = self.state.step_status[step]
        if st in (StepStatus.DONE, StepStatus.SKIPPED):
            return {"step": step, "reused": True, "status": st.value}
        self._ensure_running()
        return getattr(self, self.STEP_FN[step])()

    def run_all(self) -> dict:
        self._ensure_running()
        results = {}
        failed = False
        for step, fn in self.STEP_FN.items():
            cur = self.state.step_status[step]
            if cur in (StepStatus.DONE, StepStatus.SKIPPED):
                results[step] = {"reused": True}
                continue
            res = getattr(self, fn)()
            results[step] = res
            if res.get("failed"):
                failed = True
                break
        if failed:
            self.state.finish_run(RunStatus.FAILED)
        else:
            if self.state.step_status["P4_verify"] is StepStatus.FAILED:
                self.state.finish_run(RunStatus.FAILED)
            else:
                self.state.finish_run(RunStatus.DONE)
        return {"results": results,
                "run_status": self.state.run_status.value,
                "degraded": self.state.degraded}

    def resume(self) -> dict:
        """等价 run-all，断点续跑：只跑 PENDING/FAILED。"""
        return self.run_all()


def plan_run(root: str, goal: str, chaos_mode: str = "") -> PipelineState:
    rid = new_run_id()
    st = create_state(rid, root, goal)
    return st


def run_pipeline(root: str, goal: str, chaos_mode: str = "") -> dict:
    """plan + run-all 一步完成。"""
    rid = new_run_id()
    st = create_state(rid, root, goal)
    pipe = Pipeline(root, rid, chaos_mode=chaos_mode)
    out = pipe.run_all()
    out["run_id"] = rid
    return out
