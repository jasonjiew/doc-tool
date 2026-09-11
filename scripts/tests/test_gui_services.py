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


class IssuesPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _records(self):
        from doc_tool.application.issues import IssueRecord
        return [
            IssueRecord("pipeline", "build", "requirement", "error", "a.md", 2, "E2001", "失败", "建议", "t1"),
            IssueRecord("lint", "todo_residual", "requirement", "warning", "b.md", 4, None, "TODO", "修正", "t2"),
            IssueRecord("lint", "term_case", "design", "info", "missing.md", None, None, "术语", "修正", "t3"),
        ]

    def test_combined_filters_summary_and_refresh_preservation(self):
        from doc_tool.ui.content.issues_panel import IssuesPanel
        panel = IssuesPanel()
        panel.set_issues(self._records())
        panel._document_type.setCurrentIndex(panel._document_type.findData("requirement"))
        panel._severity.setCurrentIndex(panel._severity.findData("warning"))
        self.assertEqual([item.rel_path for item in panel.filtered_issues()], ["b.md"])
        self.assertIn("warning 1", panel._summary.text())
        panel.set_issues(self._records() + [self._records()[1]])
        self.assertEqual(panel._document_type.currentData(), "requirement")
        self.assertEqual(panel._severity.currentData(), "warning")

    def test_double_click_location_missing_line_file_and_clear(self):
        from doc_tool.ui.content.issues_panel import IssuesPanel
        opened = []
        panel = IssuesPanel(on_open=lambda path, line: opened.append((path, line)))
        panel.set_issues(self._records())
        panel._activate(panel._tree.topLevelItem(0))
        self.assertEqual(opened[-1], ("a.md", 2))
        panel._activate(panel._tree.topLevelItem(2))
        self.assertEqual(opened[-1], ("missing.md", None))
        panel.clear_project()
        self.assertEqual(panel._tree.topLevelItemCount(), 0)
        self.assertEqual(panel._state.text(), "无当前项目数据")


class NeutralWorkbenchBehaviorTests(unittest.TestCase):
    """任务 6.1-6.3/6.6：通用单项目与旧版多类型布局的树/搜索/问题中性化。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_general_single_type_tree_has_no_type_root(self):
        """通用单项目章节树直接展示章节节点，无「通用大文档」类型根。

        真实 general 项目的 rel_path 以 ``general/`` 开头（layout A）；单一类型
        时类型目录不产生根节点，章节目录直接作为顶层（节点 id 保留 rel_path 前缀）。
        """
        from doc_tool.application.content.tree import build_tree

        items = build_tree([
            "general/第1章 引言/1.1 目的.md",
            "general/第2章 功能/2.1 概述.md",
        ])
        roots = [i for i in items if i.parent_id is None]
        texts = [i.text for i in roots]
        self.assertIn("第1章 引言", texts)
        self.assertIn("第2章 功能", texts)
        self.assertNotIn("通用大文档", texts)
        # 顶层节点是章节目录，不包含类型根。
        self.assertNotIn("general", [i.node_id for i in roots])
        self.assertTrue(all(not i.is_file for i in roots))
        # 文件仍挂在对应章节目录下，rel_path 保留 general/ 前缀。
        self.assertEqual(
            [i.node_id for i in items if i.is_file],
            ["general/第1章 引言/1.1 目的.md", "general/第2章 功能/2.1 概述.md"],
        )
        # 祖先链完整：目录节点 id 是文件节点 id 的前缀。
        by_id = {i.node_id: i for i in items}
        for file_item in (i for i in items if i.is_file):
            parent = by_id.get(file_item.parent_id)
            self.assertIsNotNone(parent)
            self.assertTrue(file_item.node_id.startswith(parent.node_id + "/"))

    def test_legacy_multi_type_tree_keeps_compat_roots(self):
        """旧版多类型布局保留需求/设计兼容类型根，使用中性兼容标签。"""
        from doc_tool.application.content.tree import build_tree

        items = build_tree([
            "requirement/第1章/1.1 需求.md",
            "design/第2章/2.1 设计.md",
        ])
        roots = {i.node_id: i.text for i in items if i.parent_id is None}
        self.assertEqual(roots["requirement"], "需求文档（旧版专用）")
        self.assertEqual(roots["design"], "详细设计文档（旧版专用）")

    def test_search_panel_hides_type_filter_for_single_type(self):
        """通用单项目搜索面板不显示类型筛选，默认搜索全部内容。"""
        from doc_tool.application.content.search import SearchResult
        from doc_tool.ui.content.search_panel import SearchPanel

        class _FakeService:
            def search(self, options, cancel_token=None):
                return SearchResult(query=options.query, total=0, hits=[], file_count=0)

        panel = SearchPanel(_FakeService(), show_type_filter=False)
        self.assertFalse(panel._type_box.isVisibleTo(panel))
        options = panel._current_options()
        self.assertIsNone(options.document_types)

    def test_search_panel_keeps_type_filter_for_multi_type(self):
        from doc_tool.application.content.search import SearchResult
        from doc_tool.ui.content.search_panel import SearchPanel

        class _FakeService:
            def search(self, options, cancel_token=None):
                return SearchResult(query=options.query, total=0, hits=[], file_count=0)

        panel = SearchPanel(_FakeService(), show_type_filter=True)
        self.assertTrue(panel._type_box.isVisibleTo(panel))
        panel._type_box.setCurrentIndex(1)  # 需求文档（旧版专用）
        self.assertEqual(panel._current_options().document_types, ["requirement"])

    def test_issues_panel_hides_document_type_filter_for_single_type(self):
        """通用单项目问题中心隐藏「文档类型」筛选与列。"""
        from doc_tool.ui.content.issues_panel import IssuesPanel

        panel = IssuesPanel(show_document_type=False)
        self.assertFalse(panel._document_type.isVisibleTo(panel))
        headers = [panel._tree.headerItem().text(i) for i in range(panel._tree.columnCount())]
        self.assertNotIn("文档类型", headers)

        # 填充问题时行数据不含文档类型列
        from doc_tool.application.issues import IssueRecord
        panel.set_issues([
            IssueRecord("pipeline", "build", "general", "error", "a.md", 2, "E2001", "失败", "建议", "t1"),
        ])
        item = panel._tree.topLevelItem(0)
        self.assertEqual(item.text(0), "error")
        self.assertEqual(item.text(1), "build")
        self.assertEqual(item.text(2), "a.md")

    def test_issues_panel_keeps_document_type_filter_for_multi_type(self):
        from doc_tool.ui.content.issues_panel import IssuesPanel

        panel = IssuesPanel(show_document_type=True)
        self.assertTrue(panel._document_type.isVisibleTo(panel))


class TaskRunnerTests(unittest.TestCase):
    """任务 6.8：TaskRunner 后台执行、事件推送与取消。"""

    def test_successful_task_emits_events(self):
        """成功任务推送 started + succeeded 事件（不产生 failed）。"""
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        runner = TaskRunner()
        seen = []

        def simple_task():
            return 42

        runner.start(
            TaskSpec(name="test", target=simple_task),
            on_event=lambda event: seen.append(event),
        )
        runner.join(timeout=5)
        runner.poll()  # 驱动事件回调

        kinds = [e.kind for e in seen]
        self.assertIn("started", kinds)
        self.assertIn("succeeded", kinds)
        self.assertNotIn("failed", kinds)
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
        from unittest.mock import patch

        self._tmp = tempfile.mkdtemp(prefix="doc-gui-svc-")
        # 隔离用户配置目录：最近项目/窗口几何相关测试必须写入临时 home，
        # 绝不能读写真实用户目录下的 ~/.doctool/recent.json（否则跑一次测试
        # 套件就会清空用户真实的「最近项目」列表）。
        self._fake_home = Path(tempfile.mkdtemp(prefix="doc-gui-home-"))
        self._home_patcher = patch("pathlib.Path.home", return_value=self._fake_home)
        self._home_patcher.start()
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
        self._home_patcher.stop()
        shutil.rmtree(self._fake_home, ignore_errors=True)
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
            geometry_file = home / ".doctool" / "geometry.json"
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

    def test_recent_entry_document_type_roundtrip_and_legacy_default(self):
        """documentType 序列化往返；旧版记录缺该字段时回退空串（向后兼容）。"""
        from doc_tool.application.project_service import RecentEntry

        entry = RecentEntry(
            path="C:/p", name="p", document_name="d", document_no="n",
            document_type="requirement", last_opened="2026-08-01T00:00:00+00:00",
        )
        data = entry.to_dict()
        self.assertEqual(data["documentType"], "requirement")
        restored = RecentEntry.from_dict(data)
        self.assertEqual(restored.document_type, "requirement")
        self.assertEqual(restored.last_opened, entry.last_opened)

        legacy = RecentEntry.from_dict({"path": "C:/p", "name": "p"})
        self.assertEqual(legacy.document_type, "")
        self.assertEqual(legacy.last_opened, "")

    def test_add_recent_project_stamps_document_type_and_last_opened(self):
        """打开项目补写文档类型与最近打开时间戳（首页徽章/「N 天前打开」数据源）。"""
        from datetime import datetime

        from doc_tool.application.project_service import (
            add_recent_project,
            load_recent_projects,
        )
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(self._tmp)
        add_recent_project(self._tmp, manifest)
        entries = load_recent_projects()
        resolved = str(Path(self._tmp).resolve())
        entry = next(e for e in entries if e.path == resolved)
        self.assertEqual(entry.document_type, manifest.documentType)
        self.assertTrue(entry.last_opened)
        datetime.fromisoformat(entry.last_opened)  # 必须可解析为 ISO 时间戳


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
        # 公共版不再渲染文档类型「建议模式」
        self.assertNotIn("建议模式", text)

    def test_wizard_exposes_six_qwizard_pages(self):
        _ensure_qapp()
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard()
        self.assertEqual(wizard.pageIds(), [0, 1, 2, 3, 4, 5])
        self.assertTrue(hasattr(wizard, "_source_page"))
        self.assertTrue(hasattr(wizard, "_preflight_page"))
        self.assertTrue(hasattr(wizard, "_mapping_page"))
        self.assertTrue(hasattr(wizard, "_info_page"))
        self.assertTrue(hasattr(wizard, "_executing_page"))
        self.assertTrue(hasattr(wizard, "_result_page"))
        wizard.close()

    def test_project_info_validation_rules(self):
        """文档名/项目名必填，文档编号与版本可选（任务 4.2）。"""
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard.__new__(ImportWizard)
        wizard._doc_type = "general"
        wizard._doc_no = ""
        wizard._doc_name = ""
        wizard._doc_version = ""
        wizard._project_name = "proj"
        wizard._target_parent = "C:/x"
        # 文档名必填
        self.assertIn("文档名称", wizard._validate_project_info())

        wizard._doc_name = "文档"
        # 文档编号/版本为空不报错（可选元数据）
        self.assertEqual(wizard._validate_project_info(), "")

        wizard._project_name = "a:b"
        self.assertIn("不允许的字符", wizard._validate_project_info())

        wizard._project_name = "good-name"
        self.assertEqual(wizard._validate_project_info(), "")


class WizardFidelityAndMappingTests(unittest.TestCase):
    """任务 2.3/3.3：预检页阻断确认门禁与样式映射页下拉逻辑。"""

    def _wizard(self):
        _ensure_qapp()
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard()
        self.addCleanup(wizard.close)
        return wizard

    def test_preflight_block_gate_requires_confirmation(self):
        wizard = self._wizard()
        page = wizard._preflight_page
        page._preview_ok = True
        page._has_block = True
        page._confirm_block.setChecked(False)
        self.assertFalse(page.isComplete(), "存在阻断特性且未确认时不得继续")
        page._confirm_block.setChecked(True)
        self.assertTrue(page.isComplete(), "确认「仍然导入」后放行")
        # 无阻断特性时不要求确认
        page._has_block = False
        page._confirm_block.setChecked(False)
        self.assertTrue(page.isComplete())
        # 结构性预检失败始终阻断
        page._preview_ok = False
        self.assertFalse(page.isComplete())

    def test_format_preview_summary_renders_fidelity_block(self):
        from types import SimpleNamespace

        from doc_tool.adapters.fidelity import FidelityFinding, FidelityReport, SEVERITY_BLOCK
        from doc_tool.ui.wizard import format_preview_summary

        preview = SimpleNamespace(
            heading_level_counts={1: 2},
            image_count=1,
            table_count=0,
            warnings=[],
            fidelity=FidelityReport(findings=(
                FidelityFinding("comment", "批注", SEVERITY_BLOCK, 1, ("body[3]",)),
            )),
        )
        text = format_preview_summary(preview)
        self.assertIn("保真风险", text)
        self.assertIn("批注", text)
        self.assertIn("阻断", text)

    def test_style_mapping_page_mapping_and_complete(self):
        from types import SimpleNamespace

        from doc_tool.adapters.preflight import StyleCensus

        census = {
            "ChapterTitle": StyleCensus("ChapterTitle", "章标题", 2, True),
            "SectionTitle": StyleCensus("SectionTitle", "节标题", 2, True),
            "Normal": StyleCensus("Normal", "Normal", 5, False),
        }
        preview = SimpleNamespace(
            style_census=census,
            heading_style_map={"ChapterTitle": 1},
        )
        wizard = self._wizard()
        page = wizard._mapping_page
        page._populate(preview)
        self.assertEqual(page.mapping(), {"ChapterTitle": 1}, "自动识别级别应预填")
        self.assertTrue(page.isComplete(), "存在级别 1 映射时允许继续")
        # 把 ChapterTitle 改为忽略 -> 无 H1 -> 不可继续
        chapter_combo = next(r["combo"] for r in page._rows if r["style_id"] == "ChapterTitle")
        chapter_combo.setCurrentIndex(chapter_combo.findData(0))
        self.assertFalse(page.isComplete(), "缺少级别 1 映射时不可继续")
        # 映射 SectionTitle 到级别 1 -> 恢复可继续
        section_combo = next(r["combo"] for r in page._rows if r["style_id"] == "SectionTitle")
        section_combo.setCurrentIndex(section_combo.findData(1))
        self.assertTrue(page.isComplete())
        self.assertEqual(page.mapping()["SectionTitle"], 1)


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
            self.assertIn("正式出稿成功", window._result_state.title)
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

    def _merge_patches(self, MainWindow):
        """把 _on_merge 的外部依赖（Word/内核/前置检查）全部替换掉。"""
        from unittest.mock import patch

        return [
            patch(
                "doc_tool.application.word_check.check_word_available",
                return_value=SimpleNamespace(available=True, reasons=[]),
            ),
            patch("doc_tool.adapters.kernel.ensure_kernel_importable"),
            patch.object(MainWindow, "_refresh_interaction_state"),
            patch.object(MainWindow, "_confirm_pre_publish_checks", return_value=True),
            patch.object(MainWindow, "_start_task"),
        ]

    def _run_merge(self, last_version="V3.8"):
        """构造窗口跑一次 _on_merge，返回（_start_task mock, 前置检查 mock）。

        合并不再弹修订记录窗：项目替身指向临时目录里真实的
        ``_revision_record.md``，版本号由该文件末行决定（``last_version`` 为
        空则不创建该文件，模拟旧项目/无修订表）。
        """
        import contextlib

        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.ui.main_window import MainWindow

        root = Path(tempfile.mkdtemp(prefix="doc-tool-merge-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        type_root = root / "content" / "requirement"
        type_root.mkdir(parents=True)
        if last_version:
            (type_root / "_revision_record.md").write_text(
                "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
                "|------|----------|----------|--------|\n"
                "| {0} | 上次合并 | 2026-07-01 | 王杰 |\n".format(last_version),
                encoding="utf-8",
            )
        window = MainWindow()
        window._project_summary = SimpleNamespace(
            manifest=SimpleNamespace(
                documentVersion="V3.7",
                publishNotes="",
                relative_content_root=lambda: "content/requirement",
            ),
            paths=ProjectPaths(root),
            is_writable=True,
        )
        with contextlib.ExitStack() as stack:
            mocks = [
                stack.enter_context(patcher)
                for patcher in self._merge_patches(MainWindow)
            ]
            window._on_merge()
        window.close()
        return mocks[-1], mocks[-2]

    def test_merge_passes_no_revision_arguments_to_pipeline(self):
        """修订记录由 _revision_record.md 一处维护：管线不再收摘要/版本号参数。"""
        start, checks = self._run_merge()
        spec = start.call_args.args[0]
        self.assertEqual(spec.name, "merge")
        self.assertFalse(spec.kwargs["skip_word_refresh"])
        self.assertEqual(
            sorted(spec.kwargs), ["progress", "skip_word_refresh"]
        )
        # 前置检查按修订记录末行版本号（已去 V）提示，而非清单里的旧版本号。
        checks.assert_called_once_with("3.8")

    def test_merge_without_revision_record_falls_back_to_manifest_version(self):
        """没有修订记录文件时前置检查退回清单版本号（传 None），合并照常启动。"""
        start, checks = self._run_merge(last_version="")
        start.assert_called_once()
        checks.assert_called_once_with(None)

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

    def test_start_task_merge_and_diag_build_initializes_pending_steps(self):
        """测试正式合并与诊断构建启动时正确初始化待处理步骤列表（防 STEP_STATUS_PENDING 未定义回归）。"""
        from unittest.mock import Mock
        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.task_bridge import TaskSpec
        from doc_tool.application.pipeline import PIPELINE_STAGE_ORDER

        window = MainWindow()
        window.runner = Mock()
        window.runner.start.return_value = True
        window.runner.is_running = False

        # 1. 验证正式合并
        spec_merge = TaskSpec(name="merge", target=lambda: None)
        window._start_task(spec_merge)
        self.assertEqual(window._task_dock._step_list.count(), len(PIPELINE_STAGE_ORDER))
        # 步骤应全部初始化（文字含待执行 glyph ○）
        self.assertIn("○", window._task_dock._step_list.item(0).text())

        # 2. 验证诊断构建
        spec_diag = TaskSpec(name="diag_build", target=lambda: None)
        window._start_task(spec_diag)
        self.assertEqual(window._task_dock._step_list.count(), len(PIPELINE_STAGE_ORDER))
        self.assertIn("○", window._task_dock._step_list.item(0).text())

        window._poll_timer.stop()
        window._elapsed_timer.stop()
        window.runner.is_running = False
        window.close()

    def test_project_loading_overlay_no_nested_graphics_effect_warnings(self):
        """测试项目加载遮罩层的生命周期正常切换与淡出结束，无 QPainter 或 nested effect 异常。"""
        from PySide6.QtWidgets import QWidget
        from doc_tool.ui.project_loading_overlay import ProjectLoadingOverlay

        parent = QWidget()
        parent.show()
        overlay = ProjectLoadingOverlay(parent, dark=False)
        overlay.start("TestProject", "正在准备工作区…")
        self.assertFalse(overlay.isHidden())
        self.assertFalse(overlay._opacity_effect.isEnabled())

        # 阶段切换
        overlay.show_stage("正在加载模型…")
        self.assertEqual(overlay._stage_label.text(), "正在加载模型…")

        # 结束淡出
        done = []
        overlay.finish(on_finished=lambda: done.append(True))
        self.assertTrue(overlay._opacity_effect.isEnabled())
        overlay._on_animation_finished()
        self.assertTrue(overlay.isHidden())
        self.assertFalse(overlay._opacity_effect.isEnabled())
        self.assertEqual(done, [True])
        parent.close()

    def test_project_loading_overlay_interactive_steps_and_dismiss(self):
        """测试加载遮罩分阶段进度胶囊、跳过/关闭按钮交互与 Esc 退出。"""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget
        from doc_tool.ui.project_loading_overlay import ProjectLoadingOverlay

        parent = QWidget()
        parent.show()
        overlay = ProjectLoadingOverlay(parent, dark=False)
        overlay.start("TestProject", "正在解析配置…")

        # 验证初始状态
        self.assertEqual(overlay._current_step, 0)
        self.assertEqual(overlay._progress_bar.value(), 15)
        self.assertEqual(len(overlay._step_pills), 4)
        self.assertIn("●", overlay._step_pills[0].text())

        # 阶段推进：索引
        overlay.show_stage("正在建立全文索引…")
        self.assertEqual(overlay._current_step, 1)
        self.assertEqual(overlay._progress_bar.value(), 55)
        self.assertIn("✓", overlay._step_pills[0].text())
        self.assertIn("●", overlay._step_pills[1].text())

        # 阶段推进：工作区
        overlay.show_stage("准备工作区视图…")
        self.assertEqual(overlay._current_step, 2)
        self.assertEqual(overlay._progress_bar.value(), 75)

        # 阶段推进：恢复标签
        overlay.show_stage("正在恢复标签页…")
        self.assertEqual(overlay._current_step, 3)
        self.assertEqual(overlay._progress_bar.value(), 90)

        # 切换主题
        overlay.set_dark(True)
        overlay.set_dark(False)

        # 交互测试：跳过等待按钮点击直接结束
        self.assertFalse(overlay._opacity_effect.isEnabled())
        overlay._skip_btn.click()
        self.assertTrue(overlay._opacity_effect.isEnabled())
        overlay._on_animation_finished()
        self.assertTrue(overlay.isHidden())

        # 重新启动测试 Esc 键退出
        overlay.start("TestProject2", "正在解析配置…")
        self.assertFalse(overlay.isHidden())
        esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        overlay.keyPressEvent(esc_event)
        self.assertTrue(overlay._opacity_effect.isEnabled())
        overlay._on_animation_finished()
        self.assertTrue(overlay.isHidden())

        parent.close()

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
        from PySide6.QtWidgets import QApplication

        win._content_workspace = SimpleNamespace(
            focus_search=Mock(), focus_in_editor_find=Mock()
        )
        win._content_index_ready = True
        app = QApplication.instance()
        if app and app.focusWidget():
            app.focusWidget().clearFocus()
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
        self.assertEqual(wizard.pageIds(), [0, 1, 2, 3, 4, 5])
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
        """run() 必须用 QDialog.DialogCode 判定结果（回归：QDialogButtonBox 无该枚举导致崩溃）。

        导入成功后返回目标目录；取消/失败（目标未生成）时返回 None，避免主窗口
        把失败路径当项目打开并误报「打开项目失败」。
        """
        from unittest.mock import Mock, patch

        from PySide6.QtWidgets import QDialog

        from doc_tool.ui.wizard import ImportWizard

        _ensure_qapp()
        wizard = ImportWizard()
        with patch.object(wizard, "exec", return_value=QDialog.DialogCode.Accepted):
            wizard._target_root = "C:/proj"
            wizard._import_result = Mock(success=True)
            self.assertEqual(wizard.run(), "C:/proj")
        # 导入失败：结果页「关闭」也会 accept()，但不得返回未生成的目标路径
        with patch.object(wizard, "exec", return_value=QDialog.DialogCode.Accepted):
            wizard._target_root = "C:/proj"
            wizard._import_result = Mock(success=False)
            self.assertIsNone(wizard.run())
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


class ChapterTreeInteractionTests(unittest.TestCase):
    """章节树键盘操作与右键菜单（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        from doc_tool.application.content.tree import build_tree

        self.content_root = Path(tempfile.mkdtemp(prefix="doc-tool-tree-"))
        self.rel = "requirement/第3章/3.7 GXOA/3.7.1 设备管理.md"
        path = self.content_root / self.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 3.7.1 设备管理\n", encoding="utf-8")
        self.items = build_tree([self.rel])
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)

    def _make_tree(self, writable=True):
        from doc_tool.ui.content.tree_panel import ChapterTree

        self.opened = []
        self.renamed = []
        self.deleted = []
        self.external = []
        self.dirs_opened = []
        self.moves = []
        tree = ChapterTree(
            on_open=self.opened.append,
            on_rename_file=self.renamed.append,
            on_delete_file=self.deleted.append,
            on_move_node=lambda source, parent, before: self.moves.append(
                (source, parent, before)
            ) or True,
            on_open_external=self.external.append,
            on_open_directory=self.dirs_opened.append,
            content_root=self.content_root,
            writable=writable,
        )
        tree.set_items(self.items)
        return tree

    def _select_file(self, tree):
        index = tree._model.index_for_id(self.rel)
        tree._tree.setCurrentIndex(index)
        tree._tree.scrollTo(index)
        tree._tree.setFocus()

    def test_enter_opens_file(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tree = self._make_tree()
        tree.show()
        self._select_file(tree)  # 选中即打开一次（currentChanged → on_open）
        self.assertEqual(self.opened, [self.rel])
        QTest.keyClick(tree._tree, Qt.Key.Key_Return)
        QTest.qWait(10)
        # Enter 再次打开当前选中文件
        self.assertEqual(self.opened, [self.rel, self.rel])
        tree.close()

    def test_f2_renames_file(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tree = self._make_tree()
        tree.show()
        self._select_file(tree)
        QTest.keyClick(tree._tree, Qt.Key.Key_F2)
        QTest.qWait(10)
        self.assertEqual(self.renamed, [self.rel])
        tree.close()

    def test_delete_key_deletes_file(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tree = self._make_tree()
        tree.show()
        self._select_file(tree)
        QTest.keyClick(tree._tree, Qt.Key.Key_Delete)
        QTest.qWait(10)
        self.assertEqual(self.deleted, [self.rel])
        tree.close()

    def test_readonly_ignores_write_keys(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tree = self._make_tree(writable=False)
        tree.show()
        self._select_file(tree)
        QTest.keyClick(tree._tree, Qt.Key.Key_F2)
        QTest.keyClick(tree._tree, Qt.Key.Key_Delete)
        QTest.qWait(10)
        self.assertEqual(self.renamed, [])
        self.assertEqual(self.deleted, [])
        tree.close()

    def test_model_drop_resolves_parent_and_insert_position(self):
        from PySide6.QtCore import Qt

        tree = self._make_tree()
        source = tree._model.index_for_id(self.rel)
        mime = tree._model.mimeData([source])
        parent_id = "requirement/第3章/3.7 GXOA"
        parent = tree._model.index_for_id(parent_id)
        accepted = tree._model.dropMimeData(
            mime, Qt.DropAction.MoveAction, 0, 0, parent
        )
        self.assertTrue(accepted)
        self.assertEqual(self.moves, [(self.rel, parent_id, self.rel)])
        tree.close()

    def test_model_drop_on_file_inserts_before_that_file(self):
        from PySide6.QtCore import Qt

        tree = self._make_tree()
        source = tree._model.index_for_id(self.rel)
        mime = tree._model.mimeData([source])
        accepted = tree._model.dropMimeData(
            mime, Qt.DropAction.MoveAction, -1, 0, source
        )
        self.assertTrue(accepted)
        self.assertEqual(
            self.moves,
            [(self.rel, "requirement/第3章/3.7 GXOA", self.rel)],
        )
        tree.close()

    def test_readonly_disables_drag_and_rejects_drop_callback(self):
        tree = self._make_tree(writable=False)
        self.assertFalse(tree._tree.dragEnabled())
        self.assertFalse(tree._tree.acceptDrops())
        self.assertFalse(tree._handle_drop(self.rel, "requirement/第3章", None))
        self.assertEqual(self.moves, [])
        tree.close()

    def test_context_menu_actions_and_copy_markdown_link(self):
        from PySide6.QtWidgets import QApplication

        tree = self._make_tree()
        index = tree._model.index_for_id(self.rel)
        menu = tree._context_menu(index)
        labels = [a.text() for a in menu.actions()]
        for expected in (
            "打开",
            "在外部编辑器打开",
            "复制相对路径",
            "复制绝对路径",
            "复制 Markdown 引用",
        ):
            self.assertIn(expected, labels)
        action = next(
            a for a in menu.actions() if a.text() == "复制 Markdown 引用"
        )
        # 离屏平台的剪贴板 read-back 不可靠（setText 后 text() 常返回空）：
        # 用 spy 捕获实际写入值验证接线，不依赖 QApplication.clipboard().text()。
        clipboard = QApplication.clipboard()
        written: list = []
        original_set_text = clipboard.setText
        clipboard.setText = lambda text, mode=None: written.append(text)
        try:
            action.trigger()
        finally:
            clipboard.setText = original_set_text
        self.assertEqual(written, ["[设备管理]({0})".format(self.rel)])
        tree.close()

    def test_directory_context_menu_on_flatten_single_type_root(self):
        """测试单一类型项目中，顶层章节目录（parent_id 为 None）依然能正常展示右键菜单。"""
        from doc_tool.application.content.tree import build_tree

        # 仅包含 general 的文件列表：build_tree 会 flatten_single_type，第一层目录 parent_id 为 None
        items = build_tree(["general/1 概述/1.1 背景.md"])
        tree = self._make_tree(writable=True)
        tree.set_items(items)

        # 查找顶层目录节点
        dir_node_id = "general/1 概述"
        index = tree._model.index_for_id(dir_node_id)
        self.assertTrue(index.isValid())
        menu = tree._context_menu(index)
        labels = [a.text() for a in menu.actions()]
        self.assertIn("新增章节/文件…", labels)
        self.assertIn("在文件管理器打开", labels)
        self.assertIn("重新编号本目录（连续）…", labels)
        tree.close()


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

    def test_restore_uses_rollback_single_callback_if_provided(self):
        calls = []
        def _mock_rollback(item):
            calls.append(item.rel_path)
            return None

        from doc_tool.ui.content.changes_panel import ChangesPanel
        panel = ChangesPanel(
            snapshot=self.snapshot,
            writer=self.writer,
            content_root=self.content_root,
            on_restored=lambda: calls.append("restored"),
            rollback_single=_mock_rollback,
            writable=True,
        )
        panel.set_items(self._items_for_modified())
        panel._list.setCurrentRow(0)
        panel._restore_btn.click()
        self.assertEqual(calls, [self.rel, "restored"])
        panel.close()

    def test_binary_item_shows_placeholder_without_decoding(self):
        """选中非文本改动（content 内图片）只提示，不按 UTF-8 读文件。

        Git 模式会把 ``content/**`` 下的图片一起列进改动，此前面板会直接
        ``read_text`` 触发 UnicodeDecodeError。
        """
        from doc_tool.application.content.changes import ChangeItem

        asset_rel = "requirement/images/图1.png"
        asset_path = self.content_root / asset_rel
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary")

        panel = self._panel()
        panel.set_items([ChangeItem(asset_rel, "added", asset_rel)])
        panel._list.setCurrentRow(0)
        text = panel._diff_view.toPlainText()
        self.assertIn("非文本文件", text)
        self.assertIn("新增", text)
        # 未读取文件内容：二进制字节不会出现在 diff 视图里。
        self.assertNotIn("PNG", text)
        panel.close()

    def test_changes_panel_diff_highlighter_present_and_toggles_dark(self):
        """改动面板 diff 视图挂载 DiffHighlighter 并支持深浅主题切换。"""
        from doc_tool.ui.content.editor_highlight import DiffHighlighter

        panel = self._panel()
        self.assertIsInstance(panel._diff_highlighter, DiffHighlighter)
        panel.set_dark(True)
        self.assertTrue(panel._diff_highlighter._dark)
        panel.set_dark(False)
        self.assertFalse(panel._diff_highlighter._dark)
        panel.close()


class TabsHostDirtyTests(unittest.TestCase):
    """脏标签 ● 提示 + 关闭脏 tab 确认（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def _host(self):
        from doc_tool.ui.content.tabs_host import TabsHost

        root = Path(tempfile.mkdtemp(prefix="doc-tool-tabs-"))
        content_root = root / "content"
        rel = "requirement/第1章 引言/1.1 目的.md"
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 1.1 目的\n原文\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        writer = _FakeWriter(content_root)
        tabs = TabsHost(writer)
        tabs.open_file(rel, path.read_text(encoding="utf-8"))
        return tabs, rel

    def test_dirty_tab_shows_bullet_and_clears_on_save(self):
        tabs, _rel = self._host()
        editor = tabs.current_editor()
        self.assertNotIn("●", tabs._tabs.tabText(0))
        editor._editor.setPlainText("# 1.1 目的\n被改\n")
        self.assertTrue(editor.is_dirty())
        self.assertIn("●", tabs._tabs.tabText(0))
        editor.save()
        self.assertFalse(editor.is_dirty())
        self.assertNotIn("●", tabs._tabs.tabText(0))
        tabs.close_all()
        tabs.close()

    def test_close_dirty_tab_requires_confirmation(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        tabs, _rel = self._host()
        editor = tabs.current_editor()
        editor._editor.setPlainText("# 1.1 目的\n被改\n")
        # 拒绝 → 标签保留
        with patch.object(
            QMessageBox, "question",
            return_value=QMessageBox.StandardButton.No,
        ):
            tabs._close_tab(0)
        self.assertEqual(tabs._tabs.count(), 1)
        # 确认 → 标签关闭
        with patch.object(
            QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            tabs._close_tab(0)
        self.assertEqual(tabs._tabs.count(), 0)
        tabs.close()


class EditorFindTests(unittest.TestCase):
    """文件内查找：高亮、导航、focus_find（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def _panel(self):
        from doc_tool.ui.content.editor_panel import EditorPanel

        root = Path(tempfile.mkdtemp(prefix="doc-tool-find-"))
        content_root = root / "content"
        rel = "requirement/第1章 引言/1.1 目的.md"
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# 1.1 目的\n正文含 目的 一词。\n再看 目的。\n",
            encoding="utf-8",
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        writer = _FakeWriter(content_root)
        panel = EditorPanel(writer=writer, writable=True)
        panel.load(rel, path.read_text(encoding="utf-8"))
        return panel

    def test_focus_find_shows_bar_and_focuses(self):
        from PySide6.QtTest import QTest

        panel = self._panel()
        panel.show()
        panel.raise_()
        panel.activateWindow()
        QTest.qWait(50)
        self.assertTrue(panel._find_bar.isHidden())
        panel.focus_find()
        self.assertFalse(panel._find_bar.isHidden())
        self.assertTrue(panel._find_entry.hasFocus())
        panel.close()

    def test_highlights_all_matches(self):
        panel = self._panel()
        panel._find_entry.setText("目的")
        selections = panel._editor.extraSelections()
        # 标题 + 两处正文 = 3 处命中
        self.assertEqual(len(selections), 3)
        panel.close()

    def test_find_next_moves_cursor_to_match(self):
        panel = self._panel()
        panel._find_entry.setText("目的")
        panel._find_next()
        self.assertEqual(panel._editor.textCursor().selectedText(), "目的")
        panel.close()

    def test_hide_find_clears_highlights(self):
        panel = self._panel()
        panel._find_entry.setText("目的")
        self.assertGreater(len(panel._editor.extraSelections()), 0)
        panel.hide_find()
        self.assertFalse(panel._find_bar.isVisible())
        self.assertEqual(panel._editor.extraSelections(), [])
        panel.close()


class EditorPreviewTests(unittest.TestCase):
    """预览折叠 + 编辑滚动联动预览（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def _panel(self):
        from doc_tool.ui.content.editor_panel import EditorPanel

        root = Path(tempfile.mkdtemp(prefix="doc-tool-preview-"))
        content_root = root / "content"
        rel = "requirement/第1章 引言/1.1 目的.md"
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 1.1 目的\n正文内容。\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        writer = _FakeWriter(content_root)
        panel = EditorPanel(writer=writer, writable=True)
        panel.load(rel, path.read_text(encoding="utf-8"))
        return panel

    def test_preview_toggle_hides_and_shows(self):
        panel = self._panel()
        self.assertFalse(panel._preview_frame.isHidden())
        panel._toggle_preview()
        self.assertTrue(panel._preview_frame.isHidden())
        self.assertIn("显示预览", panel._preview_btn.text())
        panel._toggle_preview()
        self.assertFalse(panel._preview_frame.isHidden())
        self.assertIn("隐藏预览", panel._preview_btn.text())
        panel.close()

    def test_sync_preview_scroll_uses_current_heading(self):
        from unittest.mock import patch

        panel = self._panel()
        with patch.object(panel._preview, "setTextCursor") as setc, patch.object(
            panel._preview, "ensureCursorVisible"
        ) as ensure:
            panel._sync_preview_scroll()
        setc.assert_called_once()
        ensure.assert_called_once()
        panel.close()

    def test_current_heading_text(self):
        panel = self._panel()
        self.assertEqual(panel._current_heading_text(), "1.1 目的")
        panel.close()


class EditorHighlightTests(unittest.TestCase):
    """Markdown 语法高亮 + 行号槽（离屏渲染）。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def _make_panel(self):
        from doc_tool.ui.content.editor_panel import EditorPanel

        root = Path(tempfile.mkdtemp(prefix="doc-tool-highlight-"))
        content_root = root / "content"
        rel = "requirement/第1章 引言/1.1 目的.md"
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 1.1 目的\n正文。\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        writer = _FakeWriter(content_root)
        panel = EditorPanel(writer=writer, writable=True)
        panel.load(rel, path.read_text(encoding="utf-8"))
        return panel

    def test_heading_format_bold(self):
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QPlainTextEdit

        from doc_tool.ui.content.editor_highlight import MarkdownHighlighter

        edit = QPlainTextEdit()
        hl = MarkdownHighlighter(edit.document())
        self.assertEqual(hl._heading_fmt().fontWeight(), QFont.Weight.Bold)
        edit.close()

    def test_inline_code_format_has_background(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPlainTextEdit

        from doc_tool.ui.content.editor_highlight import MarkdownHighlighter

        edit = QPlainTextEdit()
        hl = MarkdownHighlighter(edit.document())
        fmt = hl._inline_code_fmt()
        self.assertNotEqual(fmt.background().style(), Qt.BrushStyle.NoBrush)
        edit.close()

    def test_heading_line_gets_bold_format(self):
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QPlainTextEdit

        from doc_tool.ui.content.editor_highlight import MarkdownHighlighter

        edit = QPlainTextEdit()
        MarkdownHighlighter(edit.document())
        edit.setPlainText("# 标题\n普通文本\n")
        formats = edit.document().firstBlock().layout().formats()
        any_bold = any(
            fr.format.fontWeight() == QFont.Weight.Bold for fr in formats
        )
        self.assertTrue(any_bold)

    def test_line_number_width_grows_with_lines(self):
        from doc_tool.ui.content.editor_highlight import _LineNumberedEdit

        edit = _LineNumberedEdit()
        edit.setPlainText("一\n二\n")
        small = edit.line_number_area_width()
        edit.setPlainText("\n".join(str(i) for i in range(15)))
        self.assertGreater(edit.line_number_area_width(), small)

    def test_editor_panel_uses_line_numbers_and_highlighter(self):
        from doc_tool.ui.content.editor_highlight import (
            MarkdownHighlighter,
            _LineNumberedEdit,
        )

        panel = self._make_panel()
        self.assertIsInstance(panel._editor, _LineNumberedEdit)
        self.assertIsInstance(panel._highlighter, MarkdownHighlighter)
        panel.close()

    def test_diff_highlighter_colors_unified_diff(self):
        """测试 DiffHighlighter 高亮器与暗黑模式切换。"""
        from PySide6.QtWidgets import QPlainTextEdit
        from doc_tool.ui.content.editor_highlight import DiffHighlighter

        edit = QPlainTextEdit()
        hl = DiffHighlighter(edit.document(), dark=False)
        edit.setPlainText("--- a/f.md\n+++ b/f.md\n@@ -1 +1 @@\n-old\n+new\n")
        hl.set_dark(True)
        self.assertTrue(hl._dark)
        hl.set_dark(False)
        self.assertFalse(hl._dark)
        edit.close()


class EditorAuthoringWorkbenchTests(unittest.TestCase):
    """创作工作台离屏交互：替换、格式、图片 MIME、预览链接与 Mermaid。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="doc-tool-authoring-ui-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.content = self.root / "content"
        self.assets = self.root / "assets"
        self.rel = "requirement/章节.md"
        path = self.content / self.rel
        path.parent.mkdir(parents=True)
        path.write_text("# 标题\nfoo foo\n", encoding="utf-8")

    def _panel(self, writable=True):
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.editor_panel import EditorPanel

        writer = ContentWriter(self.content, self.root / ".state", assets_root=self.assets)
        panel = EditorPanel(
            writer=writer, assets_root=self.assets, writable=writable
        )
        panel.load(self.rel, (self.content / self.rel).read_text(encoding="utf-8"))
        return panel

    def test_replace_all_is_single_undo_unit(self):
        panel = self._panel()
        panel._find_entry.setText("foo")
        panel._replace_entry.setText("bar")
        panel._replace_all()
        self.assertIn("bar bar", panel._editor.toPlainText())
        panel._editor.undo()
        self.assertIn("foo foo", panel._editor.toPlainText())
        panel.close()

    def test_replace_one_replaces_selection_and_moves_to_next(self):
        from PySide6.QtGui import QTextCursor

        panel = self._panel()
        panel._find_entry.setText("foo")
        panel._replace_entry.setText("bar")
        cursor = panel._editor.textCursor()
        start = panel._editor.toPlainText().index("foo")
        cursor.setPosition(start)
        cursor.setPosition(start + 3, QTextCursor.MoveMode.KeepAnchor)
        panel._editor.setTextCursor(cursor)
        panel._replace_one()
        self.assertIn("bar foo", panel._editor.toPlainText())
        self.assertEqual(panel._editor.textCursor().selectedText(), "foo")
        panel.close()

    def test_snippet_tab_locates_next_placeholder_after_edit_shift(self):
        """在占位符内输入与默认值不同长度的文本后按 Tab：必须仍定位到下一个
        占位符（旧实现沿用插入时区间，编辑后跳转到错误位置甚至空白）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from doc_tool.application.content.snippets import Snippet

        panel = self._panel()
        panel._editor.moveCursor(panel._editor.textCursor().MoveOperation.End)
        panel.insert_snippet(Snippet("demo", "", "A ${2:乙} B ${1:甲} C"))
        self.assertEqual(panel._editor.textCursor().selectedText(), "甲")
        # 在第一个占位符处输入比默认值更长的文本（区间偏移）
        panel._editor.textCursor().insertText("甲乙丙")
        QTest.keyClick(panel._editor, Qt.Key.Key_Tab)
        self.assertEqual(
            panel._editor.textCursor().selectedText(), "乙",
            "编辑使区间失效后 Tab 仍须按默认文本定位到下一个占位符",
        )
        panel.close()

    def test_snippet_tab_follows_placeholder_number_order(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from doc_tool.application.content.snippets import Snippet

        panel = self._panel()
        panel._editor.moveCursor(panel._editor.textCursor().MoveOperation.End)
        panel.insert_snippet(Snippet("demo", "", "${2:乙}-${1:甲}"))
        self.assertEqual(panel._editor.textCursor().selectedText(), "甲")
        QTest.keyClick(panel._editor, Qt.Key.Key_Tab)
        self.assertEqual(panel._editor.textCursor().selectedText(), "乙")
        QTest.keyClick(panel._editor, Qt.Key.Key_Tab)
        self.assertFalse(panel._editor.snippet_active)
        panel.close()

    def test_toolbar_wraps_selection(self):
        from PySide6.QtGui import QTextCursor

        panel = self._panel()
        cursor = panel._editor.textCursor()
        start = panel._editor.toPlainText().index("foo")
        cursor.setPosition(start)
        cursor.setPosition(start + 3, QTextCursor.MoveMode.KeepAnchor)
        panel._editor.setTextCursor(cursor)
        panel.wrap_selection("**", "**")
        self.assertIn("**foo**", panel._editor.toPlainText())
        panel.close()

    def test_clipboard_image_imports_asset_and_inserts_reference(self):
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QImage

        panel = self._panel()
        mime = QMimeData()
        mime.setImageData(QImage(8, 6, QImage.Format.Format_RGB32))
        panel._editor.insertFromMimeData(mime)
        self.assertIn("images/img_0001.png =8x6", panel._editor.toPlainText())
        self.assertTrue((self.assets / "requirement/images/img_0001.png").is_file())
        panel.close()

    def test_drop_image_file_calls_import_callback(self):
        from PySide6.QtCore import QMimeData, QUrl
        from doc_tool.ui.content.editor_highlight import _LineNumberedEdit

        image = self.root / "drop.png"
        from PIL import Image
        Image.new("RGB", (4, 3), "blue").save(image)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(image))])

        class Event:
            accepted = False
            def mimeData(self):
                return mime
            def acceptProposedAction(self):
                self.accepted = True

        received = []
        edit = _LineNumberedEdit()
        edit.set_image_import_callback(received.append)
        event = Event()
        edit.dropEvent(event)
        self.assertEqual([Path(value).resolve() for value in received], [image.resolve()])
        self.assertTrue(event.accepted)
        edit.close()

    def test_readonly_rejects_image_import(self):
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QImage

        panel = self._panel(writable=False)
        mime = QMimeData()
        mime.setImageData(QImage(8, 6, QImage.Format.Format_RGB32))
        before = panel._editor.toPlainText()
        panel._editor.insertFromMimeData(mime)
        self.assertEqual(panel._editor.toPlainText(), before)
        self.assertFalse((self.assets / "requirement/images").exists())
        panel.close()

    def test_preview_line_anchor_locates_but_external_link_does_not(self):
        from unittest.mock import patch
        from PySide6.QtCore import QUrl

        panel = self._panel()
        with patch.object(panel, "highlight_line") as locate:
            panel._on_preview_anchor_clicked(QUrl("line-2"))
            locate.assert_called_once_with(2)
            locate.reset_mock()
            with patch("doc_tool.ui.content.editor_panel.QDesktopServices.openUrl") as open_url:
                panel._on_preview_anchor_clicked(QUrl("https://example.com"))
                locate.assert_not_called()
                open_url.assert_called_once()
        panel.close()

    def test_preview_browser_scales_images_to_fit_viewport(self):
        """预览面板中超出视口宽度的图表/图片自动等比缩放，防止溢出产生横向滚动条。"""
        import base64
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage

        panel = self._panel()
        panel.resize(400, 600)
        panel.show()

        img = QImage(1200, 800, QImage.Format.Format_ARGB32)
        img.fill(0xFF00FF00)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        b64 = base64.b64encode(bytes(buf.data())).decode("ascii")

        md_text = f"![大图](data:image/png;base64,{b64})\n"
        panel._refresh_preview(md_text)

        preview = panel._preview
        self.assertLessEqual(preview.document().idealWidth(), preview.viewport().width() + 10)
        self.assertEqual(preview.horizontalScrollBar().maximum(), 0)

        panel.close()

    def test_preview_browser_non_ascii_chinese_path_does_not_crash(self):
        """测试加载包含中文或特殊字符深层目录的 Markdown 文件时，预览基准 URL 解析正常且不崩溃。"""
        panel = self._panel()
        chinese_rel = "content/design/第15章 数据存储/15.1 数据存储/15.1.2 数据归档.md"
        panel.load(chinese_rel, "# 测试标题\n\n正文内容")
        self.assertFalse(panel._preview_frame.isHidden())
        panel.close()

    def test_mermaid_dialog_valid_source_renders_preview(self):
        from doc_tool.ui.content.mermaid_dialog import MermaidDialog

        dialog = MermaidDialog("flowchart TD\n A[开始] --> B[结束]")
        dialog.refresh_preview()
        self.assertEqual(dialog.errors.count(), 0)
        self.assertIsNotNone(dialog.render_result)
        self.assertTrue(dialog.render_result.ok)
        self.assertFalse(dialog.preview.pixmap().isNull())
        dialog.close()

    def test_save_refuses_overwrite_when_file_modified_externally(self):
        """磁盘文件被外部修改后保存必须经确认：拒绝时不写入，避免 lost update。"""
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        panel = self._panel()
        target = self.content / self.rel
        # 模拟外部修改：写盘并让 mtime 前进（编辑器 _mtime 为加载时基准）
        target.write_text("# 标题\n外部修改内容\n", encoding="utf-8")
        import os as _os

        st = target.stat()
        _os.utime(target, (st.st_atime + 10, st.st_mtime + 10))
        # 编辑器变为脏
        panel._editor.setPlainText("# 标题\n编辑器修改\n")
        self.assertTrue(panel.is_dirty())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            saved = panel.save()
        self.assertFalse(saved, "拒绝覆盖外部修改时必须返回未保存")
        self.assertIn("外部修改内容", target.read_text(encoding="utf-8"))
        panel.close()

    def test_external_change_prompt_not_repeated_for_same_mtime(self):
        """用户拒绝重载后，同一外部变更（同 mtime）不再重复弹确认框；
        保存保护仍独立生效（save 的 mtime 校验不受影响）。"""
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        panel = self._panel()
        target = self.content / self.rel
        target.write_text("# 标题\n外部修改内容\n", encoding="utf-8")
        import os as _os

        st = target.stat()
        _os.utime(target, (st.st_atime + 10, st.st_mtime + 10))
        panel._editor.setPlainText("# 标题\n编辑器修改\n")
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ) as question:
            self.assertFalse(panel.check_external_change())
            self.assertFalse(panel.check_external_change())  # 再次切换标签
        # 只提示一次（第一次弹框，第二次命中 dismissed 标记直接返回）
        self.assertEqual(question.call_count, 1)
        # 保存保护仍生效：save() 的 mtime 校验独立于 dismissed 标记
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(panel.save())
        self.assertIn("外部修改内容", target.read_text(encoding="utf-8"))
        panel.close()

    def test_save_proceeds_after_confirmed_overwrite(self):
        """用户确认后保存覆盖外部修改（正常写盘路径）。"""
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        panel = self._panel()
        target = self.content / self.rel
        target.write_text("# 标题\n外部修改内容\n", encoding="utf-8")
        import os as _os

        st = target.stat()
        _os.utime(target, (st.st_atime + 10, st.st_mtime + 10))
        panel._editor.setPlainText("# 标题\n编辑器修改\n")
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            saved = panel.save()
        self.assertTrue(saved)
        self.assertIn("编辑器修改", target.read_text(encoding="utf-8"))
        panel.close()

    def test_editor_panel_mermaid_syntax_diagnostics_and_cursor_tracking(self):
        """编辑器实时扫描 Mermaid 语法：错误行波浪线高亮，光标移动提示，修复后恢复。"""
        panel = self._panel()
        invalid_text = (
            "# 架构\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  A[开始] --> B(不匹配括号]\n"
            "```\n"
        )
        panel._editor.setPlainText(invalid_text)
        panel._scan_mermaid_syntax()

        # 存在语法错误
        self.assertTrue(len(panel._mermaid_errors) > 0)
        err_line, err_msg = panel._mermaid_errors[0]
        self.assertEqual(err_line, 4)
        self.assertIn("括号不匹配", err_msg)
        self.assertTrue(len(panel._mermaid_selections) > 0)
        self.assertIn("Mermaid 语法错误", panel._status_label.text())

        # 光标移动到错误行，状态栏即时提醒
        block = panel._editor.document().findBlockByNumber(err_line - 1)
        cursor = panel._editor.textCursor()
        cursor.setPosition(block.position())
        panel._editor.setTextCursor(cursor)
        panel._on_cursor_moved()
        self.assertIn("第 4 行", panel._status_label.text())

        # 光标移动到非错误行（第 1 行），状态栏依然提供总览提醒
        block_first = panel._editor.document().findBlockByNumber(0)
        cursor.setPosition(block_first.position())
        panel._editor.setTextCursor(cursor)
        panel._on_cursor_moved()
        self.assertIn("Mermaid 语法错误", panel._status_label.text())

        # 修复错误后重扫
        fixed_text = (
            "# 架构\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  A[开始] --> B[正常括号]\n"
            "```\n"
        )
        panel._editor.setPlainText(fixed_text)
        panel._scan_mermaid_syntax()
        self.assertEqual(len(panel._mermaid_errors), 0)
        self.assertEqual(len(panel._mermaid_selections), 0)
        self.assertIn("Mermaid 语法错误已修复", panel._status_label.text())
        panel.close()

    def test_mermaid_dialog_templates_and_interactive_validation(self):
        """Mermaid 工作台：支持模板下拉填入、语法错误双击定位与多图表类型校验。"""
        from doc_tool.ui.content.mermaid_dialog import MermaidDialog

        dlg = MermaidDialog("flowchart TD\n  A --> B")
        # 选择模板：类图
        idx = dlg.template_combo.findText("类图 (Class)")
        self.assertGreater(idx, 0)
        dlg.template_combo.setCurrentIndex(idx)
        self.assertIn("classDiagram", dlg.source())

        # 输入错误语法
        dlg.source_edit.setPlainText("classDiagram\n  class Animal {\n    +name\n")  # 未闭合花括号
        dlg.refresh_preview()
        self.assertGreater(dlg.errors.count(), 0)
        self.assertIn("语法存在错误", dlg.preview.text())
        self.assertIn("发现", dlg.status.text())

        # 双击错误条目定位到源码行
        item = dlg.errors.item(0)
        dlg._locate_error(item)
        cur = dlg.source_edit.textCursor()
        self.assertTrue(cur.hasSelection())

        # 修复语法
        dlg.source_edit.setPlainText("classDiagram\n  class Animal {\n    +String name\n  }\n")
        dlg.refresh_preview()
        self.assertTrue("渲染成功" in dlg.status.text() or "语法有效" in dlg.status.text())
        dlg.close()


class LogStreamReplayTests(unittest.TestCase):
    """任务详情日志折叠/展开回放。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_lines_appended_while_collapsed_replayed_on_expand(self):
        """折叠期间到达的日志行在展开后必须回放到视图，不得丢失。"""
        from doc_tool.ui.work_detail_pane import LogStream

        stream = LogStream()
        stream.append_line("第一行")
        stream.set_expanded(False)  # 折叠
        stream.append_line("第二行")  # 折叠期间到达：只进 _lines
        self.assertEqual(stream.pending_unread, 1)
        stream.set_expanded(True)  # 展开：必须回放
        text = stream._view.toPlainText()
        self.assertIn("第一行", text)
        self.assertIn("第二行", text)
        self.assertEqual(stream.pending_unread, 0)
        stream.close()



class ConvertDialogTests(unittest.TestCase):
    """文档互转对话框：方向判定、Word 源转出格式切换与 Markdown 体量摘要。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self._dialogs = []
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 30)
        (self.root / "b.pdf").write_bytes(b"%PDF-1.4\n" + b"\x00" * 30)
        (self.root / "c.md").write_text("# 标题\n\n| 一 | 二 |\n| --- | --- |\n", encoding="utf-8")
        (self.root / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 512)

    def tearDown(self):
        for dlg in getattr(self, "_dialogs", []):
            try:
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        self._tmp.cleanup()

    def _dialog(self):
        from doc_tool.ui.convert_dialog import ConvertDialog

        dlg = ConvertDialog()
        self._dialogs.append(dlg)
        return dlg

    def test_rows_and_direction_labels(self):
        dlg = self._dialog()
        dlg._append([str(self.root / "a.docx"), str(self.root / "b.pdf"), str(self.root / "c.md")])
        labels = [dlg._table.item(r, 1).text() for r in range(dlg._table.rowCount())]
        self.assertEqual(labels, ["Word → PDF", "PDF → Word", "Markdown → Word"])
        # 下拉显式给目标格式；源族没有该方向时由注册表回落缺省（.pdf/.md 选 PDF 仍转 Word）。
        self.assertEqual(dlg._target_format(), "pdf")
        dlg.close()

    def test_format_switch_updates_docx_rows(self):
        dlg = self._dialog()
        dlg._append([str(self.root / "a.docx")])
        dlg._format_combo.setCurrentIndex(dlg._format_combo.findData("md"))
        self.assertEqual(dlg._table.item(0, 1).text(), "Word → Markdown")
        self.assertEqual(dlg._target_format(), "md")
        dlg._format_combo.setCurrentIndex(dlg._format_combo.findData("pdf"))
        self.assertEqual(dlg._table.item(0, 1).text(), "Word → PDF")
        self.assertEqual(dlg._target_format(), "pdf")
        dlg.close()

    def test_legacy_doc_skipped_for_markdown_target(self):
        from PySide6.QtWidgets import QMessageBox

        dlg = self._dialog()
        dlg._format_combo.setCurrentIndex(dlg._format_combo.findData("md"))
        warned = []
        original = QMessageBox.warning
        QMessageBox.warning = staticmethod(
            lambda *args, **kwargs: warned.append(args[2] if len(args) > 2 else "")
        )
        try:
            dlg._append([str(self.root / "old.doc")])
        finally:
            QMessageBox.warning = original
        self.assertEqual(dlg._table.rowCount(), 0)
        self.assertTrue(warned, ".doc 在 Markdown 转出格式下必须被拦下并提示")
        dlg.close()

    def test_markdown_summary_logged_on_append(self):
        dlg = self._dialog()
        dlg._append([str(self.root / "c.md")])
        text = dlg._details.toPlainText()
        self.assertIn("c.md", text)
        self.assertIn("表格 2 行", text)
        dlg.close()

    def test_markdown_summary_logs_encoding_failure(self):
        """编码解不出的 .md：给可见的 E6007 提示，不在加入清单时抛异常。"""
        dlg = self._dialog()
        bad = self.root / "bad.md"
        bad.write_bytes(b"\xff\xff\xff\xff")
        dlg._append([str(bad)])
        text = dlg._details.toPlainText()
        self.assertIn("bad.md", text)
        self.assertIn("E6007", text)
        dlg.close()

    def test_run_button_gates_on_sources(self):
        dlg = self._dialog()
        self.assertFalse(dlg._run_button.isEnabled(), "空清单时开始转换必须禁用")
        dlg._append([str(self.root / "a.docx")])
        self.assertTrue(dlg._run_button.isEnabled())
        dlg._table.selectAll()
        dlg._on_remove_selected()
        self.assertFalse(dlg._run_button.isEnabled(), "移除全部文件后开始转换应回到禁用")
        dlg.close()

    def test_ingest_paths_expands_folder(self):
        """拖放入口：文件夹要展开成一层内的可转换文件，不支持类型（notes.log）不算。

        .txt 自 A 组起是合法源（文本 → PDF），因此改用 .log 当反例。
        """
        (self.root / "notes.log").write_text("x", encoding="utf-8")
        (self.root / "说明.txt").write_text("正文", encoding="utf-8")
        dlg = self._dialog()
        dlg._ingest_paths([self.root])
        names = sorted(
            Path(dlg._table.item(r, 0).text()).name for r in range(dlg._table.rowCount())
        )
        self.assertEqual(names, ["a.docx", "b.pdf", "c.md", "old.doc", "说明.txt"])
        self.assertTrue(dlg._run_button.isEnabled())
        dlg.close()

    def test_drop_zone_highlight_toggles(self):
        dlg = self._dialog()
        self.assertEqual(dlg._drop_zone.styleSheet(), "")
        dlg._drop_zone.set_drag_over(True)
        self.assertIn("dashed", dlg._drop_zone.styleSheet())
        self.assertIn("松开鼠标", dlg._drop_zone._title.text())
        dlg._drop_zone.set_drag_over(False)
        self.assertEqual(dlg._drop_zone.styleSheet(), "")
        dlg.close()

    def test_done_enables_open_output_and_double_click(self):
        from PySide6.QtGui import QDesktopServices

        class _Record:
            ok = True
            note = ""
            target = None

            def __init__(self, target):
                self.target = Path(target)

        class _Result:
            success = True
            failed = 0
            records = []

            def summary(self):
                return "成功 1 个，失败 0 个。"

        dlg = self._dialog()
        self.assertFalse(dlg._open_output_button.isEnabled())
        (self.root / "out").mkdir()
        result = _Result()
        result.records = [_Record(self.root / "out" / "a.pdf")]
        dlg._on_done(result)
        self.assertTrue(dlg._open_output_button.isEnabled(), "有成功产物时应允许打开输出文件夹")

        opened = []
        original = QDesktopServices.openUrl
        QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toLocalFile()))
        try:
            # 双击「（待转换）」占位行：不应打开任何目录。
            dlg._append([str(self.root / "a.docx")])
            dlg._on_row_double_clicked(0, 2)
            self.assertEqual(opened, [], "占位输出不允许触发打开文件夹")
            # 真实产物行：打开其所在文件夹。
            dlg._set_item(0, 2, str(self.root / "out" / "a.pdf"))
            dlg._on_row_double_clicked(0, 2)
            self.assertEqual([Path(opened[0])], [self.root / "out"])
        finally:
            QDesktopServices.openUrl = original
        dlg.close()


class HomeTaskPageTests(unittest.TestCase):
    """首页任务页（EmptyState 改版）：双栏布局、互转接线、整页拖放与最近项目卡。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def _home(self, **callbacks):
        from PySide6.QtWidgets import QApplication

        from doc_tool.ui.empty_state import EmptyState

        home = EmptyState(**callbacks)
        # 在本用例边界内冲掉卡片重建积累的 deleteLater：延迟到下一用例的
        # qWait 里析构会在 offscreen 下诱发原生崩溃（污染全局 Qt 状态）。
        def _dispose():
            home.deleteLater()
            QApplication.processEvents()

        self.addCleanup(_dispose)
        return home

    # --- 假拖放事件（duck-typed，参照 test_drop_image_file_calls_import_callback） ---

    @staticmethod
    def _fake_drag_event(urls):
        from PySide6.QtCore import QUrl

        class _Mime:
            def hasUrls(self):
                return bool(urls)

            def urls(self):
                return [QUrl.fromLocalFile(str(p)) for p in urls]

        class _Event:
            def __init__(self):
                self.accepted = False

            def mimeData(self):
                return _Mime()

            def acceptProposedAction(self):
                self.accepted = True

        return _Event()

    def test_home_shows_convert_and_pdf_toolbox_cards(self):
        from PySide6.QtWidgets import QLabel

        from doc_tool.domain.version import APP_VERSION

        home = self._home()
        home.set_recent_projects([])
        # 互转卡：标题、card 属性、格式 chips、accent 底部标注
        self.assertEqual(home._convert_title.text(), "文档互转")
        self.assertTrue(home._convert_card.property("card"))
        chip_texts = [c.text() for c in home._convert_card.findChildren(QLabel)]
        for chip in (".docx", ".pdf", ".md", ".html"):
            self.assertIn(chip, chip_texts)
        self.assertTrue(any("支持整个文件夹拖入" in t for t in chip_texts))
        # PDF 工具箱卡已激活且可点击
        self.assertTrue(home._pdf_card.isEnabled())
        self.assertEqual(home._pdf_title.text(), "PDF 工具箱")
        pdf_texts = [c.text() for c in home._pdf_card.findChildren(QLabel)]
        for chip in ("合并", "拆分", "水印", "加密", "解密", "压缩", "页码"):
            self.assertIn(chip, pdf_texts)
        self.assertTrue(any("项离线工具" in t for t in pdf_texts))
        # 兼容旧属性名
        self.assertIs(home._placeholder_card, home._pdf_card)
        # 版本徽章取自统一版本模块，不硬编码
        self.assertEqual(home._version_badge.text(), "v{0}".format(APP_VERSION))
        # 无最近项目 → 空态文案
        self.assertIsNotNone(home._empty_label)
        self.assertIn("会在这里列出最近项目", home._empty_label.text())

    @staticmethod
    def _click(widget):
        """离屏下直接向控件派发左键按下。

        QTest.mouseClick 走窗口管理器路径，在 offscreen 平台会给同一进程里
        后续用例的 QTest.qWait/keySequence 留下损坏的窗口焦点状态（原生崩溃）；
        直接派发 QMouseEvent 只测卡片自身的点击语义，无此副作用。
        """
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(5.0, 5.0),
            QPointF(5.0, 5.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.mousePressEvent(event)

    def test_convert_card_click_triggers_main_window_convert(self):
        """点击互转卡 → EmptyState 回调 → 主窗口 _on_convert_documents → 打开互转对话框。

        在链路终点（ConvertDialog 类）打桩：回调在构造时绑定，事后替换实例
        属性不会生效；直接点真卡会弹出真实模态对话框阻塞离屏进程。
        """
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        captured = {}

        class _FakeDialog:
            def __init__(self, parent=None, busy_check=None):
                captured["parent"] = parent

            def exec(self):
                captured["exec_called"] = True

        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        with patch(
            "doc_tool.ui.convert_dialog.ConvertDialog", _FakeDialog
        ):
            self._click(window._empty_state._convert_card)
        self.assertTrue(captured.get("exec_called"))
        self.assertIs(captured.get("parent"), window)

    def test_pdf_toolbox_card_click_triggers_main_window_pdf_toolbox(self):
        """点击 PDF 工具箱卡 → EmptyState 回调 → 主窗口 _on_pdf_toolbox → 打开工具箱对话框。"""
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        captured = {}

        class _FakeDialog:
            def __init__(self, parent=None, busy_check=None):
                captured["parent"] = parent

            def exec(self):
                captured["exec_called"] = True

        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        with patch(
            "doc_tool.ui.pdf_toolbox_dialog.PdfToolboxDialog", _FakeDialog
        ):
            self._click(window._empty_state._pdf_card)
        self.assertTrue(captured.get("exec_called"))
        self.assertIs(captured.get("parent"), window)

    def test_convert_entry_accepts_paths_and_opens_dialog(self):
        """_on_convert_documents(paths) 先把路径交给 _ingest_paths 再打开对话框。"""
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "dragged.docx"
            docx.write_bytes(b"stub")
            captured = {}

            class _FakeDialog:
                def __init__(self, parent=None, busy_check=None):
                    captured["parent"] = parent
                    captured["busy_check"] = busy_check
                    captured["ingested"] = None
                    captured["exec_called"] = False

                def _ingest_paths(self, paths):
                    captured["ingested"] = list(paths)

                def exec(self):
                    captured["exec_called"] = True

            window = MainWindow()
            self.addCleanup(window.close)
            with patch(
                "doc_tool.ui.convert_dialog.ConvertDialog", _FakeDialog
            ):
                window._on_convert_documents([docx])
            self.assertEqual(captured["ingested"], [docx])
            self.assertTrue(captured["exec_called"])
            self.assertIs(captured["parent"], window)
            self.assertFalse(captured["busy_check"]())

    def test_home_drop_hands_paths_to_convert_dialog(self):
        """首页整页拖放：drop 后路径送进 ConvertDialog 并打开，互转卡还原。"""
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "dropped.docx"
            docx.write_bytes(b"stub")
            captured = {}

            class _FakeDialog:
                def __init__(self, parent=None, busy_check=None):
                    captured["ingested"] = None
                    captured["exec_called"] = False

                def _ingest_paths(self, paths):
                    captured["ingested"] = list(paths)

                def exec(self):
                    captured["exec_called"] = True

            window = MainWindow()
            self.addCleanup(window.close)
            home = window._empty_state
            with patch(
                "doc_tool.ui.convert_dialog.ConvertDialog", _FakeDialog
            ):
                home.dropEvent(self._fake_drag_event([docx]))
            self.assertEqual(captured["ingested"], [docx])
            self.assertTrue(captured["exec_called"])
            # drop 后高亮还原
            self.assertFalse(home._drag_over)
            self.assertEqual(home._convert_title.text(), "文档互转")

    def test_drag_enter_highlights_convert_card_and_leave_restores(self):
        from PySide6.QtGui import QDragLeaveEvent
        from PySide6.QtCore import QUrl

        home = self._home()
        event = self._fake_drag_event([QUrl.fromLocalFile("C:/x/a.docx")])
        home.dragEnterEvent(event)
        self.assertTrue(event.accepted)
        self.assertTrue(home._drag_over)
        self.assertEqual(home._convert_card.property("dragOver"), "true")
        self.assertEqual(home._convert_title.text(), "松开鼠标，添加这些文件")
        self.assertEqual(home._convert_desc.text(), "已识别拖入的文件，进入互转窗口。")
        home.dragLeaveEvent(QDragLeaveEvent())
        self.assertFalse(home._drag_over)
        self.assertEqual(home._convert_card.property("dragOver"), "false")
        self.assertEqual(home._convert_title.text(), "文档互转")

    def test_drag_without_urls_is_ignored(self):
        home = self._home()
        event = self._fake_drag_event([])
        home.dragEnterEvent(event)
        self.assertFalse(event.accepted)
        self.assertFalse(home._drag_over)

    def test_only_home_view_accepts_drops(self):
        """拖放只挂在首页视图，工作台视图不受影响。"""
        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        self.assertTrue(window._empty_state.acceptDrops())
        self.assertFalse(window._ide_page.acceptDrops())

    def test_recent_cards_render_click_and_exclude_empty_hint(self):
        """最近项目卡片渲染（名称/时间/路径/类型徽章）与空态互斥；点击走打开回调。"""
        from datetime import datetime, timedelta, timezone

        from PySide6.QtWidgets import QLabel

        from doc_tool.application.project_service import RecentEntry

        opened = []
        home = self._home(on_open_recent=opened.append)
        home.set_recent_projects([])
        self.assertIsNotNone(home._empty_label)
        self.assertEqual(home._recent_cards, [])

        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "proj-a"
            root_a.mkdir()
            root_b = Path(tmp) / "proj-b"
            root_b.mkdir()
            now = datetime.now(timezone.utc)
            entries = [
                RecentEntry(
                    path=str(root_a), name="proj-a",
                    document_name="需求说明书（示例）",
                    document_type="requirement",
                    last_opened=(now - timedelta(days=3, minutes=5)).isoformat(timespec="seconds"),
                ),
                RecentEntry(path=str(root_b), name="proj-b"),
            ]
            home.set_recent_projects(entries)
            self.assertEqual(len(home._recent_cards), 2)
            self.assertIsNone(home._empty_label)  # 卡片与空态互斥
            texts_a = [c.text() for c in home._recent_cards[0].findChildren(QLabel)]
            self.assertIn("需求说明书（示例）", texts_a)
            self.assertTrue(any("3 天前打开" in t and str(root_a) in t for t in texts_a))
            self.assertIn("需求", texts_a)  # 类型徽章
            self.assertIn("打开 →", texts_a)
            # 第二张：无类型无时间戳（旧数据兼容）→ 无徽章、只显示路径
            texts_b = [c.text() for c in home._recent_cards[1].findChildren(QLabel)]
            self.assertIn(str(root_b), texts_b)
            self.assertNotIn("需求", texts_b)
            # 点击卡片走现有打开项目链路
            self._click(home._recent_cards[0])
            self.assertEqual(opened, [str(root_a)])
            # 回到空态：卡片清理
            home.set_recent_projects([])
            self.assertEqual(home._recent_cards, [])
            self.assertIsNotNone(home._empty_label)

    def test_last_opened_formatting(self):
        from datetime import datetime, timedelta, timezone

        from doc_tool.ui.empty_state import _format_last_opened

        now = datetime.now(timezone.utc)
        self.assertEqual(_format_last_opened(""), "")
        self.assertEqual(_format_last_opened("not-a-date"), "")
        self.assertEqual(
            _format_last_opened(now.isoformat(timespec="seconds")), "今天打开"
        )
        self.assertEqual(
            _format_last_opened(
                (now - timedelta(days=1, minutes=5)).isoformat(timespec="seconds")
            ),
            "昨天打开",
        )
        self.assertEqual(
            _format_last_opened(
                (now - timedelta(days=3, minutes=5)).isoformat(timespec="seconds")
            ),
            "3 天前打开",
        )

    def test_home_builds_under_light_and_dark_themes(self):
        """浅/深两套主题下构建并切换拖放高亮态均不报错。"""
        from doc_tool.ui.styles import apply_theme

        app = _ensure_qapp()
        for dark in (False, True):
            apply_theme(app, dark=dark)
            home = self._home(on_convert=lambda: None)
            home.resize(1120, 720)
            home.show()
            app.processEvents()
            self.assertEqual(home._convert_title.text(), "文档互转")
            home.set_drag_over(True)
            app.processEvents()
            self.assertEqual(home._convert_card.property("dragOver"), "true")
            home.set_drag_over(False)
            home.close()
        apply_theme(app, dark=False)

    def test_help_and_about_links_wire_main_window_entries(self):
        """底部「使用说明」「关于」分别接帮助文档打开与关于对话框，不新造对话框。"""
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        home = window._empty_state
        # 「关于」：打桩 show_about_dialog（回调构造时绑定，替换实例属性无效）。
        with patch("doc_tool.ui.about_dialog.show_about_dialog") as show_about:
            home._handle_about()
        self.assertEqual(show_about.call_count, 1)
        self.assertIs(show_about.call_args.args[0], window)
        # 「使用说明」：解析到仓库 docs/使用说明.md 并交给系统关联程序打开。
        with patch.object(MainWindow, "_open_file", return_value=True) as open_file:
            home._handle_show_help()
            self.assertEqual(open_file.call_count, 1)

class EditorWorkbenchPhase2Tests(unittest.TestCase):
    """主构建区 UI 优化、多标签页右键/快捷关闭、语法弱化与专注模式。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_tabs_host_context_menu_and_batch_close(self):
        """测试多标签页批量关闭与导航。"""
        import tempfile
        import shutil
        from pathlib import Path
        from doc_tool.ui.content.tabs_host import TabsHost

        root = Path(tempfile.mkdtemp(prefix="doc-tool-tabshost-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        writer = _FakeWriter(root)
        host = TabsHost(writer, writable=True)
        self.addCleanup(host.close)

        host.open_file("doc1.md", "# 1")
        host.open_file("doc2.md", "# 2")
        host.open_file("doc3.md", "# 3")
        self.assertEqual(host._tabs.count(), 3)

        # 验证切换
        host._tabs.setCurrentIndex(0)
        host.next_tab()
        self.assertEqual(host._tabs.currentIndex(), 1)
        host.prev_tab()
        self.assertEqual(host._tabs.currentIndex(), 0)

        # 关闭右侧标签页（从索引 1 开始，只剩 doc1 和 doc2）
        host.close_right_tabs(1)
        self.assertEqual(host._tabs.count(), 2)

        # 关闭其他标签页（当前选中 0，只保留 doc1）
        host.close_other_tabs(0)
        self.assertEqual(host._tabs.count(), 1)
        self.assertEqual(host.current_rel_path(), "doc1.md")

        # 关闭全部
        host.close_all_user_tabs()
        self.assertEqual(host._tabs.count(), 0)

    def test_markdown_highlighter_comments_and_empty_par(self):
        """测试 HTML 注释与 <EMPTY_PAR/> 的浅灰弱化高亮。"""
        from PySide6.QtWidgets import QPlainTextEdit
        from doc_tool.ui.content.editor_highlight import MarkdownHighlighter

        edit = QPlainTextEdit()
        hl = MarkdownHighlighter(edit.document())
        fmt = hl._comment_fmt()
        self.assertTrue(fmt.fontItalic())
        self.assertEqual(fmt.foreground().color().name().lower(), "#94a3b8")

        # 多行注释状态机转换
        edit.setPlainText("<!-- TBL:style=43\nlay=autofit -->\n正文\n<EMPTY_PAR/>\n")
        block1 = edit.document().findBlockByNumber(0)
        self.assertEqual(block1.userState(), MarkdownHighlighter.STATE_IN_COMMENT)
        block2 = edit.document().findBlockByNumber(1)
        self.assertEqual(block2.userState(), MarkdownHighlighter.STATE_NORMAL)
        edit.close()

    def test_preview_heading_links_not_blue(self):
        """测试预览区域中的标题锚点链接使用继承色而非默认蓝色。"""
        from doc_tool.application.content.preview import render_markdown_html

        html_light = render_markdown_html("# 一级标题\n## 二级标题\n", dark=False)
        self.assertIn("h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {", html_light)
        self.assertIn("color: inherit;", html_light)

        html_dark = render_markdown_html("# 一级标题\n", dark=True)
        self.assertIn("color: inherit;", html_dark)

    def test_main_window_zen_mode_toggle(self):
        """测试 F11 专注模式显隐外围 Dock 与项目条。"""
        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        self.assertFalse(window._zen_mode)
        self.assertFalse(window._zen_mode_action.isChecked())

        # 触发进入专注模式
        window.toggle_zen_mode()
        self.assertTrue(window._zen_mode)
        self.assertTrue(window._zen_mode_action.isChecked())
        self.assertIn("退出专注", window._zen_mode_action.text())
        self.assertTrue(window._task_dock_widget.isHidden())
        self.assertTrue(window._project_bar.isHidden())

        # 再次触发退出专注模式
        window.toggle_zen_mode()
        self.assertFalse(window._zen_mode)
        self.assertFalse(window._zen_mode_action.isChecked())

    def test_mermaid_dialog_zoom_controls(self):
        """测试 Mermaid 图形工作台缩放控制：放大、缩小、适应与 1:1 重置。"""
        from doc_tool.ui.content.mermaid_dialog import MermaidDialog

        dlg = MermaidDialog("flowchart TD\n  A --> B")
        dlg.refresh_preview()
        self.assertIsNotNone(dlg._current_pixmap)
        self.assertTrue(dlg._fit_mode)

        # 放大
        dlg._zoom_in()
        self.assertFalse(dlg._fit_mode)
        self.assertGreater(dlg._zoom_factor, 1.0)
        self.assertIn("%", dlg.zoom_label.text())

        # 缩小
        dlg._zoom_out()
        self.assertLess(dlg._zoom_factor, 1.26)

        # 重置 1:1
        dlg._reset_zoom()
        self.assertAlmostEqual(dlg._zoom_factor, 1.0)
        self.assertEqual(dlg.zoom_label.text(), "100%")

        # 适应窗口
        dlg._fit_to_window()
        self.assertTrue(dlg._fit_mode)
        dlg.close()

    def test_result_card_extended_action_callbacks(self):
        """测试构建终态卡片支持定位文件、复制路径与另存为。"""
        from doc_tool.ui.work_detail_pane import ResultCard
        from doc_tool.ui.workbench_state import ResultState

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output.docx"
            output.write_bytes(b"docx")

            located = []
            copied = []
            exported = []

            card = ResultCard(
                on_locate_file=located.append,
                on_copy_path=copied.append,
                on_export_to=exported.append,
            )
            card.render(ResultState(status="success", output_path=output))

            # 校验按钮绑定
            btn_texts = [btn.text() for btn in card._action_buttons]
            self.assertIn("定位文件", btn_texts)
            self.assertIn("复制路径", btn_texts)
            self.assertIn("另存为…", btn_texts)

            locate_btn = next(b for b in card._action_buttons if b.text() == "定位文件")
            locate_btn.click()
            self.assertEqual(located, [str(output)])

            copy_btn = next(b for b in card._action_buttons if b.text() == "复制路径")
            copy_btn.click()
            self.assertEqual(copied, [str(output)])

            export_btn = next(b for b in card._action_buttons if b.text() == "另存为…")
            export_btn.click()
            self.assertEqual(exported, [str(output)])

    def test_line_numbered_edit_replace_text_range(self):
        """测试编辑器支持范围文本替换（如标题快速修复）。"""
        from doc_tool.ui.content.editor_highlight import _LineNumberedEdit

        edit = _LineNumberedEdit()
        edit.setPlainText("#1.1 标题\n第二行")
        # 替换第 0 到 4 字符为 '# 1.1'
        edit._replace_text_range(0, 4, "# 1.1")
        self.assertEqual(edit.toPlainText(), "# 1.1 标题\n第二行")

    def test_lint_panel_initialization_and_quick_fix(self):
        """测试 LintPanel 初始化无 _on_activate 缺失异常，并可执行一键修复。"""
        from doc_tool.application.content.lint import ContentLinter, TermStore, LintIssue
        from doc_tool.application.content.quality_rules import QualityRulesConfig
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.domain.content_index import ContentIndex, FileEntry
        from doc_tool.ui.content.lint_panel import LintPanel, LintTreeItem

        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            content_dir = tmp_p / "content"
            content_dir.mkdir(parents=True)
            state_dir = tmp_p / ".state"
            state_dir.mkdir(parents=True)

            md_file = content_dir / "1.1_test.md"
            md_file.write_text("#1.1 标题\n正文", encoding="utf-8")

            index = ContentIndex()
            index.lines["1.1_test.md"] = ["#1.1 标题", "正文"]
            index.files["1.1_test.md"] = FileEntry("1.1_test.md", "general", 2)

            writer = ContentWriter(content_dir, state_dir)
            terms = TermStore(state_dir)
            linter = ContentLinter(index, QualityRulesConfig(state_dir, "general"))

            opened = []
            applied = []
            panel = LintPanel(
                linter,
                terms,
                on_open=lambda rel, line: opened.append((rel, line)),
                writable=True,
                writer=writer,
                on_applied=lambda: applied.append(True),
            )
            # 验证 _on_activate 存在且可正常调用
            self.assertTrue(hasattr(panel, "_on_activate"))
            item = LintTreeItem(["1.1_test.md", "1", "标题格式", "警告", "测试说明"])
            panel._on_activate(item)
            self.assertEqual(opened, [("1.1_test.md", 1)])

            # 验证一键修复
            issue = LintIssue("heading_format", "1.1_test.md", 1, "标题 '#' 后面必须有空格：'#1.1 标题'", "heading_format")
            panel._issues = [issue]
            ok = panel.quick_fix_issue(issue)
            self.assertTrue(ok)
            fixed_text = md_file.read_text(encoding="utf-8")
            self.assertIn("# 1.1 标题", fixed_text)
            self.assertTrue(len(applied) > 0)

            # 验证 quick_fix_all_in_file
            md_file.write_text("#1.1 标题\n##1.1.1 子标题", encoding="utf-8")
            i1 = LintIssue("heading_format", "1.1_test.md", 1, "标题 '#' 后面必须有空格：'#1.1 标题'", "heading_format")
            i2 = LintIssue("heading_format", "1.1_test.md", 2, "标题 '#' 后面必须有空格：'##1.1.1 子标题'", "heading_format")
            panel._issues = [i1, i2]
            c_file = panel.quick_fix_all_in_file("1.1_test.md")
            self.assertEqual(c_file, 2)
            fixed_all = md_file.read_text(encoding="utf-8")
            self.assertEqual(fixed_all, "# 1.1 标题\n## 1.1.1 子标题")

            # 验证 quick_fix_all_in_project 跨文件批量修复
            md_file2 = content_dir / "2.1_test.md"
            md_file2.write_text("#2.1 第二章", encoding="utf-8")
            md_file.write_text("#1.1 第一章", encoding="utf-8")
            ip1 = LintIssue("heading_format", "1.1_test.md", 1, "标题 '#' 后面必须有空格：'#1.1 第一章'", "heading_format")
            ip2 = LintIssue("heading_format", "2.1_test.md", 1, "标题 '#' 后面必须有空格：'#2.1 第二章'", "heading_format")
            panel._issues = [ip1, ip2]
            c_proj = panel.quick_fix_all_in_project()
            self.assertEqual(c_proj, 2)
            self.assertEqual(md_file.read_text(encoding="utf-8"), "# 1.1 第一章")
            self.assertEqual(md_file2.read_text(encoding="utf-8"), "# 2.1 第二章")

            # 验证 TreeItem 在 sortColumn 为 -1 时不报错
            self.assertTrue(item < LintTreeItem(["2.1_test.md", "2", "说明", "警告", "说明"]))

    def test_main_window_locate_file_windows_command(self):
        """测试 MainWindow._locate_file 在 Windows 环境下构建正确的 explorer.exe /select 命令行。"""
        import unittest.mock
        from doc_tool.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "has space" / "test doc.docx"
            test_file.parent.mkdir(parents=True)
            test_file.write_bytes(b"docx")

            commands = []
            with unittest.mock.patch("subprocess.Popen", side_effect=lambda cmd: commands.append(cmd)):
                with unittest.mock.patch("os.name", "nt"):
                    window = MainWindow()
                    window._locate_file(str(test_file))
                    window.close()

            self.assertEqual(len(commands), 1)
            cmd_str = commands[0]
            # 必须为完整字符串且 /select,"path" 格式，双引号不能包裹 /select 开关
            self.assertIsInstance(cmd_str, str)
            self.assertTrue(cmd_str.startswith('explorer.exe /select,"'))
            self.assertTrue(cmd_str.endswith('"'))
            self.assertIn(str(test_file.resolve()), cmd_str)




class WizardUXOptimizationTests(unittest.TestCase):
    """测试新建项目向导 UI/UX 优化特性的逻辑行为。"""

    def setUp(self):
        _ensure_qapp()

    def _wizard(self):
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard()
        self.addCleanup(wizard.close)
        return wizard

    def test_smart_skip_next_id_with_heading1(self):
        """当预检已自动识别标准 Heading 1 且无阻断时，步骤 1 直接跳步至步骤 4（项目信息）。"""
        from types import SimpleNamespace
        wizard = self._wizard()
        wizard._preview = SimpleNamespace(
            has_heading1=True,
            fidelity=SimpleNamespace(has_block=False),
        )
        wizard._source_page._wants_tuning = False
        self.assertEqual(wizard.nextId(), 3, "标准文档应自动跳过日志与样式映射，直达步骤 4")

        wizard._source_page._wants_tuning = True
        self.assertEqual(wizard.nextId(), 2, "用户勾选微调时应进入样式映射页")

    def test_smart_skip_next_id_without_heading1(self):
        """当预检未检测到 Heading 1 时，步骤 1 引导至样式映射或预检页。"""
        from types import SimpleNamespace
        wizard = self._wizard()
        wizard._preview = SimpleNamespace(
            has_heading1=False,
            fidelity=SimpleNamespace(has_block=False),
        )
        self.assertEqual(wizard.nextId(), 1)

    def test_smart_skip_next_id_from_preflight_page(self):
        """从预检页（Page 1）若大纲良好，nextId 跳过映射页直达项目信息页（Page 3）。"""
        from types import SimpleNamespace
        wizard = self._wizard()
        wizard._preview = SimpleNamespace(
            has_heading1=True,
            fidelity=SimpleNamespace(has_block=False),
        )
        wizard.setStartId(1)
        wizard.restart()
        self.assertEqual(wizard.nextId(), 3)

    def test_reversible_error_handling_back_button(self):
        """导入失败时允许点击「上一步」返回重试，成功时禁用上一步。"""
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWizard
        wizard = self._wizard()
        result_page = wizard._result_page

        wizard._import_result = SimpleNamespace(success=True, events=[], source_sha256="abcdef123456")
        wizard._target_root = "C:/fake/proj"
        wizard.setStartId(5)
        wizard.restart()
        back_btn = wizard.button(QWizard.WizardButton.BackButton)
        next_btn = wizard.button(QWizard.WizardButton.NextButton)
        self.assertFalse(back_btn.isEnabled(), "导入成功时不应允许返回")
        self.assertEqual(next_btn.text(), "进入工作台")

        wizard._import_result = SimpleNamespace(
            success=False,
            error_code="E1005",
            events=[],
            diagnostic_log="",
        )
        result_page.initializePage()
        wizard._on_page_changed(5)
        self.assertTrue(back_btn.isEnabled(), "导入失败时必须允许点击上一步返回重试")
        self.assertEqual(next_btn.text(), "关闭")

    def test_style_mapping_sample_text_and_smooth_degrade(self):
        """样式映射表回显正文样例首句，并支持跨级跳跃自动平滑降级。"""
        from types import SimpleNamespace
        from doc_tool.adapters.preflight import StyleCensus
        wizard = self._wizard()
        page = wizard._mapping_page

        census = {
            "Custom1": StyleCensus("Custom1", "我的章标题", 5, True, sample_text="第1章 总体概述与背景"),
            "Custom2": StyleCensus("Custom2", "我的三级节", 3, True, sample_text="1.1.1 关键性能指标"),
        }
        preview = SimpleNamespace(style_census=census, heading_style_map={})
        page._populate(preview)

        self.assertEqual(page._table.item(0, 2).text(), "第1章 总体概述与背景")
        self.assertEqual(page._table.item(1, 2).text(), "1.1.1 关键性能指标")

        c1 = next(r["combo"] for r in page._rows if r["style_id"] == "Custom1")
        c2 = next(r["combo"] for r in page._rows if r["style_id"] == "Custom2")
        c1.setCurrentIndex(c1.findData(1))
        c2.setCurrentIndex(c2.findData(3))
        self.assertEqual(page.mapping(), {"Custom1": 1, "Custom2": 3})

        page._auto_smooth_degrade()
        self.assertEqual(page.mapping(), {"Custom1": 1, "Custom2": 2}, "自动平滑降级应把跳跃的级别 3 降为连续的级别 2")

    def test_project_info_smart_default_and_conflict_check(self):
        """项目信息页智能填充默认路径，并实时检测重名冲突提供一键后缀。"""
        import tempfile
        wizard = self._wizard()
        page = wizard._info_page

        with tempfile.TemporaryDirectory() as td:
            existing_dir = Path(td) / "my_project"
            existing_dir.mkdir()

            wizard._target_parent = td
            wizard._project_name = "my_project"
            wizard._doc_name = "我的测试项目"
            page.initializePage()

            self.assertFalse(page._conflict_label.isHidden(), "检测到重名目录应显示警告标签")
            self.assertFalse(page._suffix_btn.isHidden(), "重名时应显示后缀建议按钮")
            self.assertIn("v2", page._suffix_btn.text(), "重名建议按钮应包含递增后缀 (v2)")

            page._apply_suggested_name()
            self.assertEqual(page._project_name_entry.text(), "my_project-v2")
            self.assertTrue(page._conflict_label.isHidden(), "应用无冲突名称后应隐藏警告标签")

    def test_executing_stepper_progress(self):
        """流水线 Stepper 接收到阶段事件后正确推进高亮状态。"""
        from types import SimpleNamespace
        wizard = self._wizard()
        page = wizard._executing_page

        page._reset_stepper()
        self.assertIn("○", page._step_labels["validate"].text())

        page.on_stage_event(SimpleNamespace(stage="extract_content", status="started", detail="正在提取正文段落与图片"))
        self.assertIn("✓", page._step_labels["validate"].text())
        self.assertIn("✓", page._step_labels["template"].text())
        self.assertIn("⟳", page._step_labels["content"].text())
        self.assertIn("○", page._step_labels["split"].text())
        self.assertEqual(page._detail_label.text(), "正在提取正文段落与图片")


    def test_drop_zone_drag_drop_and_click_events(self):
        """拖放区 DropZone 正常响应 dragEnter, dragLeave, drop 以及点击信号。"""
        from PySide6.QtCore import QPoint, Qt, QUrl, QMimeData
        from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
        from doc_tool.ui.wizard import _DropZone

        zone = _DropZone()
        clicked_events = []
        dropped_paths = []
        zone.clicked.connect(lambda: clicked_events.append(True))
        zone.file_dropped.connect(lambda p: dropped_paths.append(p))

        from PySide6.QtTest import QTest
        QTest.mouseClick(zone, Qt.MouseButton.LeftButton)
        self.assertEqual(len(clicked_events), 1)

        mime_txt = QMimeData()
        mime_txt.setUrls([QUrl.fromLocalFile("test.txt")])
        enter_ev_txt = QDragEnterEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime_txt,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        zone.dragEnterEvent(enter_ev_txt)
        self.assertFalse(enter_ev_txt.isAccepted())

        mime_docx = QMimeData()
        mime_docx.setUrls([QUrl.fromLocalFile("C:/fake/sample.docx")])
        enter_ev = QDragEnterEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime_docx,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        zone.dragEnterEvent(enter_ev)
        self.assertTrue(enter_ev.isAccepted())

        leave_ev = QDragLeaveEvent()
        zone.dragLeaveEvent(leave_ev)

        drop_ev = QDropEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime_docx,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        zone.dropEvent(drop_ev)
        self.assertEqual(len(dropped_paths), 1)
        self.assertIn("sample.docx", dropped_paths[0])

    def test_back_navigation_from_failed_result_skips_executing_page(self):
        """导入失败后在结果页点击「上一步」回退，跳过正在执行页（Page 4），直接安全回退至项目信息页（Page 3），且保留输入数据。"""
        from types import SimpleNamespace
        wizard = self._wizard()
        wizard._source_page._source_path = "C:/fake/sample.docx"
        wizard._preview = SimpleNamespace(has_heading1=True, fidelity=SimpleNamespace(has_block=False))
        wizard.restart()
        self.assertEqual(wizard.currentId(), 0)

        wizard.next()
        self.assertEqual(wizard.currentId(), 3)
        wizard._info_page._doc_name_entry.setText("原始文档名称")
        wizard._info_page._project_name_entry.setText("my_target_project")
        wizard._info_page._target_entry.setText("C:/my_projects")

        done_callbacks = []
        wizard._do_import = lambda on_done: done_callbacks.append(on_done)
        wizard.next()
        self.assertEqual(wizard.currentId(), 4)

        done_callbacks[0](
            SimpleNamespace(success=False, error_code="E1005", events=[], diagnostic_log="Target directory permission error"),
            "C:/my_projects/my_target_project",
        )
        self.assertEqual(wizard.currentId(), 5, "导入完成后应进入结果看板页")

        wizard.back()
        self.assertEqual(wizard.currentId(), 3, "必须直接回退到项目配置页（Page 3），避免卡死在执行页或重复失败")
        self.assertEqual(wizard._info_page._doc_name_entry.text(), "原始文档名称")
        self.assertEqual(wizard._info_page._project_name_entry.text(), "my_target_project")
        self.assertEqual(wizard._info_page._target_entry.text(), "C:/my_projects")

        wizard._info_page._project_name_entry.setText("my_target_project_retry")
        wizard.next()
        self.assertEqual(wizard.currentId(), 4)
        done_callbacks[1](
            SimpleNamespace(success=True, events=[], source_sha256="abcdef012345"),
            "C:/my_projects/my_target_project_retry",
        )
        self.assertEqual(wizard.currentId(), 5)
        self.assertTrue(wizard._import_result.success)

    def test_finish_button_text_synchronization(self):
        """结果页中 FinishButton 和 NextButton 的文本保持同步（成功时为「进入工作台」，失败时为「关闭」）。"""
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWizard
        wizard = self._wizard()

        wizard._import_result = SimpleNamespace(success=True, events=[], source_sha256="1234567890ab")
        wizard._target_root = "C:/fake/proj"
        wizard.setStartId(5)
        wizard.restart()

        next_btn = wizard.button(QWizard.WizardButton.NextButton)
        finish_btn = wizard.button(QWizard.WizardButton.FinishButton)
        self.assertEqual(next_btn.text(), "进入工作台")
        self.assertEqual(finish_btn.text(), "进入工作台")

        wizard._import_result = SimpleNamespace(success=False, error_code="E5003", events=[], diagnostic_log="")
        wizard._result_page.initializePage()
        wizard._on_page_changed(5)
        self.assertEqual(next_btn.text(), "关闭")
        self.assertEqual(finish_btn.text(), "关闭")

    def test_outline_tree_live_update_and_error_degrade(self):
        """右侧大纲树根据映射实时刷新，遇到跳级展示降级按钮，点击后自动修复。"""
        from types import SimpleNamespace
        from doc_tool.adapters.preflight import StyleCensus
        from unittest.mock import patch
        import tempfile
        wizard = self._wizard()
        page = wizard._mapping_page

        census = {
            "S1": StyleCensus("S1", "章样式", 3, True, sample_text="第1章"),
            "S2": StyleCensus("S2", "节样式", 2, True, sample_text="1.1 节"),
        }
        preview = SimpleNamespace(style_census=census, heading_style_map={})
        page._populate(preview)

        c1 = next(r["combo"] for r in page._rows if r["style_id"] == "S1")
        c2 = next(r["combo"] for r in page._rows if r["style_id"] == "S2")
        c1.setCurrentIndex(c1.findData(1))
        c2.setCurrentIndex(c2.findData(3))

        with tempfile.NamedTemporaryFile(suffix=".docx") as tmp_file:
            wizard._source_page._source_path = tmp_file.name
            with patch("doc_tool.adapters.preflight.generate_preview_heading_tree") as mock_tree:
                mock_tree.return_value = ([], "标题层级跳跃：从级别 1 直接跳至级别 3")
                page._update_outline_tree()
                self.assertFalse(page._degrade_btn.isHidden(), "检测到层级跳跃错误时应显示自动平滑降级按钮")
                self.assertIn("跳跃", page._tree_status.text())

                mock_tree.return_value = ([SimpleNamespace(level=1, text="第一章"), SimpleNamespace(level=2, text="第一节")], "")
                page._degrade_btn.click()
                self.assertTrue(page._degrade_btn.isHidden(), "平滑降级修复后降级按钮应自动隐藏")
                self.assertIn("完整无跳跃", page._tree_status.text())
                self.assertEqual(page._tree.topLevelItemCount(), 1)


    def test_drop_zone_drag_move_event_accepted(self):
        """DropZone 正确响应 dragMoveEvent，使得 Windows 资源管理器拖拽悬停时不被判定为非法区域。"""
        from PySide6.QtCore import QPoint, Qt, QUrl, QMimeData
        from PySide6.QtGui import QDragMoveEvent
        from doc_tool.ui.wizard import _DropZone

        zone = _DropZone()
        mime_docx = QMimeData()
        mime_docx.setUrls([QUrl.fromLocalFile("C:/fake/sample.docx")])
        move_ev = QDragMoveEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime_docx,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        zone.dragMoveEvent(move_ev)
        self.assertTrue(move_ev.isAccepted(), "docx 文件悬停时必须接受 dragMove 以便 Windows OLE 正确放行 drop")

    def test_source_page_resets_stale_mapping_and_updates_names_on_switch(self):
        """更换源文件时，重置上一文件的样式映射残留，并同步更新文档名称与项目目录名。"""
        import tempfile
        wizard = self._wizard()
        source_page = wizard._source_page
        mapping_page = wizard._mapping_page

        mapping_page._rows = [{"style_id": "OldStyle", "combo": None}]
        wizard._heading_style_map = {"OldStyle": 1}

        with tempfile.NamedTemporaryFile(suffix=".docx", prefix="new_design_doc_") as f:
            source_page._on_file_selected(f.name)
            self.assertEqual(mapping_page._rows, [], "更换文件必须清空旧样式映射行")
            self.assertIsNone(wizard._heading_style_map, "更换文件必须重置 heading_style_map")
            self.assertIn("new_design_doc", wizard._doc_name, "更换文件后文档名称必须同步更新")
            self.assertIn("new_design_doc", wizard._project_name, "更换文件后项目目录名必须同步更新")

    def test_silent_preflight_updates_next_button_text_and_runner_gate(self):
        """静默预检运行中 NextButton 禁用防并发碰撞，完成时立即刷新按钮文案为下一步引导。"""
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWizard
        wizard = self._wizard()
        source_page = wizard._source_page

        source_page._source_path = "C:/fake/sample.docx"
        wizard._runner._is_running = True
        self.assertFalse(source_page.isComplete(), "预检执行中禁止点击下一步导致并发任务冲突")

        wizard._runner._is_running = False
        preview = SimpleNamespace(
            has_heading1=True,
            heading_level_counts={1: 3},
            image_count=2,
            table_count=1,
            warnings=[],
            fidelity=SimpleNamespace(has_block=False, findings=[]),
        )
        wizard._on_page_changed(0)
        source_page._on_silent_preflight_done((True, preview, "ok"))
        self.assertTrue(source_page.isComplete())
        next_btn = wizard.button(QWizard.WizardButton.NextButton)
        self.assertEqual(next_btn.text(), "下一步：确认项目信息", "预检完成后 NextButton 文案应即时自适应")

    def test_project_info_conflict_naming_increments_cleanly(self):
        """已存在 my_project 与 my_project-v2 时，递增建议为 my_project-v3 而非层叠 -v2-v2。"""
        import tempfile
        wizard = self._wizard()
        page = wizard._info_page

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "demo_proj").mkdir()
            (Path(td) / "demo_proj-v2").mkdir()

            wizard._target_parent = td
            wizard._project_name = "demo_proj"
            wizard._doc_name = "我的演示"
            page.initializePage()

            self.assertFalse(page.isComplete(), "存在冲突目录时禁止提交导入")
            self.assertEqual(page._suggested_safe_name, "demo_proj-v3", "连续递增应为 -v3 而非 -v2-v2")
            page._apply_suggested_name()
            self.assertTrue(page.isComplete(), "更名后应自动恢复为 Complete")
            self.assertEqual(page._project_name_entry.text(), "demo_proj-v3")

    def test_result_page_failure_surfaces_error_reason_directly(self):
        """导入失败卡片上直接呈现具体失败原因，无需非技术用户展开技术诊断折叠框。"""
        from types import SimpleNamespace
        wizard = self._wizard()
        page = wizard._result_page

        failed_event = SimpleNamespace(stage="validate_target", status="failed", detail="目标目录无写入权限", metrics={})
        wizard._import_result = SimpleNamespace(
            success=False,
            error_code="E1005",
            events=[failed_event],
            diagnostic_log="",
        )
        page.initializePage()
        self.assertFalse(page._failure_reason.isHidden())
        self.assertIn("目标目录无写入权限", page._failure_reason.text())

    def test_outline_tree_degrade_btn_appears_on_missing_h1_or_gaps(self):
        """当用户从级别 2 开始映射或跳级时，降级按钮显现并支持一键顺延对齐。"""
        from types import SimpleNamespace
        from doc_tool.adapters.preflight import StyleCensus
        from unittest.mock import patch
        import tempfile
        wizard = self._wizard()
        page = wizard._mapping_page

        census = {
            "S2": StyleCensus("S2", "二级样式", 2, True),
            "S3": StyleCensus("S3", "三级样式", 2, True),
        }
        page._populate(SimpleNamespace(style_census=census, heading_style_map={}))
        c2 = next(r["combo"] for r in page._rows if r["style_id"] == "S2")
        c3 = next(r["combo"] for r in page._rows if r["style_id"] == "S3")
        c2.setCurrentIndex(c2.findData(2))
        c3.setCurrentIndex(c3.findData(3))

        with tempfile.NamedTemporaryFile(suffix=".docx") as tmp:
            wizard._source_page._source_path = tmp.name
            with patch("doc_tool.adapters.preflight.generate_preview_heading_tree") as mock_tree:
                mock_tree.return_value = ([], "未包含级别 1（章标题）")
                page._update_outline_tree()
                self.assertFalse(page._degrade_btn.isHidden(), "映射缺少级别 1 时也应展现平滑降级按钮协助修正")

                mock_tree.return_value = ([SimpleNamespace(level=1, text="新章"), SimpleNamespace(level=2, text="新节")], "")
                page._degrade_btn.click()
                self.assertEqual(page.mapping(), {"S2": 1, "S3": 2}, "平滑降级后 2/3 应顺延降为 1/2")

    def test_generate_preview_heading_tree_reports_first_heading_not_h1(self):
        """当文档第一个标题不是 H1 时，准确回显错误信息而非误报未被使用。"""
        from doc_tool.adapters.preflight import generate_preview_heading_tree
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch("doc_tool.adapters.preflight._build_heading_tree") as mock_build:
            mock_build.return_value = [
                SimpleNamespace(level=2, text="引言"),
                SimpleNamespace(level=1, text="第一章"),
            ]
            headings, error = generate_preview_heading_tree({}, {"S": 1, "S2": 2})
            self.assertIn("第一个标题不是", error)


    def test_custom_generation_dir_checkbox_default_state_and_collapse(self):
        """测试'自定义生成目录'选项默认未勾选，路径输入框折叠，且清晰展示默认推荐路径提示。"""
        wizard = self._wizard()
        source_page = wizard._source_page
        info_page = wizard._info_page

        # 1. 步骤 1 (SourcePage) 默认未勾选，目录输入控件折叠隐藏，显示默认路径友好提示
        self.assertTrue(hasattr(source_page, "_custom_dir_check"))
        self.assertEqual(source_page._custom_dir_check.text(), "自定义生成目录")
        self.assertFalse(source_page._custom_dir_check.isChecked(), "默认状态必须未勾选")
        self.assertTrue(source_page._custom_dir_container.isHidden(), "未勾选时目录输入框和浏览按钮应折叠隐藏")
        self.assertFalse(source_page._default_path_label.isHidden(), "未勾选时应清晰展示默认生成目录提示")
        self.assertIn("系统推荐默认路径", source_page._default_path_label.text())

        # 2. 步骤 4 (ProjectInfoPage) 默认未勾选，目录输入控件折叠隐藏，显示默认路径友好提示
        info_page.initializePage()
        self.assertTrue(hasattr(info_page, "_custom_dir_check"))
        self.assertEqual(info_page._custom_dir_check.text(), "自定义生成目录")
        self.assertFalse(info_page._custom_dir_check.isChecked(), "默认状态必须未勾选")
        self.assertTrue(info_page._custom_dir_container.isHidden(), "未勾选时存放位置输入行应折叠隐藏")
        self.assertFalse(info_page._default_path_label.isHidden(), "未勾选时应清晰展示默认路径提示")
        self.assertIn("系统推荐默认路径", info_page._default_path_label.text())
        self.assertTrue(len(info_page._target_entry.text().strip()) > 0, "应智能填充默认推荐存放父目录")

    def test_custom_generation_dir_expand_and_revert_on_info_page(self):
        """测试在项目信息页勾选自定义目录展开输入框与浏览按钮，取消勾选时自动恢复默认路径并折叠。"""
        import tempfile
        wizard = self._wizard()
        info_page = wizard._info_page

        with tempfile.TemporaryDirectory() as td:
            wizard._target_parent = td
            wizard._project_name = "my_project"
            wizard._doc_name = "测试项目"
            info_page.initializePage()
            default_path = info_page._target_entry.text().strip()
            self.assertEqual(default_path, td)

            # 勾选展开
            info_page._custom_dir_check.setChecked(True)
            self.assertTrue(info_page._custom_dir_check.isChecked())
            self.assertFalse(info_page._custom_dir_container.isHidden(), "勾选后应展开目标目录输入框与浏览按钮")
            self.assertTrue(info_page._default_path_label.isHidden(), "展开自定义输入后应隐藏默认路径静态提示")

            # 修改为自定义路径
            custom_path = str(Path(td) / "custom_subfolder")
            info_page._target_entry.setText(custom_path)
            self.assertEqual(wizard._target_parent, custom_path)
            self.assertIn(custom_path, info_page._path_preview_label.text())

            # 取消勾选（没有自定义就默认）
            info_page._custom_dir_check.setChecked(False)
            self.assertTrue(info_page._custom_dir_container.isHidden(), "取消勾选后应重新折叠目录输入框")
            self.assertFalse(info_page._default_path_label.isHidden(), "取消勾选后应重新展示默认路径提示")
            self.assertEqual(info_page._target_entry.text().strip(), default_path, "取消勾选后应自动恢复默认生成路径")
            self.assertEqual(wizard._target_parent, default_path)

    def test_custom_generation_dir_sync_from_source_page_to_info_page(self):
        """测试在步骤1源页面自定义生成目录后，无缝同步至步骤4项目信息页。"""
        wizard = self._wizard()
        source_page = wizard._source_page
        info_page = wizard._info_page

        # 在步骤1勾选自定义生成目录并配置路径
        source_page._custom_dir_check.setChecked(True)
        self.assertFalse(source_page._custom_dir_container.isHidden())
        self.assertTrue(source_page._default_path_label.isHidden())

        custom_dest = "D:/my_custom_project_dir"
        source_page._target_entry.setText(custom_dest)
        self.assertEqual(wizard._target_parent, custom_dest)

        # 切换或初始化步骤 4
        info_page.initializePage()
        self.assertTrue(info_page._custom_dir_check.isChecked(), "步骤4应自动同步勾选状态")
        self.assertFalse(info_page._custom_dir_container.isHidden(), "步骤4应保持展开状态")
        self.assertEqual(info_page._target_entry.text(), custom_dest, "步骤4应保持步骤1选择的自定义目录")

    def test_custom_generation_dir_bidirectional_sync_and_uncheck_revert(self):
        """测试双向实时同步与在任一页面取消勾选均能正确恢复真实默认路径。"""
        wizard = self._wizard()
        source_page = wizard._source_page
        info_page = wizard._info_page
        real_default = wizard._get_default_target_parent()

        # 1. 步骤1勾选并自定义路径
        source_page._custom_dir_check.setChecked(True)
        source_page._target_entry.setText("D:/first_custom")
        self.assertEqual(wizard._target_parent, "D:/first_custom")

        # 2. 进入步骤4，验证默认路径未被自定义路径覆盖破坏
        info_page.initializePage()
        self.assertEqual(wizard._default_target_parent, real_default, "默认目录属性必须保持为系统真实默认目录")
        self.assertTrue(info_page._custom_dir_check.isChecked())
        self.assertEqual(info_page._target_entry.text(), "D:/first_custom")

        # 3. 在步骤4取消勾选（没有自定义就默认），必须恢复到真实默认路径，而不是恢复到自定义路径
        info_page._custom_dir_check.setChecked(False)
        self.assertFalse(info_page._custom_dir_check.isChecked())
        self.assertTrue(info_page._custom_dir_container.isHidden())
        self.assertEqual(info_page._target_entry.text().strip(), real_default, "取消勾选必须恢复为系统推荐默认目录")
        self.assertEqual(wizard._target_parent, real_default)

        # 同步回步骤1验证
        self.assertFalse(source_page._custom_dir_check.isChecked(), "步骤1勾选状态应随之重置为未勾选")
        self.assertTrue(source_page._custom_dir_container.isHidden(), "步骤1输入框应重新折叠")
        self.assertEqual(source_page._target_entry.text().strip(), real_default, "步骤1路径应恢复为真实默认目录")
        self.assertIn(real_default, source_page._default_path_label.text())

        # 4. 在步骤4重新自定义并修改路径，双向同步到步骤1
        info_page._custom_dir_check.setChecked(True)
        info_page._target_entry.setText("E:/second_custom")
        self.assertTrue(source_page._custom_dir_check.isChecked())
        self.assertEqual(source_page._target_entry.text(), "E:/second_custom")

        # 5. 在步骤1取消勾选，步骤4亦同步恢复默认并折叠
        source_page._custom_dir_check.setChecked(False)
        self.assertFalse(info_page._custom_dir_check.isChecked())
        self.assertTrue(info_page._custom_dir_container.isHidden())
        self.assertEqual(info_page._target_entry.text().strip(), real_default)

    def test_custom_generation_dir_backwards_compatibility_attributes(self):
        """向后兼容性验证：确保 _doc_name_entry, _project_name_entry, _target_entry 等旧属性依然存在可用。"""
        from PySide6.QtWidgets import QLineEdit
        wizard = self._wizard()
        info_page = wizard._info_page

        self.assertTrue(hasattr(info_page, "_doc_name_entry"))
        self.assertIsInstance(info_page._doc_name_entry, QLineEdit)
        self.assertTrue(hasattr(info_page, "_project_name_entry"))
        self.assertIsInstance(info_page._project_name_entry, QLineEdit)
        self.assertTrue(hasattr(info_page, "_target_entry"))
        self.assertIsInstance(info_page._target_entry, QLineEdit)

        # 验证属性读写及默认提交流程
        info_page._doc_name_entry.setText("系统架构方案")
        info_page._project_name_entry.setText("arch_project")
        info_page._target_entry.setText("C:/projects")

        self.assertEqual(info_page._doc_name_entry.text(), "系统架构方案")
        self.assertEqual(info_page._project_name_entry.text(), "arch_project")
        self.assertEqual(info_page._target_entry.text(), "C:/projects")

    def test_custom_generation_dir_edge_cases(self):
        """测试多次切换勾选、空路径阻断、特殊路径字符等边界情况。"""
        wizard = self._wizard()
        source_page = wizard._source_page
        info_page = wizard._info_page

        # 1. 连续多次切换勾选状态
        for _ in range(3):
            source_page._custom_dir_check.setChecked(True)
            self.assertFalse(source_page._custom_dir_container.isHidden())
            self.assertTrue(source_page._default_path_label.isHidden())
            source_page._custom_dir_check.setChecked(False)
            self.assertTrue(source_page._custom_dir_container.isHidden())
            self.assertFalse(source_page._default_path_label.isHidden())

        # 2. 步骤 1 勾选自定义目录后清空路径阻断 Next
        source_page._source_path = "sample.docx"
        source_page._custom_dir_check.setChecked(True)
        source_page._target_entry.setText("   ")
        self.assertFalse(source_page.isComplete(), "勾选自定义目录但路径为空时应阻断完成")

        source_page._target_entry.setText("D:/valid_path")
        self.assertTrue(source_page.isComplete(), "填写有效自定义目录后恢复完成")

        source_page._custom_dir_check.setChecked(False)
        self.assertTrue(source_page.isComplete(), "未勾选时自动回落默认路径，允许完成")

        # 3. 步骤 4 勾选自定义目录后清空路径阻断 Next
        info_page.initializePage()
        info_page._doc_name_entry.setText("Doc")
        info_page._project_name_entry.setText("Proj")
        info_page._custom_dir_check.setChecked(True)
        info_page._target_entry.setText("")
        self.assertFalse(info_page.isComplete(), "项目信息页自定义目录为空时应阻断完成")

        # 4. 特殊非法项目名阻断
        info_page._target_entry.setText("D:/valid_path")
        info_page._project_name_entry.setText("invalid:name*")
        self.assertFalse(info_page.isComplete(), "包含非法字符的项目名应阻断完成")

        info_page._project_name_entry.setText("valid_proj")
        self.assertTrue(info_page.isComplete())

if __name__ == "__main__":
    unittest.main()
