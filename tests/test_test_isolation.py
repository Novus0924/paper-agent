"""test_test_isolation.py — 元测试：证明单元测试之间**不会互相污染**。

为什么需要这个文件
------------------
本项目主打"可复现"，所以**测试本身**若有非确定性就是硬伤。
历史问题：`_util.build_temp_root()` 会改5 个进程级全局量
（``os.environ["paper-agent_ROOT"]`` + ``paper_agent`` 的
``PAPER_AGENT_ROOT`` / ``DATA_DIR`` / ``EXPERIMENTS_DIR`` / ``RUNS_DIR``），
原先**只设不还原**。后跑的用例会读到上一个用例留下的临时根，
而那个目录可能已被tearDown 删掉 → 表现为**偶发**的
``AssertionError: True is not false`` 之类失败（152 例里偶发 1 例）。

修法是 ``_util.isolate_temp_root()``（用 ``addCleanup`` 自动还原）。
但"改了"不等于"生效"——本文件就是来**验证它真的生效**的。

它验证两件事
------------
1. :func:`isolate_temp_root` 退出后，5 个全局量**逐一回到原值**；
2. 一个"故意污染"的用例之后，另一个用例看到的仍是干净的仓库真实根。
"""
from __future__ import annotations

import os
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEST_DIR, "..", "core"))
sys.path.insert(0, _TEST_DIR)

import paper_agent  # noqa: E402
from _util import isolate_temp_root, project_root  # noqa: E402

_WATCHED = ("PAPER_AGENT_ROOT", "DATA_DIR", "EXPERIMENTS_DIR", "RUNS_DIR")
_ENV_KEY = "paper-agent_ROOT"


def _snapshot():
    return {
        "env": os.environ.get(_ENV_KEY),
        "globals": {n: getattr(paper_agent, n) for n in _WATCHED},
    }


class TestIsolateTempRootRestores(unittest.TestCase):
    """isolate_temp_root 必须在用例结束后把全局量还原。"""

    def test_globals_restored_after_case(self):
        before = _snapshot()

        class _Inner(unittest.TestCase):
            def runTest(self):  # noqa: N802
                root = isolate_temp_root(self, "pa_iso_")
                # 用例内部：确实被改成了临时根
                self.assertNotEqual(paper_agent.PAPER_AGENT_ROOT, before["globals"]["PAPER_AGENT_ROOT"])
                self.assertEqual(os.environ.get(_ENV_KEY), root)
                self.assertTrue(os.path.isdir(root))

        # 用真实的 TestCase 生命周期跑一遍，触发 addCleanup
        import unittest as _ut
        result = _ut.TestResult()
        _Inner("runTest").run(result)
        self.assertTrue(result.wasSuccessful(), f"内部用例失败: {result.errors + result.failures}")

        after = _snapshot()
        self.assertEqual(after["env"], before["env"], "os.environ 未还原")
        for n in _WATCHED:
            with self.subTest(name=n):
                self.assertEqual(after["globals"][n], before["globals"][n],
                                 f"{n} 未还原")

    def test_temp_dir_removed_after_case(self):
        captured = {}

        class _Inner(unittest.TestCase):
            def runTest(self):  # noqa: N802
                captured["root"] = isolate_temp_root(self, "pa_iso_gone_")

        import unittest as _ut
        _ut.TestResult()
        _Inner("runTest").run(_ut.TestResult())
        self.assertFalse(os.path.isdir(captured["root"]),
                         "临时目录未被清理")

    def test_second_case_sees_clean_root(self):
        """关键回归：前一个用例污染过之后，后一个必须看到仓库真实根。"""
        class _Polluter(unittest.TestCase):
            def runTest(self):  # noqa: N802
                isolate_temp_root(self, "pa_iso_pollute_")

        import unittest as _ut
        _Polluter("runTest").run(_ut.TestResult())

        # 不做任何隔离，直接断言看到的是仓库真实根
        self.assertEqual(os.environ.get(_ENV_KEY), project_root())
        self.assertEqual(paper_agent.PAPER_AGENT_ROOT, project_root())
        self.assertEqual(paper_agent.DATA_DIR, os.path.join(project_root(), "data"))
        self.assertTrue(os.path.isdir(paper_agent.DATA_DIR),
                        "真实 data/ 目录应存在")


if __name__ == "__main__":
    unittest.main(verbosity=2)
