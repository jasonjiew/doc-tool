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
from doc_tool.ui.task_bridge import POLL_INTERVAL_MS, TaskEvent, TaskRunner, TaskSpec


# 文档类型中文映射
DOC_TYPE_LABELS = {
    "requirement": "需求文档",
    "design": "详细设计文档",
}


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

        self._build_ui()
        self._build_menu()
        self._update_no_project_state()

    # --- UI 构建 ---

    def _build_ui(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root.title("康尚文档工具 v{0}".format(APP_VERSION))
        self.root.geometry("860x600")
        self.root.minsize(640, 480)

        # --- 项目摘要面板 ---
        summary_frame = ttk.LabelFrame(self.root, text="项目摘要", padding=12)
        summary_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._summary_vars = {}
        for i, key in enumerate(
            ("document_name", "document_no", "document_type",
             "document_version", "source_hash", "last_build", "project_path")
        ):
            ttk.Label(summary_frame, text=self._summary_label(key) + "：").grid(
                row=i, column=0, sticky="w", pady=2
            )
            var = tk.StringVar(value="—")
            self._summary_vars[key] = var
            ttk.Label(summary_frame, textvariable=var).grid(
                row=i, column=1, sticky="w", padx=(8, 0), pady=2
            )

        # --- 任务进度面板 ---
        progress_frame = ttk.LabelFrame(self.root, text="任务进度", padding=8)
        progress_frame.pack(fill="x", padx=8, pady=4)

        self._task_name_var = tk.StringVar(value="无任务运行")
        ttk.Label(progress_frame, textvariable=self._task_name_var).pack(anchor="w")

        self._progress = ttk.Progressbar(
            progress_frame, mode="indeterminate", length=400
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
        self._log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

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
        from tkinter import ttk

        menubar = tk.Menu(self.root)

        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="新建项目…", command=self._on_new_project)
        file_menu.add_command(label="打开项目…", command=self._on_open_project)
        self._recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="最近打开", menu=self._recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.destroy)
        menubar.add_cascade(label="文件", menu=file_menu)

        # 操作菜单
        self._ops_menu = tk.Menu(menubar, tearoff=False)
        self._ops_menu.add_command(label="校验项目", command=self._on_validate)
        self._ops_menu.add_separator()
        self._ops_menu.add_command(label="正式合并", command=self._on_merge)
        self._ops_menu.add_command(label="诊断构建（无 Word）", command=self._on_diag_build)
        menubar.add_cascade(label="操作", menu=self._ops_menu)

        # 工具菜单
        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="打开 Markdown 目录", command=self._on_open_content)
        tools_menu.add_command(label="打开输出目录", command=self._on_open_output)
        tools_menu.add_command(label="打开日志目录", command=self._on_open_logs)
        menubar.add_cascade(label="工具", menu=tools_menu)

        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="关于 / 环境诊断", command=self._on_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.configure(menu=menubar)

    # --- 状态管理 ---

    def _update_no_project_state(self) -> None:
        """无项目时的初始状态。"""
        for key in self._summary_vars:
            self._summary_vars[key].set("—")
        self._set_ops_enabled(False)
        self._refresh_recent_menu()

    def _set_ops_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._ops_menu.entryconfig(0, state=state)  # 校验项目
        self._ops_menu.entryconfig(2, state=state)  # 正式合并
        self._ops_menu.entryconfig(3, state=state)  # 诊断构建

    def _refresh_recent_menu(self) -> None:
        from doc_tool.application.project_service import load_recent_projects

        self._recent_menu.delete(0, "end")
        entries = load_recent_projects()
        if not entries:
            self._recent_menu.add_command(label="（无）", state="disabled")
            return
        for entry in entries[:10]:
            label = entry.name
            if entry.document_name:
                label = "{0}（{1}）".format(entry.name, entry.document_name)
            self._recent_menu.add_command(
                label=label, command=lambda p=entry.path: self._open_project_path(p)
            )

    def show_project(self, summary) -> None:
        """显示已打开的项目摘要。"""
        from doc_tool.application.project_service import add_recent_project

        self._project_summary = summary
        m = summary.manifest
        self._summary_vars["document_name"].set(m.documentName)
        self._summary_vars["document_no"].set(m.documentNo)
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
            self._set_ops_enabled(False)
        else:
            self._status_var.set("就绪")
            self._set_ops_enabled(True)

        # 加入最近项目
        add_recent_project(str(summary.project_root), m)
        self._refresh_recent_menu()

    # --- 菜单回调 ---

    def _on_new_project(self) -> None:
        from doc_tool.ui.wizard import ImportWizard

        wizard = ImportWizard(self.root)
        result = wizard.run()
        if result is not None:
            # 导入成功后打开项目
            self._open_project_path(str(result))

    def _on_open_project(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="选择项目目录", mustexist=True)
        if path:
            self._open_project_path(path)

    def _open_project_path(self, path: str) -> None:
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

        spec = TaskSpec(
            name="validate",
            target=validate_with_project,
            args=(summary.manifest, summary.paths),
        )
        self._start_task(spec)

    def _on_merge(self) -> None:
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

        spec = TaskSpec(
            name="merge",
            target=run_pipeline,
            args=(summary.manifest, summary.paths),
            kwargs={"skip_word_refresh": False},
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

        spec = TaskSpec(
            name="diag_build",
            target=run_pipeline,
            args=(summary.manifest, summary.paths),
            kwargs={"skip_word_refresh": True},
        )
        self._start_task(spec)

    def _on_cancel(self) -> None:
        self.runner.cancel()
        self._status_var.set("正在取消…")

    def _on_open_content(self) -> None:
        if self._project_summary:
            self._open_in_explorer(
                self._project_summary.paths.content_dir(
                    self._project_summary.manifest.documentType
                )
            )

    def _on_open_output(self) -> None:
        if self._project_summary:
            self._open_in_explorer(self._project_summary.paths.output_dir)

    def _on_open_logs(self) -> None:
        if self._project_summary:
            self._open_in_explorer(self._project_summary.paths.logs_dir)

    def _on_about(self) -> None:
        from doc_tool.ui.about_dialog import show_about_dialog

        show_about_dialog(self.root)

    # --- 任务执行 ---

    def _start_task(self, spec: TaskSpec) -> None:
        self._cancel_btn.configure(state="normal")
        self._progress.start(15)  # 心跳动画
        self._task_name_var.set("正在执行：{0}…".format(self._task_label(spec.name)))
        self._status_var.set("任务运行中")
        self._set_ops_enabled(False)

        self.runner.start(spec, on_event=self._on_task_event, on_done=self._on_task_done)
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll_scheduled:
            return
        self._poll_scheduled = True
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_scheduled = False
        self.runner.poll()
        if self.runner.is_running:
            self._schedule_poll()

    def _on_task_event(self, event: TaskEvent) -> None:
        """处理任务事件（由 poll 调用）。"""
        if event.kind == "started":
            self._log("▶ {0} 开始".format(self._task_label(event.stage)))
        elif event.kind == "succeeded":
            self._log("✓ {0} 完成".format(self._task_label(event.stage)))
        elif event.kind == "failed":
            self._log("✗ {0} 失败：{1}（{2}）".format(
                self._task_label(event.stage), event.detail, event.error_code or "?"
            ))
        elif event.kind == "cancelled":
            self._log("⊘ {0} 已取消".format(self._task_label(event.stage)))

    def _on_task_done(self, result) -> None:
        """任务完成后更新界面。"""
        self._progress.stop()
        self._cancel_btn.configure(state="disabled")
        self._task_name_var.set("无任务运行")

        if self._project_summary and self._project_summary.is_writable:
            self._set_ops_enabled(True)

        if result is None:
            self._status_var.set("任务未成功完成")
            return

        # 处理管线结果
        if hasattr(result, "events") and hasattr(result, "success"):
            if result.success:
                self._status_var.set("任务成功完成")
                # 更新最后构建版本
                if result.output_path:
                    self._summary_vars["last_build"].set(APP_VERSION)
            else:
                code = result.error_code or "未知"
                self._status_var.set("任务失败（{0}）".format(code))
        else:
            # validate 返回 bool
            if result is True:
                self._status_var.set("校验通过")
            elif result is False:
                self._status_var.set("校验未通过")
            else:
                self._status_var.set("任务完成")

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

    def _log(self, message: str) -> None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", "[{0}] {1}\n".format(timestamp, message))
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _show_error(self, title: str, message: str, suggestion: str = "") -> None:
        from tkinter import messagebox

        full = message
        if suggestion:
            full += "\n\n建议：{0}".format(suggestion)
        messagebox.showerror(title, full, parent=self.root)

    @staticmethod
    def _open_in_explorer(path: Path) -> None:
        """在 Windows 文件管理器中打开目录。"""
        path = Path(path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
