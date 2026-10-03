# -*- coding: utf-8 -*-
"""V3.4/V3.5 主窗口入口回归：菜单动作真实接线到编辑器与规范包制作对话框。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402


def _cleanup(path):
    assert Path(path).resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(path)


class EntryPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("v34v35-entry")
        self.project = fixtures.two_chapter_project(self.work / "项目")
        self.manifest = ProjectManifest.load(self.project)
        from doc_tool.application.content.unsaved import UnsavedChoice
        from doc_tool.ui.main_window import MainWindow

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            self.window = MainWindow(unsaved_resolver=lambda *_: UnsavedChoice.DISCARD)
        self.window._project_summary = SimpleNamespace(
            project_root=str(self.project), manifest=self.manifest,
            paths=ProjectPaths(self.project), is_writable=True,
        )

    def tearDown(self):
        self.window._content_workspace = None
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        _cleanup(self.work)

    def test_table_actions_exist_and_delegate_to_active_editor(self):
        self.assertTrue(hasattr(self.window, "_table_grid_action"))
        self.assertTrue(hasattr(self.window, "_table_paste_action"))
        self.assertTrue(self.window._table_grid_action.shortcut().toString())
        calls = []
        editor = SimpleNamespace(
            open_table_grid=lambda: calls.append("grid"),
            paste_as_table=lambda: calls.append("paste"),
        )
        with patch.object(self.window, "_active_editor", return_value=editor):
            self.window._table_grid_action.trigger()
            self.window._table_paste_action.trigger()
        self.assertEqual(calls, ["grid", "paste"])

    def test_table_actions_without_open_chapter_report_reason(self):
        messages = []
        with patch.object(self.window, "_active_editor", return_value=None), patch.object(
            self.window, "_show_status_message", side_effect=lambda text: messages.append(text),
        ):
            self.window._table_grid_action.trigger()
            self.window._table_paste_action.trigger()
        self.assertEqual(len(messages), 2)
        self.assertTrue(all("章节" in text for text in messages))

    def test_standard_pack_action_opens_dialog_for_current_project(self):
        self.assertTrue(hasattr(self.window, "_standard_pack_action"))
        self.assertTrue(self.window._standard_pack_action.shortcut().toString())
        captured = {}

        from doc_tool.ui.standard_pack_dialog import StandardPackDialog

        def fake_exec(dialog_self):
            captured["dialog"] = dialog_self
            return 0

        with patch.object(StandardPackDialog, "exec", fake_exec):
            self.window._standard_pack_action.trigger()
        dialog = captured["dialog"]
        try:
            self.assertTrue(dialog.windowTitle())
            self.assertIn("pack-draft", dialog.draft_dir_edit.text())
            self.assertEqual(dialog._project_root, str(self.project))
        finally:
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
