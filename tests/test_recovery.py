"""test_recovery.py — 重试、降级、断点续跑 resume 逻辑。

覆盖文档四大故障用例：
  A p1_fail_first → 重试 1 次成功, DONE, degraded=False
  B p1_fail_all   → 耗尽触发降级, DONE, degraded=True, events 含 degrade
  C P2 后中断 resume → 已 DONE 步骤复用, 仅跑剩余
  D mutate_summary  → P4 FAIL, run FAILED, 5 项校验可查
"""
import json
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root  # noqa: E402

from paper_agent.state import create_state, load_state, new_run_id, RunStatus  # noqa: E402
from paper_agent.steps import Pipeline  # noqa: E402
from paper_agent.chaos import clear_chaos_mode  # noqa: E402


def _run_events(root: str, run_id: str) -> list:
    p = os.path.join(root, "runs", run_id, "events.jsonl")
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f.read().splitlines() if l.strip()]


class TestRecovery(unittest.TestCase):
    def setUp(self):
        clear_chaos_mode()
        self._tmp = tempfile.mkdtemp(prefix="pa_rec_")
        self.root = build_temp_root(self._tmp)

    def tearDown(self):
        clear_chaos_mode()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plan(self, chaos=""):
        rid = new_run_id()
        st = create_state(rid, self.root, "recovery goal")
        pipe = Pipeline(self.root, rid, chaos_mode=chaos)
        return rid, pipe

    def test_case_A_p1_fail_first(self):
        # 退避序列 [1,2] 会使真实 sleep ~1s；此处 patch 掉 sleep 以加速测试
        import paper_agent.steps as S
        orig_sleep = S.time.sleep
        S.time.sleep = lambda *_: None
        try:
            rid, pipe = self._plan("p1_fail_first")
            out = pipe.run_all()
        finally:
            S.time.sleep = orig_sleep
        self.assertEqual(out["run_status"], "DONE")
        self.assertFalse(out["degraded"])
        ev = _run_events(self.root, rid)
        retries = [e for e in ev if e["type"] == "retry" and e.get("step") == "P1_lit_search"]
        self.assertEqual(len(retries), 1, "用例A 应恰好 1 次重试")
        self.assertFalse(any(e["type"] == "degrade" for e in ev), "用例A 不应降级")

    def test_case_B_p1_fail_all(self):
        import paper_agent.steps as S
        orig_sleep = S.time.sleep
        S.time.sleep = lambda *_: None
        try:
            rid, pipe = self._plan("p1_fail_all")
            out = pipe.run_all()
        finally:
            S.time.sleep = orig_sleep
        self.assertEqual(out["run_status"], "DONE")
        self.assertTrue(out["degraded"])
        ev = _run_events(self.root, rid)
        self.assertTrue(any(e["type"] == "degrade" for e in ev), "用例B 必须有 degrade 事件")
        # 降级后 P1 命中全部语料（5 篇）
        with open(os.path.join(self.root, "runs", rid,
                                "literature", "literature_hits.json"),
                  "r", encoding="utf-8") as fh:
            hits = json.load(fh)
        self.assertEqual(hits["n_hits"], 5)
        self.assertTrue(hits["degraded"])

    def test_case_C_resume_reuses_done(self):
        rid, _ = self._plan("")
        pipe = Pipeline(self.root, rid)
        # 先跑 P1、P2
        pipe._ensure_running()
        pipe.run_p1()
        pipe.run_p2()
        # 模拟 P2 后进程被杀：P3-P5 仍 PENDING，P1/P2 DONE
        self.assertEqual(pipe.state.step_status["P1_lit_search"].value, "DONE")
        self.assertEqual(pipe.state.step_status["P2_clean_data"].value, "DONE")
        self.assertEqual(pipe.state.step_status["P3_run_experiment"].value, "PENDING")

        # 重新加载（模拟重启），再 resume 剩余
        p2 = Pipeline(self.root, rid)
        out = p2.resume()
        self.assertEqual(out["run_status"], "DONE")
        st = load_state(rid, self.root)
        self.assertEqual(st.attempts["P1_lit_search"], 1, "已 DONE 步骤不应再执行")
        self.assertEqual(st.attempts["P2_clean_data"], 1)
        # P3/P4/P5 各执行一次
        self.assertEqual(st.attempts["P3_run_experiment"], 1)
        self.assertEqual(st.attempts["P4_verify"], 1)
        self.assertEqual(st.attempts["P5_report"], 1)
        self.assertFalse(st.degraded)

    def test_case_D_mutate_summary(self):
        rid, pipe = self._plan("mutate_summary")
        out = pipe.run_all()
        self.assertEqual(out["run_status"], "FAILED")
        self.assertEqual(pipe.state.step_status["P4_verify"].value, "FAILED")
        with open(os.path.join(self.root, "runs", rid,
                                "verification", "verification.json"),
                  "r", encoding="utf-8") as fh:
            v = json.load(fh)
        self.assertEqual(v["status"], "FAIL")
        self.assertEqual(len(v["checks"]), 5, "5 项校验必须全部可查")
        # 仅 top3 位置项失败（results.csv 哈希仍一致，因 MUTATE 不改 csv）
        names = {c["name"]: c["pass"] for c in v["checks"]}
        self.assertTrue(names["results_csv_sha256"])
        self.assertFalse(names["top3_scores_positional"])
        self.assertTrue(names["n_rows"])

    def test_state_failed_terminal_after_d(self):
        # run FAILED 后不能再 finish_run(DONE)
        from paper_agent.state import StateError
        rid, pipe = self._plan("mutate_summary")
        pipe.run_all()
        st = load_state(rid, self.root)
        self.assertIs(st.run_status, RunStatus.FAILED)
        with self.assertRaises(StateError):
            st.finish_run(RunStatus.DONE)


if __name__ == "__main__":
    unittest.main()
