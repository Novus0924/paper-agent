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
from _util import isolate_temp_root  # noqa: E402

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
        self.root = isolate_temp_root(self, "pa_rec_")

    def tearDown(self):
        clear_chaos_mode()
        # 临时目录与全局量的清理由 isolate_temp_root 的 addCleanup 负责

    def _plan(self, chaos=""):
        rid = new_run_id()
        st = create_state(rid, self.root, "recovery goal", workflow="materials")
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

    def test_case_E2_kill_after_p2_subprocess(self):
        """kill_after_p2 真实进程崩溃：子进程 exit 137，账本保持完整，resume 续跑到 DONE。"""
        import subprocess
        import sys
        core = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core")
        env = dict(os.environ,
                   PYTHONPATH=os.path.abspath(core),
                   **{"paper-agent_ROOT": self.root})
        pr = subprocess.run(
            [sys.executable, "-m", "paper_agent.cli", "plan",
             "--goal", "kill demo", "--chaos", "kill_after_p2",
             "--workflow", "materials"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(pr.returncode, 0, pr.stderr)
        rid = json.loads(pr.stdout.strip())["run_id"]
        pk = subprocess.run(
            [sys.executable, "-m", "paper_agent.cli", "run-all",
             "--run", rid, "--chaos", "kill_after_p2"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(pk.returncode, 137, "P2 后必须被 os._exit(137) 杀死")
        # 崩溃后：P1/P2 已 DONE，P3-P5 仍 PENDING；双账本逐行可解析（append-only 完整）
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["P1_lit_search"].value, "DONE")
        self.assertEqual(st.step_status["P2_clean_data"].value, "DONE")
        self.assertEqual(st.step_status["P3_run_experiment"].value, "PENDING")
        ev = _run_events(self.root, rid)
        self.assertTrue(all(isinstance(e, dict) and e.get("run_id") == rid for e in ev))
        prov_path = os.path.join(self.root, "runs", rid, "provenance.jsonl")
        with open(prov_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    json.loads(line)
        # 断点续跑收敛
        pipe = Pipeline(self.root, rid)
        out = pipe.resume()
        self.assertEqual(out["run_status"], "DONE")

    def test_case_E3_kill_after_p2_via_run_step(self):
        """AGH 插件形态（只有 run_step 工具）：run-step P2 --chaos kill_after_p2
        同样真实杀死子进程（exit 137），resume 断点续跑到 DONE。"""
        import subprocess
        import sys
        core = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core")
        env = dict(os.environ,
                   PYTHONPATH=os.path.abspath(core),
                   **{"paper-agent_ROOT": self.root})
        pr = subprocess.run(
            [sys.executable, "-m", "paper_agent.cli", "plan", "--goal", "runstep kill",
             "--workflow", "materials"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(pr.returncode, 0, pr.stderr)
        rid = json.loads(pr.stdout.strip())["run_id"]
        p1 = subprocess.run(
            [sys.executable, "-m", "paper_agent.cli", "run-step",
             "--run", rid, "--step", "P1_lit_search"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(p1.returncode, 0, p1.stderr)
        p2 = subprocess.run(
            [sys.executable, "-m", "paper_agent.cli", "run-step",
             "--run", rid, "--step", "P2_clean_data", "--chaos", "kill_after_p2"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(p2.returncode, 137, "run-step P2 路径也必须被杀死")
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["P2_clean_data"].value, "DONE")
        self.assertEqual(st.step_status["P3_run_experiment"].value, "PENDING")
        rs = subprocess.run(
            [sys.executable, "-m", "paper_agent.cli", "resume", "--run", rid],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(rs.returncode, 0, rs.stderr)
        self.assertEqual(json.loads(rs.stdout.strip())["run_status"], "DONE")

    def test_case_F_report_idempotent_after_done(self):
        """DONE 后重复 sciret_report（cmd_report→run_p5）必须幂等复用而非 StateError。"""
        rid, pipe = self._plan("")
        out = pipe.run_all()
        self.assertEqual(out["run_status"], "DONE")
        res = pipe.run_p5()  # 第二次报告调用：复用既有 report.md
        self.assertIn("report", res)
        self.assertTrue(res.get("idempotent_reuse"))
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["P5_report"].value, "DONE")
        self.assertEqual(st.attempts["P5_report"], 1)

    def test_case_F2_report_idempotent_refuses_tampered_ledger(self):
        """P5 DONE 幂等复用前必须过信任门禁：账本被篡改时报告复用被拒绝。

        回归用例（demo_trust 攻击 A）：若 DONE 缓存无门禁，篡改 provenance.jsonl
        后 report 命令仍会返回旧报告——DONE 缓存成了绕过信任闸门的旁路。
        """
        from paper_agent.provenance import EvidenceError
        rid, pipe = self._plan("")
        pipe.run_all()
        prov_path = os.path.join(self.root, "runs", rid, "provenance.jsonl")
        with open(prov_path, "r", encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        rec = json.loads(lines[0])
        rec["ref"] = "tampered-by-test"
        lines[0] = json.dumps(rec, ensure_ascii=False)
        with open(prov_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with self.assertRaises(EvidenceError) as cm:
            pipe.run_p5()
        self.assertIn("provenance ledger tampered", str(cm.exception))

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
