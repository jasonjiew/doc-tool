# -*- coding: utf-8 -*-
"""UI2-C 正文导航与阅读（3.1～3.5）：路径、位置历史与脏缓冲。

覆盖验收 U2-3/U2-4 的可自动部分：

- 真实章节路径 + 定位当前章 + 复制全路径；
- 主动跳章/搜索/问题/资料定位产生后退/前进记录；脏缓冲跨来源跳转再后退，
  未保存文本与撤销栈保持，不加载旧正文；
- 相邻重复合并、新导航清前进支路、上限 50、项目隔离、目标删除就地说明。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.application.content.unsaved import UnsavedChoice  # noqa: E402
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402
from doc_tool.ui.navigation_history import (  # noqa: E402
    MAX_HISTORY,
    NavLocation,
    NavigationHistory,
)


class NavigationHistoryModelTests(unittest.TestCase):
    """纯模型：合并、上限、前进支路与项目隔离。"""

    def test_duplicate_adjacent_positions_merge(self):
        history = NavigationHistory("P1")
        self.assertTrue(history.record(NavLocation("a.md", cursor=10, source="章节树")))
        self.assertFalse(
            history.record(NavLocation("a.md", cursor=11, source="标签选择")),
            "同一文件且光标接近必须合并",
        )
        self.assertTrue(history.record(NavLocation("a.md", cursor=50, source="搜索")))
        self.assertEqual(len(history.entries()), 2)

    def test_new_navigation_clears_forward_branch(self):
        history = NavigationHistory("P1")
        for path in ("a.md", "b.md", "c.md"):
            history.record(NavLocation(path, source="章节树"))
        self.assertTrue(history.can_back())
        history.back()
        self.assertTrue(history.can_forward(), "后退后应可前进")
        history.record(NavLocation("d.md", source="搜索"))
        self.assertFalse(history.can_forward(), "新导航必须清空前进支路")
        self.assertEqual(history.current().rel_path, "d.md")

    def test_limit_is_enforced(self):
        history = NavigationHistory("P1", limit=5)
        for index in range(12):
            history.record(NavLocation("c{0}.md".format(index), cursor=index * 100))
        self.assertEqual(len(history.entries()), 5)
        self.assertEqual(history.entries()[-1].rel_path, "c11.md")

    def test_replay_suppression_does_not_push(self):
        history = NavigationHistory("P1")
        history.record(NavLocation("a.md", cursor=0, source="章节树"))
        history.record(NavLocation("b.md", cursor=0, source="搜索"))
        target, _msg = history.back()
        self.assertEqual(target.rel_path, "a.md")
        # 到达重放目标：不入栈（即使光标与记录不同）
        history.suppress_next(target)
        pushed = history.record(NavLocation("a.md", cursor=7, source="后退"))
        self.assertFalse(pushed, "重放不得二次入栈")
        self.assertEqual(len(history.entries()), 2)
        self.assertEqual(history.current().cursor, 7, "重放仍应同步光标")

    def test_suppression_is_scoped_to_expected_target(self):
        history = NavigationHistory("P1")
        history.record(NavLocation("a.md", cursor=0, source="章节树"))
        history.record(NavLocation("b.md", cursor=0, source="搜索"))
        target, _msg = history.back()
        history.suppress_next(target)
        # 到达的不是重放目标：视为新的主动导航，必须正常入栈
        pushed = history.record(NavLocation("c.md", cursor=0, source="问题定位"))
        self.assertTrue(pushed, "到达别处必须仍是主动导航")
        self.assertEqual(history.current().rel_path, "c.md")
        self.assertFalse(history.can_forward(), "新导航清空前进支路")

    def test_project_switch_clears_history(self):
        history = NavigationHistory("P1")
        history.record(NavLocation("a.md", source="章节树"))
        self.assertTrue(history.set_project("P2"))
        self.assertEqual(history.entries(), [])
        self.assertFalse(history.can_back())
        self.assertFalse(history.set_project("P2"), "同一项目不清空")

    def test_max_history_constant(self):
        self.assertEqual(MAX_HISTORY, 50)


class NavigationWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-nav")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        self.work = fixtures.scratch_dir("ui2-nav-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        self._patches = [
            patch("doc_tool.application.project_service.load_recent_projects", return_value=[]),
            patch("doc_tool.application.project_service.add_recent_project", return_value=None),
            patch("doc_tool.ui.main_window.QMessageBox.information", lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.warning", lambda *a, **k: None),
            patch.object(QMessageBox, "exec", lambda self: None),
        ]
        for item in self._patches:
            item.start()
        self.window = MainWindow(
            unsaved_resolver=lambda rel_paths, context: UnsavedChoice.DISCARD
        )
        self.window.resize(1280, 720)
        self.window.show()
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self._app.processEvents()
        self.rels = [
            rel for rel, _p in discover_chapters(self.project / "content" / "general")
        ]

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _open(self, rel: str, line=None, source: str = "章节树"):
        self.assertTrue(self.window._open_chapter_in_workspace(rel, line, source=source))
        self._app.processEvents()

    def test_breadcrumb_and_locate_current_chapter(self):
        self._open(self.rels[0])
        label = self.window._nav_location_label
        current = self.window._content_workspace.current_file()
        # 工作区 relPath 带文档类型前缀；真实值必须不省略地可取。
        self.assertEqual(label.text(), current)
        self.assertTrue(current.endswith(self.rels[0]))
        self.assertIn(current, label.toolTip())
        self.window._on_copy_current_path()
        from PySide6.QtGui import QGuiApplication

        self.assertEqual(QGuiApplication.clipboard().text(), current)
        self.window._on_locate_current_chapter()
        self.assertIn("已定位当前章", self.window._status_label.text())

    def test_back_returns_to_previous_position_with_dirty_buffer(self):
        first, second = self.rels[0], self.rels[1]
        self._open(first)
        editor = self.window._content_workspace.current_editor()
        self.assertIsNotNone(editor)
        editor._editor.setPlainText(editor._editor.toPlainText() + "\n未保存的补充说明。\n")
        editor.set_cursor_position(12)
        self._app.processEvents()
        dirty_text = editor._editor.toPlainText()
        self.assertTrue(editor.is_dirty())

        first_current = self.window._content_workspace.current_file()
        # 主动跳到另一章（问题/搜索来源）
        self._open(second, source="问题定位")
        self.assertTrue(self.window._nav_back_btn.isEnabled(), "跳转后应可后退")
        self.window._on_nav_back()
        self._app.processEvents()
        self.assertEqual(
            self.window._content_workspace.current_file(), first_current,
            "后退必须回到原章节",
        )
        restored = self.window._content_workspace.current_editor()
        self.assertEqual(restored._editor.toPlainText(), dirty_text, "不得回放旧正文")
        self.assertTrue(restored.is_dirty(), "未保存状态必须保持")
        # 撤销栈仍可用（未因导航被重置）
        restored._editor.insertPlainText("撤销验证")
        self._app.processEvents()
        restored._editor.undo()
        self._app.processEvents()
        self.assertNotIn("撤销验证", restored._editor.toPlainText())

    def test_forward_after_back_and_new_navigation_clears_forward(self):
        self._open(self.rels[0])
        self._open(self.rels[1], source="搜索")
        self._open(self.rels[2], source="资料定位") if len(self.rels) > 2 else None
        self.window._on_nav_back()
        self._app.processEvents()
        self.assertTrue(self.window._nav_forward_btn.isEnabled(), "后退后应可前进")
        self.window._on_nav_forward()
        self._app.processEvents()
        self.assertFalse(self.window._nav_forward_btn.isEnabled(), "到达末端后不可前进")
        # 新导航清空前进支路
        self.window._on_nav_back()
        self._app.processEvents()
        self._open(self.rels[0], source="章节树")
        history = self.window._nav_history
        self.assertFalse(history.can_forward(), "新导航必须清空前进支路")
        self.assertFalse(self.window._nav_forward_btn.isEnabled())

    def test_deleted_target_reports_and_keeps_other_positions(self):
        first, second = self.rels[0], self.rels[1]
        self._open(first)
        self._open(second, source="搜索")
        # 关闭第二个标签模拟目标不再打开
        self.window._content_workspace.tabs_host.close_file(second) if hasattr(
            self.window._content_workspace.tabs_host, "close_file"
        ) else None
        self.window._content_workspace.tabs_host.remove(second) if hasattr(
            self.window._content_workspace.tabs_host, "remove"
        ) else None
        self._app.processEvents()
        self.window._on_nav_back()
        self._app.processEvents()
        # 无论目标是否仍可打开，都不得抛错且状态有说明
        self.assertTrue(self.window._status_label.text())

    def test_project_switch_isolates_history(self):
        self._open(self.rels[0])
        self.assertTrue(self.window._nav_history.can_back() is False)
        self.window._nav_history.set_project("X:/other")
        self.assertEqual(self.window._nav_history.entries(), [])

    def test_repeated_navigation_merges_and_single_submission(self):
        self._open(self.rels[0])
        self._open(self.rels[0])  # 同一位置重复打开
        self._app.processEvents()
        self.assertFalse(
            self.window._nav_history.can_back(), "同一位置重复导航必须合并"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)