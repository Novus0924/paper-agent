"""test_litsearch.py — 联网文献腿：解析、URL、去重合并、重试与错误处理。

全部用例**离线**运行（注入假传输层），不访问网络。
"""
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)

from paper_agent import litsearch as L  # noqa: E402

CROSSREF_PAYLOAD = {
    "message": {"items": [
        {"DOI": "10.1038/NMAT3006",
         "title": ["Solid-state ionic conductivity of LGPS sulfur-based electrolytes"],
         "author": [{"given": "H.", "family": "Yamada"},
                    {"given": "T.", "family": "Kato"}],
         "issued": {"date-parts": [[2011, 7, 1]]},
         "container-title": ["Nature Materials"]},
        {"DOI": "10.1002/anie.200701144",
         "title": ["Lithium ion conducting garnet solid electrolyte LLZO"],
         "author": [{"family": "Murugan"}],
         "issued": {"date-parts": [[2007]]},
         "container-title": ["Angewandte Chemie"]},
        {"DOI": "", "title": ["Untitled record without DOI"],
         "author": [], "container-title": []},
    ]}
}

OPENALEX_PAYLOAD = {
    "results": [
        {"doi": "https://doi.org/10.1038/nmat3006",
         "display_name": "Solid-state ionic conductivity of LGPS sulfur-based electrolytes",
         "publication_year": 2011,
         "authorships": [{"author": {"display_name": "H. Yamada"}}],
         "primary_location": {"source": {"display_name": "Nature Materials"}}},
        {"doi": "https://doi.org/10.1016/j.ssi.2015.10.015",
         "display_name": "Interface resistance in sulfide solid electrolytes",
         "publication_year": 2015,
         "authorships": [{"author": {"display_name": "A. Sakuda"}}],
         "primary_location": {"source": {"display_name": "Solid State Ionics"}}},
    ]
}


def fake_transport(payload, calls=None):
    def _t(url):
        if calls is not None:
            calls.append(url)
        return payload
    return _t


def flaky_transport(payload, fail_times: int, calls=None):
    state = {"n": 0}

    def _t(url):
        if calls is not None:
            calls.append(url)
        state["n"] += 1
        if state["n"] <= fail_times:
            raise OSError("connection reset")
        return payload
    return _t


class TestParse(unittest.TestCase):
    def test_crossref_item(self):
        rec = L.parse_crossref_item(CROSSREF_PAYLOAD["message"]["items"][0],
                                    "sulfide conductivity")
        self.assertEqual(rec["doi"], "10.1038/nmat3006")   # DOI 统一小写
        self.assertEqual(rec["year"], 2011)
        self.assertEqual(rec["authors"], ["H. Yamada", "T. Kato"])
        self.assertEqual(rec["venue"], "Nature Materials")
        self.assertEqual(rec["source"], "crossref")
        self.assertEqual(rec["query"], "sulfide conductivity")

    def test_crossref_family_only_author(self):
        rec = L.parse_crossref_item(CROSSREF_PAYLOAD["message"]["items"][1])
        self.assertEqual(rec["authors"], ["Murugan"])
        self.assertEqual(rec["year"], 2007)

    def test_crossref_item_without_doi_or_title_dropped(self):
        self.assertIsNone(L.parse_crossref_item({}))

    def test_openalex_strips_doi_prefix(self):
        rec = L.parse_openalex_item(OPENALEX_PAYLOAD["results"][0])
        self.assertEqual(rec["doi"], "10.1038/nmat3006")
        self.assertEqual(rec["year"], 2011)
        self.assertEqual(rec["authors"], ["H. Yamada"])
        self.assertEqual(rec["venue"], "Nature Materials")
        self.assertEqual(rec["source"], "openalex")

    def test_openalex_missing_year_becomes_none(self):
        item = dict(OPENALEX_PAYLOAD["results"][1])
        item.pop("publication_year")
        self.assertIsNone(L.parse_openalex_item(item)["year"])


class TestUrl(unittest.TestCase):
    def test_crossref_url_has_query_rows_mailto(self):
        u = L.build_url(L.CROSSREF, "sulfide solid electrolyte", 20, "a@b.c")
        self.assertIn("api.crossref.org/works", u)
        self.assertIn("rows=20", u)
        self.assertIn("mailto=a%40b.c", u)
        self.assertIn(("sulfide%20solid%20electrolyte"), u)

    def test_openalex_url(self):
        u = L.build_url(L.OPENALEX, "garnet", 5, "a@b.c")
        self.assertIn("api.openalex.org/works", u)
        self.assertIn("per-page=5", u)

    def test_unknown_source_raises(self):
        with self.assertRaises(L.SearchError):
            L.build_url("scopus", "x", 1, "a@b.c")


class TestSearchOne(unittest.TestCase):
    def test_crossref_search(self):
        recs = L.search_one("sulfide", L.CROSSREF, 20,
                            transport=fake_transport(CROSSREF_PAYLOAD),
                            sleep=lambda s: None)
        # 第 3 条无 DOI 也无标题之外字段：标题存在故保留 → 共 3 条
        self.assertEqual(len(recs), 3)
        self.assertEqual(recs[0]["doi"], "10.1038/nmat3006")

    def test_openalex_search(self):
        recs = L.search_one("sulfide", L.OPENALEX, 20,
                            transport=fake_transport(OPENALEX_PAYLOAD),
                            sleep=lambda s: None)
        self.assertEqual(len(recs), 2)

    def test_retry_then_success(self):
        calls = []
        recs = L.search_one("sulfide", L.CROSSREF, 20,
                            transport=flaky_transport(CROSSREF_PAYLOAD, 2, calls),
                            retries=2, sleep=lambda s: None)
        self.assertEqual(len(recs), 3)
        self.assertEqual(len(calls), 3)      # 2 次失败 + 1 次成功

    def test_raises_after_retries_exhausted(self):
        with self.assertRaises(L.SearchError):
            L.search_one("sulfide", L.CROSSREF, 20,
                         transport=flaky_transport(CROSSREF_PAYLOAD, 99),
                         retries=2, sleep=lambda s: None)


class TestMerge(unittest.TestCase):
    def test_dedupe_by_doi_and_merge_sources(self):
        a = L.parse_crossref_item(CROSSREF_PAYLOAD["message"]["items"][0], "q1")
        b = L.parse_openalex_item(OPENALEX_PAYLOAD["results"][0], "q2")
        out = L.merge_records([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["sources"], ["crossref", "openalex"])
        self.assertEqual(out[0]["queries"], ["q1", "q2"])

    def test_prefers_fuller_fields(self):
        thin = L.make_record("10.1/x", "", [], None, "", "crossref", "q")
        full = L.make_record("10.1/x", "Real Title", ["A. Author"], 2020,
                             "Nature", "openalex", "q")
        out = L.merge_records([thin, full])
        self.assertEqual(out[0]["title"], "Real Title")
        self.assertEqual(out[0]["year"], 2020)
        self.assertEqual(out[0]["venue"], "Nature")

    def test_dedupe_by_title_when_no_doi(self):
        r1 = L.make_record("", "Same Title", [], 2000, "", "crossref", "q")
        r2 = L.make_record("", "same title", [], 2000, "", "openalex", "q")
        self.assertEqual(len(L.merge_records([r1, r2])), 1)

    def test_deterministic_order(self):
        recs = [L.make_record("10.1/b", "B", [], 2000, "", "crossref", "q"),
                L.make_record("10.1/a", "A", [], 2000, "", "crossref", "q")]
        out1 = [r["doi"] for r in L.merge_records(recs)]
        out2 = [r["doi"] for r in L.merge_records(list(reversed(recs)))]
        self.assertEqual(out1, out2)
        self.assertEqual(out1, ["10.1/a", "10.1/b"])


class TestSearch(unittest.TestCase):
    def test_multi_query_multi_source(self):
        def t(url):
            return (CROSSREF_PAYLOAD if "crossref" in url else OPENALEX_PAYLOAD)

        res = L.search(["sulfide", "garnet"], sources=(L.CROSSREF, L.OPENALEX),
                       rows=20, transport=t, sleep_s=0, sleep=lambda s: None)
        self.assertEqual(res["queries"], ["sulfide", "garnet"])
        self.assertEqual(res["n_raw"], 10)              # 2 查询 × 2 来源 × (3|2) 条
        self.assertEqual(len(res["per_query"]), 2)
        # nmat3006 在两个来源都命中 → 合并为一条
        dois = [r["doi"] for r in res["records"]]
        self.assertEqual(len(dois), len(set(dois)))

    def test_single_failure_does_not_break_overall(self):
        good = fake_transport(CROSSREF_PAYLOAD)

        def t(url):
            if "openalex" in url:
                raise OSError("boom")
            return good(url)

        res = L.search(["sulfide"], sources=(L.CROSSREF, L.OPENALEX),
                       transport=t, sleep_s=0, sleep=lambda s: None)
        self.assertEqual(res["n_unique"], 3)            # Crossref 结果仍在
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("openalex", res["errors"][0]["source"])

    def test_all_failures_yield_zero_hits(self):
        """零命中场景的原料：全部来源失败 → records 空、errors 非空。"""
        def t(url):
            raise OSError("network down")

        res = L.search(["sulfide"], sources=(L.CROSSREF, L.OPENALEX),
                       transport=t, retries=0, sleep_s=0, sleep=lambda s: None)
        self.assertEqual(res["records"], [])
        self.assertEqual(res["n_unique"], 0)
        self.assertEqual(len(res["errors"]), 2)

    def test_output_deterministic(self):
        res1 = L.search(["sulfide"], transport=fake_transport(CROSSREF_PAYLOAD),
                        sleep_s=0, sleep=lambda s: None)
        res2 = L.search(["sulfide"], transport=fake_transport(CROSSREF_PAYLOAD),
                        sleep_s=0, sleep=lambda s: None)
        self.assertEqual(res1["records"], res2["records"])


if __name__ == "__main__":
    unittest.main()
