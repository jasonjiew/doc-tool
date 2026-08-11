# -*- coding: utf-8 -*-
"""可滚动容器：为工作台提供垂直滚动。

内部 frame 横向拉伸到视口宽度；纵向行为按内容高度自适应：
- 内容较矮时：拉满视口高度，让 ``expand`` 子项填满可用空间。
- 内容较高时：按内容高度滚动，避免窗口过小时内容被裁剪无法触达。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    """垂直可滚动、横向拉伸的容器。

    用法::

        scroll = ScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)
        # 后续子控件都 pack 到 scroll.inner 上
        ttk.Label(scroll.inner, text="...").pack(...)
    """

    def __init__(self, master) -> None:
        super().__init__(master)
        self._canvas = tk.Canvas(self, highlightthickness=0)
        self._vbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vbar.set)
        self._vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self._canvas)
        self._window_id = self._canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self.inner.bind("<Configure>", self._sync_region)
        self._canvas.bind("<Configure>", self._stretch)
        # 光标在画布空白/边缘时滚轮滚动外层（内部控件自带滚动，不做全局接管）
        self._canvas.bind("<MouseWheel>", self._on_wheel)

    def scroll_to_top(self) -> None:
        try:
            self._canvas.yview_moveto(0)
        except Exception:
            pass

    def _sync_region(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _stretch(self, event) -> None:
        self._canvas.itemconfigure(self._window_id, width=event.width)
        content_h = self.inner.winfo_reqheight()
        if content_h < event.height:
            # 内容较矮：拉满视口，让 expand 子项填满
            self._canvas.itemconfigure(self._window_id, height=event.height)
        else:
            self._canvas.itemconfigure(self._window_id, height=content_h)

    def _on_wheel(self, event) -> None:
        try:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass
