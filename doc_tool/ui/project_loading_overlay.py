# -*- coding: utf-8 -*-
"""现代化项目加载遮罩与动效组件 (ProjectLoadingOverlay)。

特性：
- 居中悬浮玻璃质感卡片（深/浅主题自适应）；
- 60 FPS 平滑抗锯齿渐变旋转环形动画；
- 动态显示项目名称与 4 个关键加载阶段提示；
- 加载完成时通过 QPropertyAnimation 平滑淡出（250ms），确保零卡顿视觉体验。
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class LoadingSpinnerWidget(QWidget):
    """自定义 60FPS 优雅渐变旋转环。"""

    def __init__(self, size: int = 40, *, dark: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self._dark = dark
        self._angle = 0
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._rotate)

    def start(self) -> None:
        self._angle = 0
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _rotate(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width()
        h = self.height()
        pen_width = max(3.0, self._size * 0.08)
        rect = QRectF(pen_width, pen_width, w - pen_width * 2, h - pen_width * 2)

        # 1. 绘制淡色轨道圆环
        track_color = QColor(255, 255, 255, 18) if self._dark else QColor(0, 0, 0, 14)
        track_pen = QPen(track_color, pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        # 2. 绘制旋转高亮渐变弧（主色 #3b82f6）
        accent_color = QColor(59, 130, 246)
        active_pen = QPen(accent_color, pen_width)
        active_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(active_pen)

        # 旋转 120 度的弧线
        start_angle = (self._angle) * 16
        span_angle = 100 * 16
        painter.drawArc(rect, -start_angle, -span_angle)


class ProjectLoadingOverlay(QWidget):
    """项目加载全屏/宿主遮罩层。"""

    def __init__(self, parent: QWidget, *, dark: bool = False) -> None:
        super().__init__(parent)
        self._dark = dark
        self._on_finished_callback: Optional[Callable[[], None]] = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if parent:
            parent.installEventFilter(self)

        # 半透明蒙层背景
        bg_alpha = 180 if dark else 210
        bg_rgb = "15, 17, 23" if dark else "248, 250, 252"
        self.setStyleSheet(f"background-color: rgba({bg_rgb}, {bg_alpha});")

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 居中悬浮卡片
        self._card = QFrame(self)
        card_bg = "#1e2029" if dark else "#ffffff"
        card_border = "#2e3240" if dark else "#e2e8f0"
        self._card.setStyleSheet(
            f"QFrame {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 14px; }}"
        )
        self._card.setFixedWidth(340)

        card_shadow = QGraphicsDropShadowEffect(self)
        card_shadow.setBlurRadius(24)
        card_shadow.setColor(QColor(0, 0, 0, 100 if dark else 35))
        card_shadow.setOffset(0, 8)
        self._card.setGraphicsEffect(card_shadow)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(24, 28, 24, 28)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 旋转指示器
        self._spinner = LoadingSpinnerWidget(44, dark=dark, parent=self._card)
        card_layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignCenter)

        # 项目名称
        self._title_label = QLabel("正在打开项目", self._card)
        title_font = QFont(self.font())
        title_font.setPointSize(11)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            f"color: {'#f8fafc' if dark else '#0f172a'}; border: none; background: transparent;"
        )
        card_layout.addWidget(self._title_label)

        # 阶段状态文字
        self._stage_label = QLabel("准备工作区…", self._card)
        stage_font = QFont(self.font())
        stage_font.setPointSize(9)
        self._stage_label.setFont(stage_font)
        self._stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stage_label.setStyleSheet(
            f"color: {'#94a3b8' if dark else '#64748b'}; border: none; background: transparent;"
        )
        card_layout.addWidget(self._stage_label)

        main_layout.addWidget(self._card)

        # 淡出动画特效
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._anim.finished.connect(self._on_animation_finished)

        self.hide()
        self._apply_theme()

    def _apply_theme(self) -> None:
        dark = self._dark
        self._spinner._dark = dark
        bg_alpha = 180 if dark else 210
        bg_rgb = "15, 17, 23" if dark else "248, 250, 252"
        self.setStyleSheet(f"background-color: rgba({bg_rgb}, {bg_alpha});")

        card_bg = "#1e2029" if dark else "#ffffff"
        card_border = "#2e3240" if dark else "#e2e8f0"
        self._card.setStyleSheet(
            f"QFrame {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 14px; }}"
        )
        self._title_label.setStyleSheet(
            f"color: {'#f8fafc' if dark else '#0f172a'}; border: none; background: transparent;"
        )
        self._stage_label.setStyleSheet(
            f"color: {'#94a3b8' if dark else '#64748b'}; border: none; background: transparent;"
        )
        self._spinner.update()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme()

    def start(self, project_name: str = "", initial_stage: str = "正在加载配置…") -> None:
        """启动加载遮罩层并开始播放动画。"""
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        self.raise_()

        if project_name:
            self._title_label.setText(f"打开项目: {project_name}")
        else:
            self._title_label.setText("正在打开项目")

        self._anim.stop()
        self._stage_label.setText(initial_stage)
        self._opacity_effect.setOpacity(1.0)
        self._spinner.start()
        self.show()

    def show_stage(self, stage_text: str) -> None:
        """更新当前执行阶段文字。"""
        self._stage_label.setText(stage_text)

    def finish(self, on_finished: Optional[Callable[[], None]] = None) -> None:
        """平滑淡出并隐藏遮罩。"""
        self._on_finished_callback = on_finished
        if not self.isVisible():
            self._spinner.stop()
            if on_finished:
                on_finished()
            return

        self._stage_label.setText("就绪")
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_animation_finished(self) -> None:
        self._spinner.stop()
        self.hide()
        self._opacity_effect.setOpacity(1.0)
        if self._on_finished_callback:
            cb = self._on_finished_callback
            self._on_finished_callback = None
            cb()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())

    def eventFilter(self, obj, event: QEvent) -> bool:
        if obj == self.parentWidget() and event.type() == QEvent.Type.Resize:
            if self.isVisible():
                self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(obj, event)
