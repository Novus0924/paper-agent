"""test_provenance.py — 证据账本、结论绑定、引文渲染、尾部崩溃残留自愈。"""
import contextlib
import io
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


class TestLedgerTailRecovery(unittest.TestCase):
    """MAINT-9：账本尾部崩溃残留自愈（中间坏行仍响亮失败）。

    进程崩溃于 append 中途会在 provenance.jsonl 尾部留下半行 JSON：
    - 尾部残留 → 截断自愈（stderr 告警），load/verify_chain/append 恢复一致；
    - 中间坏行 → 抛 EvidenceError（疑似篡改或磁盘问题，拒绝加载）。
    """

    def setUp(self):
        self.root = isolate_temp_root(self, "pa_prov9_")
        self.run_dir = os.path.join(self.root, "runs", "run-tail")
        os.makedirs(self.run_dir, exist_ok=True)
        # 建有效账本：两条合法记录（带 chain_hash 链）
        prov = ProvenanceLedger(self.run_dir, "run-tail")
        prov.append_evidence("literature", "10.1038/nmat3066", "P1_lit_search")
        prov.append_evidence("data", "clean/x.csv", "P2_clean_data")
        self.path = os.path.join(self.run_dir, "provenance.jsonl")

    def _raw(self) -> str:
        with open(self.path, "r", encoding="utf-8", newline="") as f:
            return f.read()

    def _load_with_stderr(self) -> tuple[ProvenanceLedger, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            prov = ProvenanceLedger(self.run_dir, "run-tail")
        return prov, err.getvalue()

    def test_tail_half_line_self_heals_and_append_continues(self):
        """尾部半行：load 成功 + stderr 告警 + 截断回有效态 + append 接续正常。"""
        # 模拟进程崩溃于 append 中途：残留半行 JSON（无换行）
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write('{"ev_id": "EV-99", "chain_hash": "abc')
        prov, warning = self._load_with_stderr()

        # ① load 成功，只有崩溃前两条有效记录，残留未混入索引
        self.assertTrue(prov.has("EV-0001"))
        self.assertTrue(prov.has("EV-0002"))
        self.assertFalse(prov.has("EV-99"))
        self.assertEqual(prov.next_ev_num, 3)
        # ② stderr 恰有告警（含文件路径与截断字节数），不污染 stdout
        self.assertIn("截断", warning)
        self.assertIn(self.path, warning)
        # ③ 文件被截断回有效态：全行可解析、以换行结尾
        raw = self._raw()
        self.assertTrue(raw.endswith("\n"))
        for line in raw.splitlines():
            json.loads(line)
        self.assertEqual(len(raw.splitlines()), 2)
        # ④ 自愈后链完整
        self.assertEqual(prov.verify_chain(), [])
        # ⑤ 后续 append 正常：ev_id 序号接续、chain_hash 接续、从新行开始
        ev = prov.append_evidence("experiment", "exp/r.csv", "P3_run_experiment")
        self.assertEqual(ev, "EV-0003")
        self.assertEqual(prov.verify_chain(), [])
        lines = self._raw().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[-1])["ev_id"], "EV-0003")
        self.assertTrue(json.loads(lines[-1])["chain_hash"])
        self.assertEqual(json.loads(lines[-2])["ev_id"], "EV-0002")

    def test_mid_corrupt_line_fails_loud_with_lineno(self):
        """中间坏行（其后仍有有效行）→ 抛 EvidenceError 且错误消息含行号。"""
        lines = self._raw().splitlines()
        corrupted = lines[:1] + ['{"ev_id": "EV-77", "brok'] + lines[1:]
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(corrupted) + "\n")
        with self.assertRaises(EvidenceError) as cm:
            ProvenanceLedger(self.run_dir, "run-tail")
        msg = str(cm.exception)
        self.assertIn("第 2 行", msg)
        self.assertIn("拒绝加载", msg)

    def test_mid_and_tail_bad_lines_fail_loud_without_truncation(self):
        """复验修正：中间坏行与尾部坏行并存（[有效, 坏, 有效, 坏]）→ 必须响亮失败。

        若先判尾部自愈，中间坏行（第 2 行）会被静默放过——load 成功但坏行
        留在文件里、verify_chain 报 problem，load/verify 信任语义分裂。
        锁定：中间坏行优先无条件拒绝加载，且文件不被截断。
        """
        lines = self._raw().splitlines()
        corrupted = lines[:1] + ['{"ev_id": "EV-77", "brok'] \
            + lines[1:2] + ['{"ev_id": "EV-88", "chain_hash": "xyz']
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(corrupted) + "\n")
        before = self._raw()
        with self.assertRaises(EvidenceError) as cm:
            ProvenanceLedger(self.run_dir, "run-tail")
        self.assertIn("第 2 行", str(cm.exception))
        # 文件原样保留（不截断），保留现场供审计
        self.assertEqual(self._raw(), before)

    def test_verify_chain_clean_after_self_heal(self):
        """自愈后 verify_chain() 返回空（链完整）。"""
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write('{"ev_id": "EV-98", "chain_hash": "xyz", "kind"')
        prov, _ = self._load_with_stderr()
        self.assertEqual(prov.verify_chain(), [])


if __name__ == "__main__":
    unittest.main()
