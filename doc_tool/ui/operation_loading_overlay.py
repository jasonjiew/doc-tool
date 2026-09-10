# -*- coding: utf-8 -*-
"""现代化操作加载遮罩与异步任务调度组件 (OperationLoadingOverlay & AsyncOperationWorker)。

专为版本控制 (Git/SVN)、耗时文件操作与网络请求设计：
1. 居中悬浮现代拟态卡片（暗色/浅色自适应，与 ProjectLoadingOverlay 视觉同构）；
2. 60 FPS 抗锯齿渐变旋转环动效 (LoadingSpinnerWidget)；
3. 实时主标题、阶段描述文本与无极平滑呼吸进度条；
4. 阻断背景鼠标与键盘穿透，防止重复触发与并发 Git 锁冲突；
5. 基于 QThread 异步调度长耗时任务，彻底告别 UI 主线程冻结与“未响应”白屏；
6. 最小展示时间保护（默认 450ms），确保瞬时任务也能给予明确完整的视觉反馈；
7. 平滑淡出离场动画（200ms），保障零卡顿、零突兀的专业交互质感。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional, TypeVar

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
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

from doc_tool.ui.project_loading_overlay import LoadingSpinnerWidget

T = TypeVar("T")


class AsyncOperationWorker(QThread):
    """通用后台异步操作工作线程。

    将耗时的外部系统调用（如 git push, git pull, git checkout, commit 等）
    移出 UI 主线程执行，避免页面假死与系统“(未响应)”提示。
    """

    sig_finished = Signal(object)
    sig_error = Signal(object)
    sig_progress = Signal(int, str)

    def __init__(
        self,
        task_fn: Callable[..., Any],
        *args: Any,
        parent: Optional[QObject] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self._task_fn = task_fn
        self._args = args
        self._kwargs = kwargs

    def emit_progress(self, percent: int, text: str = "") -> None:
        """供 task_fn 回调发射进度。"""
        self.sig_progress.emit(percent, text)

    def run(self) -> None:
        try:
            result = self._task_fn(*self._args, **self._kwargs)
            self.sig_finished.emit(result)
        except Exception as exc:
            self.sig_error.emit(exc)


class OperationLoadingOverlay(QWidget):
    """通用操作级悬浮加载遮罩层（确保绝对可见且顺畅）。"""

    def __init__(
        self,
        parent: QWidget,
        *,
        dark: bool = False,
        cancellable: bool = False,
        on_cancel: Optional[Callable[[], None]] = None,
        min_display_ms: int = 450,
    ) -> None:
        super().__init__(parent)
        self._dark = dark
        self._cancellable = cancellable
        self._on_cancel = on_cancel
        self._min_display_ms = min_display_ms
        self._start_time: float = 0.0
        self._on_finished_callback: Optional[Callable[[], None]] = None
        self._is_finishing = False

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        if parent:
            parent.installEventFilter(self)
            self.setGeometry(0, 0, parent.width(), parent.height())

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 居中悬浮卡片
        self._card = QFrame(self)
        self._card.setFixedWidth(360)

        card_shadow = QGraphicsDropShadowEffect(self._card)
        card_shadow.setBlurRadius(28)
        card_shadow.setOffset(0, 8)
        self._card.setGraphicsEffect(card_shadow)
        self._card_shadow = card_shadow

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(28, 22, 28, 22)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 顶部行（可选取消按钮）
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.addStretch(1)

        self._close_btn = QPushButton("✕", self._card)
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("取消操作 (Esc)")
        self._close_btn.setVisible(self._cancellable)
        self._close_btn.clicked.connect(self._handle_cancel)
        top_row.addWidget(self._close_btn, 0)
        card_layout.addLayout(top_row)

        # 旋转环 (44px)
        self._spinner = LoadingSpinnerWidget(44, dark=dark, parent=self._card)
        card_layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignCenter)

        # 主标题
        self._title_label = QLabel("正在处理…", self._card)
        title_font = QFont(self.font())
        title_font.setPointSize(11)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        card_layout.addWidget(self._title_label)

        # 副说明文字
        self._desc_label = QLabel("请稍候，操作正在执行…", self._card)
        desc_font = QFont(self.font())
        desc_font.setPointSize(9)
        self._desc_label.setFont(desc_font)
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_label.setWordWrap(True)
        card_layout.addWidget(self._desc_label)

        # 呼吸进度条（默认为 indeterminate 状态）
        self._progress_bar = QProgressBar(self._card)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 0)  # indeterminate
        card_layout.addWidget(self._progress_bar)

        main_layout.addWidget(self._card)

        # 淡出动画特效（平时必须完全禁用，绝不能设 opacity=0！）
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setEnabled(False)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._fade_anim.finished.connect(self._on_animation_finished)

        self.hide()
        self._apply_theme()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme()

    def _apply_theme(self) -> None:
        dark = self._dark
        self._spinner._dark = dark

        bg_alpha = 190 if dark else 210
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
        self._desc_label.setStyleSheet(f"color: {text_muted}; border: none; background: transparent;")

        btn_hover_bg = "rgba(255, 255, 255, 0.1)" if dark else "rgba(0, 0, 0, 0.06)"
        self._close_btn.setStyleSheet(
            f"QPushButton {{ color: {text_muted}; border: none; background: transparent; border-radius: 11px; font-size: 11px; font-weight: bold; }}"
            f"QPushButton:hover {{ color: {text_primary}; background: {btn_hover_bg}; }}"
        )

        bar_bg = "#2e3240" if dark else "#e2e8f0"
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {bar_bg}; border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa); border-radius: 2px; }}"
        )

        self._spinner.update()

    def start(
        self,
        title: str,
        description: str = "请稍候，操作正在执行…",
        *,
        progress: Optional[int] = None,
        cancellable: bool = False,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        """显示加载遮罩并立即启动平滑旋转动效。"""
        self._is_finishing = False
        self._start_time = time.time()
        self._cancellable = cancellable
        self._on_cancel = on_cancel
        self._close_btn.setVisible(cancellable)

        # 确保透明度特效关闭，100% 毫无遮拦地直接可见！
        self._opacity_effect.setEnabled(False)

        self._title_label.setText(title)
        self._desc_label.setText(description)

        if progress is None or progress < 0:
            self._progress_bar.setRange(0, 0)
        else:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(min(100, max(0, progress)))

        if self.parentWidget():
            p = self.parentWidget()
            self.setGeometry(0, 0, p.width(), p.height())

        self.show()
        self.raise_()
        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(True)
        self.setFocus()
        self._spinner.start()

        # 立即派发一次事件循环，确保第一帧半透明遮罩与卡片瞬间渲染！
        QApplication.processEvents()

    def update_text(self, title: Optional[str] = None, description: Optional[str] = None) -> None:
        if title is not None:
            self._title_label.setText(title)
        if description is not None:
            self._desc_label.setText(description)

    def update_progress(self, percent: int, description: Optional[str] = None) -> None:
        if self._progress_bar.maximum() == 0:
            self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(min(100, max(0, percent)))
        if description:
            self._desc_label.setText(description)

    def finish(self, on_finished: Optional[Callable[[], None]] = None) -> None:
        """操作结束：确保满足最小展示时间后平滑淡出关闭。"""
        if self._is_finishing:
            if on_finished:
                on_finished()
            return

        self._is_finishing = True
        self._on_finished_callback = on_finished

        # 检查是否满足最小展示时间
        elapsed_ms = int((time.time() - self._start_time) * 1000)
        remaining_ms = max(0, self._min_display_ms - elapsed_ms)

        if remaining_ms > 0:
            # 进度条拉满至 100%
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(100)
            QTimer.singleShot(remaining_ms, self._do_fade_out)
        else:
            self._do_fade_out()

    def _do_fade_out(self) -> None:
        """开始执行淡出动画。"""
        if not self.isVisible():
            self._spinner.stop()
            self._opacity_effect.setEnabled(False)
            if self._on_finished_callback:
                cb = self._on_finished_callback
                self._on_finished_callback = None
                cb()
            return

        self._spinner.stop()
        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(False)
        self._opacity_effect.setEnabled(True)
        self._opacity_effect.setOpacity(1.0)

        self._fade_anim.stop()
        self._fade_anim.setDuration(200)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_animation_finished(self) -> None:
        self._opacity_effect.setEnabled(False)
        if hasattr(self, "_card_shadow") and self._card_shadow:
            self._card_shadow.setEnabled(True)
        self.hide()
        cb = self._on_finished_callback
        self._on_finished_callback = None
        if cb:
            cb()

    def _handle_cancel(self) -> None:
        if self._cancellable and self._on_cancel:
            self._on_cancel()
        self.finish()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._cancellable:
            self._handle_cancel()
            event.accept()
            return
        # 拦截所有键盘事件，防止背景快捷键被误触发
        event.accept()

    def mousePressEvent(self, event) -> None:
        # 拦截鼠标点击穿透
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.parentWidget():
            p = self.parentWidget()
            self.setGeometry(0, 0, p.width(), p.height())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched == self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if self.parentWidget():
                p = self.parentWidget()
                self.setGeometry(0, 0, p.width(), p.height())
                self.raise_()
        return super().eventFilter(watched, event)


def _get_top_level_window(widget: QWidget) -> QWidget:
    """递归查找最顶层的活动窗口容器。"""
    curr = widget
    while curr.parentWidget() is not None:
        curr = curr.parentWidget()
    return curr


def run_async_operation(
    parent: QWidget,
    task_fn: Callable[..., T],
    *args: Any,
    title: str,
    description: str = "请稍候，操作正在执行…",
    dark: bool = False,
    on_success: Optional[Callable[[T], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    cancellable: bool = False,
    on_cancel: Optional[Callable[[], None]] = None,
    min_display_ms: int = 450,
    **kwargs: Any,
) -> tuple[OperationLoadingOverlay, AsyncOperationWorker]:
    """统一高阶异步操作执行器。

    在后台工作线程执行 `task_fn(*args, **kwargs)`，同时在顶级窗口上方展示
    绝对置顶可见的 60FPS 顺滑加载遮罩 `OperationLoadingOverlay`。
    操作完成后经过平滑最小展示时间与淡出，在 UI 主线程安全回调 `on_success` / `on_error`。
    """
    top_container = _get_top_level_window(parent)

    overlay = OperationLoadingOverlay(
        top_container,
        dark=dark,
        cancellable=cancellable,
        on_cancel=on_cancel,
        min_display_ms=min_display_ms,
    )
    overlay.start(title, description, cancellable=cancellable, on_cancel=on_cancel)

    worker = AsyncOperationWorker(task_fn, *args, parent=top_container, **kwargs)

    # 保持对 worker 和 overlay 的引用防 GC
    if not hasattr(top_container, "_active_async_overlays"):
        top_container._active_async_overlays = []
    top_container._active_async_overlays.append((overlay, worker))

    def _cleanup() -> None:
        try:
            if hasattr(top_container, "_active_async_overlays"):
                if (overlay, worker) in top_container._active_async_overlays:
                    top_container._active_async_overlays.remove((overlay, worker))
        except Exception:
            pass

    def _handle_finished(result: Any) -> None:
        def _after_finish():
            _cleanup()
            if on_success:
                on_success(result)
            if on_finished:
                on_finished()

        overlay.finish(_after_finish)

    def _handle_error(exc: Exception) -> None:
        def _after_finish():
            _cleanup()
            if on_error:
                on_error(exc)
            if on_finished:
                on_finished()

        overlay.finish(_after_finish)

    worker.sig_finished.connect(_handle_finished)
    worker.sig_error.connect(_handle_error)

    worker.start()
    return overlay, worker
