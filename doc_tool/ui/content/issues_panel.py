# -*- coding: utf-8 -*-
"""结构化问题中心：组合筛选、严重度摘要与文件定位。"""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.issues import IssueRecord, filter_issues, severity_summary


_ALL = "全部"


class IssuesPanel(QWidget):
    """展示统一问题记录；刷新数据时保留当前筛选条件。"""

    def __init__(
        self,
        *,
        on_open: Optional[Callable[[str, Optional[int]], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        show_document_type: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_open = on_open
        self._on_status = on_status
        # 通用单项目 documentType 固定为 general，不再作为主要筛选维度；
        # 仅旧版多类型布局保留兼容过滤（任务 6.3）。
        self._show_document_type = show_document_type
        self._issues: List[IssueRecord] = []
        # 初始无数据（尚未运行任何检查）；首个任务终态/lint 结果到达前
        # 保持“无当前项目数据”状态，避免误报“当前项目未发现问题”。
        self._has_project = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        filters = QHBoxLayout()
        self._type = self._new_filter("类型", filters)
        self._document_type = self._new_filter("文档类型", filters)
        self._document_type.setVisible(self._show_document_type)
        self._severity = self._new_filter("严重度", filters)
        self._file = self._new_filter("文件", filters)
        filters.addStretch(1)
        outer.addLayout(filters)

        self._summary = QLabel("error 0 · warning 0 · info 0", self)
        self._summary.setObjectName("statusMuted")
        outer.addWidget(self._summary)

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(7)
        headers = ["严重度", "类型", "文档类型", "文件", "行", "消息", "错误码"]
        if not self._show_document_type:
            headers = [h for h in headers if h != "文档类型"]
            self._tree.setColumnCount(len(headers))
        self._tree.setHeaderLabels(headers)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setColumnWidth(0, 72)
        self._tree.setColumnWidth(1, 110)
        self._tree.setColumnWidth(2, 90)
        self._tree.setColumnWidth(3, 220)
        self._tree.setColumnWidth(4, 48)
        self._tree.itemDoubleClicked.connect(self._activate)
        outer.addWidget(self._tree, 1)

        self._state = QLabel("无当前项目数据", self)
        self._state.setObjectName("statusMuted")
        outer.addWidget(self._state)

    def _new_filter(self, label: str, layout: QHBoxLayout) -> QComboBox:
        layout.addWidget(QLabel(label, self))
        combo = QComboBox(self)
        combo.addItem(_ALL, "")
        combo.currentIndexChanged.connect(self._render)
        layout.addWidget(combo)
        return combo

    @staticmethod
    def _selected(combo: QComboBox) -> str:
        return str(combo.currentData() or "")

    @staticmethod
    def _reset_options(combo: QComboBox, values: Iterable[str]) -> None:
        selected = str(combo.currentData() or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_ALL, "")
        for value in sorted(set(v for v in values if v)):
            combo.addItem(value, value)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def clear_project(self) -> None:
        self._has_project = False
        self._issues = []
        self._render()

    def set_issues(self, issues: Iterable[IssueRecord]) -> None:
        self._has_project = True
        self._issues = list(issues)
        self._reset_options(self._type, (i.issue_type for i in self._issues))
        self._reset_options(self._document_type, (i.document_type for i in self._issues))
        self._reset_options(self._severity, (i.severity for i in self._issues))
        self._reset_options(self._file, (i.rel_path for i in self._issues))
        self._render()

    def filtered_issues(self) -> List[IssueRecord]:
        return filter_issues(
            self._issues,
            issue_type=self._selected(self._type),
            document_type=self._selected(self._document_type),
            severity=self._selected(self._severity),
            rel_path=self._selected(self._file),
        )

    def _render(self, _index: int = 0) -> None:
        visible = self.filtered_issues()
        summary = severity_summary(visible)
        self._summary.setText(
            "error {error} · warning {warning} · info {info}".format(**summary)
        )
        self._tree.clear()
        for issue in visible:
            columns = [
                issue.severity,
                issue.issue_type,
                issue.rel_path,
                "" if issue.line_no is None else str(issue.line_no),
                issue.message,
                issue.error_code or "",
            ]
            if self._show_document_type:
                columns.insert(2, issue.document_type)
            item = QTreeWidgetItem(columns)
            item.setData(0, Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(5, issue.suggested_action)
            self._tree.addTopLevelItem(item)
        if not self._has_project:
            self._state.setText("无当前项目数据")
        elif self._issues and not visible:
            self._state.setText("无匹配结果")
        elif not self._issues:
            self._state.setText("当前项目未发现问题")
        else:
            latest = max((i.generated_at for i in visible), default="")
            sources = "、".join(sorted(set(i.source for i in visible)))
            self._state.setText("共 {0} 项 · 来源 {1} · {2}".format(len(visible), sources, latest))

    def _activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        issue = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(issue, IssueRecord) or self._on_open is None:
            return
        if not issue.rel_path:
            if self._on_status is not None:
                self._on_status("该问题没有可定位的文件")
            return
        self._on_open(issue.rel_path, issue.line_no)
