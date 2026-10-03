"""freezing.py — 冻结输入快照的产出流程（redesign-decisions.md D6 + D7）。

三段式设计（对应 AGH 会话内判断的形态）：

    prepare()  → 取两腿数据 + 落盘一份 pending（含待判对象与规则式参考）
         ↓         （会话里的大模型据此推理，产出裁决）
    commit()   → 用**裁决**生成判断批次 → 跑异常检测 → 冻结快照

为什么分两段：模型判断由 AGH 会话内的 LLM 产生（Python 不调模型，见 llm.py
顶部的实测说明）。prepare/commit 之间就是"给人或模型思考"的窗口，
两段之间靠一份 pending 文件传递，**不重新检索**，保证同一轮判断对应同一批输入。

判断的产出者（judged_by）：
- ``rule``   —— 规则式基线（RuleJudge）
- ``model``  —— 模型裁决（由调用方通过 verdicts 传入，附模型身份与原始响应）
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time

from . import anomaly as anomaly_mod
from . import judge as judge_mod
from . import litsearch
from . import snapshot as snapshot_mod
from . import sources

PENDING_DIRNAME = ".pending"

MODE_BOOTSTRAP = "bootstrap"
MODE_NETWORK = "network"


class FreezeError(RuntimeError):
    pass


def _utc_now_str() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pending_dir(root: str) -> str:
    return os.path.join(snapshot_mod.snapshots_root(root), PENDING_DIRNAME)


def _pending_id() -> str:
    return f"pend-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{secrets.token_hex(3)}"


# ---------- 文献腿 ----------

def build_literature(mode: str, goal: str, rows: list[dict],
                     queries: list[str] | None, n_rows: int,
                     srcs: tuple) -> tuple[dict, dict | None]:
    """构造文献腿。返回 (literature, search_result_or_None)。"""
    if mode == MODE_BOOTSTRAP:
        dois = sorted({r["source_doi"] for r in rows if r["source_doi"]})
        return {
            "goal": goal,
            "source": "obelix_bootstrap",
            "note": ("bootstrap 文献腿：仅为数据集内原始论文 DOI 集合；"
                     "联网文献腿请用 mode=network"),
            "n_hits": len(dois),
            "hits": [{"doi": d, "source": "obelix_bootstrap"} for d in dois],
        }, None

    qs = list(queries or [])
    if not qs:
        qs = judge_mod.RuleJudge().generate_queries(goal)
    res = litsearch.search(qs, sources=srcs or (litsearch.CROSSREF,),
                           rows=n_rows, mailto=litsearch.mailto_from_env())
    return {
        "goal": goal,
        "source": "network:" + "+".join(res["sources"]),
        "note": "联网文献腿：Crossref / OpenAlex 元数据检索结果（未做相关性判断）",
        "queries": res["queries"],
        "n_hits": res["n_unique"],
        "errors": res["errors"],
        "hits": res["records"],
    }, res


# ---------- prepare ----------

def _repo_root() -> str:
    """仓库根目录（由包位置推导，**不读环境变量**）。

    不用 ``PAPER_AGENT_ROOT`` 是因为它会被测试的临时根覆盖，
    而数据集是随仓库分发的资产，应当稳定可寻。
    """
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def default_input_csv(root: str) -> str:
    """数据集的默认位置：优先 root 下；root 内没有则回落到仓库内那份。

    OBELiX 快照是**随仓库分发的资产**，不属于某个 root 的运行时状态；
    因此 ``--root`` 指向临时目录时仍能找到数据。
    """
    cand = os.path.join(root, "data", "external", "obelix", "all.csv")
    if os.path.exists(cand):
        return cand
    return os.path.join(_repo_root(), "data", "external", "obelix", "all.csv")


def prepare(root: str, goal: str, input_csv: str = "",
            literature_mode: str = MODE_BOOTSTRAP,
            queries: list[str] | None = None, n_rows: int = 20,
            srcs: tuple = (litsearch.CROSSREF, litsearch.OPENALEX)) -> dict:
    """取两腿数据并落盘 pending；返回待判对象与规则式参考裁决。"""
    csv_path = input_csv or default_input_csv(root)
    # strict=True：列名对不上就在这里响亮失败，绝不把错数据写成"成功的快照"
    rows, _ = sources.read_obelix(csv_path, strict=True)
    base = sources.summarize(rows)

    literature, search_res = build_literature(literature_mode, goal, rows,
                                              queries, n_rows, srcs)
    families = sorted({r["family"] for r in rows if r["family"]})

    rule = judge_mod.RuleJudge()
    suggestions, _ = rule.judge(goal, families)

    pid = _pending_id()
    os.makedirs(pending_dir(root), exist_ok=True)
    payload = {
        "pending_id": pid,
        "created_at": _utc_now_str(),
        "goal": goal,
        "input_csv": csv_path,
        "literature_mode": literature_mode,
        "literature": literature,
        "search_summary": ({"n_raw": search_res["n_raw"],
                            "n_unique": search_res["n_unique"],
                            "errors": search_res["errors"]} if search_res else None),
        "families": families,
        "rule_judgments": suggestions,
        "rule_scope": judge_mod.scope_from_judgments(suggestions),
        "data_summary": base,
    }
    path = os.path.join(pending_dir(root), pid + ".json")
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    return {
        "pending_id": pid,
        "pending_path": path,
        "goal": goal,
        "literature_mode": literature_mode,
        "n_families": len(families),
        "families": families,
        "rule_judgments": suggestions,
        "rule_scope": judge_mod.scope_from_judgments(suggestions),
        "rule_queries": next((j["meta"]["queries"] for j in suggestions
                              if j["kind"] == judge_mod.QUERY_GENERATION), []),
        "n_literature_hits": len(literature.get("hits", [])),
        "literature_errors": literature.get("errors", []),
        "data_summary": base,
    }


def load_pending(root: str, pending_id: str) -> dict:
    path = os.path.join(pending_dir(root), pending_id + ".json")
    if not os.path.exists(path):
        raise FreezeError(f"pending not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- 裁决规格归一 ----------

def normalize_verdicts(spec, families: list[str]) -> tuple[list[str] | None, list[dict]]:
    """把裁决规格归一为 (queries_or_None, [{family, verdict, reason}])。

    支持三种写法：
    - ``{"queries": [...], "families": {"LGPS": "relevant", ...}}``
    - ``{"queries": [...], "families": [{"family": "LGPS", "verdict": "relevant",
      "reason": "..."}]}``
    - ``{"families": {"LGPS": {"verdict": "relevant", "reason": "..."}}}``
      （嵌套写法：对**输入形状**宽容，对**完整性与取值**严格）
    """
    if not isinstance(spec, dict):
        raise FreezeError("verdicts spec must be a JSON object")
    queries = spec.get("queries")
    if queries is not None and not isinstance(queries, list):
        raise FreezeError("'queries' must be a list of strings")

    raw = spec.get("families")
    out: list[dict] = []
    if isinstance(raw, dict):
        for fam, val in raw.items():
            if isinstance(val, dict):
                if "verdict" not in val:
                    raise FreezeError(
                        f"nested verdict for {fam!r} missing 'verdict'")
                out.append({"family": fam, "verdict": val["verdict"],
                            "reason": val.get("reason", "")})
            else:
                out.append({"family": fam, "verdict": val, "reason": ""})
    elif isinstance(raw, list):
        for e in raw:
            if not isinstance(e, dict) or "family" not in e or "verdict" not in e:
                raise FreezeError("each family entry needs 'family' and 'verdict'")
            out.append({"family": e["family"], "verdict": e["verdict"],
                        "reason": e.get("reason", "")})
    elif raw is None:
        raise FreezeError("verdicts spec missing 'families'")
    else:
        raise FreezeError("'families' must be an object or an array")

    for e in out:
        e["family"] = judge_mod.normalize_family(e["family"])
        if e["verdict"] not in (judge_mod.VERDICT_RELEVANT,
                                judge_mod.VERDICT_EXCLUDED):
            raise FreezeError(f"invalid verdict for {e['family']!r}: "
                              f"{e['verdict']!r}")
    missing = set(families) - {e["family"] for e in out}
    if missing:
        raise FreezeError(f"verdicts missing {len(missing)} families, "
                          f"e.g. {sorted(missing)[:3]}")
    return queries, out


# ---------- commit ----------

def commit(root: str, pending_id: str, verdicts, judged_by: str = "model",
           model_name: str = "", raw_response: str = "",
           ack: list[str] | None = None, producer: str = "") -> dict:
    """用裁决生成判断批次 → 异常检测 → 冻结快照。

    异常未确认时**不写快照**，返回 ``{"ok": False, "stopped": True, ...}``。
    """
    pend = load_pending(root, pending_id)
    goal = pend["goal"]
    families = list(pend["families"])
    literature = pend["literature"]
    queries, items = normalize_verdicts(verdicts, families)

    if judged_by == "rule":
        impl, model_extra = judge_mod.RULE_IMPL, {}
    else:
        impl = judge_mod.MODEL_IMPL
        model_extra = {"model": model_name or "unknown", "raw_response": raw_response}

    judgments: list[dict] = [judge_mod.make_query_judgment(
        goal, queries or [], impl,
        ("由模型生成检索式" if impl == judge_mod.MODEL_IMPL
         else "规则式拆词"),
        extra=dict(model_extra))]
    for e in items:
        judgments.append(judge_mod.make_relevance_judgment(
            e["family"], e["verdict"],
            e["reason"] or ("(模型未给理由)" if impl == judge_mod.MODEL_IMPL
                            else "(规则式未给理由)"),
            impl, extra=dict(model_extra)))

    scope = judge_mod.scope_from_judgments(judgments)

    # 数据腿：重新读入并写入 in_scope（与 pending 同一份输入）
    rows, _ = sources.read_obelix(pend["input_csv"])
    for r in rows:
        r["in_scope"] = scope.get(r["family"], "excluded")
    base = sources.summarize(rows)

    join = anomaly_mod.join_legs(literature.get("hits", []), rows)
    lr = pend.get("search_summary") or {
        "n_unique": len(literature.get("hits", [])),
        "errors": literature.get("errors", [])}
    anomalies = anomaly_mod.detect(lr, join, judgments)
    pending_anoms = anomaly_mod.require_ack(anomalies, ack or [])
    if pending_anoms:
        return {
            "ok": False, "stopped": True, "reason": "unacknowledged_anomalies",
            "anomalies": [a["code"] for a in pending_anoms],
            "ack_hint": [a["ack_hint"] for a in pending_anoms],
            "report": anomaly_mod.format_report(anomalies, join),
        }

    sid = snapshot_mod.new_snapshot_id()
    snap = snapshot_mod.Snapshot(root, sid)
    manifest = snap.write(
        materials_csv=sources.to_materials_csv(rows),
        literature=literature,
        judgments=judgments,
        sources=[{"name": "obelix",
                  "url": "https://github.com/NRC-Mila/OBELiX",
                  "license": "CC-BY-4.0",
                  "citation": "Therrien et al., arXiv:2502.14234"}]
        + ([{"name": "crossref", "url": "https://api.crossref.org"},
            {"name": "openalex", "url": "https://api.openalex.org"}]
           if pend["literature_mode"] == MODE_NETWORK else []),
        producer=producer or (f"model_judge/{model_name or 'unknown'}"
                              if impl == judge_mod.MODEL_IMPL
                              else "bootstrap_rule_v1"),
        stats={
            "goal": goal,
            "judge_impl": impl,
            "judged_by": judged_by,
            "model": model_name or "",
            "pending_id": pending_id,
            "literature_mode": pend["literature_mode"],
            "n_rows": base["n_rows"],
            "value_status": base["value_status"],
            "family_empty": base["family_empty"],
            "n_families": len(families),
            "in_scope_families": sum(1 for v in scope.values()
                                     if v == judge_mod.VERDICT_RELEVANT),
            "in_scope_rows": sum(1 for r in rows if r["in_scope"] == "relevant"),
            "judgments": len(judgments),
            "leg_join": {k: join[k] for k in
                         ("n_literature_dois", "n_data_dois", "n_matched",
                          "join_rate_of_literature", "join_rate_of_data",
                          "n_literature_supporting_info_dois")},
            "anomalies_detected": [a["code"] for a in anomalies],
            "anomalies_acknowledged": sorted(set(ack or [])),
        },
    )
    ok, problems = snap.verify()
    return {
        "ok": ok, "snapshot_id": sid, "path": snap.dir,
        "content_sha256": manifest["content_sha256"],
        "stats": manifest["stats"], "verify_problems": problems,
        "report": anomaly_mod.format_report(anomalies, join),
    }


def freeze_rule_based(root: str, goal: str, input_csv: str = "",
                      literature_mode: str = MODE_BOOTSTRAP,
                      queries: list[str] | None = None, n_rows: int = 20,
                      srcs: tuple = (litsearch.CROSSREF, litsearch.OPENALEX),
                      ack: list[str] | None = None) -> dict:
    """一步完成（规则式裁决）：prepare + commit。CLI 与工具脚本的默认入口。"""
    prep = prepare(root, goal, input_csv, literature_mode, queries, n_rows, srcs)
    spec = {
        "queries": prep["rule_queries"],
        "families": {
            judge_mod.normalize_family(j["meta"]["subject"]): j["meta"]["verdict"]
            for j in prep["rule_judgments"]
            if j["kind"] == judge_mod.RELEVANCE
        },
    }
    out = commit(root, prep["pending_id"], spec, judged_by="rule", ack=ack)
    out["pending_id"] = prep["pending_id"]
    return out
