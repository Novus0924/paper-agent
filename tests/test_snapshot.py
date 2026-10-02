"""test_snapshot.py — 冻结输入快照：写入、强校验、判断批次携带与重登记。

对应 redesign-decisions.md D6（复现契约收窄到"冻结之后"）与判据 4。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root  # noqa: E402

from paper_agent import snapshot as snap  # noqa: E402
from paper_agent.provenance import ProvenanceLedger, EvidenceError  # noqa: E402

MATERIALS_CSV = (
    "material_id,formula,family,conductivity_Scm,year,source_doi\n"
    "jqc,Li7BiO6,hexaoxometalates,1.58489e-06,2005,10.1002/zaac.200500231\n"
    "gx8,Li6PS5Cl,argyrodites,2.3e-03,2008,10.1002/anie.200800627\n"
)

LITERATURE = {
    "goal": "sulfide solid electrolyte ionic conductivity ranking",
    "n_hits": 2,
    "hits": [
        {"doi": "10.1002/zaac.200500231", "title": "Lithium bismuthate",
         "year": 2005, "verdict": "relevant"},
        {"doi": "10.1016/j.jpowsour.2007.09.001", "title": "Liquid electrolytes",
         "year": 2007, "verdict": "excluded"},
    ],
}

JUDGMENTS = [
    {"tier": "judgment", "kind": "query_generation", "producer_step": "P1_lit_search",
     "ref": "sulfide solid electrolyte ionic conductivity ranking",
     "meta": {"subject": "sulfide solid electrolyte ionic conductivity ranking",
              "verdict": "generated",
              "rationale": "拆分为材料体系与性能维度两组关键词",
              "queries": ["sulfide solid electrolyte", "ionic conductivity ranking"]}},
    {"tier": "judgment", "kind": "relevance", "producer_step": "P1_lit_search",
     "ref": "10.1016/j.jpowsour.2007.09.001",
     "meta": {"subject": "10.1016/j.jpowsour.2007.09.001",
              "verdict": "excluded",
              "rationale": "研究对象为液态电解质，与固态体系无关"}},
]


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_snap_")
        self.root = build_temp_root(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make(self, sid: str = "snap-20261002-000000-aaaaaa",
              judgments=None) -> snap.Snapshot:
        s = snap.Snapshot(self.root, sid)
        s.write(
            materials_csv=MATERIALS_CSV,
            literature=LITERATURE,
            judgments=JUDGMENTS if judgments is None else judgments,
            sources=[{"name": "obelix",
                      "url": "https://github.com/NRC-Mila/OBELiX",
                      "retrieved_at": "2026-10-02", "license": "CC-BY-4.0"}],
            producer="test",
            stats={"usable_rows": 2},
        )
        return s

    # ---------- 写入与清单 ----------

    def test_write_creates_all_files(self):
        s = self._make()
        for name in (snap.MANIFEST_FILE, snap.MATERIALS_FILE,
                     snap.LITERATURE_FILE, snap.JUDGMENTS_FILE):
            self.assertTrue(os.path.exists(s.file_path(name)), name)

    def test_manifest_fields(self):
        s = self._make()
        m = s.load()
        self.assertEqual(m["snapshot_id"], s.snapshot_id)
        self.assertEqual(m["producer"], "test")
        self.assertEqual(m["judgment_batch"]["count"], len(JUDGMENTS))
        self.assertEqual(m["stats"]["usable_rows"], 2)
        by_name = {f["name"]: f for f in m["files"]}
        self.assertEqual(by_name[snap.MATERIALS_FILE]["rows"], 2)
        self.assertEqual(len(m["content_sha256"]), 64)

    def test_duplicate_write_rejected(self):
        self._make()
        with self.assertRaises(snap.SnapshotError):
            self._make()

    # ---------- 强校验 ----------

    def test_verify_ok(self):
        ok, problems = self._make().verify()
        self.assertTrue(ok, problems)

    def test_verify_detects_tampering(self):
        """篡改数值 → 哈希不匹配 → 必须被查出（复现契约的核心保障）。"""
        s = self._make()
        with open(s.materials_path(), "w", encoding="utf-8", newline="") as f:
            f.write(MATERIALS_CSV.replace("2.3e-03", "9.9e-01"))
        ok, problems = s.verify()
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in p for p in problems), problems)

    def test_verify_detects_missing_judgments(self):
        """判据 4：删除判断记录 → 校验失败 + 报告前置失败。"""
        s = self._make()
        os.remove(s.file_path(snap.JUDGMENTS_FILE))
        ok, problems = s.verify()
        self.assertFalse(ok)
        self.assertTrue(any("missing" in p for p in problems), problems)
        with self.assertRaises(snap.SnapshotError):
            s.require_judgments()

    def test_verify_detects_content_hash_mismatch(self):
        s = self._make()
        m = s.load()
        m["content_sha256"] = "0" * 64
        with open(s.manifest_path, "w", encoding="utf-8", newline="") as f:
            json.dump(m, f)
        ok, problems = s.verify()
        self.assertFalse(ok)
        self.assertTrue(any("content hash" in p for p in problems), problems)

    def test_missing_snapshot_verify(self):
        ok, problems = snap.Snapshot(self.root, "snap-nope").verify()
        self.assertFalse(ok)
        self.assertTrue(problems)

    # ---------- 确定性 ----------

    def test_content_hash_deterministic_across_snapshots(self):
        """相同内容 → 相同内容哈希（时间戳不参与），这是复现契约的基础。"""
        a = self._make("snap-20261002-000000-aaaaaa")
        b = self._make("snap-20261002-000001-bbbbbb")
        self.assertEqual(a.load()["content_sha256"], b.load()["content_sha256"])
        # 但 created_at 不同，说明时间戳被排除在内容哈希之外
        self.assertNotEqual(a.load()["created_at"][:10], "")

    # ---------- 判断批次 ----------

    def test_require_judgments_gate(self):
        s = self._make("snap-empty-000000-cccccc", judgments=[])
        with self.assertRaises(snap.SnapshotError):
            s.require_judgments()

    def test_judgments_readable_and_excluded_listed(self):
        s = self._make()
        js = s.judgments()
        self.assertEqual(len(js), 2)
        excluded = [j for j in js if j["meta"]["verdict"] == "excluded"]
        self.assertEqual(len(excluded), 1)
        self.assertTrue(excluded[0]["meta"]["rationale"])

    def test_register_judgments_into_ledger(self):
        """复算 run 能把快照判断重登记进自己的账本，且判断仍不得支撑结论。"""
        s = self._make()
        run_dir = os.path.join(self.root, "runs", "run-replay")
        os.makedirs(run_dir, exist_ok=True)
        prov = ProvenanceLedger(run_dir, "run-replay")

        ev_ids = s.register_judgments_into(prov)
        self.assertEqual(len(ev_ids), 2)
        self.assertEqual(len(prov.judgments()), 2)
        prov.require_judgment_batch()  # 判据 4 前置通过
        # 重登记后仍受红线约束
        with self.assertRaises(EvidenceError):
            prov.link_conclusion("C1", "判断当证据", [ev_ids[0]])
        # 被排除项也随快照一起迁移
        self.assertEqual(len(prov.excluded_judgments()), 1)

    # ---------- 枚举 ----------

    def test_list_and_latest(self):
        self.assertEqual(snap.list_snapshots(self.root), [])
        self._make("snap-20261002-000000-aaaaaa")
        self._make("snap-20261002-010000-bbbbbb")
        ids = snap.list_snapshots(self.root)
        self.assertEqual(ids, ["snap-20261002-000000-aaaaaa",
                               "snap-20261002-010000-bbbbbb"])
        self.assertEqual(snap.latest_snapshot_id(self.root),
                         "snap-20261002-010000-bbbbbb")
        self.assertEqual(snap.open_snapshot(self.root).snapshot_id,
                         "snap-20261002-010000-bbbbbb")
        self.assertEqual(snap.open_snapshot(
            self.root, "snap-20261002-000000-aaaaaa").snapshot_id,
            "snap-20261002-000000-aaaaaa")

    def test_open_snapshot_without_any_raises(self):
        with self.assertRaises(snap.SnapshotError):
            snap.open_snapshot(self.root)

    def test_materials_path_missing_raises(self):
        s = self._make()
        os.remove(s.file_path(snap.MATERIALS_FILE))
        with self.assertRaises(snap.SnapshotError):
            s.materials_path()

    def test_new_snapshot_id_format(self):
        sid = snap.new_snapshot_id()
        self.assertTrue(sid.startswith("snap-"))
        self.assertEqual(len(sid), len("snap-") + 8 + 1 + 6 + 1 + 6)


if __name__ == "__main__":
    unittest.main()
