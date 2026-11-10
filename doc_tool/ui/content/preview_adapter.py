# -*- coding: utf-8 -*-
"""统一 Markdown 预览适配边界（REQ-ED-01、REQ-MD-08）。

协调 QWebEngine 高保真阅读模式与 QTextBrowser 原生轻量近似模式，
实现按需加载、状态指示、模式平滑切换、页面就绪队列与崩溃安全降级。
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QCursor,
    QDesktopServices,
    QGuiApplication,
    QImage,
    QMouseEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from doc_tool.domain.preview_types import (
    BlockLocation,
    BlockRegistry,
    DiagramIdentity,
    PreviewMode,
    PreviewSnapshot,
)

logger = logging.getLogger(__name__)


@dataclass
class _ImageHitInfo:
    img_format: QTextFormat
    pixmap: QPixmap
    line_no: Optional[int]
    is_mermaid: bool


class _PreviewBrowser(QTextBrowser):
    """原生轻量 QTextBrowser Markdown 预览浏览器，支持图片等比缩放、大图查看与工作台联动。"""

    def __init__(self, parent=None, editor_panel=None):
        super().__init__(parent)
        self._last_width = -1
        self._editor_panel = editor_panel
        self.setMouseTracking(True)

    def set_editor_panel(self, panel) -> None:
        self._editor_panel = panel

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if abs(self.viewport().width() - self._last_width) > 2:
            self.adjust_images()

    def adjust_images(self) -> None:
        viewport_w = self.viewport().width()
        self._last_width = viewport_w
        doc = self.document()
        doc_margin = doc.documentMargin()
        avail_w = max(50.0, viewport_w - 2 * doc_margin - 28)

        cursor = QTextCursor(doc)
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fmt = frag.charFormat()
                    if fmt.isImageFormat():
                        img_fmt = fmt.toImageFormat()
                        prop_w = img_fmt.property(QTextFormat.Property.UserProperty + 1)
                        prop_h = img_fmt.property(QTextFormat.Property.UserProperty + 2)
                        if prop_w is None or prop_h is None:
                            specified_w = img_fmt.width()
                            specified_h = img_fmt.height()
                            name = img_fmt.name()
                            pix = doc.resource(
                                QTextDocument.ResourceType.ImageResource,
                                QUrl(name),
                            )
                            if not pix or pix.isNull():
                                pix = doc.resource(
                                    QTextDocument.ResourceType.ImageResource,
                                    doc.baseUrl().resolved(QUrl(name)),
                                )
                            pix_w = float(pix.width()) if pix and not pix.isNull() else 0.0
                            pix_h = float(pix.height()) if pix and not pix.isNull() else 0.0

                            if specified_w > 0:
                                base_w = float(specified_w)
                                if specified_h > 0:
                                    base_h = float(specified_h)
                                elif pix_w > 0:
                                    base_h = base_w * (pix_h / pix_w)
                                else:
                                    base_h = base_w
                            elif pix_w > 0:
                                base_w = pix_w
                                base_h = pix_h
                            else:
                                base_w = 0.0
                                base_h = 0.0

                            img_fmt.setProperty(QTextFormat.Property.UserProperty + 1, base_w)
                            img_fmt.setProperty(QTextFormat.Property.UserProperty + 2, base_h)
                        else:
                            base_w = float(prop_w)
                            base_h = float(prop_h)

                        if base_w > 0:
                            target_w = min(base_w, avail_w)
                            target_h = target_w * (base_h / base_w) if base_w > 0 else base_h
                            max_h = 520.0
                            if target_h > max_h and base_h > 0:
                                target_h = max_h
                                target_w = target_h * (base_w / base_h)
                            if abs(img_fmt.width() - target_w) > 0.5 or abs(img_fmt.height() - target_h) > 0.5:
                                img_fmt.setWidth(target_w)
                                img_fmt.setHeight(target_h)
                                cursor.setPosition(frag.position())
                                cursor.setPosition(
                                    frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor
                                )
                                cursor.setCharFormat(img_fmt)
                it += 1
            block = block.next()

    def _image_at(self, pos: QPoint) -> Optional[_ImageHitInfo]:
        cursor = self.cursorForPosition(pos)
        doc = self.document()
        pos_idx = cursor.position()
        candidates = [pos_idx]
        if pos_idx > 0:
            candidates.append(pos_idx - 1)
        for p in candidates:
            cur = QTextCursor(doc)
            cur.setPosition(p)
            fmt = cur.charFormat()
            if fmt.isImageFormat():
                img_fmt = fmt.toImageFormat()
                name = img_fmt.name()
                pix = doc.resource(QTextDocument.ResourceType.ImageResource, QUrl(name))
                if not pix or pix.isNull():
                    pix = doc.resource(
                        QTextDocument.ResourceType.ImageResource,
                        doc.baseUrl().resolved(QUrl(name)),
                    )
                if pix and not pix.isNull():
                    line_no = None
                    href = fmt.anchorHref() or ""
                    if "line-" in href:
                        m = re.search(r"line-(\d+)", href)
                        if m:
                            line_no = int(m.group(1))
                    if line_no is None:
                        for aname in fmt.anchorNames():
                            if "line-" in aname:
                                m = re.search(r"line-(\d+)", aname)
                                if m:
                                    line_no = int(m.group(1))
                                    break
                    is_mermaid = False
                    alt_text = img_fmt.stringProperty(QTextFormat.Property.ImageAltText) or ""
                    if (
                        "mermaid" in alt_text.lower()
                        or "mermaid" in img_fmt.name().lower()
                        or "mermaid" in (fmt.toolTip() or "").lower()
                    ):
                        is_mermaid = True
                    elif line_no is not None and self._editor_panel:
                        block = self._editor_panel.get_mermaid_block_at_line(line_no)
                        if block is not None:
                            is_mermaid = True
                    return _ImageHitInfo(img_fmt, pix, line_no, is_mermaid)
        return None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            info = self._image_at(event.pos())
            if info and not info.pixmap.isNull():
                self._open_viewer(info)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _open_viewer(self, info: _ImageHitInfo) -> None:
        from doc_tool.ui.content.diagram_viewer import DiagramViewerDialog

        mermaid_source = None
        on_edit = None
        title = "Mermaid 图表高清查看与探索" if info.is_mermaid else "图片高清查看与探索"
        if info.line_no is not None and self._editor_panel:
            block = self._editor_panel.get_mermaid_block_at_line(info.line_no)
            if block:
                mermaid_source = block.source
                on_edit = lambda: self._editor_panel.open_mermaid_workbench(block.source, block)
        dialog = DiagramViewerDialog(
            info.pixmap,
            title=title,
            mermaid_source=mermaid_source,
            on_edit_source=on_edit,
            parent=self.window(),
            dark=getattr(self, "_is_dark", False),
        )
        dialog.exec()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        info = self._image_at(event.pos())
        if info and not info.pixmap.isNull():
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            if info.is_mermaid:
                self.setToolTip("💡 Mermaid 图表：双击放大并自由缩放平移 · 右键在工作台编辑")
            else:
                self.setToolTip("💡 双击放大查看高清大图 (滚轮缩放 / 抓手平移)")
        else:
            self.unsetCursor()
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        info = self._image_at(event.pos())
        menu = self.createStandardContextMenu()
        if info and not info.pixmap.isNull():
            first_action = menu.actions()[0] if menu.actions() else None

            act_view = QAction("🔍 查看大图与自由缩放 (双击)", menu)
            act_view.triggered.connect(lambda: self._open_viewer(info))
            menu.insertAction(first_action, act_view)

            if info.line_no is not None and self._editor_panel:
                block = self._editor_panel.get_mermaid_block_at_line(info.line_no)
                if block:
                    act_edit = QAction("🖊 在 Mermaid 工作台中编辑...", menu)
                    act_edit.triggered.connect(
                        lambda: self._editor_panel.open_mermaid_workbench(block.source, block)
                    )
                    menu.insertAction(first_action, act_edit)

                    act_src = QAction("📍 定位到 Markdown 源码", menu)
                    act_src.triggered.connect(
                        lambda: (
                            self._editor_panel.highlight_line(info.line_no),
                            self._editor_panel._flash_line(info.line_no),
                        )
                    )
                    menu.insertAction(first_action, act_src)

                    act_copy_src = QAction("📄 复制 Mermaid 源码", menu)
                    act_copy_src.triggered.connect(
                        lambda: QGuiApplication.clipboard().setText(block.source)
                    )
                    menu.insertAction(first_action, act_copy_src)
                else:
                    act_src = QAction("📍 定位到 Markdown 源码", menu)
                    act_src.triggered.connect(
                        lambda: (
                            self._editor_panel.highlight_line(info.line_no),
                            self._editor_panel._flash_line(info.line_no),
                        )
                    )
                    menu.insertAction(first_action, act_src)

            act_copy_img = QAction("📋 复制图片到剪贴板", menu)
            act_copy_img.triggered.connect(
                lambda: QGuiApplication.clipboard().setPixmap(info.pixmap)
            )
            menu.insertAction(first_action, act_copy_img)

            menu.insertSeparator(first_action)

        menu.exec(event.globalPos())


class PreviewAdapter(QWidget):
    """统一预览适配边界组件。

    对外提供统一的阅读预览能力，封装 QWebEngine 高保真与 QTextBrowser 轻量模式。
    保证正文编辑/保存/撤销状态不受模式切换影响，并在运行时故障时自动优雅降级。
    """

    anchorClicked = Signal(QUrl)
    headingClicked = Signal(str)
    mermaidEditRequested = Signal(str)
    mermaidViewRequested = Signal(str)
    mermaidLocateRequested = Signal(str)
    modeChanged = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None, editor_panel=None) -> None:
        super().__init__(parent)
        self._editor_panel = editor_panel
        self._mode = PreviewMode.FIDELITY
        self._fidelity_available = False
        self._fidelity_browser: Optional[Any] = None
        self._light_browser: Optional[_PreviewBrowser] = None
        self._current_text: str = ""
        self._current_base_url: QUrl = QUrl()
        self._current_snapshot: Optional[PreviewSnapshot] = None
        self._is_dark: bool = False
        self._crash_count: int = 0
        # 高保真初始化失败的真实原因（供诊断弹窗与现场反馈，不再只写日志）。
        self._fidelity_error_text: str = ""
        self._fidelity_error_traceback: str = ""

        self._init_ui()
        self._init_browsers()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 模式与状态栏
        self._banner_frame = QFrame(self)
        self._banner_frame.setStyleSheet(
            "QFrame { background: #f1f5f9; border-bottom: 1px solid #cbd5e1; padding: 2px 6px; }"
        )
        banner_layout = QHBoxLayout(self._banner_frame)
        banner_layout.setContentsMargins(4, 2, 4, 2)
        banner_layout.setSpacing(8)

        self._lbl_mode = QLabel("模式: 高保真阅读", self._banner_frame)
        self._lbl_mode.setStyleSheet("font-weight: 600; color: #334155; font-size: 11px;")
        self._lbl_mode.setToolTip(
            "高保真 Markdown 阅读预览（对齐 VS Code / 官方 Mermaid 语义；非 Word 最终排版）"
        )
        banner_layout.addWidget(self._lbl_mode)

        self._lbl_status = QLabel("", self._banner_frame)
        self._lbl_status.setStyleSheet("color: #dc2626; font-size: 11px;")
        banner_layout.addWidget(self._lbl_status, stretch=1)

        self._btn_mode = QPushButton("切换轻量模式", self._banner_frame)
        self._btn_mode.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 1px 8px; border: 1px solid #cbd5e1; border-radius: 3px; background: #ffffff; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        self._btn_mode.setToolTip("在 QWebEngine 高保真模式与原生轻量近似模式间切换（不修改正文与撤销历史）")
        self._btn_mode.clicked.connect(self._toggle_mode_clicked)
        banner_layout.addWidget(self._btn_mode)

        self._btn_diag = QPushButton("诊断/修复", self._banner_frame)
        self._btn_diag.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 1px 8px; border: 1px solid #cbd5e1; border-radius: 3px; background: #ffffff; color: #b45309; }"
            "QPushButton:hover { background: #fef3c7; }"
        )
        self._btn_diag.setToolTip("查看高保真预览不可用的具体原因，并按运行形态修复")
        self._btn_diag.clicked.connect(self._open_diagnostic)
        self._btn_diag.setVisible(False)
        banner_layout.addWidget(self._btn_diag)

        layout.addWidget(self._banner_frame)

        # 堆叠视图
        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, stretch=1)

    def _init_browsers(self) -> None:
        # 1. 尝试按需初始化 QWebEngine
        try:
            from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser
            self._fidelity_browser = WebPreviewBrowser(self._stack, editor_panel=self._editor_panel)
            self._fidelity_browser.anchorClicked.connect(self.anchorClicked)
            self._fidelity_browser.headingClicked.connect(self.headingClicked)
            self._fidelity_browser.mermaidEditRequested.connect(self.mermaidEditRequested)
            self._fidelity_browser.mermaidViewRequested.connect(self.mermaidViewRequested)
            self._fidelity_browser.mermaidLocateRequested.connect(self.mermaidLocateRequested)
            self._fidelity_browser.loadStatusChanged.connect(self._on_fidelity_load_status)
            self._fidelity_browser.renderProcessCrashed.connect(self._on_fidelity_crashed)
            self._stack.addWidget(self._fidelity_browser)
            self._fidelity_available = True
        except Exception as exc:
            logger.warning("QWebEngine unavailable for fidelity preview: %s", exc)
            self._fidelity_error_text = "{0}: {1}".format(type(exc).__name__, exc)
            self._fidelity_error_traceback = traceback.format_exc()
            self._fidelity_available = False
            self._fidelity_browser = None

        # 2. 初始化原生轻量 QTextBrowser
        self._light_browser = _PreviewBrowser(self._stack, editor_panel=self._editor_panel)
        self._light_browser.setReadOnly(True)
        self._light_browser.setOpenExternalLinks(False)
        self._light_browser.anchorClicked.connect(self.anchorClicked)
        self._stack.addWidget(self._light_browser)

        # 3. 初始模式判定
        if self._fidelity_available:
            self._mode = PreviewMode.FIDELITY
            self._stack.setCurrentWidget(self._fidelity_browser)
            self._update_banner_ui()
        else:
            self._mode = PreviewMode.LIGHTWEIGHT
            self._stack.setCurrentWidget(self._light_browser)
            self._lbl_status.setText(
                "高保真组件不可用，已自动启用轻量近似模式（点「诊断/修复」查看原因）"
            )
            self._update_banner_ui()

    def _update_banner_ui(self) -> None:
        if self._mode == PreviewMode.FIDELITY:
            self._lbl_mode.setText("模式: 高保真阅读")
            self._lbl_mode.setToolTip(
                "高保真 Markdown 阅读预览（支持 CommonMark 嵌套列表/表格对齐/官方 Mermaid；非 Word 分页排版）"
            )
            self._btn_mode.setText("切换轻量模式")
            self._btn_mode.setEnabled(True)
        else:
            self._lbl_mode.setText("模式: 轻量预览 (近似)")
            self._lbl_mode.setToolTip(
                "轻量原生预览（快速排版与图片占位；非 Word 分页排版）"
            )
            self._btn_mode.setText("切换高保真" if self._fidelity_available else "高保真不可用")
            self._btn_mode.setEnabled(self._fidelity_available)
        self._btn_diag.setVisible(not self._fidelity_available)

    def _toggle_mode_clicked(self) -> None:
        if not self._fidelity_available:
            return
        new_mode = (
            PreviewMode.LIGHTWEIGHT
            if self._mode == PreviewMode.FIDELITY
            else PreviewMode.FIDELITY
        )
        self.set_mode(new_mode)

    def set_mode(self, mode: Union[PreviewMode, str]) -> None:
        """切换预览模式（保证不修改正文缓冲、不触发保存、不污染撤销记录）。"""
        target_mode = PreviewMode(mode) if isinstance(mode, str) else mode
        if target_mode == PreviewMode.FIDELITY and not self._fidelity_available:
            logger.info("Cannot switch to fidelity mode: WebEngine unavailable")
            target_mode = PreviewMode.LIGHTWEIGHT

        if self._mode != target_mode:
            self._mode = target_mode
            if self._mode == PreviewMode.FIDELITY:
                self._stack.setCurrentWidget(self._fidelity_browser)
            else:
                self._stack.setCurrentWidget(self._light_browser)

            self._update_banner_ui()
            self.modeChanged.emit(self._mode.value)
            # 以当前缓冲无缝刷新新视图
            if self._current_text:
                self._render_active_view(self._current_text, self._current_base_url, self._current_snapshot)

    def mode(self) -> PreviewMode:
        return self._mode

    def is_fidelity_available(self) -> bool:
        return self._fidelity_available

    def fidelity_error_text(self) -> str:
        """最近一次高保真初始化失败的原因（空串表示未失败）。"""
        return self._fidelity_error_text

    def _open_diagnostic(self) -> None:
        """打开诊断弹窗：展示原因、逐项检查与按运行形态的修复入口。"""
        from doc_tool.ui.fidelity_diagnostic_dialog import FidelityDiagnosticDialog

        dialog = FidelityDiagnosticDialog(
            self.window(),
            error_text=self._fidelity_error_text,
            traceback_text=self._fidelity_error_traceback,
        )
        dialog.exec()

    def _on_fidelity_load_status(self, ok: bool, message: str) -> None:
        if not ok:
            logger.error("Fidelity preview load failure: %s", message)
            self._lbl_status.setText(f"高保真加载失败（{message}），已降级至轻量预览")
            self.set_mode(PreviewMode.LIGHTWEIGHT)
        else:
            if not self._lbl_status.text().startswith("高保真已崩溃"):
                self._lbl_status.setText("")

    def _on_fidelity_crashed(self, err_msg: str) -> None:
        self._crash_count += 1
        logger.error("Fidelity browser crashed (count=%d): %s", self._crash_count, err_msg)
        self._lbl_status.setText("高保真引擎已崩溃退出，已自动安全降级至轻量预览")
        self.set_mode(PreviewMode.LIGHTWEIGHT)

    def update_content(
        self,
        text: str,
        base_url: Optional[QUrl] = None,
        snapshot: Optional[PreviewSnapshot] = None,
    ) -> None:
        """接收来自编辑器的最新正文更新并分发到活跃视图。"""
        self._current_text = text
        self._current_base_url = base_url or QUrl()
        self._current_snapshot = snapshot
        self._render_active_view(text, self._current_base_url, snapshot)

    def _render_active_view(
        self,
        text: str,
        base_url: QUrl,
        snapshot: Optional[PreviewSnapshot] = None,
    ) -> None:
        # 同时更新轻量文档以保持现有测试及兼容接口一致（REQ-ED-01）
        from doc_tool.application.content.preview import render_markdown_html
        html = render_markdown_html(text)
        if self._light_browser:
            self._light_browser.document().setBaseUrl(base_url)
            self._light_browser.setHtml(html)
            self._light_browser.adjust_images()

        # 如果当前在高保真模式，分发给 WebEngine 页面
        if self._mode == PreviewMode.FIDELITY and self._fidelity_browser:
            self._fidelity_browser.set_markdown(text, base_url.toString(), snapshot)

    # 兼容现有 EditorPanel 和外部调用的既有接口
    def document(self) -> QTextDocument:
        if self._mode == PreviewMode.LIGHTWEIGHT or not self._fidelity_browser:
            return self._light_browser.document()
        return self._fidelity_browser.document()

    def horizontalScrollBar(self):
        if self._mode == PreviewMode.LIGHTWEIGHT or not self._fidelity_browser:
            return self._light_browser.horizontalScrollBar()
        if hasattr(self._fidelity_browser, "horizontalScrollBar"):
            return self._fidelity_browser.horizontalScrollBar()
        return self._light_browser.horizontalScrollBar()

    def verticalScrollBar(self):
        if self._mode == PreviewMode.LIGHTWEIGHT or not self._fidelity_browser:
            return self._light_browser.verticalScrollBar()
        if hasattr(self._fidelity_browser, "verticalScrollBar"):
            return self._fidelity_browser.verticalScrollBar()
        return self._light_browser.verticalScrollBar()

    def toPlainText(self) -> str:
        if self._light_browser:
            return self._light_browser.toPlainText()
        if self._fidelity_browser and getattr(self._fidelity_browser, "_compat_doc", None):
            return self._fidelity_browser._compat_doc.toPlainText()
        return ""

    def viewport(self) -> QWidget:
        if self._mode == PreviewMode.LIGHTWEIGHT or not self._fidelity_browser:
            return self._light_browser.viewport()
        return self._fidelity_browser.viewport()

    def adjust_images(self) -> None:
        if self._light_browser:
            self._light_browser.adjust_images()

    def scrollToAnchor(self, anchor: str) -> None:
        if self._mode == PreviewMode.FIDELITY and self._fidelity_browser:
            self._fidelity_browser.scrollToAnchor(anchor)
        elif self._light_browser:
            self._light_browser.scrollToAnchor(anchor)

    def scroll_to_heading(self, heading_text: str) -> None:
        if self._mode == PreviewMode.FIDELITY and self._fidelity_browser:
            self._fidelity_browser.scroll_to_heading(heading_text)
        elif self._light_browser:
            cursor = self._light_browser.document().find(heading_text)
            if not cursor.isNull():
                self._light_browser.setTextCursor(cursor)
                self._light_browser.ensureCursorVisible()

    def set_dark(self, dark: bool) -> None:
        self._is_dark = dark
        if self._fidelity_browser:
            self._fidelity_browser.set_dark(dark)

    def setReadOnly(self, val: bool) -> None:
        if self._light_browser:
            self._light_browser.setReadOnly(val)
        if self._fidelity_browser:
            self._fidelity_browser.setReadOnly(val)

    def setOpenExternalLinks(self, val: bool) -> None:
        if self._light_browser:
            self._light_browser.setOpenExternalLinks(val)
        if self._fidelity_browser:
            self._fidelity_browser.setOpenExternalLinks(val)

    def setTextCursor(self, cursor: QTextCursor) -> None:
        if self._light_browser:
            self._light_browser.setTextCursor(cursor)
        if self._fidelity_browser:
            self._fidelity_browser.setTextCursor(cursor)

    def ensureCursorVisible(self) -> None:
        if self._light_browser:
            self._light_browser.ensureCursorVisible()

    def moveCursor(self, operation: QTextCursor.MoveOperation) -> None:
        if self._light_browser:
            self._light_browser.moveCursor(operation)

    def set_editor_panel(self, panel) -> None:
        self._editor_panel = panel
        if self._light_browser:
            self._light_browser.set_editor_panel(panel)
        if self._fidelity_browser:
            self._fidelity_browser._editor_panel = panel

    def scroll_to_line(self, line_no: int) -> None:
        """双向滚动联动（REQ-MD-06）。"""
        if self._mode == PreviewMode.FIDELITY and hasattr(self._active_browser, "scroll_to_line"):
            self._active_browser.scroll_to_line(line_no)
        elif self._mode == PreviewMode.LIGHTWEIGHT and hasattr(self._active_browser, "scrollToAnchor"):
            self._active_browser.scrollToAnchor(f"line-{line_no}")

    def cleanup(self) -> None:
        """安全释放适配器与底层浏览器资源（REQ-MD-07）。"""
        self._current_text = ""
        self._current_snapshot = None
        if self._fidelity_browser and hasattr(self._fidelity_browser, "cleanup"):
            self._fidelity_browser.cleanup()

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
