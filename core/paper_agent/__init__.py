"""paper_agent — 科研 Agent 流水线核心包。

工程决策记录：文档目标态写作 ``core/paper‑agent``，但 Python 顶层包名必须是
合法标识符（连字符 U+002D / 全角 U+2011 均不合法），故采用下划线命名
``core/paper_agent``，CLI 通过 ``python -m paper_agent.cli`` 调用。

本包提供统一的根路径探测，供所有子模块引用项目根目录下的 data/ 与
experiments/ 等静态资源，避免依赖当前工作目录。
"""
from __future__ import annotations

import os

# 核心包位于 <root>/core/paper_agent/，故根目录为两个层级之上。
# 允许通过环境变量覆盖：优先 PAPER_AGENT_ROOT（标准命名，bash 可直接操作），
# 其次 paper-agent_ROOT（AGH 插件层历史注入名，保留兼容；含连字符，
# 在 bash 中无法 unset/引用，仅可由宿主进程注入）。
def _detect_root() -> str:
    override = os.environ.get("PAPER_AGENT_ROOT") or os.environ.get("paper-agent_ROOT")
    if override:
        return os.path.abspath(override)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


PAPER_AGENT_ROOT = _detect_root()
DATA_DIR = os.path.join(PAPER_AGENT_ROOT, "data")
EXPERIMENTS_DIR = os.path.join(PAPER_AGENT_ROOT, "experiments")
RUNS_DIR = os.path.join(PAPER_AGENT_ROOT, "runs")

__all__ = ["PAPER_AGENT_ROOT", "DATA_DIR", "EXPERIMENTS_DIR", "RUNS_DIR"]
