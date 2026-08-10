# -*- coding: utf-8 -*-
"""新建项目向导：导入源 DOCX 为项目。

任务 6.2：选择源 Word、文档类型、项目名称和目标父目录。
任务 6.3：导入预览与确认页面，展示标题/资源计数和阻断告警。

向导流程：
1. 选择源 DOCX 文件
2. 执行预检，展示标题/图片/表格计数和告警
3. 选择通用模式或需求/详细设计预设，填写文档信息和目标父目录
4. 执行事务化导入
5. 显示导入结果（成功/失败）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from doc_tool.ui.task_bridge import POLL_INTERVAL_MS, TaskRunner, TaskSpec


def format_preview_summary(preview) -> str:
    """把 ``ImportPreview`` 转成向导文本；保持为纯函数便于无界面测试。"""
    lines = ["标题计数："]
    for level, count in sorted(preview.heading_level_counts.items()):
        lines.append("  Heading {0}: {1}".format(level, count))
    lines.extend([
        "",
        "图片数量：{0}".format(preview.image_count),
        "表格数量：{0}".format(preview.table_count),
        "",
    ])
    if preview.warnings:
        lines.append("告警：")
        lines.extend("  ⚠ {0}".format(warning) for warning in preview.warnings)
    else:
        lines.append("无告警。")
    suggestion = getattr(preview, "document_type_suggestion", None)
    if suggestion is not None:
        labels = {
            "general": "通用大文档",
            "requirement": "需求文档预设",
            "design": "详细设计预设",
        }
        lines.extend([
            "",
            "建议模式：{0}".format(
                labels.get(suggestion.document_type, suggestion.document_type)
            ),
            "原因：{0}".format(suggestion.reason),
        ])
    return "\n".join(lines)


class ImportWizard:
    """新建项目向导。

    使用 ``tk.Toplevel`` 模态对话框实现多步骤向导。
    返回项目目录路径（成功）或 None（取消）。
    """

    def __init__(self, parent) -> None:
        self.parent = parent
        self._result: Optional[str] = None
        self._source_path: Optional[str] = None
        self._preview = None  # PreflightPreview
        self._doc_type = "general"
        self._target_parent: Optional[str] = None
        self._runner = TaskRunner()
        self._poll_scheduled = False
        self._project_info_error = ""

    def run(self) -> Optional[str]:
        """运行向导，返回项目路径或 None。"""
        import tkinter as tk
        from tkinter import ttk

        self._dialog = tk.Toplevel(self.parent)
        self._dialog.title("新建项目向导")
        self._dialog.geometry("680x540")
        self._dialog.minsize(480, 420)
        self._dialog.transient(self.parent)
        self._dialog.grab_set()
        self._dialog.protocol("WM_DELETE_WINDOW", self._cancel)

        # 步骤变量
        self._step = 0  # 0=选择源, 1=预检预览, 2=项目信息, 3=执行中, 4=结果

        self._build_steps()
        self._show_step()

        self._dialog.wait_window()
        return self._result

    def _build_steps(self) -> None:
        """构建所有步骤面板。"""
        import tkinter as tk
        from tkinter import ttk

        # --- 步骤 0：选择源 DOCX ---
        self._step0 = ttk.Frame(self._dialog, padding=16)

        ttk.Label(self._step0, text="步骤 1/4：选择源 Word 文档", style="Heading.TLabel").pack(
            anchor="w", pady=(0, 12)
        )
        ttk.Label(
            self._step0,
            text="选择要导入的 .docx 文件。文件将被只读复制到项目中，源文件不会被修改。",
            wraplength=480,
        ).pack(anchor="w", pady=(0, 12))

        file_frame = ttk.Frame(self._step0)
        file_frame.pack(fill="x", pady=8)
        self._source_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self._source_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(file_frame, text="浏览…", command=self._browse_source).pack(
            side="right", padx=(8, 0)
        )

        # --- 步骤 1：预检预览 ---
        self._step1 = ttk.Frame(self._dialog, padding=16)

        ttk.Label(self._step1, text="步骤 2/4：导入预检", style="Heading.TLabel").pack(
            anchor="w", pady=(0, 12)
        )
        self._preview_text = tk.Text(
            self._step1, height=14, wrap="word", state="disabled",
            font=("Microsoft YaHei", 9),
        )
        self._preview_text.pack(fill="both", expand=True)

        # --- 步骤 2：项目信息 ---
        self._step2 = ttk.Frame(self._dialog, padding=16)

        ttk.Label(self._step2, text="步骤 3/4：项目信息", style="Heading.TLabel").pack(
            anchor="w", pady=(0, 12)
        )

        info_grid = ttk.Frame(self._step2)
        info_grid.pack(fill="x", pady=4)

        # 文档类型
        ttk.Label(info_grid, text="文档类型：").grid(row=0, column=0, sticky="w", pady=4)
        self._type_var = tk.StringVar(value="general")
        type_frame = ttk.Frame(info_grid)
        type_frame.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Radiobutton(
            type_frame, text="通用大文档", variable=self._type_var, value="general"
        ).pack(side="left")
        ttk.Radiobutton(
            type_frame, text="需求文档预设", variable=self._type_var, value="requirement"
        ).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(
            type_frame, text="详细设计预设", variable=self._type_var, value="design"
        ).pack(side="left", padx=(12, 0))

        # 文档编号
        ttk.Label(info_grid, text="文档编号（通用可选）：").grid(row=1, column=0, sticky="w", pady=4)
        self._doc_no_var = tk.StringVar()
        ttk.Entry(info_grid, textvariable=self._doc_no_var).grid(
            row=1, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 文档名称
        ttk.Label(info_grid, text="文档名称：").grid(row=2, column=0, sticky="w", pady=4)
        self._doc_name_var = tk.StringVar()
        ttk.Entry(info_grid, textvariable=self._doc_name_var).grid(
            row=2, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 文档版本
        ttk.Label(info_grid, text="文档版本（通用可选）：").grid(row=3, column=0, sticky="w", pady=4)
        self._doc_version_var = tk.StringVar(value="1.0")
        ttk.Entry(info_grid, textvariable=self._doc_version_var).grid(
            row=3, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 项目名称（目录名）
        ttk.Label(info_grid, text="项目目录名：").grid(row=4, column=0, sticky="w", pady=4)
        self._project_name_var = tk.StringVar()
        ttk.Entry(info_grid, textvariable=self._project_name_var).grid(
            row=4, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 目标父目录
        ttk.Label(info_grid, text="目标父目录：").grid(row=5, column=0, sticky="w", pady=4)
        target_frame = ttk.Frame(info_grid)
        target_frame.grid(row=5, column=1, sticky="we", padx=(8, 0), pady=4)
        self._target_var = tk.StringVar()
        ttk.Entry(target_frame, textvariable=self._target_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(target_frame, text="浏览…", command=self._browse_target).pack(
            side="right", padx=(8, 0)
        )

        info_grid.columnconfigure(1, weight=1)

        # --- 步骤 3：执行中 ---
        self._step3 = ttk.Frame(self._dialog, padding=16)
        ttk.Label(self._step3, text="正在导入…", style="Heading.TLabel").pack(anchor="w")
        self._import_progress = ttk.Progressbar(
            self._step3, mode="indeterminate", length=400
        )
        self._import_progress.pack(pady=20)
        self._import_status_var = tk.StringVar(value="准备中…")
        ttk.Label(self._step3, textvariable=self._import_status_var).pack()

        # --- 步骤 4：结果 ---
        self._step4 = ttk.Frame(self._dialog, padding=16)
        self._result_label = ttk.Label(self._step4, style="Heading.TLabel")
        self._result_label.pack(anchor="w", pady=(0, 8))
        self._result_detail = tk.Text(
            self._step4, height=10, wrap="word", state="disabled",
            font=("Microsoft YaHei", 9),
        )
        self._result_detail.pack(fill="both", expand=True)

        # --- 导航按钮 ---
        self._nav_frame = ttk.Frame(self._dialog, padding=(16, 0, 16, 16))
        self._nav_frame.pack(fill="x", side="bottom")

        self._back_btn = ttk.Button(self._nav_frame, text="上一步", command=self._go_back)
        self._back_btn.pack(side="left")

        self._next_btn = ttk.Button(self._nav_frame, text="下一步", command=self._go_next)
        self._next_btn.pack(side="right")

        self._cancel_btn = ttk.Button(
            self._nav_frame, text="取消", command=self._cancel
        )
        self._cancel_btn.pack(side="right", padx=(8, 0))

    def _show_step(self) -> None:
        """显示当前步骤。"""
        for step_widget in (self._step0, self._step1, self._step2, self._step3, self._step4):
            step_widget.pack_forget()

        steps = (self._step0, self._step1, self._step2, self._step3, self._step4)
        steps[self._step].pack(fill="both", expand=True)

        # 按钮状态
        self._back_btn.configure(state="normal" if self._step > 0 else "disabled")
        if self._step == 0:
            self._next_btn.configure(text="下一步", state="normal" if self._source_path else "disabled")
        elif self._step == 1:
            self._next_btn.configure(text="下一步", state="normal")
        elif self._step == 2:
            self._next_btn.configure(text="开始导入", state="normal")
        elif self._step == 3:
            self._back_btn.configure(state="disabled")
            self._next_btn.configure(state="disabled")
        elif self._step == 4:
            self._back_btn.configure(state="disabled")
            self._next_btn.configure(text="完成", state="normal")
            self._cancel_btn.configure(text="关闭")

    # --- 步骤 0：选择源文件 ---

    def _browse_source(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="选择源 Word 文档",
            filetypes=[("Word 文档", "*.docx"), ("所有文件", "*.*")],
            parent=self._dialog,
        )
        if path:
            self._source_path = path
            self._source_var.set(path)
            source_name = Path(path).stem
            if not self._doc_name_var.get().strip():
                self._doc_name_var.set(source_name)
            if not self._project_name_var.get().strip():
                self._project_name_var.set(source_name)
            self._next_btn.configure(state="normal")

    # --- 步骤 1：预检 ---

    def _do_preflight(self):
        """后台执行预检，只返回数据，不访问任何 Tk 控件。"""
        from doc_tool.adapters.preflight import preflight
        from doc_tool.domain.errors import DocToolError

        try:
            preview = preflight(self._source_path)
        except DocToolError as exc:
            return (
                False,
                None,
                "预检失败：{0}\n\n建议：{1}".format(
                    exc.user_message, exc.suggested_action
                ),
            )
        except Exception as exc:
            return False, None, "预检失败：{0}".format(str(exc)[:200])

        text = format_preview_summary(preview)
        if not preview.has_heading1:
            text += (
                "\n\n阻断：未检测到 Heading 1 标题样式，无法导入。\n"
                "请在 Word 中为一级标题应用「标题 1」样式后重新导入。"
            )
            return False, preview, text
        return True, preview, text

    def _show_preview_text(self, text: str) -> None:
        self._preview_text.configure(state="normal")
        self._preview_text.delete("1.0", "end")
        self._preview_text.insert("1.0", text)
        self._preview_text.configure(state="disabled")

    # --- 步骤 2：项目信息 ---

    def _validate_project_info(self) -> bool:
        """验证项目信息字段。"""
        self._project_info_error = ""
        doc_type = self._type_var.get()
        if doc_type in ("requirement", "design") and not self._doc_no_var.get().strip():
            self._project_info_error = "需求/详细设计预设必须填写文档编号。"
            return False
        if not self._doc_name_var.get().strip():
            return False
        if doc_type in ("requirement", "design") and not self._doc_version_var.get().strip():
            self._project_info_error = "需求/详细设计预设必须填写文档版本。"
            return False
        if not self._project_name_var.get().strip():
            return False
        if not self._target_var.get().strip():
            return False
        project_name = self._project_name_var.get().strip()
        if (
            project_name in (".", "..")
            or Path(project_name).name != project_name
            or any(c in project_name for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in project_name)
            or project_name.rstrip(" .") != project_name
        ):
            self._project_info_error = "项目目录名包含 Windows 不允许的字符或路径片段。"
            return False
        return True

    def _browse_target(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(
            title="选择目标父目录", mustexist=True, parent=self._dialog
        )
        if path:
            self._target_var.set(path)
            # 自动填充项目名（如果为空）
            if not self._project_name_var.get():
                source_name = Path(self._source_path).stem
                self._project_name_var.set(source_name)

    # --- 步骤 3：执行导入 ---

    def _do_import(self) -> None:
        """执行事务化导入。"""
        self._import_progress.start(15)
        self._import_status_var.set("正在导入…")
        from doc_tool.application.import_project import ImportRequest, import_first_time

        target_root = str(Path(self._target_var.get()) / self._project_name_var.get())
        request = ImportRequest(
            source_docx=Path(self._source_path),
            target_project_root=Path(target_root),
            document_type=self._type_var.get(),
            document_no=self._doc_no_var.get().strip(),
            document_name=self._doc_name_var.get().strip(),
            document_version=self._doc_version_var.get().strip(),
        )
        self._runner.start(
            TaskSpec(name="import", target=import_first_time, args=(request,)),
            on_done=lambda result: self._show_import_result(result, target_root),
        )
        self._schedule_poll()

    def _show_import_result(self, result, target_root: str) -> None:
        """显示导入结果。"""
        self._import_progress.stop()

        if result is None:
            self._result_label.configure(text="✗ 导入异常终止")
            self._set_result_text("导入线程未返回结果，请查看应用日志。")
        elif result.success:
            self._result = target_root
            self._result_label.configure(text="✓ 导入成功")
            detail_lines = [
                "项目目录：{0}".format(target_root),
                "源文件指纹：{0}".format(
                    (result.source_sha256 or "")[:12] + "…"
                ),
                "",
                "阶段事件：",
            ]
            for event in result.events:
                detail_lines.append("  {0}: {1}".format(event.stage, event.status))
            self._set_result_text("\n".join(detail_lines))
        else:
            self._result_label.configure(
                text="⊘ 导入已取消" if result.error_code == "E5003" else "✗ 导入失败"
            )
            error_lines = [
                "错误码：{0}".format(result.error_code or "未知"),
                "",
                "阶段事件：",
            ]
            for event in result.events:
                line = "  {0}: {1}".format(event.stage, event.status)
                if event.detail:
                    line += " — {0}".format(event.detail)
                if "errorCode" in event.metrics:
                    line += "（{0}）".format(event.metrics["errorCode"])
                error_lines.append(line)

            if result.diagnostic_log:
                error_lines.append("")
                error_lines.append("诊断日志：{0}".format(result.diagnostic_log))

            self._set_result_text("\n".join(error_lines))

        self._step = 4
        self._show_step()

    def _set_result_text(self, text: str) -> None:
        self._result_detail.configure(state="normal")
        self._result_detail.delete("1.0", "end")
        self._result_detail.insert("1.0", text)
        self._result_detail.configure(state="disabled")

    # --- 导航 ---

    def _go_next(self) -> None:
        if self._step == 0:
            # 进入预检
            self._step = 1
            self._show_step()
            self._next_btn.configure(state="disabled")
            self._dialog.after(100, self._run_preflight)
        elif self._step == 1:
            self._step = 2
            self._show_step()
        elif self._step == 2:
            if not self._validate_project_info():
                from tkinter import messagebox

                messagebox.showwarning(
                    "项目信息无效",
                    self._project_info_error or "请填写所有必填字段。",
                    parent=self._dialog,
                )
                return
            self._step = 3
            self._show_step()
            self._do_import()
        elif self._step == 4:
            self._dialog.destroy()

    def _run_preflight(self) -> None:
        """异步执行预检。"""
        self._back_btn.configure(state="disabled")
        started = self._runner.start(
            TaskSpec(name="preflight", target=self._do_preflight),
            on_done=self._after_preflight,
        )
        if not started:
            self._show_preview_text("预检任务仍在运行，请稍候。")
            return
        self._schedule_poll()

    def _after_preflight(self, response) -> None:
        if response is None:
            ok, preview, text = False, None, "预检异常终止。"
        else:
            ok, preview, text = response
        self._preview = preview
        self._show_preview_text(text)
        if ok and preview is not None and preview.document_type_suggestion is not None:
            suggestion = preview.document_type_suggestion
            if suggestion.confidence == "high":
                self._type_var.set(suggestion.document_type)
        if self._step == 1:
            self._back_btn.configure(state="normal")
        if ok:
            self._next_btn.configure(state="normal")
        else:
            # 允许返回修改
            self._next_btn.configure(state="disabled")

    def _schedule_poll(self) -> None:
        if self._poll_scheduled:
            return
        self._poll_scheduled = True
        self._dialog.after(POLL_INTERVAL_MS, self._poll_runner)

    def _poll_runner(self) -> None:
        self._poll_scheduled = False
        self._runner.poll()
        if self._runner.is_running:
            self._schedule_poll()

    def _go_back(self) -> None:
        if self._runner.is_running:
            return
        if self._step > 0 and self._step != 3:  # 执行中不可返回
            self._step -= 1
            self._show_step()

    def _cancel(self) -> None:
        if self._step == 3 and self._runner.is_running:
            self._runner.cancel()
            self._import_status_var.set("正在安全取消…")
            self._cancel_btn.configure(state="disabled")
            return
        self._result = None
        self._dialog.destroy()
