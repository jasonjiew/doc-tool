# -*- coding: utf-8 -*-
"""MAIN-C：图片入口统一、缺图修复范围、引用修复确定性与 Mermaid 源码缓存。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.asset_batch import AssetBatchService  # noqa: E402
from doc_tool.application.content.asset_manager import scan_unused  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.mermaid import render  # noqa: E402
from doc_tool.application.content.refactor import RefactorService  # noqa: E402
from doc_tool.application.content.references import ReferenceScanner  # noqa: E402
from doc_tool.application.content.writer import ContentWriter  # noqa: E402

NL = chr(10)
FLOW_A = "flowchart TD" + NL + "  A[开始] --> B[结束]"
FLOW_B = "flowchart LR" + NL + "  X[甲] --> Y[乙]"


def _png_bytes(color=(10, 120, 200)) -> bytes:
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (16, 12), color).save(buffer, format="PNG")
    return buffer.getvalue()


class _Project:
    """最小项目：assets_root 与工作区一致，都是项目根的 ``assets/``。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.content = root / "content" / "general"
        self.assets_root = root / "assets"
        self.assets = self.assets_root / "general"
        (self.assets / "images").mkdir(parents=True)
        self.content.mkdir(parents=True)
        self.state = root / ".state"
        self.state.mkdir()
        self.writer = ContentWriter(
            self.content, self.state, assets_root=self.assets_root
        )

    def write(self, rel: str, text: str) -> None:
        path = self.content / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def index(self):
        return ContentIndexService(self.content).build()

    def dangling(self):
        index = self.index()
        ReferenceScanner(index, self.assets_root).scan_all()
        return [
            (ref.source, ref.target)
            for refs in index.references.values()
            for ref in refs
            if ref.kind == "image" and ref.dangling
        ]


class ImageEntryPointTests(unittest.TestCase):
    """3.1：粘贴/拖入/选文件共用同一资源写入，引用可解析且一次撤销可还原。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-c-image-"))
        self.project = _Project(self.tmp / "proj")
        self.project.write("1 概述.md", "# 概述" + NL + NL + "正文。" + NL)
        from doc_tool.ui.content.editor_panel import EditorPanel

        self.editor = EditorPanel(
            self.project.writer, assets_root=self.project.assets_root, writable=True
        )
        self.editor.load("1 概述.md", "# 概述" + NL + NL + "正文。" + NL)

    def tearDown(self):
        self.editor.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _written_images(self):
        return sorted(
            path.name for path in (self.project.assets / "images").glob("img_*")
        )

    def test_paste_and_drop_and_button_share_one_writer(self):
        from PySide6.QtGui import QImage

        # 1) 剪贴板粘贴：QImage
        image = QImage(16, 12, QImage.Format.Format_RGB32)
        image.fill(0x336699)
        self.assertTrue(self.editor.import_image(image))
        # 2) 拖入：文件路径
        dropped = self.tmp / "dropped.png"
        dropped.write_bytes(_png_bytes((200, 10, 10)))
        self.assertTrue(self.editor.import_image(str(dropped)))
        # 3) 选文件按钮：_on_insert_image 内部同样调用 import_image
        chosen = self.tmp / "chosen.png"
        chosen.write_bytes(_png_bytes((10, 200, 10)))
        from unittest.mock import patch

        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(str(chosen), ""),
        ):
            self.editor._on_insert_image()

        images = self._written_images()
        self.assertEqual(len(images), 3, images)
        text = self.editor.plain_text()
        for name in images:
            self.assertIn("images/{0}".format(name), text)
        # 引用在资源目录下真实可解析
        self.assertEqual(self.project.dangling(), [])

    def test_insert_is_single_undo_and_export_uses_same_file(self):
        from unittest.mock import patch

        chosen = self.tmp / "single.png"
        chosen.write_bytes(_png_bytes((30, 30, 200)))
        with patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            return_value=(str(chosen), ""),
        ):
            self.editor._on_insert_image()
        text_with = self.editor.plain_text()
        self.assertIn("images/", text_with)
        # 一次撤销回到插入前
        self.editor._editor.undo()
        self.assertEqual(self.editor.plain_text(), "# 概述" + NL + NL + "正文。" + NL)
        # 资源文件仍在（插入产生的是真实文件，撤销只回退正文引用）
        self.assertEqual(len(self._written_images()), 1)


class MissingImageRepairTests(unittest.TestCase):
    """3.2：缺图修复只改明确所选引用；未引用资源只报告、保留文件。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-c-missing-"))
        self.project = _Project(self.tmp / "proj")
        self.project.write(
            "1 概述.md", "# 概述" + NL + NL + "![a](images/gone.png)" + NL
        )
        self.project.write(
            "2 设计.md", "# 设计" + NL + NL + "![a](images/gone.png)" + NL
        )
        # 一张未被任何正文引用的资源
        (self.project.assets / "images" / "unused.png").write_bytes(_png_bytes())
        self.index = self.project.index()
        ReferenceScanner(self.index, self.project.assets_root).scan_all()
        self.service = AssetBatchService(self.project.writer, self.index)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_plan_covers_all_references_and_apply_only_selected(self):
        replacement = "images/new.png"
        rows = self.service.plan("images/gone.png", replacement)
        self.assertEqual(sorted(row.source for row in rows), ["1 概述.md", "2 设计.md"])
        rows[1].selected = False
        (self.project.assets / "images" / "new.png").write_bytes(_png_bytes())
        result = self.service.apply(rows, confirmed=True)
        self.assertEqual(result["applied"], ["1 概述.md"])
        self.assertIn(
            replacement, (self.project.content / "1 概述.md").read_text(encoding="utf-8")
        )
        # 未选中的引用保持原样（不改动无关章节）
        self.assertIn(
            "images/gone.png", (self.project.content / "2 设计.md").read_text(encoding="utf-8")
        )

    def test_unused_asset_is_reported_and_file_kept(self):
        unused = scan_unused(self.project.assets_root, self.index)
        names = [row[0] for row in unused]
        self.assertIn("general/images/unused.png", names)
        # 只报告不删除
        self.assertTrue((self.project.assets / "images" / "unused.png").is_file())


class ReferenceFixDeterminismTests(unittest.TestCase):
    """3.3：改名只联动真实指向该章的引用；同名歧义引用不被误改且位置可查。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-c-refs-"))
        self.project = _Project(self.tmp / "proj")
        (self.project.content / "a").mkdir(parents=True)
        (self.project.content / "b").mkdir(parents=True)
        self.project.write("a/1 概述.md", "# 1 概述" + NL + NL + "甲。" + NL)
        self.project.write("b/1 概述.md", "# 1 概述" + NL + NL + "乙。" + NL)
        # a 目录内引用同目录章节；b 目录内引用同目录章节（同名）
        self.project.write("a/2 用途.md", "# 2 用途" + NL + NL + "见[概述](1 概述.md)。" + NL)
        self.project.write("b/2 用途.md", "# 2 用途" + NL + NL + "见[概述](1 概述.md)。" + NL)
        self.state = self.project.state
        self.project.writer = ContentWriter(
            self.project.content, self.project.state,
            assets_root=self.project.assets_root,
        )
        self.index = self.project.index()
        ReferenceScanner(self.index, self.project.assets_root).scan_all()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rename_updates_only_references_resolving_to_that_chapter(self):
        plan = RefactorService(self.index).compute_rename_plan(
            "a/1 概述.md", "1 概述（改）.md"
        )
        self.assertTrue(plan.can_apply, plan.conflicts)
        touched = {(edit.rel_path, edit.line_no) for edit in plan.edits}
        self.assertIn(("a/2 用途.md", 3), touched)
        # b 目录的同名引用解析到 b/1 概述.md，不属于本次改名范围
        self.assertNotIn(("b/2 用途.md", 3), touched)

    def test_apply_keeps_other_same_name_reference_intact(self):
        service = RefactorService(self.index)
        plan = service.compute_rename_plan("a/1 概述.md", "1 概述（改）.md")
        service.apply_rename_plan(plan, self.project.writer)
        a_text = (self.project.content / "a" / "2 用途.md").read_text(encoding="utf-8")
        b_text = (self.project.content / "b" / "2 用途.md").read_text(encoding="utf-8")
        self.assertIn("1 概述（改）.md", a_text)
        self.assertIn("(1 概述.md)", b_text)
        self.assertTrue((self.project.content / "b" / "1 概述.md").is_file())


class MermaidSourceCacheTests(unittest.TestCase):
    """3.4：缓存必须对应当前源码；失败保留源码，不影响其它内容。"""

    def test_cache_key_follows_current_source(self):
        first = render(FLOW_A, use_cli=False, want_png=False)
        second = render(FLOW_B, use_cli=False, want_png=False)
        self.assertTrue(first.ok, first.error)
        self.assertTrue(second.ok, second.error)
        self.assertNotEqual(first.svg, second.svg)
        # 回到原源码命中缓存且仍是原图（不会拿新源码的图冒充）
        again = render(FLOW_A, use_cli=False, want_png=False)
        self.assertEqual(again.svg, first.svg)

    def test_invalid_source_keeps_error_and_no_image(self):
        result = render("flowchart TD" + NL + "  A[未闭合 --> B", use_cli=False, want_png=False)
        self.assertFalse(result.ok)
        self.assertTrue(result.error)
        self.assertIsNone(result.png)


if __name__ == "__main__":
    unittest.main()