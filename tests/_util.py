"""tests 共享工具：构建隔离的临时项目根（含 data/ 与 experiments/）。

单元测试绝不写项目真实 runs/，全部在临时目录内完成，
并通过设置 paper-agent_ROOT 环境变量指向临时根，保证可复现、互不污染。
"""
from __future__ import annotations

import os
import shutil
import sys

# 让测试能 import paper_agent（core 目录加入 sys.path）
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE = os.path.join(_PROJECT_ROOT, "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def project_root() -> str:
    return _PROJECT_ROOT


def build_temp_root(tmp: str) -> str:
    """把项目的 data/ 与 experiments/ 拷入 tmp，作为隔离根。"""
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
    # 指向临时根
    os.environ["paper-agent_ROOT"] = tmp
    paper_agent.PAPER_AGENT_ROOT = tmp
    paper_agent.DATA_DIR = dst_data
    paper_agent.EXPERIMENTS_DIR = dst_exp
    paper_agent.RUNS_DIR = os.path.join(tmp, "runs")
    return tmp


def make_clean_csv(tmp: str) -> str:
    """构造一份含多家族、多行、含 tie 情形的干净 CSV，供实验脚本调用。"""
    import csv
    p = os.path.join(tmp, "clean_for_repro.csv")
    cols = ["material_id", "formula", "family", "conductivity_Scm",
            "activation_energy_eV", "year", "source_doi"]
    rows = [
        ["M001", "LGPS", "sulfide", "1.2e-2", "0.40", "2011", "10.1038/nmat3006"],
        ["M002", "Li9.54Si1.74P1.44S11.7Cl0.3", "sulfide", "2.5e-2", "0.45", "2011", "10.1038/nmat3006"],
        ["M003", "LLZO", "garnet", "3.0e-4", "0.95", "2007", "10.1002/anie.200701144"],
        ["M004", "LiPON", "thin_film", "2.0e-6", "0.25", "1992", "10.1016/0167-2738(92)90421-F"],
        ["M005", "Li6PS5Cl", "argyrodite", "4.4e-4", "0.55", "2008", "10.1002/anie.200800627"],
        ["M007", "LLZO", "garnet", "2.0e-4", "0.95", "2016", "10.1038/nenergy.2016.030"],
    ]
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return p
