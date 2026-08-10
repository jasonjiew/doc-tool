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
        # 用户在任务运行中确认退出后，等待任务安全结束再销毁窗口。
        self._close_after_task = False

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

        # --- 项目摘要面板 ---
        summary_frame = ttk.LabelFrame(self.root, text="项目摘要", padding=12)
        summary_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._summary_vars = {}
        # 需要自动换行的长字段：项目路径、文档名称等可能超出窗口宽度。
        wrap_keys = {"project_path", "document_name"}
        for i, key in enumerate(
            ("document_name", "document_no", "document_type",
             "document_version", "source_hash", "last_build", "project_path")
        ):
            ttk.Label(summary_frame, text=self._summary_label(key) + "：").grid(
                row=i, column=0, sticky="w", pady=2
            )
            var = tk.StringVar(value="—")
            self._summary_vars[key] = var
            if key in wrap_keys:
                ttk.Label(summary_frame, textvariable=var, wraplength=560).grid(
                    row=i, column=1, sticky="we", padx=(8, 0), pady=2
                )
            else:
                ttk.Label(summary_frame, textvariable=var).grid(
                    row=i, column=1, sticky="w", padx=(8, 0), pady=2
                )
        summary_frame.columnconfigure(1, weight=1)

        # --- 任务进度面板 ---
        progress_frame = ttk.LabelFrame(self.root, text="任务进度", padding=8)
        progress_frame.pack(fill="x", padx=8, pady=4)

        self._task_name_var = tk.StringVar(value="无任务运行")
        ttk.Label(progress_frame, textvariable=self._task_name_var).pack(anchor="w")

        self._progress = ttk.Progressbar(
            progress_frame, mode="determinate", length=400, maximum=100
        )
        self._progress.pack(fill="x", pady=(4, 2))

        self._cancel_btn = ttk.Button(
            progress_frame, text="取消", command=self._on_cancel, state="disabled"
        )
        self._cancel_btn.pack(side="right", pady=(4, 0))

        # --- 事件日志面板 ---
        log_frame = ttk.LabelFrame(self.root, text="事件日志", padding=4)
        log_frame.pack(fill="both", expand=True, padx=8, pady=4)

        self._log_text = tk.Text(
            log_frame, height=10, state="disabled", wrap="word",
            font=("Consolas", 9),
        )
        log_scroll = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        # 待读提示放在右上角（默认空，不占视觉空间）。
        self._log_pending_var = tk.StringVar(value="")
        self._log_pending_label = ttk.Label(
            log_frame, textvariable=self._log_pending_var,
            style="Status.TLabel", foreground="#b00", cursor="hand2",
        )
        self._log_pending_label.pack(side="top", anchor="ne")
        self._log_pending_label.bind("<Button-1>", self._scroll_log_to_bottom)
        self._log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        # 智能自动滚动：记录用户是否停在底部；离开底部时不再强制滚到底，
        # 同时在日志框右上角提示待读条数。
        self._log_at_bottom = True
        self._log_pending = 0
        self._log_text.bind("<ButtonRelease-1>", self._on_log_scroll_check)
        self._log_text.bind("<KeyRelease>", self._on_log_scroll_check)
        log_scroll.bind("<B1-Motion>", lambda _e: self._on_log_scroll_check())

        # --- 状态栏 ---
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
        self.root.bind("<F1>", lambda _e: self._on_about())

    # --- 状态管理 ---

    def _update_no_project_state(self) -> None:
        """无项目时的初始状态。"""
        for key in self._summary_vars:
            self._summary_vars[key].set("—")
        self._refresh_recent_menu()
        self._refresh_interaction_state()

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
        """根据项目、只读和任务状态统一刷新所有关键操作。"""
        has_project = self._project_summary is not None
        writable = bool(
            has_project and getattr(self._project_summary, "is_writable", False)
        )
        running = bool(self.runner.is_running)

        self._set_menu_entries(
            self._file_menu,
            self._file_entry_indexes,
            ("new", "open", "recent"),
            not running,
        )
        self._set_menu_entries(
            self._ops_menu,
            self._ops_entry_indexes,
            ("validate", "merge", "diag_build"),
            writable and not running,
        )
        self._set_menu_entries(
            self._tools_menu,
            self._tools_entry_indexes,
            ("content", "output", "logs"),
            has_project,
        )
        path = self._validation_report_path()
        self._set_menu_entries(
            self._ops_menu,
            self._ops_entry_indexes,
            ("validation_report",),
            bool(has_project and path and path.exists()),
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
        self._refresh_interaction_state()

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
        self._current_task = spec.name
        self._progress_recent_stage = ""
        self._last_error_code = None
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
            self._cancel_btn.configure(state="disabled")
            self._status_var.set("已有任务正在运行")
            return
        self._refresh_recent_menu()
        self._refresh_interaction_state()
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
        if event.kind == "failed":
            self._last_error_code = event.error_code
            self._log("✗ {0} 失败：{1}（{2}）".format(
                self._task_label(event.stage), event.detail, event.error_code or "?"
            ))
        elif event.kind == "started":
            self._log("▶ {0} 开始".format(self._task_label(event.stage)))
        elif event.kind == "succeeded":
            self._log("✓ {0} 完成".format(self._task_label(event.stage)))
        elif event.kind == "cancelled":
            self._log("⊘ {0} 已取消".format(self._task_label(event.stage)))

    def _on_task_done(self, result) -> None:
        """按当前任务的明确结果语义更新界面并统一收尾。"""
        current_task = self._current_task
        result_type = TASK_UI.get(current_task, {}).get("result_type", "unknown")
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
        self._refresh_recent_menu()
        self._refresh_interaction_state()

        if result is None:
            from doc_tool.ui.task_bridge import ERR_WATCHDOG_TIMEOUT

            if self._last_error_code == ERR_WATCHDOG_TIMEOUT:
                self._status_var.set("任务运行超时，已强制结束")
            else:
                self._status_var.set("任务未成功完成")
        elif result_type == "pipeline":
            self._handle_pipeline_result(result)
        elif result_type == "validation":
            self._handle_validation_result(bool(result))
        else:
            self._status_var.set("任务完成")

        self._last_error_code = None
        self._current_task = ""
        if self._close_after_task:
            self._finish_close()

    def _handle_pipeline_result(self, result) -> None:
        if result.success:
            from doc_tool.domain.output_state import is_formal_success

            if result.output_path:
                formal = is_formal_success(result.output_path)
                if formal:
                    self._status_var.set("正式合并成功（Word 已刷新，字段已校验）")
                    self._log("✓ 正式输出：{0}".format(result.output_path))
                else:
                    self._status_var.set("诊断构建完成（非正式，字段未实机刷新）")
                    self._log("△ 诊断输出：{0}".format(result.output_path))
                self._summary_vars["last_build"].set(APP_VERSION)
            else:
                self._status_var.set("任务成功完成")
        else:
            self._status_var.set("任务失败（{0}）".format(result.error_code or "未知"))

    def _handle_validation_result(self, passed: bool) -> None:
        from doc_tool.application.project_service import read_validation_report_summary

        report_path = self._validation_report_path()
        report = read_validation_report_summary(report_path) if report_path else {}
        if report.get("exists"):
            status = "校验通过" if passed else "校验未通过"
            self._status_var.set(
                "{0}（PASS={1} FAIL={2}）".format(
                    status, report["passCount"], report["failCount"]
                )
            )
            self._log("校验报告：{0}".format(report_path))
            for failure in report["failures"][:10]:
                self._log("  ✗ {0}".format(failure))
        else:
            self._status_var.set("校验通过" if passed else "校验未通过")

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
        if self._log_at_bottom:
            self._log_text.see("end")
            self._log_pending = 0
            self._log_pending_var.set("")
        else:
            # 用户离开底部：累计待读，提示条数。
            self._log_pending += 1
            self._log_pending_var.set("待读 {0} 条新日志…".format(self._log_pending))
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
