"""test_analyze.py — 创新点拆解 / Gap / 脉络（PRD F-3.1~F-3.3）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import parse_fixture_pdf  # noqa: E402

from paper_agent import analyze  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_method(self):
        self.assertIn("方法创新", analyze.classify_innovation("We propose a new framework."))

    def test_theory(self):
        self.assertIn("理论创新", analyze.classify_innovation("We prove a convergence theorem."))

    def test_data(self):
        self.assertIn("数据创新", analyze.classify_innovation("We collect a new dataset of 1M samples."))

    def test_application(self):
        self.assertIn("应用创新", analyze.classify_innovation("We apply it to clinical practice."))

    def test_engineering(self):
        self.assertIn("工程创新", analyze.classify_innovation("The system improves throughput and latency."))

    def test_default_is_method(self):
        self.assertEqual(analyze.classify_innovation("Nothing matches here."), ["方法创新"])


class TestInnovationExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="pa_ana_")
        cls.note = parse_fixture_pdf(cls._tmp)
        cls.res = analyze.extract_innovations(cls.note)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_finds_innovations(self):
        self.assertGreaterEqual(self.res["n_innovations"], 1)

    def test_four_elements_present(self):
        for c in self.res["innovations"]:
            for k in ("what", "problem", "technique", "effect", "locator", "confidence"):
                self.assertIn(k, c)

    def test_locator_traceable(self):
        for c in self.res["innovations"]:
            self.assertIn("section", c["locator"])
            self.assertIn("offset", c["locator"])

    def test_no_fabrication_all_from_text(self):
        """每个创新点陈述必须能在原文找到（幻觉守门）。"""
        text = self.note["text"]
        for c in self.res["innovations"]:
            self.assertIn(c["statement"][:30], text)

    def test_categories_summary(self):
        total = sum(self.res["categories_summary"].values())
        self.assertGreaterEqual(total, self.res["n_innovations"])


class TestGapAndTimeline(unittest.TestCase):
    def test_research_gap_from_limitations(self):
        notes = [
            {"doc_id": "A", "text": "However the conductivity is limited.",
             "sections": {"Limitations": "However the material is unstable at high voltage. "
                                          "However the cost remains high."}},
            {"doc_id": "B", "text": "However stability fails.",
             "sections": {"Conclusion": "However the material is unstable and degrades."}},
        ]
        g = analyze.research_gap(notes)
        self.assertGreaterEqual(g["n_gaps"], 1)
        self.assertEqual(g["gaps"][0]["id"], "GAP-1")
        self.assertTrue(g["gaps"][0]["evidence"])

    def test_gap_cluster_key_is_order_independent(self):
        """回归：聚类键必须与词序无关，否则同一课题的空白聚不到一起。

        旧实现取 `sorted(set(toks))[:5]`（字母序前 5），
        会让同义句落到不同键，F-3.3 的跨文献聚类形同虚设。
        """
        a = analyze._cluster_key(
            "existing methods are slow when training on large datasets")
        b = analyze._cluster_key(
            "training on large datasets is slow for existing methods")
        self.assertEqual(a, b)
        # 不同主题必须得到不同键
        c = analyze._cluster_key(
            "the model lacks theoretical convergence guarantees")
        self.assertNotEqual(a, c)

    def test_gap_aggregates_same_topic_across_docs(self):
        """同义表述应聚成一个 gap 且频次正确累加。"""
        notes = [
            {"doc_id": "A", "text": "",
             "sections": {"Limitations": "However existing methods are slow when training on large datasets."}},
            {"doc_id": "B", "text": "",
             "sections": {"Limitations": "However training on large datasets is slow for existing methods."}},
        ]
        g = analyze.research_gap(notes)
        self.assertEqual(g["n_gaps"], 1)
        self.assertEqual(g["gaps"][0]["frequency"], 2)

    def test_timeline_sorted(self):
        tl = analyze.technology_timeline([
            {"doc_id": "B", "year": 2020}, {"doc_id": "A", "year": 2010}])
        self.assertEqual([n["doc_id"] for n in tl["nodes"]], ["A", "B"])
        self.assertEqual(tl["year_range"], [2010, 2020])

    def test_comparison_matrix(self):
        target = {"title": "T", "_meta": {"doc_id": "T", "year": 2024, "citations": 1},
                  "innovations": [{"statement": "we propose X", "categories": ["方法创新"]}]}
        refs = [{"title": "R", "_meta": {"doc_id": "R", "year": 2020, "citations": 5},
                 "innovations": [{"statement": "we propose Y", "categories": ["数据创新"]}]}]
        m = analyze.build_comparison_matrix(target, refs)
        self.assertEqual(m["n_rows"], 2)
        self.assertIn("primary_innovation", m["columns"])


if __name__ == "__main__":
    unittest.main()
