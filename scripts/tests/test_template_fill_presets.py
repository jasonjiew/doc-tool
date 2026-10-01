import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from doc_tool.application.template_fill_presets import TemplateFillPresets, fresh_output
from doc_tool.application.template_fill import StyleInfo, TemplateStyles

class PresetTests(unittest.TestCase):
    def test_recipes_changes_jobs_corruption_and_record_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / '模板.docx'
            template.write_bytes(b'old')
            store = TemplateFillPresets(root)
            first = store.save_recipe('需求', {'template': str(template), 'mapping': {'A': 1, 'gone': 2}})
            second = store.save_recipe('设计', {'template': str(template), 'mapping': {}})
            self.assertEqual(len(TemplateFillPresets(root).recipes), 2)
            template.write_bytes(b'new')
            styles = TemplateStyles({}, {1: 'A'}, '', paragraph_styles=[StyleInfo('A', '章')])
            self.assertEqual(store.resolve_recipe(first, styles)['mapping'], {'A': 1})
            sources = [root / 'second.md', root / 'first.md']
            for i in range(25): store.record_job(sources, first, status='cancelled' if i % 2 else '待刷新')
            self.assertEqual(len(store.jobs), 20)
            self.assertEqual([s['path'] for s in store.jobs[0]['sources']], list(map(str, sources)))
            with patch('doc_tool.application.template_fill_presets.atomic_write', side_effect=OSError('disk')):
                self.assertIn('已保留', store.record_job(sources, first, status='部分完成', output='result.docx'))
            store.delete_recipe(second['recipeId'])
            self.assertEqual(len(store.recipes), 1)
            broken = root / 'template-fill-recipes.json'
            broken.write_text('{broken', encoding='utf-8')
            damaged = TemplateFillPresets(root)
            self.assertEqual(damaged.recipes, [])
            self.assertEqual(broken.read_text(), '{broken')
            damaged.save_recipe('new', {})
            self.assertTrue(list(root.glob('*.damaged-*')))
            output = root / 'result.docx'
            output.write_bytes(b'old')
            self.assertNotEqual(fresh_output(output), output)
            self.assertNotEqual(fresh_output(template, [template]), template)

if __name__ == '__main__': unittest.main()
