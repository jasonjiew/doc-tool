# -*- coding: utf-8 -*-
"""术语/一致性检查面板。

运行重复标题、术语大小写、TODO/TBD 三类检查，结果表格展示并支持点击
定位。术语清单在面板内直接增删，保存到 ``.state/terms.json`` 后立即
重跑相关检查。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from doc_tool.application.content.lint import ContentLinter, TermStore

_RULE_LABELS = {
    "duplicate_title": "重复标题",
    "term_case": "术语大小写",
    "todo_residual": "待办残留",
}


class LintPanel(ttk.Frame):
    """一致性检查面板。

    ``linter``：``ContentLinter``；``terms``：``TermStore``；
    ``on_open(rel_path, line_no)``：结果项点击定位。
    """

    def __init__(
        self,
        master,
        linter: ContentLinter,
        terms: TermStore,
        *,
        on_open: Optional[Callable[[str, int], None]] = None,
        writable: bool = True,
    ) -> None:
        super().__init__(master)
        self._linter = linter
        self._terms = terms
        self._on_open = on_open
        self._writable = writable

        self._build_terms()
        self._build_results()

    # --- 构建 ---

    def _build_terms(self) -> None:
        terms_frame = ttk.LabelFrame(self, text="术语清单（规范拼写）", padding=6)
        terms_frame.pack(fill="x", pady=(0, 4))

        self._term_listbox = tk.Listbox(terms_frame, height=4)
        self._term_listbox.pack(side="left", fill="x", expand=True, padx=(0, 6))

        side = ttk.Frame(terms_frame)
        side.pack(side="left", fill="y")
        self._term_entry = ttk.Entry(side, width=18)
        self._term_entry.pack(fill="x")
        add_btn = ttk.Button(
            side, text="添加", command=self.add_term, style="Compact.TButton"
        )
        add_btn.pack(fill="x", pady=(2, 0))
        self._remove_btn = ttk.Button(
            side, text="删除所选", command=self.remove_term, style="Compact.TButton"
        )
        self._remove_btn.pack(fill="x", pady=(2, 0))

        run_row = ttk.Frame(terms_frame)
        run_row.pack(side="left", padx=(8, 0))
        self._run_btn = ttk.Button(
            run_row, text="运行检查", command=self.run_check, style="Primary.TButton"
        )
        self._run_btn.pack()
        self._status_var = tk.StringVar(value="")
        ttk.Label(
            run_row, textvariable=self._status_var, style="Status.TLabel"
        ).pack(pady=(4, 0))

        self._load_terms()

    def _build_results(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        columns = ("file", "line", "rule", "message")
        self._tree = ttk.Treeview(frame, columns=columns, show="headings")
        self._tree.heading("file", text="文件")
        self._tree.heading("line", text="行")
        self._tree.heading("rule", text="类型")
        self._tree.heading("message", text="说明")
        self._tree.column("file", width=240, anchor="w")
        self._tree.column("line", width=48, anchor="e", stretch=False)
        self._tree.column("rule", width=90, anchor="w", stretch=False)
        self._tree.column("message", width=400, anchor="w")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

    # --- 行为 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._remove_btn.configure(state="normal" if writable else "disabled")

    def run_check(self) -> None:
        """运行全部检查并展示结果。"""
        terms = self._current_terms()
        self._terms.save(terms)
        issues = self._linter.check_all(terms)
        self._tree.delete(*self._tree.get_children())
        for i, issue in enumerate(issues):
            self._tree.insert(
                "",
                "end",
                iid="lint-{0}".format(i),
                values=(
                    issue.rel_path,
                    issue.line_no,
                    _RULE_LABELS.get(issue.rule, issue.rule),
                    issue.message,
                ),
            )
        if not issues:
            self._status_var.set("检查通过，未发现问题")
        else:
            self._status_var.set("共 {0} 项".format(len(issues)))

    def add_term(self) -> None:
        value = self._term_entry.get().strip()
        if not value:
            return
        terms = self._current_terms()
        if value not in terms:
            terms.append(value)
        self._term_entry.delete(0, "end")
        self._terms.save(terms)
        self._render_terms(terms)
        self.run_check()

    def remove_term(self) -> None:
        selection = self._term_listbox.curselection()
        if not selection:
            return
        terms = self._current_terms()
        index = selection[0]
        if 0 <= index < len(terms):
            terms.pop(index)
            self._terms.save(terms)
            self._render_terms(terms)
            self.run_check()

    # --- 内部 ---

    def _load_terms(self) -> None:
        self._render_terms(self._terms.load())

    def _current_terms(self) -> List[str]:
        return list(self._term_listbox.get(0, "end"))

    def _render_terms(self, terms: List[str]) -> None:
        self._term_listbox.delete(0, "end")
        for term in terms:
            self._term_listbox.insert("end", term)

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
