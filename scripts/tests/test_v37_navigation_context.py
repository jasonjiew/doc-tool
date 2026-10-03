# -*- coding: utf-8 -*-
"""37-B 2.1：来源跳转返回后恢复原页面、筛选与选中行。"""

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

from doc_tool.domain.content_index import FileEntry  # noqa: E402
from doc_tool.ui.navigation_history import NavLocation, NavigationHistory  # noqa: E402


class NavLocationViewStateTests(unittest.TestCase):
    def test_panel_and_view_round_trip_through_history(self):
        history = NavigationHistory("proj")
        history.record(
            NavLocation(
                rel_path="a.md", cursor=10, scroll=3, source="问题定位",
                panel="问题",
                view={"type": "link", "severity": "warning", "selected": "a.md:7:link"},
            )
        )
        history.record(NavLocation(rel_path="b.md", cursor=0, source="编辑"))
        target, _message = history.back()
        self.assertEqual(target.rel_path, "a.md")
        self.assertEqual(target.panel, "问题")
        self.assertEqual(target.view.get("severity"), "warning")
        self.assertEqual(target.view.get("selected"), "a.md:7:link")
        # 快照是深拷贝：改动返回对象不影响历史里的记录
        target.view["severity"] = "info"
        again, _message = history.forward()
        self.assertEqual(again.rel_path, "b.md")
        back_again, _message = history.back()
        self.assertEqual(back_again.view.get("severity"), "warning")

    def test_location_without_view_still_works(self):
        location = NavLocation(rel_path="a.md")
        self.assertEqual(location.panel, "")
        self.assertEqual(location.view, {})


class IssuesPanelViewStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from doc_tool.application.issues import IssueRecord
        from doc_tool.ui.content.issues_panel import IssuesPanel

        panel = IssuesPanel(show_document_type=False)
        issues = [
            IssueRecord(
                issue_type="link", severity="warning", rel_path="1 概述.md",
                line_no=7, message="悬空链接", source="validation",
                document_type="general", error_code="E-LINK",
            ),
            IssueRecord(
                issue_type="table", severity="error", rel_path="2 设计.md",
                line_no=3, message="表格列数不符", source="lint",
                document_type="general", error_code="E-TABLE",
            ),
        ]
        panel.set_issues(issues)
        return panel, issues

    def test_view_state_restores_filters_and_selected_row(self):
        panel, _issues = self._panel()
        combo = panel._type
        index = combo.findData("link")
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)
        panel._search_input.setText("悬空")
        panel._render()
        self.assertEqual(len(panel.filtered_issues()), 1)
        panel._tree.setCurrentItem(panel._tree.topLevelItem(0))
        state = panel.view_state()
        self.assertEqual(state.get("type"), "link")
        self.assertEqual(state.get("keyword"), "悬空")
        self.assertTrue(state.get("selected", "").startswith("1 概述.md:7"))

        # 清空筛选后按状态恢复
        panel.reset_filters()
        self.assertEqual(len(panel.filtered_issues()), 2)
        panel.restore_view_state(state)
        self.assertEqual(panel._selected(panel._type), "link")
        self.assertEqual(panel._search_input.text(), "悬空")
        self.assertEqual(len(panel.filtered_issues()), 1)
        current = panel._tree.currentItem()
        self.assertIsNotNone(current)

    def test_restore_ignores_stale_values(self):
        panel, _issues = self._panel()
        panel.restore_view_state(
            {"type": "不存在的类型", "severity": "warning", "selected": "gone.md:1:link"}
        )
        self.assertEqual(panel._selected(panel._type), "")
        self.assertEqual(panel._selected(panel._severity), "warning")

    def test_no_result_state_offers_clear_filters(self):
        panel, _issues = self._panel()
        panel._search_input.setText("不存在的关键词")
        panel._render()
        self.assertFalse(panel._clear_filters_btn.isHidden())
        panel._clear_filters_btn.click()
        self.assertEqual(len(panel.filtered_issues()), 2)
        self.assertTrue(panel._clear_filters_btn.isHidden())


if __name__ == "__main__":
    unittest.main()