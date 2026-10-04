# -*- coding: utf-8 -*-
"""结构化问题中心：组合筛选、严重度摘要与文件定位。"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

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

from doc_tool.application.content.quality_workbench import (
    GROUP_BY_CHAPTER,
    GROUP_BY_RULE,
    GROUP_BY_SEVERITY,
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
        # V4.2 42-C 3.1：分组维度（默认不分组，保持原列表口径）。
        self._group_combo = QComboBox(self)
        self._group_combo.setToolTip("按章节/规则/严重度分组展示；分组不改变实际总量")
        self._group_combo.addItem("不分组", "")
        self._group_combo.addItem("按章节", GROUP_BY_CHAPTER)
        self._group_combo.addItem("按规则", GROUP_BY_RULE)
        self._group_combo.addItem("按严重度", GROUP_BY_SEVERITY)
        self._group_combo.currentIndexChanged.connect(self._render)
        filters.addWidget(self._group_combo)

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
        # V4.2 42-C 3.2：本轮检查范围/时点/过期事实（缺证据显示未知）。
        self._context_label = QLabel("", self)
        self._context_label.setObjectName("statusMuted")
        self._context_label.setWordWrap(True)
        outer.addWidget(self._context_label)

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(7)
        headers = ["严重度", "类型", "文档类型", "文件", "行", "消息", "错误码"]
        if not self._show_document_type:
            headers = [h for h in headers if h != "文档类型"]
            self._tree.setColumnCount(len(headers))
        self._tree.setHeaderLabels(headers)
        # 分组展示时需要展开的分组节点。
        self._tree.setRootIsDecorated(True)
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

        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        self._state = QLabel("无当前项目数据", self)
        self._state.setObjectName("statusMuted")
        state_row.addWidget(self._state, 1)
        # 37-C 3.1：空/无结果状态就地给出下一步——清除筛选回到输入，
        # 而不是让用户自己找哪个下拉框把结果筛没了。
        self._clear_filters_btn = QPushButton("清除筛选", self)
        self._clear_filters_btn.setProperty("btnRole", "compact")
        self._clear_filters_btn.setToolTip("清空类型/严重度/文件与搜索关键词，恢复全部问题")
        self._clear_filters_btn.clicked.connect(self.reset_filters)
        self._clear_filters_btn.setVisible(False)
        state_row.addWidget(self._clear_filters_btn)
        outer.addLayout(state_row)

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

    @staticmethod
    def _rule_of(issue) -> str:
        from doc_tool.application.content.quality_workbench import rule_of

        return rule_of(issue)

    def set_group_by(self, value: str) -> None:
        """按维度分组展示（只改层级，不改实际总量与严重度统计）。"""
        index = self._group_combo.findData(str(value or ""))
        if index >= 0 and index != self._group_combo.currentIndex():
            self._group_combo.setCurrentIndex(index)
        elif index >= 0:
            self._render()

    def group_by(self) -> str:
        return str(self._group_combo.currentData() or "")

    def group_summary(self):
        """当前筛选结果的分组计数（供界面/测试核对实际总量）。"""
        from doc_tool.application.content.quality_workbench import group_summary

        return group_summary(self.filtered_issues(), by=self.group_by()) if self.group_by() else []

    def set_check_context(self, *, scope_text: str = "", checked_at: str = "", staleness: str = "") -> None:
        """记录本轮检查的范围/时点/过期事实（缺证据显示未知）。"""
        self._check_context = {
            "scopeText": str(scope_text or ""),
            "checkedAt": str(checked_at or ""),
            "staleness": str(staleness or ""),
        }
        self._render()

    def _context_text(self) -> str:
        context = dict(getattr(self, "_check_context", {}) or {})
        if not context:
            return "检查范围/时点：未知（尚未执行范围检查）"
        scope = context.get("scopeText") or "未知"
        checked = context.get("checkedAt") or "未知"
        staleness = context.get("staleness") or ""
        label = {"fresh": "最新", "stale": "待重检", "unknown": "未知"}.get(staleness, "未知")
        return "本轮检查范围：{0}｜检查时间：{1}｜结果状态：{2}".format(scope, checked, label)

    def check_context(self) -> Dict[str, str]:
        return dict(getattr(self, "_check_context", {}) or {})

    def set_baseline_issues(self, issues) -> None:
        """设置上一轮真实结果（供新增/消失/保留比较）；``None`` 表示缺基线。"""
        self._baseline_issues = None if issues is None else list(issues)
        self._render()

    def baseline_comparison(self):
        """本轮（未筛选的完整集合）与基线的比较；缺基线为未知。"""
        from doc_tool.application.content.quality_workbench import compare_issues

        baseline = getattr(self, "_baseline_issues", None)
        if baseline is None:
            return compare_issues(None, self._issues)
        return compare_issues(baseline, self._issues)

    def view_state(self) -> Dict[str, str]:
        """可还原的筛选状态（37-B 2.1：跳转返回后恢复原筛选与选中行）。"""
        state = {
            "type": self._selected(self._type),
            "severity": self._selected(self._severity),
            "file": self._selected(self._file),
            "keyword": self._search_input.text() if hasattr(self, "_search_input") else "",
        }
        if self._show_document_type:
            state["documentType"] = self._selected(self._document_type)
        if hasattr(self, "_group_combo"):
            state["groupBy"] = self.group_by()
        item = self._tree.currentItem() if hasattr(self, "_tree") else None
        issue = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if issue is None and item is not None and item.parent() is not None:
            # 分组模式下选中行是子节点，取父节点（分组）不代表具体问题。
            issue = None
        if isinstance(issue, IssueRecord):
            state["selected"] = "{0}:{1}:{2}".format(
                issue.rel_path, issue.line_no or 0, issue.issue_type,
            )
        return state

    def restore_view_state(self, state: Dict[str, str]) -> None:
        """恢复筛选与选中行；缺失/过期值退回默认，不抛异常。"""
        if not state:
            return
        pairs = [
            (self._type, state.get("type", "")),
            (self._severity, state.get("severity", "")),
            (self._file, state.get("file", "")),
        ]
        if self._show_document_type:
            pairs.append((self._document_type, state.get("documentType", "")))
        for combo, value in pairs:
            combo.blockSignals(True)
            index = combo.findData(value) if value else 0
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        if hasattr(self, "_search_input"):
            self._search_input.blockSignals(True)
            self._search_input.setText(state.get("keyword", ""))
            self._search_input.blockSignals(False)
        if hasattr(self, "_group_combo") and "groupBy" in state:
            index = self._group_combo.findData(state.get("groupBy", ""))
            self._group_combo.blockSignals(True)
            self._group_combo.setCurrentIndex(index if index >= 0 else 0)
            self._group_combo.blockSignals(False)
        self._render()
        wanted = state.get("selected", "")
        if not wanted:
            return
        for item in self._iter_issue_items():
            issue = item.data(0, Qt.ItemDataRole.UserRole)
            key = "{0}:{1}:{2}".format(issue.rel_path, issue.line_no or 0, issue.issue_type)
            if key == wanted:
                if item.parent() is not None:
                    item.parent().setExpanded(True)
                self._tree.setCurrentItem(item)
                break

    def _iter_issue_items(self):
        """遍历全部问题行（含分组层级下的子节点）。"""
        for index in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(index)
            if isinstance(top.data(0, Qt.ItemDataRole.UserRole), IssueRecord):
                yield top
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                if isinstance(child.data(0, Qt.ItemDataRole.UserRole), IssueRecord):
                    yield child

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
        grouped = self.group_by() if hasattr(self, "_group_combo") else ""
        if grouped:
            # V4.2 42-C 3.1：按章节/规则分组展示——分组只改层级，不改实际总量。
            from doc_tool.application.content.quality_workbench import group_summary

            self._summary.setText(
                "error {error} · warning {warning} · info {info} · 共 {total} 条按 {label} 分 {groups} 组".format(
                    total=len(visible), label=grouped, groups=len(group_summary(visible, by=grouped)),
                    **summary
                )
            )
        else:
            self._summary.setText(
                "error {error} · warning {warning} · info {info}".format(**summary)
            )
        if hasattr(self, "_context_label"):
            self._context_label.setText(self._context_text())
        if hasattr(self, "_baseline_issues"):
            comparison = self.baseline_comparison()
            note = "；".join(comparison.summary_lines())
            self._summary.setToolTip(note)
            if not comparison.known:
                # 缺基线只说明未知，不冒充“无变化/已清零”。
                self._summary.setText(
                    self._summary.text() + "｜与基线：未知（缺上一轮结果）"
                )
            else:
                self._summary.setText(
                    self._summary.text() + "｜与基线：新增 {0}／消失 {1}／保留 {2}".format(
                        len(comparison.added), len(comparison.removed), len(comparison.retained)
                    )
                )
        self._tree.clear()
        parents: Dict[str, QTreeWidgetItem] = {}
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
            if grouped:
                key = (
                    str(getattr(issue, "rel_path", "") or "未定位")
                    if grouped == GROUP_BY_CHAPTER
                    else (self._rule_of(issue) or "未命名规则")
                ) if grouped != GROUP_BY_SEVERITY else str(getattr(issue, "severity", "") or "未分级")
                parent = parents.get(key)
                if parent is None:
                    parent = QTreeWidgetItem(["", "", key, "", "", ""])
                    parent.setData(0, Qt.ItemDataRole.UserRole, None)
                    self._tree.addTopLevelItem(parent)
                    parents[key] = parent
                parent.addChild(item)
            else:
                self._tree.addTopLevelItem(item)
        filters_active = self._filters_active()
        if not self._has_project:
            self._state.setText("无当前项目数据：打开或导入项目后这里会列出问题")
        elif self._issues and not visible:
            self._state.setText(
                "无匹配结果：当前筛选条件下没有命中，可清除筛选或修改关键词"
                if filters_active else "无匹配结果"
            )
        elif not self._issues:
            self._state.setText("当前项目未发现问题，可继续编辑或运行检查")
        else:
            latest = max((i.generated_at for i in visible), default="")
            sources = "、".join(sorted(set(i.source for i in visible)))
            self._state.setText("共 {0} 项 · 来源 {1} · {2}".format(len(visible), sources, latest))
        if hasattr(self, "_clear_filters_btn"):
            self._clear_filters_btn.setVisible(bool(filters_active and self._issues and not visible))

    def _filters_active(self) -> bool:
        """当前是否有生效的筛选条件（决定「清除筛选」是否作为下一步动作出现）。"""
        combos = [self._type, self._severity, self._file]
        if self._show_document_type:
            combos.append(self._document_type)
        if any(self._selected(combo) for combo in combos):
            return True
        return bool(getattr(self, "_search_input", None) and self._search_input.text().strip())

    def _activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        issue = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(issue, IssueRecord) or self._on_open is None:
            return
        if not issue.rel_path:
            if self._on_status is not None:
                self._on_status("该问题没有可定位的文件")
            return
        self._on_open(issue.rel_path, issue.line_no)
