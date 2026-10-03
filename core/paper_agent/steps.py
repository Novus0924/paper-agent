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
from . import litsearch
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
        self.prov = ProvenanceLedger(os.path.join(root, "runs", run_id), run_id, root=root)
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

    def _p1_search(self, goal: str, full_corpus: bool,
                   lit_source: str | None = None) -> dict:
        """P1 文献检索：支持 arxiv / local / auto 三种来源。

        确定性契约：在线检索（arXiv）结果首次取得后**快照冻结**到 run 目录
        ``literature/arxiv_snapshot.json``；同一 run 再次执行 P1 只读快照、
        不再联网 —— 保证「同一 run 逐字节可复现」，同时让检索不再局限于
        内置的 5 篇语料。
        """
        lit_source = (lit_source or self.state.lit_source or "auto").lower()
        lit_dir = os.path.join(self.root, "runs", self.run_id, "literature")
        snap_path = os.path.join(lit_dir, "arxiv_snapshot.json")

        docs: list[dict] = []
        hits: list[dict] = []
        source_used = "local"
        query_used = ""
        fetched_at = ""
        degraded = bool(full_corpus)
        note = ""

        if full_corpus:
            # 降级路径（重试耗尽）：返回全部本地语料
            docs = litsearch.load_local_corpus(self.root)
            hits = list(docs)
            source_used = "local_full_corpus"
        else:
            if lit_source in ("arxiv", "auto"):
                if os.path.exists(snap_path):
                    # 同一 run 复跑：只读快照，绝不重新联网
                    with open(snap_path, "r", encoding="utf-8") as f:
                        snap = json.load(f)
                    docs = snap.get("documents", [])
                    query_used = snap.get("query", "")
                    fetched_at = snap.get("fetched_at", "")
                    source_used = snap.get("source", "arxiv")
                    note = "snapshot_reused"
                else:
                    try:
                        docs, query_used = litsearch.search_arxiv(goal)
                        source_used = "arxiv"
                        fetched_at = datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ")
                    except Exception as e:  # 网络/解析异常 → 交由下方降级
                        docs = []
                        note = f"arxiv_unavailable:{type(e).__name__}"

            if not docs and lit_source in ("local", "auto"):
                docs = litsearch.load_local_corpus(self.root)
                source_used = ("local_fallback" if note else "local")
                if source_used == "local_fallback":
                    degraded = True

            # arXiv 侧已由 API 按相关度排序；本地语料需按 goal 关键词过滤
            hits = (list(docs) if source_used == "arxiv"
                    else litsearch.filter_by_relevance(docs, goal))

        # 在线首跑成功后冻结快照（含检索式与时间戳，供审计与离线复现）
        if source_used == "arxiv" and note != "snapshot_reused" and not full_corpus:
            _write_json(snap_path, {
                "goal": goal,
                "query": query_used,
                "source": "arxiv",
                "endpoint": litsearch.ARXIV_API,
                "fetched_at": fetched_at,
                "n_documents": len(docs),
                "documents": docs,
            })

        out_path = os.path.join(lit_dir, "literature_hits.json")
        _write_json(out_path, {
            "goal": goal,
            "source": source_used,
            "query": query_used,
            "fetched_at": fetched_at,
            "snapshot": ("literature/arxiv_snapshot.json"
                         if os.path.exists(snap_path) else ""),
            "note": note,
            "n_hits": len(hits),
            "degraded": degraded,
            "hits": [
                {"doc_id": d.get("doc_id", ""), "doi": d.get("doi", ""),
                 "title": d.get("title", ""), "venue": d.get("venue", ""),
                 "year": d.get("year", 0), "url": d.get("url", ""),
                 "source": d.get("source", source_used),
                 "matched": full_corpus}
                for d in hits
            ],
        })
        # 登记 literature 证据（ref 优先 DOI，其次 arXiv 链接）
        ev_ids = []
        for d in hits:
            ev = self.prov.append_evidence(
                kind="literature", ref=litsearch.ref_of(d),
                producer_step="P1_lit_search",
                meta={"doc_id": d.get("doc_id", ""), "title": d.get("title", ""),
                      "year": d.get("year"), "source": d.get("source", "")},
            )
            ev_ids.append(ev)
        # 无论 0 命中与否，始终登记检索输出文件为 data 证据，
        # 作为 C1 结论的证据锚点（证据先行：0 命中也留证）。
        hits_file_ev = self.prov.append_evidence(
            kind="data",
            ref=os.path.join("literature", "literature_hits.json"),
            producer_step="P1_lit_search",
            file_path=out_path,
            meta={"n_hits": len(hits), "degraded": degraded,
                  "source": source_used},
        )
        # 在线检索的冻结快照单独留证：证明「下游用的输入」可追溯
        if os.path.exists(snap_path):
            self.prov.append_evidence(
                kind="data",
                ref=os.path.join("literature", "arxiv_snapshot.json"),
                producer_step="P1_lit_search",
                file_path=snap_path,
                meta={"query": query_used, "fetched_at": fetched_at,
                      "n_documents": len(docs)},
            )
        return {"n_hits": len(hits), "degraded": degraded,
                "source": source_used, "query": query_used,
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
                       {"goal": goal, "attempt": attempt, "degraded": degraded,
                        "lit_source": self.state.lit_source},
                       {"n_hits": result["n_hits"],
                        "source": result.get("source", ""),
                        "query": result.get("query", "")})
        step_degraded = bool(result.get("degraded", degraded))
        if step_degraded and not degraded:
            # 非「重试耗尽」型的降级：如 arXiv 不可达/0 命中 → 回落本地语料。
            # 同样要留 degrade 痕迹，让 run 级 degraded 与产物内声明保持一致。
            self.state.mark_degraded(
                sid, note=f"lit_source={self.state.lit_source} → "
                          f"{result.get('source')} ({result.get('query') or 'no-query'})")
        self.state.mark_step_done(sid, {"n_hits": result["n_hits"],
                                        "source": result.get("source", ""),
                                        "degraded": step_degraded})
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
        # 崩溃注入点同样覆盖单步 run-step 路径（AGH 插件只有 run_step 工具）；
        # 位于 P2 状态与双账本全部落盘之后，append-only 完整性不受影响。
        chaos.CH.kill_after(sid)
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
            # 幂等复用：DONE→DONE 是非法转移（终态守卫），直接返回既有报告路径
            rpath = os.path.join(self.root, "runs", self.run_id, "report.md")
            return {"report": rpath, "idempotent_reuse": True}
        self.state.mark_step_running(sid)
        from . import report as report_mod
        # 收集本步要写进报告的产物与证据，但**先不落盘**：
        # 报告正文里含"顶层状态 / 各步骤状态"快照，必须在 P5 自身 DONE 之后再落笔，
        # 否则报告会永远比真实状态落后一步（旧实现缺陷：报告自称 RUNNING）。
        ev_r = self.prov.append_evidence(
            kind="report",
            ref=os.path.join("report.md"), producer_step="P5_report",
            file_path=None, meta={"conclusions": 5})
        self._toolcall("P5_report", "sciret_report", {"run_id": self.run_id},
                       {"report": os.path.join(self.root, "runs",
                                               self.run_id, "report.md")})
        self.state.mark_step_done(sid, {"report": "report.md"})
        # P5 已 DONE 落盘，此刻状态快照才准确；此时才生成报告正文
        rpath = report_mod.generate_report(self.root, self.run_id,
                                           self.state, self.prov)
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

    # ---------- 模型驱动编排（主导路径）----------
    #
    # 设计变更（对齐赛事红线"AGH 必须承担核心任务流程 ≥3 连续步骤"）：
    #   旧形态：run_all() 是 Python 里一个写死的 for 循环，不装 AGH 也能跑完，
    #           AGH 沦为"启动器"，核心编排在框架之外。
    #   新形态：编排主动权交给 AGH 会话内的大模型。Python 每次只执行"被显式请求的
    #           一个步骤"，然后把「执行结果 + 下一步候选 + 决策提示」交还模型；
    #           由模型决定下一步调哪个 sciret_* 工具、是否重试、是否降级、是否收尾。
    #   run_all() 保留为"确定性兜底路径"（供单测与离线演示），不再是主导路径。

    def step_context(self, step: str, result: dict) -> dict:
        """把一个步骤的执行结果，翻译成"供模型决策下一步"的上下文块。

        这是模型驱动编排的核心：Python 不替模型决定下一步，只如实汇报
        已发生了什么、还剩什么可选、以及有哪些失败信号需要模型判断。
        """
        plan = self.state.pending_or_failed()
        done = [s for s in self.STEP_FN
                if self.state.step_status[s] in (StepStatus.DONE, StepStatus.SKIPPED)]
        failed = [s for s in self.STEP_FN
                  if self.state.step_status[s] is StepStatus.FAILED]

        ctx = {
            "executed_step": step,
            "result": result,
            "run_status": self.state.run_status.value,
            "steps": {s: self.state.step_status[s].value for s in self.STEP_FN},
            "attempts": dict(self.state.attempts),
            "degraded": self.state.degraded,
            "completed_steps": done,
            "remaining_steps": plan,
            "failed_steps": failed,
        }

        # 把"可调用的下一步工具"明确列出来，降低模型跑偏概率
        candidates = [f"sciret_run_step(step='{s}')" for s in plan]
        if failed:
            candidates.append("sciret_resume(run_id=...)  # 重试/续跑失败步骤")
        if not plan and not failed:
            candidates.append("sciret_verify(run_id=...)  # 复现验证（若尚未验证）")
            candidates.append("sciret_report(run_id=...)  # 生成报告收尾")
        ctx["next_tool_candidates"] = candidates

        # 失败显式化：把需要模型判断的信号写清楚，不吞异常
        if failed:
            ctx["requires_decision"] = True
            ctx["decision_reason"] = (
                f"步骤 {failed} 处于 FAILED。你必须判断：调用 sciret_resume 重试，"
                f"还是终止并说明失败原因。禁止忽略失败继续下一步。"
            )
        elif self.state.degraded:
            ctx["requires_decision"] = False
            ctx["decision_reason"] = (
                "当前 run 已发生降级（degraded=true），结论证据基于降级后语料，"
                "报告中必须显式声明。"
            )
        else:
            ctx["requires_decision"] = False

        return ctx

    def run_step_driven(self, step: str) -> dict:
        """模型驱动路径：执行单个步骤并返回决策上下文。

        与 run_step 的区别：run_step 只返回步骤结果；run_step_driven 额外返回
        next_tool_candidates / requires_decision 等字段，供 AGH 会话内大模型决策。
        """
        res = self.run_step(step)
        # 崩溃注入点：位于该步骤状态与双账本全部落盘之后（append-only 完整）
        chaos.CH.kill_after(step)
        return self.step_context(step, res)

    def finish_if_terminal(self) -> dict:
        """模型确认流水线已到终态时调用，收敛 run_status。

        由模型决定"收尾"后才调用——Python 不再自动收尾。
        """
        if self.state.run_status is not RunStatus.RUNNING:
            return {"run_status": self.state.run_status.value,
                    "note": f"run 已处于终态 {self.state.run_status.value}，无需收尾"}
        steps = self.state.step_status
        if any(st is StepStatus.FAILED for st in steps.values()):
            self.state.finish_run(RunStatus.FAILED)
        elif all(st in (StepStatus.DONE, StepStatus.SKIPPED) for st in steps.values()):
            self.state.finish_run(RunStatus.DONE)
        else:
            pending = [s for s in self.STEP_FN
                       if steps[s] in (StepStatus.PENDING, StepStatus.RUNNING)]
            return {"run_status": self.state.run_status.value,
                    "error": "尚未终态，仍有未完成步骤",
                    "remaining_steps": pending,
                    "hint": "请先对这些步骤调用 sciret_run_step 或 sciret_resume"}
        return {"run_status": self.state.run_status.value,
                "degraded": self.state.degraded}

    def run_step(self, step: str) -> dict:
        if step not in self.STEP_FN:
            raise KeyError(f"unknown step {step}")
        # resume 语义：只执行 PENDING/FAILED；DONE/SKIPPED 复用
        st = self.state.step_status[step]
        if st in (StepStatus.DONE, StepStatus.SKIPPED):
            return {"step": step, "reused": True, "status": st.value}
        self._ensure_running()
        return getattr(self, self.STEP_FN[step])()

    # ---------- 确定性兜底路径（非主导，仅供单测与离线演示）----------

    def run_all(self) -> dict:
        """确定性兜底：一次性跑完剩余步骤。**注意：这不是 AGH 会话的主导路径。**

        AGH 会话内应由大模型逐步调用 sciret_run_step / sciret_resume 驱动；
        本方法仅用于单测、离线演示与 CI，保证"不接模型也能验证 Python 核心逻辑"。
        """
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
            # 崩溃注入点：位于该步骤状态与双账本全部落盘之后（append-only 完整）
            chaos.CH.kill_after(step)
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
        """断点续跑：只跑 PENDING/FAILED，DONE/SKIPPED 直接复用。"""
        return self.run_all()


def plan_run(root: str, goal: str, chaos_mode: str = "",
             lit_source: str | None = None,
             workflow: str = "materials") -> PipelineState:
    rid = new_run_id()
    st = create_state(rid, root, goal, lit_source=lit_source, workflow=workflow)
    return st


def run_pipeline(root: str, goal: str, chaos_mode: str = "",
                 lit_source: str | None = None,
                 workflow: str = "materials") -> dict:
    """plan + run-all 一步完成（按 workflow 分发到对应编排器）。"""
    rid = new_run_id()
    create_state(rid, root, goal, lit_source=lit_source, workflow=workflow)
    pipe = open_pipeline(root, rid, chaos_mode=chaos_mode)
    out = pipe.run_all()
    out["run_id"] = rid
    return out


def open_pipeline(root: str, run_id: str, chaos_mode: str = ""):
    """按 run 的 workflow 装配对应编排器。

    - ``materials`` → :class:`Pipeline`（本模块，P1..P5）
    - ``research``  → :class:`~paper_agent.research.ResearchPipeline`（R1..R6）

    采用函数内惰性导入，避免 steps ↔ research 的循环依赖。
    """
    st = load_state(run_id, root)
    wf = getattr(st, "workflow", "materials")
    if wf == "research":
        from .research import ResearchPipeline
        return ResearchPipeline(root, run_id, chaos_mode=chaos_mode)
    return Pipeline(root, run_id, chaos_mode=chaos_mode)
