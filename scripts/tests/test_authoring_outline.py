import tempfile
import time
import unittest
from pathlib import Path
from doc_tool.application.content.authoring_outline import buffer_summary

class OutlineTests(unittest.TestCase):
    def test_buffer_counts_fences_comments_and_long_document(self):
        text = '# 标题\n中文 English_1\n```python\n# fake\n假的 code\n```\n<!-- TBL: control -->\n![图](a.png)\n| A | B |\n|---|---|\n'
        s = buffer_summary(text, '中文')
        self.assertEqual(s['headings'], [(1, '标题', 1)])
        self.assertEqual(s['selection'], 2)
        self.assertEqual(s['raw'], len(text))
        self.assertEqual(s['cjk'], 5)
        self.assertEqual(s['tables'], 1)
        self.assertEqual(s['images'], 1)
        sample = text * 5000
        start = time.perf_counter()
        long = buffer_summary(sample)
        self.assertEqual(len(long['headings']), 5000)
        elapsed = time.perf_counter() - start
        print(f'A26-8: {len(sample)} characters, outline/statistics {elapsed:.3f}s')
        self.assertLess(elapsed, 2.0)

    def test_readonly_unsaved_filter_and_navigation(self):
        from PySide6.QtWidgets import QApplication, QPlainTextEdit
        from doc_tool.ui.content.outline_panel import OutlinePanel
        app = QApplication.instance() or QApplication([])
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        located = []
        panel = OutlinePanel(editor, located.append)
        editor.setPlainText('# 未保存\ntext\n## 第二节')
        panel.refresh()
        self.assertEqual(panel.items.count(), 2)
        panel.filter.setText('第二')
        self.assertEqual(panel.items.count(), 1)
        panel.items.itemClicked.emit(panel.items.item(0))
        self.assertEqual(located, [3])
        panel.close()

if __name__ == '__main__': unittest.main()
