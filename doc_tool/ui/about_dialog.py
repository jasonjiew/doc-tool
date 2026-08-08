# -*- coding: utf-8 -*-
"""关于/环境诊断对话框。

任务 6.9：显示版本、提交、模式、Windows 和 Word 可用性。
"""

from __future__ import annotations


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
    dialog.geometry("480x420")
    dialog.minsize(400, 360)
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

    word_text = "可用（版本 {0}）".format(report.version) if report.available else "未检测到"
    word_color = "green" if report.available else "red"
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
            text="正式合并需要本机安装 Microsoft Word 并在交互式会话中运行；\n可使用「诊断构建」进行无 Word 测试。",
            foreground="gray",
        ).pack(anchor="w", pady=(4, 0))
        if report.reasons:
            for reason in report.reasons:
                ttk.Label(
                    word_frame,
                    text="  • {0}".format(reason),
                    foreground="gray",
                ).pack(anchor="w")

    # 关闭按钮
    ttk.Button(frame, text="关闭", command=dialog.destroy).pack(side="right", pady=(12, 0))
