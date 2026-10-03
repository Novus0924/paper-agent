"""sources.py — 外部数据源适配层（redesign-decisions.md D2 / D3 数据腿）。

职责边界（严格）：
- **只做"取数 + 字段映射 + 值分类"，不做语义清洗**。哪些行可以进入计算、
  如何补缺、如何标记异常，全部由 P2 决定并留痕。
- **不产生任何数值**：数值只来自外部数据集原样搬运（归一化仅为格式统一）。
- 零第三方依赖，仅标准库。

之所以单独成层：数据来源与流水线解耦后，"换数据源"不需要动状态机与计算逻辑；
同时把"列名归一"（官方 CSV 用人类可读表头、镜像用 snake_case）这类脏活集中到一处。

标准输出列（materials.csv）::

    material_id        材料标识（OBELiX 的 ID，全局唯一）
    formula            化学组成（Reduced Composition）
    family             化学族（Family，可能为空 → P2 决定如何归类）
    conductivity_Scm   电导率数值（S/cm，%.6e 定长格式化；非数值行为空）
    conductivity_raw   电导率原始写法（保留上界记法如 "<1E-10"，供留证）
    value_status       值状态：numeric | upper_bound | invalid
    space_group        空间群（用于组成无关的结构性分析）
    source_doi         原始实验论文 DOI（证据锚点）
    data_notes         数据源自带注记（可能含质量警示）
"""
from __future__ import annotations

import csv
import io
import os
import re

MATERIALS_COLUMNS = [
    "material_id", "formula", "family", "conductivity_Scm", "conductivity_raw",
    "value_status", "space_group", "source_doi", "data_notes", "in_scope",
]

#: 上界记法：以 < 开头（如 "<1E-10" / "<=1e-12"）
_UPPER_RE = re.compile(r"^\s*<")

#: OBELiX 列名映射：标准键 → 候选实际列名（规范化后比较）
_OBELIX_COLUMN_CANDIDATES = {
    "material_id": ["ID", "id"],
    "formula": ["Reduced Composition", "reduced_composition"],
    "family": ["Family", "family"],
    "cond_main": ["Ionic conductivity (S cm-1)", "ionic_conductivity_s_per_cm",
                  "ionic_conductivity_scm"],
    "cond_total": ["IC (Total)", "ic_total", "ic_total_s_per_cm"],
    "cond_bulk": ["IC (Bulk)", "ic_bulk", "ic_bulk_s_per_cm"],
    "space_group": ["Space group", "space_group"],
    "source_doi": ["DOI", "source_doi"],
    "data_notes": ["note", "notes"],
}

VALUE_NUMERIC = "numeric"
VALUE_UPPER_BOUND = "upper_bound"
VALUE_INVALID = "invalid"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def resolve_columns(fields: list[str]) -> dict[str, str | None]:
    """把标准键映射到实际列名；缺失的键值为 None。"""
    normed = {_norm(f): f for f in fields}
    out: dict[str, str | None] = {}
    for key, cands in _OBELIX_COLUMN_CANDIDATES.items():
        found = None
        for c in cands:
            n = _norm(c)
            if n in normed:
                found = normed[n]
                break
        out[key] = found
    return out


def parse_conductivity(raw: str) -> tuple[str, float | None]:
    """把原始写法分类为 (value_status, numeric_or_None)。

    - "<1E-10" → ("upper_bound", None)  上界值不是可比较的数值，绝不当作数
    - "1.58489e-06" → ("numeric", 1.58489e-06)
    - 空 / 无法解析 → ("invalid", None)
    """
    s = (raw or "").strip()
    if not s:
        return VALUE_INVALID, None
    if _UPPER_RE.match(s):
        return VALUE_UPPER_BOUND, None
    try:
        v = float(s)
    except ValueError:
        return VALUE_INVALID, None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return VALUE_INVALID, None
    if v <= 0:
        # 电导率必须为正；非正值说明数据异常，交由 P2 处理
        return VALUE_INVALID, None
    return VALUE_NUMERIC, v


def _fmt(v: float) -> str:
    """定长格式化，保证输出逐字节稳定。"""
    return f"{v:.6e}"


def _pick(row: dict, col: str | None) -> str:
    if not col:
        return ""
    return (row.get(col) or "").strip()


def map_row(row: dict, cols: dict[str, str | None]) -> dict:
    """把数据源的一行映射为标准列（不改语义）。"""
    raw = _pick(row, cols["cond_main"])
    status, num = parse_conductivity(raw)
    # 数值回落链：主列为上界/无效时，才尝试 IC(Total) / IC(Bulk)
    if status != VALUE_NUMERIC:
        for key in ("cond_total", "cond_bulk"):
            alt = _pick(row, cols[key])
            s2, n2 = parse_conductivity(alt)
            if s2 == VALUE_NUMERIC:
                status, num, raw = VALUE_NUMERIC, n2, alt
                break
    return {
        "material_id": _pick(row, cols["material_id"]),
        "formula": _pick(row, cols["formula"]),
        "family": _pick(row, cols["family"]),
        "conductivity_Scm": _fmt(num) if num is not None else "",
        "conductivity_raw": raw,
        "value_status": status,
        "space_group": _pick(row, cols["space_group"]),
        "source_doi": _pick(row, cols["source_doi"]),
        "data_notes": _pick(row, cols["data_notes"]),
        # in_scope 由冻结阶段的判断写入（数据源本身不提供），此处留空
        "in_scope": "",
    }


class SchemaError(RuntimeError):
    """输入数据不符合本适配层期望的结构（列名对不上）。"""


#: 缺这几列就无法产出有意义的标准行 —— 属于必须在边界处**响亮失败**的情形。
#:
#: 实测教训（2026-10-03）：喂入一份完全不同领域的 CSV（吸附容量，列名全不同）时，
#: 若不校验，适配层会"成功"返回 4 行全 invalid、9 列里 8 列未解析的记录，
#: 上层据此写出一个毫无意义的快照且退出码为 0 —— **静默产出垃圾**。
#: 诊断类工具（probe）仍用 strict=False，以便把"哪些列没对上"作为信息报出来。
REQUIRED_COLUMNS = ("material_id", "cond_main")


def read_obelix(path: str, strict: bool = True) -> tuple[list[dict], dict]:
    """读取 OBELiX CSV，返回 (标准行列表, 元信息)。

    strict=True（默认）时，若 ``material_id`` / ``cond_main`` 等必需列无法解析，
    立即抛 :class:`SchemaError` —— 宁可在这里响亮失败，也不要让错数据流进流水线。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"obelix dataset not found: {path}")
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        cols = resolve_columns(fields)
        rows = [map_row(r, cols) for r in reader]
    missing = [k for k in REQUIRED_COLUMNS if not cols.get(k)]
    if strict and missing:
        pretty = ", ".join(_OBELIX_COLUMN_CANDIDATES[k][0] for k in missing)
        raise SchemaError(
            f"输入数据缺少必需列，无法作为本数据集使用：{', '.join(missing)}"
            f"（期望的列名形如：{pretty}）。"
            f"实际读到的表头：{', '.join(fields) if fields else '(空)'}。"
            f"若这确实是另一个领域的数据，需要先为它写一个适配器"
            f"（见 core/paper_agent/sources.py 的映射表）。")
    return rows, {
        "source_columns": fields,
        "resolved_columns": cols,
        "unresolved_columns": [k for k, v in cols.items() if not v],
        "n_rows": len(rows),
    }


def to_materials_csv(rows: list[dict]) -> str:
    """标准行 → materials.csv 文本（UTF-8，带 BOM，字段顺序固定）。"""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=MATERIALS_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in MATERIALS_COLUMNS})
    return buf.getvalue()


def read_materials(path: str) -> list[dict]:
    """读取**标准列** materials.csv（快照数据腿的产物）。

    与 read_obelix 的区别：这里不再做列名归一，只做标准列的整行读取，
    供 P2 清洗消费。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"materials csv not found: {path}")
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [{k: (v if v is not None else "").strip()
                 for k, v in r.items()} for r in reader]


def summarize(rows: list[dict]) -> dict:
    """逐类计数（供清洗报告与审计包引用）。"""
    status: dict[str, int] = {}
    fam_empty = 0
    doi_empty = 0
    for r in rows:
        status[r["value_status"]] = status.get(r["value_status"], 0) + 1
        if not r["family"]:
            fam_empty += 1
        if not r["source_doi"]:
            doi_empty += 1
    ids = [r["material_id"] for r in rows]
    return {
        "n_rows": len(rows),
        "value_status": status,
        "family_empty": fam_empty,
        "doi_empty": doi_empty,
        "unique_material_id": len(set(ids)),
        "duplicate_material_id": len(ids) - len(set(ids)),
    }
