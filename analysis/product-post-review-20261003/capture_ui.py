"""在真实 QSS/中文字体下取样新界面，保留图片和控件几何。"""
from pathlib import Path
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / '.vendor/site-packages'), str(ROOT / 'tmp/v26-test-deps')]
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton
from PySide6.QtGui import QFontDatabase
from doc_tool.ui.styles import apply_theme
from doc_tool.ui.content.editor_panel import EditorPanel
from doc_tool.ui.content.table_grid_dialog import TableGridDialog, TablePasteDialog
from doc_tool.ui.standard_pack_dialog import StandardPackDialog
from doc_tool.ui.rd_workspace import RdWorkspaceDialog
from doc_tool.application.content import table_grid as grid
from scripts.tests import core_fixtures as fixtures

app = QApplication.instance() or QApplication([])
for name in ('msyh.ttc', 'msyhbd.ttc', 'msyhl.ttc'):
    path = Path('C:/Windows/Fonts') / name
    if path.is_file():
        QFontDatabase.addApplicationFont(str(path))
base = Path(__file__).parent / (sys.argv[1] if len(sys.argv) > 1 else 'ui-before')
base.mkdir(parents=True, exist_ok=True)
work = fixtures.scratch_dir('post-review-visual')
project = fixtures.two_chapter_project(work / 'project')
model = grid.model_from_matrix([['参数', '说明', '空列'], ['0012', '中文内容', ''], ['类型', '第一行<br>第二行', '日期']], alignments=['left', 'center', 'right'])

class Writer:
    def resolve(self, rel_path):
        return project / 'content' / 'general' / rel_path

editor = EditorPanel(Writer())
editor.load('1 概述/1.1 文档.md', '# 文档\n\n' + model.serialize() + '\n\n最后一段。')
widgets = [('editor', editor), ('grid', TableGridDialog(model)), ('paste', TablePasteDialog(grid.parse_clipboard_text('字段\t类型\n名称\t文本'))), ('pack', StandardPackDialog(draft_dir=str(work / 'draft'), project_root=str(project))), ('rd', RdWorkspaceDialog(root=str(project)))]
records = []
try:
    for dark in (False, True):
        apply_theme(app, dark=dark)
        editor.set_dark(dark)
        for width, height in ((1024, 640), (1280, 720)):
            for name, widget in widgets:
                widget.resize(width, height)
                widget.show()
                for _ in range(5):
                    app.processEvents()
                tabs = getattr(widget, 'tabs', None)
                pages = range(tabs.count()) if tabs is not None else [0]
                for page in pages:
                    if tabs is not None:
                        tabs.setCurrentIndex(page)
                    for _ in range(3):
                        app.processEvents()
                    filename = f'{name}-{page}-{width}x{height}-{"dark" if dark else "light"}.png'
                    assert widget.grab().save(str(base / filename))
                    buttons = []
                    for btn in widget.findChildren(QPushButton) + widget.findChildren(QToolButton):
                        if btn.isVisible():
                            buttons.append({'text': btn.text(), 'width': btn.width(), 'hint': btn.sizeHint().width(), 'minimumHint': btn.minimumSizeHint().width()})
                    record = {'file': filename, 'width': widget.width(), 'height': widget.height(), 'requested': [width, height], 'minimumHint': [widget.minimumSizeHint().width(), widget.minimumSizeHint().height()], 'buttons': buttons}
                    if name == 'editor':
                        record['toolbar'] = {key: list(getattr(widget, key).geometry().getRect()) for key in ('_md_toolbar', '_file_label', '_save_btn')}
                    records.append(record)
                widget.hide()
    (base / 'geometry.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'screenshots': len(records), 'sizes': sorted({(r['width'], r['height']) for r in records}), 'geometry': str(base / 'geometry.json')}, ensure_ascii=False))
finally:
    for name, widget in widgets:
        widget.close()
        widget.deleteLater()
    app.processEvents()
    assert work.resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(work)
