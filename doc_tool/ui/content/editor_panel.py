# -*- coding: utf-8 -*-
"""内置 .md 编辑器 + 侧边预览（PySide6）。

UTF-8 纯文本编辑，保存经 ``ContentWriter``（备份 + 原子写）。侧边预览由
``render_preview_blocks`` 渲染近似结构，编辑去抖刷新，标注"近似结构预览"。
提供"在外部编辑器打开"兜底与外部修改检测。
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.preview import (
    preview_summary,
    render_preview_blocks,
)
from doc_tool.ui.styles import FONT_FAMILY

_PREVIEW_DEBOUNCE_MS = 300


def _heading_format(level: int) -> QTextCharFormat:
    fmt = QTextCharFormat()
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(max(9.0, 14.0 - (level - 1) * 1.2))
    font.setBold(True)
    fmt.setFont(font)
    return fmt


class EditorPanel(QWidget):
    """单文件 .md 编辑器。

    ``writer``：``ContentWriter``（写入安全）。
    ``on_saved(rel_path)``：保存成功后回调（主窗口据此失效索引）。
    ``writable``：只读时禁用编辑与保存。
    """

    def __init__(
        self,
        writer,
        *,
        on_saved: Optional[Callable[[str], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._writer = writer
        self._on_saved = on_saved
        self._writable = writable
        self._rel_path: Optional[str] = None
        self._mtime: Optional[float] = None
        self._dirty = False
        self._preview_timer: Optional[QTimer] = None

        self._build_toolbar()
        self._build_panes()

    # --- 构建 ---

    def _build_toolbar(self) -> None:
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(8)

        self._file_label = QLabel("未打开文件", bar)
        layout.addWidget(self._file_label)

        self._dirty_label = QLabel("", bar)
        self._dirty_label.setProperty("statusTone", "warning")
        layout.addWidget(self._dirty_label)

        self._status_label = QLabel("", bar)
        self._status_label.setObjectName("statusMuted")
        layout.addWidget(self._status_label)
        layout.addStretch(1)

        self._rollback_btn = QPushButton("回滚上次保存", bar)
        self._rollback_btn.setProperty("btnRole", "compact")
        self._rollback_btn.clicked.connect(self.rollback_last)
        layout.addWidget(self._rollback_btn)

        self._ext_btn = QPushButton("在外部编辑器打开", bar)
        self._ext_btn.setProperty("btnRole", "compact")
        self._ext_btn.clicked.connect(self.open_external)
        layout.addWidget(self._ext_btn)

        self._save_btn = QPushButton("保存 (Ctrl+S)", bar)
        self._save_btn.setProperty("btnRole", "primary")
        self._save_btn.clicked.connect(self.save)
        layout.addWidget(self._save_btn)

        self._toolbar = bar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(bar)
        self._body_host = QWidget(self)
        outer.addWidget(self._body_host, 1)

    def _build_panes(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self._body_host)
        body = QVBoxLayout(self._body_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(splitter)

        edit_frame = QWidget(splitter)
        edit_layout = QVBoxLayout(edit_frame)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        self._editor = QPlainTextEdit(edit_frame)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._editor.textChanged.connect(self._on_edit)
        edit_layout.addWidget(self._editor)
        splitter.addWidget(edit_frame)

        preview_frame = QWidget(splitter)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = QPlainTextEdit(preview_frame)
        self._preview.setReadOnly(True)
        self._preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        preview_layout.addWidget(self._preview)
        splitter.addWidget(preview_frame)

        splitter.setSizes([600, 400])
        self._splitter = splitter

        self._apply_edit_state()

    # --- 加载 / 保存 ---

    def load(self, rel_path: str, text: str) -> None:
        """加载文件内容到编辑器并刷新预览。"""
        self._rel_path = rel_path
        self._mtime = self._file_mtime(rel_path)
        self._editor.setPlainText(text)
        self._dirty = False
        self._file_label.setText(rel_path)
        self._status_label.setText("已加载 · " + preview_summary(text))
        self._refresh_preview(text)
        self._update_dirty()
        self._update_save_state()

    def save(self) -> bool:
        """保存当前内容（备份 + 原子写）。成功返回 True。"""
        if not self._writable or self._rel_path is None:
            return False
        text = self._editor.toPlainText()
        result = self._writer.write_text(self._rel_path, text)
        if not result.written:
            self._status_label.setText("保存失败：{0}".format(result.error))
            return False
        self._mtime = self._file_mtime(self._rel_path)
        self._dirty = False
        self._status_label.setText(
            "已保存" + ("" if result.backup_path else "（备份不可用）")
        )
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
            self._status_label.setText("无可用备份")
            return False
        import shutil

        shutil.copy2(str(backup), str(target))
        self._mtime = self._file_mtime(self._rel_path)
        self._dirty = False
        self._status_label.setText("已回滚到备份")
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
            self._status_label.setText("文件不存在")
            return False
        try:
            if os.name == "nt":
                os.startfile(str(target))  # noqa: S606
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(target)])
            self._status_label.setText("已在外部编辑器打开（请记得回工具刷新）")
            return True
        except OSError as exc:
            self._status_label.setText("打开外部编辑器失败：{0}".format(exc))
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
            self._status_label.setText("检测到外部修改，已刷新")
            return True
        return False

    def highlight_line(self, line_no: int) -> None:
        """高亮并滚动到指定行（用于搜索结果/检查结果定位）。"""
        cursor = self._editor.textCursor()
        block = self._editor.document().findBlockByNumber(max(0, line_no - 1))
        if block.isValid():
            cursor.setPosition(block.position())
            self._editor.setTextCursor(cursor)
            self._editor.centerCursor()
            self._editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_writable(self, writable: bool) -> None:
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

    def _on_edit(self) -> None:
        self._dirty = True
        self._update_dirty()
        self._update_save_state()
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._schedule_preview)
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def _update_dirty(self) -> None:
        self._dirty_label.setText("● 未保存" if self._dirty else "")

    def _schedule_preview(self) -> None:
        self._refresh_preview(self._editor.toPlainText())

    def _refresh_preview(self, text: str) -> None:
        self._preview.clear()
        cursor = self._preview.textCursor()
        for block in render_preview_blocks(text):
            if block.kind == "heading":
                cursor.setCharFormat(_heading_format(block.level))
                cursor.insertText(block.text + "\n")
            elif block.kind == "table":
                fmt = QTextCharFormat()
                font = QFont("Consolas")
                font.setPointSizeF(9)
                fmt.setFont(font)
                cursor.setCharFormat(fmt)
                for row in block.rows[:20]:
                    cells = " | ".join(row)
                    cursor.insertText(cells + "\n")
                if len(block.rows) > 20:
                    cursor.insertText("…（表格省略）\n")
                cursor.insertText("\n")
            elif block.kind == "image":
                label = "📷 {0}".format(block.image_path)
                if block.image_size:
                    label += " ({0})".format(block.image_size)
                cursor.insertText(label + "\n")
            elif block.kind == "paragraph":
                cursor.setCharFormat(QTextCharFormat())
                cursor.insertText(block.text + "\n")
            else:
                cursor.setCharFormat(QTextCharFormat())
                cursor.insertText("\n")
        marker = QTextCharFormat()
        font = QFont(FONT_FAMILY)
        font.setItalic(True)
        marker.setFont(font)
        cursor.setCharFormat(marker)
        cursor.insertText("\n—— 近似结构预览，以 Word 输出为准 ——\n")
        self._preview.moveCursor(QTextCursor.MoveOperation.Start)

    def _apply_edit_state(self) -> None:
        self._editor.setReadOnly(not self._writable)

    def _update_save_state(self) -> None:
        can = self._writable and self._rel_path is not None
        self._save_btn.setEnabled(can and self._dirty)
        self._rollback_btn.setEnabled(can)
        self._ext_btn.setEnabled(self._rel_path is not None)

    def _file_mtime(self, rel_path: str) -> Optional[float]:
        target = self._writer_abs(rel_path)
        try:
            return target.stat().st_mtime
        except OSError:
            return None

    def _writer_abs(self, rel_path: str):
        return self._writer.resolve(rel_path)
