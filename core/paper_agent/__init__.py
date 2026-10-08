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
# 允许通过环境变量 paper-agent_ROOT 覆盖（AGH 插件层注入项目根路径）。
_ROOT_ENV = "paper-agent_ROOT"
# 校验标记：一个合法的项目根必须包含该子目录（core/paper_agent）。
_ROOT_MARKER = os.path.join("core", "paper_agent")


def _validate_root(path: str) -> str:
    """校验 ``paper-agent_ROOT`` 指向的目录确实是一个合法项目根（P0-2）。

    读到自定义根时**必须**校验，不得静默用于 ``RUNS_DIR``：失效时（目录不存在
    或缺少 ``core/paper_agent``）会表现为误导性的 ``ModuleNotFoundError: No module
    named 'paper_agent'``（表面像"组件没装"，实际是"daemon 没带对变量"），
    排查成本极高。这里改为显式的人话报错。

    :param path: 环境变量 ``paper-agent_ROOT`` 的原始取值。
    :returns: 规范化后的绝对路径。
    :raises RuntimeError: 目录不存在或缺少 ``core/paper_agent`` 子目录。
    """
    root = os.path.abspath(path)
    if not os.path.isdir(root) or not os.path.isdir(os.path.join(root, _ROOT_MARKER)):
        raise RuntimeError(
            f"paper-agent_ROOT 指向的目录不存在或不是合法的项目根：{root}\n"
            "  期望：该目录下存在 core/paper_agent/ 子目录。\n"
            "  如在 AGH 场景，请在启动 daemon 的终端里重新注入该变量（"
            'env "paper-agent_ROOT=<项目绝对路径>" ...）后重启 daemon；'
            "详见 docs/AGH插件安装指南.md。"
        )
    return root


def _detect_root() -> str:
    override = os.environ.get(_ROOT_ENV)
    if override:
        return _validate_root(override)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


PAPER_AGENT_ROOT = _detect_root()
DATA_DIR = os.path.join(PAPER_AGENT_ROOT, "data")
EXPERIMENTS_DIR = os.path.join(PAPER_AGENT_ROOT, "experiments")
RUNS_DIR = os.path.join(PAPER_AGENT_ROOT, "runs")

__all__ = ["PAPER_AGENT_ROOT", "DATA_DIR", "EXPERIMENTS_DIR", "RUNS_DIR"]
