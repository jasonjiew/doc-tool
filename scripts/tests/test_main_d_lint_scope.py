# -*- coding: utf-8 -*-
"""MAIN-D：检查范围与活内容、确定性修复的差异/应用/撤销。"""

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
from doc_tool.application.content.lint import (  # noqa: E402
    ContentLinter,
    LintIssue,
    TermStore,
)
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402
from doc_tool.application.content.writer import ContentWriter  # noqa: E402

NL = chr(10)


class LintScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-d-lint-"))
        self.content = self.tmp / "content" / "general"
        self.content.mkdir(parents=True)
        self.state = self.tmp / ".state"
        self.state.mkdir()
        # 两个文件都有标题格式问题（'#' 后缺空格）
        (self.content / "1 概述.md").write_text(
            "#1 概述" + NL + "正文。" + NL, encoding="utf-8"
        )
        (self.content / "2 设计.md").write_text(
            "#2 设计" + NL + "正文。" + NL, encoding="utf-8"
        )
        self.writer = ContentWriter(self.content, self.state)
        self.index = ContentIndexService(self.content).build()
        self.rules = QualityRulesConfig(self.state, "general")

        from doc_tool.ui.content.lint_panel import LintPanel

        self.confirmed = []
        self.panel = LintPanel(
            ContentLinter(self.index, self.rules),
            TermStore(self.state),
            writable=True,
            writer=self.writer,
            scope_provider=lambda: ("current", "1 概述.md", ["1 概述.md"]),
            live_text_provider=lambda rel: self.buffer.get(rel),
            scoped_linter_provider=self._scoped,
            confirm_fix=self._confirm,
        )
        self.buffer = {}

    def tearDown(self):
        self.panel.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scoped(self, scope_paths, overrides):
        service = ContentIndexService(self.content, override_texts=dict(overrides))
        index = service.build(save_cache=False)
        if scope_paths is not None:
            allowed = set(scope_paths)
            for mapping in (index.files, index.lines, index.headings, index.references):
                for key in [k for k in mapping if k not in allowed]:
                    mapping.pop(key, None)
        return ContentLinter(index, self.rules)

    def _confirm(self, rel_path, before, after):
        self.confirmed.append((rel_path, before, after))
        return True

    def test_scope_current_chapter_uses_unsaved_buffer(self):
        # 缓冲里已经把问题修好（'# 1 概述'），磁盘仍是旧内容
        self.buffer["1 概述.md"] = "# 1 概述" + NL + "正文。" + NL
        self.panel._scope_combo.setCurrentIndex(1)  # 当前章
        self.panel.run_check()
        rel_paths = {issue.rel_path for issue in self.panel._issues}
        self.assertEqual(rel_paths, set(), "缓冲已修复的问题不应再按旧磁盘正文报告")
        # 切回整份仍能报告磁盘上的问题（另一文件）
        self.panel._scope_combo.setCurrentIndex(0)
        self.panel.run_check()
        self.assertIn("2 设计.md", {issue.rel_path for issue in self.panel._issues})

    def test_scope_selected_chapters_limits_reported_files(self):
        self.panel._scope_combo.setCurrentIndex(2)  # 所选章（provider 返回 1 概述.md）
        self.panel.run_check()
        self.assertEqual(
            {issue.rel_path for issue in self.panel._issues}, {"1 概述.md"}
        )

    def test_quick_fix_shows_diff_and_can_be_undone(self):
        self.panel._scope_combo.setCurrentIndex(1)
        self.panel.run_check()
        self.assertTrue(self.panel._issues)
        issue = self.panel._issues[0]
        before_text = (self.content / issue.rel_path).read_text(encoding="utf-8")
        self.assertTrue(self.panel.quick_fix_issue(issue))
        # 应用前有差异确认，且确认内容就是真实的修复前后正文
        self.assertTrue(self.confirmed)
        rel_path, before, after = self.confirmed[-1]
        self.assertEqual(rel_path, issue.rel_path)
        self.assertIn("#1 ", before)
        self.assertIn("# 1 ", after)
        self.assertNotEqual(before, after)
        self.assertTrue(self.panel._undo_fix_btn.isEnabled())
        # 撤销后回到修复前正文
        self.assertTrue(self.panel.undo_last_fix())
        self.assertEqual(
            (self.content / issue.rel_path).read_text(encoding="utf-8"), before_text
        )

    def test_quick_fix_writes_to_live_buffer_without_saving(self):
        self.buffer["1 概述.md"] = "#1 概述" + NL + "缓冲正文。" + NL
        self.panel._scope_combo.setCurrentIndex(1)
        self.panel.run_check()
        issue = next(
            item for item in self.panel._issues if item.rel_path == "1 概述.md"
        )
        applied = {}

        def _applier(rel_path, new_text):
            applied[rel_path] = new_text
            self.buffer[rel_path] = new_text
            return True

        self.panel._buffer_applier = _applier
        self.assertTrue(self.panel.quick_fix_issue(issue))
        self.assertIn("# 1 概述", applied["1 概述.md"])
        # 磁盘没有被隐式保存
        disk = (self.content / "1 概述.md").read_text(encoding="utf-8")
        self.assertIn("#1 概述", disk)
        self.assertNotIn("# 1 概述", disk)


class PreviewLifecycleTests(unittest.TestCase):
    """MAIN-D 4.3：切章/关闭时挂起的预览去抖不得污染新章节。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-d-preview-"))
        self.content = self.tmp / "content"
        self.content.mkdir(parents=True)
        self.state = self.tmp / ".state"
        self.state.mkdir()
        self.writer = ContentWriter(self.content, self.state)
        from doc_tool.ui.content.editor_panel import EditorPanel

        self.editor = EditorPanel(self.writer, writable=True)

    def tearDown(self):
        self.editor.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _preview_text(self) -> str:
        return self.editor._preview.toPlainText()

    def test_pending_debounce_does_not_leak_into_next_chapter(self):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtTest import QTest

        self.editor.load("1 概述.md", "# 概述" + NL + NL + "第一章正文。" + NL)
        cursor = self.editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("追加内容。" + NL)
        # 去抖尚未触发时立即切章
        self.editor.load("2 设计.md", "# 设计" + NL + NL + "第二章正文。" + NL)
        QTest.qWait(800)
        QCoreApplication.processEvents()
        text = self._preview_text()
        self.assertIn("第二章正文", text)
        self.assertNotIn("追加内容", text)
        self.assertEqual(self.editor.current_rel_path(), "2 设计.md")

    def test_close_stops_pending_preview_timer(self):
        from PySide6.QtTest import QTest

        self.editor.load("1 概述.md", "# 概述" + NL)
        cursor = self.editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("改动。" + NL)
        self.assertTrue(self.editor._preview_timer.isActive())
        self.editor.close()
        QTest.qWait(100)
        self.assertFalse(self.editor._preview_timer.isActive())


if __name__ == "__main__":
    unittest.main()