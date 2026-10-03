"""test_review.py — 模拟自评审（PRD F-6.1）。"""
from __future__ import annotations

import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)

from paper_agent import review as RV  # noqa: E402

_DOCS = [{"doc_id": "L001", "doi": "10.1/a", "title": "T1", "authors": ["A"],
          "venue": "V", "year": 2011, "abstract": "x"},
         {"doc_id": "L002", "doi": "10.1/b", "title": "T2", "authors": ["B"],
          "venue": "V", "year": 2016, "abstract": "y"},
         {"doc_id": "L003", "doi": "10.1/c", "title": "T3", "authors": ["C"],
          "venue": "V", "year": 2007, "abstract": "z"}]

_DRAFT_OK = ("- Finding one with 42 percent improvement [L001]\n"
             "- Finding two [L002]\n- Finding three [L003]\n")
_DRAFT_BAD = ("- Claim without support [需补充引用]\n"
              "- Dangling ref [GHOST-9]\n")


class TestSelfReview(unittest.TestCase):
    def test_dimensions_all_scored(self):
        r = RV.self_review(_DRAFT_OK, _DOCS)
        self.assertEqual(set(r["scores"]), set(RV.DIMENSIONS))

    def test_statement_count_covers_prose_not_only_bullets(self):
        """回归：清晰度归一不能只数 `- ` 行；散文草稿也要被计入。

        旧实现 `n_sentences = 只数 '-' 行`，对纯散文草稿得到 0，
        使 `bad / max(1, n_sentences)` 分母退化为 1、清晰度分数虚高。
        """
        prose = ("This draft is written as flowing prose without any bullet list. "
                 "A second sentence continues the argument in more detail.")
        r = RV.self_review(prose, _DOCS)
        self.assertGreaterEqual(r["signals"]["n_statements"], 2)
        # 单条未支撑陈述不应因"总句子数=1"而被判满分
        r2 = RV.self_review(prose + "\n" + "- bad claim [需补充引用]\n", _DOCS)
        self.assertLess(r2["scores"]["写作清晰度"], 10.0)
        for v in r["scores"].values():
            self.assertGreaterEqual(v, 1)
            self.assertLessEqual(v, 10)

    def test_dangling_is_blocking(self):
        r = RV.self_review(_DRAFT_BAD, _DOCS)
        tags = {i["tag"] for i in r["blocking_issues"]}
        self.assertIn("dangling_citation", tags)
        self.assertIn("no_citation_ratio", tags)
        self.assertGreater(r["n_blocking"], 0)

    def test_clean_draft_has_no_blocking(self):
        r = RV.self_review(_DRAFT_OK, _DOCS, factcheck={"n": 3, "consistency_rate": 1.0})
        self.assertEqual(r["n_blocking"], 0)

    def test_revision_actions_map(self):
        r = RV.self_review(_DRAFT_BAD, _DOCS)
        actions = RV.revision_actions(r)
        self.assertTrue(actions)

    def test_render_review_md(self):
        md = RV.render_review_md(RV.self_review(_DRAFT_OK, _DOCS))
        for section in ("Summary", "Strengths", "Weaknesses", "Detailed Comments", "Score"):
            self.assertIn(section, md)

    def test_loop_single_pass_without_revise(self):
        out = RV.review_loop(_DRAFT_OK, _DOCS)
        self.assertEqual(out["iterations"], 1)
        self.assertIn("final", out)

    def test_loop_converges_with_revise(self):
        state = {"n": 0}

        def revise(rv, draft):
            state["n"] += 1
            fixed = "- Finding [L001]\n- More [L002] with 10 percent gain\n- Third [L003]\n"
            return fixed, {"n": 3, "consistency_rate": 1.0}

        out = RV.review_loop(_DRAFT_BAD, _DOCS, revise=revise, max_iters=3)
        self.assertTrue(out["converged"])
        self.assertLessEqual(state["n"], 2)


if __name__ == "__main__":
    unittest.main()
