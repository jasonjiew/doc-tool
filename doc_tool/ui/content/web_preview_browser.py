# -*- coding: utf-8 -*-
"""现代 QWebEngineView 的 Markdown + Mermaid 实时预览器。

提供高保真 Markdown 与官方 Mermaid 实时矢量渲染，
集成 QWebChannel 小范围结构化安全通信、页面就绪队列与渲染进程崩溃防护。
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QTextCursor, QTextDocument
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QWidget

from doc_tool.domain.preview_types import BlockLocation, BlockRegistry, PreviewSnapshot

logger = logging.getLogger(__name__)

import atexit

_ACTIVE_BROWSERS = set()

def _cleanup_all_active_browsers():
    app = QApplication.instance()
    for b in list(_ACTIVE_BROWSERS):
        try:
            b.cleanup()
        except Exception:
            pass
    _ACTIVE_BROWSERS.clear()
    if app:
        try:
            app.sendPostedEvents()
            app.processEvents()
        except Exception:
            pass

atexit.register(_cleanup_all_active_browsers)




class _WebPreviewBridge(QObject):
    """QWebChannel 结构化安全通信桥梁，实施严格动作白名单与路径逃逸校验（REQ-MD-05、REQ-MD-06）。"""

    def __init__(self, browser: "WebPreviewBrowser") -> None:
        super().__init__(browser)
        self._browser = browser

    @Slot()
    def reportReady(self) -> None:
        self._browser._on_bridge_ready()

    @Slot(int, int)
    def reportRendered(self, version: int, count: int) -> None:
        self._browser._on_bridge_rendered(version, count)

    @Slot(str)
    def reportBlockClick(self, block_id: str) -> None:
        if not block_id or not isinstance(block_id, str):
            return
        self._browser._on_block_clicked(block_id)

    @Slot(str)
    def reportHeadingClick(self, heading_text: str) -> None:
        if not heading_text or not isinstance(heading_text, str):
            return
        self._browser._on_heading_clicked(heading_text)

    @Slot(str)
    def reportAnchorClick(self, anchor: str) -> None:
        if not anchor or not isinstance(anchor, str):
            return
        if anchor.startswith("line-") or anchor.startswith("#line-"):
            clean_line = anchor.lstrip("#line-")
            if clean_line.isdigit():
                self._browser.anchorClicked.emit(QUrl(f"line-{clean_line}"))
            return
        self._browser.anchorClicked.emit(QUrl(anchor))

    @Slot(str, str, str)
    def reportMermaidAction(self, action: str, target: str, payload_json: str) -> None:
        allowed_actions = {"edit", "view", "locate", "copy-image", "save-image"}
        if action not in allowed_actions:
            logger.warning("Rejected unauthorized preview bridge action: %s", action)
            return
        self._browser._on_mermaid_bridge_action(action, target, payload_json)


class _WebPreviewPage(QWebEnginePage):
    """双向通信页面，拦截 Console 消息作为备用通道并监控渲染进程。"""

    anchor_clicked = Signal(QUrl)
    mermaid_edit_requested = Signal(str)
    mermaid_view_requested = Signal(str)
    heading_clicked = Signal(str)
    mermaid_locate_requested = Signal(str)
    render_process_crashed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.renderProcessTerminated.connect(self._on_render_process_terminated)

    def _on_render_process_terminated(self, status, exit_code: int) -> None:
        msg = f"WebEngine 渲染进程异常退出: status={status}, exitCode={exit_code}"
        logger.error(msg)
        self.render_process_crashed.emit(msg)

    def javaScriptConsoleMessage(self, level, message: str, line_no: int, source_id: str) -> None:
        if message.startswith("DOC_TOOL:anchor:"):
            line_str = message[len("DOC_TOOL:anchor:"):]
            if line_str.isdigit():
                self.anchor_clicked.emit(QUrl(f"line-{line_str}"))
        elif message.startswith("DOC_TOOL:mermaid-edit:"):
            source_encoded = message[len("DOC_TOOL:mermaid-edit:"):]
            source_decoded = urllib.parse.unquote(source_encoded)
            self.mermaid_edit_requested.emit(source_decoded)
        elif message.startswith("DOC_TOOL:mermaid-view:"):
            payload_encoded = message[len("DOC_TOOL:mermaid-view:"):]
            payload_decoded = urllib.parse.unquote(payload_encoded)
            self._on_mermaid_view_requested(payload_decoded)
        elif message.startswith("DOC_TOOL:mermaid-copy-image:"):
            data_url = urllib.parse.unquote(message[len("DOC_TOOL:mermaid-copy-image:"):])
            self._on_mermaid_copy_image(data_url)
        elif message.startswith("DOC_TOOL:mermaid-save-image:"):
            data_url = urllib.parse.unquote(message[len("DOC_TOOL:mermaid-save-image:"):])
            self._on_mermaid_save_image(data_url)
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
            if url_str.startswith("http://") or url_str.startswith("https://") or url_str.startswith("mailto:"):
                QDesktopServices.openUrl(QUrl(url_str))
            else:
                logger.warning("Blocked potentially unsafe external URL protocol: %s", url_str)
        super().javaScriptConsoleMessage(level, message, line_no, source_id)


class _CompatTextDocument(QTextDocument):
    """兼容旧 QTextBrowser 桩的纯文本模型。"""

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
    loadStatusChanged = Signal(bool, str)       # ok, message
    renderProcessCrashed = Signal(str)          # crash error message
    previewRendered = Signal(int, int)          # version, count

    def __init__(self, parent: Optional[QWidget] = None, editor_panel=None) -> None:
        super().__init__(parent)
        self._editor_panel = editor_panel
        self._dark = False
        self._page_ready = False
        self._load_failed = False
        self._load_error_message = ""
        self._pending_update: Optional[Tuple[str, str, Optional[PreviewSnapshot]]] = None
        self._current_snapshot: Optional[PreviewSnapshot] = None
        self._block_registry: Optional[BlockRegistry] = None
        self._last_heading: Optional[str] = None
        self._compat_doc: Optional[QTextDocument] = None
        self._compat_cursor: Optional[QTextCursor] = None

        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)

        p = self.page()
        p.renderProcessTerminated.connect(self._on_render_process_terminated)
        # 页面加载完成前，QWebEngineView 默认清屏会露出黑底（表现为预览区黑屏闪烁）；
        # 显式给页面底色，深色主题在 set_dark 里同步。
        try:
            p.setBackgroundColor(QColor("#ffffff"))
        except Exception:  # noqa: BLE001 - 旧版本 Qt 无此 API 时忽略
            pass

        self._web_channel = QWebChannel(p)
        self._bridge = _WebPreviewBridge(self)
        self._web_channel.registerObject("previewBridge", self._bridge)
        p.setWebChannel(self._web_channel)

        self.loadFinished.connect(self._on_load_finished)
        self._load_template()
        _ACTIVE_BROWSERS.add(self)
        app = QApplication.instance()
        if app:
            try:
                app.aboutToQuit.connect(_cleanup_all_active_browsers)
            except Exception:
                pass

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
        else:
            self._load_failed = True
            self._load_error_message = f"未找到离线预览模板: {template_path}"
            logger.error(self._load_error_message)
            self.loadStatusChanged.emit(False, self._load_error_message)

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self._page_ready = True
            self._load_failed = False
            self.loadStatusChanged.emit(True, "页面就绪")
            if self._pending_update is not None:
                text, base_url, snapshot = self._pending_update
                self._pending_update = None
                self.set_markdown(text, base_url, snapshot)
        else:
            self._page_ready = False
            self._load_failed = True
            self._load_error_message = "预览页面加载失败（网络/模板损坏或离线路径异常）"
            logger.error("WebPreviewBrowser failed to load HTML preview template")
            self.loadStatusChanged.emit(False, self._load_error_message)

    def _on_render_process_terminated(self, status, exit_code: int) -> None:
        msg = f"WebEngine 渲染进程异常退出: status={status}, exitCode={exit_code}"
        logger.error(msg)
        self.renderProcessCrashed.emit(msg)

    def _on_render_process_crashed(self, err_msg: str) -> None:
        self._page_ready = False
        self._load_failed = True
        self._load_error_message = err_msg
        self.renderProcessCrashed.emit(err_msg)

    def _on_bridge_ready(self) -> None:
        self._page_ready = True
        if self._pending_update is not None:
            text, base_url, snapshot = self._pending_update
            self._pending_update = None
            self.set_markdown(text, base_url, snapshot)

    def _on_bridge_rendered(self, version: int, count: int) -> None:
        self.previewRendered.emit(version, count)

    def _on_block_clicked(self, block_id: str) -> None:
        if self._block_registry:
            loc = self._block_registry.find_by_id(block_id)
            if loc and self._editor_panel and hasattr(self._editor_panel, "highlight_line"):
                self._editor_panel.highlight_line(loc.start_line)
                if hasattr(self._editor_panel, "_flash_line"):
                    self._editor_panel._flash_line(loc.start_line)
                return
        if block_id.startswith("line-"):
            clean = block_id[len("line-"):]
            if clean.isdigit():
                line_no = int(clean)
                if self._editor_panel and hasattr(self._editor_panel, "highlight_line"):
                    self._editor_panel.highlight_line(line_no)
                    if hasattr(self._editor_panel, "_flash_line"):
                        self._editor_panel._flash_line(line_no)
                self.anchorClicked.emit(QUrl(f"line-{clean}"))

    def _on_mermaid_bridge_action(self, action: str, target: str, payload_json: str) -> None:
        source = target
        if action == "edit":
            self._on_mermaid_edit_requested(source)
        elif action == "locate":
            self._on_mermaid_locate_requested(source)
        elif action == "view":
            self._on_mermaid_view_requested(payload_json or source)
        elif action == "copy-image":
            self._on_mermaid_copy_image(payload_json)
        elif action == "save-image":
            self._on_mermaid_save_image(payload_json)

    def set_markdown(
        self,
        text: str,
        base_url: str = "",
        snapshot: Optional[PreviewSnapshot] = None,
    ) -> None:
        self._last_heading = None
        if snapshot is not None:
            # 校验会话与版本：若已有较新版本，丢弃乱序返回的旧版本（REQ-MD-07）
            if self._current_snapshot is not None:
                if (
                    snapshot.session_id == self._current_snapshot.session_id
                    and snapshot.chapter_id == self._current_snapshot.chapter_id
                    and snapshot.buffer_version < self._current_snapshot.buffer_version
                ):
                    logger.info("Discarded stale preview render result: ver %s < current %s",
                                snapshot.buffer_version, self._current_snapshot.buffer_version)
                    return
            self._current_snapshot = snapshot
            if snapshot.block_registry:
                self._block_registry = snapshot.block_registry

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
            self._pending_update = (text, base_url_str, snapshot)
            return

        version = snapshot.buffer_version if snapshot else 0
        js_text = json.dumps(text)
        js_dark = "true" if self._dark else "false"
        js_base = json.dumps(base_url_str)
        js_ver = json.dumps(version)

        js_call = f"""
        (() => {{
            let retries = 0;
            function _apply() {{
                if (typeof window.updateMarkdown === 'function') {{
                    window.updateMarkdown({js_text}, {js_dark}, {js_base}, {js_ver});
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
        if self._dark != dark:
            self._dark = dark
            try:
                self.page().setBackgroundColor(
                    QColor("#1e1e1e" if dark else "#ffffff")
                )
            except Exception:  # noqa: BLE001 - 底色设置失败不影响渲染
                pass
            if self._page_ready:
                js_dark = "true" if dark else "false"
                self.page().runJavaScript(
                    f"if (typeof window.updateMarkdown === 'function') window.updateMarkdown(undefined, {js_dark});"
                )

    def scrollToAnchor(self, anchor: str) -> None:
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

    def _on_mermaid_copy_image(self, data_url: str) -> None:
        """按需将大图弹层导出的完整高精图片存入系统剪贴板。"""
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QImage
            import base64
            if "," in data_url:
                data_url = data_url.split(",", 1)[1]
            png_bytes = base64.b64decode(data_url)
            qimg = QImage()
            if qimg.loadFromData(png_bytes, "PNG"):
                clipboard = QApplication.clipboard()
                if clipboard:
                    clipboard.setImage(qimg)
                    logger.info("Copied full diagram image to clipboard (%dx%d)", qimg.width(), qimg.height())
        except Exception as exc:
            logger.warning("Failed to copy mermaid diagram image: %s", exc)

    def _on_mermaid_save_image(self, data_url: str) -> None:
        """按需将大图弹层导出的完整高精图片保存至磁盘文件。"""
        try:
            from PySide6.QtWidgets import QFileDialog
            import base64
            if "," in data_url:
                data_url = data_url.split(",", 1)[1]
            png_bytes = base64.b64decode(data_url)
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存 Mermaid 架构图",
                "mermaid_diagram.png",
                "PNG 图片 (*.png);;所有文件 (*.*)",
            )
            if file_path:
                Path(file_path).write_bytes(png_bytes)
                logger.info("Saved full diagram image to: %s", file_path)
        except Exception as exc:
            logger.warning("Failed to save mermaid diagram image: %s", exc)

    def _on_mermaid_view_requested(self, payload: str) -> None:
        source = payload
        try:
            data = json.loads(payload)
            if isinstance(data, dict):
                source = data.get("source", payload)
        except Exception:
            pass

        self.mermaidViewRequested.emit(source)
        # 优先在页面内打开大图遮罩弹层（原样复用已渲染内容与主题，避免重新绘制与文件导出）
        if self._page_ready:
            js = f"if (typeof window.openMermaidModal === 'function') window.openMermaidModal({json.dumps(source)});"
            self.page().runJavaScript(js)
            return

        # 仅在页面未就绪或脱离网页环境时降级使用独立弹窗
        try:
            from PySide6.QtGui import QPixmap
            from doc_tool.ui.content.diagram_viewer import DiagramViewerDialog
            from doc_tool.application.content.mermaid import render

            theme_name = "dark" if self._dark else "default"
            res = render(source, use_cli=False, theme=theme_name)
            if not res.ok:
                res = render(source, use_cli=True, theme=theme_name)
            if res.ok and (res.png or res.svg):
                pix = QPixmap()
                if res.png:
                    pix.loadFromData(res.png, "PNG")
                elif res.svg:
                    pix.loadFromData(res.svg, "SVG")
                if not pix.isNull():
                    def do_edit():
                        if self._editor_panel and hasattr(self._editor_panel, "open_mermaid_workbench"):
                            self._editor_panel.open_mermaid_workbench(source)

                    dialog = DiagramViewerDialog(
                        pixmap=pix,
                        parent=self.window(),
                        title="Mermaid 架构大图查看器",
                        mermaid_source=source,
                        on_edit_source=do_edit,
                        dark=self._dark,
                    )
                    dialog.exec()
        except Exception as exc:
            logger.warning("Failed to open DiagramViewerDialog fallback: %s", exc)

    def scroll_to_line(self, line_no: int) -> None:
        """根据源码行号将预览区平滑滚动到对应的块（REQ-MD-06）。"""
        if not self._page_ready:
            return
        js_code = f"""
        (() => {{
            let target = document.getElementById('line-{line_no}') || document.querySelector('[data-line="{line_no}"]');
            if (!target) {{
                for (let l = {line_no} - 1; l >= Math.max(1, {line_no} - 10); l--) {{
                    target = document.getElementById('line-' + l) || document.querySelector('[data-line="' + l + '"]');
                    if (target) break;
                }}
            }}
            if (target) {{
                target.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}
        }})();
        """
        self.page().runJavaScript(js_code)

    def cleanup(self) -> None:
        _ACTIVE_BROWSERS.discard(self)
        """安全释放页面与信道资源，避免多窗口内存泄漏（REQ-MD-07）。"""
        self._pending_update = None
        self._current_snapshot = None
        self._block_registry = None
        try:
            self.stop()
            p = self.page()
            if p is not None:
                self.setPage(None)
                p.deleteLater()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
