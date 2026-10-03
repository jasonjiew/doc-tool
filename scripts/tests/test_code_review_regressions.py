# -*- coding: utf-8 -*-
"""代码审查回归：来源身份、活缓冲、部分写入与父章节快照。"""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.replace import ReplaceService
from doc_tool.application.content.writer import ContentWriter
from doc_tool.application.project_from_markdown import create_project_from_markdown
from doc_tool.application.effective_snapshot import capture_snapshot, mark_source_updated
from doc_tool.application.intake_contract import ExportScope, SCOPE_CURRENT_CHAPTER
from doc_tool.domain.manifest import ProjectManifest


class ReviewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='code-review-')
        self.root = Path(self.temp.name)
        self.content = self.root / 'content'
        self.content.mkdir()
        self.state = self.root / '.state'
        self.state.mkdir()
        self.writer = ContentWriter(self.content, self.state)
        self.panels = []
        self.buffer = {}

    def tearDown(self):
        for panel in self.panels:
            panel.deleteLater()
        self.temp.cleanup()

    def write(self, rel, text):
        path = self.content / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def service(self):
        return ReplaceService(ContentIndexService(self.content).build())

    def panel(self, current='1.md', on_applied=None):
        from doc_tool.ui.content.replace_panel import ReplacePanel
        def apply(rel, text):
            self.buffer[rel] = text
            return True
        panel = ReplacePanel(self.service(), self.writer,
            scope_provider=lambda: ('current', current, []),
            live_text_provider=lambda rel: self.buffer.get(rel),
            buffer_applier=apply, on_applied=on_applied)
        self.panels.append(panel)
        return panel

    def search(self, panel, query='甲', scope=1):
        panel._scope_box.setCurrentIndex(scope)
        panel._find_entry.setText(query)
        panel._replace_entry.setText('乙')
        panel.find_all()
        if panel._tree.topLevelItemCount():
            panel._tree.setCurrentItem(panel._tree.topLevelItem(0))

    def lint_panel(self):
        from doc_tool.application.content.lint import ContentLinter, TermStore
        from doc_tool.application.content.quality_rules import QualityRulesConfig
        from doc_tool.ui.content.lint_panel import LintPanel
        rules = QualityRulesConfig(self.state, 'general')
        def scoped(paths, overrides):
            index = ContentIndexService(self.content, override_texts=overrides).build(save_cache=False)
            return ContentLinter(index, rules)
        def apply(rel, text):
            self.buffer[rel] = text
            return True
        panel = LintPanel(ContentLinter(ContentIndexService(self.content).build(), rules),
            TermStore(self.state), writer=self.writer,
            scope_provider=lambda: ('current', '1.md', ['1.md']),
            live_text_provider=lambda rel: self.buffer.get(rel),
            scoped_linter_provider=scoped, buffer_applier=apply,
            confirm_fix=lambda *args: True)
        self.panels.append(panel)
        panel._scope_combo.setCurrentIndex(1)
        panel.run_check()
        return panel

    def manifest(self):
        (self.root / 'assets').mkdir(exist_ok=True)
        ProjectManifest(documentType='general', documentNo='REVIEW',
            documentName='Review', documentVersion='1.0', sourceSha256='',
            paths={'contentRoot': 'content', 'assetRoot': 'assets', 'tableRoot': 'assets/tables'}).save(self.root)

    def test_duplicate_markdown_names_keep_their_own_images(self):
        sources = []
        for name, payload in [('left', b'left'), ('right', b'right')]:
            directory = self.root / name
            directory.mkdir()
            source = directory / 'same.md'
            source.write_text('![figure](image.png)\n', encoding='utf-8')
            (directory / 'image.png').write_bytes(payload)
            sources.append(source)
        project = self.root / 'imported'
        result = create_project_from_markdown(sources, project)
        self.assertTrue(result.ok, result.errors)
        for chapter, expected in zip(result.chapters, [b'left', b'right']):
            import re
            text = (project / 'content' / chapter).read_text(encoding='utf-8')
            resource = re.search(r'\(([^)]+)\)', text).group(1)
            self.assertEqual((project / 'assets/general' / resource).read_bytes(), expected)

    def test_import_location_skips_claimed_anchor_lines(self):
        from doc_tool.adapters.importer import locate_extraction_lines
        self.write('1.md', 'same text\n\nsame text\n')
        entries = [dict(line=1, text='same text'), dict(line=3, text='same text')]
        extraction = SimpleNamespace(unsupported_map=entries, image_map=[], table_map=[])
        self.assertEqual(locate_extraction_lines(extraction, self.content), 2)
        self.assertEqual([entry['line'] for entry in entries], [1, 3])

    def test_failed_buffer_replace_never_saves_to_disk(self):
        disk = self.write('1.md', '磁盘甲\n')
        service = self.service()
        overrides = {'1.md': '缓冲甲\n'}
        matches = service.find_matches('甲', text_overrides=overrides)
        for applier in [None, lambda *args: False, lambda *args: (_ for _ in ()).throw(RuntimeError('closed'))]:
            with self.subTest(applier=applier):
                results = service.apply_matches(matches, '乙', self.writer,
                    text_overrides=overrides, buffer_applier=applier)
                self.assertFalse(results[0].written)
                self.assertEqual(disk.read_text(encoding='utf-8'), '磁盘甲\n')

    def test_replace_one_rescans_updated_buffer(self):
        self.write('1.md', '磁盘甲\n')
        self.buffer['1.md'] = '甲 甲\n'
        panel = self.panel()
        self.search(panel)
        panel.replace_one()
        self.assertEqual(self.buffer['1.md'], '乙 甲\n')
        self.assertEqual(len(panel._matches), 1)
        panel._tree.setCurrentItem(panel._tree.topLevelItem(0))
        panel.replace_one()
        self.assertEqual(self.buffer['1.md'], '乙 乙\n')
        self.assertEqual(panel._matches, [])

    def test_replace_preserves_edits_after_preview(self):
        self.write('1.md', '磁盘甲\n')
        self.buffer['1.md'] = '甲\n'
        panel = self.panel()
        self.search(panel)
        self.buffer['1.md'] += '查找后的新正文\n'
        panel.replace_one()
        self.assertEqual(self.buffer['1.md'], '乙\n查找后的新正文\n')

    def test_changed_match_line_does_not_overwrite_buffer(self):
        self.write('1.md', '磁盘甲\n')
        self.buffer['1.md'] = '甲\n'
        panel = self.panel()
        self.search(panel)
        self.buffer['1.md'] = '新的甲正文\n'
        panel.replace_one()
        self.assertEqual(self.buffer['1.md'], '新的甲正文\n')
        self.assertIn('失败', panel._status_label.text())

    def test_document_replace_also_reads_live_buffers(self):
        self.write('1.md', '没有命中\n')
        self.buffer['1.md'] = '甲\n'
        panel = self.panel()
        self.search(panel, scope=0)
        self.assertEqual(len(panel._matches), 1)

    def test_empty_current_scope_does_not_expand_to_document(self):
        self.write('1.md', '甲\n')
        panel = self.panel(current=None)
        self.search(panel)
        self.assertEqual(panel._matches, [])

    def test_partial_replace_refreshes_successful_files(self):
        self.write('1.md', '甲\n')
        changed = self.write('2.md', '甲\n')
        callbacks = []
        panel = self.panel(on_applied=lambda: callbacks.append(True))
        self.search(panel, scope=0)
        changed.write_text('external edit\n', encoding='utf-8')
        from PySide6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            panel.replace_all()
        self.assertEqual(self.writer.resolve('1.md').read_text(encoding='utf-8'), '乙\n')
        self.assertTrue(callbacks, '部分成功也必须刷新索引和界面')

    def test_lint_failure_never_saves_live_buffer(self):
        disk = self.write('1.md', '#heading\n磁盘\n')
        self.buffer['1.md'] = '#heading\n缓冲\n'
        panel = self.lint_panel()
        panel._buffer_applier = lambda *args: False
        self.assertFalse(panel.quick_fix_issue(panel._issues[0]))
        self.assertEqual(disk.read_text(encoding='utf-8'), '#heading\n磁盘\n')
        self.assertEqual(self.buffer['1.md'], '#heading\n缓冲\n')

    def test_lint_does_not_overwrite_edits_after_check(self):
        self.write('1.md', '#heading\n磁盘\n')
        self.buffer['1.md'] = '#heading\n缓冲\n'
        panel = self.lint_panel()
        self.buffer['1.md'] += '检查后的编辑\n'
        self.assertFalse(panel.quick_fix_issue(panel._issues[0]))
        self.assertTrue(self.buffer['1.md'].endswith('检查后的编辑\n'))

    def test_lint_undo_failure_keeps_disk_and_history(self):
        disk = self.write('1.md', '#heading\n磁盘\n')
        self.buffer['1.md'] = '#heading\n缓冲\n'
        panel = self.lint_panel()
        self.assertTrue(panel.quick_fix_issue(panel._issues[0]))
        fixed = self.buffer['1.md']
        panel._buffer_applier = lambda *args: False
        self.assertFalse(panel.undo_last_fix())
        self.assertEqual(self.buffer['1.md'], fixed)
        self.assertEqual(disk.read_text(encoding='utf-8'), '#heading\n磁盘\n')
        self.assertEqual(len(panel._fix_history), 1)

    def test_lint_undo_keeps_later_manual_edits(self):
        self.write('1.md', '#heading\n磁盘\n')
        self.buffer['1.md'] = '#heading\n缓冲\n'
        panel = self.lint_panel()
        self.assertTrue(panel.quick_fix_issue(panel._issues[0]))
        self.buffer['1.md'] += '修复后的编辑\n'
        self.assertFalse(panel.undo_last_fix())
        self.assertTrue(self.buffer['1.md'].endswith('修复后的编辑\n'))

    def test_snapshot_captures_index_resources_and_buffers(self):
        self.write('第1章 Overview/_index.md', '![figure](image.png)\n')
        self.manifest()
        (self.root / 'assets/image.png').write_bytes(b'image')
        snapshot = capture_snapshot(self.root, buffer_texts={
            '第1章 Overview/_index.md': 'buffer text\n![figure](image.png)\n'})
        work = Path(snapshot.workDir)
        self.assertEqual((work / 'content/第1章 Overview/_index.md').read_text(encoding='utf-8'),
            'buffer text\n![figure](image.png)\n')
        self.assertEqual((work / 'assets/image.png').read_bytes(), b'image')
        self.assertIn('第1章 Overview/_index.md', snapshot.unsavedChapters)

    def test_index_changes_invalidate_snapshot_cache_and_source_status(self):
        index = self.write('第1章 Overview/_index.md', 'first\n')
        self.manifest()
        first = capture_snapshot(self.root)
        index.write_text('second\n', encoding='utf-8')
        self.assertTrue(mark_source_updated(first))
        second = capture_snapshot(self.root)
        self.assertNotEqual(first.cacheKey, second.cacheKey)

    def test_scoped_snapshot_includes_all_parent_indexes(self):
        self.write('第1章 Overview/_index.md', 'top parent\n')
        self.write('第1章 Overview/1.1 Detail/_index.md', 'direct parent\n')
        rel = '第1章 Overview/1.1 Detail/1.1.1 Leaf.md'
        self.write(rel, 'leaf\n')
        self.write('第2章 Other/_index.md', 'outside\n')
        self.manifest()
        snapshot = capture_snapshot(self.root,
            scope=ExportScope(kind=SCOPE_CURRENT_CHAPTER, current=rel))
        work = Path(snapshot.workDir) / 'content'
        self.assertTrue((work / '第1章 Overview/_index.md').is_file())
        self.assertTrue((work / '第1章 Overview/1.1 Detail/_index.md').is_file())
        self.assertFalse((work / '第2章 Other/_index.md').exists())

    def test_workspace_handles_inactive_dirty_tabs(self):
        from doc_tool.ui.content.workspace import ContentWorkspace
        edits = []
        inactive = SimpleNamespace(is_dirty=lambda: True, plain_text=lambda: 'unsaved',
            apply_buffer_text=lambda text: edits.append(text) or True)
        active = SimpleNamespace(current_rel_path=lambda: '2.md')
        host = SimpleNamespace(tabs_host=SimpleNamespace(current_editor=lambda: active,
            editor_for=lambda rel: inactive if rel == '1.md' else None))
        self.assertEqual(ContentWorkspace._live_buffer_text(host, '1.md'), 'unsaved')
        self.assertTrue(ContentWorkspace._apply_buffer_text(host, '1.md', 'updated'))
        self.assertEqual(edits, ['updated'])

    def test_document_lint_uses_live_buffer(self):
        self.write('1.md', '#heading\n磁盘\n')
        self.buffer['1.md'] = '# heading\n缓冲\n'
        panel = self.lint_panel()
        panel._scope_combo.setCurrentIndex(0)
        panel.run_check()
        self.assertEqual(panel._issues, [])

    def test_empty_current_lint_scope_never_reports_other_files(self):
        self.write('1.md', '#heading\n磁盘\n')
        panel = self.lint_panel()
        panel._scope_provider = lambda: ('current', None, [])
        panel.run_check()
        self.assertEqual(panel._issues, [])
        self.assertEqual(panel.quick_fix_all_in_project(), 0)

    def test_lint_without_scoped_index_still_respects_scope(self):
        self.write('1.md', '#heading\n')
        self.write('2.md', '#other\n')
        panel = self.lint_panel()
        panel._scoped_linter_provider = None
        panel.run_check()
        self.assertEqual({issue.rel_path for issue in panel._issues}, {'1.md'})


    def test_lint_preserves_edits_made_during_confirmation(self):
        self.write('1.md', '#heading\n磁盘\n')
        self.buffer['1.md'] = '#heading\n缓冲\n'
        panel = self.lint_panel()
        def confirm(*args):
            self.buffer['1.md'] += '确认期间的编辑\n'
            return True
        panel._confirm_fix = confirm
        self.assertFalse(panel.quick_fix_issue(panel._issues[0]))
        self.assertTrue(self.buffer['1.md'].endswith('确认期间的编辑\n'))

    def test_lint_preserves_disk_edits_made_during_confirmation(self):
        disk = self.write('1.md', '#heading\n磁盘\n')
        panel = self.lint_panel()
        def confirm(*args):
            disk.write_text('外部的新正文\n', encoding='utf-8')
            return True
        panel._confirm_fix = confirm
        self.assertFalse(panel.quick_fix_issue(panel._issues[0]))
        self.assertEqual(disk.read_text(encoding='utf-8'), '外部的新正文\n')


if __name__ == '__main__':
    unittest.main()
