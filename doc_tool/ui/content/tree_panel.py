# -*- coding: utf-8 -*-
"""章节树导航面板（左侧 Dock）。

``QTreeView`` + 自定义 ``QAbstractItemModel`` 渲染 ``build_tree`` 推导的
``第X章 → X.Y → X.Y.Z`` 层级。文件节点点击通过 ``on_open`` 回调打开内容
面板；``select_file`` 供搜索/检查结果定位时同步选中并展开父级。

工具栏提供"展开全部 / 折叠全部 / 刷新"；右键菜单提供"打开 / 复制相对路径"。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.tree import TreeItem


class ChapterTreeModel(QAbstractItemModel):
    """基于 ``TreeItem`` 扁平列表的只读树模型。

    根节点用空字符串 id 表示；每个有效节点把 ``node_id`` 作为
    ``internalPointer`` 保存，便于快速定位。
    """

    _ROOT = ""

    def __init__(self, items: List[TreeItem], parent=None) -> None:
        super().__init__(parent)
        self.set_items(items)

    def set_items(self, items: List[TreeItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._by_id: Dict[str, TreeItem] = {
            item.node_id: item for item in self._items
        }
        self._children: Dict[str, List[str]] = defaultdict(list)
        for item in self._items:
            self._children[item.parent_id or self._ROOT].append(item.node_id)
        self._root = self._ROOT
        self.endResetModel()

    # --- 基本导航 ---

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_id = self._node_id(parent)
        children = self._children.get(parent_id, [])
        if row >= len(children):
            return QModelIndex()
        node_id = children[row]
        return self.createIndex(row, column, node_id)

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node_id = index.internalPointer()
        item = self._by_id.get(node_id)
        if item is None or item.parent_id is None:
            return QModelIndex()
        parent_id = item.parent_id
        parent_item = self._by_id.get(parent_id)
        if parent_item is None:
            return QModelIndex()
        # 父节点为顶层类型节点（其 parent_id 为 None）时，其所在行位于根下。
        grand_id = parent_item.parent_id or self._ROOT
        siblings = self._children.get(grand_id, [])
        try:
            row = siblings.index(parent_id)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, parent_id)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        parent_id = self._node_id(parent)
        return len(self._children.get(parent_id, []))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        node_id = index.internalPointer()
        item = self._by_id.get(node_id)
        if item is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return item.text
        if role == Qt.ItemDataRole.UserRole:
            return item.rel_path if item.is_file else None
        if role == Qt.ItemDataRole.DecorationRole:
            return None
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # --- 辅助 ---

    def _node_id(self, index: QModelIndex) -> str:
        if not index.isValid():
            return self._ROOT
        return str(index.internalPointer())

    def item_for(self, node_id: str) -> Optional[TreeItem]:
        return self._by_id.get(node_id)

    def all_items(self) -> List[TreeItem]:
        return list(self._items)


class ChapterTree(QWidget):
    """章节树面板。

    ``on_open(rel_path)``：文件节点被点击/打开时回调。
    ``on_refresh()``：点击"刷新"时回调（重建索引并重绘树）。
    ``writable``：可写时显示"重命名/重编号"入口；只读时隐藏写操作。
    """

    def __init__(
        self,
        *,
        on_open: Optional[Callable[[str], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._writable = writable
        self._current: Optional[str] = None
        self._items: List[TreeItem] = []
        self._model = ChapterTreeModel([], self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        expand_btn = QPushButton("展开全部", self)
        expand_btn.setProperty("btnRole", "compact")
        expand_btn.clicked.connect(self.expand_all)
        toolbar.addWidget(expand_btn)
        collapse_btn = QPushButton("折叠全部", self)
        collapse_btn.setProperty("btnRole", "compact")
        collapse_btn.clicked.connect(self.collapse_all)
        toolbar.addWidget(collapse_btn)
        toolbar.addStretch(1)
        self._refresh_btn = QPushButton("刷新", self)
        self._refresh_btn.setProperty("btnRole", "compact")
        self._refresh_btn.clicked.connect(self._on_refresh_click)
        toolbar.addWidget(self._refresh_btn)
        layout.addLayout(toolbar)

        self._tree = QTreeView(self)
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree, 1)

        self._tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self._tree.doubleClicked.connect(self._on_double_clicked)

    # --- 数据 ---

    def set_items(self, items: List[TreeItem]) -> None:
        """重建树内容，并展开全部目录节点，打开即可看到完整章节层级。"""
        self._items = list(items)
        self._model.set_items(items)
        for item in items:
            if not item.is_file:
                index = self._index_for(item.node_id)
                if index.isValid():
                    self._tree.expand(index)

    def set_writable(self, writable: bool) -> None:
        self._writable = writable

    def is_writable(self) -> bool:
        return self._writable

    def expand_all(self) -> None:
        """展开全部目录节点。"""
        for item in self._items:
            if not item.is_file:
                index = self._index_for(item.node_id)
                if index.isValid():
                    self._tree.expand(index)

    def collapse_all(self) -> None:
        """折叠全部目录节点（保留顶层类型节点展开）。"""
        for item in self._items:
            if not item.is_file and item.parent_id is not None:
                index = self._index_for(item.node_id)
                if index.isValid():
                    self._tree.collapse(index)

    def select_file(self, rel_path: str) -> bool:
        """定位到某文件节点：展开祖先并选中；文件不在树中返回 False。"""
        item = self._model.item_for(rel_path)
        if item is None or not item.is_file:
            return False
        index = self._index_for(rel_path)
        if not index.isValid():
            return False
        # 展开祖先
        for ancestor_id in self._ancestor_ids(rel_path):
            ancestor_index = self._index_for(ancestor_id)
            if ancestor_index.isValid():
                self._tree.expand(ancestor_index)
        self._tree.setCurrentIndex(index)
        self._tree.scrollTo(index)
        return True

    def set_current(self, rel_path: Optional[str]) -> None:
        """记录当前打开的文件，供选中回调去重。"""
        self._current = rel_path

    # --- 定位联动 ---

    def _index_for(self, node_id: str) -> QModelIndex:
        """按 node_id 查找模型索引（递归）。"""
        stack = [QModelIndex()]
        while stack:
            parent = stack.pop()
            for row in range(self._model.rowCount(parent)):
                index = self._model.index(row, 0, parent)
                if index.internalPointer() == node_id:
                    return index
                if self._model.hasChildren(index):
                    stack.append(index)
        return QModelIndex()

    def _ancestor_ids(self, node_id: str) -> List[str]:
        chain: List[str] = []
        item = self._model.item_for(node_id)
        while item is not None and item.parent_id is not None:
            chain.append(item.parent_id)
            item = self._model.item_for(item.parent_id)
        return list(reversed(chain))

    # --- 事件 ---

    def _selected_file(self) -> Optional[str]:
        index = self._tree.currentIndex()
        if not index.isValid():
            return None
        rel_path = self._model.data(index, Qt.ItemDataRole.UserRole)
        return rel_path if rel_path else None

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid() or self._on_open is None:
            return
        rel_path = self._model.data(current, Qt.ItemDataRole.UserRole)
        if rel_path and rel_path != self._current:
            self._on_open(rel_path)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or self._on_open is None:
            return
        rel_path = self._model.data(index, Qt.ItemDataRole.UserRole)
        if rel_path and rel_path != self._current:
            self._on_open(rel_path)

    def _on_refresh_click(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()

    # --- 右键菜单 ---

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        rel_path = self._model.data(index, Qt.ItemDataRole.UserRole)
        if not rel_path:
            return
        menu = QMenu(self)
        open_action = QAction("打开", menu)
        open_action.triggered.connect(
            lambda: self._on_open and self._on_open(rel_path)
        )
        menu.addAction(open_action)
        copy_action = QAction("复制相对路径", menu)
        copy_action.triggered.connect(
            lambda: QApplication.clipboard().setText(rel_path)
        )
        menu.addAction(copy_action)
        menu.exec(QCursor.pos())
