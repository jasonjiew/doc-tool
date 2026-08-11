# -*- coding: utf-8 -*-
"""内置 .md 编辑器 + 侧边预览。

UTF-8 纯文本编辑，保存经 ``ContentWriter``（备份 + 原子写）。
侧边预览由 ``render_preview_blocks`` 渲染近似结构，编辑去抖刷新，
标注"近似结构预览"。提供"在外部编辑器打开"兜底与外部修改检测。
"""

from __future__ import annotations

import os
import time
from tkinter import ttk
from typing import Callable, Optional

from doc_tool.application.content.preview import (
    preview_summary,
    render_preview_blocks,
)
from doc_tool.ui.styles import FONT_MONO

_PREVIEW_DEBOUNCE_MS = 300


class EditorPanel(ttk.Frame):
    """单文件 .md 编辑器。

    ``writer``：``ContentWriter``（写入安全）。
    ``on_saved(rel_path)``：保存成功后回调（主窗口据此失效索引）。
    ``writable``：只读时禁用编辑与保存。
    """

    def __init__(
        self,
        master,
        writer,
        *,
        on_saved: Optional[Callable[[str], None]] = None,
        writable: bool = True,
    ) -> None:
        super().__init__(master)
        self._writer = writer
        self._on_saved = on_saved
        self._writable = writable
        self._rel_path: Optional[str] = None
        self._mtime: Optional[float] = None
        self._dirty = False
        self._preview_job: Optional[str] = None

        self._build_toolbar()
        self._build_panes()
        self._editor.bind("<Control-s>", lambda _e: self.save())

    # --- 构建 ---

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(0, 0, 0, 4))
        bar.pack(fill="x")

        self._file_var = tk_string_var("未打开文件")
        ttk.Label(bar, textvariable=self._file_var).pack(side="left")

        self._dirty_var = tk_string_var("")
        ttk.Label(
            bar, textvariable=self._dirty_var, style="Warning.TLabel"
        ).pack(side="left", padx=(8, 0))

        self._status_var = tk_string_var("")
        ttk.Label(
            bar, textvariable=self._status_var, style="Status.TLabel"
        ).pack(side="left", padx=(8, 0))

        self._save_btn = ttk.Button(
            bar,
            text="保存 (Ctrl+S)",
            command=self.save,
            state="disabled",
            style="Compact.TButton",
        )
        self._save_btn.pack(side="right", padx=(4, 0))

        self._ext_btn = ttk.Button(
            bar,
            text="在外部编辑器打开",
            command=self.open_external,
            state="disabled",
            style="Compact.TButton",
        )
        self._ext_btn.pack(side="right", padx=(4, 0))

        self._rollback_btn = ttk.Button(
            bar,
            text="回滚上次保存",
            command=self.rollback_last,
            state="disabled",
            style="Compact.TButton",
        )
        self._rollback_btn.pack(side="right", padx=(4, 0))

    def _build_panes(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # 编辑区
        edit_frame = ttk.Frame(paned)
        self._editor = _make_text(edit_frame, readonly=False)
        esb = ttk.Scrollbar(
            edit_frame, orient="vertical", command=self._editor.yview
        )
        self._editor.configure(yscrollcommand=esb.set)
        self._editor.pack(side="left", fill="both", expand=True)
        esb.pack(side="right", fill="y")
        self._editor.bind("<KeyRelease>", self._on_edit)

        # 预览区
        preview_frame = ttk.Frame(paned)
        self._preview = _make_text(preview_frame, readonly=True)
        psb = ttk.Scrollbar(
            preview_frame, orient="vertical", command=self._preview.yview
        )
        self._preview.configure(yscrollcommand=psb.set)
        self._preview.pack(side="left", fill="both", expand=True)
        psb.pack(side="right", fill="y")

        paned.add(edit_frame, weight=3)
        paned.add(preview_frame, weight=2)

        self._editor.tag_configure("h1", font=("Microsoft YaHei UI", 14, "bold"))
        self._editor.tag_configure("h2", font=("Microsoft YaHei UI", 12, "bold"))
        self._editor.tag_configure("h3", font=("Microsoft YaHei UI", 11, "bold"))
        self._editor.tag_configure("h4", font=("Microsoft YaHei UI", 10, "bold"))
        self._preview.tag_configure("h1", font=("Microsoft YaHei UI", 14, "bold"))
        self._preview.tag_configure("h2", font=("Microsoft YaHei UI", 12, "bold"))
        self._preview.tag_configure("h3", font=("Microsoft YaHei UI", 11, "bold"))
        self._preview.tag_configure("h4", font=("Microsoft YaHei UI", 10, "bold"))
        self._preview.tag_configure(
            "table", font=FONT_MONO, foreground="#333333"
        )
        self._preview.tag_configure(
            "image", foreground="#8a5a00"
        )

    # --- 加载 / 保存 ---

    def load(self, rel_path: str, text: str) -> None:
        """加载文件内容到编辑器并刷新预览。"""
        self._rel_path = rel_path
        self._mtime = self._file_mtime(rel_path)
        self._editor.configure(state="normal")
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", text)
        self._apply_edit_state()
        self._dirty = False
        self._file_var.set(rel_path)
        self._status_var.set("已加载 · " + preview_summary(text))
        self._refresh_preview(text)
        self._update_dirty()
        self._update_save_state()

    def save(self) -> bool:
        """保存当前内容（备份 + 原子写）。成功返回 True。"""
        if not self._writable or self._rel_path is None:
            return False
        text = self._editor.get("1.0", "end-1c")
        result = self._writer.write_text(self._rel_path, text)
        if not result.written:
            self._status_var.set("保存失败：{0}".format(result.error))
            return False
        self._mtime = self._file_mtime(self._rel_path)
        self._dirty = False
        self._status_var.set("已保存" + (
            "" if result.backup_path else "（备份不可用）"
        ))
        if self._on_saved is not None:
            self._on_saved(self._rel_path)
        self._update_dirty()
        self._update_save_state()
        return True

    def rollback_last(self) -> bool:
        """回滚本文件最近一次保存（用 .bak 恢复）。"""
        if not self._writable or self._rel_path is None:
            return False
        from doc_tool.application.content.writer import _backup_path_for

        target = self._writer_abs(self._rel_path)
        backup = _backup_path_for(target)
        if not backup.exists():
            self._status_var.set("无可用备份")
            return False
        import shutil

        shutil.copy2(str(backup), str(target))
        self._mtime = self._file_mtime(self._rel_path)
        self._dirty = False
        self._status_var.set("已回滚到备份")
        if self._on_saved is not None:
            self._on_saved(self._rel_path)
        self._update_dirty()
        self._update_save_state()
        return True

    def open_external(self) -> bool:
        """用系统默认程序在外部编辑器打开当前文件。"""
        if self._rel_path is None:
            return False
        target = self._writer_abs(self._rel_path)
        if not target.exists():
            self._status_var.set("文件不存在")
            return False
        try:
            if os.name == "nt":
                os.startfile(str(target))  # noqa: S606
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(target)])
            self._status_var.set("已在外部编辑器打开（请记得回工具刷新）")
            return True
        except OSError as exc:
            self._status_var.set("打开外部编辑器失败：{0}".format(exc))
            return False

    def check_external_change(self) -> bool:
        """检测文件是否被外部修改；是则提示并刷新内容。返回是否发生了刷新。"""
        if self._rel_path is None:
            return False
        current = self._file_mtime(self._rel_path)
        if current is not None and self._mtime is not None and current != self._mtime:
            try:
                text = self._writer_abs(self._rel_path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return False
            self.load(self._rel_path, text)
            self._status_var.set("检测到外部修改，已刷新")
            return True
        return False

    def highlight_line(self, line_no: int) -> None:
        """高亮并滚动到指定行（用于搜索结果/检查结果定位）。"""
        self._editor.tag_remove("highlight", "1.0", "end")
        self._editor.tag_configure(
            "highlight", background="#fff3cd"
        )
        start = "{0}.0".format(line_no)
        end = "{0}.0".format(line_no + 1)
        try:
            self._editor.tag_add("highlight", start, end)
            self._editor.see(start)
            self._editor.mark_set("insert", start)
        except Exception:
            pass

    def set_writable(self, writable: bool) -> None:
        """切换只读/可写。"""
        self._writable = writable
        self._apply_edit_state()
        self._update_save_state()

    def is_writable(self) -> bool:
        return self._writable

    def current_rel_path(self) -> Optional[str]:
        return self._rel_path

    def is_dirty(self) -> bool:
        return self._dirty

    # --- 内部 ---

    def _on_edit(self, _event=None) -> None:
        self._dirty = True
        self._update_dirty()
        self._update_save_state()
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(_PREVIEW_DEBOUNCE_MS, self._schedule_preview)

    def _update_dirty(self) -> None:
        """未保存修改指示（工具栏 ● 标记）。"""
        self._dirty_var.set("● 未保存" if self._dirty else "")

    def _schedule_preview(self) -> None:
        self._preview_job = None
        self._refresh_preview(self._editor.get("1.0", "end-1c"))

    def _refresh_preview(self, text: str) -> None:
        self._preview.configure(state="normal")
        self._preview.delete("1.0", "end")
        for block in render_preview_blocks(text):
            if block.kind == "heading":
                tag = "h{0}".format(min(block.level, 4))
                self._preview.insert("end", block.text + "\n", (tag,))
            elif block.kind == "table":
                for row in block.rows[:20]:
                    cells = " | ".join(row)
                    self._preview.insert("end", cells + "\n", ("table",))
                if len(block.rows) > 20:
                    self._preview.insert("end", "…（表格省略）\n", ("table",))
                self._preview.insert("end", "\n")
            elif block.kind == "image":
                label = "📷 {0}".format(block.image_path)
                if block.image_size:
                    label += " ({0})".format(block.image_size)
                self._preview.insert("end", label + "\n", ("image",))
            elif block.kind == "paragraph":
                self._preview.insert("end", block.text + "\n")
            else:
                self._preview.insert("end", "\n")
        self._preview.insert(
            "end",
            "\n—— 近似结构预览，以 Word 输出为准 ——\n",
            ("image",),
        )
        self._preview.configure(state="disabled")

    def _apply_edit_state(self) -> None:
        self._editor.configure(state="normal" if self._writable else "disabled")

    def _update_save_state(self) -> None:
        can = self._writable and self._rel_path is not None
        self._save_btn.configure(state="normal" if (can and self._dirty) else "disabled")
        self._rollback_btn.configure(state="normal" if can else "disabled")
        self._ext_btn.configure(state="normal" if self._rel_path is not None else "disabled")

    def _file_mtime(self, rel_path: str) -> Optional[float]:
        target = self._writer_abs(rel_path)
        try:
            return target.stat().st_mtime
        except OSError:
            return None

    def _writer_abs(self, rel_path: str):
        return self._writer.resolve(rel_path)


def _make_text(master, *, readonly: bool):
    import tkinter as tk

    text = tk.Text(
        master,
        wrap="word",
        undo=True,
        font=FONT_MONO,
        state="disabled" if readonly else "normal",
        padx=6,
        pady=6,
    )
    return text


def tk_string_var(value: str = ""):
    import tkinter as tk

    return tk.StringVar(value=value)
