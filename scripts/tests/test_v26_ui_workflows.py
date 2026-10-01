import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class V26UiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_recovery_cancel_stale_and_dirty_editor_preserved(self):
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.recovery_dialog import RecoveryDialog
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / 'content'
            content.mkdir()
            path = content / 'a.md'
            path.write_text('old', encoding='utf-8')
            writer = ContentWriter(content, root / '.state')
            writer.write_text('a.md', 'current')
            dialog = RecoveryDialog(writer, rel_path='a.md', guard=lambda _: False)
            dialog.restore('overwrite')
            self.assertEqual(path.read_text(), 'current')
            dialog.guard = lambda _: True
            path.write_text('external', encoding='utf-8')
            dialog.restore('overwrite')
            self.assertEqual(path.read_text(), 'external')
            self.assertIn('目标已变化', dialog.preview.toPlainText())
            dialog.close()

    def test_recipe_switches_and_actual_html_default_saved_buffer(self):
        from doc_tool.application.template_fill_presets import TemplateFillPresets
        from doc_tool.ui.template_fill_dialog import TemplateFillDialog
        from doc_tool.resources import resource_path
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.editor_panel import EditorPanel
        from doc_tool.ui.html_preview_dialog import HtmlPreviewDialog
        from doc_tool.domain.paths import ProjectPaths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            presets = TemplateFillPresets(root / 'user')
            template = resource_path('generic-template.docx')
            first = presets.save_recipe('一', dict(template=template, mapping={'Heading1': 1}, clean=True, refresh=False))
            second = presets.save_recipe('二', dict(template=template, mapping={'Heading2': 2}, clean=False, refresh=True))
            with patch('doc_tool.application.template_fill_presets.TemplateFillPresets', return_value=presets), patch('doc_tool.ui.template_fill_dialog.load_last_template', return_value=None), patch('doc_tool.ui.template_fill_dialog.save_last_template'):
                dialog = TemplateFillDialog()
                dialog._recipe_combo.setCurrentIndex(1)
                self.assertTrue(dialog._clean_body.isChecked())
                self.assertEqual(dialog._style_map, {'Heading1': 1})
                dialog._recipe_combo.setCurrentIndex(2)
                self.assertTrue(dialog._refresh_fields.isChecked())
                self.assertFalse(dialog._clean_body.isChecked())
                dialog.close()
            paths = ProjectPaths(root / 'project')
            paths.content_root.mkdir(parents=True)
            chapter = paths.content_root / 'a.md'
            chapter.write_text('# saved', encoding='utf-8')
            writer = ContentWriter(paths.content_root, paths.state_dir, assets_root=paths.assets_root)
            editor = EditorPanel(writer, writable=False)
            editor.load('a.md', '# saved', lazy_preview=True)
            editor._editor.setPlainText('# unsaved')
            editor._dirty = True
            editor._outline_panel.refresh()
            self.assertEqual(editor._outline_panel.items.item(0).text(), 'unsaved')
            self.assertTrue(editor._editor.isReadOnly())
            tabs = SimpleNamespace(current_rel_path=lambda: 'a.md', editors=lambda: [editor], save_all=lambda: [])
            summary = SimpleNamespace(paths=paths, is_writable=False, manifest=SimpleNamespace(documentVersion='1'))
            html = HtmlPreviewDialog(summary, SimpleNamespace(tabs_host=tabs), lambda _: None)
            self.assertFalse(html.save_first.isChecked())
            self.assertFalse(html.save_first.isEnabled())
            captured = []
            with patch.object(html.runner, 'start', side_effect=lambda spec, **kwargs: captured.append(spec)):
                html.run()
            self.assertEqual(captured[0].kwargs['omitted_unsaved'], ['a.md'])
            self.assertIsNone(captured[0].kwargs['rel_path'])
            html.timer.stop()
            html.close()
            editor.close()

if __name__ == '__main__': unittest.main()
