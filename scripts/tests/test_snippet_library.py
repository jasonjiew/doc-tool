import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from doc_tool.application.content.snippets import SnippetStore, Snippet, BUILTIN_SNIPPETS, decode_library

class SnippetLibraryTests(unittest.TestCase):
    def test_layers_search_utf8_merge_cancel_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'snippets.json'
            store = SnippetStore(str(path))
            self.assertEqual(len(store.library()), 6)
            self.assertEqual(len(store.library('接口')), 1)
            self.assertTrue(store.add(Snippet('用户', '说明', '${1:中文 English}\n<script>code</script>')))
            incoming = decode_library(store.export_library(store.snippets()))
            before = path.read_bytes()
            self.assertEqual(store.merge_library(incoming), [])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(store.merge_library(incoming, confirmed=True), [])
            self.assertEqual(store.merge_library(incoming, conflicts='rename', confirmed=True), ['用户-1'])
            replacement = [Snippet('用户', '新说明', 'new')]
            store.merge_library(replacement, conflicts='replace', confirmed=True)
            self.assertEqual(store.find('用户').body, 'new')
            before = path.read_bytes()
            with patch('doc_tool.application.content.snippets.os.replace', side_effect=OSError('disk')):
                with self.assertRaises(OSError): store.merge_library([Snippet('new', '', '')], confirmed=True)
            self.assertIsNone(store.find('new'))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError): decode_library('{broken')
            copy = Snippet(BUILTIN_SNIPPETS[0].trigger + '-副本', 'copy', '自定义')
            self.assertTrue(store.add(copy))
            self.assertEqual(len(SnippetStore(str(path)).library()), 9)

    def test_search_ui_and_readonly_insertion(self):
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.content.snippet_dialog import SnippetDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            store = SnippetStore(str(Path(tmp) / 'snippets.json'))
            dialog = SnippetDialog(store, writable=False)
            dialog._search.setText('时序')
            self.assertEqual(dialog._list.count(), 1)
            dialog._list.setCurrentRow(0)
            emitted = []
            dialog.insert_requested.connect(emitted.append)
            dialog._on_insert()
            self.assertEqual(emitted, [])
            dialog.close()

if __name__ == '__main__': unittest.main()
