"""test_llm.py — 模型客户端适配层（离线）。

覆盖 CallableClient 与 OpenAiChatClient 的接口、请求构造与失败路径。
**不发起真实网络请求**（传输层注入假实现）。
"""
import io
import os
import sys
import unittest
import urllib.error

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)

from paper_agent import llm as LLM  # noqa: E402


def ok_transport(content="hello", seen=None):
    def _t(url, payload, headers, timeout):
        if seen is not None:
            seen.append({"url": url, "payload": payload, "headers": headers,
                         "timeout": timeout})
        return {"choices": [{"message": {"content": content}}]}
    return _t


class TestCallableClient(unittest.TestCase):
    def test_wraps_function(self):
        c = LLM.CallableClient(lambda p: "echo:" + p, name="unit")
        self.assertEqual(c.name, "unit")
        self.assertEqual(c.complete("hi"), "echo:hi")

    def test_requires_function(self):
        with self.assertRaises(LLM.LlmError):
            LLM.CallableClient(None)


class TestOpenAiChatClient(unittest.TestCase):
    def test_requires_base_url(self):
        with self.assertRaises(LLM.LlmError):
            LLM.OpenAiChatClient("", "m")

    def test_requires_model(self):
        with self.assertRaises(LLM.LlmError):
            LLM.OpenAiChatClient("https://x/v1", "  ")

    def test_endpoint_and_name(self):
        c = LLM.OpenAiChatClient("https://x/v1/", "agnes-3.0-flash")
        self.assertEqual(c.endpoint, "https://x/v1/chat/completions")
        self.assertEqual(c.name, "openai:agnes-3.0-flash")

    def test_complete_happy_path(self):
        seen = []
        c = LLM.OpenAiChatClient("https://x/v1", "m", transport=ok_transport("OK", seen))
        self.assertEqual(c.complete("q"), "OK")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["url"], "https://x/v1/chat/completions")
        self.assertEqual(seen[0]["payload"]["temperature"], 0)
        self.assertEqual(seen[0]["payload"]["model"], "m")
        self.assertEqual(seen[0]["payload"]["messages"][0]["role"], "user")
        self.assertEqual(seen[0]["payload"]["messages"][0]["content"], "q")

    def test_authorization_header_only_when_key_present(self):
        seen = []
        LLM.OpenAiChatClient("https://x/v1", "m", api_key="sk-1",
                             transport=ok_transport("y", seen)).complete("q")
        self.assertEqual(seen[0]["headers"]["Authorization"], "Bearer sk-1")
        seen2 = []
        LLM.OpenAiChatClient("https://x/v1", "m",
                             transport=ok_transport("y", seen2)).complete("q")
        self.assertNotIn("Authorization", seen2[0]["headers"])

    def test_http_error_becomes_llm_error(self):
        def t(url, payload, headers, timeout):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, 
                                         io.BytesIO(b'{"error":"bad key"}'))
        c = LLM.OpenAiChatClient("https://x/v1", "m", transport=t)
        with self.assertRaises(LLM.LlmError) as cm:
            c.complete("q")
        self.assertIn("401", str(cm.exception))

    def test_network_error_becomes_llm_error(self):
        def t(url, payload, headers, timeout):
            raise OSError("connection refused")
        c = LLM.OpenAiChatClient("https://x/v1", "m", transport=t)
        with self.assertRaises(LLM.LlmError):
            c.complete("q")

    def test_unexpected_shape_becomes_llm_error(self):
        c = LLM.OpenAiChatClient("https://x/v1", "m",
                                 transport=lambda *a: {"nope": 1})
        with self.assertRaises(LLM.LlmError) as cm:
            c.complete("q")
        self.assertIn("unexpected response", str(cm.exception))

    def test_empty_content_ok(self):
        c = LLM.OpenAiChatClient("https://x/v1", "m",
                                 transport=ok_transport(""))
        self.assertEqual(c.complete("q"), "")


class TestAutoClient(unittest.TestCase):
    ENVS = (LLM.ENV_BASE_URL, LLM.ENV_MODEL, LLM.ENV_API_KEY)

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in self.ENVS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_none_without_env(self):
        self.assertIsNone(LLM.auto_client())

    def test_none_with_partial_env(self):
        os.environ[LLM.ENV_BASE_URL] = "https://x/v1"
        self.assertIsNone(LLM.auto_client())

    def test_builds_from_env(self):
        os.environ[LLM.ENV_BASE_URL] = "https://x/v1"
        os.environ[LLM.ENV_MODEL] = "m"
        os.environ[LLM.ENV_API_KEY] = "sk-2"
        c = LLM.auto_client()
        self.assertIsNotNone(c)
        self.assertEqual(c.endpoint, "https://x/v1/chat/completions")
        self.assertEqual(c.api_key, "sk-2")


if __name__ == "__main__":
    unittest.main()
