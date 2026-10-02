# -*- coding: utf-8 -*-
"""UI2-C 3.3/3.5 阅读与写作视图：字号、单栏阅读、偏好存取与正文不受影响。

验收 U2-4 的可自动部分：放大字号/切单栏阅读/切回写作后正文与出稿设置不变，
重开仍可恢复偏好；视图与字号不进入撤销栈、不改 Markdown 或 Word 模板。
"""

from __future__ import annotations

import json
import os
import shutil
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
from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget  # noqa: E402

from doc_tool.application.content.unsaved import UnsavedChoice  # noqa: E402
from doc_tool.application.content.workspace_state import (  # noqa: E402
    SessionState,
    WorkspaceStateStore,
)
from doc_tool.application.content.writer import ContentWriter  # noqa: E402
from doc_tool.ui.content.editor_panel import EditorPanel  # noqa: E402


class EditorViewModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui2-reading")
        content = self.work / "content" / "general"
        content.mkdir(parents=True, exist_ok=True)
        self.writer = ContentWriter(content, self.work / ".state", writable=True)
        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.panel = EditorPanel(self.writer)
        layout.addWidget(self.panel)
        self.host.resize(1280, 720)
        self.host.show()
        self.panel.load("general/01 概述.md", "# 概述\n\n正文段落一。\n\n正文段落二。\n")
        self._app.processEvents()

    def tearDown(self):
        try:
            self.host.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def test_view_modes_change_layout_only(self):
        body_before = self.panel.plain_text()
        self.panel.set_view_mode(self.panel.VIEW_COMPARE)
        self._app.processEvents()
        self.assertTrue(self.panel.preview_enabled(), "对照视图必须显示结构预览")
        self.panel.set_view_mode(self.panel.VIEW_READ)
        self._app.processEvents()
        self.assertTrue(self.panel.preview_enabled())
        self.assertTrue(self.panel._outline_panel.isHidden(), "阅读视图优先单栏正文")
        self.panel.set_view_mode(self.panel.VIEW_WRITE)
        self._app.processEvents()
        self.assertFalse(self.panel.preview_enabled(), "写作视图不占预览空间")
        self.assertEqual(self.panel.plain_text(), body_before, "视图切换不得改动正文")
        self.assertFalse(self.panel.is_dirty(), "视图切换不得把文档变脏")

    def test_zoom_steps_do_not_touch_text_or_undo(self):
        body_before = self.panel.plain_text()
        undo_before = self.panel._editor.document().isUndoAvailable()
        default = self.panel.font_step()
        bigger = self.panel.zoom_in()
        self.assertGreater(bigger, self.panel.FONT_STEPS[int(default)])
        self.panel.zoom_in()
        smaller = self.panel.zoom_out()
        self.assertLess(smaller, self.panel.FONT_STEPS[-1])
        reset = self.panel.reset_zoom()
        self.assertEqual(reset, 10.0, "重置回到默认 10pt")
        self.assertEqual(self.panel.plain_text(), body_before)
        self.assertEqual(self.panel._editor.document().isUndoAvailable(), undo_before)

    def test_zoom_is_clamped_to_available_steps(self):
        self.panel.set_font_step(-99)
        self.assertEqual(self.panel.font_step(), 0.0)
        self.panel.set_font_step(99)
        self.assertEqual(self.panel.font_step(), float(len(self.panel.FONT_STEPS) - 1))

    def test_view_and_zoom_survive_session_roundtrip(self):
        state = SessionState(view_mode="read", font_step=3.0)
        restored = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(restored.view_mode, "read")
        self.assertEqual(restored.font_step, 3.0)
        # 旧会话缺字段按默认回退
        legacy = SessionState.from_dict({"theme": "light", "openTabs": ["a.md"]})
        self.assertEqual(legacy.view_mode, "write")
        self.assertEqual(legacy.font_step, 1.0)
        # 坏值按默认回退
        broken = SessionState.from_dict({"viewMode": 5, "fontStep": "abc"})
        self.assertEqual(broken.view_mode, "5")
        self.assertEqual(broken.font_step, 1.0)


class ReadingViewWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-reading-win")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        from doc_tool.application.effective_snapshot import discover_chapters
        from doc_tool.ui.main_window import MainWindow

        self.work = fixtures.scratch_dir("ui2-reading-win-case")
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
        self.assertTrue(self.window._open_chapter_in_workspace(self.rels[0]))
        self._app.processEvents()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def test_menu_and_toolbar_share_view_actions(self):
        for mode, action in (
            ("write", self.window._view_write_action),
            ("compare", self.window._view_compare_action),
            ("read", self.window._view_read_action),
        ):
            action.trigger()
            self._app.processEvents()
            self.assertEqual(self.window._view_mode_combo.currentData(), mode)
            editor = self.window._content_workspace.current_editor()
            self.assertEqual(editor.view_mode(), mode)

    def test_zoom_actions_update_editor_font_only(self):
        editor = self.window._content_workspace.current_editor()
        body_before = editor.plain_text()
        self.window._zoom_in_action.trigger()
        self._app.processEvents()
        self.assertGreater(editor.font_step(), 1.0)
        self.window._zoom_reset_action.trigger()
        self._app.processEvents()
        self.assertEqual(editor.font_step(), 1.0)
        self.assertEqual(editor.plain_text(), body_before, "字号不得改动正文")

    def test_reading_preference_is_persisted_and_restored(self):
        editor = self.window._content_workspace.current_editor()
        editor.set_font_step(3)
        editor.set_view_mode(editor.VIEW_READ)
        self._app.processEvents()
        self.window._persist_workspace_session()
        stored = WorkspaceStateStore(self.project / ".state").load()
        self.assertEqual(stored.view_mode, "read")
        self.assertEqual(stored.font_step, 3.0)
        # 恢复后仍是该偏好（坏值只影响该项）
        stored.font_step = "bad"
        reloaded = SessionState.from_dict(stored.to_dict())
        self.assertEqual(reloaded.view_mode, "read")
        self.assertEqual(reloaded.font_step, 1.0)
        # 出稿设置未被视图改动：快速 Word 默认仍是整份/当前内容/Word/非严格。
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX,
            SCOPE_PROJECT,
            SOURCE_MODE_CURRENT_BUFFER,
        )

        captured = {}
        self.window._collect_buffer_texts = lambda: {"a.md": "当前缓冲"}

        def _fake_run(req, **kwargs):
            captured["request"] = req
            return None

        with patch(
            "doc_tool.application.project_export.run_project_export", _fake_run
        ):
            self.window._on_quick_export_word()
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                self._app.processEvents()
                time.sleep(0.02)
        request = captured.get("request")
        self.assertIsNotNone(request)
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.scope.kind, SCOPE_PROJECT)
        self.assertEqual(request.source_mode, SOURCE_MODE_CURRENT_BUFFER)
        self.assertFalse(request.strict, "视图偏好不得打开严格模式")


if __name__ == "__main__":
    unittest.main(verbosity=2)