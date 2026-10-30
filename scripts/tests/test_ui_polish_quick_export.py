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
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402
from doc_tool.ui.export_settings_dialog import ExportSettingsDialog  # noqa: E402

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
            patch.object(
                ExportSettingsDialog,
                "exec",
                lambda self: (self._on_submit(), QDialog.DialogCode.Accepted)[1],
            ),
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

    def test_quick_export_reenables_button_and_action_after_completion(self):
        from doc_tool.application import project_export as export_mod

        class _Report:
            roundId = "round-1"
            captureId = "cap-1"
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
            return _Report()

        self.assertTrue(self.window._project_bar._quick_export_btn.isEnabled())
        self.assertTrue(self.window._quick_export_action.isEnabled())

        with patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            self.window, "_present_export_report", lambda report, **kw: None
        ):
            self.window._on_quick_export_word()
            # 导出运行期间按钮与动作被禁用
            self.assertFalse(self.window._project_bar._quick_export_btn.isEnabled())
            self.assertFalse(self.window._quick_export_action.isEnabled())

            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
            QApplication.processEvents()

        # 导出完成后按钮与动作必须重新置为可用（解除置灰）
        self.assertTrue(self.window._project_bar._quick_export_btn.isEnabled())
        self.assertTrue(self.window._quick_export_action.isEnabled())
        self.assertEqual(self.window._current_task, "")

    def test_quick_export_forwards_progress_and_updates_dock(self):
        from doc_tool.application import project_export as export_mod

        class _Report:
            roundId = "round-2"
            captureId = "cap-2"
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

        captured_progress = []
        progress_values = []

        def _fake_run(request, **kwargs):
            prog = kwargs.get("progress")
            captured_progress.append(prog)
            if prog:
                prog("prepare", "started", "正在准备导出内容快照…")
                time.sleep(0.02)
                prog("prepare", "succeeded", "快照就绪")
                time.sleep(0.02)
                prog("build", "started", "开始构建 DOCX")
                time.sleep(0.02)
                prog("build", "succeeded", "DOCX 构建完成")
                time.sleep(0.02)
            return _Report()

        with patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            self.window, "_present_export_report", lambda report, **kw: None
        ):
            self.window._on_quick_export_word()
            # 刚启动时，已为 DOCX 初始化管线步骤清单，进度条不为不可用的破损状态
            dock = self.window._task_dock
            self.assertGreater(dock._step_list.count(), 0)

            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                progress_values.append(dock._step_footer._progress.value())
                time.sleep(0.02)
            QApplication.processEvents()

        self.assertIsNotNone(captured_progress[0], "run_project_export 必须收到 progress 回调")
        # 进度条在导出运行过程中真实推进
        distinct_progress = set(progress_values)
        self.assertTrue(any(v > 0 for v in distinct_progress), "导出期间进度条必须有大于0的推进数值")
        # 导出结束后按钮恢复可用
        self.assertTrue(self.window._project_bar._quick_export_btn.isEnabled())


    def test_quick_export_terminal_result_state_and_dock_preservation(self):
        from doc_tool.application import project_export as export_mod
        from doc_tool.application.intake_contract import FormatResult

        out_file = self.summary.paths.output_dir / "test.docx"
        out_file.write_bytes(b"dummy")

        class _Report:
            roundId = "round-succ"
            captureId = "cap-succ"
            projectRoot = str(self.summary.project_root)
            destination = str(self.summary.paths.output_dir)
            scope = None
            sourceMode = SOURCE_MODE_SAVED
            results = [
                FormatResult(format=FORMAT_DOCX, status="ready", path=str(out_file))
            ]

            def failed_formats(self):
                return []

            def summary_lines(self, limit=3):
                return ["Word已生成"]

            def usable_results(self):
                return self.results

        def _fake_run(request, **kwargs):
            return _Report()

        with patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            self.window, "_present_export_report", lambda report, **kw: None
        ):
            self.window._on_quick_export_word()
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
            QApplication.processEvents()

        # 终态校验：_result_state 必须被赋予 terminal 状态，而非停留在 running
        self.assertTrue(self.window._result_state.is_terminal)
        self.assertEqual(self.window._result_state.status, "success")
        self.assertEqual(self.window._result_state.task, "project-export")
        self.assertEqual(self.window._result_state.title, "导出完成")

        # TaskDock 必须展示结果卡片，按钮与菜单项全部恢复可用
        self.assertTrue(self.window._task_dock._has_result)
        self.assertTrue(self.window._project_bar._quick_export_btn.isEnabled())
        self.assertTrue(self.window._project_bar._export_settings_btn.isEnabled())
        self.assertTrue(self.window._quick_export_action.isEnabled())
        if hasattr(self.window, "_export_settings_action"):
            self.assertTrue(self.window._export_settings_action.isEnabled())

    def test_html_only_export_shows_dedicated_steps_without_docx_stages(self):
        from doc_tool.application import project_export as export_mod
        from doc_tool.application.intake_contract import ExportRequest, ExportScope, FORMAT_HTML

        html_dir = self.summary.paths.output_dir / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        index_file = html_dir / "index.html"
        index_file.write_text("<html></html>", encoding="utf-8")

        class _Report:
            roundId = "round-html"
            captureId = "cap-html"
            projectRoot = str(self.summary.project_root)
            destination = str(self.summary.paths.output_dir)
            scope = None
            sourceMode = SOURCE_MODE_SAVED
            results = []

            def failed_formats(self):
                return []

            def summary_lines(self, limit=3):
                return ["HTML已生成"]

            def usable_results(self):
                return []

        def _fake_run(request, **kwargs):
            prog = kwargs.get("progress")
            if prog:
                prog("html", "开始生成离线 HTML")
                time.sleep(0.02)
                prog("html", "离线 HTML 已生成")
                time.sleep(0.02)
            return _Report()

        req = ExportRequest(
            formats=[FORMAT_HTML],
            scope=ExportScope(kind="project"),
            destination=str(self.summary.paths.output_dir),
        )

        with patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            self.window, "_present_export_report", lambda report, **kw: None
        ):
            self.window._submit_export_request(req)
            # 刚启动时，步骤清单只包含 HTML 专用步骤，不得泄漏 DOCX 8阶段
            steps = self.window._task_dock._step_list
            self.assertEqual(steps.count(), 1)

            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
            QApplication.processEvents()

        self.assertTrue(self.window._result_state.is_terminal)
        self.assertEqual(self.window._result_state.status, "success")
        self.assertTrue(self.window._project_bar._quick_export_btn.isEnabled())

    def test_project_bar_reset_disables_export_settings_btn(self):
        bar = ProjectBar()
        bar._export_settings_btn.setEnabled(True)
        bar.reset()
        self.assertFalse(bar._export_settings_btn.isEnabled())
        self.assertFalse(bar._quick_export_btn.isEnabled())


    def test_quick_export_open_cancel_and_reopen_confirm(self):
        """Task 4.5: 打开设置、取消、再次打开并确认的真实 Qt 回归。"""
        from doc_tool.application import project_export as export_mod

        captured = []
        def _fake_run(request, **kwargs):
            captured.append(request)
            return None

        # 1. 模拟取消：执行零任务、零正文写入
        with patch.object(
            ExportSettingsDialog, "exec", lambda self: QDialog.DialogCode.Rejected
        ):
            self.window._on_quick_export_word()
        self.assertEqual(len(captured), 0, "取消设置不应提交任何任务")
        self.assertIn("已取消导出设置", self.window._status_label.text())

        # 2. 再次打开并确认：正常提交
        with patch.object(export_mod, "run_project_export", _fake_run), patch.object(
            ExportSettingsDialog,
            "exec",
            lambda self: (self._on_submit(), QDialog.DialogCode.Accepted)[1],
        ):
            self.window._on_quick_export_word()
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
        self.assertEqual(len(captured), 1, "确认后应且仅提交一次任务")

    def test_quick_export_real_events_button_and_shortcut(self):
        """Task 9.2: 用真实 Qt 按钮点击和 Ctrl+E 快捷键驱动打开→取消→重开→确认。"""
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt, QTimer
        from doc_tool.application.intake_contract import FORMAT_DOCX, SOURCE_MODE_CURRENT_BUFFER

        # 临时停止 setup 中的 exec patch，让测试面对真实 ExportSettingsDialog
        self._patches[5].stop()
        try:
            self.window.show()
            self.window.activateWindow()
            self.window._refresh_interaction_state()
            QApplication.processEvents()
            self.assertTrue(self.window._quick_export_action.isEnabled())

            submissions = []
            self.window._submit_export_request = lambda req: submissions.append(req)
            self.window._collect_buffer_texts = lambda: {"01-x.md": "活缓冲修改"}

            # 1. 项目条按钮点击 -> 弹出设置 -> 取消
            def _on_cancel():
                dlgs = [w for w in QApplication.topLevelWidgets() if isinstance(w, ExportSettingsDialog) and w.isVisible()]
                if dlgs:
                    dlgs[0].reject()
                else:
                    QTimer.singleShot(20, _on_cancel)

            QTimer.singleShot(30, _on_cancel)
            self.window._project_bar._quick_export_btn.click()
            QApplication.processEvents()

            self.assertEqual(len(submissions), 0, "取消设置不应提交任务")
            self.assertIn("已取消导出设置", self.window._status_label.text())

            # 2. 真实 Ctrl+E 快捷键 -> 弹出设置 -> 确认
            def _on_confirm():
                dlgs = [w for w in QApplication.topLevelWidgets() if isinstance(w, ExportSettingsDialog) and w.isVisible()]
                if dlgs:
                    dlgs[0]._submit_btn.click()
                else:
                    QTimer.singleShot(20, _on_confirm)

            QTimer.singleShot(30, _on_confirm)
            self.window.activateWindow()
            QTest.keyClick(self.window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
            QApplication.processEvents()

            self.assertEqual(len(submissions), 1, "确认后应且仅提交一次任务")
            req = submissions[0]
            self.assertEqual(req.formats, [FORMAT_DOCX])
            self.assertEqual(req.source_mode, SOURCE_MODE_CURRENT_BUFFER)
        finally:
            self._patches[5].start()

if __name__ == "__main__":
    unittest.main(verbosity=2)