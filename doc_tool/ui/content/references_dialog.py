# -*- coding: utf-8 -*-
"""引用分析对话框：当前文件被引用情况 + 全项目悬空引用。

读操作；结果行可点击，经 ``on_open(rel_path, line_no)`` 在内容面板定位。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from doc_tool.domain.content_index import (
    ContentIndex,
    REF_ANCHOR,
    REF_IMAGE,
    REF_LINK,
    REF_SECTION,
)

_KIND_LABELS = {
    REF_LINK: "链接",
    REF_SECTION: "章节号",
    REF_ANCHOR: "锚点",
    REF_IMAGE: "图片",
}


def _kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def _make_table(master) -> ttk.Treeview:
    columns = ("file", "line", "kind", "detail")
    tree = ttk.Treeview(master, columns=columns, show="headings")
    tree.heading("file", text="文件")
    tree.heading("line", text="行")
    tree.heading("kind", text="类型")
    tree.heading("detail", text="引用/目标")
    tree.column("file", width=280, anchor="w")
    tree.column("line", width=48, anchor="e", stretch=False)
    tree.column("kind", width=70, anchor="w", stretch=False)
    tree.column("detail", width=320, anchor="w")
    ysb = ttk.Scrollbar(master, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ysb.set)
    tree.pack(side="left", fill="both", expand=True)
    ysb.pack(side="right", fill="y")
    return tree


def show_references_dialog(
    root,
    index: ContentIndex,
    *,
    current_file: Optional[str] = None,
    on_open: Optional[Callable[[str, int], None]] = None,
) -> None:
    """弹出引用分析对话框。"""
    dialog = tk.Toplevel(root)
    dialog.title("引用分析")
    dialog.geometry("720x520")
    dialog.transient(root)
    dialog.grab_set()

    def open_from(tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if not selection or on_open is None:
            return
        values = tree.item(selection[0], "values")
        if not values:
            return
        try:
            line_no = int(values[1])
        except (TypeError, ValueError):
            line_no = 1
        dialog.destroy()
        on_open(values[0], line_no)

    # 反向引用
    if current_file:
        ttk.Label(
            dialog, text="引用当前文件：{0}".format(current_file),
            style="Heading.TLabel",
        ).pack(anchor="w", pady=(4, 2), padx=6)
        reverse_frame = ttk.Frame(dialog)
        reverse_frame.pack(fill="x", padx=6)
        reverse_tree = _make_table(reverse_frame)
        count = 0
        for source, refs in index.references.items():
            for ref in refs:
                if ref.target_rel_path == current_file:
                    reverse_tree.insert(
                        "",
                        "end",
                        values=(
                            source,
                            ref.source_line,
                            _kind_label(ref.kind),
                            "{0} → {1}".format(ref.target, ref.source_text[:40]),
                        ),
                    )
                    count += 1
        if count == 0:
            ttk.Label(
                reverse_frame,
                text="（未被其他文件引用）",
                style="Status.TLabel",
            ).pack(anchor="w", pady=4)
        reverse_tree.bind("<<TreeviewSelect>>", lambda _e: open_from(reverse_tree))
    else:
        ttk.Label(
            dialog, text="（未打开文件，仅显示全项目悬空引用）",
            style="Status.TLabel",
        ).pack(anchor="w", pady=(4, 2), padx=6)

    # 悬空引用
    ttk.Label(
        dialog, text="全项目悬空引用", style="Heading.TLabel"
    ).pack(anchor="w", pady=(8, 2), padx=6)
    dangling_frame = ttk.Frame(dialog)
    dangling_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
    dangling_tree = _make_table(dangling_frame)
    dangling = [
        (ref, source)
        for source, refs in index.references.items()
        for ref in refs
        if ref.dangling
    ]
    if not dangling:
        ttk.Label(
            dangling_frame, text="（未发现悬空引用）", style="Status.TLabel"
        ).pack(anchor="w", pady=4)
    for ref, source in dangling:
        kind = "悬空[{0}]".format(
            "确定" if ref.dangling_kind == "confirmed" else "疑似"
        )
        dangling_tree.insert(
            "",
            "end",
            values=(source, ref.source_line, kind, ref.target),
        )
    dangling_tree.bind("<<TreeviewSelect>>", lambda _e: open_from(dangling_tree))

    ttk.Button(
        dialog, text="关闭", command=dialog.destroy, style="Compact.TButton"
    ).pack(side="bottom", pady=6)
    dialog.wait_window()
