"""test_lifecycle.py — run 生命周期统一（Batch 1 / LOGIC-2 · LOGIC-5 · SEC-2）。

覆盖四组回归：
  L1 FAILED research run 调 run_all/resume → 终态幂等早退
     （P0：不再崩溃、不再重复执行 FAILED 步骤污染账本）
  L2 FAILED run（materials）单步重试全部失败步骤到 DONE → run 受控收敛 DONE
     且 events 留 run_reconverged 事件（受控边生效）
  L3 P5 报告缺失自愈：步骤 DONE 但 report.md 缺失 → 复用路径触发重建
     （文件重新生成 + 真实 sha256 入账本）；重建失败抛 EvidenceError
  L4 CLI run_id 校验纵深（SEC-2）：非法 run_id（路径穿越）被拒（exit 非 0）
"""
import json
import os
import subprocess
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEST_DIR, "..", "core"))
sys.path.insert(0, _TEST_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent.chaos import clear_chaos_mode  # noqa: E402
from paper_agent.provenance import EvidenceError, ProvenanceLedger  # noqa: E402
from paper_agent.research import ResearchPipeline  # noqa: E402
from paper_agent.state import (  # noqa: E402
    RunStatus, create_state, load_state, new_run_id,
)
from paper_agent.steps import Pipeline  # noqa: E402
from paper_agent.util import sha256_file  # noqa: E402


def _ledger_lines(root: str, run_id: str) -> list[str]:
    p = os.path.join(root, "runs", run_id, "provenance.jsonl")
    with open(p, "r", encoding="utf-8") as f:
        return [l for l in f.read().splitlines() if l.strip()]


def _events(root: str, run_id: str) -> list[dict]:
    p = os.path.join(root, "runs", run_id, "events.jsonl")
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f.read().splitlines() if l.strip()]


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        clear_chaos_mode()
        self.root = isolate_temp_root(self, "pa_life_")

    def tearDown(self):
        clear_chaos_mode()

    # ---------- L1：FAILED research run 的 run_all/resume 幂等早退 ----------

    def test_l1_failed_research_run_all_is_idempotent(self):
        rid = new_run_id()
        create_state(rid, self.root, "lifecycle goal", lit_source="local",
                     workflow="research")
        # 直接构造一个 FAILED research run：R1 执行失败后收尾
        st = load_state(rid, self.root)
        st.start_run()
        st.mark_step_running("R1_search")
        st.mark_step_failed("R1_search", "boom")
        st.finish_run(RunStatus.FAILED)
        # 预置一条证据，用于断言"幂等早退不追加账本"
        prov = ProvenanceLedger(os.path.join(self.root, "runs", rid), rid,
                                root=self.root)
        prov.append_evidence(kind="data", ref="pre-existing",
                             producer_step="R1_search")
        n_before = len(_ledger_lines(self.root, rid))

        # 修复前：FAILED 步骤被重新执行（重复 append_evidence）→ 末尾
        # finish_run 撞「仅 RUNNING 可 finish」抛 StateError。
        # 修复后：终态幂等早退，不抛错、不执行任何步骤。
        pipe = ResearchPipeline(self.root, rid)
        out = pipe.run_all()
        self.assertTrue(out["idempotent_reuse"])
        self.assertEqual(out["run_status"], "FAILED")
        self.assertEqual(out["workflow"], "research")
        self.assertEqual(out["failed_steps"], ["R1_search"])
        # resume 与 run_all 同路径，同样幂等早退
        out2 = ResearchPipeline(self.root, rid).resume()
        self.assertTrue(out2["idempotent_reuse"])
        self.assertEqual(out2["failed_steps"], ["R1_search"])
        # 账本不被污染：行数不变；run_status 仍为 FAILED
        self.assertEqual(len(_ledger_lines(self.root, rid)), n_before)
        st2 = load_state(rid, self.root)
        self.assertIs(st2.run_status, RunStatus.FAILED)
        self.assertEqual(st2.step_status["R1_search"].value, "FAILED")

    # ---------- L2：FAILED run 单步重试全部失败步骤后受控收敛 DONE ----------

    def test_l2_failed_run_single_step_retry_converges_done(self):
        rid = new_run_id()
        create_state(rid, self.root, "retry convergence")
        pipe = Pipeline(self.root, rid, chaos_mode="mutate_summary")
        out = pipe.run_all()
        self.assertEqual(out["run_status"], "FAILED")
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["P4_verify"].value, "FAILED")
        n_events_before = len(_events(self.root, rid))

        # 无 chaos 重试 P4：复跑验证 PASS；再补跑 P5（首次 FAILED 收尾时
        # run_all 在 P4 处 break，P5 仍 PENDING）。最后一步完成后 run 必须经
        # 受控边收敛回 DONE（修复前：run 永远停在 FAILED，web 端无法恢复）。
        # 对齐 CLI main() 的 finally 语义：上一个进程结束后 chaos 必须已清除，
        # 否则 P4 复跑子进程仍会被注入 paper-agent_MUTATE=1。
        clear_chaos_mode()
        pipe2 = Pipeline(self.root, rid)
        res = pipe2.run_step("P4_verify")
        self.assertFalse(res.get("failed"), res)
        self.assertIs(load_state(rid, self.root).run_status, RunStatus.FAILED,
                      "P5 未补跑前 run 必须仍是 FAILED（不提前收敛）")
        pipe2.run_step("P5_report")
        st2 = load_state(rid, self.root)
        self.assertIs(st2.run_status, RunStatus.DONE)
        evs = _events(self.root, rid)
        rc = [e for e in evs if e["type"] == "run_reconverged"]
        self.assertEqual(len(rc), 1, "必须恰好一条 run_reconverged 事件")
        self.assertEqual(rc[0].get("from"), "FAILED")
        self.assertEqual(rc[0].get("to"), "DONE")
        self.assertGreater(len(evs), n_events_before)

    # ---------- L3：P5 报告缺失自愈（重建 + 真实哈希入账本）----------

    def test_l3_p5_rebuilds_missing_report_with_real_hash(self):
        rid = new_run_id()
        create_state(rid, self.root, "p5 rebuild")
        pipe = Pipeline(self.root, rid)
        out = pipe.run_all()
        self.assertEqual(out["run_status"], "DONE")
        rpath = os.path.join(self.root, "runs", rid, "report.md")
        self.assertTrue(os.path.exists(rpath))
        os.remove(rpath)

        res = pipe.run_p5()
        # 复用路径检测到文件缺失 → 升级为重建，而非以 ok:true 返回不存在的文件
        self.assertTrue(res.get("report_regenerated"))
        self.assertTrue(res.get("idempotent_reuse"))
        self.assertEqual(res.get("report"), rpath)
        self.assertTrue(os.path.exists(rpath), "报告文件必须被重新生成")
        # 重建补登的报告证据必须带真实 sha256（旧缺陷：file_path=None → 空串）
        report_evs = [e for e in pipe.prov.all_evidence()
                      if e["kind"] == "report"]
        self.assertTrue(report_evs)
        self.assertEqual(report_evs[-1]["sha256"], sha256_file(rpath))
        self.assertTrue(report_evs[-1]["meta"].get("regenerated"))
        # conclusions 必须取自 conclusions.jsonl 真实条数（可验证来源）
        cpath = os.path.join(self.root, "runs", rid, "conclusions.jsonl")
        with open(cpath, "r", encoding="utf-8") as f:
            n_concl = sum(1 for l in f if l.strip())
        self.assertEqual(report_evs[-1]["meta"].get("conclusions"), n_concl)
        self.assertGreater(n_concl, 0)

    def test_l3b_p5_rebuild_failure_raises_evidence_error(self):
        rid = new_run_id()
        create_state(rid, self.root, "p5 rebuild fail")
        pipe = Pipeline(self.root, rid)
        pipe.run_all()
        rpath = os.path.join(self.root, "runs", rid, "report.md")
        self.assertTrue(os.path.exists(rpath))
        os.remove(rpath)
        # 让重建必然失败：删除报告生成所需输入（信任门禁能过，但读取产物抛错）
        os.remove(os.path.join(self.root, "runs", rid, "literature",
                               "literature_hits.json"))
        with self.assertRaises(EvidenceError) as cm:
            pipe.run_p5()
        self.assertIn("regeneration failed", str(cm.exception))

    def test_l3c_normal_p5_evidence_carries_real_hash(self):
        """正常路径回归：报告证据在生成成功后登记，sha256 为真实文件哈希。"""
        rid = new_run_id()
        create_state(rid, self.root, "p5 normal")
        pipe = Pipeline(self.root, rid)
        pipe.run_all()
        rpath = os.path.join(self.root, "runs", rid, "report.md")
        report_evs = [e for e in pipe.prov.all_evidence()
                      if e["kind"] == "report"]
        self.assertEqual(len(report_evs), 1)
        self.assertEqual(report_evs[0]["sha256"], sha256_file(rpath))
        self.assertNotEqual(report_evs[0]["sha256"], "")

    # ---------- L4：CLI run_id 校验纵深（SEC-2）----------

    def test_l4_cli_rejects_path_traversal_run_id(self):
        core = os.path.abspath(os.path.join(_TEST_DIR, "..", "core"))
        env = dict(os.environ, PYTHONPATH=core,
                   **{"paper-agent_ROOT": self.root})
        cases = [
            ["cite", "--run", "../../evil"],
            ["analyze-paper", "--run", "../../evil"],
            ["eval", "--run", "../../evil"],
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                pr = subprocess.run(
                    [sys.executable, "-m", "paper_agent.cli", *cmd],
                    cwd=self.root, env=env, capture_output=True, text=True,
                    timeout=120)
                self.assertNotEqual(pr.returncode, 0,
                                    f"非法 run_id 必须非 0 退出: {cmd}")
                payload = json.loads(pr.stdout.strip())
                self.assertFalse(payload["ok"])
                self.assertIn("run_id", payload["error"])


if __name__ == "__main__":
    unittest.main()
