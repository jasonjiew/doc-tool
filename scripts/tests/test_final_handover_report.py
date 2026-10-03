# -*- coding: utf-8 -*-
"""最终交接报告的一致性校验：报告必须与仓库当前状态一致。"""

from __future__ import annotations

import re
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT = REPO_ROOT / "docs" / "product-v3-final-report.md"


class FinalHandoverReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.release.report_final_handover import build_report, latest_junit

        cls.junit = latest_junit()
        cls.expected = build_report(cls.junit)
        REPORT.write_text(cls.expected, encoding="utf-8")

    def setUp(self):
        self.assertTrue(REPORT.is_file(), "缺少最终交接报告")
        self.text = REPORT.read_text(encoding="utf-8")

    @staticmethod
    def _without_timestamp(text: str) -> str:
        """生成时间每次运行都不同：比较时归一化该行，其余内容必须逐字一致。"""
        return re.sub(r"^生成时间：.*$", "生成时间：<归一化>", text, flags=re.MULTILINE)

    def test_report_matches_current_state(self):
        from scripts.release.report_final_handover import build_report, latest_junit

        self.assertEqual(
            self._without_timestamp(self.text),
            self._without_timestamp(build_report(latest_junit())),
            "报告与仓库当前状态不一致：请重新生成（python scripts\\release\\report_final_handover.py）",
        )

    def test_report_covers_all_changes_and_counts(self):
        from scripts.release.report_final_handover import task_counts

        counts = task_counts()
        total_done = sum(item["done"] for item in counts.values())
        total = total_done + sum(len(item["todo"]) for item in counts.values())
        self.assertIn("{0}/{1}".format(total_done, total), self.text)
        for change in (
            "product-core-import-export", "product-v30-content-reuse",
            "product-v31-team-workflow", "product-v32-batch-delivery",
            "product-v33-authoring-assistance",
        ):
            self.assertIn(change, self.text)
        for item in counts.values():
            for task_id in item["todo"]:
                self.assertIn(task_id, self.text, "报告未列出剩余任务：" + task_id)

    def test_artifact_paths_listed_actually_exist(self):
        for rel in (
            "dist/DocTool/DocTool.exe", "dist/DocTool/doc-tool-cli.exe",
            "docs/product-v3-handoff.md", "docs/product-v3-acceptance-runbook.md",
            "docs/product-v3-release-readiness.md",
        ):
            self.assertIn(rel, self.text, "报告未列出成果：" + rel)
            self.assertTrue((REPO_ROOT / rel).is_file(), "报告列出的产物不存在：" + rel)

    def test_report_is_linked_from_handoff_and_readiness(self):
        handoff = (REPO_ROOT / "docs" / "product-v3-handoff.md").read_text(encoding="utf-8")
        self.assertIn("product-v3-final-report.md", handoff)
        readiness = (REPO_ROOT / "docs" / "product-v3-release-readiness.md").read_text(encoding="utf-8")
        self.assertIn("product-v3-final-report.md", readiness)

    def test_report_states_uncommitted_status(self):
        self.assertIn("未提交", self.text)
        self.assertIn("未归档", self.text)

    def test_saved_report_count_does_not_grow_with_default_test_list(self):
        from scripts.release import report_final_handover as reporter

        summary = {"file": "old-run.xml", "files": 3, "tests": 3, "failures": 0, "errors": 0, "failed": []}
        with patch.object(reporter, "junit_summary", return_value=summary), patch.object(reporter, "registered_test_files", return_value=999):
            report = reporter.build_report()
        self.assertIn("**3 个测试文件 / 0 项失败 / 0 项错误**", report)
        self.assertIn("测试文件数 3／JUnit 用例数 3", report)
        self.assertIn("当前默认测试清单：999 文件", report)

    def test_junit_counts_runner_files_in_one_shared_suite(self):
        from scripts.release.report_final_handover import junit_summary

        scratch = REPO_ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="handover-count-", dir=scratch) as temp:
            report = Path(temp) / "run.xml"
            report.write_text('<testsuites><testsuite tests="3" failures="0"><testcase name="test_a.py" classname="scripts.tests"/><testcase name="test_b.py" classname="scripts.tests"/><testcase name="test_c.py" classname="scripts.tests"/></testsuite></testsuites>', encoding="utf-8")
            self.assertEqual(junit_summary(report)["files"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
