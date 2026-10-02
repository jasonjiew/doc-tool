# -*- coding: utf-8 -*-
"""V3.3 5.4 补测：应用内“采纳 → 一次撤销 → 保存”链路可达（走真实面板接线）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

ADOPTED_TERM = "DocTool"
RAW_TERM = "文档工具"


class AdoptionEditorChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v33-adopt-editor")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        from doc_tool.application.effective_snapshot import discover_chapters

        content = cls.project / "content" / "general"
        cls.chapters = [rel for rel, _path in discover_chapters(content)]
        cls.rel = cls.chapters[0]
        (content / cls.rel).write_text(
            "# 目的\n\n本项目为{0}，负责导入与出稿。\n\n## 范围\n\n覆盖导入。\n".format(RAW_TERM),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _window_with_project(self):
        from doc_tool.application.project_service import load_recent_projects  # noqa: F401
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        self._recent.start()
        # 采纳后编辑器是脏的：关闭时必须给明确选择，否则会弹真实模态框阻塞离屏测试
        from doc_tool.ui.content.unsaved_prompt import UnsavedChoice

        window = MainWindow(unsaved_resolver=lambda rel, ctx: UnsavedChoice.DISCARD)
        summary = SimpleNamespace(
            project_root=self.project,
            is_writable=True,
            manifest=ProjectManifest.load(self.project),
            paths=ProjectPaths(self.project),
        )
        window._project_summary = summary
        window._init_content_workspace(summary)
        self.assertTrue(window._open_chapter_in_workspace(self.rel), "应能打开章节")
        return window

    def _open_panel_with_alias_assistant(self, window):
        from doc_tool.application.assist.service import build_assistant as real_build

        assistant = real_build(self.project, terms=[ADOPTED_TERM], term_aliases={RAW_TERM: ADOPTED_TERM})
        with patch("doc_tool.application.assist.service.build_assistant", return_value=assistant):
            with patch("doc_tool.application.assist.commands.build_assist_overview", create=True):
                window._on_assist_panel()
        dock = getattr(window, "_assist_dock", None)
        self.assertIsNotNone(dock, "辅助面板应已打开")
        return dock.widget(), assistant

    def _editor(self, window):
        """标签键带文档类型前缀（general/…），这里两种键都试一次。"""
        tabs = window._content_workspace.tabs_host
        for key in ("general/" + self.rel, self.rel):
            editor = tabs.editor_for(key)
            if editor is not None:
                return editor
        self.fail("章节未在工作区打开：{0}".format(self.rel))

    def _check_applicable(self, panel, collected):
        """勾选当前可采纳的建议（面板每次 set_suggestions 都会重置勾选状态）。"""
        from PySide6.QtCore import Qt

        applicable = [item for item in collected.suggestions if item.applicable]
        self.assertTrue(applicable, [item.to_dict() for item in collected.suggestions])
        list_widget = panel._suggestions_list
        wanted = {item.suggestion_id for item in applicable}
        for row in range(list_widget.count()):
            widget_item = list_widget.item(row)
            suggestion = widget_item.data(Qt.ItemDataRole.UserRole)
            if suggestion is not None and suggestion.suggestion_id in wanted:
                widget_item.setCheckState(Qt.CheckState.Checked)
        self.assertTrue(panel.checked_suggestion_ids(), "应至少勾选一条建议")
        return applicable

    def test_adopt_undo_and_save_through_editor(self):
        window = self._window_with_project()
        try:
            editor = self._editor(window)
            target = editor._editor
            original = target.toPlainText()
            self.assertIn(RAW_TERM, original)

            panel, assistant = self._open_panel_with_alias_assistant(window)
            from doc_tool.application.assist.models import KIND_TERM

            collected = panel.load_suggestions([KIND_TERM])
            self.assertIsNotNone(collected, "面板应加载建议")
            applicable = [item for item in collected.suggestions if item.applicable]
            self.assertTrue(applicable, [item.to_dict() for item in collected.suggestions])

            # 勾选并按真实路径采纳
            panel.set_suggestions(collected)
            self._check_applicable(panel, collected)
            outcome = panel.adopt_selected()
            self.assertIsNotNone(outcome, "应能采纳")
            text = target.toPlainText()
            self.assertIn(ADOPTED_TERM, text, "采纳结果应写回编辑器")
            self.assertNotIn(RAW_TERM, text, "非规范写法应被替换")

            # 出稿/保存依赖的缓冲收集应包含采纳后的文本
            buffers = window._collect_buffer_texts()
            self.assertIn(ADOPTED_TERM, buffers.get(self.rel, ""), list(buffers))

            # 保存：走既有编辑器保存路径（ContentWriter：备份 + 原子写 + 改动清单）
            self.assertTrue(editor.save(), "编辑器保存应成功")
            on_disk = (self.project / "content" / "general" / self.rel).read_text(encoding="utf-8")
            self.assertIn(ADOPTED_TERM, on_disk, "保存应经 ContentWriter 落盘采纳后的文本")

            # 面板撤销 → 缓冲恢复，宿主编辑器同步回退（同样是可撤销的一次改动）
            self.assertTrue(panel.undo_last(), "面板撤销应成功")
            self.assertIn(RAW_TERM, target.toPlainText(), "面板撤销后编辑器应恢复原文")
        finally:
            self._recent.stop()
            window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)