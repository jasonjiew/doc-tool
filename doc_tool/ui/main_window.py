# -*- coding: utf-8 -*-
"""主窗口：项目摘要、菜单、状态栏与操作入口。

任务 6.1：主窗口、项目摘要、状态栏、高 DPI 适配。
任务 6.4：打开已有项目、最近项目列表、不兼容只读状态。
任务 6.5：打开 Markdown/输出/日志目录。
任务 6.6：独立项目校验。
任务 6.7：正式合并与诊断构建入口。
任务 6.9：关于/环境诊断。

主窗口不直接执行长操作——所有构建/校验/合并通过 ``TaskRunner`` 在后台执行，
界面保持响应。用户可安全取消正在运行的任务。
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from doc_tool.domain.version import APP_VERSION, get_build_info
from doc_tool.ui.task_bridge import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    POLL_INTERVAL_MS,
    TaskEvent,
    TaskRunner,
    TaskSpec,
)
from doc_tool.ui.workbench_state import (
    ResultState,
    derive_workbench_state,
    error_presentation,
)


# 文档类型中文映射
DOC_TYPE_LABELS = {
    "general": "通用大文档",
    "requirement": "需求文档",
    "design": "详细设计文档",
}

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
# 与 pipeline 阶段顺序双写漂移。延迟到首次使用时导入，便于在无 GUI
# 的纯服务测试中不被强制依赖。
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


class MainWindow:
    """主窗口控制器。

    不直接继承 ``tk.Tk``——由 ``app.py`` 创建 root 并传入，
    便于测试时注入 mock root。
    """

    def __init__(self, root) -> None:
        self.root = root
        self.runner = TaskRunner()
        self._project_summary = None  # ProjectSummary
        self._poll_scheduled = False
        # 进度通道：后台线程把 (stage, status, detail) 入队，UI 线程 poll 时消费。
        import queue as _queue

        self._progress_queue: "_queue.Queue" = _queue.Queue()
        # 当前任务是否支持阶段进度（True 才用确定性进度条，否则回退心跳）。
        self._stage_progress_enabled = False
        # 当前运行中的任务名（用于阶段文本展示）。
        self._current_task = ""
        # 最近进入 started 的阶段名（用于取消反馈展示当前阶段）。
        self._progress_recent_stage = ""
        # 最近一次任务错误码（看门狗/校验失败等），完成后清理。
        self._last_error_code: Optional[str] = None
        self._last_error_stage = ""
        self._last_error_detail = ""
        self._task_terminal_kind = ""
        # 用户在任务运行中确认退出后，等待任务安全结束再销毁窗口。
        self._close_after_task = False
        # Word availability is intentionally unknown until an explicit merge
        # attempt performs the existing non-blocking preflight check.
        self._word_available: Optional[bool] = None
        self._workbench_state = derive_workbench_state(None, running=False)
        self._result_state = ResultState()
        self._log_expanded = False
        self._task_started_at = None
        self._elapsed_timer = None

        self._build_ui()
        self._build_menu()
        self._update_no_project_state()

    # --- UI 构建 ---

    def _build_ui(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root.title("康尚文档工具 v{0}".format(APP_VERSION))
        self.root.minsize(640, 480)
        # 还原上次窗口几何/状态；缺失或异常则回退默认。
        from doc_tool.application.project_service import load_window_geometry

        geom = load_window_geometry() or {}
        saved_geo = (geom.get("geometry") or "").strip()
        self._maximized_at_start = bool(geom.get("maximized", False))
        try:
            self.root.geometry(saved_geo if saved_geo else "860x600")
        except Exception:
            self.root.geometry("860x600")
        # 几何写回：窗口关闭与尺寸稳定后保存，避免拖动过程频繁落盘。
        self._geom_save_timer = None
        self.root.bind("<Configure>", self._on_root_configure)
        try:
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            pass
        if self._maximized_at_start:
            try:
                self.root.wm_state("zoomed")
            except Exception:
                pass

        # --- Stable status bar; only the content container switches views. ---
        status_bar = ttk.Frame(self.root, relief="sunken", padding=(8, 2))
        status_bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self._status_var, style="Status.TLabel").pack(
            side="left"
        )
        self._lock_status_var = tk.StringVar(value="")
        ttk.Label(
            status_bar, textvariable=self._lock_status_var, style="Status.TLabel"
        ).pack(side="right")

        self._content_host = ttk.Frame(self.root, padding=8)
        self._content_host.pack(fill="both", expand=True)

        # --- No-project empty state ---
        self._empty_frame = ttk.Frame(self._content_host, padding=(32, 36))
        ttk.Label(
            self._empty_frame, text="康尚文档工作台", style="Title.TLabel"
        ).pack(anchor="center")
        ttk.Label(
            self._empty_frame,
            text="新建或打开项目后，可在首屏完成校验、构建、合并和产物查看。",
            wraplength=620,
        ).pack(anchor="center", pady=(8, 20))
        empty_actions = ttk.Frame(self._empty_frame)
        empty_actions.pack(anchor="center")
        ttk.Button(
            empty_actions,
            text="新建项目…",
            command=self._on_new_project,
            style="Primary.TButton",
        ).pack(side="left", padx=6)
        ttk.Button(
            empty_actions,
            text="打开项目…",
            command=self._on_open_project,
            style="Secondary.TButton",
        ).pack(side="left", padx=6)
        ttk.Label(
            self._empty_frame, text="最近项目", style="Heading.TLabel"
        ).pack(anchor="w", pady=(28, 8))
        self._empty_recent_frame = ttk.Frame(self._empty_frame)
        self._empty_recent_frame.pack(fill="x")

        # --- Open-project workbench (scrollable: 窗口过小时可滚动触达全部功能) ---
        from doc_tool.ui.scrollable import ScrollableFrame

        self._workbench_scroll = ScrollableFrame(self._content_host)
        self._workbench_frame = self._workbench_scroll.inner

        # 摘要区可折叠：默认展开，窗口偏矮时可收起以腾出内容工作区空间。
        self._summary_collapsed = False
        summary_frame = ttk.LabelFrame(
            self._workbench_frame, text="项目与就绪状态", padding=8
        )
        summary_frame.pack(fill="x", pady=(0, 6))
        summary_header = ttk.Frame(summary_frame)
        summary_header.pack(fill="x")
        self._summary_toggle_btn = ttk.Button(
            summary_header,
            text="收起",
            command=self._toggle_summary,
            style="Compact.TButton",
        )
        self._summary_toggle_btn.pack(side="right")
        self._summary_body = ttk.Frame(summary_frame)
        self._summary_body.pack(fill="x", pady=(4, 0))

        self._summary_vars = {}
        wrap_keys = {"project_path", "document_name"}
        for i, key in enumerate(
            ("document_name", "document_no", "document_type",
             "document_version", "source_hash", "last_build", "project_path")
        ):
            ttk.Label(self._summary_body, text=self._summary_label(key) + "：").grid(
                row=i, column=0, sticky="w", pady=2
            )
            var = tk.StringVar(value="—")
            self._summary_vars[key] = var
            ttk.Label(
                self._summary_body,
                textvariable=var,
                wraplength=620 if key in wrap_keys else 0,
            ).grid(row=i, column=1, sticky="we", padx=(8, 0), pady=2)
        self._summary_body.columnconfigure(1, weight=1)
        self._readiness_var = tk.StringVar(value="请选择或新建项目")
        self._readiness_label = ttk.Label(
            self._summary_body,
            textvariable=self._readiness_var,
            style="Neutral.TLabel",
            wraplength=700,
        )
        self._readiness_label.grid(
            row=0, column=2, rowspan=3, sticky="nw", padx=(20, 0)
        )
        self._disabled_reasons_var = tk.StringVar(value="")
        ttk.Label(
            self._summary_body,
            textvariable=self._disabled_reasons_var,
            style="Status.TLabel",
            wraplength=300,
            justify="left",
        ).grid(row=3, column=2, rowspan=4, sticky="nw", padx=(20, 0))

        action_frame = ttk.LabelFrame(
            self._workbench_frame, text="常用操作", padding=12
        )
        action_frame.pack(fill="x", pady=6)
        self._action_buttons = {}
        action_specs = (
            ("merge", "正式合并", self._on_merge, "Primary.TButton"),
            ("diag_build", "诊断构建", self._on_diag_build, "Secondary.TButton"),
            ("validate", "项目校验", self._on_validate, "Secondary.TButton"),
            ("content", "打开内容目录", self._on_open_content, "Secondary.TButton"),
            ("output", "打开输出位置", self._on_open_output, "Secondary.TButton"),
            ("report", "打开校验报告", self._on_open_validation_report, "Secondary.TButton"),
        )
        for column, (key, label, command, style_name) in enumerate(action_specs):
            button = ttk.Button(
                action_frame, text=label, command=command, style=style_name
            )
            button.grid(row=0, column=column, padx=4, pady=2, sticky="ew")
            action_frame.columnconfigure(column, weight=1)
            self._action_buttons[key] = button

        progress_frame = ttk.LabelFrame(
            self._workbench_frame, text="任务进度", padding=8
        )
        progress_frame.pack(fill="x", pady=6)
        self._task_name_var = tk.StringVar(value="无任务运行")
        ttk.Label(progress_frame, textvariable=self._task_name_var).pack(anchor="w")
        self._elapsed_var = tk.StringVar(value="")
        ttk.Label(
            progress_frame, textvariable=self._elapsed_var, style="Status.TLabel"
        ).pack(anchor="w")
        self._progress = ttk.Progressbar(
            progress_frame, mode="determinate", length=400, maximum=100
        )
        self._progress.pack(fill="x", pady=(4, 2))
        self._cancel_btn = ttk.Button(
            progress_frame, text="取消", command=self._on_cancel, state="disabled"
        )
        self._cancel_btn.pack(side="right", pady=(4, 0))

        self._result_frame = ttk.LabelFrame(
            self._workbench_frame,
            text="最近任务结果",
            padding=10,
            style="Result.TLabelframe",
        )
        self._result_frame.pack(fill="x", pady=6)
        self._result_title_var = tk.StringVar(value=self._result_state.title)
        self._result_summary_var = tk.StringVar(value=self._result_state.summary)
        self._result_advice_var = tk.StringVar(value="")
        ttk.Label(
            self._result_frame,
            textvariable=self._result_title_var,
            style="Neutral.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            self._result_frame,
            textvariable=self._result_summary_var,
            wraplength=760,
        ).pack(anchor="w", pady=(3, 0))
        ttk.Label(
            self._result_frame,
            textvariable=self._result_advice_var,
            style="Status.TLabel",
            wraplength=760,
        ).pack(anchor="w")
        self._result_actions = ttk.Frame(self._result_frame)
        self._result_actions.pack(fill="x", pady=(6, 0))

        # --- Compact event log; the text keeps receiving events while hidden. ---
        self._log_frame = ttk.LabelFrame(
            self._workbench_frame, text="事件日志", padding=4
        )
        self._log_frame.pack(fill="x", pady=(6, 0))
        log_header = ttk.Frame(self._log_frame)
        log_header.pack(fill="x")
        self._log_summary_var = tk.StringVar(value="日志已折叠")
        ttk.Label(
            log_header, textvariable=self._log_summary_var, style="Status.TLabel"
        ).pack(side="left")
        self._log_pending_var = tk.StringVar(value="")
        self._log_pending_label = ttk.Label(
            log_header,
            textvariable=self._log_pending_var,
            style="Warning.TLabel",
            cursor="hand2",
        )
        self._log_pending_label.pack(side="left", padx=(8, 0))
        self._log_pending_label.bind("<Button-1>", self._expand_log_and_scroll)
        self._log_toggle_btn = ttk.Button(
            log_header,
            text="展开",
            command=self._toggle_log,
            style="Compact.TButton",
        )
        self._log_toggle_btn.pack(side="right")
        self._log_body = ttk.Frame(self._log_frame)
        self._log_text = tk.Text(
            self._log_body,
            height=8,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
        )
        log_scroll = ttk.Scrollbar(self._log_body, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        log_controls = ttk.Frame(self._log_body)
        log_controls.pack(fill="x", side="bottom", pady=(4, 0))
        ttk.Button(
            log_controls,
            text="复制日志",
            command=self._copy_log,
            style="Compact.TButton",
        ).pack(side="left")
        ttk.Button(
            log_controls,
            text="打开日志目录",
            command=self._on_open_logs,
            style="Compact.TButton",
        ).pack(side="left", padx=(6, 0))
        self._log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        self._log_at_bottom = True
        self._log_pending = 0
        self._log_text.bind("<ButtonRelease-1>", self._on_log_scroll_check)
        self._log_text.bind("<KeyRelease>", self._on_log_scroll_check)
        log_scroll.bind("<B1-Motion>", lambda _e: self._on_log_scroll_check())

        # --- 内容操作工作区（打开项目后填充） ---
        self._content_host_frame = ttk.LabelFrame(
            self._workbench_frame, text="内容操作", padding=6
        )
        # 固定最小高度：外层可滚动时内容工作区也不会被压缩到不可用。
        self._content_host_frame.pack_propagate(False)
        self._content_host_frame.configure(height=420)
        self._content_host_frame.pack(fill="both", expand=True, pady=(6, 0))
        self._content_workspace = None
        self._content_placeholder = ttk.Label(
            self._content_host_frame,
            text="打开项目后，可在左侧章节树浏览，并支持全文搜索、编辑预览、"
            "全局替换、章节重命名/重编号联动与术语检查。",
            padding=24,
            wraplength=760,
            justify="left",
        )
        self._content_placeholder.pack(fill="both", expand=True)

    def _build_menu(self) -> None:
        import tkinter as tk

        menubar = tk.Menu(self.root)

        # 文件菜单
        self._file_menu = tk.Menu(menubar, tearoff=False)
        self._file_entry_indexes = {}
        self._file_menu.add_command(
            label="新建项目…",
            accelerator="Ctrl+N",
            command=self._on_new_project,
        )
        self._file_entry_indexes["new"] = int(self._file_menu.index("end"))
        self._file_menu.add_command(
            label="打开项目…",
            accelerator="Ctrl+O",
            command=self._on_open_project,
        )
        self._file_entry_indexes["open"] = int(self._file_menu.index("end"))
        self._recent_menu = tk.Menu(self._file_menu, tearoff=False)
        self._file_menu.add_cascade(label="最近打开", menu=self._recent_menu)
        self._file_entry_indexes["recent"] = int(self._file_menu.index("end"))
        self._file_menu.add_separator()
        self._file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=self._file_menu)

        # 操作菜单
        self._ops_menu = tk.Menu(menubar, tearoff=False)
        self._ops_menu.add_command(
            label="校验项目", accelerator="F5", command=self._on_validate
        )
        self._ops_entry_indexes = {"validate": int(self._ops_menu.index("end"))}
        self._ops_menu.add_separator()
        self._ops_menu.add_command(label="正式合并", command=self._on_merge)
        self._ops_entry_indexes["merge"] = int(self._ops_menu.index("end"))
        self._ops_menu.add_command(
            label="诊断构建（无 Word）",
            accelerator="Ctrl+Shift+B",
            command=self._on_diag_build,
        )
        self._ops_entry_indexes["diag_build"] = int(self._ops_menu.index("end"))
        self._ops_menu.add_separator()
        self._ops_menu.add_command(
            label="打开校验报告", command=self._on_open_validation_report,
            state="disabled",
        )
        self._ops_entry_indexes["validation_report"] = int(
            self._ops_menu.index("end")
        )
        menubar.add_cascade(label="操作", menu=self._ops_menu)

        # 内容菜单
        self._content_menu = tk.Menu(menubar, tearoff=False)
        self._content_entry_indexes = {}
        self._content_menu.add_command(
            label="全文搜索",
            accelerator="Ctrl+F",
            command=self._on_content_search,
        )
        self._content_entry_indexes["search"] = int(self._content_menu.index("end"))
        self._content_menu.add_command(
            label="引用分析…",
            command=self._on_content_references,
        )
        self._content_entry_indexes["references"] = int(
            self._content_menu.index("end")
        )
        self._content_menu.add_command(
            label="全局替换…",
            command=self._on_content_replace,
        )
        self._content_entry_indexes["replace"] = int(
            self._content_menu.index("end")
        )
        self._content_menu.add_command(
            label="章节重命名/重编号…",
            command=self._on_content_refactor,
        )
        self._content_entry_indexes["refactor"] = int(
            self._content_menu.index("end")
        )
        self._content_menu.add_command(
            label="术语/一致性检查",
            command=self._on_content_lint,
        )
        self._content_entry_indexes["lint"] = int(self._content_menu.index("end"))
        self._content_menu.add_separator()
        self._content_menu.add_command(
            label="在外部编辑器打开当前文件",
            command=self._on_content_open_external,
        )
        self._content_entry_indexes["open_external"] = int(
            self._content_menu.index("end")
        )
        menubar.add_cascade(label="内容", menu=self._content_menu)

        # 工具菜单
        self._tools_menu = tk.Menu(menubar, tearoff=False)
        self._tools_entry_indexes = {}
        self._tools_menu.add_command(
            label="打开 Markdown 目录", command=self._on_open_content
        )
        self._tools_entry_indexes["content"] = int(self._tools_menu.index("end"))
        self._tools_menu.add_command(label="打开输出目录", command=self._on_open_output)
        self._tools_entry_indexes["output"] = int(self._tools_menu.index("end"))
        self._tools_menu.add_command(label="打开日志目录", command=self._on_open_logs)
        self._tools_entry_indexes["logs"] = int(self._tools_menu.index("end"))
        menubar.add_cascade(label="工具", menu=self._tools_menu)

        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(
            label="关于 / 环境诊断", accelerator="F1", command=self._on_about
        )
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.configure(menu=menubar)
        self.root.bind("<Control-n>", lambda _e: self._on_new_project())
        self.root.bind("<Control-o>", lambda _e: self._on_open_project())
        self.root.bind("<F5>", lambda _e: self._on_validate())
        self.root.bind("<Control-Shift-B>", lambda _e: self._on_diag_build())
        self.root.bind("<Control-l>", self._scroll_log_to_bottom)
        self.root.bind("<Control-f>", lambda _e: self._on_content_search())
        # 内容工作区标签页快捷键 Ctrl+1..5
        content_tabs = (
            "章节树 / 编辑器",
            "搜索",
            "替换",
            "重命名/重编号",
            "检查",
        )
        for index, tab_text in enumerate(content_tabs, start=1):
            self.root.bind(
                "<Control-{0}>".format(index),
                lambda _e, t=tab_text: self._select_content_tab(t),
            )
        self.root.bind("<F1>", lambda _e: self._on_about())

    # --- 状态管理 ---

    def _update_no_project_state(self) -> None:
        """无项目时的初始状态。"""
        for key in self._summary_vars:
            self._summary_vars[key].set("—")
        self._refresh_recent_menu()
        self._refresh_interaction_state()

    @staticmethod
    def _set_widget_enabled(widget, enabled: bool) -> None:
        try:
            widget.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _switch_content_view(self, view: str) -> None:
        """Switch the single content host without changing window lifecycle."""
        empty = getattr(self, "_empty_frame", None)
        workbench = getattr(self, "_workbench_scroll", None)
        if empty is None or workbench is None:
            return
        try:
            empty.pack_forget()
            workbench.pack_forget()
            target = empty if view == "empty" else workbench
            target.pack(fill="both", expand=True)
        except Exception:
            pass

    def _render_empty_recent_projects(self, entries) -> None:
        frame = getattr(self, "_empty_recent_frame", None)
        if frame is None:
            return
        try:
            for child in frame.winfo_children():
                child.destroy()
        except Exception:
            return
        from tkinter import ttk

        if not entries:
            ttk.Label(
                frame,
                text="暂无有效最近项目，可从上方新建或打开。",
                style="Status.TLabel",
            ).pack(anchor="w")
            return
        for entry in entries[:5]:
            label = entry.document_name or entry.name
            button = ttk.Button(
                frame,
                text="{0}\n{1}".format(label, entry.path),
                command=lambda p=entry.path: self._open_project_path(p),
                style="Secondary.TButton",
            )
            button.pack(fill="x", pady=2)
            self._set_widget_enabled(button, not bool(self.runner.is_running))

    def _apply_workbench_state(self, state) -> None:
        """Render a pure state snapshot into both menu and workbench controls."""
        self._switch_content_view(state.view)
        if hasattr(self, "_readiness_var"):
            self._readiness_var.set(state.readiness_text)
        if hasattr(self, "_readiness_label"):
            try:
                self._readiness_label.configure(
                    style="{0}.TLabel".format(state.status_tone.capitalize())
                )
            except Exception:
                pass
        if hasattr(self, "_disabled_reasons_var"):
            self._disabled_reasons_var.set(
                "\n".join("• {0}".format(reason) for reason in state.reasons)
            )
        buttons = getattr(self, "_action_buttons", {})
        for key, action in state.actions.items():
            if key in buttons:
                self._set_widget_enabled(buttons[key], action.enabled)

    @staticmethod
    def _set_menu_entries(menu, indexes, keys, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for key in keys:
            idx = indexes.get(key)
            if idx is not None:
                try:
                    menu.entryconfig(idx, state=state)
                except Exception:
                    pass

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
        )
        self._workbench_state = state

        self._set_menu_entries(
            self._file_menu,
            self._file_entry_indexes,
            ("new", "open", "recent"),
            not running,
        )
        for key in ("validate", "merge", "diag_build"):
            action = state.actions[key]
            self._set_menu_entries(
                self._ops_menu, self._ops_entry_indexes, (key,), action.enabled
            )
        for key in ("content", "output", "logs"):
            action = state.actions[key]
            self._set_menu_entries(
                self._tools_menu, self._tools_entry_indexes, (key,), action.enabled
            )
        self._set_menu_entries(
            self._ops_menu,
            self._ops_entry_indexes,
            ("validation_report",),
            state.actions["report"].enabled,
        )
        self._refresh_content_menu_state(running)
        self._apply_workbench_state(state)

    def _refresh_content_menu_state(self, running: bool) -> None:
        """内容菜单可用性：读操作需项目打开且索引就绪；写操作额外需可写。"""
        if not hasattr(self, "_content_menu"):
            return
        workspace_ready = self._content_workspace_available() and not running
        summary = self._project_summary
        writable = bool(summary and summary.is_writable)
        self._set_menu_entries(
            self._content_menu,
            self._content_entry_indexes,
            ("search", "references", "lint"),
            workspace_ready,
        )
        self._set_menu_entries(
            self._content_menu,
            self._content_entry_indexes,
            ("replace", "refactor"),
            workspace_ready and writable,
        )
        self._set_menu_entries(
            self._content_menu,
            self._content_entry_indexes,
            ("open_external",),
            bool(getattr(self, "_content_workspace", None)),
        )

    def _set_ops_enabled(self, enabled: bool) -> None:
        """兼容旧调用；关键状态统一由 ``_refresh_interaction_state`` 驱动。"""
        self._set_menu_entries(
            self._ops_menu,
            self._ops_entry_indexes,
            ("validate", "merge", "diag_build"),
            enabled,
        )

    def _refresh_recent_menu(self) -> None:
        from doc_tool.application.project_service import load_recent_projects

        self._recent_menu.delete(0, "end")
        entries = load_recent_projects()
        self._render_empty_recent_projects(entries)
        running = bool(self.runner.is_running)
        if not entries:
            self._recent_menu.add_command(label="（无）", state="disabled")
            return
        for entry in entries[:10]:
            label = entry.name
            if entry.document_name:
                label = "{0}（{1}）".format(entry.name, entry.document_name)
            self._recent_menu.add_command(
                label=label,
                command=lambda p=entry.path: self._open_project_path(p),
                state="disabled" if running else "normal",
            )

    def show_project(self, summary) -> None:
        """显示已打开的项目摘要。"""
        from doc_tool.application.project_service import add_recent_project

        self._project_summary = summary
        self._word_available = None
        self._result_state = ResultState(project_root=summary.project_root)
        self._render_result_state()
        m = summary.manifest
        self._summary_vars["document_name"].set(m.documentName)
        self._summary_vars["document_no"].set(m.documentNo or "—")
        self._summary_vars["document_type"].set(
            DOC_TYPE_LABELS.get(m.documentType, m.documentType)
        )
        self._summary_vars["document_version"].set(m.documentVersion)
        self._summary_vars["source_hash"].set(
            m.sourceSha256[:12] + "…" if m.sourceSha256 else "—"
        )
        self._summary_vars["last_build"].set(
            m.lastSuccessfulBuildVersion or "尚未构建"
        )
        self._summary_vars["project_path"].set(str(summary.project_root))

        # 锁状态
        if summary.lock_info:
            self._lock_status_var.set(
                "锁：{0}（PID {1}）".format(
                    summary.lock_info.get("taskType", "?"),
                    summary.lock_info.get("pid", "?"),
                )
            )
        else:
            self._lock_status_var.set("")

        # 不兼容项目只读
        if not summary.is_writable:
            self._status_var.set("项目模式版本不兼容，以只读方式打开")
        else:
            self._status_var.set("就绪")

        # 加入最近项目
        add_recent_project(str(summary.project_root), m)
        self._refresh_recent_menu()
        self._init_content_workspace(summary)
        self._refresh_interaction_state()

    # --- 内容操作工作区 ---

    def _init_content_workspace(self, summary) -> None:
        """打开项目后创建/重建内容工作区。"""
        # 测试用 mock root 可能未运行 _build_ui，此时无内容宿主框架，跳过。
        if not hasattr(self, "_content_host_frame"):
            return
        self._content_index_ready = False
        self._content_current_file: Optional[str] = None
        for child in self._content_host_frame.winfo_children():
            child.destroy()
        from doc_tool.ui.content.workspace import ContentWorkspace

        self._content_workspace = ContentWorkspace(
            self._content_host_frame,
            summary.paths.content_root,
            state_dir=summary.paths.state_dir,
            assets_root=summary.paths.assets_root,
            writable=summary.is_writable,
            on_status=lambda msg: self._status_var.set(msg),
            on_open_file=self._on_content_open_file,
            on_request_validate=self._on_content_request_validate,
            on_index_ready=self._on_content_index_ready,
        )
        self._content_workspace.pack(fill="both", expand=True)

    def _on_content_index_ready(self) -> None:
        self._content_index_ready = True
        self._refresh_interaction_state()

    def _on_content_open_file(self, rel_path: str) -> None:
        self._content_current_file = rel_path
        self._refresh_interaction_state()

    def _on_content_request_validate(self) -> None:
        """替换/重命名写回后自动跑校验管线（复用现有校验任务）。"""
        self._log("内容写回完成，自动执行校验以检查悬空引用…")
        self._on_validate()

    def _content_workspace_available(self) -> bool:
        return bool(
            getattr(self, "_content_workspace", None)
            and getattr(self, "_content_index_ready", False)
        )

    def _select_content_tab(self, tab_text: str) -> None:
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None:
            return
        notebook = getattr(workspace, "_notebook", None)
        if notebook is None:
            return
        for tab_id in notebook.tabs():
            if notebook.tab(tab_id, "text") == tab_text:
                notebook.select(tab_id)
                return

    def _on_content_search(self) -> None:
        if not self._content_workspace_available():
            return
        self._select_content_tab("搜索")
        panel = getattr(self._content_workspace, "_search_panel", None)
        if panel is not None:
            panel.focus_query()

    def _on_content_replace(self) -> None:
        if not self._content_workspace_available():
            return
        summary = self._project_summary
        if summary and not summary.is_writable:
            return
        self._select_content_tab("替换")

    def _on_content_refactor(self) -> None:
        if not self._content_workspace_available():
            return
        summary = self._project_summary
        if summary and not summary.is_writable:
            return
        self._select_content_tab("重命名/重编号")
        workspace = self._content_workspace
        panel = getattr(workspace, "_refactor_panel", None)
        current = getattr(self, "_content_current_file", None)
        if panel is not None and current:
            panel.set_target(current)

    def _on_content_lint(self) -> None:
        if not self._content_workspace_available():
            return
        self._select_content_tab("检查")
        panel = getattr(self._content_workspace, "_lint_panel", None)
        if panel is not None:
            panel.run_check()

    def _on_content_open_external(self) -> None:
        workspace = getattr(self, "_content_workspace", None)
        if workspace is None:
            return
        editor = getattr(workspace, "_editor", None)
        if editor is not None:
            editor.open_external()

    def _on_content_references(self) -> None:
        """引用分析：当前文件的被引用情况 + 全项目悬空引用。"""
        workspace = getattr(self, "_content_workspace", None)
        index = getattr(workspace, "_index", None)
        if index is None:
            return
        current = getattr(self, "_content_current_file", None)
        from doc_tool.ui.content.references_dialog import show_references_dialog

        show_references_dialog(
            self.root,
            index,
            current_file=current,
            on_open=self._on_content_open_from_dialog,
        )

    def _on_content_open_from_dialog(self, rel_path: str, line_no: int) -> None:
        workspace = getattr(self, "_content_workspace", None)
        if workspace is not None:
            workspace.open_file(rel_path, line_no)

    # --- 内容菜单状态 ---

    def _render_result_state(self) -> None:
        """Render persistent task result and only actions whose paths still exist."""
        state = getattr(self, "_result_state", ResultState())
        if hasattr(self, "_result_title_var"):
            self._result_title_var.set(state.title)
            self._result_summary_var.set(state.summary)
            self._result_advice_var.set(
                "建议：{0}".format(state.advice) if state.advice else ""
            )
        frame = getattr(self, "_result_actions", None)
        if frame is None:
            return
        try:
            for child in frame.winfo_children():
                child.destroy()
        except Exception:
            return
        from tkinter import ttk

        project = getattr(self, "_project_summary", None)
        project_root = getattr(project, "project_root", None)
        if state.project_root and project_root:
            try:
                if Path(state.project_root).resolve() != Path(project_root).resolve():
                    return
            except OSError:
                return

        def add(label, command):
            ttk.Button(
                frame, text=label, command=command, style="Compact.TButton"
            ).pack(side="left", padx=(0, 6))

        if state.output_path and Path(state.output_path).is_file():
            add("打开产物", lambda p=state.output_path: self._open_result_file(p))
            add("打开所在目录", lambda p=Path(state.output_path).parent: self._open_result_directory(p))
        if state.report_path and Path(state.report_path).is_file():
            add("查看校验报告", self._on_open_validation_report)
        if state.status == "failure" and (
            state.error_code or state.stage or state.exception_summary or state.log_path
        ):
            add("技术详情…", self._show_result_technical_details)

    def _open_result_file(self, path: Path) -> None:
        if not self._open_file(Path(path)):
            self._show_error(
                "结果已不可用",
                "该任务产物已被移动或删除：{0}".format(path),
                "请重新执行任务，或打开当前项目输出目录查找仍存在的产物。",
            )
            self._render_result_state()

    def _open_result_directory(self, path: Path) -> None:
        if not self._open_directory(Path(path)):
            self._show_error("结果目录已不可用", "无法打开目录：{0}".format(path))
            self._render_result_state()

    def _show_result_technical_details(self) -> None:
        from tkinter import messagebox

        state = self._result_state
        details = [
            "错误码：{0}".format(state.error_code or "未知"),
            "失败阶段：{0}".format(state.stage or "未知"),
            "异常摘要：{0}".format(state.exception_summary or "无"),
            "日志路径：{0}".format(state.log_path or "未生成"),
        ]
        messagebox.showinfo("技术详情", "\n".join(details), parent=self.root)

    def _toggle_summary(self) -> None:
        """折叠/展开项目摘要区，为内容工作区腾出垂直空间。"""
        self._summary_collapsed = not getattr(self, "_summary_collapsed", False)
        body = getattr(self, "_summary_body", None)
        button = getattr(self, "_summary_toggle_btn", None)
        if body is None or button is None:
            return
        try:
            if self._summary_collapsed:
                body.pack_forget()
                button.configure(text="展开")
            else:
                body.pack(fill="x", pady=(4, 0))
                button.configure(text="收起")
        except Exception:
            pass

    def _toggle_log(self) -> None:
        self._log_expanded = not getattr(self, "_log_expanded", False)
        if self._log_expanded:
            self._log_body.pack(fill="both", expand=True, pady=(4, 0))
            self._log_frame.pack_configure(fill="both", expand=True)
            self._log_toggle_btn.configure(text="折叠")
            self._log_summary_var.set("日志已展开")
            self._scroll_log_to_bottom()
        else:
            self._log_body.pack_forget()
            self._log_frame.pack_configure(fill="x", expand=False)
            self._log_toggle_btn.configure(text="展开")
            self._log_summary_var.set("日志已折叠")

    def _expand_log_and_scroll(self, _event=None):
        if not getattr(self, "_log_expanded", False):
            self._toggle_log()
        return self._scroll_log_to_bottom()

    def _copy_log(self) -> None:
        try:
            content = self._log_text.get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.root.update_idletasks()
            self._status_var.set("日志内容已复制")
        except Exception:
            self._show_error("复制失败", "无法复制日志内容。")

    def _schedule_elapsed_update(self) -> None:
        if not self.runner.is_running or self._task_started_at is None:
            return
        from time import monotonic

        elapsed = max(0, int(monotonic() - self._task_started_at))
        if hasattr(self, "_elapsed_var"):
            self._elapsed_var.set("已用时间：{0:02d}:{1:02d}".format(elapsed // 60, elapsed % 60))
        self._elapsed_timer = self.root.after(1000, self._schedule_elapsed_update)

    def _stop_elapsed_update(self) -> None:
        """Stop the elapsed timer while preserving the final displayed duration."""
        timer = getattr(self, "_elapsed_timer", None)
        root = getattr(self, "root", None)
        if timer is not None and root is not None:
            try:
                root.after_cancel(timer)
            except Exception:
                pass
        self._elapsed_timer = None
        started_at = getattr(self, "_task_started_at", None)
        if started_at is not None and hasattr(self, "_elapsed_var"):
            from time import monotonic

            elapsed = max(0, int(monotonic() - started_at))
            self._elapsed_var.set(
                "已用时间：{0:02d}:{1:02d}".format(elapsed // 60, elapsed % 60)
            )
        self._task_started_at = None

    def _current_log_path(self):
        project = getattr(self, "_project_summary", None)
        paths = getattr(project, "paths", None)
        if paths is None:
            return None
        try:
            return paths.logs_dir / "runtime.log"
        except Exception:
            return None

    # --- 菜单回调 ---

    def _on_new_project(self) -> None:
        if self.runner.is_running:
            return
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard(self.root)
        result = wizard.run()
        if result is not None:
            # 导入成功后打开项目
            self._open_project_path(str(result))

    def _on_open_project(self) -> None:
        if self.runner.is_running:
            return
        from tkinter import filedialog

        path = filedialog.askdirectory(title="选择项目目录", mustexist=True)
        if path:
            self._open_project_path(path)

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
        except Exception as exc:
            self._show_error("打开项目失败", str(exc)[:200])
            return
        self.show_project(summary)
        self._log("已打开项目：{0}".format(summary.project_root.name))

    def _on_validate(self) -> None:
        if not self._project_summary or self.runner.is_running:
            return
        summary = self._project_summary
        from doc_tool.adapters.kernel import ensure_kernel_importable, validate_with_project

        try:
            ensure_kernel_importable()
        except Exception as exc:
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

        # 任务 7.1：正式合并前检查 Word 可用性，缺失时阻断并提示诊断构建
        # 这里只做快速静态检查；实际 DispatchEx 探测由后台管线执行，避免
        # Word 首次启动或故障超时冻结 Tk 主线程。
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
        except Exception as exc:
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
        except Exception as exc:
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
        # 清空上次残留，避免进度条先跳到旧任务终点。
        try:
            while True:
                q.get_nowait()
        except _queue.Empty:
            pass

        def emit(stage, status, detail=""):
            try:
                q.put((stage, status, detail))
            except Exception:
                pass

        return emit

    def _on_cancel(self) -> None:
        if not self.runner.is_running:
            return
        # 防连点：再次点击取消无意义且会让文案反复切换。
        self._cancel_btn.configure(state="disabled")
        current_stage = self._current_stage_label()
        if current_stage:
            self._status_var.set(
                "等待安全停止点（当前阶段：{0}）…".format(current_stage)
            )
        else:
            self._status_var.set("正在取消…")
        self._log("⊘ 已请求取消，将在阶段边界安全停止…")
        self.runner.cancel()

    def _current_stage_label(self) -> str:
        """返回当前正在运行的阶段中文标签（无则空串）。"""
        recent = getattr(self, "_progress_recent_stage", "")
        if not recent:
            return ""
        return _pipeline_stage_labels().get(recent, recent)

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
                # 输出目录尚未生成：不静默创建，避免掩盖「构建没产出」的问题。
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
                self._project_summary.paths.logs_dir,
                "日志目录",
                create=True,
            )

    def _validation_report_path(self):
        """返回当前项目校验报告路径（logs/<docType>-validation.md）或 None。"""
        if not self._project_summary:
            return None
        try:
            return (
                self._project_summary.paths.logs_dir
                / (self._project_summary.manifest.documentType + "-validation.md")
            )
        except Exception:
            return None

    def _refresh_validation_report_state(self) -> None:
        """兼容旧调用，转由统一状态矩阵刷新。"""
        self._refresh_interaction_state()

    def _on_open_validation_report(self) -> None:
        """打开或预览校验报告。优先用系统关联程序打开 .md 文件。"""
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

    def _show_validation_report_preview(self, path: Path) -> None:
        """系统关联程序不可用时，以只读窗口展示校验报告。"""
        import tkinter as tk
        from tkinter import ttk

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._show_error(
                "无法读取校验报告",
                "无法读取校验报告：{0}".format(exc),
                "请检查文件权限，或在文件管理器中手动打开该文件。",
            )
            return

        preview = tk.Toplevel(self.root)
        preview.title("校验报告预览")
        preview.geometry("760x560")
        preview.minsize(520, 360)
        preview.transient(self.root)

        frame = ttk.Frame(preview, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=str(path),
            wraplength=700,
            foreground="gray",
        ).pack(fill="x", anchor="w", pady=(0, 8))

        text = tk.Text(frame, wrap="word", font=("Microsoft YaHei", 9))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", content)
        text.configure(state="disabled")

        buttons = ttk.Frame(preview, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")

        def copy_path() -> None:
            try:
                preview.clipboard_clear()
                preview.clipboard_append(str(path))
                preview.update_idletasks()
            except Exception:
                pass

        ttk.Button(buttons, text="复制路径", command=copy_path).pack(side="left")
        close_btn = ttk.Button(buttons, text="关闭", command=preview.destroy)
        close_btn.pack(side="right")
        preview.bind("<Escape>", lambda _event: preview.destroy())
        preview.bind("<Return>", lambda _event: preview.destroy())
        close_btn.focus_set()

    def _on_about(self) -> None:
        from doc_tool.ui.about_dialog import show_about_dialog

        show_about_dialog(self.root)

    # --- 任务执行 ---

    def _start_task(self, spec: TaskSpec) -> None:
        from time import monotonic

        self._current_task = spec.name
        self._task_started_at = monotonic()
        if hasattr(self, "_elapsed_var"):
            self._elapsed_var.set("已用时间：00:00")
        self._result_state = ResultState(
            status="running",
            task=spec.name,
            title="任务运行中：{0}".format(self._task_label(spec.name)),
            summary="任务完成后将在这里保留结果和适用的后续操作。",
            project_root=getattr(self._project_summary, "project_root", None),
        )
        self._render_result_state()
        self._progress_recent_stage = ""
        self._last_error_code = None
        self._last_error_stage = ""
        self._last_error_detail = ""
        self._task_terminal_kind = ""
        self._cancel_btn.configure(state="normal")
        if self._stage_progress_enabled:
            self._progress.configure(mode="determinate")
            self._progress.configure(value=0)
        else:
            # 该任务无阶段进度回调（如独立校验），回退心跳动画。
            self._progress.configure(mode="indeterminate")
            self._progress.start(15)
        self._task_name_var.set("正在执行：{0}…".format(self._task_label(spec.name)))
        self._status_var.set("任务运行中")

        started = self.runner.start(
            spec, on_event=self._on_task_event, on_done=self._on_task_done
        )
        if not started:
            self._progress.stop()
            self._cancel_btn.configure(state="disabled")
            self._task_started_at = None
            self._current_task = ""
            self._result_state = ResultState(
                title="任务未启动",
                summary="已有任务正在运行，本次请求未启动。",
                advice="请等待当前任务完成后重试。",
                project_root=getattr(
                    getattr(self, "_project_summary", None), "project_root", None
                ),
            )
            self._render_result_state()
            self._task_name_var.set("无任务运行")
            self._status_var.set("已有任务正在运行")
            self._refresh_interaction_state()
            return
        self._refresh_recent_menu()
        self._refresh_interaction_state()
        self._schedule_elapsed_update()
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll_scheduled:
            return
        self._poll_scheduled = True
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_scheduled = False
        # 先消费后台线程推入的阶段进度，再处理任务事件/完成。
        self._drain_stage_progress()
        self.runner.poll()
        if self.runner.is_running:
            self._schedule_poll()

    def _drain_stage_progress(self) -> None:
        """消费进度通道，更新确定性进度条与当前阶段文本。"""
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
        """根据阶段状态更新进度条值与任务名文本。"""
        span = _pipeline_stage_percent().get(stage)
        label = _pipeline_stage_labels().get(stage, stage)
        if status == "started":
            self._progress_recent_stage = stage
            if span is not None:
                self._progress.configure(value=span[0])
            self._task_name_var.set(
                "正在执行：{0}（{1}）…".format(self._task_label(self._current_task), label)
            )
        elif status == "skipped":
            if span is not None:
                # 跳过阶段直接跨越到其终值，保持单调递增。
                self._progress.configure(value=span[1])
            self._log("· {0} 已跳过".format(label))
        elif status == "succeeded":
            if span is not None:
                self._progress.configure(value=span[1])
            self._log("✓ {0} 完成".format(label))
        elif status == "failed":
            self._log("✗ {0} 失败：{1}".format(label, detail))

    def _on_task_event(self, event: TaskEvent) -> None:
        """处理任务事件（由 poll 调用）。"""
        if event.kind in ("failed", "cancelled"):
            self._last_error_code = event.error_code
            self._last_error_stage = event.stage or self._progress_recent_stage
            self._last_error_detail = (event.detail or "")[:200]
            self._task_terminal_kind = event.kind
        if event.kind == "failed":
            self._log("✗ {0} 失败：{1}（{2}）".format(
                self._task_label(event.stage), event.detail, event.error_code or "?"
            ))
        elif event.kind == "started":
            self._log("▶ {0} 开始".format(self._task_label(event.stage)))
        elif event.kind == "succeeded":
            self._task_terminal_kind = "succeeded"
            self._log("✓ {0} 完成".format(self._task_label(event.stage)))
        elif event.kind == "cancelled":
            self._log("⊘ {0} 已取消".format(self._task_label(event.stage)))

    def _on_task_done(self, result) -> None:
        """按当前任务的明确结果语义更新界面并统一收尾。"""
        current_task = self._current_task
        result_type = TASK_UI.get(current_task, {}).get("result_type", "unknown")
        self._stop_elapsed_update()
        self._progress.stop()
        self._cancel_btn.configure(state="disabled")
        self._task_name_var.set("无任务运行")
        self._drain_stage_progress()
        if (
            self._stage_progress_enabled
            and result_type == "pipeline"
            and result is not None
            and getattr(result, "success", False)
        ):
            self._progress.configure(value=100)
        self._stage_progress_enabled = False

        if result is None:
            from doc_tool.ui.task_bridge import ERR_WATCHDOG_TIMEOUT

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
            self._render_result_state()
            self._status_var.set(title)
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
            self._render_result_state()
            self._status_var.set("任务完成")

        self._refresh_recent_menu()
        self._refresh_interaction_state()
        self._last_error_code = None
        self._last_error_stage = ""
        self._last_error_detail = ""
        self._task_terminal_kind = ""
        self._current_task = ""
        if self._close_after_task:
            self._finish_close()

    def _handle_pipeline_result(self, result) -> None:
        project = getattr(self, "_project_summary", None)
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
                    self._status_var.set("正式合并成功（Word 已刷新，字段已校验）")
                    self._log("✓ 正式输出：{0}".format(output_path))
                else:
                    title = "诊断构建完成"
                    summary = "已生成非正式诊断输出：{0}".format(output_path)
                    self._status_var.set("诊断构建完成（非正式，字段未实机刷新）")
                    self._log("△ 诊断输出：{0}".format(output_path))
                self._summary_vars["last_build"].set(APP_VERSION)
            else:
                title = "任务成功完成"
                summary = "任务已完成，但没有返回新的文档产物。"
                self._status_var.set(title)
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
            self._status_var.set(
                "任务已取消" if cancelled else "任务失败（{0}）".format(code)
            )
        self._render_result_state()

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
            self._status_var.set(summary)
            self._log("校验报告：{0}".format(report_path))
            for failure in report["failures"][:10]:
                self._log("  ✗ {0}".format(failure))
        else:
            status = "校验通过" if passed else "校验未通过"
            summary = status
            self._status_var.set(status)

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
        self._render_result_state()

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

    @staticmethod
    def _summary_label(key: str) -> str:
        labels = {
            "document_name": "文档名称",
            "document_no": "文档编号",
            "document_type": "文档类型",
            "document_version": "文档版本",
            "source_hash": "源文件指纹",
            "last_build": "最后构建版本",
            "project_path": "项目路径",
        }
        return labels.get(key, key)

    def _on_log_scroll_check(self, _event=None) -> None:
        """用户滚动日志后更新 ``_log_at_bottom``：回到底部则清待读提示。"""
        was_at_bottom = self._log_at_bottom
        self._log_at_bottom = self._log_is_at_bottom()
        if self._log_at_bottom and self._log_pending:
            self._log_pending = 0
            self._log_pending_var.set("")
        elif self._log_at_bottom and not was_at_bottom:
            self._log_pending_var.set("")

    def _scroll_log_to_bottom(self, _event=None):
        """滚到日志底部并清除待读计数。"""
        try:
            self._log_text.see("end")
        except Exception:
            pass
        self._log_at_bottom = True
        self._log_pending = 0
        self._log_pending_var.set("")
        if getattr(self, "_log_expanded", False) and hasattr(self, "_log_summary_var"):
            self._log_summary_var.set("日志已展开")
        return "break"

    def _log_is_at_bottom(self) -> bool:
        """判断当前视图是否停在日志底部。"""
        try:
            yview = self._log_text.yview()
            # yview 返回 (top, bottom)；底部判定取 bottom >= 1.0 的近似。
            return float(yview[1]) >= 0.999
        except Exception:
            return True

    def _log(self, message: str) -> None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", "[{0}] {1}\n".format(timestamp, message))
        if getattr(self, "_log_expanded", False) and self._log_at_bottom:
            self._log_text.see("end")
            self._log_pending = 0
            self._log_pending_var.set("")
        else:
            # 折叠或用户离开底部时继续接收事件，并累计待读提示。
            self._log_pending += 1
            self._log_pending_var.set("待读 {0} 条新日志…".format(self._log_pending))
            if hasattr(self, "_log_summary_var"):
                self._log_summary_var.set(
                    "日志已折叠 · {0} 条待读".format(self._log_pending)
                )
        self._log_text.configure(state="disabled")

    def _show_error(self, title: str, message: str, suggestion: str = "") -> None:
        from tkinter import messagebox

        full = message
        if suggestion:
            full += "\n\n建议：{0}".format(suggestion)
        messagebox.showerror(title, full, parent=self.root)

    @staticmethod
    def _open_path(path: Path) -> bool:
        """使用系统关联程序打开已存在的路径。"""
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
        """打开目录；仅在调用方明确允许时创建缺失目录。"""
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
        """打开已存在的文件，绝不创建缺失路径。"""
        path = Path(path)
        if not path.is_file():
            return False
        return cls._open_path(path)

    def _open_directory_or_warn(
        self,
        path: Path,
        what: str,
        create: bool = False,
    ) -> bool:
        """打开目录，失败时给出明确提示。"""
        if not self._open_directory(path, create=create):
            self._show_error(
                "无法打开{0}".format(what),
                "无法打开{0}：{1}".format(what, path),
                "请检查目录是否存在、是否被占用或权限不足。",
            )
            return False
        return True

    # --- 窗口几何持久化 ---

    def _is_maximized(self) -> bool:
        """判断窗口是否处于最大化（zoomed）状态。"""
        try:
            return bool(self.root.wm_state() == "zoomed")
        except Exception:
            return False

    def _on_root_configure(self, _event=None) -> None:
        """窗口尺寸/位置变化时去抖保存几何。拖动过程的频繁事件用 100ms 节流。"""
        # 最大化态不写回几何，避免覆盖用户期望的「正常态」尺寸。
        if self._is_maximized():
            return
        if self._geom_save_timer is not None:
            try:
                self.root.after_cancel(self._geom_save_timer)
            except Exception:
                pass
        self._geom_save_timer = self.root.after(600, self._persist_geometry)

    def _persist_geometry(self) -> None:
        from doc_tool.application.project_service import save_window_geometry

        try:
            geometry = self.root.geometry()
        except Exception:
            return
        if not geometry:
            return
        # 解析 "WxH+X+Y" 形式；非法则不保存。
        import re

        if not re.match(r"^\d+x\d+\d*[+-]\d+[+-]\d+$", geometry):
            # 仅有 WxH（未定位）也保存，避免退出态丢失。
            if not re.match(r"^\d+x\d+$", geometry):
                return
        save_window_geometry(geometry, self._is_maximized())

    def _finish_close(self) -> None:
        """保存窗口状态并只销毁一次根窗口。"""
        self._close_after_task = False
        try:
            self._persist_geometry()
        except Exception:
            pass
        try:
            if bool(self.root.winfo_exists()):
                self.root.destroy()
        except Exception:
            pass

    def _on_close(self) -> None:
        """任务运行中先请求安全取消，终态回调到达后再关闭窗口。"""
        if not self.runner.is_running:
            self._finish_close()
            return
        if self._close_after_task:
            return

        from tkinter import messagebox

        confirmed = messagebox.askyesno(
            "任务仍在运行",
            "当前任务尚未完成。是否请求安全取消，并在任务停止后退出？\n\n"
            "任务会在下一个安全阶段边界停止。",
            parent=self.root,
        )
        if not confirmed:
            return

        self._close_after_task = True
        self._cancel_btn.configure(state="disabled")
        self._status_var.set("正在安全停止任务，停止后将自动退出…")
        self._task_name_var.set(
            "正在停止：{0}…".format(self._task_label(self._current_task))
        )
        self._log("⊘ 已请求安全取消；任务停止后应用将自动退出。")
        self.runner.cancel()
