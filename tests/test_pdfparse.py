"""test_pdfparse.py — 零依赖 PDF 精读（PRD F-2.1）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import (make_pdf, make_paper_pdf, make_scanned_pdf,  # noqa: E402
                   parse_fixture_pdf)

from paper_agent import pdfparse as PP  # noqa: E402


class TestExtraction(unittest.TestCase):
    def test_uncompressed_stream(self):
        ext = PP.extract_pdf_text(make_pdf(
            b"BT /F1 12 Tf 72 720 Td (Hello world from PDF) Tj ET", compress=False))
        self.assertIn("Hello world from PDF", ext["text"])
        self.assertTrue(ext["has_text_layer"])

    def test_flate_compressed_stream(self):
        ext = PP.extract_pdf_text(make_pdf(
            b"BT /F1 12 Tf 72 720 Td (Compressed text content here) Tj ET",
            compress=True))
        self.assertIn("Compressed text content here", ext["text"])

    def test_tj_array_concatenates(self):
        ext = PP.extract_pdf_text(make_pdf(
            b"BT /F1 12 Tf 72 720 Td [(Sul) -250 (fide)] TJ ET", compress=False))
        self.assertIn("Sulfide", ext["text"])

    def test_escapes_and_hex_strings(self):
        # 字面串内含转义括号；十六进制串作为**独立操作数**（符合 PDF 语义）
        ext = PP.extract_pdf_text(make_pdf(
            b"BT /F1 12 Tf 72 720 Td (paren\\(ok\\)) Tj T* <48656C6C6F> Tj ET",
            compress=False))
        self.assertIn("paren(ok)", ext["text"])
        self.assertIn("Hello", ext["text"])   # hex string

    def test_scanned_has_no_text_layer(self):
        ext = PP.extract_pdf_text(make_scanned_pdf())
        self.assertFalse(ext["has_text_layer"])
        self.assertEqual(ext["n_chars"], 0)


class TestStructure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_pdf_")
        self.note = parse_fixture_pdf(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_sections_detected(self):
        self.assertEqual(set(self.note["sections"]),
                         {"Abstract", "Introduction", "Method", "Experiment", "Conclusion"})

    def test_key_info_with_locator(self):
        ki = self.note["key_info"]
        self.assertTrue(ki["method"])
        for item in ki["method"]:
            self.assertIn("section", item["locator"])
            self.assertIn("offset", item["locator"])

    def test_figure_table_caption(self):
        figs = self.note["figures_tables"]
        self.assertTrue(any(f["kind"] == "table" and f["index"] == 1 for f in figs))

    def test_reproducibility_links(self):
        rep = self.note["reproducibility"]
        self.assertTrue(rep["has_code"])
        self.assertTrue(rep["has_data"])
        self.assertTrue(any("github" in c for c in rep["code_links"]))

    def test_language_detection(self):
        self.assertEqual(PP.detect_language(self.note["text"]), "en")
        self.assertEqual(PP.detect_language("这是一段中文论文摘要，用于测试语言识别是否正确。"), "zh")

    def test_status_and_confidence(self):
        self.assertIn(self.note["status"], ("ok", "scanned"))
        self.assertIn(self.note["confidence"], ("high", "medium", "low"))

    def test_render_note_language_follow(self):
        md_en = PP.render_note(self.note, "en")
        md_zh = PP.render_note(self.note, "zh")
        self.assertIn("Reproducibility", md_en)
        self.assertIn("可复现性", md_zh)


class TestScannedDegrade(unittest.TestCase):
    def test_scanned_note_marks_low_confidence(self):
        tmp = tempfile.mkdtemp(prefix="pa_scan_")
        try:
            p = os.path.join(tmp, "scan.pdf")
            with open(p, "wb") as f:
                f.write(make_scanned_pdf())
            note = PP.parse_paper(p)
            self.assertEqual(note["status"], "scanned")
            self.assertEqual(note["confidence"], "low")
            self.assertTrue(note["warnings"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_source_is_unavailable(self):
        note = PP.parse_paper("does_not_exist.pdf")
        self.assertEqual(note["status"], "unavailable")
        self.assertTrue(note["warnings"])


class TestParsePdfBytes(unittest.TestCase):
    def test_bytes_entry(self):
        note = PP.parse_pdf_bytes(make_paper_pdf(), "DOC-1")
        self.assertEqual(note["doc_id"], "DOC-1")
        self.assertIn("Abstract", note["sections"])


if __name__ == "__main__":
    unittest.main()
