# -*- coding: utf-8 -*-
"""结构化问题中心：组合筛选、严重度摘要与文件定位。"""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
        self._document_type = self._new_filter(
            "文档类型", filters, visible=self._show_document_type
        )
        self._severity = self._new_filter("严重度", filters)
        self._file = self._new_filter("文件", filters)

        search_lbl = QLabel("搜索：", self)
        filters.addWidget(search_lbl)
        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("搜索问题描述、错误码、文件或行号...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._render)
        filters.addWidget(self._search_input, 1)

        self._reset_btn = QPushButton("重置", self)
        self._reset_btn.setProperty("btnRole", "compact")
        self._reset_btn.setToolTip("重置所有分类筛选与搜索关键词")
        self._reset_btn.clicked.connect(self.reset_filters)
        filters.addWidget(self._reset_btn)

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
        # 列宽按当前列布局定位：通用单项目（隐藏文档类型列）时，文件列保持宽、
        # 行号列收窄，消息列不被迫压缩为固定小宽度。
        widths = [(0, 72), (1, 110)]
        if self._show_document_type:
            widths += [(2, 90), (3, 220), (4, 48)]
        else:
            widths += [(2, 220), (3, 48)]
        for col, width in widths:
            self._tree.setColumnWidth(col, width)
        self._tree.itemDoubleClicked.connect(self._activate)
        outer.addWidget(self._tree, 1)

        self._state = QLabel("无当前项目数据", self)
        self._state.setObjectName("statusMuted")
        outer.addWidget(self._state)

    def _new_filter(self, label: str, layout: QHBoxLayout, *, visible: bool = True) -> QComboBox:
        label_widget = QLabel(label, self)
        label_widget.setVisible(visible)
        layout.addWidget(label_widget)
        combo = QComboBox(self)
        combo.setVisible(visible)
        combo.addItem(_ALL, "")
        combo.currentIndexChanged.connect(self._render)
        layout.addWidget(combo)
        return combo

    @staticmethod
    def _selected(combo: QComboBox) -> str:
        return str(combo.currentData() or "")

    @staticmethod
    def _reset_options(
        combo: QComboBox,
        values: Iterable[str],
        label_formatter: Optional[Callable[[str], str]] = None,
    ) -> None:
        selected = str(combo.currentData() or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_ALL, "")
        for value in sorted(set(v for v in values if v)):
            label = label_formatter(value) if label_formatter else value
            combo.addItem(label, value)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def reset_filters(self) -> None:
        self._type.blockSignals(True)
        self._type.setCurrentIndex(0)
        self._type.blockSignals(False)

        self._document_type.blockSignals(True)
        self._document_type.setCurrentIndex(0)
        self._document_type.blockSignals(False)

        self._severity.blockSignals(True)
        self._severity.setCurrentIndex(0)
        self._severity.blockSignals(False)

        self._file.blockSignals(True)
        self._file.setCurrentIndex(0)
        self._file.blockSignals(False)

        if hasattr(self, "_search_input"):
            self._search_input.blockSignals(True)
            self._search_input.clear()
            self._search_input.blockSignals(False)

        self._render()

    def clear_project(self) -> None:
        self._has_project = False
        self._issues = []
        if hasattr(self, "_search_input"):
            self._search_input.blockSignals(True)
            self._search_input.clear()
            self._search_input.blockSignals(False)
        self._render()

    def set_issues(self, issues: Iterable[IssueRecord]) -> None:
        self._has_project = True
        self._issues = list(issues)
        from doc_tool.application.content.lint import RULE_LABELS, SEVERITY_LABELS
        type_formatter = lambda v: f"{RULE_LABELS.get(v, v)} ({v})" if v in RULE_LABELS else v
        sev_formatter = lambda v: f"{SEVERITY_LABELS.get(v, v)} ({v})" if v in SEVERITY_LABELS else v
        self._reset_options(self._type, (i.issue_type for i in self._issues), type_formatter)
        self._reset_options(self._document_type, (i.document_type for i in self._issues))
        self._reset_options(self._severity, (i.severity for i in self._issues), sev_formatter)
        self._reset_options(self._file, (i.rel_path for i in self._issues))
        self._render()

    def filtered_issues(self) -> List[IssueRecord]:
        kw = self._search_input.text().strip() if hasattr(self, "_search_input") else ""
        return filter_issues(
            self._issues,
            issue_type=self._selected(self._type),
            document_type=self._selected(self._document_type),
            severity=self._selected(self._severity),
            rel_path=self._selected(self._file),
            keyword=kw,
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
            # 提示气泡落在「消息」列：7 列布局为第 5 列，隐藏文档类型列后为第 4 列。
            message_col = 5 if self._show_document_type else 4
            item.setToolTip(message_col, issue.suggested_action)
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
