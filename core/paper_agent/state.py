"""有限状态机 + run 生命周期 + 状态持久化。

设计要点（对齐文档 §4.3）：
- StepStatus: PENDING / RUNNING / DONE / FAILED / SKIPPED
- RunStatus:  PLANNED / RUNNING / DONE / FAILED
- 合法转移矩阵：
    PENDING -> RUNNING | SKIPPED
    RUNNING -> DONE | FAILED
    FAILED  -> RUNNING          (重试 / 断点续跑)
    DONE, SKIPPED: 终态，无出边
- 非法转移抛 StateError，并立即写入事件账本（由调用方负责持久化）
- run 实例目录 runs/<run_id>/state.json 每次状态转移立即落盘
- run_id 命名：run-YYYYMMDD-HHMMSS-<6位hex>（UTC）
- events.jsonl append-only；事件类型：run_planned / run_started /
  transition / retry / degrade / skip / run_finished
- DONE 步骤产物损坏 → 不允许回退修改原 run；应新建 run 实例

多工作流（v0.3 新增）
---------------------
同一套状态机 / 账本 / 编排协议，服务两条**独立的科研工作流**：

- ``materials``（默认，向后兼容）：P1..P5
    文献检索 → 数据清洗 → 真实实验 → 复现验证 → 报告（可复现实验底座）
- ``research``（v0.3 PRD 核心链路）：R1..R6
    多源检索 → 论文精读 → 创新点拆解 → 事实验证 → 综述写作 → 自评审

工作流只决定「步骤 ID 列表」，状态机转移规则完全一致，
因此 run-step / step-driven / resume / 证据账本 / 故障恢复全部复用。
"""
from __future__ import annotations

import json
import os
import secrets
import time
from enum import Enum

from .security_scan import validate_run_id, safe_runs_path


class StepStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RunStatus(Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class StateError(RuntimeError):
    """非法状态转移或状态机一致性破坏。"""


# 合法转移矩阵
_STEP_TRANSITIONS = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.SKIPPED},
    StepStatus.RUNNING: {StepStatus.DONE, StepStatus.FAILED},
    StepStatus.FAILED: {StepStatus.RUNNING},
    StepStatus.DONE: set(),
    StepStatus.SKIPPED: set(),
}
_RUN_TRANSITIONS = {
    RunStatus.PLANNED: {RunStatus.RUNNING},
    RunStatus.RUNNING: {RunStatus.DONE, RunStatus.FAILED},
    RunStatus.DONE: set(),
    RunStatus.FAILED: set(),
}

# ---- 工作流一：材料实验可复现流水线（默认，向后兼容）----
MATERIALS_STEPS = [
    "P1_lit_search",
    "P2_clean_data",
    "P3_run_experiment",
    "P4_verify",
    "P5_report",
]

# ---- 工作流二：科研全流程（v0.3 PRD §2 核心用户旅程）----
RESEARCH_STEPS = [
    "R1_search",     # 多源学术检索
    "R2_read",       # 论文精读（结构化笔记）
    "R3_analyze",    # 创新点拆解 / 技术脉络 / Research Gap
    "R4_verify",     # 事实验证（引用/数据一致性/矛盾）
    "R5_write",      # 综述写作（带引用 + BibTeX）
    "R6_review",     # 模拟自评审
]

WORKFLOWS: dict[str, list[str]] = {
    "materials": MATERIALS_STEPS,
    "research": RESEARCH_STEPS,
}
DEFAULT_WORKFLOW = "materials"

# 向后兼容：历史上 STEP_IDS 指材料流水线五步
STEP_IDS = MATERIALS_STEPS
STEP_NAMES = {sid: sid for sid in MATERIALS_STEPS + RESEARCH_STEPS}


def steps_for(workflow: str | None) -> list[str]:
    """按工作流名取步骤列表；未知工作流回落到默认（materials）。"""
    wf = (workflow or DEFAULT_WORKFLOW).lower()
    return list(WORKFLOWS.get(wf, MATERIALS_STEPS))


def _utc_now_str() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"run-{stamp}-{secrets.token_hex(3)}"


# P1 文献检索来源。默认 local（离线、逐字节可复现）；联网检索需显式开启：
#   --lit-source arxiv  实时检索 arXiv（结果快照冻结，保确定性）
#   --lit-source auto   先试 arXiv，失败自动降级本地语料
# 单测通过环境变量 paper-agent_LIT_SOURCE=local 强制离线（见 tests/__init__.py）。
LIT_SOURCES = ("local", "arxiv", "auto")


def default_lit_source() -> str:
    """解析文献检索来源的默认值（环境变量 > 内置默认）。"""
    env = os.environ.get("paper-agent_LIT_SOURCE", "").strip().lower()
    return env if env in LIT_SOURCES else "auto"


class PipelineState:
    """一个 run 实例的完整状态机。

    所有状态变更都必须经过 transition() / mark_step_*() 等接口，
    禁止直接改 state.json。接口在合法时持久化 state.json，
    并 append 一条事件到 events.jsonl。

    ``workflow`` 决定步骤集合（materials / research）；``steps`` 可显式覆盖。
    """

    def __init__(self, run_id: str, root: str, goal: str = "",
                 lit_source: str | None = None,
                 workflow: str = DEFAULT_WORKFLOW,
                 steps: list[str] | None = None):
        self.run_id = run_id
        self.root = root
        self.goal = goal
        self.lit_source = (lit_source or default_lit_source()).lower()
        if self.lit_source not in LIT_SOURCES:
            self.lit_source = "auto"
        wf = (workflow or DEFAULT_WORKFLOW).lower()
        self.workflow = wf if wf in WORKFLOWS else DEFAULT_WORKFLOW
        self.step_ids = list(steps) if steps else steps_for(self.workflow)
        # 防御 H1：run_id 来自不可信输入（LLM 工具参数），构造期即强校验 +
        # realpath 容器检查，阻断 ../../ 穿越写/读任意文件。
        validate_run_id(run_id)
        self.run_dir = safe_runs_path(root, run_id)
        self.state_path = os.path.join(self.run_dir, "state.json")
        self.events_path = os.path.join(self.run_dir, "events.jsonl")

        self.run_status = RunStatus.PLANNED
        self.step_status = {sid: StepStatus.PENDING for sid in self.step_ids}
        self.attempts = {sid: 0 for sid in self.step_ids}
        self.degraded = False
        self.created_at = _utc_now_str()
        self.updated_at = self.created_at
        self._loaded = False

    # ---------- 生命周期 ----------

    def plan(self) -> None:
        """创建 run 实例目录，初始化状态并写 run_planned 事件。幂等。"""
        os.makedirs(self.run_dir, exist_ok=True)
        for sub in ("toolcalls", "literature", "clean", "experiment",
                    "verification", "results", "reading", "analysis",
                    "factcheck", "writing", "review", "evaluation", "batch"):
            os.makedirs(os.path.join(self.run_dir, sub), exist_ok=True)
        if not self._loaded:
            self._append_event("run_planned", {
                "goal": self.goal,
                "workflow": self.workflow,
                "steps": list(self.step_ids),
                "lit_source": self.lit_source,
                "created_at": self.created_at,
            })
            self._persist_state()
            self._loaded = True

    def load(self) -> None:
        """从 state.json 恢复 run 状态（断点续跑）。"""
        if not os.path.exists(self.state_path):
            raise StateError(f"state.json not found for run {self.run_id}")
        with open(self.state_path, "r", encoding="utf-8") as f:
            snap = json.load(f)
        self.run_status = RunStatus(snap["run_status"])
        self.workflow = snap.get("workflow", DEFAULT_WORKFLOW)
        if self.workflow not in WORKFLOWS:
            self.workflow = DEFAULT_WORKFLOW
        # 优先用快照里显式记录的 steps，保证历史 run 的前向兼容；
        # 必须**重建** step_status/attempts，清掉构造器按默认工作流预置的步骤，
        # 否则 research run 会混入 materials 的 P1..P5（PENDING）而无法收敛。
        self.step_ids = list(snap.get("steps_order") or steps_for(self.workflow))
        self.step_status = {}
        self.attempts = {}
        for sid in self.step_ids:
            self.step_status[sid] = StepStatus(snap["steps"][sid])
            self.attempts[sid] = snap.get("attempts", {}).get(sid, 0)
        self.degraded = snap.get("degraded", False)
        self.lit_source = snap.get("lit_source", self.lit_source)
        if self.lit_source not in LIT_SOURCES:
            self.lit_source = "auto"
        self.created_at = snap.get("created_at", self.created_at)
        self.updated_at = snap.get("updated_at", self.updated_at)
        if snap.get("goal"):
            self.goal = snap["goal"]
        self._loaded = True

    @property
    def run_id_name(self) -> str:
        return self.run_id

    # ---------- 事件账本 ----------

    def _append_event(self, etype: str, payload: dict) -> None:
        os.makedirs(self.run_dir, exist_ok=True)
        entry = {"ts": _utc_now_str(), "type": etype, "run_id": self.run_id}
        entry.update(payload)
        with open(self.events_path, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def _persist_state(self) -> None:
        snap = {
            "run_id": self.run_id,
            "run_status": self.run_status.value,
            "workflow": self.workflow,
            "steps_order": list(self.step_ids),
            "steps": {sid: self.step_status[sid].value for sid in self.step_ids},
            "attempts": dict(self.attempts),
            "degraded": self.degraded,
            "goal": self.goal,
            "lit_source": self.lit_source,
            "created_at": self.created_at,
            "updated_at": _utc_now_str(),
        }
        os.makedirs(self.run_dir, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, self.state_path)
        self.updated_at = snap["updated_at"]

    # ---------- run 级转移 ----------

    def start_run(self) -> None:
        self._ensure_run(RunStatus.PLANNED, RunStatus.RUNNING, "run_started")
        self._append_event("run_started", {"at": _utc_now_str()})
        self._persist_state()

    def finish_run(self, status: RunStatus) -> None:
        if status not in (RunStatus.DONE, RunStatus.FAILED):
            raise StateError(f"finish_run expects DONE or FAILED, got {status}")
        self._ensure_run(RunStatus.RUNNING, status, "run_finished")
        self._append_event("run_finished", {"final_status": status.value})
        self._persist_state()

    def _ensure_run(self, src: RunStatus, dst: RunStatus, etype: str) -> None:
        if self.run_status is not src:
            raise StateError(
                f"run {self.run_id} status {self.run_status.value} -> "
                f"{dst.value} illegal (expected {src.value})"
            )
        self.run_status = dst
        self._append_event(etype, {"from": src.value, "to": dst.value})

    # ---------- step 级转移 ----------

    def _check_step(self, sid: str) -> None:
        if sid not in self.step_ids:
            raise StateError(f"unknown step {sid} for workflow {self.workflow}")

    def mark_step_running(self, sid: str, retry: bool = False) -> None:
        self._check_step(sid)
        cur = self.step_status[sid]
        if cur not in _STEP_TRANSITIONS:
            raise StateError(f"step {sid} in unmodeled state {cur}")
        if StepStatus.RUNNING not in _STEP_TRANSITIONS[cur]:
            raise StateError(f"illegal step transition {sid}: {cur.value} -> RUNNING")
        self.step_status[sid] = StepStatus.RUNNING
        self.attempts[sid] += 1
        etype = "retry" if retry else "transition"
        self._append_event(etype, {
            "step": sid,
            "from": cur.value,
            "to": "RUNNING",
            "attempt": self.attempts[sid],
        })
        self._persist_state()

    def mark_step_done(self, sid: str, extra: dict | None = None) -> None:
        self._check_step(sid)
        cur = self.step_status[sid]
        if cur is not StepStatus.RUNNING:
            raise StateError(f"illegal step transition {sid}: {cur.value} -> DONE")
        self.step_status[sid] = StepStatus.DONE
        payload = {"step": sid, "from": "RUNNING", "to": "DONE"}
        if extra:
            payload.update(extra)
        self._append_event("transition", payload)
        self._persist_state()

    def retry_attempt(self, sid: str, reason: str = "") -> None:
        """在 RUNNING 态内记录一次重试（attempts+=1 + retry 事件），不做状态转移。

        用于 P1 重试‑降级策略：首次 mark_step_running 已将 attempts 置 1；
        每次重试调用本接口递增 attempts 并留痕。chaos 判断"仅首次"仍由
        上层传入 attempt 参数决定，本接口只负责记账，不改变状态。
        """
        self._check_step(sid)
        if self.step_status[sid] is not StepStatus.RUNNING:
            raise StateError(f"retry_attempt on {sid} not RUNNING ({self.step_status[sid].value})")
        self.attempts[sid] += 1
        self._append_event("retry", {
            "step": sid,
            "attempt": self.attempts[sid],
            "reason": reason,
        })
        self._persist_state()

    def mark_step_failed(self, sid: str, reason: str = "") -> None:
        self._check_step(sid)
        cur = self.step_status[sid]
        if cur is not StepStatus.RUNNING:
            raise StateError(f"illegal step transition {sid}: {cur.value} -> FAILED")
        self.step_status[sid] = StepStatus.FAILED
        self._append_event("transition", {
            "step": sid, "from": "RUNNING", "to": "FAILED",
            "reason": reason,
        })
        self._persist_state()

    def mark_step_skipped(self, sid: str, reason: str = "") -> None:
        self._check_step(sid)
        cur = self.step_status[sid]
        if cur is not StepStatus.PENDING:
            raise StateError(f"illegal step transition {sid}: {cur.value} -> SKIPPED")
        self.step_status[sid] = StepStatus.SKIPPED
        self._append_event("skip", {"step": sid, "reason": reason})
        self._persist_state()

    # ---------- 降级标记 ----------

    def mark_degraded(self, sid: str, note: str = "") -> None:
        self.degraded = True
        self._append_event("degrade", {"step": sid, "note": note})
        self._persist_state()

    # ---------- 查询 ----------

    def pending_or_failed(self) -> list[str]:
        return [sid for sid in self.step_ids
                if self.step_status[sid] in (StepStatus.PENDING, StepStatus.FAILED)]

    def all_terminal(self) -> bool:
        return all(st in (StepStatus.DONE, StepStatus.SKIPPED, StepStatus.FAILED)
                   for st in self.step_status.values())

    def snapshot(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_status": self.run_status.value,
            "workflow": self.workflow,
            "steps": {sid: st.value for sid, st in self.step_status.items()},
            "attempts": dict(self.attempts),
            "degraded": self.degraded,
        }


def new_run_id() -> str:
    return _run_id()


def create_state(run_id: str, root: str, goal: str = "",
                 lit_source: str | None = None,
                 workflow: str = DEFAULT_WORKFLOW,
                 steps: list[str] | None = None) -> PipelineState:
    st = PipelineState(run_id, root, goal, lit_source=lit_source,
                       workflow=workflow, steps=steps)
    st.plan()
    return st


def load_state(run_id: str, root: str) -> PipelineState:
    st = PipelineState(run_id, root)
    st.load()
    return st
