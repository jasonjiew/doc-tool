# -*- coding: utf-8 -*-
"""术语/一致性检查面板（底部工具面板）。

运行重复标题、术语大小写、TODO/TBD 三类检查，结果表格展示并支持点击
定位。术语清单在面板内直接增删，保存到 ``.state/terms.json`` 后立即
重跑相关检查。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from collections import defaultdict

from PySide6.QtWidgets import (
    QComboBox,
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
    RULE_CATEGORIES,
    RULE_CATEGORY_GROUPS,
    RULE_LABELS,
    SEVERITY_LABELS,
    ContentLinter,
    LintIssue,
    TermStore,
    apply_all_quick_fixes,
    apply_quick_fix,
    can_quick_fix,
    filter_lint_issues,
)

#: 差异预览里的换行（面板不依赖平台默认换行）。
NL = chr(10)

_RULE_LABELS = RULE_LABELS
_SEVERITY_LABELS = SEVERITY_LABELS

#: V3.6 36-D：问题列表单页渲染条数（“显示更多”逐页增加，内容不截断）。
ISSUE_PAGE_SIZE = 200


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
        scope_provider: Optional[Callable[[], tuple]] = None,
        live_text_provider: Optional[Callable[[str], Optional[str]]] = None,
        scoped_linter_provider: Optional[Callable[[object, dict], object]] = None,
        buffer_applier: Optional[Callable[[str, str], bool]] = None,
        confirm_fix: Optional[Callable[[str, str, str], bool]] = None,
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
        # MAIN-D 4.1/4.2：范围（当前章/所选章/整份）、活缓冲内容、
        # 确定性修复的差异确认与撤销。
        self._scope_provider = scope_provider
        self._live_text_provider = live_text_provider
        self._scoped_linter_provider = scoped_linter_provider
        self._buffer_applier = buffer_applier
        self._confirm_fix = confirm_fix
        self._scope_paths: Optional[List[str]] = None
        self._text_overrides: Dict[str, str] = {}
        self._scope_note = "整份文档"
        #: 本次检查会话内已应用的修复（rel_path → 修复前正文），用于「撤销上次修复」。
        self._fix_history: List[tuple] = []

        # 唯一外层布局：术语卡片 + 结果表 + 状态行。原先各 _build_*
        # 各自创建 QVBoxLayout(self)，只有第一个会被安装，结果表因此不可见。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 4, 4, 4)
        self._outer.setSpacing(4)
        self._build_header()
        self._build_filter_bar()
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

    def _build_filter_bar(self) -> None:
        filter_frame = QFrame(self)
        filter_frame.setObjectName("lintFilterBar")
        layout = QHBoxLayout(filter_frame)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        lbl_cat = QLabel("分类：", filter_frame)
        layout.addWidget(lbl_cat)
        self._category_combo = QComboBox(filter_frame)
        self._category_combo.setToolTip("按规则分类或大类筛选检查结果")
        self._category_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._category_combo)

        lbl_sev = QLabel("级别：", filter_frame)
        layout.addWidget(lbl_sev)
        self._severity_combo = QComboBox(filter_frame)
        self._severity_combo.addItem("全部级别", "")
        self._severity_combo.addItem("阻断 (error)", "error")
        self._severity_combo.addItem("警告 (warning)", "warning")
        self._severity_combo.addItem("提示 (info)", "info")
        self._severity_combo.setToolTip("按问题严重度筛选")
        self._severity_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._severity_combo)

        lbl_scope = QLabel("范围：", filter_frame)
        layout.addWidget(lbl_scope)
        self._scope_combo = QComboBox(filter_frame)
        self._scope_combo.addItem("整份文档", "document")
        self._scope_combo.addItem("当前章", "current")
        self._scope_combo.addItem("所选章", "selected")
        self._scope_combo.setToolTip(
            "检查范围；当前章/所选章使用未保存的编辑器正文，结果按实际内容给出"
        )
        layout.addWidget(self._scope_combo)
        self._scope_label = QLabel("范围：整份文档", filter_frame)
        self._scope_label.setObjectName("statusMuted")
        layout.addWidget(self._scope_label)

        lbl_fix = QLabel("状态：", filter_frame)
        layout.addWidget(lbl_fix)
        self._fixable_combo = QComboBox(filter_frame)
        self._fixable_combo.addItem("全部状态", "")
        self._fixable_combo.addItem("⚡ 仅可一键修复", "fixable")
        self._fixable_combo.addItem("需人工处理", "manual")
        self._fixable_combo.setToolTip("按是否支持一键自动修复筛选")
        self._fixable_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._fixable_combo)

        self._undo_fix_btn = QPushButton("撤销上次修复", filter_frame)
        self._undo_fix_btn.setProperty("btnRole", "compact")
        self._undo_fix_btn.setToolTip("回到最近一次格式修复前的正文（按文件逐个恢复）")
        self._undo_fix_btn.clicked.connect(self.undo_last_fix)
        self._undo_fix_btn.setEnabled(False)
        layout.addWidget(self._undo_fix_btn)

        self._search_input = QLineEdit(filter_frame)
        self._search_input.setPlaceholderText("搜索文件、行号、说明或规则关键词...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search_input, 1)

        self._reset_btn = QPushButton("重置", filter_frame)
        self._reset_btn.setProperty("btnRole", "compact")
        self._reset_btn.setToolTip("清空所有筛选条件并恢复全部条目")
        self._reset_btn.clicked.connect(self.reset_filters)
        layout.addWidget(self._reset_btn)

        self._outer.addWidget(filter_frame)
        self._refresh_category_combo()

    def _refresh_category_combo(self) -> None:
        if not hasattr(self, "_category_combo"):
            return
        current_data = str(self._category_combo.currentData() or "")
        self._category_combo.blockSignals(True)
        self._category_combo.clear()
        self._category_combo.addItem("全部分类", "")

        group_counts: dict[str, int] = defaultdict(int)
        rule_counts: dict[str, int] = defaultdict(int)
        for issue in self._issues:
            rid = getattr(issue, "rule_id", "") or getattr(issue, "rule", "")
            rule_counts[rid] += 1
            cat = RULE_CATEGORIES.get(rid)
            if cat:
                group_counts[cat] += 1

        for group_name in ("格式规范", "内容质量", "结构完整", "合规与安全"):
            cnt = group_counts.get(group_name, 0)
            suffix = f" ({cnt})" if self._issues else ""
            self._category_combo.addItem(f"【{group_name}】全部{suffix}", f"group:{group_name}")

        for rid, label in sorted(RULE_LABELS.items(), key=lambda x: x[1]):
            cnt = rule_counts.get(rid, 0)
            suffix = f" ({cnt})" if self._issues else ""
            self._category_combo.addItem(f"{label}{suffix}", rid)

        for rid in sorted(rule_counts.keys()):
            if rid and rid not in RULE_LABELS:
                self._category_combo.addItem(f"{rid} ({rule_counts[rid]})", rid)

        idx = self._category_combo.findData(current_data)
        self._category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._category_combo.blockSignals(False)

    def _is_filter_active(self) -> bool:
        cat = str(self._category_combo.currentData() or "") if hasattr(self, "_category_combo") else ""
        sev = str(self._severity_combo.currentData() or "") if hasattr(self, "_severity_combo") else ""
        fix = str(self._fixable_combo.currentData() or "") if hasattr(self, "_fixable_combo") else ""
        kw = self._search_input.text().strip() if hasattr(self, "_search_input") else ""
        return bool(cat or sev or fix or kw)

    def _filtered_issue_indices(self) -> List[int]:
        cat = str(self._category_combo.currentData() or "") if hasattr(self, "_category_combo") else ""
        sev = str(self._severity_combo.currentData() or "") if hasattr(self, "_severity_combo") else ""
        fix = str(self._fixable_combo.currentData() or "") if hasattr(self, "_fixable_combo") else ""
        kw = self._search_input.text().strip() if hasattr(self, "_search_input") else ""

        fixable_opt = None
        if fix == "fixable":
            fixable_opt = True
        elif fix == "manual":
            fixable_opt = False

        filtered_list = filter_lint_issues(
            self._issues,
            category=cat,
            severity=sev,
            quick_fixable=fixable_opt,
            keyword=kw,
        )
        filtered_ids = set(id(i) for i in filtered_list)
        return [idx for idx, issue in enumerate(self._issues) if id(issue) in filtered_ids]

    def _render_results(self) -> None:
        """渲染筛选后的结果；V3.6 36-D：大列表分页，避免一次插入上万行卡住界面。"""
        self._tree.clear()
        indices = self._filtered_issue_indices()
        total_filtered = len(indices)
        page_size = max(1, int(getattr(self, "_page_size", ISSUE_PAGE_SIZE)))
        indices = indices[:page_size]
        self._paged_total = total_filtered
        for idx in indices:
            issue = self._issues[idx]
            rule_label = RULE_LABELS.get(issue.rule_id, issue.rule_id)
            if can_quick_fix(issue):
                rule_label += " [⚡可修复]"
            item = LintTreeItem(
                [
                    issue.rel_path,
                    str(issue.line_no),
                    rule_label,
                    SEVERITY_LABELS.get(issue.severity, issue.severity),
                    issue.message,
                ]
            )
            if issue.severity == "error":
                item.setForeground(3, Qt.GlobalColor.red)
            elif issue.severity == "warning":
                item.setForeground(3, Qt.GlobalColor.darkYellow)
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            self._tree.addTopLevelItem(item)

        self._on_selection_changed()

        total_cnt = len(self._issues)
        shown_cnt = len(indices)
        fixable_cnt = sum(1 for idx in indices if can_quick_fix(self._issues[idx]))
        paged = total_filtered > shown_cnt
        if hasattr(self, "_more_btn"):
            self._more_btn.setVisible(paged)
            self._more_btn.setText(
                "显示更多…（已显示 {0}/{1}）".format(shown_cnt, total_filtered)
            )

        if total_cnt == 0:
            self._status_label.setText("✓ 检查通过，未发现问题")
        elif paged:
            self._status_label.setText(
                "已显示前 {0} / 共 {1} 项（其中 {2} 项支持 ⚡ 一键修复）——可继续显示更多".format(
                    shown_cnt, total_filtered, fixable_cnt,
                )
            )
        elif shown_cnt == 0:
            self._status_label.setText(
                "无匹配结果（共 {0} 项已按分类/关键词筛选排除）".format(total_cnt)
            )
        elif shown_cnt < total_cnt:
            self._status_label.setText(
                "已筛选显示 {0} / 共 {1} 项（其中 {2} 项支持 ⚡ 一键修复）".format(
                    shown_cnt, total_cnt, fixable_cnt
                )
            )
        else:
            if fixable_cnt > 0:
                self._status_label.setText(
                    "共 {0} 项（其中 {1} 项支持 ⚡ 一键修复）".format(total_cnt, fixable_cnt)
                )
            else:
                self._status_label.setText("共 {0} 项".format(total_cnt))

    def reset_filters(self) -> None:
        if hasattr(self, "_category_combo"):
            self._category_combo.blockSignals(True)
            self._category_combo.setCurrentIndex(0)
            self._category_combo.blockSignals(False)
        if hasattr(self, "_severity_combo"):
            self._severity_combo.blockSignals(True)
            self._severity_combo.setCurrentIndex(0)
            self._severity_combo.blockSignals(False)
        if hasattr(self, "_fixable_combo"):
            self._fixable_combo.blockSignals(True)
            self._fixable_combo.setCurrentIndex(0)
            self._fixable_combo.blockSignals(False)
        if hasattr(self, "_search_input"):
            self._search_input.blockSignals(True)
            self._search_input.clear()
            self._search_input.blockSignals(False)
        self._render_results()

    def _on_filter_changed(self) -> None:
        # 筛选条件变化回到第一页，避免“筛选后只剩下一页尾部”的错觉。
        self._page_size = ISSUE_PAGE_SIZE
        self._render_results()

    def _show_more_issues(self) -> None:
        """每点一次多显示一页；实际内容不截断。"""
        self._page_size = max(1, int(getattr(self, "_page_size", ISSUE_PAGE_SIZE))) + ISSUE_PAGE_SIZE
        self._render_results()

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

        self._more_btn = QPushButton("显示更多…", self)
        self._more_btn.setProperty("btnRole", "compact")
        self._more_btn.setToolTip("分页显示更多问题（大项目一次渲染过多会卡住界面）")
        self._more_btn.clicked.connect(self._show_more_issues)
        self._more_btn.hide()
        bottom_bar.addWidget(self._more_btn)

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

        self._quick_fix_filtered_btn = QPushButton("⚡ 修复当前筛选", self)
        self._quick_fix_filtered_btn.setProperty("btnRole", "compact")
        self._quick_fix_filtered_btn.setToolTip("自动修正当前筛选结果中所有支持自动修复的问题")
        self._quick_fix_filtered_btn.setEnabled(False)
        self._quick_fix_filtered_btn.clicked.connect(self.quick_fix_all_in_filtered)
        bottom_bar.addWidget(self._quick_fix_filtered_btn)

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

    def _resolve_scope(self) -> Tuple[Optional[List[str]], Dict[str, str], str]:
        """空的章节范围保持为空，整份检查也纳入活缓冲。"""
        kind = self._scope_combo.currentData() if hasattr(self, "_scope_combo") else "document"
        current, selected = None, []
        if self._scope_provider is not None and kind != "document":
            _kind, current, selected = self._scope_provider()
        if kind == "document":
            scope_paths, note = None, "整份文档"
            paths = self._linter._index.all_files() if self._live_text_provider is not None else []
        elif kind == "current":
            paths = [current] if current else []
            scope_paths, note = paths, "当前章"
        else:
            paths = [item for item in (selected or []) if item]
            scope_paths, note = paths, "所选章"
        overrides = {}
        if self._live_text_provider is not None:
            for rel_path in paths:
                text = self._live_text_provider(rel_path)
                if text is not None:
                    overrides[rel_path] = text
        return scope_paths, overrides, note

    def run_check(self) -> None:
        terms = self._current_terms()
        persist_error = self._terms.save(terms)
        try:
            scope_paths, overrides, note = self._resolve_scope()
        except Exception as exc:  # noqa: BLE001 - 缓冲不可读时不使用旧磁盘代替
            self._issues = []
            self._render_results()
            self._status_label.setText("检查失败：无法读取章节范围或编辑缓冲：{0}".format(exc))
            return
        self._scope_paths = scope_paths
        self._text_overrides = overrides
        self._scope_note = note
        linter = self._linter
        scoped_used = False
        if self._scoped_linter_provider is not None and (
            scope_paths is not None or overrides
        ):
            try:
                scoped = self._scoped_linter_provider(scope_paths, overrides)
            except Exception:  # noqa: BLE001 - 作用域索引不可用退回原索引
                scoped = None
            if scoped is not None:
                linter = scoped
                scoped_used = True
        issues = linter.check_all(terms)
        if overrides and not scoped_used:
            # 无法按活缓冲建立作用域检查时，绝不拿旧磁盘正文冒充当前结果：
            # 有未保存正文的章节本次不报告（状态行明确说明）。
            issues = [issue for issue in issues if issue.rel_path not in overrides]
        if scope_paths is not None:
            allowed = set(scope_paths)
            issues = [issue for issue in issues if issue.rel_path in allowed]
        self._issues = list(issues)
        self._page_size = ISSUE_PAGE_SIZE
        if self._on_issues is not None:
            self._on_issues(issues)
        self._refresh_category_combo()
        self._render_results()
        if hasattr(self, "_scope_label"):
            self._scope_label.setText(
                "范围：{0}{1}".format(note, "（含未保存正文）" if overrides else "")
            )
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

        filtered_indices = self._filtered_issue_indices()
        is_filtered = self._is_filter_active() or (len(filtered_indices) < len(self._issues) and len(self._issues) > 0)
        has_filtered_fixable = any(can_quick_fix(self._issues[i]) for i in filtered_indices) if has_writer else False
        if hasattr(self, "_quick_fix_filtered_btn"):
            self._quick_fix_filtered_btn.setEnabled(has_filtered_fixable and is_filtered)

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
            filtered_indices = self._filtered_issue_indices()
            is_filtered = self._is_filter_active() or (len(filtered_indices) < len(self._issues) and len(self._issues) > 0)
            if is_filtered and any(can_quick_fix(self._issues[i]) for i in filtered_indices):
                fix_filtered_act = menu.addAction("⚡ 一键修复当前筛选全部可修复项")
                fix_filtered_act.triggered.connect(self.quick_fix_all_in_filtered)
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

    # --- MAIN-D 4.2：确定性修复的读取 / 差异确认 / 应用 / 撤销 ---

    def _read_current_text(self, rel_path: str) -> Tuple[str, bool]:
        if self._live_text_provider is not None:
            text = self._live_text_provider(rel_path)
            if text is not None:
                return str(text), True
        elif rel_path in self._text_overrides:
            return str(self._text_overrides[rel_path]), True
        return self._writer.resolve(rel_path).read_text(encoding="utf-8"), False

    def _current_text(self, rel_path: str) -> str:
        """检查后的编辑需重新检查，避免按陈旧问题位置修复。"""
        content, from_buffer = self._read_current_text(rel_path)
        expected = self._text_overrides.get(rel_path)
        if expected is not None and content != expected:
            raise ValueError("正文已变化，请重新检查后修复")
        if expected is None and from_buffer:
            raise ValueError("正文已变化，请重新检查后修复")
        if from_buffer:
            self._text_overrides[rel_path] = content
        else:
            self._text_overrides.pop(rel_path, None)
        return content

    def _write_fixed_text(self, rel_path: str, updated: str, *, expected: Optional[str] = None) -> bool:
        """确认后再次核对正文，缓冲不可写时不退回磁盘写入。"""
        if expected is not None:
            current, from_buffer = self._read_current_text(rel_path)
            if current != expected:
                self._status_label.setText("正文已变化，请重新检查后修复")
                return False
            if from_buffer:
                self._text_overrides[rel_path] = current
            else:
                self._text_overrides.pop(rel_path, None)
        if rel_path in self._text_overrides:
            try:
                applied = self._buffer_applier is not None and self._buffer_applier(rel_path, updated)
            except Exception as exc:  # noqa: BLE001 - 缓冲不可写时报告失败
                self._status_label.setText("编辑缓冲写入失败：{0}".format(exc))
                return False
            if not applied:
                self._status_label.setText("编辑缓冲不可写，请重新打开章节后检查")
                return False
            self._text_overrides[rel_path] = updated
            return True
        res = self._writer.write_text(rel_path, updated)
        if not res.written:
            self._status_label.setText(
                "修复写入失败：{0}".format(res.error or "无法写入文件")
            )
            return False
        return True

    @staticmethod
    def _diff_excerpt(before: str, after: str, line_no: int) -> Tuple[str, str]:
        """给出修复前后差异片段（以命中行为中心的 3 行窗口）。"""
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        index = max(0, int(line_no or 1) - 1)
        start = max(0, index - 1)
        before_part = before_lines[start:index + 2]
        after_part = after_lines[start:index + 2]
        return NL.join(before_part), NL.join(after_part)

    def _confirm(self, rel_path: str, before: str, after: str, line_no: int) -> bool:
        if self._confirm_fix is not None:
            return bool(self._confirm_fix(rel_path, before, after))
        if not self.isVisible():
            # 面板不可见（非交互上下文/离屏检查）：不弹模态框，直接按当前差异应用。
            # 按钮只有面板可见时才可点，因此交互路径始终会看到差异确认。
            return True
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

        before_text, after_text = self._diff_excerpt(before, after, line_no)
        dialog = QDialog(self)
        dialog.setWindowTitle("确认修复：{0}".format(rel_path))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("修复前：", dialog))
        before_view = QPlainTextEdit(before_text, dialog)
        before_view.setReadOnly(True)
        layout.addWidget(before_view)
        layout.addWidget(QLabel("修复后：", dialog))
        after_view = QPlainTextEdit(after_text, dialog)
        after_view.setReadOnly(True)
        layout.addWidget(after_view)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(640, 360)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _remember_fix(self, rel_path: str, before: str, after: str) -> None:
        self._fix_history.append((rel_path, before, after))
        if hasattr(self, "_undo_fix_btn"):
            self._undo_fix_btn.setEnabled(True)

    def undo_last_fix(self) -> bool:
        """仅在正文仍对应修复结果时撤销，保留修复后的手工编辑。"""
        if not self._writable or self._writer is None or not self._fix_history:
            return False
        rel_path, before, after = self._fix_history[-1]
        try:
            current, from_buffer = self._read_current_text(rel_path)
            if current != after:
                self._status_label.setText("正文已变化，未撤销修复；请使用编辑器撤销")
                return False
            if from_buffer:
                self._text_overrides[rel_path] = current
            else:
                self._text_overrides.pop(rel_path, None)
            if not self._write_fixed_text(rel_path, before, expected=after):
                return False
        except Exception as exc:  # noqa: BLE001 - 保留失败的撤销历史以便重试
            self._status_label.setText("撤销失败：{0}".format(exc))
            return False
        self._fix_history.pop()
        self._after_fix_applied()
        self._status_label.setText("已撤销 {0} 的本次修复".format(rel_path))
        return True

    def _after_fix_applied(self) -> None:
        if self._on_applied is not None:
            self._on_applied()
        self.run_check()
        if hasattr(self, "_undo_fix_btn"):
            self._undo_fix_btn.setEnabled(bool(self._fix_history))

    def quick_fix_issue(self, issue: LintIssue) -> bool:
        if not self._writable or self._writer is None:
            return False
        if not can_quick_fix(issue):
            return False
        try:
            rel_path = issue.rel_path
            content = self._current_text(rel_path)
            updated, success, msg = apply_quick_fix(content, issue)
            if not success:
                return False
            if not self._confirm(rel_path, content, updated, issue.line_no):
                return False
            if not self._write_fixed_text(rel_path, updated, expected=content):
                return False
            self._remember_fix(rel_path, content, updated)
            self._after_fix_applied()
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
            content = self._current_text(rel_path)
            updated, count = apply_all_quick_fixes(content, file_issues)
            if count <= 0:
                return 0
            first_line = min(
                (i.line_no for i in file_issues if can_quick_fix(i)), default=1
            )
            if not self._confirm(rel_path, content, updated, first_line):
                return 0
            if not self._write_fixed_text(rel_path, updated, expected=content):
                return 0
            self._remember_fix(rel_path, content, updated)
            self._after_fix_applied()
            self._status_label.setText(
                "✓ 已自动修复 {0} 中的 {1} 个格式问题".format(rel_path, count)
            )
            return count
        except Exception as exc:
            self._status_label.setText("批量修复失败：{0}".format(exc))
        return 0

    def quick_fix_all_in_project(self) -> int:
        """批量修复当前检查范围内的全部可修复问题。

        MAIN-D 4.1/4.2：只处理本次检查范围（整份/当前章/所选章）内的章节；
        有未保存正文的章节按缓冲内容修复并写回缓冲，普通章节走可回滚磁盘写；
        应用前给出差异确认，应用后可用「撤销上次修复」逐文件恢复。
        """
        if not self._writable or self._writer is None:
            return 0
        fixable = [i for i in self._issues if can_quick_fix(i)]
        if self._scope_paths is not None:
            allowed = set(self._scope_paths)
            fixable = [i for i in fixable if i.rel_path in allowed]
        if not fixable:
            return 0
        by_file: dict = {}
        for issue in fixable:
            by_file.setdefault(issue.rel_path, []).append(issue)

        pending: List[tuple] = []
        for rel_path, file_issues in by_file.items():
            try:
                content = self._current_text(rel_path)
                updated, count = apply_all_quick_fixes(content, file_issues)
            except Exception:
                continue
            if count > 0:
                pending.append((rel_path, file_issues, content, updated, count))
        if not pending:
            return 0
        rel_path, file_issues, content, updated, _count = pending[0]
        first_line = min((i.line_no for i in file_issues if can_quick_fix(i)), default=1)
        if not self._confirm(rel_path, content, updated, first_line):
            return 0

        total_fixed = 0
        touched = 0
        for rel_path, _issues, content, updated, count in pending:
            if not self._write_fixed_text(rel_path, updated, expected=content):
                continue
            self._remember_fix(rel_path, content, updated)
            total_fixed += count
            touched += 1

        if total_fixed > 0:
            self._after_fix_applied()
            self._status_label.setText(
                "✓ 已自动修复 {0} 个文件中的 {1} 处格式问题（范围：{2}）".format(
                    touched, total_fixed, self._scope_note
                )
            )
        return total_fixed

    def quick_fix_all_in_filtered(self) -> int:
        """自动批量修复当前筛选结果中所有支持自动修复的问题。

        MAIN-D 4.2：与单条/文件/整份修复共用同一条路径——按当前（含未保存）
        正文计算差异、应用前确认、写回可撤销，并记录撤销历史。
        """
        if not self._writable or self._writer is None:
            return 0
        indices = self._filtered_issue_indices()
        fixable = [self._issues[i] for i in indices if can_quick_fix(self._issues[i])]
        if not fixable:
            return 0
        by_file: dict = {}
        for issue in fixable:
            by_file.setdefault(issue.rel_path, []).append(issue)

        pending: List[tuple] = []
        for rel_path, file_issues in by_file.items():
            try:
                content = self._current_text(rel_path)
                updated, count = apply_all_quick_fixes(content, file_issues)
            except Exception:
                continue
            if count > 0:
                pending.append((rel_path, file_issues, content, updated, count))
        if not pending:
            return 0
        rel_path, file_issues, content, updated, _count = pending[0]
        first_line = min((i.line_no for i in file_issues if can_quick_fix(i)), default=1)
        if not self._confirm(rel_path, content, updated, first_line):
            return 0

        total_fixed = 0
        successful_files = 0
        for rel_path, _issues, content, updated, count in pending:
            if not self._write_fixed_text(rel_path, updated, expected=content):
                continue
            self._remember_fix(rel_path, content, updated)
            total_fixed += count
            successful_files += 1

        if total_fixed > 0:
            if self._on_applied is not None:
                self._on_applied()
            self.run_check()
            self._status_label.setText(
                "✓ 已自动修复当前筛选的 {0} 个文件中的 {1} 处格式问题".format(
                    successful_files, total_fixed
                )
            )
        return total_fixed

