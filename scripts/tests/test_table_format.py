# -*- coding: utf-8 -*-
"""单元测试：Markdown 表格格式化与字宽计算。"""

import unittest

from doc_tool.application.content.table_format import (
    calculate_display_width,
    find_table_range_at_line,
    format_markdown_table,
    is_separator_row,
    is_table_row,
    split_table_cells,
)


class TableFormatTests(unittest.TestCase):
    def test_calculate_display_width(self):
        self.assertEqual(calculate_display_width("abc"), 3)
        self.assertEqual(calculate_display_width("中文"), 4)
        # '中'(2) + ' '(1) + 'a'(1) + ' '(1) + '文'(2) = 7
        self.assertEqual(calculate_display_width("中 a 文"), 7)
        self.assertEqual(calculate_display_width("（全角标点）"), 12)

    def test_split_table_cells(self):
        line = r"| id | name | desc \| note |"
        cells = split_table_cells(line)
        self.assertEqual(cells, ["id", "name", r"desc \| note"])

        # 包含转义反斜杠和末尾未转义管道符的边界测试
        line_with_bs = r"| path\\ | val |"
        cells_bs = split_table_cells(line_with_bs)
        self.assertEqual(cells_bs, [r"path\\", "val"])

    def test_is_table_row_and_separator(self):
        self.assertTrue(is_table_row("| a | b |"))
        self.assertFalse(is_table_row("a | b"))
        self.assertFalse(is_table_row("# 标题"))
        # 仅有单个未转义管道符不算合法表格行
        self.assertFalse(is_table_row(r"| a \| b"))

        self.assertTrue(is_separator_row(["---", ":---:", "---:"]))
        self.assertFalse(is_separator_row(["---", "name", "---:"]))
        self.assertFalse(is_separator_row(["", ""]))

    def test_find_table_range_at_line(self):
        lines = [
            "# Heading",
            "",
            "| col1 | col2 |",
            "| :--- | ---: |",
            "| val1 | val2 |",
            "",
            "Paragraph",
        ]
        self.assertIsNone(find_table_range_at_line(lines, 0))
        self.assertIsNone(find_table_range_at_line(lines, 1))
        self.assertEqual(find_table_range_at_line(lines, 2), (2, 4))
        self.assertEqual(find_table_range_at_line(lines, 3), (2, 4))
        self.assertEqual(find_table_range_at_line(lines, 4), (2, 4))
        self.assertIsNone(find_table_range_at_line(lines, 5))

    def test_format_markdown_table_simple(self):
        raw = """| a | b | c |
|---|---|---|
| 1 | hello | world |
| 20 | x | y |"""
        formatted = format_markdown_table(raw)
        expected = """| a   | b     | c     |
| --- | ----- | ----- |
| 1   | hello | world |
| 20  | x     | y     |"""
        self.assertEqual(formatted, expected)

    def test_format_markdown_table_chinese_and_alignments(self):
        raw = """| 序号 | 字段名 | 说明 |
| :---: | :--- | ---: |
| 1 | id | 主键标识 |
| 2 | user_name | 用户登录名 |"""
        formatted = format_markdown_table(raw)
        lines = formatted.splitlines()
        self.assertEqual(len(lines), 4)
        for l in lines:
            self.assertTrue(l.startswith("| ") and l.endswith(" |"))
        # 居中对齐、左对齐、右对齐
        self.assertIn(":--:", lines[1])
        self.assertIn(":--------", lines[1])
        self.assertIn("---------:", lines[1])


class TableEditorInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_table_tab_navigation_and_row_append(self):
        from doc_tool.ui.content.editor_highlight import _LineNumberedEdit

        editor = _LineNumberedEdit()
        text = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        editor.setPlainText(text)

        # 光标置于第 1 行第 1 个单元格
        c = editor.textCursor()
        c.setPosition(2)
        editor.setTextCursor(c)

        # Tab -> 跳转到第 2 个单元格 ('b')
        handled = editor._handle_table_tab(shift=False)
        self.assertTrue(handled)
        self.assertEqual(editor.textCursor().selectedText(), "b")

        # 光标置于末行第 2 个单元格 ('2')
        last_block = editor.document().findBlockByNumber(2)
        c.setPosition(last_block.position() + 6)
        editor.setTextCursor(c)

        # 在表格末尾按 Tab -> 自动追加新行
        handled = editor._handle_table_tab(shift=False)
        self.assertTrue(handled)
        self.assertEqual(editor.document().blockCount(), 4)
        new_line = editor.document().findBlockByNumber(3).text()
        self.assertTrue(new_line.startswith("|") and new_line.endswith("|"))

        # Shift+Tab -> 应该能往回跳
        handled_back = editor._handle_table_tab(shift=True)
        self.assertTrue(handled_back)


if __name__ == "__main__":
    unittest.main()
