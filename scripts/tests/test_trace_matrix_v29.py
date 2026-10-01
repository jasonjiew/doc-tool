# -*- coding: utf-8 -*-
"""V2.9 29-D\uff1a\u77e9\u9635\u3001\u53ef\u89e3\u91ca\u8986\u76d6\u7387\u4e0e\u5bfc\u51fa\uff084.1\uff5e4.5\uff09\u3002"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.relations import Endpoint, RelationGraph, add_relation  # noqa: E402
from doc_tool.application.content.trace_matrix import (  # noqa: E402
    build_coverage,
    endpoint_for,
    export_report,
)
from doc_tool.application.content.traceable_items import ItemRef  # noqa: E402

P = "proj-req"
PD = "proj-design"
PT = "proj-test"


def _ref(kind, name):
    return ItemRef(project_id={"requirement": P, "design": PD, "test": PT}[kind], item_id=name, kind=kind)


def _link(graph, relation_type, source, target):
    add_relation(
        graph,
        relation_type=relation_type,
        source=endpoint_for(source),
        target=endpoint_for(target),
    )


class CoverageTests(unittest.TestCase):
    """4.2\uff1a\u6bcd\u3001\u76f4\u63a5/\u95f4\u63a5\u4e0e N/A\u3002"""

    def setUp(self):
        self.r1 = _ref("requirement", "req-1")
        self.r2 = _ref("requirement", "req-2")
        self.d1 = _ref("design", "des-1")
        self.t1 = _ref("test", "tst-1")
        self.t2 = _ref("test", "tst-2")

    def test_full_chain_counts_direct_and_indirect(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        _link(graph, "verifies", self.t1, self.r1)          # \u76f4\u63a5\u9a8c\u8bc1\u9700\u6c42
        _link(graph, "verifies", self.d1, self.t2)          # \u8bbe\u8ba1 \u2192 \u6d4b\u8bd5\uff08\u95f4\u63a5\uff09
        report = build_coverage([self.r1, self.r2, self.d1, self.t1, self.t2], graph)
        self.assertEqual(report.total_requirements, 2)
        self.assertEqual(report.design_coverage, 0.5)
        self.assertEqual(report.direct_coverage, 0.5)
        self.assertEqual(report.test_coverage, 0.5)
        row = report.rows[0]
        self.assertEqual([ref.item_id for ref in row.direct_tests], ["tst-1"])
        self.assertEqual([ref.item_id for ref in row.indirect_tests], ["tst-2"])
        self.assertTrue(row.covered)
        self.assertFalse(report.rows[1].covered)

    def test_no_requirements_is_na_not_zero(self):
        report = build_coverage([self.d1, self.t1], RelationGraph())
        self.assertFalse(report.applicable)
        self.assertIsNone(report.design_coverage)
        self.assertIsNone(report.test_coverage)
        self.assertIn("N/A", report.markdown_text())
        self.assertNotIn("0.0%", report.markdown_text())

    def test_duplicate_verifies_edges_do_not_double_count(self):
        graph = RelationGraph()
        _link(graph, "verifies", self.t1, self.r1)
        _link(graph, "verifies", self.t1, self.r1)
        report = build_coverage([self.r1, self.t1], graph)
        self.assertEqual(len(report.rows[0].direct_tests), 1)
        self.assertEqual(report.test_coverage, 1.0)

    def test_orphans_and_dangling_reported(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        _link(graph, "verifies", self.t1, self.r2)  # r2 \u4e0d\u5b58\u5728 \u2192 \u60ac\u7a7a
        report = build_coverage([self.r1, self.d1, self.t2], graph)
        self.assertTrue(report.dangling)
        self.assertEqual([ref.item_id for ref in report.test_orphans], ["tst-2"])

    def test_pending_review_not_counted_as_confirmed(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        report = build_coverage(
            [self.r1, self.d1], graph,
            pending_review_items=[self.d1.key], confirmed_items=[],
        )
        self.assertEqual(report.pending_review, 1)
        self.assertEqual(report.linked, 0)
        self.assertEqual(report.review_coverage, 0.0)
        report2 = build_coverage(
            [self.r1, self.d1], graph,
            pending_review_items=[], confirmed_items=[self.d1.key],
        )
        self.assertEqual(report2.linked, 1)
        self.assertEqual(report2.review_coverage, 1.0)

    def test_unmarked_content_never_in_denominator(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        # \u53ea\u58f0\u660e\u4e00\u6761\u9700\u6c42\u6761\u76ee\uff1a\u5206\u6bcd\u5373 1\uff0c\u4e0d\u53d7\u5176\u4ed6\u6b63\u6587\u5f71\u54cd
        report = build_coverage([self.r1, self.d1], graph)
        self.assertEqual(report.total_requirements, 1)
        self.assertEqual(report.design_coverage, 1.0)

    def test_no_false_hundred_percent(self):
        """\u4ec5\u6709\u90e8\u5206\u9700\u6c42\u88ab\u8986\u76d6\u65f6\u4e0d\u5f97\u62a5 100%\u3002"""
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        report = build_coverage([self.r1, self.r2, self.d1], graph)
        self.assertNotEqual(report.design_coverage, 1.0)
        self.assertEqual(report.design_coverage, 0.5)


class ExportTests(unittest.TestCase):
    """4.4\uff1aJSON/CSV/Markdown \u540c\u6e90\u4e14\u987a\u5e8f\u786e\u5b9a\u3002"""

    def setUp(self):
        self.r1 = _ref("requirement", "req-1")
        self.d1 = _ref("design", "des-1")
        self.t1 = _ref("test", "tst-1")
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        _link(graph, "verifies", self.t1, self.r1)
        self.report = build_coverage([self.r1, self.d1, self.t1], graph)

    def test_json_export_has_stable_keys(self):
        data = json.loads(export_report(self.report, "json"))
        for key in (
            "applicable", "totalRequirements", "designCoverage", "testCoverage",
            "directTestCoverage", "reviewCoverage", "rows", "dangling",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["testCoverage"], 1.0)

    def test_csv_export_is_parseable_and_deterministic(self):
        text = export_report(self.report, "csv")
        lines = text.strip().splitlines()
        self.assertEqual(
            lines[0], "requirementId,requirementAlias,designIds,directTestIds,indirectTestIds,covered"
        )
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("req-1"))

    def test_markdown_and_json_agree_on_numbers(self):
        md = export_report(self.report, "markdown")
        data = json.loads(export_report(self.report, "json"))
        self.assertIn("{0:.1f}%".format(data["testCoverage"] * 100), md)
        self.assertIn("{0:.1f}%".format(data["designCoverage"] * 100), md)

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            export_report(self.report, "xml")

    def test_repeated_export_is_identical(self):
        first = export_report(self.report, "csv")
        second = export_report(self.report, "csv")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()