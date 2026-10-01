"""test_provenance.py — 证据账本、结论绑定、引文渲染。"""
import json
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root  # noqa: E402

from paper_agent.provenance import ProvenanceLedger, EvidenceError  # noqa: E402


def _sample_file(tmp: str, name: str, content: str) -> str:
    p = os.path.join(tmp, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return p


class TestProvenance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_prov_")
        self.root = build_temp_root(self._tmp)
        self.run_dir = os.path.join(self.root, "runs", "run-test")
        os.makedirs(self.run_dir, exist_ok=True)
        self.prov = ProvenanceLedger(self.run_dir, "run-test")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ev_ids_increment(self):
        e1 = self.prov.append_evidence("literature", "10.1038/nmat3006",
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
        ev = self.prov.append_evidence("literature", "10.1038/nmat3006",
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
            "literature", "10.1038/nmat3006", "P1_lit_search")
        text = self.prov.cite(ev)
        self.assertIn("10.1038/nmat3006", text)
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


if __name__ == "__main__":
    unittest.main()
