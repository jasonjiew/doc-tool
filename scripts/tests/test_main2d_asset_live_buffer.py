# -*- coding: utf-8 -*-
"""MAIN2-D：当前引用可就地修图（活缓冲引用 / 单项修复 / 批量预览 / 显式回收）。

覆盖 tasks.md 4.1～4.4：
(a) 仅被活缓冲引用的资产不出现在 scan_unused，缺失清单列出缓冲新增悬空引用；
(b) 单项修复写打开中的编辑器缓冲，一次撤销恢复修复前的整章内容；
(c) 未打开章节走 ContentWriter，除目标外整行逐字节一致；
(d) 显式回收走回收站，可恢复到原路径且字节与原图一致。
"""

from __future__ import annotations

import io
import os
import re
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

from PySide6.QtCore import Qt  # noqa: E402

from scripts.tests import core_fixtures as fixtures  # noqa: E402


def _png_bytes(color=(10, 120, 200)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), color).save(buffer, format="PNG")
    return buffer.getvalue()


class _PanelProject:
    """最小项目：assets_root 与主窗口一致，都是项目根的 ``assets/``。"""

    def __init__(self, root: Path) -> None:
        from doc_tool.application.content.writer import ContentWriter

        self.root = root
        self.content = root / "content" / "general"
        self.assets_root = root / "assets"
        self.assets = self.assets_root / "general"
        (self.assets / "images").mkdir(parents=True)
        self.content.mkdir(parents=True)
        self.state = root / ".state"
        self.state.mkdir()
        self.writer = ContentWriter(self.content, self.state, assets_root=self.assets_root)

    def write(self, rel: str, text: str) -> None:
        path = self.content / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def index(self):
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner

        index = ContentIndexService(self.content).build()
        ReferenceScanner(index, assets_root=self.assets_root).scan_all()
        return index


class LiveBufferReferenceScanTests(unittest.TestCase):
    """4.1：活缓冲引用计入「已用」；未保存新增引用的资源不得列为可清理。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2d-scan-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = _PanelProject(self.work / "proj")
        self.project.write("1 概述.md", "# 概述\n\n正文。\n")
        (self.project.assets / "images" / "live.png").write_bytes(_png_bytes())
        self.index = self.project.index()

    def test_buffer_only_reference_is_not_unused(self):
        from doc_tool.application.content.asset_manager import scan_unused

        names = [row[0] for row in scan_unused(self.project.assets_root, self.index)]
        self.assertIn("general/images/live.png", names)
        buffers = {"1 概述.md": "# 概述\n\n![新图](images/live.png)\n"}
        names = [
            row[0]
            for row in scan_unused(
                self.project.assets_root, self.index, buffer_texts=buffers
            )
        ]
        self.assertNotIn(
            "general/images/live.png", names, "活缓冲已引用的图不得列为可清理"
        )

    def test_missing_list_includes_buffer_only_dangling_reference(self):
        from doc_tool.application.content.asset_manager import list_missing

        buffers = {"1 概述.md": "# 概述\n\n![新图](images/gone.png =10x20)\n"}
        rows = list_missing(self.index, self.project.assets_root, buffer_texts=buffers)
        self.assertIn(
            ("1 概述.md", 3, "images/gone.png"),
            {(row.source, row.line, row.target) for row in rows},
        )


class WorkspaceLiveBufferTests(unittest.TestCase):
    """4.1/4.2/4.3：真实工作区入口——清单叠加活缓冲，修复按打开/未打开分流。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2d-ui-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.paths = ProjectPaths(self.project)
        self.manifest = ProjectManifest.load(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())
        self.assets_root = self.paths.assets_root
        self.assets = self.assets_root / self.manifest.documentType
        (self.assets / "images").mkdir(parents=True, exist_ok=True)
        self.rel_path = "第1章 引言/1.1 目的.md"
        self.other_path = "第2章 设计/2.1 架构.md"
        self.assertTrue((self.content_root / self.rel_path).is_file())

    def _workspace(self):
        from doc_tool.application.content.references import ReferenceScanner
        from doc_tool.ui.content.workspace import ContentWorkspace

        workspace = ContentWorkspace(
            self.content_root,
            project_root=self.project,
            state_dir=self.paths.state_dir,
            assets_root=self.assets_root,
            on_status=lambda message: None,
        )
        self.addCleanup(workspace.deleteLater)
        if getattr(workspace, "_index", None) is None:
            workspace._index = workspace._index_service.build()
            ReferenceScanner(workspace._index, assets_root=workspace._assets_root).scan_all()
            # 与真实项目加载一致（_on_index_done）：索引就绪后建立各面板。
            workspace._populate_panels()
        self.assertIsNotNone(workspace._index, "工作区索引应已建立")
        return workspace

    def _append_to_editor(self, workspace, rel_path: str, text: str):
        workspace.open_file(rel_path)
        editor = workspace.tabs_host.editor_for(rel_path)
        self.assertIsNotNone(editor, "目标章节应已打开")
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        return editor

    @staticmethod
    def _unused_names(panel):
        return [
            panel._unused.topLevelItem(i).text(0)
            for i in range(panel._unused.topLevelItemCount())
        ]

    @staticmethod
    def _select_missing(panel, source: str, target: str):
        for row in range(panel._missing.topLevelItemCount()):
            item = panel._missing.topLevelItem(row)
            ref = item.data(0, Qt.ItemDataRole.UserRole)
            if ref is not None and ref.source == source and ref.target == target:
                panel._missing.setCurrentItem(item)
                return ref
        return None

    def test_panel_unused_list_follows_live_buffer(self):
        (self.assets / "images" / "live.png").write_bytes(_png_bytes())
        workspace = self._workspace()
        panel = workspace._image_assets_panel
        panel.refresh()
        self.assertIn("general/images/live.png", self._unused_names(panel))
        self.assertIn("依据：磁盘索引（编辑器当前无未保存内容）", panel._status.text())
        self._append_to_editor(workspace, self.rel_path, "![新增](images/live.png)\n")
        panel.refresh()
        self.assertNotIn(
            "general/images/live.png",
            self._unused_names(panel),
            "活缓冲引用的资产不得出现在可清理清单",
        )
        self.assertIn("未保存编辑器缓冲", panel._status.text())

    def test_live_buffer_missing_row_is_marked_as_current_content(self):
        workspace = self._workspace()
        self._append_to_editor(workspace, self.rel_path, "![缺图](images/gone.png)\n")
        panel = workspace._image_assets_panel
        panel.refresh()
        origin = None
        for row in range(panel._missing.topLevelItemCount()):
            item = panel._missing.topLevelItem(row)
            ref = item.data(0, Qt.ItemDataRole.UserRole)
            if ref is not None and ref.source == self.rel_path and ref.target == "images/gone.png":
                origin = item.text(3)
        self.assertEqual(origin, "编辑器当前内容")

    def test_repair_open_chapter_writes_editor_buffer_and_single_undo(self):
        workspace = self._workspace()
        editor = self._append_to_editor(
            workspace, self.rel_path, "![缺图](images/gone.png =120x80)\n"
        )
        before = editor.plain_text()
        self.assertTrue(editor.is_dirty())
        panel = workspace._image_assets_panel
        panel.refresh()
        ref = self._select_missing(panel, self.rel_path, "images/gone.png")
        self.assertIsNotNone(ref, "缺失清单应列出活缓冲里新增的悬空引用")
        outside = self.work / "外部替代图.png"
        outside.write_bytes(_png_bytes((200, 10, 10)))
        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(str(outside), ""),
        ):
            panel.repoint_selected()
        after = editor.plain_text()
        self.assertIn("![缺图](images/img_", after)
        self.assertIn(" =120x80)", after, "尺寸后缀应保留")
        self.assertNotIn("images/gone.png", after)
        imported = sorted((self.assets / "images").glob("img_*"))
        self.assertEqual(len(imported), 1, "外部图片应按原命名入库一次")
        self.assertEqual(imported[0].read_bytes(), outside.read_bytes())
        disk = (self.content_root / self.rel_path).read_text(encoding="utf-8")
        self.assertNotIn(imported[0].name, disk, "打开章修复不得隐式保存到磁盘")
        self.assertTrue(editor.is_dirty())
        # 一次 Ctrl+Z 恢复修复前的整章内容
        editor._editor.undo()
        self.assertEqual(editor.plain_text(), before)

    def test_repair_unopened_chapter_writes_disk_and_keeps_line(self):
        original_line = (
            "前文 ![缺图](images/gone.png =120x80) 后文 "
            "![另一张](images/other-missing.png) 结束\n"
        )
        path = self.content_root / self.other_path
        path.write_text("# 架构\n\n" + original_line, encoding="utf-8")
        workspace = self._workspace()
        self.assertIsNone(
            workspace.tabs_host.editor_for(self.other_path), "目标章未打开"
        )
        panel = workspace._image_assets_panel
        panel.refresh()
        ref = self._select_missing(panel, self.other_path, "images/gone.png")
        self.assertIsNotNone(ref)
        outside = self.work / "外部替代图2.png"
        outside.write_bytes(_png_bytes((10, 200, 10)))
        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(str(outside), ""),
        ):
            panel.repoint_selected()
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        self.assertEqual(lines[0], "# 架构\n")
        self.assertEqual(lines[1], "\n")
        restored = re.sub(
            r"!\[缺图\]\(images/img_\d+\.(?:png|PNG) =120x80\)",
            "![缺图](images/gone.png =120x80)",
            lines[2],
        )
        self.assertEqual(restored, original_line, "除目标外整行应逐字节一致")
        imported = sorted((self.assets / "images").glob("img_*"))
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0].read_bytes(), outside.read_bytes())
        # 重新解析（等价于重开项目）：正文与资源读回，引用不再悬空
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner

        reopened = ContentIndexService(self.content_root).build()
        ReferenceScanner(reopened, assets_root=self.assets_root).scan_all()
        dangling_targets = {
            str(ref.target).split()[0]
            for refs in reopened.references.values()
            for ref in refs
            if ref.kind == "image" and ref.dangling
        }
        self.assertNotIn("images/gone.png", dangling_targets)
        self.assertIn("images/other-missing.png", dangling_targets)
        self.assertTrue(
            (self.assets / "images" / imported[0].name).is_file(), "资源读回"
        )

    def test_remove_reference_keeps_rest_of_line(self):
        line = "前文 ![选择](images/gone.png =120x80) 后文 ![保留](images/kept.png) 结束\n"
        path = self.content_root / self.other_path
        path.write_text("# 架构\n\n" + line, encoding="utf-8")
        (self.assets / "images" / "kept.png").write_bytes(_png_bytes((1, 2, 3)))
        workspace = self._workspace()
        panel = workspace._image_assets_panel
        panel.refresh()
        ref = self._select_missing(panel, self.other_path, "images/gone.png")
        self.assertIsNotNone(ref)
        panel.remove_reference_line()
        updated = path.read_text(encoding="utf-8")
        self.assertNotIn("gone.png", updated, "所选引用应被移除")
        self.assertIn(
            "前文  后文 ![保留](images/kept.png) 结束\n",
            updated,
            "同一行的其他正文与图片必须原样保留",
        )

    def test_batch_repair_preview_is_buffer_aware_and_keeps_siblings(self):
        from PySide6.QtWidgets import QDialog, QTreeWidget

        line = "甲 ![缺](images/gone.png =10x20) 乙 ![缺2](images/gone.png) 丙\n"
        (self.content_root / self.rel_path).write_text("# 目的\n\n" + line, encoding="utf-8")
        other = self.content_root / self.other_path
        other.write_text("# 架构\n\n" + line, encoding="utf-8")
        (self.assets / "images" / "correct.png").write_bytes(_png_bytes((9, 9, 9)))
        workspace = self._workspace()
        # 第1章打开且有未保存编辑：批量预览只列跳过项，不得写该章。
        self._append_to_editor(workspace, self.rel_path, "编辑器未保存补充\n")
        panel = workspace._image_assets_panel
        panel.refresh()
        ref = self._select_missing(panel, self.rel_path, "images/gone.png")
        self.assertIsNotNone(ref)
        captured = {}
        original_line_ch1 = (self.content_root / self.rel_path).read_text(encoding="utf-8")

        def _auto_accept(dialog):
            tree = dialog.findChild(QTreeWidget)
            captured["rows"] = [
                (
                    tree.topLevelItem(i).text(0),
                    tree.topLevelItem(i).text(1),
                    tree.topLevelItem(i).text(2),
                    tree.topLevelItem(i).checkState(0),
                )
                for i in range(tree.topLevelItemCount())
            ]
            return QDialog.DialogCode.Accepted

        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(str(self.assets / "images" / "correct.png"), ""),
        ), patch.object(QDialog, "exec", _auto_accept):
            panel.batch_repair()

        rows = captured.get("rows") or []
        self.assertTrue(rows, "批量修复应给出预览行")
        other_rows = [row for row in rows if row[0].startswith(self.other_path)]
        dirty_rows = [row for row in rows if row[0].startswith(self.rel_path)]
        self.assertEqual(len(other_rows), 2, "未打开章应列出 2 处实际引用")
        for row in other_rows:
            self.assertEqual(row[3], Qt.CheckState.Checked)
            self.assertIn("images/gone.png → images/correct.png", row[1])
        self.assertTrue(dirty_rows, "有未保存编辑的章节应在预览中列出")
        for row in dirty_rows:
            self.assertEqual(row[3], Qt.CheckState.Unchecked)
            self.assertIn("跳过", row[1])
        # 未打开章：只改目标，同行其他正文/图片原样保留
        updated = other.read_text(encoding="utf-8")
        self.assertIn(
            "甲 ![缺](images/correct.png =10x20) 乙 ![缺2](images/correct.png) 丙\n",
            updated,
        )
        # 有未保存编辑的章节：磁盘正文完全不变，且状态报告跳过
        self.assertEqual(
            (self.content_root / self.rel_path).read_text(encoding="utf-8"),
            original_line_ch1,
        )
        self.assertIn("跳过", panel._status.text())


    def test_batch_repair_skips_source_that_moved_on(self):
        from PySide6.QtWidgets import QDialog

        line = "甲 ![缺](images/gone.png) 乙 ![留](images/kept.png) 丙\n"
        other = self.content_root / self.other_path
        other.write_text("# 架构\n\n" + line, encoding="utf-8")
        (self.assets / "images" / "correct.png").write_bytes(_png_bytes((9, 9, 9)))
        (self.assets / "images" / "kept.png").write_bytes(_png_bytes((4, 4, 4)))
        workspace = self._workspace()
        panel = workspace._image_assets_panel
        panel.refresh()
        ref = self._select_missing(panel, self.other_path, "images/gone.png")
        self.assertIsNotNone(ref)
        changed = "# 架构\n\n" + line + "预览后外部新增内容。\n"

        def _auto_accept(dialog):
            # 预览与「应用」之间源文件被外部改动：该项必须跳过，不得按旧范围写。
            other.write_text(changed, encoding="utf-8")
            return QDialog.DialogCode.Accepted

        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(str(self.assets / "images" / "correct.png"), ""),
        ), patch.object(QDialog, "exec", _auto_accept):
            panel.batch_repair()

        self.assertEqual(
            other.read_text(encoding="utf-8"), changed, "外部变化项不得被覆盖"
        )
        self.assertIn("已处理 0 章", panel._status.text())
        self.assertIn("跳过", panel._status.text())


class ExplicitReclaimTests(unittest.TestCase):
    """4.4：显式回收走回收站并可回原路径恢复；默认不勾选、不自动删除。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2d-reclaim-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = _PanelProject(self.work / "proj")
        self.project.write("1 概述.md", "# 概述\n\n正文。\n")
        self.raw = _png_bytes((7, 8, 9))
        self.orphan = self.project.assets / "images" / "orphan.png"
        self.orphan.write_bytes(self.raw)
        self.index = self.project.index()
        from doc_tool.ui.content.image_assets_panel import ImageAssetsPanel

        self.panel = ImageAssetsPanel(
            self.index,
            assets_root=self.project.assets_root,
            writer=self.project.writer,
        )
        self.addCleanup(self.panel.deleteLater)

    def _item(self, name: str):
        for row in range(self.panel._unused.topLevelItemCount()):
            item = self.panel._unused.topLevelItem(row)
            if item.text(0) == "general/images/" + name:
                return item
        return None

    def test_reclaim_then_restore_returns_original_bytes_at_same_path(self):
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.content.trash import TrashStore

        item = self._item("orphan.png")
        self.assertIsNotNone(item, "未引用资源应出现在可清理清单")
        self.assertEqual(
            item.checkState(0), Qt.CheckState.Unchecked, "未使用资源默认不得预勾选"
        )
        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.panel.clean_checked()
        self.assertTrue(self.orphan.is_file(), "未勾选时不得删除任何资源")
        item = self._item("orphan.png")
        item.setCheckState(0, Qt.CheckState.Checked)
        with patch(
            "PySide6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.panel.clean_checked()
        self.assertFalse(self.orphan.is_file(), "勾选确认后应移入回收站")
        store = TrashStore(self.project.writer)
        entries = [
            entry
            for entry in store.list_entries()
            if entry.rel_path == "assets/general/images/orphan.png"
        ]
        self.assertEqual(len(entries), 1, [entry.rel_path for entry in store.list_entries()])
        restored = store.restore(entries[0], mode="copy", confirmed=True)
        self.assertEqual(restored, "assets/general/images/orphan.png", "恢复回原路径")
        self.assertTrue(self.orphan.is_file())
        self.assertEqual(self.orphan.read_bytes(), self.raw, "恢复后字节应与原图一致")
        # 重新解析（等价于重开项目）：恢复的资源被真实扫描读回
        from doc_tool.application.content.asset_manager import scan_unused

        fresh = self.project.index()
        self.assertIn(
            "general/images/orphan.png",
            [row[0] for row in scan_unused(self.project.assets_root, fresh)],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)