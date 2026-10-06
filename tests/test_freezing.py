"""test_freezing.py — 冻结流程：prepare / commit / 异常闸门 / 裁决归一。

全程离线（bootstrap 文献腿），不访问网络。
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
from _util import isolate_temp_root  # noqa: E402

from paper_agent import freezing as F  # noqa: E402
from paper_agent import snapshot as S  # noqa: E402
from paper_agent import judge as J  # noqa: E402

GOAL = "sulfide solid electrolyte ionic conductivity ranking"
# 模型裁决：比规则式多认下 NASICON 与 garnet（规则式只认硫系别名），
# 因此 in_scope 行数必然不同 —— 这正是判据 2 要证明的事
REL_FAMS = {"lgps", "argyrodite", "argyrodites", "sulfides", "thio-lisicon",
            "thio-phosphate", "nasicon", "garnet"}


def _rel(fam: str) -> bool:
    return fam.lower() in REL_FAMS


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_frz_")

    def test_prepare_writes_pending(self):
        prep = F.prepare(self.root, GOAL)
        self.assertTrue(os.path.exists(prep["pending_path"]))
        self.assertTrue(prep["pending_id"].startswith("pend-"))
        with open(prep["pending_path"], "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["goal"], GOAL)
        self.assertEqual(payload["literature_mode"], "bootstrap")
        self.assertEqual(payload["families"], prep["families"])

    def test_prepare_reports_families_and_rule_baseline(self):
        prep = F.prepare(self.root, GOAL)
        self.assertGreater(prep["n_families"], 20)
        self.assertNotIn("", prep["families"])          # 空族名不进待判集合
        self.assertTrue(prep["rule_queries"])
        relevant = {k for k, v in prep["rule_scope"].items() if v == "relevant"}
        self.assertTrue(relevant)
        self.assertTrue(relevant <= set(prep["families"]))
        self.assertTrue(all(j["tier"] == "judgment" for j in prep["rule_judgments"]))

    def test_prepare_does_not_write_snapshot(self):
        F.prepare(self.root, GOAL)
        self.assertEqual(S.list_snapshots(self.root), [])


class TestNormalizeVerdicts(unittest.TestCase):
    FAM = ["LGPS", "NASICON", ""]

    def test_dict_form(self):
        q, items = F.normalize_verdicts(
            {"queries": ["a"], "families": {"LGPS": "relevant", "NASICON": "excluded",
                                            "": "excluded"}}, self.FAM)
        self.assertEqual(q, ["a"])
        self.assertEqual(len(items), 3)
        self.assertEqual({i["family"] for i in items}, {"LGPS", "NASICON", ""})

    def test_list_form_with_reason(self):
        q, items = F.normalize_verdicts({"families": [
            {"family": "LGPS", "verdict": "relevant", "reason": "含 lgps"},
            {"family": "NASICON", "verdict": "excluded", "reason": "氧化物"},
            {"family": "", "verdict": "excluded", "reason": "空"}], }, self.FAM)
        self.assertIsNone(q)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["reason"], "含 lgps")

    def test_placeholder_normalized(self):
        _, items = F.normalize_verdicts(
            {"families": {"LGPS": "relevant", "NASICON": "excluded",
                          "(empty)": "excluded"}}, self.FAM)
        self.assertIn("", {i["family"] for i in items})

    def test_nested_object_form(self):
        """模型常产出嵌套写法 {族: {verdict, reason}}；输入形状宽容、取值严格。"""
        _, items = F.normalize_verdicts({"families": {
            "LGPS": {"verdict": "relevant", "reason": "含 lgps 别名"},
            "NASICON": {"verdict": "excluded", "reason": "氧化物体系"},
            "": {"verdict": "excluded"}}}, self.FAM)
        by = {i["family"]: i for i in items}
        self.assertEqual(by["LGPS"]["verdict"], "relevant")
        self.assertEqual(by["LGPS"]["reason"], "含 lgps 别名")
        self.assertEqual(by["NASICON"]["verdict"], "excluded")
        self.assertEqual(by[""]["verdict"], "excluded")

    def test_nested_object_missing_verdict_raises(self):
        with self.assertRaises(F.FreezeError):
            F.normalize_verdicts({"families": {
                "LGPS": {"reason": "忘了写 verdict"},
                "NASICON": "excluded", "": "excluded"}}, self.FAM)

    def test_missing_family_raises(self):
        with self.assertRaises(F.FreezeError) as cm:
            F.normalize_verdicts({"families": {"LGPS": "relevant"}}, self.FAM)
        self.assertIn("missing", str(cm.exception))

    def test_invalid_verdict_raises(self):
        with self.assertRaises(F.FreezeError):
            F.normalize_verdicts({"families": {"LGPS": "maybe", "NASICON": "excluded",
                                               "": "excluded"}}, self.FAM)

    def test_bad_shapes_raise(self):
        for spec in ([], "x", {"families": 3}, {"families": [{"family": "a"}]}):
            with self.assertRaises(F.FreezeError):
                F.normalize_verdicts(spec, self.FAM)

    def test_queries_must_be_list(self):
        with self.assertRaises(F.FreezeError):
            F.normalize_verdicts({"queries": "a",
                                  "families": {"LGPS": "relevant",
                                               "NASICON": "excluded", "": "excluded"}},
                                 self.FAM)


class TestCommit(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_frz_")

    def _spec(self, prep, verdicts=None):
        return {"queries": ["sulfide solid electrolyte conductivity"],
                "families": {f: ("relevant" if _rel(f) else "excluded")
                             for f in prep["families"]}}

    def test_commit_writes_snapshot_with_model_judgments(self):
        prep = F.prepare(self.root, GOAL)
        out = F.commit(self.root, prep["pending_id"], self._spec(prep),
                       judged_by="model", model_name="unit-model")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["stats"]["judged_by"], "model")
        self.assertEqual(out["stats"]["judge_impl"], J.MODEL_IMPL)
        self.assertEqual(out["stats"]["model"], "unit-model")
        self.assertTrue(S.Snapshot(self.root, out["snapshot_id"]).exists())
        self.assertEqual(S.Snapshot(self.root, out["snapshot_id"]).verify()[0], True)

    def test_model_judgment_changes_scope(self):
        """判据 2 的单元级体现：模型裁决确实改变了进入分析的材料范围。"""
        rule = F.freeze_rule_based(self.root, GOAL)
        prep = F.prepare(self.root, GOAL)
        model = F.commit(self.root, prep["pending_id"], self._spec(prep),
                         judged_by="model", model_name="unit-model")
        self.assertNotEqual(rule["stats"]["in_scope_rows"],
                            model["stats"]["in_scope_rows"])
        self.assertGreater(model["stats"]["in_scope_rows"],
                           rule["stats"]["in_scope_rows"])

    def test_rule_based_freeze(self):
        out = F.freeze_rule_based(self.root, GOAL)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["stats"]["judged_by"], "rule")
        self.assertEqual(out["stats"]["judge_impl"], J.RULE_IMPL)
        self.assertIn("pending_id", out)

    def test_rule_based_is_deterministic(self):
        """同一输入两次规则式冻结 → 内容哈希必须一致（时间戳不参与）。"""
        a = F.freeze_rule_based(self.root, GOAL)
        b = F.freeze_rule_based(self.root, GOAL)
        self.assertNotEqual(a["snapshot_id"], b["snapshot_id"])
        self.assertEqual(a["content_sha256"], b["content_sha256"])

    def test_commit_rejects_incomplete_verdicts(self):
        prep = F.prepare(self.root, GOAL)
        bad = {"families": {prep["families"][0]: "relevant"}}
        with self.assertRaises(F.FreezeError):
            F.commit(self.root, prep["pending_id"], bad, judged_by="model")

    def test_unknown_pending_raises(self):
        with self.assertRaises(F.FreezeError):
            F.commit(self.root, "pend-nope", {"families": {}}, judged_by="model")


class TestAnomalyGate(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_frz_")

    def _zero_hit_pending(self):
        """构造一个"文献腿零命中"的 pending，用于验证闸门。

        返回 (pending_id, 完整裁决)；裁决用正常命中率（8/42），
        以确保**只有 zero_hits 一项异常**，隔离被测行为。
        """
        prep = F.prepare(self.root, GOAL)
        path = prep["pending_path"]
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["literature"] = {"goal": GOAL, "source": "network", "n_hits": 0,
                                 "hits": [], "errors": []}
        payload["search_summary"] = {"n_raw": 0, "n_unique": 0, "errors": []}
        with open(path, "w", encoding="utf-8", newline="") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        spec = {"queries": ["sulfide solid electrolyte"],
                "families": {f: ("relevant" if _rel(f) else "excluded")
                             for f in prep["families"]}}
        return prep["pending_id"], spec

    def test_zero_hits_stops_without_writing_snapshot(self):
        pid, spec = self._zero_hit_pending()
        out = F.commit(self.root, pid, spec, judged_by="model")
        self.assertTrue(out["stopped"])
        self.assertEqual(out["anomalies"], ["zero_hits"])
        self.assertIn("--ack zero_hits", " ".join(out["ack_hint"]))
        self.assertIn("流程已停下", out["report"])
        # 关键：没有写出任何快照
        self.assertEqual(S.list_snapshots(self.root), [])

    def test_ack_allows_proceeding(self):
        pid, spec = self._zero_hit_pending()
        out = F.commit(self.root, pid, spec, judged_by="model", ack=["zero_hits"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["stats"]["anomalies_acknowledged"], ["zero_hits"])
        self.assertIn("zero_hits", out["stats"]["anomalies_detected"])
        self.assertEqual(len(S.list_snapshots(self.root)), 1)

    def test_ack_of_all_excluded_still_flagged_as_low_hit_rate(self):
        """全部判为不相关 → 命中率 0% 也是异常，确认一个码不足以放行。"""
        pid, _ = self._zero_hit_pending()
        with open(os.path.join(F.pending_dir(self.root), pid + ".json"),
                  "r", encoding="utf-8") as f:
            fams = json.load(f)["families"]
        spec = {"families": {f: "excluded" for f in fams}}
        out = F.commit(self.root, pid, spec, judged_by="model", ack=["zero_hits"])
        self.assertTrue(out["stopped"])
        self.assertEqual(out["anomalies"], ["judge_hit_rate"])

    def test_unknown_ack_code_rejected(self):
        pid, spec = self._zero_hit_pending()
        with self.assertRaises(ValueError):
            F.commit(self.root, pid, spec, judged_by="model", ack=["not_a_code"])


class TestDefaultInputCsv(unittest.TestCase):
    def test_falls_back_to_repo_dataset(self):
        """--root 指向无数据的临时目录时，仍能找到仓库内的数据集。"""
        tmp = tempfile.mkdtemp(prefix="pa_frz_nodata_")
        try:
            p = F.default_input_csv(tmp)
            self.assertTrue(os.path.exists(p), p)
            self.assertIn("obelix", p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
