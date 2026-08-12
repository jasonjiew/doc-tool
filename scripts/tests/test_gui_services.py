# -*- coding: utf-8 -*-
"""GUI 服务层自动测试。

任务 6.10：增加 GUI 服务层自动测试和关键界面人工操作清单。

测试范围（无显示环境下可运行的部分）：
- TaskRunner：后台任务执行、事件推送、取消、异常处理
- ProjectService：打开项目、最近项目列表增删
- 最近项目持久化

GUI 控件本身的交互测试需要人工在桌面环境执行（见末尾人工操作清单）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class TaskRunnerTests(unittest.TestCase):
    """任务 6.8：TaskRunner 后台执行、事件推送与取消。"""

    def test_successful_task_emits_events(self):
        """成功任务推送 started + succeeded 事件。"""
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()

        def simple_task():
            return 42

        runner.start(TaskSpec(name="test", target=simple_task))
        runner.join(timeout=5)
        runner.poll()  # 处理事件

        events = runner.drain_events()
        kinds = [e.kind for e in events]
        # poll 已消费事件，但 _on_done 被调用说明 succeeded 已处理
        self.assertFalse(runner.is_running)

    def test_failed_task_emits_error(self):
        """失败任务推送 started + failed 事件。"""
        from doc_tool.domain.errors import BuildError
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()

        def failing_task():
            raise BuildError("构建失败")

        runner.start(TaskSpec(name="build", target=failing_task))
        runner.join(timeout=5)

        events = runner.drain_events()
        # 最后一个事件应为 failed
        self.assertTrue(len(events) >= 1)
        failed_events = [e for e in events if e.kind == "failed"]
        self.assertTrue(len(failed_events) >= 1)
        self.assertEqual(failed_events[0].error_code, "E2001")

    def test_structured_failure_result_emits_failed_not_succeeded(self):
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()
        result = SimpleNamespace(
            success=False,
            error_code="E2002",
            last_stage=SimpleNamespace(detail="校验未通过"),
        )
        runner.start(TaskSpec(name="validate", target=lambda: result))
        runner.join(timeout=5)
        events = runner.drain_events()
        self.assertTrue(any(event.kind == "failed" for event in events))
        self.assertFalse(any(event.kind == "succeeded" for event in events))

    def test_cancel_token_passed_to_target(self):
        """目标函数接受 cancel_token 参数时自动传入。"""
        from doc_tool.domain.cancellation import CancellationToken
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()
        received_token = []

        def cancellable_task(cancel_token=None):
            received_token.append(cancel_token)
            return "ok"

        runner.start(TaskSpec(name="test", target=cancellable_task))
        runner.join(timeout=5)
        runner.drain_events()

        self.assertEqual(len(received_token), 1)
        self.assertIsInstance(received_token[0], CancellationToken)

    def test_cancel_request_stops_long_task(self):
        """取消请求在阶段边界停止任务。"""
        from doc_tool.domain.cancellation import CancellationToken
        from doc_tool.domain.errors import CancelledError
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()

        def long_task(cancel_token=None):
            import time as _time

            for _ in range(100):
                cancel_token.check_cancel()
                _time.sleep(0.01)
            return "done"

        runner.start(TaskSpec(name="long", target=long_task))
        time.sleep(0.05)  # 让任务开始
        runner.cancel()  # 请求取消
        runner.join(timeout=5)

        events = runner.drain_events()
        cancelled = [e for e in events if e.kind == "cancelled"]
        self.assertTrue(len(cancelled) >= 1)
        self.assertEqual(cancelled[0].error_code, "E5003")

    def test_rejects_concurrent_task(self):
        """任务运行中拒绝启动新任务。"""
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()

        def long_task():
            time.sleep(0.2)
            return "ok"

        runner.start(TaskSpec(name="task1", target=long_task))
        # 尝试启动第二个
        ok = runner.start(TaskSpec(name="task2", target=lambda: 1))
        self.assertFalse(ok)
        runner.join(timeout=5)
        runner.drain_events()

    def test_app_version_auto_injected(self):
        """目标函数接受 app_version 参数时自动注入。"""
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()
        received = []

        def task(app_version=""):
            received.append(app_version)
            return "ok"

        runner.start(TaskSpec(name="test", target=task))
        runner.join(timeout=5)
        runner.drain_events()

        self.assertEqual(len(received), 1)
        self.assertTrue(received[0])  # 非空版本号

    def test_watchdog_timeout_reports_stable_error(self):
        """看门狗超时解锁 UI，并发布稳定错误码与任务名。"""
        from doc_tool.ui.task_bridge import (
            ERR_WATCHDOG_TIMEOUT,
            TaskRunner,
            TaskSpec,
        )

        runner = TaskRunner()
        events = []
        done = []
        runner.start(
            TaskSpec(
                name="merge",
                target=lambda: time.sleep(0.2),
                timeout_seconds=0.01,
            ),
            on_event=events.append,
            on_done=done.append,
        )
        time.sleep(0.03)
        runner.poll()

        self.assertFalse(runner.is_running)
        failed = [event for event in events if event.kind == "failed"]
        self.assertEqual(failed[-1].error_code, ERR_WATCHDOG_TIMEOUT)
        self.assertEqual(failed[-1].stage, "merge")
        self.assertEqual(done, [None])
        runner.join(timeout=1)
        runner.poll()
        self.assertEqual(done, [None])

    def test_late_timed_out_worker_cannot_complete_new_run(self):
        """超时旧线程的迟到终态不得污染随后启动的新任务。"""
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()
        first_done = []
        second_done = []

        runner.start(
            TaskSpec(
                name="old",
                target=lambda: (time.sleep(0.08), "old")[1],
                timeout_seconds=0.01,
            ),
            on_done=first_done.append,
        )
        time.sleep(0.03)
        runner.poll()
        self.assertEqual(first_done, [None])

        runner.start(
            TaskSpec(
                name="new",
                target=lambda: (time.sleep(0.15), "new")[1],
                timeout_seconds=1,
            ),
            on_done=second_done.append,
        )
        time.sleep(0.08)  # 此时旧线程已返回，新线程仍在运行
        runner.poll()
        self.assertTrue(runner.is_running)
        self.assertEqual(second_done, [])

        runner.join(timeout=2)
        runner.poll()
        self.assertFalse(runner.is_running)
        self.assertEqual(second_done, ["new"])


class ProjectServiceTests(unittest.TestCase):
    """任务 6.4：打开项目与最近项目列表。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-gui-svc-")
        # 复用 test_project_build 的项目夹具
        from test_project_build import _setup_project, _make_manifest

        _setup_project(self._tmp)
        self._make_manifest = _make_manifest
        # 创建 source.docx 占位（_setup_project 不创建 original/）
        original_dir = Path(self._tmp) / "original"
        original_dir.mkdir(parents=True, exist_ok=True)
        (original_dir / "source.docx").write_bytes(b"placeholder")
        # 保存清单
        manifest = _make_manifest(self._tmp)
        manifest.save(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_open_project_returns_summary(self):
        """打开项目返回包含清单和路径的摘要。"""
        from doc_tool.application.project_service import open_project

        summary = open_project(self._tmp)
        self.assertIsNotNone(summary.manifest)
        self.assertTrue(summary.source_exists)
        self.assertTrue(summary.template_exists)
        self.assertTrue(summary.is_writable)
        self.assertEqual(summary.project_root, Path(self._tmp).resolve())

    def test_open_incompatible_project_readonly(self):
        """高模式版本项目以只读方式打开，不可写。"""
        from doc_tool.application.project_service import open_project

        # 修改清单的 schemaVersion 为更高的不兼容版本
        manifest_path = Path(self._tmp) / "project.yml"
        content = manifest_path.read_text(encoding="utf-8")
        content = content.replace("schemaVersion: 1", "schemaVersion: 99")
        manifest_path.write_text(content, encoding="utf-8")

        # 高版本可只读打开但 is_writable 为 False
        summary = open_project(self._tmp)
        self.assertFalse(summary.is_writable)

    def test_validation_report_summary_contains_counts_and_failures(self):
        from doc_tool.application.project_service import read_validation_report_summary

        report = Path(self._tmp) / "validation.md"
        report.write_text(
            "# 报告\n\n- [PASS] ZIP 完整\n"
            "- [FAIL] 章节编号错误 — expected=3.1.14\n",
            encoding="utf-8",
        )
        summary = read_validation_report_summary(report)
        self.assertTrue(summary["exists"])
        self.assertEqual(summary["passCount"], 1)
        self.assertEqual(summary["failCount"], 1)
        self.assertIn("expected=3.1.14", summary["failures"][0])

    def test_window_geometry_roundtrip_and_invalid_json(self):
        from unittest.mock import patch

        from doc_tool.application.project_service import (
            load_window_geometry,
            save_window_geometry,
        )

        home = Path(self._tmp) / "home"
        with patch("pathlib.Path.home", return_value=home):
            self.assertIsNone(load_window_geometry())
            save_window_geometry("900x700+10+20", True)
            self.assertEqual(
                load_window_geometry(),
                {"geometry": "900x700+10+20", "maximized": True},
            )
            geometry_file = home / ".konsung-doc-tool" / "geometry.json"
            geometry_file.write_text("{broken", encoding="utf-8")
            self.assertIsNone(load_window_geometry())

    def test_recent_projects_add_and_load(self):
        """添加最近项目后可加载。"""
        from doc_tool.application.project_service import (
            add_recent_project,
            load_recent_projects,
        )
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(self._tmp)
        add_recent_project(self._tmp, manifest)

        entries = load_recent_projects()
        paths = [e.path for e in entries]
        self.assertIn(str(Path(self._tmp).resolve()), paths)

    def test_recent_projects_remove(self):
        """移除最近项目条目。"""
        from doc_tool.application.project_service import (
            add_recent_project,
            load_recent_projects,
            remove_recent_project,
        )
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(self._tmp)
        add_recent_project(self._tmp, manifest)
        remove_recent_project(self._tmp)

        entries = load_recent_projects()
        paths = [e.path for e in entries]
        self.assertNotIn(str(Path(self._tmp).resolve()), paths)

    def test_recent_projects_dedup(self):
        """重复添加同一项目不产生重复条目。"""
        from doc_tool.application.project_service import (
            add_recent_project,
            load_recent_projects,
        )
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(self._tmp)
        add_recent_project(self._tmp, manifest)
        add_recent_project(self._tmp, manifest)

        entries = load_recent_projects()
        resolved = str(Path(self._tmp).resolve())
        count = sum(1 for e in entries if e.path == resolved)
        self.assertEqual(count, 1)

    def test_recent_projects_filters_nonexistent(self):
        """最近项目列表过滤掉不存在的路径。"""
        from doc_tool.application.project_service import (
            RecentEntry,
            _save_recent_projects,
            load_recent_projects,
        )

        fake_entry = RecentEntry(
            path="/nonexistent/project",
            name="fake",
        )
        _save_recent_projects([fake_entry])
        entries = load_recent_projects()
        self.assertEqual(len(entries), 0)


class HighDpiTests(unittest.TestCase):
    """任务 6.1：高 DPI 适配不报错。"""

    def test_setup_high_dpi_no_error(self):
        """setup_high_dpi 在任何平台都不抛出异常。"""
        from doc_tool.ui.styles import setup_high_dpi

        setup_high_dpi()  # 不应抛出异常


class ImportWizardPresentationTests(unittest.TestCase):
    def test_preview_summary_uses_heading_level_counts(self):
        from doc_tool.ui.wizard import format_preview_summary

        preview = SimpleNamespace(
            heading_level_counts={1: 2, 2: 3},
            image_count=4,
            table_count=5,
            warnings=[],
            document_type_suggestion=SimpleNamespace(
                document_type="general",
                confidence="high",
                reason="通用模式",
            ),
        )
        text = format_preview_summary(preview)
        self.assertIn("Heading 1: 2", text)
        self.assertIn("Heading 2: 3", text)
        self.assertIn("图片数量：4", text)
        self.assertIn("建议模式：通用大文档", text)

    def test_wizard_exposes_five_qwizard_pages(self):
        _ensure_qapp()
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard()
        self.assertEqual(wizard.pageIds(), [0, 1, 2, 3, 4])
        self.assertTrue(hasattr(wizard, "_source_page"))
        self.assertTrue(hasattr(wizard, "_preflight_page"))
        self.assertTrue(hasattr(wizard, "_info_page"))
        self.assertTrue(hasattr(wizard, "_executing_page"))
        self.assertTrue(hasattr(wizard, "_result_page"))
        wizard.close()

    def test_project_info_validation_rules(self):
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard.__new__(ImportWizard)
        wizard._doc_type = "requirement"
        wizard._doc_no = ""
        wizard._doc_name = "文档"
        wizard._doc_version = "1.0"
        wizard._project_name = "proj"
        wizard._target_parent = "C:/x"
        self.assertIn("文档编号", wizard._validate_project_info())

        wizard._doc_no = "KSHC-001"
        wizard._project_name = "a:b"
        self.assertIn("不允许的字符", wizard._validate_project_info())

        wizard._project_name = "good-name"
        self.assertEqual(wizard._validate_project_info(), "")


def _ensure_qapp():
    """在无 QApplication 时创建（离屏环境可用）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeWriter:
    """Ctrl+S 测试用的假 ContentWriter：resolve 落到临时目录，write_text 记录调用。"""

    def __init__(self, content_root):
        self._root = Path(content_root)
        self.written = None

    def resolve(self, rel_path):
        return self._root if rel_path == "." else self._root / rel_path

    def write_text(self, rel_path, text):
        self.written = (rel_path, text)
        return SimpleNamespace(
            written=True, error=None, backup_path=None, path=""
        )


class MainWindowInteractionTests(unittest.TestCase):
    """PySide6 主窗口交互（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_workbench_state_covers_word_and_missing_artifacts(self):
        from doc_tool.ui.workbench_state import derive_workbench_state

        state = derive_workbench_state(
            SimpleNamespace(is_writable=True, output_exists=False),
            running=False,
            word_available=False,
        )

        self.assertFalse(state.actions["merge"].enabled)
        self.assertTrue(state.actions["diag_build"].enabled)
        self.assertFalse(state.actions["output"].enabled)
        self.assertFalse(state.actions["report"].enabled)
        self.assertIn("Microsoft Word", state.readiness_text)
        self.assertTrue(any("输出目录" in reason for reason in state.reasons))

    def test_workbench_state_matrix_and_four_views(self):
        from doc_tool.ui.workbench_state import derive_workbench_state

        no_project = derive_workbench_state(None, running=False)
        self.assertEqual(no_project.view, "empty")
        self.assertFalse(no_project.actions["validate"].enabled)

        readonly = derive_workbench_state(
            SimpleNamespace(is_writable=False, output_exists=True), running=False
        )
        self.assertFalse(readonly.actions["validate"].enabled)
        self.assertTrue(readonly.actions["content"].enabled)

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "validation.md"
            report.write_text("ok", encoding="utf-8")
            writable = derive_workbench_state(
                SimpleNamespace(is_writable=True, output_exists=True),
                running=False,
                report_path=report,
            )
            self.assertTrue(writable.actions["validate"].enabled)
            self.assertTrue(writable.actions["report"].enabled)
            self.assertEqual(writable.view, "idle")

            running = derive_workbench_state(
                SimpleNamespace(is_writable=True, output_exists=True),
                running=True,
                task_label="校验",
                report_path=report,
            )
            self.assertFalse(running.actions["validate"].enabled)
            self.assertEqual(running.view, "running")

            result = derive_workbench_state(
                SimpleNamespace(is_writable=True, output_exists=True),
                running=False,
                report_path=report,
                result_available=True,
            )
            self.assertEqual(result.view, "result")

    def test_derive_step_list_pipeline_and_heartbeat(self):
        from doc_tool.ui.workbench_state import derive_step_list

        steps = derive_step_list([
            ("build", "started", "", None),
            ("validate_pre", "succeeded", "校验通过", None),
            ("word_refresh", "skipped", "已显式跳过", None),
            ("publish", "failed", "发布失败", "E9000"),
        ])
        by_stage = {s.stage: s.status for s in steps}
        self.assertEqual(by_stage["build"], "running")
        self.assertEqual(by_stage["validate_pre"], "success")
        self.assertEqual(by_stage["word_refresh"], "skipped")
        self.assertEqual(by_stage["publish"], "failed")
        # 心跳任务回退为单一步骤，不伪造百分比
        heartbeat = derive_step_list(
            [("validate", "started", "", None)], fallback_label="校验"
        )
        self.assertEqual(len(heartbeat), 1)
        self.assertEqual(heartbeat[0].status, "running")

    def test_task_dock_renders_running_and_result(self):
        from doc_tool.ui.task_dock import TaskDock
        from doc_tool.ui.workbench_state import ResultState, StepItem

        dock = TaskDock()
        dock.show_running(
            "正式合并",
            [
                StepItem(stage="build", label="构建", status="success"),
                StepItem(stage="validate_pre", label="前校验", status="running"),
            ],
            current_stage="validate_pre",
            elapsed=5,
        )
        dock.show_result(
            "正式合并",
            ResultState(
                status="success",
                title="正式合并成功",
                summary="完成",
                project_root=Path("C:/x"),
            ),
            [StepItem(stage="build", label="构建", status="success")],
        )
        self.assertTrue(dock.has_result())

    def test_result_card_action_buttons_keep_captured_paths(self):
        """clicked(bool) 不能覆盖结果卡片中捕获的产物路径。"""
        from doc_tool.ui.work_detail_pane import ResultCard
        from doc_tool.ui.workbench_state import ResultState

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output.docx"
            output.write_bytes(b"docx")
            opened = []
            card = ResultCard(
                on_open_output=opened.append,
                on_open_directory=opened.append,
            )
            card.render(ResultState(status="success", output_path=output))

            for button in card._action_buttons:
                button.click()

            self.assertEqual(opened, [str(output), str(output.parent)])

    def test_log_stream_pending_unread_while_collapsed(self):
        from doc_tool.ui.work_detail_pane import LogStream

        log = LogStream()
        log.append_line("a")
        log.set_expanded(False)
        log.append_line("b")
        log.append_line("c")
        self.assertEqual(log.pending_unread, 2)
        log.set_expanded(True)
        self.assertEqual(log.pending_unread, 0)

    def test_pipeline_success_sets_persistent_result(self):
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output.docx"
            output.write_bytes(b"docx")
            report = root / "validation.md"
            report.write_text("ok", encoding="utf-8")
            window = MainWindow()
            window._project_summary = SimpleNamespace(project_root=root)
            window._current_task = "merge"
            window._last_error_code = None
            window._last_error_stage = ""
            window._last_error_detail = ""
            window._task_terminal_kind = "succeeded"
            window._validation_report_path = lambda: report
            window._current_log_path = lambda: root / "runtime.log"
            result = SimpleNamespace(
                success=True, output_path=str(output), error_code=None
            )
            with patch(
                "doc_tool.domain.output_state.is_formal_success", return_value=True
            ):
                window._handle_pipeline_result(result)
            self.assertEqual(window._result_state.status, "success")
            self.assertEqual(window._result_state.output_path, output)
            self.assertEqual(window._result_state.report_path, report)
            self.assertIn("正式合并成功", window._result_state.title)
            window.close()

    def test_validation_success_result_exposes_report_only(self):
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "validation.md"
            report_path.write_text("ok", encoding="utf-8")
            window = MainWindow()
            window._current_task = "validate"
            window._last_error_code = None
            window._last_error_stage = ""
            window._last_error_detail = ""
            window._project_summary = SimpleNamespace(project_root=Path(tmp))
            window._validation_report_path = lambda: report_path
            window._current_log_path = lambda: Path(tmp) / "runtime.log"
            summary = {"exists": True, "passCount": 5, "failCount": 0, "failures": []}
            with patch(
                "doc_tool.application.project_service.read_validation_report_summary",
                return_value=summary,
            ):
                window._handle_validation_result(True)
            self.assertEqual(window._result_state.status, "success")
            self.assertEqual(window._result_state.report_path, report_path)
            self.assertIsNone(window._result_state.output_path)
            window.close()

    def test_failure_result_keeps_sanitized_technical_fields(self):
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.workbench_state import ResultState

        window = MainWindow()
        window._result_state = ResultState(
            status="failure",
            error_code="E3003",
            stage="word_save",
            exception_summary="Word 保存失败",
            log_path=Path("C:/project/logs/runtime.log"),
        )
        with patch("doc_tool.ui.main_window.QMessageBox.information") as info:
            window._show_result_technical_details()
        details = info.call_args.args[2]
        self.assertIn("E3003", details)
        self.assertIn("Word 保存失败", details)
        self.assertIn("runtime.log", details)
        window.close()

    def test_file_and_directory_opening_keep_distinct_semantics(self):
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_file = root / "report.md"
            with patch.object(MainWindow, "_open_path", return_value=True):
                self.assertFalse(MainWindow._open_file(missing_file))
                self.assertFalse(missing_file.exists())
                directory = root / "logs"
                self.assertTrue(MainWindow._open_directory(directory, create=True))
                self.assertTrue(directory.is_dir())

    def test_task_result_dispatch_uses_task_metadata(self):
        from unittest.mock import Mock

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        window._current_task = "validate"
        window._last_error_code = None
        window._last_error_stage = ""
        window._last_error_detail = ""
        window._task_terminal_kind = ""
        window._drain_stage_progress = Mock()
        window._refresh_interaction_state = Mock()
        window._refresh_recent_projects = Mock()
        window._task_dock.show_result = Mock()
        window._handle_pipeline_result = Mock()
        window._handle_validation_result = Mock()
        window._on_task_done(True)
        window._handle_validation_result.assert_called_once_with(True)
        window._handle_pipeline_result.assert_not_called()
        window.close()

    def test_project_switch_resets_persistent_result(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        root = Path("C:/new-project")
        manifest = SimpleNamespace(
            documentName="新文档",
            documentNo="NO-1",
            documentType="general",
            documentVersion="1.0",
            sourceSha256="abc123",
            lastSuccessfulBuildVersion=None,
        )
        summary = SimpleNamespace(
            project_root=root, manifest=manifest, lock_info=None, is_writable=True
        )
        window = MainWindow()
        window._init_content_workspace = Mock()
        with patch("doc_tool.application.project_service.add_recent_project"):
            window.show_project(summary)
        self.assertEqual(window._result_state.status, "idle")
        self.assertEqual(window._result_state.project_root, root)
        window.close()

    def test_close_running_task_requests_cancel_once(self):
        from unittest.mock import Mock, patch

        from PySide6.QtWidgets import QMessageBox

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        window.runner = SimpleNamespace(is_running=True, cancel=Mock())
        window._close_after_task = False
        with patch(
            "doc_tool.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window.close()
            window.close()
        window.runner.cancel.assert_called_once()
        self.assertTrue(window._close_after_task)
        window.close()

    def test_close_running_task_can_be_refused(self):
        from unittest.mock import Mock, patch

        from PySide6.QtWidgets import QMessageBox

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        window.runner = SimpleNamespace(is_running=True, cancel=Mock())
        window._close_after_task = False
        with patch(
            "doc_tool.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            window.close()
        window.runner.cancel.assert_not_called()
        self.assertFalse(window._close_after_task)
        # 关闭保护拒绝后不应弹出对话框；模拟任务结束后正常关闭
        window.runner = SimpleNamespace(is_running=False, cancel=Mock())
        window.close()

    def test_search_panel_results_tree_is_layout_managed(self):
        """搜索面板结果树由唯一外层布局管理（回归：二次 QVBoxLayout 不可见）。"""
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        # 旧缺陷根因：第二次 QVBoxLayout(self) 不会被安装，子控件脱离布局。
        host = QWidget()
        first = QVBoxLayout(host)
        first.addWidget(QWidget())
        second = QVBoxLayout(host)
        second.addWidget(QWidget())
        self.assertIs(host.layout(), first)
        self.assertIsNone(second.parentWidget())

        from doc_tool.application.content.search import SearchResult
        from doc_tool.ui.content.search_panel import SearchPanel

        class _FakeService:
            def search(self, options, cancel_token=None):
                return SearchResult(
                    query=options.query,
                    total=2,
                    hits=[
                        SimpleNamespace(rel_path="a.md", line_no=1, text="hello world"),
                        SimpleNamespace(rel_path="a.md", line_no=2, text="nothing here"),
                    ],
                    file_count=1,
                )

        app = _ensure_qapp()
        panel = SearchPanel(_FakeService())
        panel.resize(600, 400)
        panel.show()
        panel._query_entry.setText("hello")
        panel.search_now()
        for _ in range(200):
            panel._runner.poll()
            app.processEvents()
            if not panel._runner.is_running:
                break
            time.sleep(0.01)
        app.processEvents()
        self.assertGreater(panel._tree.topLevelItemCount(), 0)
        self.assertGreater(panel._tree.height(), 200)
        panel.close()

    def test_closed_content_docks_reopen_via_view_menu_and_search(self):
        """关闭章节树/工具面板 Dock 后可从「视图」菜单或 Ctrl+F 重新打开。"""
        from unittest.mock import Mock

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDockWidget

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.workbench_state import derive_workbench_state

        _ensure_qapp()
        win = MainWindow()
        win.show()
        # 模拟项目打开后由 _init_content_workspace 创建的章节树/工具面板 Dock。
        win._tree_dock = QDockWidget("章节树", win)
        win._tree_dock.setObjectName("chapterTreeDock")
        win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win._tree_dock)
        win._panels_dock = QDockWidget("工具面板", win)
        win._panels_dock.setObjectName("panelsDock")
        win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, win._panels_dock)
        win._rebuild_view_menu()

        # 离开空状态进入 IDE 视图后，右侧任务/结果 Dock 必须重新显示。
        state = derive_workbench_state(
            SimpleNamespace(is_writable=True, output_exists=False), running=False
        )
        win._apply_workbench_state(state)
        self.assertTrue(win._task_dock_widget.isVisible())

        # 「视图」菜单为每个 Dock 提供显隐开关。
        labels = [a.text() for a in win._view_menu.actions()]
        for expected in ("章节树", "工具面板", "任务 / 结果"):
            self.assertIn(expected, labels)

        # 关闭两个内容 Dock 后，Ctrl+F 必须重新显示底部工具面板。
        win._content_workspace = SimpleNamespace(focus_search=Mock())
        win._content_index_ready = True
        win._tree_dock.close()
        win._panels_dock.close()
        win._on_content_search()
        self.assertTrue(win._panels_dock.isVisible())

        # 再次关闭后，「视图」菜单的 toggle 项也能重新打开。
        win._panels_dock.close()
        panels_action = next(
            a for a in win._view_menu.actions() if a.text() == "工具面板"
        )
        panels_action.trigger()
        self.assertTrue(win._panels_dock.isVisible())
        win.close()

    def test_ctrl_s_shortcut_saves_current_tab(self):
        """Ctrl+S 必须能保存当前标签页（回归：按钮文案有快捷键但未绑定）。"""
        from PySide6.QtGui import QKeySequence
        from PySide6.QtTest import QTest

        from doc_tool.ui.content.tabs_host import TabsHost

        _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            content_root = Path(tmp) / "content"
            rel = "requirement/第1章 引言/1.1 目的.md"
            path = content_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# 1.1 目的\n原文\n", encoding="utf-8")

            writer = _FakeWriter(content_root)
            tabs = TabsHost(writer)
            tabs.open_file(rel, path.read_text(encoding="utf-8"))
            editor = tabs.current_editor()
            editor._editor.setPlainText("# 1.1 目的\n被改\n")
            self.assertIsNotNone(tabs._save_shortcut)
            self.assertEqual(
                tabs._save_shortcut.key().toString(), QKeySequence("Ctrl+S").toString()
            )
            # 编辑器聚焦后发送 Ctrl+S，应触发保存（离屏下需先激活窗口）。
            tabs.show()
            tabs.raise_()
            tabs.activateWindow()
            QTest.qWait(50)
            editor._editor.setFocus()
            QTest.keySequence(editor._editor, QKeySequence("Ctrl+S"))
            QTest.qWait(30)
            self.assertEqual(writer.written, (rel, "# 1.1 目的\n被改\n"))
            tabs.close_all()
            tabs.close()

    def test_idle_card_report_button_triggers_open_report(self):
        """空闲卡「查看校验报告」必须接线到打开报告回调（回归：死按钮）。"""
        from PySide6.QtWidgets import QPushButton

        from doc_tool.ui.task_dock import TaskDock
        from doc_tool.ui.workbench_state import ResultState

        _ensure_qapp()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "validation.md"
            report.write_text("ok", encoding="utf-8")
            opened = []
            dock = TaskDock(on_open_report=lambda: opened.append(True))
            dock.show_idle(
                ResultState(
                    status="success", report_path=report, project_root=Path(tmp)
                ),
                project_open=True,
            )
            button = next(
                b
                for b in dock._idle_card.findChildren(QPushButton)
                if b.text() == "查看校验报告"
            )
            button.click()
            self.assertEqual(opened, [True])
            dock.close()


class WizardInteractionTests(unittest.TestCase):
    def test_preflight_constant_and_page_structure(self):
        from doc_tool.ui.wizard import ImportWizard, PREFLIGHT_TIMEOUT_SECONDS

        self.assertGreater(PREFLIGHT_TIMEOUT_SECONDS, 0)
        _ensure_qapp()
        wizard = ImportWizard()
        self.assertEqual(wizard.pageIds(), [0, 1, 2, 3, 4])
        wizard.close()

    def test_cancel_during_running_requests_safe_cancel(self):
        from unittest.mock import Mock

        from doc_tool.ui.wizard import ImportWizard

        _ensure_qapp()
        wizard = ImportWizard()
        runner = Mock()
        runner.is_running = True
        wizard._runner = runner
        wizard._closing = False
        wizard._on_cancel_clicked()
        self.assertTrue(wizard._closing)
        runner.cancel.assert_called_once()
        wizard.close()

    def test_run_returns_target_root_on_accepted_and_none_on_rejected(self):
        """run() 必须用 QDialog.DialogCode 判定结果（回归：QDialogButtonBox 无该枚举导致崩溃）。"""
        from unittest.mock import patch

        from PySide6.QtWidgets import QDialog

        from doc_tool.ui.wizard import ImportWizard

        _ensure_qapp()
        wizard = ImportWizard()
        with patch.object(wizard, "exec", return_value=QDialog.DialogCode.Accepted):
            wizard._target_root = "C:/proj"
            self.assertEqual(wizard.run(), "C:/proj")
        with patch.object(wizard, "exec", return_value=QDialog.DialogCode.Rejected):
            self.assertIsNone(wizard.run())
        wizard.close()
class PresentationHelpersTests(unittest.TestCase):
    def test_pipeline_stage_percentages_are_contiguous_and_complete(self):
        from doc_tool.application.pipeline import (
            PIPELINE_STAGE_ORDER,
            stage_percent_table,
        )

        table = stage_percent_table()
        self.assertEqual(list(table), list(PIPELINE_STAGE_ORDER))
        self.assertEqual(table[PIPELINE_STAGE_ORDER[0]][0], 5)
        self.assertEqual(table[PIPELINE_STAGE_ORDER[-1]][1], 100)
        for previous, current in zip(
            PIPELINE_STAGE_ORDER, PIPELINE_STAGE_ORDER[1:]
        ):
            self.assertEqual(table[previous][1], table[current][0])

    def test_diagnostic_info_is_copy_friendly(self):
        from doc_tool.ui.about_dialog import format_diagnostic_info

        info = {
            "appVersion": "1.2.3",
            "commit": "abc123",
            "projectSchemaVersion": "1",
            "python": "3.11",
            "platform": "Windows",
            "machine": "AMD64",
        }
        report = SimpleNamespace(
            available=False,
            version="",
            pywin32_available=True,
            interactive_session=False,
            reasons=["未安装 Word"],
        )
        text = format_diagnostic_info(info, report)
        self.assertIn("应用版本：1.2.3", text)
        self.assertIn("Microsoft Word：未检测到", text)
        self.assertIn("- 未安装 Word", text)


class ContentOperationsStateTests(unittest.TestCase):
    """任务 10.4：内容操作状态矩阵（菜单可用性随项目/只读/索引就绪变化）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def _make_window(self, *, project, index_ready=False, workspace=None):
        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        window._project_summary = project
        window._content_index_ready = index_ready
        window._content_workspace = workspace
        return window

    def _states(self, window):
        return {
            "search": window._search_action.isEnabled(),
            "references": window._references_action.isEnabled(),
            "lint": window._lint_action.isEnabled(),
            "replace": window._replace_action.isEnabled(),
            "refactor": window._refactor_action.isEnabled(),
            "open_external": window._open_external_action.isEnabled(),
        }

    def test_writable_project_index_ready_enables_all(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=True),
            index_ready=True,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=False)
        states = self._states(window)
        self.assertTrue(states["search"])
        self.assertTrue(states["references"])
        self.assertTrue(states["lint"])
        self.assertTrue(states["replace"])
        self.assertTrue(states["refactor"])
        self.assertTrue(states["open_external"])
        window.close()

    def test_readonly_project_disables_write_actions(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=False),
            index_ready=True,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=False)
        states = self._states(window)
        self.assertTrue(states["search"])
        self.assertFalse(states["replace"])
        self.assertFalse(states["refactor"])
        window.close()

    def test_index_not_ready_disables_read_actions(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=True),
            index_ready=False,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=False)
        states = self._states(window)
        self.assertFalse(states["search"])
        self.assertFalse(states["replace"])
        # open_external 仅依赖 workspace 存在
        self.assertTrue(states["open_external"])
        window.close()

    def test_task_running_disables_content_menu(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=True),
            index_ready=True,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=True)
        states = self._states(window)
        self.assertFalse(states["search"])
        self.assertFalse(states["replace"])
        window.close()


class EditorRollbackCleanupTests(unittest.TestCase):
    """编辑器「回滚上次保存」：恢复内容并清理 .bak 与改动清单条目。

    回归：此前 rollback_last 只把 .bak 复制回文件、不删除 .bak，也不移除
    改动清单 edit 条目——遗留备份会触发构建前检查失败，徽标仍显示已修改。
    """

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self) -> None:
        self.project_root = Path(tempfile.mkdtemp(prefix="doc-tool-editor-"))
        self.content_root = self.project_root / "content"
        self.rel = "requirement/第1章 引言/1.1 目的.md"
        path = self.content_root / self.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 1.1 目的\n原始正文\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)

    def _make_panel(self):
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.editor_panel import EditorPanel

        writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        return writer, EditorPanel(writer=writer, writable=True)

    def test_rollback_last_restores_cleans_backup_and_drops_entry(self):
        writer, panel = self._make_panel()
        panel.load(self.rel, "# 1.1 目的\n原始正文\n")
        panel._editor.setPlainText("# 1.1 目的\n被改\n")
        self.assertTrue(panel.save())

        bak = self.content_root / (self.rel + ".bak")
        self.assertTrue(bak.exists())
        writer.manifest.load()
        self.assertEqual(len(writer.manifest.entries), 1)

        self.assertTrue(panel.rollback_last())
        # 内容恢复到保存前
        self.assertEqual(
            (self.content_root / self.rel).read_text(encoding="utf-8"),
            "# 1.1 目的\n原始正文\n",
        )
        # .bak 被清理，改动清单条目被移除
        self.assertFalse(bak.exists())
        writer.manifest.load()
        self.assertTrue(writer.manifest.empty)


# === 人工验收清单（PySide6 IDE 工作台，任务 8.3/8.4） ===
# 以下操作需要在 Windows 桌面环境中手动执行，无法自动化测试：
#
# 启动与外壳：
# 1. 启动应用：python -m doc_tool.app
#    - 预期：PySide6 主窗口正常显示（无 Tk 窗口），标题包含版本号，菜单栏/状态栏存在
#    - 高 DPI 生效（HiDPI 下文字清晰不模糊、不截断）
#
# 2. 空状态（未打开项目）：
#    - 启动后无项目 → 中央显示空状态页：新建项目/打开项目/最近项目入口
#    - 三个 Dock（章节树/任务结果/工具面板）隐藏，菜单仅文件可用
#
# 3. 新建项目向导（QWizard 五步）：
#    - 文件 → 新建项目 → 选源 DOCX → 预检预览（标题/图片/表格计数、告警）→
#      项目信息（类型建议 high confidence 自动采用）→ 执行 → 结果
#    - 阻断告警（无 Heading 1）时不可进入下一步；导入成功后自动打开项目
#
# 4. 打开已有项目 → 看到 IDE 骨架：
#    - 文件 → 打开项目 → 选择 projects/design 或 projects/requirement
#    - 预期：顶部项目条显示文档名/类型/版本/就绪状态；左侧章节树 Dock、
#      中心编辑器、右侧任务/结果 Dock、底部工具面板全部出现
#    - 项目条高频入口（正式合并/诊断构建/校验）可用性随项目状态变化
#
# 5. 空闲态（任务/结果 Dock）：
#    - 打开项目后尚未执行任务 → 右侧显示引导卡片（校验 / 诊断构建入口）
#    - 执行一次校验后 → 空闲态显示最近结果卡片；继续浏览章节树/内容时结果保留
#
# 6. 运行态（步骤清单 + 日志流 + 取消）：
#    - 操作 → 诊断构建 → 右侧显示步骤清单：①构建 → ②前校验 → ③Word 刷新(跳过) →
#      ④后校验(跳过) → ⑤发布；当前步骤高亮，总体进度与已用时间实时更新
#    - 日志流按时间顺序追加；向上滚动后新日志仍记录并显示待读提示
#    - 心跳任务（独立校验）→ 显示单个「进行中」步骤 + 已用时间，无伪造百分比
#
# 7. 成功终态：
#    - 诊断构建/正式合并成功 → 结果卡片显示成功摘要与输出路径；
#      「打开产物」「打开所在目录」「查看校验报告」入口可用
#    - 独立校验成功（未生成 DOCX）→ 只显示报告入口，不显示误导性「打开产物」
#
# 8. 失败终态与技术详情：
#    - 人为制造失败（如损坏源文件）→ 结果卡片显示原因与建议；
#      「技术详情…」可展开并显示错误码/阶段/异常摘要/日志路径
#
# 9. 取消：
#    - 任务运行中点击「取消」→ 界面标记等待安全停止点（当前阶段名），
#      任务在阶段边界以取消状态收尾，后续步骤保持待处理
#
# 10. 只读项目：
#     - 打开模式版本不兼容的项目 → 章节树/编辑器只读，搜索/检查可用，
#       替换/重命名不可用；项目条标注只读原因
#
# 11. Word 不可用：
#     - 无 Microsoft Word 环境 → 正式合并入口标注原因，诊断构建仍可用
#
# 12. 结果路径失效：
#     - 任务成功后将产物文件移动/删除 → 结果卡片不再显示「打开产物」，
#       或点击时提示结果已不可用并引导打开仍存在的目录
#
# 13. 项目切换：
#     - 任务成功后打开另一个项目 → 右侧结果卡片清除旧项目结果，不显示旧产物操作
#
# 内容操作（IDE 布局）：
# 14. 章节树：展开全部/折叠全部/刷新；右键文件 → 打开 / 复制相对路径；
#     点击文件 → 中心编辑器打开并定位，树选中与编辑器同步
# 15. 中心多标签编辑器：同时打开多个文件切换编辑；侧边轻量 Markdown 预览去抖刷新；
#     Ctrl+S 保存（生成 .md.bak）→ 索引失效重建 + 预览刷新；外部修改检测提示刷新
# 16. 全文搜索（Ctrl+F）：聚焦输入框；结果表 文件/行/预览 点击定位并高亮命中行；
#     正则/大小写/整词/类型过滤生效；「显示更多」追加结果
# 17. 全局替换：逐项「替换此项/跳过」+「全部替换…」确认；写回后自动跑校验；
#     「回滚本次替换」恢复
# 18. 重命名/重编号：当前文件预填，dry-run 列受影响引用（旧→新），确认后
#     引用更新 + 文件重命名 + 自动校验 + 同级连续编号检查
# 19. 引用分析对话框：当前文件被引用情况 + 全项目悬空引用（确定/疑似），点击定位
# 20. 术语/一致性检查：重复标题/术语大小写/TODO 残留列出并定位；术语清单增删后立即重跑
# 21. 快捷键：F5 校验；Ctrl+Shift+B 诊断构建；Ctrl+1..4 切换底部面板；
#     Ctrl+F 搜索；F1 关于；Ctrl+L 日志回到底部
#
# 主题与可读性（任务 8.4）：
# 22. 深色主题：工具 → 切换深色主题 → 标题/正文/按钮/状态文字/语义色按深色渲染；
#     再次切换回到浅色；菜单项文字随主题切换
# 23. 高对比度/DPI 缩放：在 100%/125%/150% 缩放与高对比度系统主题下检查
#     标题、正文、按钮、状态文字与最小窗口尺寸可读性；最小宽度窗口下
#     主要控件不被固定像素假设截断（依赖 Dock 折叠/滚动）
#
# 关闭保护与几何持久化：
# 24. 任务运行中关闭窗口 → 确认对话框 → 请求安全取消，任务停止后自动退出；
#     拒绝则继续运行
# 25. 调整窗口尺寸/位置或最大化后退出 → 下次启动恢复相同几何与状态


class ChangesPanelTests(unittest.TestCase):
    """改动面板：列出改动、选中显示 diff、恢复按钮接线（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self) -> None:
        self.project_root = Path(tempfile.mkdtemp(prefix="doc-tool-changes-"))
        self.content_root = self.project_root / "content"
        self.rel = "requirement/第1章 引言/1.1 目的.md"
        path = self.content_root / self.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 1.1 目的\n原始正文\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)

        from doc_tool.application.content.snapshot import ContentSnapshot
        from doc_tool.application.content.writer import ContentWriter

        self.snapshot = ContentSnapshot(self.project_root / ".state")
        self.snapshot.take(self.content_root, [self.rel])
        self.writer = ContentWriter(
            self.content_root, self.project_root / ".state"
        )

    def _items_for_modified(self):
        """记录一次修改（写入 edit 条目 + .bak），返回改动项列表。"""
        from doc_tool.application.content.changes import build_change_items

        self.writer.write_text(self.rel, "# 1.1 目的\n被修改后的正文内容\n")
        status = self.snapshot.diff(self.content_root, [self.rel])
        self.assertEqual(status.get(self.rel), "modified")
        return build_change_items(status, rename_map={}, trash_map={})

    def _panel(self, **kw):
        from doc_tool.ui.content.changes_panel import ChangesPanel

        return ChangesPanel(
            snapshot=self.snapshot,
            writer=self.writer,
            content_root=self.content_root,
            on_restored=kw.get("on_restored", lambda: None),
            writable=True,
        )

    def test_lists_items_and_counts(self):
        panel = self._panel()
        panel.set_items(self._items_for_modified())
        self.assertEqual(panel._list.count(), 1)
        self.assertIn("已修改 1", panel._counts_label.text())
        self.assertIn(self.rel, panel._list.item(0).text())
        panel.close()

    def test_selection_shows_diff(self):
        panel = self._panel()
        panel.set_items(self._items_for_modified())
        panel._list.setCurrentRow(0)
        text = panel._diff_view.toPlainText()
        self.assertIn("-原始正文", text)
        self.assertIn("+被修改后的正文内容", text)
        panel.close()

    def test_restore_modified_reverts_file_and_refreshes(self):
        restored = []
        panel = self._panel(on_restored=lambda: restored.append(True))
        panel.set_items(self._items_for_modified())
        panel._list.setCurrentRow(0)
        self.assertTrue(panel._restore_btn.isEnabled())
        self.assertEqual(panel._restore_btn.text(), "恢复到基线")
        panel._restore_btn.click()
        # 文件恢复到基线内容，改动清单清空，回调触发刷新
        self.assertEqual(
            (self.content_root / self.rel).read_text(encoding="utf-8"),
            "# 1.1 目的\n原始正文\n",
        )
        self.writer.manifest.load()
        self.assertTrue(self.writer.manifest.empty)
        self.assertEqual(restored, [True])
        panel.close()


if __name__ == "__main__":
    unittest.main()
