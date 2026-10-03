"""test_writing.py — 综述写作 / 引用管理（PRD F-5.1~F-5.3）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import parse_fixture_pdf  # noqa: E402

from paper_agent import writing as W  # noqa: E402


def _docs():
    return [
        {"doc_id": "L001", "doi": "10.1/a", "title": "A lithium superionic conductor",
         "authors": ["N. Kamaya", "K. Homma"], "venue": "Nature Materials", "year": 2011,
         "keywords": ["LGPS"], "abstract": "Reports the lithium superionic conductor Li10GeP2S12."},
        {"doc_id": "L002", "doi": "10.1/b", "title": "High-power sulfide",
         "authors": ["Y. Kato"], "venue": "Nature Energy", "year": 2016,
         "keywords": ["sulfide"], "abstract": "Demonstrates high-power sulfide batteries."},
        {"doc_id": "L003", "doi": "", "title": "Garnet", "authors": ["R. Murugan"],
         "venue": "Angew", "year": 2007, "keywords": ["garnet"], "abstract": "Reports garnet LLZO."},
    ]


class TestCitationFormats(unittest.TestCase):
    def test_apa(self):
        s = W.format_citation(_docs()[0], "APA")
        self.assertIn("Kamaya", s)
        self.assertIn("(2011)", s)
        self.assertIn("https://doi.org/10.1/a", s)

    def test_ieee(self):
        s = W.format_citation(_docs()[0], "IEEE")
        self.assertIn('"A lithium superionic conductor,"', s)

    def test_chicago(self):
        self.assertIn('"A lithium superionic conductor."',
                      W.format_citation(_docs()[0], "CHICAGO"))

    def test_bibtex_key_stable(self):
        self.assertEqual(W.bibtex_key(_docs()[0]), "kamaya2011a")

    def test_missing_fields(self):
        self.assertIn("doi", W.missing_fields(_docs()[2]))


class TestBibtexRis(unittest.TestCase):
    def test_bibtex_entries_and_warnings(self):
        out = W.generate_bibtex(_docs())
        self.assertEqual(out["n_entries"], 3)
        self.assertTrue(any(w["doc_id"] == "L003" for w in out["warnings"]))
        self.assertIn("@article", out["bibtex"])

    def test_bibtex_key_collision_resolved(self):
        d = _docs()[0]
        out = W.generate_bibtex([d, dict(d), dict(d)])
        self.assertEqual(out["n_entries"], 3)
        self.assertEqual(len({l for l in out["bibtex"].split("@")}), 4)  # 3 entries + 头

    def test_ris(self):
        ris = W.generate_ris(_docs())
        self.assertIn("TY  - JOUR", ris)
        self.assertIn("DO  - 10.1/a", ris)

    def test_dedup_citations(self):
        d = _docs()[0]
        out = W.dedup_citations([d, dict(d), _docs()[1]])
        self.assertEqual(out["removed"], 1)


class TestReviewGeneration(unittest.TestCase):
    def test_review_sections_and_citations(self):
        rv = W.generate_review("solid electrolytes", _docs())
        names = [s["name"] for s in rv["sections"]]
        self.assertEqual(names, ["Introduction", "Related Work", "Method Landscape",
                                 "Open Problems", "Conclusion"])
        self.assertGreater(rv["n_citations"], 0)
        self.assertIn("[L001]", rv["markdown"])

    def test_unsupported_marked_not_fabricated(self):
        rv = W.generate_review("topic", [])
        joined = " ".join(rv["unsupported"])
        self.assertIn("需补充引用", joined)

    def test_consistency_check_dangling(self):
        rv = W.generate_review("t", _docs())
        self.assertTrue(rv["consistency"]["ok"])
        bad = W.check_review_consistency("Claim [GHOST-1].", _docs())
        self.assertFalse(bad["ok"])
        self.assertIn("GHOST-1", bad["dangling"])

    def test_analysis_and_gaps_feed_sections(self):
        tmp = tempfile.mkdtemp(prefix="pa_w_")
        try:
            note = parse_fixture_pdf(tmp)
            from paper_agent import analyze
            a = analyze.extract_innovations(note)
            rv = W.generate_review("t", _docs(), [a], {"gaps": [
                {"id": "GAP-1", "problem": "stability", "frequency": 2,
                 "importance": "高", "feasibility": "中",
                 "evidence": [{"doc_id": "L001"}]}]})
            self.assertTrue(any("[GAP-1]" in s for s in rv["sections"][3]["content"]))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
