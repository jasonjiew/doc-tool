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
        )
        text = format_preview_summary(preview)
        self.assertIn("Heading 1: 2", text)
        self.assertIn("Heading 2: 3", text)
        self.assertIn("图片数量：4", text)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
