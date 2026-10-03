"""test_judge.py — 可插拔判断器：规则式基线 / 模型判断 / 严格校验。

模型判断器通过注入假客户端测试，**全程离线**。
"""
import json
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)

from paper_agent import judge as J  # noqa: E402

FAMILIES = ["LGPS", "NASICON", "argyrodites", "garnet", "unknown", ""]


class FakeClient:
    """假模型客户端：按顺序吐出预设响应，并记录收到的 prompt。"""

    name = "fake-model-v1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else ""


class TestExtractJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(J.extract_json('["a"]'), ["a"])

    def test_fenced(self):
        self.assertEqual(J.extract_json('```json\n["a"]\n```'), ["a"])

    def test_fenced_without_lang(self):
        self.assertEqual(J.extract_json('```\n{"k":1}\n```'), {"k": 1})

    def test_prose_around(self):
        text = '好的，结果如下：\n["a","b"]\n以上。'
        self.assertEqual(J.extract_json(text), ["a", "b"])

    def test_invalid_raises(self):
        for bad in ("", "no json here", None):
            with self.assertRaises(J.JudgeError):
                J.extract_json(bad)


class TestRuleJudge(unittest.TestCase):
    def setUp(self):
        self.j = J.RuleJudge()

    def test_generate_queries_deterministic(self):
        q1 = self.j.generate_queries("sulfide solid electrolyte ranking")
        q2 = self.j.generate_queries("sulfide solid electrolyte ranking")
        self.assertEqual(q1, q2)
        self.assertTrue(q1)
        self.assertIn("sulfide", q1[0])

    def test_different_goals_give_different_queries(self):
        a = self.j.generate_queries("sulfide solid electrolyte conductivity")
        b = self.j.generate_queries("garnet oxide interface resistance")
        self.assertNotEqual(a, b)

    def test_family_verdicts(self):
        js = {x["meta"]["subject"]: x["meta"]["verdict"]
              for x in self.j.judge_families("sulfide solid electrolyte", FAMILIES)}
        self.assertEqual(js["LGPS"], "relevant")          # lgps 别名
        self.assertEqual(js["argyrodites"], "relevant")    # argyrodit 别名
        self.assertEqual(js["NASICON"], "excluded")
        self.assertEqual(js["unknown"], "excluded")
        # 机器键用原始族名（空族名为 ""），人类可读占位只在 ref 里
        self.assertEqual(js[""], "excluded")
        empty = [x for x in self.j.judge_families("sulfide", FAMILIES)
                 if x["meta"]["subject"] == ""][0]
        self.assertEqual(empty["ref"], "(empty)")
        self.assertIn("为空", empty["meta"]["rationale"])

    def test_judge_returns_scope_and_judgments(self):
        judgments, scope = self.j.judge("sulfide solid electrolyte", FAMILIES)
        self.assertEqual(judgments[0]["kind"], J.QUERY_GENERATION)
        self.assertTrue(all(x["tier"] == "judgment" for x in judgments))
        self.assertEqual(scope["LGPS"], "relevant")
        self.assertEqual(len(judgments), 1 + len(FAMILIES))

    def test_impl_recorded(self):
        judgments, _ = self.j.judge("sulfide", ["LGPS"])
        self.assertTrue(all(x["meta"]["judge_impl"] == J.RULE_IMPL
                            for x in judgments))

    def test_deterministic_output(self):
        a, _ = self.j.judge("sulfide solid electrolyte", FAMILIES)
        b, _ = self.j.judge("sulfide solid electrolyte", FAMILIES)
        self.assertEqual(a, b)


class TestModelJudge(unittest.TestCase):
    QUERIES_JSON = '["sulfide solid electrolyte ionic conductivity", "LGPS conductivity"]'

    @staticmethod
    def _rel_json(verdicts):
        return json.dumps([
            {"family": f, "verdict": verdicts.get(f, "excluded"), "reason": f"理由-{f}"}
            for f in FAMILIES])

    def _judge(self, responses, families=FAMILIES, retries=1):
        client = FakeClient(responses)
        j = J.ModelJudge(client, model_name="fake-model-v1", retries=retries)
        return j, client

    def test_happy_path(self):
        verdicts = {"LGPS": "relevant", "argyrodites": "relevant"}
        j, client = self._judge([self.QUERIES_JSON, self._rel_json(verdicts)])
        judgments, scope = j.judge("sulfide solid electrolyte", FAMILIES)
        self.assertEqual(scope["LGPS"], "relevant")
        self.assertEqual(scope["NASICON"], "excluded")
        self.assertEqual(judgments[0]["kind"], J.QUERY_GENERATION)
        self.assertEqual(len(client.prompts), 2)

    def test_model_and_raw_response_recorded(self):
        j, _ = self._judge([self.QUERIES_JSON, self._rel_json({"LGPS": "relevant"})])
        judgments, _ = j.judge("sulfide", FAMILIES)
        rel = [x for x in judgments if x["kind"] == J.RELEVANCE]
        self.assertTrue(all(x["meta"]["model"] == "fake-model-v1" for x in rel))
        self.assertTrue(all(x["meta"]["raw_response"] for x in rel))
        self.assertEqual(judgments[0]["meta"]["judge_impl"], J.MODEL_IMPL)

    def test_retry_on_bad_json_then_success(self):
        verdicts = {"LGPS": "relevant"}
        j, client = self._judge(["not json at all",
                                 self.QUERIES_JSON,
                                 self._rel_json(verdicts)])
        judgments, _ = j.judge("sulfide", FAMILIES)
        self.assertIn("LGPS", [x["meta"]["subject"] for x in judgments])
        self.assertEqual(len(client.prompts), 3)

    def test_raises_after_retries_exhausted(self):
        j, _ = self._judge(["garbage", "garbage"], retries=1)
        with self.assertRaises(J.JudgeError):
            j.judge("sulfide", FAMILIES)

    def test_rejects_incomplete_coverage(self):
        """模型漏判某个族 → 必须报错，不得静默接受。"""
        partial = json.dumps([{"family": "LGPS", "verdict": "relevant",
                               "reason": "r"}])
        j, _ = self._judge([self.QUERIES_JSON, partial, partial], retries=1)
        with self.assertRaises(J.JudgeError) as cm:
            j.judge("sulfide", FAMILIES)
        self.assertIn("missed", str(cm.exception))

    def test_rejects_invalid_verdict(self):
        bad = json.dumps([{"family": f, "verdict": "maybe", "reason": "r"}
                          for f in FAMILIES])
        j, _ = self._judge([self.QUERIES_JSON, bad, bad], retries=1)
        with self.assertRaises(J.JudgeError):
            j.judge("sulfide", FAMILIES)

    def test_rejects_empty_query_array(self):
        j, _ = self._judge(["[]", "[]"], retries=1)
        with self.assertRaises(J.JudgeError):
            j.generate_queries("sulfide")

    def test_queries_deduped(self):
        dup = '["a b", "a b", "c d"]'
        j, _ = self._judge([dup, self._rel_json({})])
        self.assertEqual(j.generate_queries("x"), ["a b", "c d"])

    def test_missing_reason_becomes_placeholder(self):
        payload = json.dumps([{"family": f, "verdict": "excluded"} for f in FAMILIES])
        j, _ = self._judge([self.QUERIES_JSON, payload])
        judgments, _ = j.judge("sulfide", FAMILIES)
        rel = [x for x in judgments if x["kind"] == J.RELEVANCE]
        self.assertTrue(all(x["meta"]["rationale"] for x in rel))

    def test_requires_client(self):
        with self.assertRaises(J.JudgeError):
            J.ModelJudge(None)

    def test_placeholder_family_normalized_to_empty_key(self):
        """模型返回展示占位 "(empty)" 时必须还原成机器键 ""，否则 scope 会对不上数据行。"""
        fams = ["LGPS", ""]
        payload = json.dumps([{"family": "LGPS", "verdict": "relevant",
                               "reason": "r"},
                              {"family": "(empty)", "verdict": "excluded",
                               "reason": "空族名"}])
        j, _ = self._judge([self.QUERIES_JSON, payload], families=fams)
        judgments, scope = j.judge("sulfide", fams)
        self.assertEqual(scope[""], "excluded")
        self.assertEqual(scope["LGPS"], "relevant")


class TestFactoryAndScope(unittest.TestCase):
    def test_build_rule(self):
        self.assertIsInstance(J.build("rule"), J.RuleJudge)

    def test_build_model_requires_client(self):
        with self.assertRaises(J.JudgeError):
            J.build("model")

    def test_build_unknown(self):
        with self.assertRaises(J.JudgeError):
            J.build("gpt-ish")

    def test_scope_from_judgments_ignores_query_generation(self):
        js = [{"kind": J.QUERY_GENERATION, "meta": {"subject": "goal",
                                                    "verdict": "generated"}},
              {"kind": J.RELEVANCE, "meta": {"subject": "LGPS",
                                             "verdict": "relevant"}}]
        self.assertEqual(J.scope_from_judgments(js), {"LGPS": "relevant"})

    def test_make_relevance_judgment_validates_verdict(self):
        with self.assertRaises(J.JudgeError):
            J.make_relevance_judgment("x", "perhaps", "r", "rule")


class TestCompareJudges(unittest.TestCase):
    """反判据：模型判断是否真的改变结果（判据 2 的反面）。"""

    QUERIES = '["sulfide solid electrolyte ionic conductivity", "argyrodite conductivity"]'

    @staticmethod
    def _client(verdicts):
        """构造按 prompt 内容分流的假客户端。"""
        rel = json.dumps([{"family": f, "verdict": verdicts.get(f, "excluded"),
                           "reason": f"r-{f}"} for f in FAMILIES])

        def fn(prompt):
            return TestCompareJudges.QUERIES if "检索式" in prompt else rel
        return FakeClient([fn("检索式"), fn("族")])

    def test_rule_vs_rule_is_decoration(self):
        """两个同实现判断器对比 → 必然完全一致（反判据的退化情形）。"""
        out = J.compare_judges("sulfide solid electrolyte", FAMILIES,
                               J.RuleJudge(), J.RuleJudge(),
                               "rule1", "rule2")
        self.assertTrue(out["queries_identical"])
        self.assertTrue(out["scope_identical"])
        self.assertFalse(out["model_changes_outcome"])
        self.assertEqual(out["verdict"], "model_is_decoration")

    def test_model_changes_scope(self):
        # 规则式把 NASICON 判为 excluded；模型判为 relevant → 出现翻转
        client = self._client({"NASICON": "relevant", "garnet": "relevant"})
        out = J.compare_judges("sulfide solid electrolyte", FAMILIES,
                               J.RuleJudge(),
                               J.ModelJudge(client, model_name="fake"),
                               "rule", "model")
        self.assertFalse(out["scope_identical"])
        self.assertTrue(out["model_changes_outcome"])
        self.assertEqual(out["verdict"], "model_matters")
        flips = {f["family"] for f in out["flips"]}
        self.assertIn("NASICON", flips)
        self.assertIn("garnet", flips)

    def test_model_changes_queries_only(self):
        """范围一致但检索式不同 → 也算模型改变了结果。"""
        # 与规则式同范围（LGPS / argyrodites 相关），但检索式不同
        client = self._client({"LGPS": "relevant", "argyrodites": "relevant"})
        out = J.compare_judges("sulfide solid electrolyte", FAMILIES,
                               J.RuleJudge(),
                               J.ModelJudge(client, model_name="fake"),
                               "rule", "model")
        self.assertTrue(out["scope_identical"])
        self.assertFalse(out["queries_identical"])
        self.assertTrue(out["model_changes_outcome"])

    def test_counts_reported(self):
        client = self._client({"NASICON": "relevant"})
        out = J.compare_judges("sulfide", FAMILIES, J.RuleJudge(),
                               J.ModelJudge(client, model_name="fake"))
        self.assertEqual(out["a"]["n_subjects"], len(FAMILIES))
        self.assertEqual(out["b"]["n_subjects"], len(FAMILIES))
        self.assertGreaterEqual(out["a"]["n_relevant"], 0)
        self.assertEqual(out["goal"], "sulfide")

    def test_flip_entry_uses_stable_keys(self):
        """翻转项用稳定键 a/b，不随标签变化（两标签同名时也不能互相覆盖）。"""
        client = self._client({"NASICON": "relevant"})
        out = J.compare_judges("sulfide", FAMILIES, J.RuleJudge(),
                               J.ModelJudge(client, model_name="fake"),
                               "rule", "model")
        for f in out["flips"]:
            self.assertEqual(set(f), {"family", "a", "b"})
        self.assertEqual(out["labels"], {"a": "rule", "b": "model"})

    def test_same_labels_still_distinguishable(self):
        out = J.compare_judges("sulfide", FAMILIES,
                               J.RuleJudge(), J.RuleJudge(), "x", "x")
        self.assertEqual(out["labels"], {"a": "x", "b": "x"})
        # 自比时无翻转，不会暴露键冲突；这里主要锁住 labels 的形状
        self.assertEqual(out["flips"], [])


if __name__ == "__main__":
    unittest.main()
