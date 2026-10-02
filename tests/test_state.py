"""test_state.py — 状态机转移、持久化、非法转移异常。"""
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import build_temp_root  # noqa: E402

from paper_agent.state import (  # noqa: E402
    PipelineState, StepStatus, RunStatus, StateError,
    create_state, load_state, new_run_id, STEP_IDS,
)


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_state_")
        self.root = build_temp_root(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_plan_creates_run_and_events(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "goal-x")
        self.assertTrue(os.path.exists(os.path.join(self.root, "runs", rid, "state.json")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "runs", rid, "events.jsonl")))
        self.assertIs(st.run_status, RunStatus.PLANNED)
        for s in STEP_IDS:
            self.assertIs(st.step_status[s], StepStatus.PENDING)

    def test_legal_transitions(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        self.assertIs(st.run_status, RunStatus.RUNNING)
        st.mark_step_running("P1_lit_search")
        self.assertIs(st.step_status["P1_lit_search"], StepStatus.RUNNING)
        st.mark_step_done("P1_lit_search")
        self.assertIs(st.step_status["P1_lit_search"], StepStatus.DONE)
        st.finish_run(RunStatus.DONE)
        self.assertIs(st.run_status, RunStatus.DONE)

    def test_failed_step_can_retry(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        st.mark_step_running("P2_clean_data")
        st.mark_step_failed("P2_clean_data", "boom")
        self.assertIs(st.step_status["P2_clean_data"], StepStatus.FAILED)
        # FAILED -> RUNNING 合法（重试 / 断点续跑）
        st.mark_step_running("P2_clean_data", retry=True)
        self.assertIs(st.step_status["P2_clean_data"], StepStatus.RUNNING)
        st.mark_step_done("P2_clean_data")
        self.assertIs(st.step_status["P2_clean_data"], StepStatus.DONE)

    def test_done_is_terminal(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        st.mark_step_running("P3_run_experiment")
        st.mark_step_done("P3_run_experiment")
        with self.assertRaises(StateError):
            st.mark_step_running("P3_run_experiment")
        with self.assertRaises(StateError):
            st.mark_step_done("P3_run_experiment")
        with self.assertRaises(StateError):
            st.mark_step_failed("P3_run_experiment")

    def test_skipped_is_terminal(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        st.mark_step_skipped("P4_verify", "skipping")
        self.assertIs(st.step_status["P4_verify"], StepStatus.SKIPPED)
        with self.assertRaises(StateError):
            st.mark_step_running("P4_verify")

    def test_pending_to_done_illegal(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        with self.assertRaises(StateError):
            st.mark_step_done("P1_lit_search")  # PENDING -> DONE 非法
        with self.assertRaises(StateError):
            st.mark_step_failed("P1_lit_search")  # PENDING -> FAILED 非法

    def test_run_finished_from_planned_illegal(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        with self.assertRaises(StateError):
            st.finish_run(RunStatus.DONE)  # PLANNED -> DONE 非法

    def test_state_persisted_and_reloaded(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        st.mark_step_running("P1_lit_search")
        st.mark_step_done("P1_lit_search")
        st.mark_degraded("P1_lit_search", "forced")
        st.finish_run(RunStatus.DONE)

        st2 = load_state(rid, self.root)
        self.assertIs(st2.run_status, RunStatus.DONE)
        self.assertIs(st2.step_status["P1_lit_search"], StepStatus.DONE)
        self.assertTrue(st2.degraded)

    def test_events_append_only(self):
        import json as _j
        rid = new_run_id()
        st = create_state(rid, self.root, "g")
        st.start_run()
        st.mark_step_running("P5_report")
        st.mark_step_done("P5_report")
        ev_path = os.path.join(self.root, "runs", rid, "events.jsonl")
        with open(ev_path, "r", encoding="utf-8") as f:
            lines1 = [l for l in f.read().splitlines() if l.strip()]
        types = [_j.loads(l)["type"] for l in lines1]
        self.assertIn("run_planned", types)
        self.assertIn("run_started", types)
        self.assertIn("transition", types)
        # append-only：加载后再次追加事件，账本只增不减
        st2 = load_state(rid, self.root)
        st2.mark_step_running("P4_verify")
        st2.mark_step_done("P4_verify")
        with open(ev_path, "r", encoding="utf-8") as f:
            lines2 = [l for l in f.read().splitlines() if l.strip()]
        self.assertGreater(len(lines2), len(lines1))
        # 原始行未被修改（append-only 校验）
        self.assertEqual(lines1, lines2[:len(lines1)])


if __name__ == "__main__":
    unittest.main()
