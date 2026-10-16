# -*- coding: utf-8 -*-
"""User-initiated request preview. Nothing is sent by constructing this dialog."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout,
)


class EnhancementPreviewDialog(QDialog):
    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("可选增强：确认实际发送内容")
        self.setObjectName("enhancementRequestPreview")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        payload = preview.wire_payload()
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        label = QLabel("目标：{0}\n用途：{1} · 范围：{2}\n正文 {3}/{4} 字符{5}；JSON 请求体 {6} 字节（不含认证头）".format(
            preview.target_description, preview.purpose, preview.scope_label,
            len(preview.text), preview.requested_chars, "，已截断" if preview.truncated else "",
            len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))), self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.payload_view = QPlainTextEdit(self)
        self.payload_view.setObjectName("enhancementActualPayload")
        self.payload_view.setReadOnly(True)
        self.payload_view.setPlainText(serialized)
        layout.addWidget(self.payload_view, 1)
        note = QLabel("仅发送上方冻结的请求体；凭据值不在预览/日志中。取消不请求。返回内容只是候选，不能批准业务事实或自动改稿。", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认并发送一次")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消，不发送")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(min(720, max(400, available.width()-60)),
                        min(520, max(300, available.height()-60)))

    @classmethod
    def confirm(cls, preview, parent=None):
        dialog = cls(preview, parent)
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()
