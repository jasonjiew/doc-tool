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
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.changes import ChangeItem

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
        self._items: List[ChangeItem] = []
        self._source = "local"
        self._source_note = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # 计数行 + 检测来源
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self._counts_label = QLabel("无改动", self)
        self._counts_label.setObjectName("statusMuted")
        top.addWidget(self._counts_label)
        self._source_label = QLabel("", self)
        self._source_label.setObjectName("statusMuted")
        top.addWidget(self._source_label)
        top.addStretch(1)
        self._rollback_all_btn = QPushButton("回滚全部会话改动", self)
        self._rollback_all_btn.setProperty("btnRole", "secondary")
        self._rollback_all_btn.clicked.connect(self._on_rollback_all)
        top.addWidget(self._rollback_all_btn)
        outer.addLayout(top)

        # 列表 + diff 分栏
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._list = QListWidget(splitter)
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_selected)
        splitter.addWidget(self._list)
        self._diff_view = QPlainTextEdit(splitter)
        self._diff_view.setReadOnly(True)
        self._diff_view.setObjectName("logView")
        splitter.addWidget(self._diff_view)
        splitter.setSizes([280, 420])
        outer.addWidget(splitter, 1)

        # 上下文操作行
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._restore_btn = QPushButton("恢复到基线", self)
        self._restore_btn.setProperty("btnRole", "primary")
        self._restore_btn.clicked.connect(self._on_restore_clicked)
        actions.addWidget(self._restore_btn)
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("statusMuted")
        self._status_label.setWordWrap(True)
        actions.addWidget(self._status_label, 1)
        self._revision_btn = QPushButton("生成修订记录", self)
        self._revision_btn.setProperty("btnRole", "secondary")
        self._revision_btn.clicked.connect(self._on_generate_revision_record)
        actions.addWidget(self._revision_btn)
        outer.addLayout(actions)
        self._update_action_state()

    # --- 数据 ---

    def set_source(self, source: str, note: str = "") -> None:
        """标注变更检测来源（git/svn/local），显示在计数行。

        ``note``：可选说明（如「项目未纳入 Git，已回退本地快照」），让用户
        知道为什么不是用版本控制在判断新增/修改。
        """
        self._source = source or "local"
        self._source_note = note or ""
        self._render_source_label()

    def _render_source_label(self) -> None:
        label = _SOURCE_LABELS.get(self._source, self._source)
        text = "检测来源：{0}".format(label)
        if getattr(self, "_source_note", ""):
            text = "{0}（{1}）".format(text, self._source_note)
        self._source_label.setText(text)

    def set_items(self, items: List[ChangeItem]) -> None:
        """推送改动项并渲染列表与计数（保留当前选中不动）。"""
        self._items = list(items)
        selected_rel = self._selected_rel()
        self._list.clear()
        for item in self._items:
            label = "{0}  {1}".format(
                _ITEM_LABELS.get(item.status, item.status), item.rel_path
            )
            list_item = QListWidgetItem(label, self._list)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._list.addItem(list_item)
            if item.rel_path == selected_rel:
                self._list.setCurrentItem(list_item)
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

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    # --- 选中 → diff ---

    def _selected_item(self) -> Optional[ChangeItem]:
        current = self._list.currentItem()
        if current is None:
            return None
        return current.data(Qt.ItemDataRole.UserRole)

    def _selected_rel(self) -> Optional[str]:
        item = self._selected_item()
        return item.rel_path if item is not None else None

    def _on_item_selected(self, _current, _previous) -> None:
        item = self._selected_item()
        self._diff_view.setPlainText(self._diff_text(item) if item else "")
        self._update_action_state()

    def _read_current(self, rel_path: str) -> str:
        """读当前文件文本；非文本（图片/表格 XML 等）不参与 diff。"""
        if not rel_path.endswith((".md", ".markdown")):
            return ""
        try:
            return (self._content_root / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def _diff_text(self, item: ChangeItem) -> str:
        from doc_tool.application.content.changes import render_unified_diff

        if not item.rel_path.endswith((".md", ".markdown")):
            # 资源文件（图片/表格）没有可读的文本差异，只说明状态。
            return "（{0}：非文本文件，不显示差异）".format(
                _ITEM_LABELS.get(item.status, item.status)
            )
        if item.status == "added":
            old = ""
        else:
            old = self._snapshot.content_of(item.baseline_rel_path) or ""
        new = self._read_current(item.rel_path)
        return render_unified_diff(old, new)

    # --- 操作 ---

    def _update_action_state(self) -> None:
        item = self._selected_item()
        restorable = bool(
            self._writable
            and item is not None
            and not item.is_rename
            and item.restorable
        )
        self._restore_btn.setEnabled(restorable)
        self._rollback_all_btn.setEnabled(self._writable and bool(self._items))
        self._revision_btn.setEnabled(self._has_revision_candidates())
        if item is None:
            self._restore_btn.setText("恢复到基线")
            self._status_label.setText("")
        elif not item.restorable:
            self._restore_btn.setText("恢复到基线")
            self._status_label.setText("该条目仅展示，不提供单文件恢复")
        elif item.is_rename:
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

    def _on_restore_clicked(self) -> None:
        item = self._selected_item()
        if (
            item is None
            or item.is_rename
            or not item.restorable
            or not self._writable
        ):
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
        if self._rollback_all is not None:
            failures = self._rollback_all()
        else:
            failures = self._writer.rollback()
        if failures:
            self._status_label.setText(
                "回滚失败：{0}".format(", ".join(failures))
            )
            return
        if self._on_restored is not None:
            self._on_restored()
        self._update_action_state()

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
