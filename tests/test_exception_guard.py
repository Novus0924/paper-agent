"""test_exception_guard.py — 回归测试：异常兜底与解析器推进保障。

锁定两处实测缺陷的修复，防止回退：
1. steps.py：步骤函数抛异常（如实验子进程超时/解释器缺失）时，
   步骤必须先落 FAILED 再抛出；否则步骤永久卡在 RUNNING，
   状态机拒绝 RUNNING→RUNNING，run 从此无法 resume（变砖）。
2. pdfparse.py：_content_text 遇到孤立 ')' / '>' / '<<' 的 '<' 时
   必须强制推进游标；否则损坏的 PDF 内容流会导致死循环挂死 CPU。
"""
import os
import subprocess
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEST_DIR, "..", "core"))
sys.path.insert(0, _TEST_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent.state import create_state, load_state, new_run_id  # noqa: E402
from paper_agent.steps import Pipeline  # noqa: E402
from paper_agent.chaos import clear_chaos_mode  # noqa: E402
from paper_agent.pdfparse import _content_text  # noqa: E402


class TestStepExceptionGuard(unittest.TestCase):
    """步骤函数抛异常 → 先 mark_step_failed 再冒泡，且 FAILED 可重试。"""

    def setUp(self):
        clear_chaos_mode()
        self.root = isolate_temp_root(self, "pa_guard_")

    def tearDown(self):
        clear_chaos_mode()

    def test_p3_exception_marks_failed_and_resumable(self):
        import paper_agent.steps as S

        rid = new_run_id()
        create_state(rid, self.root, "guard goal", workflow="materials")
        pipe = Pipeline(self.root, rid)
        pipe._ensure_running()

        def _boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="arrhenius_rank.py", timeout=30)

        orig = S.Pipeline._spawn_experiment
        S.Pipeline._spawn_experiment = _boom
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                pipe.run_step("P3_run_experiment")
        finally:
            S.Pipeline._spawn_experiment = orig

        # ① 步骤必须已落 FAILED（而非永久卡 RUNNING）
        st = load_state(rid, self.root)
        self.assertEqual(st.step_status["P3_run_experiment"].value, "FAILED")

        # ② FAILED 步骤必须可重试：run_step 不抛 StateError，
        #    恢复真实 spawn 后（clean csv 缺失）实验返回非零 → failed=True
        pipe2 = Pipeline(self.root, rid)
        res = pipe2.run_step("P3_run_experiment")
        self.assertTrue(res.get("failed"),
                        "重试路径应正常执行并因产物缺失而 failed，而非 StateError 变砖")


class TestPdfparseAdvances(unittest.TestCase):
    """_content_text 对畸形定界符必须推进游标（曾死循环挂死）。"""

    def test_orphan_delimiters_do_not_hang(self):
        # 正常内容在前，畸形定界符（孤立 ')' '>'、'<<' 的 '<'、'\'）在后。
        # 修复前：i 游标在孤立定界符处零推进 → 无限循环挂死。
        data = b"(hello) Tj ) > << \\"
        out = _content_text(data)   # 修复前：无限循环
        self.assertIsInstance(out, str)
        self.assertIn("hello", out)

    def test_truncated_hexstring_returns(self):
        # 未闭合的十六进制字符串 <abc（无 '>'）→ 应立即返回，不挂死
        out = _content_text(b"<abc")
        self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main()
