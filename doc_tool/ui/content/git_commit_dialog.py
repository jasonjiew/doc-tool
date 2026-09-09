# -*- coding: utf-8 -*-
"""Git 提交对话框 (GitCommitDialog)。

特性：
- 改动文件复选列表（支持全选/全不选，已选数量统计）；
- 状态标签高亮（新增 / 已修改 / 已删除 / 重命名）；
- 规范化提交信息多行输入框；
- 快捷 Commit 规范前缀标签栏（feat, fix, docs, style, refactor, chore）；
- 支持「提交」与「提交并推送 (Commit & Push)」两种操作。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.changes import ChangeItem
from doc_tool.ui.styles import SEMANTIC_COLORS, SEMANTIC_COLORS_DARK

_STATUS_TEXT = {
    "added": "新增",
    "modified": "已修改",
    "deleted": "已删除",
    "renamed": "重命名",
}

_STATUS_COLOR_KEY = {
    "added": "success",
    "modified": "neutral",
    "deleted": "failure",
    "renamed": "purple",
}

_PREFIXES = [
    ("feat:", "功能"),
    ("fix:", "修复"),
    ("docs:", "文档"),
    ("refactor:", "重构"),
    ("style:", "格式"),
    ("chore:", "事务"),
]


class CommitFileItemWidget(QWidget):
    """单个文件复选行。"""

    def __init__(
        self,
        item: ChangeItem,
        *,
        dark: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        colors = SEMANTIC_COLORS_DARK if dark else SEMANTIC_COLORS

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 状态徽章
        status_key = item.status
        status_str = _STATUS_TEXT.get(status_key, status_key)
        color_tone = _STATUS_COLOR_KEY.get(status_key, "neutral")
        tag_color = colors.get(color_tone, "#3b82f6")

        badge = QLabel(f" {status_str} ", self)
        font = QFont(self.font())
        font.setPointSize(8)
        font.setBold(True)
        badge.setFont(font)
        badge_bg = "#27272a" if dark else "#f1f5f9"
        badge.setStyleSheet(
            f"background: {badge_bg}; color: {tag_color}; border-radius: 4px; padding: 2px 4px;"
        )
        layout.addWidget(badge)

        # 文件路径
        path_label = QLabel(item.rel_path, self)
        path_font = QFont(self.font())
        path_font.setPointSize(9)
        path_label.setFont(path_font)
        layout.addWidget(path_label, 1)


class GitCommitDialog(QDialog):
    """专业 Git 提交对话框。"""

    def __init__(
        self,
        items: Sequence[ChangeItem],
        *,
        dark: bool = False,
        can_push: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("提交改动到版本控制 (Git Commit)")
        self.setMinimumSize(560, 480)
        self._items = list(items)
        self._dark = dark
        self._can_push = can_push

        self.selected_paths: List[str] = []
        self.commit_message: str = ""
        self.should_push: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 1. 顶部全选与数量统计行
        top_bar = QHBoxLayout()
        self._select_all_cb = QCheckBox("全选改动文件", self)
        self._select_all_cb.setChecked(True)
        self._select_all_cb.toggled.connect(self._on_select_all_toggled)
        top_bar.addWidget(self._select_all_cb)

        self._count_label = QLabel("", self)
        self._count_label.setStyleSheet("color: #94a3b8; font-size: 8.5pt;")
        top_bar.addStretch(1)
        top_bar.addWidget(self._count_label)
        layout.addLayout(top_bar)

        # 2. 文件复选列表
        self._list_widget = QListWidget(self)
        self._list_widget.setAlternatingRowColors(True)
        list_bg = "#18181c" if dark else "#f8fafc"
        list_border = "#2e2f38" if dark else "#e2e8f0"
        self._list_widget.setStyleSheet(
            f"QListWidget {{ background: {list_bg}; border: 1px solid {list_border}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 2px 4px; }}"
        )
        layout.addWidget(self._list_widget, 1)

        # 3. 提交信息区域
        msg_header = QHBoxLayout()
        msg_label = QLabel("提交信息 (Commit Message):", self)
        msg_label.setStyleSheet("font-weight: 600; font-size: 9pt;")
        msg_header.addWidget(msg_label)
        msg_header.addStretch(1)
        layout.addLayout(msg_header)

        # 快捷前缀按钮栏
        prefix_layout = QHBoxLayout()
        prefix_layout.setSpacing(6)
        prefix_hint = QLabel("快捷前缀:", self)
        prefix_hint.setStyleSheet("color: #94a3b8; font-size: 8.5pt;")
        prefix_layout.addWidget(prefix_hint)

        btn_bg = "#27272a" if dark else "#f1f5f9"
        btn_hover = "#3f3f46" if dark else "#e2e8f0"
        chip_style = (
            f"QPushButton {{ background: {btn_bg}; border: 1px solid transparent; border-radius: 4px; "
            f"padding: 3px 8px; font-size: 8pt; font-weight: 600; }} "
            f"QPushButton:hover {{ background: {btn_hover}; border-color: #3b82f6; }}"
        )
        for tag, hint in _PREFIXES:
            btn = QPushButton(f"{tag}", self)
            btn.setToolTip(f"{hint}：{tag}")
            btn.setStyleSheet(chip_style)
            btn.clicked.connect(lambda _, t=tag: self._insert_prefix(t))
            prefix_layout.addWidget(btn)
        prefix_layout.addStretch(1)
        layout.addLayout(prefix_layout)

        # 提交输入框
        self._msg_input = QPlainTextEdit(self)
        self._msg_input.setPlaceholderText("请输入本次提交的清晰说明（必填）...")
        self._msg_input.setFixedHeight(90)
        self._msg_input.setStyleSheet(
            f"QPlainTextEdit {{ background: {list_bg}; border: 1px solid {list_border}; "
            f"border-radius: 6px; padding: 6px; font-size: 9pt; }}"
            f"QPlainTextEdit:focus {{ border-color: #3b82f6; }}"
        )
        self._msg_input.installEventFilter(self)
        layout.addWidget(self._msg_input)

        # 4. 底部动作按钮
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch(1)

        self._cancel_btn = QPushButton("取消", self)
        self._cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self._cancel_btn)

        if self._can_push:
            self._commit_push_btn = QPushButton("提交并推送 (Commit & Push)", self)
            self._commit_push_btn.setProperty("btnRole", "secondary")
            self._commit_push_btn.clicked.connect(lambda: self._on_confirm(push=True))
            btn_box.addWidget(self._commit_push_btn)

        self._commit_btn = QPushButton("提交 (Commit)", self)
        self._commit_btn.setProperty("btnRole", "primary")
        self._commit_btn.setToolTip("快捷键: Ctrl+Enter")
        self._commit_btn.clicked.connect(lambda: self._on_confirm(push=False))
        btn_box.addWidget(self._commit_btn)

        layout.addLayout(btn_box)

        self._populate_files()
        self._list_widget.itemChanged.connect(self._on_item_state_changed)
        self._update_counts()

    def _populate_files(self) -> None:
        self._list_widget.clear()
        for item in self._items:
            list_item = QListWidgetItem(self._list_widget)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Checked)
            list_item.setData(Qt.ItemDataRole.UserRole, item)

            widget = CommitFileItemWidget(item, dark=self._dark)
            list_item.setSizeHint(widget.sizeHint())
            self._list_widget.addItem(list_item)
            self._list_widget.setItemWidget(list_item, widget)

    def _on_select_all_toggled(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._list_widget.blockSignals(True)
        for i in range(self._list_widget.count()):
            self._list_widget.item(i).setCheckState(state)
        self._list_widget.blockSignals(False)
        self._update_counts()

    def _on_item_state_changed(self) -> None:
        self._update_counts()

    def _update_counts(self) -> None:
        total = self._list_widget.count()
        selected = 0
        for i in range(total):
            if self._list_widget.item(i).checkState() == Qt.CheckState.Checked:
                selected += 1
        self._count_label.setText(f"已选择 {selected} / {total} 个改动文件")

        # 同步全选框状态
        self._select_all_cb.blockSignals(True)
        if selected == total:
            self._select_all_cb.setCheckState(Qt.CheckState.Checked)
        elif selected == 0:
            self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)
        else:
            self._select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self._select_all_cb.blockSignals(False)

        can_commit = selected > 0
        self._commit_btn.setEnabled(can_commit)
        if hasattr(self, "_commit_push_btn"):
            self._commit_push_btn.setEnabled(can_commit)

    def eventFilter(self, obj, event: QEvent) -> bool:
        """支持在提交说明框中按 Ctrl+Enter 直接提交。"""
        if obj == self._msg_input and event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if key_event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if self._commit_btn.isEnabled():
                        self._on_confirm(push=False)
                    return True
        return super().eventFilter(obj, event)

    def _insert_prefix(self, prefix: str) -> None:
        cur_text = self._msg_input.toPlainText().strip()
        # 移除已有已知前缀（若有）
        for tag, _ in _PREFIXES:
            if cur_text.startswith(tag):
                cur_text = cur_text[len(tag):].lstrip()
                break
        new_text = f"{prefix} {cur_text}" if cur_text else f"{prefix} "
        self._msg_input.setPlainText(new_text)
        cursor = self._msg_input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._msg_input.setTextCursor(cursor)
        self._msg_input.setFocus()

    def _on_confirm(self, push: bool = False) -> None:
        message = self._msg_input.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "提示", "请输入提交信息 (Commit Message)！")
            self._msg_input.setFocus()
            return

        selected: List[str] = []
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                change_item: ChangeItem = item.data(Qt.ItemDataRole.UserRole)
                selected.append(change_item.rel_path)

        if not selected:
            QMessageBox.warning(self, "提示", "请至少勾选一个要提交的文件！")
            return

        self.selected_paths = selected
        self.commit_message = message
        self.should_push = push
        self.accept()
