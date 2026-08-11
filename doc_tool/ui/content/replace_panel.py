# -*- coding: utf-8 -*-
"""全局替换面板。

默认逐项确认：命中列表 + 选中行的"前/后"diff 预览，"替换此项/跳过此条"
逐条处理。"全部替换"为显式选项，先汇总再经确认对话框批量写回。

写回经 ``ReplaceService.apply_matches``（每文件 .md.bak + 改动清单），
完成后回调 ``on_applied`` 由主窗口触发校验管线检测悬空引用。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional

from doc_tool.application.content.replace import (
    ReplaceMatch,
    ReplacePreview,
    ReplaceService,
    diff_line,
)
from doc_tool.ui.styles import FONT_MONO

# 文档类型过滤下拉（与搜索面板一致）。
_TYPE_FILTERS = (
    ("全部", None),
    ("需求文档", "requirement"),
    ("详细设计文档", "design"),
    ("通用大文档", "general"),
)


class ReplacePanel(ttk.Frame):
    """全局替换面板。

    ``writer``：``ContentWriter``；``on_applied``：一批替换写回后回调
    （主窗口据此触发校验管线）。
    """

    def __init__(
        self,
        master,
        service: ReplaceService,
        writer,
        *,
        on_applied: Optional[Callable[[], None]] = None,
        writable: bool = True,
    ) -> None:
        super().__init__(master)
        self._service = service
        self._writer = writer
        self._on_applied = on_applied
        self._writable = writable
        self._matches: List[ReplaceMatch] = []
        self._preview: Optional[ReplacePreview] = None

        self._build_inputs()
        self._build_diff()
        self._build_results()

    # --- 构建 ---

    def _build_inputs(self) -> None:
        inputs = ttk.LabelFrame(self, text="查找与替换", padding=8)
        inputs.pack(fill="x")

        row1 = ttk.Frame(inputs)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="查找：").pack(side="left")
        self._find_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self._find_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Label(row1, text="替换为：").pack(side="left", padx=(8, 0))
        self._replace_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self._replace_var).pack(
            side="left", fill="x", expand=True
        )

        row2 = ttk.Frame(inputs)
        row2.pack(fill="x", pady=2)
        self._regex_var = tk.BooleanVar(value=False)
        self._case_var = tk.BooleanVar(value=False)
        self._word_var = tk.BooleanVar(value=False)
        for var, label in (
            (self._regex_var, "正则"),
            (self._case_var, "区分大小写"),
            (self._word_var, "整词"),
        ):
            ttk.Checkbutton(row2, text=label, variable=var).pack(side="left", padx=(0, 6))
        self._type_var = tk.StringVar(value=_TYPE_FILTERS[0][0])
        type_box = ttk.Combobox(
            row2,
            textvariable=self._type_var,
            values=[label for label, _ in _TYPE_FILTERS],
            width=10,
            state="readonly",
        )
        type_box.pack(side="left", padx=(6, 0))
        self._find_btn = ttk.Button(
            row2, text="查找全部", command=self.find_all, style="Compact.TButton"
        )
        self._find_btn.pack(side="right")
        self._status_var = tk.StringVar(value="")
        ttk.Label(
            row2, textvariable=self._status_var, style="Status.TLabel"
        ).pack(side="right", padx=(8, 0))

    def _build_diff(self) -> None:
        diff_frame = ttk.LabelFrame(self, text="选中项差异预览", padding=6)
        diff_frame.pack(fill="x", pady=4)
        self._before_text = _readonly_text(diff_frame, height=2)
        self._after_text = _readonly_text(diff_frame, height=2)
        self._before_text.pack(fill="x")
        ttk.Label(diff_frame, text="↓ 替换为", style="Status.TLabel").pack(
            anchor="w", pady=(2, 0)
        )
        self._after_text.pack(fill="x")

    def _build_results(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        columns = ("file", "line", "before")
        self._tree = ttk.Treeview(frame, columns=columns, show="headings")
        self._tree.heading("file", text="文件")
        self._tree.heading("line", text="行")
        self._tree.heading("before", text="原文")
        self._tree.column("file", width=260, anchor="w")
        self._tree.column("line", width=48, anchor="e", stretch=False)
        self._tree.column("before", width=420, anchor="w")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(4, 0))
        self._replace_one_btn = ttk.Button(
            actions, text="替换此项", command=self.replace_one, style="Primary.TButton"
        )
        self._replace_one_btn.pack(side="left", padx=4)
        self._skip_btn = ttk.Button(
            actions, text="跳过此条", command=self.skip_one, style="Compact.TButton"
        )
        self._skip_btn.pack(side="left", padx=4)
        self._replace_all_btn = ttk.Button(
            actions, text="全部替换…", command=self.replace_all, style="Secondary.TButton"
        )
        self._replace_all_btn.pack(side="left", padx=4)
        self._clear_btn = ttk.Button(
            actions, text="清空", command=self.clear, style="Compact.TButton"
        )
        self._clear_btn.pack(side="right", padx=4)
        self._rollback_btn = ttk.Button(
            actions, text="回滚本次替换", command=self.rollback, style="Compact.TButton"
        )
        self._rollback_btn.pack(side="right", padx=4)

        self._update_action_state()

    # --- 行为 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    def find_all(self) -> None:
        try:
            preview = self._service.build_preview(
                self._find_var.get().strip(),
                regex=self._regex_var.get(),
                case_sensitive=self._case_var.get(),
                whole_word=self._word_var.get(),
                document_types=self._selected_types(),
            )
        except ValueError as exc:
            self._status_var.set("查询无效：{0}".format(exc))
            return
        self._preview = preview
        self._matches = list(preview.matches)
        self._render_matches()
        if preview.total == 0:
            self._status_var.set("无匹配")
        else:
            self._status_var.set(
                "共 {0} 处（{1} 个文件），逐项确认后写回".format(
                    preview.total, preview.file_count
                )
            )

    def replace_one(self) -> None:
        """替换当前选中的命中。"""
        match = self._selected_match()
        if match is None:
            return
        results = self._service.apply_matches(
            [match], self._replace_var.get(), self._writer
        )
        self._matches.remove(match)
        self._render_matches()
        self._status_var.set("已替换 1 处")
        self._after_applied(results)

    def skip_one(self) -> None:
        """跳过当前选中的命中。"""
        match = self._selected_match()
        if match is None:
            return
        self._matches.remove(match)
        self._render_matches()
        self._status_var.set("已跳过 1 处")

    def replace_all(self) -> None:
        """全部替换：先汇总确认，再批量写回。"""
        if not self._matches:
            self._status_var.set("无命中可替换")
            return
        replacement = self._replace_var.get()
        total = len(self._matches)
        files = {m.rel_path for m in self._matches}
        confirmed = messagebox.askyesno(
            "全部替换",
            "将替换 {0} 处命中，涉及 {1} 个文件。\n"
            "每文件会保留 .md.bak 备份，可一键回滚。\n"
            "确认执行？".format(total, len(files)),
        )
        if not confirmed:
            return
        results = self._service.apply_matches(self._matches, replacement, self._writer)
        count = sum(1 for r in results if getattr(r, "written", False))
        self._matches = []
        self._preview = None
        self._render_matches()
        self._status_var.set("已批量替换 {0} 处（{1} 个文件）".format(total, len(files)))
        self._after_applied(results)

    def rollback(self) -> None:
        """回滚本面板最近一次替换写回（按改动清单）。"""
        failures = self._writer.manifest.rollback()
        if failures:
            self._status_var.set("回滚失败：{0}".format(", ".join(failures)))
        else:
            self._status_var.set("已回滚本次替换")
            if self._on_applied is not None:
                self._on_applied()

    def clear(self) -> None:
        self._matches = []
        self._preview = None
        self._render_matches()
        self._status_var.set("")

    # --- 内部 ---

    def _after_applied(self, results) -> None:
        # 触发校验管线（主窗口接线）；同时保留面板内状态。
        if self._on_applied is not None:
            self._on_applied()
        self._update_action_state()

    def _render_matches(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for i, match in enumerate(self._matches):
            preview_text = match.line_text.strip()
            if len(preview_text) > 160:
                preview_text = preview_text[:160] + "…"
            self._tree.insert(
                "",
                "end",
                iid="m-{0}".format(i),
                values=(match.rel_path, match.line_no, preview_text),
            )
        self._update_diff()
        self._update_action_state()

    def _selected_match(self) -> Optional[ReplaceMatch]:
        selection = self._tree.selection()
        if not selection:
            return None
        try:
            index = int(selection[0].split("-", 1)[1])
        except (ValueError, IndexError):
            return None
        if 0 <= index < len(self._matches):
            return self._matches[index]
        return None

    def _on_select(self, _event=None) -> None:
        self._update_diff()

    def _update_diff(self) -> None:
        match = self._selected_match()
        if match is None:
            self._before_text.delete("1.0", "end")
            self._after_text.delete("1.0", "end")
            return
        before, after = diff_line(match, self._replace_var.get())
        self._before_text.configure(state="normal")
        self._before_text.delete("1.0", "end")
        self._before_text.insert("1.0", before)
        self._before_text.configure(state="disabled")
        self._after_text.configure(state="normal")
        self._after_text.delete("1.0", "end")
        self._after_text.insert("1.0", after)
        self._after_text.configure(state="disabled")

    def _update_action_state(self) -> None:
        can_write = self._writable
        has_matches = bool(self._matches)
        self._replace_one_btn.configure(
            state="normal" if (can_write and has_matches) else "disabled"
        )
        self._skip_btn.configure(
            state="normal" if has_matches else "disabled"
        )
        self._replace_all_btn.configure(
            state="normal" if (can_write and has_matches) else "disabled"
        )
        self._rollback_btn.configure(
            state="normal" if can_write else "disabled"
        )

    def _selected_types(self) -> Optional[List[str]]:
        label = self._type_var.get()
        value = next(
            (v for l, v in _TYPE_FILTERS if l == label), None
        )
        return [value] if value else None


def _readonly_text(master, height: int):
    text = tk.Text(
        master,
        height=height,
        wrap="word",
        font=FONT_MONO,
        state="disabled",
    )
    return text
