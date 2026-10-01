import json
import tempfile
import unittest
from pathlib import Path
from doc_tool.application.content.history import BuildHistoryStore

class DeliveryHistoryTests(unittest.TestCase):
    def test_legacy_damage_diff_missing_and_readonly_ui(self):
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.build_history_dialog import BuildHistoryDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = BuildHistoryStore(root)
            store.root.mkdir()
            for id, text in [('old', '旧章'), ('new', '新章')]:
                (store.root / (id + '.json')).write_text(json.dumps({'historyId': id, 'completedAt': id, 'contentFiles': {'章.md': text}}), encoding='utf-8')
                folder = store.root / id / 'content'
                folder.mkdir(parents=True)
                (folder / '章.md').write_text(text, encoding='utf-8')
            (store.root / 'bad.json').write_text('{', encoding='utf-8')
            self.assertEqual(len(store.list_entries()), 3)
            self.assertIn('error', store.get('bad').data)
            self.assertEqual(store.diff('old', 'new')['modified'], ['章.md'])
            self.assertIn('新章', store.text_diff('old', 'new', '章.md'))
            with self.assertRaises(ValueError): store.text_diff('old', 'new', '../escape')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            dialog = BuildHistoryDialog(root)
            self.assertFalse(dialog.open_btn.isEnabled())
            dialog.close()
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
            empty = BuildHistoryDialog(root / 'empty')
            self.assertIn('没有交付历史', empty.details.toPlainText())
            empty.close()
            self.assertFalse((root / 'empty').exists())

if __name__ == '__main__': unittest.main()
