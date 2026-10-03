"""test_litsearch_multi.py — 多源检索（PRD F-1.1）。

全部离线：解析器为纯函数；search_papers 通过注入伪后端验证
去重 / 单源超时降级 / 相关性排序，不触网。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root  # noqa: E402

from paper_agent import litsearch as LS  # noqa: E402


def _doc(doc_id, doi="", title="T", authors=None, source="arxiv", citations=0,
         keywords=None, abstract=""):
    return {"doc_id": doc_id, "doi": doi, "title": title,
            "authors": authors or [], "venue": "V", "year": 2024,
            "keywords": keywords or [], "abstract": abstract,
            "url": f"https://x/{doc_id}", "source": source, "citations": citations}


class TestParsers(unittest.TestCase):
    def test_parse_semantic_scholar(self):
        payload = {"data": [{
            "paperId": "abc", "title": "GNN for molecules", "year": 2021,
            "venue": "NeurIPS", "authors": [{"name": "X Y"}],
            "externalIds": {"DOI": "10.2/y", "ArXiv": "2101.1"},
            "citationCount": 42, "url": "", "fieldsOfStudy": ["CS"], "abstract": "a"}]}
        d = LS.parse_semantic_scholar(payload)[0]
        self.assertEqual(d["doc_id"], "SS:abc")
        self.assertEqual(d["doi"], "10.2/y")
        self.assertEqual(d["citations"], 42)
        self.assertEqual(d["url"], "https://arxiv.org/abs/2101.1")  # 无 url 时回退 arxiv
        self.assertEqual(d["authors"], ["X Y"])

    def test_parse_openalex_reconstructs_abstract(self):
        payload = {"results": [{
            "id": "https://openalex.org/W1", "doi": "https://doi.org/10.3/z",
            "title": "Perovskite", "publication_year": 2020,
            "authorships": [{"author": {"display_name": "A B"}}],
            "primary_location": {"source": {"display_name": "Nature"},
                                 "landing_page_url": "https://oa/1"},
            "cited_by_count": 7,
            "abstract_inverted_index": {"Hello": [0], "world": [1]},
            "concepts": [{"display_name": "Materials"}]}]}
        d = LS.parse_openalex(payload)[0]
        self.assertEqual(d["doc_id"], "OpenAlex:W1")
        self.assertEqual(d["doi"], "10.3/z")
        self.assertEqual(d["abstract"], "Hello world")
        self.assertEqual(d["citations"], 7)
        self.assertEqual(d["venue"], "Nature")

    def test_parse_crossref(self):
        payload = {"message": {"items": [{
            "DOI": "10.4/w", "title": ["A title"],
            "author": [{"given": "J", "family": "Doe"}],
            "issued": {"date-parts": [[2019, 5]]},
            "container-title": ["J. Test"], "URL": "https://doi.org/10.4/w",
            "is-referenced-by-count": 3, "subject": ["Chem"]}]}}
        d = LS.parse_crossref(payload)[0]
        self.assertEqual(d["doc_id"], "CrossRef:10.4/w")
        self.assertEqual(d["year"], 2019)
        self.assertEqual(d["authors"], ["J Doe"])
        self.assertEqual(d["venue"], "J. Test")

    def test_parsers_tolerate_empty(self):
        self.assertEqual(LS.parse_semantic_scholar({}), [])
        self.assertEqual(LS.parse_openalex({}), [])
        self.assertEqual(LS.parse_crossref({}), [])


class TestDedupAndRank(unittest.TestCase):
    def test_doi_exact_dedup_merges_sources(self):
        docs = [_doc("A", doi="10.1/x", source="arxiv", citations=5),
                _doc("B", doi="10.1/X", source="openalex", citations=9)]
        out = LS.dedup_documents(docs)
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(out[0]["sources"]), ["arxiv", "openalex"])
        self.assertEqual(out[0]["citations"], 9)   # 取最大

    def test_title_author_fuzzy_dedup_without_doi(self):
        docs = [_doc("A", title="Sulfide Solid Electrolyte!!", authors=["Ada Lovelace"]),
                _doc("B", title="sulfide solid electrolyte", authors=["A. Lovelace"])]
        out = LS.dedup_documents(docs)
        self.assertEqual(len(out), 1)

    def test_distinct_docs_kept(self):
        docs = [_doc("A", doi="10.1/x"), _doc("B", doi="10.1/y")]
        self.assertEqual(len(LS.dedup_documents(docs)), 2)

    def test_relevance_weights_title_over_abstract(self):
        goal = "sulfide electrolyte"
        title_hit = _doc("T", title="sulfide electrolyte study")
        abstract_hit = _doc("A", abstract="sulfide electrolyte study")
        self.assertGreater(LS.score_relevance(title_hit, goal),
                           LS.score_relevance(abstract_hit, goal))

    def test_rank_is_stable(self):
        goal = "sulfide electrolyte"
        docs = [_doc("Z", title="sulfide electrolyte"), _doc("Y", title="sulfide electrolyte")]
        r1 = [d["doc_id"] for d in LS.rank_documents(docs, goal)]
        r2 = [d["doc_id"] for d in LS.rank_documents(list(reversed(docs)), goal)]
        self.assertEqual(r1, r2)


class TestSearchPapers(unittest.TestCase):
    def _backends(self):
        def ok_arxiv(goal, n, t):
            return ([_doc("A1", doi="10.1/x", title="sulfide electrolyte",
                          source="arxiv", citations=5)], "all:sulfide")

        def dup_openalex(goal, n, t):
            return ([_doc("O1", doi="10.1/x", title="sulfide electrolyte",
                          source="openalex", citations=9),
                     _doc("O2", doi="10.1/z", title="garnet", source="openalex")], goal)

        def boom(goal, n, t):
            raise TimeoutError("ss down")

        return {"arxiv": ok_arxiv, "openalex": dup_openalex,
                "semantic_scholar": boom}

    def test_dedup_and_single_source_failure(self):
        out = LS.search_papers("sulfide electrolyte",
                               sources=["arxiv", "openalex", "semantic_scholar"],
                               backends=self._backends())
        self.assertEqual(out["n_raw"], 3)
        self.assertEqual(out["n_documents"], 2)      # DOI 去重
        self.assertEqual(out["unavailable_sources"], ["semantic_scholar"])
        self.assertEqual(out["sources_status"]["semantic_scholar"],
                         "unavailable:TimeoutError")
        self.assertFalse(out["degraded"])            # 仍有可用源 → 非整体降级

    def test_all_sources_fail_marks_degraded(self):
        def boom(goal, n, t):
            raise OSError("net")
        out = LS.search_papers("x", sources=["arxiv", "openalex"],
                               backends={"arxiv": boom, "openalex": boom})
        self.assertTrue(out["degraded"])
        self.assertEqual(out["n_documents"], 0)

    def test_unknown_source_skipped(self):
        out = LS.search_papers("x", sources=["arxiv", "nope"],
                               backends={"arxiv": lambda g, n, t: ([], g)})
        self.assertEqual(out["skipped_sources"], ["nope"])

    def test_max_results_truncates(self):
        def many(goal, n, t):
            return ([_doc(f"D{i}", doi=f"10.1/{i}", title="sulfide") for i in range(20)], goal)
        out = LS.search_papers("sulfide", sources=["arxiv"], max_results=3,
                               backends={"arxiv": many})
        self.assertEqual(out["n_documents"], 3)


if __name__ == "__main__":
    unittest.main()
