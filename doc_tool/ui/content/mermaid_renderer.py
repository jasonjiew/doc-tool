# -*- coding: utf-8 -*-
"""官方 Mermaid 桌面高保真渲染服务（REQ-MM-01～REQ-MM-06）。

复用随包自带的 Mermaid 11.16.1 与 QWebEngine 运行时，
为编辑器预览、工作台（MermaidDialog）、大图查看（DiagramViewerDialog）与桌面无 Node 导出
提供完全统一的官方语法校验、矢量 SVG 渲染及高保真 PNG 栅格捕获能力。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QObject, QRect, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from doc_tool.application.content.mermaid import MermaidError, RenderResult

logger = logging.getLogger(__name__)

_GLOBAL_RENDERER: Optional["OfficialMermaidRenderer"] = None


class _MermaidWorkerBridge(QObject):
    def __init__(self, renderer: "OfficialMermaidRenderer") -> None:
        super().__init__()
        self._renderer = renderer

    @Slot(str)
    def onRenderComplete(self, result_json: str) -> None:
        self._renderer._on_js_complete(result_json)


class OfficialMermaidRenderer:
    MERMAID_VERSION = "11.16.1"

    def get_engine_version(self) -> str:
        return self.MERMAID_VERSION

    """官方 Mermaid 渲染器（单例工作页面）。"""

    def __init__(self) -> None:
        self._view = QWebEngineView()
        self._page_ready = False
        self._last_result: Optional[Dict[str, Any]] = None
        self._loop: Optional[QEventLoop] = None

        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self._bridge = _MermaidWorkerBridge(self)
        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("mermaidWorkerBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)

        self._view.loadFinished.connect(self._on_load_finished)
        self._view.resize(1024, 768)

        # 加载离线 preview.html
        from doc_tool.resources import resource_path
        try:
            tpl = resource_path("web_preview", "preview.html")
            if Path(tpl).exists():
                self._view.load(QUrl.fromLocalFile(tpl))
            else:
                raise FileNotFoundError(tpl)
        except Exception:
            tpl_path = Path(__file__).resolve().parent.parent.parent / "resources" / "web_preview" / "preview.html"
            self._view.load(QUrl.fromLocalFile(str(tpl_path)))

        # 等待页面初始化就绪
        if not self._page_ready:
            loop = QEventLoop()
            self._view.loadFinished.connect(lambda ok: loop.quit())
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

    def _on_load_finished(self, ok: bool) -> None:
        self._page_ready = ok

    def _on_js_complete(self, result_json: str) -> None:
        try:
            self._last_result = json.loads(result_json)
        except Exception as exc:
            self._last_result = {"ok": False, "error": f"JSON解析错误: {exc}"}
        if self._loop and self._loop.isRunning():
            self._loop.quit()

    def render(
        self,
        source: str,
        *,
        want_png: bool = True,
        scale: float = 2.0,
        theme: str = "default",
    ) -> RenderResult:
        """使用官方 Mermaid 引擎渲染源码，输出 SVG 与高质量 PNG。"""
        if not self._page_ready:
            return RenderResult(False, error="官方渲染引擎页面未就绪", backend="official-webengine")

        source_clean = source.strip()
        if not source_clean:
            return RenderResult(False, error="Mermaid 源码为空", backend="official-webengine")

        js_script = f"""
        new QWebChannel(qt.webChannelTransport, async function(ch) {{
            const bridge = ch.objects.mermaidWorkerBridge;
            try {{
                if (typeof mermaid === 'undefined') {{
                    bridge.onRenderComplete(JSON.stringify({{ ok: false, error: 'Mermaid 运行库未加载' }}));
                    return;
                }}
                mermaid.initialize({{
                    startOnLoad: false,
                    theme: {json.dumps(theme)},
                    securityLevel: 'loose',
                    htmlLabels: false,
                    flowchart: {{ htmlLabels: false }}
                }});
                const id = 'render_worker_' + Math.random().toString(36).substr(2, 9);
                const {{ svg }} = await mermaid.render(id, {json.dumps(source_clean)});
                
                let container = document.getElementById('render-worker-container');
                if (!container) {{
                    container = document.createElement('div');
                    container.id = 'render-worker-container';
                    container.style.position = 'fixed';
                    container.style.top = '0';
                    container.style.left = '0';
                    container.style.zIndex = '99999';
                    container.style.background = {json.dumps('#1e1f26' if theme == 'dark' else '#ffffff')};
                    container.style.padding = '0';
                    container.style.margin = '0';
                    document.body.appendChild(container);
                }}
                container.innerHTML = svg;
                const svgEl = container.querySelector('svg');
                const bbox = svgEl.getBoundingClientRect();
                bridge.onRenderComplete(JSON.stringify({{
                    ok: true,
                    svg: svg,
                    width: Math.ceil(bbox.width) || 400,
                    height: Math.ceil(bbox.height) || 300,
                    hasForeignObject: svg.indexOf('<foreignObject') !== -1
                }}));
            }} catch (err) {{
                bridge.onRenderComplete(JSON.stringify({{
                    ok: false,
                    error: String(err && err.message ? err.message : err)
                }}));
            }}
        }});
        """

        self._last_result = None
        self._loop = QEventLoop()
        self._view.page().runJavaScript(js_script)
        QTimer.singleShot(8000, self._loop.quit)
        self._loop.exec()

        if not self._last_result:
            return RenderResult(False, error="官方渲染超时无响应", backend="official-webengine")

        if not self._last_result.get("ok"):
            err_msg = self._last_result.get("error", "未知渲染错误")
            return RenderResult(False, error=err_msg, backend="official-webengine")

        svg_str = self._last_result.get("svg", "")
        width = int(self._last_result.get("width", 400))
        height = int(self._last_result.get("height", 300))
        svg_bytes = svg_str.encode("utf-8")

        png_bytes: Optional[bytes] = None
        if want_png:
            # 浏览器视口精确裁切捕获（保留外国对象、CSS样式与字体渲染）
            target_w = max(width, 100)
            target_h = max(height, 100)
            self._view.resize(target_w, target_h)

            loop_frame = QEventLoop()
            QTimer.singleShot(250, loop_frame.quit)
            loop_frame.exec()

            pixmap = self._view.grab(QRect(0, 0, target_w, target_h))
            if not pixmap.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "PNG")
                png_bytes = bytes(buffer.data().data())

        return RenderResult(
            ok=True,
            svg=svg_bytes,
            png=png_bytes,
            width=width,
            height=height,
            backend="official-webengine",
            error=None,
        )

    def validate(self, source: str) -> List[MermaidError]:
        """使用官方语法解析器检验源码（REQ-MM-01）。"""
        if not self._page_ready:
            return []

        js_script = f"""
        new QWebChannel(qt.webChannelTransport, async function(ch) {{
            const bridge = ch.objects.mermaidWorkerBridge;
            try {{
                await mermaid.parse({json.dumps(source)});
                bridge.onRenderComplete(JSON.stringify({{ ok: true }}));
            }} catch (err) {{
                bridge.onRenderComplete(JSON.stringify({{
                    ok: false,
                    error: String(err && err.message ? err.message : err)
                }}));
            }}
        }});
        """
        self._last_result = None
        self._loop = QEventLoop()
        self._view.page().runJavaScript(js_script)
        QTimer.singleShot(4000, self._loop.quit)
        self._loop.exec()

        if self._last_result and not self._last_result.get("ok"):
            err_msg = self._last_result.get("error", "语法错误")
            line_no = 1
            m = re.search(r"line\s+(\d+)", err_msg, re.IGNORECASE)
            if m:
                line_no = int(m.group(1))
            return [MermaidError(line_no, err_msg)]
        return []


def get_official_mermaid_renderer() -> OfficialMermaidRenderer:
    """获取官方 Mermaid 渲染器单例。"""
    global _GLOBAL_RENDERER
    if _GLOBAL_RENDERER is None:
        _GLOBAL_RENDERER = OfficialMermaidRenderer()
    return _GLOBAL_RENDERER

def _cleanup_global_renderer():
    global _GLOBAL_RENDERER
    if _GLOBAL_RENDERER is not None:
        try:
            r = _GLOBAL_RENDERER
            _GLOBAL_RENDERER = None
            if hasattr(r, "_view") and r._view:
                p = r._view.page()
                r._view.setPage(None)
                if p:
                    p.deleteLater()
                r._view.deleteLater()
                app = QApplication.instance()
                if app:
                    app.sendPostedEvents()
                    app.processEvents()
        except Exception:
            pass

import atexit
atexit.register(_cleanup_global_renderer)
