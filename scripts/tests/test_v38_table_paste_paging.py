# -*- coding: utf-8 -*-
"""38-A 1.1/1.4：粘贴预览分页、末页查看、完整插入与文本保真。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content import table_grid as grid  # noqa: E402

NL = chr(10)


class PreviewPagingServiceTests(unittest.TestCase):
    def test_pages_cover_all_rows_without_losing_any(self):
        rows = [["r{0}".format(i), "v{0}".format(i)] for i in range(1000)]
        seen = 0
        page = 0
        pages = None
        while True:
            shown, page, pages, total = grid.preview_page(rows, page=page)
            if pages is None:
                pages = pages
            seen += len(shown)
            if page + 1 >= pages:
                break
            page += 1
        self.assertEqual(total, 1000)
        self.assertEqual(pages, 50)
        self.assertEqual(seen, 1000)

    def test_last_page_starts_at_expected_row(self):
        rows = [["r{0}".format(i)] for i in range(1000)]
        shown, page, pages, total = grid.preview_page(rows, page=49)
        self.assertEqual(page, 49)
        self.assertEqual(shown[0], ["r980"])
        self.assertEqual(len(shown), 20)

    def test_page_does_not_change_full_matrix(self):
        rows = [["a"], ["b"], ["c"]]
        _shown, page, pages, total = grid.preview_page(rows, page=99)
        self.assertEqual((page, pages, total), (0, 1, 3))
        self.assertEqual(rows, [["a"], ["b"], ["c"]])


class PasteDialogPagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, text: str):
        from doc_tool.ui.content.table_grid_dialog import TablePasteDialog

        result = grid.parse_clipboard_text(text)
        return TablePasteDialog(result)

    def test_dialog_pages_and_keeps_complete_model(self):
        # 1000×20 TSV，含尾空行列、前导零与公式文本
        lines = []
        for row in range(1000):
            cells = []
            for column in range(20):
                if row == 999 and column >= 18:
                    cells.append("")  # 尾空列
                elif column == 0:
                    cells.append("007")
                elif column == 1:
                    cells.append("=SUM(A1:A2)")
                else:
                    cells.append("r{0}c{1}".format(row, column))
            lines.append("\t".join(cells))
        text = NL.join(lines)
        dialog = self._dialog(text)
        self.assertEqual(dialog._result.row_count, 1000)
        self.assertEqual(dialog._result.column_count, 20)
        self.assertFalse(dialog.next_btn.isEnabled() is False)
        self.assertIn("第 1/50 页", dialog.page_label.text())
        # 翻到末页
        for _ in range(49):
            dialog._turn_page(1)
        self.assertIn("第 50/50 页", dialog.page_label.text())
        self.assertFalse(dialog.next_btn.isEnabled())
        self.assertTrue(dialog.prev_btn.isEnabled())
        self.assertIn("共 1000 行", dialog.page_label.text())
        # 完整模型未因翻页改变
        self.assertEqual(len(dialog._result.rows), 1000)
        self.assertEqual(len(dialog._result.rows[0]), 20)
        markdown = dialog.markdown_text()
        # 插入内容包含末行、前导零与公式文本，且尾空列仍存在
        self.assertIn("r999c17", markdown)
        self.assertIn("007", markdown)
        self.assertIn("=SUM(A1:A2)", markdown)
        # 表头行 + 分隔行 + 1000 数据行 = 1001 行 → 1000 个换行（首行即表头）
        self.assertEqual(markdown.count(NL), 1000)
        self.assertEqual(len(markdown.splitlines()), 1001)
        # 首行表头切换也不改完整模型
        dialog.header_check.setChecked(False)
        self.assertEqual(len(dialog._result.rows), 1000)
        self.assertIn("r999c17", dialog.markdown_text())


if __name__ == "__main__":
    unittest.main()