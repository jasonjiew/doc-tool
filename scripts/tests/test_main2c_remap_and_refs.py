# -*- coding: utf-8 -*-
"""MAIN2-C 3.2：章节改名/移动/排序保持原身份、缓冲键与返回位置。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class TabRemapTests(unittest.TestCase):
    """改名后沿用同一编辑器实例：未保存正文、脏标记与保存目标都跟到新路径。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2c-remap-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.paths = ProjectPaths(self.project)
        self.manifest = ProjectManifest.load(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())
        self.rel_path = "第1章 引言/1.1 目的.md"
        self.assertTrue((self.content_root / self.rel_path).is_file())

    def _workspace(self):
        from doc_tool.ui.content.workspace import ContentWorkspace

        workspace = ContentWorkspace(
            self.content_root,
            project_root=self.project,
            state_dir=self.paths.state_dir,
            assets_root=self.paths.resolve(self.manifest.relative_asset_root()),
            on_status=lambda message: None,
        )
        self.addCleanup(workspace.deleteLater)
        if getattr(workspace, "_index", None) is None:
            workspace._index = workspace._index_service.build()
        return workspace

    def test_remap_keeps_buffer_dirty_state_and_cursor(self):
        workspace = self._workspace()
        workspace.open_file(self.rel_path)
        editor = workspace.tabs_host.editor_for(self.rel_path)
        self.assertIsNotNone(editor)
        marker = "改名前的未保存正文标记"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + "\n")
        position_before = editor._editor.textCursor().position()
        undo_before = editor._editor.document().isUndoAvailable()
        self.assertTrue(editor.is_dirty())
        self.assertTrue(undo_before)

        new_rel = "第1章 引言/1.1 目的（改名）.md"
        self.assertTrue(workspace.tabs_host.remap_path(self.rel_path, new_rel))
        # 缓冲键随新路径走，旧键不再存在
        self.assertIn(new_rel, workspace.tabs_host.open_rel_paths())
        self.assertNotIn(self.rel_path, workspace.tabs_host.open_rel_paths())
        same_editor = workspace.tabs_host.editor_for(new_rel)
        self.assertIs(same_editor, editor, "必须沿用同一个编辑器实例")
        self.assertEqual(editor.current_rel_path(), new_rel)
        self.assertIn(marker, editor.plain_text(), "未保存正文必须保留")
        self.assertTrue(editor.is_dirty(), "改名不应清除脏标记")
        self.assertEqual(editor._editor.textCursor().position(), position_before)
        self.assertTrue(editor._editor.document().isUndoAvailable(), "撤销栈必须保留")

    def test_rename_keeps_item_identity_and_buffer(self):
        """经真实 RefactorService 改名：条目身份保持，缓冲改挂新路径。"""
        workspace = self._workspace()
        workspace.open_file(self.rel_path)
        editor = workspace.tabs_host.editor_for(self.rel_path)
        marker = "改名后仍要保存的未保存内容"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + "\n")

        from doc_tool.application.content.refactor import RefactorService

        items_before = sorted(
            str(getattr(entry, "item_id", ""))
            for entry in (workspace._index.files or {}).values()
            if getattr(entry, "item_id", "")
        )
        service = RefactorService(workspace._index)
        plan = service.compute_rename_plan(self.rel_path, "1.1 目的（改名）.md")
        self.assertIsNotNone(plan)
        results = service.apply_rename_plan(plan, workspace._writer)
        self.assertTrue(all(item.written for item in results), "改名写回应全部成功")
        workspace.tabs_host.remap_path(self.rel_path, plan.new_rel_path)
        self.assertEqual(
            workspace.tabs_host.editor_for(plan.new_rel_path).current_rel_path(),
            plan.new_rel_path,
        )
        items_after = sorted(
            str(getattr(entry, "item_id", ""))
            for entry in (workspace._index.files or {}).values()
            if getattr(entry, "item_id", "")
        )
        self.assertEqual(items_before, items_after, "改名必须保持稳定条目身份")

    def test_save_after_remap_writes_new_path_not_old(self):
        workspace = self._workspace()
        workspace.open_file(self.rel_path)
        editor = workspace.tabs_host.editor_for(self.rel_path)
        marker = "改挂后保存的目标内容"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + "\n")
        new_rel = "第1章 引言/1.1 目的（新名）.md"
        # 真实改名文件后进行改挂
        (self.content_root / new_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.content_root / self.rel_path, self.content_root / new_rel)
        (self.content_root / self.rel_path).unlink()
        workspace.tabs_host.remap_path(self.rel_path, new_rel)
        self.assertTrue(editor.save(), "改挂后保存应成功")
        self.assertIn(marker, (self.content_root / new_rel).read_text(encoding="utf-8"))
        self.assertFalse((self.content_root / self.rel_path).exists(), "不得重建旧路径文件")


if __name__ == "__main__":
    unittest.main(verbosity=2)