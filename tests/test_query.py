"""test_query.py — 证据查询层（Batch 4 / B4-1）：跨 run 检索、引文图、聚合、全库链校验。

只读查询层，全部用例在隔离临时根内构造迷你 run（2-3 条 provenance），
绝不触碰真实 runs/。哈希链校验断言复用 provenance.verify_chain 的既有的
篡改检出语义（与 test_security_scan.py::TestProvenanceChain 同手法）。
"""
import json
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent import query as q  # noqa: E402
from paper_agent.provenance import ProvenanceLedger  # noqa: E402


def _make_run(root: str, rid: str, *, goal: str = "g", workflow: str = "research",
              status: str = "DONE", degraded: bool = False,
              with_conclusion: bool = True,
              doi: str = "10.1038/nmat3066",
              lit_title: str = "A lithium superionic conductor",
              data_title: str = "OBELiX cleaned") -> str:
    """在隔离根内构造一个迷你 run：2 条 fact + 1 条 judgment（链哈希由账本生成）。

    各 run 的 DOI/标题可定制 → 让 kw/doi 过律试题只命中预期 run。
    """
    run_dir = os.path.join(root, "runs", rid)
    os.makedirs(run_dir, exist_ok=True)
    prov = ProvenanceLedger(run_dir, rid)
    prov.append_evidence("literature", doi, "R1_search",
                         meta={"title": lit_title, "sources": ["crossref"]})
    prov.append_evidence("data", "clean/x.csv", "P2_clean_data",
                         meta={"title": data_title, "sources": ["local"]})
    prov.append_judgment("relevance", "R1_search", "10.1/noise", "excluded",
                         "与固态体系无关")
    if with_conclusion:
        prov.link_conclusion("C1", "结论一：LGPS 是超离子导体", ["EV-0001"])
    with open(os.path.join(run_dir, "state.json"), "w",
              encoding="utf-8", newline="") as f:
        json.dump({"run_id": rid, "goal": goal, "workflow": workflow,
                   "run_status": status, "degraded": degraded,
                   "steps_order": ["R1_search"], "steps": {"R1_search": "DONE"},
                   "attempts": {}}, f, ensure_ascii=False)
    return run_dir


class TestQueryBase(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_query_")
        self.runs = os.path.join(self.root, "runs")
        _make_run(self.root, "run-alpha", goal="硫化物综述")
        _make_run(self.root, "run-beta", goal=" garnet 调研", workflow="materials",
                  status="RUNNING", degraded=True,
                  doi="10.1002/anie.200701144",
                  lit_title="Fast lithium ion conduction in garnet-type LLZO",
                  data_title="conductivity raw")


class TestQueryRuns(TestQueryBase):
    def test_kw_hits_title_ref_and_kind(self):
        hits = q.query_runs(self.runs, kw="superionic")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["run_id"], "run-alpha")
        self.assertEqual(hits[0]["ev_id"], "EV-0001")
        self.assertEqual(len(q.query_runs(self.runs, kw="obelix")), 1)
        self.assertEqual(len(q.query_runs(self.runs, kw="不存在的词")), 0)
        # kw 大小写不敏感
        self.assertEqual(len(q.query_runs(self.runs, kw="SUPERIONIC")), 1)

    def test_tier_filter(self):
        facts = q.query_runs(self.runs, tier="fact")
        self.assertTrue(facts)
        self.assertTrue(all(i["tier"] == "fact" for i in facts))
        juds = q.query_runs(self.runs, tier="judgment")
        self.assertEqual(len(juds), 2)          # 每个 run 一条 judgment
        self.assertTrue(all(i["kind"] == "relevance" for i in juds))

    def test_doi_exact_match(self):
        hits = q.query_runs(self.runs, doi="10.1038/nmat3066")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["run_id"], "run-alpha")
        hits = q.query_runs(self.runs, doi="10.1002/anie.200701144")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["run_id"], "run-beta")
        self.assertEqual(q.query_runs(self.runs, doi="10.9999/nope"), [])

    def test_kind_and_source_filter(self):
        self.assertEqual({i["kind"] for i in q.query_runs(self.runs, kind="data")},
                         {"data"})
        src = q.query_runs(self.runs, source="crossref")
        self.assertEqual(len(src), 2)            # 每个 run 的文献证据均来自 crossref
        self.assertEqual({i["ev_id"] for i in src}, {"EV-0001"})
        self.assertEqual(q.query_runs(self.runs, source="arxiv"), [])

    def test_run_ids_restricts_scope(self):
        hits = q.query_runs(self.runs, kw="superionic", run_ids=["run-beta"])
        self.assertEqual(hits, [])
        hits = q.query_runs(self.runs, run_ids=["run-alpha"])
        self.assertTrue(hits)
        self.assertTrue(all(i["run_id"] == "run-alpha" for i in hits))

    def test_limit_truncates(self):
        hits = q.query_runs(self.runs, limit=2)
        self.assertEqual(len(hits), 2)

    def test_unknown_run_id_is_skipped_not_fatal(self):
        hits = q.query_runs(self.runs, run_ids=["run-nope"])
        self.assertEqual(hits, [])

    def test_traversal_run_id_rejected(self):
        for bad in ("../escape", "a/b", "a\\b", "..", "run-..x"):
            with self.assertRaises(q.QueryError):
                q.query_runs(self.runs, run_ids=[bad])


class TestCitationGraph(TestQueryBase):
    def test_three_layer_shape(self):
        g = q.citation_graph(self.runs, "run-alpha")
        self.assertEqual(g["run_id"], "run-alpha")
        self.assertEqual(g["n_conclusions"], 1)
        self.assertEqual(g["n_evidence"], 1)     # 只有被结论绑定的 EV 进图
        self.assertEqual(g["conclusions"][0]["id"], "C1")
        kinds = {(e["from"], e["to"]) for e in g["edges"]}
        self.assertIn(("C1", "EV-0001"), kinds)                    # C → EV
        self.assertIn(("EV-0001", "10.1038/nmat3066"), kinds)      # EV → ref
        ev = g["evidence"][0]
        self.assertEqual(ev["title"], "A lithium superionic conductor")
        self.assertEqual(ev["tier"], "fact")

    def test_dangling_binding_keeps_edge_but_no_node(self):
        """悬空引用：C→EV 边保留（暴露不一致），但不造出假 evidence 节点。"""
        run_dir = _make_run(self.root, "run-dangling", with_conclusion=False)
        with open(os.path.join(run_dir, "conclusions.jsonl"), "a",
                  encoding="utf-8", newline="") as f:
            f.write(json.dumps({"cid": "C9", "text": "悬空",
                                "evidence_ids": ["EV-9999"]}) + "\n")
        g = q.citation_graph(self.runs, "run-dangling")
        self.assertIn(("C9", "EV-9999"), {(e["from"], e["to"]) for e in g["edges"]})
        self.assertEqual(g["n_evidence"], 0)     # EV-9999 不存在 → 不进节点（该 run 无合法绑定）

    def test_traversal_run_id_rejected(self):
        with self.assertRaises(q.QueryError):
            q.citation_graph(self.runs, "../../etc")


class TestAggregate(TestQueryBase):
    def test_counts_and_top_dois(self):
        agg = q.aggregate_runs(self.runs)
        self.assertEqual(agg["n_runs"], 2)
        by_id = {r["run_id"]: r for r in agg["runs"]}
        self.assertEqual(by_id["run-alpha"]["n_evidence"], 3)
        self.assertEqual(by_id["run-alpha"]["n_conclusions"], 1)
        self.assertEqual(by_id["run-alpha"]["workflow"], "research")
        self.assertEqual(by_id["run-alpha"]["run_status"], "DONE")
        self.assertTrue(by_id["run-beta"]["degraded"])
        self.assertEqual(by_id["run-beta"]["workflow"], "materials")
        dois = {d["doi"]: d["count"] for d in agg["top_dois"]}
        self.assertEqual(dois.get("10.1038/nmat3066"), 1)
        self.assertEqual(dois.get("10.1002/anie.200701144"), 1)


class TestVerifyAllChains(TestQueryBase):
    def test_all_clean(self):
        res = q.verify_all_chains(self.runs)
        self.assertTrue(res["ok"])
        self.assertEqual(res["n_runs"], 2)
        self.assertTrue(all(r["ok"] and r["first_bad_line"] is None
                            for r in res["runs"]))

    def test_tampered_record_detected_with_line(self):
        """篡改一条记录（不重算链）→ verify_all 检出并给出坏链行号。"""
        target = os.path.join(self.runs, "run-beta", "provenance.jsonl")
        with open(target, "r", encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        rec = json.loads(lines[1])
        rec["ref"] = "forged/path.csv"           # 只改记录体，不重算链哈希
        lines[1] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines) + "\n")

        res = q.verify_all_chains(self.runs)
        self.assertFalse(res["ok"])
        by_id = {r["run_id"]: r for r in res["runs"]}
        self.assertFalse(by_id["run-beta"]["ok"])
        self.assertTrue(by_id["run-alpha"]["ok"])   # 未篡改的 run 不受牵连
        self.assertEqual(by_id["run-beta"]["first_bad_line"], 2)
        self.assertIn("chain hash mismatch",
                      by_id["run-beta"]["problems"][0])

    def test_run_ids_scope(self):
        res = q.verify_all_chains(self.runs, run_ids=["run-alpha"])
        self.assertEqual(res["n_runs"], 1)
        self.assertEqual(res["runs"][0]["run_id"], "run-alpha")


class TestValidRunId(unittest.TestCase):
    def test_accepts_normal_ids(self):
        self.assertTrue(q.valid_run_id("run-20261008-064350-b354f6"))
        self.assertTrue(q.valid_run_id("run-alpha"))

    def test_rejects_traversal_and_separators(self):
        for bad in ("", "../escape", "a/b", "a\\b", "..", ".hidden", "x/y/z"):
            self.assertFalse(q.valid_run_id(bad), bad)


if __name__ == "__main__":
    unittest.main()
