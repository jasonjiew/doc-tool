# -*- coding: utf-8 -*-
"""代码片段管理器对话框（增删改 + 预览 + 插入）。

编辑内容经 ``SnippetStore`` 持久化（用户级 ``snippets.json``）。底部
「插入选中片段」发出 ``insert_requested`` 信号，编辑器据此把模板写入光标处。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.snippets import Snippet, expand_placeholders


class SnippetDialog(QDialog):
    """代码片段管理器。"""

    insert_requested = Signal(object)  # Snippet

    def __init__(self, store, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("代码片段管理器")
        self.setMinimumSize(600, 440)

        layout = QVBoxLayout(self)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("片段列表："))
        self._list = QListWidget(self)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(lambda _item: self._on_edit())
        left.addWidget(self._list, 1)

        btn_col = QVBoxLayout()
        add_btn = QPushButton("新增", self)
        add_btn.clicked.connect(self._on_add)
        edit_btn = QPushButton("编辑", self)
        edit_btn.clicked.connect(self._on_edit)
        delete_btn = QPushButton("删除", self)
        delete_btn.clicked.connect(self._on_delete)
        btn_col.addWidget(add_btn)
        btn_col.addWidget(edit_btn)
        btn_col.addWidget(delete_btn)
        btn_col.addStretch(1)
        left.addLayout(btn_col)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        right.addWidget(QLabel("预览（占位符已展开）："))
        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)
        right.addWidget(self._preview, 1)
        body.addLayout(right, 3)
        layout.addLayout(body, 1)

        buttons = QDialogButtonBox(self)
        insert_btn = buttons.addButton(
            "插入选中片段", QDialogButtonBox.ButtonRole.AcceptRole
        )
        insert_btn.clicked.connect(self._on_insert)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._reload()

    # --- 列表 ---

    def _reload(self) -> None:
        self._list.clear()
        for snippet in self._store.snippets():
            item = QListWidgetItem(
                "{0} · {1}".format(snippet.trigger, snippet.description or "（无描述）")
            )
            item.setData(Qt.ItemDataRole.UserRole, snippet)
            self._list.addItem(item)
        self._on_selection_changed()

    def _on_selection_changed(self, *_args) -> None:
        snippet = self._selected_snippet()
        if snippet is None:
            self._preview.clear()
            return
        text, _placeholders = expand_placeholders(snippet.body)
        self._preview.setPlainText(text)

    def _selected_snippet(self) -> Optional[Snippet]:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # --- 操作 ---

    def _on_add(self) -> None:
        snippet = self._edit_snippet(None)
        if snippet is None:
            return
        if not self._store.add(snippet):
            QMessageBox.warning(self, "新增失败", "触发词已存在：{0}".format(snippet.trigger))
            return
        self._reload()

    def _on_edit(self) -> None:
        existing = self._selected_snippet()
        if existing is None:
            return
        snippet = self._edit_snippet(existing)
        if snippet is None:
            return
        self._store.update(existing.trigger, snippet)
        self._reload()

    def _on_delete(self) -> None:
        existing = self._selected_snippet()
        if existing is None:
            return
        answer = QMessageBox.question(
            self,
            "删除片段",
            "删除片段「{0}」？".format(existing.trigger),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.remove(existing.trigger)
        self._reload()

    def _on_insert(self) -> None:
        snippet = self._selected_snippet()
        if snippet is None:
            QMessageBox.information(self, "插入片段", "请先在列表中选择一条片段。")
            return
        self.insert_requested.emit(snippet)
        self.accept()

    # --- 编辑表单 ---

    def _edit_snippet(self, existing: Optional[Snippet]) -> Optional[Snippet]:
        """弹出编辑表单；保存返回 Snippet，取消返回 None。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑片段" if existing else "新增片段")
        form = QVBoxLayout(dialog)
        form.addWidget(QLabel("触发词："))
        trigger_entry = QLineEdit(dialog)
        form.addWidget(trigger_entry)
        form.addWidget(QLabel("描述："))
        desc_entry = QLineEdit(dialog)
        form.addWidget(desc_entry)
        form.addWidget(QLabel("模板（占位符 ${1:默认值}）："))
        body_entry = QPlainTextEdit(dialog)
        form.addWidget(body_entry, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if existing is not None:
            trigger_entry.setText(existing.trigger)
            desc_entry.setText(existing.description)
            body_entry.setPlainText(existing.body)
        dialog.resize(460, 340)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        trigger = trigger_entry.text().strip()
        if not trigger:
            QMessageBox.warning(self, "编辑片段", "触发词不能为空。")
            return None
        return Snippet(trigger=trigger, description=desc_entry.text().strip(), body=body_entry.toPlainText())
