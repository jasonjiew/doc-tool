# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tempfile
import unittest
from types import SimpleNamespace

from doc_tool.application.issues import (
    IssueRecord,
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
        self.assertEqual([r.severity for r in records], ["error", "warning"])
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

    def test_validation_report_check_name_not_merged_into_path(self):
        # validate_docx 生产报告形如 ``[FAIL] {check.name}: {detail}``；
        # 检查名不得并入 rel_path（旧正则把 ``章节编号错误:`` 一起吞进路径）。
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "requirement-validation.md"
            report.write_text(
                "- [FAIL] 章节编号错误: chapters/3.7.md:12 编号不连续\n"
                "- [FAIL] 内部标题层级跳跃: content/requirement/第1章 概述/_index.md:3\n",
                encoding="utf-8",
            )
            records = issues_from_validation_report(report, "requirement")
        self.assertEqual(len(records), 2)
        self.assertEqual((records[0].rel_path, records[0].line_no), ("chapters/3.7.md", 12))
        self.assertEqual(
            records[1].rel_path, "content/requirement/第1章 概述/_index.md"
        )
        self.assertEqual(records[1].line_no, 3)

    def test_pipeline_line_zero_is_kept(self):
        # 行号显式 0 时不得被 ``or`` 吞成 None。
        events = [
            SimpleNamespace(stage="build", status="failed", detail="x", error_code="E2001",
                            metrics={"line": 0, "lineNo": 7}),
            SimpleNamespace(stage="build", status="failed", detail="y", error_code="E2001",
                            metrics={"lineNo": 0}),
        ]
        records = issues_from_pipeline(events, "requirement")
        self.assertEqual([r.line_no for r in records], [0, 0])

    def test_lint_mapping_filter_and_summary(self):
        raw = [
            SimpleNamespace(rule="todo_residual", rel_path="a.md", line_no=2, message="TODO"),
            SimpleNamespace(rule="term_case", rel_path="b.md", line_no=4, message="gxpc"),
        ]
        records = issues_from_lint(raw, "design")
        self.assertEqual(severity_summary(records), {"error": 0, "warning": 1, "info": 1})
        self.assertEqual(filter_issues(records, severity="warning"), [records[0]])

    def test_filter_issues_with_keyword_and_category(self):
        records = [
            IssueRecord("lint", "heading_format", "general", "warning", "ch1/intro.md", 1, None, "标题缺少空格", "补全空格"),
            IssueRecord("lint", "markdown_structure", "general", "error", "ch2/table.md", 10, "E1001", "表格缺少分隔行", "补分隔行"),
            IssueRecord("validation", "validation", "general", "error", "ch3/ref.md", 5, "E2002", "引用丢失", "修复引用"),
            IssueRecord("pipeline", "build", "general", "error", "ch4/code.md", 20, "E3001", "代码块未闭合", "闭合代码块"),
        ]

        # 关键词检索消息
        res = filter_issues(records, keyword="空格")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].rel_path, "ch1/intro.md")

        # 关键词检索错误码
        res = filter_issues(records, keyword="E1001")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].issue_type, "markdown_structure")

        # 关键词检索路径
        res = filter_issues(records, keyword="ch3/ref")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].error_code, "E2002")

        # 关键词检索大小写无关
        res = filter_issues(records, keyword="e3001")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].rel_path, "ch4/code.md")

        # 类型 + 关键词筛选
        res = filter_issues(records, issue_type="markdown_structure", keyword="表格")
        self.assertEqual(len(res), 1)

        # 存在但关键词不匹配时返回空
        res = filter_issues(records, issue_type="markdown_structure", keyword="无此词")
        self.assertEqual(len(res), 0)

        # 严重度 + 关键词筛选
        res = filter_issues(records, severity="error", keyword="代码块")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].issue_type, "build")

        # 检索规则中文标签（如“标题格式”）
        res_cn = filter_issues(records, keyword="标题格式")
        self.assertEqual(len(res_cn), 1)
        self.assertEqual(res_cn[0].issue_type, "heading_format")

        # 检索严重度中文标签（如“阻断”）
        res_sev = filter_issues(records, keyword="阻断")
        self.assertEqual(len(res_sev), 3)

        # 检索分类大类名称（如“格式规范”）
        res_cat = filter_issues(records, keyword="格式规范")
        self.assertEqual(len(res_cat), 2)
        self.assertTrue(all(r.issue_type in ("heading_format", "markdown_structure") for r in res_cat))

        # 多词联合检索（空格分隔）
        res_multi = filter_issues(records, keyword="ch1 补全空格")
        self.assertEqual(len(res_multi), 1)
        self.assertEqual(res_multi[0].rel_path, "ch1/intro.md")

        # 不匹配关键词返回空
        res = filter_issues(records, keyword="not_exist_word")
        self.assertEqual(len(res), 0)

    def test_issues_from_lint_preserves_rule_id(self):
        raw = [
            SimpleNamespace(rule="heading_format", rule_id="heading_format", rel_path="a.md", line_no=1, message="空格"),
            SimpleNamespace(rule="", rule_id="markdown_structure", rel_path="b.md", line_no=2, message="表格"),
        ]
        records = issues_from_lint(raw, "general")
        self.assertEqual([r.issue_type for r in records], ["heading_format", "markdown_structure"])


if __name__ == "__main__":
    unittest.main()
