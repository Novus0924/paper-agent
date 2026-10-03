"""test_research.py — 科研全流程工作流（R1..R6）+ 三类异常恢复（PRD F-4.8）。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root, project_root  # noqa: E402

from paper_agent.state import (create_state, load_state, new_run_id,  # noqa: E402
                               RESEARCH_STEPS, MATERIALS_STEPS)
from paper_agent.research import ResearchPipeline  # noqa: E402
from paper_agent.steps import open_pipeline, Pipeline, run_pipeline  # noqa: E402
from paper_agent.chaos import clear_chaos_mode, set_chaos_mode  # noqa: E402
from paper_agent import litsearch  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        clear_chaos_mode()
        self._tmp = tempfile.mkdtemp(prefix="pa_research_")
        self.root = build_temp_root(self._tmp)

    def tearDown(self):
        clear_chaos_mode()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _new(self, goal="sulfide solid electrolyte ionic conductivity"):
        rid = new_run_id()
        create_state(rid, self.root, goal, lit_source="local", workflow="research")
        return rid

    def _json(self, rid, *parts):
        with open(os.path.join(self.root, "runs", rid, *parts), encoding="utf-8") as f:
            return json.load(f)


class TestWorkflowIsolation(_Base):
    def test_research_run_has_only_research_steps(self):
        rid = self._new()
        st = load_state(rid, self.root)
        self.assertEqual(st.workflow, "research")
        self.assertEqual(st.step_ids, RESEARCH_STEPS)
        self.assertEqual(set(st.step_status), set(RESEARCH_STEPS))

    def test_state_snapshot_has_no_materials_steps(self):
        rid = self._new()
        snap = self._json(rid, "state.json")
        self.assertEqual(snap["workflow"], "research")
        self.assertEqual(set(snap["steps"]), set(RESEARCH_STEPS))

    def test_run_all_converges_to_done(self):
        rid = self._new()
        out = ResearchPipeline(self.root, rid).run_all()
        self.assertEqual(out["run_status"], "DONE")
        self.assertEqual(load_state(rid, self.root).run_status.value, "DONE")
        st = load_state(rid, self.root)
        for sid in RESEARCH_STEPS:
            self.assertEqual(st.step_status[sid].value, "DONE")

    def test_open_pipeline_dispatches_by_workflow(self):
        rid = self._new()
        self.assertIsInstance(open_pipeline(self.root, rid), ResearchPipeline)
        rid2 = new_run_id()
        create_state(rid2, self.root, "g", workflow="materials")
        self.assertIsInstance(open_pipeline(self.root, rid2), Pipeline)


class TestResearchArtifacts(_Base):
    @classmethod
    def setUpClass(cls):
        cls._tmpc = tempfile.mkdtemp(prefix="pa_resart_")
        cls.rootc = build_temp_root(cls._tmpc)
        cls.rid = new_run_id()
        create_state(cls.rid, cls.rootc, "sulfide solid electrolyte ionic conductivity",
                     lit_source="local", workflow="research")
        cls.out = ResearchPipeline(cls.rootc, cls.rid).run_all()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpc, ignore_errors=True)

    def _p(self, *parts):
        return os.path.join(self.rootc, "runs", self.rid, *parts)

    def _read(self, *parts):
        with open(self._p(*parts), encoding="utf-8") as f:
            return f.read()

    def _json_art(self, *parts):
        with open(self._p(*parts), encoding="utf-8") as f:
            return json.load(f)

    def test_artifacts_exist(self):
        for rel in ("literature/research_hits.json", "reading/reading_report.json",
                    "analysis/innovations.json", "analysis/gaps.json",
                    "factcheck/factcheck.json", "writing/review.md",
                    "writing/references.bib", "review/review_report.md", "report.md"):
            self.assertTrue(os.path.exists(self._p(*rel.split("/"))), rel)

    def test_reading_report(self):
        rep = self._json_art("reading", "reading_report.json")
        self.assertGreater(rep["n_read"], 0)
        self.assertEqual(rep["n_failed"], 0)

    def test_notes_have_locators(self):
        notes_dir = self._p("reading", "notes")
        notes = []
        for f in os.listdir(notes_dir):
            if f.endswith(".json"):
                with open(os.path.join(notes_dir, f), encoding="utf-8") as fh:
                    notes.append(json.load(fh))
        self.assertTrue(notes)
        for n in notes:
            self.assertIn("sections", n)
            self.assertIn(n["status"], ("ok", "scanned"))

    def test_review_draft_citations_resolve(self):
        md = self._read("writing", "review.md")
        self.assertIn("[L001]", md)
        # 全文一致性：不应出现文献集合之外的悬空引用
        from paper_agent.writing import check_review_consistency
        hits = self._json_art("literature", "research_hits.json")
        self.assertTrue(check_review_consistency(md, hits["hits"])["ok"])

    def test_report_binds_evidence(self):
        md = self._read("report.md")
        self.assertIn("顶层状态: DONE", md)
        self.assertIn("[EV-", md)
        self.assertIn("R1_search", md)

    def test_evidence_kinds_registered(self):
        kinds = set()
        with open(self._p("provenance.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    kinds.add(json.loads(line)["kind"])
        self.assertIn("literature", kinds)
        self.assertIn("note", kinds)
        self.assertIn("analysis", kinds)
        self.assertIn("factcheck", kinds)
        self.assertIn("draft", kinds)
        self.assertIn("review", kinds)


class TestExceptionRecovery(_Base):
    def test_scenario2_scanned_pdf_degrades(self):
        rid = self._new()
        out = ResearchPipeline(self.root, rid, chaos_mode="scan_pdf").run_all()
        self.assertEqual(out["run_status"], "DONE")
        self.assertTrue(out["degraded"])
        rep = self._json(rid, "reading", "reading_report.json")
        self.assertGreater(rep["scanned_or_low_conf"], 0)
        note = self._json(rid, "reading", "notes", "L001.json")
        self.assertEqual(note["status"], "scanned")
        self.assertEqual(note["confidence"], "low")

    def test_scenario3_batch_item_failure_skipped(self):
        rid = self._new()
        out = ResearchPipeline(self.root, rid, chaos_mode="batch_fail_at=2").run_all()
        self.assertEqual(out["run_status"], "DONE")   # 不中断
        rep = self._json(rid, "reading", "reading_report.json")
        self.assertEqual(rep["n_failed"], 1)
        self.assertEqual(rep["failures"][0]["doc_id"], "L002")
        self.assertGreaterEqual(rep["n_read"], 1)
        self.assertTrue(out["degraded"])

    def test_scenario3_batch_failures_do_not_block_downstream(self):
        rid = self._new()
        ResearchPipeline(self.root, rid, chaos_mode="batch_fail_at=1").run_all()
        st = load_state(rid, self.root)
        # R1 之后的步骤仍全部完成
        for sid in ("R3_analyze", "R4_verify", "R5_write", "R6_review"):
            self.assertEqual(st.step_status[sid].value, "DONE", sid)

    def test_scenario1_source_timeout_switches(self):
        """SS 源超时 → 标记不可用并切源，任务不中断（离线用伪后端模拟）。"""
        set_chaos_mode("ss_timeout")
        rid = self._new()
        pipe = ResearchPipeline(self.root, rid, chaos_mode="ss_timeout")
        backends = pipe._resolve_search_backends()
        self.assertTrue(backends["semantic_scholar"] is not litsearch.DEFAULT_BACKENDS["semantic_scholar"])

        def ok(goal, n, t):
            return ([{"doc_id": "arXiv:1", "doi": "", "title": "Sulfide electrolyte",
                      "authors": ["A"], "venue": "arXiv", "year": 2024,
                      "keywords": ["sulfide"], "abstract": "sulfide conductivity",
                      "url": "u", "source": "arxiv", "citations": 1}], "all:sulfide")

        backends["arxiv"] = ok
        res = litsearch.search_papers("sulfide electrolyte",
                                      sources=["arxiv", "semantic_scholar"],
                                      backends=backends)
        self.assertIn("semantic_scholar", res["unavailable_sources"])
        self.assertEqual(res["n_documents"], 1)      # 已切换到可用源
        self.assertFalse(res["degraded"])            # 非整体降级

    def test_scenario1_timeout_takes_effect_on_local_path(self):
        """回归：`--lit-source local --chaos ss_timeout` 必须真实生效。

        此前 R1 的 local 分支直接短路、从不经过多源层，导致该组合下
        ``unavailable_sources`` 恒为空、`degraded` 恒为 False，
        文档里声称的验证结论并不成立。本用例锁死修复后的行为。
        """
        rid = self._new()
        ResearchPipeline(self.root, rid, chaos_mode="ss_timeout").run_all()
        hits = self._json(rid, "literature", "research_hits.json")
        self.assertEqual(hits["unavailable_sources"], ["semantic_scholar"])
        self.assertEqual(hits["note"], "local_source_failover")
        snap = self._json(rid, "state.json")
        self.assertTrue(snap["degraded"])            # 切源必须被记为降级
        self.assertGreater(hits["n_hits"], 0)        # 任务未被中断，仍有结果

    def test_scenario_unknown_step_rejected(self):
        rid = self._new()
        pipe = ResearchPipeline(self.root, rid)
        with self.assertRaises(KeyError):
            pipe.run_step("P1_lit_search")           # materials 步骤不应存在于 research run

    def test_step_dependency_is_enforced_without_side_effects(self):
        """R3 缺 R2 前置时必须**显式失败**，且不得偷偷把 R2 跑掉。"""
        rid = self._new()
        pipe = ResearchPipeline(self.root, rid)
        pipe.run_step("R1_search")
        res = pipe.run_step("R3_analyze")
        self.assertTrue(res.get("failed"))
        self.assertEqual(res.get("error_type"), "StepDependencyError")
        # 关键：R2 不能被隐式执行
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["R2_read"].value, "PENDING")
        self.assertEqual(st.step_status["R3_analyze"].value, "PENDING")

    def test_all_steps_guard_prerequisites(self):
        """R4/R5/R6 同样必须有前置依赖声明（防止空数据静默出报告）。"""
        for sid in ("R2_read", "R3_analyze", "R4_verify", "R5_write", "R6_review"):
            self.assertTrue(ResearchPipeline.STEP_DEPS.get(sid), sid)


class TestCrashAndResume(_Base):
    def _cli(self, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(project_root(), "core")
        env["paper-agent_ROOT"] = self.root
        env["paper-agent_LIT_SOURCE"] = "local"
        r = subprocess.run([sys.executable, "-m", "paper_agent.cli", *args],
                           capture_output=True, text=True, env=env)
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, {"stdout": r.stdout, "stderr": r.stderr}

    def test_kill_after_r3_then_resume(self):
        rc, out = self._cli("run-all", "--workflow", "research",
                            "--goal", "sulfide solid electrolyte conductivity",
                            "--lit-source", "local", "--chaos", "kill_after_r3")
        self.assertEqual(rc, 137, f"expect SIGKILL 137, got {rc}: {out}")
        runs = sorted(d for d in os.listdir(os.path.join(self.root, "runs"))
                      if d.startswith("run-"))
        rid = runs[-1]
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["R3_analyze"].value, "DONE")
        self.assertEqual(st.step_status["R4_verify"].value, "PENDING")
        rc2, out2 = self._cli("resume", "--run", rid)
        self.assertEqual(out2.get("run_status"), "DONE")
        st2 = load_state(rid, self.root)
        for sid in RESEARCH_STEPS:
            self.assertEqual(st2.step_status[sid].value, "DONE", sid)
        # 账本 append-only 仍完整
        self.assertTrue(os.path.exists(os.path.join(self.root, "runs", rid, "report.md")))


if __name__ == "__main__":
    unittest.main()
