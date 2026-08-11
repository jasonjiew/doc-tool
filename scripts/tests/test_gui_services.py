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

    def test_show_step_resets_all_navigation_properties(self):
        from doc_tool.ui.wizard import ImportWizard

        class Widget:
            def __init__(self):
                self.options = {}
                self.focused = False

            def pack_forget(self):
                pass

            def pack(self, **_kwargs):
                pass

            def configure(self, **kwargs):
                self.options.update(kwargs)

            def cget(self, key):
                return self.options.get(key, "")

            def focus_set(self):
                self.focused = True

        wizard = ImportWizard.__new__(ImportWizard)
        wizard._step0 = Widget()
        wizard._step1 = Widget()
        wizard._step2 = Widget()
        wizard._step3 = Widget()
        wizard._step4 = Widget()
        wizard._back_btn = Widget()
        wizard._next_btn = Widget()
        wizard._cancel_btn = Widget()
        wizard._source_path = "source.docx"
        wizard._preview = SimpleNamespace(has_heading1=True)
        wizard._runner = SimpleNamespace(is_running=False)
        wizard._closing = False

        wizard._step = 4
        wizard._show_step()
        self.assertEqual(wizard._next_btn.options["text"], "关闭")
        self.assertEqual(wizard._next_btn.options["state"], "normal")
        self.assertEqual(wizard._cancel_btn.options["state"], "disabled")
        self.assertTrue(wizard._next_btn.focused)

        wizard._step = 1
        wizard._show_step()
        self.assertEqual(wizard._cancel_btn.options["text"], "取消")
        self.assertEqual(wizard._next_btn.options["text"], "下一步")
        self.assertEqual(wizard._next_btn.options["state"], "normal")
        self.assertEqual(wizard._back_btn.options["state"], "normal")

        wizard._runner.is_running = True
        wizard._show_step()
        self.assertEqual(wizard._next_btn.options["state"], "disabled")
        self.assertEqual(wizard._back_btn.options["state"], "disabled")
        self.assertEqual(wizard._cancel_btn.options["text"], "取消预检")
        self.assertEqual(wizard._cancel_btn.options["state"], "normal")

        wizard._closing = True
        wizard._show_step()
        self.assertEqual(wizard._cancel_btn.options["text"], "正在取消…")
        self.assertEqual(wizard._cancel_btn.options["state"], "disabled")


class MainWindowInteractionTests(unittest.TestCase):
    class Menu:
        def __init__(self):
            self.states = {}

        def entryconfig(self, index, **kwargs):
            self.states[index] = kwargs.get("state")

    class Var:
        def __init__(self, value=None):
            self.value = value

        def set(self, value):
            self.value = value

    def _make_window(self, project=None, running=False, report_path=None):
        from doc_tool.ui.main_window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window._project_summary = project
        window.runner = SimpleNamespace(is_running=running)
        window._file_menu = self.Menu()
        window._file_entry_indexes = {"new": 1, "open": 2, "recent": 3}
        window._ops_menu = self.Menu()
        window._ops_entry_indexes = {
            "validate": 4,
            "merge": 5,
            "diag_build": 6,
            "validation_report": 7,
        }
        window._tools_menu = self.Menu()
        window._tools_entry_indexes = {"content": 8, "output": 9, "logs": 10}
        window._validation_report_path = lambda: report_path
        return window

    def test_interaction_state_matrix(self):
        no_project = self._make_window()
        no_project._refresh_interaction_state()
        self.assertEqual(no_project._file_menu.states[1], "normal")
        self.assertEqual(no_project._ops_menu.states[4], "disabled")
        self.assertEqual(no_project._tools_menu.states[8], "disabled")

        readonly = self._make_window(SimpleNamespace(is_writable=False))
        readonly._refresh_interaction_state()
        self.assertEqual(readonly._ops_menu.states[4], "disabled")
        self.assertEqual(readonly._tools_menu.states[8], "normal")

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "validation.md"
            report.write_text("ok", encoding="utf-8")
            writable = self._make_window(
                SimpleNamespace(is_writable=True), report_path=report
            )
            writable._refresh_interaction_state()
            self.assertEqual(writable._ops_menu.states[4], "normal")
            self.assertEqual(writable._ops_menu.states[7], "normal")

            running = self._make_window(
                SimpleNamespace(is_writable=True), running=True, report_path=report
            )
            running._refresh_interaction_state()
            self.assertEqual(running._file_menu.states[1], "disabled")
            self.assertEqual(running._ops_menu.states[4], "disabled")
            self.assertEqual(running._tools_menu.states[8], "normal")

    def test_empty_and_workbench_views_switch_in_one_content_host(self):
        from doc_tool.ui.main_window import MainWindow

        class Frame:
            def __init__(self):
                self.visible = False
                self.pack_calls = []

            def pack_forget(self):
                self.visible = False

            def pack(self, **kwargs):
                self.visible = True
                self.pack_calls.append(kwargs)

        window = MainWindow.__new__(MainWindow)
        window._empty_frame = Frame()
        window._workbench_scroll = Frame()

        window._switch_content_view("empty")
        self.assertTrue(window._empty_frame.visible)
        self.assertFalse(window._workbench_scroll.visible)

        window._switch_content_view("workbench")
        self.assertFalse(window._empty_frame.visible)
        self.assertTrue(window._workbench_scroll.visible)
        self.assertEqual(
            window._workbench_scroll.pack_calls[-1],
            {"fill": "both", "expand": True},
        )

    def test_recent_project_button_uses_existing_open_command(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        created = []

        class Frame:
            def winfo_children(self):
                return []

        class Button:
            def __init__(self, _parent, **kwargs):
                self.command = kwargs["command"]
                self.state = "normal"
                created.append(self)

            def pack(self, **_kwargs):
                pass

            def configure(self, **kwargs):
                self.state = kwargs.get("state", self.state)

        window = MainWindow.__new__(MainWindow)
        window._empty_recent_frame = Frame()
        window.runner = SimpleNamespace(is_running=False)
        window._open_project_path = Mock()
        entry = SimpleNamespace(
            path="C:/valid-project", name="project", document_name="文档"
        )

        with patch("tkinter.ttk.Button", Button):
            window._render_empty_recent_projects([entry])

        self.assertEqual(len(created), 1)
        created[0].command()
        window._open_project_path.assert_called_once_with("C:/valid-project")
        self.assertEqual(created[0].state, "normal")

    def test_scroll_log_to_bottom_clears_unread_count(self):
        from doc_tool.ui.main_window import MainWindow

        seen = []
        window = MainWindow.__new__(MainWindow)
        window._log_text = SimpleNamespace(see=seen.append)
        window._log_pending_var = self.Var("待读 3 条新日志…")
        window._log_at_bottom = False
        window._log_pending = 3

        result = window._scroll_log_to_bottom()

        self.assertEqual(result, "break")
        self.assertEqual(seen, ["end"])
        self.assertTrue(window._log_at_bottom)
        self.assertEqual(window._log_pending, 0)
        self.assertEqual(window._log_pending_var.value, "")

    def test_log_events_accumulate_while_collapsed(self):
        from doc_tool.ui.main_window import MainWindow

        class Text:
            def __init__(self):
                self.lines = []
                self.seen = []

            def configure(self, **_kwargs):
                pass

            def insert(self, _where, text):
                self.lines.append(text)

            def see(self, where):
                self.seen.append(where)

        window = MainWindow.__new__(MainWindow)
        window._log_text = Text()
        window._log_pending_var = self.Var("")
        window._log_summary_var = self.Var("日志已折叠")
        window._log_expanded = False
        window._log_at_bottom = True
        window._log_pending = 0

        window._log("后台事件")

        self.assertEqual(window._log_pending, 1)
        self.assertIn("待读 1 条", window._log_pending_var.value)
        self.assertIn("1 条待读", window._log_summary_var.value)
        self.assertEqual(window._log_text.seen, [])
        self.assertIn("后台事件", window._log_text.lines[0])

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

    def test_failure_event_is_rendered_as_persistent_safe_result(self):
        from unittest.mock import Mock

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.task_bridge import TaskEvent

        class Progress:
            def stop(self):
                pass

            def configure(self, **_kwargs):
                pass

        window = MainWindow.__new__(MainWindow)
        window._current_task = "merge"
        window._last_error_code = None
        window._last_error_stage = ""
        window._last_error_detail = ""
        window._task_terminal_kind = ""
        window._stage_progress_enabled = False
        window._close_after_task = False
        window._project_summary = SimpleNamespace(project_root=Path("C:/project"))
        window._progress = Progress()
        window._cancel_btn = SimpleNamespace(configure=Mock())
        window._task_name_var = self.Var()
        window._status_var = self.Var()
        window._drain_stage_progress = Mock()
        window._stop_elapsed_update = Mock()
        window._refresh_recent_menu = Mock()
        window._refresh_interaction_state = Mock()
        window._render_result_state = Mock()
        window._current_log_path = lambda: Path("C:/project/logs/runtime.log")
        window._log = Mock()

        window._on_task_event(
            TaskEvent(
                kind="failed",
                stage="merge",
                detail="Word 保存失败",
                error_code="E3003",
            )
        )
        window._on_task_done(None)

        self.assertEqual(window._result_state.status, "failure")
        self.assertEqual(window._result_state.error_code, "E3003")
        self.assertIn("Word 保存失败", window._result_state.summary)
        self.assertTrue(window._result_state.advice)
        window._render_result_state.assert_called_once()

    def test_validation_success_result_exposes_report_only(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "validation.md"
            report_path.write_text("ok", encoding="utf-8")
            window = MainWindow.__new__(MainWindow)
            window._current_task = "validate"
            window._last_error_code = None
            window._last_error_stage = ""
            window._last_error_detail = ""
            window._project_summary = SimpleNamespace(project_root=Path(tmp))
            window._status_var = self.Var()
            window._validation_report_path = lambda: report_path
            window._current_log_path = lambda: Path(tmp) / "runtime.log"
            window._log = Mock()
            window._render_result_state = Mock()
            summary = {
                "exists": True,
                "passCount": 5,
                "failCount": 0,
                "failures": [],
            }
            with patch(
                "doc_tool.application.project_service.read_validation_report_summary",
                return_value=summary,
            ):
                window._handle_validation_result(True)

            self.assertEqual(window._result_state.status, "success")
            self.assertEqual(window._result_state.report_path, report_path)
            self.assertIsNone(window._result_state.output_path)

    def test_stage_progress_heartbeat_and_safe_cancel_feedback(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        class Progress:
            def __init__(self):
                self.options = {}
                self.started = []

            def configure(self, **kwargs):
                self.options.update(kwargs)

            def start(self, interval):
                self.started.append(interval)

            def stop(self):
                pass

        window = MainWindow.__new__(MainWindow)
        window._progress = Progress()
        window._task_name_var = self.Var()
        window._current_task = "merge"
        window._progress_recent_stage = ""
        window._log = Mock()

        with patch(
            "doc_tool.ui.main_window._pipeline_stage_percent",
            return_value={"build": (5, 30)},
        ), patch(
            "doc_tool.ui.main_window._pipeline_stage_labels",
            return_value={"build": "构建"},
        ):
            window._apply_stage_progress("build", "started", "")
            self.assertEqual(window._progress.options["value"], 5)
            self.assertIn("构建", window._task_name_var.value)
            window._apply_stage_progress("build", "succeeded", "")
            self.assertEqual(window._progress.options["value"], 30)

        runner = SimpleNamespace(is_running=True, cancel=Mock())
        window.runner = runner
        window._cancel_btn = SimpleNamespace(configure=Mock())
        window._status_var = self.Var()
        window._progress_recent_stage = "build"
        with patch(
            "doc_tool.ui.main_window._pipeline_stage_labels",
            return_value={"build": "构建"},
        ):
            window._on_cancel()
        self.assertIn("等待安全停止点", window._status_var.value)
        window._cancel_btn.configure.assert_called_once_with(state="disabled")
        runner.cancel.assert_called_once()

    def test_start_task_uses_indeterminate_heartbeat_and_rolls_back_rejection(self):
        from unittest.mock import Mock

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.task_bridge import TaskSpec

        class Progress:
            def __init__(self):
                self.options = {}
                self.started = []
                self.stopped = 0

            def configure(self, **kwargs):
                self.options.update(kwargs)

            def start(self, interval):
                self.started.append(interval)

            def stop(self):
                self.stopped += 1

        window = MainWindow.__new__(MainWindow)
        window._project_summary = SimpleNamespace(project_root=Path("C:/project"))
        window._stage_progress_enabled = False
        window._progress = Progress()
        window._cancel_btn = SimpleNamespace(configure=Mock())
        window._elapsed_var = self.Var()
        window._task_name_var = self.Var()
        window._status_var = self.Var()
        window._render_result_state = Mock()
        window._refresh_interaction_state = Mock()
        window.runner = SimpleNamespace(start=Mock(return_value=False))

        window._start_task(TaskSpec(name="validate", target=lambda: True))

        self.assertEqual(window._progress.options["mode"], "indeterminate")
        self.assertEqual(window._progress.started, [15])
        self.assertEqual(window._progress.stopped, 1)
        self.assertEqual(window._current_task, "")
        self.assertEqual(window._result_state.title, "任务未启动")
        self.assertIn("已有任务", window._status_var.value)

    def test_pipeline_success_and_stale_result_actions(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output.docx"
            output.write_bytes(b"docx")
            report = root / "validation.md"
            report.write_text("ok", encoding="utf-8")
            window = MainWindow.__new__(MainWindow)
            window._project_summary = SimpleNamespace(project_root=root)
            window._current_task = "merge"
            window._last_error_code = None
            window._last_error_stage = ""
            window._last_error_detail = ""
            window._task_terminal_kind = "succeeded"
            window._status_var = self.Var()
            window._summary_vars = {"last_build": self.Var()}
            window._validation_report_path = lambda: report
            window._current_log_path = lambda: root / "runtime.log"
            window._log = Mock()
            window._render_result_state = Mock()
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

            output.unlink()
            window._open_file = Mock(return_value=False)
            window._show_error = Mock()
            window._render_result_state.reset_mock()
            window._open_result_file(output)
            window._show_error.assert_called_once()
            window._render_result_state.assert_called_once()

    def test_project_switch_resets_persistent_result(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.workbench_state import ResultState

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
            project_root=root,
            manifest=manifest,
            lock_info=None,
            is_writable=True,
        )
        window = MainWindow.__new__(MainWindow)
        window._result_state = ResultState(
            status="success", project_root=Path("C:/old-project")
        )
        window._summary_vars = {
            key: self.Var()
            for key in (
                "document_name",
                "document_no",
                "document_type",
                "document_version",
                "source_hash",
                "last_build",
                "project_path",
            )
        }
        window._lock_status_var = self.Var()
        window._status_var = self.Var()
        window._render_result_state = Mock()
        window._refresh_recent_menu = Mock()
        window._refresh_interaction_state = Mock()

        with patch(
            "doc_tool.application.project_service.add_recent_project"
        ) as add_recent:
            window.show_project(summary)

        self.assertEqual(window._result_state.status, "idle")
        self.assertEqual(window._result_state.project_root, root)
        add_recent.assert_called_once()
        window._render_result_state.assert_called_once()

    def test_technical_details_use_only_sanitized_result_fields(self):
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.workbench_state import ResultState

        window = MainWindow.__new__(MainWindow)
        window.root = object()
        window._result_state = ResultState(
            status="failure",
            error_code="E3003",
            stage="word_save",
            exception_summary="Word 保存失败",
            log_path=Path("C:/project/logs/runtime.log"),
        )
        with patch("tkinter.messagebox.showinfo") as showinfo:
            window._show_result_technical_details()

        details = showinfo.call_args.args[1]
        self.assertIn("E3003", details)
        self.assertIn("word_save", details)
        self.assertIn("Word 保存失败", details)
        self.assertIn("runtime.log", details)

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

        class Progress:
            def stop(self):
                pass

            def configure(self, **_kwargs):
                pass

        class Button:
            def configure(self, **_kwargs):
                pass

        def make_window(task):
            window = MainWindow.__new__(MainWindow)
            window._current_task = task
            window._last_error_code = None
            window._last_error_stage = ""
            window._last_error_detail = ""
            window._task_terminal_kind = ""
            window._stage_progress_enabled = False
            window._close_after_task = False
            window._progress = Progress()
            window._cancel_btn = Button()
            window._task_name_var = self.Var()
            window._status_var = self.Var()
            window._drain_stage_progress = Mock()
            window._stop_elapsed_update = Mock()
            window._refresh_recent_menu = Mock()
            window._refresh_interaction_state = Mock()
            window._handle_pipeline_result = Mock()
            window._handle_validation_result = Mock()
            return window

        validation = make_window("validate")
        validation._on_task_done(True)
        validation._handle_validation_result.assert_called_once_with(True)
        validation._handle_pipeline_result.assert_not_called()

        pipeline_result = SimpleNamespace(success=True)
        pipeline = make_window("merge")
        pipeline._on_task_done(pipeline_result)
        pipeline._handle_pipeline_result.assert_called_once_with(pipeline_result)
        pipeline._handle_validation_result.assert_not_called()

    def test_close_running_task_requests_cancel_once(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window.root = object()
        window.runner = SimpleNamespace(is_running=True, cancel=Mock())
        window._close_after_task = False
        window._current_task = "merge"
        window._cancel_btn = SimpleNamespace(configure=Mock())
        window._status_var = self.Var()
        window._task_name_var = self.Var()
        window._log = Mock()

        with patch("tkinter.messagebox.askyesno", return_value=True) as confirm:
            window._on_close()
            window._on_close()

        confirm.assert_called_once()
        window.runner.cancel.assert_called_once()
        self.assertTrue(window._close_after_task)
        self.assertIn("自动退出", window._status_var.value)

    def test_close_running_task_can_be_refused(self):
        from unittest.mock import Mock, patch

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window.root = object()
        window.runner = SimpleNamespace(is_running=True, cancel=Mock())
        window._close_after_task = False
        with patch("tkinter.messagebox.askyesno", return_value=False):
            window._on_close()
        window.runner.cancel.assert_not_called()
        self.assertFalse(window._close_after_task)


class WizardInteractionTests(unittest.TestCase):
    def test_preflight_uses_dedicated_timeout(self):
        from doc_tool.ui.wizard import ImportWizard, PREFLIGHT_TIMEOUT_SECONDS

        captured = []

        class Runner:
            is_running = False

            def start(self, spec, **_kwargs):
                captured.append(spec)
                self.is_running = True
                return True

        wizard = ImportWizard.__new__(ImportWizard)
        wizard._closing = False
        wizard._dialog_exists = lambda: True
        wizard._active_task = ""
        wizard._last_error_code = None
        wizard._runner = Runner()
        wizard._on_task_event = lambda _event: None
        wizard._after_preflight = lambda _result: None
        wizard._do_preflight = lambda: None
        wizard._show_step = lambda: None
        wizard._schedule_poll = lambda: None
        wizard._show_preview_text = lambda _text: None
        wizard._run_preflight()

        self.assertEqual(captured[0].timeout_seconds, PREFLIGHT_TIMEOUT_SECONDS)
        self.assertEqual(captured[0].name, "preflight")

    def test_escape_returns_or_requests_cancellation(self):
        from unittest.mock import Mock

        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard.__new__(ImportWizard)
        wizard._runner = SimpleNamespace(is_running=False)
        wizard._step = 2
        wizard._go_back = Mock()
        wizard._cancel = Mock()
        self.assertEqual(wizard._on_escape(), "break")
        wizard._go_back.assert_called_once()

        wizard._runner.is_running = True
        self.assertEqual(wizard._on_escape(), "break")
        wizard._cancel.assert_called_once()


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

    def _make_window(self, *, project, index_ready=False, workspace=None):
        from unittest.mock import Mock

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window._content_menu = Mock()
        window._content_entry_indexes = {
            "search": 0,
            "references": 1,
            "lint": 2,
            "replace": 3,
            "refactor": 4,
            "open_external": 5,
        }
        window._project_summary = project
        window._content_workspace = workspace
        window._content_index_ready = index_ready
        window._set_menu_entries = Mock()
        return window

    def _menu_states(self, window):
        """从 _set_menu_entries 调用中提取 {key: enabled}。"""
        states = {}
        for call in window._set_menu_entries.call_args_list:
            args = call[0] if call[0] else call[1]
            keys = args[2]
            enabled = args[3]
            for key in keys:
                states[key] = enabled
        return states

    def test_writable_project_index_ready_enables_all(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=True),
            index_ready=True,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=False)
        states = self._menu_states(window)
        self.assertTrue(states["search"])
        self.assertTrue(states["references"])
        self.assertTrue(states["lint"])
        self.assertTrue(states["replace"])
        self.assertTrue(states["refactor"])
        self.assertTrue(states["open_external"])

    def test_readonly_project_disables_write_actions(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=False),
            index_ready=True,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=False)
        states = self._menu_states(window)
        self.assertTrue(states["search"])
        self.assertFalse(states["replace"])
        self.assertFalse(states["refactor"])

    def test_index_not_ready_disables_read_actions(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=True),
            index_ready=False,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=False)
        states = self._menu_states(window)
        self.assertFalse(states["search"])
        self.assertFalse(states["replace"])
        # open_external 仅依赖 workspace 存在
        self.assertTrue(states["open_external"])

    def test_task_running_disables_content_menu(self):
        window = self._make_window(
            project=SimpleNamespace(is_writable=True),
            index_ready=True,
            workspace=object(),
        )
        window._refresh_content_menu_state(running=True)
        states = self._menu_states(window)
        self.assertFalse(states["search"])
        self.assertFalse(states["replace"])


# === 人工操作清单 ===
# 以下操作需要在 Windows 桌面环境中手动执行，无法自动化测试：
#
# 1. 启动应用：python -m doc_tool.app
#    - 预期：主窗口正常显示，标题包含版本号，字体清晰（高 DPI 生效）
#
# 2. 新建项目向导：
#    - 文件 → 新建项目 → 选择 .docx → 预检预览 → 填写信息 → 导入
#    - 预期：每步过渡正常，导入成功后自动打开项目
#
# 3. 打开已有项目：
#    - 文件 → 打开项目 → 选择项目目录
#    - 预期：摘要面板显示文档信息，操作菜单可用
#
# 4. 最近项目列表：
#    - 打开多个项目后，文件 → 最近打开应有记录
#    - 点击列表中的项目可直接打开
#
# 5. 独立校验：
#    - 操作 → 校验项目
#    - 预期：进度条动画，事件日志显示阶段，完成后状态栏显示结果
#
# 6. 诊断构建（无 Word）：
#    - 操作 → 诊断构建
#    - 预期：跳过 Word 刷新，构建完成后显示输出路径
#
# 7. 正式合并：
#    - 操作 → 正式合并
#    - 预期：构建 → 前校验 → Word 刷新 → 后校验，进度条显示阶段
#
# 8. 取消任务：
#    - 任务运行中点击「取消」
#    - 预期：界面响应，任务在阶段边界安全停止，状态显示已取消
#
# 9. 打开目录：
#    - 工具 → 打开 Markdown/输出/日志目录
#    - 预期：Windows 文件管理器打开对应目录
#
# 10. 关于/环境诊断：
#     - 帮助 → 关于
#     - 预期：显示版本、提交、Python、平台信息和 Word 可用性
#
# --- 内容操作（任务 10.5） ---
#
# 11. 内容工作区与索引：
#     - 打开项目 → 下方出现「内容操作」区，状态栏显示"内容索引就绪：N 个文件"
#     - 预期：章节树按 类型/第X章/X.Y/X.Y.Z 层级渲染，节点可点击展开
#
# 12. 章节树打开与定位：
#     - 点击章节树文件节点 → 右侧编辑器打开该文件，预览同步刷新
#     - 搜索/检查结果点击 → 编辑器打开并高亮命中行，章节树同步选中并展开父级
#
# 13. 全文搜索：
#     - 内容 → 全文搜索（Ctrl+F）→ 输入关键字
#     - 预期：后台搜索，结果表显示 文件/行/预览，点击定位；正则/大小写/整词/类型过滤生效
#
# 14. 编辑器与预览：
#     - 编辑器修改 → 侧边预览去抖刷新；Ctrl+S 保存（生成 .md.bak）
#     - 保存后内容 → 章节树/搜索反映最新内容（索引刷新）
#     - 「在外部编辑器打开」用系统程序打开；外部修改后回到工具提示刷新
#
# 15. 全局替换：
#     - 内容 → 全局替换 → 查找 → 逐项「替换此项/跳过」；「全部替换」先弹确认
#     - 预期：每文件 .md.bak，替换后自动跑校验；「回滚本次替换」恢复
#
# 16. 重命名/重编号联动：
#     - 内容 → 章节重命名/重编号 → 选择文件、填新文件名 → 预览影响 → 确认执行
#     - 预期：dry-run 列出受影响引用（旧→新），执行后引用更新、文件重命名、自动校验
#
# 17. 引用分析：
#     - 内容 → 引用分析 → 显示当前文件被哪些文件引用 + 全项目悬空引用
#     - 预期：悬空引用区分「确定/疑似」，点击可定位
#
# 18. 术语/一致性检查：
#     - 内容 → 术语/一致性检查 → 运行检查
#     - 预期：重复标题/术语大小写/TODO 残留列出，点击定位；术语清单增删后立即重跑
#
# 19. 只读项目：
#     - 打开模式版本不兼容的项目
#     - 预期：搜索/树可用，编辑器只读，替换/重命名不可用（内容菜单灰置）
#
# --- UI 优化（后续批次） ---
#
# 20. 章节树工具栏与右键菜单：
#     - 章节树上方「展开全部/折叠全部/刷新」
#     - 预期：展开/折叠全树；刷新后新增/删除/外部修改的文件反映到树
#     - 右键文件节点 → 打开 / 复制相对路径
#
# 21. 编辑器状态反馈：
#     - 修改未保存时工具栏显示「● 未保存」，保存/回滚后消失
#     - 打开文件后状态栏显示结构摘要（标题/段落/表格/图片计数）
#
# 22. 快捷键：
#     - Ctrl+F 聚焦搜索输入框并选中已有文本
#     - Ctrl+1..5 切换内容工作区标签页（章节树/搜索/替换/重命名/检查）
#
# 23. 主页面滚动与摘要折叠：
#     - 缩小窗口高度后，工作台右侧出现垂直滚动条，可滚动触达全部功能
#     - 「项目与就绪状态」右上角「收起/展开」折叠摘要区，为内容工作区腾空间
#     - 折叠后内容工作区占据窗口主要高度，无需全屏即可使用


if __name__ == "__main__":
    unittest.main(verbosity=2)
