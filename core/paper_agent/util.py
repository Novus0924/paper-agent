"""util.py — 跨模块共享的文件 IO / 哈希工具。

背景（可维护性整改）：``_sha256_file`` 曾在 steps / research / snapshot /
provenance / materials_snapshot / arrhenius_rank 六处各有一份拷贝，
``_write_json`` 三份、JSON 读取三种变体——同一逻辑多处维护，修一处漏五处。
本模块收敛为唯一实现，各业务模块统一 import。

设计约束：
- 仅标准库、零第三方依赖（与 core 整体约束一致）；
- 不 import 本包其他模块（避免循环依赖）；
- ``experiments/arrhenius_rank.py`` 除外——它是经 subprocess 独立调用的
  确定性实验脚本，必须保持自包含，故保留自身拷贝（见其模块 docstring）。

异常语义：
- ``read_json``：严格模式，文件缺失抛 ``FileNotFoundError``；
- ``read_json_or``：容错模式，文件缺失返回 default（缺省 ``{}``）；
- ``sha256_file``：不做存在性预检，缺失自然抛 ``FileNotFoundError``；
  provenance 需要域错误类型，故在其模块内保留薄包装。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os


def sha256_file(path: str) -> str:
    """流式计算文件 SHA-256（64KB 分块，兼容大文件）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: str, obj) -> None:
    """JSON 落盘：自动建父目录；utf-8、ensure_ascii=False、sort_keys、尾换行。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def write_text(path: str, text: str) -> None:
    """文本落盘：自动建父目录；utf-8。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    """CSV 落盘：utf-8-sig（带 BOM，Excel 直接打开不乱码），DictWriter 行写入。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_json(path: str):
    """严格 JSON 读取；缺失即抛 FileNotFoundError（语义由调用方决定）。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_json_or(path: str, default=None):
    """容错 JSON 读取：文件不存在返回 default（缺省 ``{}``），存在则解析。"""
    if not os.path.exists(path):
        return {} if default is None else default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
