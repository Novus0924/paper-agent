"""test_evaluate.py — 量化验证指标与评估（PRD F-7.1~7.4）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root  # noqa: E402

from paper_agent import evaluate as EV  # noqa: E402


class TestMetrics(unittest.TestCase):
    def test_precision_recall(self):
        got = ["A", "B", "C"]
        gold = {"A", "C"}
        self.assertAlmostEqual(EV.precision_at_k(got, gold), 2 / 3, places=6)
        self.assertAlmostEqual(EV.recall_at_k(got, gold), 1.0, places=6)

    def test_recall_with_miss(self):
        self.assertAlmostEqual(EV.recall_at_k(["A"], {"A", "B"}), 0.5, places=6)

    def test_f1(self):
        self.assertAlmostEqual(EV.f1_at_k(["A", "B"], {"A"}), 2 * 0.5 * 1.0 / 1.5, places=6)

    def test_ndcg_perfect_ranking_is_one(self):
        self.assertAlmostEqual(EV.ndcg_at_k(["A", "B"], {"A", "B"}, k=10), 1.0, places=6)

    def test_ndcg_better_ranking_higher(self):
        gold = {"A"}
        self.assertGreater(EV.ndcg_at_k(["A", "X"], gold), EV.ndcg_at_k(["X", "A"], gold))

    def test_empty_safe(self):
        self.assertEqual(EV.precision_at_k([], {"A"}), 0.0)
        self.assertEqual(EV.recall_at_k(["A"], set()), 0.0)
        self.assertEqual(EV.ndcg_at_k([], {"A"}), 0.0)


class TestSearchEval(unittest.TestCase):
    def test_with_baseline_and_failure_case(self):
        def searcher(q):
            return {"q1": ["A", "B"], "q2": ["X"]}.get(q, [])

        def baseline(q):
            return ["X"]

        ts = [{"query": "q1", "gold": ["A", "B"]}, {"query": "q2", "gold": ["A"]}]
        out = EV.eval_search_quality(ts, searcher, baseline)
        self.assertEqual(out["n_cases"], 2)
        self.assertAlmostEqual(out["system"]["recall"], 0.5, places=6)
        self.assertIn("baseline", out)
        self.assertTrue(out["failures"])


class TestDemoEvals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="pa_eval_")
        cls.root = build_temp_root(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_build_demo_evals_shapes(self):
        d = EV.build_demo_evals(self.root)
        self.assertEqual(len(d["reading"]), 5)
        self.assertTrue(d["innovation"])
        self.assertTrue(d["citation"])

    def test_run_all_offline(self):
        rep = EV.run_all(self.root, include_demo=True)
        self.assertEqual(set(rep), {"search", "read", "innovation", "citation"})
        self.assertGreater(rep["search"]["n_cases"], 0)
        self.assertGreaterEqual(rep["read"]["structure_accuracy"], 0.0)
        self.assertGreaterEqual(rep["innovation"]["identification_rate"], 0.0)
        # 引用准确率应较高（gold 由人工可核查事实导出）
        self.assertGreaterEqual(rep["citation"]["citation_accuracy"], 0.6)
        md = EV.render_eval_md(rep)
        self.assertIn("F-7.1", md)
        self.assertIn("F-7.4", md)

    def test_run_all_scale_note_present(self):
        rep = EV.run_all(self.root, include_demo=True)
        self.assertIn("demo", rep["search"]["scale_note"])


if __name__ == "__main__":
    unittest.main()
