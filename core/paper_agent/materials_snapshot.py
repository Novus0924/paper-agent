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
from . import sources
from . import snapshot as snapshot_mod

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

    # ---------- P1 主路径：消费冻结快照（redesign D6）----------

    def _open_snapshot_or_none(self):
        """打开项目级冻结快照；不存在或显式禁用则返回 None（回退内置语料路径）。

        环境变量控制（同时支持连字符与下划线两种写法——连字符名在部分
        shell 下无法 export，故提供等价的下划线别名）：
          - 未设置   → 自动取最新快照
          - ``none`` → 强制禁用快照，走内置语料路径（legacy 演示 / 回归用）
          - 其它值   → 指定快照 id（回放某个特定快照）
        """
        raw = ""
        for name in ("PAPER_AGENT_SNAPSHOT", "paper-agent_SNAPSHOT"):
            v = os.environ.get(name)
            if v is not None and str(v).strip():
                raw = str(v).strip()
                break
        if raw.lower() == "none":
            return None
        try:
            return snapshot_mod.open_snapshot(self.root, raw)
        except snapshot_mod.SnapshotError:
            return None

    def _p1_from_snapshot(self, sid: str, snap) -> dict:
        """消费冻结快照：强校验 → 重登记判断 → 登记事实 → 产出命中清单。

        检索与相关性判断本身发生在**快照冻结阶段**（D6：复现契约只覆盖
        "冻结之后"）；本步骤负责让当前 run 的账本自包含、可独立审计。
        """
        self.state.mark_step_running(sid)

        ok, problems = snap.verify()
        if not ok:
            self.state.mark_step_failed(
                sid, "snapshot integrity check failed: " + "; ".join(problems))
            return {"failed": True, "snapshot_problems": problems}

        # 判据 4 前置：快照必须携带判断批次
        snap.require_judgments()
        manifest = snap.load()

        judgment_evs = snap.register_judgments_into(self.prov)

        mat_rows = sources.read_materials(snap.materials_path())
        mat_stats = sources.summarize(mat_rows)

        ev_manifest = self.prov.append_evidence(
            kind="data", ref=f"snapshots/{snap.snapshot_id}/manifest.json",
            producer_step=sid, file_path=snap.manifest_path,
            meta={"snapshot_id": snap.snapshot_id,
                  "content_sha256": manifest.get("content_sha256"),
                  "producer": manifest.get("producer")})
        ev_lit = self.prov.append_evidence(
            kind="literature",
            ref=f"snapshots/{snap.snapshot_id}/{snapshot_mod.LITERATURE_FILE}",
            producer_step=sid,
            file_path=snap.file_path(snapshot_mod.LITERATURE_FILE),
            meta={"source": "snapshot"})
        ev_mat = self.prov.append_evidence(
            kind="data",
            ref=f"snapshots/{snap.snapshot_id}/{snapshot_mod.MATERIALS_FILE}",
            producer_step=sid, file_path=snap.materials_path(),
            meta={"rows": mat_stats["n_rows"],
                  "usable_rows": mat_stats["value_status"].get("numeric", 0)})

        literature = snap.literature()
        hits = literature.get("hits", [])
        out_path = os.path.join(self.root, "runs", self.run_id, "literature",
                                "literature_hits.json")
        _write_json(out_path, {
            "goal": self.state.goal,
            "snapshot_id": snap.snapshot_id,
            "snapshot_content_sha256": manifest.get("content_sha256"),
            "n_hits": len(hits),
            "hits": hits,
            "degraded": False,
            "materials_rows": mat_stats["n_rows"],
            "materials_usable": mat_stats["value_status"].get("numeric", 0),
            "judgments_registered": len(judgment_evs),
        })

        self._toolcall("P1_lit_search", "sciret_run_step",
                       {"snapshot_id": snap.snapshot_id},
                       {"n_hits": len(hits), "materials_rows": mat_stats["n_rows"]})
        self.state.mark_step_done(sid, {
            "snapshot_id": snap.snapshot_id,
            "n_hits": len(hits),
            "materials_rows": mat_stats["n_rows"],
            "judgments": len(judgment_evs)})
        return {"snapshot_id": snap.snapshot_id,
                "n_hits": len(hits),
                "materials_rows": mat_stats["n_rows"],
                "output": out_path,
                "evidence": [ev_manifest, ev_lit, ev_mat],
                "judgment_evidence": judgment_evs}

    def run_p1(self) -> dict:
        sid = "P1_lit_search"
        # 主路径：消费冻结输入快照（redesign D6）；无快照时回退内置语料本地匹配
        snap = self._open_snapshot_or_none()
        if snap is not None:
            return self._p1_from_snapshot(sid, snap)

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
        # 主路径：清洗快照数据腿产出的标准 materials.csv
        snap = self._open_snapshot_or_none()
        if snap is not None:
            return self._p2_from_materials(sid, snap)

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

    # ---------- P2 主路径：清洗真实数据集 ----------

    #: 数据源自带注记 → 质量标记（不删行，只标注，供报告与人工复核）
    QUALITY_RULES = (
        ("not matching", "structure_mismatch"),
        ("not correct", "source_flagged"),
        ("partial occupancy", "partial_occupancy"),
        ("check", "needs_review"),
    )

    #: 清洗后供计算使用的列
    CLEAN_COLUMNS = ["material_id", "formula", "family", "conductivity_Scm",
                     "space_group", "source_doi", "dup_measurement",
                     "quality_flag", "in_scope"]

    def _quality_flags(self, note: str) -> str:
        n = (note or "").lower()
        return "|".join(name for kw, name in self.QUALITY_RULES if kw in n)

    def _p2_from_materials(self, sid: str, snap) -> dict:
        """清洗真实数据集：值分类过滤 / 家族补缺 / 重复标注 / 质量标注。

        原则：
        - **不可比较的值必须剔除，但绝不静默丢弃**（写入 excluded_rows.json 留证）
        - **重复测量不删除**（同一材料同一论文的多条记录是真实存在的），只标注
        - 清洗只做过滤与标注，**不做任何科学计算**（派生量留给 P3）
        """
        self.state.mark_step_running(sid)
        src = snap.materials_path()
        rows = sources.read_materials(src)
        in_n = len(rows)

        # (formula, doi) 出现次数：用于识别"同论文同材料的重复记录"
        pair_count: dict[tuple, int] = {}
        for r in rows:
            pair_count[(r.get("formula", ""), r.get("source_doi", ""))] = \
                pair_count.get((r.get("formula", ""), r.get("source_doi", "")), 0) + 1

        actions: list[dict] = []
        excluded: list[dict] = []
        clean: list[dict] = []
        seen_rows: set[tuple] = set()

        for r in rows:
            mid = r.get("material_id", "")
            status = r.get("value_status", "")

            # 规则 1：值状态过滤（上界值 / 无效值不可参与排序）
            if status != sources.VALUE_NUMERIC:
                reason = ("upper bound notation (e.g. '<1E-10'): "
                          "not a comparable value"
                          if status == sources.VALUE_UPPER_BOUND
                          else "no parsable positive numeric value")
                excluded.append({
                    "material_id": mid,
                    "formula": r.get("formula", ""),
                    "family": r.get("family", ""),
                    "conductivity_raw": r.get("conductivity_raw", ""),
                    "value_status": status,
                    "source_doi": r.get("source_doi", ""),
                    "reason": reason,
                })
                actions.append({"action": "exclude_non_numeric",
                                "material_id": mid,
                                "value_status": status,
                                "reason": reason})
                continue

            # 规则 2：完全重复行剔除（防御性；本数据集 ID 全唯一，预期 0 条）
            key = tuple(sorted(r.items()))
            if key in seen_rows:
                actions.append({"action": "dedup_exact", "material_id": mid,
                                "note": "entire row identical to a previous one"})
                continue
            seen_rows.add(key)

            out = {k: r.get(k, "") for k in self.CLEAN_COLUMNS}

            # 规则 3：家族缺失 → unknown（不删除，避免静默缩小样本）
            if not out["family"]:
                out["family"] = "unknown"
                actions.append({"action": "family_fill_unknown",
                                "material_id": mid,
                                "note": "source family empty → 'unknown'"})

            # 规则 4：同论文同材料的重复记录 → 标注（不删除）
            pair = (r.get("formula", ""), r.get("source_doi", ""))
            if pair_count.get(pair, 0) > 1:
                out["dup_measurement"] = "yes"
                actions.append({"action": "flag_duplicate_measurement",
                                "material_id": mid,
                                "note": "same composition + same DOI appears "
                                        f"{pair_count[pair]} times"})

            # 规则 5：数据源质量注记 → 质量标记（不删除）
            qf = self._quality_flags(r.get("data_notes", ""))
            if qf:
                out["quality_flag"] = qf
                actions.append({"action": "flag_quality_note",
                                "material_id": mid, "flags": qf})

            clean.append({k: out.get(k, "") for k in self.CLEAN_COLUMNS})

        clean_path = os.path.join(self.root, "runs", self.run_id, "clean",
                                  "materials_clean.csv")
        _write_csv(clean_path, self.CLEAN_COLUMNS, clean)

        counts: dict[str, int] = {}
        for a in actions:
            counts[a["action"]] = counts.get(a["action"], 0) + 1

        def _family_counts(rs):
            c: dict[str, int] = {}
            for x in rs:
                c[x["family"]] = c.get(x["family"], 0) + 1
            return dict(sorted(c.items()))

        report = {
            "input_rows": in_n,
            "output_rows": len(clean),
            "excluded_rows": len(excluded),
            "action_counts": dict(sorted(counts.items())),
            "actions": actions,
            "value_source": "snapshot:" + snap.snapshot_id,
            "included_families": _family_counts(clean),
            "excluded_families": _family_counts(excluded) if excluded else {},
        }
        rep_path = os.path.join(self.root, "runs", self.run_id, "clean",
                                "cleaning_report.json")
        _write_json(rep_path, report)

        exc_path = os.path.join(self.root, "runs", self.run_id, "clean",
                                "excluded_rows.json")
        _write_json(exc_path, {
            "note": "行被排除出排序计算，但保留留证（不静默丢弃）",
            "n_excluded": len(excluded),
            "rows": excluded,
        })

        ev_data = self.prov.append_evidence(
            kind="data", ref="clean/materials_clean.csv",
            producer_step="P2_clean_data", file_path=clean_path,
            meta={"input_rows": in_n, "output_rows": len(clean)})
        ev_rep = self.prov.append_evidence(
            kind="data", ref="clean/cleaning_report.json",
            producer_step="P2_clean_data", file_path=rep_path,
            meta={"action_count": len(actions)})
        ev_exc = self.prov.append_evidence(
            kind="data", ref="clean/excluded_rows.json",
            producer_step="P2_clean_data", file_path=exc_path,
            meta={"n_excluded": len(excluded),
                  "n_upper_bound": sum(
                      1 for e in excluded
                      if e["value_status"] == sources.VALUE_UPPER_BOUND)})

        self._toolcall("P2_clean_data", "sciret_run_step",
                       {"input": f"snapshot:{snap.snapshot_id}",
                        "input_rows": in_n},
                       {"clean": clean_path, "output_rows": len(clean),
                        "excluded": len(excluded)})
        self.state.mark_step_done(sid, {"output_rows": len(clean),
                                        "excluded": len(excluded),
                                        "actions": len(actions)})
        chaos.CH.kill_after(sid)
        return {"clean": clean_path, "report": rep_path, "excluded": exc_path,
                "input_rows": in_n, "output_rows": len(clean),
                "excluded_rows": len(excluded),
                "evidence": [ev_data, ev_rep, ev_exc]}

    # ---------- P3 实验子进程 ----------

    def _clean_csv(self) -> str:
        """优先使用真实数据集清洗产物（materials_clean.csv）；
        否则回退内置演示数据的清洗产物（conductivity_clean.csv）。"""
        p_new = os.path.join(self.root, "runs", self.run_id, "clean",
                             "materials_clean.csv")
        if os.path.exists(p_new):
            return p_new
        return os.path.join(self.root, "runs", self.run_id, "clean",
                            "conductivity_clean.csv")

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
        clean_csv = self._clean_csv()
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
        clean_csv = self._clean_csv()

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
