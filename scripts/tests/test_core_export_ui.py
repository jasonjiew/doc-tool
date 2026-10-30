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
from PySide6.QtWidgets import QDialog
from doc_tool.ui.export_settings_dialog import ExportSettingsDialog
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
            patch.object(
                ExportSettingsDialog,
                "exec",
                lambda self: (self._on_submit(), QDialog.DialogCode.Accepted)[1],
            ),
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


    def test_quick_export_key_event_and_dialog_isolation(self):
        """Task 9.2: 真实 Ctrl+E 快捷键、单窗打开、取消与确认隔离断言。"""
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt, QTimer
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog
        from doc_tool.application.intake_contract import FORMAT_DOCX, SOURCE_MODE_CURRENT_BUFFER

        self._patches[3].stop()
        try:
            self.window.show()
            self.window._refresh_interaction_state()
            QApplication.processEvents()
            self.assertTrue(self.window._quick_export_action.isEnabled(), "Ctrl+E 必须处于可用状态")

            submissions = []
            self.window._submit_export_request = lambda req: submissions.append(req)
            self.window._collect_buffer_texts = lambda: {"01-x.md": "活缓冲测试正文"}

            # 1. 真实 Ctrl+E 触发，验证恰好打开一个弹窗，取消时零提交
            def _on_cancel():
                dlgs = [w for w in QApplication.topLevelWidgets() if isinstance(w, ExportSettingsDialog) and w.isVisible()]
                if dlgs:
                    dlgs[0].reject()
                else:
                    QTimer.singleShot(20, _on_cancel)

            QTimer.singleShot(30, _on_cancel)
            self.window.activateWindow()
            QTest.keyClick(self.window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
            QApplication.processEvents()

            self.assertEqual(len(submissions), 0, "取消设置不应提交任何任务")
            self.assertIn("已取消导出设置", self.window._status_label.text())

            # 2. 再次按 Ctrl+E，确认后恰好提交一次
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

            self.assertEqual(len(submissions), 1, "确认后应且仅提交一次导出任务")
            req = submissions[0]
            self.assertEqual(req.formats, [FORMAT_DOCX])
            self.assertEqual(req.source_mode, SOURCE_MODE_CURRENT_BUFFER)
        finally:
            self._patches[3].start()

    def test_f5_validation_checks_living_buffer_without_flushing_or_version_bump(self):
        """Task 10.1: F5 检查保持检查职责，基于活缓冲检查，不刷盘不改写版本。"""
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt

        yml_path = self.project / "project.yml"
        orig_yml_bytes = yml_path.read_bytes() if yml_path.exists() else b""

        # 找到一个章节
        chapters = list((self.project / "content").rglob("*.md"))
        self.assertTrue(chapters, "必须存在章节文件")
        test_ch = chapters[0]
        orig_ch_bytes = test_ch.read_bytes()

        # 模拟工作区与 lint
        lint_called = []
        tabs_selected = []
        class _FakeWorkspace:
            def run_lint(self):
                lint_called.append(True)
                return True

        self.window._content_workspace = _FakeWorkspace()
        self.window._select_content_tab = lambda tab: tabs_selected.append(tab)

        # 触发 F5 主动检查
        self.window.show()
        self.window._refresh_interaction_state()
        self.window.setFocus()
        self.window.activateWindow()
        QApplication.processEvents()
        self.assertTrue(self.window._validate_action.isEnabled(), "F5 动作必须处于可用状态")
        QTest.keyClick(self.window, Qt.Key.Key_F5)
        QApplication.processEvents()

        self.assertTrue(lint_called, "F5 必须调用 run_lint 执行活缓冲检查")
        self.assertEqual(tabs_selected, [4], "主动 F5 检查必须展开面板并定位到格式检查页 (tab 4)")
        if yml_path.exists():
            self.assertEqual(yml_path.read_bytes(), orig_yml_bytes, "F5 不得写回或修改 project.yml")
        self.assertEqual(test_ch.read_bytes(), orig_ch_bytes, "F5 不得将脏正文持久化到磁盘")
        self.assertIn("当前正文检查结果已更新", self.window.statusBar().currentMessage())

        # 自动校验回调（如替换/重命名后触发）保留面板偏好
        tabs_selected.clear()
        self.window._on_content_request_validate()
        self.assertEqual(tabs_selected, [], "自动校验回调不得强行切换或展开面板")

class ChangeDirectoryActionTests(unittest.TestCase):
    """更换目录动作（UI 包 3.2）：当前内容来源必须继续带上编辑器缓冲。

    审计补测：此前该分支未传 buffer_texts，会在报告仍标注“当前编辑内容”的同时
    导出磁盘内容（静默丢失未保存编辑）。本用例锁定修复后的行为，并改为直接驱动
    「换目录并重新导出」动作（不再依赖模态结果框的按钮点击）。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("export-changedir-direct")
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

    def _drive_change_directory(self, source_mode: str, *, destination: str):
        from unittest.mock import patch
        from doc_tool.ui.main_window import MainWindow

        report = self._report(source_mode)
        captured: dict = {}
        buffers = {"content/general/第1章 引言/1.1 目的.md": "编辑器里的未保存内容"}

        def _fake_export(request, **kwargs):
            captured["kwargs"] = kwargs
            captured["destination"] = request.destination
            captured["source_mode"] = request.source_mode
            return report

        recent = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        recent.start()
        try:
            window = MainWindow()
            self.addCleanup(window.close)
            window._project_summary = _FakeSummary(self.project)
            window._collect_buffer_texts = lambda: dict(buffers)
            # 后台任务完成后会弹「出稿结果」框；非交互用例必须显式处理模态等待，
            # 否则 exec() 会一直阻塞（V4.0 40-A 1.3）。这里记录被调用事实，
            # 不影响真实按钮/服务行为。
            modal_calls: list = []
            window._exec_message_box = lambda box, _calls=modal_calls: _calls.append(box) or None
            view = window._record_export_round(report)
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from doc_tool.ui.export_settings_dialog import ExportSettingsDialog

            def _submit_exec(dlg):
                dlg._on_submit()
                if dlg._request is None:
                    dlg._request = dlg.request()
                return QDialog.DialogCode.Accepted

            with patch(
                "doc_tool.ui.main_window.QFileDialog.getExistingDirectory",
                return_value=destination,
            ), patch(
                "doc_tool.application.project_export.run_project_export", _fake_export
            ), patch.object(
                ExportSettingsDialog, "exec", _submit_exec
            ):
                window._on_change_export_destination(view)
                import time

                from PySide6.QtWidgets import QApplication

                deadline = time.monotonic() + 30
                while window.runner.is_running and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.02)
        finally:
            recent.stop()
        return captured, buffers

    def test_change_directory_keeps_editor_buffer_for_buffer_source(self):
        from doc_tool.application.intake_contract import SOURCE_MODE_CURRENT_BUFFER

        captured, buffers = self._drive_change_directory(
            SOURCE_MODE_CURRENT_BUFFER, destination=str(self.work / "另一目录")
        )
        self.assertTrue(captured, "更换目录分支应调用统一出稿")
        self.assertEqual(
            captured["kwargs"].get("buffer_texts"), buffers,
            "当前编辑内容来源必须继续携带编辑器缓冲，不能用磁盘内容顶替",
        )
        self.assertIn("另一目录", str(captured.get("destination")))

    def test_change_directory_omits_buffer_for_saved_source(self):
        from doc_tool.application.intake_contract import SOURCE_MODE_SAVED

        captured, _buffers = self._drive_change_directory(
            SOURCE_MODE_SAVED, destination=str(self.work / "第三目录")
        )
        self.assertTrue(captured)
        self.assertEqual(
            captured["kwargs"].get("buffer_texts"), {},
            "已保存来源不应注入编辑器缓冲内容",
        )
        self.assertEqual(captured["source_mode"], SOURCE_MODE_SAVED)






class ConflictDetectionAndProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("conflict-detection-shared")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("conflict-case")
        self.doc_file = self.work / "ch1.md"
        self.doc_file.write_text("# Chapter 1\nInitial content\n", encoding="utf-8")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_editor_panel_conflict_detection_scenarios(self):
        """Task 12.1: 真实内容核对（仅窗口变、仅磁盘变、双方分叉、内容相同、同 mtime 不同内容、基准未知）。"""
        import os
        from unittest.mock import MagicMock
        from doc_tool.ui.content.editor_panel import EditorPanel

        writer = MagicMock()
        writer.resolve.side_effect = lambda rel: self.work / rel

        panel = EditorPanel(writer=writer)
        panel.load("ch1.md", "# Chapter 1\nInitial content\n")
        self.assertFalse(panel._dirty)

        # 1. 初始状态：无变更，内容相同
        status = panel.check_buffer_disk_status()
        self.assertFalse(status["is_fork"])
        self.assertTrue(status["same_content"])

        # 2. 仅窗口变
        panel._editor.setPlainText("# Chapter 1\nWindow change only\n")
        panel._dirty = True
        status = panel.check_buffer_disk_status()
        self.assertFalse(status["is_fork"])
        self.assertTrue(status["only_buffer"])

        # 3. 内容相同（磁盘写成与窗口一致）
        self.doc_file.write_text("# Chapter 1\nWindow change only\n", encoding="utf-8")
        status = panel.check_buffer_disk_status()
        self.assertFalse(status["is_fork"])
        self.assertTrue(status["same_content"])

        # 4. 仅磁盘变（窗口重置为干净状态）
        panel.load("ch1.md", "# Chapter 1\nWindow change only\n")
        self.doc_file.write_text("# Chapter 1\nExternal disk change only\n", encoding="utf-8")
        status = panel.check_buffer_disk_status()
        self.assertFalse(status["is_fork"])
        self.assertTrue(status["only_disk"])

        # 5. 双方分叉（窗口有未保存修改，磁盘也有不同修改）
        panel._editor.setPlainText("# Chapter 1\nConflicting window edit\n")
        panel._dirty = True
        status = panel.check_buffer_disk_status()
        self.assertTrue(status["is_fork"], "双方同时不同修改必须判定为分叉")

        # 6. 同 mtime 不同内容
        old_mtime = self.doc_file.stat().st_mtime
        self.doc_file.write_text("# Chapter 1\nDifferent text with old mtime\n", encoding="utf-8")
        os.utime(str(self.doc_file), (old_mtime, old_mtime))
        status = panel.check_buffer_disk_status()
        self.assertTrue(status["is_fork"], "同 mtime 不同内容必须通过哈希准确检出冲突")

        # 7. 基准未知（通过 load_draft 但磁盘被删）
        self.doc_file.unlink()
        panel.load_draft("ch1.md", "# Chapter 1\nDraft text\n")
        self.doc_file.write_text("# Chapter 1\nRecreated file\n", encoding="utf-8")
        status = panel.check_buffer_disk_status()
        self.assertTrue(status["is_fork"], "基准未知且内容不一致应作为冲突保护")

    def test_export_settings_dialog_with_conflicts_requires_explicit_choice(self):
        """Task 12.2: 冲突说明接入设置下拉和提示区，分叉时拒绝静默默认，明确选择后才可提交。"""
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog
        from doc_tool.application.intake_contract import (
            SOURCE_MODE_CURRENT_BUFFER, SOURCE_MODE_SAVED,
        )

        conflicts = [
            {"chapter_key": "ch1.md", "rel_path": "ch1.md", "is_fork": True}
        ]

        dialog = ExportSettingsDialog(
            project_root=str(self.work),
            destination=str(self.work / "output"),
            chapters=["ch1.md"],
            conflicts=conflicts,
        )

        # 1. 冲突存在时，默认未选择（空字符串）
        self.assertEqual(dialog.source_mode(), "")
        self.assertEqual(dialog._source_combo.currentIndex(), 0)
        self.assertIn("冲突", dialog._source_combo.currentText())
        self.assertIn("存在外部修改与窗口未保存冲突", dialog._source_hint.text())

        # 2. 未选择直接提交：被拦截并显示错误
        dialog.show()
        dialog._on_submit()
        self.assertFalse(dialog._error_label.isHidden())
        self.assertIn("明确选择采用窗口或磁盘", dialog._error_label.text())

        # 3. 明确选择采用窗口修改
        idx_buf = dialog._source_combo.findData(SOURCE_MODE_CURRENT_BUFFER)
        dialog._source_combo.setCurrentIndex(idx_buf)
        self.assertEqual(dialog.source_mode(), SOURCE_MODE_CURRENT_BUFFER)
        self.assertIn("外部磁盘修改未纳入本次导出", dialog._source_hint.text())

        # 4. 明确选择采用磁盘修改
        idx_saved = dialog._source_combo.findData(SOURCE_MODE_SAVED)
        dialog._source_combo.setCurrentIndex(idx_saved)
        self.assertEqual(dialog.source_mode(), SOURCE_MODE_SAVED)
        self.assertIn("窗口未保存修改未纳入本次导出", dialog._source_hint.text())

        dialog.close()
        dialog.deleteLater()
        self._app.processEvents()

if __name__ == "__main__":
    unittest.main(verbosity=2)
