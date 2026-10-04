# -*- coding: utf-8 -*-
"""批量导入结果与接续窗口（MAIN2-A 1.3）。

多份 Word 导入时一文件一项目：这里给出每份输入的**真实状态**，已成功的立即可
打开，失败/待转换/未开始的项可以按选择接续补做，输入设置与已成功项目保持不变。

约束：

- 只重试所选且非成功的项，绝不重复创建已成功项目；
- 取消后未开始项保留为可接续状态，设置与成功项目不丢；
- 动作绑定打开本窗口的项目窗口（``host``）。
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_STATUS_LABELS = {
    "ok": "可打开",
    "failed": "失败",
    "pending-convert": "待转换",
    "skipped": "已跳过",
    "cancelled": "未开始",
}


class BatchResultWindow(QDialog):
    """批量导入结果（非模态）：成功项直接打开，所选项接续补做。"""

    def __init__(self, batch, host, parent=None) -> None:
        super().__init__(parent)
        self._batch = batch
        self._host = host
        self.setWindowTitle("批量导入结果")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)
        self._summary = QLabel("\n".join(batch.summary_lines()), self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["输入", "状态", "已生成项目", "说明"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._sync_actions)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        self._open_btn = QPushButton("打开所选项目", self)
        self._open_btn.clicked.connect(self._on_open_selected)
        actions.addWidget(self._open_btn)
        self._retry_btn = QPushButton("接续所选项（保留设置）", self)
        self._retry_btn.setProperty("btnRole", "primary")
        self._retry_btn.clicked.connect(self._on_retry_selected)
        actions.addWidget(self._retry_btn)
        self._footer = QLabel("", self)
        self._footer.setObjectName("statusMuted")
        actions.addWidget(self._footer, 1)
        close_btn = QPushButton("关闭（可继续编辑）", self)
        close_btn.clicked.connect(self.close)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._render()

    # --- 渲染 ---

    def _render(self) -> None:
        items = list(self._batch.items or [])
        self._table.setRowCount(len(items))
        for index, item in enumerate(items):
            values = [
                item.source,
                _STATUS_LABELS.get(item.status, item.status),
                item.project_root or "—",
                item.message or "",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self._table.setItem(index, column, cell)
        retryable = len(getattr(self._batch, "retryable", []) or [])
        self._footer.setText(
            "共 {0} 项，可接续 {1} 项（未开始/失败/待转换；成功项目不会被重建）".format(
                len(items), retryable,
            )
        )
        self._sync_actions()

    # --- 选择与动作 ---

    def _selected_items(self) -> List[object]:
        model = self._table.selectionModel()
        if model is None:
            return []
        rows = sorted(index.row() for index in model.selectedRows())
        items = list(self._batch.items or [])
        return [items[row] for row in rows if 0 <= row < len(items)]

    def _sync_actions(self) -> None:
        selected = self._selected_items()
        self._open_btn.setEnabled(any(item.status == "ok" for item in selected))
        self._retry_btn.setEnabled(
            any(item.status in ("failed", "pending-convert", "cancelled", "skipped") for item in selected)
        )

    def _on_open_selected(self) -> None:
        if self._host is None:
            return
        for item in self._selected_items():
            if item.status == "ok" and item.project_root:
                self._host._open_project_in_new_window(item.project_root)

    def _on_retry_selected(self) -> None:
        sources = [
            item.source for item in self._selected_items()
            if item.status != "ok"
        ]
        if not sources or self._host is None:
            return
        if self._host._retry_intake_items(self._batch, sources, self):
            self._reload()

    def _reload(self) -> None:
        batch = getattr(self._host, "_last_batch_result", None)
        if batch is None:
            return
        self._batch = batch
        self._summary.setText("\n".join(batch.summary_lines()))
        self._render()

    def selected_source_list(self) -> List[str]:
        """供测试核对所选行。"""
        return [item.source for item in self._selected_items()]


__all__ = ["BatchResultWindow"]