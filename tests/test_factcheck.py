"""test_factcheck.py — 事实验证（PRD F-4.1~F-4.3）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import parse_fixture_pdf  # noqa: E402

from paper_agent import factcheck as FC  # noqa: E402


class TestCitationVerify(unittest.TestCase):
    def test_unknown_when_no_source(self):
        r = FC.verify_citation("anything", None, "X")
        self.assertEqual(r["verdict"], "❓ 无法获取原文")
        self.assertFalse(r["exists"])

    def test_consistent_when_supported(self):
        src = "We propose a novel sulfide solid electrolyte with high ionic conductivity."
        r = FC.verify_citation("We propose a novel sulfide solid electrolyte", src, "S")
        self.assertEqual(r["verdict"], "✅ 一致")

    def test_inconsistent_when_off_topic(self):
        src = "We propose a novel sulfide solid electrolyte."
        r = FC.verify_citation(
            "Quantum chromodynamics lattice gauge theory analysis of hadrons.", src, "S")
        self.assertEqual(r["verdict"], "❌ 不一致")

    def test_missing_number_flagged(self):
        src = "Conductivity reaches 1e-2 S/cm."
        r = FC.verify_citation("Conductivity reaches 1e-2 S/cm with 99 percent yield.", src, "S")
        self.assertFalse(r["number_ok"])
        self.assertIn("99", r["missing_numbers"])

    def test_batch_tally(self):
        out = FC.verify_citations([
            {"claim": "sulfide solid electrolyte high conductivity",
             "source_text": "sulfide solid electrolyte high conductivity", "source_ref": "A"},
            {"claim": "totally unrelated quarks and gluons", "source_text": "sulfide", "source_ref": "B"},
            {"claim": "x", "source_text": None, "source_ref": "C"}])
        self.assertEqual(out["n"], 3)
        self.assertAlmostEqual(out["consistency_rate"], 1 / 3, places=4)


class TestDataConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="pa_fc_")
        cls.note = parse_fixture_pdf(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_checks_present(self):
        out = FC.check_data_consistency(self.note)
        names = {c["name"] for c in out["checks"]}
        self.assertIn("abstract_vs_experiment_numbers", names)
        self.assertIn("figure_trend_vs_conclusion", names)
        self.assertIn("ablation_self_consistency", names)
        self.assertIn(out["status"], ("PASS", "WARN"))

    def test_anomaly_detected_when_number_missing(self):
        note = {"doc_id": "X",
                "sections": {"Abstract": "We achieve 42 percent efficiency.",
                             "Experiment": "The method is fast."},
                "text": "We achieve 42 percent efficiency. The method is fast."}
        out = FC.check_data_consistency(note)
        c = [c for c in out["checks"]
             if c["name"] == "abstract_vs_experiment_numbers"][0]
        self.assertFalse(c["pass"])
        self.assertIn("42", c["missing"])


class TestContradictions(unittest.TestCase):
    def test_direction_conflict_detected(self):
        a = {"doc_id": "A", "sections": {"Conclusion": "Our method improves conductivity significantly."},
             "text": "Our method improves conductivity significantly."}
        b = {"doc_id": "B", "sections": {"Conclusion": "The treatment decreases conductivity markedly."},
             "text": "The treatment decreases conductivity markedly."}
        out = FC.detect_contradictions([a, b])
        self.assertGreaterEqual(out["n_contradictions"], 1)
        self.assertEqual(out["contradictions"][0]["type"], "direction_conflict")

    def test_no_contradiction_for_same_direction(self):
        a = {"doc_id": "A", "sections": {"Conclusion": "Method improves conductivity markedly."},
             "text": "Method improves conductivity markedly."}
        b = {"doc_id": "B", "sections": {"Conclusion": "Another method improves conductivity markedly."},
             "text": "Another method improves conductivity markedly."}
        out = FC.detect_contradictions([a, b])
        self.assertEqual(out["n_contradictions"], 0)


if __name__ == "__main__":
    unittest.main()
