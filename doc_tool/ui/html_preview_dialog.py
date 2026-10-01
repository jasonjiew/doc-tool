from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QCheckBox, QPushButton, QPlainTextEdit
from doc_tool.ui.task_bridge import TaskRunner, TaskSpec
from doc_tool.application.export.readonly_html import export_readonly_html


class HtmlPreviewDialog(QDialog):
    def __init__(self, summary, workspace, open_directory, parent=None):
        super().__init__(parent)
        self.summary, self.workspace, self.open_directory = summary, workspace, open_directory
        self.runner = TaskRunner()
        self.last_directory = None
        self.setWindowTitle('只读离线 HTML 快照（非正式发布）')
        self.resize(700, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('默认导出已保存版本；目录/图片随包复制，可断网阅读。'))
        self.scope = QComboBox()
        self.scope.addItem('整项目（既有章节顺序）', None)
        current = workspace.tabs_host.current_rel_path()
        if current: self.scope.addItem('当前章：' + current, current)
        layout.addWidget(self.scope)
        self.save_first = QCheckBox('可选：保存未保存编辑后导出')
        self.save_first.setEnabled(summary.is_writable)
        layout.addWidget(self.save_first)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        self.run_btn = QPushButton('导出只读包')
        self.run_btn.clicked.connect(self.run)
        layout.addWidget(self.run_btn)
        self.cancel_btn = QPushButton('取消当前导出')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.runner.cancel)
        layout.addWidget(self.cancel_btn)
        self.open_btn = QPushButton('打开预览目录')
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self.open_directory(self.last_directory))
        layout.addWidget(self.open_btn)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def run(self):
        if self.runner.is_running: return
        if self.save_first.isChecked():
            failed = self.workspace.tabs_host.save_all()
            if failed: self.details.appendPlainText('部分保存失败，采用其已保存版本：' + ', '.join(failed))
        from doc_tool.application.content.unsaved import collect_unsaved
        omitted = collect_unsaved(self.workspace.tabs_host.editors())
        paths = self.summary.paths
        self.runner.start(TaskSpec(name='readonly-html', target=export_readonly_html,
            args=(paths.content_root, paths.assets_root, paths.output_dir, self.summary.manifest.documentVersion),
            kwargs=dict(rel_path=self.scope.currentData(), omitted_unsaved=omitted)),
            on_event=lambda event: self.details.appendPlainText(event.detail or event.kind), on_done=self.done)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.timer.start()

    def done(self, result):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.timer.stop()
        if result:
            self.last_directory = result.directory
            self.open_btn.setEnabled(True)
            self.details.appendPlainText(result.status + '：' + str(result.directory / 'index.html'))
            for warning in result.warnings:
                self.details.appendPlainText(f'{warning["path"]}:{warning["line"]} {warning["message"]}')
        else: self.details.appendPlainText('导出失败或取消，旧包保持可用。')

    def poll(self): self.runner.poll()

    def reject(self):
        if self.runner.is_running:
            self.runner.cancel()
            return
        super().reject()
