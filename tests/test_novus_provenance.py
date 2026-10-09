"""test_provenance.py — 证据账本、结论绑定、引文渲染。"""
import json
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent.provenance import ProvenanceLedger, EvidenceError  # noqa: E402


def _sample_file(tmp: str, name: str, content: str) -> str:
    p = os.path.join(tmp, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return p


class TestProvenance(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_prov_")
        self.run_dir = os.path.join(self.root, "runs", "run-test")
        os.makedirs(self.run_dir, exist_ok=True)
        self.prov = ProvenanceLedger(self.run_dir, "run-test")

    def test_ev_ids_increment(self):
        e1 = self.prov.append_evidence("literature", "10.1038/nmat3066",
                                        "P1_lit_search")
        e2 = self.prov.append_evidence("data", "clean/x.csv", "P2_clean_data",
                                        file_path=_sample_file(self._tmp, "x.csv", "a,b\n1,2\n"))
        self.assertEqual(e1, "EV-0001")
        self.assertEqual(e2, "EV-0002")
        self.assertTrue(self.prov.has("EV-0001"))
        self.assertTrue(self.prov.has("EV-0002"))

    def test_file_sha256_recorded(self):
        p = _sample_file(self._tmp, "f.bin", "hello")
        ev = self.prov.append_evidence("experiment", "f.bin", "P3_run_experiment",
                                        file_path=p)
        rec = self.prov.get(ev)
        self.assertGreater(len(rec["sha256"]), 0)
        self.assertEqual(len(rec["sha256"]), 64)
        # 计算实际 sha256 对照
        import hashlib
        self.assertEqual(rec["sha256"], hashlib.sha256(b"hello").hexdigest())

    def test_literature_sha_empty(self):
        ev = self.prov.append_evidence("literature", "10.1002/anie.200701144",
                                        "P1_lit_search")
        self.assertEqual(self.prov.get(ev)["sha256"], "")

    def test_conclusion_requires_existing_evidence(self):
        ev = self.prov.append_evidence("literature", "10.1038/nmat3066",
                                        "P1_lit_search")
        # 合法绑定
        self.prov.link_conclusion("C1", "结论一", [ev])
        with self.assertRaises(EvidenceError):
            self.prov.link_conclusion("C2", "结论二", ["EV-9999"])  # 不存在
        # 无证据必须快速失败
        with self.assertRaises(EvidenceError):
            self.prov.link_conclusion("C3", "无证据结论", [])

    def test_conclusions_persisted(self):
        ev = self.prov.append_evidence("verification", "verification.json",
                                        "P4_verify")
        self.prov.link_conclusion("C4", "复现通过", [ev])
        cpath = os.path.join(self.run_dir, "conclusions.jsonl")
        with open(cpath, "r", encoding="utf-8") as f:
            rec = json.loads(f.readline())
        self.assertEqual(rec["cid"], "C4")
        self.assertEqual(rec["evidence_ids"], [ev])

    def test_cite_literature(self):
        ev = self.prov.append_evidence(
            "literature", "10.1038/nmat3066", "P1_lit_search")
        text = self.prov.cite(ev)
        self.assertIn("10.1038/nmat3066", text)
        self.assertIn("Nature Materials", text)  # 从 literature.json 取元数据

    def test_cite_file_artifact(self):
        p = _sample_file(self._tmp, "out.bin", "12345")
        ev = self.prov.append_evidence("experiment", "out.bin", "P3_run_experiment",
                                        file_path=p)
        text = self.prov.cite(ev)
        self.assertIn("EV-0001", text)
        self.assertIn("experiment", text)
        # 含 sha256 前 16 位
        self.assertIn("sha256=", text)

    def test_cite_unknown_raises(self):
        with self.assertRaises(EvidenceError):
            self.prov.cite("EV-7777")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(EvidenceError):
            self.prov.append_evidence("weird_kind", "x", "P1_lit_search")

    def test_ledger_reloaded_on_new_instance(self):
        ev = self.prov.append_evidence("figure", "fig.svg", "P3_run_experiment",
                                        file_path=_sample_file(self._tmp, "fig.svg", "<svg/>"))
        prov2 = ProvenanceLedger(self.run_dir, "run-test")
        self.assertTrue(prov2.has(ev))
        self.assertEqual(prov2.next_ev_num, 2)


class TestThreeTierTrust(unittest.TestCase):
    """三级信任模型：fact 可进结论，judgment 不得进结论（redesign D5 / 判据 4）。"""

    def setUp(self):
        self.root = isolate_temp_root(self, "pa_tier_")
        self.run_dir = os.path.join(self.root, "runs", "run-tier")
        os.makedirs(self.run_dir, exist_ok=True)
        self.prov = ProvenanceLedger(self.run_dir, "run-tier")

    def test_fact_evidence_is_tiered_fact(self):
        ev = self.prov.append_evidence("data", "x.csv", "P2_clean_data",
                                       file_path=_sample_file(self._tmp, "x.csv", "a\n1\n"))
        self.assertEqual(self.prov.get(ev)["tier"], "fact")
        self.assertEqual([r["ev_id"] for r in self.prov.facts()], [ev])
        self.assertEqual(self.prov.judgments(), [])

    def test_judgment_recorded_with_rationale(self):
        ev = self.prov.append_judgment(
            judgment_kind="relevance", producer_step="P1_lit_search",
            subject="10.1234/fake", verdict="excluded",
            rationale="主题为液态电解质，与固态体系无关")
        rec = self.prov.get(ev)
        self.assertEqual(rec["tier"], "judgment")
        self.assertEqual(rec["meta"]["verdict"], "excluded")
        self.assertEqual([r["ev_id"] for r in self.prov.judgments()], [ev])
        # judgment 不进入 fact 视图
        self.assertEqual(self.prov.facts(), [])

    def test_query_generation_judgment_kind(self):
        ev = self.prov.append_judgment(
            judgment_kind="query_generation", producer_step="P1_lit_search",
            subject="sulfide solid electrolyte", verdict="generated",
            rationale="拆分为材料体系+性能维度两组关键词",
            meta={"queries": ["sulfide electrolyte conductivity",
                              "argyrodite ionic conductivity"]})
        self.assertEqual(self.prov.get(ev)["meta"]["queries"][0],
                         "sulfide electrolyte conductivity")

    def test_unknown_judgment_kind_rejected(self):
        with self.assertRaises(EvidenceError):
            self.prov.append_judgment("wild_guess", "P1_lit_search", "s", "v")

    def test_conclusion_rejects_judgment_evidence(self):
        """核心红线：判断不得支撑结论。"""
        j = self.prov.append_judgment("relevance", "P1_lit_search",
                                      "10.1/x", "relevant", "题目直接相关")
        with self.assertRaises(EvidenceError) as cm:
            self.prov.link_conclusion("C1", "试图用判断当证据", [j])
        self.assertIn("tier", str(cm.exception))
        # 混绑（fact + judgment）同样必须失败
        f = self.prov.append_evidence("literature", "10.1038/nmat3066",
                                      "P1_lit_search")
        with self.assertRaises(EvidenceError):
            self.prov.link_conclusion("C2", "混绑", [f, j])

    def test_link_conclusion_accepts_fact_only(self):
        f = self.prov.append_evidence("literature", "10.1038/nmat3066",
                                      "P1_lit_search")
        self.prov.link_conclusion("C1", "正常结论", [f])
        self.assertEqual(self.prov.check_binding_invariants(), [])

    def test_excluded_judgments_are_listed(self):
        self.prov.append_judgment("relevance", "P1_lit_search", "doi:a",
                                  "relevant", "相关")
        self.prov.append_judgment("relevance", "P1_lit_search", "doi:b",
                                  "excluded", "仅研究液态体系")
        self.prov.append_judgment("relevance", "P1_lit_search", "doi:c",
                                  "excluded", "未报告室温电导率")
        ex = self.prov.excluded_judgments()
        self.assertEqual(len(ex), 2)
        self.assertEqual({r["meta"]["subject"] for r in ex}, {"doi:b", "doi:c"})
        # 被排除项必须带理由，便于复核与反驳
        for r in ex:
            self.assertTrue(r["meta"]["rationale"])

    def test_require_judgment_batch_gate(self):
        """判据 4：账本无判断记录时，报告生成的前置校验必须失败。"""
        with self.assertRaises(EvidenceError):
            self.prov.require_judgment_batch()
        self.prov.append_judgment("query_generation", "P1_lit_search",
                                  "goal", "generated", "拆分关键词")
        self.prov.require_judgment_batch()  # 存在判断记录 → 通过

    def test_binding_invariants_tolerates_bad_line(self):
        """BIND-1：conclusions.jsonl 坏行 → 审计函数报告行号问题而非崩溃。

        审计职责是**报告问题**（口径对齐 verify_chain）；自愈截断是
        load 侧的职责，此处不做自愈。
        """
        f = self.prov.append_evidence("literature", "10.1/ok", "P1_lit_search")
        self.prov.link_conclusion("C1", "正常结论", [f])
        cpath = os.path.join(self.run_dir, "conclusions.jsonl")
        with open(cpath, "a", encoding="utf-8", newline="") as fh:
            fh.write("{broken json\n")          # 行 2：JSONDecodeError
            fh.write('"just a string"\n')       # 行 3：解析结果非 dict
        problems = self.prov.check_binding_invariants()  # 不应抛异常
        self.assertTrue(any("line 2" in p and "not valid JSON" in p
                            for p in problems),
                        f"坏行 2 未被报告: {problems}")
        self.assertTrue(any("line 3" in p and "not valid JSON" in p
                            for p in problems),
                        f"非 dict 行 3 未被报告: {problems}")
        # 正常行（行 1）不受坏行影响，仍参与校验且无问题
        self.assertFalse(any("C1" in p for p in problems))

    def test_cite_judgment_is_readable(self):
        ev = self.prov.append_judgment("relevance", "P1_lit_search",
                                       "10.1038/nmat3066", "relevant",
                                       "标题含 sulfide 与 ionic conductivity")
        text = self.prov.cite(ev)
        self.assertIn("judgment", text)
        self.assertIn("relevant", text)
        self.assertIn("sulfide", text)

    def test_legacy_record_without_tier_treated_as_fact(self):
        """向后兼容：旧账本记录无 tier 字段，必须视为 fact 并可正常支撑结论。"""
        rec = {"ev_id": "EV-0001", "kind": "literature", "ref": "10.1/legacy",
               "sha256": "", "producer_step": "P1_lit_search", "meta": {}}
        with open(os.path.join(self.run_dir, "provenance.jsonl"),
                  "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(rec) + "\n")
        prov = ProvenanceLedger(self.run_dir, "run-tier")
        self.assertEqual(prov.tier_of(prov.get("EV-0001")), "fact")
        prov.link_conclusion("C1", "旧账本结论", ["EV-0001"])
        self.assertEqual(prov.check_binding_invariants(), [])

    def test_invariant_checker_detects_non_fact_binding(self):
        """审计不变量：外部写入的非法绑定（judgment 当证据）必须被查出。"""
        j = self.prov.append_judgment("relevance", "P1_lit_search",
                                      "doi:x", "relevant", "相关")
        with open(os.path.join(self.run_dir, "conclusions.jsonl"),
                  "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps({"cid": "C9", "text": "非法绑定",
                                "evidence_ids": [j]}) + "\n")
        problems = self.prov.check_binding_invariants()
        self.assertTrue(any("non-fact" in p for p in problems))

    def test_invariant_checker_detects_unknown_evidence(self):
        with open(os.path.join(self.run_dir, "conclusions.jsonl"),
                  "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps({"cid": "C8", "text": "悬空引用",
                                "evidence_ids": ["EV-9999"]}) + "\n")
        problems = self.prov.check_binding_invariants()
        self.assertTrue(any("unknown evidence" in p for p in problems))

    def test_single_id_space_across_tiers(self):
        """单一 EV 编号空间：fact 与 judgment 交替登记仍连续。"""
        a = self.prov.append_evidence("data", "a.csv", "P2_clean_data")
        b = self.prov.append_judgment("relevance", "P1_lit_search", "d", "relevant")
        c = self.prov.append_evidence("data", "b.csv", "P2_clean_data")
        self.assertEqual([a, b, c], ["EV-0001", "EV-0002", "EV-0003"])


if __name__ == "__main__":
    unittest.main()
