"""Read-only previews followed by explicit recovery choices."""
import hashlib
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPlainTextEdit, QPushButton, QMessageBox
from doc_tool.application.content.trash import TrashStore


class RecoveryDialog(QDialog):
    def __init__(self, writer, *, rel_path=None, guard=None, on_restored=None, parent=None):
        super().__init__(parent)
        self.writer, self.rel_path = writer, rel_path
        self.guard, self.on_restored = guard, on_restored
        self.trash = TrashStore(writer)
        self.setWindowTitle("本地历史" if rel_path else "回收站（正文 / 资源）")
        self.resize(850, 550)
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.items)
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        for label, callback in [("恢复选中（覆盖前备份）", lambda: self.restore("overwrite")),
                                ("恢复为副本", lambda: self.restore("copy")),
                                ("清理选中的回收文件", self.clean)]:
            button = QPushButton(label)
            button.setEnabled(writer._writable and (rel_path is None or label.startswith("恢复选中")))
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.items.currentRowChanged.connect(self.show_preview)
        self.reload()

    def reload(self):
        self.entries = (self.writer.local_history.list_entries(self.rel_path) if self.rel_path else self.trash.list_entries())
        self.items.clear()
        self.items.addItems([e.created_at + " · " + e.operation if self.rel_path else
                            e.deleted_at + " · " + e.kind + " · " + e.rel_path for e in self.entries])
        if self.entries:
            self.items.setCurrentRow(0)
        else:
            self.preview.setPlainText("没有可用记录。")

    def show_preview(self, row):
        if row < 0 or row >= len(self.entries):
            return
        entry = self.entries[row]
        try:
            if self.rel_path:
                target = self.writer.resolve(self.rel_path)
                self.expected_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
                text = self.writer.local_history.diff(self.rel_path, entry.snapshot_id)
            else:
                from doc_tool.application.content.writer import _resolve_inside
                root, inner = self.writer._split_root(entry.rel_path)
                target = _resolve_inside(root, inner)
                self.expected_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
                text = self.trash.diff(entry) + "\n\n" + self.trash.preview(entry)
            self.preview.setPlainText(text)
        except (OSError, ValueError) as exc:
            self.preview.setPlainText(str(exc))

    def restore(self, mode):
        row = self.items.currentRow()
        if row < 0 or row >= len(self.entries):
            return
        entry = self.entries[row]
        rel = self.rel_path or entry.rel_path
        if self.guard and not self.guard(rel):
            return
        # Saving a dirty editor changes the reviewed target: refresh and require a new choice.
        from doc_tool.application.content.writer import _resolve_inside
        root, inner = self.writer._split_root(rel)
        target = _resolve_inside(root, inner)
        current_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
        if current_hash != getattr(self, "expected_hash", None):
            self.show_preview(row)
            self.preview.appendPlainText("\n目标已变化，差异已刷新；请选择恢复方式。")
            return
        try:
            if self.rel_path:
                result = self.writer.local_history.restore(rel, entry.snapshot_id, self.writer, confirmed=True, expected_sha256=self.expected_hash)
                if not result.written:
                    raise OSError(result.error)
            else:
                rel = self.trash.restore(entry, mode=mode, confirmed=True, expected_sha256=self.expected_hash)
            if self.on_restored:
                self.on_restored(rel)
            self.reload()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "恢复未完成", str(exc))

    def clean(self):
        row = self.items.currentRow()
        if self.rel_path or row < 0:
            return
        entry = self.entries[row]
        if QMessageBox.question(self, "清理选中范围", "永久清理这一份记录：" + entry.rel_path,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.trash.clean([entry], confirmed=True)
            self.reload()
        except OSError as exc:
            QMessageBox.warning(self, "清理失败", str(exc))
