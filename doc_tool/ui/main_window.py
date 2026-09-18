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

from doc_tool.application.content.unsaved import (
    UnsavedChoice,
    UnsavedResolver,
    collect_unsaved,
)
from doc_tool.application.content.workspace_state import (
    SessionState,
    WorkspaceStateStore,
)
from doc_tool.domain.version import APP_VERSION, get_build_info
from doc_tool.ui.content.unsaved_prompt import confirm_unsaved_dialog
from doc_tool.ui.project_bar import ProjectBar
from doc_tool.ui.empty_state import EmptyState
from doc_tool.ui.styles import apply_theme, is_dark_theme
from doc_tool.ui.task_dock import TaskDock
from doc_tool.ui.operation_loading_overlay import run_async_operation
from doc_tool.ui.task_bridge import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    ERR_WATCHDOG_TIMEOUT,
    POLL_INTERVAL_MS,
    TaskEvent,
    TaskRunner,
    TaskSpec,
)
from doc_tool.ui.workbench_state import (
    STEP_STATUS_CANCELLED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SKIPPED,
    STEP_STATUS_SUCCESS,
    ResultState,
    StepItem,
    WorkView,
    derive_step_list,
    derive_workbench_state,
    error_presentation,
    format_stage_locations,
)


# 文档类型中文映射（与 project_bar 共享同一数据源）。
from doc_tool.ui.project_bar import DOC_TYPE_LABELS

# 主窗口只负责展示语义；业务结果仍使用原有 bool / PipelineResult。
TASK_UI = {
    "validate": {
        "label": "项目检查",
        "stage_progress": False,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "validation",
    },
    "merge": {
        "label": "正式出稿",
        "stage_progress": True,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "pipeline",
    },
    "diag_build": {
        "label": "快速构建",
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

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        unsaved_resolver: Optional[UnsavedResolver] = None,
        window_registry=None,
        window_factory=None,
    ) -> None:
        super().__init__(parent)
        self.runner = TaskRunner()
        self._unsaved_resolver = unsaved_resolver or confirm_unsaved_dialog
        # 多窗口：注册表保存强引用；工厂回调用于「在新窗口打开项目」。
        self._window_registry = window_registry
        self._window_factory = window_factory
        self._closed = False
        self._pending_session: Optional[SessionState] = None
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
        self._zen_mode = False
        self._zen_prev_state: dict[str, bool] = {}

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
        from doc_tool.domain.branding import APP_DISPLAY_NAME

        self.setWindowTitle("{0} v{1}".format(APP_DISPLAY_NAME, APP_VERSION))
        self.setMinimumSize(720, 480)
        self._restore_geometry()

        # 状态栏（稳定；只有中央内容区切换视图）
        status_bar = self.statusBar()
        self._status_label = QLabel("就绪", self)
        self._status_label.setObjectName("statusMuted")
        status_bar.addWidget(self._status_label)

        self._branch_btn = QPushButton("", self)
        self._branch_btn.setObjectName("statusBranchBtn")
        self._branch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._branch_btn.setToolTip("当前 Git 分支（点击切换分支）")
        self._branch_btn.setVisible(False)
        self._branch_btn.clicked.connect(self._on_switch_branch_clicked)
        status_bar.addWidget(self._branch_btn)

        # 构建成功产物动作胶囊条（默认隐藏，构建完成有产物时显示）
        self._output_capsules_widget = QWidget(self)
        capsule_layout = QHBoxLayout(self._output_capsules_widget)
        capsule_layout.setContentsMargins(6, 0, 0, 0)
        capsule_layout.setSpacing(4)

        self._capsule_open_btn = QPushButton("📄 打开 Word", self._output_capsules_widget)
        self._capsule_open_btn.setProperty("btnRole", "compact")
        self._capsule_open_btn.setToolTip("用系统默认程序打开 Word 产物")
        self._capsule_open_btn.clicked.connect(
            lambda: self._current_output_path and self._on_open_result_output(self._current_output_path)
        )
        capsule_layout.addWidget(self._capsule_open_btn)

        self._capsule_locate_btn = QPushButton("📁 定位文件", self._output_capsules_widget)
        self._capsule_locate_btn.setProperty("btnRole", "compact")
        self._capsule_locate_btn.setToolTip("在资源管理器中选中并高亮该产物")
        self._capsule_locate_btn.clicked.connect(
            lambda: self._current_output_path and self._locate_file(self._current_output_path)
        )
        capsule_layout.addWidget(self._capsule_locate_btn)

        self._capsule_copy_btn = QPushButton("📋 复制路径", self._output_capsules_widget)
        self._capsule_copy_btn.setProperty("btnRole", "compact")
        self._capsule_copy_btn.setToolTip("复制生成文件的绝对路径到剪贴板")
        self._capsule_copy_btn.clicked.connect(
            lambda: self._current_output_path and self._copy_output_path(self._current_output_path)
        )
        capsule_layout.addWidget(self._capsule_copy_btn)

        self._capsule_export_btn = QPushButton("📤 另存为…", self._output_capsules_widget)
        self._capsule_export_btn.setProperty("btnRole", "compact")
        self._capsule_export_btn.setToolTip("将文档另存/复制到外部交付目录")
        self._capsule_export_btn.clicked.connect(
            lambda: self._current_output_path and self._export_output_to_external(self._current_output_path)
        )
        capsule_layout.addWidget(self._capsule_export_btn)

        self._current_output_path: Optional[str] = None
        self._output_capsules_widget.setVisible(False)
        status_bar.addWidget(self._output_capsules_widget)

        self._lock_label = QLabel("", self)
        self._lock_label.setObjectName("statusMuted")
        status_bar.addPermanentWidget(self._lock_label)

        # 中央：空状态 / IDE 布局
        self._stack = QStackedWidget(self)
        self._empty_state = EmptyState(
            on_new_project=self._on_new_project,
            on_open_project=self._on_open_project,
            on_open_recent=self._on_open_recent,
            on_remove_recent=self._on_remove_recent,
            on_convert=self._on_convert_documents,
            on_pdf_toolbox=self._on_pdf_toolbox,
            on_drop_files=self._on_convert_documents,
            on_show_help=self._on_open_help,
            on_about=self._on_about,
            on_command_palette=self.open_command_palette,
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
            on_switch_branch=self._on_switch_branch_clicked,
            on_close_project=self.close_project,
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
            on_copy_path=self._copy_output_path,
            on_export_to=self._export_output_to_external,
            on_locate_file=self._locate_file,
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

        # 项目加载动效遮罩层
        from doc_tool.ui.project_loading_overlay import ProjectLoadingOverlay

        self._loading_overlay = ProjectLoadingOverlay(self, dark=self._dark)

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
        self._open_new_action = QAction("在新窗口打开项目…", self)
        self._open_new_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self._open_new_action.triggered.connect(self._on_open_project_new_window)
        file_menu.addAction(self._open_new_action)
        self._recent_menu = file_menu.addMenu("最近打开")
        file_menu.addSeparator()
        self._save_all_action = QAction("保存全部", self)
        self._save_all_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_all_action.triggered.connect(self._on_save_all)
        file_menu.addAction(self._save_all_action)
        self._close_action = QAction("关闭项目", self)
        self._close_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        self._close_action.triggered.connect(self.close_project)
        file_menu.addAction(self._close_action)
        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 操作
        ops_menu = menubar.addMenu("操作")
        self._validate_action = QAction("项目检查", self)
        self._validate_action.setShortcut(QKeySequence("F5"))
        self._validate_action.triggered.connect(self._on_validate)
        ops_menu.addAction(self._validate_action)
        ops_menu.addSeparator()
        self._diag_action = QAction("快速构建（无 Word）", self)
        self._diag_action.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self._diag_action.triggered.connect(self._on_diag_build)
        ops_menu.addAction(self._diag_action)
        self._merge_action = QAction("正式出稿", self)
        self._merge_action.triggered.connect(self._on_merge)
        ops_menu.addAction(self._merge_action)
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

        # 版本控制 (Git)
        git_menu = menubar.addMenu("版本控制")
        self._switch_branch_action = QAction("切换分支…", self)
        self._switch_branch_action.setShortcut(QKeySequence("Ctrl+B"))
        self._switch_branch_action.triggered.connect(self._on_switch_branch_clicked)
        git_menu.addAction(self._switch_branch_action)

        self._new_branch_action = QAction("新建并切换分支…", self)
        self._new_branch_action.triggered.connect(self._on_new_branch_menu_clicked)
        git_menu.addAction(self._new_branch_action)

        git_menu.addSeparator()

        self._git_commit_action = QAction("提交改动…", self)
        self._git_commit_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self._git_commit_action.triggered.connect(self._on_git_commit_menu_clicked)
        git_menu.addAction(self._git_commit_action)

        self._git_push_action = QAction("推送代码 (Git Push)", self)
        self._git_push_action.triggered.connect(self._on_git_push_menu_clicked)
        git_menu.addAction(self._git_push_action)

        self._git_pull_action = QAction("拉取更新 (Git Pull)", self)
        self._git_pull_action.triggered.connect(self._on_git_pull_menu_clicked)
        git_menu.addAction(self._git_pull_action)

        git_menu.addSeparator()

        self._git_stash_action = QAction("暂存工作区改动 (Stash)", self)
        self._git_stash_action.triggered.connect(self._on_git_stash_menu_clicked)
        git_menu.addAction(self._git_stash_action)

        self._git_pop_stash_action = QAction("恢复暂存改动 (Stash Pop)", self)
        self._git_pop_stash_action.triggered.connect(self._on_git_pop_stash_menu_clicked)
        git_menu.addAction(self._git_pop_stash_action)

        git_menu.addSeparator()

        self._refresh_changes_action = QAction("刷新改动状态", self)
        self._refresh_changes_action.setShortcut(QKeySequence("Ctrl+R"))
        self._refresh_changes_action.triggered.connect(self._on_refresh_changes_menu_clicked)
        git_menu.addAction(self._refresh_changes_action)

        # 视图：Dock 显隐开关、专注模式与全局命令面板
        self._view_menu = QMenu("视图", self)
        menubar.insertMenu(content_menu.menuAction(), self._view_menu)

        self._cmd_palette_action = QAction("命令面板…", self)
        self._cmd_palette_action.setShortcut(QKeySequence("Ctrl+K"))
        self._cmd_palette_action.triggered.connect(self.open_command_palette)
        self.addAction(self._cmd_palette_action)

        self._cmd_palette_shift_action = QAction("命令面板 (Shift)…", self)
        self._cmd_palette_shift_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self._cmd_palette_shift_action.triggered.connect(self.open_command_palette)
        self.addAction(self._cmd_palette_shift_action)

        self._quick_open_action = QAction("快速打开章节…", self)
        self._quick_open_action.setShortcut(QKeySequence("Ctrl+P"))
        self._quick_open_action.triggered.connect(self.open_quick_open)
        self.addAction(self._quick_open_action)

        self._zen_mode_action = QAction("专注写作模式", self)
        self._zen_mode_action.setShortcut(QKeySequence("F11"))
        self._zen_mode_action.setCheckable(True)
        self._zen_mode_action.setChecked(False)
        self._zen_mode_action.triggered.connect(self.toggle_zen_mode)
        self.addAction(self._zen_mode_action)
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
        self._settings_action = QAction("项目设置…", self)
        self._settings_action.triggered.connect(self._on_project_settings)
        tools_menu.addAction(self._settings_action)
        self._reimport_action = QAction("重新导入更新源 Word…", self)
        self._reimport_action.triggered.connect(self._on_reimport_source)
        tools_menu.addAction(self._reimport_action)
        # 互转面向任意文件，不需要打开项目，因此不受项目状态门控。
        self._convert_action = QAction("文档互转（Word / PDF / Markdown）…", self)
        # lambda 包装：triggered 自带 checked 参数，避免混入 _on_convert_documents 的 paths 形参。
        self._convert_action.triggered.connect(lambda: self._on_convert_documents())
        tools_menu.addAction(self._convert_action)
        self._pdf_toolbox_action = QAction("PDF 工具箱（合并 / 拆分 / 水印 / 加密）…", self)
        self._pdf_toolbox_action.triggered.connect(lambda: self._on_pdf_toolbox())
        tools_menu.addAction(self._pdf_toolbox_action)
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
        if getattr(self, "_content_workspace", None) is not None:
            self._content_workspace.set_dark(self._dark)
        self._theme_action.setText("切换浅色主题" if self._dark else "切换深色主题")

    # --- 视图菜单（Dock 显隐与专注模式） ---

    def _rebuild_view_menu(self) -> None:
        """重建「视图」菜单：为专注模式与当前存在的每个 Dock 提供显隐开关。

        章节树/工具面板 Dock 在项目打开时才创建，因此每次打开项目都要
        重建；右侧任务 Dock 始终存在。QDockWidget 被用户关闭后，唯一
        的恢复途径就是这里的 ``toggleViewAction()``。
        """
        self._view_menu.clear()
        if hasattr(self, "_cmd_palette_action"):
            self._view_menu.addAction(self._cmd_palette_action)
        if hasattr(self, "_quick_open_action"):
            self._view_menu.addAction(self._quick_open_action)
        self._view_menu.addSeparator()
        if hasattr(self, "_zen_mode_action"):
            self._view_menu.addAction(self._zen_mode_action)
            self._view_menu.addSeparator()
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

    def toggle_zen_mode(self) -> None:
        """切换 F11 专注写作模式（隐藏/恢复外围面板与项目条）。"""
        self._zen_mode = not getattr(self, "_zen_mode", False)
        if hasattr(self, "_zen_mode_action"):
            self._zen_mode_action.setChecked(self._zen_mode)
            self._zen_mode_action.setText(
                "退出专注写作模式 (F11)" if self._zen_mode else "专注写作模式 (F11)"
            )

        tree = getattr(self, "_tree_dock", None)
        task = getattr(self, "_task_dock_widget", None)
        panels = getattr(self, "_panels_dock", None)
        pbar = getattr(self, "_project_bar", None)

        if self._zen_mode:
            self._zen_prev_state = {
                "tree": tree.isVisible() if tree is not None else False,
                "task": task.isVisible() if task is not None else False,
                "panels": panels.isVisible() if panels is not None else False,
                "pbar": pbar.isVisible() if pbar is not None else False,
            }
            if tree is not None:
                tree.hide()
            if task is not None:
                task.hide()
            if panels is not None:
                panels.hide()
            if pbar is not None:
                pbar.hide()
            self._status_label.setText("已进入专注写作模式，按 F11 退出并恢复完整布局")
        else:
            prev = getattr(self, "_zen_prev_state", {})
            if tree is not None and prev.get("tree", True):
                tree.show()
            if task is not None and prev.get("task", True):
                task.show()
            if panels is not None and prev.get("panels", False):
                panels.show()
            if pbar is not None and prev.get("pbar", True):
                pbar.show()
            self._status_label.setText("已退出专注模式")

    def open_command_palette(self) -> None:
        """打开全局命令面板 (Ctrl+K / Ctrl+Shift+P)。"""
        from doc_tool.ui.command_palette import CommandPaletteDialog, PaletteItem

        items: List[PaletteItem] = []

        # 文件 / 项目操作
        items.append(
            PaletteItem(
                title="新建项目…",
                category="文件",
                shortcut="Ctrl+N",
                callback=self._on_new_project,
            )
        )
        items.append(
            PaletteItem(
                title="打开项目…",
                category="文件",
                shortcut="Ctrl+O",
                callback=self._on_open_project,
            )
        )
        if self._project_summary:
            items.append(
                PaletteItem(
                    title="快速打开章节…",
                    category="导航",
                    shortcut="Ctrl+P",
                    callback=self.open_quick_open,
                )
            )
            items.append(
                PaletteItem(
                    title="全部保存",
                    category="编辑",
                    shortcut="Ctrl+Shift+S",
                    callback=self._on_content_save_all,
                )
            )
            items.append(
                PaletteItem(
                    title="重新导入更新源 Word…",
                    category="文件",
                    callback=self._on_reimport_source,
                )
            )

        # 构建 / 校验
        if self._project_summary:
            items.append(
                PaletteItem(
                    title="正式合并出稿",
                    category="构建",
                    shortcut="Ctrl+Shift+B",
                    callback=self._on_merge_task,
                )
            )
            items.append(
                PaletteItem(
                    title="快速构建（草稿）",
                    category="构建",
                    callback=self._on_diag_task,
                )
            )
            items.append(
                PaletteItem(
                    title="项目结构与资源校验",
                    category="校验",
                    shortcut="F5",
                    callback=self._on_validate_task,
                )
            )

        # 版本控制 (Git)
        if self._project_summary:
            items.append(
                PaletteItem(
                    title="Git: 切换分支…",
                    category="Git",
                    shortcut="Ctrl+B",
                    callback=self._on_switch_branch_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="Git: 新建并切换分支…",
                    category="Git",
                    callback=self._on_new_branch_menu_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="Git: 提交改动…",
                    category="Git",
                    shortcut="Ctrl+Shift+C",
                    callback=self._on_git_commit_menu_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="Git: 推送代码 (Push)",
                    category="Git",
                    callback=self._on_git_push_menu_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="Git: 拉取更新 (Pull)",
                    category="Git",
                    callback=self._on_git_pull_menu_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="Git: 暂存工作区改动 (Stash)",
                    category="Git",
                    callback=self._on_git_stash_menu_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="Git: 恢复暂存改动 (Stash Pop)",
                    category="Git",
                    callback=self._on_git_pop_stash_menu_clicked,
                )
            )
            items.append(
                PaletteItem(
                    title="改动: 刷新改动列表与状态",
                    category="改动",
                    shortcut="Ctrl+R",
                    callback=self._on_refresh_changes_menu_clicked,
                )
            )

        # 视图
        items.append(
            PaletteItem(
                title="专注写作模式",
                category="视图",
                shortcut="F11",
                callback=self.toggle_zen_mode,
            )
        )
        items.append(
            PaletteItem(
                title="切换浅色主题" if self._dark else "切换深色主题",
                category="视图",
                callback=self._toggle_theme,
            )
        )

        # 常用工具
        items.append(
            PaletteItem(
                title="文档互转（Word / PDF / Markdown 等）…",
                category="工具",
                callback=lambda: self._on_convert_documents(),
            )
        )
        items.append(
            PaletteItem(
                title="PDF 工具箱（合并/拆分/水印/加密等）…",
                category="工具",
                callback=lambda: self._on_pdf_toolbox(),
            )
        )

        if self._project_summary:
            items.append(
                PaletteItem(
                    title="打开 Markdown 正文目录",
                    category="目录",
                    callback=self._on_open_content,
                )
            )
            items.append(
                PaletteItem(
                    title="打开输出目录 output/",
                    category="目录",
                    callback=self._on_open_output,
                )
            )
            items.append(
                PaletteItem(
                    title="打开日志目录 logs/",
                    category="目录",
                    callback=self._on_open_logs,
                )
            )
            items.append(
                PaletteItem(
                    title="项目设置…",
                    category="设置",
                    callback=self._on_project_settings,
                )
            )

            # 编辑器联动命令
            ws = getattr(self, "_content_workspace", None)
            if ws is not None:
                editor = ws.current_editor()
                if editor is not None:
                    items.append(
                        PaletteItem(
                            title="美化对齐当前表格",
                            category="编辑",
                            shortcut="Ctrl+Alt+T",
                            callback=editor.format_table_at_cursor,
                        )
                    )
                    items.append(
                        PaletteItem(
                            title="插入表格骨架",
                            category="编辑",
                            callback=editor._insert_table,
                        )
                    )
                    items.append(
                        PaletteItem(
                            title="打开 Mermaid 图形工作台",
                            category="编辑",
                            callback=editor.open_mermaid_workbench,
                        )
                    )
                    items.append(
                        PaletteItem(
                            title="代码片段管理器",
                            category="编辑",
                            callback=editor.open_snippet_manager,
                        )
                    )
                items.append(
                    PaletteItem(
                        title="全文搜索 (Search)",
                        category="搜索",
                        callback=self._on_content_search,
                    )
                )
                items.append(
                    PaletteItem(
                        title="全局替换 (Replace)",
                        category="搜索",
                        callback=self._on_content_replace,
                    )
                )
                items.append(
                    PaletteItem(
                        title="重构与重命名 (Refactor)",
                        category="编辑",
                        callback=self._on_content_refactor,
                    )
                )
                items.append(
                    PaletteItem(
                        title="运行正文检查 (Lint)",
                        category="质量",
                        callback=self._on_content_lint,
                    )
                )

        items.append(
            PaletteItem(
                title="关于 Doc Tool / 环境诊断",
                category="帮助",
                shortcut="F1",
                callback=self._on_about,
            )
        )

        dlg = CommandPaletteDialog(items, mode="command", dark=self._dark, parent=self)
        dlg.exec()

    def open_quick_open(self) -> None:
        """打开章节快速跳转 (Ctrl+P)。"""
        if not self._project_summary:
            self.open_command_palette()
            return

        from doc_tool.ui.command_palette import CommandPaletteDialog, PaletteItem

        items: List[PaletteItem] = []
        c_root = self._project_summary.paths.content_root

        if c_root.exists():
            for p in sorted(c_root.rglob("*.md")):
                rel = p.relative_to(c_root).as_posix()
                if "/." in ("/" + rel):
                    continue
                title = rel
                try:
                    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for line in lines[:5]:
                        s = line.strip()
                        if s.startswith("#"):
                            title = s.lstrip("#").strip()
                            break
                except OSError:
                    pass

                def make_cb(target_rel: str):
                    return (
                        lambda: self._content_workspace.open_file(target_rel)
                        if self._content_workspace
                        else None
                    )

                items.append(
                    PaletteItem(
                        title=title,
                        category="章节",
                        shortcut=rel,
                        description=rel,
                        callback=make_cb(rel),
                    )
                )

        dlg = CommandPaletteDialog(items, mode="file", dark=self._dark, parent=self)
        dlg.exec()

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
            if hasattr(self, "_branch_btn"):
                self._branch_btn.setVisible(False)
            self._set_git_menu_enabled(False)
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
        if hasattr(self, "_open_new_action"):
            self._open_new_action.setEnabled(not running)
        self._validate_action.setEnabled(state.actions["validate"].enabled)
        self._merge_action.setEnabled(state.actions["merge"].enabled)
        self._diag_action.setEnabled(state.actions["diag_build"].enabled)
        self._report_action.setEnabled(state.actions["report"].enabled)
        self._content_action.setEnabled(state.actions["content"].enabled)
        self._output_action.setEnabled(state.actions["output"].enabled)
        self._logs_action.setEnabled(state.actions["logs"].enabled)
        self._settings_action.setEnabled(bool(self._project_summary) and not running)
        self._reimport_action.setEnabled(bool(self._project_summary) and not running)
        if hasattr(self, "_close_action"):
            self._close_action.setEnabled(bool(self._project_summary) and not running)

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
        self._save_all_action.setEnabled(workspace_ready and writable)
        if hasattr(self, "_refresh_changes_action"):
            self._refresh_changes_action.setEnabled(bool(self._content_workspace) and not running)

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

        # 未保存保护：当前工作区存在脏标签时先确认；取消则中止打开新项目。
        if not self._confirm_switch_project():
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.finish()
            return
        # 保存旧项目会话（在旧工作区销毁前收集）。
        self._persist_workspace_session()

        if hasattr(self, "_loading_overlay"):
            if not self._loading_overlay.isVisible():
                self._loading_overlay.start(summary.project_root.name, "正在准备工作区…")
            else:
                self._loading_overlay.show_stage("正在准备工作区…")
            QApplication.processEvents()

        self._project_summary = summary
        self._word_available = None
        self._result_state = ResultState(project_root=summary.project_root)
        self._stage_events = []
        self._pending_session = self._load_session_state(summary)

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
        self._restore_window_session()
        self._refresh_recent_projects()
        self._task_dock.show_idle(None, project_open=True)
        self._refresh_interaction_state()
        try:
            from doc_tool.application.content.reimport import ReimportService
            if ReimportService(summary.manifest, summary.paths).source_changed():
                self._status_label.setText("检测到源 Word 已变化，可从工具菜单重新导入")
        except (OSError, AttributeError):
            pass

    def _open_project_path(self, path: str) -> None:
        if self.runner.is_running:
            return
        # 重复打开保护：同一项目已在其它窗口打开 → 激活已有窗口。
        registry = self._window_registry
        if registry is not None:
            existing = registry.window_for_project(path)
            if existing is not None and existing is not self:
                self._activate_window(existing)
                return

        proj_name = Path(path).name
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.start(proj_name, "正在解析项目配置与元数据…")
            QApplication.processEvents()

        from doc_tool.application.project_service import open_project
        from doc_tool.domain.errors import DocToolError

        try:
            summary = open_project(path)
        except DocToolError as exc:
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.finish()
            self._show_error("打开项目失败", exc.user_message, exc.suggested_action)
            return
        except Exception as exc:  # noqa: BLE001
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.finish()
            self._show_error("打开项目失败", str(exc)[:200])
            return
        self.show_project(summary)
        self._append_log("已打开项目：{0}".format(summary.project_root.name))

    def _on_open_recent(self, path: str) -> None:
        """最近项目点击：在新窗口打开，不在当前窗口切换项目。

        菜单「最近打开」与空状态「最近项目」按钮都经此回调；
        重复打开保护（同一项目已在其它窗口打开 → 激活已有窗口）由
        ``_open_project_in_new_window`` 承担。
        """
        self._open_project_in_new_window(path)

    # --- 内容工作区 ---

    def _init_content_workspace(self, summary) -> None:
        """打开项目后创建/重建内容工作区并摆放各 Dock。"""
        from doc_tool.ui.content.workspace import ContentWorkspace

        # 清空旧的左侧/底部 Dock 容器
        self._remove_content_docks()
        if self._content_workspace is not None:
            try:
                # 先停止旧工作区的索引任务与轮询，避免其迟到回调污染新项目。
                self._content_workspace.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._content_workspace.deleteLater()
            except Exception:  # noqa: BLE001
                pass
            self._content_workspace = None

        self._content_index_ready = False
        self._content_current_file = None
        self._content_workspace = ContentWorkspace(
            summary.paths.content_root,
            project_root=summary.project_root,
            state_dir=summary.paths.state_dir,
            assets_root=summary.paths.assets_root,
            writable=summary.is_writable,
            on_status=lambda msg: self._status_label.setText(msg),
            on_open_file=self._on_content_open_file,
            on_request_validate=self._on_content_request_validate,
            on_index_ready=self._on_content_index_ready,
            on_branch_changed=self._on_branch_changed,
            on_stage=lambda s: self._loading_overlay.show_stage(s) if hasattr(self, "_loading_overlay") else None,
            unsaved_resolver=self._unsaved_resolver,
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
        QTimer.singleShot(0, self._update_git_branch_ui)

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
        self._update_git_branch_ui()
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.finish()

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
        # 编辑器聚焦时 Ctrl+F 走文件内查找，否则走全局搜索
        if self._content_editor_has_focus():
            self._content_workspace.focus_in_editor_find()
            return
        self._show_panels_dock()
        self._content_workspace.focus_search()

    def _content_editor_has_focus(self) -> bool:
        """判断当前焦点是否在中心编辑器（EditorPanel）或其子控件上。"""
        from doc_tool.ui.content.editor_panel import EditorPanel

        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, EditorPanel):
                return True
            widget = widget.parentWidget()
        return False

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

    def _on_open_project_new_window(self) -> None:
        """「在新窗口打开项目…」：项目已打开则激活已有窗口。"""
        if self.runner.is_running:
            return
        path = QFileDialog.getExistingDirectory(self, "选择项目目录（新窗口）")
        if path:
            self._open_project_in_new_window(path)

    def _open_project_in_new_window(self, path: str) -> None:
        """在新窗口打开项目：同一项目已在其它窗口打开时，激活已有窗口。

        不允许两个可写窗口无保护地同时打开同一项目（需求第十一条）；
        窗口级任务锁（build/validate）继续作为第二道防线。
        """
        if self.runner.is_running:
            return
        registry = self._window_registry
        if registry is None or self._window_factory is None:
            # 单窗口环境（测试/无注册表）：退回当前窗口打开。
            self._open_project_path(path)
            return
        existing = registry.window_for_project(path)
        if existing is not None:
            if existing is not self:
                # 其它窗口已打开同一项目：激活已有窗口，不新建可写窗口。
                self._activate_window(existing)
            else:
                self.raise_()
                self.activateWindow()
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
        new_window = self._window_factory()
        new_window.show_project(summary)
        new_window.show()
        new_window.raise_()
        new_window.activateWindow()

    def _activate_window(self, window) -> None:
        """激活已有窗口并提示（重复打开保护）。"""
        try:
            window.show()
            window.raise_()
            window.activateWindow()
        except RuntimeError:
            return
        self._status_label.setText("该项目已在另一个窗口打开，已切换到该窗口")

    # --- 任务执行 ---

    def _check_output_file_locked_and_prompt(self, target_output: Optional[Path]) -> bool:
        """检查目标产物是否正被其他程序（如 Word）独占打开锁定；若是则弹窗提示用户关闭，返回 True 表示需要中止/无法继续。"""
        if target_output is None or not target_output.is_file():
            return False

        def _is_locked(path: Path) -> bool:
            try:
                with open(path, "r+b"):
                    pass
                return False
            except (PermissionError, OSError):
                return True

        if not _is_locked(target_output):
            return False

        # 文件被占用，循环提示用户关闭
        while _is_locked(target_output):
            reply = QMessageBox.warning(
                self,
                "目标文件正被占用",
                "目标文档「{0}」当前正被 Microsoft Word 或其他程序打开，无法写入覆盖。\n\n"
                "请先在 Word 中保存并关闭该文档，然后点击「重试」；或点击「取消」放弃本次构建。".format(
                    target_output.name
                ),
                QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Retry,
            )
            if reply != QMessageBox.StandardButton.Retry:
                return True

        return False

    def _run_source_content_check(self, summary, config: Optional[dict] = None) -> None:
        """本地无 Word 产物时的源码与结构检查（不依赖 Word 产物，绝不阻断）。"""
        from doc_tool.adapters.kernel import ensure_kernel_importable, config_from_project

        def _do_check(manifest, paths):
            ensure_kernel_importable()
            from docx_common import validate_content_tree

            cfg = config or config_from_project(manifest, paths)
            tree_errors = []
            try:
                validate_content_tree(cfg)
            except Exception as exc:  # noqa: BLE001
                tree_errors.append(str(exc))

            # 术语与质量规则检查
            err_issues = []
            warn_issues = []
            try:
                from doc_tool.application.content.index import ContentIndexService
                from doc_tool.application.content.lint import ContentLinter, TermStore
                from doc_tool.application.content.quality_rules import QualityRulesConfig

                state_dir = paths.state_dir
                content_root = paths.resolve(manifest.relative_content_root())
                index = ContentIndexService(content_root).build()
                q_config = QualityRulesConfig(state_dir, manifest.documentType, writable=False)
                issues = ContentLinter(index, q_config).check_all(TermStore(state_dir).load())
                err_issues = [iss for iss in issues if iss.severity == "error"]
                warn_issues = [iss for iss in issues if iss.severity == "warning"]
            except Exception:
                pass

            report_lines = [
                "# {0} 源码与结构检查报告".format(manifest.documentName or manifest.documentType),
                "",
                "- 检查模式: **Markdown 源码与结构检查（本地无 Word 产物）**",
                "- 项目路径: `{0}`".format(paths.root),
                "",
                "## 校验结果",
            ]
            if not tree_errors:
                report_lines.append("- [PASS] 目录层次、编号连续性与资源引用完整")
            else:
                for err in tree_errors:
                    report_lines.append("- [FAIL] 目录结构/资源引用错误: {0}".format(err))

            if not err_issues:
                report_lines.append("- [PASS] 质量规则检查通过（{0} 个提示）".format(len(warn_issues)))
            else:
                for iss in err_issues[:10]:
                    rel = getattr(iss, "rel_path", getattr(iss, "file", ""))
                    line = getattr(iss, "line_no", getattr(iss, "line", 0))
                    report_lines.append("- [FAIL] [{0}] {1}:{2} {3}".format(iss.rule_id, rel, line, iss.message))

            report_lines.extend(["", "## 关键指标", ""])
            report_lines.append("- 结构错误: {0}".format(len(tree_errors)))
            report_lines.append("- 质量错误: {0}".format(len(err_issues)))
            report_lines.append("- 质量警告: {0}".format(len(warn_issues)))

            passes = (1 if not tree_errors else 0) + (1 if not err_issues else 0)
            fails = (len(tree_errors) if tree_errors else 0) + len(err_issues)
            report_lines.extend(["", "## 总结", "", "- PASS: {0}".format(passes), "- FAIL: {0}".format(fails)])
            report_lines.append("- 结论: **{0}**".format("通过" if fails == 0 else "失败"))

            report_path = paths.logs_dir / "{0}-validation.md".format(manifest.documentType)
            paths.logs_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
            return fails == 0

        self._stage_progress_enabled = False
        spec = TaskSpec(
            name="validate",
            target=_do_check,
            args=(summary.manifest, summary.paths),
            timeout_seconds=TASK_UI["validate"]["timeout"],
        )
        self._start_task(spec)
        self._append_log("ℹ 提示：本地尚未生成 Word 产物，已自动执行【Markdown 源码与结构检查】。")

    def _on_validate(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        summary = self._project_summary
        from doc_tool.adapters.kernel import (
            config_from_project,
            ensure_kernel_importable,
            validate_with_project,
        )

        try:
            ensure_kernel_importable()
        except Exception as exc:  # noqa: BLE001
            self._show_error("内核不可用", str(exc)[:200])
            return

        try:
            config = config_from_project(summary.manifest, summary.paths)
            target_output = Path(config["paths"]["output"])
        except Exception:
            config = None
            target_output = None

        # 查找目标 Word 产物或本地已有生成的产物
        effective_output: Optional[Path] = None
        using_fallback_output = False
        if target_output is not None and target_output.exists():
            effective_output = target_output
        elif summary.paths.output_dir.is_dir():
            # 查找同输出目录下的已有 docx 产物（排除临时文件与备份）
            existing_docxs = sorted(
                [p for p in summary.paths.output_dir.glob("*.docx") if not p.name.startswith(".")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if existing_docxs:
                effective_output = existing_docxs[0]
                using_fallback_output = True

        # 如果存在可比对的 Word 产物（无论是精确版本还是本地已有产物）
        if effective_output is not None and effective_output.is_file():
            # 检查源 Markdown 是否在产物生成后被修改过
            stale_notice = False
            try:
                content_root = summary.paths.resolve(summary.manifest.relative_content_root())
                if content_root.is_dir():
                    md_files = [p for p in content_root.glob("**/*.md") if p.is_file()]
                    if md_files:
                        latest_md_mtime = max(p.stat().st_mtime for p in md_files)
                        output_mtime = effective_output.stat().st_mtime
                        if latest_md_mtime > output_mtime:
                            stale_notice = True
            except Exception:
                pass

            self._stage_progress_enabled = TASK_UI["validate"]["stage_progress"]
            # 若使用的是 fallback 已有产物，通过 output_override 传入
            kwargs = {}
            if using_fallback_output:
                kwargs["output_override"] = str(effective_output)
            spec = TaskSpec(
                name="validate",
                target=validate_with_project,
                args=(summary.manifest, summary.paths),
                kwargs=kwargs,
                timeout_seconds=TASK_UI["validate"]["timeout"],
            )
            self._start_task(spec)
            if using_fallback_output:
                self._append_log(
                    "ℹ 提示：未检测到与当前版本完全同名的产物（{0}），已自动选用本地最新已有产物「{1}」进行比对检查。".format(
                        target_output.name if target_output else "指定版本",
                        effective_output.name,
                    )
                )
            if stale_notice:
                self._append_log(
                    "⚠ 提示：检测到源 Markdown 的修改时间晚于当前校验产物。当前校验基于磁盘已有产物；若需验证最新改动，请先执行「快速构建」或「正式出稿」。"
                )
            return

        # 若本地完全未生成任何 Word 产物，执行纯 Markdown 源码与结构检查，不阻断用户！
        self._run_source_content_check(summary, config)

    def _on_merge(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        self._pending_publish_skip_note = None
        summary = self._project_summary
        from doc_tool.adapters.kernel import config_from_project, ensure_kernel_importable
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.application.word_check import check_word_available

        # 产物被占用探针（防止 Windows 下 Word 打开导致写入失败）
        try:
            cfg = config_from_project(summary.manifest, summary.paths)
            target_output = Path(cfg["paths"]["output"])
            if self._check_output_file_locked_and_prompt(target_output):
                return
        except Exception:
            pass

        report = check_word_available(dispatch_check=False)
        self._word_available = bool(report.available)
        self._refresh_interaction_state()
        if not report.available:
            reasons = "\n".join("  • {0}".format(r) for r in report.reasons) or "  • 未知原因"
            self._show_error(
                "Microsoft Word 不可用",
                "正式出稿需要本机交互式会话中的 Microsoft Word。",
                "请改用「操作 → 快速构建（无 Word）」，或在安装 Microsoft Word 的电脑上执行正式出稿。\n"
                "原因：\n{0}".format(reasons),
            )
            return
        revision_version = self._revision_record_version()
        if not self._confirm_pre_publish_checks(revision_version):
            return
        try:
            ensure_kernel_importable()
        except Exception as exc:  # noqa: BLE001
            self._show_error("内核不可用", str(exc)[:200])
            return
        # 前置检查已过、Word 与内核均可用：此时才把「跳过检查」标注写入发布说明，
        # 保证不会因后续中止留下未发布却标注跳过的陈旧审计记录。
        if getattr(self, "_pending_publish_skip_note", None):
            note = self._pending_publish_skip_note
            summary.manifest.publishNotes = (summary.manifest.publishNotes + "\n" + note).strip()
            try:
                summary.manifest.save(summary.project_root, backup=True)
            except Exception:
                pass
        self._stage_progress_enabled = TASK_UI["merge"]["stage_progress"]
        spec = TaskSpec(
            name="merge",
            target=run_pipeline,
            args=(summary.manifest, summary.paths),
            kwargs={
                "skip_word_refresh": False,
                "progress": self._progress_callback(),
            },
            timeout_seconds=TASK_UI["merge"]["timeout"],
        )
        self._start_task(spec)

    def _revision_record_version(self) -> Optional[str]:
        """``_revision_record.md`` 末行版本号（发布前检查用），取不到返回 None。

        修订记录由作者手工维护，末行即本次要发布的版本；管线会在锁内把它同步
        到 ``documentVersion``。这里只是让发布前检查按「即将发布的版本号」比对
        冻结基线，避免清单里的旧版本号让检查结论对不上。只读且不写盘：文件
        缺失/表里还没有数据行时返回 None，检查退回清单现有版本号。
        """
        summary = self._project_summary
        if summary is None:
            return None
        try:
            from doc_tool.application.content.revision_record import (
                document_version_from_record,
            )

            md_path = (
                summary.paths.resolve(summary.manifest.relative_content_root())
                / "_revision_record.md"
            )
            return document_version_from_record(md_path)
        except Exception:  # noqa: BLE001
            return None

    def _confirm_pre_publish_checks(self, proposed_version: Optional[str] = None) -> bool:
        """Show the required pre-publish checklist and return whether to continue.

        全量 lint 扫描在后台线程执行（大项目可能数秒）：旧实现在 UI 线程同步
        扫描全部章节文件，期间主窗口冻结无进度。后台线程计算期间显示模态进度
        对话框，UI 保持响应；其余快速项在同一线程内一并计算。
        """
        import threading
        import time

        from PySide6.QtWidgets import QProgressDialog

        summary = self._project_summary
        workspace = self._content_workspace
        if summary is None or workspace is None:
            return False
        if workspace.index() is None:
            QMessageBox.information(
                self,
                "内容索引未就绪",
                "内容索引仍在构建中，请稍候再执行正式合并。",
            )
            return False
        manifest = summary.manifest
        state_dir = summary.paths.state_dir
        index = workspace.index()
        holder: dict = {}

        def compute() -> None:
            from doc_tool.application.content.baselines import pre_publish_checks
            from doc_tool.application.content.lint import ContentLinter, TermStore
            from doc_tool.application.content.quality_rules import QualityRulesConfig
            from doc_tool.application.content.writer import ChangeManifest
            from doc_tool.application.review.review_store import ReviewStore

            try:
                config = QualityRulesConfig(state_dir, manifest.documentType, writable=False)
                quality_errors = sum(
                    issue.severity == "error"
                    for issue in ContentLinter(index, config).check_all(
                        TermStore(state_dir).load()
                    )
                )
                review_store = ReviewStore(state_dir)
                baseline_versions = [
                    path.stem for path in (state_dir / "baselines").glob("*.json")
                ]
                baseline_version = max(
                    baseline_versions,
                    key=lambda value: tuple(
                        int(part) for part in value.split(".") if part.isdigit()
                    ),
                    default=None,
                )
                pending_changes = ChangeManifest(state_dir).entry_count()
                holder["checks"] = pre_publish_checks(
                    quality_errors=quality_errors,
                    unresolved_reviews=review_store.unresolved_count,
                    current_version=proposed_version or manifest.documentVersion,
                    baseline_version=baseline_version,
                    pending_changes=pending_changes,
                )
                holder["review_store"] = review_store
            except Exception as exc:  # noqa: BLE001
                # 线程内异常必须传回主线程：吞掉会静默显示空清单并放行合并。
                holder["error"] = exc

        dialog = QProgressDialog("正在检查发布前置条件…", "", 0, 0, self)
        dialog.setWindowTitle("发布前检查")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()
        thread = threading.Thread(target=compute, daemon=True)
        thread.start()
        try:
            while thread.is_alive():
                QApplication.processEvents()
                time.sleep(0.05)
        finally:
            dialog.close()

        error = holder.get("error")
        if error is not None:
            QMessageBox.warning(
                self,
                "发布前检查失败",
                "无法完成发布前检查：{0}".format(error),
            )
            return False
        checks = holder.get("checks", [])
        review_store = holder.get("review_store")
        lines = ["{0} {1}".format("✓" if item.passed else "✗", item.message) for item in checks]
        failed = [item for item in checks if not item.passed]
        if not failed:
            QMessageBox.information(self, "发布前检查", "\n".join(lines))
            return True
        answer = QMessageBox.warning(
            self,
            "发布前检查存在阻断项",
            "\n".join(lines) + "\n\n是否跳过检查并继续发布？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes and review_store is not None:
            from doc_tool.application.review.review_store import approval_gate

            gate = approval_gate(review_store.comments(), review_store.signoffs(), skip=True)
            note = gate.history_note or "跳过检查清单"
            # 不立即写入 project.yml：合并还可能因 Word 不可用/内核加载失败而中止，
            # 此时落盘会留下「未发布却标注跳过」的陈旧记录。仅暂存，待合并真正
            # 启动前再写入发布说明，供本次发布的历史归档记录。
            self._pending_publish_skip_note = note
            return True
        return False

    def _on_diag_build(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        summary = self._project_summary
        from doc_tool.adapters.kernel import config_from_project, ensure_kernel_importable
        from doc_tool.application.pipeline import run_pipeline

        # 产物被占用探针（防止 Windows 下 Word 打开导致写入失败）
        try:
            cfg = config_from_project(summary.manifest, summary.paths)
            target_output = Path(cfg["paths"]["output"])
            if self._check_output_file_locked_and_prompt(target_output):
                return
        except Exception:
            pass

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
        self._hide_output_capsules()
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
        initial_steps = []
        if spec.name in ("merge", "diag_build"):
            from doc_tool.application.pipeline import (
                PIPELINE_STAGE_LABELS,
                PIPELINE_STAGE_ORDER,
            )
            initial_steps = [
                StepItem(
                    stage=stage,
                    label=PIPELINE_STAGE_LABELS.get(stage, stage),
                    status=STEP_STATUS_PENDING,
                )
                for stage in PIPELINE_STAGE_ORDER
            ]
        self._task_dock.show_running(
            self._task_label(spec.name),
            steps=initial_steps,
            current_stage="",
            elapsed=0,
        )
        if initial_steps:
            self._task_dock._step_footer.set_progress(0, len(initial_steps))
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
        elif status == "warning":
            self._append_log("⚠ {0} 警告：{1}".format(label, detail))
        elif status == "succeeded":
            self._append_log("✓ {0} 完成".format(label))
        elif status == "failed":
            self._append_log("✗ {0} 失败：{1}".format(label, detail))
        self._render_step_list()

    def _render_step_list(self) -> None:
        steps = derive_step_list(
            self._stage_events, fallback_label=self._task_label(self._current_task)
        )
        if not steps and self.runner.is_running:
            if self._current_task in ("merge", "diag_build"):
                from doc_tool.application.pipeline import (
                    PIPELINE_STAGE_LABELS,
                    PIPELINE_STAGE_ORDER,
                )
                steps = [
                    StepItem(
                        stage=stage,
                        label=PIPELINE_STAGE_LABELS.get(stage, stage),
                        status=STEP_STATUS_PENDING,
                    )
                    for stage in PIPELINE_STAGE_ORDER
                ]
            else:
                steps = [
                    StepItem(
                        stage="",
                        label=self._task_label(self._current_task),
                        status=STEP_STATUS_RUNNING,
                    )
                ]
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
        running_weight = 0.45 if any(s.status == "running" for s in steps) else 0.0
        self._task_dock._step_footer.set_progress(done, len(steps), running_weight=running_weight)

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

        workspace = self._content_workspace
        project = self._project_summary
        if workspace is not None and project is not None:
            report_path = self._validation_report_path()
            workspace.refresh_issues(
                pipeline_events=getattr(result, "events", None),
                document_type=project.manifest.documentType,
                validation_report=(
                    report_path if report_path is not None and report_path.is_file() else None
                ),
            )
            # 失败且有可定位问题时直接把「问题」面板推到前台：双击即可
            # 打开对应 .md 并定位到行，不需要用户自己去找面板。
            if self._result_state.status == "failure" and self._result_state.locations:
                try:
                    workspace.show_issues()
                except Exception:  # noqa: BLE001 - 面板聚焦失败不得影响结果展示
                    pass

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
                self._show_output_capsules(str(output_path))
                if formal:
                    title = "正式出稿成功"
                    summary = "Word 字段已刷新并完成正式输出：{0}".format(output_path)
                    self._status_label.setText("正式出稿成功（Word 已刷新，字段已校验）")
                    self._append_log("✓ 正式输出：{0}".format(output_path))
                else:
                    title = "快速构建完成"
                    summary = "已生成快速预览产物：{0}".format(output_path)
                    self._status_label.setText("快速构建完成（非正式，字段未实机刷新）")
                    self._append_log("△ 快速构建输出：{0}".format(output_path))
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
            locations = format_stage_locations(getattr(result, "events", None))
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
                locations=locations,
            )
            # 出错位置同时写入日志流：用户看到的第一屏就含“哪个文件第几行”。
            for location in locations[:20]:
                self._append_log("  ✗ {0}".format(location))
            if len(locations) > 20:
                self._append_log(
                    "  …共 {0} 处内容问题，完整清单见「问题」面板。".format(len(locations))
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
            status = "项目检查通过" if passed else "项目检查未通过"
            summary = "{0}（PASS={1} FAIL={2}）".format(
                status, report["passCount"], report["failCount"]
            )
            self._status_label.setText(summary)
            self._append_log("校验报告：{0}".format(report_path))
            for failure in report["failures"][:10]:
                self._append_log("  ✗ {0}".format(failure))
        else:
            status = "项目检查通过" if passed else "项目检查未通过"
            summary = status
            self._status_label.setText(status)

        if passed:
            self._result_state = ResultState(
                status="success",
                task=self._current_task,
                title="项目检查通过",
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
                title="项目检查未通过",
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
                    "请先执行「操作 → 快速构建」或「正式出稿」生成输出。",
                )
                return
            self._open_directory_or_warn(out, "输出目录")

    def _on_open_logs(self) -> None:
        if self._project_summary:
            self._open_directory_or_warn(
                self._project_summary.paths.logs_dir, "日志目录", create=True
            )

    def _on_project_settings(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        from doc_tool.ui.settings_dialog import SettingsDialog

        summary = self._project_summary
        dialog = SettingsDialog(
            summary.manifest,
            summary.project_root,
            writable=summary.is_writable,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            summary.manifest = dialog.manifest
            self._project_bar.render(summary, self._workbench_state)
            self._status_label.setText("项目设置已保存")

    def _on_reimport_source(self) -> None:
        if not self._project_summary or not self._project_summary.is_writable:
            return
        source, _ = QFileDialog.getOpenFileName(self, "选择更新后的源 Word", "", "Word 文档 (*.docx)")
        if not source:
            return
        from doc_tool.application.content.reimport import ReimportService
        service = ReimportService(self._project_summary.manifest, self._project_summary.paths)
        result = service.reimport(Path(source))
        if not result.success:
            self._show_error("重新导入失败", result.message, result.error_code)
            return
        if self._content_workspace is not None:
            self._content_workspace._rebuild_index()
        detail = "已合入 {0} 个章节变更。".format(sum(item.status != "unchanged" for item in result.changes))
        if result.conflicts:
            detail += "\n{0} 个冲突章节默认保留本地内容。".format(len(result.conflicts))
        QMessageBox.information(self, "重新导入完成", detail)

    def _on_convert_documents(
        self,
        paths_or_target: Optional[object] = None,
        target_format: Optional[str] = None,
    ) -> None:
        """文档互转：处理任意文件（Word/PDF/Markdown），无需打开项目。

        工具菜单、首页互转卡与首页拖放共用此入口；拖放路径（文件夹由
        ``ConvertDialog._ingest_paths`` 展开一层）在打开对话框前填入清单。
        """
        from doc_tool.ui.convert_dialog import ConvertDialog

        paths = None
        target = target_format
        if isinstance(paths_or_target, str):
            target = paths_or_target
        elif isinstance(paths_or_target, (list, tuple, set)):
            paths = list(paths_or_target)
        elif isinstance(paths_or_target, Path):
            paths = [paths_or_target]

        dialog = ConvertDialog(parent=self, busy_check=lambda: self.runner.is_running)
        try:
            if target and hasattr(dialog, "_format_combo"):
                idx = dialog._format_combo.findData(target)
                if idx >= 0:
                    dialog._format_combo.setCurrentIndex(idx)
            if paths:
                dialog._ingest_paths(list(paths))
            dialog.exec()
        finally:
            if hasattr(dialog, "deleteLater"):
                dialog.deleteLater()

    def _on_pdf_toolbox(
        self,
        paths_or_tool_id: Optional[object] = None,
        tool_id: Optional[str] = None,
    ) -> None:
        """PDF 工具箱：页面组织、转换、编辑与安全优化（无需打开项目）。"""
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog

        paths = None
        target_tool = tool_id
        if isinstance(paths_or_tool_id, str):
            target_tool = paths_or_tool_id
        elif isinstance(paths_or_tool_id, (list, tuple, set)):
            paths = list(paths_or_tool_id)
        elif isinstance(paths_or_tool_id, Path):
            paths = [paths_or_tool_id]

        dialog = PdfToolboxDialog(parent=self, busy_check=lambda: self.runner.is_running)
        try:
            if target_tool and hasattr(dialog, "select_tool"):
                dialog.select_tool(target_tool)
            if paths:
                dialog._ingest_paths(list(paths))
            dialog.exec()
        finally:
            if hasattr(dialog, "deleteLater"):
                dialog.deleteLater()

    def _on_remove_recent(self, path: str) -> None:
        """从最近项目列表中移除条目并刷新界面。"""
        from doc_tool.application.project_service import remove_recent_project

        remove_recent_project(path)
        self._refresh_recent_projects()

    @property
    def project(self):
        """兼容属性：返回当前打开的项目摘要（若无则为 None）。"""
        return self._project_summary

    @project.setter
    def project(self, val) -> None:
        self._project_summary = val

    def close_project(self) -> bool:
        """关闭当前项目，保存必要状态后返回首页任务页。"""
        if self.project is None:
            return True
        if bool(self.runner.is_running):
            QMessageBox.warning(
                self,
                "任务执行中",
                "当前有任务正在执行中，请等待任务完成或先取消任务后再关闭项目。",
            )
            return False
        if not self._confirm_switch_project():
            return False
        self._persist_workspace_session()
        self._remove_content_docks()
        if self._content_workspace is not None:
            try:
                self._content_workspace.shutdown()
            except Exception:
                pass
            try:
                self._content_workspace.deleteLater()
            except Exception:
                pass
            self._content_workspace = None
        self.project = None
        self._project_summary = None
        self._refresh_interaction_state()
        self._refresh_recent_projects()
        return True

    def _on_open_help(self) -> None:
        """打开《使用说明》帮助文档（系统默认程序）；缺失时给出可见提示。"""
        help_path = Path(__file__).resolve().parents[2] / "docs" / "使用说明.md"
        if not help_path.is_file():
            self._show_error(
                "帮助文档不存在",
                "未找到帮助文档：{0}".format(help_path),
                "完整源码检出的 docs/ 目录应包含使用说明。",
            )
            return
        if not self._open_file(help_path):
            self._show_error(
                "无法打开帮助文档",
                "系统没有关联程序可打开：{0}".format(help_path),
                "请用文本编辑器手动打开该文件。",
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

    def _show_output_capsules(self, path: str) -> None:
        self._current_output_path = path
        if hasattr(self, "_output_capsules_widget"):
            self._output_capsules_widget.setVisible(True)

    def _hide_output_capsules(self) -> None:
        self._current_output_path = None
        if hasattr(self, "_output_capsules_widget"):
            self._output_capsules_widget.setVisible(False)

    def _locate_file(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            self._show_error("产物不存在", "无法定位文件，文件不存在：{0}".format(p))
            return
        try:
            if os.name == "nt":
                subprocess.Popen(f'explorer.exe /select,"{p.resolve()}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(p)])
            else:
                self._open_directory(p.parent)
        except Exception:
            self._open_directory(p.parent)

    def _copy_output_path(self, path: str) -> None:
        p = str(Path(path).resolve())
        QApplication.clipboard().setText(p)
        self._status_label.setText("✓ 已复制产物路径：{0}".format(Path(path).name))

    def _export_output_to_external(self, source_path: str) -> None:
        src = Path(source_path)
        if not src.is_file():
            self._show_error("产物不存在", "无法导出，源文件不存在：{0}".format(src))
            return
        from PySide6.QtWidgets import QFileDialog
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "另存产物为…",
            src.name,
            "Word 文档 (*.docx);;全部文件 (*.*)",
        )
        if dest:
            try:
                import shutil
                shutil.copy2(str(src), dest)
                self._status_label.setText("✓ 已另存到：{0}".format(Path(dest).name))
                self._append_log("✓ 产物已另存为：{0}".format(dest))
            except Exception as exc:
                self._show_error("另存失败", "无法另存文件：{0}".format(exc))

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
            "validate": "项目检查",
            "merge": "正式出稿",
            "diag_build": "快速构建",
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

    # --- 未保存保护 / 会话持久化 ---

    def _on_save_all(self) -> None:
        """「保存全部」：保存全部脏标签，汇总失败提示。"""
        ws = self._content_workspace
        if ws is None:
            return
        failed = ws.tabs_host.save_all()
        if failed:
            self._show_error(
                "部分保存失败",
                "以下文件保存失败：\n" + "\n".join(failed),
                "请检查文件权限或磁盘状态后重试。",
            )
            return
        self._status_label.setText("已全部保存")

    def _confirm_close_with_unsaved(self) -> bool:
        """退出前未保存保护：返回 True 表示可继续关闭。"""
        ws = self._content_workspace
        tabs_host = getattr(ws, "tabs_host", None) if ws is not None else None
        if tabs_host is None:
            return True
        dirty = collect_unsaved(tabs_host.editors())
        if not dirty:
            return True
        choice = self._unsaved_resolver(dirty, "exit")
        if choice == UnsavedChoice.SAVE:
            failed = tabs_host.save_all()
            if failed:
                # 保存失败中止退出，避免内容丢失。
                self._show_error(
                    "部分保存失败",
                    "以下文件保存失败：\n" + "\n".join(failed),
                )
                return False
            return True
        if choice == UnsavedChoice.DISCARD:
            ws.clear_drafts(dirty)  # 明确放弃 → 清除这些文件的草稿
            return True
        return False  # CANCEL → 中止退出

    def _confirm_switch_project(self) -> bool:
        """切项目前未保存保护：返回 True 表示可打开新项目。"""
        ws = self._content_workspace
        tabs_host = getattr(ws, "tabs_host", None) if ws is not None else None
        if tabs_host is None:
            return True
        dirty = collect_unsaved(tabs_host.editors())
        if not dirty:
            return True
        choice = self._unsaved_resolver(dirty, "switch")
        if choice == UnsavedChoice.SAVE:
            failed = tabs_host.save_all()
            if failed:
                self._show_error(
                    "部分保存失败",
                    "以下文件保存失败：\n" + "\n".join(failed),
                )
                return False
            return True
        if choice == UnsavedChoice.DISCARD:
            ws.clear_drafts(dirty)
            return True
        return False  # CANCEL → 中止项目切换

    def _persist_workspace_session(self) -> None:
        """收集并写入当前项目的工作区会话（Dock/主题/标签/滚动）。"""
        ws = self._content_workspace
        if ws is None:
            return
        try:
            session = ws.collect_session_state(
                theme="dark" if is_dark_theme(QApplication.instance()) else "light",
                dock_visibility=self._dock_visibility(),
                dock_state=self._dock_state(),
            )
            ws.session_store().save(session)
        except Exception:  # noqa: BLE001  # 会话写入失败不影响关闭
            pass

    def _load_session_state(self, summary) -> SessionState:
        try:
            return WorkspaceStateStore(summary.paths.state_dir).load()
        except Exception:  # noqa: BLE001
            return SessionState()

    def _restore_window_session(self) -> None:
        """恢复主题与 Dock 布局/显隐（会话标签由工作区在索引就绪后恢复）。"""
        session = self._pending_session or SessionState()
        self._restore_theme(session.theme)
        self._restore_dock_state(session)

    def _restore_theme(self, theme: str) -> None:
        target_dark = theme == "dark"
        if target_dark != self._dark:
            apply_theme(QApplication.instance(), dark=target_dark)
            self._dark = target_dark
            self._task_dock.set_dark(target_dark)
            self._theme_action.setText(
                "切换浅色主题" if target_dark else "切换深色主题"
            )

    def _restore_dock_state(self, session: SessionState) -> None:
        if session.dock_state:
            try:
                from PySide6.QtCore import QByteArray

                self.restoreState(
                    QByteArray.fromBase64(session.dock_state.encode("utf-8"))
                )
            except Exception:  # noqa: BLE001
                pass
        vis = session.dock_visibility
        for name, dock in self._dock_widgets():
            if dock is not None and name in vis:
                if vis[name]:
                    dock.show()
                else:
                    dock.hide()

    def _dock_widgets(self):
        return (
            ("taskDock", getattr(self, "_task_dock_widget", None)),
            ("chapterTreeDock", getattr(self, "_tree_dock", None)),
            ("panelsDock", getattr(self, "_panels_dock", None)),
        )

    def _dock_visibility(self) -> dict:
        result = {}
        for name, dock in self._dock_widgets():
            if dock is not None:
                result[name] = not dock.isHidden()
        return result

    def _dock_state(self) -> str:
        try:
            return self.saveState().toBase64().data().decode("utf-8")
        except Exception:  # noqa: BLE001
            return ""

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

        # 多窗口时不写全局几何，避免后关窗口覆盖先关窗口的位置。
        registry = self._window_registry
        if registry is not None and registry.count() > 1:
            return
        if self.isMaximized():
            # 最大化态不写回几何，避免覆盖用户期望的「正常态」尺寸。
            save_window_geometry("", True)
            return
        rect = self.geometry()
        geometry = "{0}x{1}+{2}+{3}".format(rect.width(), rect.height(), rect.x(), rect.y())
        save_window_geometry(geometry, False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay") and self._loading_overlay.isVisible():
            self._loading_overlay.setGeometry(self.rect())

    def _finish_close(self) -> None:
        self._close_after_task = False
        try:
            self._persist_geometry()
        except Exception:  # noqa: BLE001
            pass
        self.close()

    # --- Git 分支与工作流 ---

    def _on_branch_changed(self, new_branch: str) -> None:
        """底层分支变更时刷新界面展示。"""
        self._update_git_branch_ui()

    def _update_git_branch_ui(self) -> None:
        """刷新底部状态栏与顶部项目条的分支展示及菜单状态。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            if hasattr(self, "_branch_btn"):
                self._branch_btn.setVisible(False)
            if hasattr(self, "_project_bar"):
                self._project_bar.set_branch("")
            self._set_git_menu_enabled(False)
            return

        try:
            branches, _ = ws.list_branches()
        except Exception:  # noqa: BLE001
            branches = []

        if not branches:
            if hasattr(self, "_branch_btn"):
                self._branch_btn.setVisible(False)
            if hasattr(self, "_project_bar"):
                self._project_bar.set_branch("")
            self._set_git_menu_enabled(False)
            return

        current_b = next((b for b in branches if b.is_current), None)
        if current_b:
            b_name = current_b.name
            u_count = current_b.uncommitted_count
            ahead = current_b.ahead_count
            behind = current_b.behind_count
            badges = []
            if ahead > 0:
                badges.append(f"↑{ahead}")
            if behind > 0:
                badges.append(f"↓{behind}")
            sync_str = (" " + "".join(badges)) if badges else ""
            badge = f" ({u_count})" if u_count > 0 else ""
            btn_text = f"⎇ {b_name}{sync_str}{badge} ▾"
            if hasattr(self, "_branch_btn"):
                self._branch_btn.setText(btn_text)
                self._branch_btn.setToolTip(f"当前 Git 分支：{b_name}{sync_str}{badge}（点击切换分支）")
                self._branch_btn.setVisible(True)
            if hasattr(self, "_project_bar"):
                self._project_bar.set_branch(b_name, u_count, ahead_count=ahead, behind_count=behind)
            self._set_git_menu_enabled(True)
        else:
            if hasattr(self, "_branch_btn"):
                self._branch_btn.setVisible(False)
            if hasattr(self, "_project_bar"):
                self._project_bar.set_branch("")
            self._set_git_menu_enabled(False)

    def _set_git_menu_enabled(self, enabled: bool) -> None:
        for attr in (
            "_switch_branch_action",
            "_new_branch_action",
            "_git_commit_action",
            "_git_push_action",
            "_git_pull_action",
            "_git_stash_action",
            "_git_pop_stash_action",
        ):
            act = getattr(self, attr, None)
            if act is not None:
                act.setEnabled(enabled)

    def _on_switch_branch_clicked(self) -> None:
        """点击状态栏分支胶囊或项目条分支按钮弹出 Codex 风格浮层。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        branches, err = ws.list_branches()
        if not branches:
            QMessageBox.information(self, "分支切换", "当前项目未纳入 Git 仓库或暂无可用的 Git 分支。")
            return

        from doc_tool.ui.content.branch_popover import BranchPopover

        popover = BranchPopover(branches, dark=self._dark, parent=self)
        popover.branch_selected.connect(self._handle_branch_selected)
        popover.create_branch_requested.connect(self._on_new_branch_menu_clicked)
        popover.create_from_branch_requested.connect(self._on_create_branch_from)
        popover.refresh_requested.connect(lambda: self._handle_popover_refresh(popover))
        popover.fetch_requested.connect(lambda: self._handle_popover_fetch(popover))
        popover.delete_branch_requested.connect(lambda b: self._handle_popover_delete_branch(popover, b))
        popover.rename_branch_requested.connect(lambda o, n: self._handle_popover_rename_branch(popover, o, n))

        sender = self.sender()
        anchor = getattr(self, "_branch_btn", None)
        if hasattr(self, "_project_bar") and sender == getattr(self._project_bar, "_branch_btn", None):
            anchor = self._project_bar.branch_anchor()
        popover.show_anchored(anchor)

    def _handle_popover_refresh(self, popover) -> None:
        """刷新分支浮层与界面状态。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        ws._vcs.invalidate_cache()
        branches, _ = ws.list_branches()
        popover.set_branches(branches)
        self._update_git_branch_ui()

    def _handle_popover_fetch(self, popover) -> None:
        """从远端获取最新分支信息（异步执行，带平滑加载动画）。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        popover.set_loading(True, "正在获取远端分支…")

        def _do_fetch():
            return ws.fetch_branches()

        def _on_fetch_done(result):
            popover.set_loading(False)
            ok, err = result
            if not ok:
                QMessageBox.warning(self, "获取远端分支失败", f"拉取分支失败：\n\n{err}")
            else:
                ws._vcs.invalidate_cache()
                branches, _ = ws.list_branches()
                popover.set_branches(branches)
                self._update_git_branch_ui()
                self._status_label.setText("✓ 已从远端同步最新分支列表")

        run_async_operation(
            self,
            _do_fetch,
            title="正在获取远端分支…",
            description="正在执行 git fetch --prune 同步远端分支信息，请稍候…",
            dark=self._dark,
            on_success=_on_fetch_done,
            on_error=lambda exc: (popover.set_loading(False), QMessageBox.warning(self, "获取远端分支失败", f"拉取分支异常：\n\n{exc}")),
        )

    def _handle_popover_delete_branch(self, popover, branch_name: str) -> None:
        """删除本地分支（支持二次确认与强制删除）。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return

        def _execute_delete(force: bool):
            def _do_del():
                return ws.delete_branch(branch_name, force=force)

            def _on_del_done(result):
                ok, err = result
                if not ok:
                    if not force:
                        ans = QMessageBox.question(
                            self,
                            "强制删除分支",
                            f"分支「{branch_name}」包含尚未合并的提交，普通删除失败：\n\n{err}\n\n是否强制删除此分支？",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        if ans == QMessageBox.StandardButton.Yes:
                            _execute_delete(force=True)
                            return
                    else:
                        QMessageBox.warning(self, "删除分支失败", f"强制删除失败：\n\n{err}")
                        return
                else:
                    ws._vcs.invalidate_cache()
                    branches, _ = ws.list_branches()
                    popover.set_branches(branches)
                    self._update_git_branch_ui()
                    self._status_label.setText(f"✓ 已删除本地分支：{branch_name}")

            run_async_operation(
                self,
                _do_del,
                title="正在删除分支…",
                description=f"正在删除本地分支「{branch_name}」，请稍候…",
                dark=self._dark,
                on_success=_on_del_done,
            )

        _execute_delete(force=False)

    def _handle_popover_rename_branch(self, popover, old_name: str, new_name: str) -> None:
        """重命名本地分支。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return

        def _do_rename():
            return ws.rename_branch(old_name, new_name)

        def _on_rename_done(result):
            ok, err = result
            if not ok:
                QMessageBox.warning(self, "重命名分支失败", f"重命名失败：\n\n{err}")
                return
            ws._vcs.invalidate_cache()
            branches, _ = ws.list_branches()
            popover.set_branches(branches)
            self._update_git_branch_ui()
            self._status_label.setText(f"✓ 分支已重命名为：{new_name}")

        run_async_operation(
            self,
            _do_rename,
            title="正在重命名分支…",
            description=f"正在将分支「{old_name}」重命名为「{new_name}」，请稍候…",
            dark=self._dark,
            on_success=_on_rename_done,
        )

    def _on_create_branch_from(self, base_branch: str) -> None:
        """基于指定基准分支新建并切换分支。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        branches, _ = ws.list_branches()
        existing = [b.name for b in branches]

        from doc_tool.ui.content.branch_popover import NewBranchDialog

        dlg = NewBranchDialog(base_branch, existing, dark=self._dark, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_branch = dlg.branch_name
        base = getattr(dlg, "base_branch", base_branch) or base_branch
        if not new_branch:
            return

        def _do_create_and_switch():
            return ws._vcs.switch_branch(new_branch, create=True, base_branch=base)

        def _on_create_done(result):
            ok, err = result
            if not ok:
                QMessageBox.warning(self, "创建分支失败", f"创建并切换分支失败：\n\n{err}")
                return

            # 主线程重载文件与索引
            if hasattr(ws, "tabs_host"):
                for rel in ws.tabs_host.open_rel_paths():
                    ws.tabs_host.reload_file(rel)
            ws._rebuild_index()
            ws._refresh_changes_panel()
            if ws._on_branch_changed is not None:
                ws._on_branch_changed(new_branch)
            if ws._on_status is not None:
                ws._on_status(f"已切换至分支: {new_branch}")

            self._update_git_branch_ui()
            self._status_label.setText(f"✓ 已创建并切换至新分支：{new_branch}")
            self._append_log(f"✓ 已基于「{base}」创建并切换至新分支「{new_branch}」")

        run_async_operation(
            self,
            _do_create_and_switch,
            title="正在创建并切换分支…",
            description=f"正在基于「{base}」创建新分支「{new_branch}」并准备工作区…",
            dark=self._dark,
            on_success=_on_create_done,
        )

    def _handle_branch_selected(self, target_branch: str) -> None:
        """处理选中的目标分支切换（异步安全检出 + 优雅遮罩反馈）。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        cur_branch = ws.current_branch_name()
        if cur_branch and target_branch == cur_branch:
            return

        # 检查未提交改动
        branches, _ = ws.list_branches()
        cur_b = next((b for b in branches if b.is_current), None)
        uncommitted = cur_b.uncommitted_count if cur_b else 0

        did_stash = False
        if uncommitted > 0:
            box = QMessageBox(self)
            box.setWindowTitle("切换分支提示")
            box.setText(
                f"当前工作区有 <b>{uncommitted}</b> 个未提交的文件改动。<br><br>"
                f"直接切换到分支「<b>{target_branch}</b>」可能会因文件冲突导致失败或覆盖修改。<br><br>"
                "请选择处理方式："
            )
            stash_btn = box.addButton("暂存改动并切换 (Stash & Switch)", QMessageBox.ButtonRole.AcceptRole)
            commit_btn = box.addButton("先提交改动 (Commit Changes)", QMessageBox.ButtonRole.ActionRole)
            direct_btn = box.addButton("直接尝试切换 (Direct Checkout)", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()

            clicked = box.clickedButton()
            if clicked == cancel_btn or clicked is None:
                return
            elif clicked == stash_btn:
                ok, err = ws.stash_changes(f"Auto-stash before checkout {target_branch}")
                if not ok:
                    QMessageBox.warning(self, "暂存失败", f"暂存改动失败：\n\n{err}")
                    return
                did_stash = True
            elif clicked == commit_btn:
                self._on_git_commit_menu_clicked()
                return

        def _do_switch_vcs():
            return ws._vcs.switch_branch(target_branch)

        def _on_switch_done(result):
            ok, err = result
            if not ok:
                if did_stash:
                    try:
                        ws.pop_stash()
                    except Exception:
                        pass
                QMessageBox.warning(self, "切换分支失败", f"无法切换到分支「{target_branch}」：\n\n{err}")
                return

            # 主线程重载文件与索引
            if hasattr(ws, "tabs_host"):
                for rel in ws.tabs_host.open_rel_paths():
                    ws.tabs_host.reload_file(rel)
            ws._rebuild_index()
            ws._refresh_changes_panel()
            if ws._on_branch_changed is not None:
                ws._on_branch_changed(target_branch)
            if ws._on_status is not None:
                ws._on_status(f"已切换至分支: {target_branch}")

            self._update_git_branch_ui()
            if did_stash:
                self._status_label.setText(f"✓ 已切换至分支：{target_branch}（未提交改动已安全暂存入栈，可通过 菜单「版本控制」->「弹出暂存」恢复）")
                self._append_log(f"✓ 已切换至分支「{target_branch}」，原分支未提交改动已保存在暂存区（Stash），随时可在顶部菜单「版本控制」->「弹出暂存」中恢复。")
            else:
                self._status_label.setText(f"✓ 已切换至分支：{target_branch}")
                self._append_log(f"✓ 已切换至分支：{target_branch}")

        run_async_operation(
            self,
            _do_switch_vcs,
            title="正在切换分支…",
            description=f"正在检出分支「{target_branch}」并重载工作区，请稍候…",
            dark=self._dark,
            on_success=_on_switch_done,
        )

    def _on_new_branch_menu_clicked(self, initial_name: Any = "") -> None:
        """新建并切换分支对话框。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        cur_branch = ws.current_branch_name()
        branches, _ = ws.list_branches()
        existing = [b.name for b in branches]

        name_str = initial_name if isinstance(initial_name, str) else ""

        from doc_tool.ui.content.branch_popover import NewBranchDialog

        dlg = NewBranchDialog(cur_branch or "HEAD", existing, initial_name=name_str, dark=self._dark, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_branch = dlg.branch_name
        base_branch = getattr(dlg, "base_branch", cur_branch) or cur_branch
        if not new_branch:
            return

        def _do_create_and_switch():
            return ws._vcs.switch_branch(new_branch, create=True, base_branch=base_branch)

        def _on_create_done(result):
            ok, err = result
            if not ok:
                QMessageBox.warning(self, "创建分支失败", f"创建并切换分支失败：\n\n{err}")
                return

            if hasattr(ws, "tabs_host"):
                for rel in ws.tabs_host.open_rel_paths():
                    ws.tabs_host.reload_file(rel)
            ws._rebuild_index()
            ws._refresh_changes_panel()
            if ws._on_branch_changed is not None:
                ws._on_branch_changed(new_branch)
            if ws._on_status is not None:
                ws._on_status(f"已切换至分支: {new_branch}")

            self._update_git_branch_ui()
            self._status_label.setText(f"✓ 已创建并切换至新分支：{new_branch}")
            self._append_log(f"✓ 已基于「{base_branch}」创建并切换至新分支「{new_branch}」")

        run_async_operation(
            self,
            _do_create_and_switch,
            title="正在创建新分支…",
            description=f"正在基于「{base_branch}」创建分支「{new_branch}」并准备工作区…",
            dark=self._dark,
            on_success=_on_create_done,
        )

    def _on_git_commit_menu_clicked(self) -> None:
        """菜单触发提交改动。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        ws.trigger_commit()

    def _on_git_push_menu_clicked(self) -> None:
        """菜单触发推送代码（异步推送 + 状态遮罩反馈）。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        ans = QMessageBox.question(
            self,
            "推送代码",
            "确定要将当前分支的所有本地提交推送到远端仓库吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        def _on_push_done(res):
            if res.ok:
                QMessageBox.information(self, "推送成功", res.summary or "已成功推送到远端仓库！")
                self._update_git_branch_ui()
                self._status_label.setText("✓ " + (res.summary or "已成功推送到远端仓库"))
            else:
                QMessageBox.warning(self, "推送失败", f"推送代码到远端失败：\n\n{res.error}")
                self._status_label.setText(f"推送失败：{res.error}")

        run_async_operation(
            self,
            ws._push_changes,
            title="正在推送代码到远端…",
            description="正在与远端仓库通信并推送本地提交，请稍候…",
            dark=self._dark,
            on_success=_on_push_done,
        )

    def _on_git_pull_menu_clicked(self) -> None:
        """菜单触发拉取更新（异步拉取 + 状态遮罩反馈）。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return
        ans = QMessageBox.question(
            self,
            "拉取更新",
            "将执行 git pull，把远端最新变更合并到当前工作副本。\n\n请先保存所有打开的编辑内容。确认？",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        def _on_pull_done(res):
            if res.conflicts:
                QMessageBox.warning(
                    self,
                    "拉取存在冲突",
                    f"以下 {len(res.conflicts)} 个文件有合并冲突，需要手工解决：\n\n"
                    + "\n".join(res.conflicts),
                )
                self._status_label.setText(f"拉取完成但有 {len(res.conflicts)} 个冲突，需手工解决")
            elif not res.ok:
                first_line = res.error.strip().splitlines()[0] if res.error else "未知错误"
                self._status_label.setText(f"拉取失败：{first_line}")
                is_conflict = (
                    "未提交的改动与远端冲突" in (res.error or "")
                    or "未跟踪的新增文件与远端冲突" in (res.error or "")
                    or "would be overwritten by merge" in (res.error or "")
                    or "将因合并而覆盖" in (res.error or "")
                    or "本地修改将被合并操作覆盖" in (res.error or "")
                    or "未跟踪的工作区文件将被覆盖" in (res.error or "")
                )
                if is_conflict:
                    is_untracked = (
                        "未跟踪" in (res.error or "")
                        or "untracked working tree files" in (res.error or "")
                    )
                    ans = QMessageBox.question(
                        self,
                        "拉取失败 - 本地改动冲突",
                        f"{res.error}\n\n是否尝试「暂存本地改动{'（含未跟踪文件）' if is_untracked else ''}并重新拉取」？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if ans == QMessageBox.StandardButton.Yes:
                        st_ok, st_err = ws.stash_changes(
                            "拉取更新前自动暂存", include_untracked=is_untracked
                        )
                        if st_ok:
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(100, self._on_git_pull_menu_clicked)
                            return
                        else:
                            QMessageBox.warning(self, "暂存失败", f"自动暂存本地改动失败：\n\n{st_err}")
                            return
                else:
                    QMessageBox.warning(self, "拉取失败", f"拉取更新失败：\n\n{res.error}")
            else:
                QMessageBox.information(self, "拉取完成", res.summary or "已拉取最新更新！")
                ws._after_restore()
                self._update_git_branch_ui()
                self._status_label.setText("✓ " + (res.summary or "已拉取最新更新"))

        run_async_operation(
            self,
            ws._pull_changes,
            title="正在拉取远端更新…",
            description="正在执行 git pull 获取最新变更并合并，请稍候…",
            dark=self._dark,
            on_success=_on_pull_done,
        )

    def _on_git_stash_menu_clicked(self) -> None:
        """菜单触发暂存工作区改动。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return

        def _on_stash_done(result):
            ok, err = result
            if ok:
                QMessageBox.information(self, "暂存成功", "当前工作区的全部未提交改动已成功暂存 (git stash)。")
                self._update_git_branch_ui()
                self._status_label.setText("✓ 未提交改动已安全暂存 (git stash)")
            elif err and "没有需要暂存" in err:
                ans = QMessageBox.question(
                    self,
                    "暂存改动",
                    "当前已跟踪文件没有改动。是否包含未跟踪的新增文件一起暂存？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans == QMessageBox.StandardButton.Yes:
                    st_ok, st_err = ws.stash_changes("暂存改动（含未跟踪文件）", include_untracked=True)
                    if st_ok:
                        QMessageBox.information(self, "暂存成功", "当前工作区改动（含未跟踪文件）已成功暂存。")
                        self._update_git_branch_ui()
                        self._status_label.setText("✓ 未提交改动已安全暂存 (git stash)")
                    else:
                        QMessageBox.warning(self, "暂存失败", f"暂存改动失败：\n\n{st_err}")
            else:
                QMessageBox.warning(self, "暂存失败", f"暂存改动失败：\n\n{err}")

        def _do_stash():
            return ws._vcs.stash()

        def _on_stash_success(result):
            ok, err = result
            if ok:
                ws._after_restore()
            _on_stash_done(result)

        run_async_operation(
            self,
            _do_stash,
            title="正在暂存改动…",
            description="正在将工作区未提交的文件改动暂存到栈区，请稍候…",
            dark=self._dark,
            on_success=_on_stash_success,
        )

    def _on_git_pop_stash_menu_clicked(self) -> None:
        """菜单触发恢复暂存改动。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is None:
            return

        def _on_pop_done(result):
            ok, err = result
            if ok:
                QMessageBox.information(self, "恢复暂存成功", "已成功恢复最近一次暂存的改动 (git stash pop)。")
                self._update_git_branch_ui()
                self._status_label.setText("✓ 已恢复最近一次暂存的改动")
            elif err and ("conflict" in err.lower() or "unmerged" in err.lower()):
                self._status_label.setText("恢复暂存时发生冲突，请解决冲突后提交。")
                self._update_git_branch_ui()
                QMessageBox.warning(
                    self,
                    "恢复暂存发生冲突",
                    f"恢复暂存改动时发生文件冲突：\n\n{err}\n\n冲突标记已写入对应文件，暂存记录仍被保留。请解决冲突后提交。",
                )
            else:
                QMessageBox.warning(self, "恢复暂存失败", f"恢复暂存改动失败：\n\n{err}")

        def _do_pop():
            return ws._vcs.pop_stash()

        def _on_pop_success(result):
            ok, err = result
            if ok or (err and ("conflict" in err.lower() or "unmerged" in err.lower())):
                ws._after_restore()
            _on_pop_done(result)

        run_async_operation(
            self,
            _do_pop,
            title="正在恢复暂存…",
            description="正在弹出并应用最近一次暂存的改动，请稍候…",
            dark=self._dark,
            on_success=_on_pop_success,
        )

    def _on_refresh_changes_menu_clicked(self) -> None:
        """菜单或全局快捷键触发刷新改动。"""
        ws = getattr(self, "_content_workspace", None)
        if ws is not None and hasattr(ws, "refresh_changes"):
            ws.refresh_changes()

    def closeEvent(self, event) -> None:
        """任务运行中先请求安全取消，终态回调到达后再关闭窗口。

        未保存保护：存在脏标签时先确认（保存/不保存/取消），取消中止退出；
        退出前持久化工作区会话与窗口几何。
        """
        if not self.runner.is_running:
            if not self._confirm_close_with_unsaved():
                event.ignore()
                return
            self._persist_workspace_session()
            self._persist_geometry()
            # 关闭后从注册表移除：避免已关闭窗口继续占用项目、
            # 也避免重复打开保护命中已关闭窗口。
            self._closed = True
            if self._window_registry is not None:
                self._window_registry.unregister(self)
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
