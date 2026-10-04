# -*- coding: utf-8 -*-
"""导入结果独立窗口（MAIN2-A 1.2）。

导入结果不再是一次性 ``QMessageBox``：这里给出**非模态、可重开、可搜索、
可分页**的完整处理事实列表，用户处理完一项可以继续写，随时回来接着处理。

设计约束：

- 列表**不截断**：默认视图只把少数主要问题放在“优先处理”区，完整记录始终
  在同一个窗口里可查（总数与筛选后的条数都显示实际值）；
- 每个动作绑定**打开它的那个项目窗口**（``host``），同名相对路径不会串项目；
- 动作复用既有服务（章节定位、原件查看、占位图替换），不新建数据模型。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

#: 每页显示的处理事实条数（可翻页，绝不截断）。
PAGE_SIZE = 50


class IntakeResultWindow(QDialog):
    """导入结果的非模态窗口（完整列表 + 搜索 + 分页 + 直接动作）。"""

    def __init__(self, page, host, parent=None) -> None:
        super().__init__(parent)
        self._page = page
        self._host = host
        self._rows: List[Dict[str, object]] = list(page.details or [])
        self._filtered: List[Dict[str, object]] = list(self._rows)
        self._page_index = 0
        self._kind_filter = ""

        self.setWindowTitle("导入结果与待处理项")
        self.setModal(False)
        # 非模态窗口：不抢焦点、不阻塞写作区，可与其他窗口并存。
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setMinimumSize(760, 480)

        layout = QVBoxLayout(self)
        header = QLabel("\n".join(page.summary or ["项目已生成，可直接编辑"]), self)
        header.setWordWrap(True)
        header.setObjectName("intakeSummary")
        layout.addWidget(header)

        self._counts = QLabel("", self)
        self._counts.setObjectName("statusMuted")
        layout.addWidget(self._counts)

        filters = QHBoxLayout()
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("搜索类型/章节/说明（例如：图片、第1章）")
        self._search.textChanged.connect(self._on_search_changed)
        filters.addWidget(self._search, 1)
        self._kind_combo = QComboBox(self)
        self._kind_combo.addItem("全部类型", "")
        for feature in sorted({str(item.get("feature") or "") for item in self._rows}):
            if feature:
                self._kind_combo.addItem(feature, feature)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        filters.addWidget(self._kind_combo)
        layout.addLayout(filters)

        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(["类型", "处理方式", "章节", "行", "说明/动作"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._sync_action_state)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        self._locate_btn = QPushButton("定位正文", self)
        self._locate_btn.clicked.connect(self._on_locate)
        actions.addWidget(self._locate_btn)
        self._original_btn = QPushButton("查看原件", self)
        self._original_btn.clicked.connect(self._on_view_original)
        actions.addWidget(self._original_btn)
        self._replace_btn = QPushButton("选择替代图片", self)
        self._replace_btn.clicked.connect(self._on_replace_image)
        actions.addWidget(self._replace_btn)
        actions.addStretch(1)
        self._prev_btn = QPushButton("上一页", self)
        self._prev_btn.clicked.connect(lambda: self._turn_page(-1))
        actions.addWidget(self._prev_btn)
        self._page_label = QLabel("", self)
        self._page_label.setObjectName("statusMuted")
        actions.addWidget(self._page_label)
        self._next_btn = QPushButton("下一页", self)
        self._next_btn.clicked.connect(lambda: self._turn_page(1))
        actions.addWidget(self._next_btn)
        close_btn = QPushButton("关闭（可继续编辑）", self)
        close_btn.setProperty("btnRole", "primary")
        close_btn.clicked.connect(self.close)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._render()

    # --- 筛选与分页 ---

    def _on_search_changed(self, _text: str) -> None:
        self._page_index = 0
        self._apply_filter()

    def _on_kind_changed(self, _index: int) -> None:
        self._kind_filter = str(self._kind_combo.currentData() or "")
        self._page_index = 0
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self._search.text().strip().lower()
        self._filtered = []
        for item in self._rows:
            feature = str(item.get("feature") or "")
            if self._kind_filter and feature != self._kind_filter:
                continue
            if needle:
                haystack = " ".join(
                    str(item.get(key) or "")
                    for key in ("feature", "handling", "target_chapter", "source_part", "detail")
                ).lower()
                if needle not in haystack:
                    continue
            self._filtered.append(item)
        self._render()

    def _page_count(self) -> int:
        if not self._filtered:
            return 1
        return (len(self._filtered) + PAGE_SIZE - 1) // PAGE_SIZE

    def _turn_page(self, delta: int) -> None:
        target = min(max(0, self._page_index + delta), self._page_count() - 1)
        if target != self._page_index:
            self._page_index = target
            self._render()

    # --- 渲染 ---

    def _render(self) -> None:
        total = len(self._rows)
        shown = len(self._filtered)
        first = self._page_index * PAGE_SIZE
        rows = self._filtered[first:first + PAGE_SIZE]
        self._table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            values = [
                str(item.get("feature") or ""),
                str(item.get("handling") or ""),
                str(item.get("target_chapter") or item.get("source_part") or ""),
                "" if item.get("target_line") in (None, "") else str(item.get("target_line")),
                str(item.get("detail") or item.get("action") or ""),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self._table.setItem(index, column, cell)
        self._counts.setText(
            "共 {0} 项处理事实，当前筛选 {1} 项，本页 {2} 项（不截断，可翻页/搜索）".format(
                total, shown, len(rows),
            )
        )
        self._page_label.setText("第 {0}/{1} 页".format(self._page_index + 1, self._page_count()))
        self._prev_btn.setEnabled(self._page_index > 0)
        self._next_btn.setEnabled(self._page_index + 1 < self._page_count())
        self._rows_cache = rows
        # 默认选中第一行：打开窗口即可直接处理，不必先手动点一行（用户可用性）。
        if rows and self._table.selectionModel() is not None:
            try:
                self._table.selectRow(0)
            except RuntimeError:  # noqa: BLE001 - 控件销毁时忽略
                pass
        self._sync_action_state()

    def _selected_row(self) -> Optional[Dict[str, object]]:
        selected = self._table.selectionModel()
        if selected is None:
            return None
        indexes = selected.selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(getattr(self, "_rows_cache", [])):
            return self._rows_cache[row]
        return None

    def _sync_action_state(self) -> None:
        item = self._selected_row()
        has = item is not None
        self._locate_btn.setEnabled(has)
        self._original_btn.setEnabled(has)
        self._replace_btn.setEnabled(
            has and str(item.get("handling") or "") == "placeholder"
        )

    # --- 动作（绑定打开本窗口的项目窗口） ---

    def _on_locate(self) -> None:
        item = self._selected_row()
        if item is None or self._host is None:
            return
        self._host._locate_intake_finding(self._page, item, self)

    def _on_view_original(self) -> None:
        item = self._selected_row()
        if item is None or self._host is None:
            return
        self._host._open_intake_original(self._page, item)

    def _on_replace_image(self) -> None:
        item = self._selected_row()
        if item is None or self._host is None:
            return
        if self._host._replace_intake_image(self._page, item, self):
            # 处理事实已更新：重新读取真实记录数量（不是本地减一）。
            self._reload()

    def _reload(self) -> None:
        """处理完一项后重新读取真实账本（数量与列表同步）。"""
        if self._host is None:
            return
        page = self._host._build_intake_page(self._page.projectRoot)
        if page is None:
            return
        self._page = page
        self._rows = list(page.details or [])
        self._apply_filter()

    def selected_row_dict(self) -> Optional[Dict[str, object]]:
        """供测试核对所选行的真实内容。"""
        return self._selected_row()


__all__ = ["IntakeResultWindow", "PAGE_SIZE"]