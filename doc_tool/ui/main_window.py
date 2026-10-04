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

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Dict, List, Optional

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
    QComboBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
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

#: 主窗口兜底日志（无状态栏时仍留下可诊断记录）。
logger = logging.getLogger(__name__)

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


def _run_reimport_preview(service, source, dirty_paths, local_contents, cancel_token=None):
    """后台执行隔离差异预览（MAIN2-B 2.1）——纯只读，不写正文/源记录。

    取消失效于阶段边界：取消令牌在抽取前后各检查一次，取消后返回 ``(None, 原因)``。
    """
    if cancel_token is not None:
        try:
            cancel_token.check_cancel()
        except Exception:  # noqa: BLE001 - 已取消时立即返回
            return None, "已取消，未生成差异"
    session, error = service.preview(
        source, dirty_paths=list(dirty_paths or ()), local_contents=dict(local_contents or {}),
    )
    if cancel_token is not None:
        try:
            cancel_token.check_cancel()
        except Exception:  # noqa: BLE001 - 取消后不返回会话
            return None, "已取消，未生成差异"
    return session, error


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
        # UI 包 UI-C：本项目最近轮次（只保留引用，不复制文件，不提升正式状态）。
        from doc_tool.ui.export_rounds import RoundStore

        self._export_rounds = RoundStore()
        self._selected_round_id = ""
        self._last_export_round = None
        # 批量交付：表单校验后的预览缓存（新建批次路径直接复用，不重复解析）。
        self._last_delivery_preview = None
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
        # 2.2：首用默认布局是否已套用 / 用户是否已显式选择布局（用于会话持久化）。
        self._writing_layout_default_applied = False
        self._writing_layout_chosen = False

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
            on_toggle_pin=self._on_toggle_recent_pin,
            on_convert=self._on_convert_documents,
            on_pdf_toolbox=self._on_pdf_toolbox,
            # 主区拖放 = 导入建项路由（与「新建项目…」同一服务）；
            # 互转卡自身拖放才进入文档互转，两类语义不再混淆。
            on_drop_intake=self._on_import_document,
            on_drop_convert=self._on_convert_documents,
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
            on_quick_export=self._on_quick_export_word,
            on_show_results=self._on_show_results,
            on_switch_branch=self._on_switch_branch_clicked,
            on_close_project=self.close_project,
        )
        ide_layout.addWidget(self._project_bar)
        ide_layout.addWidget(self._build_nav_bar())
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
            on_open_format=self._on_open_export_format,
            on_locate_format=self._locate_file,
            on_retry_formats=self._on_retry_export_round,
            on_regenerate_round=self._on_regenerate_round,
            on_change_destination=self._on_change_export_destination,
            on_open_settings=self._on_export_settings_for_round,
            on_select_round=self._on_select_export_round,
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

    def _build_nav_bar(self) -> QWidget:
        """路径导航条（UI2-C 3.1/3.4）：后退/前进 + 真实章节路径 + 定位当前章。

        复用已有章节树/标签联动；长路径省略显示，完整值在提示与右键复制里。
        """
        bar = QWidget(self._ide_page)
        bar.setObjectName("editorNavBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self._nav_back_btn = QPushButton("←", bar)
        self._nav_back_btn.setObjectName("navBackBtn")
        self._nav_back_btn.setProperty("btnRole", "compact")
        self._nav_back_btn.setText("← 后退")
        self._nav_back_btn.setToolTip("回到上一个位置 (Alt+←)")
        self._nav_back_btn.setEnabled(False)
        self._nav_back_btn.clicked.connect(self._on_nav_back)
        layout.addWidget(self._nav_back_btn)

        self._nav_forward_btn = QPushButton("前进 →", bar)
        self._nav_forward_btn.setObjectName("navForwardBtn")
        self._nav_forward_btn.setProperty("btnRole", "compact")
        self._nav_forward_btn.setToolTip("前进到下一个位置 (Alt+→)")
        self._nav_forward_btn.setEnabled(False)
        self._nav_forward_btn.clicked.connect(self._on_nav_forward)
        layout.addWidget(self._nav_forward_btn)

        self._nav_location_label = QLabel("未打开章节", bar)
        self._nav_location_label.setObjectName("navLocationLabel")
        self._nav_location_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._nav_location_label.setMinimumWidth(80)
        self._nav_location_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._nav_location_label.customContextMenuRequested.connect(
            lambda pos: self._on_copy_current_path()
        )
        layout.addWidget(self._nav_location_label, 1)

        locate_btn = QPushButton("定位当前章", bar)
        locate_btn.setObjectName("navLocateBtn")
        locate_btn.setProperty("btnRole", "compact")
        locate_btn.setToolTip("在章节树中选中当前章并给出完整路径")
        locate_btn.clicked.connect(self._on_locate_current_chapter)
        layout.addWidget(locate_btn)

        copy_btn = QPushButton("复制路径", bar)
        copy_btn.setObjectName("navCopyPathBtn")
        copy_btn.setProperty("btnRole", "compact")
        copy_btn.setToolTip("复制当前章的完整相对路径")
        copy_btn.clicked.connect(self._on_copy_current_path)
        layout.addWidget(copy_btn)

        # UI2-C 3.3/3.4：写作/对照/阅读 + 字号档位（复用原预览/目录）。
        self._view_mode_combo = QComboBox(bar)
        self._view_mode_combo.setObjectName("viewModeCombo")
        self._view_mode_combo.addItem("写作", "write")
        self._view_mode_combo.addItem("对照", "compare")
        self._view_mode_combo.addItem("阅读", "read")
        self._view_mode_combo.setToolTip("切换写作/对照/阅读视图（不改正文与模板）")
        self._view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        layout.addWidget(self._view_mode_combo)

        for text, slot, tip in (
            ("A-", self._on_zoom_out, "缩小正文与预览字号 (Ctrl+-)"),
            ("A+", self._on_zoom_in, "放大正文与预览字号 (Ctrl+=)"),
            ("A0", self._on_zoom_reset, "重置字号到默认 (Ctrl+0)"),
        ):
            btn = QPushButton(text, bar)
            btn.setProperty("btnRole", "compact")
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
        return bar

    def _active_panel(self):
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None:
            return None
        try:
            return workspace.current_editor()
        except Exception:  # noqa: BLE001 - 编辑器不可用时按无编辑器处理
            return None

    def _on_view_mode_changed(self, _index: int) -> None:
        mode = str(self._view_mode_combo.currentData() or "write")
        editor = self._active_panel()
        if editor is None or not hasattr(editor, "set_view_mode"):
            self._show_status_message("请先打开一个章节再切换视图")
            return
        applied = editor.set_view_mode(mode)
        labels = {"write": "写作", "compare": "对照", "read": "阅读"}
        self._status_label.setText(
            "已切换到{0}视图（正文与模板未改变）".format(labels.get(applied, applied))
        )
        self._persist_workspace_session()

    def _on_zoom_in(self) -> None:
        editor = self._active_panel()
        if editor is None or not hasattr(editor, "zoom_in"):
            return
        size = editor.zoom_in()
        self._status_label.setText("字号已放大到 {0:g}pt".format(size))
        self._persist_workspace_session()

    def _on_zoom_out(self) -> None:
        editor = self._active_panel()
        if editor is None or not hasattr(editor, "zoom_out"):
            return
        size = editor.zoom_out()
        self._status_label.setText("字号已缩小到 {0:g}pt".format(size))
        self._persist_workspace_session()

    def _on_zoom_reset(self) -> None:
        editor = self._active_panel()
        if editor is None or not hasattr(editor, "reset_zoom"):
            return
        size = editor.reset_zoom()
        self._status_label.setText("字号已重置为默认 {0:g}pt".format(size))
        self._persist_workspace_session()

    def _set_view_mode(self, mode: str) -> None:
        index = self._view_mode_combo.findData(mode)
        if index >= 0:
            self._view_mode_combo.setCurrentIndex(index)

    def _build_menu(self) -> None:
        from PySide6.QtGui import QAction, QKeySequence

        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu("文件")
        # 1.4：导入与新建是同一件事（同一 intake 路由），合并为一个可发现入口。
        self._import_action = QAction("导入 / 新建项目（Word / Markdown）…", self)
        self._import_action.setShortcut(QKeySequence("Ctrl+N"))
        self._import_action.setToolTip(
            "自动识别 Word / Markdown 并调用对应建项服务：DOCX 逐份进向导，"
            "Markdown 多文件按列表顺序组稿成一份项目"
        )
        self._import_action.triggered.connect(self._on_import_document)
        file_menu.addAction(self._import_action)
        # MAIN2-A 1.2：导入结果可重开（非模态窗口），处理完问题可随时回来继续。
        self._intake_result_action = QAction("导入结果与待处理项…", self)
        self._intake_result_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self._intake_result_action.setToolTip(
            "重新打开当前项目的导入结果：完整处理事实、按类型/章节筛选、分页与就地处理"
        )
        self._intake_result_action.triggered.connect(self.reopen_intake_result)
        file_menu.addAction(self._intake_result_action)
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
        # UI2-D 4.2：导出设置与快速 Word 并列，共享同一提交链路。
        self._export_settings_action = QAction("导出设置…", self)
        self._export_settings_action.setToolTip("按格式/范围/来源/目录/版式提交一次导出（默认值可直接提交）")
        self._export_settings_action.triggered.connect(self._on_export_settings)
        ops_menu.addAction(self._export_settings_action)
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
        # UI 包 2.3：Ctrl+F 在当前章内查找（编辑器有焦点），
        # Ctrl+Shift+F 始终查项目全文；两者提示与实际作用域一致。
        self._search_action = QAction("查找（当前章 Ctrl+F / 全文 Ctrl+Shift+F）", self)
        self._search_action.setShortcut(QKeySequence("Ctrl+F"))
        self._search_action.setToolTip(
            "编辑器有焦点时查当前章；焦点在别处时打开项目全文搜索面板 (Ctrl+F)"
        )
        self._search_action.triggered.connect(self._on_content_search)
        content_menu.addAction(self._search_action)
        self._search_project_action = QAction("项目全文搜索", self)
        self._search_project_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self._search_project_action.setToolTip("在整份项目的所有章节中检索 (Ctrl+Shift+F)")
        self._search_project_action.triggered.connect(self._on_content_search_project)
        content_menu.addAction(self._search_project_action)
        self._references_action = QAction("引用分析…", self)
        self._references_action.triggered.connect(self._on_content_references)
        content_menu.addAction(self._references_action)
        self._replace_action = QAction("全局替换…", self)
        self._replace_action.triggered.connect(self._on_content_replace)
        content_menu.addAction(self._replace_action)
        self._refactor_action = QAction("章节重命名/重编号…", self)
        self._refactor_action.triggered.connect(self._on_content_refactor)
        content_menu.addAction(self._refactor_action)
        # V3.4 34-B/34-C：表格网格与显式表格粘贴（普通 Ctrl+V 行为不变）
        self._table_grid_action = QAction("编辑表格网格…", self)
        self._table_grid_action.setShortcut(QKeySequence("Ctrl+Alt+G"))
        self._table_grid_action.setToolTip("网格编辑光标所在的普通表格；一次撤销可还原")
        self._table_grid_action.triggered.connect(self._on_table_grid)
        content_menu.addAction(self._table_grid_action)
        self._table_paste_action = QAction("粘贴为表格…", self)
        self._table_paste_action.setShortcut(QKeySequence("Ctrl+Alt+V"))
        self._table_paste_action.setToolTip("把剪贴板 TSV/管道表格预览后插入；普通粘贴保持既有行为")
        self._table_paste_action.triggered.connect(self._on_paste_as_table)
        content_menu.addAction(self._table_paste_action)
        # V3.5：规范包制作（草稿/冻结/导出/隔离样例）
        self._standard_pack_action = QAction("规范包制作…", self)
        self._standard_pack_action.setShortcut(QKeySequence("Ctrl+Alt+P"))
        self._standard_pack_action.setToolTip(
            "从项目或已有规范包创建草稿，冻结导出 ZIP，并在隔离样例中试用"
        )
        self._standard_pack_action.triggered.connect(self._on_standard_pack)
        content_menu.addAction(self._standard_pack_action)
        # V4.1 41-A 1.4：本地模板目录（列表/详情 + 按用途接入既有建项/填充/出稿）
        self._template_library_action = QAction("本地模板目录…", self)
        self._template_library_action.setShortcut(QKeySequence("Ctrl+Alt+L"))
        self._template_library_action.setToolTip(
            "按用途（骨架建项/模板填充/项目出稿）查看本地规范与模板，读真实来源与内容摘要，"
            "并接入既有建项/填充/出稿入口"
        )
        self._template_library_action.triggered.connect(self._on_template_library)
        content_menu.addAction(self._template_library_action)
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
        # RD-A 1.4：研发工作区一个入口集中成员/概览/设置、条目/关系、矩阵/影响、集合/成果。
        self._rd_workspace_action = QAction("研发工作区…", self)
        self._rd_workspace_action.setShortcut(QKeySequence("Ctrl+Alt+D"))
        self._rd_workspace_action.setToolTip(
            "工作区成员与概览、稳定条目与显式关系、矩阵与影响复核、版本集合与成果"
        )
        self._rd_workspace_action.triggered.connect(self._on_rd_workspace)
        content_menu.addAction(self._rd_workspace_action)
        content_menu.addSeparator()
        self._open_external_action = QAction("在外部编辑器打开当前文件", self)
        self._open_external_action.triggered.connect(self._on_content_open_external)
        content_menu.addAction(self._open_external_action)

        # 版本控制 (Git)
        git_menu = menubar.addMenu("版本控制")
        self._switch_branch_action = QAction("切换分支…（编辑器外 Ctrl+B）", self)
        self._switch_branch_action.setShortcut(QKeySequence("Ctrl+B"))
        self._switch_branch_action.setToolTip(
            "切换 Git 分支；编辑器聚焦时 Ctrl+B 是加粗，分支入口仍可从本菜单或命令面板使用"
        )
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

        # UI2-C 3.2：位置后退/前进（Alt+←/→）；与导航条按钮同一 handler。
        self._nav_back_action = QAction("后退", self)
        self._nav_back_action.setShortcut(QKeySequence("Alt+Left"))
        self._nav_back_action.triggered.connect(self._on_nav_back)
        self.addAction(self._nav_back_action)
        self._nav_forward_action = QAction("前进", self)
        self._nav_forward_action.setShortcut(QKeySequence("Alt+Right"))
        self._nav_forward_action.triggered.connect(self._on_nav_forward)
        self.addAction(self._nav_forward_action)

        self._restore_layout_action = QAction("恢复写作布局", self)
        self._restore_layout_action.setToolTip(
            "只重置面板显隐与尺寸：正文、未保存修改、主题、标签与滚动位置保持不变"
        )
        self._restore_layout_action.triggered.connect(self._on_restore_writing_layout)
        self.addAction(self._restore_layout_action)

        self._zen_mode_action = QAction("专注写作模式", self)
        self._zen_mode_action.setShortcut(QKeySequence("F11"))
        self._zen_mode_action.setCheckable(True)
        self._zen_mode_action.setChecked(False)
        self._zen_mode_action.triggered.connect(self.toggle_zen_mode)
        self.addAction(self._zen_mode_action)

        # UI2-C 3.3：写作/对照/阅读与字号档位（菜单/工具条同一 handler）。
        self._view_write_action = QAction("写作视图", self)
        self._view_write_action.triggered.connect(lambda: self._set_view_mode("write"))
        self.addAction(self._view_write_action)
        self._view_compare_action = QAction("对照视图", self)
        self._view_compare_action.triggered.connect(lambda: self._set_view_mode("compare"))
        self.addAction(self._view_compare_action)
        self._view_read_action = QAction("阅读视图", self)
        self._view_read_action.triggered.connect(lambda: self._set_view_mode("read"))
        self.addAction(self._view_read_action)

        self._zoom_in_action = QAction("放大字号", self)
        self._zoom_in_action.setShortcut(QKeySequence("Ctrl+="))
        self._zoom_in_action.triggered.connect(self._on_zoom_in)
        self.addAction(self._zoom_in_action)
        self._zoom_out_action = QAction("缩小字号", self)
        self._zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self._zoom_out_action.triggered.connect(self._on_zoom_out)
        self.addAction(self._zoom_out_action)
        self._zoom_reset_action = QAction("重置字号", self)
        self._zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self._zoom_reset_action.triggered.connect(self._on_zoom_reset)
        self.addAction(self._zoom_reset_action)
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
        for action in (
            getattr(self, "_view_write_action", None),
            getattr(self, "_view_compare_action", None),
            getattr(self, "_view_read_action", None),
        ):
            if action is not None:
                self._view_menu.addAction(action)
        self._view_menu.addSeparator()
        for action in (
            getattr(self, "_zoom_in_action", None),
            getattr(self, "_zoom_out_action", None),
            getattr(self, "_zoom_reset_action", None),
        ):
            if action is not None:
                self._view_menu.addAction(action)
        if hasattr(self, "_restore_layout_action"):
            self._view_menu.addAction(self._restore_layout_action)
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
        # 只把可导入的 Word/.doc 计入批次判定；不支持格式仍按原路由单独提示。
        word_like = [
            item for item in others
            if detect_intake_kind(item) in ("docx", "doc")
        ]
        if not others:
            return
        # MAIN2-A 1.3：多份 Word 走批次（一文件一项目，失败项可接续），
        # 单份仍走既有向导以保留模板/映射选择体验。
        if len(word_like) > 1:
            self._start_word_batch([Path(item) for item in word_like])
            return
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

    def _start_word_batch(self, sources: List[Path]) -> None:
        """多份 Word：调用既有批次服务，结果非模态展示并支持接续。"""
        from doc_tool.application.intake_batch import run_word_batch
        from doc_tool.application.intake_entries import default_project_parent

        batch = run_word_batch(sources, parent_dir=default_project_parent())
        self._last_batch_result = batch
        self._show_batch_result(batch)
        succeeded = list(getattr(batch, "succeeded", []) or [])
        if succeeded:
            # 成功项目立即可编辑：打开第一份并给出可重开的导入结果。
            self._open_import_result(succeeded[0].project_root)

    def _show_batch_result(self, batch) -> None:
        from doc_tool.ui.batch_result_window import BatchResultWindow

        existing = getattr(self, "_batch_result_window", None)
        if existing is not None:
            try:
                existing.close()
                # 关闭只是隐藏：必须显式销毁，否则每次重开都留下一个隐藏窗口。
                existing.deleteLater()
            except RuntimeError:  # noqa: BLE001 - 控件已销毁
                pass
        window = BatchResultWindow(batch, host=self, parent=self)
        self._batch_result_window = window
        window.show()

    def _retry_intake_items(self, batch, sources, window=None) -> bool:
        """接续所选失败/待转换/未开始项，保留输入设置与已成功项目。"""
        from doc_tool.application.intake_batch import retry_selected_word_items

        merged = retry_selected_word_items(batch, sources)
        self._last_batch_result = merged
        retried = len(sources)
        done = len([item for item in merged.items if item.status == "ok"])
        self._show_status_message(
            "已接续 {0} 项；当前可打开 {1} 份（成功项目未重建）".format(retried, done)
        )
        return True

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
        # MAIN2-A：导入后立即进入可编辑状态，结果以**非模态**窗口常驻可重开。
        self._show_intake_result_page(project_root)

    def _build_intake_page(self, project_root: str):
        """读取导入结果页模型（失败返回 None，不影响已生成项目）。"""
        from doc_tool.application.intake_result_page import build_result_page

        try:
            return build_result_page(project_root)
        except Exception:  # noqa: BLE001 - 结果页失败不影响已生成项目
            return None

    def _show_intake_result_page(self, project_root: str) -> None:
        """展示导入结果窗口（非模态、可重开、完整列表可搜索分页）。"""
        page = self._build_intake_page(project_root)
        if page is None:
            return
        if not page.needsAttention and not page.unavailableComparisons and not page.details:
            self._show_status_message("导入完成，可直接编辑")
            return
        self._intake_page = page
        # 同一项目只保留一个结果窗口；再次打开时复用并前置，避免窗口堆积。
        existing = getattr(self, "_intake_result_window", None)
        if existing is not None:
            try:
                existing.close()
                # 关闭只是隐藏：必须显式销毁，否则每次重开都留下一个隐藏窗口。
                existing.deleteLater()
            except RuntimeError:  # noqa: BLE001 - 控件已销毁
                pass
        from doc_tool.ui.intake_result_window import IntakeResultWindow

        window = IntakeResultWindow(page, host=self, parent=self)
        self._intake_result_window = window
        window.show()
        window.raise_()

    def reopen_intake_result(self) -> bool:
        """重开导入结果窗口（菜单/快捷键入口）；没有记录时给出下一步。"""
        project_root = ""
        if self._project_summary is not None:
            project_root = str(self._project_summary.project_root or "")
        if not project_root:
            self._show_status_message("当前没有打开的项目：导入或打开项目后可查看导入结果")
            return False
        from doc_tool.application.import_record import read_import_record

        if read_import_record(Path(project_root)) is None:
            self._show_status_message("该项目没有导入记录（Markdown/规范包建项属于该情况）")
            return False
        self._show_intake_result_page(project_root)
        return True

    def _locate_intake_finding(self, page, item, window=None) -> None:
        """定位一条处理事实（绑定本项目窗口，不串同名相对路径）。"""
        rel_path = str(item.get("target_path") or "")
        if not rel_path:
            from doc_tool.application.intake_result_page import resolve_chapter_rel_path

            rel_path = resolve_chapter_rel_path(
                getattr(page, "projectRoot", "") or "", str(item.get("target_chapter") or "")
            )
        line = item.get("target_line")
        line = line if isinstance(line, int) else None
        if rel_path and self._open_chapter_in_workspace(rel_path, line, source="导入结果定位"):
            self._show_status_message("已定位到章节：{0}".format(rel_path))
            return
        self._show_status_message("请在章节树中定位：{0}".format(
            item.get("target_chapter") or item.get("detail") or item.get("feature") or ""
        ))

    def _open_intake_original(self, page, item) -> None:
        """查看原件（缺文件时给出可执行的下一步，不静默失败）。"""
        retained = str(item.get("retained_path") or page.retainedPath or "original/source.docx")
        target = Path(str(page.projectRoot or "")) / retained
        if target.is_file():
            self._on_open_result_output(str(target))
            return
        self._show_status_message("原件不存在：{0}（可继续编辑正文，或从来源重新导入）".format(retained))

    def _replace_intake_image(self, page, item, window=None) -> bool:
        """用项目外图片替换占位（复用资产入库与写入服务），成功返回 True。"""
        from doc_tool.application.intake_result_page import replace_placeholder_image

        chosen, _selected = QFileDialog.getOpenFileName(
            self, "选择替代图片", "",
            "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*)",
        )
        if not chosen:
            return False
        outcome = replace_placeholder_image(
            str(page.projectRoot or ""), str(item.get("target_path") or ""), chosen,
            line=item.get("target_line") if isinstance(item.get("target_line"), int) else None,
        )
        self._show_status_message(outcome.summary_line())
        if outcome.ok and getattr(self, "_content_workspace", None) is not None:
            try:
                self._content_workspace._rebuild_index()
            except Exception:  # noqa: BLE001 - 索引刷新失败不影响已替换的正文
                pass
        return bool(outcome.ok)

    def _show_intake_details(self, page) -> None:
        """兼容入口：完整处理事实现在由非模态结果窗口承载（不截断）。"""
        self._show_intake_result_page(getattr(page, "projectRoot", "") or "")

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
        if rel_path and self._open_chapter_in_workspace(
            rel_path, action.line, source="导入结果定位"
        ):
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
        logger.info("ui/status_message: %s", message)

    # --- 命令注册表（V3.1 4.2 / V3.3 5.3）：菜单与命令面板同源 ---

    def _command_context(self):
        """当前上下文（项目/可写/空闲/选区/缓冲），供注册表判定可用性。"""
        from doc_tool.application.command_registry import CommandContext

        summary = self._project_summary
        running = bool(getattr(self.runner, "is_running", False))
        has_selection = False
        has_buffer = False
        try:
            # UI 包 4.2 修复：此前调用的是不存在的 _current_editor，异常被下面的
            # except 吞掉，导致「选区/缓冲」上下文恒为假（命令可用性判定失真）。
            editor = self._active_editor()
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
                title="导入 / 新建项目（Word / Markdown）…",
                category="文件",
                shortcut="Ctrl+N",
                description="与「导出」入口同一 intake 路由：自动识别源类型并真实建项",
                callback=self._on_import_document,
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
                    callback=self._on_save_all,
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
                    callback=self._on_merge,
                )
            )
            items.append(
                PaletteItem(
                    title="快速构建（草稿）",
                    category="构建",
                    callback=self._on_diag_build,
                )
            )
            items.append(
                PaletteItem(
                    title="项目结构与资源校验",
                    category="校验",
                    shortcut="F5",
                    callback=self._on_validate,
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
                title="以 Markdown 起步建项（按文件顺序）…",
                category="新建",
                description="显式选定多个 Markdown 并按列表顺序组稿成一份项目",
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
                title="本地模板目录（规范/模板/出稿）…",
                category="工具",
                callback=lambda: self._on_template_library(),
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
                    # V3.4：表格网格与显式表格粘贴也从命令面板可达
                    items.append(
                        PaletteItem(
                            title="编辑表格网格",
                            category="编辑",
                            shortcut="Ctrl+Alt+G",
                            callback=editor.open_table_grid,
                        )
                    )
                    items.append(
                        PaletteItem(
                            title="粘贴为表格",
                            category="编辑",
                            shortcut="Ctrl+Alt+V",
                            callback=editor.paste_as_table,
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
        running = bool(self.runner.is_running)
        if state.view == WorkView.EMPTY:
            self._stack.setCurrentWidget(self._empty_state)
            self._task_dock_widget.hide()
            self._project_bar.reset()
            if hasattr(self, "_branch_btn"):
                self._branch_btn.setVisible(False)
            self._set_git_menu_enabled(False)
        else:
            self._stack.setCurrentWidget(self._ide_page)
            # 任务/结果 Dock 只在确有任务或用户主动要求时展开：首用默认布局下
            # 空闲工作台不再强迫大面板占据正文空间（可随时从视图菜单找回）。
            if running or getattr(self, "_writing_layout_task_dock", True):
                self._task_dock_widget.show()
            else:
                self._task_dock_widget.hide()
            # 顶部快速导出提示必须反映真实未保存数量，不由菜单/按钮各自猜测。
            self._project_bar.set_pending_edits(len(self._collect_buffer_texts()))
            self._project_bar.set_round_count(
                len(
                    self._export_rounds.for_project(
                        getattr(self._project_summary, "project_root", "")
                    )
                )
            )
            self._project_bar.render(self._project_summary, state)
            # 右侧 Dock 内容由任务生命周期驱动，不在此覆盖 running/result
            if state.view == WorkView.IDLE and not self.runner.is_running:
                self._task_dock.show_idle(
                    self._result_state if self._result_state.is_terminal else None,
                    project_open=True,
                )

        # 导入/新建合并为同一入口后，运行中统一禁用该入口（保持原保护）。
        self._import_action.setEnabled(not running)
        self._open_action.setEnabled(not running)
        if hasattr(self, "_open_new_action"):
            self._open_new_action.setEnabled(not running)
        self._validate_action.setEnabled(state.actions["validate"].enabled)
        self._merge_action.setEnabled(state.actions["merge"].enabled)
        # 按钮/菜单/Ctrl+E 共用同一 quick_export 可用性（删旧高级轮次不改变默认）。
        quick_export = state.actions.get("quick_export")
        self._quick_export_action.setEnabled(bool(quick_export and quick_export.enabled))
        if quick_export is not None and not quick_export.enabled and quick_export.reason:
            self._quick_export_action.setToolTip(quick_export.reason)
        else:
            self._quick_export_action.setToolTip(
                "默认整份文档 + 当前编辑内容 + Word + 项目导出目录 (Ctrl+E)"
            )
        self._diag_action.setEnabled(state.actions["diag_build"].enabled)
        self._report_action.setEnabled(state.actions["report"].enabled)
        self._content_action.setEnabled(state.actions["content"].enabled)
        self._output_action.setEnabled(state.actions["output"].enabled)
        self._logs_action.setEnabled(state.actions["logs"].enabled)
        self._settings_action.setEnabled(bool(self._project_summary) and not running)
        self._reimport_action.setEnabled(bool(self._project_summary) and not running)
        if hasattr(self, "_close_action"):
            self._close_action.setEnabled(bool(self._project_summary) and not running)

        if hasattr(self, "_search_project_action"):
            self._search_project_action.setEnabled(
                self._content_workspace_available() and not running
            )
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
        # UI2-C 3.2：项目隔离的历史栈（切换项目即清空，不跨项目回放）。
        from doc_tool.ui.navigation_history import NavigationHistory

        self._nav_history = NavigationHistory(str(summary.project_root))
        self._refresh_navigation_ui()

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
        # UI 包 3.1：重开项目时沿用既有报告索引恢复最近一轮成果（只存引用）。
        self._last_export_round = None
        self._load_last_export_round()
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
            on_navigate=self._on_content_navigate,
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
        self._sync_view_controls()

    def _sync_view_controls(self) -> None:
        """把当前编辑器的视图/字号同步到工具条（不回写正文）。"""
        editor = self._active_panel()
        if editor is None:
            return
        combo = getattr(self, "_view_mode_combo", None)
        if combo is not None and hasattr(editor, "view_mode"):
            index = combo.findData(editor.view_mode())
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

    # --- UI2-C 3.1/3.2：章节路径、定位当前章与位置后退/前进 ---

    def _on_content_navigate(self, rel_path: str, line_no, source: str) -> None:
        """记录一次主动导航（不回放正文；同一位置合并）。"""
        from doc_tool.ui.navigation_history import NavLocation

        workspace = getattr(self, "_content_workspace", None)
        if workspace is None or not rel_path:
            return
        from doc_tool.ui.navigation_history import NavigationHistory

        if not isinstance(getattr(self, "_nav_history", None), NavigationHistory):
            self._nav_history = NavigationHistory(
                str(getattr(self._project_summary, "project_root", "") or "")
            )
        location = NavLocation(
            rel_path=rel_path,
            cursor=0,
            scroll=0,
            source=str(source or "导航"),
            project_root=str(getattr(self._project_summary, "project_root", "") or ""),
        )
        current = workspace.current_location()
        if current is not None and current.rel_path == rel_path:
            location.cursor = current.cursor
            location.scroll = current.scroll
        self._nav_history.record(location)
        self._refresh_navigation_ui()

    def _nav_record_current(self, source: str) -> None:
        """把当前编辑器位置登记为一条导航记录（跳转前调用）。"""
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None:
            return
        location = workspace.current_location()
        if location is None:
            return
        from doc_tool.ui.navigation_history import NavigationHistory

        if not isinstance(getattr(self, "_nav_history", None), NavigationHistory):
            self._nav_history = NavigationHistory(
                str(getattr(self._project_summary, "project_root", "") or "")
            )
        location.source = str(source or "当前位置")
        location.project_root = str(
            getattr(self._project_summary, "project_root", "") or ""
        )
        self._nav_history.record(location)
        self._refresh_navigation_ui()

    def _refresh_navigation_ui(self) -> None:
        history = getattr(self, "_nav_history", None)
        back_btn = getattr(self, "_nav_back_btn", None)
        forward_btn = getattr(self, "_nav_forward_btn", None)
        if history is None or back_btn is None or forward_btn is None:
            return
        back_btn.setEnabled(history.can_back())
        forward_btn.setEnabled(history.can_forward())
        back_btn.setToolTip(
            "回到上一个位置（{0}）".format(
                history.entries()[history._index - 1].describe()
            ) if history.can_back() else "没有可后退的位置"
        )
        forward_btn.setToolTip(
            "前进到下一个位置（{0}）".format(
                history.entries()[history._index + 1].describe()
            ) if history.can_forward() else "没有可前进的位置"
        )
        label = getattr(self, "_nav_location_label", None)
        if label is not None:
            current = history.current()
            label.setText(current.rel_path if current is not None else "未打开章节")
            if current is not None:
                label.setToolTip(
                    "完整路径：{0}\n来源：{1}\n（右键可复制完整路径）".format(
                        current.rel_path, current.source or "导航"
                    )
                )

    def _on_nav_back(self) -> None:
        history = getattr(self, "_nav_history", None)
        if history is None:
            return
        step = history.back()
        if step is None:
            self._show_status_message("已到最早的位置")
            return
        target, message = step
        self._replay_navigation(target, message)

    def _on_nav_forward(self) -> None:
        history = getattr(self, "_nav_history", None)
        if history is None:
            return
        step = history.forward()
        if step is None:
            self._show_status_message("已到最新的位置")
            return
        target, message = step
        self._replay_navigation(target, message)

    def _replay_navigation(self, target, message: str) -> None:
        """重放历史位置：只在原 EditorPanel 上还原光标/滚动，不加载旧正文。"""
        workspace = getattr(self, "_content_workspace", None)
        history = getattr(self, "_nav_history", None)
        if workspace is None or history is None or target is None:
            return
        editor = workspace.tabs_host.editor_for(target.rel_path)
        if editor is None:
            self._show_status_message(
                "该位置对应文件已不再打开或已删除：{0}（可继续后退到有效位置）".format(
                    target.rel_path
                )
            )
            self._refresh_navigation_ui()
            return
        history.suppress_next()
        # 只在真的重放时消耗一次抑制标记：失败路径不得留悬挂标记，
        # 否则后续主动导航会被误判为重放而不入栈（审计发现的真实回归）。
        if not workspace.restore_location(target):
            self._show_status_message("无法还原位置：{0}".format(target.rel_path))
            return
        self._refresh_navigation_ui()
        self._status_label.setText(message)

    def _on_locate_current_chapter(self) -> None:
        """定位当前章：选中章节树中的真实节点并给出完整路径。"""
        rel_path = self._content_current_file or (
            self._content_workspace.current_file()
            if getattr(self, "_content_workspace", None) is not None
            and hasattr(self._content_workspace, "current_file")
            else None
        )
        if not rel_path:
            self._show_status_message("当前没有打开的章节")
            return
        try:
            self._content_workspace.tree_host.select_file(rel_path)
        except Exception:  # noqa: BLE001 - 树未就绪时只给文字
            pass
        self._status_label.setText("已定位当前章：{0}".format(rel_path))

    def _on_copy_current_path(self) -> None:
        rel_path = self._content_current_file
        if not rel_path:
            self._show_status_message("当前没有打开的章节")
            return
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(rel_path)
        self._status_label.setText("已复制完整章节路径：{0}".format(rel_path))

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

    def _on_content_search_project(self) -> None:
        """Ctrl+Shift+F：始终打开项目全文搜索面板（不受编辑器焦点影响）。"""
        if not self._content_workspace_available():
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
            workspace.open_file(rel_path, line_no, source="引用/搜索结果")

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
        """批量交付首用入口：新建表单或打开已有计划，再走既有 TaskRunner 串行执行。

        UI 包 4.1：没有 batch.json 也能从按钮完成首次交付，不再要求先手写 JSON。
        """
        if self.runner.is_running:
            self._show_status_message("已有任务正在运行，本次批量交付未开始")
            return
        from doc_tool.application.delivery import gui_tasks

        default_dir = str(getattr(self, "_last_delivery_dir", "") or "")
        plan_path = self._choose_delivery_plan(default_dir)
        if not plan_path:
            return
        self._last_delivery_dir = str(Path(plan_path).parent)
        if self._last_delivery_preview is not None:
            preview = self._last_delivery_preview
        else:
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

    def _ask_delivery_mode(self) -> str:
        """询问交付方式：``new`` 新建批次表单 / ``open`` 打开已有计划 / ``""`` 取消。

        抽成独立方法便于测试与复用；GUI 上仍是原生按钮对话框。
        """
        box = QMessageBox(self)
        box.setWindowTitle("批量交付")
        box.setText(
            "新建批次：填写成员/格式/目录后生成 batch.json 并开始交付。\n"
            "打开已有计划：选择已有 batch.json（保持原有高级路径）。"
        )
        new_button = box.addButton("新建批次…", QMessageBox.ButtonRole.AcceptRole)
        open_button = box.addButton("打开已有计划…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is new_button:
            return "new"
        if clicked is open_button:
            return "open"
        return ""

    def _choose_delivery_plan(self, default_dir: str) -> str:
        """让用户选择「新建批次表单」或「打开已有 batch.json」；返回计划路径。

        保留高级包文件入口；新建路径生成原 batch 格式并经过原服务校验。
        无计划且未选择时默认走「打开已有计划」，兼容旧入口的主要提交路径。
        """
        from doc_tool.ui.delivery_form_dialog import DeliveryFormDialog

        self._last_delivery_preview = None
        mode = self._ask_delivery_mode()
        if mode == "new":
            dialog = DeliveryFormDialog(default_dir=default_dir, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._show_status_message("已取消新建批次")
                return ""
            plan_path = dialog.plan_path()
            if plan_path is None or not Path(plan_path).is_file():
                self._show_status_message("批次表单已关闭，未生成计划")
                return ""
            self._last_delivery_preview = self._delivery_preview_from_plan(
                dialog.validated()
            )
            self._show_status_message("已生成批次计划：{0}".format(plan_path))
            return str(plan_path)
        if mode in ("open", ""):
            chosen, _selected = QFileDialog.getOpenFileName(
                self, "选择批次计划（batch.json）", default_dir,
                "批次计划 (*.json);;所有文件 (*)",
            )
            return chosen or ""
        return ""

    def _delivery_preview_from_plan(self, plan) -> dict:
        """把已校验的表单计划转成既有预览结构（与 gui_tasks.plan_preview 同形）。"""
        from doc_tool.application.delivery import gui_tasks

        try:
            return gui_tasks.plan_preview(plan.planPath)
        except Exception:  # noqa: BLE001 - 预览失败时回退为计划摘要
            return {
                "summary": plan.summary_lines(),
                "executable": bool(plan.executable_entries()),
                "invalid": [entry.to_dict() for entry in plan.invalid_entries()],
                "view": {"rows": []},
            }

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

        dialog = ReuseDialog(
            self._project_summary.project_root,
            self,
            buffer_source=self._module_buffer_source,
            on_insert_module=self._on_module_insert_requested,
        )
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _module_buffer_source(self):
        """当前章节的内存缓冲快照（relPath, text）；无脏缓冲返回 ("", "")。

        明确区分缓冲/保存来源：只有编辑器里有未保存修改时才提供字符串快照，
        避免「当前正文为空时拿旧磁盘内容冒充创建来源」。
        """
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None:
            return "", ""
        rel = workspace.tabs_host.current_rel_path()
        if not rel:
            return "", ""
        editor = workspace.tabs_host.editor_for(rel)
        if editor is None or not editor.is_dirty():
            return "", ""
        text = editor.plain_text()
        document_type = ""
        try:
            document_type = str(self._project_summary.manifest.documentType or "")
        except Exception:  # noqa: BLE001
            document_type = ""
        key = str(rel).replace("\\", "/")
        if document_type and key.startswith(document_type + "/"):
            key = key[len(document_type) + 1:]
        return key, text

    def _active_editor(self):
        """当前活动编辑器（工作区未就绪时返回 None，不抛异常）。"""
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None:
            return None
        try:
            return workspace.current_editor()
        except Exception:  # noqa: BLE001 - 编辑器不可用时按无编辑器处理
            return None

    def _on_module_insert_requested(self, text: str, mode: str) -> bool:
        """把模块引用/正文一次插入当前编辑器（可一次撤销）；无编辑器返回 False。"""
        editor = self._active_editor()
        if editor is None:
            self._show_status_message("请先打开一个章节，再插入模块")
            return False
        editor.insert_template(text)
        self._show_status_message(
            "已插入模块{0}（可一次撤销）".format("固定引用" if mode == "reference" else "正文副本")
        )
        return True

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
            on_scope_changed=self._on_assist_scope_changed,
            parent=self,
        )
        panel.insert_requested.connect(self._on_assist_insert_requested)
        panel.summary_candidate.connect(self._on_assist_summary_candidate)
        panel.buffers_changed.connect(self._on_assist_buffers_changed)
        panel.status_message.connect(lambda message: self._show_status_message(message))
        self._assist_scope_roots = []
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

    def _on_assist_scope_changed(self, roots) -> None:
        """资料范围变更：用新范围重装助手（旧的检索结果不覆盖新范围）。"""
        self._assist_scope_roots = [str(item) for item in (roots or [])]
        panel = None
        dock = getattr(self, "_assist_dock", None)
        if dock is not None:
            panel = dock.widget()
        if panel is None:
            return
        try:
            from doc_tool.application.assist.service import build_assistant

            assistant = build_assistant(
                str(self._project_summary.project_root),
                module_roots=self._assist_scope_roots,
            )
            buffers = self._collect_buffer_texts()
            if buffers:
                assistant.set_buffers(buffers)
            panel.set_assistant(assistant)
            self._show_status_message(
                "资料范围已更新：{0} 个来源".format(len(self._assist_scope_roots) + 1)
            )
        except Exception as exc:  # noqa: BLE001 - 范围更新失败不阻断本地检索
            self._show_status_message("资料范围更新未生效：{0}".format(exc))

    def _open_chapter_in_workspace(
        self, rel_path: str, line: Optional[int] = None, *, source: str = "章节"
    ) -> bool:
        """在编辑器中打开章节：工作区 relPath 带文档类型前缀（如 ``general/第1章 …``）。

        ``source`` 会进入位置历史（章节树/搜索/问题/资料），用于后退说明。
        """
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
                workspace.open_file(candidate, line, source=source)
            except TypeError:  # 旧签名（无行号/无来源）
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
                if self._open_chapter_in_workspace(rel_path, source="资料面板"):
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

    def _quick_export_defaults(self, buffers: Dict[str, str]):
        """快速出稿的日常默认：整份 + 当前缓冲优先 + 项目导出目录。

        每次都从零构造请求，因此**不会**继承上一轮的部分章节范围、saved 来源
        或 strict 策略；旧高级决定只影响旧轮次本身。``refresh`` 保持默认，
        本机没有 Microsoft Word 时仍会产出可读 DOCX（结果标「待刷新」）。
        """
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX,
            SCOPE_PROJECT,
            SOURCE_MODE_CURRENT_BUFFER,
            SOURCE_MODE_SAVED,
            ExportRequest,
            ExportScope,
        )

        return ExportRequest(
            project_root=str(self._project_summary.project_root),
            formats=[FORMAT_DOCX],
            scope=ExportScope(kind=SCOPE_PROJECT),
            source_mode=SOURCE_MODE_CURRENT_BUFFER if buffers else SOURCE_MODE_SAVED,
            destination=str(self._project_summary.paths.output_dir),
        )

    def _export_settings_context(self) -> dict:
        """导出设置需要的真实上下文：章节、当前章、未保存数、目录、变体。"""
        from doc_tool.application.effective_snapshot import discover_chapters

        summary = self._project_summary
        chapters = []
        variants = []
        if summary is not None:
            try:
                content_root = summary.paths.resolve(
                    summary.manifest.relative_content_root()
                )
                chapters = [rel for rel, _path in discover_chapters(content_root)]
            except Exception:  # noqa: BLE001 - 索引不可用时按整份
                chapters = []
            try:
                variants = [
                    item.get("variantId") or item.get("name")
                    for item in (
                        self._preview_text_resolver() or []
                    )
                ] if False else []
            except Exception:  # noqa: BLE001
                variants = []
            if not variants:
                try:
                    from doc_tool.application.content.variants import VariantsConfig

                    variants = list(VariantsConfig.load(summary.project_root).ids())
                except Exception:  # noqa: BLE001 - 无变体配置时留空
                    variants = []
        return {
            "project_root": str(getattr(summary, "project_root", "") or ""),
            "destination": str(summary.paths.output_dir) if summary is not None else "",
            "chapters": chapters,
            "current_chapter": self._content_current_file or "",
            "unsaved_count": len(self._collect_buffer_texts()),
            "variants": variants,
        }

    def _on_export_settings(self, preset_request=None, *, notice="") -> None:
        """打开导出设置；一次“开始导出”即提交原服务。"""
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog

        if self._project_summary is None:
            self._show_status_message("请先打开项目后再使用导出设置")
            return
        context = self._export_settings_context()
        dialog = ExportSettingsDialog(
            project_root=context["project_root"],
            destination=context["destination"],
            chapters=context["chapters"],
            current_chapter=context["current_chapter"],
            unsaved_count=context["unsaved_count"],
            variants=context["variants"],
            notice=notice,
            parent=self,
        )
        if preset_request is not None:
            dialog.apply_request(preset_request)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_label.setText("已取消导出设置：编辑缓冲与原有成果保持不变")
            return
        request = dialog.submitted_request()
        if request is None:
            return
        self._submit_export_request(request)

    def _submit_export_request(self, request) -> None:
        """用原 TaskRunner 提交一次导出；当前缓冲在 UI 线程采集后传入后台。"""
        from doc_tool.application.intake_contract import SOURCE_MODE_CURRENT_BUFFER
        from doc_tool.application.project_export import run_project_export

        buffers = (
            self._collect_buffer_texts()
            if request.source_mode == SOURCE_MODE_CURRENT_BUFFER
            else {}
        )
        self._run_export_task(
            name="project-export",
            target=run_project_export,
            args=(request,),
            kwargs={"buffer_texts": buffers},
            message="正在按导出设置生成（{0}）…".format(
                "、".join(request.formats)
            ),
        )

    def _on_quick_export_word(self) -> None:
        """快速导出 Word：整份 + 当前内容 + 项目导出目录（默认值，可再调整）。"""
        if self._project_summary is None:
            return
        if self.runner.is_running:
            # 忙时只拒绝重复启动：运行中的任务/轮次保持，编辑与成果查看不受影响。
            self._status_label.setText("已有任务正在运行，本次导出未开始；可继续编辑或查看已有成果")
            return
        from doc_tool.application.project_export import run_project_export

        buffers = self._collect_buffer_texts()
        request = self._quick_export_defaults(buffers)
        # 出稿在既有 TaskRunner 后台线程执行：界面可继续编辑，任务 Dock 可取消，
        # 重复点击由 runner.is_running 与动作禁用共同防重。
        from doc_tool.ui.task_bridge import TaskSpec

        spec = TaskSpec(
            name="project-export",
            target=run_project_export,
            args=(request,),
            kwargs={"buffer_texts": buffers},
            timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        )
        self._status_label.setText(
            "正在生成 Word…（{0}）".format(
                "含 {0} 章未保存修改".format(len(buffers)) if buffers else "整份已保存内容"
            )
        )
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

    # --- UI 包 UI-C：非模态成果（逐文件、按轮次） ---

    def _record_export_round(self, report) -> object:
        """把一轮真实报告登记到成果视图，并刷新入口计数（只存引用）。"""
        from doc_tool.ui.export_rounds import round_view_from_report

        view = round_view_from_report(report)
        self._export_rounds.record(view)
        self._selected_round_id = view.round_id
        return view

    def _refresh_export_results(self, report=None) -> None:
        """按项目刷新成果页；有报告时先登记该轮，再展示本项目最近轮次。"""
        if report is not None:
            self._record_export_round(report)
        root = getattr(self._project_summary, "project_root", "")
        rounds = self._export_rounds.for_project(root)
        self._task_dock.show_results(rounds, self._selected_round_id)
        self._project_bar.set_round_count(len(rounds))

    def _on_show_results(self) -> None:
        """「成果」入口：找回本项目最近结果（关闭面板后仍可用）。"""
        if self._project_summary is None:
            self._show_status_message("请先打开项目，再查看出稿成果")
            return
        rounds = self._export_rounds.for_project(
            getattr(self._project_summary, "project_root", "")
        )
        if not rounds and self._last_export_round is None:
            self._load_last_export_round()
            rounds = self._export_rounds.for_project(
                getattr(self._project_summary, "project_root", "")
            )
        self._task_dock_widget.show()
        self._task_dock_widget.raise_()
        self._refresh_export_results()
        self._status_label.setText(
            "本项目有 {0} 轮出稿成果".format(len(rounds))
            if rounds
            else "本项目还没有出稿成果；可先用顶部「导出 Word」生成一轮"
        )

    def _load_last_export_round(self, *, force: bool = False) -> None:
        """重开项目时从既有报告索引恢复最近一轮（沿用索引，不另建状态）。"""
        summary = self._project_summary
        if summary is None:
            return
        root = str(getattr(summary, "project_root", "") or "")
        if not force and self._export_rounds.latest(root) is not None:
            return
        try:
            output_dir = summary.paths.output_dir
        except Exception:  # noqa: BLE001 - 缺少输出目录时不恢复
            return
        from doc_tool.ui.export_rounds import load_round_from_index

        view = load_round_from_index(output_dir)
        if view is None:
            return
        self._export_rounds.record(view)
        self._selected_round_id = view.round_id
        self._last_export_round = view

    def _on_select_export_round(self, round_id: str) -> None:
        self._selected_round_id = str(round_id or "")

    def _on_open_export_format(self, fmt: str, path: str) -> None:
        """逐格式打开：只打开本轮真实路径，失效时给重新定位/重新生成建议。"""
        if path and Path(path).is_file():
            self._on_open_result_output(path)
            return
        self._show_status_message(
            "{0} 产物路径已失效（{1}）：可重新定位或按当前修改重新生成".format(
                fmt or "该格式", path or "未记录路径"
            )
        )

    def _round_request(self, view, report=None):
        """由成果轮次重建出稿请求（原轮范围/来源/目录，不读新正文）。"""
        from doc_tool.application.intake_contract import ExportRequest, ExportScope

        if report is None:
            report = self._report_for_round(view)
        scope = self._scope_for_export_round(view, report)

        return ExportRequest(
            project_root=view.project_root or str(self._project_summary.project_root),
            formats=[item.format for item in view.formats] or ["docx"],
            scope=ExportScope.from_dict(scope.to_dict()) if scope is not None else ExportScope(),
            source_mode=view.source_mode or "saved",
            destination=view.destination,
            output_name=str(getattr(report, "outputName", "") or ""),
            capture_id=str(getattr(report, "captureId", "") or ""),
        )

    def _run_export_task(self, *, name: str, target, args, kwargs, message: str) -> None:
        """走既有 TaskRunner 的后台出稿（Word 仍串行；忙时不覆盖当前任务）。"""
        if self._project_summary is None:
            return
        if self.runner.is_running:
            self._status_label.setText(
                "已有任务正在运行，本次未开始；可继续编辑或查看已有成果"
            )
            return
        from doc_tool.ui.task_bridge import TaskSpec

        spec = TaskSpec(
            name=name,
            target=target,
            args=args,
            kwargs=kwargs,
            timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        )
        self._status_label.setText(message)
        self._start_task(spec, on_done=self._on_export_task_done)

    def _on_retry_export_round(self, view) -> None:
        """补这次成果：用旧捕获与原范围只补缺失/失败格式，不读当前新正文。"""
        from doc_tool.application.project_export import retry_export_formats

        report = self._report_for_round(view)
        if report is None:
            self._show_status_message("原轮报告不可用：请按当前修改重新生成一轮")
            return
        pending = [
            item.format for item in view.formats
            if item.status in ("failed", "pending-convert", "pending-refresh")
        ]
        if not pending:
            self._show_status_message("本轮没有需要补的格式")
            return
        self._status_label.setText(
            "正在用原轮捕获补 {0}…".format("、".join(pending))
        )
        self._run_export_task(
            name="project-export",
            target=retry_export_formats,
            args=(report, pending),
            kwargs={"request": self._round_request(view, report)},
            message="正在补本轮缺失格式（沿用原捕获）…",
        )

    def _report_for_round(self, view):
        """取回该轮真实报告，并校验 roundId/captureId 身份。

        同目录 ``export-result.json`` 会被新轮覆盖：若读到的报告不是所选轮，
        返回 None，并由新轮/设置入口继续，不能拿最新索引冒充旧轮。
        """
        from doc_tool.application.project_export import read_export_index

        candidates = []
        if view.index_path and Path(view.index_path).is_file():
            candidates.append(Path(view.index_path))
        summary = self._project_summary
        if summary is not None:
            try:
                candidates.append(Path(summary.paths.output_dir))
            except Exception:  # noqa: BLE001 - 缺输出目录时只用已知索引
                pass
        for candidate in candidates:
            report = read_export_index(candidate)
            if report is None:
                continue
            if self._round_identity_matches(view, report):
                return report
        return None

    @staticmethod
    def _round_identity_matches(view, report) -> bool:
        """轮次身份校验：roundId 必须相等；已知 captureId 必须得到匹配。

        历史引用只保存了 roundId 时不得因缺少 captureId 而误判失配。
        """
        wanted_round = str(getattr(view, "round_id", "") or "")
        got_round = str(getattr(report, "roundId", "") or "")
        if not wanted_round or not got_round or wanted_round != got_round:
            return False
        wanted_capture = str(getattr(view, "capture_id", "") or "")
        got_capture = str(getattr(report, "captureId", "") or "")
        return bool(got_capture and (not wanted_capture or wanted_capture == got_capture))

    @staticmethod
    def _scope_for_export_round(view, report):
        if report is not None and getattr(report, "scopeKnown", True):
            return getattr(report, "scope", None)
        return getattr(view, "scope", None)

    def _new_round_request(self, view, *, destination=None, force_source=None):
        """带入原范围创建新轮；失效范围回到可见设置，不静默扩大范围。

        ``force_source`` 显式指定本轮来源（``current-buffer`` 用于“按最新内容
        重新生成”），缺省时沿用原轮报告里的真实来源，避免把未保存缓冲悄悄
        混进“已保存来源”的新轮。
        """
        from doc_tool.application.intake_contract import (
            SCOPE_CHAPTERS,
            SCOPE_CURRENT_CHAPTER,
            SOURCE_MODE_CURRENT_BUFFER,
            SOURCE_MODE_SAVED,
        )

        report = self._report_for_round(view)
        scope = self._scope_for_export_round(view, report)
        request = self._round_request(view, report)
        request.project_root = str(self._project_summary.project_root)
        request.capture_id = ""
        request.destination = destination or view.destination or str(self._project_summary.paths.output_dir)
        buffers = self._collect_buffer_texts()
        # 来源范围必须沿用原轮事实：已保存来源的旧轮换目录/重新生成时不得
        # 静默把编辑器缓冲注入进来（否则报告写“已保存”却导出了未保存正文）。
        previous_mode = str(getattr(report, "sourceMode", "") or "")
        if force_source == SOURCE_MODE_SAVED:
            request.source_mode, buffers = SOURCE_MODE_SAVED, {}
        elif force_source == SOURCE_MODE_CURRENT_BUFFER:
            request.source_mode = SOURCE_MODE_CURRENT_BUFFER
        elif previous_mode == SOURCE_MODE_SAVED:
            request.source_mode, buffers = SOURCE_MODE_SAVED, {}
        elif previous_mode == SOURCE_MODE_CURRENT_BUFFER:
            request.source_mode = SOURCE_MODE_CURRENT_BUFFER
        else:
            request.source_mode = SOURCE_MODE_CURRENT_BUFFER if buffers else SOURCE_MODE_SAVED
        missing = scope is None
        if scope is not None and scope.kind in (SCOPE_CHAPTERS, SCOPE_CURRENT_CHAPTER):
            available = set(self._export_settings_context()["chapters"])
            wanted = scope.chapters if scope.kind == SCOPE_CHAPTERS else [scope.current]
            missing = not wanted or any(chapter not in available for chapter in wanted)
        if missing:
            notice = "原范围缺失或部分章节已不可用：请查看下方实际范围，可改选章节或整份后开始导出。旧成果保留。"
            self._on_export_settings(request, notice=notice)
            return None, {}
        return request, buffers

    def _on_regenerate_round(self, view) -> None:
        """按当前修改重新生成：UI 线程收集缓冲，后台建立新 current-buffer 轮次。"""
        from doc_tool.application.intake_contract import SOURCE_MODE_CURRENT_BUFFER
        from doc_tool.application.project_export import run_project_export

        if self._project_summary is None:
            return
        # 该入口的语义就是“按最新内容”：原轮即使是已保存来源，这一轮也明确
        # 建立 current-buffer 捕获（不静默沿用旧来源口径）。
        request, buffers = self._new_round_request(
            view, force_source=SOURCE_MODE_CURRENT_BUFFER
        )
        if request is None:
            return
        self._run_export_task(
            name="project-export",
            target=run_project_export,
            args=(request,),
            kwargs={"buffer_texts": buffers},
            message="正在按当前修改建立新一轮（含 {0} 章未保存修改）…".format(
                len(buffers)
            ) if buffers else "正在按当前修改建立新一轮…",
        )

    def _on_export_settings_for_round(self, view) -> None:
        """从旧轮打开导出设置：带入可解析的原范围/格式/目录，提交产生新轮。

        原范围从真实报告或生成时结构化视图读取（不从 scope_text 反解析）；
        无法恢复时在表单内显示默认范围，供用户明确提交。
        """
        if view is None or self._project_summary is None:
            return
        preset = self._round_request(view)
        preset.capture_id = ""
        preset.destination = preset.destination or str(self._project_summary.paths.output_dir)
        report = self._report_for_round(view)
        notice = ""
        if self._scope_for_export_round(view, report) is None:
            notice = "原范围无法恢复，当前预填整份文档；可改选范围后生成新轮。旧成果保留。"
        self._on_export_settings(preset, notice=notice)

    def _on_change_export_destination(self, view) -> None:
        """换目录并重新导出：明示来源/范围，建立新轮，旧成果保留。"""
        from doc_tool.application.project_export import run_project_export

        if self._project_summary is None:
            return
        chosen = QFileDialog.getExistingDirectory(
            self, "选择新的导出目录（默认按当前内容建立新轮）", view.destination or ""
        )
        if not chosen:
            self._status_label.setText("已取消换目录：原成果保持不变")
            return
        request, buffers = self._new_round_request(view, destination=chosen)
        if request is None:
            return
        self._run_export_task(
            name="project-export",
            target=run_project_export,
            args=(request,),
            kwargs={"buffer_texts": buffers},
            message="正在导出到新目录（新轮次；旧成果保留）…",
        )

    def _present_export_report(self, report, *, allow_retry: bool = True) -> None:
        """出稿结果：先登记非模态成果，再给可打开产物与恢复动作。

        使用模块级 ``QMessageBox``（不在函数内重新导入），这样离屏测试可以
        整体替换为记录器而不会弹出真模态框。
        """
        self._refresh_export_results(report)
        try:
            usable = len(report.usable_results())
        except Exception:  # noqa: BLE001 - 报告形态异常时不给假成功
            usable = 0
        rounds = len(
            self._export_rounds.for_project(
                getattr(self._project_summary, "project_root", "")
            )
        )
        self._status_label.setText(
            "本轮已生成 {0} 个可用格式；成果（共 {1} 轮）可从顶部「成果」再次查看".format(
                usable, rounds
            )
        )
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
        detail_button = box.addButton("复制阶段诊断", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        clicked = self._exec_message_box(box)
        if clicked is detail_button:
            self._copy_export_stage_diagnostic(report)
            return
        if clicked is open_button:
            usable = report.usable_results()
            if usable:
                self._on_open_result_output(usable[0].path)
        elif clicked is dir_button:
            self._on_open_result_directory(report.destination)
        elif retry_button is not None and clicked is retry_button:
            # 补缺同样走后台 TaskRunner，不再在 UI 线程里同步重跑。
            view = self._record_export_round(report)
            self._on_retry_export_round(view)
        elif clicked is regenerate_button:
            # 明确开新一轮：收集当前缓冲后交给后台（新 captureId，不复用旧轮快照）。
            self._on_regenerate_round(self._record_export_round(report))
        elif clicked is change_button:
            self._on_change_export_destination(self._record_export_round(report))
        else:
            try:
                usable = len(report.usable_results())
            except Exception:  # noqa: BLE001 - 报告形态异常时不给假成功
                usable = 0
            self._status_label.setText(
                "已生成 {0} 个可用结果；可从顶部「成果」逐文件打开或补缺".format(usable)
            )

    def _copy_export_stage_diagnostic(self, report) -> str:
        """把本轮 Word 阶段/清理/环境诊断复制到剪贴板（不含业务正文）。

        事实来自 ``ExportReport.wordRefresh``（由 ``WordOperationReport.to_dict()``
        写入），缺字段显示“未知”，不补造阶段。
        """
        from doc_tool.domain.word_operations import WordOperationReport, environment_facts

        payload = dict(getattr(report, "wordRefresh", None) or {})
        lines = ["{0}：{1}".format(key, value) for key, value in environment_facts().items()]
        lines.append("")
        lines.append("轮次：{0}".format(getattr(report, "roundId", "") or "未知"))
        lines.append("来源：{0}".format(
            "当前编辑内容" if getattr(report, "sourceMode", "") == "current-buffer" else "已保存版本"
        ))
        if payload:
            lines.append("阶段：")
            for item in payload.get("stages") or []:
                if not isinstance(item, dict):
                    continue
                lines.append("  - {0} {1}s（{2}）{3}".format(
                    item.get("label") or item.get("stage") or "未知",
                    item.get("elapsedSeconds"), item.get("outcome") or "未知",
                    ("：" + str(item.get("detail"))) if item.get("detail") else "",
                ))
            ownership = payload.get("ownership") or {}
            lines.append("归属：{0}".format(
                "已证明（{0}）".format(ownership.get("proof")) if ownership.get("provable")
                else "无法证明，未清理任何 Word 进程"
            ))
            lines.append("清理：{0}".format(payload.get("cleanup") or "未执行"))
            if payload.get("residual"):
                lines.append("残留待处理：{0}".format(payload.get("residualDetail") or "未知"))
        else:
            lines.append("阶段：未知（本轮未执行 Word 刷新或缺失记录）")
        stages = [str(item) for item in getattr(report, "wordStages", None) or []]
        if stages:
            lines.append("阶段原文：")
            lines.extend("  - {0}".format(item) for item in stages)
        elif not payload:
            lines.append("阶段原文：未知")
        text = "\n".join(lines)
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
        except Exception:  # noqa: BLE001 - 无剪贴板时仍给出状态说明
            pass
        self._status_label.setText("已复制阶段诊断（不含业务正文）")
        return text

    def _exec_message_box(self, box):
        """显示结果框并返回被点击的按钮（非交互测试可替换此单一入口）。

        保留模块级 ``QMessageBox`` 引用是为了让离屏测试整体替换掉真实弹窗；
        这里再提供一个**动作级**的接缝，使“后台任务完成后弹结果框”的用例不必
        逐个打桩 QMessageBox 也能避免模态等待（V4.0 40-A 1.3）。
        """
        box.exec()
        try:
            return box.clickedButton()
        except RuntimeError:  # noqa: BLE001 - 控件已销毁时视为未选择动作
            return None

    def _on_reimport_source(self) -> None:
        if not self._project_summary or not self._project_summary.is_writable:
            return
        source, _ = QFileDialog.getOpenFileName(self, "选择更新后的源 Word", "", "Word 文档 (*.docx)")
        if not source:
            return
        self._reimport_into_current(Path(source))

    def _reimport_into_current(self, source: Path, *, auto_apply: bool = False) -> None:
        """把外部 Word 修改接回当前项目：先生成隔离差异，再由用户选择接收。

        MAIN2-B：默认走“预览 → 选择 → 应用”的真实入口（复用既有只读差异服务）。
        ``auto_apply=True`` 保留给无界面/兼容调用：直接应用全部合法项。
        """
        if not self._project_summary or not self._project_summary.is_writable:
            QMessageBox.information(
                self, "当前没有可写项目",
                "请先打开需要更新的项目，再接收外部 Word 修改。",
            )
            return
        from doc_tool.application.content.reimport import ReimportService

        source = Path(source)
        service = ReimportService(self._project_summary.manifest, self._project_summary.paths)
        if auto_apply:
            result = service.reimport(source)
            self._after_reimport(result)
            return
        buffers = self._collect_buffer_texts()
        local_contents = dict(buffers)
        try:
            root = self._project_summary.paths.resolve(
                self._project_summary.manifest.relative_content_root()
            )
            local_contents.update({
                rel_path: path.read_text(encoding="utf-8")
                for rel_path, path in (
                    (rel, root / rel) for rel in self._chapter_rel_paths(root)
                )
                if path.is_file() and rel_path not in local_contents
            })
        except Exception:  # noqa: BLE001 - 读不到磁盘正文时只用缓冲做 diff
            local_contents = dict(buffers)
        # 差异计算放后台（可取消）：大文档抽取/对比不应卡住写作区。
        self._status_label.setText("正在后台生成隔离差异（不写正式正文）…")
        from doc_tool.ui.task_bridge import TaskSpec

        self._start_task(TaskSpec(
            name="reimport-preview", target=_run_reimport_preview,
            args=(service, source, sorted(buffers), local_contents),
            timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        ), on_done=self._on_reimport_preview_done)

    def _on_reimport_preview_done(self, result) -> None:
        """后台差异返回：打开选择窗口；失败/取消只提示，不写任何正文。

        结果形态容错（非交互测试/异常返回）：不是 ``(session, error)`` 时一律按
        “未生成差异”处理并给出可读原因，绝不静默挂起或把异常对象当成会话。
        """
        # 自定义 on_done 取代了标准收尾：必须在这里结束任务态，否则计时器不停、
        # _current_task 残留，导入/打开项目/正式合并/重新导入会一直被禁用。
        self._elapsed_timer.stop()
        self._poll_timer.stop()
        self._task_started_at = None
        self._current_task = ""
        self._refresh_interaction_state()
        if isinstance(result, tuple) and len(result) == 2:
            session, error = result
        elif result is None:
            session, error = None, "后台任务未返回结果（可能已取消）"
        else:
            session, error = None, "后台任务返回了非预期结果：{0}".format(type(result).__name__)
        if session is None:
            self._status_label.setText("差异预览未生成：{0}".format(error or "已取消或未知原因"))
            return
        self._reimport_session = session
        self._reimport_source = getattr(session.plan, "source_path", "")
        self._status_label.setText("已生成隔离差异，请在窗口中选择要接收的章节")
        from doc_tool.ui.reimport_preview_window import ReimportPreviewWindow

        existing = getattr(self, "_reimport_window", None)
        if existing is not None:
            try:
                existing.close()
                # 关闭只是隐藏：必须显式销毁，否则每次重开都留下一个隐藏窗口。
                existing.deleteLater()
            except RuntimeError:  # noqa: BLE001 - 控件已销毁
                pass
        window = ReimportPreviewWindow(
            session, host=self, source_path=self._reimport_source, parent=self,
        )
        self._reimport_window = window
        window.show()
        window.raise_()

    def _chapter_rel_paths(self, content_root) -> List[str]:
        """当前项目的章节相对路径（用于 diff 的“当前内容”一侧）。"""
        try:
            from doc_tool.application.effective_snapshot import discover_chapters

            return [rel for rel, _path in discover_chapters(content_root)]
        except Exception:  # noqa: BLE001 - 发现失败时只用缓冲
            return []

    def _apply_reimport_session(self, session, source_path: str) -> bool:
        """应用差异会话：只写“已选且未被阻止”的项，失败按原事务回滚。"""
        from doc_tool.application.content.reimport import ReimportService
        from doc_tool.application.content.reimport_preview import apply_session

        if not self._project_summary or not self._project_summary.is_writable:
            self._show_status_message("当前项目不可写，未写入任何内容")
            return False
        service = ReimportService(self._project_summary.manifest, self._project_summary.paths)
        outcome = apply_session(session, service, source_path)
        applied = list(outcome.get("applied") or [])
        skipped = list(outcome.get("blocked") or []) + list(outcome.get("skipped") or [])
        if outcome.get("rolledBack"):
            self._show_status_message("写入失败，已恢复本次范围；未接收的差异仍保留")
            return False
        if applied:
            message = "已接收 {0} 章".format(len(applied))
            if skipped:
                message += "；保留 {0} 章（冲突/未保存内容）".format(len(skipped))
            self._show_status_message(message)
        else:
            self._show_status_message("没有接收任何章节（未选或冲突项保留本地）")
            return False
        if self._content_workspace is not None:
            try:
                self._content_workspace._rebuild_index()
            except Exception:  # noqa: BLE001 - 索引刷新失败不影响已写入正文
                pass
        return True

    def _save_reimport_incoming_copy(self, source_path: str) -> str:
        """另存传入副本（不写正式正文），返回保存路径（取消返回空串）。"""
        source = Path(str(source_path or ""))
        if not source.is_file():
            self._show_status_message("传入文件已不存在，无法另存副本")
            return ""
        suggested = source.with_name("{0}-传入副本{1}".format(source.stem, source.suffix))
        chosen, _selected = QFileDialog.getSaveFileName(
            self, "另存传入副本", str(suggested), "Word 文档 (*.docx);;所有文件 (*)",
        )
        if not chosen:
            return ""
        try:
            import shutil

            shutil.copy2(str(source), chosen)
        except OSError as exc:
            self._show_status_message("另存副本失败：{0}".format(exc))
            return ""
        self._show_status_message("已另存传入副本：{0}（正式正文未改动）".format(chosen))
        return chosen

    def _save_chapters_then_refresh(self, source_path: str, rel_paths, window=None) -> bool:
        """只保存相关章后重新生成差异（其它章节的脏内容保持不动）。"""
        saved = 0
        for rel_path in rel_paths:
            if self._save_chapter_buffer(str(rel_path)):
                saved += 1
        if not saved:
            self._show_status_message("相关章节没有可保存的未保存内容")
            return False
        self._show_status_message("已保存 {0} 章未保存内容，正在刷新差异…".format(saved))
        self._reimport_into_current(Path(source_path))
        return True

    def _save_chapter_buffer(self, rel_path: str) -> bool:
        """保存单个章节的编辑器缓冲（只影响该章，不触发全量保存）。"""
        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None) if workspace is not None else None
        if tabs is None or not hasattr(tabs, "editor_for"):
            return False
        # 差异会话给的是 contentRoot 相对路径，而标签键带文档类型前缀
        # （general/…）：两种键都要试，否则永远找不到编辑器、按钮变成空操作。
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
        if editor is None:
            return False
        saver = getattr(editor, "save", None)
        if not callable(saver):
            return False
        try:
            return bool(saver())
        except Exception:  # noqa: BLE001 - 单章保存失败不影响其它章节
            return False

    def _after_reimport(self, result) -> None:
        """兼容入口：直接应用后的结果说明（不经过差异窗口）。"""
        if not result.success:
            self._show_error("重新导入失败", result.message, result.error_code)
            return
        if self._content_workspace is not None:
            self._content_workspace._rebuild_index()
        detail = "已合入 {0} 个章节变更。".format(
            sum(item.status != "unchanged" for item in result.changes)
        )
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
        """从最近项目列表中移除条目并刷新界面（不删除工程目录）。"""
        from doc_tool.application.project_service import remove_recent_project

        remove_recent_project(path)
        self._refresh_recent_projects()

    def _on_toggle_recent_pin(self, path: str, pinned: bool) -> None:
        """固定/取消固定最近项目：只改个人记录，不动工程。"""
        from doc_tool.application.project_service import set_recent_pinned

        hit = set_recent_pinned(path, bool(pinned))
        self._refresh_recent_projects()
        self._show_status_message(
            ("已固定：{0}" if pinned else "已取消固定：{0}").format(Path(path).name)
            if hit else "该记录已不在最近列表，未保存固定状态"
        )

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
            # 用户是否动过布局要一并持久化：否则下次打开会把首用默认重新套到
            # 用户已习惯的布局上（复核发现的旧偏好覆盖风险）。
            session.layout_chosen = bool(
                getattr(self, "_writing_layout_chosen", False)
                or (self._pending_session is not None and self._pending_session.layout_chosen)
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
        """恢复主题与 Dock 布局/显隐（会话标签由工作区在索引就绪后恢复）。

        有效旧会话优先：只有缺失/损坏（无任何布局偏好）时才套用首用写作默认，
        避免覆盖用户已经习惯的布局。
        """
        session = self._pending_session
        self._restore_theme(session.theme if session is not None else "light")
        from doc_tool.ui.writing_layout import DOCK_TASK, should_apply_default_layout

        if should_apply_default_layout(session):
            self._apply_default_writing_layout()
        else:
            self._restore_dock_state(session)
            # 有效旧会话：按用户偏好决定空闲时是否展开任务/结果 Dock。
            self._writing_layout_task_dock = bool(
                session.dock_visibility.get(DOCK_TASK, True)
            )

    def _apply_default_writing_layout(self) -> None:
        """套用首用写作布局：正文优先，工具/空闲任务 Dock 收起，章节树收窄。"""
        from doc_tool.ui.writing_layout import default_writing_layout

        self._apply_dock_layout(default_writing_layout())
        self._writing_layout_default_applied = True
        self._writing_layout_chosen = False
        # 默认收起任务/结果 Dock；用户手动展开或恢复旧会话后置 True。
        self._writing_layout_task_dock = False

    def _apply_dock_layout(self, layout) -> None:
        """按布局定义设置 Dock 显隐与宽度（只动布局，不动文档/会话内容）。"""
        for name, dock in self._dock_widgets():
            if dock is None:
                continue
            target = layout.docks.get(name)
            if target is None:
                continue
            if target.minimum_width is not None:
                dock.setMinimumWidth(target.minimum_width)
            if target.maximum_width is not None:
                dock.setMaximumWidth(target.maximum_width)
            if target.visible:
                dock.show()
            else:
                dock.hide()

    def _mark_layout_chosen(self) -> None:
        """记录用户已经显式选择过布局（下次打开不再套用首用默认）。"""
        session = self._pending_session
        if session is None:
            session = SessionState()
            self._pending_session = session
        session.layout_chosen = True
        session.dock_visibility = self._dock_visibility()

    def _on_restore_writing_layout(self) -> None:
        """「恢复写作布局」：只重设 Dock 显隐/尺寸，保留正文、草稿、主题与滚动。"""
        from doc_tool.ui.writing_layout import default_writing_layout

        layout = default_writing_layout()
        self._apply_dock_layout(layout)
        self._writing_layout_chosen = True
        self._writing_layout_task_dock = False
        self._mark_layout_chosen()
        self._rebuild_view_menu()
        self._status_label.setText(layout.describe_restored())

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

    # ------------------------------------------------------------------
    # RD 研发工作区（RD-A 1.4 / RD-B～RD-E）
    # ------------------------------------------------------------------

    def _on_standard_pack_entry(self) -> None:
        self._on_standard_pack()

    def _on_table_grid(self) -> None:
        """菜单入口 → 当前编辑器表格网格（没有打开章节或不是普通表格时给出原因）。"""
        editor = self._active_editor()
        if editor is None:
            self._show_status_message("请先打开要编辑表格的章节")
            return
        editor.open_table_grid()

    def _on_paste_as_table(self) -> None:
        editor = self._active_editor()
        if editor is None:
            self._show_status_message("请先打开要插入表格的章节")
            return
        editor.paste_as_table()

    def _on_rd_workspace(self) -> None:
        """打开研发工作区：成员/概览/设置、条目/关系、矩阵/影响、集合/成果。"""
        dialog = self.rd_workspace_dialog()
        dialog.exec()

    def rd_workspace_dialog(self):
        """构建研发工作区对话框（同一实例可被测试直接驱动）。"""
        from doc_tool.ui.rd_workspace import RdWorkspaceDialog

        dialog = RdWorkspaceDialog(self, root=self._rd_workspace_root(), parent=self)
        self._rd_dialog = dialog
        return dialog

    def _rd_workspace_root(self) -> str:
        """工作区根目录：已选记录 → 当前项目或其上级的 workspace.yml → 当前项目。"""
        remembered = str(getattr(self, "_rd_workspace_path", "") or "")
        if remembered and (Path(remembered) / "workspace.yml").is_file():
            return remembered
        summary = getattr(self, "_project_summary", None)
        root = ""
        try:
            root = str(getattr(summary, "project_root", "") or "")
        except Exception:  # noqa: BLE001 - 未打开项目时按空处理
            root = ""
        if not root:
            return remembered
        candidate = Path(root)
        for base in (candidate, candidate.parent, candidate.parent.parent, candidate.parent.parent.parent):
            try:
                if (base / "workspace.yml").is_file():
                    return str(base)
            except OSError:
                continue
        return root

    # --- 宿主接口：供 RdWorkspaceDialog 复用现有入口 ---

    def rd_project_root(self) -> str:
        try:
            return str(self._project_summary.project_root)
        except Exception:  # noqa: BLE001 - 未打开项目
            return ""

    def rd_project_id(self) -> str:
        try:
            return str(self._project_summary.manifest.projectId or "")
        except Exception:  # noqa: BLE001 - 未打开项目
            return ""

    def rd_collect_buffers(self) -> dict:
        return dict(self._collect_buffer_texts())

    def rd_current_chapter(self) -> str:
        workspace = getattr(self, "_content_workspace", None)
        current = ""
        getter = getattr(workspace, "current_file", None)
        if callable(getter):
            try:
                current = str(getter() or "")
            except Exception:  # noqa: BLE001 - 无当前章节
                current = ""
        return self._normalize_buffer_rel_path(current)

    def rd_cursor_line(self) -> int:
        editor = self._active_editor()
        target = getattr(editor, "_editor", None) or editor
        getter = getattr(target, "textCursor", None)
        if not callable(getter):
            return 0
        try:
            return int(getter().blockNumber()) + 1
        except Exception:  # noqa: BLE001 - 光标不可用时按第 1 行
            return 1

    def rd_open_source(self, rel_path: str, line_no=None, source: str = "") -> bool:
        """按真实来源定位：relPath + 行号，来源进入位置历史说明。"""
        return self._open_chapter_in_workspace(
            rel_path, int(line_no) if line_no else None,
            source=source or "研发工作区",
        )

    def _rd_tab_key(self, rel_path: str) -> str:
        """编辑器标签使用的键（带文档类型前缀），找不到返回空串。"""
        value = str(rel_path or "").replace("\\", "/")
        if not value:
            return ""
        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None)
        if tabs is None:
            return ""
        candidates = [value]
        document_type = ""
        try:
            document_type = str(self._project_summary.manifest.documentType or "")
        except Exception:  # noqa: BLE001
            document_type = ""
        if document_type and not value.startswith(document_type + "/"):
            candidates.insert(0, "{0}/{1}".format(document_type, value))
        for candidate in candidates:
            try:
                if tabs.editor_for(candidate) is not None:
                    return candidate
            except Exception:  # noqa: BLE001 - 接口差异时继续尝试
                continue
        return ""

    def rd_apply_item_edit(self, rel_path: str, text: str, message: str = ""):
        """把条目动作结果一次写入编辑缓冲（整段替换，一次撤销可还原）。"""
        from PySide6.QtGui import QTextCursor

        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None)
        if tabs is None:
            return None
        key = self._rd_tab_key(rel_path)
        if not key:
            opened = self._open_chapter_in_workspace(rel_path, None, source="研发工作区")
            if not opened:
                return None
            key = self._rd_tab_key(rel_path)
        editor = tabs.editor_for(key) if key else None
        target = getattr(editor, "_editor", None)
        if target is None:
            return None
        cursor = target.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        target.setTextCursor(cursor)
        cursor.insertText(str(text))
        target.setTextCursor(cursor)
        target.setFocus()
        if message:
            self._show_status_message(message)
        return True

    def rd_save_chapters(self, rel_paths) -> bool:
        """只保存指定章节（不隐式保存整个工作区）。"""
        workspace = getattr(self, "_content_workspace", None)
        tabs = getattr(workspace, "tabs_host", None)
        if tabs is None:
            return False
        wanted = [str(item) for item in (rel_paths or [])]
        if not wanted:
            return False
        saved: list = []
        for rel_path in wanted:
            key = self._rd_tab_key(rel_path)
            if not key:
                continue
            try:
                if hasattr(tabs, "activate"):
                    tabs.activate(key)
                if tabs.save_current():
                    saved.append(key)
            except Exception:  # noqa: BLE001 - 单个章节保存失败不影响其他章节
                continue
        return len(saved) == len(wanted)

    def rd_open_project(self, path: str):
        """打开/激活成员项目窗口（保留其他窗口的未保存缓冲）。"""
        try:
            existing = self._find_window_for_project(str(path))
        except Exception:  # noqa: BLE001 - 查找失败时按新窗口打开
            existing = None
        if existing is not None:
            self._activate_window(existing)
            return True
        try:
            self._open_project_in_new_window(str(path))
            return True
        except Exception:  # noqa: BLE001 - 打开失败返回 None，由界面给出可执行兜底
            return None

    def _find_window_for_project(self, path: str):
        try:
            from PySide6.QtWidgets import QApplication
        except Exception:  # noqa: BLE001
            return None
        target = ""
        try:
            target = str(Path(path).resolve())
        except OSError:
            target = str(path)
        for widget in QApplication.topLevelWidgets():
            if widget is self or not isinstance(widget, MainWindow):
                continue
            try:
                root = str(Path(widget.rd_project_root()).resolve())
            except Exception:  # noqa: BLE001 - 无项目的窗口跳过
                continue
            if root and root == target:
                return widget
        return None

    def rd_open_path(self, path: str):
        return self._open_path(Path(path))

    def rd_member_delivery(self, root: str) -> str:
        """成员交付：直接复用既有批量交付入口（V3.2 持久队列，不另建协调器）。"""
        try:
            self._on_delivery_batch()
        except Exception as exc:  # noqa: BLE001 - 交付入口不可用时给出可执行兜底
            return "批量交付入口不可用：{0}；可在菜单「操作 → 批量交付」重试。".format(exc)
        return "已打开既有批量交付入口：串行 Word、逐成员状态与未完成重试沿用持久队列。"

    def rd_status(self, message: str) -> None:
        if message:
            self._show_status_message(message)

    def rd_workspace_root_changed(self, root: str) -> None:
        self._rd_workspace_path = str(root or "")

    # ------------------------------------------------------------------
    # V3.5 规范包制作（35-B～35-D）
    # ------------------------------------------------------------------

    def _on_standard_pack(self) -> None:
        dialog = self.standard_pack_dialog()
        dialog.exec()

    def standard_pack_dialog(self):
        from doc_tool.ui.standard_pack_dialog import StandardPackDialog

        dialog = StandardPackDialog(
            self, draft_dir=str(getattr(self, "_standard_pack_dir", "") or ""),
            project_root=self.rd_project_root(), parent=self,
        )
        self._standard_pack_dialog = dialog
        return dialog

    def sp_project_root(self) -> str:
        return self.rd_project_root()

    def sp_default_draft_dir(self) -> str:
        remembered = str(getattr(self, "_standard_pack_dir", "") or "")
        if remembered:
            return remembered
        root = self.rd_project_root()
        return str(Path(root) / "pack-draft") if root else str(Path.cwd() / "pack-draft")

    def sp_open_path(self, path: str):
        target = Path(path)
        if target.is_dir():
            return self._open_directory(target, create=False)
        return self._open_path(target)

    def sp_status(self, message: str) -> None:
        if message:
            self._show_status_message(message)

    # ------------------------------------------------------------------
    # V4.1 41-A 1.4 本地企业模板目录（列表/详情 + 既有动作）
    # ------------------------------------------------------------------

    def _on_template_library(self) -> None:
        dialog = self.template_library_dialog()
        dialog.exec()

    def template_library_dialog(self):
        from doc_tool.ui.template_library_dialog import TemplateLibraryDialog

        summary = self._project_summary
        writable = bool(getattr(summary, "is_writable", False)) if summary is not None else None
        dialog = TemplateLibraryDialog(
            self, project_root=self.rd_project_root(), state_dir=self.tl_state_dir(),
            project_writable=writable, parent=self,
        )
        self._template_library_dialog = dialog
        return dialog

    def tl_state_dir(self) -> str:
        from doc_tool.ui.template_library_dialog import default_state_dir

        return str(default_state_dir())

    def tl_project_root(self) -> str:
        return self.rd_project_root()

    def tl_project_writable(self) -> bool:
        summary = self._project_summary
        return bool(summary is not None and getattr(summary, "is_writable", False))

    def tl_project_chapters(self) -> list:
        """当前项目的章节 Markdown 绝对路径（只读，不写盘；未打开项目返回空）。"""
        summary = self._project_summary
        if summary is None:
            return []
        try:
            paths = getattr(summary, "paths", None)
            manifest = getattr(summary, "manifest", None)
            if paths is not None and manifest is not None:
                content_root = Path(paths.resolve(manifest.relative_content_root()))
            else:
                content_root = Path(str(summary.project_root)) / "content"
        except Exception:  # noqa: BLE001 - 读不出章节只返回空清单，不阻断目录界面
            return []
        try:
            return [str(item) for item in sorted(content_root.rglob("*.md")) if item.is_file()]
        except OSError:
            return []

    def tl_busy_check(self) -> bool:
        return bool(self.runner.is_running)

    def tl_open_path(self, path: str):
        return self.sp_open_path(path)

    def tl_status(self, message: str) -> None:
        if message:
            self._show_status_message(message)

    def tl_project_created(self, project_root: str) -> None:
        """模板目录建项：新项目在新窗口打开，当前项目与打开中的章节保持原样。"""
        self._open_import_result(str(project_root))

    def tl_open_pack_draft(self, draft_dir: str) -> None:
        """模板目录的副本用既有「规范包制作」打开（原固定包不原地修改）。"""
        from doc_tool.ui.standard_pack_dialog import StandardPackDialog

        dialog = StandardPackDialog(
            self, draft_dir=str(draft_dir), project_root=self.rd_project_root(), parent=self,
        )
        self._standard_pack_dialog = dialog
        dialog.exec()
