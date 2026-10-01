"""P4 复现验证器 —— 纯函数层（文档 §4.6 + 陷阱 #4）。

- 递归容差比对：支持 dict / list / 标量嵌套，规避 "== 对浮点失效"
  与 "标量 abs 相减抛 TypeError" 两类陷阱。
- 五项校验：results.csv sha256 / n_rows / top3 material_id 集合 /
  top3 score 数值(容差1e-9, 位置比对) / family_mean_log10_cond(容差1e-9)
- 输出 verification.json 结构固定
"""
from __future__ import annotations

import json
import os

DEFAULT_TOL = 1e-9


def deep_equal(expected, actual, tol: float = DEFAULT_TOL) -> tuple[bool, list[str]]:
    """深度容差比对。返回 (是否相等, 不匹配路径列表)。

    - dict: 键并集比较
    - list: 先比长度，再按位置递归比对（位置敏感，用于 top3 复现检测）
    - 数值: abs 差 <= tol
    - 其它: 值相等
    """
    mismatches: list[str] = []
    _walk(expected, actual, "", tol, mismatches)
    return (len(mismatches) == 0, mismatches)


def _walk(a, b, path: str, tol: float, out: list[str]) -> None:
    key = path if path else "<root>"
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            sub = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append(f"{sub}: missing in expected")
            elif k not in b:
                out.append(f"{sub}: missing in actual")
            else:
                _walk(a[k], b[k], sub, tol, out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{key}: list length {len(a)} != {len(b)}")
        for i in range(min(len(a), len(b))):
            _walk(a[i], b[i], f"{path}[{i}]", tol, out)
        return
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        if abs(float(a) - float(b)) > tol:
            out.append(f"{key}: {a} vs {b} (diff > {tol})")
        return
    if a != b:
        out.append(f"{key}: {a!r} vs {b!r}")


def build_checks(
    expected_sha: str,
    actual_sha: str,
    expected_summary: dict,
    actual_summary: dict,
) -> tuple[str, list[dict]]:
    """生成五项校验。返回 (status, checks)。"""
    checks: list[dict] = []

    c1 = expected_sha == actual_sha
    checks.append({
        "name": "results_csv_sha256",
        "pass": c1,
        "expected": expected_sha,
        "actual": actual_sha,
    })

    e_n = expected_summary.get("n_rows")
    a_n = actual_summary.get("n_rows")
    checks.append({
        "name": "n_rows",
        "pass": e_n == a_n,
        "expected": e_n,
        "actual": a_n,
    })

    e_ids = sorted(t.get("material_id") for t in expected_summary.get("top3", []))
    a_ids = sorted(t.get("material_id") for t in actual_summary.get("top3", []))
    checks.append({
        "name": "top3_material_id_set",
        "pass": e_ids == a_ids,
        "expected": e_ids,
        "actual": a_ids,
    })

    ok4, mm4 = deep_equal(
        expected_summary.get("top3", []),
        actual_summary.get("top3", []),
        DEFAULT_TOL,
    )
    checks.append({
        "name": "top3_scores_positional",
        "pass": ok4,
        "expected": expected_summary.get("top3", []),
        "actual": actual_summary.get("top3", []),
        "mismatch_paths": mm4,
    })

    ef = expected_summary.get("family_mean_log10_cond", {})
    af = actual_summary.get("family_mean_log10_cond", {})
    ok5, mm5 = deep_equal(ef, af, DEFAULT_TOL)
    checks.append({
        "name": "family_mean_log10_cond",
        "pass": ok5,
        "expected": ef,
        "actual": af,
        "mismatch_paths": mm5,
    })

    status = "PASS" if all(c["pass"] for c in checks) else "FAIL"
    return status, checks


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_verification(
    run_dir: str,
    status: str,
    checks: list[dict],
    rerun_results_sha256: str,
) -> str:
    vpath = os.path.join(run_dir, "verification", "verification.json")
    os.makedirs(os.path.dirname(vpath), exist_ok=True)
    doc = {
        "status": status,
        "checks": checks,
        "rerun_results_sha256": rerun_results_sha256,
    }
    with open(vpath, "w", encoding="utf-8", newline="") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return vpath
