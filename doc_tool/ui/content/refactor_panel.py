# -*- coding: utf-8 -*-
"""章节重命名/重编号联动面板。

选择文件 + 输入新文件名 -> "预览影响"生成 dry-run 清单（文件内位置 ×
旧→新）-> 确认后批量更新引用并重命名文件。写回经 ``ContentWriter``
备份与改动清单，可回滚；完成后回调 ``on_applied`` 触发校验。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional

from doc_tool.application.content.refactor import EditOp, RefactorService, RenamePlan


class RefactorPanel(ttk.Frame):
    """重命名/重编号联动面板。

    ``writer``：``ContentWriter``；``on_applied``：执行成功后回调。
    ``set_target(rel_path)``：由章节树/编辑器选中文件预填。
    """

    def __init__(
        self,
        master,
        service: RefactorService,
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
        self._plan: Optional[RenamePlan] = None
        self._all_files: List[str] = []

        self._build_inputs()
        self._build_results()

    # --- 构建 ---

    def _build_inputs(self) -> None:
        inputs = ttk.LabelFrame(self, text="重命名 / 重编号", padding=8)
        inputs.pack(fill="x")

        row1 = ttk.Frame(inputs)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="章节文件：").pack(side="left")
        self._file_var = tk.StringVar()
        self._file_box = ttk.Combobox(
            row1,
            textvariable=self._file_var,
            width=60,
        )
        self._file_box.pack(side="left", fill="x", expand=True)

        row2 = ttk.Frame(inputs)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="新文件名：").pack(side="left")
        self._new_name_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self._new_name_var).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        self._preview_btn = ttk.Button(
            row2, text="预览影响", command=self.preview, style="Compact.TButton"
        )
        self._preview_btn.pack(side="left")
        self._status_var = tk.StringVar(value="")
        ttk.Label(
            row2, textvariable=self._status_var, style="Status.TLabel"
        ).pack(side="right", padx=(8, 0))

    def _build_results(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        columns = ("file", "line", "old", "new")
        self._tree = ttk.Treeview(frame, columns=columns, show="headings")
        self._tree.heading("file", text="文件")
        self._tree.heading("line", text="行")
        self._tree.heading("old", text="旧文本")
        self._tree.heading("new", text="新文本")
        self._tree.column("file", width=220, anchor="w")
        self._tree.column("line", width=48, anchor="e", stretch=False)
        self._tree.column("old", width=220, anchor="w")
        self._tree.column("new", width=220, anchor="w")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(4, 0))
        self._apply_btn = ttk.Button(
            actions,
            text="确认并执行",
            command=self.apply_plan,
            state="disabled",
            style="Primary.TButton",
        )
        self._apply_btn.pack(side="left", padx=4)
        self._rollback_btn = ttk.Button(
            actions, text="回滚本次联动", command=self.rollback, style="Compact.TButton"
        )
        self._rollback_btn.pack(side="left", padx=4)

    # --- 数据 ---

    def set_files(self, files: List[str]) -> None:
        """设置可选择的文件列表。"""
        self._all_files = list(files)
        self._file_box.configure(values=self._all_files)

    def set_target(self, rel_path: str) -> None:
        """预填目标文件（由章节树/编辑器选中触发）。"""
        self._file_var.set(rel_path)
        self._file_box.configure(values=self._all_files)
        from pathlib import Path

        self._new_name_var.set(Path(rel_path).name)
        self.clear()

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    # --- 行为 ---

    def preview(self) -> None:
        """计算并展示 dry-run 清单。"""
        rel_path = self._file_var.get().strip()
        new_name = self._new_name_var.get().strip()
        if not rel_path or not new_name:
            self._status_var.set("请选择文件并填写新文件名")
            return
        try:
            plan = self._service.compute_rename_plan(rel_path, new_name)
        except Exception as exc:  # noqa: BLE001
            self._status_var.set("计算失败：{0}".format(exc))
            return
        if plan is None:
            self._status_var.set("目标文件不在内容索引中")
            return
        self._plan = plan
        self._tree.delete(*self._tree.get_children())
        for i, edit in enumerate(plan.edits):
            self._tree.insert(
                "",
                "end",
                iid="r-{0}".format(i),
                values=(edit.rel_path, edit.line_no, edit.old_substr, edit.new_substr),
            )
        if plan.total == 0:
            self._status_var.set("无受影响引用（仅重命名文件本身）")
        else:
            self._status_var.set(
                "受影响引用 {0} 处（{1} 个文件）+ 重命名文件本身".format(
                    plan.total, len(plan.affected_files)
                )
            )
        self._update_action_state()

    def apply_plan(self) -> None:
        """确认 dry-run 清单并执行。"""
        if self._plan is None:
            return
        plan = self._plan
        confirmed = messagebox.askyesno(
            "确认执行",
            "将更新 {0} 处引用，并把文件重命名为：\n{1}\n"
            "每文件保留 .md.bak 备份，可回滚。确认执行？".format(
                plan.total, plan.new_rel_path
            ),
        )
        if not confirmed:
            return
        results = self._service.apply_rename_plan(plan, self._writer)
        self._status_var.set(
            "已执行：{0} 处引用更新 + 文件重命名".format(plan.total)
        )
        self._plan = None
        self._tree.delete(*self._tree.get_children())
        if self._on_applied is not None:
            self._on_applied()
        self._update_action_state()

    def rollback(self) -> None:
        """回滚最近一次联动（按改动清单）。"""
        failures = self._writer.manifest.rollback()
        if failures:
            self._status_var.set("回滚失败：{0}".format(", ".join(failures)))
        else:
            self._status_var.set("已回滚本次联动")
            if self._on_applied is not None:
                self._on_applied()

    def clear(self) -> None:
        self._plan = None
        self._tree.delete(*self._tree.get_children())
        self._update_action_state()

    def _update_action_state(self) -> None:
        self._apply_btn.configure(
            state="normal" if (self._writable and self._plan is not None) else "disabled"
        )
        self._rollback_btn.configure(
            state="normal" if self._writable else "disabled"
        )
