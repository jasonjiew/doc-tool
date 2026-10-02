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
    "project-export": {
        "label": "导出 Word",
        "stage_progress": False,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "export",
    },
    "delivery-run": {
        "label": "批量交付",
        "stage_progress": False,
        "timeout": DEFAULT_TASK_TIMEOUT_SECONDS,
        "result_type": "delivery",
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
        self._project_summary = None
        self._reset_command_registry()
        self._refresh_registry_menu()  # ProjectSummary
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
        history_btn = QPushButton("交付历史", self)
        history_btn.clicked.connect(self._on_build_history)
        status_bar.addWidget(history_btn)

        self._lock_label = QLabel("", self)
        self._lock_label.setObjectName("statusMuted")
        status_bar.addPermanentWidget(self._lock_label)

        # 中央：空状态 / IDE 布局
        self._stack = QStackedWidget(self)
        self._empty_state = EmptyState(
            on_new_project=self._on_import_document,
            on_open_project=self._on_open_project,
            on_open_recent=self._on_open_recent,
            on_remove_recent=self._on_remove_recent,
            on_relocate_recent=self._on_relocate_recent,
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
        self._import_action = QAction("导入文档（Word / Markdown）…", self)
        self._import_action.setShortcut(QKeySequence("Ctrl+N"))
        self._import_action.setToolTip(
            "自动识别 Word / Markdown 并调用对应建项服务；Markdown 多文件按列表顺序建一份项目"
        )
        self._import_action.triggered.connect(self._on_import_document)
        file_menu.addAction(self._import_action)
        self._new_action = QAction("新建项目（导入向导）…", self)
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
        # CORE-F 6.1：一个快速出稿入口，按钮文案直接说明这次出什么格式。
        self._quick_export_action = QAction("快速导出 Word（整份 / 当前内容）", self)
        self._quick_export_action.setShortcut(QKeySequence("Ctrl+E"))
        self._quick_export_action.setToolTip("默认整份文档 + 当前编辑内容 + Word + 项目导出目录")
        self._quick_export_action.triggered.connect(self._on_quick_export_word)
        ops_menu.addAction(self._quick_export_action)
        # V3.2 32-E：批量交付（持久队列，可续跑/只补未完成项）
        self._delivery_action = QAction("批量交付（持久队列）…", self)
        self._delivery_action.setShortcut(QKeySequence("Ctrl+Alt+B"))
        self._delivery_action.setToolTip("按批次计划串行交付多个项目/变体；中断后可继续，只补未完成项")
        self._delivery_action.triggered.connect(self._on_delivery_batch)
        ops_menu.addAction(self._delivery_action)
        ops_menu.addSeparator()
        self._report_action = QAction("打开校验报告", self)
        self._report_action.triggered.connect(self._on_open_validation_report)
        ops_menu.addAction(self._report_action)

        # 内容
        # 命令注册表菜单（V3.1 4.2 / V3.3 5.3）：与命令面板同源
        self._registry_menu = menubar.addMenu("命令")
        try:
            self._refresh_registry_menu()
        except Exception:  # noqa: BLE001 - 注册表异常不阻断菜单构建
            pass

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
        # V3.3 5.1：资料搜索/建议面板（插入走既有编辑器，可一次撤销）
        self._discard_summary_action = QAction("取消摘要候选", self)
        self._discard_summary_action.setEnabled(False)
        self._discard_summary_action.setToolTip("撤销刚填入修订记录的摘要候选（不写入任何记录）")
        self._discard_summary_action.triggered.connect(self._discard_assist_summary_candidate)
        content_menu.addAction(self._discard_summary_action)
        self._assist_action = QAction("资料搜索与写作建议…", self)
        self._assist_action.setShortcut(QKeySequence("Ctrl+Alt+A"))
        self._assist_action.triggered.connect(self._on_assist_panel)
        content_menu.addAction(self._assist_action)
        # V3.0 6.1/6.2：正文模块库、引用解析与展开副本入口
        self._reuse_action = QAction("正文模块库与引用解析…", self)
        self._reuse_action.setShortcut(QKeySequence("Ctrl+Alt+R"))
        self._reuse_action.triggered.connect(self._on_reuse_dialog)
        content_menu.addAction(self._reuse_action)
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
        html_action = QAction('只读离线 HTML 预览包…', self)
        html_action.triggered.connect(self._on_html_preview)
        tools_menu.addAction(html_action)
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
        self._template_fill_action = QAction("Markdown 模板填充（底模出稿）…", self)
        self._template_fill_action.triggered.connect(lambda: self._on_template_fill())
        tools_menu.addAction(self._template_fill_action)
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
        assist = getattr(self, "_assist_dock", None)
        if assist is not None:
            entries.append(("资料搜索与建议", assist))
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

    # --- V2.8（5.5）三条建项路径的命令面板入口 ---

    INTAKE_FILE_FILTER = (
        "文档 (*.docx *.docm *.dotx *.doc *.md *.markdown);;"
        "Word 文档 (*.docx *.doc *.docm);;"
        "Markdown (*.md *.markdown);;"
        "所有文件 (*)"
    )

    def _on_import_document(self, paths: Optional[object] = None) -> None:
        """导入文档：自动识别 Word/Markdown 并调用对应建项服务（CORE 1.3）。

        路由决定来自 ``doc_tool.application.intake_entries``；本方法只负责
        选文件、把结果打开到工作区，以及已打开项目时走既有差异重导入。
        """
        if self.runner.is_running:
            return
        selected = self._intake_selection(paths)
        if not selected:
            return
        from doc_tool.application.intake_entries import (
            ACTION_PENDING_CONVERT, ACTION_REIMPORT, ACTION_UNSUPPORTED,
            KIND_MARKDOWN, detect_intake_kind, route_for,
        )

        markdown_paths = [item for item in selected if detect_intake_kind(item) == KIND_MARKDOWN]
        others = [item for item in selected if detect_intake_kind(item) != KIND_MARKDOWN]
        if markdown_paths:
            self._create_markdown_project(markdown_paths)
        for item in others:
            route = route_for(item, project_open=bool(self._project_summary))
            if route.action == ACTION_REIMPORT:
                self._reimport_into_current(Path(item))
                continue
            if route.action == ACTION_PENDING_CONVERT:
                QMessageBox.information(
                    self, "待转换",
                    "{0}\n{1}".format(route.reason, route.suggested_action),
                )
                continue
            if route.action == ACTION_UNSUPPORTED:
                QMessageBox.warning(self, "无法导入", route.reason)
                continue
            from doc_tool.ui.wizard import ImportWizard

            wizard = ImportWizard(self, initial_file=str(item))
            wizard._intake_preset_name = str(getattr(self, "_pending_intake_preset", "") or "")
            # 预设只对“下一次导入”生效：交给向导后即清空（复核发现原先会一直粘住）
            self._pending_intake_preset = ""
            result = wizard.run()
            if result is not None:
                self._open_import_result(str(result))

    def _intake_selection(self, paths: Optional[object]) -> List[Path]:
        """把入参（拖放列表/单个路径）归一为文件列表；为空时弹选择框。"""
        if isinstance(paths, (list, tuple, set)):
            candidates = [Path(item) for item in paths]
        elif isinstance(paths, Path):
            candidates = [paths]
        elif isinstance(paths, str) and paths.strip():
            candidates = [Path(paths)]
        else:
            chosen, _selected_filter = QFileDialog.getOpenFileNames(
                self, "导入文档（Word / Markdown）", "", self.INTAKE_FILE_FILTER
            )
            candidates = [Path(item) for item in chosen]
        files: List[Path] = []
        for item in candidates:
            if item.is_dir():
                continue
            if item.is_file():
                files.append(item)
        return files

    def _create_markdown_project(self, markdown_paths: List[Path]) -> None:
        """Markdown 建项：按用户确认顺序调用既有建项服务生成一份项目。"""
        from doc_tool.application.intake_entries import (
            default_project_parent, run_intake,
        )

        outcome = run_intake(
            markdown_paths[0],
            parent_dir=default_project_parent(),
            markdown_sources=list(markdown_paths),
        )
        self._present_intake_outcome(outcome)

    def _present_intake_outcome(self, outcome) -> None:
        """统一展示导入结果：先给可打开项目，再集中提示待完善。"""
        if outcome.ok and outcome.project_root is not None:
            lines = outcome.summary_lines()
            self._show_status_message(lines[0] if lines else "导入完成")
            for item in list(outcome.warnings)[:3]:
                self._show_status_message(item)
            self._open_import_result(str(outcome.project_root))
            return
        detail = "\n".join(outcome.summary_lines() or outcome.errors) or "导入未完成"
        QMessageBox.warning(self, "导入未完成", detail)

    def _open_import_result(self, project_root: str) -> None:
        """打开导入结果：已有工作区时保留当前编辑，在新窗口打开新项目。"""
        if self._project_summary is None:
            self._open_project_path(project_root)
        else:
            self._open_project_in_new_window(project_root)
        # CORE 3.3：结果页先给可打开项目与待完善数量，再给最多 3 个直接动作。
        self._show_intake_result_page(project_root)

    def _show_intake_result_page(self, project_root: str) -> None:
        """展示导入结果页（按类型/章节归并，默认最多 3 项可行动问题）。"""
        from doc_tool.application.intake_result_page import build_result_page

        try:
            page = build_result_page(project_root)
        except Exception:  # noqa: BLE001 - 结果页失败不影响已生成项目
            return
        if not page.needsAttention and not page.unavailableComparisons:
            return
        box = QMessageBox(self)
        box.setWindowTitle("导入结果")
        box.setText("\n".join(page.summary))
        buttons = {}
        for action in page.actions[:3]:
            buttons[box.addButton(action.label, QMessageBox.ButtonRole.ActionRole)] = action
        detail_button = box.addButton("查看全部问题", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is detail_button:
            self._show_intake_details(page)
            return
        action = buttons.get(clicked)
        if action is not None:
            self._run_intake_action(project_root, action)

    def _show_intake_details(self, page) -> None:
        """完整处理事实与自动处理项（不在默认视图中逐项打扰用户）。"""
        lines = list(page.summary)
        lines.append("")
        lines.append("共 {0} 项处理事实（自动处理 {1} 项）".format(
            len(page.details), page.autoHandled,
        ))
        for item in page.details[:40]:
            lines.append("· {0} / {1} / {2}{3}".format(
                item.get("feature", ""), item.get("handling", ""),
                item.get("target_chapter", "") or item.get("source_part", ""),
                ("｜" + str(item.get("detail"))) if item.get("detail") else "",
            ))
        QMessageBox.information(self, "全部问题与自动处理", "\n".join(lines))

    def _run_intake_action(self, project_root: str, action) -> None:
        """执行结果页动作：复用既有资源修复、章节定位与原件查看服务。"""
        from doc_tool.application.intake_result_page import (
            ACTION_REPLACE_IMAGE, ACTION_VIEW_ORIGINAL, replace_placeholder_image,
        )

        if action.kind == ACTION_VIEW_ORIGINAL:
            target = Path(project_root) / (action.retainedPath or "original/source.docx")
            if target.is_file():
                self._on_open_result_output(str(target))
            else:
                self._show_status_message("原件不存在：{0}".format(target))
            return
        if action.kind == ACTION_REPLACE_IMAGE:
            chosen, _selected = QFileDialog.getOpenFileName(
                self, "选择替代图片", "",
                "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*)",
            )
            if not chosen:
                return
            outcome = replace_placeholder_image(
                project_root, action.relPath, chosen, line=action.line,
            )
            self._show_status_message(outcome.summary_line())
            if outcome.ok and getattr(self, "_content_workspace", None) is not None:
                try:
                    self._content_workspace._rebuild_index()
                except Exception:  # noqa: BLE001 - 索引刷新失败不影响已替换的正文
                    pass
            return
        rel_path = action.relPath
        if rel_path and self._open_chapter_in_workspace(rel_path, action.line):
            self._show_status_message("已定位到章节：{0}".format(rel_path))
        else:
            self._show_status_message(
                "请在章节树中定位：{0}".format(action.detail or action.feature or rel_path)
            )

    def _on_create_from_pack(self) -> None:
        """从规范包起步：真实调用 ``create_project_from_pack`` 建立项目。"""
        if self.runner.is_running:
            return
        pack_dir = QFileDialog.getExistingDirectory(self, "选择规范包目录")
        if not pack_dir:
            return
        from doc_tool.application.intake_entries import (
            default_project_parent, plan_target,
        )
        from doc_tool.application.project_from_pack import create_project_from_pack

        target = plan_target(
            Path(pack_dir), parent_dir=default_project_parent(),
            trusted_name=Path(pack_dir).name,
        )
        result = create_project_from_pack(
            pack_dir, target.directory, document_name=target.document_name,
        )
        if not result.ok or result.project_root is None:
            QMessageBox.warning(
                self, "从规范包建项未完成",
                "\n".join(result.errors or result.warnings) or "未知原因",
            )
            return
        self._show_status_message("已从规范包建立项目：{0}".format(Path(result.project_root).name))
        self._open_import_result(str(result.project_root))

    def _on_intake_word(self) -> None:
        """接管现有 Word：自动识别后进入导入向导（含预检与往返门禁）。"""
        self._on_import_document()

    def _on_create_from_markdown(self) -> None:
        """以 Markdown 起步：真实调用 Markdown 建项服务（会建项目）。"""
        if self.runner.is_running:
            return
        chosen, _selected = QFileDialog.getOpenFileNames(
            self, "选择 Markdown 文件（按列表顺序建章节）", "",
            "Markdown (*.md *.markdown);;所有文件 (*)",
        )
        files = [Path(item) for item in chosen if Path(item).is_file()]
        if not files:
            return
        self._create_markdown_project(files)

    def _show_status_message(self, message: str) -> None:
        """在状态栏反馈一行；无状态栏时退化为日志。"""
        bar = getattr(self, "statusBar", None)
        if callable(bar):
            try:
                bar().showMessage(str(message), 6000)
                return
            except Exception:  # noqa: BLE001 - 状态栏不可用时不影响主流程
                pass
        logger.info("ui", "status_message", {"message": str(message)})

    # --- 命令注册表（V3.1 4.2 / V3.3 5.3）：菜单与命令面板同源 ---

    def _command_context(self):
        """当前上下文（项目/可写/空闲/选区/缓冲），供注册表判定可用性。"""
        from doc_tool.application.command_registry import CommandContext

        summary = self._project_summary
        running = bool(getattr(self.runner, "is_running", False))
        has_selection = False
        has_buffer = False
        try:
            editor = self._current_editor()
            if editor is not None:
                cursor = editor.textCursor()
                has_selection = bool(cursor.hasSelection())
                has_buffer = True
        except Exception:  # noqa: BLE001 - 无编辑器时按无选区处理
            pass
        return CommandContext(
            projectOpen=summary is not None,
            writable=bool(summary is not None and getattr(summary, "is_writable", False)),
            running=running,
            hasGit=False,
            hasSelection=has_selection,
            hasBuffer=has_buffer,
            documentType=str(getattr(summary, "document_type", "") or "") if summary else "",
        )

    def _ensure_command_registry(self):
        """惰性构建并注册团队/写作辅助命令（单个模块失败不影响其它入口）。"""
        from doc_tool.application.command_registry import CommandRegistry

        summary = self._project_summary
        root = getattr(summary, "project_root", None) if summary is not None else None
        registry = getattr(self, "_command_registry", None)
        if registry is not None and getattr(self, "_command_registry_root", "") == str(root or ""):
            return registry
        registry = CommandRegistry()
        try:
            from doc_tool.application.command_registry import CONTEXT_IDLE, CommandSpec

            def _intake_presets(_context, payload):
                from doc_tool.application.intake_presets import IntakePresets

                presets = IntakePresets()
                apply_name = str((payload or {}).get("applyPreset") or "").strip()
                if apply_name:
                    preset = presets.find(apply_name)
                    if preset is None:
                        raise ValueError("未找到导入预设：{0}".format(apply_name))
                    self._pending_intake_preset = preset.name
                return {
                    "presets": [
                        {"name": item.name, "presetId": item.presetId, "styles": len(item.mapping)}
                        for item in presets.presets
                    ],
                    "applied": getattr(self, "_pending_intake_preset", ""),
                    "nextActions": [
                        "导入文档时将自动套用所选预设；也可在向导内改用自动识别",
                        "用 import --save-preset 名称 保存新的预设",
                    ],
                }

            registry.register(CommandSpec(
                commandId="intake.presets", title="导入映射预设（查看/套用）", handler=_intake_presets,
                aliases=["intake-presets", "presets"], category="导入",
                description="查看命名样式映射预设，并指定下一次导入套用的预设",
                # 预设是全局的：没有项目也能查看/指定（导入时生效）
                contexts=[CONTEXT_IDLE],
            ))
            self._pending_intake_preset = getattr(self, "_pending_intake_preset", "")
        except Exception:  # noqa: BLE001 - 预设命令注册失败不影响其它入口
            pass
        if root is not None:
            try:
                from doc_tool.application.assist.commands import register_assist_commands
                from doc_tool.application.content.team_entry import register_team_commands

                # 注册函数签名是 (registry, project_root)；没有项目时只保留空注册表，
                # 面板/菜单在打开项目后重新构建即可拿到命令。
                register_team_commands(registry, root)
                register_assist_commands(registry, root)
            except Exception:  # noqa: BLE001 - 单个模块注册失败不影响其它入口
                pass
        self._command_registry = registry
        self._command_registry_root = str(root or "")
        return registry

    def _reset_command_registry(self) -> None:
        """项目切换后重建注册表（命令 handler 绑定项目根）。"""
        self._command_registry = None
        self._command_registry_root = ""

    def _registry_menu_object(self):
        """取「命令」菜单对象；若底层对象已失效则重新挂一个（避免访问已删除的 C++ 对象）。"""
        menu = getattr(self, "_registry_menu", None)
        if menu is not None:
            try:
                import shiboken6

                if shiboken6.isValid(menu):
                    return menu
            except Exception:  # noqa: BLE001 - 无法判定有效性时按需重建
                pass
        try:
            self._registry_menu = self.menuBar().addMenu("命令")
        except Exception:  # noqa: BLE001 - 菜单栏不可用时放弃
            return None
        return self._registry_menu

    def _refresh_registry_menu(self) -> None:
        """按当前项目重建「命令」菜单（无项目时保持为空）。"""
        menu = self._registry_menu_object()
        if menu is None:
            return
        try:
            menu.clear()
            self._registry_menu_refs = []
            self._build_registry_menu(menu)
        except Exception:  # noqa: BLE001 - 刷新失败不改动既有菜单
            pass

    def _registry_palette_items(self):
        """把注册表面板视图转成命令面板条目（点击经注册表派发）。"""
        from doc_tool.ui.command_palette import PaletteItem

        registry = self._ensure_command_registry()
        context = self._command_context()
        items: List[PaletteItem] = []
        for row in registry.palette_items(context):
            reason = str(row.get("reason") or "")
            title = str(row.get("title") or row.get("commandId") or "")
            if not row.get("available") and reason:
                title = "{0}（不可用：{1}）".format(title, reason)
            items.append(PaletteItem(
                title=title,
                category=str(row.get("category") or "命令"),
                shortcut=str(row.get("shortcut") or ""),
                description=str(row.get("description") or row.get("nextAction") or ""),
                payload=row,
                callback=self._make_registry_callback(row),
            ))
        return items

    def _augment_registry_payload(self, row) -> dict:
        """按命令补齐界面才能提供的参数（包路径/目录/章节/缓冲），避免 handler 空跑。"""
        command_id = str((row or {}).get("commandId") or "")
        payload: dict = {}
        if command_id == "team.chapter-history":
            # 与未保存缓冲比较：把当前编辑器内容一并交给 handler
            workspace = getattr(self, "_content_workspace", None)
            editor = workspace.current_editor() if workspace is not None else None
            target = getattr(editor, "_editor", None)
            if target is not None:
                payload["buffer_text"] = target.toPlainText()
                rel = ""
                try:
                    rel = str(workspace.current_file() or "")
                except Exception:  # noqa: BLE001
                    rel = ""
                if rel:
                    payload["chapter"] = rel.split("/", 1)[-1]
        elif command_id == "team.handoff-export":
            from PySide6.QtWidgets import QFileDialog

            directory = QFileDialog.getExistingDirectory(self, "选择交接包导出目录")
            if directory:
                payload["handoffDir"] = directory
        elif command_id == "team.handoff-apply":
            from PySide6.QtWidgets import QFileDialog

            package, _selected = QFileDialog.getOpenFileName(
                self, "选择要应用的交接包", "", "交接包 (*.zip);;所有文件 (*)",
            )
            if package:
                payload["package"] = package
        return payload

    def _show_registry_result(self, row, result) -> None:
        """把注册表命令的结果显示出来（此前被直接丢弃，界面看不到任何输出）。"""
        command_id = str((row or {}).get("commandId") or "")
        title = str((row or {}).get("title") or command_id)
        if result is None:
            return
        if not getattr(result, "ok", False):
            message = str(getattr(result, "message", "") or "命令未完成")
            self._show_status_message("{0}：{1}".format(title, message))
            self._show_result_dialog(title, message, str(getattr(result, "detail", "") or ""))
            return
        value = getattr(result, "value", None)
        lines: List[str] = []
        if isinstance(value, dict):
            for key in ("summary", "summaryLines"):
                items = value.get(key)
                if isinstance(items, list):
                    lines.extend(str(item) for item in items)
            if not lines:
                for key in ("chapter", "source", "history", "counts", "artifacts", "nextActions",
                            "processed", "pending", "conflicts", "skipped", "status", "message"):
                    if key not in value:
                        continue
                    item = value[key]
                    if isinstance(item, (list, tuple)):
                        if item:
                            lines.append("{0}：{1}".format(key, "、".join(str(x) for x in item[:6])))
                    elif item not in (None, "", {}):
                        lines.append("{0}：{1}".format(key, str(item)[:200]))
        elif value not in (None, ""):
            lines.append(str(value))
        if not lines:
            lines = [str(getattr(result, "message", "") or "命令已完成")]
        self._show_status_message("{0}：{1}".format(title, lines[0][:120]))
        detail = ""
        try:
            import json as _json

            detail = _json.dumps(value, ensure_ascii=False, indent=2, default=str)[:8000]
        except Exception:  # noqa: BLE001 - 报告不可序列化时只显示摘要
            detail = ""
        self._show_result_dialog(title, "\n".join(lines[:10]), detail)

    def _show_result_dialog(self, title: str, text: str, detail: str = "") -> None:
        """非阻塞展示命令结果：模态对话框会在离屏/无人值守场景把界面卡住。"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        if detail:
            box.setDetailedText(detail)
        box.setStandardButtons(QMessageBox.StandardButton.Close)
        box.setModal(False)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        keep = getattr(self, "_result_dialogs", None)
        if keep is None:
            keep = []
            self._result_dialogs = keep
        keep.append(box)
        box.finished.connect(lambda _code, b=box: keep.remove(b) if b in keep else None)
        box.show()

    def _make_registry_callback(self, row):
        """统一回调：走注册表 handle_item，并把结果展示出来（与菜单同一 handler/可用性）。"""
        def _invoke() -> None:
            registry = self._ensure_command_registry()
            payload = self._augment_registry_payload(row)
            command_id = str((row or {}).get("commandId") or "")
            if command_id in ("team.handoff-export", "team.handoff-apply") and not payload:
                self._show_status_message("已取消：未选择交接包{0}".format(
                    "目录" if command_id.endswith("export") else ""
                ))
                return
            result = registry.handle_item(row, self._command_context(), payload or None)
            self._show_registry_result(row, result)
        return _invoke

    def _build_registry_menu(self, menu) -> int:
        """按注册表菜单视图填充一个菜单；返回填充条数。"""
        from PySide6.QtGui import QAction, QKeySequence
        from PySide6.QtWidgets import QMenu

        registry = self._ensure_command_registry()
        context = self._command_context()
        groups: dict = {}
        for row in registry.menu_items(context):
            groups.setdefault(str(row.get("category") or "命令"), []).append(row)
        count = 0
        # PySide6 所有权陷阱：`menu.addMenu(title)` 会把子菜单所有权交给返回的
        # Python 包装对象，其它代码再取一次 `action.menu()` 就会顶掉旧包装并删除
        # C++ 对象（菜单项凭空消失/访问已删除对象）。显式指定父对象可避免该问题。
        self._registry_menu_refs = []
        for category, rows in groups.items():
            submenu = QMenu(category, self)
            menu.addMenu(submenu)
            self._registry_menu_refs.append(submenu)
            for row in rows:
                action = QAction(str(row.get("title") or row.get("commandId")), self)
                if row.get("shortcut"):
                    action.setShortcut(QKeySequence(str(row["shortcut"])))
                action.triggered.connect(self._make_registry_callback(row))
                submenu.addAction(action)
                count += 1
        return count

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
            items.append(PaletteItem(title="交付历史与章节比较…", category="构建", callback=self._on_build_history))
            items.append(PaletteItem(title="只读离线 HTML 预览包…", category="工具", callback=self._on_html_preview))
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

        # V2.8（5.5）：三条建项路径与即时模板填充明确区分。
        items.append(
            PaletteItem(
                title="从规范包起步建项（章节骨架）…",
                category="新建",
                description="选择规范包生成可持续维护的项目",
                callback=lambda: self._on_create_from_pack(),
            )
        )
        items.append(
            PaletteItem(
                title="接管现有 Word 建项…",
                category="新建",
                description="复用预检/样式映射/往返门禁，先预览差异再导入",
                callback=lambda: self._on_intake_word(),
            )
        )
        items.append(
            PaletteItem(
                title="以 Markdown 起步建项（按文件顺序）…",
                category="新建",
                description="按文件顺序生成章节，适合 Docs-as-Code 内容",
                callback=lambda: self._on_create_from_markdown(),
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
                title="Markdown 模板填充（底模出稿）…",
                category="工具",
                callback=lambda: self._on_template_fill(),
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

        # 注册表命令（团队/写作辅助等）：与菜单同 handler、同可用性（V3.1 4.2 / V3.3 5.3）
        try:
            items.extend(self._registry_palette_items())
        except Exception:  # noqa: BLE001 - 注册表异常不影响既有面板
            pass

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
                self._loading_overlay.finish_immediately()
            return
        # 保存旧项目会话（在旧工作区销毁前收集）。
        self._persist_workspace_session()

        if hasattr(self, "_loading_overlay"):
            target_title = f"打开项目: {summary.project_root.name}"
            current_title = getattr(self._loading_overlay, "_title_label", None)
            is_finishing = getattr(self._loading_overlay, "_is_finishing", False)
            if not self._loading_overlay.isVisible() or is_finishing or (current_title and current_title.text() != target_title):
                self._loading_overlay.start(summary.project_root.name, "正在解析项目配置与元数据…")
            self._loading_overlay.raise_()
            QApplication.processEvents()

        self._project_summary = summary
        self._reset_command_registry()
        self._refresh_registry_menu()
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
        def _check_source_reimport():
            try:
                from doc_tool.application.content.reimport import ReimportService
                if ReimportService(summary.manifest, summary.paths).source_changed():
                    self._status_label.setText("检测到源 Word 已变化，可从工具菜单重新导入")
            except (OSError, AttributeError):
                pass
        QTimer.singleShot(150, _check_source_reimport)

    def _open_project_path(self, path: str) -> None:
        if self.runner.is_running:
            return
        if not path or not str(path).strip():
            return
        path_obj = Path(path).resolve()
        if path_obj.is_file() or path_obj.name.lower() in ("project.yml", "project.yaml"):
            path_obj = path_obj.parent
        path = str(path_obj)
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
            self.show_project(summary)
            self._append_log("已打开项目：{0}".format(summary.project_root.name))
        except DocToolError as exc:
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.finish_immediately()
            self._show_error("打开项目失败", exc.user_message, exc.suggested_action)
            return
        except Exception as exc:  # noqa: BLE001
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.finish_immediately()
            self._show_error("打开项目失败", str(exc)[:200])
            return

    def _on_open_recent(self, path: str) -> None:
        """最近项目点击：在新窗口打开，不在当前窗口切换项目。

        菜单「最近打开」与空状态「最近项目」按钮都经此回调；
        重复打开保护（同一项目已在其它窗口打开 → 激活已有窗口）由
        ``_open_project_in_new_window`` 承担。
        """
        self._open_project_in_new_window(path)

    # --- 内容工作区 ---

    def _preview_text_resolver(self):
        """预览展开器（V3.0 3.4）：与出稿共用同一份模块引用解析。

        无声明项目返回 None（预览保持原样、零额外开销）；解析器构建失败同样返回 None，
        调用方保留原文。
        """
        summary = self._project_summary
        root = getattr(summary, "project_root", None) if summary is not None else None
        if root is None:
            return None
        cached = getattr(self, "_preview_resolver_cache", None)
        if cached is not None and cached[0] == str(root):
            return cached[1]
        resolver = None
        try:
            from doc_tool.application.content.reuse_hook import build_project_resolver

            resolver = build_project_resolver(root)
        except Exception:  # noqa: BLE001 - 解析器不可用时预览保持原样
            resolver = None
        self._preview_resolver_cache = (str(root), resolver)
        return resolver

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
            text_resolver=self._preview_text_resolver(),
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
        if hasattr(self, "_loading_overlay") and self._loading_overlay.isVisible():
            self._loading_overlay.setGeometry(self.rect())
            self._loading_overlay.raise_()
        # 分支 UI 在 _on_content_index_ready 中就绪时统一刷新，避免在此处阻塞主线程加载动画

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
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.finish()
        self._update_git_branch_ui()

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

        wizard = ImportWizard(self)
        wizard._intake_preset_name = str(getattr(self, "_pending_intake_preset", "") or "")
        self._pending_intake_preset = ""
        result = wizard.run()
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
        if not path or not str(path).strip():
            return
        path_obj = Path(path).resolve()
        if path_obj.is_file() or path_obj.name.lower() in ("project.yml", "project.yaml"):
            path_obj = path_obj.parent
        path = str(path_obj)
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
        new_window.show()
        new_window.raise_()
        new_window.activateWindow()
        new_window.show_project(summary)

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

    def _start_task(self, spec: TaskSpec, on_done=None) -> None:
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
            spec, on_event=self._on_task_event,
            on_done=on_done or self._on_task_done,
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
        if event.kind == "stage":
            # 逐项阶段事件（如批量交付的 delivery:started/succeeded）→ 记录并推到任务面板，
            # 否则后台任务虽有进度事件，界面只看得到任务级状态（复核发现）。
            detail = str(getattr(event, "detail", "") or "")
            stage = str(getattr(event, "stage", "") or "")
            self._stage_events.append({
                "stage": stage, "status": getattr(event, "status", ""),
                "detail": detail, "metrics": dict(getattr(event, "metrics", {}) or {}),
            })
            if detail:
                self._progress_recent_stage = detail
            dock = getattr(self, "_task_dock", None)
            append_log = getattr(dock, "append_log", None)
            if callable(append_log) and detail:
                try:
                    append_log("[{0}] {1}".format(stage or "stage", detail))
                except Exception:  # noqa: BLE001 - 面板接口差异不影响任务
                    pass
            if detail:
                self._status_label.setText(detail)
            return
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

    def _on_html_preview(self):
        if self._project_summary and self._content_workspace:
            from doc_tool.ui.html_preview_dialog import HtmlPreviewDialog
            HtmlPreviewDialog(
            self._project_summary, self._content_workspace, self._open_directory,
            text_resolver=self._preview_text_resolver(), parent=self,
        ).exec()

    def _on_build_history(self):
        if self._project_summary:
            from doc_tool.ui.build_history_dialog import BuildHistoryDialog
            BuildHistoryDialog(self._project_summary.paths.state_dir,
                open_artifact=lambda path: self._on_open_result_output(str(path)), parent=self).exec()

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

    # --- V3.2 32-E：批量交付入口（复用 TaskRunner 与 gui_hooks 视图） ---

    def _delivery_member_lines(self, payload: dict) -> List[str]:
        """逐成员/变体/格式/状态/路径明细（供结果页“显示详细信息”与计划预览）。"""
        rows = payload.get("memberRows") or (payload.get("batch") or {}).get("rows") or []
        lines: List[str] = []
        for row in rows:
            member = str(row.get("memberName") or row.get("member") or "")
            variant = str(row.get("variantId") or "")
            head = member + (("（变体 {0}）".format(variant)) if variant else "")
            lines.append("{0}｜{1}｜{2}/{3} 个格式可用".format(
                head, row.get("statusLabel") or row.get("status") or "",
                row.get("usableCount", 0), row.get("totalCount", 0),
            ))
            if row.get("waitingReason"):
                lines.append("    待刷新原因：{0}".format(row["waitingReason"]))
            if row.get("error"):
                lines.append("    错误：{0}".format(row["error"]))
            for cell in row.get("cells") or []:
                target = str(cell.get("path") or "")
                lines.append("    · {0}｜{1}｜{2}{3}".format(
                    cell.get("label") or cell.get("format") or "",
                    cell.get("statusLabel") or cell.get("status") or "",
                    target or "（无路径）",
                    "" if cell.get("exists", True) else "（文件不存在）",
                ))
        return lines

    def _on_delivery_batch(self) -> None:
        """选择批次计划 → 预览 → 通过既有 TaskRunner 串行执行。"""
        if self.runner.is_running:
            self._show_status_message("已有任务正在运行，本次批量交付未开始")
            return
        from doc_tool.application.delivery import gui_tasks

        default_dir = str(getattr(self, "_last_delivery_dir", "") or "")
        plan_path, _selected = QFileDialog.getOpenFileName(
            self, "选择批次计划（batch.json）", default_dir,
            "批次计划 (*.json);;所有文件 (*)",
        )
        if not plan_path:
            return
        self._last_delivery_dir = str(Path(plan_path).parent)
        try:
            preview = gui_tasks.plan_preview(plan_path)
        except Exception as exc:  # noqa: BLE001 - 计划非法给明确原因
            self._show_error("批次计划不可用", str(exc))
            return
        lines = list(preview.get("summary") or [])
        invalid = preview.get("invalid") or []
        if invalid:
            lines.append("不可执行成员 {0} 个（将跳过）".format(len(invalid)))
        plan_lines = [
            "· {0}｜变体 {1}｜格式 {2}｜{3}".format(
                row.get("memberName") or row.get("member") or "",
                row.get("variantId") or "（无）",
                "、".join(row.get("formats") or []) or "（默认）",
                row.get("statusLabel") or row.get("status") or "",
            )
            for row in (preview.get("view") or {}).get("rows") or []
        ]
        box = QMessageBox(self)
        box.setWindowTitle("批次计划预览")
        box.setText("\n".join(lines[:12]))
        if plan_lines:
            box.setDetailedText("\n".join(plan_lines))
        run_button = box.addButton("开始交付", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not run_button:
            return
        if not preview.get("executable"):
            self._show_status_message("计划里没有可执行成员：请检查项目路径与格式")
            return
        from doc_tool.ui.task_bridge import TaskSpec

        spec = TaskSpec(
            name="delivery-run",
            target=gui_tasks.run_plan_task,
            args=(str(plan_path),),
            kwargs={},
            timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        )
        self._status_label.setText("批量交付进行中…")
        self._start_task(spec, on_done=self._on_delivery_done)

    def _on_delivery_done(self, payload) -> None:
        """结果页：成员/格式状态 + 打开产物 / 只重试未完成项。"""
        self._elapsed_timer.stop()
        self._poll_timer.stop()
        if payload is None:
            self._status_label.setText("批量交付已取消，已完成成员保留")
            return
        if isinstance(payload, BaseException):
            self._show_error("批量交付未完成", str(payload))
            self._status_label.setText("批量交付未完成")
            return
        targets = payload.get("openTargets") or []
        summary = list(payload.get("summary") or [])
        box = QMessageBox(self)
        box.setWindowTitle("批量交付结果")
        box.setText("\n".join(summary[:12]))
        detail_lines = self._delivery_member_lines(payload if isinstance(payload, dict) else {})
        if detail_lines:
            # 逐成员/变体/格式/状态/路径：供“显示详细信息”展开查看
            box.setDetailedText("\n".join(detail_lines))
        open_button = box.addButton("打开首个产物", QMessageBox.ButtonRole.AcceptRole)
        dir_button = box.addButton("打开结果目录", QMessageBox.ButtonRole.ActionRole)
        retry_button = box.addButton("只重试未完成项", QMessageBox.ButtonRole.ActionRole)
        refresh_button = box.addButton("补刷新（正式稿）", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        first = targets[0] if targets else None
        if clicked is open_button and first is not None:
            self._on_open_result_output(str(first.get("path") or ""))
        elif clicked is dir_button and first is not None:
            parent = str(Path(str(first.get("path") or "")).parent)
            self._on_open_result_directory(parent)
        elif clicked is retry_button:
            self._retry_delivery_unfinished(payload)
        elif clicked is refresh_button:
            # 补刷新：对未完成（含待刷新）成员重跑一次并驱动 Word 刷新，
            # 使用队列内原轮快照，不重走已完成成员。
            self._retry_delivery_unfinished(payload, skip_word_refresh=False)
        else:
            self._status_label.setText("批量交付结束：{0} 个可用产物".format(len(targets)))

    def _retry_delivery_unfinished(self, payload, *, skip_word_refresh: bool = True) -> None:
        """只补未完成项（队列内原轮快照），不重走已完成成员。

        ``skip_word_refresh=False`` 即“补刷新”：驱动 Word 刷新产出正式稿；无 Word
        时保持可读稿并标待刷新（沿用既有 OutputState 判定）。
        """
        store_path = str((payload.get("queue") or {}).get("storePath") or "")
        if not store_path:
            self._show_status_message("缺少队列位置，无法只补未完成项")
            return
        from doc_tool.application.delivery import gui_tasks
        from doc_tool.ui.task_bridge import TaskSpec

        spec = TaskSpec(
            name="delivery-run",
            target=gui_tasks.retry_unfinished_task,
            args=(store_path,),
            kwargs={"skip_word_refresh": bool(skip_word_refresh)},
            timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        )
        self._status_label.setText(
            "正在补未完成成员…" if skip_word_refresh else "正在补刷新（Word 正式稿）…"
        )
        self._start_task(spec, on_done=self._on_delivery_done)

    # --- V3.0 6.1/6.2：正文模块库与引用解析入口 ---

    def _on_reuse_dialog(self) -> None:
        """打开模块库/引用解析对话框（能力全部复用 reuse_commands 服务）。"""
        if self._project_summary is None:
            self._show_status_message("请先打开或新建项目后再使用正文模块库")
            return
        from doc_tool.ui.reuse_dialog import ReuseDialog

        dialog = ReuseDialog(self._project_summary.project_root, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    # --- V3.3 5.1：资料搜索与建议面板接线 ---

    def _on_assist_panel(self) -> None:
        """打开资料搜索/建议面板，并集中提示覆盖范围与增强未执行。"""
        if self._project_summary is None:
            self._show_status_message("请先打开或新建项目后再使用资料搜索与建议")
            return
        from doc_tool.application.assist.commands import build_assist_overview
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        try:
            assistant = build_assistant(str(self._project_summary.project_root))
        except Exception as exc:  # noqa: BLE001 - 辅助不可用不阻止编辑
            self._show_error("写作辅助不可用", str(exc))
            return
        buffers = self._collect_buffer_texts()
        if buffers:
            try:
                assistant.set_buffers(buffers)
            except Exception:  # noqa: BLE001 - 缓冲不可用时用磁盘内容
                pass
        existing = getattr(self, "_assist_dock", None)
        if existing is not None:
            existing.widget().set_assistant(assistant)
            existing.show()
            existing.raise_()
            return
        panel = AssistPanel(
            assistant,
            project_root=getattr(self._project_summary, "project_root", None),
            parent=self,
        )
        panel.insert_requested.connect(self._on_assist_insert_requested)
        panel.summary_candidate.connect(self._on_assist_summary_candidate)
        panel.buffers_changed.connect(self._on_assist_buffers_changed)
        panel.status_message.connect(lambda message: self._show_status_message(message))
        dock = QDockWidget("资料搜索与建议", self)
        dock.setObjectName("assistDock")
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setMinimumWidth(320)
        self._assist_dock = dock
        self._rebuild_view_menu()
        overview = build_assist_overview(
            self._project_summary.project_root, buffers=buffers,
        )
        for line in overview.summary_lines()[:4]:
            self._show_status_message(line)
        if not overview.scope:
            self._show_status_message("资料范围为空：可先在项目中打开或保存章节")

    def _open_chapter_in_workspace(self, rel_path: str, line: Optional[int] = None) -> bool:
        """在编辑器中打开章节：工作区 relPath 带文档类型前缀（如 ``general/第1章 …``）。"""
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None or not rel_path:
            return False
        document_type = ""
        try:
            document_type = str(self._project_summary.manifest.documentType or "")
        except Exception:  # noqa: BLE001
            document_type = ""
        candidates = [rel_path]
        if document_type and not rel_path.startswith(document_type + "/"):
            candidates.insert(0, "{0}/{1}".format(document_type, rel_path))
        for candidate in candidates:
            try:
                workspace.open_file(candidate, line)
            except TypeError:  # 旧签名（无行号）
                workspace.open_file(candidate)
            except Exception:  # noqa: BLE001 - 打不开时尝试下一种写法
                continue
            current = None
            getter = getattr(workspace, "current_file", None)
            if callable(getter):
                try:
                    current = getter()
                except Exception:  # noqa: BLE001
                    current = None
            if current == candidate:
                return True
        return False

    def _on_assist_insert_requested(self, text: str, mode: str) -> None:
        """把引用/正文插入当前编辑器光标处；一次操作进入撤销栈。"""
        if not text:
            return
        workspace = getattr(self, "_content_workspace", None)
        editor = workspace.current_editor() if workspace is not None else None
        target = getattr(editor, "_editor", None)
        if target is None:
            self._show_status_message("没有打开的章节：请先打开要插入的章节")
            return
        cursor = target.textCursor()
        cursor.insertText(text)
        target.setTextCursor(cursor)
        target.setFocus()
        self._show_status_message(
            "已插入{0}（可一次撤销）".format("出处引用" if mode == "citation" else "正文")
        )

    def _normalize_buffer_rel_path(self, rel_path: str) -> str:
        """把辅助层的缓冲路径归一成内容根相对路径（去掉 content/<docType>/ 前缀）。"""
        value = str(rel_path or "").replace("\\", "/").strip()
        if not value:
            return ""
        document_type = ""
        try:
            document_type = str(self._project_summary.manifest.documentType or "")
        except Exception:  # noqa: BLE001
            document_type = ""
        for prefix in ("content/",):
            if value.startswith(prefix):
                value = value[len(prefix):]
        if document_type and value.startswith(document_type + "/"):
            value = value[len(document_type) + 1:]
        return value

    def _on_assist_buffers_changed(self, texts) -> None:
        """采纳/撤销后把缓冲写回编辑器：整篇替换记为**一个撤销步**，并标脏保存路径不变。"""
        if not isinstance(texts, dict) or not texts:
            return
        from PySide6.QtGui import QTextCursor

        workspace = getattr(self, "_content_workspace", None)
        applied = 0
        for raw_path, raw_text in texts.items():
            rel_path = self._normalize_buffer_rel_path(raw_path)
            if not rel_path:
                continue
            tabs = getattr(workspace, "tabs_host", None) if workspace is not None else None
            if tabs is None or not hasattr(tabs, "editor_for"):
                continue
            # 标签键带文档类型前缀（general/…）：两种键都试，避免“已打开却找不到”
            keys = [rel_path]
            try:
                document_type = str(self._project_summary.manifest.documentType or "")
            except Exception:  # noqa: BLE001
                document_type = ""
            if document_type and not rel_path.startswith(document_type + "/"):
                keys.insert(0, "{0}/{1}".format(document_type, rel_path))
            editor = None
            for key in keys:
                try:
                    editor = tabs.editor_for(key)
                except Exception:  # noqa: BLE001
                    editor = None
                if editor is not None:
                    break
            if editor is None and workspace is not None:
                if self._open_chapter_in_workspace(rel_path):
                    for key in keys:
                        editor = tabs.editor_for(key)
                        if editor is not None:
                            break
            if editor is None:
                continue
            target = getattr(editor, "_editor", None) or editor
            if target is None or not hasattr(target, "textCursor"):
                continue
            if target.toPlainText() == str(raw_text):
                continue
            cursor = target.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(str(raw_text))
            cursor.endEditBlock()
            target.setTextCursor(cursor)
            applied += 1
        if applied:
            self._show_status_message(
                "已把采纳结果写入编辑器 {0} 个章节（可一次撤销；保存走既有保存路径）".format(applied)
            )

    def _discard_assist_summary_candidate(self) -> bool:
        """取消刚填入修订记录的摘要候选：一次撤销，不写盘、不改评审状态。

        返回是否真的撤销了编辑。
        """
        record = getattr(self, "_last_summary_candidate", None)
        action = getattr(self, "_discard_summary_action", None)
        if not isinstance(record, dict):
            if action is not None:
                action.setEnabled(False)
            self._show_status_message("没有待取消的摘要候选")
            return False
        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None)
        reverted = False
        if tabs is not None:
            editor = tabs.editor_for(record.get("rel_path", ""))
            target = getattr(editor, "_editor", None)
            if target is not None:
                target.undo()
                reverted = True
        self._last_summary_candidate = None
        if action is not None:
            action.setEnabled(False)
        self._show_status_message(
            "已取消摘要候选（未写入修订记录，评审状态未变）"
            if reverted else "已放弃摘要候选（未写入任何记录）"
        )
        return reverted

    def _on_assist_summary_candidate(self, text: str) -> None:
        """修订摘要候选只填既有修订记录，不新建发布状态。"""
        if not text:
            return
        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None)
        filled = False
        if tabs is not None:
            for rel_path in list(getattr(tabs, "open_rel_paths", lambda: [])()):
                if not str(rel_path).endswith("_revision_record.md"):
                    continue
                editor = tabs.editor_for(rel_path)
                target = getattr(editor, "_editor", None)
                if target is None:
                    continue
                cursor = target.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText("\n" + text.strip() + "\n")
                target.setTextCursor(cursor)
                # 记住本次插入，便于“取消摘要候选”一次撤销（V3.3 3.4）
                self._last_summary_candidate = {
                    "rel_path": str(rel_path), "text": str(text).strip(), "saved": False,
                }
                action = getattr(self, "_discard_summary_action", None)
                if action is not None:
                    action.setEnabled(True)
                filled = True
                self._show_status_message("摘要候选已填入修订记录（未保存；如需放弃请用「取消摘要候选」）")
                break
        if not filled:
            try:
                from PySide6.QtWidgets import QApplication

                clipboard = QApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(text)
            except Exception:  # noqa: BLE001 - 剪贴板不可用时仍给出文本
                pass
            self._show_status_message("修订记录未打开：摘要候选已复制到剪贴板，可粘贴后核对")

    # --- CORE-F：统一出稿入口与结果直接动作 ---

    def _collect_buffer_texts(self) -> Dict[str, str]:
        """收集编辑器缓冲（未保存修改），供“当前内容”出稿使用。

        只读取编辑器内存文本；不写回源文件、不清除脏标记。路径统一为
        contentRoot 相对路径（去掉可能的文档类型前缀）。
        """
        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None) if workspace is not None else None
        if tabs is None or not hasattr(tabs, "open_rel_paths"):
            return {}
        document_type = ""
        try:
            document_type = str(self._project_summary.manifest.documentType or "")
        except Exception:  # noqa: BLE001
            document_type = ""
        buffers: Dict[str, str] = {}
        for rel_path in tabs.open_rel_paths():
            editor = tabs.editor_for(rel_path) if hasattr(tabs, "editor_for") else None
            if editor is None:
                continue
            dirty = False
            marker = getattr(editor, "is_dirty", None)
            try:
                dirty = bool(marker()) if callable(marker) else bool(marker)
            except Exception:  # noqa: BLE001
                dirty = False
            if not dirty:
                continue
            text = None
            for attr in ("plain_text", "toPlainText", "text"):
                getter = getattr(editor, attr, None)
                if callable(getter):
                    try:
                        text = getter()
                    except Exception:  # noqa: BLE001
                        text = None
                    if isinstance(text, str):
                        break
                    text = None
            if not isinstance(text, str):
                # 面板形态：文本在内层 QPlainTextEdit 里
                inner = getattr(editor, "_editor", None)
                getter = getattr(inner, "toPlainText", None)
                if callable(getter):
                    try:
                        text = getter()
                    except Exception:  # noqa: BLE001
                        text = None
            if not isinstance(text, str):
                continue
            key = str(rel_path).replace("\\", "/")
            if document_type and key.startswith(document_type + "/"):
                key = key[len(document_type) + 1:]
            buffers[key] = text
        return buffers

    def _on_quick_export_word(self) -> None:
        """快速导出 Word：整份 + 当前内容 + 项目导出目录（默认值，可再调整）。"""
        if self._project_summary is None or self.runner.is_running:
            return
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, SOURCE_MODE_CURRENT_BUFFER, SOURCE_MODE_SAVED, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        buffers = self._collect_buffer_texts()
        request = ExportRequest(
            project_root=str(self._project_summary.project_root),
            formats=[FORMAT_DOCX],
            source_mode=SOURCE_MODE_CURRENT_BUFFER if buffers else SOURCE_MODE_SAVED,
            destination=str(self._project_summary.paths.output_dir),
        )
        # 出稿在既有 TaskRunner 后台线程执行：界面可继续编辑，任务 Dock 可取消，
        # 重复点击由 runner.is_running 与动作禁用共同防重。
        from doc_tool.ui.task_bridge import TaskSpec

        if self.runner.is_running:
            self._status_label.setText("已有任务正在运行，本次导出未开始")
            return
        spec = TaskSpec(
            name="project-export",
            target=run_project_export,
            args=(request,),
            kwargs={"buffer_texts": buffers},
            timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        )
        self._status_label.setText("正在生成 Word…")
        self._start_task(spec, on_done=self._on_export_task_done)

    def _on_export_task_done(self, report) -> None:
        """后台出稿结束：正常展示结果页，取消/超时/异常给明确原因。"""
        self._elapsed_timer.stop()
        self._poll_timer.stop()
        if report is None:
            self._status_label.setText("导出已取消，已完成的格式保留")
            return
        if isinstance(report, BaseException):
            self._show_error("导出未完成", str(report))
            self._status_label.setText("导出未完成")
            return
        self._present_export_report(report)

    def _present_export_report(self, report, *, allow_retry: bool = True) -> None:
        """结果页：先给可打开产物与目录，再给“补失败格式/更换目录”等直接动作。

        使用模块级 ``QMessageBox``（不在函数内重新导入），这样离屏测试可以
        整体替换为记录器而不会弹出真模态框。
        """
        box = QMessageBox(self)
        box.setWindowTitle("出稿结果")
        box.setText("\n".join(report.summary_lines()))
        open_button = box.addButton("打开文件", QMessageBox.ButtonRole.AcceptRole)
        dir_button = box.addButton("打开目录", QMessageBox.ButtonRole.ActionRole)
        retry_button = None
        if allow_retry and report.failed_formats():
            retry_button = box.addButton("补失败格式（原轮）", QMessageBox.ButtonRole.ActionRole)
        change_button = box.addButton("更换目录…", QMessageBox.ButtonRole.ActionRole)
        regenerate_button = box.addButton("按最新内容重新生成", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is open_button:
            usable = report.usable_results()
            if usable:
                self._on_open_result_output(usable[0].path)
        elif clicked is dir_button:
            self._on_open_result_directory(report.destination)
        elif retry_button is not None and clicked is retry_button:
            from doc_tool.application.project_export import retry_export_formats

            retried = retry_export_formats(report, report.failed_formats())
            self._present_export_report(retried, allow_retry=False)
        elif clicked is regenerate_button:
            # 明确开新一轮：重新捕获当前内容（新 captureId），不复用旧轮快照。
            from doc_tool.application.intake_contract import ExportRequest
            from doc_tool.application.project_export import run_project_export

            if self._project_summary is None:
                return
            request = ExportRequest(
                project_root=str(self._project_summary.project_root),
                formats=[item.format for item in report.results] or ["docx"],
                scope=report.scope,
                source_mode=report.sourceMode,
                destination=report.destination,
            )
            self._present_export_report(
                run_project_export(request, buffer_texts=self._collect_buffer_texts()),
                allow_retry=False,
            )
        elif clicked is change_button:
            chosen = QFileDialog.getExistingDirectory(self, "选择导出目录", report.destination)
            if not chosen:
                return
            from doc_tool.application.intake_contract import (
                SOURCE_MODE_CURRENT_BUFFER, ExportRequest,
            )
            from doc_tool.application.project_export import run_project_export

            request = ExportRequest(
                project_root=report.projectRoot or str(self._project_summary.project_root),
                formats=[item.format for item in report.results] or ["docx"],
                scope=report.scope,
                source_mode=report.sourceMode,
                destination=chosen,
            )
            # 上一轮可能是“当前编辑内容”来源：这里必须同样带上编辑器缓冲，
            # 否则会导出磁盘内容却在报告里仍标注“当前编辑内容”（审计发现的真实不一致）。
            buffer_texts = (
                self._collect_buffer_texts()
                if report.sourceMode == SOURCE_MODE_CURRENT_BUFFER
                else None
            )
            self._present_export_report(
                run_project_export(request, buffer_texts=buffer_texts), allow_retry=False,
            )
        else:
            self._status_label.setText("已生成 {0} 个可用结果".format(len(report.usable_results())))

    def _on_reimport_source(self) -> None:
        if not self._project_summary or not self._project_summary.is_writable:
            return
        source, _ = QFileDialog.getOpenFileName(self, "选择更新后的源 Word", "", "Word 文档 (*.docx)")
        if not source:
            return
        self._reimport_into_current(Path(source))

    def _reimport_into_current(self, source: Path) -> None:
        """把外部 Word 修改接回当前项目（既有差异重导入服务，不新建项目）。"""
        if not self._project_summary or not self._project_summary.is_writable:
            QMessageBox.information(
                self, "当前没有可写项目",
                "请先打开需要更新的项目，再接收外部 Word 修改。",
            )
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

    def _on_template_fill(self, paths: Optional[list] = None) -> None:
        """模板填充向导：底模 + 多个 Markdown 按顺序合并为单个 Word（无需项目）。"""
        from doc_tool.ui.template_fill_dialog import TemplateFillDialog

        dialog = TemplateFillDialog(
            parent=self, busy_check=lambda: self.runner.is_running, paths=paths
        )
        try:
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

    def _on_relocate_recent(self, old_path: str, new_path: str) -> None:
        """把失效的最近项目重新定位到新目录（规范 R9）：改列表、保留元信息并刷新首页。"""
        from doc_tool.application.project_service import (
            add_recent_project, load_recent_projects, remove_recent_project,
        )
        from doc_tool.domain.manifest import ProjectManifest

        try:
            manifest = ProjectManifest.load(new_path)
        except Exception as exc:  # noqa: BLE001 - 不是项目时如实说明，不改列表
            self._show_status_message("重新定位失败：{0}".format(exc))
            return
        previous = None
        for entry in load_recent_projects():
            try:
                same = str(Path(entry.path).resolve()) == str(Path(old_path).resolve())
            except Exception:  # noqa: BLE001
                same = entry.path == old_path
            if same:
                previous = entry
                break
        remove_recent_project(old_path)
        add_recent_project(new_path, manifest)
        self._refresh_recent_projects()
        label = manifest.documentName or Path(new_path).name
        detail = ""
        if previous is not None and previous.document_name and previous.document_name != label:
            detail = "（原记录：{0}）".format(previous.document_name)
        self._show_status_message(
            "已重新定位最近项目：{0} → {1}{2}".format(old_path, new_path, detail)
        )

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
        """系统关联程序不可用时，以交互式窗口展示校验报告（支持分类筛选与搜索）。"""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._show_error(
                "无法读取校验报告",
                "无法读取校验报告：{0}".format(exc),
                "请检查文件权限，或在文件管理器中手动打开该文件。",
            )
            return

        from PySide6.QtWidgets import QComboBox, QLineEdit
        from doc_tool.application.project_service import (
            filter_validation_report_content,
            read_validation_report_summary,
        )

        summary = read_validation_report_summary(path)

        dialog = QDialog(self)
        dialog.setWindowTitle("校验报告预览")
        dialog.resize(800, 580)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        path_label = QLabel(str(path), dialog)
        path_label.setObjectName("statusMuted")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)

        lbl_cat = QLabel("分类：", dialog)
        filter_bar.addWidget(lbl_cat)
        status_combo = QComboBox(dialog)
        pass_cnt = summary.get("passCount", 0)
        fail_cnt = summary.get("failCount", 0)
        status_combo.addItem("全部内容", "")
        status_combo.addItem("仅失败项 [FAIL] ({0})".format(fail_cnt), "FAIL")
        status_combo.addItem("仅通过项 [PASS] ({0})".format(pass_cnt), "PASS")
        status_combo.addItem("关键指标与统计", "METRICS")
        filter_bar.addWidget(status_combo)

        lbl_search = QLabel("搜索：", dialog)
        filter_bar.addWidget(lbl_search)
        search_input = QLineEdit(dialog)
        search_input.setPlaceholderText("在报告中搜索关键词...")
        search_input.setClearButtonEnabled(True)
        filter_bar.addWidget(search_input, 1)

        reset_btn = QPushButton("重置", dialog)
        reset_btn.setProperty("btnRole", "compact")
        filter_bar.addWidget(reset_btn)

        layout.addLayout(filter_bar)

        count_lbl = QLabel(
            "共 {0} 项检查（通过 {1}，失败 {2}）".format(
                pass_cnt + fail_cnt, pass_cnt, fail_cnt
            ),
            dialog,
        )
        count_lbl.setObjectName("statusMuted")
        layout.addWidget(count_lbl)

        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(content)
        layout.addWidget(text, 1)

        def update_preview() -> None:
            sf = str(status_combo.currentData() or "")
            kw = search_input.text().strip()
            if not sf and not kw:
                text.setPlainText(content)
                count_lbl.setText(
                    "共 {0} 项检查（通过 {1}，失败 {2}）".format(
                        pass_cnt + fail_cnt, pass_cnt, fail_cnt
                    )
                )
            else:
                filtered_text, count = filter_validation_report_content(
                    content, status_filter=sf, keyword=kw
                )
                text.setPlainText(filtered_text)
                count_lbl.setText("已筛选出 {0} 条相关内容".format(count))

        def reset_filters() -> None:
            status_combo.setCurrentIndex(0)
            search_input.clear()
            update_preview()

        status_combo.currentIndexChanged.connect(update_preview)
        search_input.textChanged.connect(update_preview)
        reset_btn.clicked.connect(reset_filters)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch(1)

        ext_btn = QPushButton("在外部编辑器打开", dialog)
        ext_btn.setProperty("btnRole", "secondary")
        ext_btn.setToolTip("在系统关联的外部文本/Markdown 编辑器中打开原始报告文件")
        ext_btn.clicked.connect(lambda: self._open_file(path))
        btn_row.addWidget(ext_btn)

        close_btn = QPushButton("关闭", dialog)
        close_btn.setProperty("btnRole", "secondary")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
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
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.set_dark(target_dark)
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
        if hasattr(self, "_content_workspace") and self._content_workspace is not None:
            try:
                self._content_workspace.shutdown()
            except Exception:
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
            cached_branches, has_cache = ws.get_cached_branches()
            if has_cache:
                branches = cached_branches
            else:
                branches, _ = ws.list_branches(timeout=1.5)
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
            if hasattr(self, "_content_workspace") and self._content_workspace is not None:
                try:
                    self._content_workspace.shutdown()
                except Exception:
                    pass
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
