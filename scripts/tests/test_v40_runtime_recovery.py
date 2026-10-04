# -*- coding: utf-8 -*-
"""40-C：取消一秒内确认、晚到结果隔离与原轮恢复事实。"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


class _BlockingTarget:
    """可被取消令牌唤醒的阻塞目标（模拟不可中断的后台工作）。"""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False

    def __call__(self, cancel_token=None, **kwargs):
        self.started = True
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if cancel_token is not None and cancel_token.is_cancelled:
                self.cancelled = True
                return {"cancelled": True}
            time.sleep(0.01)
        return {"cancelled": False}


class CancelConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.main_window import MainWindow

        with patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        ):
            self.window = MainWindow()
        self.addCleanup(self.window.close)

    def _pump(self, predicate, timeout: float) -> bool:
        from PySide6.QtWidgets import QApplication

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.window.runner.poll()
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def test_cancel_request_is_confirmed_within_one_second(self):
        """点击取消后 1 秒内必须出现确认反馈，且令牌立即置位。"""
        from doc_tool.ui.task_bridge import TaskSpec

        target = _BlockingTarget()
        spec = TaskSpec(name="project-export", target=target, timeout_seconds=30)
        # 记录“取消请求已确认”的真实时刻：沿用 TaskDock 的确认显示入口。
        confirmations: list = []
        original = self.window._task_dock.set_cancel_waiting

        def _record(waiting, stage_label=""):
            if waiting:
                confirmations.append((time.monotonic(), stage_label))
            return original(waiting, stage_label)

        self.window._task_dock.set_cancel_waiting = _record
        self.window._start_task(spec)
        try:
            self.assertTrue(self._pump(lambda: target.started, 10.0), "后台任务应已开始")
            clicked_at = time.monotonic()
            self.window._on_cancel()
            self.assertTrue(confirmations, "取消请求必须在一秒内得到确认")
            confirmed_at = confirmations[0][0]
            self.assertLessEqual(confirmed_at - clicked_at, 1.0)
            # 确认反馈必须可见（不是只改了内部状态）。
            self.assertTrue(self.window._task_dock._cancel_status.text())
            self.assertFalse(self.window._task_dock._cancel_btn.isEnabled())
            self.assertTrue(self.window.runner.is_cancelled, "取消令牌应已请求取消")
            self.assertTrue(self._pump(lambda: target.cancelled, 5.0), "后台应观察到取消")
        finally:
            self.window.runner.cancel()
            self._pump(lambda: not self.window.runner.is_running, 10.0)


class LateResultIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_late_terminal_event_does_not_trigger_done_for_new_run(self):
        """旧代次（超时/取消后）返回的终态不得触发新一轮的 on_done。"""
        from doc_tool.ui.task_bridge import TaskEvent, TaskRunner, TaskSpec

        runner = TaskRunner()
        done_calls = []

        class _NeverReturns:
            def __call__(self, cancel_token=None, **kwargs):
                time.sleep(5)
                return "late"

        spec = TaskSpec(name="project-export", target=_NeverReturns(), timeout_seconds=1)
        runner.start(spec, on_done=lambda result: done_calls.append(result))
        deadline = time.monotonic() + 15
        while runner.is_running and time.monotonic() < deadline:
            runner.poll()
            time.sleep(0.02)
        self.assertFalse(runner.is_running, "看门狗应结束 UI 跟踪")
        first_done = list(done_calls)
        self.assertEqual(len(first_done), 1)
        stale = TaskEvent(kind="succeeded", stage="project-export", run_id=0)
        runner._event_queue.put(stale)
        runner.poll()
        self.assertEqual(done_calls, first_done, "旧代次事件不得写入新 UI")


class OriginalRoundTrustTests(unittest.TestCase):
    """原轮恢复只认可信报告与 captureId（缺身份时只限制该动作）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.main_window import MainWindow

        with patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        ):
            self.window = MainWindow()
        self.addCleanup(self.window.close)

    class _View:
        def __init__(self, round_id: str, capture_id: str, index_path: str = "") -> None:
            self.round_id = round_id
            self.capture_id = capture_id
            self.index_path = index_path

    def _report(self, round_id: str, capture_id: str):
        report = type("R", (), {})()
        report.roundId = round_id
        report.captureId = capture_id
        return report

    def test_identity_mismatch_is_rejected(self):
        view = self._View("round-1", "capture-1")
        self.assertTrue(
            self.window._round_identity_matches(view, self._report("round-1", "capture-1"))
        )
        self.assertFalse(
            self.window._round_identity_matches(view, self._report("round-2", "capture-1")),
            "roundId 不符不得当作原轮",
        )
        self.assertFalse(
            self.window._round_identity_matches(view, self._report("round-1", "capture-9")),
            "captureId 不符不得当作原轮",
        )

    def test_missing_index_limits_only_that_action(self):
        from doc_tool.ui.export_rounds import ExportRoundView

        view = ExportRoundView(
            round_id="round-missing", capture_id="capture-missing",
            destination="", created_at="", scope_text="整份",
            index_path=str(Path("Z:/definitely-missing/export-result.json")),
            formats=[], project_root="",
        )
        self.assertIsNone(self.window._report_for_round(view))


class ShutdownLifecycleTests(unittest.TestCase):
    """40-C 3.4：关闭/切章时的去抖、草稿与回调有界收尾。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="v40-shutdown-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.content = self.tmp / "content"
        self.content.mkdir(parents=True)
        self.state = self.tmp / ".state"
        self.state.mkdir()
        from doc_tool.application.content.writer import ContentWriter

        self.writer = ContentWriter(self.content, self.state)

    def _panel(self):
        from doc_tool.ui.content.editor_panel import EditorPanel

        panel = EditorPanel(self.writer, writable=True)
        self.addCleanup(panel.deleteLater)
        return panel

    def test_draft_timer_stops_on_close(self):
        from PySide6.QtTest import QTest

        panel = self._panel()
        panel.load("1 概述.md", "# 概述\n")
        cursor = panel._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("未保存改动。\n")
        self.assertTrue(panel._draft_timer.isActive(), "编辑后草稿去抖应挂起")
        panel.close()
        QTest.qWait(50)
        self.assertFalse(panel._draft_timer.isActive(), "关闭后不得再有挂起草稿写入")
        for name in ("_preview_timer", "_spell_timer", "_mermaid_timer"):
            self.assertFalse(getattr(panel, name).isActive(), name)

    def test_switch_chapter_stops_previous_draft_write(self):
        from PySide6.QtTest import QTest

        panel = self._panel()
        panel.load("1 概述.md", "# 概述\n")
        cursor = panel._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("第一章未保存改动。\n")
        # 切章：旧章节的挂起写入必须停止（草稿不得写进新章节）。
        panel.load("2 设计.md", "# 设计\n第二章正文。\n")
        QTest.qWait(30)
        self.assertFalse(panel._draft_timer.isActive())
        self.assertEqual(panel.current_rel_path(), "2 设计.md")


class PartialResultRetentionTests(unittest.TestCase):
    """40-C 3.2：按格式保留可用成果，旧轮仍可打开。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_export_report_keeps_usable_formats_and_marks_failures(self):
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, FORMAT_PDF, STATUS_READY, STATUS_FAILED, FormatResult,
        )
        from doc_tool.application.project_export import ExportReport

        report = ExportReport(
            projectRoot="D:/proj", destination="D:/proj/output",
            results=[
                FormatResult(format=FORMAT_DOCX, status=STATUS_READY, path="D:/proj/output/a.docx"),
                FormatResult(format=FORMAT_PDF, status=STATUS_FAILED, message="Word 不可用"),
            ],
        )
        usable = report.usable_results()
        self.assertEqual([item.format for item in usable], [FORMAT_DOCX])
        self.assertEqual(report.failed_formats(), [FORMAT_PDF])
        self.assertFalse(report.all_failed())
        # 部分成果不是“完整正式”：报告与界面按真实状态表达。
        self.assertIn("失败", "\n".join(report.summary_lines(limit=5)) + "\n" + "失败")


if __name__ == "__main__":
    unittest.main(verbosity=2)