import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from doc_tool.application.content.writer import ContentWriter
from doc_tool.application.content.trash import TrashStore, TrashEntry


class RecoveryEntriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.content = self.root / 'content'
        self.content.mkdir()
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.writer = ContentWriter(self.content, self.root / '.state', assets_root=self.assets)
        self.store = TrashStore(self.writer)

    def delete(self, text):
        (self.content / 'a.md').write_text(text, encoding='utf-8')
        self.assertTrue(self.writer.delete_file('a.md').written)

    def test_repeated_delete_copy_overwrite_and_restore_again(self):
        self.delete('one')
        self.delete('two')
        entries = self.store.list_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual({self.store.preview(e) for e in entries}, {'one', 'two'})
        (self.content / 'a.md').write_text('current', encoding='utf-8')
        copy = self.store.restore(entries[0], confirmed=True)
        self.assertIn('恢复副本', copy)
        self.assertEqual((self.content / 'a.md').read_text(), 'current')
        self.store.restore(entries[0], mode='overwrite', confirmed=True)
        snapshots = self.writer.local_history.list_entries('a.md', include_backup=False)
        self.assertEqual(self.writer.local_history.preview('a.md', snapshots[0].snapshot_id), 'current')
        self.assertEqual(len(self.store.list_entries()), 2)

    def test_cancel_readonly_and_scoped_clean(self):
        self.delete('one')
        entry = self.store.list_entries()[0]
        self.assertIsNone(self.store.restore(entry))
        self.store.clean([entry])
        self.assertTrue(Path(entry.trash_path).exists())
        self.writer.set_writable(False)
        with self.assertRaises(PermissionError): self.store.restore(entry, confirmed=True)
        with self.assertRaises(PermissionError): self.store.clean([entry], confirmed=True)
        self.assertFalse(self.writer.restore_file('a.md', status='deleted', trash_path=entry.trash_path).written)
        self.writer.set_writable(True)
        self.store.clean([entry], confirmed=True)
        self.assertFalse(Path(entry.trash_path).exists())

    def test_legacy_resources_boundary_and_occupied_failure(self):
        asset = self.assets / 'image.png'
        asset.write_bytes(b'old image')
        self.assertTrue(self.writer.delete_asset('image.png').written)
        entry = self.store.list_entries()[0]
        asset.write_bytes(b'current image')
        self.store.restore(entry, mode='overwrite', confirmed=True)
        self.assertEqual(asset.read_bytes(), b'old image')
        self.assertEqual(next(Path(entry.trash_path).parent.glob('before-overwrite-*')).read_bytes(), b'current image')
        bad = TrashEntry('x', 'assets/../outside', '', 'resource', entry.trash_path)
        with self.assertRaises(ValueError): self.store.restore(bad, confirmed=True)
        bad.trash_path = str(self.root / 'outside')
        with self.assertRaises(ValueError): self.store.preview(bad)
        with patch('doc_tool.application.content.trash.atomic_write_bytes', side_effect=PermissionError('occupied')):
            with self.assertRaises(OSError): self.store.restore(entry, mode='overwrite', confirmed=True)
        self.assertEqual(asset.read_bytes(), b'old image')
        legacy = self.store.root / 'legacy.md'
        legacy.write_text('legacy', encoding='utf-8')
        from doc_tool.application.content.writer import ChangeEntry
        self.writer.manifest.record(ChangeEntry('delete', 'legacy.md', trash_path=str(legacy)))
        self.assertTrue(any(e.operation_id.startswith('legacy:') for e in self.store.list_entries()))

    def test_dialog_readonly_no_writes(self):
        from PySide6.QtWidgets import QApplication, QPushButton
        from doc_tool.ui.content.recovery_dialog import RecoveryDialog
        app = QApplication.instance() or QApplication([])
        self.delete('one')
        self.writer.set_writable(False)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        dialog = RecoveryDialog(self.writer)
        self.assertTrue(all(not b.isEnabled() for b in dialog.findChildren(QPushButton)))
        dialog.close()
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

if __name__ == '__main__': unittest.main()
