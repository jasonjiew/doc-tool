# -*- coding: utf-8 -*-
"""关于/环境诊断对话框。

任务 6.9：显示版本、提交、模式、Windows 和 Word 可用性。
"""

from __future__ import annotations


def format_diagnostic_info(info: dict, report) -> str:
    """生成可复制的纯文本环境诊断信息。"""
    labels = [
        ("应用版本", "appVersion"),
        ("提交标识", "commit"),
        ("项目模式版本", "projectSchemaVersion"),
        ("Python", "python"),
        ("平台", "platform"),
        ("架构", "machine"),
    ]
    lines = ["康尚文档工具 - 环境诊断"]
    lines.extend(
        "{0}：{1}".format(label, info.get(key, "—"))
        for label, key in labels
    )
    lines.extend([
        "Microsoft Word：{0}".format(
            "可用" + (
                "（版本 {0}）".format(report.version)
                if report.available and report.version
                else ""
            )
            if report.available
            else "未检测到"
        ),
        "pywin32：{0}".format(
            "已安装" if report.pywin32_available else "未安装"
        ),
        "交互式会话：{0}".format(
            "是" if report.interactive_session else "否"
        ),
    ])
    if report.reasons:
        lines.append("原因：")
        lines.extend("- {0}".format(reason) for reason in report.reasons)
    return "\n".join(lines)


def show_about_dialog(parent) -> None:
    """显示关于/环境诊断对话框。"""
    import tkinter as tk
    from tkinter import ttk

    from doc_tool.domain.version import (
        APP_VERSION,
        PROJECT_SCHEMA_VERSION,
        get_build_info,
    )

    dialog = tk.Toplevel(parent)
    dialog.title("关于 / 环境诊断")
    dialog.geometry("520x460")
    dialog.minsize(420, 380)
    dialog.transient(parent)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="康尚文档工具", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="版本 {0}".format(APP_VERSION)).pack(anchor="w", pady=(0, 12))

    # 环境诊断信息
    info = get_build_info()

    info_frame = ttk.LabelFrame(frame, text="环境诊断", padding=8)
    info_frame.pack(fill="x", pady=4)

    row = 0
    for label, key in [
        ("应用版本", "appVersion"),
        ("提交标识", "commit"),
        ("项目模式版本", "projectSchemaVersion"),
        ("Python", "python"),
        ("平台", "platform"),
        ("架构", "machine"),
    ]:
        ttk.Label(info_frame, text="{0}：".format(label)).grid(
            row=row, column=0, sticky="w", pady=2
        )
        ttk.Label(info_frame, text=str(info.get(key, "—"))).grid(
            row=row, column=1, sticky="w", padx=(8, 0), pady=2
        )
        row += 1

    # Word 可用性（任务 7.1：使用综合检查，含交互式会话与 DispatchEx 探测）
    word_frame = ttk.LabelFrame(frame, text="Microsoft Word", padding=8)
    word_frame.pack(fill="x", pady=4)

    # 对话框内的检查默认不实际启动 Word，避免每次打开关于对话框都弹一次进程
    from doc_tool.application.word_check import check_word_available

    report = check_word_available(dispatch_check=False)

    word_text = "可用"
    word_color = "green"
    if report.available:
        # 静态探测通常拿不到 Word 真实版本；非空时才附带，避免「可用（版本 ）」。
        if report.version:
            word_text = "可用（版本 {0}）".format(report.version)
    else:
        word_text = "未检测到"
        word_color = "red"
    ttk.Label(word_frame, text=word_text, foreground=word_color).pack(anchor="w")

    # 子项详情
    detail_frame = ttk.Frame(word_frame)
    detail_frame.pack(fill="x", pady=(4, 0))
    for label, value in [
        ("pywin32", "已安装" if report.pywin32_available else "未安装"),
        ("交互式会话", "是" if report.interactive_session else "否"),
    ]:
        row = ttk.Frame(detail_frame)
        row.pack(fill="x")
        ttk.Label(row, text="  • {0}：".format(label), foreground="gray").pack(side="left")
        ttk.Label(row, text=value, foreground="gray").pack(side="left")

    if not report.available:
        ttk.Label(
            word_frame,
            text=(
                "正式合并需要本机安装 Microsoft Word 并在交互式会话中运行；\n"
                "可使用「诊断构建」进行无 Word 测试。"
            ),
            foreground="gray",
            wraplength=450,
            justify="left",
        ).pack(fill="x", anchor="w", pady=(4, 0))
        if report.reasons:
            for reason in report.reasons:
                ttk.Label(
                    word_frame,
                    text="  • {0}".format(reason),
                    foreground="gray",
                    wraplength=450,
                    justify="left",
                ).pack(fill="x", anchor="w")

    # 操作按钮
    button_frame = ttk.Frame(frame)
    button_frame.pack(fill="x", pady=(12, 0))
    copied_var = tk.StringVar(value="")
    ttk.Label(
        button_frame,
        textvariable=copied_var,
        foreground="green",
    ).pack(side="left")

    diagnostic_text = format_diagnostic_info(info, report)

    def copy_diagnostics() -> None:
        try:
            dialog.clipboard_clear()
            dialog.clipboard_append(diagnostic_text)
            dialog.update_idletasks()
            copied_var.set("已复制诊断信息")
            dialog.after(2000, lambda: copied_var.set(""))
        except Exception:
            copied_var.set("复制失败")

    ttk.Button(
        button_frame,
        text="复制诊断信息",
        command=copy_diagnostics,
    ).pack(side="left")
    close_btn = ttk.Button(
        button_frame, text="关闭", command=dialog.destroy
    )
    close_btn.pack(side="right")

    def copy_shortcut(_event=None):
        copy_diagnostics()
        return "break"

    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    dialog.bind("<Return>", lambda _event: dialog.destroy())
    dialog.bind("<Control-c>", copy_shortcut)
    close_btn.focus_set()
