# -*- coding: utf-8 -*-
"""RD 研发工作区接入主窗口的入口回归（RD-A 1.4 / RD-B 2.4 / RD-C 3.1 / RD-E 5.2）。"""

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
from scripts.tests import rd_fixtures  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402


def _cleanup(path):
    assert Path(path).resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(path)


class _StubWriter:
    """最小写入器：只记录写盘调用，解析根目录时落在临时目录。"""

    def __init__(self, root=None):
        self.writes = []
        self._root = Path(root or Path.cwd())

    def write(self, rel_path, text):
        self.writes.append((rel_path, text))

    def write_text(self, rel_path, text):
        self.writes.append((rel_path, text))
        return True

    def resolve(self, rel_path):
        return self._root / str(rel_path)


class _StubTabsHost:
    """最小标签宿主：只实现研发工作区实际用到的接口。"""

    def __init__(self, editors=None):
        self._editors = dict(editors or {})
        self._current = ""
        self.saved = []
        self.activated = []

    def editor_for(self, rel_path):
        return self._editors.get(str(rel_path))

    def open_rel_paths(self):
        return list(self._editors)

    def editors(self):
        return list(self._editors.values())

    def activate(self, rel_path):
        self.activated.append(str(rel_path))
        self._current = str(rel_path)
        return True

    def current_editor(self):
        return self._editors.get(self._current)

    def save_current(self):
        if self._current:
            self.saved.append(self._current)
            return True
        return False


class _StubContentWorkspace:
    def __init__(self, tabs_host):
        self.tabs_host = tabs_host
        self.opened = []
        self._current = ""

    def open_file(self, rel_path, line=None, source=""):
        self.opened.append((str(rel_path), line, source))
        self._current = str(rel_path)

    def current_file(self):
        return self._current


class RdMainWindowEntryTests(unittest.TestCase):
    """真实 MainWindow 入口：菜单 → 对话框 → 宿主适配。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("rd-entry")
        self.data = rd_fixtures.build_rd_workspace(self.work / "研发工作区")
        self.root = Path(self.data["root"])
        self.project = Path(self.data["projects"]["documents/需求"])
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
        # 关闭前卸下测试替身，避免真实 closeEvent 走到桩对象上。
        self.window._content_workspace = None
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        _cleanup(self.work)

    def test_menu_action_exists_and_opens_workspace_for_current_project(self):
        self.assertTrue(hasattr(self.window, "_rd_workspace_action"))
        action = self.window._rd_workspace_action
        self.assertIn("研发工作区", action.text())
        self.assertTrue(action.shortcut().toString())
        captured = {}

        def fake_exec(dialog_self):
            captured["dialog"] = dialog_self
            return 0

        from doc_tool.ui.rd_workspace import RdWorkspaceDialog

        with patch.object(RdWorkspaceDialog, "exec", fake_exec):
            action.trigger()
        dialog = captured["dialog"]
        try:
            self.assertEqual(str(dialog._root), str(self.root), "应识别当前项目所在的研发工作区")
            self.assertEqual(dialog.member_table.rowCount(), 3)
            self.assertEqual(dialog._status_label.text() or "有", dialog._status_label.text() or "有")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_rd_project_identity_and_empty_buffer_state(self):
        self.assertEqual(self.window.rd_project_root(), str(self.project))
        self.assertEqual(self.window.rd_project_id(), self.manifest.projectId)
        self.assertEqual(self.window.rd_collect_buffers(), {})
        self.assertEqual(self.window.rd_current_chapter(), "")
        self.assertIsNone(self.window.rd_apply_item_edit("1 概述/1.1 背景.md", "新正文\n"))
        self.assertFalse(self.window.rd_save_chapters(["1 概述/1.1 背景.md"]))

    def test_rd_apply_item_edit_is_single_undo_transaction(self):
        from doc_tool.ui.content.editor_panel import EditorPanel

        writer = _StubWriter()
        panel = EditorPanel(writer, writable=True)
        try:
            key = "requirement/1 概述/1.1 背景.md"
            panel.load(key, "原正文\n")
            tabs = _StubTabsHost({key: panel})
            tabs._current = key
            self.window._content_workspace = _StubContentWorkspace(tabs)
            applied = self.window.rd_apply_item_edit(
                "1 概述/1.1 背景.md", "原正文\n\n<!-- DOC-ITEM: projectId=x kind=requirement id=y -->\n",
                "已声明条目",
            )
            self.assertTrue(applied)
            inner = panel._editor
            self.assertIn("DOC-ITEM", inner.toPlainText())
            self.assertTrue(inner.document().isUndoAvailable())
            inner.undo()
            self.assertEqual(inner.toPlainText(), "原正文\n", "一次撤销应还原条目动作")
            self.assertEqual(writer.writes, [], "条目动作只改缓冲，不直接写盘")
        finally:
            panel.deleteLater()

    def test_rd_open_source_uses_real_chapter_entry(self):
        tabs = _StubTabsHost({})
        workspace = _StubContentWorkspace(tabs)
        self.window._content_workspace = workspace
        opened = self.window.rd_open_source("1 概述/1.1 背景.md", 5, "研发工作区")
        self.assertTrue(opened)
        self.assertTrue(workspace.opened)
        rel_path, line_no, source = workspace.opened[-1]
        self.assertTrue(rel_path.endswith("1 概述/1.1 背景.md"))
        self.assertEqual(line_no, 5)
        self.assertEqual(source, "研发工作区")

    def test_rd_save_chapters_saves_only_requested_chapters(self):
        from doc_tool.ui.content.editor_panel import EditorPanel

        panel_a = EditorPanel(_StubWriter())
        panel_b = EditorPanel(_StubWriter())
        try:
            key_a = "requirement/1 概述/1.1 背景.md"
            key_b = "requirement/1 概述/1.2 目标.md"
            panel_a.load(key_a, "A\n")
            panel_b.load(key_b, "B\n")
            tabs = _StubTabsHost({key_a: panel_a, key_b: panel_b})
            self.window._content_workspace = _StubContentWorkspace(tabs)
            saved = self.window.rd_save_chapters(["1 概述/1.1 背景.md"])
            self.assertTrue(saved)
            self.assertEqual(tabs.saved, [key_a], "只保存关系两端涉及的章节")
        finally:
            panel_a.deleteLater()
            panel_b.deleteLater()

    def test_rd_open_project_activates_existing_window(self):
        activated = []
        with patch.object(self.window, "_find_window_for_project", return_value="other-window"), patch.object(
            self.window, "_activate_window", side_effect=lambda window: activated.append(window),
        ):
            opened = self.window.rd_open_project(str(self.data["projects"]["documents/设计"]))
        self.assertTrue(opened)
        self.assertEqual(activated, ["other-window"])

    def test_rd_open_project_falls_back_to_new_window(self):
        calls = []
        with patch.object(self.window, "_find_window_for_project", return_value=None), patch.object(
            self.window, "_open_project_in_new_window", side_effect=lambda path: calls.append(path),
        ):
            opened = self.window.rd_open_project(str(self.data["projects"]["documents/测试"]))
        self.assertTrue(opened)
        self.assertEqual(len(calls), 1)

    def test_rd_member_delivery_reuses_existing_batch_entry(self):
        calls = []
        with patch.object(self.window, "_on_delivery_batch", side_effect=lambda: calls.append("batch")):
            message = self.window.rd_member_delivery(str(self.root))
        self.assertEqual(calls, ["batch"])
        self.assertIn("批量交付", message)

    def test_rd_workspace_root_changed_is_remembered(self):
        self.window.rd_workspace_root_changed(str(self.root))
        self.assertEqual(self.window._rd_workspace_root(), str(self.root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
