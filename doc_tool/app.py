# -*- coding: utf-8 -*-
"""GUI 入口（tkinter/ttk）。

任务 1.1 建立入口骨架；任务 6.1-6.10 实现完整界面。
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("当前环境缺少 tkinter，无法启动图形界面。", file=sys.stderr)
        return 1

    from doc_tool.ui.main_window import MainWindow
    from doc_tool.ui.styles import apply_styles, setup_high_dpi

    setup_high_dpi()
    root = tk.Tk()
    apply_styles(root)

    window = MainWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
