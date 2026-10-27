# -*- coding: utf-8 -*-
"""Regression tests for Patrol 5.4: GUI 主工作台交互、信号连接与并发状态机死角巡检."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from doc_tool.ui.project_bar import ProjectBar
from doc_tool.ui.workbench_state import WorkbenchState, ActionState, derive_workbench_state
from doc_tool.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestPatrol54GuiInteractionAndStateMachine:
    def test_project_bar_buttons_and_signals_invocation(self, qapp):
        """测试用例：ProjectBar 全部按钮点击、信号连接与快捷键无未连接槽或参数不匹配。"""
        calls = []

        bar = ProjectBar(
            on_quick_export=lambda: calls.append("quick_export"),
            on_export_settings=lambda: calls.append("export_settings"),
            on_validate=lambda: calls.append("validate"),
            on_diag_build=lambda: calls.append("diag_build"),
            on_merge=lambda: calls.append("merge"),
            on_show_results=lambda: calls.append("results"),
        )

        # 模拟点击主按钮与各级按钮
        bar._quick_export_btn.click()
        assert "quick_export" in calls

        bar._export_settings_btn.click()
        assert "export_settings" in calls

        bar._validate_btn.click()
        assert "validate" in calls

        bar._diag_btn.click()
        assert "diag_build" in calls

        bar._merge_btn.click()
        assert "merge" in calls

        bar._results_btn.click()
        assert "results" in calls

    def test_state_machine_busy_and_recovery(self, qapp):
        """测试用例：导出任务运行中按钮禁用、任务结束后按钮状态恢复，无死锁置灰。"""
        bar = ProjectBar()
        summary = MagicMock()
        summary.manifest.documentName = "状态机测试"
        summary.manifest.documentType = "general"
        summary.manifest.documentVersion = "1.0"
        summary.manifest.documentNo = "STATE-01"
        summary.project_root = Path(".")

        # 1. 正常可用状态
        ready_state = WorkbenchState(
            view="project",
            actions={
                "quick_export": ActionState(enabled=True, reason="导出正式 Word"),
                "validate": ActionState(enabled=True, reason="项目检查"),
            },
        )
        bar.render(summary, ready_state)
        assert bar._quick_export_btn.isEnabled() is True
        assert bar._export_settings_btn.isEnabled() is True

        # 2. 任务运行中状态 (busy)
        running_state = WorkbenchState(
            view="project",
            actions={
                "quick_export": ActionState(enabled=False, reason="任务运行中..."),
                "validate": ActionState(enabled=False, reason="任务运行中..."),
            },
        )
        bar.render(summary, running_state)
        assert bar._quick_export_btn.isEnabled() is False
        assert bar._export_settings_btn.isEnabled() is False

        # 3. 任务结束状态恢复可用
        bar.render(summary, ready_state)
        assert bar._quick_export_btn.isEnabled() is True
        assert bar._export_settings_btn.isEnabled() is True

    def test_main_window_flush_unsaved_on_validate_and_export(self, qapp):
        """测试用例：在执行项目检查与导出前，_flush_unsaved_and_sync_version 准确保存未保存修改。"""
        win = MainWindow()
        try:
            mock_workspace = MagicMock()
            mock_workspace.has_unsaved_changes.return_value = True
            win._workspace = mock_workspace

            summary = MagicMock()
            summary.manifest.documentVersion = "1.0"
            summary.paths.root = Path(".")
            win._project_summary = summary
            win._revision_record_version = MagicMock(return_value="2.0")

            # 调用刷新保存辅助方法
            win._flush_unsaved_and_sync_version()

            # 断言未保存工作区被调用 save_all()，且 manifest documentVersion 被同步为 2.0
            mock_workspace.save_all.assert_called_once()
            assert summary.manifest.documentVersion == "2.0"
        finally:
            win.close()
