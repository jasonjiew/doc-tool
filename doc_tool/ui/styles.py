# -*- coding: utf-8 -*-
"""高 DPI 适配与 ttk 样式。

任务 6.1：Windows 高 DPI 基础适配。
"""

from __future__ import annotations

import os
import sys

from doc_tool.resources import resource_path


def setup_high_dpi() -> None:
    """启用 Windows 高 DPI 感知，使界面在 HiDPI 显示器上不模糊。

    在非 Windows 或无 shcore 的环境上为空操作。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        # Windows 10 1703+ 的 per-monitor DPI 感知
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        except (OSError, AttributeError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (OSError, AttributeError):
                pass
    except Exception:
        pass


def apply_styles(root) -> None:
    """应用统一的 ttk 样式（Microsoft YaHei 字体，原生主题）。"""
    import tkinter as tk
    from tkinter import ttk

    style = ttk.Style(root)
    # 优先使用 Windows 原生主题
    available = style.theme_names()
    for theme in ("vista", "winnative", "clam"):
        if theme in available:
            try:
                style.theme_use(theme)
            except tk.TclError:
                pass
            break

    # 统一字体
    default_font = ("Microsoft YaHei", 9)
    heading_font = ("Microsoft YaHei", 12, "bold")
    title_font = ("Microsoft YaHei", 16, "bold")

    try:
        style.configure(".", font=default_font)
        style.configure("Heading.TLabel", font=heading_font)
        style.configure("Title.TLabel", font=title_font)
        style.configure("Status.TLabel", font=("Microsoft YaHei", 8), foreground="gray")
    except tk.TclError:
        pass


def set_window_icon(root) -> bool:
    """为窗口设置应用图标。

    开发态从 ``doc_tool/resources/app.ico`` 读取，打包态从 PyInstaller
    资源目录读取。图标缺失时静默跳过（不阻断启动）。

    返回 True 表示图标已应用，False 表示图标不可用。
    """
    icon = resource_path("app.ico")
    if not os.path.isfile(icon):
        return False
    try:
        root.iconbitmap(default=icon)
        return True
    except Exception:
        # 非窗口环境或 Tk 不接受图标时静默跳过
        return False
