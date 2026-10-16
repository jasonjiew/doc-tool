# -*- coding: utf-8 -*-
"""Small optional tab for explanations; the editor and existing result tabs stay intact."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget


class MainflowAdvicePanel(QWidget):
    action_requested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mainflowAdvicePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self._context = QLabel(self)
        self._context.setWordWrap(True)
        self._context.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._context)
        self._steps = QListWidget(self)
        layout.addWidget(self._steps, 1)
        self._reason = QLabel(self)
        self._reason.setWordWrap(True)
        self._reason.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._reason)
        self._execute = QPushButton("执行所选下一步", self)
        self._execute.setObjectName("mainflowExecuteButton")
        layout.addWidget(self._execute)
        self._execute.clicked.connect(self._request)
        self._steps.currentRowChanged.connect(self._selection_changed)
        self._steps.itemActivated.connect(lambda _item: self._request())
        self._report = None

    def set_report(self, report, project_root=""):
        self._report = report
        if report is None:
            self._steps.clear()
            self._reason.clear()
            self._context.setText("当前事实不可读取，请刷新后再执行建议。")
            self._execute.setEnabled(False)
            return
        facts = report.facts
        quality = facts.quality
        self._context.setText("离线建议 · 当前来源：{0} · 未保存 {1} 章\n最近检查：{2} · {3} · 来源 {4}".format(
            facts.source_mode, facts.unsaved_chapters, quality.state, quality.scope_text, quality.source_mode))
        self._steps.clear()
        for step in report.steps:
            self._steps.addItem(step.label)
            item = self._steps.item(self._steps.count()-1)
            item.setData(Qt.ItemDataRole.UserRole, (step.action, project_root, step.round_id))
            item.setToolTip(step.reason)
        if self._steps.count():
            self._steps.setCurrentRow(0)
        self._execute.setEnabled(bool(report.steps))

    def _selection_changed(self, row):
        steps = self._report.steps if self._report is not None else ()
        self._reason.setText(steps[row].reason if 0 <= row < len(steps) else "")

    def _request(self):
        item = self._steps.currentItem()
        if item is not None:
            self.action_requested.emit(*item.data(Qt.ItemDataRole.UserRole))
