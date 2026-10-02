# -*- coding: utf-8 -*-
"""V3.3 5.1 测试：面板接线到编辑器（插入可一次撤销、摘要候选不新建发布状态）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class AssistEditorWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("assist-ui")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        from doc_tool.ui.main_window import MainWindow

        self.work = fixtures.scratch_dir("assist-ui-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        self._recent = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        self._recent.start()
        self._dialogs = []
        self._patches = [
            patch("doc_tool.ui.main_window.QMessageBox.information",
                  side_effect=lambda *a, **k: self._dialogs.append(a)),
            patch("doc_tool.ui.main_window.QMessageBox.warning",
                  side_effect=lambda *a, **k: self._dialogs.append(a)),
            patch("doc_tool.ui.main_window.QMessageBox.critical",
                  side_effect=lambda *a, **k: self._dialogs.append(a)),
        ]
        for item in self._patches:
            item.start()
        # 测试里不留脏缓冲弹窗：明确选择“丢弃草稿”，避免真实模态框阻塞
        from doc_tool.application.content.unsaved import UnsavedChoice

        self.window = MainWindow(
            unsaved_resolver=lambda rel_paths, context: UnsavedChoice.DISCARD
        )

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._recent.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def _open_project_and_wait(self):
        from PySide6.QtWidgets import QApplication

        import time

        self.window._open_project_path(str(self.project))
        self.assertIsNotNone(self.window._project_summary)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        QApplication.processEvents()

    def test_action_exists_and_panel_opens_with_overview(self):
        self.assertTrue(hasattr(self.window, "_assist_action"))
        self.assertIn("资料", self.window._assist_action.text())
        self._open_project_and_wait()
        self.window._on_assist_panel()
        dock = getattr(self.window, "_assist_dock", None)
        self.assertIsNotNone(dock)
        self.assertIsNotNone(dock.widget())
        # 视图菜单提供显隐入口
        titles = [action.text() for action in self.window._view_menu.actions()]
        self.assertIn("资料搜索与建议", titles)
        # 概览集中提示（至少状态栏给出范围/增强说明）
        self.assertTrue(self.window._status_label.text())

    def test_insert_requested_goes_into_current_editor_and_undoes_once(self):
        from PySide6.QtWidgets import QApplication

        from doc_tool.application.effective_snapshot import discover_chapters

        self._open_project_and_wait()
        workspace = self.window._content_workspace
        content_root = self.project / "content" / "general"
        rel_paths = [rel for rel, _path in discover_chapters(content_root)]
        # 工作区 relPath 需要文档类型前缀
        self.assertTrue(self.window._open_chapter_in_workspace(rel_paths[0]))
        QApplication.processEvents()
        editor = workspace.current_editor()
        if editor is None:
            self.skipTest("离屏环境下编辑器未就绪：由 test_gui_services 覆盖打开路径")
        target = editor._editor
        before = target.toPlainText()
        self.window._on_assist_insert_requested("[1] 出处：接口说明 1.0", "citation")
        QApplication.processEvents()
        after = target.toPlainText()
        self.assertNotEqual(before, after)
        self.assertIn("[1] 出处：接口说明 1.0", after)
        # 一次撤销即回到插入前内容（不新建编辑器、不绕过撤销栈）
        target.undo()
        QApplication.processEvents()
        self.assertEqual(target.toPlainText(), before)

    def test_summary_candidate_does_not_create_publish_state(self):
        from PySide6.QtWidgets import QApplication

        from doc_tool.application.content.revision_record import ensure_revision_record
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self._open_project_and_wait()
        manifest = ProjectManifest.load(self.project)
        paths = ProjectPaths(self.project)
        revision = paths.resolve(manifest.relative_content_root()) / "_revision_record.md"
        self.assertTrue(self.window._open_chapter_in_workspace("_revision_record.md"))
        QApplication.processEvents()
        before = revision.read_text(encoding="utf-8")
        self.window._on_assist_summary_candidate("本轮修订摘要候选")
        QApplication.processEvents()
        # 只改内存缓冲：磁盘文件（正式内容）不变
        self.assertEqual(revision.read_text(encoding="utf-8"), before)
        self.assertTrue(self.window._status_label.text())

    def test_panel_requires_project(self):
        messages = []
        self.window._show_status_message = lambda message: messages.append(str(message))
        self.window._on_assist_panel()
        self.assertIsNone(getattr(self.window, "_assist_dock", None))
        self.assertTrue(any("项目" in item for item in messages), messages)


if __name__ == "__main__":
    unittest.main(verbosity=2)