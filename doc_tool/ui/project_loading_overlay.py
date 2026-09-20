# -*- coding: utf-8 -*-
"""现代化项目加载遮罩与动效交互组件 (ProjectLoadingOverlay)。

特性：
- 居中悬浮玻璃质感卡片（深/浅主题自适应）；
- 60 FPS 平滑抗锯齿渐变旋转环形动画；
- 4 阶段进度胶囊与迷你平滑进度条（解析配置 -> 全文索引 -> 准备工作区 -> 恢复标签）；
- 动态阶段切换，自动高亮已完成和进行中步骤；
- 支持「跳过等待 / Esc」主动关闭交互，保障用户掌控感；
- 加载完成时通过 QPropertyAnimation 平滑淡出（220ms），确保零卡顿视觉体验。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LoadingSpinnerWidget(QWidget):
    """自定义 60FPS 优雅渐变旋转环。"""

    def __init__(self, size: int = 44, *, dark: bool = False, parent: Optional[QWidget] = None) -> None:
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
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _rotate(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            w = self.width()
            h = self.height()
            pen_width = max(3.0, self._size * 0.08)
            rect = QRectF(pen_width, pen_width, w - pen_width * 2, h - pen_width * 2)

            # 1. 绘制淡色轨道圆环
            track_color = QColor(255, 255, 255, 22) if self._dark else QColor(0, 0, 0, 18)
            track_pen = QPen(track_color, pen_width)
            track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(track_pen)
            painter.drawArc(rect, 0, 360 * 16)

            # 2. 绘制旋转高亮渐变弧（主色 #3b82f6）
            accent_color = QColor(59, 130, 246)
            active_pen = QPen(accent_color, pen_width)
            active_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(active_pen)

            # 旋转 110 度的弧线
            start_angle = (self._angle) * 16
            span_angle = 110 * 16
            painter.drawArc(rect, -start_angle, -span_angle)
        finally:
            painter.end()


class ProjectLoadingOverlay(QWidget):
    """项目加载全屏/宿主遮罩层（增强样式与交互）。"""

    STAGES = [
        ("配置", "解析配置"),
        ("索引", "全文索引"),
        ("准备", "准备工作区"),
        ("标签", "恢复标签"),
    ]

    def __init__(self, parent: QWidget, *, dark: bool = False) -> None:
        super().__init__(parent)
        self._dark = dark
        self._on_finished_callback: Optional[Callable[[], None]] = None
        self._is_finishing = False
        self._anim_generation = 0
        self._current_step = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if parent:
            parent.installEventFilter(self)

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 居中悬浮卡片
        self._card = QFrame(self)
        self._card.setFixedWidth(380)

        card_shadow = QGraphicsDropShadowEffect(self._card)
        card_shadow.setBlurRadius(28)
        card_shadow.setOffset(0, 8)
        self._card.setGraphicsEffect(card_shadow)
        self._card_shadow = card_shadow

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(24, 22, 24, 20)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 顶部操作行：项目标题 + 关闭/跳过按钮
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        self._title_label = QLabel("正在打开项目", self._card)
        title_font = QFont(self.font())
        title_font.setPointSize(11)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self._title_label, 1)

        self._close_btn = QPushButton("✕", self._card)
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("跳过等待并关闭遮罩 (Esc)")
        self._close_btn.clicked.connect(self.finish)
        top_row.addWidget(self._close_btn, 0)
        card_layout.addLayout(top_row)

        # 旋转环
        self._spinner = LoadingSpinnerWidget(44, dark=dark, parent=self._card)
        card_layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignCenter)

        # 当前阶段提示文字
        self._stage_label = QLabel("正在准备工作区…", self._card)
        stage_font = QFont(self.font())
        stage_font.setPointSize(9)
        stage_font.setBold(False)
        self._stage_label.setFont(stage_font)
        self._stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._stage_label)

        # 分段步骤胶囊条
        self._steps_widget = QWidget(self._card)
        steps_layout = QHBoxLayout(self._steps_widget)
        steps_layout.setContentsMargins(0, 4, 0, 2)
        steps_layout.setSpacing(6)
        self._step_pills: List[QLabel] = []
        for idx, (_, label_text) in enumerate(self.STAGES, 1):
            pill = QLabel(f"{idx}. {label_text}", self._steps_widget)
            pill_font = QFont(self.font())
            pill_font.setPointSize(8)
            pill.setFont(pill_font)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setFixedHeight(22)
            steps_layout.addWidget(pill, 1)
            self._step_pills.append(pill)
        card_layout.addWidget(self._steps_widget)

        # 进度条
        self._progress_bar = QProgressBar(self._card)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(15)
        card_layout.addWidget(self._progress_bar)

        # 底部轻量跳过提示
        self._skip_btn = QPushButton("跳过等待直接进入", self._card)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setProperty("btnRole", "compact")
        self._skip_btn.setFixedHeight(24)
        self._skip_btn.clicked.connect(self.finish)
        card_layout.addWidget(self._skip_btn, 0, Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(self._card)

        # 淡出动画特效
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setEnabled(False)
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

        bg_alpha = 190 if dark else 220
        bg_rgb = "15, 17, 23" if dark else "248, 250, 252"
        self.setStyleSheet(f"background-color: rgba({bg_rgb}, {bg_alpha});")

        card_bg = "#1e2029" if dark else "#ffffff"
        card_border = "#2e3240" if dark else "#cbd5e1"
        self._card.setStyleSheet(
            f"QFrame {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 14px; }}"
        )
        self._card_shadow.setColor(QColor(0, 0, 0, 90 if dark else 30))

        text_primary = "#f8fafc" if dark else "#0f172a"
        text_muted = "#94a3b8" if dark else "#64748b"

        self._title_label.setStyleSheet(f"color: {text_primary}; border: none; background: transparent;")
        self._stage_label.setStyleSheet(f"color: {text_muted}; border: none; background: transparent;")

        # 关闭按钮样式
        btn_hover_bg = "rgba(255, 255, 255, 0.1)" if dark else "rgba(0, 0, 0, 0.06)"
        self._close_btn.setStyleSheet(
            f"QPushButton {{ color: {text_muted}; border: none; background: transparent; border-radius: 11px; font-size: 11px; font-weight: bold; }}"
            f"QPushButton:hover {{ color: {text_primary}; background: {btn_hover_bg}; }}"
        )

        # 跳过按钮样式
        self._skip_btn.setStyleSheet(
            f"QPushButton {{ color: #3b82f6; border: none; background: transparent; font-size: 10px; padding: 2px 8px; }}"
            f"QPushButton:hover {{ text-decoration: underline; color: #60a5fa; }}"
        )

        # 进度条轨道
        bar_bg = "#2e3240" if dark else "#e2e8f0"
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {bar_bg}; border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa); border-radius: 2px; }}"
        )

        self._update_step_pills()
        self._spinner.update()

    def _update_step_pills(self) -> None:
        dark = self._dark
        cur = self._current_step
        for idx, pill in enumerate(self._step_pills):
            if idx < cur:
                # 已完成
                bg = "#064e3b" if dark else "#dcfce7"
                color = "#34d399" if dark else "#15803d"
                border = "#059669" if dark else "#86efac"
                text = f"✓ {self.STAGES[idx][1]}"
            elif idx == cur:
                # 进行中
                bg = "#1e3a8a" if dark else "#dbeafe"
                color = "#60a5fa" if dark else "#1d4ed8"
                border = "#3b82f6" if dark else "#93c5fd"
                text = f"● {self.STAGES[idx][1]}"
            else:
                # 未开始
                bg = "#262936" if dark else "#f1f5f9"
                color = "#64748b" if dark else "#94a3b8"
                border = "transparent"
                text = f"{idx + 1}. {self.STAGES[idx][0]}"
            pill.setText(text)
            pill.setStyleSheet(
                f"QLabel {{ background: {bg}; color: {color}; border: 1px solid {border}; border-radius: 6px; font-weight: {'bold' if idx == cur else 'normal'}; }}"
            )

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

        self._anim_generation += 1
        self._on_finished_callback = None
        self._is_finishing = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._anim.stop()
        self._opacity_effect.setEnabled(False)
        self._opacity_effect.setOpacity(1.0)
        self._current_step = 0
        self._progress_bar.setValue(15)
        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(True)
        self._stage_label.setText(initial_stage)
        self._update_step_pills()
        self._spinner.start()
        self.show()
        self.raise_()
        QApplication.processEvents()

    def show_stage(self, stage_text: str) -> None:
        """更新当前执行阶段文字并步进进度。"""
        self._stage_label.setText(stage_text)

        # 智能匹配步进（先匹配终态与高位阶段，防止关键词包含误判）
        if "就绪" in stage_text or "完成" in stage_text:
            self._current_step = 4
            self._progress_bar.setValue(100)
        elif "标签" in stage_text or "恢复" in stage_text:
            self._current_step = 3
            self._progress_bar.setValue(90)
        elif "工作区" in stage_text or "准备" in stage_text or "视图" in stage_text:
            self._current_step = 2
            self._progress_bar.setValue(75)
        elif "索引" in stage_text:
            self._current_step = 1
            self._progress_bar.setValue(55)
        elif "配置" in stage_text or "元数据" in stage_text:
            self._current_step = 0
            self._progress_bar.setValue(25)

        self._update_step_pills()
        QApplication.processEvents()

    def finish(self, on_finished: Optional[Callable[[], None]] = None, *args) -> None:
        """平滑淡出并隐藏遮罩。"""
        cb = on_finished if callable(on_finished) else None
        if getattr(self, "_is_finishing", False):
            if cb:
                cb()
            return

        self._is_finishing = True
        self._on_finished_callback = cb
        if not self.isVisible():
            self._spinner.stop()
            self._opacity_effect.setEnabled(False)
            self._is_finishing = False
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            if cb:
                cb()
            return

        self._current_step = 4
        self._progress_bar.setValue(100)
        self._update_step_pills()
        self._stage_label.setText("就绪")
        # 淡出期间保持 spinner 顺畅旋转，直至 _on_animation_finished 彻底隐藏时停止

        # 淡出期间将鼠标事件透传给下层工作区，避免 220ms 动画期间界面卡顿
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(False)

        self._opacity_effect.setEnabled(True)
        self._opacity_effect.setOpacity(1.0)
        self._anim_generation += 1
        gen = self._anim_generation
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()
        # 安全兜底：如果 QPropertyAnimation 因任何原因未正常触发 finished，定时器确保强行退出
        QTimer.singleShot(self._anim.duration() + 80, lambda: self._safety_hide(gen))

    def _on_animation_finished(self) -> None:
        self._spinner.stop()
        self.hide()
        self._is_finishing = False
        self._opacity_effect.setEnabled(False)
        self._opacity_effect.setOpacity(1.0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(True)
        if self._on_finished_callback and callable(self._on_finished_callback):
            cb = self._on_finished_callback
            self._on_finished_callback = None
            cb()
        else:
            self._on_finished_callback = None

    def finish_immediately(self, on_finished: Optional[Callable[[], None]] = None, *args) -> None:
        """立即隐藏遮罩，不等待淡出动画（用于 Esc、跳过按钮或异常恢复）。"""
        self._anim_generation += 1
        self._anim.stop()
        self._spinner.stop()
        self.hide()
        self._is_finishing = False
        self._opacity_effect.setEnabled(False)
        self._opacity_effect.setOpacity(1.0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(True)
        cb = on_finished if callable(on_finished) else self._on_finished_callback
        self._on_finished_callback = None
        if cb and callable(cb):
            cb()

    def _safety_hide(self, gen: Optional[int] = None) -> None:
        if gen is not None and gen != self._anim_generation:
            return
        try:
            if self.isVisible():
                self._on_animation_finished()
        except RuntimeError:
            pass

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """按 Esc 键平滑退出遮罩。"""
        if event.key() == Qt.Key.Key_Escape:
            self.finish()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())

    def eventFilter(self, obj, event: QEvent) -> bool:
        if obj == self.parentWidget() and event.type() == QEvent.Type.Resize:
            if self.isVisible():
                self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(obj, event)
