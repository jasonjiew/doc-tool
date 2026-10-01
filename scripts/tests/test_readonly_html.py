import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from doc_tool.application.export.readonly_html import export_readonly_html
from doc_tool.domain.cancellation import CancellationToken
from doc_tool.domain.errors import CancelledError

class HtmlPreviewTests(unittest.TestCase):
    def test_offline_chinese_assets_source_locations_and_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / '正文'
            content.mkdir()
            assets = root / 'assets'
            folder = assets / 'general/images'
            folder.mkdir(parents=True)
            from PIL import Image
            Image.new('RGB', (3, 4), 'red').save(folder / '中文.png')
            (folder / 'unused.png').write_bytes(b'unused')
            chapter = content / '第1章.md'
            chapter.write_text('# 标题\n![图片](images/中文.png =3x4)\n![缺图](missing.png)\n![越界](../../outside.png)\n<script>alert(1)</script>\n[x](javascript:evil)\n```mermaid\nflowchart TD\nA-->B\n```', encoding='utf-8')
            (content / '第2章.md').write_text('# 第二章', encoding='utf-8')
            before = chapter.read_bytes()
            with patch('doc_tool.application.content.mermaid._render_with_cli', side_effect=AssertionError('no mmdc')):
                result = export_readonly_html(content, assets, root / 'output', '1.2', omitted_unsaved=['第1章.md'])
            self.assertEqual(result.status, '带提醒完成')
            manifest = json.loads((result.directory / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['sources']), 2)
            self.assertEqual(chapter.read_bytes(), before)
            self.assertEqual(len(list((result.directory / 'assets').iterdir())), 1)
            copied = root / '复制离线包'
            shutil.copytree(result.directory, copied)
            text = (copied / 'index.html').read_text(encoding='utf-8')
            self.assertIn('chapter-2', text)
            self.assertIn('line-1', text)
            self.assertNotIn('<script>', text)
            self.assertNotIn('href="javascript:', text)
            self.assertNotIn('src="http', text)
            self.assertIn('图片待补', text)
            single = export_readonly_html(content, assets, root / 'output', rel_path='第2章.md')
            self.assertEqual(single.status, '完成')
            self.assertNotIn('第1章.md', (single.directory / 'index.html').read_text(encoding='utf-8'))
            token = CancellationToken()
            token.request_cancel()
            with self.assertRaises(CancelledError): export_readonly_html(content, assets, root / 'output', cancel_token=token)
            self.assertFalse(list((root / 'output/preview').glob('.tmp-*')))
            with patch('doc_tool.application.export.readonly_html.export_html', side_effect=OSError('disk')):
                with self.assertRaises(OSError): export_readonly_html(content, assets, root / 'output')
            self.assertFalse(list((root / 'output/preview').glob('.tmp-*')))

if __name__ == '__main__': unittest.main()
