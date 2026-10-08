"""query.py — 证据查询层（Batch 4 / 增量实施任务列表 §四 B4-1）。

在 :class:`~paper_agent.provenance.ProvenanceLedger` 之上提供**只读**的
跨 run 检索、引文关系图、跨 run 聚合与全库哈希链校验。

设计红线：
- **纯 stdlib 零依赖**（与内核一致）；
- **只读**：不写任何文件、不改 provenance.py 的任何语义；
- 哈希链校验**复用** ``ProvenanceLedger.verify_chain()``（唯一真源，勿重复实现）；
- 所有 run_id 入参先过 :func:`valid_run_id`，防目录穿越；
- 大 run 全表加载内存 → ``query_runs`` 支持 ``limit`` 流式截断。
"""
from __future__ import annotations

import json
import os
import re

from .provenance import ProvenanceLedger

# run_id / run 目录名白名单：字母数字 + . _ -（拒绝路径分隔符与 ..，防穿越）
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# verify_chain 的问题串形如 "line 2 (EV-0002): chain hash mismatch ..."
_LINE_RE = re.compile(r"line (\d+)")


class QueryError(ValueError):
    """查询参数非法（如 run_id 穿越企图）。"""


def valid_run_id(run_id: str) -> bool:
    """run_id 是否安全（可作为 runs/ 下的目录名）。"""
    return isinstance(run_id, str) and bool(_RUN_ID_RE.match(run_id)) \
        and ".." not in run_id


def _require_valid_run_id(run_id: str) -> str:
    if not valid_run_id(run_id):
        raise QueryError(f"illegal run_id: {run_id!r}")
    return run_id


def _read_jsonl(path: str, *, strict: bool = False) -> list[dict]:
    """读 JSONL。strict=False 时跳过坏行（查询用）；校验场景走 verify_chain。"""
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                if strict:
                    raise
                continue
    return out


def _read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _run_dirs(runs_dir: str, run_ids=None) -> list[tuple[str, str]]:
    """列出待扫描的 (run_dir, run_id)。

    - 传 run_ids：按白名单逐个解析（不存在则跳过）；
    - 不传：扫描 runs/ 下所有合法命名的子目录（按名字典序）。
    """
    if not os.path.isdir(runs_dir):
        return []
    if run_ids:
        out = []
        for rid in run_ids:
            _require_valid_run_id(rid)
            d = os.path.join(runs_dir, rid)
            if os.path.isdir(d):
                out.append((d, rid))
        return out
    out = []
    for name in sorted(os.listdir(runs_dir)):
        d = os.path.join(runs_dir, name)
        if os.path.isdir(d) and valid_run_id(name):
            out.append((d, name))
    return out


def _to_item(run_id: str, rec: dict) -> dict:
    """provenance 行 → 查询结果条目（tier 走 tier_of 兼容旧记录默认 fact）。"""
    meta = rec.get("meta") or {}
    return {
        "run_id": run_id,
        "ev_id": rec.get("ev_id", ""),
        "tier": ProvenanceLedger.tier_of(rec),
        "kind": rec.get("kind", ""),
        "ref": rec.get("ref", ""),
        "sha256": rec.get("sha256", ""),
        "chain_hash": rec.get("chain_hash", ""),
        "producer_step": rec.get("producer_step", ""),
        "meta": meta,
    }


def _match(item: dict, *, kw=None, doi=None, tier=None, kind=None,
           source=None) -> bool:
    """单条过滤。kw 命中 ev_id/ref/kind/producer_step/meta.title/subject/doc_id。"""
    meta = item["meta"] or {}
    if tier and item["tier"] != tier:
        return False
    if kind and item["kind"] != kind:
        return False
    if doi:
        if item["ref"] != doi and str(meta.get("doi") or "") != doi:
            return False
    if source:
        srcs = meta.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        if source not in srcs:
            return False
    if kw:
        hay = " ".join([
            item["ev_id"], item["ref"], item["kind"], item["producer_step"],
            str(meta.get("title") or ""), str(meta.get("subject") or ""),
            str(meta.get("doc_id") or ""),
        ]).lower()
        if str(kw).lower() not in hay:
            return False
    return True


# ══════════════════════════════════════════════════════════════
# 1) 跨 run 证据检索
# ══════════════════════════════════════════════════════════════

def query_runs(runs_dir: str, kw: str | None = None, doi: str | None = None,
               tier: str | None = None, kind: str | None = None,
               source: str | None = None, run_ids: list[str] | None = None,
               limit: int | None = None) -> list[dict]:
    """跨 run 扫描全部 ``runs/*/provenance.jsonl``，按条件过滤，返回条目列表。

    条目形状：``{"run_id","ev_id","tier","kind","ref","sha256","chain_hash",
    "producer_step","meta"}``。
    ``limit`` 给定时取**先命中的前 limit 条**（流式截断，防大库内存膨胀）。
    """
    items: list[dict] = []
    for d, rid in _run_dirs(runs_dir, run_ids):
        path = os.path.join(d, "provenance.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue        # 坏行留给 verify_all_chains 上报，检索不中断
                item = _to_item(rid, rec)
                if _match(item, kw=kw, doi=doi, tier=tier, kind=kind,
                          source=source):
                    items.append(item)
                    if limit is not None and len(items) >= limit:
                        return items
    return items


# ══════════════════════════════════════════════════════════════
# 2) 引文关系图（结论 → 证据 → 文献 三层）
# ══════════════════════════════════════════════════════════════

def citation_graph(runs_dir: str, run_id: str) -> dict:
    """构建某 run 的 结论(C) → 证据(EV) → 文献(ref/title) 三层关系图。

    返回 ``{"run_id","n_conclusions","n_evidence","conclusions","evidence",
    "edges"}``；edges 为 ``{"from","to"}``（C→EV 与 EV→ref 两类）。
    悬空引用（evidence_ids 指向不存在的 EV）不进 evidence 节点，但 C→EV 边保留，
    便于暴露账本不一致。
    """
    _require_valid_run_id(run_id)
    d = os.path.join(runs_dir, run_id)
    prov: dict[str, dict] = {}
    for rec in _read_jsonl(os.path.join(d, "provenance.jsonl")):
        if rec.get("ev_id"):
            prov[rec["ev_id"]] = rec
    conclusions = _read_jsonl(os.path.join(d, "conclusions.jsonl"))

    c_nodes: list[dict] = []
    ev_nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for c in conclusions:
        cid = str(c.get("cid", ""))
        c_nodes.append({"id": cid, "text": c.get("text", "")})
        for ev in c.get("evidence_ids") or []:
            edges.append({"from": cid, "to": ev})
            rec = prov.get(ev)
            if not rec:
                continue
            if ev not in ev_nodes:
                meta = rec.get("meta") or {}
                ev_nodes[ev] = {
                    "id": ev,
                    "tier": ProvenanceLedger.tier_of(rec),
                    "kind": rec.get("kind", ""),
                    "ref": rec.get("ref", ""),
                    "title": meta.get("title", ""),
                }
            ref = rec.get("ref", "")
            if ref:
                edges.append({"from": ev, "to": ref})
    return {
        "run_id": run_id,
        "n_conclusions": len(c_nodes),
        "n_evidence": len(ev_nodes),
        "conclusions": c_nodes,
        "evidence": [ev_nodes[k] for k in sorted(ev_nodes)],
        "edges": edges,
    }


# ══════════════════════════════════════════════════════════════
# 3) 跨 run 聚合
# ══════════════════════════════════════════════════════════════

def aggregate_runs(runs_dir: str) -> dict:
    """跨 run 聚合：每 run 的元信息 + 证据/结论计数 + top DOI 频次（前 10）。

    state.json 缺失/损坏时对应字段给空值（不抛错，聚合要健壮）。
    """
    runs: list[dict] = []
    doi_count: dict[str, int] = {}
    for d, rid in _run_dirs(runs_dir):
        st = _read_json(os.path.join(d, "state.json"), {}) or {}
        prov = _read_jsonl(os.path.join(d, "provenance.jsonl"))
        concl = _read_jsonl(os.path.join(d, "conclusions.jsonl"))
        for rec in prov:
            if rec.get("kind") == "literature":
                ref = rec.get("ref", "")
                if ref:
                    doi_count[ref] = doi_count.get(ref, 0) + 1
        runs.append({
            "run_id": rid,
            "workflow": st.get("workflow", ""),
            "run_status": st.get("run_status", ""),
            "degraded": bool(st.get("degraded")),
            "goal": st.get("goal", ""),
            "n_evidence": len(prov),
            "n_conclusions": len(concl),
        })
    # 新 run 在前（run_id 内嵌时间戳，字典序即时间序）
    runs.sort(key=lambda r: r["run_id"], reverse=True)
    top = sorted(doi_count.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return {
        "n_runs": len(runs),
        "runs": runs,
        "top_dois": [{"doi": k, "count": v} for k, v in top],
    }


# ══════════════════════════════════════════════════════════════
# 4) 全库哈希链校验（复用 ProvenanceLedger.verify_chain）
# ══════════════════════════════════════════════════════════════

def verify_all_chains(runs_dir: str, run_ids: list[str] | None = None) -> dict:
    """对全部（或指定）run 逐个做哈希链校验，返回每 run 的结论与首条坏链位置。

    **校验逻辑唯一真源 = ``ProvenanceLedger.verify_chain()``**——本函数只做
    编排与汇总，绝不重复实现链算法。返回::

        {"n_runs": N, "ok": bool,
         "runs": [{"run_id","ok","n_problems","problems","first_bad_line"}]}
    """
    out: list[dict] = []
    all_ok = True
    for d, rid in _run_dirs(runs_dir, run_ids):
        try:
            ledger = ProvenanceLedger(d, rid)
            problems = ledger.verify_chain()
        except Exception as e:                      # 账本文件损坏到无法加载
            all_ok = False
            out.append({"run_id": rid, "ok": False, "n_problems": 1,
                        "problems": [f"ledger unloadable: "
                                     f"{type(e).__name__}: {e}"],
                        "first_bad_line": None})
            continue
        ok = not problems
        all_ok = all_ok and ok
        first_bad = None
        if problems:
            m = _LINE_RE.search(problems[0])
            if m:
                first_bad = int(m.group(1))
        out.append({
            "run_id": rid, "ok": ok, "n_problems": len(problems),
            "problems": problems[:5], "first_bad_line": first_bad,
        })
    return {"n_runs": len(out), "ok": all_ok, "runs": out}
