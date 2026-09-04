# -*- coding: utf-8 -*-
"""全局命令面板与章节秒开浮层（PySide6）。

提供：
- Command Palette（Ctrl+K / Ctrl+Shift+P）：聚合全应用核心动作与菜单项，支持模糊过滤与键盘触发。
- Quick Open（Ctrl+P）：快速检索项目中的全部 Markdown 章节与文件，回车秒开。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


@dataclass
class PaletteItem:
    """命令面板条目。"""

    title: str
    category: str = ""
    shortcut: str = ""
    description: str = ""
    callback: Optional[Callable[[], None]] = None
    payload: Any = None


class PaletteItemDelegate(QStyledItemDelegate):
    """自定义条目绘制：左侧分类微标 + 标题，右侧快捷键/路径微标。"""

    def __init__(self, parent=None, dark: bool = False) -> None:
        super().__init__(parent)
        self._dark = dark

    def set_dark(self, dark: bool) -> None:
        self._dark = dark

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 38)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        item: Optional[PaletteItem] = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            painter.restore()
            return

        is_selected = bool(option.state & QStyledItemDelegate.StateFlag.State_Selected)

        # 背景底色
        if is_selected:
            bg_color = QColor("#1e293b" if self._dark else "#eff6ff")
            border_color = QColor("#3b82f6")
            painter.fillRect(option.rect, bg_color)
            painter.setPen(QPen(border_color, 2))
            painter.drawLine(
                option.rect.left() + 2,
                option.rect.top() + 4,
                option.rect.left() + 2,
                option.rect.bottom() - 4,
            )
        else:
            bg_color = QColor("#18181b" if self._dark else "#ffffff")
            painter.fillRect(option.rect, bg_color)

        rect = option.rect.adjusted(12, 0, -12, 0)
        y_mid = rect.center().y()

        # 1. 绘制分类胶囊（如果有）
        cur_x = rect.left()
        if item.category:
            cat_text = item.category
            font_cat = QFont(option.font)
            font_cat.setPointSize(max(8, font_cat.pointSize() - 1))
            painter.setFont(font_cat)
            metrics = painter.fontMetrics()
            cat_w = metrics.horizontalAdvance(cat_text) + 12
            cat_h = 20
            cat_rect = QRect(cur_x, y_mid - cat_h // 2, cat_w, cat_h)

            c_pill_bg = QColor("#27272a" if self._dark else "#f1f5f9")
            c_pill_fg = QColor("#a1a1aa" if self._dark else "#64748b")
            painter.setBrush(c_pill_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(cat_rect, 4, 4)

            painter.setPen(c_pill_fg)
            painter.drawText(cat_rect, Qt.AlignmentFlag.AlignCenter, cat_text)
            cur_x += cat_w + 8

        # 2. 绘制右侧快捷键 / 相对路径
        right_info = item.shortcut or item.description
        right_w = 0
        if right_info:
            font_right = QFont(option.font)
            font_right.setPointSize(max(8, font_right.pointSize() - 1))
            painter.setFont(font_right)
            c_right = QColor("#71717a" if self._dark else "#94a3b8")
            painter.setPen(c_right)
            metrics_right = painter.fontMetrics()
            text_advance = metrics_right.horizontalAdvance(right_info)
            max_right_w = min(240, max(60, rect.width() // 2))
            right_w = min(max_right_w, text_advance + 4)
            right_rect = QRect(rect.right() - right_w, rect.top(), right_w, rect.height())
            elided_right = metrics_right.elidedText(
                right_info, Qt.TextElideMode.ElideLeft, right_rect.width()
            )
            painter.drawText(
                right_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                elided_right,
            )

        # 3. 绘制标题（根据右侧宽度自适应剪裁，防止重叠）
        font_title = QFont(option.font)
        font_title.setPointSize(max(9, font_title.pointSize()))
        if is_selected:
            font_title.setBold(True)
        painter.setFont(font_title)
        c_title = QColor(
            "#60a5fa" if (is_selected and self._dark) else
            ("#1d4ed8" if is_selected else ("#f4f4f5" if self._dark else "#0f172a"))
        )
        painter.setPen(c_title)

        title_w = max(10, rect.width() - (cur_x - rect.left()) - right_w - 8)
        title_rect = QRect(cur_x, rect.top(), title_w, rect.height())
        elided_title = painter.fontMetrics().elidedText(
            item.title, Qt.TextElideMode.ElideRight, title_rect.width()
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_title,
        )

        painter.restore()


class CommandPaletteDialog(QDialog):
    """命令面板与快速打开对话框。"""

    itemActivated = Signal(object)

    def __init__(
        self,
        items: List[PaletteItem],
        *,
        mode: str = "command",  # "command" 或 "file"
        dark: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._all_items = list(items)
        self._mode = mode
        self._dark = dark
        self._filtered_items: List[PaletteItem] = []

        self.setWindowTitle("命令面板" if mode == "command" else "快速打开章节")
        self.setModal(True)
        self.resize(620, 420)

        # 隐藏标准标题栏装饰以达到现代化浮层视觉效果
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._build_ui()
        self._apply_style()
        self._filter_items("")

        # 居中显示在父窗口上方
        if parent is not None:
            parent_window = parent.window()
            p_geo = parent_window.geometry()
            x = p_geo.x() + max(0, (p_geo.width() - self.width()) // 2)
            y = p_geo.y() + max(0, (p_geo.height() - self.height()) // 3)
            self.move(x, y)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部搜索栏
        search_wrap = QWidget(self)
        search_layout = QHBoxLayout(search_wrap)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)

        prefix_lbl = QLabel(">" if self._mode == "command" else "🔍", search_wrap)
        prefix_lbl.setStyleSheet("font-size: 14pt; font-weight: bold; color: #3b82f6;")
        search_layout.addWidget(prefix_lbl)

        self._search_input = QLineEdit(search_wrap)
        self._search_input.setPlaceholderText(
            "输入命令名称或关键字…" if self._mode == "command" else "搜索章节标题或文件名…"
        )
        self._search_input.textChanged.connect(self._filter_items)
        self._search_input.installEventFilter(self)
        search_layout.addWidget(self._search_input, 1)

        layout.addWidget(search_wrap)

        # 结果列表
        self._list_widget = QListWidget(self)
        self._list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._delegate = PaletteItemDelegate(self._list_widget, dark=self._dark)
        self._list_widget.setItemDelegate(self._delegate)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list_widget, 1)

        # 底部快捷提示
        hint_lbl = QLabel(
            "↑ / ↓ 选择 · 回车 激活 · Esc 退出",
            self,
        )
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        hint_lbl.setStyleSheet("color: #71717a; font-size: 9pt;")
        layout.addWidget(hint_lbl)

    def _apply_style(self) -> None:
        if self._dark:
            bg_col = "#18181b"
            border_col = "#3f3f46"
            input_bg = "#27272a"
            input_fg = "#f4f4f5"
        else:
            bg_col = "#ffffff"
            border_col = "#cbd5e1"
            input_bg = "#f8fafc"
            input_fg = "#0f172a"

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 8px;
            }}
            QLineEdit {{
                background-color: {input_bg};
                color: {input_fg};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 11pt;
            }}
            QLineEdit:focus {{
                border: 1px solid #3b82f6;
            }}
            QListWidget {{
                background-color: {bg_col};
                border: none;
                outline: none;
            }}
            """
        )

    def _filter_items(self, query: str) -> None:
        q = query.strip().lower()
        self._list_widget.clear()
        self._filtered_items = []

        for item in self._all_items:
            if not q:
                matched = True
            else:
                search_scope = f"{item.title} {item.category} {item.shortcut} {item.description}".lower()
                matched = q in search_scope

            if matched:
                self._filtered_items.append(item)
                list_item = QListWidgetItem(self._list_widget)
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                self._list_widget.addItem(list_item)

        if self._filtered_items:
            self._list_widget.setCurrentRow(0)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._trigger_current()

    def _trigger_current(self) -> None:
        row = self._list_widget.currentRow()
        if 0 <= row < len(self._filtered_items):
            target = self._filtered_items[row]
            self.accept()
            self.itemActivated.emit(target)
            if target.callback is not None:
                target.callback()

    def eventFilter(self, watched, event) -> bool:
        if watched == self._search_input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                cur = self._list_widget.currentRow()
                if cur < self._list_widget.count() - 1:
                    self._list_widget.setCurrentRow(cur + 1)
                return True
            elif key == Qt.Key.Key_Up:
                cur = self._list_widget.currentRow()
                if cur > 0:
                    self._list_widget.setCurrentRow(cur - 1)
                return True
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._trigger_current()
                return True
            elif key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.reject()
        super().changeEvent(event)

