"""证据账本 + 结论‑证据绑定 + 引文格式化（文档 §4.4 + redesign-decisions.md D5）。

合并版（Plan A 整合）
--------------------
以 mike 双工作流（materials + research）的全部证据种类为基底，吸收 novus 的
三级信任模型（fact / judgment）：

- **fact 级**（含 research 的 note/analysis/factcheck/draft/review/evaluation）
  可进结论；
- **judgment 级**（query_generation/relevance/anomaly）不得进结论，且被排除项
  全额留痕，使模型筛选可复核、可反驳；
- ``__init__`` 支持 ``root`` 形参（mike ``research.py`` 依赖，用于定位
  ``<root>/data/literature.json``）；
- 旧记录无 ``tier`` 字段时默认视为 fact（向后兼容）；
- ``link_conclusion`` 强制仅 fact 级证据可支撑结论（三级信任模型红线）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

from .util import sha256_file


class EvidenceError(RuntimeError):
    pass


TIER_FACT = "fact"
TIER_JUDGMENT = "judgment"

#: fact 级证据类型（可进结论）：materials 6 型 + research 6 型
FACT_KINDS = (
    "literature", "data", "experiment", "figure", "verification", "report",
    "note", "analysis", "factcheck", "draft", "review", "evaluation",
)

#: judgment 级判断类型（不得进结论）
JUDGMENT_KINDS = ("query_generation", "relevance", "anomaly")

#: 合法证据/判断类型全集（append_evidence 接受全部）
EVIDENCE_KINDS = FACT_KINDS + JUDGMENT_KINDS


def _tier_of_kind(kind: str) -> str:
    """按种类判定 tier：judgment 三类走 judgment，其余默认 fact。"""
    return TIER_JUDGMENT if kind in JUDGMENT_KINDS else TIER_FACT


def _sha256_file(path: str) -> str:
    """证据文件哈希：缺失抛域错误 EvidenceError（区别于裸 FileNotFoundError）。"""
    if not os.path.exists(path):
        raise EvidenceError(f"evidence file missing: {path}")
    return sha256_file(path)


# ---- 账本哈希链（M3：防篡改检测）----
# 每条记录携带 chain_hash = SHA-256(prev_chain_hash || 规范化记录体)，形成 append-only
# 单向链。任意记录被篡改（未同步重算链）都会被 verify_chain() 检出。注意：哈希链用于
# *检测*篡改并支持独立审计，不能抵御"完全控制文件系统、可整体重算链"的本地攻击者——
# 其价值在于让伪造在可被比对的可信基线前无所遁形（配合 M2 验证完整性闸门）。
_CHAIN_ZERO = "0" * 64


def _chain_hash(prev: str, rec: dict) -> str:
    payload = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"))
    return hashlib.sha256((prev + "|" + payload).encode("utf-8")).hexdigest()


class ProvenanceLedger:
    def __init__(self, run_dir: str, run_id: str = "", root: str = ""):
        self.run_dir = run_dir
        self.run_id = run_id
        self.root = root            # 项目根（用于定位 data/literature.json）；空则回退全局
        self.path = os.path.join(run_dir, "provenance.jsonl")
        self.conclusions_path = os.path.join(run_dir, "conclusions.jsonl")
        self._ev_index: dict[str, dict] = {}
        self._chain_hash = _CHAIN_ZERO
        self._next_num = 1
        self._load_existing()

    def _load_existing(self) -> None:
        """加载已持久化账本（MAINT-9：尾部崩溃残留自愈 + 中间坏行响亮失败）。

        进程崩溃于 append 中途会在文件尾部留下半行 JSON，此前直接让
        ``json.loads`` 抛错——cite/status/append 全部不可用。现按方案 C：

        - **尾部残留自愈**：坏行之后无任何有效记录 → 视为 append 中断残留
          （残留不是账本记录，丢弃等价自愈），把文件截断到残留行起点，
          保留之前的全部有效记录；stderr 一行告警（不污染 stdout 的机器
          可读 JSON）。自愈后文件回到"全行有效"，load / verify_chain /
          append 三方语义一致，且消除"下次 append 拼接到半行上"的隐患。
        - **中间坏行响亮失败**：坏行之后仍有有效记录 → 抛 EvidenceError，
          与 ``verify_chain`` 的防篡改哲学一致（疑似篡改或磁盘问题）。
        """
        if not os.path.exists(self.path):
            return
        # 一次读入全部字节并逐行记录（起始字节偏移, 原始行）。账本行数有限；
        # 用字节偏移而非文本偏移，避免 UTF-8 多字节字符上截断点错位。
        with open(self.path, "rb") as f:
            data = f.read()
        entries: list[tuple[int, bytes]] = []
        offset = 0
        for chunk in data.splitlines(keepends=True):
            entries.append((offset, chunk))
            offset += len(chunk)

        records: list[tuple[int, dict]] = []       # (lineno, rec)
        bad_lines: list[tuple[int, int, str]] = []  # (lineno, byte_offset, err)
        last_valid_idx = -1                         # 最后一个有效行的条目下标
        for idx, (line_off, chunk) in enumerate(entries):
            lineno = idx + 1
            text = chunk.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                rec = json.loads(text)
                if not isinstance(rec, dict) or "ev_id" not in rec:
                    raise ValueError("record is not an object with ev_id")
            except (json.JSONDecodeError, ValueError) as e:
                bad_lines.append((lineno, line_off, str(e)))
                continue
            records.append((lineno, rec))
            last_valid_idx = idx

        # 尾部坏行 = 位置在最后一个有效行之后的坏行（其后无有效记录跟随）
        tail_bad = [b for b in bad_lines if b[0] > last_valid_idx + 1]
        if bad_lines:
            if tail_bad:
                cut = tail_bad[0][1]  # 首个尾部坏行的字节偏移（= 有效记录终点）
                truncated = len(data) - cut
                # 自愈截断：同一文件以 'r+b' 重开 truncate（读句柄已关闭，
                # Windows 下无句柄竞争）；截断点之前的有效记录原样保留。
                with open(self.path, "r+b") as f:
                    f.truncate(cut)
                    f.flush()
                print(f"[paper-agent] 警告：证据账本尾部发现崩溃残留"
                      f"（append 中断的半行 JSON），已截断自愈 {truncated} 字节"
                      f"（自第 {tail_bad[0][0]} 行起）：{self.path}",
                      file=sys.stderr)
            else:
                lineno = bad_lines[0][0]
                raise EvidenceError(
                    f"证据账本第 {lineno} 行损坏且其后仍有有效记录"
                    f"（疑似篡改或磁盘问题，拒绝加载）: {self.path}")

        for _lineno, rec in records:
            self._ev_index[rec["ev_id"]] = rec
            # 推进哈希链到已持久化记录的链尾（旧记录无 chain_hash 则不推进）
            if rec.get("chain_hash"):
                self._chain_hash = rec["chain_hash"]
        self._next_num = self._recompute_next_num()

    def _recompute_next_num(self) -> int:
        """从已加载索引重算下一个 ev 序号（仅 load 时 O(n) 一次）。"""
        nums = [int(re.sub(r"\D", "", k)) for k in self._ev_index
                if k.startswith("EV-")]
        return (max(nums) + 1) if nums else 1

    @property
    def next_ev_num(self) -> int:
        """下一个证据序号（缓存值；append 时 O(1) 递增，避免每次全表重算）。"""
        return self._next_num

    def append_evidence(
        self,
        kind: str,
        ref: str,
        producer_step: str,
        meta: dict | None = None,
        file_path: str | None = None,
    ) -> str:
        """登记一条证据（fact 或 judgment tier 由种类决定），返回 ev_id。

        kind 见 ``EVIDENCE_KINDS``。judgment 三类（query_generation/relevance/
        anomaly）会落为 judgment tier，但仍可被本方法登记（等价于 append_judgment
        的宽松入口）。
        """
        if kind not in EVIDENCE_KINDS:
            raise EvidenceError(f"unknown evidence kind: {kind}")
        return self._append(_tier_of_kind(kind), kind, ref,
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
        rationale:     判断理由（便于复核）
        """
        if judgment_kind not in JUDGMENT_KINDS:
            raise EvidenceError(
                f"unknown judgment kind: {judgment_kind} "
                f"(expect one of {JUDGMENT_KINDS})")
        merged = dict(meta or {})
        merged.update({"subject": subject, "verdict": verdict,
                       "rationale": rationale})
        return self._append(TIER_JUDGMENT, judgment_kind, subject,
                            producer_step=producer_step, meta=merged,
                            file_path=None)

    def _append(self, tier: str, kind: str, ref: str, producer_step: str,
                meta: dict | None, file_path: str | None) -> str:
        """统一落盘：分配 ev_id、计算文件哈希与链哈希、append-only 写入。"""
        sha = _sha256_file(file_path) if file_path else ""
        ev_id = f"EV-{self._next_num:04d}"
        self._next_num += 1
        rec = {
            "ev_id": ev_id,
            "tier": tier,
            "kind": kind,
            "ref": ref,
            "sha256": sha,
            "producer_step": producer_step,
            "meta": meta or {},
        }
        # 哈希链：链头 = SHA-256(前一条链哈希 || 规范化记录体)
        rec["chain_hash"] = _chain_hash(self._chain_hash, rec)
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        self._chain_hash = rec["chain_hash"]
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
        """绑定结论与证据。三级信任模型红线：judgment 不得支撑结论。

        校验：① 非空 ② 全部存在 ③ **全部为 fact 级**。
        """
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
        "判断留痕"成为报告生成的硬前置。
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

    def verify_chain(self) -> list[str]:
        """重放账本哈希链，检测记录篡改。返回问题列表，空列表 = 链完整。

        防御 M3：账本原为无签名的明文 append-only 文件，任何有写权限者可改写。
        现在每条记录携带 chain_hash = SHA-256(prev_chain_hash || 规范化记录体)，
        修改任意记录而未同步重算全链即被检出。注意：哈希链是**检测**机制，
        不能阻止完全控制文件系统者整体重算——其价值在于让篡改在独立审计
        （配合 M2 验证完整性闸门）面前可被发现。
        """
        if not os.path.exists(self.path):
            return []
        problems: list[str] = []
        prev = _CHAIN_ZERO
        with open(self.path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    problems.append(f"line {lineno}: not valid JSON ({e})")
                    continue
                stored = rec.get("chain_hash")
                if not stored:
                    # 旧版记录（无链字段）——跳过校验，保持向后兼容
                    continue
                body = {k: v for k, v in rec.items() if k != "chain_hash"}
                expect = _chain_hash(prev, body)
                if expect != stored:
                    problems.append(f"line {lineno} ({rec.get('ev_id', '?')}): "
                                    f"chain hash mismatch (record tampered)")
                prev = stored
        return problems

    def _literature_lookup(self, doi: str) -> dict | None:
        """从文献语料取元数据（作者/年份/标题）。

        优先用本 run 所属项目根下的 ``<root>/data/literature.json``；
        未指定 root 时回退到全局 ``DATA_DIR``。
        """
        try:
            from paper_agent import DATA_DIR
            base = os.path.join(self.root, "data") if self.root else DATA_DIR
            lit = os.path.join(base, "literature.json")
            if not os.path.exists(lit):
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
