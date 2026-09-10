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

    STATE_NORMAL = 0
    STATE_IN_CODE = 1
    STATE_IN_COMMENT = 2

    _HEADING_RE = QRegularExpression(r"^#{1,6}\s+.*$")
    _BOLD_RE = QRegularExpression(r"\*\*[^*]+\*\*")
    _INLINE_CODE_RE = QRegularExpression(r"`[^`]+`")
    _LINK_RE = QRegularExpression(r"\[[^\]]*\]\([^)]*\)")
    _LIST_RE = QRegularExpression(r"^(\s*[-*+]|\s*\d+\.)\s+")
    _QUOTE_RE = QRegularExpression(r"^>\s?")
    _FENCE_RE = QRegularExpression(r"^```")
    _EMPTY_PAR_RE = QRegularExpression(r"<EMPTY_PAR\s*/?>")

    def __init__(self, document) -> None:
        super().__init__(document)
        self._in_code = False

    def highlightBlock(self, text: str) -> None:
        prev_state = self.previousBlockState()
        if prev_state == -1:
            prev_state = self.STATE_NORMAL

        # 1. 代码围栏 (```)
        if prev_state == self.STATE_IN_CODE:
            self.setFormat(0, len(text), self._code_fmt())
            if self._FENCE_RE.match(text).hasMatch():
                self.setCurrentBlockState(self.STATE_NORMAL)
                self._in_code = False
            else:
                self.setCurrentBlockState(self.STATE_IN_CODE)
                self._in_code = True
            return

        if self._FENCE_RE.match(text).hasMatch():
            self.setFormat(0, len(text), self._code_fmt())
            self.setCurrentBlockState(self.STATE_IN_CODE)
            self._in_code = True
            return

        self._in_code = False

        # 2. 跨行 HTML 注释处理 (如 <!-- TBL:style=... -->)
        if prev_state == self.STATE_IN_COMMENT:
            end_idx = text.find("-->")
            if end_idx != -1:
                self.setFormat(0, end_idx + 3, self._comment_fmt())
                self.setCurrentBlockState(self.STATE_NORMAL)
            else:
                self.setFormat(0, len(text), self._comment_fmt())
                self.setCurrentBlockState(self.STATE_IN_COMMENT)
                return
        else:
            self.setCurrentBlockState(self.STATE_NORMAL)

        # 3. 行级规则互斥：命中即整行上色
        for regex, fmt in self._line_rules():
            if regex.match(text).hasMatch():
                self.setFormat(0, len(text), fmt)
                return

        # 4. 单行/行内 HTML 注释及开启跨行注释
        comment_start = text.find("<!--")
        if comment_start != -1:
            comment_end = text.find("-->", comment_start + 4)
            if comment_end != -1:
                self.setFormat(comment_start, comment_end + 3 - comment_start, self._comment_fmt())
            else:
                self.setFormat(comment_start, len(text) - comment_start, self._comment_fmt())
                self.setCurrentBlockState(self.STATE_IN_COMMENT)

        # 5. 空段落标记 <EMPTY_PAR/>
        it_par = self._EMPTY_PAR_RE.globalMatch(text)
        while it_par.hasNext():
            m = it_par.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self._comment_fmt())

        # 6. 词内规则叠加
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

    def _comment_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFontItalic(True)
        fmt.setForeground(QColor("#94a3b8"))
        return fmt

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
        if hasattr(fmt, "setFontFamilies"):
            fmt.setFontFamilies(["Consolas"])
        else:
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
        if hasattr(fmt, "setFontFamilies"):
            fmt.setFontFamilies(["Consolas"])
        else:
            fmt.setFontFamily("Consolas")
        fmt.setBackground(QColor("#eef1f4"))
        return fmt


# --- Diff 语法高亮 ---

class DiffHighlighter(QSyntaxHighlighter):
    """Unified Diff 语法高亮器（支持浅色/深色主题）。"""

    def __init__(self, document, dark: bool = False) -> None:
        super().__init__(document)
        self._dark = dark

    def set_dark(self, dark: bool) -> None:
        """切换高亮器暗黑模式。"""
        if self._dark != dark:
            self._dark = dark
            self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not text:
            return
        if text.startswith("+++") or text.startswith("---") or text.startswith("diff "):
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setForeground(QColor("#94a3b8" if self._dark else "#475569"))
            self.setFormat(0, len(text), fmt)
        elif text.startswith("+"):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#86efac" if self._dark else "#166534"))
            fmt.setBackground(QColor("#14532d" if self._dark else "#dcfce7"))
            self.setFormat(0, len(text), fmt)

            # 字级别差异高亮（Intra-line / Word Diff）
            block = self.currentBlock()
            prev_block = block.previous()
            if prev_block.isValid() and prev_block.text().startswith("-") and not prev_block.text().startswith("---"):
                old_line = prev_block.text()[1:]
                new_line = text[1:]
                from doc_tool.application.content.changes import compute_word_diff_spans

                _, new_spans = compute_word_diff_spans(old_line, new_line)
                for span in new_spans:
                    w_fmt = QTextCharFormat(fmt)
                    w_fmt.setFontWeight(QFont.Weight.Bold)
                    w_fmt.setBackground(QColor("#15803d" if self._dark else "#86efac"))
                    w_fmt.setForeground(QColor("#f0fdf4" if self._dark else "#14532d"))
                    self.setFormat(span.start + 1, span.end - span.start, w_fmt)
        elif text.startswith("-"):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#fca5a5" if self._dark else "#991b1b"))
            fmt.setBackground(QColor("#450a0a" if self._dark else "#fee2e2"))
            self.setFormat(0, len(text), fmt)

            # 字级别差异高亮（Intra-line / Word Diff）
            block = self.currentBlock()
            next_block = block.next()
            if next_block.isValid() and next_block.text().startswith("+") and not next_block.text().startswith("+++"):
                old_line = text[1:]
                new_line = next_block.text()[1:]
                from doc_tool.application.content.changes import compute_word_diff_spans

                old_spans, _ = compute_word_diff_spans(old_line, new_line)
                for span in old_spans:
                    w_fmt = QTextCharFormat(fmt)
                    w_fmt.setFontWeight(QFont.Weight.Bold)
                    w_fmt.setBackground(QColor("#991b1b" if self._dark else "#fca5a5"))
                    w_fmt.setForeground(QColor("#fef2f2" if self._dark else "#7f1d1d"))
                    self.setFormat(span.start + 1, span.end - span.start, w_fmt)
        elif text.startswith("@@"):
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setForeground(QColor("#60a5fa" if self._dark else "#1d4ed8"))
            fmt.setBackground(QColor("#1e293b" if self._dark else "#eff6ff"))
            self.setFormat(0, len(text), fmt)


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
    formatTableRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_width()

        self._spell_checker = None
        self._snippet_active = False
        self._snippet_placeholders: List[Tuple[int, int, str]] = []
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
        from doc_tool.application.content.table_format import is_table_row
        cursor_at_pos = self.cursorForPosition(event.pos())
        if not self.isReadOnly():
            line_text = cursor_at_pos.block().text()
            # 1. 标题缺少空格快速修复 (#1.1 标题 -> # 1.1 标题)
            m_heading = re.match(r"^(\s*#{1,6})([^\s#].*)$", line_text)
            if m_heading:
                menu.addSeparator()
                fixed_heading = "{0} {1}".format(m_heading.group(1), m_heading.group(2))
                fix_h_act = menu.addAction("⚡ 快速修复标题格式（补全空格为 '{0}'）".format(fixed_heading.strip()))
                b_pos = cursor_at_pos.block().position()
                b_len = len(cursor_at_pos.block().text())
                fix_h_act.triggered.connect(
                    lambda _=False, bp=b_pos, bl=b_len, fh=fixed_heading: (
                        self._replace_text_range(bp, bp + bl, fh)
                    )
                )

            # 2. 表格操作
            if is_table_row(line_text):
                table_action = menu.addAction("美化当前表格 (Ctrl+Alt+T)")
                table_action.triggered.connect(lambda _=False: self.formatTableRequested.emit())
            else:
                ins_tbl_act = menu.addAction("插入标准 Markdown 表格 (3×3)")
                table_tmpl = "| 列 1 | 列 2 | 列 3 |\n| --- | --- | --- |\n| 内容 | 内容 | 内容 |\n"
                ins_tbl_act.triggered.connect(
                    lambda _=False, p=cursor_at_pos.position(), t=table_tmpl: (
                        self._insert_table_at(p, t)
                    )
                )
        menu.exec(event.globalPos())

    def _insert_table_at(self, position: int, text: str) -> None:
        c = self.textCursor()
        c.setPosition(position)
        line_text = c.block().text()
        pos_in_block = c.positionInBlock()
        prefix = ""
        suffix = ""
        if line_text.strip():
            if pos_in_block > 0:
                prefix = "\n\n"
            else:
                suffix = "\n"
        c.insertText(prefix + text + suffix)
        self.setTextCursor(c)

    def _replace_text_range(self, start: int, end: int, text: str) -> None:
        c = self.textCursor()
        c.setPosition(start)
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        c.insertText(text)
        self.setTextCursor(c)

    # --- 代码片段占位符跳转 ---

    def begin_snippet(self, specs: List[Tuple[int, int, str]]) -> None:
        """片段插入后记录占位符 ``(起, 止, 默认文本)``；第一个占位符由调用方选中。

        跳转时按默认文本在当前文档中重新定位，而不是沿用插入时的固定区间：
        用户在占位符内输入与默认值不同长度的文本后，旧区间已失效，按文本
        搜索可正确定位后续占位符。
        """
        self._snippet_placeholders = list(specs)
        self._snippet_index = 0 if specs else None
        self._snippet_active = bool(specs)

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
        doc = self.document()
        doc_length = doc.characterCount()
        while True:
            self._snippet_index += 1
            if self._snippet_index >= len(self._snippet_placeholders):
                # 全部占位符已填完：恢复正常 Tab（插入一个制表符）。
                self.end_snippet()
                self.textCursor().insertText("\t")
                return
            _start, _end, default = self._snippet_placeholders[self._snippet_index]
            if default:
                # 占位符 Tab 顺序按序号、不按文档位置（``${2:x}`` 可出现在
                # ``${1:y}`` 之前），因此从该占位符插入时的原始起点向后搜索：
                # 文档被编辑后发生偏移仍能命中；找不到（默认文本被改掉）则
                # 跳过该占位符。
                found = doc.find(default, max(0, _start))
                if found is not None and not found.isNull():
                    self.setTextCursor(found)
                    return
                continue
            # 无默认值的占位符（纯光标停靠点）无法文本定位：退化为原区间，
            # 越界则跳过（文档被外部改动）。
            if 0 <= _start <= _end <= doc_length:
                sel = self.textCursor()
                sel.setPosition(_start)
                sel.setPosition(_end, QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(sel)
                return

    @staticmethod
    def _get_unescaped_pipes(text: str) -> List[int]:
        """获取文本中所有未被反斜杠转义的管道符索引列表。"""
        pipes: List[int] = []
        escaped = False
        for i, ch in enumerate(text):
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "|":
                pipes.append(i)
        return pipes

    def _handle_table_tab(self, shift: bool) -> bool:
        """在 Markdown 表格中拦截 Tab/Shift+Tab 进行单元格跳转与末行自动加行。"""
        if self.isReadOnly():
            return False

        cursor = self.textCursor()
        block = cursor.block()
        line_text = block.text()
        from doc_tool.application.content.table_format import is_table_row

        if not is_table_row(line_text):
            return False

        pipes = self._get_unescaped_pipes(line_text)
        if len(pipes) < 2:
            return False

        cells: List[Tuple[int, int]] = []
        for idx in range(len(pipes) - 1):
            c_start = pipes[idx] + 1
            c_end = pipes[idx + 1]
            cells.append((c_start, c_end))

        pos = cursor.positionInBlock()

        current_cell_idx = 0
        for idx, (c_start, c_end) in enumerate(cells):
            if pos <= c_end:
                current_cell_idx = idx
                break
        else:
            current_cell_idx = len(cells) - 1

        def select_cell(target_block, cell_span):
            s, e = cell_span
            txt = target_block.text()
            raw = txt[s:e]
            l_strip = len(raw) - len(raw.lstrip())
            r_strip = len(raw) - len(raw.rstrip())
            act_s = s + l_strip
            act_e = e - r_strip
            if act_s >= act_e:
                act_s, act_e = s, e
            tc = self.textCursor()
            tc.setPosition(target_block.position() + act_s)
            tc.setPosition(target_block.position() + act_e, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(tc)

        if shift:
            if current_cell_idx > 0:
                select_cell(block, cells[current_cell_idx - 1])
                return True
            else:
                prev_b = block.previous()
                if prev_b.isValid() and is_table_row(prev_b.text()):
                    prev_pipes = self._get_unescaped_pipes(prev_b.text())
                    if len(prev_pipes) >= 2:
                        prev_last_cell = (prev_pipes[-2] + 1, prev_pipes[-1])
                        select_cell(prev_b, prev_last_cell)
                        return True
            return False
        else:
            if current_cell_idx < len(cells) - 1:
                select_cell(block, cells[current_cell_idx + 1])
                return True
            else:
                next_b = block.next()
                if next_b.isValid() and is_table_row(next_b.text()):
                    next_pipes = self._get_unescaped_pipes(next_b.text())
                    if len(next_pipes) >= 2:
                        next_first_cell = (next_pipes[0] + 1, next_pipes[1])
                        select_cell(next_b, next_first_cell)
                        return True
                else:
                    num_cols = len(cells)
                    new_row_text = "\n| " + " | ".join(["   "] * num_cols) + " |"
                    tc = self.textCursor()
                    tc.beginEditBlock()
                    tc.setPosition(block.position() + len(line_text))
                    tc.insertText(new_row_text)
                    tc.endEditBlock()
                    new_block = block.next()
                    if new_block.isValid():
                        new_pipes = self._get_unescaped_pipes(new_block.text())
                        if len(new_pipes) >= 2:
                            select_cell(new_block, (new_pipes[0] + 1, new_pipes[1]))
                    return True

    def keyPressEvent(self, event) -> None:
        if self._snippet_active and event.key() == Qt.Key.Key_Tab:
            self._advance_snippet()
            event.accept()
            return

        is_backtab = event.key() == Qt.Key.Key_Backtab or (
            event.key() == Qt.Key.Key_Tab
            and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        )
        if is_backtab:
            if self._handle_table_tab(shift=True):
                event.accept()
                return
        elif event.key() == Qt.Key.Key_Tab:
            if self._handle_table_tab(shift=False):
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
