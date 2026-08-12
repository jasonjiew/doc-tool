# -*- coding: utf-8 -*-
"""内置 .md 编辑器 + Markdown 阅读预览（PySide6）。

UTF-8 纯文本编辑，保存经 ``ContentWriter``（备份 + 原子写）。右侧使用 Qt
原生 Markdown 文档渲染器，编辑去抖后即时更新；项目自定义图片尺寸后缀会在
预览前转换为标准 Markdown。提供"在外部编辑器打开"兜底与外部修改检测。
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.preview import (
    preview_summary,
    render_markdown_html,
)
from doc_tool.ui.content.editor_highlight import (
    MarkdownHighlighter,
    _LineNumberedEdit,
)

_PREVIEW_DEBOUNCE_MS = 300


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
        assets_root=None,
        writable: bool = True,
        on_dirty_changed: Optional[Callable[[bool], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._writer = writer
        self._on_saved = on_saved
        self._assets_root = assets_root
        self._writable = writable
        self._on_dirty_changed = on_dirty_changed
        self._rel_path: Optional[str] = None
        self._mtime: Optional[float] = None
        self._dirty = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._schedule_preview)

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

        self._preview_btn = QPushButton("隐藏预览", bar)
        self._preview_btn.setProperty("btnRole", "compact")
        self._preview_btn.clicked.connect(self._toggle_preview)
        layout.addWidget(self._preview_btn)

        self._save_btn = QPushButton("保存 (Ctrl+S)", bar)
        self._save_btn.setProperty("btnRole", "primary")
        self._save_btn.clicked.connect(self.save)
        layout.addWidget(self._save_btn)

        self._toolbar = bar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(bar)
        self._find_bar = self._build_find_bar()
        outer.addWidget(self._find_bar)
        self._body_host = QWidget(self)
        outer.addWidget(self._body_host, 1)

    def _build_find_bar(self) -> QWidget:
        """文件内查找条：输入 + 上/下导航 + 关闭。默认隐藏。"""
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)
        layout.addWidget(QLabel("查找：", bar))
        self._find_entry = QLineEdit(bar)
        self._find_entry.setPlaceholderText("在文件中查找…")
        self._find_entry.textChanged.connect(self._on_find_changed)
        self._find_entry.returnPressed.connect(self._find_next)
        layout.addWidget(self._find_entry, 1)
        prev_btn = QPushButton("上一个", bar)
        prev_btn.setProperty("btnRole", "compact")
        prev_btn.clicked.connect(self._find_prev)
        layout.addWidget(prev_btn)
        next_btn = QPushButton("下一个", bar)
        next_btn.setProperty("btnRole", "compact")
        next_btn.clicked.connect(self._find_next)
        layout.addWidget(next_btn)
        close_btn = QPushButton("关闭", bar)
        close_btn.setProperty("btnRole", "compact")
        close_btn.clicked.connect(self.hide_find)
        layout.addWidget(close_btn)
        bar.hide()
        return bar

    def _build_panes(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self._body_host)
        body = QVBoxLayout(self._body_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(splitter)

        edit_frame = QWidget(splitter)
        edit_layout = QVBoxLayout(edit_frame)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        self._editor = _LineNumberedEdit(edit_frame)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._editor.textChanged.connect(self._on_edit)
        self._editor.verticalScrollBar().valueChanged.connect(
            self._sync_preview_scroll
        )
        self._highlighter = MarkdownHighlighter(self._editor.document())
        edit_layout.addWidget(self._editor)
        splitter.addWidget(edit_frame)

        preview_frame = QWidget(splitter)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = QTextBrowser(preview_frame)
        self._preview.setReadOnly(True)
        self._preview.setOpenExternalLinks(True)
        preview_layout.addWidget(self._preview)
        splitter.addWidget(preview_frame)
        self._preview_frame = preview_frame

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
        from doc_tool.application.content.writer import (
            OP_EDIT,
            _backup_path_for,
        )

        target = self._writer_abs(self._rel_path)
        backup = _backup_path_for(target)
        if not backup.exists():
            self._status_label.setText("无可用备份")
            return False
        import shutil

        shutil.copy2(str(backup), str(target))
        # 已恢复到保存前状态：丢弃备份，并从改动清单移除该文件 edit 条目，
        # 避免 .bak 残留在 contentRoot 阻断构建、徽标仍显示"已修改"。
        try:
            backup.unlink()
        except OSError:
            pass
        try:
            self._writer.manifest.load()
            self._writer.manifest.drop(
                OP_EDIT, self._rel_path
            )
        except OSError:
            pass
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
        """检测文件是否被外部修改；是则提示并刷新内容。返回是否发生了刷新。

        编辑器有未保存更改时不静默重载——先弹确认框，避免外部写盘后
        标签切换把用户正在编辑的内容无声清空。
        """
        if self._rel_path is None:
            return False
        current = self._file_mtime(self._rel_path)
        if current is not None and self._mtime is not None and current != self._mtime:
            if self._dirty:
                from PySide6.QtWidgets import QMessageBox

                answer = QMessageBox.question(
                    self,
                    "外部修改检测",
                    "文件已在外部被修改：\n{0}\n\n"
                    "重载将丢弃未保存的更改，是否重载？".format(self._rel_path),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self._status_label.setText("保留未保存更改，未重载外部版本")
                    return False
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

    # --- 文件内查找 ---

    def focus_find(self) -> None:
        """显示查找条并聚焦输入框（Ctrl+F 且编辑器聚焦时调用）。"""
        self._find_bar.show()
        self._find_entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._find_entry.selectAll()

    def hide_find(self) -> None:
        self._find_bar.hide()
        self._clear_highlights()

    def _find_text(self) -> str:
        return self._find_entry.text()

    def _on_find_changed(self, _text: str) -> None:
        self._update_highlights()

    def _clear_highlights(self) -> None:
        self._editor.setExtraSelections([])

    def _update_highlights(self) -> None:
        """高亮全部命中；最后一个命中用更深的颜色表示当前匹配。"""
        query = self._find_text()
        if not query:
            self._clear_highlights()
            return
        doc = self._editor.document()
        selections = []
        cursor = QTextCursor(doc)
        base_fmt = QTextCharFormat()
        base_fmt.setBackground(QColor("#ffe08a"))
        current_fmt = QTextCharFormat()
        current_fmt.setBackground(QColor("#ffb84d"))
        while True:
            cursor = doc.find(query, cursor)
            if cursor.isNull():
                break
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = base_fmt
            selections.append(selection)
        if selections:
            selections[-1].format = current_fmt
        self._editor.setExtraSelections(selections)

    def _find_next(self) -> None:
        query = self._find_text()
        if not query:
            return
        if not self._editor.find(query):
            # 到末尾未命中 → 循环回开头
            self._editor.moveCursor(QTextCursor.MoveOperation.Start)
            self._editor.find(query)

    def _find_prev(self) -> None:
        query = self._find_text()
        if not query:
            return
        flags = QTextDocument.FindFlag.FindBackward
        if not self._editor.find(query, flags):
            self._editor.moveCursor(QTextCursor.MoveOperation.End)
            self._editor.find(query, flags)

    # --- 预览折叠 / 同步滚动 ---

    def _toggle_preview(self) -> None:
        """切换预览区显示/隐藏。"""
        visible = self._preview_frame.isHidden()
        self._preview_frame.setVisible(visible)
        self._preview_btn.setText("隐藏预览" if visible else "显示预览")

    def _sync_preview_scroll(self) -> None:
        """编辑滚动时按当前光标所在标题把预览滚动到对应位置（单向 best-effort）。"""
        if self._preview_frame.isHidden():
            return
        heading = self._current_heading_text()
        if heading:
            self._scroll_preview_to_heading(heading)

    def _current_heading_text(self) -> Optional[str]:
        """从光标所在块向上找最近的 Markdown 标题文本。"""
        block = self._editor.textCursor().block()
        while block.isValid():
            text = block.text().strip()
            if text.startswith("#"):
                return text.lstrip("#").strip()
            block = block.previous()
        return None

    def _scroll_preview_to_heading(self, heading: str) -> None:
        """在预览中定位到包含该标题文本的位置并滚动到可见。"""
        cursor = self._preview.document().find(heading)
        if cursor.isNull():
            return
        self._preview.setTextCursor(cursor)
        self._preview.ensureCursorVisible()

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
        if self._find_bar.isVisible():
            self._update_highlights()
        self._preview_timer.stop()
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def _update_dirty(self) -> None:
        self._dirty_label.setText("● 未保存" if self._dirty else "")
        if self._on_dirty_changed is not None:
            self._on_dirty_changed(self._dirty)

    def _schedule_preview(self) -> None:
        self._refresh_preview(self._editor.toPlainText())

    def _refresh_preview(self, text: str) -> None:
        document = self._preview.document()
        document.setBaseUrl(self._preview_base_url())
        document.setHtml(render_markdown_html(text))
        self._preview.moveCursor(QTextCursor.MoveOperation.Start)

    def _preview_base_url(self) -> QUrl:
        """返回当前文档图片等相对资源的解析目录。"""
        if self._rel_path is not None and self._assets_root is not None:
            document_type = self._rel_path.replace("\\", "/").split("/", 1)[0]
            base = self._assets_root / document_type
        elif self._rel_path is not None:
            base = self._writer_abs(self._rel_path).parent
        else:
            base = self._writer.resolve(".")
        return QUrl.fromLocalFile(str(base) + os.sep)

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
