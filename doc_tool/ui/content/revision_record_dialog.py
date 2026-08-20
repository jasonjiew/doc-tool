# -*- coding: utf-8 -*-
"""修订记录对话框。

``RevisionRecordDialog``：改动面板「生成修订记录」按钮，展示本次变动的定位
清单（``3.7产品管理->3.7.9呼吸机应用升级``）供复制，作者据此到
``_revision_record.md`` 里补写本次改了什么。本对话框不写任何文件——修订记录
只有 ``_revision_record.md`` 一个维护点，合并按该文件覆盖 Word 修订记录表。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RevisionRecordDialog(QDialog):
    """修订记录生成结果：可编辑文本 + 复制到剪贴板。"""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("生成修订记录")
        self.resize(680, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        if text.strip():
            hint_text = (
                "已按当前改动列出变动到了哪些小节，仅供定位；"
                "请改写成本次改了什么，再粘贴到 _revision_record.md 表格末尾。"
            )
        else:
            hint_text = "当前改动中没有可生成修订记录的 Markdown 条目，请先改动内容文件。"
        hint = QLabel(hint_text, self)
        hint.setObjectName("statusMuted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._text = QPlainTextEdit(self)
        self._text.setPlainText(text)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._text, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._status = QLabel("", self)
        self._status.setObjectName("statusMuted")
        actions.addWidget(self._status, 1)
        self._copy_btn = QPushButton("复制到剪贴板", self)
        self._copy_btn.setProperty("btnRole", "primary")
        self._copy_btn.clicked.connect(self._on_copy)
        actions.addWidget(self._copy_btn)
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._text.setFocus()

    def _on_copy(self) -> None:
        """复制当前文本到剪贴板并给出反馈。"""
        QApplication.clipboard().setText(self._text.toPlainText())
        self._status.setText("已复制到剪贴板")
