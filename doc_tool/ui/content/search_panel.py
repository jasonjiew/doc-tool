# -*- coding: utf-8 -*-
"""全文搜索面板（底部工具面板）。

输入去抖自动搜索；结果以"文件 + 行号 + 上下文预览"表格展示，点击定位。
支持正则/大小写/整词开关与文档类型范围过滤；超阈值显示"显示更多"。
复用 ``SearchService``；搜索在后台线程执行，UI 经 ``TaskRunner`` 轮询。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
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

from doc_tool.application.content.search import (
    DEFAULT_LIMIT,
    SearchOptions,
    SearchResult,
    SearchService,
)

# 文档类型过滤下拉：显示名 -> 过滤值。
# 仅旧版多类型布局（同时含 requirement/design）时展示；通用单项目隐藏。
_TYPE_FILTERS = (
    ("全部", None),
    ("需求文档（旧版专用）", "requirement"),
    ("详细设计文档（旧版专用）", "design"),
    ("通用大文档", "general"),
)

_DEBOUNCE_MS = 350


class SearchPanel(QWidget):
    """全文搜索面板。

    ``on_open(rel_path, line_no)``：结果项被点击时回调，用于在编辑器打开
    文件并定位到命中行。
    """

    def __init__(
        self,
        service: SearchService,
        *,
        on_open: Optional[Callable[[str, int], None]] = None,
        show_type_filter: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._on_open = on_open
        # 通用单项目不展示需求/设计类型筛选；仅旧版多类型布局保留兼容过滤。
        self._show_type_filter = show_type_filter
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self.search_now)
        self._limit = DEFAULT_LIMIT
        self._last_result: Optional[SearchResult] = None
        # 旧搜索运行中输入的新查询：待旧任务终态后自动启动，不静默丢弃。
        self._pending_options: Optional[SearchOptions] = None

        from doc_tool.ui.task_bridge import TaskRunner

        self._runner = TaskRunner()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll)

        # 唯一外层布局：控件行 + 结果表 + “显示更多”。原先各 _build_* 各自
        # 创建 QVBoxLayout(self)，只有第一个会被安装，结果表因此不可见。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 4, 4, 4)
        self._build_controls()
        self._build_results()

    # --- 构建 ---

    def _build_controls(self) -> None:
        controls = QWidget(self)
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        self._query_entry = QLineEdit(controls)
        self._query_entry.setPlaceholderText("全文搜索…")
        self._query_entry.returnPressed.connect(self.search_now)
        self._query_entry.textEdited.connect(self._schedule)
        layout.addWidget(self._query_entry, 1)

        self._search_btn = QPushButton("搜索", controls)
        self._search_btn.setProperty("btnRole", "secondary")
        self._search_btn.clicked.connect(self.search_now)
        layout.addWidget(self._search_btn)

        self._type_box = QComboBox(controls)
        self._type_box.addItems([label for label, _ in _TYPE_FILTERS])
        self._type_box.currentIndexChanged.connect(lambda _i: self.search_now())
        # 通用单项目不显示类型筛选；旧版多类型布局显示。
        self._type_box.setVisible(self._show_type_filter)
        layout.addWidget(self._type_box)

        self._regex_cb = QCheckBox("正则", controls)
        self._regex_cb.stateChanged.connect(lambda _s: self.search_now())
        layout.addWidget(self._regex_cb)
        self._case_cb = QCheckBox("区分大小写", controls)
        self._case_cb.stateChanged.connect(lambda _s: self.search_now())
        layout.addWidget(self._case_cb)
        self._word_cb = QCheckBox("整词", controls)
        self._word_cb.stateChanged.connect(lambda _s: self.search_now())
        layout.addWidget(self._word_cb)

        self._summary_label = QLabel("", controls)
        self._summary_label.setObjectName("statusMuted")
        layout.addWidget(self._summary_label)

        self._outer.addWidget(controls)

    def _build_results(self) -> None:
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["文件", "行", "内容预览"])
        self._tree.setColumnWidth(0, 300)
        self._tree.setColumnWidth(1, 48)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.itemActivated.connect(self._on_activate)
        self._tree.itemClicked.connect(self._on_activate)

        self._more_btn = QPushButton("显示更多…", self)
        self._more_btn.setProperty("btnRole", "compact")
        self._more_btn.clicked.connect(self._show_more)
        self._more_btn.hide()

        self._outer.addWidget(self._tree, 1)
        self._outer.addWidget(self._more_btn)

    # --- 行为 ---

    def _schedule(self) -> None:
        self._debounce_timer.stop()
        self._debounce_timer.start(_DEBOUNCE_MS)

    def search_now(self) -> None:
        self._debounce_timer.stop()
        options = self._current_options()
        if not options.query.strip():
            self._pending_options = None
            self._render(SearchResult(query="", total=0))
            return
        from doc_tool.application.content.search import compile_pattern

        try:
            compile_pattern(
                options.query,
                regex=options.regex,
                case_sensitive=options.case_sensitive,
                whole_word=options.whole_word,
            )
        except ValueError as exc:
            self._summary_label.setText("查询无效：{0}".format(exc))
            return
        if self._runner.is_running:
            # 旧搜索仍在运行：TaskRunner.start 在运行中直接返回 False，取消再启动
            # 会静默丢弃新查询。改为记录为排队查询，待旧任务终态回调后自动启动。
            self._pending_options = options
            self._summary_label.setText("搜索中…")
            return
        self._pending_options = None
        self._summary_label.setText("搜索中…")
        self._start_search(options)

    def _start_search(self, options: SearchOptions) -> None:
        from doc_tool.application.content.search import run_search
        from doc_tool.ui.task_bridge import TaskSpec

        self._runner.start(
            TaskSpec(
                name="search",
                target=run_search,
                kwargs={"service": self._service, "options": options},
            ),
            on_done=self._on_search_done,
        )
        self._poll_timer.start()

    def _poll(self) -> None:
        self._runner.poll()
        if not self._runner.is_running:
            self._poll_timer.stop()

    def _on_search_done(self, result) -> None:
        pending = self._pending_options
        self._pending_options = None
        if pending is not None:
            # 有排队的新查询：丢弃过期旧结果，直接启动新搜索。
            self._start_search(pending)
            return
        if result is None:
            if self._runner.is_cancelled:
                self._summary_label.setText("搜索被取消")
            else:
                self._summary_label.setText("搜索失败，请检查查询条件")
            return
        self._last_result = result
        self._render(result)

    def _current_options(self) -> SearchOptions:
        # 通用单项目默认搜索全部内容，不应用类型过滤。
        if not self._show_type_filter:
            return SearchOptions(
                query=self._query_entry.text(),
                regex=self._regex_cb.isChecked(),
                case_sensitive=self._case_cb.isChecked(),
                whole_word=self._word_cb.isChecked(),
                document_types=None,
                limit=self._limit,
            )
        selected_label = self._type_box.currentText()
        doc_types = next(
            (value for label, value in _TYPE_FILTERS if label == selected_label),
            None,
        )
        return SearchOptions(
            query=self._query_entry.text(),
            regex=self._regex_cb.isChecked(),
            case_sensitive=self._case_cb.isChecked(),
            whole_word=self._word_cb.isChecked(),
            document_types=([doc_types] if doc_types else None),
            limit=self._limit,
        )

    def _render(self, result: SearchResult) -> None:
        self._tree.clear()
        for hit in result.hits:
            preview = hit.text.strip()
            if len(preview) > 200:
                preview = preview[:200] + "…"
            item = QTreeWidgetItem(
                [hit.rel_path, str(hit.line_no), preview]
            )
            self._tree.addTopLevelItem(item)
        if result.total == 0:
            summary = "无匹配内容" if result.query else "请输入关键字"
        elif result.truncated:
            summary = "共 {0} 处（{1} 个文件），显示前 {2} 条".format(
                result.total, result.file_count, len(result.hits)
            )
        else:
            summary = "共 {0} 处（{1} 个文件）".format(
                result.total, result.file_count
            )
        self._summary_label.setText(summary)
        self._more_btn.setVisible(result.truncated)

    def _show_more(self) -> None:
        self._limit += DEFAULT_LIMIT
        self.search_now()

    def _on_activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if item is None or self._on_open is None:
            return
        rel_path = item.text(0)
        try:
            line_no = int(item.text(1))
        except ValueError:
            line_no = 1
        self._on_open(rel_path, line_no)

    # --- 外部控制 ---

    def focus_query(self) -> None:
        """聚焦搜索输入框并选中已有文本（Ctrl+F 定位用）。"""
        self._query_entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._query_entry.selectAll()

    def set_writable(self, writable: bool) -> None:
        """搜索是只读操作，始终可用；保留接口以便状态统一。"""
