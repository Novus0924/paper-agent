"""test_data_integrity.py — 数据自洽性守门测试（离线为主）。

评审最容易抓的两类数据问题，这里都固化成测试：

1. DOI 格式合法性（离线）：所有 source_doi / 语料 DOI 必须匹配
   `10.<registrant>/<suffix>` 形态，且大小写、括号等可疑字符受限。
   —— 防止再次出现 "10.1038/nmat3006" 指到无关论文这类硬伤。

2. CSV ↔ 语料 交叉一致（离线）：
   - CSV 每一行的 source_doi 必须能在 data/literature.json 里找到；
   - 语料里的 DOI 反向也必须被 CSV 至少引用一次（无孤儿文献）；
   - 材料–年份–DOI 三者自洽：CSV 行的 year 必须等于所引语料的 year
     （防止 M002 用了 Kato 2016 材料却标 2011 这类错配）。

3. 真实可解析性（可选，联网）：设置 RUN_ONLINE=1 时，用 Crossref /
   doi.org 逐条验证 DOI 真实存在。默认跳过，保证 CI 离线可跑。
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import unittest
import urllib.request

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))

# DOI 形态：10.<4~9位 registrant>/<suffix>，suffix 允许常见可见字符
_DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$")
# 可疑字符：空格、引号、中文标点、全角括号等
_BAD_CHARS = set(' "\u201c\u201d\u2018\u2019（），、；：')


def _load_literature():
    p = os.path.join(_PROJECT_ROOT, "data", "literature.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_raw_csv():
    p = os.path.join(_PROJECT_ROOT, "data", "conductivity_raw.csv")
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestDoiFormat(unittest.TestCase):
    """DOI 字符串本身合法、整洁。"""

    def test_corpus_dois_wellformed(self):
        lit = _load_literature()
        self.assertTrue(lit["documents"], "语料不能为空")
        for d in lit["documents"]:
            doi = d["doi"]
            self.assertRegex(doi, _DOI_RE, f"{d['doc_id']} DOI 形态非法: {doi!r}")
            for ch in doi:
                self.assertNotIn(ch, _BAD_CHARS,
                                 f"{d['doc_id']} DOI 含可疑字符 {ch!r}: {doi!r}")

    def test_corpus_doi_unique(self):
        lit = _load_literature()
        dois = [d["doi"] for d in lit["documents"]]
        self.assertEqual(len(dois), len(set(dois)), "语料 DOI 必须唯一")

    def test_csv_dois_wellformed(self):
        for r in _load_raw_csv():
            doi = r["source_doi"].strip()
            self.assertRegex(doi, _DOI_RE,
                             f"{r['material_id']} source_doi 形态非法: {doi!r}")

    def test_no_legacy_wrong_dois(self):
        """回归护栏：这批已确认错误的 DOI 绝不允许再次出现。"""
        legacy_bad = {
            "10.1038/nmat3006",       # 曾被错标为 LGPS
            "10.1038/nenergy.2016.030",  # 应为 …2016.30（无多余 0）
            "10.1016/0167-2738(92)90421-F",  # 应为 …90442-r
            "10.1002/anie.200800627",  # 应为 …200703900
        }
        blob = json.dumps(_load_literature(), ensure_ascii=False)
        blob += "\n" + "\n".join(
            r["source_doi"] for r in _load_raw_csv())
        for bad in legacy_bad:
            self.assertNotIn(bad, blob,
                             f"检测到已修正的历史错误 DOI 残留: {bad}")


class TestCsvCorpusConsistency(unittest.TestCase):
    """CSV 与文献语料双向一致、材料–年份–DOI 自洽。"""

    def setUp(self):
        self.lit = _load_literature()
        self.by_doi = {d["doi"]: d for d in self.lit["documents"]}
        self.rows = _load_raw_csv()

    def test_every_csv_doi_in_corpus(self):
        for r in self.rows:
            doi = r["source_doi"].strip()
            self.assertIn(doi, self.by_doi,
                          f"{r['material_id']} 引用了语料中不存在的 DOI: {doi}")

    def test_no_orphan_corpus_doi(self):
        """语料里每篇文献都应被 CSV 至少引用一次（无摆设文献）。"""
        used = {r["source_doi"].strip() for r in self.rows}
        for doi in self.by_doi:
            self.assertIn(doi, used, f"语料 DOI 未被任何材料引用: {doi}")

    def test_year_matches_source(self):
        """材料年份必须等于所引文献年份（防材料–来源错配）。"""
        for r in self.rows:
            doi = r["source_doi"].strip()
            src = self.by_doi.get(doi)
            if src is None:
                continue  # 由上一个测试负责报错
            self.assertEqual(
                int(r["year"]), int(src["year"]),
                f"{r['material_id']} 年份 {r['year']} 与来源 {doi} "
                f"({src['year']}) 不一致")

    def test_same_formula_same_family_consistent(self):
        """同一 formula 在不同行必须归属同一 family。"""
        seen = {}
        for r in self.rows:
            fam = r["family"]
            f = r["formula"]
            if f in seen:
                self.assertEqual(seen[f], fam,
                                 f"formula {f} 家族不一致: {seen[f]} vs {fam}")
            seen[f] = fam


class TestOnlineDoiResolvable(unittest.TestCase):
    """可选在线核验：RUN_ONLINE=1 时逐条打 Crossref，确认 DOI 真实存在。"""

    @unittest.skipUnless(os.environ.get("RUN_ONLINE") == "1",
                         "设置 RUN_ONLINE=1 才执行联网 DOI 核验")
    def test_dois_resolvable(self):
        lit = _load_literature()
        for d in lit["documents"]:
            url = "https://api.crossref.org/works/" + d["doi"]
            req = urllib.request.Request(
                url, headers={"User-Agent": "paper-agent-verify/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    code = resp.status
            except urllib.error.HTTPError as e:  # noqa: F821
                code = e.code
            self.assertIn(code, (200, 403),
                          f"{d['doc_id']} DOI 无法解析 (HTTP {code}): {d['doi']}")
            if code == 200:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    meta = json.loads(resp.read().decode("utf-8"))
                title = (meta.get("message", {}).get("title") or [""])[0]
                self.assertTrue(title, f"{d['doc_id']} Crossref 未返回标题")


if __name__ == "__main__":
    unittest.main()
