"""test_judgment_enforcement.py — 判据4 硬前置（judge 接入 research 主线）的端到端验证。

红线：判断（judgment）留痕是报告生成的硬前置——
  ① 正常 research run 的账本必含 query_generation（R1）与 relevance（R2）判断；
  ② 精读选择逐篇留痕：选中 → relevant，超限排除 → excluded（排除项可经
     excluded_judgments() 审计视图取回）；
  ③ 账本无判断记录（删除记录 / 链合法但本无判断）→ 报告生成失败（EvidenceError）；
  ④ PAPER_AGENT_ENFORCE_JUDGMENT=0 可显式旁路（仅调试用途）；
  ⑤ materials 侧 P1 同样登记检索式生成判断。
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEST_DIR, "..", "core"))
sys.path.insert(0, _TEST_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent import report as report_mod  # noqa: E402
from paper_agent import steps as steps_mod  # noqa: E402
from paper_agent.chaos import clear_chaos_mode  # noqa: E402
from paper_agent.provenance import EvidenceError, ProvenanceLedger  # noqa: E402
from paper_agent.research import _read_limit  # noqa: E402
from paper_agent.state import load_state  # noqa: E402

GOAL = "solid-state electrolyte conductivity prediction"


class TestJudgmentEnforcement(unittest.TestCase):
    def setUp(self):
        clear_chaos_mode()
        self.root = isolate_temp_root(self, "pa_judg_")

    def tearDown(self):
        clear_chaos_mode()

    def _run_research(self):
        """跑一个完整 research run（local 语料，离线确定）。"""
        rid = steps_mod.new_run_id()
        steps_mod.create_state(rid, self.root, GOAL, lit_source="local",
                               workflow="research")
        pipe = steps_mod.open_pipeline(self.root, rid)
        out = pipe.run_all()
        return rid, pipe, out

    # ---------- ① ② 判断登记 ----------

    def test_research_run_registers_query_and_relevance_judgments(self):
        rid, pipe, out = self._run_research()
        self.assertEqual(out["run_status"], "DONE")
        js = pipe.prov.judgments()
        kinds = {j["kind"] for j in js}
        self.assertIn("query_generation", kinds)
        self.assertIn("relevance", kinds)

        # query_generation 恰好 1 条（R1），subject = 研究目标
        qj = [j for j in js if j["kind"] == "query_generation"]
        self.assertEqual(len(qj), 1)
        self.assertEqual(qj[0]["ref"], GOAL)
        self.assertEqual(qj[0]["meta"]["verdict"], "generated")
        self.assertTrue(qj[0]["meta"]["rationale"])

        # relevance 逐篇留痕：条数 == 检索命中数；选中/排除符合精读上限切分
        with open(os.path.join(self.root, "runs", rid, "literature",
                               "research_hits.json"), encoding="utf-8") as f:
            hits = json.load(f)["hits"]
        limit = _read_limit()
        rj = [j for j in js if j["kind"] == "relevance"]
        self.assertEqual(len(rj), len(hits))
        n_selected = sum(1 for j in rj if j["meta"]["verdict"] == "relevant")
        n_excluded = sum(1 for j in rj if j["meta"]["verdict"] == "excluded")
        self.assertEqual(n_selected, min(limit, len(hits)))
        self.assertEqual(n_excluded, max(0, len(hits) - limit))
        for j in rj:
            self.assertEqual(j["meta"]["axis"], "paper_selection")
            self.assertTrue(j["meta"]["rationale"])
        # 被排除项可经审计视图取回（可复核、可反驳）
        self.assertEqual(len(pipe.prov.excluded_judgments()), n_excluded)

    def test_report_generation_succeeds_with_judgments_by_default(self):
        """enforce 默认开启：正常 run（账本含判断）→ 不设环境变量也出报告。"""
        rid, pipe, out = self._run_research()
        self.assertEqual(out["run_status"], "DONE")
        state = load_state(rid, self.root)
        with patch.dict(os.environ):
            os.environ.pop("PAPER_AGENT_ENFORCE_JUDGMENT", None)
            rpath = report_mod.generate_research_report(
                self.root, rid, state, pipe.prov)
        self.assertTrue(os.path.exists(rpath))

    # ---------- ③ 判据4：无判断 → 报告失败 ----------

    def test_report_refused_when_judgment_records_deleted(self):
        """删除账本中的判断记录 → 报告生成失败（判据4 端到端）。"""
        rid, pipe, out = self._run_research()
        self.assertEqual(out["run_status"], "DONE")
        self.assertGreater(len(pipe.prov.judgments()), 0)

        ledger_path = os.path.join(self.root, "runs", rid, "provenance.jsonl")
        with open(ledger_path, "r", encoding="utf-8") as f:
            recs = [json.loads(line) for line in f if line.strip()]
        kept = [r for r in recs if r.get("tier") != "judgment"]
        self.assertLess(len(kept), len(recs))
        with open(ledger_path, "w", encoding="utf-8", newline="") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

        # 重新加载账本（内存态不可信，磁盘即真相）
        fresh = ProvenanceLedger(os.path.join(self.root, "runs", rid), rid,
                                 root=self.root)
        state = load_state(rid, self.root)
        # R6 收尾时已自动出过一次报告；先移除旧报告，验证"拒绝后不产出新报告"
        old_report = os.path.join(self.root, "runs", rid, "report.md")
        if os.path.exists(old_report):
            os.remove(old_report)
        with self.assertRaises(EvidenceError):
            report_mod.generate_research_report(self.root, rid, state, fresh)
        self.assertFalse(os.path.exists(old_report))

    def test_report_refused_when_ledger_has_facts_but_no_judgments(self):
        """链合法但账本无判断记录 → enforce 默认拒绝（判据4 纯门禁路径）。"""
        rid = steps_mod.new_run_id()
        steps_mod.create_state(rid, self.root, GOAL, lit_source="local",
                               workflow="research")
        run_dir = os.path.join(self.root, "runs", rid)
        prov = ProvenanceLedger(run_dir, rid, root=self.root)
        # 只登记 fact 级证据（R1 检索输出文件），不登记任何判断
        prov.append_evidence(
            kind="data", ref=os.path.join("literature", "research_hits.json"),
            producer_step="R1_search")
        state = load_state(rid, self.root)
        with patch.dict(os.environ):
            os.environ.pop("PAPER_AGENT_ENFORCE_JUDGMENT", None)
            with self.assertRaises(EvidenceError) as cm:
                report_mod.generate_research_report(
                    self.root, rid, state, prov)
        self.assertIn("no judgment records", str(cm.exception))

    # ---------- ④ 显式旁路 ----------

    def test_enforce_bypass_with_env_zero(self):
        """PAPER_AGENT_ENFORCE_JUDGMENT=0 显式旁路（调试历史 run 用）。"""
        rid = steps_mod.new_run_id()
        steps_mod.create_state(rid, self.root, GOAL, lit_source="local",
                               workflow="research")
        run_dir = os.path.join(self.root, "runs", rid)
        prov = ProvenanceLedger(run_dir, rid, root=self.root)
        prov.append_evidence(
            kind="data", ref=os.path.join("literature", "research_hits.json"),
            producer_step="R1_search")
        state = load_state(rid, self.root)
        with patch.dict(os.environ, {"PAPER_AGENT_ENFORCE_JUDGMENT": "0"}):
            rpath = report_mod.generate_research_report(
                self.root, rid, state, prov)
        self.assertTrue(os.path.exists(rpath))

    # ---------- ⑤ materials 侧 ----------

    def test_p1_registers_query_generation_judgment(self):
        rid = steps_mod.new_run_id()
        steps_mod.create_state(rid, self.root, GOAL, lit_source="local")
        pipe = steps_mod.Pipeline(self.root, rid)
        pipe.run_step("P1_lit_search")
        qj = [j for j in pipe.prov.judgments()
              if j["kind"] == "query_generation"]
        self.assertEqual(len(qj), 1)
        self.assertEqual(qj[0]["ref"], GOAL)
        self.assertEqual(qj[0]["meta"]["verdict"], "generated")
        self.assertTrue(qj[0]["meta"]["rationale"])

    def test_p1_snapshot_reuse_does_not_duplicate_judgment(self):
        """auto 源首跑建快照后复跑 P1 → 走 snapshot_reused 分支，不重复登记。"""
        rid = steps_mod.new_run_id()
        steps_mod.create_state(rid, self.root, GOAL, lit_source="auto")
        pipe = steps_mod.Pipeline(self.root, rid)
        pipe.run_step("P1_lit_search")  # 离线环境：auto → 回落本地语料
        n_before = len([j for j in pipe.prov.judgments()
                        if j["kind"] == "query_generation"])
        self.assertEqual(n_before, 1)
        # 人为放置一份快照，强制下一次 _p1_search 走 snapshot_reused 分支
        lit_dir = os.path.join(self.root, "runs", rid, "literature")
        snap_path = os.path.join(lit_dir, "arxiv_snapshot.json")
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump({"goal": GOAL, "query": GOAL, "source": "arxiv",
                       "fetched_at": "2026-10-06T00:00:00Z",
                       "n_documents": 1,
                       "documents": [{"doc_id": "demo-1", "title": "demo"}]}, f)
        pipe._p1_search(GOAL, full_corpus=False)
        n_after = len([j for j in pipe.prov.judgments()
                       if j["kind"] == "query_generation"])
        self.assertEqual(n_after, 1)


if __name__ == "__main__":
    unittest.main()
