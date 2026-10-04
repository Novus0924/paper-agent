"""test_sources.py — 外部数据源适配层：列名归一、值分类、标准列映射、确定性。

对应 redesign-decisions.md D2 / D3（数据腿）。零依赖，不联网。
"""
import os
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TESTS_DIR, "..", "core"))
sys.path.insert(0, _TESTS_DIR)
from _util import project_root  # noqa: E402

from paper_agent import sources  # noqa: E402

# 官方人类可读表头（含上界值、IC 回落、空家族、坏值、注记五种情形）
FIXTURE_HUMAN = (
    "ID,Reduced Composition,Ionic conductivity (S cm-1),IC (Total),IC (Bulk),"
    "Space group,Family,DOI,note\n"
    "jqc,Li7BiO6,1.58489e-06,,,P -1,hexaoxometalates,10.1002/zaac.200500231,\n"
    "abc,Li10GeP2S12,1.2e-2,,,P 42/ncm,LGPS,10.1038/nmat3006,\n"
    "up1,Li3PS4,<1E-10,,,Pnma,sulfides,10.1/upper,\n"
    "fb1,Li6PS5Cl,<1E-8,2.3e-03,,F -43m,argyrodites,10.1/fallback,note here\n"
    "bad,LiX,,,,-,sulfides,10.1/bad,\n"
    "nofam,Li2S,1.0e-05,,,Fm-3m,,10.1/nofamily,partial occupancy corrected\n"
)

# 第三方镜像的 snake_case 表头
FIXTURE_SNAKE = (
    "id,reduced_composition,ionic_conductivity_s_per_cm,space_group,family,source_doi\n"
    "x1,Li7BiO6,1.0e-06,P -1,hexaoxometalates,10.1/x\n"
)


def _write(tmp: str, text: str, name: str = "d.csv") -> str:
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


class TestParseConductivity(unittest.TestCase):
    def test_numeric_scientific(self):
        self.assertEqual(sources.parse_conductivity("1.58489e-06"),
                         (sources.VALUE_NUMERIC, 1.58489e-06))

    def test_numeric_plain_decimal(self):
        status, v = sources.parse_conductivity("0.025")
        self.assertEqual(status, sources.VALUE_NUMERIC)
        self.assertAlmostEqual(v, 0.025)

    def test_upper_bound_never_becomes_number(self):
        """上界值不得被当作数值——否则会把 "<1E-10" 误当 1e-10 参与排序。"""
        for raw in ("<1E-10", " <1E-8 ", "<=1e-12"):
            status, v = sources.parse_conductivity(raw)
            self.assertEqual(status, sources.VALUE_UPPER_BOUND, raw)
            self.assertIsNone(v, raw)

    def test_empty_is_invalid(self):
        self.assertEqual(sources.parse_conductivity(""),
                         (sources.VALUE_INVALID, None))
        self.assertEqual(sources.parse_conductivity("   "),
                         (sources.VALUE_INVALID, None))
        self.assertEqual(sources.parse_conductivity(None),
                         (sources.VALUE_INVALID, None))

    def test_garbage_is_invalid(self):
        self.assertEqual(sources.parse_conductivity("n/a"),
                         (sources.VALUE_INVALID, None))

    def test_non_positive_is_invalid(self):
        self.assertEqual(sources.parse_conductivity("0"),
                         (sources.VALUE_INVALID, None))
        self.assertEqual(sources.parse_conductivity("-1e-3"),
                         (sources.VALUE_INVALID, None))


class TestColumnResolution(unittest.TestCase):
    def test_human_readable_headers(self):
        cols = sources.resolve_columns(FIXTURE_HUMAN.splitlines()[0].split(","))
        self.assertEqual(cols["material_id"], "ID")
        self.assertEqual(cols["formula"], "Reduced Composition")
        self.assertEqual(cols["cond_main"], "Ionic conductivity (S cm-1)")
        self.assertEqual(cols["cond_total"], "IC (Total)")
        self.assertEqual(cols["source_doi"], "DOI")
        self.assertEqual(cols["data_notes"], "note")
        self.assertEqual(cols["family"], "Family")

    def test_snake_case_headers(self):
        cols = sources.resolve_columns(FIXTURE_SNAKE.splitlines()[0].split(","))
        self.assertEqual(cols["material_id"], "id")
        self.assertEqual(cols["formula"], "reduced_composition")
        self.assertEqual(cols["cond_main"], "ionic_conductivity_s_per_cm")
        self.assertEqual(cols["source_doi"], "source_doi")

    def test_missing_column_reported(self):
        cols = sources.resolve_columns(["ID", "DOI"])
        self.assertIsNone(cols["cond_main"])
        self.assertIsNone(cols["family"])


class TestReadObelix(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_src_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_rows_mapped_and_classified(self):
        p = _write(self._tmp, FIXTURE_HUMAN)
        rows, meta = sources.read_obelix(p)
        self.assertEqual(meta["n_rows"], 6)
        self.assertEqual(meta["unresolved_columns"], [])
        by_id = {r["material_id"]: r for r in rows}

        self.assertEqual(by_id["jqc"]["value_status"], sources.VALUE_NUMERIC)
        self.assertEqual(by_id["jqc"]["conductivity_Scm"], "1.584890e-06")
        self.assertEqual(by_id["jqc"]["family"], "hexaoxometalates")
        self.assertEqual(by_id["jqc"]["space_group"], "P -1")

        # 上界值：无数值、原文保留
        self.assertEqual(by_id["up1"]["value_status"], sources.VALUE_UPPER_BOUND)
        self.assertEqual(by_id["up1"]["conductivity_Scm"], "")
        self.assertEqual(by_id["up1"]["conductivity_raw"], "<1E-10")

        # 主列为上界 → 回落到 IC (Total)
        self.assertEqual(by_id["fb1"]["value_status"], sources.VALUE_NUMERIC)
        self.assertEqual(by_id["fb1"]["conductivity_Scm"], "2.300000e-03")
        self.assertEqual(by_id["fb1"]["conductivity_raw"], "2.3e-03")

        # 坏值
        self.assertEqual(by_id["bad"]["value_status"], sources.VALUE_INVALID)
        self.assertEqual(by_id["bad"]["conductivity_Scm"], "")

        # 空家族与注记原样搬运（清洗决策留给 P2）
        self.assertEqual(by_id["nofam"]["family"], "")
        self.assertEqual(by_id["nofam"]["data_notes"],
                         "partial occupancy corrected")

    def test_snake_case_fixture_readable(self):
        p = _write(self._tmp, FIXTURE_SNAKE)
        rows, meta = sources.read_obelix(p)
        self.assertEqual(meta["n_rows"], 1)
        self.assertEqual(rows[0]["material_id"], "x1")
        self.assertEqual(rows[0]["conductivity_Scm"], "1.000000e-06")

    def test_canonical_columns_complete(self):
        p = _write(self._tmp, FIXTURE_HUMAN)
        rows, _ = sources.read_obelix(p)
        for r in rows:
            self.assertEqual(sorted(r.keys()), sorted(sources.MATERIALS_COLUMNS))

    def test_csv_output_is_deterministic(self):
        """相同输入两次映射 → 逐字节一致的 CSV（复现契约前提）。"""
        p = _write(self._tmp, FIXTURE_HUMAN)
        a, _ = sources.read_obelix(p)
        b, _ = sources.read_obelix(p)
        self.assertEqual(sources.to_materials_csv(a), sources.to_materials_csv(b))

    def test_csv_header_order_fixed(self):
        p = _write(self._tmp, FIXTURE_HUMAN)
        rows, _ = sources.read_obelix(p)
        first = sources.to_materials_csv(rows).splitlines()[0]
        self.assertEqual(first, ",".join(sources.MATERIALS_COLUMNS))

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            sources.read_obelix(os.path.join(self._tmp, "nope.csv"))

    def test_summarize_counts(self):
        p = _write(self._tmp, FIXTURE_HUMAN)
        rows, _ = sources.read_obelix(p)
        s = sources.summarize(rows)
        self.assertEqual(s["n_rows"], 6)
        self.assertEqual(s["value_status"][sources.VALUE_NUMERIC], 4)
        self.assertEqual(s["value_status"][sources.VALUE_UPPER_BOUND], 1)
        self.assertEqual(s["value_status"][sources.VALUE_INVALID], 1)
        self.assertEqual(s["family_empty"], 1)
        self.assertEqual(s["doi_empty"], 0)
        self.assertEqual(s["duplicate_material_id"], 0)


class TestSchemaGuard(unittest.TestCase):
    """边界处必须响亮失败：列名对不上就抛错，绝不静默产出垃圾行。

    实测教训（2026-10-03）：喂入完全不同领域的 CSV（吸附容量）时，
    旧实现"成功"返回 4 行全 invalid、9 列里 8 列未解析的记录。
    """

    ALT_DOMAIN_CSV = (
        "sample_id,material_name,group,uptake_mg_g,source_doi\n"
        "A001,Zeolite-5A,zeolite,142.3,10.1002/adma.201800123\n"
        "A002,MOF-808,MOF,198.7,10.1038/nmat3006\n"
    )

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pa_schema_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, text):
        p = os.path.join(self._tmp, "alt.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return p

    def test_wrong_schema_raises_by_default(self):
        p = self._write(self.ALT_DOMAIN_CSV)
        with self.assertRaises(sources.SchemaError):
            sources.read_obelix(p)

    def test_error_message_is_actionable(self):
        p = self._write(self.ALT_DOMAIN_CSV)
        with self.assertRaises(sources.SchemaError) as cm:
            sources.read_obelix(p)
        msg = str(cm.exception)
        self.assertIn("material_id", msg)      # 缺哪列
        self.assertIn("Ionic conductivity", msg)  # 期望的列名
        self.assertIn("uptake_mg_g", msg)      # 实际读到的表头
        self.assertIn("适配器", msg)            # 下一步该做什么

    def test_strict_false_returns_diagnostics(self):
        """诊断路径（probe 类工具）仍能拿到未解析列清单。"""
        p = self._write(self.ALT_DOMAIN_CSV)
        rows, meta = sources.read_obelix(p, strict=False)
        self.assertEqual(len(rows), 2)
        self.assertIn("cond_main", meta["unresolved_columns"])
        self.assertIn("material_id", meta["unresolved_columns"])
        self.assertEqual(meta["resolved_columns"]["source_doi"], "source_doi")

    def test_correct_schema_still_works(self):
        p = _write(self._tmp, FIXTURE_HUMAN)
        rows, meta = sources.read_obelix(p, strict=True)
        self.assertEqual(meta["unresolved_columns"], [])
        self.assertEqual(len(rows), 6)

    def test_only_doi_column_present_still_raises(self):
        """只对上 DOI 一列也不够——数值列必须存在。"""
        p = self._write("DOI,title\n10.1/a,x\n")
        with self.assertRaises(sources.SchemaError) as cm:
            sources.read_obelix(p)
        self.assertIn("cond_main", str(cm.exception))


class TestRealDatasetIntegrity(unittest.TestCase):
    """对仓库内 OBELiX 快照的完整性断言（无该文件时跳过）。"""

    def setUp(self):
        self.path = os.path.join(project_root(), "data", "external", "obelix",
                                 "all.csv")
        if not os.path.exists(self.path):
            self.skipTest("bundled OBELiX snapshot not present")

    def test_expected_shape(self):
        rows, meta = sources.read_obelix(self.path)
        s = sources.summarize(rows)
        # 探针实测基线：599 行 / 562 可用 / 37 上界 / 33 空家族 / 0 空 DOI
        self.assertEqual(s["n_rows"], 599)
        self.assertEqual(s["value_status"][sources.VALUE_NUMERIC], 562)
        self.assertEqual(s["value_status"][sources.VALUE_UPPER_BOUND], 37)
        self.assertEqual(s["value_status"].get(sources.VALUE_INVALID, 0), 0)
        self.assertEqual(s["family_empty"], 33)
        self.assertEqual(s["doi_empty"], 0)
        self.assertEqual(s["duplicate_material_id"], 0)

    def test_all_rows_carry_doi(self):
        rows, _ = sources.read_obelix(self.path)
        self.assertTrue(all(r["source_doi"] for r in rows))

    def test_numeric_values_positive_and_finite(self):
        rows, _ = sources.read_obelix(self.path)
        vals = [float(r["conductivity_Scm"]) for r in rows
                if r["value_status"] == sources.VALUE_NUMERIC]
        self.assertEqual(len(vals), 562)
        self.assertTrue(all(v > 0 for v in vals))
        self.assertLessEqual(max(vals), 1.0)  # 物理合理上限，超出说明单位可能错

    def test_families_present(self):
        rows, _ = sources.read_obelix(self.path)
        fams = {r["family"] for r in rows if r["family"]}
        for expected in ("NASICON", "garnet", "argyrodites", "LGPS"):
            self.assertIn(expected, fams)


if __name__ == "__main__":
    unittest.main()
