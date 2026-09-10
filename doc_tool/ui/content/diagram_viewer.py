# -*- coding: utf-8 -*-
"""沉浸式架构图/大图查看器（交互式 Lightbox）。

支持以鼠标为中心的无级缩放、全图抓手平移、一键适应/1:1还原、图片复制、保存与直接跳转工作台编辑。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeySequence,
    QMouseEvent,
    QPixmap,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class _DiagramScrollArea(QScrollArea):
    """支持抓手平移拖拽的滚动区（无缝全局平移，防锯齿定位）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._last_global_pos = QPoint()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_global_pos = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            cur_global = event.globalPosition().toPoint()
            delta = cur_global - self._last_global_pos
            self._last_global_pos = cur_global
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            if h_bar:
                h_bar.setValue(h_bar.value() - delta.x())
            if v_bar:
                v_bar.setValue(v_bar.value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DiagramViewerDialog(QDialog):
    """全功能 Mermaid/文档图片沉浸式对话框。"""

    def __init__(
        self,
        pixmap: QPixmap,
        *,
        title: str = "图表查看与探查",
        mermaid_source: Optional[str] = None,
        on_edit_source: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1080, 720)
        self.setMinimumSize(600, 400)

        self._raw_pixmap = pixmap
        self._mermaid_source = mermaid_source
        self._on_edit_source = on_edit_source
        self._zoom_factor = 1.0
        self._fit_mode = True

        self._setup_ui()
        self._setup_shortcuts()
        self._fit_to_window()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_to_window)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 主查看区
        self.scroll_area = _DiagramScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background-color: #1e2029; border: none; }"
        )

        self.preview_label = QLabel(self.scroll_area)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("QLabel { background-color: transparent; }")
        self.scroll_area.setWidget(self.preview_label)

        outer.addWidget(self.scroll_area, 1)

        # 底部浮动控制栏
        bottom_bar = QWidget(self)
        bottom_bar.setStyleSheet(
            "QWidget { background-color: #181920; border-top: 1px solid #2e313d; }"
        )
        bar_layout = QHBoxLayout(bottom_bar)
        bar_layout.setContentsMargins(16, 8, 16, 8)
        bar_layout.setSpacing(10)

        # 分辨率提示信息
        if not self._raw_pixmap.isNull():
            orig_w = self._raw_pixmap.width()
            orig_h = self._raw_pixmap.height()
            self.info_label = QLabel(f"原始分辨率: {orig_w} × {orig_h} px", bottom_bar)
        else:
            self.info_label = QLabel("无图像数据", bottom_bar)
        self.info_label.setStyleSheet("QLabel { color: #94a3b8; font-size: 12px; }")
        bar_layout.addWidget(self.info_label)

        bar_layout.addStretch(1)

        # 缩放指示
        self.label_zoom = QLabel("100%", bottom_bar)
        self.label_zoom.setStyleSheet("QLabel { color: #e2e8f0; font-size: 13px; font-weight: bold; min-width: 50px; }")
        self.label_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar_layout.addWidget(self.label_zoom)

        # 缩小
        self.btn_zoom_out = QPushButton("－ 缩小", bottom_bar)
        self.btn_zoom_out.setToolTip("缩小图表 (-)")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        bar_layout.addWidget(self.btn_zoom_out)

        # 放大
        self.btn_zoom_in = QPushButton("＋ 放大", bottom_bar)
        self.btn_zoom_in.setToolTip("放大图表 (+)")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        bar_layout.addWidget(self.btn_zoom_in)

        # 适应窗口
        self.btn_fit = QPushButton("适应窗口", bottom_bar)
        self.btn_fit.setToolTip("自适应当前窗口尺寸 (0)")
        self.btn_fit.clicked.connect(self._fit_to_window)
        bar_layout.addWidget(self.btn_fit)

        # 1:1
        self.btn_100 = QPushButton("1:1 还原", bottom_bar)
        self.btn_100.setToolTip("恢复原始 100% 大小 (1)")
        self.btn_100.clicked.connect(self._reset_zoom)
        bar_layout.addWidget(self.btn_100)

        # 分隔线
        sep = QFrame(bottom_bar)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("QFrame { color: #374151; }")
        bar_layout.addWidget(sep)

        # 保存图片按钮
        self.btn_save = QPushButton("保存图片", bottom_bar)
        self.btn_save.setToolTip("保存当前架构图到本地文件 (Ctrl+S)")
        self.btn_save.clicked.connect(self._save_image)
        bar_layout.addWidget(self.btn_save)

        # 复制图片按钮
        self.btn_copy = QPushButton("复制图片", bottom_bar)
        self.btn_copy.setToolTip("将当前高清图片复制到剪贴板 (Ctrl+C)")
        self.btn_copy.clicked.connect(self._copy_image)
        bar_layout.addWidget(self.btn_copy)

        # 在工作台编辑按钮（有回调时）
        if self._on_edit_source:
            self.btn_edit = QPushButton("在工作台编辑", bottom_bar)
            self.btn_edit.setProperty("btnRole", "primary")
            self.btn_edit.setToolTip("打开 Mermaid 工作台进行编辑并替换")
            self.btn_edit.clicked.connect(self._handle_edit)
            bar_layout.addWidget(self.btn_edit)

        # 关闭按钮
        self.btn_close = QPushButton("关闭 (ESC)", bottom_bar)
        self.btn_close.clicked.connect(self.accept)
        bar_layout.addWidget(self.btn_close)

        outer.addWidget(bottom_bar)

        # 安装事件过滤器支持滚轮与双击切换
        self.scroll_area.viewport().installEventFilter(self)
        self.preview_label.installEventFilter(self)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+W"), self, self.accept)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_image)
        QShortcut(QKeySequence("Ctrl+C"), self, self._copy_image)
        QShortcut(QKeySequence("+"), self, self._zoom_in)
        QShortcut(QKeySequence("="), self, self._zoom_in)
        QShortcut(QKeySequence("-"), self, self._zoom_out)
        QShortcut(QKeySequence("0"), self, self._fit_to_window)
        QShortcut(QKeySequence("1"), self, self._reset_zoom)

    def eventFilter(self, watched, event: QEvent) -> bool:
        if watched in (self.scroll_area.viewport(), self.preview_label):
            if event.type() == QEvent.Type.Wheel:
                wheel_event: QWheelEvent = event
                num_degrees = wheel_event.angleDelta().y()
                mouse_viewport_pos = self.scroll_area.viewport().mapFromGlobal(wheel_event.globalPosition().toPoint())
                if num_degrees > 0:
                    self._zoom_at(1.2, mouse_viewport_pos)
                elif num_degrees < 0:
                    self._zoom_at(0.833, mouse_viewport_pos)
                return True
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                if self._fit_mode or abs(self._zoom_factor - 1.0) > 0.05:
                    self._reset_zoom()
                else:
                    self._fit_to_window()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode and not self._raw_pixmap.isNull():
            self._render_fit()

    def _zoom_in(self) -> None:
        self._zoom_at(1.25, None)

    def _zoom_out(self) -> None:
        self._zoom_at(0.8, None)

    def _zoom_at(self, multiplier: float, anchor_pos: Optional[QPoint]) -> None:
        if self._raw_pixmap.isNull():
            return
        self._fit_mode = False
        new_factor = max(0.08, min(8.0, round(self._zoom_factor * multiplier, 3)))
        if abs(new_factor - self._zoom_factor) < 0.001:
            return

        old_factor = self._zoom_factor
        self._zoom_factor = new_factor
        self._update_display(anchor_pos, old_factor)

    def _fit_to_window(self) -> None:
        if self._raw_pixmap.isNull():
            return
        self._fit_mode = True
        self._render_fit()

    def _render_fit(self) -> None:
        # 获取视口宽高，未展示时回退到 dialog 的尺寸
        vp_w = self.scroll_area.viewport().width()
        vp_h = self.scroll_area.viewport().height()
        if vp_w <= 100 or vp_h <= 100:
            vp_w = max(vp_w, self.width() - 32)
            vp_h = max(vp_h, self.height() - 80)
        viewport_w = max(50, vp_w - 32)
        viewport_h = max(50, vp_h - 32)

        orig_w = self._raw_pixmap.width()
        orig_h = self._raw_pixmap.height()

        if orig_w <= 0 or orig_h <= 0:
            self.preview_label.setText("无效图片数据")
            self.preview_label.setStyleSheet("QLabel { color: #94a3b8; font-size: 11pt; }")
            return

        scale_w = viewport_w / orig_w
        scale_h = viewport_h / orig_h
        # 若原图尺寸小于视口，默认 100% (1.0) 展开展示，杜绝盲目放大导致小图失真
        scale = min(1.0, scale_w, scale_h)

        self._zoom_factor = scale
        target_w = max(10, int(orig_w * scale))
        target_h = max(10, int(orig_h * scale))

        scaled = self._raw_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setFixedSize(scaled.size())
        self.label_zoom.setText(f"{int(scale * 100)}%")

    def _reset_zoom(self) -> None:
        if self._raw_pixmap.isNull():
            return
        self._fit_mode = False
        self._zoom_factor = 1.0
        self._update_display(None, 1.0)

    def _update_display(self, anchor_pos: Optional[QPoint], old_factor: float) -> None:
        orig_w = self._raw_pixmap.width()
        orig_h = self._raw_pixmap.height()
        if orig_w <= 0 or orig_h <= 0:
            return

        target_w = max(10, int(orig_w * self._zoom_factor))
        target_h = max(10, int(orig_h * self._zoom_factor))

        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        old_h = h_bar.value() if h_bar else 0
        old_v = v_bar.value() if v_bar else 0

        scaled = self._raw_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setFixedSize(scaled.size())
        self.label_zoom.setText(f"{int(self._zoom_factor * 100)}%")

        # 保持鼠标边缘平移补偿
        if anchor_pos is not None and old_factor > 0:
            ratio = self._zoom_factor / old_factor
            new_h = int((old_h + anchor_pos.x()) * ratio - anchor_pos.x())
            new_v = int((old_v + anchor_pos.y()) * ratio - anchor_pos.y())
            if h_bar:
                h_bar.setValue(max(0, new_h))
            if v_bar:
                v_bar.setValue(max(0, new_v))

    def _reset_copy_btn(self, old_text: str) -> None:
        try:
            self.btn_copy.setText(old_text)
            self.btn_copy.setStyleSheet("")
        except RuntimeError:
            pass

    def _reset_save_btn(self, old_text: str) -> None:
        try:
            self.btn_save.setText(old_text)
            self.btn_save.setStyleSheet("")
        except RuntimeError:
            pass

    def _copy_image(self) -> None:
        if not self._raw_pixmap.isNull():
            clipboard = QGuiApplication.clipboard()
            if clipboard:
                clipboard.setPixmap(self._raw_pixmap)
                self.btn_copy.setText("已复制 ✓")
                self.btn_copy.setStyleSheet("QPushButton { color: #22c55e; font-weight: bold; }")
                QTimer.singleShot(1500, self, lambda: self._reset_copy_btn("复制图片"))

    def _save_image(self) -> None:
        if self._raw_pixmap.isNull():
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "保存架构图",
            "diagram.png",
            "PNG 图像 (*.png);;所有文件 (*.*)",
        )
        if filename:
            try:
                ok = self._raw_pixmap.save(filename, "PNG")
                if ok:
                    self.btn_save.setText("已保存 ✓")
                    self.btn_save.setStyleSheet("QPushButton { color: #22c55e; font-weight: bold; }")
                    QTimer.singleShot(1500, self, lambda: self._reset_save_btn("保存图片"))
                else:
                    QMessageBox.warning(self, "保存失败", "无法保存图像文件。")
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", f"无法保存图像：{exc}")

    def _handle_edit(self) -> None:
        self.accept()
        if self._on_edit_source:
            self._on_edit_source()
