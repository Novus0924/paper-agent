"""security_scan.py — 攻击面检测与输入校验（防御提升模块）。

针对上一轮攻击者审计（paper-agent-integ）暴露的判定条件，提供两类能力：

1. **run_id 强校验（H1 路径穿越防御）**
   攻击者判定条件 H1：``run_id`` 来自不可信输入（LLM 工具参数），若未规范化即拼进
   ``os.path.join``，可借 ``../../`` 或绝对路径穿越 ``runs/`` 写/读任意文件。
   本模块用严格白名单正则 + ``realpath`` 容器检查双重保险阻断。

2. **提示注入启发式检测（M1 检测能力）**
   外部文献（arXiv / Semantic Scholar / OpenAlex / CrossRef）/ PDF 解析内容未经隔离即
   回流 LLM 上下文。本模块对文本内容做保守、低误报的指令式短语 / 工具名提及扫描，
   命中即在证据账本留痕，供人工闸门复核（检测能力，而非自动拦截）。
"""
from __future__ import annotations

import os
import re

# run_id 严格格式：run-<UTC时间戳>-<hex>，仅含字母数字、连字符、下划线。
# 不含任何路径分隔符（/ 或 \\）、不含盘符、不含前导点。
RUN_ID_RE = re.compile(r"^run-[\w\-]+$")
_RUNS_DIRNAME = "runs"

# 提示注入启发式（保守、低误报）。命中任一项即标记为潜在注入。
# 顺序即匹配优先级，标签用于账本留痕与审计。
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
     "ignore-instructions"),
    (re.compile(r"disregard\s+(the\s+)?(above|previous)", re.I), "disregard"),
    (re.compile(r"you\s+are\s+now\s+", re.I), "role-swap"),
    (re.compile(r"\bsciret_\w+", re.I), "tool-name-mention"),
    (re.compile(r"\b(call|invoke|run|execute)\s+(the\s+)?(sciret|tool|command)", re.I),
     "tool-invocation"),
    (re.compile(r"system\s*[:\-]\s*(prompt|message|instruction)", re.I), "system-injection"),
    (re.compile(r"print\s+this\s+to\s+(the\s+)?user", re.I), "exfil-instruction"),
    (re.compile(r"exfiltrat", re.I), "exfiltration"),
    (re.compile(r"bypass\s+(the\s+)?(security|guard|check|verif)", re.I), "bypass"),
]


def validate_run_id(run_id: str) -> str:
    """校验 run_id；非法（含路径分隔符 / 绝对路径 / 越界字符）即抛 ``ValueError``。

    防御 H1：run_id 一旦含 ``../`` 或绝对路径即可穿越 ``runs/``。严格白名单已排除
    ``/`` ``\\`` ``.`` 等所有可用于穿越的字符；即便未来放宽正则，``safe_runs_path``
    的 ``realpath`` 容器检查仍兜底。
    """
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"invalid run_id: empty or non-string ({run_id!r})")
    if not RUN_ID_RE.match(run_id):
        raise ValueError(
            f"invalid run_id {run_id!r}: must match ^run-[\\w-]+$ "
            f"(no path separators / absolute paths allowed)")
    return run_id


def safe_runs_path(root: str, run_id: str, *sub: str) -> str:
    """返回 ``runs/<run_id>[/...sub]`` 的规范绝对路径，并保证其位于 ``root/runs`` 内。

    即使 run_id 侥幸绕过正则（如未来改动），``realpath`` 容器检查仍兜底拦截越界。
    """
    validate_run_id(run_id)
    base = os.path.realpath(os.path.join(root, _RUNS_DIRNAME))
    target = os.path.realpath(os.path.join(base, run_id, *sub))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError(f"run_id {run_id!r} escapes runs directory: {target}")
    return target


def detect_prompt_injection(text: str) -> list[str]:
    """对外部内容做提示注入启发式检测，返回命中的标签列表（空列表 = 未命中）。"""
    if not text:
        return []
    hits: list[str] = []
    for pat, label in _INJECTION_PATTERNS:
        if pat.search(text):
            hits.append(label)
    # 保序去重
    seen: set[str] = set()
    return [h for h in hits if not (h in seen or seen.add(h))]


__all__ = ["RUN_ID_RE", "validate_run_id", "safe_runs_path", "detect_prompt_injection"]
