import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from doc_tool.application.content.writer import ContentWriter, WriteResult
from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.asset_batch import AssetBatchService, asset_inventory

class AssetBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.content = self.root / 'content'
        self.content.mkdir()
        self.assets = self.root / 'assets'
        images = self.assets / 'general/images'
        images.mkdir(parents=True)
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGB', (10, 20), 'red').save(data, format='PNG')
        self.raw = data.getvalue()
        (images / 'correct.png').write_bytes(self.raw)
        (images / 'duplicate.png').write_bytes(self.raw)
        for name in ('a.md', 'b.md', 'c.md'):
            (self.content / name).write_text('![甲](images/missing.png =10x20) tail ![乙](images/missing.png)\n```\n![不动](images/missing.png)\n```', encoding='utf-8')
        self.index = ContentIndexService(self.content).build()
        ReferenceScanner(self.index, assets_root=self.assets).scan_all()
        self.writer = ContentWriter(self.content, self.root / '.state', assets_root=self.assets)
        self.service = AssetBatchService(self.writer, self.index)

    def test_partial_exact_spans_dimensions_and_duplicates(self):
        rows = self.service.plan('images/missing.png', 'images/correct.png')
        self.assertEqual(len(rows), 6)
        for row in rows: row.selected = row.source == 'a.md' or (row.source == 'b.md' and row.start == 6)
        result = self.service.apply(rows, confirmed=True)
        self.assertIn('a.md', result['applied'])
        text = (self.content / 'a.md').read_text(encoding='utf-8')
        self.assertIn('![甲](images/correct.png =10x20) tail ![乙](images/correct.png)', text)
        self.assertIn('![不动](images/missing.png)', text)
        self.assertIn('![甲](images/missing.png', (self.content / 'c.md').read_text(encoding='utf-8'))
        inventory = asset_inventory(self.assets, self.index)
        self.assertTrue(all(len(row['duplicates']) == 1 for row in inventory))

    def test_dirty_external_changes_cancel_and_readonly(self):
        rows = self.service.plan('images/missing.png', 'images/correct.png')
        self.assertEqual(self.service.apply(rows)['applied'], [])
        self.service.is_dirty = lambda rel: rel == 'b.md'
        (self.content / 'c.md').write_text('external', encoding='utf-8')
        result = self.service.apply(rows, confirmed=True)
        self.assertEqual(result['applied'], ['a.md'])
        self.assertEqual(set(result['skipped']), {'b.md', 'c.md'})
        self.writer.set_writable(False)
        with self.assertRaises(PermissionError): self.service.apply(rows, confirmed=True)

    def test_midwrite_rollback_and_import_cleanup(self):
        target = self.assets / 'general/images/new.png'
        rows = self.service.plan('images/missing.png', 'images/new.png')
        before = {p: p.read_bytes() for p in self.content.glob('*.md')}
        original = self.writer.write_text
        def write(rel, text, **kwargs):
            if rel == 'b.md': return WriteResult(rel, None, False, error='occupied')
            return original(rel, text, **kwargs)
        with patch.object(self.writer, 'write_text', side_effect=write):
            with self.assertRaises(OSError): self.service.apply(rows, confirmed=True, imported={target: self.raw})
        self.assertFalse(target.exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.content.glob('*.md')})
        rows = self.service.plan('images/missing.png', '../escape.png')
        result = self.service.apply(rows, confirmed=True)
        self.assertEqual(result['applied'], [])
        self.assertEqual(len(result['skipped']), 3)

if __name__ == '__main__': unittest.main()
