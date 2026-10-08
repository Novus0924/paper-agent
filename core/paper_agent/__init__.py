"""paper_agent — 科研 Agent 流水线核心包。

工程决策记录：文档目标态写作 ``core/paper‑agent``，但 Python 顶层包名必须是
合法标识符（连字符 U+002D / 全角 U+2011 均不合法），故采用下划线命名
``core/paper_agent``，CLI 通过 ``python -m paper_agent.cli`` 调用。

本包提供统一的根路径探测，供所有子模块引用项目根目录下的 data/ 与
experiments/ 等静态资源，避免依赖当前工作目录。
"""
from __future__ import annotations

import os
import sys

# 核心包位于 <root>/core/paper_agent/，故根目录为两个层级之上。
# 项目根可通过环境变量覆盖（merge 融合：双名兼容 + 合法性校验 + 回退不崩溃）：
#   - PAPER_AGENT_ROOT（标准命名，bash 可直接 export/unset）——优先级更高；
#   - paper-agent_ROOT（AGH 插件层历史注入名，保留兼容；含连字符，
#     bash 无法 export/unset，仅可由宿主进程以 env 前缀注入）。
_ROOT_ENV = "paper-agent_ROOT"
_ROOT_ENV_STD = "PAPER_AGENT_ROOT"
# 校验标记：一个合法的项目根必须包含该子目录（core/paper_agent）。
_ROOT_MARKER = os.path.join("core", "paper_agent")


def _is_valid_root(path: str) -> bool:
    """路径是否为合法项目根（存在且含 ``core/paper_agent/`` 子目录）。"""
    return bool(path) and os.path.isdir(os.path.join(os.path.abspath(path), _ROOT_MARKER))


def _root_override() -> str:
    """读环境变量覆盖（双名兼容）：标准名优先，历史名兜底；未设置返回 ""。"""
    return os.environ.get(_ROOT_ENV_STD) or os.environ.get(_ROOT_ENV, "")


def _root_env_problem() -> str:
    """若任一根环境变量被设成非法目录，返回人话说明；否则返回 ""。

    仅在"变量已设置但指向非法目录"时非空。用于把环境变量契约问题**显式**承载出来，
    供 ``cli doctor`` / ``demo-kit/health-check`` 展示（不静默、不误导）。
    """
    raw = _root_override()
    if raw and not _is_valid_root(raw):
        return (
            f"项目根环境变量指向的目录不存在或不是合法的项目根：{raw}\n"
            "  期望：该目录下存在 core/paper_agent/ 子目录。\n"
            "  当前已自动回退到探测到的项目根，命令仍可运行；\n"
            "  但 daemon 侧的环境变量仍需修正：在启动 daemon 的终端里重新注入 "
            '（env "paper-agent_ROOT=<项目绝对路径>" ...）后重启 daemon；'
            "详见 docs/AGH插件安装指南.md。"
        )
    return ""


# 环境变量契约问题（"" 表示正常）。模块级常量，供 cli/external 读取。
ROOT_ENV_PROBLEM = _root_env_problem()


def _detect_root() -> str:
    """解析项目根。

    融合（Batch 4 merge）：
    - **双名兼容**（origin/leyon）：标准名 ``PAPER_AGENT_ROOT`` 优先、
      历史名 ``paper-agent_ROOT`` 兜底；
    - **导入期不抛异常**（HEAD 修订）：``paper-agent`` 是诸多诊断/演示工具的
      最底层依赖，导入期崩溃会让 ``cli doctor``、``health-check`` 这类
      "带病也要能跑"的诊断入口一并失效（表现为一大段 traceback）。
    现策略：override 合法则采用；**非法则回退到基于本包位置的自动探测根**，
    问题由 ``ROOT_ENV_PROBLEM`` 承载 + 模块级（本文件下方）向 stderr 播报
    **一次**警告。既不静默指向错误的 ``RUNS_DIR``（回退到的一定是"代码实际
    所在的那个仓库"，即真正正确的根），又保证任何命令在污染环境下都能运行
    并给出人话诊断。
    """
    override = _root_override()
    if override and _is_valid_root(override):
        return os.path.abspath(override)
    # 非法覆盖：不静默采用（会指向错误的 RUNS_DIR），也不崩溃（诊断入口要能跑），
    # 回退到"代码实际所在仓库"；警告由模块级 ROOT_ENV_PROBLEM 分支统一播报
    # （MAINT 收官：删除本函数内的一次重复 print，避免同一问题警告两遍）。
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


PAPER_AGENT_ROOT = _detect_root()
DATA_DIR = os.path.join(PAPER_AGENT_ROOT, "data")
EXPERIMENTS_DIR = os.path.join(PAPER_AGENT_ROOT, "experiments")
RUNS_DIR = os.path.join(PAPER_AGENT_ROOT, "runs")

if ROOT_ENV_PROBLEM:
    # 一行警告到 stderr（stdout 仍只给机器可读的 JSON，互不干扰）。
    print(
        "[paper-agent] 警告：根环境变量（PAPER_AGENT_ROOT / paper-agent_ROOT）指向非法目录，"
        "已回退到自动探测根（命令可继续运行）。运行 `python -m paper_agent.cli doctor` 查看修复指引。",
        file=sys.stderr,
    )

__all__ = [
    "PAPER_AGENT_ROOT",
    "DATA_DIR",
    "EXPERIMENTS_DIR",
    "RUNS_DIR",
    "ROOT_ENV_PROBLEM",
    "_is_valid_root",
    "_root_override",
]
