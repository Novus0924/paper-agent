"""test_repro.py — 实验确定性复现（SHA-256）+ verify 递归容差比对。

- 两次独立子进程运行 arrhenius_rank.py，results.csv 逐字节一致
- paper-agent_MUTATE=1 交换 summary top3 但不改 results.csv
- verify.deep_equal 支持 dict/list/标量嵌套、容差、缺失键、位置敏感
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root, make_clean_csv  # noqa: E402

from paper_agent import verify as V  # noqa: E402


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _spawn(root: str, clean_csv: str, outdir: str, mutate: bool = False) -> int:
    env = dict(os.environ)
    if mutate:
        env["paper-agent_MUTATE"] = "1"
    else:
        env.pop("paper-agent_MUTATE", None)
    script = os.path.join(root, "experiments", "arrhenius_rank.py")
    p = subprocess.run(
        [sys.executable, script, "--input", clean_csv,
         "--outdir", outdir, "--seed", "0"],
        capture_output=True, text=True, env=env,
    )
    return p.returncode


class TestRepro(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_repro_")
        self.root = build_temp_root(self._tmp)
        self.clean_csv = make_clean_csv(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_deterministic_two_runs(self):
        out1 = os.path.join(self._tmp, "o1")
        out2 = os.path.join(self._tmp, "o2")
        self.assertEqual(_spawn(self.root, self.clean_csv, out1), 0)
        self.assertEqual(_spawn(self.root, self.clean_csv, out2), 0)
        h1 = _sha(os.path.join(out1, "results", "results.csv"))
        h2 = _sha(os.path.join(out2, "results", "results.csv"))
        self.assertEqual(h1, h2, "两次运行 results.csv 必须逐字节一致")
        self.assertEqual(len(h1), 64)

    def test_mutate_keeps_csv_deterministic(self):
        out_n = os.path.join(self._tmp, "on")
        out_m = os.path.join(self._tmp, "om")
        self.assertEqual(_spawn(self.root, self.clean_csv, out_n), 0)
        self.assertEqual(_spawn(self.root, self.clean_csv, out_m, mutate=True), 0)
        # results.csv 不变（MUTATE 只交换 summary.top3）
        self.assertEqual(
            _sha(os.path.join(out_n, "results", "results.csv")),
            _sha(os.path.join(out_m, "results", "results.csv")),
        )
        # summary.top3 被交换（前两项），material_id 集合不变
        with open(os.path.join(out_n, "results", "summary.json"), "r",
                  encoding="utf-8") as fh:
            s_n = json.load(fh)
        with open(os.path.join(out_m, "results", "summary.json"), "r",
                  encoding="utf-8") as fh:
            s_m = json.load(fh)
        ids_n = [t["material_id"] for t in s_n["top3"]]
        ids_m = [t["material_id"] for t in s_m["top3"]]
        self.assertNotEqual(ids_n, ids_m)
        self.assertEqual(sorted(ids_n), sorted(ids_m), "MUTATE 只交换顺序不改成员")
        # 首位被交换
        self.assertEqual(ids_n[0], ids_m[1])
        self.assertEqual(ids_m[0], ids_n[1])

    def test_required_artifacts_exist(self):
        out = os.path.join(self._tmp, "o")
        self.assertEqual(_spawn(self.root, self.clean_csv, out), 0)
        for rel in ("results/results.csv", "results/summary.json",
                    "figures/fig1_conductivity.svg"):
            self.assertTrue(os.path.exists(os.path.join(out, *rel.split("/"))),
                            f"missing {rel}")

    # ---------- deep_equal 递归容差比对 ----------

    def test_deep_equal_scalar_equal(self):
        self.assertTrue(V.deep_equal(3, 3)[0])
        self.assertTrue(V.deep_equal(3.0, 3)[0])
        self.assertTrue(V.deep_equal("a", "a")[0])

    def test_deep_equal_float_tolerance(self):
        self.assertTrue(V.deep_equal(1.0, 1.0 + 5e-10)[0])
        self.assertFalse(V.deep_equal(1.0, 1.0 + 1e-3, 1e-9)[0])

    def test_deep_equal_bool_not_numeric(self):
        # bool 是 int 子类，但不应走浮点容差
        self.assertTrue(V.deep_equal(True, True)[0])
        self.assertFalse(V.deep_equal(True, 1.5)[0])

    def test_deep_equal_nested_dict_missing_key(self):
        exp = {"a": 1, "b": 2}
        act = {"a": 1}
        ok, mm = V.deep_equal(exp, act)
        self.assertFalse(ok)
        self.assertTrue(any("b" in m for m in mm))

    def test_deep_equal_nested_dict_value_mismatch(self):
        exp = {"fam": {"sulfide": 1.0}}
        act = {"fam": {"sulfide": 1.0 + 1e-3}}
        ok, mm = V.deep_equal(exp, act, 1e-9)
        self.assertFalse(ok)

    def test_deep_equal_list_position_sensitive(self):
        # 模拟 top3 交换：位置不同必须判不等（复现 FAIL 场景）
        exp = [{"material_id": "M002", "score": 0.8},
               {"material_id": "M001", "score": 0.7}]
        act = [{"material_id": "M001", "score": 0.7},
               {"material_id": "M002", "score": 0.8}]
        ok, mm = V.deep_equal(exp, act)
        self.assertFalse(ok, "top3 交换后位置比对必须 FAIL")

    def test_deep_equal_list_length_mismatch(self):
        ok, mm = V.deep_equal([1, 2, 3], [1, 2])
        self.assertFalse(ok)

    def test_build_checks_pass_on_identical(self):
        summary = {"n_rows": 6,
                   "top3": [{"material_id": "M002", "score": 0.8},
                             {"material_id": "M001", "score": 0.7},
                             {"material_id": "M007", "score": 0.6}],
                   "family_mean_log10_cond": {"sulfide": -1.7, "garnet": -3.6}}
        status, checks = V.build_checks("shaX", "shaX", summary, dict(summary))
        self.assertEqual(status, "PASS")
        self.assertTrue(all(c["pass"] for c in checks))
        self.assertEqual(len(checks), 5)

    def test_build_checks_fail_on_sha_and_top3(self):
        exp = {"n_rows": 6,
               "top3": [{"material_id": "M002", "score": 0.8},
                         {"material_id": "M001", "score": 0.7}],
               "family_mean_log10_cond": {"sulfide": -1.7}}
        act = {"n_rows": 6,
               "top3": [{"material_id": "M001", "score": 0.7},
                         {"material_id": "M002", "score": 0.8}],
               "family_mean_log10_cond": {"sulfide": -1.7}}
        status, checks = V.build_checks("shaA", "shaB", exp, act)
        self.assertEqual(status, "FAIL")
        names = {c["name"]: c["pass"] for c in checks}
        self.assertFalse(names["results_csv_sha256"])
        self.assertFalse(names["top3_scores_positional"])
        self.assertTrue(names["n_rows"])


if __name__ == "__main__":
    unittest.main()
