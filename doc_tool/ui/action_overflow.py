# -*- coding: utf-8 -*-
"""动作溢出控制器：按真实可用宽度把次要动作收进「更多」菜单。

UI2 视觉与工作台层级（1.2/1.4）的共用逻辑：

- 主要动作（导出 Word / 成果）**不参与溢出**，按完整样式 sizeHint 保留；
- 次要动作按声明顺序尽量留在原位，放不下的进入同一个「更多」菜单；
- 菜单项与原地按钮共用同一个 ``QAction``（enabled / tooltip / 快捷键 /
  triggered 全部沿用），因此可用性与实际行为不会各写一套；
- 只在 resize / style / font 变化时重排，用真实控件宽度与 ``sizeHint`` 计算，
  不重建界面、不在 resize 中递归调用。

本模块不含业务判断，也不复制命令注册表状态。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

#: 溢出项：``(key, 原地控件, 共享 QAction, 该动作所需最小宽度)``。
OverflowItem = Tuple[str, Optional[QWidget], QAction, int]


class ActionOverflow:
    """一组可溢出动作的宽度自适应容器。"""

    def __init__(
        self,
        host: QWidget,
        menu: QMenu,
        button: QToolButton,
        *,
        spacing: int = 6,
    ) -> None:
        self._host = host
        self._menu = menu
        self._button = button
        self._spacing = max(0, int(spacing))
        self._items: List[OverflowItem] = []
        self._primary_width = 0
        self._hidden: List[str] = []
        self._menu_action_pairs: List[Tuple[QAction, QAction]] = []
        self._verify_pending = False
        self._protected: List[QWidget] = []

    # --- 配置 ---

    def register(
        self,
        key: str,
        widget: Optional[QWidget],
        action: QAction,
        *,
        minimum_width: Optional[int] = None,
    ) -> None:
        """登记一个可溢出动作。

        宽度取 ``sizeHint``（完整文字 + QSS 内边距后的自然宽度）而不是
        ``minimumSizeHint``：后者允许 Qt 继续压缩按钮，会重现「文字被裁切」。
        """
        if minimum_width is None:
            if widget is not None:
                hint = widget.sizeHint().width()
                minimum_width = max(hint, widget.minimumSizeHint().width())
            else:
                minimum_width = 0
        self._items.append((key, widget, action, max(0, int(minimum_width))))

    def set_primary_width(self, width: int) -> None:
        """设置必须为不可溢出控件保留的宽度（主要动作 + 省略标签）。"""
        self._primary_width = max(0, int(width))

    def protect(self, *widgets: Optional[QWidget]) -> None:
        """声明“不得被压缩”的主要动作：布局后发现它们被挤压时继续溢出次级动作。"""
        self._protected = [w for w in widgets if w is not None]

    # --- 查询 ---

    @property
    def hidden_keys(self) -> List[str]:
        return list(self._hidden)

    def reset_hidden(self) -> None:
        """清空溢出记录（重新按宽度求解前调用）。"""
        self._hidden = []

    def visible_keys(self) -> List[str]:
        return [key for key, _w, _a, _min in self._items if key not in self._hidden]

    def item(self, key: str) -> Optional[OverflowItem]:
        for entry in self._items:
            if entry[0] == key:
                return entry
        return None

    # --- 重排 ---

    def refresh(self, available_width: Optional[int] = None) -> bool:
        """按可用宽度重排；返回当前是否有动作被收进菜单。

        做两遍收敛：隐藏/显示「更多」按钮本身会改变布局占用宽度，第二遍用固定点
        复核一次，避免刚好卡在边界时反复横跳（界面不会被重建，只切显隐）。
        """
        if not self._alive():
            return False
        total = self._host.width() if available_width is None else int(available_width)
        budget = max(0, total - self._primary_width)
        self._hidden = []
        fits = self._fit(budget)
        button_width = self._button.sizeHint().width() + self._spacing
        for _pass in range(3):
            hidden = [key for key, _w, _a, _m in self._items if key not in fits]
            button_visible = bool(hidden)
            # 预算里已经为「更多」按钮预留了宽度：它不显示时把这份预留还回去。
            adjusted = budget if button_visible else budget + button_width
            new_fits = self._fit(adjusted)
            if new_fits == fits:
                break
            fits = new_fits
        self._hidden = [key for key, _w, _a, _m in self._items if key not in fits]
        for key, widget, _action, _min in self._items:
            if widget is None:
                continue
            widget.setVisible(key in fits)
        self._rebuild_menu()
        has_overflow = bool(self._hidden)
        self._button.setVisible(has_overflow)
        self._button.setEnabled(has_overflow)
        self._schedule_layout_verify()
        return has_overflow

    def _alive(self) -> bool:
        """底层 C++ 对象是否仍有效（控件随窗口销毁后排队回调必须安全退出）。"""
        for widget in (self._host, self._menu, self._button):
            try:
                if widget is None:
                    return False
                widget.width()
            except RuntimeError:
                return False
        return True

    def verify_rendered_widths(self) -> bool:
        """布局完成后再核对一次真实渲染宽度：仍有动作被压缩就继续溢出。

        ``sizeHint`` 与 QSS 内边距之间存在少量差值时，仅靠预计算偶尔会留下
        1～2px 的裁切；这里按实际控件宽度兜底，最多多收一个动作进菜单。
        """
        if not self._alive():
            return False
        overflowed = False
        # 1) 主要动作被压缩：继续溢出次级动作直到它们恢复完整宽度。
        for widget in self._protected:
            try:
                if widget.isHidden():
                    continue
                width = widget.width()
                need = widget.sizeHint().width()
            except RuntimeError:
                continue
            if width + 1 < need:
                for index in range(len(self._items) - 1, -1, -1):
                    key, candidate, _action, _min = self._items[index]
                    if key in self._hidden or candidate is None:
                        continue
                    try:
                        if candidate.isHidden():
                            continue
                    except RuntimeError:
                        continue
                    self._hidden.append(key)
                    candidate.setVisible(False)
                    overflowed = True
                    break
                if overflowed:
                    break
        for index in range(len(self._items) - 1, -1, -1):
            key, widget, _action, _min = self._items[index]
            if widget is None or key in self._hidden:
                continue
            try:
                if widget.isHidden():
                    continue
                width = widget.width()
                need = widget.minimumSizeHint().width()
            except RuntimeError:
                continue
            if width + 1 < need:
                self._hidden.append(key)
                widget.setVisible(False)
                overflowed = True
                break
        if not overflowed:
            return False
        self._rebuild_menu()
        self._button.setVisible(True)
        self._button.setEnabled(True)
        return True

    def _schedule_layout_verify(self) -> None:
        """排队一次布局后复核（避免在 resize 里递归重建界面）。"""
        if self._verify_pending:
            return
        try:
            from PySide6.QtCore import QTimer

            self._verify_pending = True

            def _run() -> None:
                self._verify_pending = False
                if not self._alive():
                    return
                if self.verify_rendered_widths():
                    self._schedule_layout_verify()

            QTimer.singleShot(0, _run)
        except Exception:  # noqa: BLE001 - 无事件循环时跳过复核
            self._verify_pending = False

    def _fit(self, budget: int) -> set:
        """在预算内尽量多保留原位动作；溢出按钮自身也要占位。"""
        fits = set()
        used = 0
        count = len(self._items)
        for index, (key, _widget, _action, width) in enumerate(self._items):
            remaining = count - index - 1
            need = width + self._spacing
            reserve = (self._button.sizeHint().width() + self._spacing) if remaining else 0
            if used + need + reserve <= budget:
                used += need
                fits.add(key)
        return fits

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        self._menu_action_pairs = []
        for key, _widget, action, _min in self._items:
            if key not in self._hidden:
                continue
            entry = self._menu.addAction(action.text())
            entry.setEnabled(action.isEnabled())
            if action.toolTip():
                entry.setToolTip(action.toolTip())
            entry.triggered.connect(action.trigger)
            self._menu_action_pairs.append((entry, action))

    @property
    def menu_action_pairs(self) -> List[Tuple[QAction, QAction]]:
        """当前菜单项与来源动作的配对（供核对可用性/行为一致）。"""
        return list(self._menu_action_pairs)


__all__ = ["ActionOverflow", "OverflowItem"]