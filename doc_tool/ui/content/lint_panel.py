# -*- coding: utf-8 -*-
"""术语/一致性检查面板（底部工具面板）。

运行重复标题、术语大小写、TODO/TBD 三类检查，结果表格展示并支持点击
定位。术语清单在面板内直接增删，保存到 ``.state/terms.json`` 后立即
重跑相关检查。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.lint import (
    ContentLinter,
    LintIssue,
    TermStore,
    apply_all_quick_fixes,
    apply_quick_fix,
    can_quick_fix,
)

_RULE_LABELS = {
    "duplicate_title": "重复标题",
    "term_case": "术语大小写",
    "todo_residual": "待办残留",
    "required_section": "必备章节",
    "field_completeness": "字段完整性",
    "numbering_uniqueness": "编号唯一性",
    "sensitive_info": "敏感信息",
    "interface_table_structure": "接口表结构",
    "markdown_structure": "表格结构",
    "mermaid_syntax": "流程图语法",
    "heading_format": "标题格式",
}

_SEVERITY_LABELS = {
    "error": "阻断",
    "warning": "警告",
    "info": "提示",
}


class LintTreeItem(QTreeWidgetItem):
    """支持按自然路径与数值行号排序的树条目。"""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree is not None else 0
        if col < 0:
            col = 0
        if col == 0:
            from doc_tool.domain.content_index import path_natural_sort_key
            k1 = path_natural_sort_key(self.text(0))
            k2 = path_natural_sort_key(other.text(0))
            if k1 != k2:
                return k1 < k2
            try:
                return int(self.text(1)) < int(other.text(1))
            except ValueError:
                return self.text(1) < other.text(1)
        if col == 1:
            try:
                return int(self.text(1)) < int(other.text(1))
            except ValueError:
                pass
        return self.text(col) < other.text(col)


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
        writer=None,
        on_applied: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._linter = linter
        self._terms = terms
        self._on_open = on_open
        self._on_issues = on_issues
        self._writable = writable
        self._writer = writer
        self._on_applied = on_applied
        self._issues: List[LintIssue] = []

        # 唯一外层布局：术语卡片 + 结果表 + 状态行。原先各 _build_*
        # 各自创建 QVBoxLayout(self)，只有第一个会被安装，结果表因此不可见。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 4, 4, 4)
        self._outer.setSpacing(4)
        self._build_header()
        self._build_results()

    # --- 构建 ---

    def _build_header(self) -> None:
        header_frame = QFrame(self)
        header_frame.setProperty("card", True)
        layout = QVBoxLayout(header_frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # 顶部操作行：功能说明 + 主操作按钮
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        title_lbl = QLabel("<b>Markdown 格式与规范检查</b>", header_frame)
        desc_lbl = QLabel("检查标题格式、未闭合代码块/表格、Mermaid语法及术语；双击结果直达文件所在行", header_frame)
        desc_lbl.setObjectName("statusMuted")
        info_col.addWidget(title_lbl)
        info_col.addWidget(desc_lbl)
        top_row.addLayout(info_col, 1)

        self._run_btn = QPushButton("🔍 运行格式检查", header_frame)
        self._run_btn.setProperty("btnRole", "primary")
        self._run_btn.clicked.connect(self.run_check)
        top_row.addWidget(self._run_btn)
        layout.addLayout(top_row)

        # 术语折叠配置区（按需展开，避免抢占视觉焦点）
        term_toggle_btn = QPushButton("▸ 术语字典配置（可选）", header_frame)
        term_toggle_btn.setFlat(True)
        term_toggle_btn.setProperty("btnRole", "compact")
        term_toggle_btn.setStyleSheet("text-align: left; padding: 2px; font-weight: normal;")
        layout.addWidget(term_toggle_btn)

        terms_box = QWidget(header_frame)
        terms_layout = QHBoxLayout(terms_box)
        terms_layout.setContentsMargins(0, 0, 0, 0)
        terms_layout.setSpacing(6)

        self._term_list = QListWidget(terms_box)
        self._term_list.setMaximumHeight(64)
        terms_layout.addWidget(self._term_list, 1)

        side = QWidget(terms_box)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(2)
        self._term_entry = QLineEdit(side)
        self._term_entry.setPlaceholderText("术语规范拼写")
        side_layout.addWidget(self._term_entry)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加", side)
        add_btn.setProperty("btnRole", "secondary")
        add_btn.clicked.connect(self.add_term)
        btn_row.addWidget(add_btn)
        self._remove_btn = QPushButton("删除", side)
        self._remove_btn.setProperty("btnRole", "compact")
        self._remove_btn.clicked.connect(self.remove_term)
        btn_row.addWidget(self._remove_btn)
        side_layout.addLayout(btn_row)
        terms_layout.addWidget(side)

        terms_box.setVisible(False)
        layout.addWidget(terms_box)

        def toggle_terms():
            is_visible = terms_box.isVisible()
            terms_box.setVisible(not is_visible)
            term_toggle_btn.setText("▾ 术语字典配置（可选）" if not is_visible else "▸ 术语字典配置（可选）")

        term_toggle_btn.clicked.connect(toggle_terms)

        self._outer.addWidget(header_frame)
        self._load_terms()

    def _build_results(self) -> None:
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["文件", "行", "类型", "级别", "说明"])
        self._tree.setColumnWidth(0, 240)
        self._tree.setColumnWidth(1, 48)
        self._tree.setColumnWidth(2, 110)
        self._tree.setColumnWidth(3, 56)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tree.itemActivated.connect(self._on_activate)
        self._tree.itemClicked.connect(self._on_activate)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(0, 0, 0, 0)
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("statusMuted")
        bottom_bar.addWidget(self._status_label, 1)

        self._quick_fix_btn = QPushButton("⚡ 一键修复", self)
        self._quick_fix_btn.setProperty("btnRole", "compact")
        self._quick_fix_btn.setToolTip("自动修正所选问题的格式（如添加标题空格、闭合代码块、生成表格分隔线）")
        self._quick_fix_btn.setEnabled(False)
        self._quick_fix_btn.clicked.connect(self._on_quick_fix_clicked)
        bottom_bar.addWidget(self._quick_fix_btn)

        self._quick_fix_file_btn = QPushButton("⚡ 修复本文件全部", self)
        self._quick_fix_file_btn.setProperty("btnRole", "compact")
        self._quick_fix_file_btn.setToolTip("自动修正选中文件中的全部可修复格式问题")
        self._quick_fix_file_btn.setEnabled(False)
        self._quick_fix_file_btn.clicked.connect(self._on_quick_fix_file_clicked)
        bottom_bar.addWidget(self._quick_fix_file_btn)

        self._quick_fix_all_btn = QPushButton("⚡ 修复全项目全部", self)
        self._quick_fix_all_btn.setProperty("btnRole", "compact")
        self._quick_fix_all_btn.setToolTip("自动修正当前项目全部文档中所有可修复格式问题")
        self._quick_fix_all_btn.setEnabled(False)
        self._quick_fix_all_btn.clicked.connect(self._on_quick_fix_all_clicked)
        bottom_bar.addWidget(self._quick_fix_all_btn)

        self._outer.addWidget(self._tree, 1)
        self._outer.addLayout(bottom_bar)

    # --- 行为 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._remove_btn.setEnabled(writable)

    def run_check(self) -> None:
        terms = self._current_terms()
        persist_error = self._terms.save(terms)
        issues = self._linter.check_all(terms)
        self._issues = list(issues)
        if self._on_issues is not None:
            self._on_issues(issues)
        self._tree.clear()
        for i, issue in enumerate(issues):
            rule_label = _RULE_LABELS.get(issue.rule_id, issue.rule_id)
            if can_quick_fix(issue):
                rule_label += " [⚡可修复]"
            item = LintTreeItem(
                [
                    issue.rel_path,
                    str(issue.line_no),
                    rule_label,
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
        self._on_selection_changed()
        fixable_cnt = sum(1 for i in issues if can_quick_fix(i))
        if not issues:
            self._status_label.setText("✓ 检查通过，未发现问题")
        else:
            if fixable_cnt > 0:
                self._status_label.setText(
                    "共 {0} 项（其中 {1} 项支持 ⚡ 一键修复）".format(len(issues), fixable_cnt)
                )
            else:
                self._status_label.setText("共 {0} 项".format(len(issues)))
        if persist_error:
            # 术语未持久化必须提示：否则用户以为已保存、重启后消失。
            self._status_label.setText(
                self._status_label.text() + "；术语保存失败：{0}".format(persist_error)
            )

    def add_term(self) -> None:
        value = self._term_entry.text().strip()
        if not value:
            return
        terms = self._current_terms()
        if value not in terms:
            terms.append(value)
        self._term_entry.clear()
        self._render_terms(terms)
        self.run_check()  # run_check 内部保存术语并透出持久化失败

    def remove_term(self) -> None:
        row = self._term_list.currentRow()
        if row < 0:
            return
        terms = self._current_terms()
        if 0 <= row < len(terms):
            terms.pop(row)
            self._render_terms(terms)
            self.run_check()  # run_check 内部保存术语并透出持久化失败

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

    def _on_selection_changed(self) -> None:
        has_writer = bool(self._writable and self._writer is not None)
        any_fixable = any(can_quick_fix(i) for i in self._issues) if has_writer else False
        self._quick_fix_all_btn.setEnabled(any_fixable)

        current = self._tree.currentItem()
        if current is None or not has_writer:
            self._quick_fix_btn.setEnabled(False)
            self._quick_fix_file_btn.setEnabled(False)
            return
        idx = current.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None and 0 <= idx < len(self._issues):
            issue = self._issues[idx]
            file_has_fixable = any(can_quick_fix(i) for i in self._issues if i.rel_path == issue.rel_path)
            self._quick_fix_btn.setEnabled(can_quick_fix(issue))
            self._quick_fix_file_btn.setEnabled(file_has_fixable)
        else:
            self._quick_fix_btn.setEnabled(False)
            self._quick_fix_file_btn.setEnabled(False)

    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is None or not (0 <= idx < len(self._issues)):
            return
        issue = self._issues[idx]
        menu = QMenu(self)

        open_act = menu.addAction("定位到所在行")
        open_act.triggered.connect(lambda: self._on_activate(item))

        if self._writable and self._writer is not None:
            if can_quick_fix(issue):
                fix_act = menu.addAction("⚡ 一键修复此条目")
                fix_act.triggered.connect(lambda: self.quick_fix_issue(issue))
            if any(can_quick_fix(i) for i in self._issues if i.rel_path == issue.rel_path):
                fix_all_act = menu.addAction("⚡ 一键修复本文件全部可修复项")
                fix_all_act.triggered.connect(lambda: self.quick_fix_all_in_file(issue.rel_path))
            if any(can_quick_fix(i) for i in self._issues):
                fix_proj_act = menu.addAction("⚡ 一键修复全项目全部可修复项")
                fix_proj_act.triggered.connect(self.quick_fix_all_in_project)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_quick_fix_clicked(self) -> None:
        current = self._tree.currentItem()
        if current is None:
            return
        idx = current.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None and 0 <= idx < len(self._issues):
            self.quick_fix_issue(self._issues[idx])

    def _on_quick_fix_file_clicked(self) -> None:
        current = self._tree.currentItem()
        if current is None:
            return
        idx = current.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None and 0 <= idx < len(self._issues):
            self.quick_fix_all_in_file(self._issues[idx].rel_path)

    def _on_quick_fix_all_clicked(self) -> None:
        self.quick_fix_all_in_project()

    def quick_fix_issue(self, issue: LintIssue) -> bool:
        if not self._writable or self._writer is None:
            return False
        if not can_quick_fix(issue):
            return False
        try:
            rel_path = issue.rel_path
            abs_path = self._writer.resolve(rel_path)
            content = abs_path.read_text(encoding="utf-8")
            updated, success, msg = apply_quick_fix(content, issue)
            if success:
                res = self._writer.write_text(rel_path, updated)
                if not res.written:
                    self._status_label.setText("修复写入失败：{0}".format(res.error or "无法写入文件"))
                    return False
                if self._on_applied is not None:
                    self._on_applied()
                self.run_check()
                self._status_label.setText("✓ {0}".format(msg))
                return True
        except Exception as exc:
            self._status_label.setText("修复失败：{0}".format(exc))
        return False

    def quick_fix_all_in_file(self, rel_path: str) -> int:
        if not self._writable or self._writer is None:
            return 0
        file_issues = [i for i in self._issues if i.rel_path == rel_path]
        if not file_issues:
            return 0
        try:
            abs_path = self._writer.resolve(rel_path)
            content = abs_path.read_text(encoding="utf-8")
            updated, count = apply_all_quick_fixes(content, file_issues)
            if count > 0:
                res = self._writer.write_text(rel_path, updated)
                if not res.written:
                    self._status_label.setText("批量修复写入失败：{0}".format(res.error or "无法写入文件"))
                    return 0
                if self._on_applied is not None:
                    self._on_applied()
                self.run_check()
                self._status_label.setText(
                    "✓ 已自动修复 {0} 中的 {1} 个格式问题".format(rel_path, count)
                )
                return count
        except Exception as exc:
            self._status_label.setText("批量修复失败：{0}".format(exc))
        return 0

    def quick_fix_all_in_project(self) -> int:
        """自动批量修复整个项目中所有支持自动修复的问题。"""
        if not self._writable or self._writer is None:
            return 0
        fixable = [i for i in self._issues if can_quick_fix(i)]
        if not fixable:
            return 0
        by_file: dict = {}
        for issue in fixable:
            by_file.setdefault(issue.rel_path, []).append(issue)

        total_fixed = 0
        for rel_path, file_issues in by_file.items():
            try:
                abs_path = self._writer.resolve(rel_path)
                content = abs_path.read_text(encoding="utf-8")
                updated, count = apply_all_quick_fixes(content, file_issues)
                if count > 0:
                    res = self._writer.write_text(rel_path, updated)
                    if res.written:
                        total_fixed += count
            except Exception:
                continue

        if total_fixed > 0:
            if self._on_applied is not None:
                self._on_applied()
            self.run_check()
            self._status_label.setText(
                "✓ 已自动修复全项目 {0} 个文件中的 {1} 处格式问题".format(
                    len(by_file), total_fixed
                )
            )
        return total_fixed

