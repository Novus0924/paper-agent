"""chaos — 故障注入模块（文档 §4.5 + 四大故障用例）。

设计要点（陷阱 #2 强规避）：
- 必须通过传入的 attempt 参数判断"仅首次失败"，禁止读 step 内部计数器
- 用例矩阵：
    p1_fail_first : P1 第 1 次 attempt 抛 TransientError；重试后成功
    p1_fail_all   : P1 所有 attempt 都抛 TransientError；触发降级
    kill_after_p2 : run-all 在 P2 完成后 os._exit(137) 杀死进程（真实崩溃模拟，
                    账本已落盘；后续用 resume 断点续跑）
    mutate_summary: P3/P4 实验子进程注入环境变量 paper-agent_MUTATE=1，制造复现不一致
- 故障开关通过环境变量 paper-agent_CHAOS=<mode> 设置；
  也允许通过 set_chaos_mode() 直接设定，方便测试与 CLI。
"""
from __future__ import annotations

import os

CHAOS_ENV = "paper-agent_MUTATE"
CHAOS_MODE_ENV = "paper-agent_CHAOS"


class TransientError(RuntimeError):
    """可重试的临时故障（唯一允许触发重试的异常类型）。"""


class PermanentError(RuntimeError):
    """不可重试的硬故障，触发后直接 FAILED。"""


class _ChaosRegistry:
    def __init__(self) -> None:
        self._mode = os.environ.get(CHAOS_MODE_ENV, "")

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        os.environ[CHAOS_MODE_ENV] = mode

    def clear(self) -> None:
        self._mode = ""
        os.environ.pop(CHAOS_MODE_ENV, None)

    # ---- 针对 P1 的故障钩子（通过 attempt 判断"仅首次"）----

    def p1_maybe_raise(self, attempt: int) -> None:
        """attempt 从 1 开始。p1_fail_first 仅在 attempt==1 时抛出；
        p1_fail_all 每次 attempt 都抛出。"""
        if self._mode == "p1_fail_first" and attempt == 1:
            raise TransientError("chaos: p1_fail_first (attempt=1)")
        if self._mode == "p1_fail_all":
            raise TransientError(f"chaos: p1_fail_all (attempt={attempt})")

    def p4_rerun_env(self) -> dict:
        """P4 复现复跑子进程环境变量注入。

        仅 P4 的复跑子进程在 mutate_summary 模式下注入 paper-agent_MUTATE=1，
        使复跑 summary 的 top3 被交换，从而与原 P3 实验（正常 env）产生不一致，
        触发 P4 验证 FAIL。P3 原实验始终使用正常 env（保证 results.csv 确定性）。
        """
        if self._mode == "mutate_summary":
            return {CHAOS_ENV: "1"}
        return {}

    def kill_after(self, step_id: str) -> None:
        """kill_after_p2：在 run-all 循环中 P2 完成后杀死当前进程（os._exit 模拟
        SIGKILL，退出码 137 = 128+9）。调用点保证位于该步骤账本与状态全部落盘
        之后，因此 events.jsonl / provenance.jsonl 保持 append-only 完整，
        P3-P5 仍为 PENDING，可由 resume 断点续跑。"""
        if self._mode == "kill_after_p2" and step_id == "P2_clean_data":
            for stream in (getattr(os, "stderr", None), getattr(os, "stdout", None)):
                try:
                    stream.flush()
                except Exception:
                    pass
            os._exit(137)


# 模块级单例，跨 CLI / steps 共享
CH = _ChaosRegistry()


def chaos_mode() -> str:
    return CH.mode


def set_chaos_mode(mode: str) -> None:
    CH.set_mode(mode)


def clear_chaos_mode() -> None:
    CH.clear()
