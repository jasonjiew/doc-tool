# -*- coding: utf-8 -*-
"""现代 QWebEngineView 的 Markdown + Mermaid 实时预览器。

使用工业级 marked.js + 官方 mermaid.min.js 进行矢量异步渲染，
主线程 0 阻塞卡顿、100% 官方 Mermaid 全图表语法支持、支持平移抓手与无级缩放。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextDocument
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class _WebPreviewPage(QWebEnginePage):
    """拦截 Console 消息与超链接的双向通信页面。"""

    anchor_clicked = Signal(QUrl)
    mermaid_edit_requested = Signal(str)
    mermaid_view_requested = Signal(str)
    heading_clicked = Signal(str)
    mermaid_locate_requested = Signal(str)

    def javaScriptConsoleMessage(self, level, message: str, line_no: int, source_id: str) -> None:
        if message.startswith("DOC_TOOL:anchor:"):
            line_str = message[len("DOC_TOOL:anchor:"):]
            self.anchor_clicked.emit(QUrl(f"line-{line_str}"))
        elif message.startswith("DOC_TOOL:mermaid-edit:"):
            source_encoded = message[len("DOC_TOOL:mermaid-edit:"):]
            source_decoded = urllib.parse.unquote(source_encoded)
            self.mermaid_edit_requested.emit(source_decoded)
        elif message.startswith("DOC_TOOL:mermaid-view:"):
            payload_encoded = message[len("DOC_TOOL:mermaid-view:"):]
            payload_decoded = urllib.parse.unquote(payload_encoded)
            self.mermaid_view_requested.emit(payload_decoded)
        elif message.startswith("DOC_TOOL:heading-click:"):
            heading_encoded = message[len("DOC_TOOL:heading-click:"):]
            heading_text = urllib.parse.unquote(heading_encoded)
            self.heading_clicked.emit(heading_text)
        elif message.startswith("DOC_TOOL:mermaid-locate:"):
            source_encoded = message[len("DOC_TOOL:mermaid-locate:"):]
            source_decoded = urllib.parse.unquote(source_encoded)
            self.mermaid_locate_requested.emit(source_decoded)
        elif message.startswith("DOC_TOOL:external:"):
            url_str = message[len("DOC_TOOL:external:"):]
            QDesktopServices.openUrl(QUrl(url_str))
        super().javaScriptConsoleMessage(level, message, line_no, source_id)


class _CompatTextDocument(QTextDocument):
    """兼容旧 QTextBrowser 桩的文本模型。"""

    def idealWidth(self) -> float:
        parent = self.parent()
        vp_w = parent.viewport().width() if parent and hasattr(parent, "viewport") else 380
        real_ideal = super().idealWidth()
        if real_ideal > vp_w:
            return float(vp_w)
        return real_ideal


class WebPreviewBrowser(QWebEngineView):
    """现代化 Markdown + Mermaid 全矢量实时预览控件。"""

    anchorClicked = Signal(QUrl)
    mermaidEditRequested = Signal(str)
    mermaidViewRequested = Signal(str)
    headingClicked = Signal(str)
    mermaidLocateRequested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None, editor_panel=None) -> None:
        super().__init__(parent)
        self._editor_panel = editor_panel
        self._dark = False
        self._page_ready = False
        self._pending_markdown: Optional[str] = None
        self._pending_base_url: str = ""
        self._last_heading: Optional[str] = None
        self._compat_doc: Optional[QTextDocument] = None
        self._compat_cursor: Optional[QTextCursor] = None

        # 设置必要安全权限
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self._custom_page = _WebPreviewPage(self)
        self._custom_page.anchor_clicked.connect(self.anchorClicked)
        self._custom_page.mermaid_edit_requested.connect(self._on_mermaid_edit_requested)
        self._custom_page.mermaid_view_requested.connect(self._on_mermaid_view_requested)
        self._custom_page.heading_clicked.connect(self._on_heading_clicked)
        self._custom_page.mermaid_locate_requested.connect(self._on_mermaid_locate_requested)
        self.setPage(self._custom_page)

        self.loadFinished.connect(self._on_load_finished)
        self._load_template()

    def _load_template(self) -> None:
        try:
            from doc_tool.resources import resource_path
            template_file = resource_path("web_preview", "preview.html")
            if os.path.isfile(template_file):
                self.load(QUrl.fromLocalFile(template_file))
                return
        except Exception:
            pass
        template_path = Path(__file__).resolve().parent.parent.parent / "resources" / "web_preview" / "preview.html"
        if template_path.exists():
            self.load(QUrl.fromLocalFile(str(template_path)))

    def _on_load_finished(self, ok: bool) -> None:
        self._page_ready = ok
        if not ok:
            logger.error("WebPreviewBrowser failed to load HTML preview template")
            return
        if self._pending_markdown is not None:
            text = self._pending_markdown
            base_url = self._pending_base_url
            self._pending_markdown = None
            self.set_markdown(text, base_url)

    def set_markdown(self, text: str, base_url: str = "") -> None:
        """异步将 Markdown 文本分发至前端渲染（主线程 0 阻塞）。"""
        self._last_heading = None
        if self._compat_doc is None:
            self._compat_doc = _CompatTextDocument(self)
        self._compat_doc.setPlainText(text)

        if hasattr(base_url, "toString"):
            base_url_str = base_url.toString()
        elif isinstance(base_url, Path):
            base_url_str = base_url.as_uri()
        else:
            base_url_str = str(base_url) if base_url else ""

        if not self._page_ready:
            self._pending_markdown = text
            self._pending_base_url = base_url_str
            return

        js_text = json.dumps(text)
        js_dark = "true" if self._dark else "false"
        js_base = json.dumps(base_url_str)
        js_call = f"""
        (() => {{
            let retries = 0;
            function _apply() {{
                if (typeof window.updateMarkdown === 'function') {{
                    window.updateMarkdown({js_text}, {js_dark}, {js_base});
                }} else if (retries < 30) {{
                    retries++;
                    setTimeout(_apply, 30);
                }}
            }}
            _apply();
        }})();
        """
        self.page().runJavaScript(js_call)

    def set_dark(self, dark: bool) -> None:
        """切换深色/浅色主题。"""
        if self._dark != dark:
            self._dark = dark
            if self._page_ready:
                js_dark = "true" if dark else "false"
                self.page().runJavaScript(f"if (typeof window.updateMarkdown === 'function') window.updateMarkdown(undefined, {js_dark});")

    def scrollToAnchor(self, anchor: str) -> None:
        """平滑滚动至锚点。"""
        if self._page_ready and anchor:
            anchor_clean = anchor.lstrip("#")
            js_anchor = json.dumps(anchor_clean)
            js_call = f"""
            (() => {{
                const id = {js_anchor};
                const el = document.getElementById(id) || document.querySelector('[name="' + id.replace(/"/g, '\\"') + '"]');
                if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
            }})();
            """
            self.page().runJavaScript(js_call)

    def scroll_to_heading(self, heading_text: str) -> None:
        """滚动至指定文本的标题（带节流去重）。"""
        if self._page_ready and heading_text:
            if getattr(self, "_last_heading", None) == heading_text:
                return
            self._last_heading = heading_text
            js = f"""
            (() => {{
                const headers = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                const target = headers.find(h => h.textContent.includes({json.dumps(heading_text)}));
                if (target) target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
            }})();
            """
            self.page().runJavaScript(js)

    # 兼容 QTextBrowser 的接口桩
    def viewport(self) -> QWidget:
        return self

    def document(self) -> QTextDocument:
        if self._compat_doc is None:
            self._compat_doc = _CompatTextDocument(self)
        vp_w = self.viewport().width() if hasattr(self, "viewport") and self.viewport() else 400
        self._compat_doc.setTextWidth(max(10, vp_w - 20))
        return self._compat_doc

    def setTextCursor(self, cursor: QTextCursor) -> None:
        self._compat_cursor = cursor

    def ensureCursorVisible(self) -> None:
        pass

    def textCursor(self) -> QTextCursor:
        if self._compat_cursor:
            return self._compat_cursor
        return QTextCursor(self.document())

    def horizontalScrollBar(self):
        class _FakeScrollBar:
            def maximum(self) -> int:
                return 0
            def value(self) -> int:
                return 0
            def setValue(self, v: int) -> None:
                pass
        return _FakeScrollBar()

    def setReadOnly(self, val: bool) -> None:
        pass

    def setOpenExternalLinks(self, val: bool) -> None:
        pass

    def adjust_images(self) -> None:
        pass

    def _on_heading_clicked(self, heading_text: str) -> None:
        self.headingClicked.emit(heading_text)
        if self._editor_panel and hasattr(self._editor_panel, "jump_to_heading"):
            self._editor_panel.jump_to_heading(heading_text)

    def _on_mermaid_locate_requested(self, source: str) -> None:
        self.mermaidLocateRequested.emit(source)
        if self._editor_panel and hasattr(self._editor_panel, "locate_mermaid_source"):
            self._editor_panel.locate_mermaid_source(source)

    def _on_mermaid_edit_requested(self, source: str) -> None:
        self.mermaidEditRequested.emit(source)
        if self._editor_panel and hasattr(self._editor_panel, "open_mermaid_workbench"):
            self._editor_panel.open_mermaid_workbench(source)

    def _on_mermaid_view_requested(self, payload: str) -> None:
        source = payload
        svg_content = ""
        try:
            data = json.loads(payload)
            if isinstance(data, dict):
                source = data.get("source", payload)
                svg_content = data.get("svg", "")
        except Exception:
            pass

        self.mermaidViewRequested.emit(source)
        try:
            from PySide6.QtGui import QPixmap
            from doc_tool.ui.content.diagram_viewer import DiagramViewerDialog

            pix: Optional[QPixmap] = None

            # 1. 优先使用已渲染的高精矢量 SVG（毫秒级，无子进程）
            if svg_content:
                try:
                    from PySide6.QtCore import QByteArray
                    from PySide6.QtGui import QImage, QPainter
                    from PySide6.QtSvg import QSvgRenderer

                    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
                    if renderer.isValid():
                        sz = renderer.defaultSize()
                        w = sz.width() if sz.width() > 0 else 800
                        h = sz.height() if sz.height() > 0 else 600
                        scale = 2.0
                        img = QImage(max(100, int(w * scale)), max(100, int(h * scale)), QImage.Format.Format_ARGB32)
                        img.fill(0xFFFFFFFF)
                        p = QPainter(img)
                        renderer.render(p)
                        p.end()
                        pix = QPixmap.fromImage(img)
                except Exception as exc:
                    logger.debug("Failed to render SVG via QSvgRenderer: %s", exc)

            # 2. 降级：调用内置渲染引擎（先用快速内置引擎，失败再走 CLI）
            if pix is None or pix.isNull():
                from doc_tool.application.content.mermaid import render

                res = render(source, use_cli=False)
                if not res.ok:
                    res = render(source, use_cli=True)
                if res.ok and (res.png or res.svg):
                    pix = QPixmap()
                    if res.png:
                        pix.loadFromData(res.png, "PNG")
                    elif res.svg:
                        pix.loadFromData(res.svg, "SVG")

            if pix is not None and not pix.isNull():
                def do_edit():
                    if self._editor_panel and hasattr(self._editor_panel, "open_mermaid_workbench"):
                        self._editor_panel.open_mermaid_workbench(source)

                dialog = DiagramViewerDialog(
                    pixmap=pix,
                    parent=self.window(),
                    title="Mermaid 架构大图查看器",
                    mermaid_source=source,
                    on_edit_source=do_edit,
                )
                dialog.exec()
            else:
                logger.warning("Unable to generate pixmap for mermaid diagram: %s", source[:50])
        except Exception as exc:
            logger.warning("Failed to open DiagramViewerDialog: %s", exc)
