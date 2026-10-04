"""anomaly.py — 双腿对接与异常驱动打断（redesign-decisions.md D7）。

## 关于"两腿 DOI 对接"的实测修正（重要）

设计文档 D3 曾隐含"两腿 DOI 高重合"。**实测否证了这一假设**：

    文献腿（4 检索式 × 2 来源）373 篇  ∩  OBELiX 数据腿 222 篇  =  8 篇（2.1%）

原因很清楚：文献腿给的是**话题全景**（综述与近年高影响论文），数据腿是
**一个特定实测数据集的来源论文**；两者天然只有少量重叠。

因此本模块的异常规则据此修正：
- **"对接率低"不是异常**（正常就低），只作为指标报告（join_rate_*）
- **"两腿交集为零"才是异常**——说明检索式完全跑偏，需要人裁决

其余三条异常按 D7：零命中 / 命中率反常 / 模型自相矛盾。
"""
from __future__ import annotations

import re

# ---------- 异常码 ----------

ZERO_HITS = "zero_hits"
NO_LEG_OVERLAP = "no_leg_overlap"
JUDGE_HIT_RATE = "judge_hit_rate"
JUDGE_SELF_CONTRADICTION = "judge_self_contradiction"

ANOMALY_CODES = (ZERO_HITS, NO_LEG_OVERLAP, JUDGE_HIT_RATE,
                 JUDGE_SELF_CONTRADICTION)

SEVERITY_BLOCKING = "blocking"

#: 命中率异常的判定阈值与最小样本量（样本不足不判定，避免小样本误报）
HIT_RATE_HIGH = 0.90
HIT_RATE_LOW = 0.05
HIT_RATE_MIN_SAMPLE = 20

#: 支撑信息 DOI（如 10.1021/acsami.3c17535.s001、10.1002/x.2020.s1）：
#: 不是主论文，不参与两腿对接。位数不定（ACS 用 .s001，其他用 .s1），故取 1+ 位。
#: 这是**启发式**：仅用于把这类记录排除出"可对接集合"，不用于丢弃任何记录。
_SI_RE = re.compile(r"\.s\d+$", re.I)


def is_supporting_information(doi: str) -> bool:
    return bool(_SI_RE.search((doi or "").strip()))


class AnomalyError(RuntimeError):
    """存在未被人工确认的异常：流程必须停下。"""

    def __init__(self, anomalies: list[dict]):
        self.anomalies = anomalies
        codes = ", ".join(a["code"] for a in anomalies)
        super().__init__(f"unacknowledged anomalies: {codes}")


# ---------- 双腿对接 ----------

def join_legs(lit_records: list[dict], materials_rows: list[dict]) -> dict:
    """按 DOI 对接文献腿与数据腿。纯统计，不做判断，不做丢弃。

    - 支撑信息 DOI 单独统计并从"可对接集合"中排除（它们不是主论文）
    - 无 DOI 的记录计入 no_doi，同样不参与对接
    """
    lit_dois, lit_si = set(), set()
    for r in lit_records:
        d = (r.get("doi") or "").strip().lower()
        if not d:
            continue
        (lit_si if is_supporting_information(d) else lit_dois).add(d)

    data_dois, data_si = set(), set()
    for r in materials_rows:
        d = (r.get("source_doi") or "").strip().lower()
        if not d:
            continue
        (data_si if is_supporting_information(d) else data_dois).add(d)

    matched = sorted(lit_dois & data_dois)
    return {
        "n_literature_dois": len(lit_dois),
        "n_literature_supporting_info_dois": len(lit_si),
        "n_data_dois": len(data_dois),
        "n_data_supporting_info_dois": len(data_si),
        "matched": matched,
        "n_matched": len(matched),
        "literature_only": sorted(lit_dois - data_dois),
        "data_only": sorted(data_dois - lit_dois),
        "join_rate_of_literature": round(len(matched) / len(lit_dois), 4)
        if lit_dois else 0.0,
        "join_rate_of_data": round(len(matched) / len(data_dois), 4)
        if data_dois else 0.0,
        "no_leg_overlap": (len(matched) == 0
                           and bool(lit_dois) and bool(data_dois)),
    }


# ---------- 异常检测 ----------

def _anomaly(code: str, detail: str, metrics: dict, severity: str = SEVERITY_BLOCKING) -> dict:
    return {"code": code, "severity": severity, "detail": detail,
            "metrics": metrics, "ack_hint": f"--ack {code}"}


def detect_zero_hits(literature_result: dict) -> list[dict]:
    """检索式零命中：文献腿一条都没搜到。"""
    n = int((literature_result or {}).get("n_unique", 0))
    if n == 0:
        return [_anomaly(
            ZERO_HITS,
            "文献腿零命中：所有检索式与来源均未返回任何论文"
            "（或全部来源请求失败）",
            {"n_unique": 0,
             "errors": len((literature_result or {}).get("errors") or [])})]
    return []


def detect_no_overlap(join: dict) -> list[dict]:
    """两腿交集为零：检索式完全跑偏（注意：低对接率不算异常）。"""
    if join.get("no_leg_overlap"):
        return [_anomaly(
            NO_LEG_OVERLAP,
            "两腿 DOI 完全无交集：文献腿与数据腿指向互不相干的两批论文，"
            "疑似检索式跑偏或目标领域不匹配",
            {"n_literature_dois": join["n_literature_dois"],
             "n_data_dois": join["n_data_dois"],
             "n_matched": 0})]
    return []


def detect_hit_rate(judgments: list[dict]) -> list[dict]:
    """命中率反常：模型把几乎所有对象判为相关，或几乎全判为不相关。

    仅在样本量足够时判定；样本不足不报（避免小样本误报）。
    """
    rel = [j for j in (judgments or [])
           if j.get("kind") == "relevance"]
    n = len(rel)
    if n < HIT_RATE_MIN_SAMPLE:
        return []
    verdicts = [(j.get("meta") or {}).get("verdict") for j in rel]
    n_rel = sum(1 for v in verdicts if v == "relevant")
    rate = n_rel / n
    if rate >= HIT_RATE_HIGH:
        return [_anomaly(
            JUDGE_HIT_RATE,
            f"相关性命中率过高（{rate:.0%}）：{n} 个对象中 {n_rel} 个被判相关，"
            f"通常意味着判断在放水",
            {"n": n, "n_relevant": n_rel, "rate": round(rate, 4),
             "threshold_high": HIT_RATE_HIGH})]
    if rate <= HIT_RATE_LOW:
        return [_anomaly(
            JUDGE_HIT_RATE,
            f"相关性命中率过低（{rate:.0%}）：{n} 个对象中仅 {n_rel} 个被判相关，"
            f"通常意味着判断在误杀",
            {"n": n, "n_relevant": n_rel, "rate": round(rate, 4),
             "threshold_low": HIT_RATE_LOW})]
    return []


def detect_self_contradiction(judgments: list[dict]) -> list[dict]:
    """模型自相矛盾：同一对象既被判相关又被判不相关。"""
    seen: dict[tuple, set] = {}
    for j in (judgments or []):
        if j.get("kind") != "relevance":
            continue
        m = j.get("meta") or {}
        key = (m.get("axis", "material_family"), m.get("subject", ""))
        seen.setdefault(key, set()).add(m.get("verdict"))
    conflicts = sorted(k for k, v in seen.items() if len(v) > 1)
    if conflicts:
        return [_anomaly(
            JUDGE_SELF_CONTRADICTION,
            f"同一对象出现相反裁决：{len(conflicts)} 个对象同时被判相关与不相关",
            {"conflicts": [f"{a}:{s}" for a, s in conflicts[:10]],
             "n_conflicts": len(conflicts)})]
    return []


def detect(literature_result: dict, join: dict, judgments: list[dict]) -> list[dict]:
    """跑全部规则，返回异常列表（按码排序，确定性）。"""
    out: list[dict] = []
    out += detect_zero_hits(literature_result)
    out += detect_no_overlap(join)
    out += detect_hit_rate(judgments)
    out += detect_self_contradiction(judgments)
    return sorted(out, key=lambda a: a["code"])


def format_report(anomalies: list[dict], join: dict | None = None) -> str:
    """人类可读的异常报告（供停下时打印）。"""
    lines = ["=" * 68, "异常检测报告（D7：异常必须停下等待人工裁决）", "=" * 68]
    if join:
        lines.append("双腿对接指标（低对接率属正常，不作为异常）：")
        lines.append(f"  文献腿 DOI {join['n_literature_dois']} 篇"
                     f"（其中支撑信息 DOI {join['n_literature_supporting_info_dois']} 条）")
        lines.append(f"  数据腿 DOI {join['n_data_dois']} 篇"
                     f"（其中支撑信息 DOI {join['n_data_supporting_info_dois']} 条）")
        lines.append(f"  交集 {join['n_matched']} 篇"
                     f"（占文献腿 {join['join_rate_of_literature']:.1%}，"
                     f"占数据腿 {join['join_rate_of_data']:.1%}）")
        lines.append("")
    if not anomalies:
        lines.append("未检出异常。")
        return "\n".join(lines)
    lines.append(f"检出 {len(anomalies)} 项异常：")
    for a in anomalies:
        lines.append(f"  [{a['severity']}] {a['code']}")
        lines.append(f"      {a['detail']}")
        lines.append(f"      指标: {a['metrics']}")
        lines.append(f"      确认方式（人工裁决后重跑）: {a['ack_hint']}")
    lines.append("")
    lines.append("流程已停下。请逐项复核后，用上述 --ack 码显式确认再继续；")
    lines.append("确认动作会被记录进快照清单（谁在什么时间接受了哪项异常）。")
    return "\n".join(lines)


def require_ack(anomalies: list[dict], acknowledged: list[str] | set) -> list[dict]:
    """返回未被确认的异常；有则调用方应停止（或抛 AnomalyError）。"""
    ack = set(acknowledged or [])
    unknown = ack - set(ANOMALY_CODES)
    if unknown:
        raise ValueError(f"unknown ack codes: {sorted(unknown)}")
    return [a for a in anomalies if a["code"] not in ack]
