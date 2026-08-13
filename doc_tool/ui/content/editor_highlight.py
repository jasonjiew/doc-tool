# -*- coding: utf-8 -*-
"""Markdown 语法高亮 + 行号槽（编辑器增强）。

``MarkdownHighlighter``：``QSyntaxHighlighter`` 实现标题/粗体/行内代码/
代码块/链接/列表/引用高亮；代码块用 ``_in_code`` 状态机在 ``` 围栏间上色。

``LineNumberArea`` + ``_LineNumberedEdit``：在 ``QPlainTextEdit`` 左侧绘制
行号（标准 gutter 模式），随内容/滚动/行数变化重绘。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

# 英文词 token（与拼写服务一致）：至少一个字母开头，可含撇号/连字符。
_SPELL_TOKEN_RE = re.compile(r"\b[a-zA-Z][a-zA-Z'-]{1,}\b")


# --- Markdown 语法高亮 ---

class MarkdownHighlighter(QSyntaxHighlighter):
    """Markdown 语法高亮。"""

    _HEADING_RE = QRegularExpression(r"^#{1,6}\s+.*$")
    _BOLD_RE = QRegularExpression(r"\*\*[^*]+\*\*")
    _INLINE_CODE_RE = QRegularExpression(r"`[^`]+`")
    _LINK_RE = QRegularExpression(r"\[[^\]]*\]\([^)]*\)")
    _LIST_RE = QRegularExpression(r"^(\s*[-*+]|\s*\d+\.)\s+")
    _QUOTE_RE = QRegularExpression(r"^>\s?")
    _FENCE_RE = QRegularExpression(r"^```")

    def __init__(self, document) -> None:
        super().__init__(document)
        self._in_code = False

    def highlightBlock(self, text: str) -> None:
        if self._FENCE_RE.match(text).hasMatch():
            self._in_code = not self._in_code
            self.setFormat(0, len(text), self._code_fmt())
            return
        if self._in_code:
            self.setFormat(0, len(text), self._code_fmt())
            return
        # 行级规则互斥：命中即整行上色
        for regex, fmt in self._line_rules():
            if regex.match(text).hasMatch():
                self.setFormat(0, len(text), fmt)
                return
        # 词内规则叠加
        for regex, fmt in self._inline_rules():
            it = regex.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(
                    match.capturedStart(), match.capturedLength(), fmt
                )

    # --- 格式工厂（供测试直接断言） ---

    def _line_rules(self):
        return [
            (self._HEADING_RE, self._heading_fmt()),
            (self._QUOTE_RE, self._quote_fmt()),
            (self._LIST_RE, self._list_fmt()),
        ]

    def _inline_rules(self):
        return [
            (self._BOLD_RE, self._bold_fmt()),
            (self._INLINE_CODE_RE, self._inline_code_fmt()),
            (self._LINK_RE, self._link_fmt()),
        ]

    def _heading_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold)
        fmt.setForeground(QColor("#1f2328"))
        return fmt

    def _quote_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontItalic(True)
        fmt.setForeground(QColor("#57606a"))
        return fmt

    def _list_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#2563eb"))
        return fmt

    def _bold_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold)
        return fmt

    def _inline_code_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontFamily("Consolas")
        fmt.setBackground(QColor("#eef1f4"))
        return fmt

    def _link_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#2563eb"))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
        return fmt

    def _code_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontFamily("Consolas")
        fmt.setBackground(QColor("#eef1f4"))
        return fmt


# --- 行号槽 ---

class LineNumberArea(QWidget):
    """编辑器左侧行号区（由 _LineNumberedEdit 驱动重绘）。"""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.line_number_area_paint_event(event)


class _LineNumberedEdit(QPlainTextEdit):
    """带行号的只读友好编辑器（标准 gutter 模式）。

    扩展：
    - 拼写检查右键菜单：对错误词提供「更改为…」建议与「加入词典」
      （``addWordRequested`` 信号交由上层持久化）。
    - 代码片段占位符跳转：``begin_snippet`` 记录占位符位置，片段激活期间
      ``Tab`` 依次选中下一个占位符，全部填完后恢复普通 Tab。
    - 图片粘贴/拖放（见 ``insertFromMimeData``/``dropEvent``，由资源面板接线）。
    """

    addWordRequested = Signal(str)
    mermaidEditRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_width()

        self._spell_checker = None
        self._snippet_active = False
        self._snippet_placeholders: List[Tuple[int, int]] = []
        self._snippet_index: Optional[int] = None
        self._image_import_callback = None

    # --- 拼写检查 ---

    def set_spellchecker(self, checker) -> None:
        """注入拼写检查器（右键菜单据此提供候选与「加入词典」）。"""
        self._spell_checker = checker

    def set_image_import_callback(self, callback) -> None:
        """注入图片导入回调（粘贴/拖放时调用；回调签名见资源面板）。"""
        self._image_import_callback = callback

    def _misspelled_at(self, position: int) -> Optional[Tuple[str, int, int]]:
        """返回位置处的拼写错误 (词, 起, 止)；无错误或非错误词返回 None。"""
        if self._spell_checker is None:
            return None
        block = self.document().findBlock(position)
        if not block.isValid():
            return None
        text = block.text()
        relative = position - block.position()
        for match in _SPELL_TOKEN_RE.finditer(text):
            if match.start() <= relative <= match.end():
                word = match.group(0)
                if not self._spell_checker.contains(word):
                    return (
                        word,
                        block.position() + match.start(),
                        block.position() + match.end(),
                    )
                return None
        return None

    def _replace_text_range(self, start: int, end: int, text: str) -> None:
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def contextMenuEvent(self, event) -> None:
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        mermaid_action = menu.addAction("用 Mermaid 工作台编辑")
        position = self.cursorForPosition(event.pos()).position()
        mermaid_action.triggered.connect(
            lambda _=False, p=position: self.mermaidEditRequested.emit(p)
        )
        if self._spell_checker is not None and not self.isReadOnly():
            found = self._misspelled_at(position)
            if found is not None:
                word, start, end = found
                menu.addSeparator()
                suggestions = self._spell_checker.suggest(word)
                for suggestion in suggestions[:6]:
                    action = menu.addAction("更改为「{0}」".format(suggestion))
                    action.triggered.connect(
                        lambda _=False, s=suggestion, a=start, b=end: (
                            self._replace_text_range(a, b, s)
                        )
                    )
                menu.addSeparator()
                add_action = menu.addAction("加入词典")
                add_action.triggered.connect(
                    lambda _=False, w=word: self.addWordRequested.emit(w)
                )
        menu.exec(event.globalPos())

    # --- 代码片段占位符跳转 ---

    def begin_snippet(self, positions: List[Tuple[int, int]]) -> None:
        """片段插入后记录占位符文档区间；第一个占位符由调用方选中。"""
        self._snippet_placeholders = list(positions)
        self._snippet_index = 0 if positions else None
        self._snippet_active = bool(positions)

    def end_snippet(self) -> None:
        self._snippet_active = False
        self._snippet_index = None
        self._snippet_placeholders = []

    @property
    def snippet_active(self) -> bool:
        return self._snippet_active

    def _advance_snippet(self) -> None:
        if self._snippet_index is None or not self._snippet_placeholders:
            self._snippet_active = False
            return
        self._snippet_index += 1
        if self._snippet_index >= len(self._snippet_placeholders):
            # 全部占位符已填完：恢复正常 Tab（插入一个制表符）。
            self.end_snippet()
            self.textCursor().insertText("\t")
            return
        start, end = self._snippet_placeholders[self._snippet_index]
        doc_length = self.document().characterCount()
        if 0 <= start <= end <= doc_length:
            cursor = self.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def keyPressEvent(self, event) -> None:
        if self._snippet_active and event.key() == Qt.Key.Key_Tab:
            self._advance_snippet()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- 图片导入钩子 ---

    def insertFromMimeData(self, source) -> None:
        if (
            self._image_import_callback is not None
            and not self.isReadOnly()
            and source.hasImage()
        ):
            image = source.imageData()
            if image is not None:
                self._image_import_callback(image)
                return
        super().insertFromMimeData(source)

    def dropEvent(self, event) -> None:
        if self._image_import_callback is not None and not self.isReadOnly():
            urls = event.mimeData().urls()
            if urls:
                local = urls[0].toLocalFile()
                if local.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
                ):
                    import os

                    self._image_import_callback(local)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def line_number_area_width(self) -> int:
        """行号区宽度：按当前最大行号位数自适应。"""
        digits = len(str(max(1, self.blockCount())))
        return 12 + 6 * digits

    def _update_line_number_width(self, _count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_line_number_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(
                rect.left(),
                rect.top(),
                self.line_number_area_width(),
                rect.height(),
            )
        )

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#f0f1f4"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset())
            .top()
        )
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#9ca3af"))
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()
