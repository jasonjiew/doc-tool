# -*- coding: utf-8 -*-
"""MAIN2-C：章节操作跟随当前内容（复制/改名/移动/排序与表达一致）。"""

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


class CopyCurrentTextTests(unittest.TestCase):
    """3.1：复制默认读当前有效正文，副本新身份，原磁盘/草稿不隐式保存。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2c-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.manifest = ProjectManifest.load(self.project)
        self.paths = ProjectPaths(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())
        self.writer = ContentWriter(
            self.content_root, self.paths.state_dir,
            self.paths.resolve(self.manifest.relative_asset_root()),
        )
        self.index = ContentIndexService(self.content_root).build()
        # 修订记录不是正文章节：只取真实章节做复制测试。
        self.rel_path = sorted(
            rel for rel in self.index.all_files()
            if not Path(rel).name.startswith("_revision_record")
        )[0]

    def test_copy_uses_editor_buffer_not_index(self):
        from doc_tool.application.content.refactor import copy_chapter

        buffer_text = "# 目的\n\n编辑器里的未保存正文。\n"
        result = copy_chapter(
            self.index, self.rel_path, self.writer,
            title="目的（副本）", source_text=buffer_text,
        )
        self.assertTrue(result.ok, result.message)
        target = self.content_root / result.target
        self.assertTrue(target.is_file())
        text = target.read_text(encoding="utf-8")
        self.assertIn("编辑器里的未保存正文。", text)
        # 原磁盘内容不被副本文本覆盖，也不因复制而保存
        original = (self.content_root / self.rel_path).read_text(encoding="utf-8")
        self.assertNotIn("编辑器里的未保存正文。", original)
        # 副本是新身份：条目 ID 与原文不同（正文里有 DOC-ITEM 标记时）
        if result.item_ids:
            self.assertTrue(all(new and new != old for old, new in result.item_ids.items()))

    def test_copy_without_text_keeps_index_behaviour(self):
        from doc_tool.application.content.refactor import copy_chapter

        result = copy_chapter(self.index, self.rel_path, self.writer, title="副本二")
        self.assertTrue(result.ok, result.message)
        text = (self.content_root / result.target).read_text(encoding="utf-8")
        self.assertIn("目的", text)

    def test_copy_rejects_unknown_chapter_without_text(self):
        from doc_tool.application.content.refactor import copy_chapter

        result = copy_chapter(self.index, "不存在/章节.md", self.writer)
        self.assertFalse(result.ok)
        self.assertIn("索引", result.message)


class WorkspaceCopyEntryTests(unittest.TestCase):
    """真实界面：章节树「复制章节…」用编辑器活缓冲。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2c-ui-"))
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

        ready: list = []
        workspace = ContentWorkspace(
            self.content_root,
            project_root=self.project,
            state_dir=self.paths.state_dir,
            assets_root=self.paths.resolve(self.manifest.relative_asset_root()),
            on_status=lambda message: None,
            on_index_ready=lambda: ready.append(True),
        )
        self.addCleanup(workspace.deleteLater)
        # 独立构造工作区时索引不会自动建立（主窗口走项目加载路径）：
        # 这里按真实服务建立一次索引，等价于界面进入项目后的状态。
        if getattr(workspace, "_index", None) is None:
            workspace._index = workspace._index_service.build()
        self.assertIsNotNone(workspace._index, "工作区索引应已建立")
        return workspace

    def test_copy_menu_uses_current_editor_text(self):
        workspace = self._workspace()
        workspace.open_file(self.rel_path)
        editor = workspace.tabs_host.editor_for(self.rel_path)
        self.assertIsNotNone(editor, "打开后的章节应有编辑器")
        marker = "界面复制时的未保存正文标记"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + "\n")
        self.assertTrue(editor.is_dirty(), "插入后应处于未保存状态")
        self.assertIn(marker, workspace._current_chapter_text(self.rel_path))
        notices: list = []
        workspace._on_status = lambda message: notices.append(message)
        with patch(
            "PySide6.QtWidgets.QInputDialog.getText",
            return_value=("界面副本", True),
        ), patch(
            "PySide6.QtWidgets.QMessageBox.warning",
            side_effect=lambda *a, **k: notices.append(a),
        ):
            workspace._on_copy_file(self.rel_path)
        self.assertTrue(
            any("已复制为" in str(item) for item in notices),
            "复制应给出真实结果：{0}".format(notices),
        )
        copies = sorted((self.content_root / "第1章 引言").glob("*界面副本*.md"))
        self.assertTrue(copies, "复制应生成同目录新章节：{0}".format(notices))
        copied = copies[0]
        self.assertIn(marker, copied.read_text(encoding="utf-8"))
        # 原章磁盘内容不被副本文本覆盖（活缓冲不隐式保存）
        original = (self.content_root / self.rel_path).read_text(encoding="utf-8")
        self.assertNotIn(marker, original)
        self.assertTrue(editor.is_dirty(), "复制不应清除原章的未保存状态")


if __name__ == "__main__":
    unittest.main(verbosity=2)