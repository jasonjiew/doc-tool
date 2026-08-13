# -*- coding: utf-8 -*-
"""引用分析对话框：当前文件被引用情况 + 全项目悬空引用。

读操作；结果行可点击，经 ``on_open(rel_path, line_no)`` 在内容面板定位。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.domain.content_index import (
    REF_ANCHOR,
    REF_IMAGE,
    REF_LINK,
    REF_SECTION,
)

_KIND_LABELS = {
    REF_LINK: "链接",
    REF_SECTION: "章节号",
    REF_ANCHOR: "锚点",
    REF_IMAGE: "图片",
}


def _kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def _make_table(parent) -> QTreeWidget:
    tree = QTreeWidget(parent)
    tree.setColumnCount(4)
    tree.setHeaderLabels(["文件", "行", "类型", "引用/目标"])
    tree.setColumnWidth(0, 280)
    tree.setColumnWidth(1, 48)
    tree.setColumnWidth(2, 70)
    tree.setColumnWidth(3, 320)
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    return tree


class ReferencesDialog(QDialog):
    """引用分析对话框。"""

    def __init__(
        self,
        index,
        *,
        current_file: Optional[str] = None,
        on_open: Optional[Callable[[str, int], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._on_open = on_open
        self.setWindowTitle("引用分析")
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 反向引用
        if current_file:
            title = QLabel("引用当前文件：{0}".format(current_file), self)
            title.setObjectName("sectionTitle")
            layout.addWidget(title)
            reverse_tree = _make_table(self)
            layout.addWidget(reverse_tree, 1)
            count = 0
            for source, refs in index.references.items():
                for ref in refs:
                    if ref.target_rel_path == current_file:
                        reverse_tree.addTopLevelItem(
                            QTreeWidgetItem(
                                [
                                    source,
                                    str(ref.source_line),
                                    _kind_label(ref.kind),
                                    "{0} → {1}".format(ref.target, ref.source_text[:40]),
                                ]
                            )
                        )
                        count += 1
            if count == 0:
                empty = QLabel("（未被其他文件引用）", self)
                empty.setObjectName("statusMuted")
                layout.addWidget(empty)
            reverse_tree.itemActivated.connect(
                lambda item: self._open_from(reverse_tree, item)
            )
            reverse_tree.itemClicked.connect(
                lambda item: self._open_from(reverse_tree, item)
            )
        else:
            title = QLabel("（未打开文件，仅显示全项目悬空引用）", self)
            title.setObjectName("statusMuted")
            layout.addWidget(title)

        # 悬空引用
        dangling_title = QLabel("全项目悬空引用", self)
        dangling_title.setObjectName("sectionTitle")
        layout.addWidget(dangling_title)
        dangling_tree = _make_table(self)
        layout.addWidget(dangling_tree, 2)
        dangling = [
            (ref, source)
            for source, refs in index.references.items()
            for ref in refs
            if ref.dangling
        ]
        if not dangling:
            empty = QLabel("（未发现悬空引用）", self)
            empty.setObjectName("statusMuted")
            layout.addWidget(empty)
        for ref, source in dangling:
            kind = "悬空[{0}]".format(
                "确定" if ref.dangling_kind == "confirmed" else "疑似"
            )
            dangling_tree.addTopLevelItem(
                QTreeWidgetItem([source, str(ref.source_line), kind, ref.target])
            )
        dangling_tree.itemActivated.connect(
            lambda item: self._open_from(dangling_tree, item)
        )
        dangling_tree.itemClicked.connect(
            lambda item: self._open_from(dangling_tree, item)
        )

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("关闭", self)
        close_btn.setProperty("btnRole", "secondary")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _open_from(self, tree: QTreeWidget, item: QTreeWidgetItem) -> None:
        if item is None or self._on_open is None:
            return
        try:
            line_no = int(item.text(1))
        except ValueError:
            line_no = 1
        self.accept()
        self._on_open(item.text(0), line_no)


def show_references_dialog(
    parent,
    index,
    *,
    current_file: Optional[str] = None,
    on_open: Optional[Callable[[str, int], None]] = None,
) -> None:
    """弹出引用分析对话框。"""
    dialog = ReferencesDialog(
        index, current_file=current_file, on_open=on_open, parent=parent
    )
    dialog.exec()
