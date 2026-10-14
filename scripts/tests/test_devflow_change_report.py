# -*- coding: utf-8 -*-
"""回归测试：变更报告（change-report）、JUnit 解析、多仓证据与 MR 附件生成。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from doc_tool.application.change_report import (
    generate_change_report,
    parse_junit_xml,
    parse_manual_evidence,
)


class DevFlowChangeReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        # 构造有效 JUnit XML
        self.junit_ok = self.root / "junit_ok.xml"
        self.junit_ok.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<testsuites tests="2" failures="0" errors="0" skipped="0">\n'
            '  <testsuite name="SuiteA" tests="2" failures="0" errors="0" skipped="0">\n'
            '    <testcase name="test_one" classname="pkg.TestA" time="0.10"/>\n'
            '    <testcase name="test_two" classname="pkg.TestA" time="0.20"/>\n'
            '  </testsuite>\n'
            '</testsuites>\n',
            encoding="utf-8",
        )

        # 构造含跳过与失败的 JUnit XML
        self.junit_fail = self.root / "junit_fail.xml"
        self.junit_fail.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<testsuite name="SuiteB" tests="3" failures="1" errors="0" skipped="1">\n'
            '  <testcase name="test_pass" classname="pkg.TestB" time="0.05"/>\n'
            '  <testcase name="test_skip" classname="pkg.TestB">\n'
            '    <skipped message="环境无Word，跳过此用例"/>\n'
            '  </testcase>\n'
            '  <testcase name="test_error" classname="pkg.TestB">\n'
            '    <failure message="断言失败：预期 0 实际 1">详情堆栈</failure>\n'
            '  </testcase>\n'
            '</testsuite>\n',
            encoding="utf-8",
        )

        # 构造损坏与空 JUnit
        self.junit_empty = self.root / "empty.xml"
        self.junit_empty.write_text("   \n", encoding="utf-8")

        self.junit_corrupted = self.root / "corrupt.xml"
        self.junit_corrupted.write_text("<testsuite><not-closed>", encoding="utf-8")

        # 构造多仓 Git 证据 JSON
        self.git_ev1 = self.root / "repo1_git.json"
        self.git_ev1.write_text(
            json.dumps({
                "schemaVersion": 1,
                "repository": "D:/workspace/backend",
                "branch": "main",
                "head": "1111222233334444",
                "base": "0000111122223333",
                "committedBaseToHead": ["M  src/main/App.java"],
                "staged": [],
                "unstaged": [],
                "diagnostics": [],
            }),
            encoding="utf-8",
        )

        self.git_ev2 = self.root / "repo2_git.json"
        self.git_ev2.write_text(
            json.dumps({
                "schemaVersion": 1,
                "repository": "D:/workspace/frontend",
                "branch": "feat/login",
                "head": "aaaabbbbccccdddd",
                "base": "9999aaaabbbbcccc",
                "committedBaseToHead": ["M  src/views/Login.vue"],
                "staged": ["M  src/views/Login.vue"],
                "unstaged": [],
                "diagnostics": ["warn: untracked files exist"],
            }),
            encoding="utf-8",
        )

        # 构造人工验收证据
        self.manual_ev = self.root / "manual.json"
        self.manual_ev.write_text(
            json.dumps([
                {
                    "id": "TC-MANUAL-01",
                    "description": "干净 Windows 桌面双击启动",
                    "status": "passed",
                    "author": "张工",
                    "date": "2026-10-14",
                    "reason": "实机验证成功",
                },
                {
                    "id": "TC-MANUAL-02",
                    "description": "Word COM 目录刷新",
                    "status": "not-applicable",
                    "author": "李工",
                    "date": "2026-10-14",
                    "reason": "CI 容器无桌面 Office 环境，由换机服务补刷",
                },
            ]),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_junit_ok_and_failure(self):
        ok = parse_junit_xml(self.junit_ok)
        self.assertEqual(ok["status"], "passed")
        self.assertEqual(ok["tests"], 2)
        self.assertEqual(ok["failures"], 0)

        fail = parse_junit_xml(self.junit_fail)
        self.assertEqual(fail["status"], "failed")
        self.assertEqual(fail["tests"], 3)
        self.assertEqual(fail["failures"], 1)
        self.assertEqual(fail["skipped"], 1)

    def test_parse_junit_blocked_on_empty_and_corrupt(self):
        emp = parse_junit_xml(self.junit_empty)
        self.assertEqual(emp["status"], "blocked")

        corrupt = parse_junit_xml(self.junit_corrupted)
        self.assertEqual(corrupt["status"], "blocked")

    def test_affected_items_without_slash_and_tool_metadata(self):
        report = generate_change_report(
            change_id="change-no-slash",
            git_evidence_files=[self.git_ev1],
            junit_files=[self.junit_ok],
            manual_evidence_files=[self.manual_ev],
            affected_items=["REQ-01"],
            project_root=self.root,
        )
        self.assertIn("tool", report)
        self.assertEqual(report["tool"]["name"], "doc-tool")
        self.assertIn("REQ-01", report["documentation"]["impactedItems"])

    def test_blocked_junit_causes_incomplete_and_reported_in_gaps(self):
        report = generate_change_report(
            change_id="change-blocked",
            git_evidence_files=[self.git_ev1],
            junit_files=[self.junit_corrupted],
        )
        self.assertEqual(report["verdict"], "incomplete")
        self.assertEqual(report["exitCode"], 1)
        self.assertTrue(any("阻断异常" in g for g in report["gapsAndRisks"]))

    def test_generate_change_report_full_passed(self):
        report = generate_change_report(
            change_id="change-20261014-01",
            openspec_ref="doc-tool/openspec/changes/sample",
            gitlab_mr_ref="!42",
            git_evidence_files=[self.git_ev1],
            junit_files=[self.junit_ok],
            manual_evidence_files=[self.manual_ev],
            no_doc_change_reason="无需修改文档：纯后端性能优化",
        )
        self.assertEqual(report["verdict"], "passed")
        self.assertEqual(report["exitCode"], 0)
        self.assertEqual(len(report["gapsAndRisks"]), 0)
        self.assertIn("## 变更与交付验证报告：change-20261014-01", report["mrMarkdown"])
        self.assertIn("TC-MANUAL-01", report["mrMarkdown"])

    def test_generate_change_report_with_failure_and_dirty_gaps(self):
        # 包含失败用例和脏工作树 repo2
        report = generate_change_report(
            change_id="change-20261014-02",
            git_evidence_files=[self.git_ev1, self.git_ev2],
            junit_files=[self.junit_fail],
            manual_evidence_files=[],
            no_doc_change_reason="",
        )
        self.assertEqual(report["verdict"], "failed")
        self.assertEqual(report["exitCode"], 1)
        self.assertTrue(any("frontend" in g and "改动" in g for g in report["gapsAndRisks"]))
        self.assertTrue(any("skipped" in g for g in report["gapsAndRisks"]))
        self.assertTrue(any("文档" in g for g in report["gapsAndRisks"]))


if __name__ == "__main__":
    unittest.main()
