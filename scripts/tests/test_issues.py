# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from doc_tool.application.issues import (
    filter_issues,
    issues_from_lint,
    issues_from_pipeline,
    issues_from_validation_report,
    severity_summary,
)


class IssueNormalizationTests(unittest.TestCase):
    def test_pipeline_known_and_unknown_error_codes(self):
        events = [
            SimpleNamespace(stage="build", status="failed", detail="构建失败", error_code="E2001", metrics={}),
            SimpleNamespace(stage="validate_pre", status="failed", detail="未知", error_code="E7777", metrics={}),
        ]
        records = issues_from_pipeline(events, "requirement")
        self.assertEqual([r.severity for r in records], ["error", "info"])
        self.assertEqual(records[0].suggested_action, "请查看日志中的阶段和错误详情。")
        self.assertEqual(records[1].error_code, "E7777")

    def test_validation_report_location_and_missing_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "requirement-validation.md"
            report.write_text(
                "- [PASS] 正常\n- [FAIL] chapters/3.7.md:12 编号不连续\n"
                "- [FAIL] 无法解析的普通失败\n- [FAIL] \n",
                encoding="utf-8",
            )
            records = issues_from_validation_report(report, "requirement")
        self.assertEqual(len(records), 3)
        self.assertEqual((records[0].rel_path, records[0].line_no), ("chapters/3.7.md", 12))
        self.assertIsNone(records[1].line_no)
        self.assertIn("缺少说明", records[2].message)

    def test_validation_report_location_with_spaces_in_path(self):
        # 章节目录名可含空格与中文（``第1章 概述/_index.md:3``）；旧字符类
        # 正则把路径截断到空格处（得到 ``概述/_index.md``），用户无法定位到文件。
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "requirement-validation.md"
            report.write_text(
                "- [FAIL] content/requirement/第1章 概述/_index.md:3 内部标题层级跳跃\n",
                encoding="utf-8",
            )
            records = issues_from_validation_report(report, "requirement")
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].rel_path, "content/requirement/第1章 概述/_index.md"
        )
        self.assertEqual(records[0].line_no, 3)

    def test_lint_mapping_filter_and_summary(self):
        raw = [
            SimpleNamespace(rule="todo_residual", rel_path="a.md", line_no=2, message="TODO"),
            SimpleNamespace(rule="term_case", rel_path="b.md", line_no=4, message="kshc"),
        ]
        records = issues_from_lint(raw, "design")
        self.assertEqual(severity_summary(records), {"error": 0, "warning": 1, "info": 1})
        self.assertEqual(filter_issues(records, severity="warning"), [records[0]])


if __name__ == "__main__":
    unittest.main()
