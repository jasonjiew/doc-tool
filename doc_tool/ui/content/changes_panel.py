# -*- coding: utf-8 -*-
"""改动汇总面板（底部工具面板第 5 个 Tab）。

以「会话改动」为单一入口：按状态分组列出新增/已修改/已删除文件 + 计数，
选中项显示「基线 vs 当前」diff，提供单文件恢复/撤销（经 ``ContentWriter``
restore_file）与「回滚全部会话改动」。已删除文件从快照 diff 列出，恢复走
改动清单 delete 条目的回收站路径。

``snapshot``：``ContentSnapshot``（基线内容副本，diff 原文来源）。
``writer``：``ContentWriter``（改动清单 + 单文件恢复）。
``on_restored()``：单文件恢复/回滚全部成功后回调（上层重建索引与树）。

顶部计数行同时展示检测来源（``set_source``）：Git / SVN / 本地快照。
非可恢复条目（如 Git/SVN 检测出的 ``project.yml`` 变更）仅展示，禁用恢复。
``rollback_all``：可选的「回滚全部」实现；VCS 模式下由上层用
git restore / svn revert 恢复，而不是本地 .bak 清单。
``on_commit`` / ``on_pull``：可选的「提交改动」/「拉取更新」实现；
仅在 Git/SVN 项目启用（git > svn），由上层执行 git add/commit、git pull
或 svn add/rm/commit、svn update。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.changes import ChangeItem
from doc_tool.application.content.vcs_changes import PullResult, PushResult
from doc_tool.ui.operation_loading_overlay import run_async_operation

_ITEM_LABELS = {"added": "新增", "modified": "已修改", "deleted": "已删除"}

# 检测来源 → 展示文本。
_SOURCE_LABELS = {
    "git": "Git",
    "svn": "SVN",
    "local": "本地快照",
}


class ChangesPanel(QWidget):
    """改动汇总面板。

    ``set_items(items)``：由上层（工作区）推送改动项并渲染；选中项由面板
    直接读 ``snapshot`` / ``content_root`` 计算 diff。只读时隐藏写操作。
    ``set_source(source)``：标注变更检测来源（git/svn/local）。
    """

    def __init__(
        self,
        *,
        snapshot,
        writer,
        content_root,
        on_restored: Optional[Callable[[], None]] = None,
        writable: bool = True,
        rollback_all: Optional[Callable[[], List[str]]] = None,
        rollback_single: Optional[Callable[[ChangeItem], Optional[str]]] = None,
        on_open_file: Optional[Callable[[str], None]] = None,
        on_commit: Optional[Callable[[str], List[str]]] = None,
        on_commit_files: Optional[Callable[[Sequence[str], str], List[str]]] = None,
        on_pull: Optional[Callable[[], PullResult]] = None,
        on_push: Optional[Callable[[], PushResult]] = None,
        on_export_review: Optional[Callable[[], None]] = None,
        on_detection_mode_changed: Optional[Callable[[str], None]] = None,
        initial_detection_mode: str = "vcs",
        on_set_baseline: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._writer = writer
        self._content_root = Path(content_root).resolve()
        self._on_restored = on_restored
        self._writable = writable
        # VCS 模式下由上层提供版本控制回滚实现（否则用本地 .bak 清单）。
        self._rollback_all = rollback_all
        self._rollback_single = rollback_single
        self._on_open_file = on_open_file
        # 提交/拉取/推送仅 Git/SVN 项目可用，由上层提供实现（git > svn）。
        self._on_commit = on_commit
        self._on_commit_files = on_commit_files
        self._on_pull = on_pull
        self._on_push = on_push
        self._on_export_review = on_export_review
        self._on_detection_mode_changed = on_detection_mode_changed
        self._on_set_baseline = on_set_baseline
        self._on_refresh = on_refresh
        self._items: List[ChangeItem] = []
        self._source = "local"
        self._source_note = ""
        self._dark = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # 计数行 + 检测来源模式切换
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self._counts_label = QLabel("无改动", self)
        self._counts_label.setObjectName("statusMuted")
        top.addWidget(self._counts_label)

        # 改动点检测模式切换（默认：本地记录改动点）
        self._mode_combo = QComboBox(self)
        self._mode_combo.addItem("按本地记录改动点", "local")
        self._mode_combo.addItem("按 Git/版本控制", "vcs")
        self._mode_combo.setCurrentIndex(0 if initial_detection_mode == "local" else 1)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_combo_changed)
        top.addWidget(self._mode_combo)

        self._source_label = QLabel("", self)
        self._source_label.setObjectName("statusMuted")
        top.addWidget(self._source_label)

        self._refresh_btn = QPushButton("刷新", self)
        self._refresh_btn.setProperty("btnRole", "secondary")
        self._refresh_btn.setToolTip("重新检测并刷新改动列表与差异对比 (Ctrl+R)")
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        top.addWidget(self._refresh_btn)

        refresh_act = QAction("刷新改动", self)
        refresh_act.setShortcut(QKeySequence("Ctrl+R"))
        refresh_act.triggered.connect(self._on_refresh_clicked)
        self.addAction(refresh_act)

        top.addStretch(1)
        self._commit_btn = QPushButton("提交改动", self)
        self._commit_btn.setProperty("btnRole", "secondary")
        self._commit_btn.clicked.connect(self._on_commit_clicked)
        top.addWidget(self._commit_btn)
        self._push_btn = QPushButton("推送代码", self)
        self._push_btn.setProperty("btnRole", "secondary")
        self._push_btn.clicked.connect(self._on_push_clicked)
        top.addWidget(self._push_btn)
        self._pull_btn = QPushButton("拉取更新", self)
        self._pull_btn.setProperty("btnRole", "secondary")
        self._pull_btn.clicked.connect(self._on_pull_clicked)
        top.addWidget(self._pull_btn)
        self._rollback_all_btn = QPushButton("回滚全部会话改动", self)
        self._rollback_all_btn.setProperty("btnRole", "secondary")
        self._rollback_all_btn.clicked.connect(self._on_rollback_all)
        top.addWidget(self._rollback_all_btn)

        self._set_baseline_btn = QPushButton("设为新基线", self)
        self._set_baseline_btn.setProperty("btnRole", "secondary")
        self._set_baseline_btn.setToolTip("将本阶段已确认修改归档为新基线，清空当前变动点")
        self._set_baseline_btn.clicked.connect(self._on_set_baseline_clicked)
        top.addWidget(self._set_baseline_btn)

        outer.addLayout(top)

        # 列表 + diff 分栏
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        left_box = QWidget(splitter)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        self._filter_input = QLineEdit(left_box)
        self._filter_input.setPlaceholderText("🔍 筛选改动文件 (路径/名称)...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._on_filter_text_changed)
        left_layout.addWidget(self._filter_input)

        self._list = QListWidget(left_box)
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_selected)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_list_context_menu)
        left_layout.addWidget(self._list, 1)
        splitter.addWidget(left_box)

        # 右侧 Diff 区域（支持单栏统一与双栏对比切换）
        diff_host = QWidget(splitter)
        diff_layout = QVBoxLayout(diff_host)
        diff_layout.setContentsMargins(0, 0, 0, 0)
        diff_layout.setSpacing(2)

        diff_toolbar = QHBoxLayout()
        diff_toolbar.setContentsMargins(4, 0, 4, 0)
        diff_toolbar.addWidget(QLabel("差异对比：", diff_host))
        self._diff_view_mode_combo = QComboBox(diff_host)
        self._diff_view_mode_combo.addItem("单栏统一差异 (Unified)", "unified")
        self._diff_view_mode_combo.addItem("双栏分栏对比 (Side-by-Side)", "side_by_side")
        self._diff_view_mode_combo.currentIndexChanged.connect(self._on_diff_mode_changed)
        diff_toolbar.addWidget(self._diff_view_mode_combo)

        self._diff_stat_label = QLabel("", diff_host)
        self._diff_stat_label.setObjectName("statusMuted")
        diff_toolbar.addWidget(self._diff_stat_label)
        diff_toolbar.addStretch(1)
        diff_layout.addLayout(diff_toolbar)

        self._diff_stack = QStackedWidget(diff_host)

        # 页面 0：单栏统一差异
        self._diff_view = QPlainTextEdit(self._diff_stack)
        self._diff_view.setReadOnly(True)
        self._diff_view.setObjectName("logView")
        self._diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        from doc_tool.ui.content.editor_highlight import DiffHighlighter
        from doc_tool.ui.styles import is_dark_theme
        app = QApplication.instance()
        self._is_dark = is_dark_theme(app) if app is not None else False
        self._diff_highlighter = DiffHighlighter(self._diff_view.document(), dark=self._is_dark)
        self._diff_stack.addWidget(self._diff_view)

        # 页面 1：双栏分栏对比
        self._side_splitter = QSplitter(Qt.Orientation.Horizontal, self._diff_stack)

        old_box = QWidget(self._side_splitter)
        old_layout = QVBoxLayout(old_box)
        old_layout.setContentsMargins(0, 0, 0, 0)
        old_layout.setSpacing(2)
        old_label = QLabel("基线版本 (Baseline)", old_box)
        old_label.setObjectName("statusMuted")
        old_layout.addWidget(old_label)
        self._side_old_view = QPlainTextEdit(old_box)
        self._side_old_view.setReadOnly(True)
        self._side_old_view.setObjectName("logView")
        self._side_old_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        old_layout.addWidget(self._side_old_view, 1)
        self._side_splitter.addWidget(old_box)

        new_box = QWidget(self._side_splitter)
        new_layout = QVBoxLayout(new_box)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(2)
        new_label = QLabel("当前版本 (Current)", new_box)
        new_label.setObjectName("statusMuted")
        new_layout.addWidget(new_label)
        self._side_new_view = QPlainTextEdit(new_box)
        self._side_new_view.setReadOnly(True)
        self._side_new_view.setObjectName("logView")
        self._side_new_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        new_layout.addWidget(self._side_new_view, 1)
        self._side_splitter.addWidget(new_box)

        self._side_splitter.setSizes([200, 200])

        self._syncing_scroll = False
        def _sync_old(val):
            if not self._syncing_scroll:
                self._syncing_scroll = True
                self._side_new_view.verticalScrollBar().setValue(val)
                self._syncing_scroll = False

        def _sync_new(val):
            if not self._syncing_scroll:
                self._syncing_scroll = True
                self._side_old_view.verticalScrollBar().setValue(val)
                self._syncing_scroll = False

        self._side_old_view.verticalScrollBar().valueChanged.connect(_sync_old)
        self._side_new_view.verticalScrollBar().valueChanged.connect(_sync_new)

        self._syncing_h_scroll = False
        def _sync_h_old(val):
            if not self._syncing_h_scroll:
                self._syncing_h_scroll = True
                self._side_new_view.horizontalScrollBar().setValue(val)
                self._syncing_h_scroll = False

        def _sync_h_new(val):
            if not self._syncing_h_scroll:
                self._syncing_h_scroll = True
                self._side_old_view.horizontalScrollBar().setValue(val)
                self._syncing_h_scroll = False

        self._side_old_view.horizontalScrollBar().valueChanged.connect(_sync_h_old)
        self._side_new_view.horizontalScrollBar().valueChanged.connect(_sync_h_new)

        self._diff_stack.addWidget(self._side_splitter)
        diff_layout.addWidget(self._diff_stack, 1)
        splitter.addWidget(diff_host)
        splitter.setSizes([280, 420])
        outer.addWidget(splitter, 1)

        # 上下文操作行
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._restore_btn = QPushButton("恢复到基线", self)
        self._restore_btn.setProperty("btnRole", "primary")
        self._restore_btn.setToolTip("撤销当前选中文件的改动并恢复到基线/版本控制状态")
        self._restore_btn.clicked.connect(self._on_restore_clicked)
        actions.addWidget(self._restore_btn)
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("statusMuted")
        self._status_label.setWordWrap(True)
        actions.addWidget(self._status_label, 1)
        self._export_review_btn = QPushButton("导出评审稿", self)
        self._export_review_btn.setProperty("btnRole", "secondary")
        self._export_review_btn.setToolTip("提取当前改动章节并导出会议评审稿 Word")
        self._export_review_btn.clicked.connect(self._on_export_review_clicked)
        actions.addWidget(self._export_review_btn)
        self._revision_btn = QPushButton("生成修订记录", self)
        self._revision_btn.setProperty("btnRole", "secondary")
        self._revision_btn.clicked.connect(self._on_generate_revision_record)
        actions.addWidget(self._revision_btn)
        outer.addLayout(actions)
        self._update_action_state()

    def _on_export_review_clicked(self) -> None:
        if self._on_export_review is not None:
            self._on_export_review()

    def _on_mode_combo_changed(self, index: int) -> None:
        mode = self._mode_combo.itemData(index)
        if self._on_detection_mode_changed is not None:
            self._on_detection_mode_changed(mode)

    def detection_mode(self) -> str:
        """获取当前改动检测模式（'local' 或 'vcs'）。"""
        return self._mode_combo.currentData() or "local"

    def set_detection_mode(self, mode: str) -> None:
        """从外部同步改动检测模式选择（'local' 或 'vcs'）。"""
        idx = self._mode_combo.findData(mode)
        if idx >= 0 and self._mode_combo.currentIndex() != idx:
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(idx)
            self._mode_combo.blockSignals(False)

    # --- 数据 ---

    def set_source(self, source: str, note: str = "") -> None:
        """标注变更检测来源（git/svn/local），显示在计数行。

        ``note``：可选说明（如「项目未纳入 Git，已回退本地快照」），让用户
        知道为什么不是用版本控制在判断新增/修改。
        """
        self._source = source or "local"
        self._source_note = note or ""
        self._render_source_label()
        self._update_vcs_buttons()

    def _render_source_label(self) -> None:
        label = _SOURCE_LABELS.get(self._source, self._source)
        text = "检测来源：{0}".format(label)
        if getattr(self, "_source_note", ""):
            text = "{0}（{1}）".format(text, self._source_note)
        self._source_label.setText(text)

    def _on_filter_text_changed(self, _text: str) -> None:
        self._refill_list()

    def _refill_list(self) -> None:
        selected_rel = self._selected_rel()
        self._list.clear()
        query = (
            self._filter_input.text().strip().lower()
            if hasattr(self, "_filter_input")
            else ""
        )
        for item in self._items:
            st_label = _ITEM_LABELS.get(item.status, item.status)
            if query and query not in item.rel_path.lower() and query not in st_label.lower():
                continue
            label = "{0}  {1}".format(st_label, item.rel_path)
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._list.addItem(list_item)
            if item.rel_path == selected_rel:
                self._list.setCurrentItem(list_item)

    def set_items(self, items: List[ChangeItem]) -> None:
        """推送改动项并渲染列表与计数（保留当前选中不动）。"""
        self._items = list(items)
        self._refill_list()
        counts = {"added": 0, "modified": 0, "deleted": 0}
        for item in self._items:
            counts[item.status] = counts.get(item.status, 0) + 1
        if not self._items:
            self._counts_label.setText("无改动")
        else:
            self._counts_label.setText(
                "新增 {0} · 已修改 {1} · 已删除 {2}".format(
                    counts["added"], counts["modified"], counts["deleted"]
                )
            )
        self._render_source_label()
        self._update_action_state()
        self._render_diff(self._selected_item())

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    def set_dark(self, dark: bool) -> None:
        """更新暗黑模式状态。"""
        self._dark = dark
        if hasattr(self, "_diff_highlighter") and self._diff_highlighter is not None:
            self._diff_highlighter.set_dark(dark)

    # --- 选中 → diff ---

    def _selected_item(self) -> Optional[ChangeItem]:
        current = self._list.currentItem()
        if current is None:
            return None
        return current.data(Qt.ItemDataRole.UserRole)

    def _selected_rel(self) -> Optional[str]:
        item = self._selected_item()
        return item.rel_path if item is not None else None

    def _on_refresh_clicked(self) -> None:
        """处理刷新请求：重新检测改动并渲染。"""
        if self._on_refresh is not None:
            self._on_refresh()
        else:
            self._refill_list()
            item = self._selected_item()
            self._render_diff(item)

    def refresh(self) -> None:
        """公有刷新方法，便于外部或测试调用。"""
        self._on_refresh_clicked()

    def _on_diff_mode_changed(self, index: int) -> None:
        self._diff_stack.setCurrentIndex(index)

    def _on_set_baseline_clicked(self) -> None:
        if self._on_set_baseline is None:
            return
        res = QMessageBox.question(
            self,
            "确认设为新基线",
            "确认要将当前所有修改设为新基线吗？\n\n本阶段修改将被确认并归档，改动面板变动点将清空，后续编辑将以当前状态为基准继续记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        def _do_baseline():
            if self._snapshot is not None and self._writer is not None:
                self._snapshot.take(
                    self._content_root,
                    [rel for rel, _ in self._writer.manifest.entries] if not self._snapshot.entries else None,
                )
                self._snapshot.save()
                if hasattr(self._writer, "manifest"):
                    self._writer.manifest.clear()
            return None

        def _on_baseline_done(_):
            if self._on_set_baseline is not None:
                self._on_set_baseline()
            self._status_label.setText("已将当前状态设定为新基线")

        top = self.window() if hasattr(self, "window") and self.window() else self
        run_async_operation(
            top,
            _do_baseline,
            title="正在更新基线快照…",
            description="正在将当前工作区全部文档设定为基线，请稍候…",
            dark=getattr(self, "_dark", False),
            on_success=_on_baseline_done,
        )

    def _on_item_selected(self, _current, _previous) -> None:
        item = self._selected_item()
        self._render_diff(item)
        self._update_action_state()

    def _read_current(self, rel_path: str) -> str:
        """读当前文件文本；非文本（图片/表格 XML 等）不参与 diff。"""
        if not rel_path.endswith((".md", ".markdown")):
            return ""
        try:
            return (self._content_root / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def _baseline_text(self, item: ChangeItem) -> str:
        """获取改动项的基线文本。VCS 模式下优先取版本控制 HEAD 内容，兜底或 local 模式取本地快照。"""
        if item.status == "added":
            return ""
        if self.detection_mode() == "vcs":
            try:
                import subprocess
                posix_path = "./" + item.baseline_rel_path.replace("\\", "/").lstrip("./")
                res = subprocess.run(
                    ["git", "show", f"HEAD:{posix_path}"],
                    cwd=str(self._content_root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                if res.returncode == 0:
                    return res.stdout
            except Exception:
                pass
        return self._snapshot.content_of(item.baseline_rel_path) or ""

    def _diff_text(self, item: ChangeItem) -> str:
        from doc_tool.application.content.changes import render_unified_diff

        if not item.rel_path.endswith((".md", ".markdown")):
            # 资源文件（图片/表格）没有可读的文本差异，只说明状态。
            return "（{0}：非文本文件，不显示差异）".format(
                _ITEM_LABELS.get(item.status, item.status)
            )
        old = self._baseline_text(item)
        new = self._read_current(item.rel_path)
        return render_unified_diff(old, new)

    def _render_diff(self, item: Optional[ChangeItem]) -> None:
        if not item:
            self._diff_view.setPlainText("")
            self._side_old_view.setPlainText("")
            self._side_new_view.setPlainText("")
            self._side_old_view.setExtraSelections([])
            self._side_new_view.setExtraSelections([])
            if hasattr(self, "_diff_stat_label"):
                self._diff_stat_label.setText("")
            return
        if not item.rel_path.endswith((".md", ".markdown")):
            msg = "（{0}：非文本文件，不显示差异）".format(
                _ITEM_LABELS.get(item.status, item.status)
            )
            self._diff_view.setPlainText(msg)
            self._side_old_view.setPlainText(msg)
            self._side_new_view.setPlainText(msg)
            self._side_old_view.setExtraSelections([])
            self._side_new_view.setExtraSelections([])
            if hasattr(self, "_diff_stat_label"):
                self._diff_stat_label.setText("")
            return

        old = self._baseline_text(item)
        new = self._read_current(item.rel_path)

        from doc_tool.application.content.changes import (
            render_unified_diff,
            render_side_by_side_diff,
        )

        self._diff_view.setPlainText(render_unified_diff(old, new))

        side_lines = render_side_by_side_diff(old, new)
        old_text_lines = []
        new_text_lines = []
        add_cnt = 0
        del_cnt = 0
        for line in side_lines:
            old_prefix = "{0:4d} | ".format(line.old_line_no) if line.old_line_no else "     | "
            new_prefix = "{0:4d} | ".format(line.new_line_no) if line.new_line_no else "     | "
            old_text_lines.append(old_prefix + line.old_text)
            new_text_lines.append(new_prefix + line.new_text)
            if line.change_type in ("insert", "replace"):
                add_cnt += 1
            if line.change_type in ("delete", "replace"):
                del_cnt += 1

        self._side_old_view.setPlainText("\n".join(old_text_lines))
        self._side_new_view.setPlainText("\n".join(new_text_lines))
        self._apply_side_by_side_highlights(side_lines)

        if hasattr(self, "_diff_stat_label"):
            if add_cnt or del_cnt:
                self._diff_stat_label.setText(f"（+{add_cnt}  -{del_cnt}）")
            else:
                self._diff_stat_label.setText("")

    def _apply_side_by_side_highlights(self, side_lines) -> None:
        from PySide6.QtGui import QColor, QTextCursor
        from PySide6.QtWidgets import QTextEdit

        old_selections = []
        new_selections = []
        doc_old = self._side_old_view.document()
        doc_new = self._side_new_view.document()
        is_dark = getattr(self, "_is_dark", False)

        for idx, line in enumerate(side_lines):
            prefix_len_old = len("{0:4d} | ".format(line.old_line_no)) if line.old_line_no else 7
            prefix_len_new = len("{0:4d} | ".format(line.new_line_no)) if line.new_line_no else 7
            if line.change_type in ("delete", "replace"):
                block = doc_old.findBlockByNumber(idx)
                if block.isValid():
                    cur = QTextCursor(block)
                    cur.select(QTextCursor.SelectionType.LineUnderCursor)
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cur
                    sel.format.setBackground(QColor("#450a0a" if is_dark else "#fee2e2"))
                    old_selections.append(sel)
                    max_pos = block.position() + max(0, block.length() - 1)
                    for span in line.old_spans:
                        s_pos = min(max_pos, block.position() + prefix_len_old + span.start)
                        e_pos = min(max_pos, block.position() + prefix_len_old + span.end)
                        if e_pos <= s_pos:
                            continue
                        cur_w = QTextCursor(doc_old)
                        cur_w.setPosition(s_pos)
                        cur_w.setPosition(e_pos, QTextCursor.MoveMode.KeepAnchor)
                        sel_w = QTextEdit.ExtraSelection()
                        sel_w.cursor = cur_w
                        sel_w.format.setBackground(QColor("#991b1b" if is_dark else "#fca5a5"))
                        sel_w.format.setForeground(QColor("#fef2f2" if is_dark else "#7f1d1d"))
                        old_selections.append(sel_w)

            if line.change_type in ("insert", "replace"):
                block = doc_new.findBlockByNumber(idx)
                if block.isValid():
                    cur = QTextCursor(block)
                    cur.select(QTextCursor.SelectionType.LineUnderCursor)
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cur
                    sel.format.setBackground(QColor("#14532d" if is_dark else "#dcfce7"))
                    new_selections.append(sel)
                    max_pos = block.position() + max(0, block.length() - 1)
                    for span in line.new_spans:
                        s_pos = min(max_pos, block.position() + prefix_len_new + span.start)
                        e_pos = min(max_pos, block.position() + prefix_len_new + span.end)
                        if e_pos <= s_pos:
                            continue
                        cur_w = QTextCursor(doc_new)
                        cur_w.setPosition(s_pos)
                        cur_w.setPosition(e_pos, QTextCursor.MoveMode.KeepAnchor)
                        sel_w = QTextEdit.ExtraSelection()
                        sel_w.cursor = cur_w
                        sel_w.format.setBackground(QColor("#15803d" if is_dark else "#86efac"))
                        sel_w.format.setForeground(QColor("#f0fdf4" if is_dark else "#14532d"))
                        new_selections.append(sel_w)

        self._side_old_view.setExtraSelections(old_selections)
        self._side_new_view.setExtraSelections(new_selections)

    # --- 操作 ---

    def _update_action_state(self) -> None:
        item = self._selected_item()
        can_restore_rename = bool(item and item.is_rename and self._rollback_single is not None)
        restorable = bool(
            self._writable
            and item is not None
            and (item.restorable or can_restore_rename)
        )
        self._restore_btn.setEnabled(restorable)
        self._rollback_all_btn.setEnabled(self._writable and bool(self._items))
        can_set_baseline = (
            self._writable
            and bool(self._items)
            and self.detection_mode() == "local"
            and self._on_set_baseline is not None
        )
        self._set_baseline_btn.setEnabled(can_set_baseline)
        self._revision_btn.setEnabled(self._has_revision_candidates())
        self._update_vcs_buttons()
        if item is None:
            self._restore_btn.setText("恢复到基线")
            self._status_label.setText("")
        elif not item.restorable and not can_restore_rename:
            self._restore_btn.setText("恢复到基线")
            self._status_label.setText("该条目仅展示，不提供单文件恢复")
        elif item.is_rename:
            if can_restore_rename:
                self._restore_btn.setText("撤销重命名")
                self._status_label.setText("")
            else:
                self._restore_btn.setText("恢复到基线")
                self._status_label.setText("重命名文件请使用「回滚全部会话改动」")
        else:
            self._restore_btn.setText(
                {
                    "added": "撤销新增",
                    "deleted": "恢复删除",
                    "modified": "恢复到基线",
                }.get(item.status, "恢复到基线")
            )
            self._status_label.setText("")

    def _update_vcs_buttons(self) -> None:
        """提交/拉取/推送仅 Git/SVN 项目可用；本地项目禁用并标注命令差异。"""
        vcs_managed = self._source in ("git", "svn")
        self._commit_btn.setEnabled(
            self._writable and vcs_managed and bool(self._items)
        )
        self._pull_btn.setEnabled(self._writable and vcs_managed)
        can_push = self._writable and (self._source == "git") and (self._on_push is not None)
        self._push_btn.setEnabled(can_push)

        if self._source == "git":
            self._commit_btn.setToolTip(
                "git add -A + git commit -m（限定当前项目路径，支持复选文件）"
            )
            self._push_btn.setToolTip("git push：推送当前分支改动至远端仓库")
            self._pull_btn.setToolTip("git pull：拉取远端最新变更")
        elif self._source == "svn":
            self._commit_btn.setToolTip(
                "svn add + svn rm + svn commit -m（限定当前项目路径）"
            )
            self._push_btn.setToolTip("仅在 Git 项目中可用")
            self._pull_btn.setToolTip("svn update：更新到远端最新版本")
        else:
            self._commit_btn.setToolTip("仅在版本控制项目（Git/SVN）中可用")
            self._push_btn.setToolTip("仅在 Git 项目中可用")
            self._pull_btn.setToolTip("仅在版本控制项目（Git/SVN）中可用")

    def _on_item_double_clicked(self, list_item: QListWidgetItem) -> None:
        item: Optional[ChangeItem] = list_item.data(Qt.ItemDataRole.UserRole)
        if item and item.status != "deleted" and self._on_open_file is not None:
            self._on_open_file(item.rel_path)

    def _show_list_context_menu(self, pos) -> None:
        item_widget = self._list.itemAt(pos)
        item: Optional[ChangeItem] = (
            item_widget.data(Qt.ItemDataRole.UserRole)
            if item_widget is not None
            else None
        )

        menu = QMenu(self)

        if item is not None:
            # 撤销改动
            label_map = {
                "added": "撤销新增（删除文件）…",
                "deleted": "恢复已删除文件…",
                "modified": "撤销此修改（恢复基线）…",
            }
            revert_label = "撤销重命名…" if item.is_rename else label_map.get(item.status, "撤销此文件改动…")
            revert_act = QAction(revert_label, menu)
            can_restore = self._writable and (
                item.restorable or (item.is_rename and self._rollback_single is not None)
            )
            revert_act.setEnabled(can_restore)
            revert_act.triggered.connect(lambda: self._confirm_and_restore(item))
            menu.addAction(revert_act)

            menu.addSeparator()

            # 打开文件
            if item.status != "deleted":
                open_act = QAction("在编辑器中打开", menu)
                open_act.triggered.connect(
                    lambda: self._on_open_file and self._on_open_file(item.rel_path)
                )
                menu.addAction(open_act)

            # 复制相对路径
            copy_act = QAction("复制相对路径", menu)
            copy_act.triggered.connect(
                lambda: QApplication.clipboard().setText(item.rel_path)
            )
            menu.addAction(copy_act)
            menu.addSeparator()

        refresh_act = QAction("刷新改动列表", menu)
        refresh_act.triggered.connect(self._on_refresh_clicked)
        menu.addAction(refresh_act)

        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.exec(QCursor.pos())

    def _confirm_and_restore(self, item: ChangeItem) -> None:
        ans = QMessageBox.question(
            self,
            "撤销改动确认",
            f"确定要撤销「{item.rel_path}」的改动吗？\n\n此操作将放弃所有未提交修改并恢复到基线内容，此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._async_restore_item(item)

    def _async_restore_item(self, item: ChangeItem) -> None:
        """异步撤销单个文件改动，带有全屏加载遮罩与动效。"""
        if not self._writable:
            return
        can_restore_rename = bool(item.is_rename and self._rollback_single is not None)
        if not item.restorable and not can_restore_rename:
            return

        def _do_restore():
            if self._rollback_single is not None:
                return self._rollback_single(item)
            if item.is_rename:
                return "重命名改动无法直接恢复"
            baseline = None
            if item.status == "modified":
                baseline = self._snapshot.content_of(item.baseline_rel_path)
                if baseline is None:
                    return "基线内容不可用，无法恢复到基线"
            result = self._writer.restore_file(
                item.rel_path,
                status=item.status,
                baseline_text=baseline,
                trash_path=item.trash_path,
            )
            if not result.written:
                return result.error or "未知原因"
            return None

        def _on_restore_done(err):
            if err:
                self._status_label.setText(f"撤销失败：{err}")
                QMessageBox.warning(self, "撤销失败", f"撤销文件改动失败：\n\n{err}")
                return
            if self._on_restored is not None:
                self._on_restored()
            self._status_label.setText(f"已撤销改动：{item.rel_path}")
            self._update_action_state()

        top = self.window() if hasattr(self, "window") and self.window() else self
        run_async_operation(
            top,
            _do_restore,
            title="正在撤销文件改动…",
            description=f"正在将「{item.rel_path}」恢复到基线状态并更新工作区，请稍候…",
            dark=getattr(self, "_dark", False),
            on_success=_on_restore_done,
        )

    def _on_restore_clicked(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        if not self.isVisible():
            # 兼容无头单元测试（非离屏交互）
            self._do_restore_item(item)
            return
        self._confirm_and_restore(item)

    def _do_restore_item(self, item: ChangeItem) -> None:
        if not self._writable:
            return
        can_restore_rename = bool(item.is_rename and self._rollback_single is not None)
        if not item.restorable and not can_restore_rename:
            return

        if self._rollback_single is not None:
            err = self._rollback_single(item)
            if err:
                self._status_label.setText(f"撤销失败：{err}")
                return
            if self._on_restored is not None:
                self._on_restored()
            self._status_label.setText(f"已撤销改动：{item.rel_path}")
            self._update_action_state()
            return

        # 回退到原有 writer.restore_file 逻辑（用于未传 rollback_single 的场景/单测）
        if item.is_rename:
            return
        baseline = None
        if item.status == "modified":
            baseline = self._snapshot.content_of(item.baseline_rel_path)
            if baseline is None:
                self._status_label.setText("基线内容不可用，无法恢复到基线")
                return
        result = self._writer.restore_file(
            item.rel_path,
            status=item.status,
            baseline_text=baseline,
            trash_path=item.trash_path,
        )
        if not result.written:
            self._status_label.setText(
                "恢复失败：{0}".format(result.error or "未知原因")
            )
            return
        if self._on_restored is not None:
            self._on_restored()
        self._update_action_state()

    def _on_rollback_all(self) -> None:
        if not self._writable or not self._items:
            return
        if self._rollback_all is not None:
            scope = "将用版本控制恢复当前项目的全部未提交改动（{0} 项）。"
        else:
            scope = "将回滚本次会话的全部改动（{0} 项：编辑 / 重命名 / 新增 / 删除）。"
        answer = QMessageBox.question(
            self,
            "回滚全部改动",
            scope.format(len(self._items)) + "\n\n确认？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def _do_rollback() -> List[str]:
            if self._rollback_all is not None:
                return self._rollback_all()
            else:
                return self._writer.rollback()

        def _on_rollback_done(failures: List[str]) -> None:
            if failures:
                self._status_label.setText(
                    "回滚失败：{0}".format(", ".join(failures))
                )
                QMessageBox.warning(self, "回滚失败", "回滚全部改动失败：\n\n" + "\n".join(failures))
                return
            if self._on_restored is not None:
                self._on_restored()
            self._update_action_state()
            self._status_label.setText("已成功回滚全部未提交改动")

        top = self.window() if hasattr(self, "window") and self.window() else self
        run_async_operation(
            top,
            _do_rollback,
            title="正在回滚全部改动…",
            description=f"正在恢复工作区中的 {len(self._items)} 项改动到基准版本，请稍候…",
            dark=getattr(self, "_dark", False),
            on_success=_on_rollback_done,
        )

    def _on_commit_clicked(self) -> None:
        """「提交改动」：弹出专业 Git 提交对话框，收集勾选文件与提交信息后提交。"""
        if not self._writable or not self._items or self._source not in ("git", "svn"):
            return
        if self._on_commit is None and self._on_commit_files is None:
            self._status_label.setText("提交功能不可用（未配置版本控制提交）")
            return

        from doc_tool.ui.content.git_commit_dialog import GitCommitDialog

        dark = getattr(self, "_dark", False)
        can_push = bool(self._on_push is not None and self._source == "git")
        dlg = GitCommitDialog(self._items, dark=dark, can_push=can_push, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        message = dlg.commit_message.strip()
        selected_paths = dlg.selected_paths
        if not message or not selected_paths:
            return

        def _do_commit() -> List[str]:
            if self._on_commit_files is not None:
                return self._on_commit_files(selected_paths, message)
            elif self._on_commit is not None:
                return self._on_commit(message)
            return []

        def _on_commit_done(failures: List[str]) -> None:
            if failures:
                self._status_label.setText("提交失败：{0}".format("；".join(failures)))
                QMessageBox.warning(self, "提交失败", "提交改动失败：\n\n" + "\n".join(failures))
                return

            if self._on_restored is not None:
                self._on_restored()
            self._update_action_state()
            self._status_label.setText(f"已提交 {len(selected_paths)} 个文件改动到版本控制")

            # 若用户在弹窗中点击了「提交并推送」
            if dlg.should_push:
                self._do_push()

        top = self.window() if hasattr(self, "window") and self.window() else self
        run_async_operation(
            top,
            _do_commit,
            title="正在提交改动到版本控制…",
            description=f"正在提交勾选的 {len(selected_paths)} 个文件，请稍候…",
            dark=dark,
            on_success=_on_commit_done,
        )

    def _on_push_clicked(self) -> None:
        """「推送代码」：确认后执行 git push，将本地提交推送到远端。"""
        if not self._writable or self._source != "git":
            return
        if self._on_push is None:
            self._status_label.setText("推送功能不可用（未配置推送实现）")
            return
        ans = QMessageBox.question(
            self,
            "推送代码",
            "确定要将当前分支的所有本地提交推送到远端仓库吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._do_push()

    def trigger_commit(self) -> None:
        """程序化触发提交改动对话框。"""
        self._on_commit_clicked()

    def _do_push(self) -> None:
        if self._on_push is None:
            return

        def _on_push_done(result: PushResult) -> None:
            if result.ok:
                if self._on_restored is not None:
                    self._on_restored()
                self._update_action_state()
                self._status_label.setText(result.summary or "推送成功")
                QMessageBox.information(self, "推送成功", result.summary or "已成功推送到远端仓库！")
            else:
                self._status_label.setText("推送失败：{0}".format(result.error or "未知原因"))
                QMessageBox.warning(self, "推送失败", f"推送代码到远端失败：\n\n{result.error}")

        top = self.window() if hasattr(self, "window") and self.window() else self
        run_async_operation(
            top,
            self._on_push,
            title="正在推送代码到远端…",
            description="正在与远端仓库通信并推送本地提交，请稍候…",
            dark=getattr(self, "_dark", False),
            on_success=_on_push_done,
        )

    def _on_pull_clicked(self) -> None:
        """「拉取更新」：确认后执行 git pull / svn update，并反馈结果。

        成功后状态行展示摘要（更新了 N 个文件 / 已是最新版本）；存在冲突时
        弹窗列出冲突文件并提示手工解决；失败时展示命令错误文本。
        """
        if not self._writable or self._source not in ("git", "svn"):
            return
        if self._on_pull is None:
            self._status_label.setText("拉取功能不可用（未配置版本控制拉取）")
            return
        verb = "git pull" if self._source == "git" else "svn update"
        answer = QMessageBox.question(
            self,
            "拉取更新",
            "将执行 {0}，把远端最新变更合并到当前工作副本。\n\n"
            "请先保存所有打开的编辑内容。确认？".format(verb),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        def _on_pull_done(result: PullResult) -> None:
            message = ""
            if result.conflicts:
                QMessageBox.warning(
                    self,
                    "拉取存在冲突",
                    "以下 {0} 个文件有合并冲突，需要手工解决：\n\n{1}\n\n"
                    "请编辑冲突文件（或使用「回滚全部会话改动」放弃改动）后重新提交。".format(
                        len(result.conflicts), "\n".join(result.conflicts)
                    ),
                )
                message = "拉取：{0}，{1} 个文件冲突，需手工解决".format(
                    result.summary or "完成", len(result.conflicts)
                )
            elif not result.ok:
                self._status_label.setText(
                    "拉取失败：{0}".format(result.error or "未知原因")
                )
                QMessageBox.warning(self, "拉取失败", f"拉取更新失败：\n\n{result.error}")
                return
            else:
                message = "拉取完成：{0}".format(result.summary or "已更新")
            if self._on_restored is not None:
                self._on_restored()
            self._update_action_state()
            if message:
                self._status_label.setText(message)

        top = self.window() if hasattr(self, "window") and self.window() else self
        run_async_operation(
            top,
            self._on_pull,
            title="正在拉取远端更新…",
            description=f"正在执行 {verb} 获取最新改动并执行合并，请稍候…",
            dark=getattr(self, "_dark", False),
            on_success=_on_pull_done,
        )

    def _has_revision_candidates(self) -> bool:
        """是否存在可生成修订记录的 Markdown 改动条目（资源/project.yml 不计）。"""
        return any(
            item.rel_path.endswith((".md", ".markdown")) for item in self._items
        )

    def _on_generate_revision_record(self) -> None:
        """生成修订记录定位清单（章节->小节），弹窗展示可编辑并复制。"""
        if not self._items:
            return
        from doc_tool.application.content.revision_record import build_revision_record
        from doc_tool.ui.content.revision_record_dialog import RevisionRecordDialog

        RevisionRecordDialog(build_revision_record(self._items), parent=self).exec()
