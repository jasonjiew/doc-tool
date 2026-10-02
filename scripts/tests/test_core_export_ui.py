# -*- coding: utf-8 -*-
"""CORE-F 6.1/6.5 界面接线测试：快速导出入口真实调用服务，结果页给直接动作。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402


class _FakeSummary:
    is_writable = True

    def __init__(self, root: Path):
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.project_root = str(root)
        self.manifest = ProjectManifest.load(root)
        self.paths = ProjectPaths(root)


class QuickExportUiTests(unittest.TestCase):
    """无需 Word：默认走诊断/已保存分支，验证入口与结果动作接线。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui-export")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        self.work = fixtures.scratch_dir("ui-export-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        with patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        ):
            self.window = MainWindow()
        self.window._project_summary = _FakeSummary(self.project)
        self._patches = [
            patch("doc_tool.ui.main_window.QMessageBox.information", lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.warning", lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.critical", lambda *a, **k: None),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def test_action_exists_and_states_real_format(self):
        self.assertTrue(hasattr(self.window, "_quick_export_action"))
        self.assertIn("Word", self.window._quick_export_action.text())
        self.assertEqual(self.window._quick_export_action.shortcut().toString(), "Ctrl+E")

    def test_quick_export_calls_service_and_presents_results(self):
        from doc_tool.application.intake_contract import FORMAT_DOCX, SOURCE_MODE_SAVED

        seen = {}
        opened = {}

        class _FakeReport:
            projectRoot = str(self.project)
            destination = str(self.project / "output")
            scope = None
            sourceMode = SOURCE_MODE_SAVED
            failed_formats = lambda self: []
            results = []

            def summary_lines(self, limit=3):
                return ["Word已生成", "输出位置：{0}".format(self.destination)]

            def usable_results(self):
                return []

        def _fake_export(request, **kwargs):
            seen["request"] = request
            return _FakeReport()

        self.window._present_export_report = lambda report, **kwargs: opened.update({"report": report})
        with patch(
            "doc_tool.application.project_export.run_project_export", _fake_export
        ):
            self.window._on_quick_export_word()
            # 导出在既有 TaskRunner 后台线程执行：泵事件等待结束
            import time

            from PySide6.QtWidgets import QApplication

            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
            QApplication.processEvents()
        self.assertIn("request", seen)
        request = seen["request"]
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.project_root, str(self.project))
        self.assertEqual(request.destination, str(self.project / "output"))
        self.assertIn("report", opened)

    def test_present_report_offers_open_and_retry_buttons(self):
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, FORMAT_PDF, STATUS_PENDING_REFRESH, STATUS_PENDING_CONVERT,
            FormatResult,
        )

        labels = {}

        class _Box:
            ButtonRole = QMessageBox.ButtonRole
            clickedButton = staticmethod(lambda: None)

            def __init__(self, parent=None):
                pass

            def setWindowTitle(self, value):
                labels["title"] = value

            def setText(self, value):
                labels["text"] = value

            def addButton(self, text, role=None):
                labels.setdefault("buttons", []).append(text)
                return text

            def exec(self):
                return 0

        report = type("R", (), {})()
        report.projectRoot = str(self.project)
        report.destination = str(self.project / "output")
        report.scope = None
        report.sourceMode = "saved"
        report.results = [
            FormatResult(format=FORMAT_DOCX, status=STATUS_PENDING_REFRESH, path=str(self.project / "output" / "a.docx")),
            FormatResult(format=FORMAT_PDF, status=STATUS_PENDING_CONVERT, message="待转换"),
        ]
        report.summary_lines = lambda limit=3: ["Word待刷新", "PDF待转换"]
        report.usable_results = lambda: [report.results[0]]
        report.failed_formats = lambda: [FORMAT_PDF]
        # 必须补丁 main_window 的模块级 QMessageBox 引用，否则会弹真模态框
        with patch("doc_tool.ui.main_window.QMessageBox", _Box):
            self.window._present_export_report(report)
        buttons = labels.get("buttons", [])
        self.assertIn("打开文件", buttons)
        self.assertIn("打开目录", buttons)
        self.assertIn("补失败格式（原轮）", buttons)
        self.assertIn("更换目录…", buttons)
        self.assertIn("按最新内容重新生成", buttons)


class ExportChangeDirectoryBufferTests(unittest.TestCase):
    """审计补测：结果页「更换目录…」在“当前编辑内容”来源下必须带上编辑器缓冲。

    此前该分支未传 buffer_texts，会在报告仍标注“当前编辑内容”的同时导出磁盘内容
    （静默丢失未保存编辑）。本用例锁定修复后的行为。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("export-changedir")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _report(self, source_mode: str):
        from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest
        from doc_tool.application.project_export import run_project_export

        return run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_DOCX],
                source_mode=source_mode, destination=str(self.work / "out"),
            ),
            skip_word_refresh=True,
        )

    def test_change_directory_keeps_editor_buffer_for_buffer_source(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.intake_contract import SOURCE_MODE_CURRENT_BUFFER
        from doc_tool.ui.main_window import MainWindow

        report = self._report(SOURCE_MODE_CURRENT_BUFFER)
        captured: dict = {}
        buffers = {"content/general/第1章 引言/1.1 目的.md": "编辑器里的未保存内容"}

        state = {"clicks": 0}

        class _Box:
            ButtonRole = QMessageBox.ButtonRole

            def __init__(self, parent=None):
                self._buttons = {}

            def setWindowTitle(self, value):
                pass

            def setText(self, value):
                pass

            def addButton(self, text, role=None):
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                # 只在第一次点击“更换目录…”，随后关闭，避免结果页递归重开
                state["clicks"] += 1
                if state["clicks"] == 1:
                    return self._buttons.get("更换目录…")
                return self._buttons.get("关闭")

        def _fake_export(request, **kwargs):
            captured["kwargs"] = kwargs
            captured["destination"] = request.destination
            return report

        recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        recent.start()
        try:
            window = MainWindow()
            window._project_summary = type("S", (), {"project_root": self.project, "is_writable": True})()
            window._collect_buffer_texts = lambda: dict(buffers)
            with patch("doc_tool.ui.main_window.QMessageBox", _Box), patch(
                "doc_tool.ui.main_window.QFileDialog.getExistingDirectory",
                return_value=str(self.work / "另一目录"),
            ), patch("doc_tool.application.project_export.run_project_export", _fake_export):
                window._present_export_report(report, allow_retry=False)
            window.close()
        finally:
            recent.stop()

        self.assertTrue(captured, "更换目录分支应调用统一出稿")
        self.assertEqual(captured["kwargs"].get("buffer_texts"), buffers,
                         "当前编辑内容来源必须继续携带编辑器缓冲，不能用磁盘内容顶替")
        self.assertIn("另一目录", str(captured.get("destination")))

    def test_change_directory_omits_buffer_for_saved_source(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.intake_contract import SOURCE_MODE_SAVED
        from doc_tool.ui.main_window import MainWindow

        report = self._report(SOURCE_MODE_SAVED)
        captured: dict = {}

        state = {"clicks": 0}

        class _Box:
            ButtonRole = QMessageBox.ButtonRole

            def __init__(self, parent=None):
                self._buttons = {}

            def setWindowTitle(self, value):
                pass

            def setText(self, value):
                pass

            def addButton(self, text, role=None):
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                # 只在第一次点击“更换目录…”，随后关闭，避免结果页递归重开
                state["clicks"] += 1
                if state["clicks"] == 1:
                    return self._buttons.get("更换目录…")
                return self._buttons.get("关闭")

        def _fake_export(request, **kwargs):
            captured["kwargs"] = kwargs
            return report

        recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        recent.start()
        try:
            window = MainWindow()
            window._project_summary = type("S", (), {"project_root": self.project, "is_writable": True})()
            with patch("doc_tool.ui.main_window.QMessageBox", _Box), patch(
                "doc_tool.ui.main_window.QFileDialog.getExistingDirectory",
                return_value=str(self.work / "第三目录"),
            ), patch("doc_tool.application.project_export.run_project_export", _fake_export):
                window._present_export_report(report, allow_retry=False)
            window.close()
        finally:
            recent.stop()

        self.assertTrue(captured)
        self.assertIsNone(captured["kwargs"].get("buffer_texts"), "已保存来源不应注入编辑器缓冲")


if __name__ == "__main__":
    unittest.main(verbosity=2)