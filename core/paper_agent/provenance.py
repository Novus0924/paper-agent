"""证据账本 + 结论‑证据绑定 + 引文格式化（文档 §4.4 + redesign-decisions.md D5）。

三级信任模型（tier）：
- **fact（事实）**：来自外部数据源或本地确定性计算的数值/元数据 → **唯一可进结论者**
- **judgment（判断）**：模型产生的检索式、相关性裁决与理由 → 仅影响流程走向，
  不得进结论，且**含被排除项**全额留痕（使筛选可复核、可反驳）
- **conclusion（结论）**：由确定性程序从 fact 推导，必须绑定 fact 级证据编号
  （存于 conclusions.jsonl，不占用 EV 编号）

账本要点：
- provenance.jsonl 每行一条记录，append-only；ev_id 自增 EV-0001...（单一编号空间）
- 旧记录无 ``tier`` 字段时默认视为 fact（向后兼容）
- link_conclusion(cid, text, evidence_ids) 前置校验：
  ① 非空 ② 全部存在 ③ **全部为 fact 级**（judgment 不得支撑结论）
- cite(ev_id) 返回人类可读引用：文献类输出 DOI/作者/年份；文件类输出 sha256 前16位；
  判断类输出裁决主体 + 结论 + 理由
"""
from __future__ import annotations

import hashlib
import json
import os
import re

# ---- 三级信任模型常量 ----

TIER_FACT = "fact"
TIER_JUDGMENT = "judgment"

#: fact 级证据类型（可进结论）
FACT_KINDS = ("literature", "data", "experiment", "figure", "verification", "report")

#: judgment 级判断类型（不得进结论）
JUDGMENT_KINDS = ("query_generation", "relevance", "anomaly")


class EvidenceError(RuntimeError):
    pass


def _sha256_file(path: str) -> str:
    if not os.path.exists(path):
        raise EvidenceError(f"evidence file missing: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ProvenanceLedger:
    def __init__(self, run_dir: str, run_id: str = ""):
        self.run_dir = run_dir
        self.run_id = run_id
        self.path = os.path.join(run_dir, "provenance.jsonl")
        self.conclusions_path = os.path.join(run_dir, "conclusions.jsonl")
        self._ev_index: dict[str, dict] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self._ev_index[rec["ev_id"]] = rec

    @property
    def next_ev_num(self) -> int:
        nums = [int(re.sub(r"\D", "", k)) for k in self._ev_index if k.startswith("EV-")]
        return (max(nums) + 1) if nums else 1

    def append_evidence(
        self,
        kind: str,
        ref: str,
        producer_step: str,
        meta: dict | None = None,
        file_path: str | None = None,
    ) -> str:
        """登记一条 **fact 级**证据，返回 ev_id。

        kind: literature|data|experiment|figure|verification|report
        """
        if kind not in FACT_KINDS:
            raise EvidenceError(
                f"unknown fact kind: {kind} (expect one of {FACT_KINDS})")
        return self._append(tier=TIER_FACT, kind=kind, ref=ref,
                            producer_step=producer_step, meta=meta,
                            file_path=file_path)

    def append_judgment(
        self,
        judgment_kind: str,
        producer_step: str,
        subject: str,
        verdict: str,
        rationale: str = "",
        meta: dict | None = None,
    ) -> str:
        """登记一条 **judgment 级**判断，返回 ev_id。

        判断只影响流程走向，**不得**被 link_conclusion 引用。

        judgment_kind: query_generation|relevance|anomaly
        subject:       判断对象（检索式文本 / 论文 DOI 或标题 / 异常名）
        verdict:       裁决（如 generated|relevant|excluded|raised）
        rationale:     判断理由（必填语义上要求非空，便于复核；此处不强制）
        """
        if judgment_kind not in JUDGMENT_KINDS:
            raise EvidenceError(
                f"unknown judgment kind: {judgment_kind} "
                f"(expect one of {JUDGMENT_KINDS})")
        merged = dict(meta or {})
        merged.update({"subject": subject, "verdict": verdict,
                       "rationale": rationale})
        return self._append(tier=TIER_JUDGMENT, kind=judgment_kind, ref=subject,
                            producer_step=producer_step, meta=merged,
                            file_path=None)

    def _append(self, tier: str, kind: str, ref: str, producer_step: str,
                meta: dict | None, file_path: str | None) -> str:
        """统一落盘：分配 ev_id、计算哈希、append-only 写入。"""
        sha = _sha256_file(file_path) if file_path else ""
        ev_id = f"EV-{self.next_ev_num:04d}"
        rec = {
            "ev_id": ev_id,
            "tier": tier,
            "kind": kind,
            "ref": ref,
            "sha256": sha,
            "producer_step": producer_step,
            "meta": meta or {},
        }
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        self._ev_index[ev_id] = rec
        return ev_id

    @staticmethod
    def tier_of(rec: dict) -> str:
        """读取记录的 tier；旧记录无该字段时视为 fact（向后兼容）。"""
        return rec.get("tier", TIER_FACT)

    def get(self, ev_id: str) -> dict | None:
        return self._ev_index.get(ev_id)

    def has(self, ev_id: str) -> bool:
        return ev_id in self._ev_index

    def link_conclusion(
        self,
        conclusion_id: str,
        text: str,
        evidence_ids: list[str],
    ) -> None:
        """绑定结论与**事实**证据。三级信任模型红线：judgment 不得支撑结论。"""
        if not evidence_ids:
            raise EvidenceError(f"conclusion {conclusion_id} has no evidence binding")
        for ev in evidence_ids:
            if ev not in self._ev_index:
                raise EvidenceError(f"conclusion {conclusion_id} references unknown evidence {ev}")
            tier = self.tier_of(self._ev_index[ev])
            if tier != TIER_FACT:
                raise EvidenceError(
                    f"conclusion {conclusion_id} binds {ev} of tier '{tier}': "
                    f"only '{TIER_FACT}' evidence may back a conclusion")
        rec = {
            "cid": conclusion_id,
            "text": text,
            "evidence_ids": list(evidence_ids),
        }
        with open(self.conclusions_path, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    # ---------- 分级视图 ----------

    def _sorted_ids(self) -> list[str]:
        return sorted(self._ev_index,
                      key=lambda x: int(re.sub(r"\D", "", x)))

    def facts(self) -> list[dict]:
        """全部 fact 级记录（唯一可进结论者）。"""
        return [self._ev_index[k] for k in self._sorted_ids()
                if self.tier_of(self._ev_index[k]) == TIER_FACT]

    def judgments(self) -> list[dict]:
        """全部 judgment 级记录。"""
        return [self._ev_index[k] for k in self._sorted_ids()
                if self.tier_of(self._ev_index[k]) == TIER_JUDGMENT]

    def excluded_judgments(self) -> list[dict]:
        """被模型排除的条目（verdict == excluded）——筛选必须可复核、可反驳。"""
        return [r for r in self.judgments()
                if (r.get("meta") or {}).get("verdict") == "excluded"]

    def require_judgment_batch(self) -> None:
        """校验账本中存在判断记录；缺失即快速失败。

        对应判据 4：删除模型判断记录后，报告必须生成失败——使
        "判断留痕"成为报告生成的硬前置，而不是"记了但没人用"。
        """
        if not self.judgments():
            raise EvidenceError(
                "no judgment records in ledger: report cannot be generated "
                "(model filtering must be traceable)")

    def check_binding_invariants(self) -> list[str]:
        """审计不变量检查：返回问题列表，空列表表示全部通过。

        ① conclusions.jsonl 每条 evidence_ids 必须全部存在
        ② 且必须全部为 fact 级
        """
        problems: list[str] = []
        path = self.conclusions_path
        if not os.path.exists(path):
            return problems
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                cid = rec.get("cid", f"<line {lineno}>")
                ids = rec.get("evidence_ids") or []
                if not ids:
                    problems.append(f"{cid}: no evidence binding")
                    continue
                for ev in ids:
                    if ev not in self._ev_index:
                        problems.append(f"{cid}: unknown evidence {ev}")
                        continue
                    tier = self.tier_of(self._ev_index[ev])
                    if tier != TIER_FACT:
                        problems.append(f"{cid}: non-fact evidence {ev} (tier={tier})")
        return problems

    def _literature_lookup(self, doi: str) -> dict | None:
        """从 data/literature.json 取文献元数据（作者/年份/标题）。"""
        try:
            from paper_agent import DATA_DIR
            lit = os.path.join(DATA_DIR, "literature.json")
            with open(lit, "r", encoding="utf-8") as f:
                corpus = json.load(f)
            for doc in corpus.get("documents", []):
                if doc.get("doi") == doi:
                    return doc
        except Exception:
            return None
        return None

    def cite(self, ev_id: str) -> str:
        """人类可读引用。文献类：DOI+作者+年份；文件类：sha256 前16位；
        判断类：裁决主体 + 结论 + 理由。"""
        rec = self._ev_index.get(ev_id)
        if rec is None:
            raise EvidenceError(f"cannot cite unknown evidence {ev_id}")
        if self.tier_of(rec) == TIER_JUDGMENT:
            meta = rec.get("meta") or {}
            reason = (meta.get("rationale") or "").strip() or "(未给理由)"
            return (f"[{ev_id}] judgment({rec['kind']}) "
                    f"subject={meta.get('subject') or rec['ref']} "
                    f"verdict={meta.get('verdict')} reason={reason} "
                    f"by={rec['producer_step']}")
        if rec["kind"] == "literature":
            doc = self._literature_lookup(rec["ref"])
            if doc:
                authors = ", ".join(doc.get("authors", [])) or "unknown author"
                return (f"[{ev_id}] {authors} ({doc.get('year')}). "
                        f"{doc.get('title')}. {doc.get('venue')}. "
                        f"DOI: {doc.get('doi')}")
            return f"[{ev_id}] DOI: {rec['ref']}"
        sha16 = (rec.get("sha256") or "")[:16]
        return f"[{ev_id}] {rec['kind']} artifact ref={rec['ref']} sha256={sha16}"

    def all_evidence(self) -> list[dict]:
        return [self._ev_index[k] for k in self._sorted_ids()]
