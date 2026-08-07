# -*- coding: utf-8 -*-
"""GUI 入口（tkinter/ttk）。

任务 1.1 建立入口骨架；任务 6.1-6.10 实现完整界面。
首版仅提供占位主窗口与版本信息，避免无显示环境导入失败。
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("当前环境缺少 tkinter，无法启动图形界面。", file=sys.stderr)
        return 1

    from doc_tool import APP_VERSION, get_build_info

    root = tk.Tk()
    root.title("康尚文档工具")
    root.geometry("640x420")
    root.minsize(480, 320)

    info = get_build_info()
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="康尚文档工具", font=("Microsoft YaHei", 16, "bold")).pack(anchor="w", pady=(0, 8))
    ttk.Label(frame, text="版本 {0}（提交 {1}）".format(APP_VERSION, info["commit"])).pack(anchor="w")
    ttk.Label(
        frame,
        text="完整桌面界面将在任务 6.1-6.10 中实现。",
        foreground="gray",
    ).pack(anchor="w", pady=(8, 0))

    ttk.Button(frame, text="退出", command=root.destroy).pack(side="right", pady=(16, 0))

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
