"""judge.py — 可插拔判断器（redesign-decisions.md D4 档 3）。

判断 = "生成检索式" + "判定哪些对象相关"。它是本项目中**唯一**允许模型参与的
环节，产出物一律为 **judgment 级**对象：影响流程走向、**不得进入结论**、
必须全额留痕（含被排除项与理由）。

两个实现（同一数据契约，可互换）：
- ``RuleJudge``  —— 可见规则式基线。规则写在本文件里，可读、可复核、可反驳。
  它同时是**反判据的对照组**：若模型判断与它的结论几乎无差异，说明模型是装饰品。
- ``ModelJudge`` —— 由外部模型驱动（本项目由 AGH 提供模型，见 D10）。
  通过注入 ``llm_client`` 实现可测：单测注入假客户端，**全程离线**。

严格校验（不用"容错"掩盖问题）：
- 模型输出必须是合法 JSON，且字段齐全、verdict 取值合法、覆盖全部待判对象；
- 校验失败先重试一次，仍失败则抛 ``JudgeError``（宁可停下，不要静默降级）；
- **原始响应全文记入 meta.raw_response**，模型身份记入 meta.model —— 判断必须可复核。
"""
from __future__ import annotations

import json
import re

QUERY_GENERATION = "query_generation"
RELEVANCE = "relevance"

VERDICT_GENERATED = "generated"
VERDICT_RELEVANT = "relevant"
VERDICT_EXCLUDED = "excluded"

RULE_IMPL = "rule"
MODEL_IMPL = "model"

STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is",
        "are", "with", "as", "at", "by", "from", "it", "its", "ranking",
        "rank", "best", "top", "which", "what"}

#: 规则式基线的化学同义词表（可复核、可反驳；模型接入后由模型替代）
FAMILY_ALIASES = {
    "sulfide": ("sulfide", "sulfides", "thio", "argyrodit", "lgps"),
    "sulphide": ("sulfide", "sulfides", "thio", "argyrodit", "lgps"),
    "oxide": ("oxide", "oxides", "garnet", "perovskit", "nasicon", "lisicon",
              "phosphate", "molybdate", "hexaoxometalate"),
    "halide": ("halide", "halides", "chloride", "chlorides", "bromide",
               "iodide"),
    "garnet": ("garnet",),
    "nasicon": ("nasicon",),
    "argyrodite": ("argyrodit",),
    "perovskite": ("perovskit",),
    "hydride": ("hydride", "hydrides"),
    "nitride": ("nitride", "nitrides"),
    "phosphate": ("phosphate", "phosphates"),
    "polymer": ("polymer",),
    "antiperovskite": ("antiperovskit",),
}


class JudgeError(RuntimeError):
    """判断器输出不合法或模型调用失败。"""


def tokenize(goal: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", (goal or "").lower())
    return [t for t in toks if t not in STOP and len(t) > 2]


def extract_json(text: str):
    """从模型输出里抽取 JSON：容忍 ```json 围栏与前后解释性文字。"""
    if text is None:
        raise JudgeError("empty model response")
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    # 退一步：取第一个平衡的 { } 或 [ ] 片段
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        i = s.find(open_ch)
        j = s.rfind(close_ch)
        if i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                continue
    raise JudgeError(f"cannot parse JSON from model response: {text[:200]!r}")


# ---------- 统一产出 ----------

def make_query_judgment(goal: str, queries: list[str], impl: str,
                        rationale: str, extra: dict | None = None) -> dict:
    meta = {"subject": goal, "verdict": VERDICT_GENERATED,
            "rationale": rationale, "queries": list(queries),
            "judge_impl": impl}
    if extra:
        meta.update(extra)
    return {"tier": "judgment", "kind": QUERY_GENERATION,
            "producer_step": "P1_lit_search", "ref": goal, "meta": meta}


def make_relevance_judgment(subject: str, verdict: str, rationale: str,
                            impl: str, axis: str = "material_family",
                            extra: dict | None = None) -> dict:
    if verdict not in (VERDICT_RELEVANT, VERDICT_EXCLUDED):
        raise JudgeError(f"invalid verdict: {verdict!r}")
    meta = {"subject": subject, "verdict": verdict, "rationale": rationale,
            "axis": axis, "judge_impl": impl}
    if extra:
        meta.update(extra)
    return {"tier": "judgment", "kind": RELEVANCE,
            "producer_step": "P1_lit_search", "ref": subject or "(empty)",
            "meta": meta}


def normalize_family(name) -> str:
    """把展示用的占位串还原成机器键（空族名统一为 ""）。

    ``meta.subject`` 始终是**原始族名**（机器键）；人类可读的 "(empty)" 只出现在 ``ref``。
    这样 scope 映射与数据行的 family 列永远能对上。
    """
    s = (name or "").strip()
    return "" if s in ("(empty)", "（空）", "") else s


def scope_from_judgments(judgments: list[dict]) -> dict[str, str]:
    """从相关性判断里取回 subject → verdict 映射。"""
    out: dict[str, str] = {}
    for j in judgments or []:
        if j.get("kind") != RELEVANCE:
            continue
        m = j.get("meta") or {}
        out[normalize_family(m.get("subject", ""))] = m.get("verdict", "")
    return out


# ---------- 规则式基线 ----------

class RuleJudge:
    """可见规则式判断器：既是默认实现，也是反判据的对照组。"""

    impl = RULE_IMPL

    def generate_queries(self, goal: str) -> list[str]:
        toks = tokenize(goal)
        if not toks:
            return [goal.strip()] if (goal or "").strip() else []
        out = [" ".join(toks)]
        if len(toks) > 2:
            out.append(" ".join(toks[:2]))
        return out

    def judge_families(self, goal: str, families: list[str]) -> list[dict]:
        toks = tokenize(goal)
        out = []
        for fam in sorted(families):
            if not fam:
                out.append(make_relevance_judgment(
                    "", VERDICT_EXCLUDED,
                    "源数据家族字段为空，无法判定主题归属", self.impl))
                continue
            verdict, why = VERDICT_EXCLUDED, f"家族名未匹配目标关键词（{', '.join(toks)}）"
            low = fam.lower()
            for t in toks:
                hit = next((c for c in FAMILY_ALIASES.get(t, (t,)) if c in low), None)
                if hit:
                    verdict = VERDICT_RELEVANT
                    why = f"家族名含关键词 {t!r} 的同义词 {hit!r}"
                    break
            out.append(make_relevance_judgment(fam, verdict, why, self.impl))
        return out

    def judge(self, goal: str, families: list[str]) -> tuple[list[dict], dict[str, str]]:
        queries = self.generate_queries(goal)
        judgments = [make_query_judgment(
            goal, queries, self.impl,
            f"规则式拆词（{RULE_IMPL}，非模型判断）：去停用词后取关键词")]
        judgments += self.judge_families(goal, families)
        return judgments, scope_from_judgments(judgments)


# ---------- 模型判断器 ----------

_QUERY_PROMPT = """你是科研检索助手。请把下面的科研目标拆成 1-4 条英文检索式，
用于在 Crossref / OpenAlex 的元数据接口上检索论文。

科研目标：{goal}

只输出 JSON 数组，元素为字符串，不要任何解释或 Markdown 围栏。例如：
["sulfide solid electrolyte ionic conductivity", "argyrodite ionic conductivity"]
"""

_RELEVANCE_PROMPT = """你是材料科学文献助手。下面是一个科研目标和一批材料"化学族"名称。
请判断每个族是否属于该目标的研究范围，并给出一句中文理由。

科研目标：{goal}

待判族（共 {n} 个）：
{items}

只输出 JSON 数组，每个元素形如：
{{"family": "族名", "verdict": "relevant" 或 "excluded", "reason": "中文理由"}}
必须覆盖全部 {n} 个族，且 verdict 只能是 relevant 或 excluded。
不要输出任何解释或 Markdown 围栏。
"""


class ModelJudge:
    """由模型驱动的判断器。``llm_client`` 需实现 ``complete(prompt) -> str``。"""

    impl = MODEL_IMPL

    def __init__(self, llm_client, model_name: str = "", retries: int = 1):
        if llm_client is None:
            raise JudgeError("ModelJudge requires an llm_client")
        self.client = llm_client
        self.model_name = model_name or getattr(llm_client, "name", "unknown")
        self.retries = retries

    # ---- 内部：带校验与重试的模型调用 ----

    def _complete_json(self, prompt: str, validator) -> tuple[object, str]:
        last = None
        raw = ""
        for attempt in range(self.retries + 1):
            raw = self.client.complete(prompt)
            try:
                data = extract_json(raw)
                validator(data)
                return data, raw
            except (JudgeError, ValueError) as e:
                last = e
        raise JudgeError(f"model output invalid after {self.retries + 1} attempt(s): "
                         f"{last}; raw={raw[:300]!r}")

    # ---- 对外 ----

    def generate_queries(self, goal: str) -> list[str]:
        def _validate(d):
            if not isinstance(d, list) or not d:
                raise JudgeError("expected non-empty JSON array of strings")
            if not all(isinstance(x, str) and x.strip() for x in d):
                raise JudgeError("array items must be non-empty strings")
        data, _ = self._complete_json(_QUERY_PROMPT.format(goal=goal), _validate)
        out, seen = [], set()
        for q in data:
            q = q.strip()
            if q and q not in seen:
                seen.add(q)
                out.append(q)
        return out

    def judge_families(self, goal: str, families: list[str]) -> list[dict]:
        fams = sorted(families)
        items = "\n".join(f"- {f or '(empty)'}" for f in fams)
        prompt = _RELEVANCE_PROMPT.format(goal=goal, n=len(fams), items=items)

        def _validate(d):
            if not isinstance(d, list):
                raise JudgeError("expected JSON array")
            got = set()
            for e in d:
                if not isinstance(e, dict):
                    raise JudgeError("array items must be objects")
                if e.get("verdict") not in (VERDICT_RELEVANT, VERDICT_EXCLUDED):
                    raise JudgeError(f"bad verdict: {e.get('verdict')!r}")
                got.add(normalize_family(e.get("family", "")))
            missing = set(fams) - got
            if missing:
                raise JudgeError(f"model missed {len(missing)} families, "
                                 f"e.g. {sorted(missing)[:3]}")

        data, raw = self._complete_json(prompt, _validate)
        out = []
        for e in data:
            fam = normalize_family(e.get("family", ""))
            out.append(make_relevance_judgment(
                fam, e["verdict"],
                (e.get("reason") or "").strip() or "(模型未给理由)",
                self.impl, extra={"model": self.model_name,
                                  "raw_response": raw}))
        out.sort(key=lambda j: j["meta"]["subject"])
        return out

    def judge(self, goal: str, families: list[str]) -> tuple[list[dict], dict[str, str]]:
        queries = self.generate_queries(goal)
        judgments = [make_query_judgment(
            goal, queries, self.impl,
            f"由模型生成检索式（model={self.model_name}）",
            extra={"model": self.model_name})]
        judgments += self.judge_families(goal, families)
        return judgments, scope_from_judgments(judgments)


# ---------- 工厂 ----------

def build(impl: str, llm_client=None, model_name: str = ""):
    if impl == RULE_IMPL:
        return RuleJudge()
    if impl == MODEL_IMPL:
        return ModelJudge(llm_client, model_name=model_name)
    raise JudgeError(f"unknown judge impl: {impl!r}")


# ---------- 反判据对比 ----------

def compare_judges(goal: str, families: list[str], judge_a, judge_b,
                   label_a: str = "", label_b: str = "") -> dict:
    """对比两个判断器的产出，用于**反判据**检验（redesign 判据 2 的反面）。

    反判据：把模型换回固定规则，如果**结论几乎不变** → 说明模型是装饰品。

    这里把"结论"落到两个可观测面：**生成的检索式**与**判定出的范围**。
    两者都完全一致时判定为 model_is_decoration。
    """
    ja, sa = judge_a.judge(goal, families)
    jb, sb = judge_b.judge(goal, families)

    qa = next((x["meta"].get("queries") or [] for x in ja
               if x["kind"] == QUERY_GENERATION), [])
    qb = next((x["meta"].get("queries") or [] for x in jb
               if x["kind"] == QUERY_GENERATION), [])
    sa_n = {k: v for k, v in sa.items() if v == VERDICT_RELEVANT}
    sb_n = {k: v for k, v in sb.items() if v == VERDICT_RELEVANT}

    qu = set(qa) | set(qb)
    queries_identical = set(qa) == set(qb) == qu
    # 翻转项用**稳定键 a/b**（不随标签变化，避免两个标签同名时互相覆盖）
    flips = sorted(
        ({"family": f, "a": sa.get(f), "b": sb.get(f)}
         for f in (set(sa) | set(sb)) if sa.get(f) != sb.get(f)),
        key=lambda x: x["family"])

    identical = queries_identical and not flips
    return {
        "goal": goal,
        "labels": {"a": label_a or "a", "b": label_b or "b"},
        "a": {"impl": getattr(judge_a, "impl", "?"), "queries": list(qa),
              "n_relevant": len(sa_n), "n_subjects": len(sa)},
        "b": {"impl": getattr(judge_b, "impl", "?"), "queries": list(qb),
              "n_relevant": len(sb_n), "n_subjects": len(sb)},
        "queries_identical": queries_identical,
        "queries_only_a": sorted(set(qa) - set(qb)),
        "queries_only_b": sorted(set(qb) - set(qa)),
        "scope_identical": not flips,
        "n_flips": len(flips),
        "flips": flips,
        "model_changes_outcome": not identical,
        "verdict": "model_matters" if not identical else "model_is_decoration",
    }
