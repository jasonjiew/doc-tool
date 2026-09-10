# -*- coding: utf-8 -*-
"""Codex 风格分支切换悬浮卡片 (BranchPopover) 与分支管理对话框。

对标 Codex / VS Code / JetBrains 分支选择器：
- 宽幅现代卡片设计 (430px)，阴影与圆角层次；
- 顶部宽幅搜索框与快捷刷新/拉取远程分支按钮；
- 分类标签切换（全部 / 本地分支 / 远程分支），带实时计数；
- 当前激活分支智能置顶展示，带鲜明激活标识、超前/落后提交数与未提交改动子标题；
- 分支列表项悬停浮现更多操作按钮 (⋮) 与快捷检出，支持右键快捷菜单；
- 搜索即创建 (Search-to-Create)：搜索无匹配时回车或点击直接基于当前分支新建并切换；
- 新建分支对话框支持规范化快捷前缀胶囊 (feature/、fix/、docs/ 等) 与基准分支灵活选择；
- 智能贴靠在底部状态栏或顶部项目条上方/下方，自动边界防溢出。
"""

from __future__ import annotations

import html
from typing import List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.vcs_changes import GitBranch
from doc_tool.ui.styles import SEMANTIC_COLORS, SEMANTIC_COLORS_DARK, is_dark_theme


class BranchItemWidget(QWidget):
    """单个分支行渲染组件。"""

    menu_requested = Signal(object, QPoint)

    def __init__(
        self,
        branch: GitBranch,
        *,
        dark: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._branch = branch
        self._dark = dark

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)

        # 1. 分支图标（本地分支 ⎇ / 远程分支 ☁）
        icon_str = "☁" if branch.is_remote else "⎇"
        icon_label = QLabel(icon_str, self)
        icon_font = QFont(self.font())
        icon_font.setPointSize(11)
        icon_font.setBold(True)
        icon_label.setFont(icon_font)
        if branch.is_current:
            icon_color = "#3b82f6"
        elif branch.is_remote:
            icon_color = "#818cf8" if dark else "#6366f1"
        else:
            icon_color = "#9ca3af" if dark else "#6b7280"
        icon_label.setStyleSheet(f"color: {icon_color};")
        layout.addWidget(icon_label)

        # 2. 分支名与副标题（未提交提示 / 追踪与超前落后信息）
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        name_layout = QHBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(6)

        name_label = QLabel(branch.name, self)
        name_label.setToolTip(branch.name)
        name_font = QFont(self.font())
        name_font.setPointSize(9)
        if branch.is_current:
            name_font.setBold(True)
        name_label.setFont(name_font)
        name_layout.addWidget(name_label)

        # 领先 / 落后提交数徽标
        badges = []
        if branch.ahead_count > 0:
            badges.append(f"↑{branch.ahead_count}")
        if branch.behind_count > 0:
            badges.append(f"↓{branch.behind_count}")
        if badges:
            track_badge = QLabel(" ".join(badges), self)
            track_badge.setStyleSheet(
                "background: rgba(59, 130, 246, 0.15); color: #3b82f6; "
                "border-radius: 4px; padding: 1px 4px; font-size: 7.5pt; font-weight: 600;"
            )
            name_layout.addWidget(track_badge)

        name_layout.addStretch(1)
        text_layout.addLayout(name_layout)

        # 副标题：当前分支未提交文件数或远程分支提示
        sub_text = ""
        sub_color = "#9ca3af" if dark else "#6b7280"
        if branch.is_current and branch.uncommitted_count > 0:
            sub_text = f"未提交：{branch.uncommitted_count} 个文件"
            colors = SEMANTIC_COLORS_DARK if dark else SEMANTIC_COLORS
            sub_color = colors.get("warning", "#eab308")
        elif branch.is_remote:
            sub_text = "远端分支 · 点击检出并跟踪"
        elif branch.upstream:
            sub_text = f"跟踪 {branch.upstream}"

        if sub_text:
            sub_label = QLabel(sub_text, self)
            sub_font = QFont(self.font())
            sub_font.setPointSize(8)
            sub_label.setFont(sub_font)
            sub_label.setStyleSheet(f"color: {sub_color};")
            text_layout.addWidget(sub_label)

        layout.addLayout(text_layout, 1)

        # 3. 当前分支标识 / 悬停操作按钮
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)

        if branch.is_current:
            cur_tag = QLabel("当前", self)
            cur_tag.setStyleSheet(
                "background: rgba(59, 130, 246, 0.15); color: #3b82f6; "
                "border-radius: 4px; padding: 1px 5px; font-size: 7.5pt; font-weight: 600;"
            )
            action_layout.addWidget(cur_tag)

            check_label = QLabel("✓", self)
            check_font = QFont(self.font())
            check_font.setPointSize(10)
            check_font.setBold(True)
            check_label.setFont(check_font)
            check_label.setStyleSheet("color: #3b82f6;")
            action_layout.addWidget(check_label)

        self._more_btn = QToolButton(self)
        self._more_btn.setText("⋮")
        self._more_btn.setToolTip("分支操作选项")
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; border-radius: 4px; "
            f"font-size: 11pt; font-weight: bold; color: {'#94a3b8' if dark else '#64748b'}; padding: 0 4px; }} "
            f"QToolButton:hover {{ background: {'#2a2b34' if dark else '#e2e8f0'}; color: #3b82f6; }}"
        )
        self._more_btn.clicked.connect(self._on_more_clicked)
        action_layout.addWidget(self._more_btn)

        layout.addLayout(action_layout)

    def _on_more_clicked(self) -> None:
        pos = self._more_btn.mapToGlobal(QPoint(0, self._more_btn.height()))
        self.menu_requested.emit(self._branch, pos)


class BranchPopover(QDialog):
    """Codex 风格分支选择器浮层。"""

    branch_selected = Signal(str)
    create_branch_requested = Signal(str)
    create_from_branch_requested = Signal(str)
    refresh_requested = Signal()
    fetch_requested = Signal()
    delete_branch_requested = Signal(str)
    rename_branch_requested = Signal(str, str)

    def __init__(
        self,
        branches: List[GitBranch],
        *,
        dark: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._branches = list(branches)
        self._dark = dark
        self._active_tab = "all"  # "all", "local", "remote"

        self.setFixedWidth(430)
        self.setMaximumHeight(520)

        # 外层阴影容器
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        self._container = QFrame(self)
        self._container.setObjectName("branchPopoverContainer")
        bg_color = "#1f2026" if dark else "#ffffff"
        border_color = "#3a3b44" if dark else "#e2e8f0"
        self._container.setStyleSheet(
            f"QFrame#branchPopoverContainer {{ "
            f"  background: {bg_color}; "
            f"  border: 1px solid {border_color}; "
            f"  border-radius: 12px; "
            f"}}"
        )

        shadow = QGraphicsDropShadowEffect(self._container)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 120 if dark else 50))
        shadow.setOffset(0, 6)
        self._container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(6)

        # 1. 顶部操作条：宽幅搜索框 + 图标化刷新/Fetch
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("搜索分支或输入新分支名...")
        self._search_input.setClearButtonEnabled(True)
        input_bg = "#18181c" if dark else "#f8fafc"
        input_border = "#2e2f38" if dark else "#cbd5e1"
        self._search_input.setStyleSheet(
            f"QLineEdit {{ "
            f"  background: {input_bg}; "
            f"  border: 1px solid {input_border}; "
            f"  border-radius: 6px; "
            f"  padding: 6px 10px; "
            f"  font-size: 9pt; "
            f"}}"
            f"QLineEdit:focus {{ "
            f"  border-color: #3b82f6; "
            f"}}"
        )
        self._search_input.textChanged.connect(self._on_search_changed)
        self._search_input.installEventFilter(self)
        top_bar.addWidget(self._search_input, 1)

        # 刷新分支按钮
        btn_hover = "#2a2b34" if dark else "#f1f5f9"
        icon_btn_style = (
            f"QPushButton {{ "
            f"  background: transparent; border: 1px solid {input_border}; border-radius: 6px; "
            f"  padding: 5px 8px; font-size: 9pt; font-weight: 500; color: {'#cbd5e1' if dark else '#475569'};"
            f"}} "
            f"QPushButton:hover {{ background: {btn_hover}; border-color: #3b82f6; color: #3b82f6; }}"
        )

        self._refresh_btn = QPushButton("⟳", self)
        self._refresh_btn.setToolTip("重新检查本地与跟踪分支 (Refresh)")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setFixedSize(32, 30)
        self._refresh_btn.setStyleSheet(icon_btn_style)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        top_bar.addWidget(self._refresh_btn)

        # 远端拉取分支 (Fetch) 按钮
        self._fetch_btn = QPushButton("⬇ 远端", self)
        self._fetch_btn.setToolTip("从远程仓库获取最新分支列表 (git fetch --prune)")
        self._fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fetch_btn.setFixedHeight(30)
        self._fetch_btn.setStyleSheet(icon_btn_style)
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        top_bar.addWidget(self._fetch_btn)

        layout.addLayout(top_bar)

        # 2. 分类切换条：全部 / 本地 / 远程
        cat_bar = QHBoxLayout()
        cat_bar.setSpacing(4)

        self._tab_btns = {}
        for key, title in (("all", "全部"), ("local", "本地"), ("remote", "远程")):
            btn = QPushButton(title, self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._on_tab_changed(k))
            cat_bar.addWidget(btn)
            self._tab_btns[key] = btn

        cat_bar.addStretch(1)

        # 状态加载提示
        self._loading_label = QLabel("", self)
        self._loading_label.setStyleSheet("color: #3b82f6; font-size: 8pt;")
        self._loading_label.setVisible(False)
        cat_bar.addWidget(self._loading_label)

        layout.addLayout(cat_bar)

        # 3. 分支列表
        self._list_widget = QListWidget(self)
        self._list_widget.setFrameShape(QFrame.Shape.NoFrame)
        self._list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._show_context_menu)
        list_bg = "transparent"
        list_hover = "#2a2b34" if dark else "#f1f5f9"
        self._list_widget.setStyleSheet(
            f"QListWidget {{ background: {list_bg}; outline: none; border: none; }}"
            f"QListWidget::item {{ border-radius: 6px; margin: 1px 0; padding: 0; }}"
            f"QListWidget::item:hover {{ background: {list_hover}; }}"
            f"QListWidget::item:selected {{ background: {list_hover}; }}"
        )
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list_widget, 1)

        # 空状态提示标签
        self._empty_label = QLabel("未找到匹配的分支", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #94a3b8; font-size: 9pt; padding: 20px 0;")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # 4. 分隔线
        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setStyleSheet(f"background-color: {border_color}; min-height: 1px; max-height: 1px; margin: 4px 0;")
        layout.addWidget(divider)

        # 5. 底部动作：新建并切换分支
        self._new_branch_btn = QPushButton("+ 新建并切换分支...", self)
        self._new_branch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_branch_btn.setStyleSheet(
            f"QPushButton {{ "
            f"  text-align: left; "
            f"  padding: 8px 10px; "
            f"  background: transparent; "
            f"  border: none; "
            f"  border-radius: 6px; "
            f"  color: #3b82f6; "
            f"  font-weight: 600; "
            f"  font-size: 9pt; "
            f"}}"
            f"QPushButton:hover {{ "
            f"  background: {btn_hover}; "
            f"}}"
        )
        self._new_branch_btn.clicked.connect(self._on_create_clicked)
        layout.addWidget(self._new_branch_btn)

        outer_layout.addWidget(self._container)

        self._update_tab_styles()
        self._apply_filter()

    def set_branches(self, branches: List[GitBranch]) -> None:
        """动态更新分支列表数据。"""
        self._branches = list(branches)
        self._update_tab_styles()
        self._apply_filter()

    def set_loading(self, loading: bool, message: str = "") -> None:
        """设置加载状态（例如刷新中/拉取中）。"""
        self._refresh_btn.setEnabled(not loading)
        self._fetch_btn.setEnabled(not loading)
        if loading:
            self._loading_label.setText(message or "正在同步…")
            self._loading_label.setVisible(True)
        else:
            self._loading_label.setVisible(False)

    def _on_tab_changed(self, tab_key: str) -> None:
        self._active_tab = tab_key
        self._update_tab_styles()
        self._apply_filter()

    def _update_tab_styles(self) -> None:
        local_count = sum(1 for b in self._branches if not b.is_remote)
        remote_count = sum(1 for b in self._branches if b.is_remote)
        total_count = len(self._branches)

        counts = {"all": total_count, "local": local_count, "remote": remote_count}
        titles = {"all": "全部", "local": "本地", "remote": "远程"}

        for key, btn in self._tab_btns.items():
            cnt = counts.get(key, 0)
            btn.setText(f"{titles[key]} ({cnt})")
            if key == self._active_tab:
                btn.setStyleSheet(
                    "QPushButton { background: rgba(59, 130, 246, 0.15); color: #3b82f6; "
                    "border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 4px; padding: 2px 8px; font-size: 8pt; font-weight: 600; }"
                )
            else:
                c = "#9ca3af" if self._dark else "#64748b"
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {c}; "
                    f"border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; font-size: 8pt; }}"
                    f"QPushButton:hover {{ background: {'#2a2b34' if self._dark else '#f1f5f9'}; color: {'#e2e8f0' if self._dark else '#334155'}; }}"
                )

    def _on_search_changed(self, text: str) -> None:
        self._apply_filter()

    def _filter_branches(self, text: str) -> None:
        """单元测试与向后兼容保留的方法。"""
        self._search_input.setText(text)
        self._apply_filter()

    def _apply_filter(self) -> None:
        keyword = self._search_input.text().strip()
        kw_lower = keyword.lower()
        filtered = []
        for b in self._branches:
            if self._active_tab == "local" and b.is_remote:
                continue
            if self._active_tab == "remote" and not b.is_remote:
                continue
            if kw_lower and kw_lower not in b.name.lower():
                continue
            filtered.append(b)

        # 排序：当前激活分支置顶，其余按本地/远端及名称排列
        def _sort_key(b: GitBranch):
            return (
                0 if b.is_current else 1,
                1 if b.is_remote else 0,
                b.name.lower(),
            )

        filtered.sort(key=_sort_key)

        # 动态调整底部新建按钮文案与提示
        exact_match = any(b.name.lower() == kw_lower for b in self._branches)
        if keyword and not exact_match:
            self._new_branch_btn.setText(f"✨ 创建并切换至「{keyword}」分支...")
            self._new_branch_btn.setToolTip(f"直接基于当前分支创建「{keyword}」并切换")
        else:
            self._new_branch_btn.setText("+ 新建并切换分支...")
            self._new_branch_btn.setToolTip("创建新分支并切换")

        self._populate_list(filtered)

    def _populate_list(self, branches: List[GitBranch]) -> None:
        self._list_widget.clear()
        keyword = self._search_input.text().strip()
        if not branches:
            self._list_widget.setVisible(False)
            if keyword:
                self._empty_label.setText(f"未找到匹配分支\n回车或点击下方可直接创建「{keyword}」")
            else:
                self._empty_label.setText("暂无可用分支")
            self._empty_label.setVisible(True)
            return

        self._empty_label.setVisible(False)
        self._list_widget.setVisible(True)

        for b in branches:
            item = QListWidgetItem(self._list_widget)
            item.setData(Qt.ItemDataRole.UserRole, b)
            widget = BranchItemWidget(b, dark=self._dark)
            widget.menu_requested.connect(self._show_context_menu_for_branch)
            item.setSizeHint(widget.sizeHint())
            self._list_widget.addItem(item)
            self._list_widget.setItemWidget(item, widget)
        if self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(0)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        branch: Optional[GitBranch] = item.data(Qt.ItemDataRole.UserRole)
        if branch:
            self.branch_selected.emit(branch.name)
            self.accept()

    def _on_create_clicked(self) -> None:
        keyword = self._search_input.text().strip()
        self.create_branch_requested.emit(keyword or "")
        self.accept()

    def _on_refresh_clicked(self) -> None:
        self.refresh_requested.emit()

    def _on_fetch_clicked(self) -> None:
        self.fetch_requested.emit()

    def _show_context_menu_for_branch(self, branch: GitBranch, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {'#1f2026' if self._dark else '#ffffff'}; "
            f"border: 1px solid {'#3a3b44' if self._dark else '#e2e8f0'}; border-radius: 6px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 16px; border-radius: 4px; font-size: 9pt; color: {'#e2e8f0' if self._dark else '#1e293b'}; }}"
            f"QMenu::item:selected {{ background: {'#2a2b34' if self._dark else '#f1f5f9'}; color: #3b82f6; }}"
        )

        if not branch.is_current:
            title = "检出为本地跟踪分支" if branch.is_remote else "切换至此分支"
            act_checkout = menu.addAction(title)
            act_checkout.triggered.connect(lambda: (self.branch_selected.emit(branch.name), self.accept()))

        act_create_from = menu.addAction("基于此分支新建分支…")
        act_create_from.triggered.connect(lambda: (self.create_from_branch_requested.emit(branch.name), self.accept()))

        if not branch.is_remote:
            act_rename = menu.addAction("重命名分支…")
            act_rename.triggered.connect(lambda: self._trigger_rename(branch.name))

            if not branch.is_current:
                act_delete = menu.addAction("删除此分支")
                act_delete.triggered.connect(lambda: self._trigger_delete(branch.name))

        menu.addSeparator()
        act_copy = menu.addAction("复制分支名称")
        act_copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(branch.name))

        menu.exec(global_pos)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._list_widget.itemAt(pos)
        if not item:
            return
        branch: Optional[GitBranch] = item.data(Qt.ItemDataRole.UserRole)
        if not branch:
            return
        self._show_context_menu_for_branch(branch, self._list_widget.mapToGlobal(pos))

    def _trigger_rename(self, old_name: str) -> None:
        existing = [b.name for b in self._branches]
        dlg = RenameBranchDialog(old_name, existing, dark=self._dark, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.new_name:
            self.rename_branch_requested.emit(old_name, dlg.new_name)

    def _trigger_delete(self, branch_name: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("删除分支确认")
        box.setText(f"确定要删除本地分支「<b>{html.escape(branch_name)}</b>」吗？\n\n此操作将不可逆。")
        box.setIcon(QMessageBox.Icon.Warning)
        btn_del = box.addButton("删除", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == btn_del:
            self.delete_branch_requested.emit(branch_name)

    def eventFilter(self, obj, event: QEvent) -> bool:
        """支持在搜索输入框中用上下键移动分支列表、按回车选择。"""
        if obj == self._search_input and event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() == Qt.Key.Key_Down:
                cur = self._list_widget.currentRow()
                if cur < self._list_widget.count() - 1:
                    self._list_widget.setCurrentRow(cur + 1)
                return True
            elif key_event.key() == Qt.Key.Key_Up:
                cur = self._list_widget.currentRow()
                if cur > 0:
                    self._list_widget.setCurrentRow(cur - 1)
                return True
            elif key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._list_widget.count() > 0:
                    cur_item = self._list_widget.currentItem() or self._list_widget.item(0)
                    if cur_item:
                        self._on_item_clicked(cur_item)
                        return True
                else:
                    if self._search_input.text().strip():
                        self._on_create_clicked()
                        return True
        return super().eventFilter(obj, event)

    def hideEvent(self, event) -> None:
        if hasattr(self, "_container"):
            eff = self._container.graphicsEffect()
            if eff:
                eff.setEnabled(False)
        super().hideEvent(event)

    def show_anchored(self, anchor: Optional[QWidget] = None) -> None:
        """根据锚点控件位置智能弹出在上方（状态栏）或下方（顶部工具栏）。若无锚点则居中弹出。"""
        if hasattr(self, "_container"):
            eff = self._container.graphicsEffect()
            if eff:
                eff.setEnabled(True)
        self.adjustSize()
        pop_w = 430
        item_count = self._list_widget.count() if self._list_widget.isVisible() else 0
        target_h = max(260, min(self.maximumHeight(), 160 + max(1, min(item_count, 8)) * 44))
        self.resize(pop_w, target_h)

        scr = (anchor.screen() if anchor else None) or QApplication.primaryScreen()
        screen = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)

        if anchor and anchor.isVisible():
            anchor_rect = anchor.rect()
            top_left_global = anchor.mapToGlobal(anchor_rect.topLeft())
            x = top_left_global.x()
            if x + pop_w > screen.right() - 8:
                x = screen.right() - pop_w - 8
            if x < screen.left() + 8:
                x = screen.left() + 8

            if top_left_global.y() > screen.center().y():
                # 靠底端（状态栏）：弹出在按钮上方
                y = top_left_global.y() - target_h - 6
                if y < screen.top() + 8:
                    y = screen.top() + 8
            else:
                # 靠顶端（项目条）：弹出在按钮下方
                y = top_left_global.y() + anchor.height() + 6
                if y + target_h > screen.bottom() - 8:
                    y = screen.bottom() - target_h - 8
        else:
            parent = self.parentWidget()
            if parent and parent.isVisible():
                p_geo = parent.geometry()
                x = p_geo.center().x() - pop_w // 2
                y = p_geo.top() + 80
            else:
                x = screen.center().x() - pop_w // 2
                y = screen.top() + 100

        self.move(x, y)
        self.show()
        self._search_input.setFocus()


class NewBranchDialog(QDialog):
    """新建并切换分支对话框。"""

    def __init__(
        self,
        current_branch: str,
        existing_branches: List[str],
        *,
        initial_name: str = "",
        dark: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建并切换分支")
        self.setMinimumWidth(430)
        self._existing_branches = set(existing_branches)
        self._current_branch = current_branch
        self.branch_name = ""
        self.base_branch = current_branch

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        # 1. 基准分支选择
        base_layout = QHBoxLayout()
        base_layout.setSpacing(8)
        base_title = QLabel("基准分支:", self)
        base_title.setStyleSheet("font-weight: 500;")
        base_layout.addWidget(base_title)

        self._base_combo = QComboBox(self)
        unique_branches = []
        if current_branch and current_branch != "HEAD":
            unique_branches.append(current_branch)
        for b in existing_branches:
            if b and b not in unique_branches:
                unique_branches.append(b)
        if not unique_branches:
            unique_branches.append(current_branch or "HEAD")
        self._base_combo.addItems(unique_branches)
        if current_branch in unique_branches:
            self._base_combo.setCurrentText(current_branch)
        base_layout.addWidget(self._base_combo, 1)
        layout.addLayout(base_layout)

        # 2. 分支名称输入
        name_title = QLabel("新分支名称:", self)
        name_title.setStyleSheet("font-weight: 500;")
        layout.addWidget(name_title)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText("例如: feature/new-module 或 fix/issue-123")
        self._input.textChanged.connect(self._validate_input)
        layout.addWidget(self._input)

        # 3. 快捷前缀胶囊
        prefix_layout = QHBoxLayout()
        prefix_layout.setSpacing(6)
        prefix_tip = QLabel("常用前缀:", self)
        prefix_tip.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        prefix_layout.addWidget(prefix_tip)

        prefixes = ["feature/", "fix/", "docs/", "refactor/", "release/"]
        self._prefix_btns = []
        for pfx in prefixes:
            btn = QPushButton(pfx, self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: {'#2a2b34' if dark else '#f1f5f9'}; "
                f"border: 1px solid {'#3a3b44' if dark else '#e2e8f0'}; border-radius: 4px; "
                f"padding: 2px 7px; font-size: 8pt; color: {'#93c5fd' if dark else '#2563eb'}; font-weight: 500; }} "
                f"QPushButton:hover {{ background: {'#3b82f6' if dark else '#dbeafe'}; color: {'#ffffff' if dark else '#1d4ed8'}; }}"
            )
            btn.clicked.connect(lambda _, p=pfx: self._apply_prefix(p))
            prefix_layout.addWidget(btn)
            self._prefix_btns.append(btn)
        prefix_layout.addStretch(1)
        layout.addLayout(prefix_layout)

        # 4. 校验提示标签
        self._tip_label = QLabel("", self)
        self._tip_label.setStyleSheet("color: #ef4444; font-size: 8.5pt;")
        layout.addWidget(self._tip_label)

        # 5. 底部按钮区
        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        self._cancel_btn = QPushButton("取消", self)
        self._cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self._cancel_btn)

        self._create_btn = QPushButton("创建并切换", self)
        self._create_btn.setProperty("btnRole", "primary")
        self._create_btn.setDefault(True)
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_confirm)
        self._input.returnPressed.connect(lambda: self._create_btn.click() if self._create_btn.isEnabled() else None)
        btn_box.addWidget(self._create_btn)

        layout.addLayout(btn_box)

        if initial_name:
            self._input.setText(initial_name)
            self._input.selectAll()

    def _apply_prefix(self, prefix: str) -> None:
        cur = self._input.text().strip()
        common_prefixes = ["feature/", "fix/", "docs/", "refactor/", "release/", "hotfix/", "test/"]
        replaced = False
        for p in common_prefixes:
            if cur.startswith(p):
                cur = prefix + cur[len(p):]
                replaced = True
                break
        if not replaced:
            cur = prefix + cur.lstrip("/")
        self._input.setText(cur)
        self._input.setFocus()
        self._input.setCursorPosition(len(cur))

    def _validate_input(self, text: str) -> None:
        name = text.strip()
        if not name:
            self._tip_label.setText("")
            self._create_btn.setEnabled(False)
            return
        if any(ch in name for ch in " ~^:?*[\\]"):
            self._tip_label.setText("分支名包含空格或非法特殊字符 (~^:?*[\\])")
            self._create_btn.setEnabled(False)
            return
        if ".." in name or name.startswith("/") or name.endswith("/") or name.endswith(".lock"):
            self._tip_label.setText("分支名格式不符合 Git 命名规则")
            self._create_btn.setEnabled(False)
            return
        if name in self._existing_branches:
            self._tip_label.setText("该分支名已存在")
            self._create_btn.setEnabled(False)
            return
        self._tip_label.setText("")
        self._create_btn.setEnabled(True)

    def _on_confirm(self) -> None:
        self.branch_name = self._input.text().strip()
        self.base_branch = self._base_combo.currentText().strip() or self._current_branch
        self.accept()


class RenameBranchDialog(QDialog):
    """重命名分支对话框。"""

    def __init__(
        self,
        old_name: str,
        existing_branches: List[str],
        *,
        dark: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("重命名分支")
        self.setMinimumWidth(380)
        self._old_name = old_name
        self._existing_branches = set(existing_branches)
        self.new_name = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        safe_name = html.escape(old_name)
        info_label = QLabel(f"为分支 <b>{safe_name}</b> 输入新名称：", self)
        layout.addWidget(info_label)

        self._input = QLineEdit(self)
        self._input.setText(old_name)
        self._input.selectAll()
        self._input.textChanged.connect(self._validate_input)
        layout.addWidget(self._input)

        self._tip_label = QLabel("", self)
        self._tip_label.setStyleSheet("color: #ef4444; font-size: 8.5pt;")
        layout.addWidget(self._tip_label)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        self._confirm_btn = QPushButton("重命名", self)
        self._confirm_btn.setProperty("btnRole", "primary")
        self._confirm_btn.setDefault(True)
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._on_confirm)
        self._input.returnPressed.connect(lambda: self._confirm_btn.click() if self._confirm_btn.isEnabled() else None)
        btn_box.addWidget(self._confirm_btn)

        layout.addLayout(btn_box)

    def _validate_input(self, text: str) -> None:
        name = text.strip()
        if not name or name == self._old_name:
            self._tip_label.setText("")
            self._confirm_btn.setEnabled(False)
            return
        if any(ch in name for ch in " ~^:?*[\\]"):
            self._tip_label.setText("分支名包含空格或非法特殊字符")
            self._confirm_btn.setEnabled(False)
            return
        if ".." in name or name.startswith("/") or name.endswith("/") or name.endswith(".lock"):
            self._tip_label.setText("分支名格式不符合 Git 规则")
            self._confirm_btn.setEnabled(False)
            return
        if name in self._existing_branches:
            self._tip_label.setText("该分支名已存在")
            self._confirm_btn.setEnabled(False)
            return
        self._tip_label.setText("")
        self._confirm_btn.setEnabled(True)

    def _on_confirm(self) -> None:
        self.new_name = self._input.text().strip()
        self.accept()
