# -*- coding: utf-8 -*-
"""全局日志、环境快照、诊断包与帮助菜单入口的回归测试。

覆盖用户报障闭环的四段：
1. ``%APPDATA%\\DocTool\\logs`` 下的轮转文件日志（5 MiB × 3 份可配置）；
2. 启动环境快照（系统/Python/Qt/Office/Git，逐项失败不影响整体）；
3. 未捕获异常写入完整堆栈并触发一次通知；
4. 「帮助 → 打开应用日志目录 / 导出诊断日志包」两个入口。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class AppLoggingTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("diagnostics-logging")
        from doc_tool.application import app_logging

        self.logging = app_logging
        app_logging.uninstall_exception_hooks()
        app_logging.uninstall_app_logging()
        app_logging.disable_faulthandler()

    def tearDown(self):
        self.logging.uninstall_exception_hooks()
        self.logging.uninstall_app_logging()
        self.logging.disable_faulthandler()
        fixtures.cleanup(self.work)

    def test_setup_creates_rotating_file_and_records(self):
        state = self.logging.setup_app_logging(directory=self.work, console=False)
        self.assertTrue(state.enabled, "显式可写目录必须启用日志")
        self.assertEqual(state.log_file, self.work / "doc-tool.log")

        from logging.handlers import RotatingFileHandler

        self.assertIsInstance(state.handler, RotatingFileHandler)
        self.assertEqual(state.handler.maxBytes, self.logging.DEFAULT_MAX_BYTES)
        self.assertEqual(state.handler.backupCount, self.logging.DEFAULT_BACKUP_COUNT)

        logging.getLogger("doc_tool.test").info("日志落盘探针")
        self.logging.flush_logging()

        text = state.log_file.read_text(encoding="utf-8")
        self.assertIn("日志落盘探针", text)
        self.assertIn("doc_tool.test", text)

    def test_rotation_keeps_configured_backups(self):
        state = self.logging.setup_app_logging(
            directory=self.work, console=False, max_bytes=2048, backup_count=2
        )
        logger = logging.getLogger("doc_tool.test.rotate")
        for index in range(120):
            logger.info("row %03d %s", index, "x" * 60)
        self.logging.flush_logging()

        names = [path.name for path in self.logging.log_files(self.work)]
        self.assertIn("doc-tool.log", names)
        self.assertIn("doc-tool.log.1", names)
        self.assertLessEqual(len(names), 3, "最多保留当前日志 + 2 份备份：{0}".format(names))
        self.assertNotIn("doc-tool.log.3", names)
        self.assertLessEqual(state.log_file.stat().st_size, 8192)

    def test_unwritable_primary_directory_falls_back(self):
        bad = self.work / "blocked" / "logs"
        with patch.dict(
            os.environ, {self.logging.LOG_DIR_ENV: str(self.work)}, clear=False
        ), patch.object(
            self.logging,
            "_probe_writable",
            side_effect=lambda directory: Path(directory) == self.work,
        ):
            state = self.logging.setup_app_logging(directory=bad, console=False)
        self.assertTrue(state.enabled, "首选目录不可写时应回退而不是禁用日志")
        self.assertEqual(state.log_file.parent, self.work)
        self.assertTrue(state.used_fallback_directory)

    def test_exception_hook_records_traceback_and_notifies(self):
        state = self.logging.setup_app_logging(directory=self.work, console=False)
        seen = []
        self.logging.install_exception_hooks(
            notify=lambda exc, path: seen.append((type(exc).__name__, path))
        )
        try:
            raise ValueError("probe-boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        self.logging.flush_logging()

        text = state.log_file.read_text(encoding="utf-8")
        self.assertIn("ValueError", text)
        self.assertIn("probe-boom", text)
        self.assertIn("Traceback", text, "必须记录完整调用栈")
        self.assertEqual([item[0] for item in seen], ["ValueError"])
        self.assertEqual(seen[0][1], state.log_file)

    def test_faulthandler_creates_crash_log(self):
        path = self.logging.enable_faulthandler(self.work)
        self.assertEqual(path, self.work / "doc-tool-crash.log")
        self.assertTrue(path.is_file(), "原生崩溃日志应创建在应用日志目录")

    def test_threading_hook_records_thread_name(self):
        state = self.logging.setup_app_logging(directory=self.work, console=False)
        self.logging.install_exception_hooks()
        try:
            raise RuntimeError("thread-boom")
        except RuntimeError:
            args = SimpleNamespace(
                exc_type=RuntimeError,
                exc_value=sys.exc_info()[1],
                exc_traceback=sys.exc_info()[2],
                thread=threading.current_thread(),
            )
            threading.excepthook(args)
        self.logging.flush_logging()

        text = state.log_file.read_text(encoding="utf-8")
        self.assertIn("thread-boom", text)
        self.assertIn("后台线程", text)


class EnvironmentSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("diagnostics-env")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_snapshot_has_all_sections_and_stable_fields(self):
        from doc_tool.application.environment_snapshot import (
            collect_environment_snapshot,
            format_environment_snapshot,
        )

        snapshot = collect_environment_snapshot(include_office=False)
        for section in ("应用", "系统", "Python", "Qt/PySide6", "Git"):
            self.assertIn(section, snapshot, snapshot.keys())
        self.assertIn("版本", snapshot["应用"])
        self.assertIn("64 位", snapshot["系统"])
        self.assertIn("WebEngine 进程", snapshot["Qt/PySide6"])

        text = format_environment_snapshot(snapshot, timestamp=datetime(2026, 11, 10, 9, 0, 0))
        self.assertIn("Doc Tool 环境快照", text)
        self.assertIn("生成时间：2026-11-10 09:00:00", text)
        self.assertIn("[Git]", text)

    def test_office_probe_failure_is_contained(self):
        from doc_tool.application.environment_snapshot import collect_environment_snapshot

        with patch(
            "doc_tool.application.word_check.check_word_available",
            side_effect=RuntimeError("office-boom"),
        ):
            snapshot = collect_environment_snapshot(include_git=False)
        office = snapshot["Office"]
        self.assertTrue(
            any("失败" in value for value in office.values()), office
        )

    def test_git_missing_is_reported_not_raised(self):
        from doc_tool.application.environment_snapshot import collect_environment_snapshot

        with patch(
            "doc_tool.application.environment_snapshot._run_command",
            return_value=(-1, "未找到命令（未安装或不在 PATH）"),
        ):
            snapshot = collect_environment_snapshot(include_office=False)
        self.assertIn("不可用", snapshot["Git"]["Git"])


class DiagnosticBundleTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("diagnostics-bundle")
        self.logs = self.work / "logs"
        self.logs.mkdir(parents=True)
        (self.logs / "doc-tool.log").write_text("current line\n", encoding="utf-8")
        (self.logs / "doc-tool.log.1").write_text("old line\n", encoding="utf-8")
        self.snapshot = {"应用": {"版本": "1.2.3"}, "系统": {"Windows": "test"}}

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _export(self, now):
        from doc_tool.application.diagnostics_export import export_diagnostic_bundle

        return export_diagnostic_bundle(
            destination_dir=self.work / "out",
            log_directory=self.logs,
            snapshot=self.snapshot,
            now=now,
        )

    def test_bundle_contains_logs_environment_and_build_info(self):
        bundle = self._export(datetime(2026, 11, 10, 17, 30, 0))
        self.assertTrue(bundle.is_file())
        self.assertTrue(bundle.name.startswith("DocTool-diagnostics-20261110-173000"))
        self.assertEqual(bundle.parent, self.work / "out")

        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            self.assertTrue({"README.txt", "environment.txt", "build-info.json"} <= names)
            self.assertIn("logs/doc-tool.log", names)
            self.assertIn("logs/doc-tool.log.1", names)
            environment = archive.read("environment.txt").decode("utf-8")
            self.assertIn("Doc Tool 环境快照", environment)
            self.assertIn("版本：1.2.3", environment)
            info = json.loads(archive.read("build-info.json").decode("utf-8"))
            self.assertIn("appVersion", info)

    def test_second_export_does_not_overwrite(self):
        moment = datetime(2026, 11, 10, 17, 30, 0)
        first = self._export(moment)
        second = self._export(moment)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file() and second.is_file())
        self.assertTrue(second.name.endswith("-2.zip"), second.name)


class AppBootstrapTests(unittest.TestCase):
    """GUI 入口 ``_bootstrap_logging`` 的真实接线（启动即可落盘）。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("diagnostics-bootstrap")
        from doc_tool.application import app_logging

        self.logging = app_logging
        app_logging.uninstall_exception_hooks()
        app_logging.uninstall_app_logging()
        app_logging.disable_faulthandler()

    def tearDown(self):
        self.logging.uninstall_exception_hooks()
        self.logging.uninstall_app_logging()
        self.logging.disable_faulthandler()
        fixtures.cleanup(self.work)

    def test_bootstrap_writes_banner_into_configured_log_directory(self):
        import doc_tool.app as app_module

        with patch.dict(
            os.environ, {self.logging.LOG_DIR_ENV: str(self.work)}, clear=False
        ):
            app_module._bootstrap_logging()
        state = self.logging.current_state()
        self.assertIsNotNone(state)
        self.assertTrue(state.enabled, "启动日志未启用")
        self.assertEqual(state.log_file.parent, self.work)
        text = state.log_file.read_text(encoding="utf-8")
        self.assertIn("Doc Tool 启动", text)
        self.assertIn("日志文件：", text)


class DiagnosticsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.main_window import MainWindow

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            self.window = MainWindow()
        self.addCleanup(self.window.close)

    def _help_menu(self):
        # PySide6 所有权坑：QAction 包装器一旦被回收，action.menu() 返回的
        # QMenu 包装器可能跟着失效；把 action 一并留住再断言。
        for action in self.window.menuBar().actions():
            if action.text() == "帮助":
                self._help_action = action
                return action.menu()
        return None

    def test_help_menu_exposes_log_and_bundle_entries(self):
        menu = self._help_menu()
        self.assertIsNotNone(menu)
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertIn("打开应用日志目录", texts)
        self.assertIn("导出诊断日志包（ZIP）…", texts)
        self.assertIn("关于 / 环境诊断", texts, "原有入口不得丢失")

    def test_open_app_logs_uses_log_directory(self):
        with patch(
            "doc_tool.application.app_logging.ensure_log_directory",
            return_value=Path("/tmp/doctool-logs"),
        ), patch.object(
            self.window, "_open_directory_or_warn", return_value=True
        ) as opener:
            self.window._on_open_app_logs()
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(opener.call_args.args[1], "应用日志目录")

    def test_export_diagnostics_reports_bundle_path(self):
        bundle = Path("/tmp/DocTool-diagnostics-20261110-173000.zip")
        with patch(
            "doc_tool.application.diagnostics_export.export_diagnostic_bundle",
            return_value=bundle,
        ) as exporter, patch.object(
            self.window, "_show_status_message"
        ) as status:
            self.window._on_export_diagnostics()
        self.assertEqual(exporter.call_count, 1)
        self.assertIn(str(bundle), status.call_args.args[0])

    def test_qt_message_handler_routes_warnings_into_logger(self):
        from doc_tool.ui import diagnostics_hooks

        context = SimpleNamespace(file="preview.py", line=42)
        with self.assertLogs("qt", level="WARNING") as captured:
            diagnostics_hooks._qt_message_handler(
                diagnostics_hooks.QtMsgType.QtWarningMsg, context, "webengine warning"
            )
        self.assertIn("webengine warning", "\n".join(captured.output))
        self.assertIn("preview.py:42", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
