# -*- coding: utf-8 -*-
"""全文搜索面板。

输入去抖自动搜索；结果以"文件 + 行号 + 上下文预览"表格展示，点击定位。
支持正则/大小写/整词开关与文档类型范围过滤；超阈值显示"显示更多"。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from doc_tool.application.content.search import (
    DEFAULT_LIMIT,
    SearchOptions,
    SearchResult,
    SearchService,
)
from doc_tool.ui.styles import FONT_MONO

# 文档类型过滤下拉：显示名 -> 过滤值。
_TYPE_FILTERS = (
    ("全部", None),
    ("需求文档", "requirement"),
    ("详细设计文档", "design"),
    ("通用大文档", "general"),
)

_DEBOUNCE_MS = 350


class SearchPanel(ttk.Frame):
    """全文搜索面板。

    ``on_open(rel_path, line_no)``：结果项被点击时回调，用于在内容面板
    打开文件并定位到命中行。
    ``writable`` 不影响搜索（搜索是只读操作），保留参数以便界面统一。
    """

    def __init__(
        self,
        master,
        service: SearchService,
        *,
        on_open: Optional[Callable[[str, int], None]] = None,
        writable: bool = True,
    ) -> None:
        super().__init__(master)
        self._service = service
        self._on_open = on_open
        self._writable = writable
        self._debounce_job: Optional[str] = None
        self._limit = DEFAULT_LIMIT
        self._last_result: Optional[SearchResult] = None
        from doc_tool.ui.task_bridge import TaskRunner

        self._runner = TaskRunner()

        self._build_controls()
        self._build_results()

    # --- 构建 ---

    def _build_controls(self) -> None:
        controls = ttk.Frame(self, padding=(0, 0, 0, 4))
        controls.pack(fill="x")

        self._query_var = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self._query_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.search_now())
        entry.bind("<KeyRelease>", self._schedule)
        self._query_entry = entry

        self._search_btn = ttk.Button(
            controls, text="搜索", command=self.search_now, style="Compact.TButton"
        )
        self._search_btn.pack(side="left", padx=(4, 0))

        # 文档类型过滤
        self._type_var = tk.StringVar(value=_TYPE_FILTERS[0][0])
        type_box = ttk.Combobox(
            controls,
            textvariable=self._type_var,
            values=[label for label, _ in _TYPE_FILTERS],
            width=10,
            state="readonly",
        )
        type_box.pack(side="left", padx=(6, 0))
        type_box.bind("<<ComboboxSelected>>", lambda _e: self.search_now())

        # 选项开关
        self._regex_var = tk.BooleanVar(value=False)
        self._case_var = tk.BooleanVar(value=False)
        self._word_var = tk.BooleanVar(value=False)
        for var, label in (
            (self._regex_var, "正则"),
            (self._case_var, "区分大小写"),
            (self._word_var, "整词"),
        ):
            cb = ttk.Checkbutton(
                controls, text=label, variable=var, command=self.search_now
            )
            cb.pack(side="left", padx=(6, 0))

        self._summary_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self._summary_var).pack(
            side="right", padx=(8, 0)
        )

    def _build_results(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)

        columns = ("rel_path", "line", "preview")
        self._tree = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode="browse"
        )
        self._tree.heading("rel_path", text="文件")
        self._tree.heading("line", text="行")
        self._tree.heading("preview", text="内容预览")
        self._tree.column("rel_path", width=300, anchor="w")
        self._tree.column("line", width=48, anchor="e", stretch=False)
        self._tree.column("preview", width=420, anchor="w")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._more_var = tk.StringVar(value="")
        self._more_btn = ttk.Button(
            frame,
            textvariable=self._more_var,
            command=self._show_more,
            style="Compact.TButton",
        )
        # 放底部工具栏而非结果区内
        self._more_btn.pack(side="bottom", pady=(2, 0))
        self._more_var.set("")

    # --- 行为 ---

    def _schedule(self, _event=None) -> None:
        if self._debounce_job is not None:
            try:
                self.after_cancel(self._debounce_job)
            except Exception:
                pass
        self._debounce_job = self.after(_DEBOUNCE_MS, self.search_now)

    def search_now(self) -> None:
        if self._debounce_job is not None:
            try:
                self.after_cancel(self._debounce_job)
            except Exception:
                pass
            self._debounce_job = None
        options = self._current_options()
        if not options.query.strip():
            self._render(SearchResult(query=""))
            return
        # UI 线程预校验查询模式（便宜），避免后台任务报泛化失败
        from doc_tool.application.content.search import compile_pattern

        try:
            compile_pattern(
                options.query,
                regex=options.regex,
                case_sensitive=options.case_sensitive,
                whole_word=options.whole_word,
            )
        except ValueError as exc:
            self._summary_var.set("查询无效：{0}".format(exc))
            return
        self._summary_var.set("搜索中…")
        # 取消上一次仍在运行的搜索，再启动新搜索
        if self._runner.is_running:
            self._runner.cancel()
        from doc_tool.application.content.search import run_search
        from doc_tool.ui.task_bridge import TaskSpec

        self._runner.start(
            TaskSpec(name="search", target=run_search, kwargs={
                "service": self._service,
                "options": options,
            }),
            on_done=lambda result: self._on_search_done(result),
        )
        self._poll()

    def _poll(self) -> None:
        """UI 线程轮询后台搜索事件队列。"""
        if not self._runner.is_running:
            return
        self._runner.poll()
        if self._runner.is_running:
            try:
                self.after(100, self._poll)
            except Exception:
                pass

    def _on_search_done(self, result) -> None:
        if result is None:
            if self._runner.is_cancelled:
                self._summary_var.set("搜索被取消")
            else:
                self._summary_var.set("搜索失败，请检查查询条件")
            return
        self._last_result = result
        self._render(result)

    def _current_options(self) -> SearchOptions:
        selected_label = self._type_var.get()
        doc_types = next(
            (value for label, value in _TYPE_FILTERS if label == selected_label),
            None,
        )
        return SearchOptions(
            query=self._query_var.get(),
            regex=self._regex_var.get(),
            case_sensitive=self._case_var.get(),
            whole_word=self._word_var.get(),
            document_types=([doc_types] if doc_types else None),
            limit=self._limit,
        )

    def _render(self, result: SearchResult) -> None:
        self._tree.delete(*self._tree.get_children())
        for hit in result.hits:
            preview = hit.text.strip()
            if len(preview) > 200:
                preview = preview[:200] + "…"
            self._tree.insert(
                "",
                "end",
                iid="hit-{0}".format(len(self._tree.get_children())),
                values=(hit.rel_path, hit.line_no, preview),
            )
        if result.total == 0:
            summary = "无匹配内容" if result.query else "请输入关键字"
        elif result.truncated:
            summary = "共 {0} 处（{1} 个文件），显示前 {2} 条".format(
                result.total, result.file_count, len(result.hits)
            )
        else:
            summary = "共 {0} 处（{1} 个文件）".format(
                result.total, result.file_count
            )
        self._summary_var.set(summary)
        self._more_var.set("显示更多…" if result.truncated else "")

    def _show_more(self) -> None:
        self._limit += DEFAULT_LIMIT
        self.search_now()

    def _on_select(self, _event=None) -> None:
        selection = self._tree.selection()
        if not selection or self._on_open is None:
            return
        values = self._tree.item(selection[0], "values")
        if not values:
            return
        try:
            line_no = int(values[1])
        except (TypeError, ValueError):
            line_no = 1
        self._on_open(values[0], line_no)

    # --- 外部控制 ---

    def set_writable(self, writable: bool) -> None:
        """搜索是只读操作，始终可用；保留接口以便状态统一。"""
        self._writable = writable

    def focus_query(self) -> None:
        """聚焦搜索输入框并选中已有文本（Ctrl+F 定位用）。"""
        try:
            self._query_entry.focus_set()
            self._query_entry.select_range(0, "end")
        except Exception:
            pass
