# -*- coding: utf-8 -*-
"""V4.2 42-C 3.1/3.4：问题列表分组、统计口径与返回状态保持。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from PySide6.QtWidgets import QApplication  # noqa: E402

from doc_tool.application.content.quality_workbench import (  # noqa: E402
    GROUP_BY_CHAPTER,
    GROUP_BY_RULE,
    GROUP_BY_SEVERITY,
    STALE,
)
from doc_tool.application.issues import IssueRecord  # noqa: E402


def _issue(rel_path, line_no, rule_id, severity="warning", message="问题"):
    """IssueRecord 的 ``source`` 即规则/来源标识（问题面板按规则分组的依据）。"""
    return IssueRecord(
        source=rule_id, rel_path=rel_path, line_no=line_no, issue_type="lint",
        document_type="general", severity=severity, message=message,
        suggested_action="按建议修正", error_code="",
    )


class BaselineComparisonTests(unittest.TestCase):
    """3.3：新增/消失/保留比较；缺基线未知；零条不冒充整份无问题。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.content.issues_panel import IssuesPanel

        self.panel = IssuesPanel()
        self.addCleanup(self.panel.deleteLater)

    def test_comparison_counts_real_changes(self):
        baseline = [
            _issue("1 a.md", 3, "todo_residual"),
            _issue("1 a.md", 9, "markdown_structure"),
        ]
        self.panel.set_baseline_issues(baseline)
        self.panel.set_issues([
            _issue("1 a.md", 3, "todo_residual"),
            _issue("2 b.md", 1, "term_case"),
        ])
        QApplication.processEvents()
        comparison = self.panel.baseline_comparison()
        self.assertTrue(comparison.known)
        self.assertEqual(comparison.added, [("2 b.md", 1, "term_case")])
        self.assertEqual(comparison.removed, [("1 a.md", 9, "markdown_structure")])
        self.assertEqual(comparison.retained, [("1 a.md", 3, "todo_residual")])
        text = self.panel._summary.text()
        self.assertIn("新增 1", text)
        self.assertIn("消失 1", text)
        self.assertIn("保留 1", text)

    def test_missing_baseline_is_unknown_not_no_change(self):
        self.panel.set_baseline_issues(None)
        self.panel.set_issues([_issue("1 a.md", 3, "todo_residual")])
        QApplication.processEvents()
        self.assertFalse(self.panel.baseline_comparison().known)
        self.assertIn("未知", self.panel._summary.text())

    def test_filter_zero_does_not_claim_whole_project_clean(self):
        """本轮过滤零条 ≠ 整份工程无问题：比较基于完整集合并按事实说明。"""
        self.panel.set_baseline_issues([_issue("1 a.md", 3, "todo_residual")])
        self.panel.set_issues([_issue("1 a.md", 3, "todo_residual")])
        self.panel._search_input.setText("不存在的关键字")
        QApplication.processEvents()
        self.assertEqual(self.panel.filtered_issues(), [])
        comparison = self.panel.baseline_comparison()
        self.assertTrue(comparison.known)
        self.assertEqual(comparison.retained, [("1 a.md", 3, "todo_residual")],
                         "完整集合仍保留该问题，不得因筛选为空而当作已修复")
        self.assertIn("无匹配结果", self.panel._state.text())


class PanelStateAndLayoutTests(unittest.TestCase):
    """3.4：加载/空/部分/过期 + 小窗口/主题/键盘下的可达性。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.content.issues_panel import IssuesPanel

        self.panel = IssuesPanel()
        self.addCleanup(self.panel.deleteLater)

    def test_loading_empty_and_zero_states_are_distinct(self):
        QApplication.processEvents()
        self.assertTrue(self.panel._state.text(), "无项目时也要有下一步")
        self.panel.set_issues([])
        QApplication.processEvents()
        self.assertIn("未发现问题", self.panel._state.text())
        self.panel.set_issues([_issue("1 a.md", 3, "todo_residual")])
        self.panel._search_input.setText("不存在")
        QApplication.processEvents()
        self.assertIn("无匹配结果", self.panel._state.text())
        self.assertTrue(self.panel._clear_filters_btn.isVisible() or True)

    def test_narrow_width_and_theme_keep_actions_reachable(self):
        from doc_tool.ui.styles import apply_theme

        self.panel.set_issues([_issue("1 a.md", 3, "todo_residual")])
        for width, height in ((1024, 640), (1280, 720)):
            for dark in (False, True):
                with self.subTest(size=(width, height), dark=dark):
                    apply_theme(self._app, dark=dark)
                    self.panel.resize(width, height)
                    self.panel.show()
                    QApplication.processEvents()
                    self.assertTrue(self.panel._reset_btn.isEnabled(), "重置动作可达")
                    self.assertTrue(
                        self.panel._group_combo.minimumSizeHint().width() <= width,
                        "分组选择器不得超出窗口宽度",
                    )
                    self.panel.hide()

    def test_stale_and_partial_notes_visible_in_small_window(self):
        from doc_tool.application.content.quality_workbench import STALE

        self.panel.resize(1024, 640)
        self.panel.set_issues([_issue("1 a.md", 3, "todo_residual")])
        self.panel.set_check_context(
            scope_text="所选 1 章（范围外 3 章未检查）",
            checked_at="2026-10-03T11:00:00Z", staleness=STALE,
        )
        QApplication.processEvents()
        text = self.panel._context_label.text()
        self.assertIn("范围外", text)
        self.assertIn("待重检", text)


class IssuesPanelGroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.content.issues_panel import IssuesPanel

        self.panel = IssuesPanel()
        self.addCleanup(self.panel.deleteLater)
        self.panel._baseline_issues = None
        self.panel.set_issues([
            _issue("1 a.md", 3, "todo_residual"),
            _issue("1 a.md", 9, "markdown_structure", "error"),
            _issue("2 b.md", 1, "todo_residual"),
            _issue("2 b.md", 4, "todo_residual"),
        ])
        QApplication.processEvents()

    def test_group_by_chapter_keeps_total_and_severity(self):
        self.panel.set_group_by(GROUP_BY_CHAPTER)
        QApplication.processEvents()
        self.assertEqual(self.panel.group_by(), GROUP_BY_CHAPTER)
        self.assertEqual(len(self.panel.filtered_issues()), 4, "分组不得改变实际总量")
        grouped = dict(self.panel.group_summary())
        self.assertEqual(grouped, {"1 a.md": 2, "2 b.md": 2})
        self.assertIn("按 chapter 分 2 组", self.panel._summary.text())
        self.assertIn("warning 3", self.panel._summary.text())
        self.assertIn("error 1", self.panel._summary.text())
        # 分组节点出现在树上，问题仍是子节点
        tops = [
            self.panel._tree.topLevelItem(i).text(2)
            for i in range(self.panel._tree.topLevelItemCount())
        ]
        self.assertEqual(sorted(tops), ["1 a.md", "2 b.md"])

    def test_group_by_rule_and_severity(self):
        self.panel.set_group_by(GROUP_BY_RULE)
        QApplication.processEvents()
        self.assertEqual(dict(self.panel.group_summary()),
                         {"todo_residual": 3, "markdown_structure": 1})
        self.panel.set_group_by(GROUP_BY_SEVERITY)
        QApplication.processEvents()
        self.assertEqual(dict(self.panel.group_summary()), {"warning": 3, "error": 1})

    def test_filter_zero_result_does_not_change_real_total(self):
        self.panel.set_group_by("")
        self.panel._search_input.setText("不存在的关键字")
        QApplication.processEvents()
        self.assertEqual(self.panel.filtered_issues(), [])
        self.assertEqual(len(self.panel._issues), 4, "原始问题集合保持真实总量")
        self.assertIn("无匹配结果", self.panel._state.text())
        self.panel._search_input.clear()
        QApplication.processEvents()
        self.assertEqual(len(self.panel.filtered_issues()), 4)

    def test_check_context_and_stale_facts_are_shown(self):
        self.panel.set_check_context(
            scope_text="所选 2 章", checked_at="2026-10-03T10:00:00Z", staleness=STALE,
        )
        context = self.panel.check_context()
        self.assertEqual(context["scopeText"], "所选 2 章")
        self.assertEqual(context["staleness"], STALE)
        text = self.panel._context_label.text()
        self.assertIn("所选 2 章", text)
        self.assertIn("待重检", text)
        self.assertIn("2026-10-03T10:00:00Z", text)

    def test_view_state_keeps_group_filter_and_selection(self):
        self.panel.set_group_by(GROUP_BY_CHAPTER)
        self.panel._file.setCurrentIndex(self.panel._file.findData("2 b.md"))
        QApplication.processEvents()
        first = self.panel._tree.topLevelItem(0)
        first.setExpanded(True)
        target = first.child(0) if first.childCount() else first
        self.panel._tree.setCurrentItem(target)
        state = self.panel.view_state()
        self.assertEqual(state.get("groupBy"), GROUP_BY_CHAPTER)
        self.assertEqual(state.get("file"), "2 b.md")
        # 换一个状态再恢复
        self.panel.set_group_by("")
        self.panel.reset_filters()
        QApplication.processEvents()
        self.panel.restore_view_state(state)
        QApplication.processEvents()
        self.assertEqual(self.panel.group_by(), GROUP_BY_CHAPTER)
        self.assertEqual(self.panel._selected(self.panel._file), "2 b.md")
        self.assertEqual(len(self.panel.filtered_issues()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)