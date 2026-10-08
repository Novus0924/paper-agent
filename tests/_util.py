"""tests 共享工具：构建隔离的临时项目根（含 data/ 与experiments/）。

单元测试绝不写项目真实 runs/，全部在临时目录内完成，
并通过设置 paper-agent_ROOT 环境变量指向临时根，保证可复现、互不污染。

⚠️ 隔离的关键：``build_temp_root()`` 会改**四个进程级全局量**
（``os.environ["paper-agent_ROOT"]`` + ``paper_agent`` 的
``PAPER_AGENT_ROOT`` / ``DATA_DIR`` / ``EXPERIMENTS_DIR`` / ``RUNS_DIR``）。
只设不还原会造成**测试间污染**：后跑的用例会读到上一个用例留下的临时根，
而那个目录可能已被 ``tearDown`` 删掉→ 表现为**偶发**的
``AssertionError: True is not false`` 之类断言失败（flaky）。

因此**请一律用** ``isolate_temp_root()``（自动还原，推荐），
或手动调 ``build_temp_root()`` 后紧跟 ``restore_globals()``。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

# 让测试能 import paper_agent（core 目录加入 sys.path）
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE = os.path.join(_PROJECT_ROOT, "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

# 被 build_temp_root 改动的全局量名字（用于保存/还原）
_ENV_KEY = "paper-agent_ROOT"
_GLOBALS = ("PAPER_AGENT_ROOT", "DATA_DIR", "EXPERIMENTS_DIR", "RUNS_DIR")


def project_root() -> str:
    return _PROJECT_ROOT


def _snapshot_globals():
    """记录当前全局量取值（只在该变量已存在时记，缺失则记None）。"""
    import paper_agent
    env = os.environ.get(_ENV_KEY)
    saved = {name: getattr(paper_agent, name, None) for name in _GLOBALS}
    return env, saved


def _restore_globals(env, saved):
    """把全局量还原到快照状态。"""
    import paper_agent
    if env is None:
        os.environ.pop(_ENV_KEY, None)
    else:
        os.environ[_ENV_KEY] = env
    for name, value in saved.items():
        if value is not None:
            setattr(paper_agent, name, value)


def build_temp_root(tmp: str) -> str:
    """把项目的 data/ 与 experiments/ 拷入 tmp，作为隔离根。

    ⚠️ 调用方**必须**还原全局量，否则污染同进程内的后续测试。
    优先改用 :func:`isolate_temp_root`。
    """
    import paper_agent
    src_data = os.path.join(_PROJECT_ROOT, "data")
    src_exp = os.path.join(_PROJECT_ROOT, "experiments")
    dst_data = os.path.join(tmp, "data")
    dst_exp = os.path.join(tmp, "experiments")
    if os.path.isdir(src_data):
        shutil.copytree(src_data, dst_data)
    else:
        os.makedirs(dst_data, exist_ok=True)
    if os.path.isdir(src_exp):
        shutil.copytree(src_exp, dst_exp)
    else:
        os.makedirs(dst_exp, exist_ok=True)
    os.makedirs(os.path.join(tmp, "runs"), exist_ok=True)
    # 隔离根也必须是一个「合法项目根」：子进程（如 E2/E3 崩溃用例）会以
    # paper-agent_ROOT=<tmp> 重新 import paper_agent，而 __init__ 现在会校验
    # core/paper_agent 子目录存在（P0-2）。故镜像一个空的包标记目录。
    os.makedirs(os.path.join(tmp, "core", "paper_agent"), exist_ok=True)
    # 指向临时根
    os.environ[_ENV_KEY] = tmp
    paper_agent.PAPER_AGENT_ROOT = tmp
    paper_agent.DATA_DIR = dst_data
    paper_agent.EXPERIMENTS_DIR = dst_exp
    paper_agent.RUNS_DIR = os.path.join(tmp, "runs")
    return tmp


def restore_globals() -> None:
    """还原到**项目真实根**。

    供 tearDown 兜底调用：把全局量指回仓库真实路径与真实 data/，
    避免"上一个临时目录已被删、后续用例还在往里写"的情况。
    """
    import paper_agent
    os.environ[_ENV_KEY] = _PROJECT_ROOT
    paper_agent.PAPER_AGENT_ROOT = _PROJECT_ROOT
    paper_agent.DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
    paper_agent.EXPERIMENTS_DIR = os.path.join(_PROJECT_ROOT, "experiments")
    paper_agent.RUNS_DIR = os.path.join(_PROJECT_ROOT, "runs")


def isolate_temp_root(case, prefix: str = "pa_") -> str:
    """给 unittest 用例建隔离临时根，并**自动注册清理**。

    这是推荐入口：既建目录，又保证 tearDown 时
    ①还原全局量 ②删除临时目录 —— 即使用例中途抛异常也不会留下污染。

    ⚠️ ``addCleanup`` 是 **LIFO**（后进先出）执行，所以注册顺序要讲究：
    先注册"删目录"、再注册"还原全局量"→ 实际执行时
    **先还原全局量、后删目录**。这个顺序才对：还原时若还要读目录也不受影响，
    且万一删目录失败，全局量也已经回到安全状态。

    兼容性：仍会设置 ``case._tmp``，因为多个测试用 ``self._tmp`` 拼装
    自己的样本文件路径（历史写法，保留以免大面积改动）。

    用法::

        def setUp(self):
            self.root = isolate_temp_root(self, "pa_prov_")
    """
    # ⚠️ 快照必须在 build_temp_root 改写全局量**之前**取
    env, saved = _snapshot_globals()
    tmp = tempfile.mkdtemp(prefix=prefix)
    try:
        root = build_temp_root(tmp)
    except Exception:
        # 建根失败也别留下半改的状态
        _restore_globals(env, saved)
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    case._tmp = tmp          # 兼容历史写法：self._tmp 拼样本文件路径
    case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    case.addCleanup(_restore_globals, env, saved)
    return root



def make_clean_csv(tmp: str) -> str:
    """构造一份含多家族、多行、含 tie 情形的干净 CSV，供实验脚本调用。"""
    import csv
    p = os.path.join(tmp, "clean_for_repro.csv")
    cols = ["material_id", "formula", "family", "conductivity_Scm",
            "activation_energy_eV", "year", "source_doi"]
    rows = [
        ["M001", "LGPS", "sulfide", "1.2e-2", "0.40", "2011", "10.1038/nmat3066"],
        ["M002", "Li9.54Si1.74P1.44S11.7Cl0.3", "sulfide", "2.5e-2", "0.45", "2016", "10.1038/nenergy.2016.30"],
        ["M003", "LLZO", "garnet", "3.0e-4", "0.95", "2007", "10.1002/anie.200701144"],
        ["M004", "LiPON", "thin_film", "2.0e-6", "0.25", "1992", "10.1016/0167-2738(92)90421-F"],
        ["M005", "Li6PS5Cl", "argyrodite", "4.4e-4", "0.55", "2008", "10.1002/anie.200800627"],
        ["M007", "LLZO", "garnet", "2.0e-4", "0.95", "2007", "10.1002/anie.200701144"],
    ]
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return p
