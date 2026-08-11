# -*- coding: utf-8 -*-
"""高 DPI 适配与 ttk 样式。

任务 6.1：Windows 高 DPI 基础适配。
"""

from __future__ import annotations

import os
import sys

from doc_tool.resources import resource_path


# Restrained visual hierarchy shared by the main window and dialogs.  Spacing is
# expressed in Tk logical pixels so Windows display scaling can apply normally.
FONT_FAMILY = "Microsoft YaHei UI"
FONT_BODY = (FONT_FAMILY, 9)
FONT_SMALL = (FONT_FAMILY, 8)
FONT_HEADING = (FONT_FAMILY, 12, "bold")
FONT_TITLE = (FONT_FAMILY, 17, "bold")
FONT_MONO = ("Consolas", 9)
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 20

# Colours are auxiliary only; every semantic style is paired with explicit text.
SEMANTIC_COLORS = {
    "neutral": "#4b5563",
    "success": "#176b3a",
    "warning": "#8a5a00",
    "failure": "#a12622",
}


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

    # Native themes remain the first choice.  The explicit styles below only
    # add hierarchy and conservative foreground colours that remain readable
    # when a theme ignores custom backgrounds.
    try:
        style.configure(".", font=FONT_BODY)
        style.configure("Heading.TLabel", font=FONT_HEADING)
        style.configure("Title.TLabel", font=FONT_TITLE)
        style.configure(
            "Status.TLabel", font=FONT_SMALL, foreground=SEMANTIC_COLORS["neutral"]
        )
        style.configure("Primary.TButton", font=(FONT_FAMILY, 9, "bold"), padding=(16, 8))
        style.configure("Secondary.TButton", padding=(12, 6))
        style.configure("Compact.TButton", padding=(8, 3))
        for tone, color in SEMANTIC_COLORS.items():
            style.configure(
                "{0}.TLabel".format(tone.capitalize()),
                foreground=color,
            )
        style.configure(
            "Result.TLabelframe",
            padding=SPACE_MD,
        )
        style.configure(
            "Result.TLabelframe.Label",
            font=(FONT_FAMILY, 10, "bold"),
        )
    except tk.TclError:
        # Some native/high-contrast themes reject individual options.  Widgets
        # still retain their explicit Chinese status text and default theme.
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
