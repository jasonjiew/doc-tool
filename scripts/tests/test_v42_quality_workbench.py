# -*- coding: utf-8 -*-
"""V4.2 42-C：问题工作台分组、时点、过期与基线比较。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content import quality_workbench as qw  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.lint import ContentLinter  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402
from doc_tool.application.intake_contract import ExportScope  # noqa: E402


class _Issue:
    def __init__(self, rel_path, line_no, rule_id, severity="warning"):
        self.rel_path = rel_path
        self.line_no = line_no
        self.rule_id = rule_id
        self.rule = rule_id
        self.severity = severity


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.issues = [
            _Issue("1 a.md", 3, "todo_residual"),
            _Issue("1 a.md", 9, "markdown_structure", "error"),
            _Issue("2 b.md", 1, "todo_residual"),
            _Issue("2 b.md", 4, "todo_residual"),
        ]

    def test_group_by_chapter_keeps_real_total(self):
        grouped = qw.group_issues(self.issues, by=qw.GROUP_BY_CHAPTER)
        self.assertEqual(sorted(grouped), ["1 a.md", "2 b.md"])
        self.assertEqual(sum(len(value) for value in grouped.values()), 4, "分组不得丢条目")
        self.assertEqual(qw.group_summary(self.issues, by=qw.GROUP_BY_CHAPTER),
                         [("1 a.md", 2), ("2 b.md", 2)])

    def test_group_by_rule_and_severity(self):
        by_rule = dict(qw.group_summary(self.issues, by=qw.GROUP_BY_RULE))
        self.assertEqual(by_rule, {"todo_residual": 3, "markdown_structure": 1})
        by_sev = dict(qw.group_summary(self.issues, by=qw.GROUP_BY_SEVERITY))
        self.assertEqual(by_sev, {"warning": 3, "error": 1})
        self.assertEqual(qw.severity_totals(self.issues), {"warning": 3, "error": 1})

    def test_unknown_dimension_is_rejected(self):
        with self.assertRaises(ValueError):
            qw.group_issues(self.issues, by="whatever")


class SnapshotAndStalenessTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-c-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.work / ".state").mkdir(exist_ok=True)
        (self.content / "1 a.md").write_text("# A\n\nTODO: 待办\n", encoding="utf-8")
        (self.content / "2 b.md").write_text("# B\n\n正文。\n", encoding="utf-8")
        self.config = QualityRulesConfig(self.work / ".state", "general")

    def _check(self, scope=None):
        index = ContentIndexService(self.content).build()
        issues = ContentLinter(index, self.config, use_result_cache=False).check_all([])
        return qw.IssueSnapshot.build(issues, index=index, scope=scope)

    def test_snapshot_records_real_scope_and_time(self):
        snapshot = self._check(ExportScope(kind="chapters", chapters=["1 a.md"]))
        self.assertEqual(snapshot.scopeText, "所选 1 章")
        self.assertEqual(snapshot.scopeChapters, ["1 a.md"])
        self.assertTrue(snapshot.checkedAt)
        self.assertEqual(len(snapshot.contentDigest), 64)
        full = self._check()
        self.assertEqual(full.scopeText, "整份")

    def test_content_change_marks_stale(self):
        snapshot = self._check()
        index = ContentIndexService(self.content).build()
        self.assertEqual(qw.staleness(snapshot, index=index), qw.FRESH)
        (self.content / "1 a.md").write_text("# A\n\nTODO: 改了\n", encoding="utf-8")
        changed_index = ContentIndexService(self.content).build()
        self.assertEqual(qw.staleness(snapshot, index=changed_index), qw.STALE)

    def test_rule_signature_change_marks_stale(self):
        snapshot = self._check()
        snapshot.ruleSignature = "sig-1"
        index = ContentIndexService(self.content).build()
        self.assertEqual(
            qw.staleness(snapshot, index=index, rules_signature="sig-2"), qw.STALE
        )

    def test_missing_evidence_is_unknown_not_fresh(self):
        self.assertEqual(qw.staleness(None, index=None), qw.UNKNOWN)
        snapshot = self._check()
        snapshot.contentDigest = ""
        index = ContentIndexService(self.content).build()
        self.assertEqual(qw.staleness(snapshot, index=index), qw.UNKNOWN)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.base = [
            _Issue("1 a.md", 3, "todo_residual"),
            _Issue("1 a.md", 9, "markdown_structure"),
        ]
        self.now = [
            _Issue("1 a.md", 3, "todo_residual"),
            _Issue("2 b.md", 1, "term_case"),
        ]

    def _snap(self, issues):
        snapshot = qw.IssueSnapshot(scopeText="整份", contentDigest="x")
        snapshot.issues = list(issues)
        return snapshot

    def test_added_removed_retained(self):
        comparison = qw.compare_snapshots(self._snap(self.base), self._snap(self.now))
        self.assertTrue(comparison.known)
        self.assertEqual(comparison.added, [("2 b.md", 1, "term_case")])
        self.assertEqual(comparison.removed, [("1 a.md", 9, "markdown_structure")])
        self.assertEqual(comparison.retained, [("1 a.md", 3, "todo_residual")])
        self.assertIn("新增 1", "\n".join(comparison.summary_lines()))

    def test_missing_baseline_is_unknown(self):
        comparison = qw.compare_snapshots(None, self._snap(self.now))
        self.assertFalse(comparison.known)
        self.assertIn("未知", "\n".join(comparison.summary_lines()))
        self.assertEqual(comparison.added, [], "缺基线不得冒充全部新增")

    def test_empty_current_is_not_reported_as_all_cleared_without_baseline(self):
        comparison = qw.compare_snapshots(None, self._snap([]))
        self.assertFalse(comparison.known)

    def test_current_view_note_keeps_report_facts(self):
        self.assertIn("正式报告仍保留全部 5 条", qw.current_view_note(2, 5))
        self.assertIn("全部 3 条", qw.current_view_note(0, 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)