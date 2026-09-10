# -*- coding: utf-8 -*-
"""测试改动面板刷新功能 (ChangesPanel & ContentWorkspace refresh)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChangesPanelRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.content_root = Path(self.temp_dir) / "content"
        self.content_root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_panel(self, on_refresh=None):
        from doc_tool.application.content.changes import ChangeItem
        from doc_tool.ui.content.changes_panel import ChangesPanel

        snapshot = SimpleNamespace(
            content_of=lambda path: "baseline text\n",
            diff=lambda root, files: {},
        )
        writer = SimpleNamespace(
            manifest=SimpleNamespace(entries=[]),
            resolve=lambda p: self.content_root / p,
        )

        panel = ChangesPanel(
            snapshot=snapshot,
            writer=writer,
            content_root=self.content_root,
            on_refresh=on_refresh,
        )
        return panel

    def test_refresh_button_exists_and_connected(self):
        called = []
        panel = self._make_panel(on_refresh=lambda: called.append(True))

        self.assertTrue(hasattr(panel, "_refresh_btn"))
        self.assertEqual(panel._refresh_btn.text(), "刷新")
        self.assertIn("刷新", panel._refresh_btn.toolTip())
        self.assertTrue(panel._refresh_btn.isEnabled())

        # 点击按钮触发刷新回调
        panel._refresh_btn.click()
        self.assertEqual(len(called), 1)

        # 调用 public refresh() 触发回调
        panel.refresh()
        self.assertEqual(len(called), 2)

    def test_refresh_without_callback_does_not_crash(self):
        from doc_tool.application.content.changes import ChangeItem

        panel = self._make_panel(on_refresh=None)

        # 写入一个文件
        test_file = self.content_root / "01.md"
        test_file.write_text("modified content\n", encoding="utf-8")

        item = ChangeItem(
            rel_path="01.md",
            status="modified",
            baseline_rel_path="01.md",
            restorable=True,
        )
        panel.set_items([item])
        self.assertEqual(panel._list.count(), 1)

        # 默认无回调时刷新正常执行，重新填充与渲染
        panel.refresh()
        self.assertEqual(panel._list.count(), 1)

    def test_context_menu_has_refresh_action(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMenu
        from doc_tool.application.content.changes import ChangeItem

        panel = self._make_panel()
        item = ChangeItem(
            rel_path="01.md",
            status="modified",
            baseline_rel_path="01.md",
            restorable=True,
        )
        panel.set_items([item])

        created_menus = []

        class NonBlockingMenu(QMenu):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created_menus.append(self)

            def exec(self, *args, **kwargs):
                return None

            def exec_(self, *args, **kwargs):
                return None

        with patch("doc_tool.ui.content.changes_panel.QMenu", NonBlockingMenu):
            # 1. 右键在空白处弹出菜单
            panel._show_list_context_menu(QPoint(999, 999))
            self.assertEqual(len(created_menus), 1)
            actions = [act.text() for act in created_menus[-1].actions()]
            self.assertIn("刷新改动列表", actions)

            # 2. 右键在条目上弹出菜单
            item_rect = panel._list.visualItemRect(panel._list.item(0))
            panel._show_list_context_menu(item_rect.center())
            self.assertEqual(len(created_menus), 2)
            actions2 = [act.text() for act in created_menus[-1].actions()]
            self.assertIn("刷新改动列表", actions2)

    def test_set_items_rerenders_selected_diff(self):
        from doc_tool.application.content.changes import ChangeItem

        panel = self._make_panel()
        file1 = self.content_root / "01.md"
        file1.write_text("v1\n", encoding="utf-8")

        item = ChangeItem(
            rel_path="01.md",
            status="modified",
            baseline_rel_path="01.md",
            restorable=True,
        )
        panel.set_items([item])

        # 选中项
        panel._list.setCurrentRow(0)
        self.assertIn("v1", panel._diff_view.toPlainText())

        # 文件内容在磁盘变化
        file1.write_text("v2\n", encoding="utf-8")

        # set_items 重新推送时，当前选中项的 diff 自动重新读取磁盘并渲染
        panel.set_items([item])
        self.assertIn("v2", panel._diff_view.toPlainText())


class WorkspaceChangesRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_workspace_refresh_changes_method(self):
        from doc_tool.ui.content.workspace import ContentWorkspace
        self.assertTrue(hasattr(ContentWorkspace, "refresh_changes"))

    def test_workspace_refresh_changes_logic(self):
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace.__new__(ContentWorkspace)
        ws._vcs = MagicMock()
        ws._index = MagicMock()
        ws._index_service = MagicMock()
        ws._tree = MagicMock()
        ws._apply_status_map = MagicMock()
        status_msgs = []
        ws._on_status = lambda msg: status_msgs.append(msg)

        ws.refresh_changes()

        # 验证缓存失效、索引刷新、状态图应用与状态提示
        ws._vcs.invalidate_cache.assert_called_once()
        ws._index_service.refresh.assert_called_once_with(ws._index)
        ws._apply_status_map.assert_called_once()
        self.assertIn("已刷新改动列表", status_msgs)


class MainWindowRefreshActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_has_refresh_action(self):
        from doc_tool.ui.main_window import MainWindow
        self.assertTrue(hasattr(MainWindow, "_on_refresh_changes_menu_clicked"))

    def test_main_window_refresh_action_triggers_workspace(self):
        from doc_tool.ui.main_window import MainWindow

        win = MainWindow.__new__(MainWindow)
        mock_ws = MagicMock()
        win._content_workspace = mock_ws

        win._on_refresh_changes_menu_clicked()
        mock_ws.refresh_changes.assert_called_once()


if __name__ == "__main__":
    unittest.main()
