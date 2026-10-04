"""test_anomaly.py — 双腿对接与异常驱动打断（D7）。

关键回归：**低对接率不是异常**（实测文献腿 vs OBELiX 仅 2.1% 交集），
只有"交集为零"才判定为异常。
"""
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)

from paper_agent import anomaly as A  # noqa: E402


def lit(dois):
    return [{"doi": d, "title": f"T-{d}", "query": "q"} for d in dois]


def mats(dois):
    return [{"material_id": f"M{i}", "source_doi": d}
            for i, d in enumerate(dois)]


class TestSupportingInformation(unittest.TestCase):
    def test_detects_si_suffix(self):
        for d in ("10.1021/acsami.3c17535.s001",
                  "10.1021/acs.jpcc.4c05656.S001",
                  "10.1002/anie.202000001.s1"):
            self.assertTrue(A.is_supporting_information(d), d)

    def test_main_articles_not_flagged(self):
        for d in ("10.1038/nmat3006", "10.1021/cm001207u",
                  "10.1016/j.ssi.2015.10.015"):
            self.assertFalse(A.is_supporting_information(d), d)


class TestJoinLegs(unittest.TestCase):
    def test_match_and_rates(self):
        j = A.join_legs(lit(["10.1/a", "10.1/b", "10.1/c"]),
                        mats(["10.1/b", "10.1/c", "10.1/d"]))
        self.assertEqual(j["matched"], ["10.1/b", "10.1/c"])
        self.assertEqual(j["literature_only"], ["10.1/a"])
        self.assertEqual(j["data_only"], ["10.1/d"])
        self.assertAlmostEqual(j["join_rate_of_literature"], 0.6667, places=3)
        self.assertAlmostEqual(j["join_rate_of_data"], 0.6667, places=3)
        self.assertFalse(j["no_leg_overlap"])

    def test_case_and_whitespace_normalized(self):
        j = A.join_legs(lit([" 10.1/A "]), mats(["10.1/a"]))
        self.assertEqual(j["n_matched"], 1)

    def test_supporting_info_excluded_from_matching(self):
        j = A.join_legs(lit(["10.1/a.s001", "10.1/b"]),
                        mats(["10.1/a.s001", "10.1/b"]))
        # SI 不进对接集合，只在计数里体现
        self.assertEqual(j["n_literature_supporting_info_dois"], 1)
        self.assertEqual(j["n_data_supporting_info_dois"], 1)
        self.assertEqual(j["n_literature_dois"], 1)
        self.assertEqual(j["matched"], ["10.1/b"])

    def test_missing_doi_ignored(self):
        j = A.join_legs([{"doi": ""}, {"doi": "10.1/a"}],
                        [{"source_doi": ""}, {"source_doi": "10.1/a"}])
        self.assertEqual(j["n_matched"], 1)
        self.assertEqual(j["n_literature_dois"], 1)

    def test_no_overlap_flag(self):
        j = A.join_legs(lit(["10.1/a"]), mats(["10.2/z"]))
        self.assertTrue(j["no_leg_overlap"])
        self.assertEqual(j["n_matched"], 0)

    def test_empty_legs_not_flagged_as_no_overlap(self):
        j = A.join_legs([], mats(["10.1/a"]))
        self.assertFalse(j["no_leg_overlap"])

    def test_deterministic(self):
        a = A.join_legs(lit(["10.1/c", "10.1/a", "10.1/b"]), mats(["10.1/b"]))
        b = A.join_legs(lit(["10.1/b", "10.1/c", "10.1/a"]), mats(["10.1/b"]))
        self.assertEqual(a, b)


class TestZeroHits(unittest.TestCase):
    def test_fires_on_empty(self):
        out = A.detect_zero_hits({"n_unique": 0, "errors": [{"x": 1}]})
        self.assertEqual([a["code"] for a in out], [A.ZERO_HITS])
        self.assertEqual(out[0]["metrics"]["errors"], 1)

    def test_silent_when_hits_exist(self):
        self.assertEqual(A.detect_zero_hits({"n_unique": 3, "errors": []}), [])


class TestNoOverlap(unittest.TestCase):
    def test_fires_when_zero(self):
        j = A.join_legs(lit(["10.1/a"]), mats(["10.2/z"]))
        self.assertEqual([a["code"] for a in A.detect_no_overlap(j)],
                         [A.NO_LEG_OVERLAP])

    def test_low_join_rate_is_NOT_anomaly(self):
        """实测基线：文献腿 373 篇 vs 数据腿 222 篇，交集仅 8 篇（2.1%）——
        这属于正常行为，绝不能误报为异常。"""
        lit_dois = [f"10.lit/{i}" for i in range(365)]
        data_dois = [f"10.data/{i}" for i in range(214)]
        shared = [f"10.shared/{i}" for i in range(8)]
        j = A.join_legs(lit(lit_dois + shared), mats(data_dois + shared))
        self.assertEqual(j["n_matched"], 8)
        self.assertLess(j["join_rate_of_literature"], 0.03)
        self.assertFalse(j["no_leg_overlap"])
        self.assertEqual(A.detect_no_overlap(j), [])


class TestHitRate(unittest.TestCase):
    def _judgments(self, n_rel, n_exc):
        js = []
        for i in range(n_rel):
            js.append({"kind": "relevance",
                       "meta": {"subject": f"r{i}", "verdict": "relevant"}})
        for i in range(n_exc):
            js.append({"kind": "relevance",
                       "meta": {"subject": f"e{i}", "verdict": "excluded"}})
        return js

    def test_too_high(self):
        out = A.detect_hit_rate(self._judgments(48, 2))
        self.assertEqual([a["code"] for a in out], [A.JUDGE_HIT_RATE])
        self.assertIn("过高", out[0]["detail"])

    def test_too_low(self):
        out = A.detect_hit_rate(self._judgments(1, 39))
        self.assertEqual([a["code"] for a in out], [A.JUDGE_HIT_RATE])
        self.assertIn("过低", out[0]["detail"])

    def test_normal_rate_silent(self):
        self.assertEqual(A.detect_hit_rate(self._judgments(7, 36)), [])

    def test_small_sample_not_judged(self):
        """样本不足不判定——本次真实快照是 6/36 命中率但样本 42，属正常。"""
        self.assertEqual(A.detect_hit_rate(self._judgments(6, 6)), [])

    def test_ignores_non_relevance_judgments(self):
        js = self._judgments(1, 1)
        js.append({"kind": "query_generation",
                   "meta": {"subject": "goal", "verdict": "generated"}})
        self.assertEqual(A.detect_hit_rate(js), [])


class TestSelfContradiction(unittest.TestCase):
    def test_detects_opposite_verdicts(self):
        js = [
            {"kind": "relevance",
             "meta": {"axis": "material_family", "subject": "garnet",
                      "verdict": "relevant"}},
            {"kind": "relevance",
             "meta": {"axis": "material_family", "subject": "garnet",
                      "verdict": "excluded"}},
        ]
        out = A.detect_self_contradiction(js)
        self.assertEqual([a["code"] for a in out], [A.JUDGE_SELF_CONTRADICTION])
        self.assertEqual(out[0]["metrics"]["n_conflicts"], 1)

    def test_consistent_verdicts_silent(self):
        js = [{"kind": "relevance",
               "meta": {"axis": "material_family", "subject": "garnet",
                        "verdict": "relevant"}},
              {"kind": "relevance",
               "meta": {"axis": "material_family", "subject": "NASICON",
                        "verdict": "excluded"}}]
        self.assertEqual(A.detect_self_contradiction(js), [])

    def test_different_axes_not_conflicting(self):
        js = [{"kind": "relevance",
               "meta": {"axis": "material_family", "subject": "x",
                        "verdict": "relevant"}},
              {"kind": "relevance",
               "meta": {"axis": "paper", "subject": "x", "verdict": "excluded"}}]
        self.assertEqual(A.detect_self_contradiction(js), [])


class TestDetectAndGate(unittest.TestCase):
    def test_detect_is_sorted_and_complete(self):
        lr = {"n_unique": 0, "errors": []}
        j = A.join_legs([], mats(["10.1/a"]))
        js = [{"kind": "relevance",
               "meta": {"subject": "s", "verdict": "relevant"}}] * 25
        out = A.detect(lr, j, js)
        codes = [a["code"] for a in out]
        self.assertIn(A.ZERO_HITS, codes)
        self.assertIn(A.JUDGE_HIT_RATE, codes)
        self.assertEqual(codes, sorted(codes))

    def test_format_report_has_ack_hints(self):
        out = A.detect_zero_hits({"n_unique": 0, "errors": []})
        text = A.format_report(out)
        self.assertIn("zero_hits", text)
        self.assertIn("--ack zero_hits", text)
        self.assertIn("流程已停下", text)

    def test_format_report_clean(self):
        self.assertIn("未检出异常", A.format_report([], A.join_legs([], [])))

    def test_require_ack_filters(self):
        out = A.detect_zero_hits({"n_unique": 0, "errors": []})
        self.assertEqual(A.require_ack(out, []), out)
        self.assertEqual(A.require_ack(out, [A.ZERO_HITS]), [])

    def test_require_ack_rejects_unknown_code(self):
        with self.assertRaises(ValueError):
            A.require_ack([], ["not_a_code"])

    def test_anomaly_error_lists_codes(self):
        out = A.detect_zero_hits({"n_unique": 0, "errors": []})
        err = A.AnomalyError(out)
        self.assertIn(A.ZERO_HITS, str(err))


if __name__ == "__main__":
    unittest.main()
