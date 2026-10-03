"""test_docs_consistency.py — 文档 ↔ 实现一致性守门（回归"文档漂移"）。

背景
----
本项目曾出现两类**测试全绿但事实错误**的问题：

1. 文档写「`--lit-source local --chaos ss_timeout` 会得到
   `unavailable_sources=['semantic_scholar']`」，但实现里 local 分支短路，
   该命令实际产出 `[]`。单测只测了 `search_papers` 单函数，**没测文档给的命令**。
2. 文档写「系统 0.05s/篇」，而该数字是 `build_demo_evals` 里的**硬编码常量**，非实测。

因此本文件把**文档中的关键可验证声称**变成**可执行断言**：
不是去解析 Markdown（脆弱），而是把「文档承诺的行为」在本文件中复现一遍，
一旦实现漂移，这些用例就会红——把"文档-实现不一致"变成 CI 可捕获的错误。

约定：本文件只断言**稳定契约**（工具数量、工作流步骤、F-4.8 行为、指标口径），
不断言随实验波动的具体浮点值（如 NDCG=0.987），后者的阈值断言在 test_evaluate.py。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
sys.path.insert(0, os.path.join(_PROJ, "core"))
sys.path.insert(0, _TESTS_DIR)

from paper_agent.state import MATERIALS_STEPS, RESEARCH_STEPS  # noqa: E402


def _read(rel: str) -> str:
    with open(os.path.join(_PROJ, rel), "r", encoding="utf-8") as f:
        return f.read()


def _cli(*args, root: str):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(_PROJ, "core")
    env["paper-agent_ROOT"] = root
    env["paper-agent_LIT_SOURCE"] = "local"
    return subprocess.run([sys.executable, "-m", "paper_agent.cli", *args],
                          capture_output=True, text=True, env=env)


class TestPluginToolCount(unittest.TestCase):
    """文档声称插件注册 17 工具 + 1 Skill，必须与插件真实注册数一致。"""

    DOCS = ("README.md", "submission/项目说明.md",
            "docs/PRD-v0.3-需求实现映射.md")

    def test_docs_claim_17_tools(self):
        for rel in self.DOCS:
            txt = _read(rel)
            self.assertTrue(
                re.search(r"17\s*(?:个)?\s*`?sciret", txt)
                or "17 工具" in txt or "17 个" in txt and "工具" in txt,
                f"{rel} 未声明 17 个工具（文档漂移）")

    def test_plugin_registers_17_tool_names(self):
        """直接在 mock 宿主下加载插件，核对注册的工具数。"""
        script = (
            "import('./plugins/paper-agent-tools/index.mjs').then(async (m)=>{"
            "const tools=[];"
            "const agnes={on:()=>{},ctx:{log:{info(){},warn(){}}},"
            "registerTool:(t)=>tools.push(t.name)};"
            "const ctx={extension:()=>agnes,skills:{register:()=>{}}};"
            "await m.paperAgentTools.apply(ctx);"
            "console.log(tools.length);"
            "}).catch(e=>{console.error(e);process.exit(1);});")
        r = subprocess.run(["node", "-e", script], capture_output=True,
                           text=True, cwd=_PROJ)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "17",
                         "插件实际注册工具数与文档声称的 17 不一致")


class TestWorkflowSteps(unittest.TestCase):
    def test_docs_state_research_steps(self):
        txt = _read("docs/PRD-v0.3-需求实现映射.md")
        for sid in RESEARCH_STEPS:
            self.assertIn(sid, txt, f"映射文档缺少 research 步骤 {sid}")
        for sid in MATERIALS_STEPS:
            self.assertIn(sid, txt, f"映射文档缺少 materials 步骤 {sid}")

    def test_readme_mentions_both_workflows(self):
        txt = _read("README.md")
        self.assertIn("materials", txt)
        self.assertIn("research", txt)


class TestDocumentedF48CommandsActuallyWork(unittest.TestCase):
    """README / HOW-TO-VERIFY / 映射文档给出的 F-4.8 命令，逐条实跑并与文档一致。

    这是本项目最重要的一组守门用例：此前的重大缺陷正是
    「文档给的命令触发不到文档声称的场景」，而单测没覆盖命令本身。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_doc_")
        shutil.copytree(os.path.join(_PROJ, "data"),
                        os.path.join(self._tmp, "data"))
        shutil.copytree(os.path.join(_PROJ, "experiments"),
                        os.path.join(self._tmp, "experiments"))

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, chaos: str):
        r = _cli("run-all", "--workflow", "research",
                 "--goal", "sulfide solid electrolyte ionic conductivity",
                 "--lit-source", "local", "--chaos", chaos, root=self._tmp)
        runs = sorted(d for d in os.listdir(os.path.join(self._tmp, "runs"))
                      if d.startswith("run-"))
        rid = runs[-1]
        base = os.path.join(self._tmp, "runs", rid)
        with open(os.path.join(base, "literature", "research_hits.json"),
                  encoding="utf-8") as f:
            hits = json.load(f)
        with open(os.path.join(base, "reading", "reading_report.json"),
                  encoding="utf-8") as f:
            rep = json.load(f)
        with open(os.path.join(base, "state.json"), encoding="utf-8") as f:
            st = json.load(f)
        return r, rid, hits, rep, st

    def test_scenario1_command_switches_source_offline(self):
        """文档：`--lit-source local --chaos ss_timeout` → 标注切源、任务不中断。

        这条命令**正是文档给出**的复验方式；它必须真正触发切源语义。
        """
        r, _, hits, _, st = self._run("ss_timeout")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(hits["unavailable_sources"], ["semantic_scholar"])
        self.assertTrue(st["degraded"], "切源必须被记为 degraded")
        self.assertGreater(hits["n_hits"], 0, "任务不应中断")

    def test_scenario2_command_degrades_scanned(self):
        r, _, _, rep, st = self._run("scan_pdf")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(rep["scanned_or_low_conf"], 0)
        self.assertTrue(st["degraded"])

    def test_scenario3_command_skips_failed_item(self):
        r, _, _, rep, st = self._run("batch_fail_at=2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rep["n_failed"], 1)
        self.assertEqual(rep["failures"][0]["doc_id"], "L002")
        self.assertTrue(st["degraded"])

    def test_scenario3prime_command_crashes_then_resumes(self):
        r, rid, _, _, _ = self._run("kill_after_r3")
        self.assertEqual(r.returncode, 137, "kill_after_r3 必须真实 SIGKILL(137)")
        r2 = _cli("resume", "--run", rid, root=self._tmp)
        self.assertEqual(json.loads(r2.stdout).get("run_status"), "DONE")


class TestEvalMetricsAreMeasuredNotHardcoded(unittest.TestCase):
    """文档口径：精读耗时是**实测**，不是写死常量。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_doc_ev_")
        shutil.copytree(os.path.join(_PROJ, "data"),
                        os.path.join(self._tmp, "data"))
        shutil.copytree(os.path.join(_PROJ, "experiments"),
                        os.path.join(self._tmp, "experiments"))
        sys.path.insert(0, os.path.join(_PROJ, "core"))

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_system_seconds_vary_across_docs(self):
        """实测耗时不可能每篇完全一致；若全等说明又被写死了。"""
        from paper_agent.evaluate import build_demo_evals
        demo = build_demo_evals(self._tmp)
        times = [c["system_seconds"] for c in demo["reading"]]
        self.assertTrue(all(t > 0 for t in times), "耗时必须为正数")
        self.assertGreater(len(set(times)), 1,
                           "5 篇耗时完全相同 → 疑似重新被硬编码")

    def test_docs_do_not_claim_exact_hardcoded_seconds(self):
        """文档不应再出现「0.05s/篇」这种写死常量式声称。"""
        for rel in ("README.md", "docs/PRD-v0.3-需求实现映射.md",
                    "submission/项目说明.md"):
            txt = _read(rel)
            self.assertNotIn("0.05s/篇", txt,
                             f"{rel} 仍保留写死的 0.05s/篇 声称")


class TestSearchPrecisionHonesty(unittest.TestCase):
    """文档必须如实说明 Precision 低于基线，不能只报有利指标。"""

    def test_docs_disclose_precision_below_baseline(self):
        for rel in ("docs/PRD-v0.3-需求实现映射.md", "README.md"):
            txt = _read(rel)
            self.assertTrue(
                ("低于基线" in txt) or ("略低于" in txt),
                f"{rel} 未诚实披露 Precision 低于基线")


if __name__ == "__main__":
    unittest.main()
