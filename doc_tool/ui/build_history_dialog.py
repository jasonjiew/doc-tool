"""Browse archived delivery metadata and chapter differences without writing."""
from pathlib import Path
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPlainTextEdit, QPushButton, QAbstractItemView
from doc_tool.application.content.history import BuildHistoryStore


class BuildHistoryDialog(QDialog):
    def __init__(self, state_dir, *, open_artifact=None, parent=None):
        super().__init__(parent)
        self.store = BuildHistoryStore(state_dir)
        self.open_artifact = open_artifact
        self.entries = self.store.list_entries()
        self.setWindowTitle('交付历史（只读章节快照）')
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items.addItems([f'{e.document_version or "未记录"} · {e.completed_at or "未记录"} · 应用 {e.data.get("appVersion") or "未记录"} · {"正式" if e.formal else "诊断/待刷新"}' for e in self.entries])
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.items)
        layout.addWidget(self.details, 1)
        row = QHBoxLayout()
        self.open_btn = QPushButton('打开选中产物')
        self.open_btn.clicked.connect(self.open_selected)
        compare = QPushButton('比较选中两版章节')
        compare.clicked.connect(self.compare_selected)
        row.addWidget(self.open_btn)
        row.addWidget(compare)
        layout.addLayout(row)
        self.items.currentRowChanged.connect(self.show_entry)
        if self.entries:
            self.items.setCurrentRow(0)
        else:
            self.details.setPlainText('没有交付历史；模板填充任务见模板填充最近任务。')
            self.open_btn.setEnabled(False)

    def show_entry(self, row):
        if row < 0: return
        e = self.store.get(self.entries[row].history_id)
        d = e.data
        self.details.setPlainText(d.get('error') or '\n'.join([
            '产物：' + str(d.get('outputPath') or '未记录'),
            '产物状态：' + ('可打开' if e.output_exists else '缺失或未记录'),
            '检查摘要：' + (str(d.get('stages')) if d.get('stages') else '未记录'),
            '发布说明：' + str(d.get('publishNotes') or '未记录')]))
        self.open_btn.setEnabled(e.output_exists and bool(self.open_artifact))

    def open_selected(self):
        row = self.items.currentRow()
        if row >= 0:
            e = self.store.get(self.entries[row].history_id)
            if e.output_exists and self.open_artifact:
                self.open_artifact(Path(str(e.data['outputPath'])))

    def compare_selected(self):
        selected = [self.entries[self.items.row(item)] for item in self.items.selectedItems()]
        if len(selected) != 2:
            self.details.setPlainText('请选择两条历史记录。')
            return
        older, newer = sorted(selected, key=lambda e: (e.completed_at, e.history_id))
        if any(e.data.get('error') for e in selected):
            self.details.setPlainText('损坏记录无法比较。')
            return
        try:
            changes = self.store.diff(older.history_id, newer.history_id)
            text = []
            for kind, paths in changes.items():
                for rel in paths:
                    text.append(kind + ': ' + rel + '\n' + self.store.text_diff(older.history_id, newer.history_id, rel))
            self.details.setPlainText('\n\n'.join(text) or '章节内容没有变化。')
        except (OSError, ValueError) as exc:
            self.details.setPlainText('快照不可用：' + str(exc))
