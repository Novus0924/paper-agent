"""test_litsearch.py — P1 文献检索后端（arXiv / local / auto）。

离线（默认）：
  1. tokenize / build_arxiv_query：自然语言 goal → arXiv search_query 语法
  2. parse_arxiv_atom：喂固定 Atom XML，校验规范化字段（纯函数，无网络）
  3. load_local_corpus / filter_by_relevance：本地语料读取与稳定排序
  4. ref_of：证据引用回退顺序（DOI → URL → doc_id）
  5. 集成：P1 在 local 来源下产出 literature_hits.json
  6. 集成：**快照冻结** —— 存在 arxiv_snapshot.json 时只读快照、不联网
  7. 集成：auto 来源在网络异常时自动回落 local_fallback 并置 degraded

在线（可选）：`RUN_ONLINE=1` 时定义真实检索用例；默认不定义，故运行零 skip。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import isolate_temp_root  # noqa: E402

from paper_agent import litsearch as LS  # noqa: E402
from paper_agent.state import create_state, load_state, new_run_id  # noqa: E402
from paper_agent.steps import Pipeline  # noqa: E402
from paper_agent.chaos import clear_chaos_mode  # noqa: E402

_ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <updated>2024-02-01T00:00:00Z</updated>
    <published>2024-01-22T00:00:00Z</published>
    <title>Superionic sulfide electrolytes
      for solid-state batteries</title>
    <summary>We report a sulfide electrolyte with high ionic conductivity.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:primary_category term="cond-mat.mtrl-sci"/>
    <category term="cond-mat.mtrl-sci"/>
    <category term="physics.app-ph"/>
    <arxiv:doi>10.1234/example.2024</arxiv:doi>
    <arxiv:journal_ref>J. Power Sources 1 (2024)</arxiv:journal_ref>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.54321v1</id>
    <published>2024-02-10T00:00:00Z</published>
    <title>Garnet electrolytes</title>
    <summary>LLZO thin films.</summary>
  </entry>
</feed>
"""


class TestQueryBuilding(unittest.TestCase):
    def test_tokenize_drops_stopwords_and_dedups(self):
        toks = LS.tokenize("Sulfide solid electrolyte and the ranking of Sulfide")
        self.assertNotIn("the", toks)
        self.assertNotIn("and", toks)
        self.assertNotIn("of", toks)
        self.assertNotIn("ranking", toks)          # 任务型词也过滤
        self.assertEqual(toks.count("sulfide"), 1)  # 去重
        self.assertEqual(toks[0], "sulfide")

    def test_build_query_and_form(self):
        q = LS.build_arxiv_query("sulfide solid electrolyte conductivity")
        self.assertEqual(
            q, "all:sulfide AND all:solid AND all:electrolyte AND all:conductivity")

    def test_build_query_or_form(self):
        q = LS.build_arxiv_query("sulfide electrolyte", join=" OR ")
        self.assertEqual(q, "all:sulfide OR all:electrolyte")

    def test_build_query_empty_goal_is_safe(self):
        self.assertEqual(LS.build_arxiv_query("the and of"), "all:science")


class TestParseAtom(unittest.TestCase):
    def setUp(self):
        self.docs = LS.parse_arxiv_atom(_ATOM_FIXTURE)

    def test_two_entries(self):
        self.assertEqual(len(self.docs), 2)

    def test_first_entry_normalized(self):
        d = self.docs[0]
        self.assertEqual(d["doc_id"], "arXiv:2401.12345")   # 版本号已剥离
        self.assertEqual(d["doi"], "10.1234/example.2024")
        self.assertEqual(d["title"],
                         "Superionic sulfide electrolytes for solid-state batteries")
        self.assertEqual(d["authors"], ["Ada Lovelace", "Alan Turing"])
        self.assertEqual(d["venue"], "J. Power Sources 1 (2024)")
        self.assertEqual(d["year"], 2024)
        self.assertEqual(d["keywords"][0], "cond-mat.mtrl-sci")  # primary 置前
        self.assertEqual(d["url"], "https://arxiv.org/abs/2401.12345")
        self.assertEqual(d["source"], "arxiv")

    def test_second_entry_defaults(self):
        d = self.docs[1]
        self.assertEqual(d["doc_id"], "arXiv:2402.54321")
        self.assertEqual(d["doi"], "")
        self.assertEqual(d["authors"], [])
        self.assertEqual(d["keywords"], [])
        self.assertEqual(d["venue"], "arXiv preprint")

    def test_accepts_str_payload(self):
        self.assertEqual(len(LS.parse_arxiv_atom(_ATOM_FIXTURE)), 2)


class TestLocalCorpus(unittest.TestCase):
    def setUp(self):
        self.root = isolate_temp_root(self, "pa_lit_")

    def test_load_local_corpus(self):
        docs = LS.load_local_corpus(self.root)
        self.assertEqual(len(docs), 5)
        for d in docs:
            self.assertEqual(d["source"], "local")
            self.assertTrue(d["url"])

    def test_filter_is_stable_and_relevant(self):
        docs = LS.load_local_corpus(self.root)
        hits = LS.filter_by_relevance(docs, "sulfide solid electrolyte conductivity")
        self.assertTrue(hits)
        # 同一输入两次结果一致（确定性）
        self.assertEqual([d["doc_id"] for d in hits],
                         [d["doc_id"] for d in LS.filter_by_relevance(
                             docs, "sulfide solid electrolyte conductivity")])
        # 完全不相关的 goal → 0 命中
        self.assertEqual(
            LS.filter_by_relevance(docs, "quantum chromodynamics lattice"), [])

    def test_ref_of_fallback_order(self):
        self.assertEqual(LS.ref_of({"doi": "10.1/x", "url": "u", "doc_id": "d"}), "10.1/x")
        self.assertEqual(LS.ref_of({"doi": "", "url": "u", "doc_id": "d"}), "u")
        self.assertEqual(LS.ref_of({"doi": "", "url": "", "doc_id": "arXiv:1"}), "arXiv:1")


class TestP1Integration(unittest.TestCase):
    """P1 集成：来源选择、快照冻结、网络异常降级。"""

    def setUp(self):
        clear_chaos_mode()
        self.root = isolate_temp_root(self, "pa_p1_")

    def tearDown(self):
        clear_chaos_mode()
        # 临时目录与全局量的清理由 isolate_temp_root 的 addCleanup 负责

    def _plan(self, goal, lit_source):
        rid = new_run_id()
        create_state(rid, self.root, goal, lit_source=lit_source,
                     workflow="materials")
        return rid, Pipeline(self.root, rid)

    def _hits(self, rid):
        p = os.path.join(self.root, "runs", rid, "literature", "literature_hits.json")
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_lit_source_persisted_in_state(self):
        rid, _ = self._plan("g", "arxiv")
        self.assertEqual(load_state(rid, self.root).lit_source, "arxiv")

    def test_local_source_hits_corpus(self):
        rid, pipe = self._plan("sulfide solid electrolyte conductivity", "local")
        pipe._ensure_running()
        res = pipe.run_p1()
        self.assertEqual(res["source"], "local")
        self.assertFalse(res["degraded"])
        hits = self._hits(rid)
        self.assertEqual(hits["source"], "local")
        self.assertGreater(hits["n_hits"], 0)
        self.assertEqual(hits["snapshot"], "")   # 本地来源不产生快照

    def test_snapshot_is_reused_without_network(self):
        """存在 arxiv_snapshot.json 时：只读快照、不联网（确定性契约）。"""
        rid, pipe = self._plan("frozen goal", "arxiv")
        lit_dir = os.path.join(self.root, "runs", rid, "literature")
        os.makedirs(lit_dir, exist_ok=True)
        with open(os.path.join(lit_dir, "arxiv_snapshot.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "goal": "frozen goal", "query": "all:frozen", "source": "arxiv",
                "endpoint": LS.ARXIV_API, "fetched_at": "2026-01-01T00:00:00Z",
                "n_documents": 1,
                "documents": [{
                    "doc_id": "arXiv:2401.00001", "doi": "",
                    "title": "Frozen paper", "authors": ["A"],
                    "venue": "arXiv preprint", "year": 2024,
                    "keywords": ["cond-mat"], "abstract": "frozen",
                    "url": "https://arxiv.org/abs/2401.00001", "source": "arxiv",
                }],
            }, f, ensure_ascii=False)

        # 若代码在此处发起网络请求，本测试会变慢/失败 —— 即回归保护点
        pipe._ensure_running()
        res = pipe.run_p1()
        self.assertEqual(res["source"], "arxiv")
        hits = self._hits(rid)
        self.assertEqual(hits["note"], "snapshot_reused")
        self.assertEqual(hits["n_hits"], 1)
        self.assertEqual(hits["hits"][0]["doc_id"], "arXiv:2401.00001")
        self.assertEqual(hits["snapshot"], "literature/arxiv_snapshot.json")

    def test_auto_falls_back_to_local_on_network_error(self):
        rid, pipe = self._plan("sulfide electrolyte", "auto")

        def _boom(*_a, **_k):
            raise OSError("network unreachable")

        orig = LS.search_arxiv
        LS.search_arxiv = _boom
        try:
            pipe._ensure_running()
            res = pipe.run_p1()
        finally:
            LS.search_arxiv = orig

        self.assertEqual(res["source"], "local_fallback")
        self.assertTrue(res["degraded"])
        hits = self._hits(rid)
        self.assertTrue(hits["degraded"])
        self.assertTrue(hits["note"].startswith("arxiv_unavailable"))
        self.assertTrue(pipe.state.degraded, "run 级 degraded 必须同步置位")


if os.environ.get("RUN_ONLINE") == "1":

    class TestOnlineArxivSearch(unittest.TestCase):
        """可选在线用例：RUN_ONLINE=1 时才定义（默认运行零 skip）。

        开启方式：
            paper-agent_LIT_SOURCE=arxiv RUN_ONLINE=1 \
              python -m unittest tests.test_litsearch -v
        """

        def test_search_returns_real_papers(self):
            docs, query = LS.search_arxiv(
                "sulfide solid electrolyte ionic conductivity", max_results=3)
            self.assertTrue(docs, f"arXiv 检索应有命中（query={query}）")
            d = docs[0]
            self.assertEqual(d["source"], "arxiv")
            self.assertTrue(d["title"])
            self.assertTrue(d["url"].startswith("https://arxiv.org/abs/"))
            self.assertGreaterEqual(d["year"], 1991)


class _FakeResponse:
    """最小 urlopen 返回值：上下文管理器 + read()。"""

    def __init__(self, body: bytes = b""):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


class TestFetchJsonRetry(unittest.TestCase):
    """PERF-3a：_fetch_json 瞬时错误退避重试。

    手法：monkeypatch ``urllib.request.urlopen`` 计数 + 注入 ``sleep``
    假时钟（不打真睡眠），口径对齐本文件既有离线测试风格。
    """

    def setUp(self):
        self.sleeps = []

    def _fake_sleep(self, seconds):
        self.sleeps.append(seconds)

    def _patch_urlopen(self, fn):
        orig = urllib.request.urlopen
        urllib.request.urlopen = fn
        self.addCleanup(setattr, urllib.request, "urlopen", orig)

    def test_transient_error_retries_then_success(self):
        """连接类 URLError → 退避重试，3 次尝试内成功，按 BACKOFF=[1,2] 睡眠。"""
        calls = {"n": 0}

        def _flaky(req, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError(
                    ConnectionRefusedError(111, "Connection refused"))
            return _FakeResponse(b'{"ok": 1}')

        self._patch_urlopen(_flaky)
        out = LS._fetch_json("https://api.example.org/works", 5.0,
                             sleep=self._fake_sleep)
        self.assertEqual(out, {"ok": 1})
        self.assertEqual(calls["n"], 3)          # 首次 + 2 次重试
        self.assertEqual(self.sleeps, [1, 2])    # BACKOFF 退避序列

    def test_timeout_is_transient_and_exhaustion_raises_original(self):
        """超时为瞬时错误；重试耗尽后抛**原异常**（降级链语义不变）。"""
        calls = {"n": 0}

        def _slow(req, timeout=None):
            calls["n"] += 1
            raise TimeoutError("timed out")

        self._patch_urlopen(_slow)
        with self.assertRaises(TimeoutError):
            LS._fetch_json("https://api.example.org/works", 5.0,
                           sleep=self._fake_sleep)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(self.sleeps, [1, 2])

    def test_http_429_and_5xx_retry(self):
        """HTTP 429 / 5xx 属瞬时错误：退避重试。"""
        for code in (429, 500, 503):
            with self.subTest(code=code):
                calls = {"n": 0}
                self.sleeps.clear()

                def _err(req, timeout=None, code=code):
                    calls["n"] += 1
                    raise urllib.error.HTTPError(
                        "https://api.example.org/works", code, "err", {},
                        io.BytesIO(b""))

                self._patch_urlopen(_err)
                with self.assertRaises(urllib.error.HTTPError):
                    LS._fetch_json("https://api.example.org/works", 5.0,
                                   sleep=self._fake_sleep)
                self.assertEqual(calls["n"], 3)
                self.assertEqual(self.sleeps, [1, 2])

    def test_http_4xx_no_retry(self):
        """确定性 4xx（除 429）不重试：urlopen 恰好调用 1 次、零睡眠。"""
        calls = {"n": 0}

        def _denied(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                "https://api.example.org/works", 403, "Forbidden", {},
                io.BytesIO(b"{}"))

        self._patch_urlopen(_denied)
        with self.assertRaises(urllib.error.HTTPError):
            LS._fetch_json("https://api.example.org/works", 5.0,
                           sleep=self._fake_sleep)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.sleeps, [])

    def test_bad_json_no_retry(self):
        """JSON 解析失败不属于网络瞬时错误：不重试，原样上抛。"""
        calls = {"n": 0}

        def _garbage(req, timeout=None):
            calls["n"] += 1
            return _FakeResponse(b"not-json")

        self._patch_urlopen(_garbage)
        with self.assertRaises(json.JSONDecodeError):
            LS._fetch_json("https://api.example.org/works", 5.0,
                           sleep=self._fake_sleep)
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
