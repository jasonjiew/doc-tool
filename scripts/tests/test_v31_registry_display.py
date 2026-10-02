# -*- coding: utf-8 -*-
"""V3.1 spec 缺口补测：注册表命令结果必须显示、参数必须补齐、历史含缓冲比较。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class RegistryResultDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v31-reg-display")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _window(self):
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        self._recent.start()
        window = MainWindow()
        window._project_summary = SimpleNamespace(
            project_root=self.project, is_writable=True,
            manifest=ProjectManifest.load(self.project), paths=ProjectPaths(self.project),
        )
        window._reset_command_registry()
        return window

    def _row(self, window, command_id: str) -> dict:
        for row in window._ensure_command_registry().palette_items(window._command_context()):
            if row.get("commandId") == command_id:
                return row
        self.fail("命令不存在：" + command_id)

    def _capture_display(self, window):
        captured = []
        window._show_result_dialog = lambda title, body, detail="": captured.append(
            {"title": title, "text": body, "detail": detail}
        )
        return captured

    def test_todo_command_result_is_shown_not_discarded(self):
        window = self._window()
        try:
            captured = self._capture_display(window)
            row = self._row(window, "team.my-todos")
            window._make_registry_callback(row)()
            self.assertTrue(captured, "待办结果必须显示，不能丢弃")
            blob = captured[-1]["text"] + captured[-1]["detail"]
            self.assertIn("counts", blob)
            self.assertIn("我的待办", captured[-1]["title"])
        finally:
            self._recent.stop()
            window.close()

    def test_handoff_apply_prompts_for_package_and_shows_plan(self):
        from doc_tool.application.content.handoff import export_handoff_package
        from doc_tool.application.effective_snapshot import discover_chapters

        package_dir = self.work / "交接"
        package_dir.mkdir(parents=True, exist_ok=True)
        chapters = [rel for rel, _path in discover_chapters(self.project / "content" / "general")]
        export_handoff_package(self.project, package_dir, chapters=chapters)
        candidates = sorted(package_dir.rglob("*.zip"))
        self.assertTrue(candidates, "交接包应生成")
        package = candidates[-1]

        window = self._window()
        try:
            captured = self._capture_display(window)
            row = self._row(window, "team.handoff-apply")
            with patch(
                "doc_tool.ui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(package), ""),
            ):
                window._make_registry_callback(row)()
            self.assertTrue(captured, "应用命令必须显示结果（计划/已应用）")
            blob = captured[-1]["text"] + captured[-1]["detail"]
            self.assertTrue("plan" in blob or "applied" in blob, blob[:240])
        finally:
            self._recent.stop()
            window.close()

    def test_history_command_uses_editor_buffer_for_comparison(self):
        window = self._window()
        try:
            window._init_content_workspace(window._project_summary)
            workspace = window._content_workspace
            self.assertIsNotNone(workspace)
            opened = window._open_chapter_in_workspace("第1章 引言/1.1 目的.md")
            self.assertTrue(opened, "应能打开章节")
            from doc_tool.application.content.team_entry import CMD_CHAPTER_HISTORY

            row = self._row(window, CMD_CHAPTER_HISTORY)
            payload = window._augment_registry_payload(row)
            self.assertIn("buffer_text", payload, payload)
            self.assertTrue(payload["buffer_text"].strip(), payload)

            # handler 拿到缓冲后必须给出比较结果（无 Git 时退回本地历史/当前）
            from doc_tool.application.command_registry import CommandContext

            result = window._ensure_command_registry().invoke(
                CMD_CHAPTER_HISTORY, window._command_context(), payload,
            )
            self.assertTrue(result.ok, getattr(result, "message", ""))
            value = result.value or {}
            self.assertEqual(value.get("chapter"), "第1章 引言/1.1 目的.md")
            self.assertIn("bufferCompared", value)
        finally:
            self._recent.stop()
            window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)