# -*- coding: utf-8 -*-
"""章节树导航面板。

左侧按 `第X章 → X.Y → X.Y.Z` 渲染目录树，节点对应 contentRoot 下文件。
点击文件节点通过 ``on_open`` 回调打开内容面板；``select_file`` 供搜索/
引用结果定位时同步选中并展开父级。

工具栏提供"展开全部 / 折叠全部 / 刷新"；右键菜单提供"打开 / 复制相对路径"。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from doc_tool.application.content.tree import TreeItem


class ChapterTree(ttk.Frame):
    """章节树面板。

    ``on_open(rel_path)``：文件节点被点击/打开时回调。
    ``on_refresh()``：点击"刷新"时回调（重建索引并重绘树）。
    ``writable``：可写时显示"重命名/重编号"入口；只读时隐藏写操作。
    """

    def __init__(
        self,
        master,
        *,
        on_open: Optional[Callable[[str], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        writable: bool = True,
    ) -> None:
        super().__init__(master)
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._writable = writable
        self._items: List[TreeItem] = []
        self._by_id = {}
        # 当前已打开的文件；``_on_select`` 在选中文件与当前打开文件相同
        # 时跳过 on_open，避免程序化定位触发的 <<TreeviewSelect>>（延迟事件）
        # 在事件循环中 open_file -> select_file 无限递归导致 UI 挂起。
        self._current: Optional[str] = None

        self._build_toolbar()
        self._build_tree()
        self._build_context_menu()

    # --- 构建 ---

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 2))
        ttk.Button(
            bar,
            text="展开全部",
            command=self.expand_all,
            style="Compact.TButton",
        ).pack(side="left", padx=(0, 2))
        ttk.Button(
            bar,
            text="折叠全部",
            command=self.collapse_all,
            style="Compact.TButton",
        ).pack(side="left", padx=(0, 2))
        self._refresh_btn = ttk.Button(
            bar,
            text="刷新",
            command=self._on_refresh_click,
            style="Compact.TButton",
        )
        self._refresh_btn.pack(side="right")

    def _build_tree(self) -> None:
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(body, show="tree", selectmode="browse")
        ysb = ttk.Scrollbar(body, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<Button-3>", self._on_right_click)

    def _build_context_menu(self) -> None:
        self._context_menu = tk.Menu(self._tree, tearoff=False)
        self._context_menu.add_command(
            label="打开", command=self._ctx_open
        )
        self._context_menu.add_command(
            label="复制相对路径", command=self._ctx_copy_path
        )

    # --- 工具栏行为 ---

    def expand_all(self) -> None:
        """展开全部目录节点。"""
        for item in self._items:
            if not item.is_file:
                try:
                    self._tree.item(item.node_id, open=True)
                except Exception:
                    pass

    def collapse_all(self) -> None:
        """折叠全部目录节点（保留顶层类型节点展开）。"""
        for item in self._items:
            if not item.is_file and item.parent_id is not None:
                try:
                    self._tree.item(item.node_id, open=False)
                except Exception:
                    pass

    def _on_refresh_click(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()

    # --- 右键菜单 ---

    def _on_right_click(self, event) -> None:
        item_id = self._tree.identify_row(event.y)
        if item_id:
            self._tree.selection_set(item_id)
            try:
                self._context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._context_menu.grab_release()

    def _ctx_open(self) -> None:
        rel_path = self._selected_file()
        if rel_path is not None and self._on_open is not None:
            self._on_open(rel_path)

    def _ctx_copy_path(self) -> None:
        rel_path = self._selected_file()
        if rel_path is None:
            return
        try:
            self._tree.clipboard_clear()
            self._tree.clipboard_append(rel_path)
        except Exception:
            pass

    # --- 数据 ---

    def set_items(self, items: List[TreeItem]) -> None:
        """重建树内容（清空后按层级插入）。"""
        self._items = items
        self._by_id = {item.node_id: item for item in items}
        self._tree.delete(*self._tree.get_children())
        for item in items:
            parent = "" if item.parent_id is None else item.parent_id
            self._tree.insert(
                parent,
                "end",
                iid=item.node_id,
                text=item.text,
                open=(not item.is_file and item.parent_id is None),
            )

    def set_writable(self, writable: bool) -> None:
        """切换只读/可写：写操作（重命名）仅在可写时可用。"""
        self._writable = writable

    def is_writable(self) -> bool:
        return self._writable

    # --- 定位联动 ---

    def select_file(self, rel_path: str) -> bool:
        """定位到某文件节点：展开祖先并选中；文件不在树中返回 False。"""
        if rel_path not in self._by_id or not self._by_id[rel_path].is_file:
            return False
        for ancestor in self._ancestor_ids(rel_path):
            if ancestor in self._by_id and ancestor in self._tree.get_children(""):
                try:
                    self._tree.item(ancestor, open=True)
                except Exception:
                    pass
        self._tree.selection_set(rel_path)
        self._tree.see(rel_path)
        return True

    def set_current(self, rel_path: Optional[str]) -> None:
        """记录当前打开的文件，供选中回调去重。"""
        self._current = rel_path

    def _ancestor_ids(self, node_id: str) -> List[str]:
        chain: List[str] = []
        parent = self._tree.parent(node_id)
        while parent:
            chain.append(parent)
            parent = self._tree.parent(parent)
        return list(reversed(chain))

    # --- 事件 ---

    def _selected_file(self) -> Optional[str]:
        selection = self._tree.selection()
        if not selection:
            return None
        item = self._by_id.get(selection[0])
        if item is None or not item.is_file:
            return None
        return item.rel_path

    def _on_select(self, _event=None) -> None:
        rel_path = self._selected_file()
        if (
            rel_path is not None
            and rel_path != self._current
            and self._on_open is not None
        ):
            self._on_open(rel_path)

    def _on_double_click(self, _event=None) -> None:
        rel_path = self._selected_file()
        if (
            rel_path is not None
            and rel_path != self._current
            and self._on_open is not None
        ):
            self._on_open(rel_path)
