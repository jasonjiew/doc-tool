# -*- coding: utf-8 -*-
"""主窗口：PySide6 IDE/Dock 工作台。

结构：
- 菜单栏（文件/操作/内容/工具/帮助）+ 状态栏。
- 顶部项目条：文档身份 + 就绪状态 + 高频入口（正式合并/诊断构建/校验）。
- 左侧 Dock：章节树；中心：多标签编辑器 + 预览；右侧 Dock：任务/结果；
  底部面板：搜索/替换/重命名/检查。
- 视图四态：empty（空状态）/ idle（空闲 IDE）/ running（运行）/ result（结果）。

主窗口不直接执行长操作——所有构建/校验/合并通过 ``TaskRunner`` 在后台执行，
UI 经 QTimer 轮询事件队列。用户可安全取消正在运行的任务。窗口几何/最大化
持久化与任务运行中关闭保护沿用 Tk 版语义。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from doc_tool.domain.version import APP_VERSION, get_build_info
from doc_tool.ui.project_bar import ProjectBar
from doc_tool.ui.empty_state import EmptyState
from doc_tool.ui.task_dock import TaskDock
from doc_tool.ui.task_bridge import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    ERR_WATCHDOG_TIMEOUT,
    POLL_INTERVAL_MS,
    TaskEvent,
    TaskRunner,
    TaskSpec,
)
from doc_tool.ui.workbench_state import (
    ResultState,
    WorkView,
    derive_step_list,
    derive_workbench_state,
    error_presentation,
)


# 文档类型中文映射（与 project_bar 共享同一数据源）。
from doc_tool.ui.project_bar import DOC_TYPE_LABELS

# 主窗口只负责展示语义；业务结果仍使用原有 bool / PipelineResult。
TASK_UI = {
    "validate": {
        "label": "校验",
        "stage_progress": False,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "validation",
    },
    "merge": {
        "label": "正式合并",
        "stage_progress": True,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "pipeline",
    },
    "diag_build": {
        "label": "诊断构建",
        "stage_progress": True,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "pipeline",
    },
}

# 管线阶段进度百分比与中文标签：来自 pipeline 单一数据源，避免本文件
# 与 pipeline 阶段顺序双写漂移。延迟到首次使用时导入。
_PIPELINE_STAGE_PERCENT = None
_PIPELINE_STAGE_UI_LABELS = None


def _pipeline_stage_percent():
    global _PIPELINE_STAGE_PERCENT
    if _PIPELINE_STAGE_PERCENT is None:
        from doc_tool.application.pipeline import stage_percent_table

        _PIPELINE_STAGE_PERCENT = stage_percent_table()
    return _PIPELINE_STAGE_PERCENT


def _pipeline_stage_labels():
    global _PIPELINE_STAGE_UI_LABELS
    if _PIPELINE_STAGE_UI_LABELS is None:
        from doc_tool.application.pipeline import PIPELINE_STAGE_LABELS

        _PIPELINE_STAGE_UI_LABELS = PIPELINE_STAGE_LABELS
    return _PIPELINE_STAGE_UI_LABELS


class MainWindow(QMainWindow):
    """PySide6 主窗口。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.runner = TaskRunner()
        self._project_summary = None  # ProjectSummary
        self._word_available: Optional[bool] = None
        self._workbench_state = derive_workbench_state(None, running=False)
        self._result_state = ResultState()
        self._current_task = ""
        self._stage_progress_enabled = False
        self._progress_recent_stage = ""
        self._last_error_code: Optional[str] = None
        self._last_error_stage = ""
        self._last_error_detail = ""
        self._task_terminal_kind = ""
        self._close_after_task = False
        self._task_started_at: Optional[float] = None
        self._dark = False

        # 阶段事件累积（供 derive_step_list 派生步骤清单）
        self._stage_events: List[tuple] = []

        # 内容工作区
        self._content_workspace = None
        self._content_index_ready = False
        self._content_current_file: Optional[str] = None

        self._build_ui()
        self._build_menu()
        self._refresh_recent_projects()
        self._apply_workbench_state(self._workbench_state)

    # --- UI 构建 ---

    def _build_ui(self) -> None:
        self.setWindowTitle("康尚文档工具 v{0}".format(APP_VERSION))
        self.setMinimumSize(720, 480)
        self._restore_geometry()

        # 状态栏（稳定；只有中央内容区切换视图）
        status_bar = self.statusBar()
        self._status_label = QLabel("就绪", self)
        self._status_label.setObjectName("statusMuted")
        status_bar.addWidget(self._status_label)
        self._lock_label = QLabel("", self)
        self._lock_label.setObjectName("statusMuted")
        status_bar.addPermanentWidget(self._lock_label)

        # 中央：空状态 / IDE 布局
        self._stack = QStackedWidget(self)
        self._empty_state = EmptyState(
            on_new_project=self._on_new_project,
            on_open_project=self._on_open_project,
            on_open_recent=self._on_open_recent,
        )
        self._stack.addWidget(self._empty_state)

        self._ide_page = QWidget(self)
        ide_layout = QVBoxLayout(self._ide_page)
        ide_layout.setContentsMargins(0, 0, 0, 0)
        ide_layout.setSpacing(0)
        self._project_bar = ProjectBar(
            on_merge=self._on_merge,
            on_diag_build=self._on_diag_build,
            on_validate=self._on_validate,
        )
        ide_layout.addWidget(self._project_bar)
        self._ide_center_host = QWidget(self._ide_page)
        ide_layout.addWidget(self._ide_center_host, 1)
        self._stack.addWidget(self._ide_page)
        self.setCentralWidget(self._stack)

        # 右侧任务/结果 Dock
        self._task_dock_widget = QDockWidget("任务 / 结果", self)
        self._task_dock_widget.setObjectName("taskDock")
        self._task_dock = TaskDock(
            on_cancel=self._on_cancel,
            on_validate=self._on_validate,
            on_diag_build=self._on_diag_build,
            on_open_output=self._on_open_result_output,
            on_open_directory=self._on_open_result_directory,
            on_open_report=self._on_open_validation_report,
            on_show_tech=self._show_result_technical_details,
            on_copy_log=self._copy_log,
            on_open_log_dir=self._on_open_logs,
        )
        self._task_dock_widget.setWidget(self._task_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._task_dock_widget)
        self._task_dock_widget.setMinimumWidth(230)
        self._task_dock_widget.setMaximumWidth(460)

        # 轮询计时器（后台任务事件）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        # 已用时间计时器
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

    def _build_menu(self) -> None:
        from PySide6.QtGui import QAction, QKeySequence

        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu("文件")
        self._new_action = QAction("新建项目…", self)
        self._new_action.setShortcut(QKeySequence("Ctrl+N"))
        self._new_action.triggered.connect(self._on_new_project)
        file_menu.addAction(self._new_action)
        self._open_action = QAction("打开项目…", self)
        self._open_action.setShortcut(QKeySequence("Ctrl+O"))
        self._open_action.triggered.connect(self._on_open_project)
        file_menu.addAction(self._open_action)
        self._recent_menu = file_menu.addMenu("最近打开")
        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 操作
        ops_menu = menubar.addMenu("操作")
        self._validate_action = QAction("校验项目", self)
        self._validate_action.setShortcut(QKeySequence("F5"))
        self._validate_action.triggered.connect(self._on_validate)
        ops_menu.addAction(self._validate_action)
        ops_menu.addSeparator()
        self._merge_action = QAction("正式合并", self)
        self._merge_action.triggered.connect(self._on_merge)
        ops_menu.addAction(self._merge_action)
        self._diag_action = QAction("诊断构建（无 Word）", self)
        self._diag_action.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self._diag_action.triggered.connect(self._on_diag_build)
        ops_menu.addAction(self._diag_action)
        ops_menu.addSeparator()
        self._report_action = QAction("打开校验报告", self)
        self._report_action.triggered.connect(self._on_open_validation_report)
        ops_menu.addAction(self._report_action)

        # 内容
        content_menu = menubar.addMenu("内容")
        self._search_action = QAction("全文搜索", self)
        self._search_action.setShortcut(QKeySequence("Ctrl+F"))
        self._search_action.triggered.connect(self._on_content_search)
        content_menu.addAction(self._search_action)
        self._references_action = QAction("引用分析…", self)
        self._references_action.triggered.connect(self._on_content_references)
        content_menu.addAction(self._references_action)
        self._replace_action = QAction("全局替换…", self)
        self._replace_action.triggered.connect(self._on_content_replace)
        content_menu.addAction(self._replace_action)
        self._refactor_action = QAction("章节重命名/重编号…", self)
        self._refactor_action.triggered.connect(self._on_content_refactor)
        content_menu.addAction(self._refactor_action)
        self._lint_action = QAction("术语/一致性检查", self)
        self._lint_action.triggered.connect(self._on_content_lint)
        content_menu.addAction(self._lint_action)
        content_menu.addSeparator()
        self._open_external_action = QAction("在外部编辑器打开当前文件", self)
        self._open_external_action.triggered.connect(self._on_content_open_external)
        content_menu.addAction(self._open_external_action)

        # 视图：Dock 显隐开关。QDockWidget 关闭后仅保留标题栏上的 X，必须
        # 通过 toggleViewAction 重新打开——这里为每个 Dock 提供菜单项。
        self._view_menu = QMenu("视图", self)
        menubar.insertMenu(content_menu.menuAction(), self._view_menu)
        self._rebuild_view_menu()

        # 工具
        tools_menu = menubar.addMenu("工具")
        self._content_action = QAction("打开 Markdown 目录", self)
        self._content_action.triggered.connect(self._on_open_content)
        tools_menu.addAction(self._content_action)
        self._output_action = QAction("打开输出目录", self)
        self._output_action.triggered.connect(self._on_open_output)
        tools_menu.addAction(self._output_action)
        self._logs_action = QAction("打开日志目录", self)
        self._logs_action.triggered.connect(self._on_open_logs)
        tools_menu.addAction(self._logs_action)
        tools_menu.addSeparator()
        self._theme_action = QAction("切换深色主题", self)
        self._theme_action.triggered.connect(self._toggle_theme)
        tools_menu.addAction(self._theme_action)

        # 帮助
        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于 / 环境诊断", self)
        about_action.setShortcut(QKeySequence("F1"))
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

        # 标签切换 Ctrl+1..5（底部面板）
        for index in range(1, 6):
            shortcut = QAction(self)
            shortcut.setShortcut(QKeySequence("Ctrl+{0}".format(index)))
            shortcut.triggered.connect(
                lambda _=False, i=index: self._select_content_tab(i)
            )
            self.addAction(shortcut)

    def _toggle_theme(self) -> None:
        from doc_tool.ui.styles import toggle_theme

        self._dark = toggle_theme(QApplication.instance())
        self._task_dock.set_dark(self._dark)
        self._theme_action.setText("切换浅色主题" if self._dark else "切换深色主题")

    # --- 视图菜单（Dock 显隐） ---

    def _rebuild_view_menu(self) -> None:
        """重建「视图」菜单：为当前存在的每个 Dock 提供显隐开关。

        章节树/工具面板 Dock 在项目打开时才创建，因此每次打开项目都要
        重建；右键侧任务 Dock 始终存在。QDockWidget 被用户关闭后，唯一
        的恢复途径就是这里的 ``toggleViewAction()``。
        """
        self._view_menu.clear()
        entries = []
        task = getattr(self, "_task_dock_widget", None)
        if task is not None:
            entries.append(("任务 / 结果", task))
        tree = getattr(self, "_tree_dock", None)
        if tree is not None:
            entries.append(("章节树", tree))
        panels = getattr(self, "_panels_dock", None)
        if panels is not None:
            entries.append(("工具面板", panels))
        if not entries:
            placeholder = self._view_menu.addAction("（无可切换面板）")
            placeholder.setEnabled(False)
            return
        for label, dock in entries:
            action = dock.toggleViewAction()
            action.setText(label)
            self._view_menu.addAction(action)

    def _show_panels_dock(self) -> None:
        """内容操作入口被触发时确保底部工具面板可见（用户可能已关闭它）。"""
        dock = getattr(self, "_panels_dock", None)
        if dock is not None:
            dock.show()

    # --- 视图状态 ---

    def _apply_workbench_state(self, state) -> None:
        """把纯状态快照渲染进菜单、项目条、中央区与右侧 Dock。"""
        self._workbench_state = state
        if state.view == WorkView.EMPTY:
            self._stack.setCurrentWidget(self._empty_state)
            self._task_dock_widget.hide()
            self._project_bar.reset()
        else:
            self._stack.setCurrentWidget(self._ide_page)
            # 离开空状态后重新显示右侧任务/结果 Dock（空状态会隐藏它）。
            self._task_dock_widget.show()
            self._project_bar.render(self._project_summary, state)
            # 右侧 Dock 内容由任务生命周期驱动，不在此覆盖 running/result
            if state.view == WorkView.IDLE and not self.runner.is_running:
                self._task_dock.show_idle(
                    self._result_state if self._result_state.is_terminal else None,
                    project_open=True,
                )

        running = bool(self.runner.is_running)
        self._new_action.setEnabled(not running)
        self._open_action.setEnabled(not running)
        self._validate_action.setEnabled(state.actions["validate"].enabled)
        self._merge_action.setEnabled(state.actions["merge"].enabled)
        self._diag_action.setEnabled(state.actions["diag_build"].enabled)
        self._report_action.setEnabled(state.actions["report"].enabled)
        self._content_action.setEnabled(state.actions["content"].enabled)
        self._output_action.setEnabled(state.actions["output"].enabled)
        self._logs_action.setEnabled(state.actions["logs"].enabled)

        self._refresh_content_menu_state(running)
        if hasattr(self, "_empty_state"):
            self._empty_state.set_enabled(not running)

    def _refresh_content_menu_state(self, running: bool) -> None:
        """内容菜单可用性：读操作需项目打开且索引就绪；写操作额外需可写。"""
        workspace_ready = self._content_workspace_available() and not running
        summary = self._project_summary
        writable = bool(summary and summary.is_writable)
        self._search_action.setEnabled(workspace_ready)
        self._references_action.setEnabled(workspace_ready)
        self._lint_action.setEnabled(workspace_ready)
        self._replace_action.setEnabled(workspace_ready and writable)
        self._refactor_action.setEnabled(workspace_ready and writable)
        self._open_external_action.setEnabled(bool(self._content_workspace))

    def _switch_to_result_view(self) -> None:
        """任务终态：切到 result 视图（右侧 Dock 已由 on_task_done 渲染）。"""
        self._refresh_interaction_state()

    def _refresh_interaction_state(self) -> None:
        """根据项目、只读、任务、Word 和产物状态统一刷新操作。"""
        running = bool(self.runner.is_running)
        report_path = self._validation_report_path()
        state = derive_workbench_state(
            self._project_summary,
            running=running,
            task_label=self._task_label(getattr(self, "_current_task", "")),
            word_available=getattr(self, "_word_available", None),
            report_path=report_path,
            result_available=bool(self._result_state.is_terminal),
        )
        self._apply_workbench_state(state)

    # --- 最近项目 ---

    def _refresh_recent_projects(self) -> None:
        from doc_tool.application.project_service import load_recent_projects

        entries = load_recent_projects()
        enabled = not bool(self.runner.is_running)
        if hasattr(self, "_empty_state"):
            self._empty_state.set_recent_projects(entries, enabled=enabled)
        self._recent_menu.clear()
        if not entries:
            no_items = self._recent_menu.addAction("（无）")
            no_items.setEnabled(False)
            return
        for entry in entries[:10]:
            label = entry.name
            if entry.document_name:
                label = "{0}（{1}）".format(entry.name, entry.document_name)
            action = self._recent_menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(
                lambda _=False, p=entry.path: self._on_open_recent(p)
            )

    # --- 打开项目 ---

    def show_project(self, summary) -> None:
        """显示已打开的项目摘要并初始化内容工作区。"""
        from doc_tool.application.project_service import add_recent_project

        self._project_summary = summary
        self._word_available = None
        self._result_state = ResultState(project_root=summary.project_root)
        self._stage_events = []

        m = summary.manifest
        if summary.lock_info:
            self._lock_label.setText(
                "锁：{0}（PID {1}）".format(
                    summary.lock_info.get("taskType", "?"),
                    summary.lock_info.get("pid", "?"),
                )
            )
        else:
            self._lock_label.setText("")
        if not summary.is_writable:
            self._status_label.setText("项目模式版本不兼容，以只读方式打开")
        else:
            self._status_label.setText("就绪")

        add_recent_project(str(summary.project_root), m)
        self._init_content_workspace(summary)
        self._refresh_recent_projects()
        self._task_dock.show_idle(None, project_open=True)
        self._refresh_interaction_state()

    def _open_project_path(self, path: str) -> None:
        if self.runner.is_running:
            return
        from doc_tool.application.project_service import open_project
        from doc_tool.domain.errors import DocToolError

        try:
            summary = open_project(path)
        except DocToolError as exc:
            self._show_error("打开项目失败", exc.user_message, exc.suggested_action)
            return
        except Exception as exc:  # noqa: BLE001
            self._show_error("打开项目失败", str(exc)[:200])
            return
        self.show_project(summary)
        self._append_log("已打开项目：{0}".format(summary.project_root.name))

    def _on_open_recent(self, path: str) -> None:
        self._open_project_path(path)

    # --- 内容工作区 ---

    def _init_content_workspace(self, summary) -> None:
        """打开项目后创建/重建内容工作区并摆放各 Dock。"""
        from doc_tool.ui.content.workspace import ContentWorkspace

        # 清空旧的左侧/底部 Dock 容器
        self._remove_content_docks()
        if self._content_workspace is not None:
            try:
                self._content_workspace.deleteLater()
            except Exception:  # noqa: BLE001
                pass
            self._content_workspace = None

        self._content_index_ready = False
        self._content_current_file = None
        self._content_workspace = ContentWorkspace(
            summary.paths.content_root,
            state_dir=summary.paths.state_dir,
            assets_root=summary.paths.assets_root,
            writable=summary.is_writable,
            on_status=lambda msg: self._status_label.setText(msg),
            on_open_file=self._on_content_open_file,
            on_request_validate=self._on_content_request_validate,
            on_index_ready=self._on_content_index_ready,
        )

        # 左侧章节树 Dock
        self._tree_dock = QDockWidget("章节树", self)
        self._tree_dock.setObjectName("chapterTreeDock")
        self._tree_dock.setWidget(self._content_workspace.tree_host)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._tree_dock)

        # 中央多标签编辑器
        self._set_ide_center(self._content_workspace.tabs_host)

        # 底部工具面板
        self._panels_dock = QDockWidget("工具面板", self)
        self._panels_dock.setObjectName("panelsDock")
        self._panels_dock.setWidget(self._content_workspace.panels_host)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._panels_dock)
        self._panels_dock.setMinimumHeight(180)

        self._rebuild_view_menu()

    def _remove_content_docks(self) -> None:
        for name in ("chapterTreeDock", "panelsDock"):
            dock = self.findChild(QDockWidget, name)
            if dock is not None:
                self.removeDockWidget(dock)
                dock.deleteLater()

    def _set_ide_center(self, widget: QWidget) -> None:
        """把编辑器放入 IDE 中央宿主（可切换/清理）。"""
        layout = self._ide_center_host.layout()
        if layout is None:
            layout = QVBoxLayout(self._ide_center_host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(widget)
        else:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            layout.addWidget(widget)

    def _on_content_index_ready(self) -> None:
        self._content_index_ready = True
        self._refresh_interaction_state()

    def _on_content_open_file(self, rel_path: str) -> None:
        self._content_current_file = rel_path
        self._refresh_interaction_state()

    def _on_content_request_validate(self) -> None:
        """替换/重命名写回后自动跑校验管线（复用现有校验任务）。"""
        self._append_log("内容写回完成，自动执行校验以检查悬空引用…")
        self._on_validate()

    def _content_workspace_available(self) -> bool:
        return bool(
            self._content_workspace is not None and self._content_index_ready
        )

    def _select_content_tab(self, index: int) -> None:
        """Ctrl+1..5：底部面板标签切换（面板 Dock 关闭时先重新显示）。"""
        workspace = self._content_workspace
        if workspace is None:
            return
        panels = getattr(workspace, "_panels", None)
        if panels is None:
            return
        self._show_panels_dock()
        # index 1..5：1=搜索,2=替换,3=重命名,4=检查,5=改动
        names = ["搜索", "替换", "重命名/重编号", "检查", "改动"]
        if 1 <= index <= len(names):
            target = names[index - 1]
            for i in range(panels.count()):
                if panels.tabText(i) == target:
                    panels.setCurrentIndex(i)
                    return

    # --- 内容菜单回调 ---

    def _on_content_search(self) -> None:
        if not self._content_workspace_available():
            return
        self._show_panels_dock()
        self._content_workspace.focus_search()

    def _on_content_replace(self) -> None:
        if not self._content_workspace_available():
            return
        summary = self._project_summary
        if summary and not summary.is_writable:
            return
        self._show_panels_dock()
        self._content_workspace.show_replace()

    def _on_content_refactor(self) -> None:
        if not self._content_workspace_available():
            return
        summary = self._project_summary
        if summary and not summary.is_writable:
            return
        self._show_panels_dock()
        self._content_workspace.show_refactor(self._content_current_file)

    def _on_content_lint(self) -> None:
        if not self._content_workspace_available():
            return
        self._show_panels_dock()
        self._content_workspace.run_lint()

    def _on_content_open_external(self) -> None:
        workspace = self._content_workspace
        if workspace is not None:
            workspace.open_current_external()

    def _on_content_references(self) -> None:
        """引用分析：当前文件的被引用情况 + 全项目悬空引用。"""
        workspace = self._content_workspace
        index = workspace.index() if workspace is not None else None
        if index is None:
            return
        from doc_tool.ui.content.references_dialog import show_references_dialog

        show_references_dialog(
            self,
            index,
            current_file=self._content_current_file,
            on_open=self._on_content_open_from_dialog,
        )

    def _on_content_open_from_dialog(self, rel_path: str, line_no: int) -> None:
        workspace = self._content_workspace
        if workspace is not None:
            workspace.open_file(rel_path, line_no)

    # --- 菜单回调：新建 / 打开 ---

    def _on_new_project(self) -> None:
        if self.runner.is_running:
            return
        from doc_tool.ui.wizard import ImportWizard

        result = ImportWizard(self).run()
        if result is not None:
            self._open_project_path(str(result))

    def _on_open_project(self) -> None:
        if self.runner.is_running:
            return
        path = QFileDialog.getExistingDirectory(self, "选择项目目录")
        if path:
            self._open_project_path(path)

    # --- 任务执行 ---

    def _on_validate(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        summary = self._project_summary
        from doc_tool.adapters.kernel import ensure_kernel_importable, validate_with_project

        try:
            ensure_kernel_importable()
        except Exception as exc:  # noqa: BLE001
            self._show_error("内核不可用", str(exc)[:200])
            return
        self._stage_progress_enabled = TASK_UI["validate"]["stage_progress"]
        spec = TaskSpec(
            name="validate",
            target=validate_with_project,
            args=(summary.manifest, summary.paths),
            timeout_seconds=TASK_UI["validate"]["timeout"],
        )
        self._start_task(spec)

    def _on_merge(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        summary = self._project_summary
        from doc_tool.adapters.kernel import ensure_kernel_importable
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.application.word_check import check_word_available

        report = check_word_available(dispatch_check=False)
        self._word_available = bool(report.available)
        self._refresh_interaction_state()
        if not report.available:
            reasons = "\n".join("  • {0}".format(r) for r in report.reasons) or "  • 未知原因"
            self._show_error(
                "Microsoft Word 不可用",
                "正式合并需要本机交互式会话中的 Microsoft Word。",
                "请改用「操作 → 诊断构建（无 Word）」，或在安装 Microsoft Word 的电脑上执行正式合并。\n"
                "原因：\n{0}".format(reasons),
            )
            return
        try:
            ensure_kernel_importable()
        except Exception as exc:  # noqa: BLE001
            self._show_error("内核不可用", str(exc)[:200])
            return
        self._stage_progress_enabled = TASK_UI["merge"]["stage_progress"]
        spec = TaskSpec(
            name="merge",
            target=run_pipeline,
            args=(summary.manifest, summary.paths),
            kwargs={"skip_word_refresh": False, "progress": self._progress_callback()},
            timeout_seconds=TASK_UI["merge"]["timeout"],
        )
        self._start_task(spec)

    def _on_diag_build(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        summary = self._project_summary
        from doc_tool.adapters.kernel import ensure_kernel_importable
        from doc_tool.application.pipeline import run_pipeline

        try:
            ensure_kernel_importable()
        except Exception as exc:  # noqa: BLE001
            self._show_error("内核不可用", str(exc)[:200])
            return
        self._stage_progress_enabled = TASK_UI["diag_build"]["stage_progress"]
        spec = TaskSpec(
            name="diag_build",
            target=run_pipeline,
            args=(summary.manifest, summary.paths),
            kwargs={"skip_word_refresh": True, "progress": self._progress_callback()},
            timeout_seconds=TASK_UI["diag_build"]["timeout"],
        )
        self._start_task(spec)

    def _progress_callback(self):
        """构造后台线程用的进度回调：把阶段状态线程安全地推入 UI 队列。"""
        import queue as _queue

        q = self._progress_queue
        try:
            while True:
                q.get_nowait()
        except _queue.Empty:
            pass

        def emit(stage, status, detail=""):
            try:
                q.put((stage, status, detail))
            except Exception:  # noqa: BLE001
                pass

        return emit

    @property
    def _progress_queue(self):
        import queue as _queue

        if not hasattr(self, "_progress_q"):
            self._progress_q = _queue.Queue()
        return self._progress_q

    def _start_task(self, spec: TaskSpec) -> None:
        self._current_task = spec.name
        self._task_started_at = monotonic()
        self._stage_events = []
        self._progress_recent_stage = ""
        self._last_error_code = None
        self._last_error_stage = ""
        self._last_error_detail = ""
        self._task_terminal_kind = ""
        self._result_state = ResultState(
            status="running",
            task=spec.name,
            title="任务运行中：{0}".format(self._task_label(spec.name)),
            summary="任务完成后将在这里保留结果和适用的后续操作。",
            project_root=getattr(self._project_summary, "project_root", None),
        )
        self._task_dock.show_running(
            self._task_label(spec.name),
            steps=[],
            current_stage="",
            elapsed=0,
        )
        self._task_dock.clear_log()
        self._task_dock.set_cancel_waiting(False)
        self._status_label.setText("任务运行中")
        self._append_log("▶ {0} 开始".format(self._task_label(spec.name)))

        started = self.runner.start(
            spec, on_event=self._on_task_event, on_done=self._on_task_done
        )
        if not started:
            self._task_dock.show_idle(
                ResultState(
                    title="任务未启动",
                    summary="已有任务正在运行，本次请求未启动。",
                    advice="请等待当前任务完成后重试。",
                    project_root=getattr(
                        getattr(self, "_project_summary", None), "project_root", None
                    ),
                ),
                project_open=True,
            )
            self._task_started_at = None
            self._current_task = ""
            self._status_label.setText("已有任务正在运行")
            self._refresh_interaction_state()
            return
        self._elapsed_timer.start()
        self._poll_timer.start()
        self._refresh_recent_projects()
        self._refresh_interaction_state()

    def _poll(self) -> None:
        """消费后台任务事件队列。"""
        self._drain_stage_progress()
        self.runner.poll()
        if not self.runner.is_running:
            self._poll_timer.stop()

    def _drain_stage_progress(self) -> None:
        import queue as _queue

        drained = False
        while True:
            try:
                stage, status, detail = self._progress_queue.get_nowait()
            except _queue.Empty:
                break
            drained = True
            self._apply_stage_progress(stage, status, detail)
        return drained

    def _apply_stage_progress(self, stage: str, status: str, detail: str) -> None:
        """按阶段状态更新步骤清单、日志与当前阶段文本。"""
        self._stage_events.append((stage, status, detail, None))
        label = _pipeline_stage_labels().get(stage, stage)
        if status == "started":
            self._progress_recent_stage = stage
            self._append_log("▶ {0} 开始".format(label))
        elif status == "skipped":
            self._append_log("· {0} 已跳过".format(label))
        elif status == "succeeded":
            self._append_log("✓ {0} 完成".format(label))
        elif status == "failed":
            self._append_log("✗ {0} 失败：{1}".format(label, detail))
        self._render_step_list()

    def _render_step_list(self) -> None:
        steps = derive_step_list(
            self._stage_events, fallback_label=self._task_label(self._current_task)
        )
        current_stage = self._progress_recent_stage
        if current_stage not in {s.stage for s in steps}:
            current_stage = ""
        self._task_dock.show_running(
            self._task_label(self._current_task),
            steps=steps,
            current_stage=current_stage,
            elapsed=self._elapsed_seconds(),
        )
        done = sum(
            1
            for s in steps
            if s.status in ("success", "skipped", "failed", "cancelled")
        )
        self._task_dock._step_footer.set_progress(done, len(steps))

    def _update_elapsed(self) -> None:
        self._task_dock.set_elapsed(self._elapsed_seconds())

    def _elapsed_seconds(self) -> int:
        if self._task_started_at is None:
            return 0
        return max(0, int(monotonic() - self._task_started_at))

    def _append_log(self, message: str) -> None:
        self._task_dock.append_log(message)

    def _on_cancel(self) -> None:
        if not self.runner.is_running:
            return
        self._task_dock.set_cancel_waiting(True, self._current_stage_label())
        self._append_log("⊘ 已请求取消，将在阶段边界安全停止…")
        self.runner.cancel()

    def _current_stage_label(self) -> str:
        recent = getattr(self, "_progress_recent_stage", "")
        if not recent:
            return ""
        return _pipeline_stage_labels().get(recent, recent)

    def _on_task_event(self, event: TaskEvent) -> None:
        """处理任务事件（由 poll 调用）。"""
        if event.kind in ("failed", "cancelled"):
            self._last_error_code = event.error_code
            self._last_error_stage = event.stage or self._progress_recent_stage
            self._last_error_detail = (event.detail or "")[:200]
            self._task_terminal_kind = event.kind
        elif event.kind == "succeeded":
            self._task_terminal_kind = "succeeded"

    def _on_task_done(self, result) -> None:
        """按当前任务的明确结果语义更新界面并统一收尾。"""
        current_task = self._current_task
        result_type = TASK_UI.get(current_task, {}).get("result_type", "unknown")
        self._elapsed_timer.stop()
        self._drain_stage_progress()

        if result is None:
            code = self._last_error_code or "E9000"
            reason, advice = error_presentation(code, self._last_error_detail)
            cancelled = self._task_terminal_kind == "cancelled" or code == "E5003"
            timed_out = code == ERR_WATCHDOG_TIMEOUT
            status = "cancelled" if cancelled else "failure"
            title = "任务已取消" if cancelled else "任务失败"
            if timed_out:
                title = "任务运行超时"
            self._result_state = ResultState(
                status=status,
                task=current_task,
                title=title,
                summary=reason,
                advice=advice,
                error_code=code,
                stage=self._last_error_stage or current_task,
                exception_summary=self._last_error_detail,
                log_path=self._current_log_path(),
                project_root=getattr(
                    getattr(self, "_project_summary", None), "project_root", None
                ),
            )
        elif result_type == "pipeline":
            self._handle_pipeline_result(result)
        elif result_type == "validation":
            self._handle_validation_result(bool(result))
        else:
            self._result_state = ResultState(
                status="success",
                task=current_task,
                title="任务完成",
                summary="任务已成功完成。",
                project_root=getattr(
                    getattr(self, "_project_summary", None), "project_root", None
                ),
            )

        steps = derive_step_list(
            self._stage_events, fallback_label=self._task_label(current_task)
        )
        self._task_dock.show_result(self._task_label(current_task), self._result_state, steps)
        self._task_started_at = None
        self._status_label.setText(self._result_state.title)

        self._refresh_recent_projects()
        self._refresh_interaction_state()
        self._last_error_code = None
        self._last_error_stage = ""
        self._last_error_detail = ""
        self._task_terminal_kind = ""
        self._current_task = ""
        if self._close_after_task:
            self._finish_close()

    def _handle_pipeline_result(self, result) -> None:
        project = self._project_summary
        project_root = getattr(project, "project_root", None)
        report_path = self._validation_report_path()
        report_path = report_path if report_path and Path(report_path).is_file() else None
        output_path = Path(result.output_path) if result.output_path else None
        output_path = output_path if output_path and output_path.is_file() else None
        if result.success:
            from doc_tool.domain.output_state import is_formal_success

            formal = bool(output_path and is_formal_success(str(output_path)))
            if output_path:
                if formal:
                    title = "正式合并成功"
                    summary = "Word 字段已刷新并完成正式输出：{0}".format(output_path)
                    self._status_label.setText("正式合并成功（Word 已刷新，字段已校验）")
                    self._append_log("✓ 正式输出：{0}".format(output_path))
                else:
                    title = "诊断构建完成"
                    summary = "已生成非正式诊断输出：{0}".format(output_path)
                    self._status_label.setText("诊断构建完成（非正式，字段未实机刷新）")
                    self._append_log("△ 诊断输出：{0}".format(output_path))
            else:
                title = "任务成功完成"
                summary = "任务已完成，但没有返回新的文档产物。"
                self._status_label.setText(title)
            self._result_state = ResultState(
                status="success",
                task=self._current_task,
                title=title,
                summary=summary,
                output_path=output_path,
                report_path=report_path,
                log_path=self._current_log_path(),
                project_root=project_root,
            )
        else:
            last_stage = getattr(result, "last_stage", None)
            code = result.error_code or self._last_error_code or "E9000"
            detail = getattr(last_stage, "detail", "") or self._last_error_detail
            reason, advice = error_presentation(code, detail)
            old_output_exists = bool(
                project
                and getattr(project, "paths", None)
                and project.paths.output_dir.is_dir()
            )
            if old_output_exists:
                reason += " 本次任务未生成新的正式产物；项目中原有输出未被覆盖。"
            cancelled = code == "E5003" or self._task_terminal_kind == "cancelled"
            self._result_state = ResultState(
                status="cancelled" if cancelled else "failure",
                task=self._current_task,
                title="任务已取消" if cancelled else "任务失败",
                summary=reason,
                advice=advice,
                error_code=code,
                stage=getattr(last_stage, "stage", "") or self._last_error_stage,
                exception_summary=(detail or "")[:200],
                log_path=self._current_log_path(),
                project_root=project_root,
            )
            self._status_label.setText(
                "任务已取消" if cancelled else "任务失败（{0}）".format(code)
            )

    def _handle_validation_result(self, passed: bool) -> None:
        from doc_tool.application.project_service import read_validation_report_summary

        report_path = self._validation_report_path()
        report = read_validation_report_summary(report_path) if report_path else {}
        existing_report = report_path if report.get("exists") else None
        if report.get("exists"):
            status = "校验通过" if passed else "校验未通过"
            summary = "{0}（PASS={1} FAIL={2}）".format(
                status, report["passCount"], report["failCount"]
            )
            self._status_label.setText(summary)
            self._append_log("校验报告：{0}".format(report_path))
            for failure in report["failures"][:10]:
                self._append_log("  ✗ {0}".format(failure))
        else:
            status = "校验通过" if passed else "校验未通过"
            summary = status
            self._status_label.setText(status)

        if passed:
            self._result_state = ResultState(
                status="success",
                task=self._current_task,
                title="项目校验通过",
                summary=summary,
                report_path=existing_report,
                log_path=self._current_log_path(),
                project_root=getattr(
                    getattr(self, "_project_summary", None), "project_root", None
                ),
            )
        else:
            code = self._last_error_code or "E2002"
            reason, advice = error_presentation(code, self._last_error_detail)
            self._result_state = ResultState(
                status="failure",
                task=self._current_task,
                title="项目校验未通过",
                summary=reason,
                advice=advice,
                error_code=code,
                stage=self._last_error_stage or "validate",
                exception_summary=self._last_error_detail,
                report_path=existing_report,
                log_path=self._current_log_path(),
                project_root=getattr(
                    getattr(self, "_project_summary", None), "project_root", None
                ),
            )

    # --- 目录/报告打开 ---

    def _current_log_path(self) -> Optional[Path]:
        project = self._project_summary
        paths = getattr(project, "paths", None)
        if paths is None:
            return None
        try:
            return paths.logs_dir / "runtime.log"
        except Exception:  # noqa: BLE001
            return None

    def _validation_report_path(self) -> Optional[Path]:
        if not self._project_summary:
            return None
        try:
            return (
                self._project_summary.paths.logs_dir
                / (self._project_summary.manifest.documentType + "-validation.md")
            )
        except Exception:  # noqa: BLE001
            return None

    def _on_open_content(self) -> None:
        if self._project_summary:
            self._open_directory_or_warn(
                self._project_summary.paths.resolve(
                    self._project_summary.manifest.relative_content_root()
                ),
                "内容目录",
                create=True,
            )

    def _on_open_output(self) -> None:
        if self._project_summary:
            out = self._project_summary.paths.output_dir
            if not out.exists():
                self._show_error(
                    "尚未生成输出",
                    "输出目录尚未生成：{0}".format(out),
                    "请先执行「操作 → 诊断构建」或「正式合并」生成输出。",
                )
                return
            self._open_directory_or_warn(out, "输出目录")

    def _on_open_logs(self) -> None:
        if self._project_summary:
            self._open_directory_or_warn(
                self._project_summary.paths.logs_dir, "日志目录", create=True
            )

    def _on_open_validation_report(self) -> None:
        path = self._validation_report_path()
        if not path or not path.exists():
            self._show_error(
                "校验报告不存在",
                "尚未生成校验报告。",
                "请先执行「操作 → 校验项目」生成报告。",
            )
            return
        if not self._open_file(path):
            self._show_validation_report_preview(path)

    def _on_open_result_output(self, path: str) -> None:
        p = Path(path)
        if not self._open_file(p):
            self._show_error(
                "结果已不可用",
                "该任务产物已被移动或删除：{0}".format(p),
                "请重新执行任务，或打开当前项目输出目录查找仍存在的产物。",
            )

    def _on_open_result_directory(self, path: str) -> None:
        p = Path(path)
        if not self._open_directory(p):
            self._show_error("结果目录已不可用", "无法打开目录：{0}".format(p))

    def _show_result_technical_details(self) -> None:
        state = self._result_state
        details = [
            "错误码：{0}".format(state.error_code or "未知"),
            "失败阶段：{0}".format(state.stage or "未知"),
            "异常摘要：{0}".format(state.exception_summary or "无"),
            "日志路径：{0}".format(state.log_path or "未生成"),
        ]
        QMessageBox.information(self, "技术详情", "\n".join(details))

    def _copy_log(self) -> None:
        try:
            text = self._task_dock._log_stream.full_text()
            QApplication.clipboard().setText(text)
            self._status_label.setText("日志内容已复制")
        except Exception:  # noqa: BLE001
            self._show_error("复制失败", "无法复制日志内容。")

    def _show_validation_report_preview(self, path: Path) -> None:
        """系统关联程序不可用时，以只读窗口展示校验报告。"""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._show_error(
                "无法读取校验报告",
                "无法读取校验报告：{0}".format(exc),
                "请检查文件权限，或在文件管理器中手动打开该文件。",
            )
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("校验报告预览")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        path_label = QLabel(str(path), dialog)
        path_label.setObjectName("statusMuted")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(content)
        layout.addWidget(text, 1)
        close_btn = QPushButton("关闭", dialog)
        close_btn.setProperty("btnRole", "secondary")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _on_about(self) -> None:
        from doc_tool.ui.about_dialog import show_about_dialog

        show_about_dialog(self)

    # --- 辅助 ---

    @staticmethod
    def _task_label(name: str) -> str:
        labels = {
            "import": "导入",
            "build": "构建",
            "validate": "校验",
            "merge": "正式合并",
            "diag_build": "诊断构建",
        }
        return labels.get(name, name)

    def _show_error(self, title: str, message: str, suggestion: str = "") -> None:
        full = message
        if suggestion:
            full += "\n\n建议：{0}".format(suggestion)
        QMessageBox.critical(self, title, full)

    @staticmethod
    def _open_path(path: Path) -> bool:
        path = Path(path)
        if not path.exists():
            return False
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return True
        except OSError:
            return False

    @classmethod
    def _open_directory(cls, path: Path, create: bool = False) -> bool:
        path = Path(path)
        if not path.exists() and create:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                return False
        if not path.is_dir():
            return False
        return cls._open_path(path)

    @classmethod
    def _open_file(cls, path: Path) -> bool:
        path = Path(path)
        if not path.is_file():
            return False
        return cls._open_path(path)

    def _open_directory_or_warn(self, path: Path, what: str, create: bool = False) -> bool:
        if not self._open_directory(path, create=create):
            self._show_error(
                "无法打开{0}".format(what),
                "无法打开{0}：{1}".format(what, path),
                "请检查目录是否存在、是否被占用或权限不足。",
            )
            return False
        return True

    # --- 窗口几何持久化 ---

    def _restore_geometry(self) -> None:
        from doc_tool.application.project_service import load_window_geometry

        geom = load_window_geometry() or {}
        saved_geo = (geom.get("geometry") or "").strip()
        maximized = bool(geom.get("maximized", False))
        m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", saved_geo)
        if m:
            w, h, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            self.resize(max(w, 640), max(h, 480))
            self.move(x, y)
        else:
            self.resize(1200, 760)
        if maximized:
            self.showMaximized()

    def _persist_geometry(self) -> None:
        from doc_tool.application.project_service import save_window_geometry

        if self.isMaximized():
            # 最大化态不写回几何，避免覆盖用户期望的「正常态」尺寸。
            save_window_geometry("", True)
            return
        rect = self.geometry()
        geometry = "{0}x{1}+{2}+{3}".format(rect.width(), rect.height(), rect.x(), rect.y())
        save_window_geometry(geometry, False)

    def _finish_close(self) -> None:
        self._close_after_task = False
        try:
            self._persist_geometry()
        except Exception:  # noqa: BLE001
            pass
        self.close()

    def closeEvent(self, event) -> None:
        """任务运行中先请求安全取消，终态回调到达后再关闭窗口。"""
        if not self.runner.is_running:
            self._persist_geometry()
            event.accept()
            return
        if self._close_after_task:
            event.ignore()
            return
        confirmed = QMessageBox.question(
            self,
            "任务仍在运行",
            "当前任务尚未完成。是否请求安全取消，并在任务停止后退出？\n\n"
            "任务会在下一个安全阶段边界停止。",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self._close_after_task = True
        self._task_dock.set_cancel_waiting(True)
        self._status_label.setText("正在安全停止任务，停止后将自动退出…")
        self._append_log("⊘ 已请求安全取消；任务停止后应用将自动退出。")
        self.runner.cancel()
        event.ignore()
