# -*- coding: utf-8 -*-
"""窄面板动作行：按真实可用宽度横排或竖排（UI2-E 5.1/5.3）。

成果与辅助面板在 340px 下必须可操作，而不是把 minimumWidth 固定成 400+。
本控件按自身宽度把子控件排成一行或堆叠成一列；切换只改布局方向，
不重建子控件、不改变动作语义与顺序。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QSizePolicy, QWidget

#: 低于该宽度（逻辑像素）时改为竖排，保证主动作完整可读。
DEFAULT_STACK_WIDTH = 300


class FlowRow(QWidget):
    """自适应动作行：宽则横排，窄则竖排。"""

    def __init__(
        self,
        *,
        stack_below: int = DEFAULT_STACK_WIDTH,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._stack_below = max(0, int(stack_below))
        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._laid_out: List[QWidget] = []
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._stacked: Optional[bool] = None

    @property
    def inner_layout(self) -> QBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        """按顺序加入一个动作控件。"""
        self._layout.addWidget(widget)
        self._laid_out.append(widget)
        return widget

    def add_stretch(self) -> None:
        self._layout.addStretch(1)

    def is_stacked(self) -> bool:
        return bool(self._stacked)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_direction(int(event.size().width()))

    def apply_width(self, width: int) -> None:
        """按给定宽度重排（供无真实 resize 的场景/测试使用）。"""
        self._apply_direction(int(width))

    def minimumSizeHint(self):  # noqa: N802 - 与 Qt 命名保持一致
        """绝对下限：总是按竖排估算（最宽子控件）。

        这样宽度才能真正降到 340px 以下，进而触发竖排；
        若在本方法里返回樬排总宽，就会出现“永远不会窄到触发竖排”的死锁。
        """
        from PySide6.QtCore import QSize

        widest = max(
            (child.minimumSizeHint().width() for child in self._laid_out),
            default=0,
        )
        tallest = sum(
            child.minimumSizeHint().height() for child in self._laid_out
        ) + max(0, len(self._laid_out) - 1) * self._layout.spacing()
        return QSize(widest, max(tallest, self._layout.minimumSize().height()))

    def _apply_direction(self, width: int) -> None:
        target = width < self._stack_below
        if target == self._stacked:
            return
        self._stacked = target
        self._layout.setDirection(
            QBoxLayout.Direction.TopToBottom if target else QBoxLayout.Direction.LeftToRight
        )
        self.updateGeometry()


__all__ = ["DEFAULT_STACK_WIDTH", "FlowRow"]