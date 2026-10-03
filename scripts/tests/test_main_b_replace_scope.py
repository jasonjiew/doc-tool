# -*- coding: utf-8 -*-
"""MAIN-B 2.1/2.4：替换范围、活缓冲与预览后变化处理。"""

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

from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.replace import ReplaceService  # noqa: E402
from doc_tool.application.content.writer import ContentWriter  # noqa: E402

NL = chr(10)


class _Project:
    """最小项目：两章正文 + 可回滚写入服务。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.content = root / "content" / "general"
        self.content.mkdir(parents=True, exist_ok=True)
        (root / "assets" / "general" / "images").mkdir(parents=True, exist_ok=True)
        (self.content / "1 概述.md").write_text(
            "# 概述" + NL + NL + "术语甲用于说明。" + NL, encoding="utf-8"
        )
        (self.content / "2 设计.md").write_text(
            "# 设计" + NL + NL + "术语甲在设计章。" + NL, encoding="utf-8"
        )
        self.state = root / ".state"
        self.state.mkdir(parents=True, exist_ok=True)
        self.writer = ContentWriter(self.content, self.state)
        self.index = ContentIndexService(self.content).build()
        self.service = ReplaceService(self.index)

    def rel(self, name: str) -> str:
        return name

    def read(self, name: str) -> str:
        return (self.content / name).read_text(encoding="utf-8")


class ReplaceScopeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-b-replace-"))
        self.project = _Project(self.tmp / "proj")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scope_paths_limit_matches_to_selected_chapter(self):
        matches = self.project.service.find_matches(
            "术语甲", scope_paths=["2 设计.md"]
        )
        self.assertEqual([m.rel_path for m in matches], ["2 设计.md"])
        whole = self.project.service.find_matches("术语甲")
        self.assertEqual(len(whole), 2)

    def test_unsaved_buffer_is_searched(self):
        overrides = {"1 概述.md": "# 概述" + NL + NL + "缓冲里的术语乙。" + NL}
        matches = self.project.service.find_matches(
            "术语乙", scope_paths=["1 概述.md"], text_overrides=overrides
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rel_path, "1 概述.md")
        # 未保存内容不进磁盘：磁盘上仍查不到
        self.assertEqual(self.project.service.find_matches("术语乙"), [])

    def test_buffer_apply_keeps_disk_untouched_and_reports_written(self):
        overrides = {"1 概述.md": "# 概述" + NL + NL + "缓冲里的术语乙。" + NL}
        matches = self.project.service.find_matches(
            "术语乙", scope_paths=["1 概述.md"], text_overrides=overrides
        )
        applied = {}

        def _applier(rel_path, new_text):
            applied[rel_path] = new_text
            return True

        results = self.project.service.apply_matches(
            matches, "术语丙", self.project.writer,
            text_overrides=overrides, buffer_applier=_applier,
        )
        self.assertTrue(all(r.written for r in results))
        self.assertIn("术语丙", applied["1 概述.md"])
        # 磁盘未被隐式保存：仍是替换前的磁盘正文，缓冲内容既没落盘也没被覆盖
        disk = self.project.read("1 概述.md")
        self.assertIn("术语甲用于说明。", disk)
        self.assertNotIn("术语丙", disk)
        self.assertNotIn("术语乙", disk)

    def test_stale_line_skips_that_file_and_continues_others(self):
        matches = self.project.service.find_matches("术语甲")
        self.assertEqual(len(matches), 2)
        # 预览后磁盘上的设计章被外部改动：命中行文本不再匹配
        (self.project.content / "2 设计.md").write_text(
            "# 设计" + NL + NL + "外部改写的正文。" + NL, encoding="utf-8"
        )
        results = self.project.service.apply_matches(
            matches, "术语丙", self.project.writer
        )
        by_file = {r.rel_path: r for r in results}
        self.assertTrue(by_file["1 概述.md"].written)
        self.assertFalse(by_file["2 设计.md"].written)
        self.assertIn("已变化", by_file["2 设计.md"].error or "")
        self.assertIn("术语丙", self.project.read("1 概述.md"))
        self.assertIn("外部改写的正文。", self.project.read("2 设计.md"))


class ReplacePanelBufferTests(unittest.TestCase):
    """面板级：范围下拉 + 未保存缓冲替换（离屏 Qt，不落盘）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-b-panel-"))
        self.project = _Project(self.tmp / "proj")
        from doc_tool.ui.content.replace_panel import ReplacePanel

        self.buffer = {}
        self.panel = ReplacePanel(
            self.project.service,
            self.project.writer,
            scope_provider=lambda: ("current", "1 概述.md", ["1 概述.md"]),
            live_text_provider=lambda rel: self.buffer.get(rel),
            buffer_applier=self._apply,
        )

    def tearDown(self):
        self.panel.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _apply(self, rel_path, new_text):
        self.buffer[rel_path] = new_text
        return True

    def test_current_chapter_scope_uses_unsaved_buffer(self):
        self.buffer["1 概述.md"] = "# 概述" + NL + NL + "缓冲里的术语乙。" + NL
        self.panel._scope_box.setCurrentIndex(1)  # 当前章
        self.panel._find_entry.setText("术语乙")
        self.panel.find_all()
        self.assertEqual(len(self.panel._matches), 1)
        self.panel._tree.setCurrentItem(self.panel._tree.topLevelItem(0))
        self.panel._replace_entry.setText("术语丙")
        self.panel.replace_one()
        self.assertIn("术语丙", self.buffer["1 概述.md"])
        # 磁盘未被隐式保存：缓冲内容与替换结果都不落盘
        disk = self.project.read("1 概述.md")
        self.assertNotIn("术语丙", disk)
        self.assertNotIn("术语乙", disk)
        self.assertIn("术语甲用于说明。", disk)


class BufferExportTests(unittest.TestCase):
    """MAIN-B 2.4：替换后导出仍使用活缓冲（不依赖是否保存）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-b-export-"))
        self.project = _Project(self.tmp / "proj")
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION

        ProjectManifest(
            documentType="general",
            documentNo="T-1",
            documentName="测试",
            documentVersion="1.0",
            sourceSha256="",
            schemaVersion=PROJECT_SCHEMA_VERSION,
            paths={
                "contentRoot": "content/general",
                "assetRoot": "assets/general",
                "tableRoot": "assets/general/tables",
            },
        ).save(self.project.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_capture_snapshot_uses_live_buffer_after_replace(self):
        from doc_tool.application.effective_snapshot import capture_snapshot

        overrides = {"1 概述.md": "# 概述" + NL + NL + "缓冲里的术语乙。" + NL}
        matches = self.project.service.find_matches(
            "术语乙", scope_paths=["1 概述.md"], text_overrides=overrides
        )
        applied = {}

        def _applier(rel_path, new_text):
            applied[rel_path] = new_text
            return True

        self.project.service.apply_matches(
            matches, "术语丙", self.project.writer,
            text_overrides=overrides, buffer_applier=_applier,
        )
        self.assertIn("术语丙", applied["1 概述.md"])
        snapshot = capture_snapshot(
            self.project.root,
            source_mode="current-buffer",
            buffer_texts=applied,
        )
        self.assertIn("1 概述.md", snapshot.captureIndex)
        candidates = sorted(Path(snapshot.workDir).rglob("1 概述.md"))
        self.assertTrue(candidates, "快照工作目录应包含该章")
        text = candidates[0].read_text(encoding="utf-8")
        self.assertIn("术语丙", text)
        self.assertNotIn("术语乙", text)
        # 磁盘仍是替换前内容：导出结果来自活缓冲而不是被隐式保存
        self.assertNotIn("术语丙", self.project.read("1 概述.md"))


class FormatToolCodeFenceTests(unittest.TestCase):
    """MAIN-B 2.2：标题/列表工具不改写围栏代码块，空行不变成空列表项。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-b-format-"))
        self.project = _Project(self.tmp / "proj")
        from doc_tool.ui.content.editor_panel import EditorPanel

        self.editor = EditorPanel(self.project.writer, writable=True)

    def tearDown(self):
        self.editor.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _load(self, text):
        from PySide6.QtGui import QTextCursor as Cursor

        self.editor.load("1 概述.md", text)
        cursor = self.editor._editor.textCursor()
        cursor.movePosition(Cursor.MoveOperation.Start)
        self.editor._editor.setTextCursor(cursor)
        return self.editor._editor

    def _select_all(self):
        from PySide6.QtGui import QTextCursor as Cursor

        cursor = self.editor._editor.textCursor()
        cursor.select(Cursor.SelectionType.Document)
        self.editor._editor.setTextCursor(cursor)

    def test_heading_tool_skips_fenced_code(self):
        body = (
            "# 概述" + NL + NL + "说明文字。" + NL + NL
            + "\x60\x60\x60python" + NL + "def f():" + NL + "    return 1" + NL
            + "\x60\x60\x60" + NL + NL + "结尾。" + NL
        )
        self._load(body)
        self._select_all()
        self.editor.apply_heading_level(2)
        text = self.editor.plain_text()
        self.assertIn("## 概述", text)
        self.assertIn("## 说明文字。", text)
        self.assertIn("def f():", text)
        # 代码行与围栏未被加标题、缩进保持
        self.assertIn("\x60\x60\x60python" + NL + "def f():" + NL + "    return 1", text)
        self.assertNotIn("## def f()", text)

    def test_list_tool_skips_code_and_blank_lines(self):
        body = (
            "# 概述" + NL + NL + "第一段。" + NL + NL
            + "\x60\x60\x60" + NL + "code line" + NL + "\x60\x60\x60" + NL + NL
            + "第二段。" + NL
        )
        self._load(body)
        self._select_all()
        self.editor._prefix_lines("- ")
        text = self.editor.plain_text()
        self.assertIn("- 第一段。", text)
        self.assertIn("- 第二段。", text)
        self.assertIn("code line", text)
        self.assertNotIn("- code line", text)
        self.assertNotIn("- \x60\x60\x60", text)
        # 空行保持为空（不产生空列表项）
        self.assertNotIn("- " + NL, text)


if __name__ == "__main__":
    unittest.main()