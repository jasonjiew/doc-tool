# -*- coding: utf-8 -*-
"""外部 Word 修订的选择接收窗口（MAIN2-B）。

把既有只读差异服务（``reimport_plan`` + ``reimport_preview``）接到真实入口：用户
先看到**新增/修改/删除**与逐项 diff，再决定接收哪些章；冲突与脏内容默认保留，
可查看差异、另存传入副本，或只保存相关章后刷新。

约束：

- 预览阶段不写正式正文、不改源记录；
- 取消不写任何内容；
- 应用只处理“已选且未被阻止”的项，复用原事务与回滚；
- 动作绑定打开本窗口的项目窗口（``host``）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_CHANGE_LABELS = {
    "added": "新增",
    "modified": "修改",
    "deleted": "删除",
    "unchanged": "未变化",
}


class ReimportPreviewWindow(QDialog):
    """重导入差异窗口（非模态）：选择要接收的章节。"""

    def __init__(self, session, host, source_path: str = "", parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self._host = host
        self._source_path = source_path
        self.setWindowTitle("接收外部 Word 修订")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setMinimumSize(880, 560)

        layout = QVBoxLayout(self)
        counts = session.counts() if hasattr(session, "counts") else {}
        header = QLabel(
            "来源：{0}\n可应用 {1} 项；冲突 {2} 项、未保存内容 {3} 项默认保留本地".format(
                source_path or "（未记录）",
                counts.get("applicable", 0), counts.get("conflict", 0), counts.get("dirty", 0),
            ),
            self,
        )
        header.setWordWrap(True)
        layout.addWidget(header)
        if getattr(session, "warnings", None):
            warn = QLabel("；".join(str(item) for item in session.warnings[:4]), self)
            warn.setWordWrap(True)
            warn.setObjectName("statusMuted")
            layout.addWidget(warn)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["章节", "变化", "本地保留原因", "将应用"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_row_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        splitter.addWidget(self._table)

        diff_host = QWidget(splitter)
        diff_layout = QVBoxLayout(diff_host)
        diff_layout.setContentsMargins(0, 0, 0, 0)
        self._diff_label = QLabel("差异（当前 / 新源）", diff_host)
        diff_layout.addWidget(self._diff_label)
        self._diff = QPlainTextEdit(diff_host)
        self._diff.setReadOnly(True)
        diff_layout.addWidget(self._diff)
        splitter.addWidget(diff_host)
        splitter.setSizes([320, 240])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self._apply_btn = QPushButton("应用所选章节", self)
        self._apply_btn.setProperty("btnRole", "primary")
        self._apply_btn.clicked.connect(self._on_apply)
        actions.addWidget(self._apply_btn)
        self._save_incoming_btn = QPushButton("另存传入副本…", self)
        self._save_incoming_btn.clicked.connect(self._on_save_incoming)
        actions.addWidget(self._save_incoming_btn)
        self._save_related_btn = QPushButton("仅保存相关章后刷新", self)
        self._save_related_btn.clicked.connect(self._on_save_related)
        actions.addWidget(self._save_related_btn)
        actions.addStretch(1)
        cancel_btn = QPushButton("取消（不写入）", self)
        cancel_btn.clicked.connect(self._on_cancel)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

        self._render()

    # --- 渲染 ---

    def _render(self) -> None:
        entries = list(getattr(self._session, "entries", []) or [])
        self._table.blockSignals(True)
        self._table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            blocked = entry.conflict or entry.dirty
            name = QTableWidgetItem(entry.rel_path)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name)
            change = QTableWidgetItem(_CHANGE_LABELS.get(entry.change, entry.change))
            change.setFlags(change.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 1, change)
            reason = QTableWidgetItem(entry.blocked_reason or "")
            reason.setFlags(reason.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 2, reason)
            check = QTableWidgetItem("")
            check.setFlags(
                (check.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable
            )
            check.setCheckState(
                Qt.CheckState.Unchecked if blocked else Qt.CheckState.Checked
            )
            if blocked:
                check.setFlags(check.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._table.setItem(row, 3, check)
        self._table.blockSignals(False)
        if entries:
            self._table.selectRow(0)
        self._sync_apply_state()

    def _on_row_changed(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self._diff.setPlainText("")
            return
        self._diff_label.setText(
            "差异：{0}（{1}）".format(entry.rel_path, _CHANGE_LABELS.get(entry.change, entry.change))
        )
        lines = list(getattr(entry, "diff_lines", []) or [])
        self._diff.setPlainText("\n".join(lines) if lines else "（无逐行差异内容）")

    def _on_item_changed(self, item) -> None:
        if item.column() != 3:
            return
        entry = self.entry_at(item.row())
        if entry is None:
            return
        from doc_tool.application.content.reimport_preview import toggle_selection

        toggle_selection(self._session, entry.rel_path, item.checkState() == Qt.CheckState.Checked)
        self._sync_apply_state()

    def _sync_apply_state(self) -> None:
        applicable = [item for item in (getattr(self._session, "entries", []) or []) if item.applicable]
        self._apply_btn.setEnabled(bool(applicable))
        self._apply_btn.setText(
            "应用所选章节（{0}）".format(len(applicable)) if applicable else "应用所选章节"
        )

    # --- 查询 ---

    def entry_at(self, row: int):
        entries = list(getattr(self._session, "entries", []) or [])
        if 0 <= row < len(entries):
            return entries[row]
        return None

    def selected_entry(self):
        model = self._table.selectionModel()
        if model is None:
            return None
        rows = model.selectedRows()
        if not rows:
            return None
        return self.entry_at(rows[0].row())

    def selected_paths(self) -> List[str]:
        result: List[str] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 3)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                entry = self.entry_at(row)
                if entry is not None:
                    result.append(entry.rel_path)
        return result

    # --- 动作 ---

    def _on_apply(self) -> None:
        if self._host is None:
            return
        outcome = self._host._apply_reimport_session(self._session, self._source_path)
        if outcome:
            self.close()

    def _on_save_incoming(self) -> None:
        if self._host is not None:
            self._host._save_reimport_incoming_copy(self._source_path)

    def _on_save_related(self) -> None:
        if self._host is None:
            return
        entries = [item for item in (getattr(self._session, "entries", []) or []) if item.dirty]
        paths = [item.rel_path for item in entries]
        if not paths:
            self._host._show_status_message("当前没有未保存章节需要先保存")
            return
        if self._host._save_chapters_then_refresh(self._source_path, paths, self):
            self.close()

    def _on_cancel(self) -> None:
        from doc_tool.application.content.reimport_preview import cancel_session

        cancel_session(self._session)
        self.close()


__all__ = ["ReimportPreviewWindow"]