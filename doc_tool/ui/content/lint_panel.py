# -*- coding: utf-8 -*-
"""术语/一致性检查面板（底部工具面板）。

运行重复标题、术语大小写、TODO/TBD 三类检查，结果表格展示并支持点击
定位。术语清单在面板内直接增删，保存到 ``.state/terms.json`` 后立即
重跑相关检查。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.lint import ContentLinter, LintIssue, TermStore

_RULE_LABELS = {
    "duplicate_title": "重复标题",
    "term_case": "术语大小写",
    "todo_residual": "待办残留",
    "required_section": "必备章节",
    "field_completeness": "字段完整性",
    "numbering_uniqueness": "编号唯一性",
    "sensitive_info": "敏感信息",
    "interface_table_structure": "接口表结构",
}

_SEVERITY_LABELS = {
    "error": "阻断",
    "warning": "警告",
    "info": "提示",
}


class LintPanel(QWidget):
    """一致性检查面板。

    ``linter``：``ContentLinter``；``terms``：``TermStore``；
    ``on_open(rel_path, line_no)``：结果项点击定位。
    """

    def __init__(
        self,
        linter: ContentLinter,
        terms: TermStore,
        *,
        on_open: Optional[Callable[[str, int], None]] = None,
        on_issues: Optional[Callable[[List[LintIssue]], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._linter = linter
        self._terms = terms
        self._on_open = on_open
        self._on_issues = on_issues
        self._writable = writable

        # 唯一外层布局：术语卡片 + 结果表 + 状态行。原先各 _build_*
        # 各自创建 QVBoxLayout(self)，只有第一个会被安装，结果表因此不可见。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 4, 4, 4)
        self._outer.setSpacing(4)
        self._build_terms()
        self._build_results()

    # --- 构建 ---

    def _build_terms(self) -> None:
        terms_frame = QFrame(self)
        terms_frame.setProperty("card", True)
        layout = QHBoxLayout(terms_frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._term_list = QListWidget(terms_frame)
        self._term_list.setMaximumHeight(84)
        layout.addWidget(self._term_list, 1)

        side = QWidget(terms_frame)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(4)
        self._term_entry = QLineEdit(side)
        self._term_entry.setPlaceholderText("术语规范拼写")
        side_layout.addWidget(self._term_entry)
        add_btn = QPushButton("添加", side)
        add_btn.setProperty("btnRole", "secondary")
        add_btn.clicked.connect(self.add_term)
        side_layout.addWidget(add_btn)
        self._remove_btn = QPushButton("删除所选", side)
        self._remove_btn.setProperty("btnRole", "compact")
        self._remove_btn.clicked.connect(self.remove_term)
        side_layout.addWidget(self._remove_btn)
        layout.addWidget(side)

        self._run_btn = QPushButton("运行检查", terms_frame)
        self._run_btn.setProperty("btnRole", "primary")
        self._run_btn.clicked.connect(self.run_check)
        layout.addWidget(self._run_btn)

        self._outer.addWidget(terms_frame)
        self._load_terms()

    def _build_results(self) -> None:
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["文件", "行", "类型", "级别", "说明"])
        self._tree.setColumnWidth(0, 240)
        self._tree.setColumnWidth(1, 48)
        self._tree.setColumnWidth(2, 90)
        self._tree.setColumnWidth(3, 56)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.itemActivated.connect(self._on_activate)
        self._tree.itemClicked.connect(self._on_activate)

        self._status_label = QLabel("", self)
        self._status_label.setObjectName("statusMuted")

        self._outer.addWidget(self._tree, 1)
        self._outer.addWidget(self._status_label)

    # --- 行为 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._remove_btn.setEnabled(writable)

    def run_check(self) -> None:
        terms = self._current_terms()
        self._terms.save(terms)
        issues = self._linter.check_all(terms)
        if self._on_issues is not None:
            self._on_issues(issues)
        self._tree.clear()
        for i, issue in enumerate(issues):
            item = QTreeWidgetItem(
                [
                    issue.rel_path,
                    str(issue.line_no),
                    _RULE_LABELS.get(issue.rule_id, issue.rule_id),
                    _SEVERITY_LABELS.get(issue.severity, issue.severity),
                    issue.message,
                ]
            )
            if issue.severity == "error":
                item.setForeground(3, Qt.GlobalColor.red)
            elif issue.severity == "warning":
                item.setForeground(3, Qt.GlobalColor.darkYellow)
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)
        if not issues:
            self._status_label.setText("检查通过，未发现问题")
        else:
            self._status_label.setText("共 {0} 项".format(len(issues)))

    def add_term(self) -> None:
        value = self._term_entry.text().strip()
        if not value:
            return
        terms = self._current_terms()
        if value not in terms:
            terms.append(value)
        self._term_entry.clear()
        self._terms.save(terms)
        self._render_terms(terms)
        self.run_check()

    def remove_term(self) -> None:
        row = self._term_list.currentRow()
        if row < 0:
            return
        terms = self._current_terms()
        if 0 <= row < len(terms):
            terms.pop(row)
            self._terms.save(terms)
            self._render_terms(terms)
            self.run_check()

    # --- 内部 ---

    def _load_terms(self) -> None:
        self._render_terms(self._terms.load())

    def _current_terms(self) -> List[str]:
        return [self._term_list.item(i).text() for i in range(self._term_list.count())]

    def _render_terms(self, terms: List[str]) -> None:
        self._term_list.clear()
        self._term_list.addItems(terms)

    def _on_activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if item is None or self._on_open is None:
            return
        rel_path = item.text(0)
        try:
            line_no = int(item.text(1))
        except ValueError:
            line_no = 1
        self._on_open(rel_path, line_no)
