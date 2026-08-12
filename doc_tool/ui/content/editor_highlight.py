# -*- coding: utf-8 -*-
"""Markdown 语法高亮 + 行号槽（编辑器增强）。

``MarkdownHighlighter``：``QSyntaxHighlighter`` 实现标题/粗体/行内代码/
代码块/链接/列表/引用高亮；代码块用 ``_in_code`` 状态机在 ``` 围栏间上色。

``LineNumberArea`` + ``_LineNumberedEdit``：在 ``QPlainTextEdit`` 左侧绘制
行号（标准 gutter 模式），随内容/滚动/行数变化重绘。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter
from PySide6.QtGui import QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit, QWidget


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
    """带行号的只读友好编辑器（标准 gutter 模式）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_width()

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
