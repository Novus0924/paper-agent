"""证据账本 + 结论‑证据绑定 + 引文格式化（文档 §4.4）。

- provenance.jsonl 每行一条证据，append-only；ev_id 自增 EV-0001...
- link_conclusion(cid, text, evidence_ids) 前置校验所有 evidence_id 已存在，
  否则快速失败（结论‑证据强绑定）
- cite(ev_id) 返回人类可读引用：文献类输出 DOI/作者/年份；文件类输出 sha256 前16位
- 任何报告中出现的结论必须至少绑定一条证据 ID
"""
from __future__ import annotations

import hashlib
import json
import os
import re


class EvidenceError(RuntimeError):
    pass


# 合法证据类型（materials 流水线 + research 全流程）
EVIDENCE_KINDS = (
    # materials（P1..P5）
    "literature", "data", "experiment", "figure", "verification", "report",
    # research（R1..R6）
    "note", "analysis", "factcheck", "draft", "review", "evaluation",
)


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
        """登记一条证据，返回 ev_id。kind 见 ``EVIDENCE_KINDS``。"""
        sha = _sha256_file(file_path) if file_path else ""
        if kind not in EVIDENCE_KINDS:
            raise EvidenceError(f"unknown evidence kind: {kind}")
        ev_id = f"EV-{self.next_ev_num:04d}"
        rec = {
            "ev_id": ev_id,
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
        if not evidence_ids:
            raise EvidenceError(f"conclusion {conclusion_id} has no evidence binding")
        for ev in evidence_ids:
            if ev not in self._ev_index:
                raise EvidenceError(f"conclusion {conclusion_id} references unknown evidence {ev}")
        rec = {
            "cid": conclusion_id,
            "text": text,
            "evidence_ids": list(evidence_ids),
        }
        with open(self.conclusions_path, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

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
        """人类可读引用。文献类：DOI+作者+年份；文件类：sha256 前16位。"""
        rec = self._ev_index.get(ev_id)
        if rec is None:
            raise EvidenceError(f"cannot cite unknown evidence {ev_id}")
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
        return [self._ev_index[k] for k in sorted(self._ev_index, key=lambda x: int(re.sub(r"\D", "", x)))]
