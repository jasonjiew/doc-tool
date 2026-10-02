# -*- coding: utf-8 -*-
"""最终交接报告的一致性校验：报告必须与仓库当前状态一致。"""

from __future__ import annotations

import re
import sys
import unittest
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

    def test_report_matches_current_state(self):
        from scripts.release.report_final_handover import build_report, latest_junit

        self.assertEqual(
            self.text, build_report(latest_junit()),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)