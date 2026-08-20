# -*- coding: utf-8 -*-
"""章节树导航面板（左侧 Dock）。

``QTreeView`` + 自定义 ``QAbstractItemModel`` 渲染 ``build_tree`` 推导的
``第X章 → X.Y → X.Y.Z`` 层级。文件节点点击通过 ``on_open`` 回调打开内容
面板；``select_file`` 供搜索/检查结果定位时同步选中并展开父级。

工具栏提供"展开全部 / 折叠全部 / 刷新"；右键菜单提供"打开 / 复制相对路径"。
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import json
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QAbstractItemModel, QByteArray, QMimeData, QModelIndex, Qt
from PySide6.QtGui import QAction, QCursor, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.tree import (
    TreeItem,
    filter_tree_items,
    strip_number_prefix,
)


_STATUS_COLORS = {"added": "#1a9c5b", "modified": "#c98a12"}


@lru_cache(maxsize=None)
def status_icon(status: str) -> QIcon:
    """生成指定状态的彩色圆点图标（运行时绘制，不依赖资源文件）。"""
    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_STATUS_COLORS[status]))
    painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    return QIcon(pix)


class ChapterTreeModel(QAbstractItemModel):
    """基于 ``TreeItem`` 扁平列表的只读树模型。

    根节点用空字符串 id 表示；每个有效节点把 ``node_id`` 作为
    ``internalPointer`` 保存，便于快速定位。
    """

    _ROOT = ""
    MIME_TYPE = "application/x-doc-tool-chapter-node"

    def __init__(self, items, parent=None, *, status=None, on_drop=None) -> None:
        super().__init__(parent)
        self._on_drop = on_drop
        self.set_items(items, status)

    def set_items(self, items: List[TreeItem], status: Optional[Dict[str, str]] = None) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._status = dict(status) if status else {}
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
            if item.is_file:
                state = self._status.get(item.rel_path)
                if state in ("added", "modified"):
                    return status_icon(state)
            return None
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )

    def mimeTypes(self) -> List[str]:
        return [self.MIME_TYPE]

    def mimeData(self, indexes) -> QMimeData:
        mime = QMimeData()
        valid = [index for index in indexes if index.isValid()]
        if valid:
            payload = json.dumps({"nodeId": str(valid[0].internalPointer())})
            mime.setData(self.MIME_TYPE, QByteArray(payload.encode("utf-8")))
        return mime

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def dropMimeData(self, data, action, row, column, parent) -> bool:
        if action == Qt.DropAction.IgnoreAction:
            return True
        if not data.hasFormat(self.MIME_TYPE) or self._on_drop is None:
            return False
        try:
            payload = json.loads(bytes(data.data(self.MIME_TYPE)).decode("utf-8"))
            source_node = str(payload["nodeId"])
        except (KeyError, TypeError, ValueError, UnicodeError):
            return False
        parent_id = self._node_id(parent)
        if parent_id == self._ROOT:
            return False
        parent_item = self._by_id.get(parent_id)
        # Qt 把“放到文件节点上”表示为 parent=该文件、row=-1；文件不能容纳
        # 子节点，因此解释为插入该文件之前。
        if parent_item is not None and parent_item.is_file:
            return bool(
                self._on_drop(source_node, parent_item.parent_id or self._ROOT, parent_id)
            )
        children = self._children.get(parent_id, [])
        before_node = children[row] if 0 <= row < len(children) else None
        return bool(self._on_drop(source_node, parent_id, before_node))

    # --- 辅助 ---

    def _node_id(self, index: QModelIndex) -> str:
        if not index.isValid():
            return self._ROOT
        return str(index.internalPointer())

    def item_for(self, node_id: str) -> Optional[TreeItem]:
        return self._by_id.get(node_id)

    def all_items(self) -> List[TreeItem]:
        return list(self._items)

    def index_for_id(self, node_id: str) -> QModelIndex:
        """按 node_id 深度优先构造模型索引；不存在返回无效索引。"""
        return self._find_index(QModelIndex(), node_id)

    def _find_index(self, parent: QModelIndex, node_id: str) -> QModelIndex:
        parent_id = self._node_id(parent)
        for row, child_id in enumerate(self._children.get(parent_id, [])):
            index = self.createIndex(row, 0, child_id)
            if child_id == node_id:
                return index
            if self.rowCount(index) > 0:
                found = self._find_index(index, node_id)
                if found.isValid():
                    return found
        return QModelIndex()

    def set_status(self, status: Dict[str, str]) -> None:
        """更新徽标状态并重绘受影响文件节点（不重置模型/不折叠展开）。"""
        self._status = dict(status)
        for item in self._items:
            if not item.is_file:
                continue
            index = self.index_for_id(item.node_id)
            if index.isValid():
                self.dataChanged.emit(
                    index, index, [Qt.ItemDataRole.DecorationRole]
                )


class _ChapterTreeView(QTreeView):
    """支持键盘操作的章节树视图：按键委托给面板的 _handle_tree_key。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._on_key: Optional[Callable[[int], bool]] = None

    def keyPressEvent(self, event) -> None:
        if self._on_key is not None and self._on_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def set_drag_enabled(self, enabled: bool) -> None:
        self.setDragEnabled(enabled)
        self.setAcceptDrops(enabled)
        self.setDropIndicatorShown(enabled)
        self.setDragDropMode(
            QTreeView.DragDropMode.InternalMove
            if enabled
            else QTreeView.DragDropMode.NoDragDrop
        )
        self.setDefaultDropAction(Qt.DropAction.MoveAction)


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
        on_create_file: Optional[Callable[[str], None]] = None,
        on_delete_file: Optional[Callable[[str], None]] = None,
        on_rename_file: Optional[Callable[[str], None]] = None,
        on_renumber_dir: Optional[Callable[[str], None]] = None,
        on_move_node: Optional[Callable[[str, str, Optional[str]], bool]] = None,
        on_clear_markers: Optional[Callable[[], None]] = None,
        on_open_external: Optional[Callable[[str], None]] = None,
        on_open_directory: Optional[Callable[[str], None]] = None,
        content_root: Optional[Path] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._on_create_file = on_create_file
        self._on_delete_file = on_delete_file
        self._on_rename_file = on_rename_file
        self._on_renumber_dir = on_renumber_dir
        self._on_move_node = on_move_node
        self._on_clear_markers = on_clear_markers
        self._on_open_external = on_open_external
        self._on_open_directory = on_open_directory
        self._content_root = Path(content_root) if content_root else None
        self._writable = writable
        self._current: Optional[str] = None
        self._items: List[TreeItem] = []
        self._visible_items: List[TreeItem] = []
        self._status_map: Dict[str, str] = {}
        self._model = ChapterTreeModel([], self, on_drop=self._handle_drop)

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
        self._clear_btn = QPushButton("清除标记", self)
        self._clear_btn.setProperty("btnRole", "compact")
        self._clear_btn.clicked.connect(
            lambda: self._on_clear_markers and self._on_clear_markers()
        )
        self._clear_btn.setVisible(self._writable)
        toolbar.addWidget(self._clear_btn)
        self._refresh_btn = QPushButton("刷新", self)
        self._refresh_btn.setProperty("btnRole", "compact")
        self._refresh_btn.clicked.connect(self._on_refresh_click)
        toolbar.addWidget(self._refresh_btn)
        layout.addLayout(toolbar)

        self._filter_entry = QLineEdit(self)
        self._filter_entry.setPlaceholderText("筛选章节或文件名…")
        self._filter_entry.setClearButtonEnabled(True)
        self._filter_entry.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_entry)

        self._tree = _ChapterTreeView(self)
        self._tree._on_key = self._handle_tree_key
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._tree.set_drag_enabled(self._writable)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree, 1)

        self._tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self._tree.doubleClicked.connect(self._on_double_clicked)

    # --- 数据 ---

    def set_items(self, items: List[TreeItem]) -> None:
        """重建树内容，并展开全部目录节点，打开即可看到完整章节层级。"""
        self._items = list(items)
        self._apply_filter(self._filter_entry.text())

    def _apply_filter(self, query: str) -> None:
        """根据输入重建可见节点，并展开匹配结果的完整层级。"""
        self._visible_items = filter_tree_items(self._items, query)
        self._model.set_items(self._visible_items, status=self._status_map)
        for item in self._visible_items:
            if not item.is_file:
                index = self._index_for(item.node_id)
                if index.isValid():
                    self._tree.expand(index)

    def set_status_map(self, status_map: Dict[str, str]) -> None:
        """设置徽标状态映射并重建可见节点（配合 set_items 使用）。"""
        self._status_map = dict(status_map)
        self._apply_filter(self._filter_entry.text())

    def set_status(self, status: Dict[str, str]) -> None:
        """增量更新徽标状态（不重建模型/不折叠展开），仅重绘受影响节点。"""
        self._status_map = dict(status)
        self._model.set_status(status)

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._clear_btn.setVisible(writable)
        self._tree.set_drag_enabled(writable)

    def is_writable(self) -> bool:
        return self._writable

    def expand_all(self) -> None:
        """展开全部目录节点。"""
        for item in self._visible_items:
            if not item.is_file:
                index = self._index_for(item.node_id)
                if index.isValid():
                    self._tree.expand(index)

    def collapse_all(self) -> None:
        """折叠全部目录节点（保留顶层类型节点展开）。"""
        for item in self._visible_items:
            if not item.is_file and item.parent_id is not None:
                index = self._index_for(item.node_id)
                if index.isValid():
                    self._tree.collapse(index)

    def select_file(self, rel_path: str) -> bool:
        """定位到某文件节点：展开祖先并选中；文件不在树中返回 False。"""
        if self._model.item_for(rel_path) is None and self._filter_entry.text():
            self._filter_entry.clear()
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

    def expanded_node_ids(self) -> List[str]:
        """返回当前展开目录 id，供批量移动刷新后恢复。"""
        return [
            item.node_id
            for item in self._visible_items
            if not item.is_file
            and self._index_for(item.node_id).isValid()
            and self._tree.isExpanded(self._index_for(item.node_id))
        ]

    def restore_expanded(self, node_ids: List[str]) -> None:
        for node_id in node_ids:
            index = self._index_for(node_id)
            if index.isValid():
                self._tree.expand(index)

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

    def _handle_drop(
        self, source_node: str, target_parent: str, before_node: Optional[str]
    ) -> bool:
        if not self._writable or self._on_move_node is None:
            return False
        return bool(self._on_move_node(source_node, target_parent, before_node))

    def _handle_tree_key(self, key: int) -> bool:
        """Enter 打开 / F2 重命名 / Del 删除（仅文件节点；写操作需可写）。"""
        rel = self._selected_file()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if rel and self._on_open is not None:
                self._on_open(rel)
                return True
        elif key == Qt.Key.Key_F2:
            if rel and self._writable and self._on_rename_file is not None:
                self._on_rename_file(rel)
                return True
        elif key == Qt.Key.Key_Delete:
            if rel and self._writable and self._on_delete_file is not None:
                self._on_delete_file(rel)
                return True
        return False

    # --- 右键菜单 ---

    def _context_menu(self, index: QModelIndex) -> QMenu:
        """构建指定节点的右键菜单（不 exec，便于测试）。"""
        menu = QMenu(self)
        if not index.isValid():
            return menu
        item = self._model.item_for(str(index.internalPointer()))
        if item is None:
            return menu
        if item.is_file:
            rel_path = item.rel_path
            open_action = QAction("打开", menu)
            open_action.triggered.connect(
                lambda: self._on_open and self._on_open(rel_path)
            )
            menu.addAction(open_action)
            ext_action = QAction("在外部编辑器打开", menu)
            ext_action.triggered.connect(
                lambda: self._on_open_external
                and self._on_open_external(rel_path)
            )
            menu.addAction(ext_action)
            menu.addSeparator()
            copy_rel = QAction("复制相对路径", menu)
            copy_rel.triggered.connect(
                lambda: QApplication.clipboard().setText(rel_path)
            )
            menu.addAction(copy_rel)
            if self._content_root is not None:
                copy_abs = QAction("复制绝对路径", menu)
                copy_abs.triggered.connect(
                    lambda: QApplication.clipboard().setText(
                        str(self._content_root / rel_path)
                    )
                )
                menu.addAction(copy_abs)
            copy_link = QAction("复制 Markdown 引用", menu)
            copy_link.triggered.connect(
                lambda: QApplication.clipboard().setText(
                    self._markdown_link(rel_path)
                )
            )
            menu.addAction(copy_link)
            if self._writable:
                menu.addSeparator()
                rename_action = QAction("重命名…", menu)
                rename_action.triggered.connect(
                    lambda: self._on_rename_file
                    and self._on_rename_file(rel_path)
                )
                menu.addAction(rename_action)
                delete_action = QAction("删除", menu)
                delete_action.triggered.connect(
                    lambda: self._on_delete_file
                    and self._on_delete_file(rel_path)
                )
                menu.addAction(delete_action)
        elif item.parent_id is not None:
            # 目录节点（非类型根）→ 新增章节/文件 + 在文件管理器打开
            if self._writable:
                renumber_action = QAction("重新编号本目录（连续）…", menu)
                renumber_action.triggered.connect(
                    lambda: self._on_renumber_dir
                    and self._on_renumber_dir(item.node_id)
                )
                menu.addAction(renumber_action)
                create_action = QAction("新增章节/文件…", menu)
                create_action.triggered.connect(
                    lambda: self._on_create_file
                    and self._on_create_file(item.node_id)
                )
                menu.addAction(create_action)
            open_dir = QAction("在文件管理器打开", menu)
            open_dir.triggered.connect(
                lambda: self._on_open_directory
                and self._on_open_directory(item.node_id)
            )
            menu.addAction(open_dir)
        return menu

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        menu = self._context_menu(index)
        # 菜单关闭即删除：每次右键新建的 QMenu 以面板为父，若不删除会随
        # 打开次数累积控件树（资源泄漏）。
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.exec(QCursor.pos())

    def _markdown_link(self, rel_path: str) -> str:
        """生成章节引用链接：[标题](相对路径)。"""
        stem = Path(rel_path).stem
        title = strip_number_prefix(stem) or stem
        return "[{0}]({1})".format(title, rel_path)
