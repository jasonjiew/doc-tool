# -*- coding: utf-8 -*-
"""UI 包 1.2：顶部「导出 Word」与菜单/Ctrl+E 共用同一 handler 与可用性。

验证事实：
- 顶部按钮、菜单项、Ctrl+E 指向同一个 ``_on_quick_export_word``；
- 日常默认是整份 + 当前缓冲优先 + 有效输出目录，不继承上一轮的部分范围、
  saved 来源或 strict；
- 缺少 Microsoft Word 不阻断可读稿；有冲突任务时只拒绝本次重复启动；
- 顶部提示显示真实未保存章节数量。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    SCOPE_PROJECT,
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED,
)
from doc_tool.ui.main_window import MainWindow  # noqa: E402
from doc_tool.ui.project_bar import ProjectBar  # noqa: E402
from doc_tool.ui.workbench_state import derive_workbench_state  # noqa: E402


class _FakeSummary:
    """真实磁盘项目 + 真实 manifest/paths 的最小摘要（与 CORE-F 用例一致）。"""

    is_writable = True

    def __init__(self, root: Path):
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.project_root = str(root)
        self.manifest = ProjectManifest.load(root)
        self.paths = ProjectPaths(root)


class ProjectBarQuickExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_button_calls_injected_handler(self):
        calls = []
        bar = ProjectBar(on_quick_export=lambda: calls.append(True))
        bar._quick_export_btn.click()
        self.assertEqual(calls, [True])

    def test_availability_ignores_missing_word_but_respects_running(self):
        class _Summary:
            is_writable = True
            manifest = None
            paths = None
            project_root = None
            output_exists = True

        idle = derive_workbench_state(_Summary(), running=False, word_available=False)
        self.assertTrue(idle.actions["quick_export"].enabled)
        self.assertFalse(idle.actions["merge"].enabled)

        busy = derive_workbench_state(_Summary(), running=True, task_label="正式出稿")
        self.assertFalse(busy.actions["quick_export"].enabled)

    def test_tooltip_reports_unsaved_source_and_count(self):
        bar = ProjectBar()
        bar.set_pending_edits(0)
        self.assertIn("整份已保存内容", bar._quick_export_tooltip())
        bar.set_pending_edits(3)
        tooltip = bar._quick_export_tooltip()
        self.assertIn("当前编辑内容", tooltip)
        self.assertIn("3 章未保存修改", tooltip)


class QuickExportWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-quick-export")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        self._patches = [
            patch("doc_tool.application.project_service.load_recent_projects", return_value=[]),
            patch("doc_tool.application.project_service.add_recent_project", return_value=None),
            patch("doc_tool.ui.main_window.QMessageBox.information", lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.warning", lambda *a, **k: None),
            patch.object(QMessageBox, "exec", lambda self: None),
        ]
        for item in self._patches:
            item.start()
        self.summary = _FakeSummary(fixtures.two_chapter_project(self.work / "proj"))
        self.window = MainWindow()
        self.window.resize(1280, 720)
        self.window.show()
        self.window._project_summary = self.summary
        self.window._refresh_interaction_state()
        self._app.processEvents()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def test_button_menu_and_shortcut_share_one_handler(self):
        bar = self.window._project_bar
        self.assertIs(
            bar._on_quick_export.__func__, self.window._on_quick_export_word.__func__
        )
        self.assertIs(bar._on_quick_export.__self__, self.window)
        self.assertEqual(self.window._quick_export_action.shortcut().toString(), "Ctrl+E")
        self.assertTrue(self.window._quick_export_action.isEnabled())

    def test_quick_export_uses_daily_defaults_and_counts_unsaved(self):
        from doc_tool.application import project_export as export_mod

        captured = {}

        class _Report:
            projectRoot = str(self.summary.project_root)
            destination = str(self.summary.paths.output_dir)
            scope = None
            sourceMode = SOURCE_MODE_SAVED
            results = []

            def failed_formats(self):
                return []

            def summary_lines(self, limit=3):
                return ["Word已生成"]

            def usable_results(self):
                return []

        def _fake_run(request, **kwargs):
            captured["request"] = request
            captured["buffer_texts"] = kwargs.get("buffer_texts")
            return _Report()

        # 伪造一章未保存缓冲，验证来源与数量都来自真实编辑器缓冲。
        with patch.object(
            self.window, "_collect_buffer_texts", return_value={"01-x.md": "改过的正文"}
        ), patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            self.window, "_present_export_report", lambda report, **kw: captured.setdefault("presented", True)
        ):
            self.window._on_quick_export_word()
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
            QApplication.processEvents()

        request = captured["request"]
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.scope.kind, SCOPE_PROJECT)
        self.assertTrue(request.scope.is_full)
        self.assertEqual(request.source_mode, SOURCE_MODE_CURRENT_BUFFER)
        self.assertEqual(request.destination, str(self.summary.paths.output_dir))
        self.assertFalse(request.strict)
        self.assertEqual(captured["buffer_texts"], {"01-x.md": "改过的正文"})
        self.assertTrue(captured.get("presented"))

    def test_quick_export_without_buffers_falls_back_to_saved(self):
        from doc_tool.application import project_export as export_mod

        captured = {}

        def _fake_run(request, **kwargs):
            captured["request"] = request
            return None

        with patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            self.window, "_collect_buffer_texts", return_value={}
        ):
            self.window._on_quick_export_word()
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
        self.assertEqual(captured["request"].source_mode, SOURCE_MODE_SAVED)
        self.assertEqual(captured["request"].scope.kind, SCOPE_PROJECT)

    def test_busy_runner_refuses_second_start_and_keeps_state(self):
        captured = []
        # TaskRunner.is_running 是只读属性：直接改内部标志模拟“已有任务运行”。
        self.window.runner._is_running = True
        try:
            with patch(
                "doc_tool.application.project_export.run_project_export",
                lambda request, **kw: captured.append(request),
            ):
                self.window._on_quick_export_word()
        finally:
            self.window.runner._is_running = False
        self.assertEqual(captured, [], "忙时不得重复启动出稿")
        self.assertIn("已有任务正在运行", self.window._status_label.text())

    def test_project_bar_tooltip_reflects_real_unsaved_count(self):
        with patch.object(
            self.window, "_collect_buffer_texts", return_value={"a.md": "x", "b.md": "y"}
        ):
            self.window._refresh_interaction_state()
        tooltip = self.window._project_bar._quick_export_tooltip()
        self.assertIn("当前编辑内容", tooltip)
        self.assertIn("2 章未保存修改", tooltip)


if __name__ == "__main__":
    unittest.main(verbosity=2)