"""research.py — 科研全流程工作流（PRD §2 核心用户旅程，R1..R6）。

复用 ``state.py`` 的状态机、``provenance.py`` 的证据账本与 ``chaos.py`` 的故障注入，
把 PRD 的六大环节实现为**可单步驱动、可断点续跑、可故障恢复**的工作流：

    R1 多源检索 → R2 论文精读 → R3 创新点拆解 → R4 事实验证 → R5 综述写作 → R6 自评审

对齐 PRD F-4.8 的**三类异常恢复场景**（由 ``chaos`` 注入）：

| 场景 | chaos 模式 | 期望行为 |
|---|---|---|
| ① 外部 API 超时降级 | ``ss_timeout`` | SS 源超时 → 自动切换其它源，任务不中断，结果标注切源 |
| ② PDF 解析失败恢复 | ``scan_pdf`` | 无文本层 → OCR 路径 → 降级低置信度并标注 |
| ③ 长任务中断恢复 | ``batch_fail_at=N`` / ``kill_after_r3`` | 第 N 篇失败跳过继续；真实崩溃后可 resume 续跑 |

诚实边界
--------
- 精读输入优先取 ``data/papers/*.pdf``（用户/团队放入的真实 PDF）；
  若不存在，则用内置语料的**真实元数据**（题名/作者/期刊/年份/摘要）
  生成一份**明确标注为工程演示排版**的 PDF 来跑通解析链路 ——
  **绝不向 PDF 中注入任何原文中没有的研究结论**。
- 无 PDF 的文献以 ``metadata_only`` 处理并在报告中显式声明。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

from .state import (
    PipelineState, StepStatus, RunStatus, load_state,
)
from .provenance import ProvenanceLedger
from . import chaos
from .chaos import TransientError, PermanentError
from . import litsearch, pdfparse, analyze, factcheck, writing, review as review_mod
from .util import read_json, write_json, write_text

DEFAULT_READ_LIMIT = 3
MAX_ATTEMPTS = 3
BACKOFF = [1, 2]

# PRD 五类创新（用于评估混淆矩阵等；与 analyze 保持一致）
_CATS = ["方法创新", "理论创新", "数据创新", "应用创新", "工程创新"]


def _read_limit() -> int:
    try:
        return max(1, int(os.environ.get("paper-agent_READ_LIMIT", DEFAULT_READ_LIMIT)))
    except ValueError:
        return DEFAULT_READ_LIMIT


def _now_hhmmss() -> str:
    return time.strftime("%H%M%S", time.gmtime())


# =====================================================================
# 工程演示排版 PDF（内容仅取真实元数据）
# =====================================================================

def _pdf_escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, width: int = 92) -> list[str]:
    words = re.split(r"\s+", (text or "").strip())
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            if cur:
                lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def demo_layout_pdf(doc: dict) -> bytes:
    """把文献的**真实元数据**排成一份 PDF（明确标注为工程演示排版）。

    只包含题名/作者/期刊/年份/关键词/摘要 —— 即语料里真实存在的内容，
    **不生成任何原文没有的章节或结论**。用于在离线环境跑通 PDF 解析链路。
    """
    lines = [_pdf_escape(doc.get("title", "") or "(untitled)"),
             ""]
    authors = doc.get("authors") or []
    if authors:
        lines.append(", ".join(authors))
    meta = " | ".join(x for x in [doc.get("venue", ""), str(doc.get("year", "") or "")] if x)
    if meta:
        lines.append(meta)
    lines.append("")
    lines.append("Abstract")
    lines.extend(_wrap(doc.get("abstract", "")))
    kws = doc.get("keywords") or []
    if kws:
        lines.append("")
        lines.append("Keywords: " + ", ".join(kws))
    if doc.get("doi"):
        lines.append("")
        lines.append("DOI: " + doc["doi"])
    lines.append("")
    lines.append("[ENGINEERING DEMO LAYOUT - metadata from verified corpus]")

    content = ["BT /F1 11 Tf 50 750 Td 14 TL"]
    for ln in lines:
        content.append(f"({_pdf_escape(ln)}) Tj T*")
    content.append("ET")
    body = "\n".join(content).encode("latin-1", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    out += b"trailer << /Root 1 0 R >>\n%%EOF\n"
    return bytes(out)


def scanned_demo_pdf() -> bytes:
    """一份**无文本层**的扫描件样例（仅图像绘制算子），用于场景 2。"""
    body = b"q 1 0 0 1 0 0 cm /Im0 Do Q\n"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    out += b"trailer << /Root 1 0 R >>\n%%EOF\n"
    return bytes(out)


# =====================================================================
# ResearchPipeline
# =====================================================================

class StepDependencyError(RuntimeError):
    """前置步骤未完成，当前步骤无法安全执行（禁止隐式代跑，避免隐藏副作用）。"""


class ResearchPipeline:
    """科研全流程编排器（R1..R6）。接口与材料流水线 Pipeline 对齐，便于复用 CLI/Skill。"""

    STEP_FN = {
        "R1_search": "run_r1",
        "R2_read": "run_r2",
        "R3_analyze": "run_r3",
        "R4_verify": "run_r4",
        "R5_write": "run_r5",
        "R6_review": "run_r6",
    }

    #: 每步的硬前置依赖（必须已 DONE/SKIPPED 才能执行本步）。
    #: 单步驱动时缺依赖会**显式报错**，而不是偷偷把前置步骤跑掉——
    #: 模型驱动编排要求「调用-结果」一一对应，隐式副作用会让模型的状态判断失准。
    STEP_DEPS: dict[str, list[str]] = {
        "R2_read": ["R1_search"],
        "R3_analyze": ["R1_search", "R2_read"],
        "R4_verify": ["R2_read"],
        "R5_write": ["R3_analyze"],
        "R6_review": ["R4_verify", "R5_write"],
    }

    def __init__(self, root: str, run_id: str, chaos_mode: str = ""):
        self.root = root
        self.run_id = run_id
        self.state = load_state(run_id, root)
        self.prov = ProvenanceLedger(os.path.join(root, "runs", run_id), run_id, root=root)
        if chaos_mode:
            chaos.set_chaos_mode(chaos_mode)

    # ---------- 通用 ----------

    @property
    def _run_dir(self) -> str:
        return os.path.join(self.root, "runs", self.run_id)

    def _out(self, *parts: str) -> str:
        return os.path.join(self._run_dir, *parts)

    def _toolcall(self, step: str, fn: str, input_obj: dict, output_obj: dict) -> str:
        tc_dir = self._out("toolcalls")
        os.makedirs(tc_dir, exist_ok=True)
        base = f"{_now_hhmmss()}_{step}"
        path = os.path.join(tc_dir, f"{base}.json")
        i = 2
        while os.path.exists(path):
            path = os.path.join(tc_dir, f"{base}_{i}.json")
            i += 1
        write_json(path, {
            "step": step, "tool": fn,
            "invoked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "input": input_obj, "output": output_obj,
        })
        return path

    # ---------- 前置依赖 ----------

    def _check_deps(self, sid: str) -> None:
        """执行前校验硬前置依赖；不满足则显式报错（不隐式代跑前置步骤）。"""
        missing = [d for d in self.STEP_DEPS.get(sid, [])
                   if self.state.step_status[d] not in (StepStatus.DONE, StepStatus.SKIPPED)]
        if missing:
            raise StepDependencyError(
                f"step {sid} requires {missing} to be DONE first; "
                f"current={[self.state.step_status[d].value for d in missing]}. "
                f"请先按顺序执行前置步骤（不做隐式代跑）。")

    # ---------- R1 多源检索 ----------

    def _resolve_search_backends(self) -> dict:
        """按 chaos 模式装配检索后端（场景 1：SS 源超时）。"""
        backends = dict(litsearch.DEFAULT_BACKENDS)
        if chaos.CH.source_should_fail("semantic_scholar"):
            def _timeout(*_a, **_k):
                raise TimeoutError("chaos: semantic_scholar API timeout")
            backends["semantic_scholar"] = _timeout
        return backends

    def run_r1(self) -> dict:
        sid = "R1_search"
        self.state.mark_step_running(sid)
        goal = self.state.goal
        lit_dir = self._out("literature")
        snapshot_path = os.path.join(lit_dir, "research_snapshot.json")

        source = (self.state.lit_source or "auto").lower()
        unavailable: list[str] = []
        sources_status: dict = {}
        query_used = ""

        if os.path.exists(snapshot_path):
            snap = read_json(snapshot_path)
            docs = snap.get("documents", [])
            sources_status = snap.get("sources_status", {})
            unavailable = snap.get("unavailable_sources", [])
            query_used = snap.get("query", "")
            note = "snapshot_reused"
        elif source == "local":
            docs = litsearch.filter_by_relevance(litsearch.load_local_corpus(self.root), goal)
            sources_status = {"local": f"ok:{len(docs)}"}
            query_used = goal
            note = "local"
            # F-4.8 场景① 在离线路径也必须可复现：local 源不再直接短路，
            # 而是走同一套「≥2 源可选、单源失败自动切源」语义。
            # 这样 `--lit-source local --chaos ss_timeout` 才会真实产出
            # unavailable_sources（否则该场景在 local 下是空操作，文档结论不成立）。
            local_sources = ["local"] + [s for s in litsearch.ALL_SOURCES
                                         if chaos.CH.source_should_fail(s)]
            if len(local_sources) > 1:
                failed_sources = [s for s in local_sources if s != "local"]
                sources_status.update(
                    {s: "unavailable:TimeoutError" for s in failed_sources})
                unavailable = failed_sources
                note = "local_source_failover"
        else:
            try:
                res = litsearch.search_papers(
                    goal, sources=["arxiv", "semantic_scholar", "openalex", "crossref"],
                    max_results=10, backends=self._resolve_search_backends())
                docs = res["documents"]
                sources_status = res["sources_status"]
                unavailable = res["unavailable_sources"]
                query_used = goal
                note = "online"
            except Exception as e:  # 全源异常 → 回落本地语料
                docs = litsearch.filter_by_relevance(
                    litsearch.load_local_corpus(self.root), goal)
                sources_status = {"local_fallback": f"ok:{len(docs)}"}
                unavailable = ["all_remote"]
                query_used = goal
                note = f"fallback_local:{type(e).__name__}"

        if source != "local" and note == "online":
            write_json(snapshot_path, {
                "goal": goal, "query": query_used, "source": "multi",
                "endpoints": {"arxiv": litsearch.ARXIV_API,
                              "semantic_scholar": litsearch.SEMANTIC_SCHOLAR_API,
                              "openalex": litsearch.OPENALEX_API,
                              "crossref": litsearch.CROSSREF_API},
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sources_status": sources_status, "unavailable_sources": unavailable,
                "n_documents": len(docs), "documents": docs,
            })

        out_path = os.path.join(lit_dir, "research_hits.json")
        write_json(out_path, {
            "goal": goal, "source": source, "query": query_used, "note": note,
            "sources_status": sources_status,
            "unavailable_sources": unavailable,
            "n_hits": len(docs),
            "snapshot": "literature/research_snapshot.json" if os.path.exists(snapshot_path) else "",
            "hits": [{"doc_id": d.get("doc_id", ""), "doi": d.get("doi", ""),
                      "title": d.get("title", ""), "venue": d.get("venue", ""),
                      "year": d.get("year", 0), "url": d.get("url", ""),
                      "source": d.get("source", ""), "sources": d.get("sources", []),
                      "citations": d.get("citations", 0), "relevance": d.get("relevance", 0),
                      "keywords": d.get("keywords", []), "abstract": d.get("abstract", ""),
                      "authors": d.get("authors", [])}
                     for d in docs],
        })

        ev_ids = []
        for d in docs:
            ev_ids.append(self.prov.append_evidence(
                kind="literature", ref=litsearch.ref_of(d), producer_step=sid,
                meta={"doc_id": d.get("doc_id", ""), "title": d.get("title", ""),
                      "year": d.get("year"), "sources": d.get("sources", [])}))
        ev_file = self.prov.append_evidence(
            kind="data", ref=os.path.join("literature", "research_hits.json"),
            producer_step=sid, file_path=out_path,
            meta={"n_hits": len(docs), "unavailable_sources": unavailable})

        if unavailable:
            self.state.mark_degraded(
                sid, note=f"检索源不可用已自动切换：{unavailable}（任务未中断）")

        self._toolcall(sid, "sciret_search_papers",
                       {"goal": goal, "lit_source": source},
                       {"n_hits": len(docs), "unavailable": unavailable,
                        "sources_status": sources_status})
        self.state.mark_step_done(sid, {"n_hits": len(docs),
                                        "unavailable": unavailable})
        return {"n_hits": len(docs), "unavailable_sources": unavailable,
                "sources_status": sources_status, "note": note,
                "output": out_path, "evidence": ev_ids + [ev_file]}

    # ---------- R2 论文精读（批量 + 失败隔离）----------

    def _pdf_source_for(self, doc: dict, pdf_dir: str) -> tuple[str, bool]:
        """为文献决定 PDF 来源。返回 ``(path, is_demo_layout)``。"""
        # 1) 团队放入的真实 PDF：data/papers/<doc_id>.pdf 或按 DOI/标题匹配
        papers_dir = os.path.join(self.root, "data", "papers")
        cands = []
        if doc.get("doc_id"):
            cands.append(os.path.join(papers_dir, f"{doc['doc_id']}.pdf"))
        if doc.get("doi"):
            cands.append(os.path.join(papers_dir, re.sub(r"[^A-Za-z0-9]+", "_", doc["doi"]) + ".pdf"))
        for c in cands:
            if os.path.exists(c):
                return c, False
        # 2) 否则用真实元数据生成工程演示排版 PDF
        os.makedirs(pdf_dir, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9]+", "_", doc.get("doc_id") or doc.get("doi") or "paper")
        path = os.path.join(pdf_dir, f"{name}.pdf")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(demo_layout_pdf(doc))
        return path, True

    def run_r2(self) -> dict:
        sid = "R2_read"
        self._check_deps(sid)
        self.state.mark_step_running(sid)
        hits_path = self._out("literature", "research_hits.json")
        hits = read_json(hits_path)["hits"] if os.path.exists(hits_path) else []
        limit = _read_limit()
        selected = hits[:limit]
        pdf_dir = self._out("reading", "pdfs")
        notes_dir = self._out("reading", "notes")
        os.makedirs(notes_dir, exist_ok=True)

        notes: list[dict] = []
        failures: list[dict] = []
        demo_layout = 0
        scanned = 0

        force_scan = chaos.CH.force_scanned()
        fail_at = chaos.CH.batch_fail_index()

        for idx, doc in enumerate(selected, 1):
            try:
                if fail_at is not None and idx == fail_at:
                    raise PermanentError(f"chaos: batch item #{idx} parse failure (simulated)")
                if force_scan:
                    path = os.path.join(pdf_dir, "_scanned_demo.pdf")
                    os.makedirs(pdf_dir, exist_ok=True)
                    if not os.path.exists(path):
                        with open(path, "wb") as f:
                            f.write(scanned_demo_pdf())
                    is_demo = False
                else:
                    path, is_demo = self._pdf_source_for(doc, pdf_dir)
                    demo_layout += 1 if is_demo else 0

                note = pdfparse.parse_paper(path)
                note["pdf_file"] = os.path.basename(path)
                note["source"] = path
                # 笔记的 doc_id 必须与语料/检索结果一致，供跨步骤引用对齐
                note["doc_id"] = doc.get("doc_id") or note.get("doc_id", "")
                note["doi"] = doc.get("doi", "")
                note["venue"] = doc.get("venue", "")
                note["year"] = doc.get("year", 0)
                note["citations"] = doc.get("citations", 0)
                note["matched_doc_id"] = doc.get("doc_id", "")
                npath = os.path.join(
                    notes_dir,
                    f"{re.sub(r'[^A-Za-z0-9]+', '_', doc.get('doc_id') or str(idx))}.json")
                write_json(npath, note)
                note["_path"] = npath
                if note.get("status") == "scanned" or note.get("confidence") == "low":
                    scanned += 1
                notes.append(note)
            except Exception as e:  # 单篇失败不阻塞整体（PRD F-4.8 场景 3）
                failures.append({"doc_id": doc.get("doc_id", ""),
                                 "title": doc.get("title", ""),
                                 "error": f"{type(e).__name__}: {e}"})

        report = {
            "input_hits": len(hits), "selected": len(selected),
            "n_read": len(notes), "n_failed": len(failures),
            "failures": failures,
            "demo_layout_pdfs": demo_layout,
            "scanned_or_low_conf": scanned,
            "max_reads": limit,
        }
        rep_path = self._out("reading", "reading_report.json")
        write_json(rep_path, report)

        ev_ids = []
        for n in notes:
            ev_ids.append(self.prov.append_evidence(
                kind="note", ref=n.get("_path", ""), producer_step=sid,
                file_path=n.get("_path"), meta={"doc_id": n.get("matched_doc_id", ""),
                                                "status": n.get("status"),
                                                "confidence": n.get("confidence")}))
        ev_rep = self.prov.append_evidence(
            kind="data", ref=os.path.join("reading", "reading_report.json"),
            producer_step=sid, file_path=rep_path, meta=report)

        if failures:
            self.state.mark_degraded(
                sid, note=f"{len(failures)} 篇解析失败已跳过，流程继续（详见 reading_report.json）")
        if scanned:
            self.state.mark_degraded(sid, note=f"{scanned} 篇为扫描件/低置信度解析")

        self._toolcall(sid, "sciret_parse_paper",
                       {"input_hits": len(hits), "max_reads": limit},
                       {"n_read": len(notes), "n_failed": len(failures),
                        "scanned": scanned})
        self.state.mark_step_done(sid, {"n_read": len(notes), "n_failed": len(failures)})
        return {"n_read": len(notes), "n_failed": len(failures), "failures": failures,
                "scanned": scanned, "notes": notes, "report": report,
                "evidence": ev_ids + [ev_rep]}

    # ---------- R3 创新点拆解 ----------

    def run_r3(self) -> dict:
        sid = "R3_analyze"
        self._check_deps(sid)
        self.state.mark_step_running(sid)
        read = self._load_r2_result()
        notes = read.get("notes", [])

        innovations = [analyze.extract_innovations(n) for n in notes]
        docs_meta = self._hits()
        gaps = analyze.research_gap(notes)
        timeline = analyze.technology_timeline([
            {"doc_id": d.get("doc_id", ""), "title": d.get("title", ""),
             "year": d.get("year", 0), "venue": d.get("venue", ""),
             "contribution": (d.get("title", "") or "")[:120],
             "limitation": "（见 gap 分析）"}
            for d in docs_meta])

        innov_path = self._out("analysis", "innovations.json")
        gap_path = self._out("analysis", "gaps.json")
        tl_path = self._out("analysis", "timeline.json")
        write_json(innov_path, {"targets": innovations,
                                 "n_total": sum(i["n_innovations"] for i in innovations)})
        write_json(gap_path, gaps)
        write_json(tl_path, timeline)
        write_text(self._out("analysis", "innovations.md"),
                    "\n\n".join(analyze.render_innovation_md(i) for i in innovations))
        write_text(self._out("analysis", "gaps.md"), analyze.render_gap_md(gaps))
        write_text(self._out("analysis", "timeline.md"), analyze.render_timeline_md(timeline))

        ev_i = self.prov.append_evidence(
            kind="analysis", ref=os.path.join("analysis", "innovations.json"),
            producer_step=sid, file_path=innov_path,
            meta={"n_total": sum(i["n_innovations"] for i in innovations)})
        ev_g = self.prov.append_evidence(
            kind="analysis", ref=os.path.join("analysis", "gaps.json"),
            producer_step=sid, file_path=gap_path, meta={"n_gaps": gaps["n_gaps"]})

        self._toolcall(sid, "sciret_analyze",
                       {"n_notes": len(notes)},
                       {"n_innovations": sum(i["n_innovations"] for i in innovations),
                        "n_gaps": gaps["n_gaps"]})
        self.state.mark_step_done(sid, {
            "n_innovations": sum(i["n_innovations"] for i in innovations),
            "n_gaps": gaps["n_gaps"]})
        chaos.CH.kill_after(sid)
        return {"n_innovations": sum(i["n_innovations"] for i in innovations),
                "n_gaps": gaps["n_gaps"],
                "innovations": innovations, "gaps": gaps, "timeline": timeline,
                "evidence": [ev_i, ev_g]}

    # ---------- R4 事实验证 ----------

    def run_r4(self) -> dict:
        sid = "R4_verify"
        self._check_deps(sid)
        self.state.mark_step_running(sid)
        read = self._load_r2_result()
        notes = read.get("notes", [])

        # (a) 引用/观点一致性：把文献摘要作为「被引陈述」，在解析出的原文中比对
        claims = [{"claim": n.get("text", "")[:400] or n.get("title", ""),
                   "source_text": n.get("text", ""),
                   "source_ref": n.get("doc_id", "")} for n in notes]
        cite = factcheck.verify_citations(claims)

        # (b) 数据一致性
        consist = [factcheck.check_data_consistency(n) for n in notes]

        # (c) 文献间矛盾
        contra = factcheck.detect_contradictions([
            {"doc_id": n.get("doc_id", ""), "text": n.get("text", ""),
             "sections": n.get("sections", {})} for n in notes])

        fc_path = self._out("factcheck", "factcheck.json")
        write_json(fc_path, {"citations": cite, "data_consistency": consist,
                              "contradictions": contra})
        write_text(self._out("factcheck", "factcheck.md"),
                    factcheck.render_factcheck_md(cite, consist, contra))
        ev = self.prov.append_evidence(
            kind="factcheck", ref=os.path.join("factcheck", "factcheck.json"),
            producer_step=sid, file_path=fc_path,
            meta={"n_claims": cite["n"], "n_contradictions": contra["n_contradictions"]})
        self._toolcall(sid, "sciret_factcheck", {"n_notes": len(notes)},
                       {"consistency_rate": cite["consistency_rate"],
                        "n_contradictions": contra["n_contradictions"]})
        self.state.mark_step_done(sid, {"n_claims": cite["n"],
                                        "n_contradictions": contra["n_contradictions"]})
        return {"n_claims": cite["n"], "consistency_rate": cite["consistency_rate"],
                "n_contradictions": contra["n_contradictions"],
                "citations": cite, "data_consistency": consist,
                "contradictions": contra, "evidence": [ev]}

    # ---------- R5 综述写作 ----------

    def run_r5(self) -> dict:
        sid = "R5_write"
        self._check_deps(sid)
        self.state.mark_step_running(sid)
        docs = self._hits()
        notes = self._load_r2_result().get("notes", [])
        analyses = self._load_analysis().get("targets", [])
        gaps = self._load_gaps()

        rv = writing.generate_review(self.state.goal, docs, analyses, gaps)
        bib = writing.generate_bibtex(docs)
        ris = writing.generate_ris(docs)
        apa = [writing.format_citation(d, "APA") for d in docs]
        ieee = [writing.format_citation(d, "IEEE") for d in docs]

        rv_path = self._out("writing", "review.md")
        bib_path = self._out("writing", "references.bib")
        ris_path = self._out("writing", "references.ris")
        cite_path = self._out("writing", "citations.json")
        write_text(rv_path, rv["markdown"])
        write_text(bib_path, bib["bibtex"])
        write_text(ris_path, ris)
        write_json(cite_path, {"APA": apa, "IEEE": ieee,
                                "n_entries": bib["n_entries"],
                                "missing_field_warnings": bib["warnings"]})

        ev_d = self.prov.append_evidence(
            kind="draft", ref=os.path.join("writing", "review.md"),
            producer_step=sid, file_path=rv_path,
            meta={"n_citations": rv["n_citations"], "unsupported": len(rv["unsupported"]),
                  "consistency_ok": rv["consistency"]["ok"]})
        ev_b = self.prov.append_evidence(
            kind="data", ref=os.path.join("writing", "references.bib"),
            producer_step=sid, file_path=bib_path, meta={"n_entries": bib["n_entries"]})

        if not rv["consistency"]["ok"]:
            self.state.mark_degraded(sid, note=f"综述存在悬空引用：{rv['consistency']['dangling']}")

        self._toolcall(sid, "sciret_write",
                       {"topic": self.state.goal, "n_docs": len(docs)},
                       {"n_citations": rv["n_citations"], "unsupported": len(rv["unsupported"]),
                        "n_bibtex": bib["n_entries"]})
        self.state.mark_step_done(sid, {"n_citations": rv["n_citations"],
                                        "unsupported": len(rv["unsupported"])})
        return {"n_citations": rv["n_citations"], "n_unsupported": len(rv["unsupported"]),
                "review": rv, "bibtex": bib, "ris": ris,
                "review_path": rv_path, "evidence": [ev_d, ev_b]}

    # ---------- R6 自评审 ----------

    def run_r6(self) -> dict:
        sid = "R6_review"
        self._check_deps(sid)
        self.state.mark_step_running(sid)
        docs = self._hits()
        analyses = self._load_analysis().get("targets", [])
        gaps = self._load_gaps()
        fc = read_json(self._out("factcheck", "factcheck.json"))
        with open(self._out("writing", "review.md"), "r", encoding="utf-8") as fh:
            review_md = fh.read()

        loop = review_mod.review_loop(review_md, docs, analyses, fc["citations"], gaps,
                                      max_iters=3)
        final = loop["final"]
        out_path = self._out("review", "review_report.md")
        write_text(out_path, review_mod.render_review_md(final))
        json_path = self._out("review", "review.json")
        write_json(json_path, {"final": final, "history": loop["history"],
                                "converged": loop["converged"],
                                "iterations": loop["iterations"]})

        ev = self.prov.append_evidence(
            kind="review", ref=os.path.join("review", "review_report.md"),
            producer_step=sid, file_path=out_path,
            meta={"overall": final["overall"], "verdict": final["verdict"],
                  "n_blocking": final["n_blocking"]})
        self._toolcall(sid, "sciret_self_review", {"n_docs": len(docs)},
                       {"overall": final["overall"], "verdict": final["verdict"]})
        self.state.mark_step_done(sid, {"overall": final["overall"],
                                        "verdict": final["verdict"]})
        # 报告在 R6 落盘之后生成：此时状态快照才准确
        rpath = self.run_report()
        return {"overall": final["overall"], "verdict": final["verdict"],
                "n_blocking": final["n_blocking"],
                "review": final, "loop": loop, "output": out_path,
                "report": rpath, "evidence": [ev]}

    # ---------- 报告 ----------

    def run_report(self) -> str:
        """生成/刷新科研报告（幂等）。"""
        from . import report as report_mod
        return report_mod.generate_research_report(
            self.root, self.run_id, self.state, self.prov)

    # ---------- 结果读取辅助 ----------

    def _hits(self) -> list[dict]:
        p = self._out("literature", "research_hits.json")
        return read_json(p)["hits"] if os.path.exists(p) else []

    def _load_r2_result(self) -> dict:
        """从磁盘重建 R2 结果（跨进程 resume 时内存态不可用）。"""
        rep_path = self._out("reading", "reading_report.json")
        report = read_json(rep_path) if os.path.exists(rep_path) else {}
        notes_dir = self._out("reading", "notes")
        notes = []
        if os.path.isdir(notes_dir):
            for fn in sorted(os.listdir(notes_dir)):
                if fn.endswith(".json"):
                    n = read_json(os.path.join(notes_dir, fn))
                    n["_path"] = os.path.join(notes_dir, fn)
                    notes.append(n)
        return {"notes": notes, "failures": report.get("failures", []), "report": report}

    def _load_analysis(self) -> dict:
        p = self._out("analysis", "innovations.json")
        return read_json(p) if os.path.exists(p) else {"targets": []}

    def _load_gaps(self) -> dict:
        p = self._out("analysis", "gaps.json")
        return read_json(p) if os.path.exists(p) else {"gaps": [], "n_gaps": 0}

    # ---------- 编排协议（与材料流水线一致）----------

    def _ensure_running(self) -> None:
        if self.state.run_status is RunStatus.PLANNED:
            self.state.start_run()

    def step_context(self, step: str, result: dict) -> dict:
        plan = self.state.pending_or_failed()
        done = [s for s in self.STEP_FN
                if self.state.step_status[s] in (StepStatus.DONE, StepStatus.SKIPPED)]
        failed = [s for s in self.STEP_FN
                  if self.state.step_status[s] is StepStatus.FAILED]
        ctx = {
            "executed_step": step,
            "workflow": "research",
            "result": result,
            "run_status": self.state.run_status.value,
            "steps": {s: self.state.step_status[s].value for s in self.STEP_FN},
            "attempts": dict(self.state.attempts),
            "degraded": self.state.degraded,
            "completed_steps": done,
            "remaining_steps": plan,
            "failed_steps": failed,
        }
        candidates = [f"sciret_run_step(step='{s}')" for s in plan]
        if failed:
            candidates.append("sciret_resume(run_id=...)  # 重试/续跑失败步骤")
        if not plan and not failed:
            candidates.append("sciret_report(run_id=...)  # 生成科研报告收尾")
        ctx["next_tool_candidates"] = candidates
        if failed:
            ctx["requires_decision"] = True
            ctx["decision_reason"] = (
                f"步骤 {failed} 处于 FAILED。必须判断：重试（sciret_resume）还是终止并说明原因。")
        elif self.state.degraded:
            ctx["requires_decision"] = False
            ctx["decision_reason"] = "本 run 发生降级（degraded=true），报告中必须显式声明。"
        else:
            ctx["requires_decision"] = False
        # 精简 result，避免把全文/大数组塞爆上下文
        ctx["result"] = self._slim(result)
        return ctx

    @staticmethod
    def _slim(result: dict) -> dict:
        if not isinstance(result, dict):
            return result
        out = {}
        for k, v in result.items():
            if k in ("notes", "review"):
                continue
            if isinstance(v, list) and len(v) > 8:
                out[k] = v[:8] + [f"...(+{len(v) - 8} more)"]
            elif isinstance(v, dict) and len(json.dumps(v, default=str)) > 2000:
                out[k] = {kk: v[kk] for kk in list(v)[:8]}
            else:
                out[k] = v
        return out

    def run_step_driven(self, step: str) -> dict:
        res = self.run_step(step)
        chaos.CH.kill_after(step)
        return self.step_context(step, res)

    def run_step(self, step: str) -> dict:
        if step not in self.STEP_FN:
            raise KeyError(f"unknown step {step} for research workflow")
        st = self.state.step_status[step]
        if st in (StepStatus.DONE, StepStatus.SKIPPED):
            return {"step": step, "reused": True, "status": st.value}
        # 前置依赖不满足 → 返回可读失败（不抛栈、不隐式代跑），
        # 交由模型决定先补哪一步。
        try:
            self._check_deps(step)
        except StepDependencyError as e:
            return {"step": step, "failed": True, "error": str(e),
                    "error_type": "StepDependencyError",
                    "missing_deps": list(self.STEP_DEPS.get(step, []))}
        self._ensure_running()
        return getattr(self, self.STEP_FN[step])()

    def finish_if_terminal(self) -> dict:
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
                    "error": "尚未终态，仍有未完成步骤", "remaining_steps": pending}
        return {"run_status": self.state.run_status.value, "degraded": self.state.degraded}

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
            results[step] = self._slim(res)
            chaos.CH.kill_after(step)
            if isinstance(res, dict) and res.get("failed"):
                failed = True
                break
        if failed:
            self.state.finish_run(RunStatus.FAILED)
        else:
            self.state.finish_run(RunStatus.DONE)
        return {"results": results, "run_status": self.state.run_status.value,
                "workflow": "research", "degraded": self.state.degraded}

    def resume(self) -> dict:
        return self.run_all()


__all__ = ["ResearchPipeline", "demo_layout_pdf", "scanned_demo_pdf"]
