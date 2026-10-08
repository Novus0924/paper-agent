"""test_state.py — 状态机转移、持久化、非法转移异常。"""
import json
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent.state import (  # noqa: E402
    PipelineState, StepStatus, RunStatus, StateError,
    create_state, load_state, new_run_id, STEP_IDS,
    MATERIALS_STEPS, RESEARCH_STEPS,
)


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_state_")

    def test_plan_creates_run_and_events(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "goal-x", workflow="materials")
        self.assertTrue(os.path.exists(os.path.join(self.root, "runs", rid, "state.json")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "runs", rid, "events.jsonl")))
        self.assertIs(st.run_status, RunStatus.PLANNED)
        for s in STEP_IDS:
            self.assertIs(st.step_status[s], StepStatus.PENDING)

    def test_legal_transitions(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g", workflow="materials")
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
        st = create_state(rid, self.root, "g", workflow="materials")
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
        st = create_state(rid, self.root, "g", workflow="materials")
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
        st = create_state(rid, self.root, "g", workflow="materials")
        st.start_run()
        st.mark_step_skipped("P4_verify", "skipping")
        self.assertIs(st.step_status["P4_verify"], StepStatus.SKIPPED)
        with self.assertRaises(StateError):
            st.mark_step_running("P4_verify")

    def test_pending_to_done_illegal(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g", workflow="materials")
        st.start_run()
        with self.assertRaises(StateError):
            st.mark_step_done("P1_lit_search")  # PENDING -> DONE 非法
        with self.assertRaises(StateError):
            st.mark_step_failed("P1_lit_search")  # PENDING -> FAILED 非法

    def test_run_finished_from_planned_illegal(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g", workflow="materials")
        with self.assertRaises(StateError):
            st.finish_run(RunStatus.DONE)  # PLANNED -> DONE 非法

    def test_state_persisted_and_reloaded(self):
        rid = new_run_id()
        st = create_state(rid, self.root, "g", workflow="materials")
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
        st = create_state(rid, self.root, "g", workflow="materials")
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


class TestMaybeConvergeDone(unittest.TestCase):
    """统一收敛方法 maybe_converge_done（LOGIC-2）的状态机级单测。"""

    def setUp(self):
        self.root = isolate_temp_root(self, "pa_conv_")

    def _state_with_all_steps_done(self) -> PipelineState:
        st = create_state(new_run_id(), self.root, "g", workflow="materials")
        st.start_run()
        for sid in st.step_ids:
            st.mark_step_running(sid)
            st.mark_step_done(sid)
        return st

    def test_running_run_converges_done(self):
        st = self._state_with_all_steps_done()
        self.assertTrue(st.maybe_converge_done())
        self.assertIs(st.run_status, RunStatus.DONE)

    def test_failed_run_reconverges_with_event(self):
        st = self._state_with_all_steps_done()
        st.finish_run(RunStatus.FAILED)  # 模拟历史：曾以 FAILED 收尾
        self.assertTrue(st.maybe_converge_done())
        self.assertIs(st.run_status, RunStatus.DONE)
        ev_path = os.path.join(self.root, "runs", st.run_id, "events.jsonl")
        with open(ev_path, "r", encoding="utf-8") as f:
            recs = [json.loads(l) for l in f.read().splitlines() if l.strip()]
        rc = [e for e in recs if e["type"] == "run_reconverged"]
        self.assertEqual(len(rc), 1)
        self.assertEqual(rc[0]["from"], "FAILED")
        self.assertEqual(rc[0]["to"], "DONE")

    def test_failed_run_with_failed_step_does_not_converge(self):
        st = create_state(new_run_id(), self.root, "g", workflow="materials")
        st.start_run()
        st.mark_step_running("P1_lit_search")
        st.mark_step_failed("P1_lit_search", "boom")
        for sid in st.step_ids[1:]:
            st.mark_step_running(sid)
            st.mark_step_done(sid)
        st.finish_run(RunStatus.FAILED)
        self.assertFalse(st.maybe_converge_done())
        self.assertIs(st.run_status, RunStatus.FAILED)

    def test_running_with_pending_does_not_converge(self):
        st = create_state(new_run_id(), self.root, "g", workflow="materials")
        st.start_run()
        st.mark_step_running("P1_lit_search")
        st.mark_step_done("P1_lit_search")
        self.assertFalse(st.maybe_converge_done())
        self.assertIs(st.run_status, RunStatus.RUNNING)

    def test_public_transition_matrix_not_relaxed(self):
        """受控收敛不开旁门：finish_run 仍硬编码 src=RUNNING，DONE 不可再收敛。"""
        st = self._state_with_all_steps_done()
        st.finish_run(RunStatus.FAILED)
        with self.assertRaises(StateError):
            st.finish_run(RunStatus.DONE)
        self.assertTrue(st.maybe_converge_done())
        # 已 DONE：再次调用不动、返回 False（幂等）
        self.assertFalse(st.maybe_converge_done())
        self.assertIs(st.run_status, RunStatus.DONE)


class TestDefaultWorkflow(unittest.TestCase):
    """P1-1 冒烟：默认工作流锁定为 research；materials 仍为显式合法工作流。"""

    def setUp(self):
        self.root = isolate_temp_root(self, "pa_dflt_")

    def test_default_is_research(self):
        """不传 workflow（构造 / create_state）默认得到 research 步骤集 R1..R6。"""
        st = PipelineState(new_run_id(), self.root, "g")
        self.assertEqual(st.workflow, "research")
        self.assertEqual(st.step_ids, RESEARCH_STEPS)
        st2 = create_state(new_run_id(), self.root, "g")
        self.assertEqual(st2.step_ids, RESEARCH_STEPS)
        self.assertTrue(all(sid.startswith("R") for sid in st2.step_ids))

    def test_materials_remains_explicit(self):
        """向后兼容承诺：显式 workflow="materials" 仍得到 P1..P5。"""
        st = create_state(new_run_id(), self.root, "g", workflow="materials")
        self.assertEqual(st.workflow, "materials")
        self.assertEqual(st.step_ids, MATERIALS_STEPS)

    def test_legacy_snapshot_without_workflow_field(self):
        """历史快照缺 workflow 字段 → 按 steps_order 推断，不误标为 research。

        v0.3 之前的 state.json 无 workflow 字段（steps_order=P1..P5）；
        默认切到 research 后若按默认兜底，会把历史 materials run 误分发到
        ResearchPipeline。锁定：按 steps_order 首步前缀推断回 materials。
        """
        rid = new_run_id()
        st = create_state(rid, self.root, "g", workflow="materials")
        st.start_run()
        with open(st.state_path, "r", encoding="utf-8") as f:
            snap = json.load(f)
        snap.pop("workflow", None)
        with open(st.state_path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2, sort_keys=True)
        st2 = load_state(rid, self.root)
        self.assertEqual(st2.workflow, "materials")
        self.assertEqual(st2.step_ids, MATERIALS_STEPS)


if __name__ == "__main__":
    unittest.main()
