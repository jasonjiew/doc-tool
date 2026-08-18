# -*- coding: utf-8 -*-
"""官方 mermaid.js 经 QtWebEngine 渲染服务（实时预览专用）。

背景：DocTool 内置的 SVG 渲染器只覆盖 flowchart/sequenceDiagram 子集
（alt/else、loop、opt、par、Note、activate 等结构全部丢弃），与 mermaid
真实输出差距很大；mermaid-cli (mmdc) 是官方渲染但每屏阻塞 30s 起步，无法
用于每敲一字刷新的实时预览。这里折中：用同一进程内 QWebEngineView 载入
官方 mermaid.min.js，把用户源码经 runJavaScript 塞进 mermaid.render，
拿到 SVG 后在浏览器内 canvas 栅格化成 PNG，再回传 Python。

设计要点：
- 进程级单视图。首次初始化失败则永久禁用（_DISABLED），后续每次预览直
  接回退内置/CLI，避免反复重试阻塞 UI 线程；初始化成功则缓存复用，后续每次
  预览只跑一次 JS（典型 50~250ms）。
- 与 runJavaScript 的「是否自动等待 Promise」无关：所有轮询都查询同步 JS
  表达式（window.__cb_done === true），回调固定 QEventLoop 同步收结果；
  kick-off 阶段只 runJavaScript(无回调)，结果仍写在全局变量里。
- __cb_done / __cb_result 是渲染阶段槽；__cb_done2 / __cb_result2
  是栅格化阶段槽，互相不影响。
- 适配打包：DocTool.exe 故意 excludes 了 QtWebEngineCore/Widgets
  以控制体积；打包版下 find_spec 为 None -> web_available() 返回
  False，render_web 直接返回 None，行为退化为内置渲染器，不影响其它功能。
- 包装器永不抛异常给上层；需要原因时用 web_disabled_reason()。
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import re
import time
import os
from pathlib import Path
from typing import Optional

from doc_tool.application.content.mermaid import RenderResult, svg_to_png

# 进程级状态：渲染器单例、永久禁用标记。
_RENDERER: Optional["_WebMermaidEngine"] = None
_DISABLED: bool = False
_DISABLED_REASON: str = ""

def _env_disabled() -> bool:
    """DOCTOOL_MERMAID_WEB=0/false/no 时强制关闭 web 渲染（用于离屏测试环境）。"""
    return os.environ.get("DOCTOOL_MERMAID_WEB", "1").strip().lower() in ("0", "false", "no", "off")

# 浏览器端一次性脚本：装两个 proxy（渲染、栅格化），并把 mermaid 初始化成
# 安全等级 loose（允许节点标签含 / . 等特殊字符）+ 主题 default。
_INIT_JS = """
window.__installProxies = function () {
  if (window.__proxyInstalled) { return; }
  window.__proxyInstalled = true;
  try {
    if (window.mermaid && mermaid.initialize) {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'loose',
        theme: 'default'
      });
    }
  } catch (e) {}
  window.__cb_done = false;
  window.__cb_result = null;
  window.__cb_done2 = false;
  window.__cb_result2 = null;
  window.__renderMermaidProxy = function (src) {
    window.__cb_done = false;
    window.__cb_result = null;
    var id = 'm' + ('00000' + ((Math.random() * 1e7) | 0)).slice(-6) + '_' + Date.now();
    mermaid.render(id, src)
      .then(function (r) {
        window.__cb_result = { ok: true, svg: r.svg };
        window.__cb_done = true;
      })
      .catch(function (e) {
        var m = (e && (e.message || e.str)) ? String(e.message || e.str) : String(e);
        window.__cb_result = { ok: false, message: m };
        window.__cb_done = true;
      });
  };
  window.__rasterizeProxy = function (svgStr, scale) {
    window.__cb_done2 = false;
    window.__cb_result2 = null;
    try {
      var svg = new DOMParser().parseFromString(svgStr, 'image/svg+xml');
      var root = svg.querySelector('svg');
      if (!root) {
        window.__cb_result2 = { ok: false, message: 'no <svg> root' };
        window.__cb_done2 = true;
        return;
      }
      var vb = (root.getAttribute('viewBox') || '').trim().split(/\\s+/);
      var w = parseFloat(root.getAttribute('width')) || (+vb[2]) || 800;
      var h = parseFloat(root.getAttribute('height')) || (+vb[3]) || 600;
      w = Math.max(2, Math.round(w * scale));
      h = Math.max(2, Math.round(h * scale));
      var img = new Image();
      var blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      img.onload = function () {
        var c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        var ctx = c.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        try {
          var dataUrl = c.toDataURL('image/png');
          URL.revokeObjectURL(url);
          window.__cb_result2 = { ok: true, dataUrl: dataUrl, width: w, height: h };
        } catch (e2) {
          URL.revokeObjectURL(url);
          window.__cb_result2 = { ok: false, message: 'toDataURL blocked: ' + String(e2) };
        }
        window.__cb_done2 = true;
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        window.__cb_result2 = { ok: false, message: 'img.onerror' };
        window.__cb_done2 = true;
      };
      img.src = url;
    } catch (ex) {
      window.__cb_result2 = { ok: false, message: 'rasterize threw ' + String(ex) };
      window.__cb_done2 = true;
    }
  };
};
window.__installProxies();
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _bundle_path() -> Optional[str]:
    """定位官方 mermaid.min.js（与 mermaid.py._find_mmdc 一致思路）。

    优先仓库本地 tools/mermaid-cli/node_modules/mermaid/dist/mermaid.min.js。
    未来如需在打包产物里使用本渲染器，应将 mermaid.min.js 复制到
    doc_tool/resources/mermaid/mermaid.min.js 并加入 spec all_datas。
    """
    candidates = [
        _repo_root() / "tools" / "mermaid-cli" / "node_modules" / "mermaid" / "dist" / "mermaid.min.js",
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 100_000:
            return str(c)
    return None


def _spin(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    if hasattr(loop, "exec_"):
        loop.exec_()
    else:
        loop.exec()


class _WebMermaidEngine:
    """持有一个隐藏 QWebEngineView，复用 mermaid.min.js 实例。仅 GUI 线程用。"""

    def __init__(self, bundle_path: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView

        if QApplication.instance() is None:
            raise RuntimeError("QtWebEngine 需要运行中的 QApplication")

        self._bundle = bundle_path
        self._view = QWebEngineView()
        self._loaded = {"v": None}

        def _on_load(ok: bool) -> None:
            self._loaded["v"] = ok

        self._view.loadFinished.connect(_on_load)

        url = QUrl.fromLocalFile(bundle_path)
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;background:#fff;font-family:sans-serif}"
            "#stage{display:none}</style>"
            "<script src=\"" + url.toString() + "\"></script>"
            "</head><body><div id='stage'></div></body></html>"
        )
        base = QUrl.fromLocalFile(str(Path(bundle_path).parent) + "/")
        self._view.setHtml(html, base)

        # 等 loadFinished + mermaid 对象就绪（解析 3.4MB min.js 需要几十~几百 ms）
        ready = False
        for _ in range(160):  # 8s 上限
            _spin(50)
            if self._loaded["v"] is False:
                raise RuntimeError("QtWebEngine 页面加载失败")
            if self._loaded["v"] is True:
                done = {"v": False}
                self._run_js_sync(
                    "(typeof window.mermaid !== 'undefined') && !!window.mermaid.render",
                    lambda v: done.update(v=bool(v)),
                )
                if done["v"]:
                    ready = True
                    break
        if not ready:
            raise RuntimeError("QtWebEngine 页面或 mermaid 对象未就绪")

        self._view.page().runJavaScript(_INIT_JS)
        installed = {"v": False}
        for _ in range(40):  # 2s 上限
            self._run_js_sync("!!window.__proxyInstalled", lambda v: installed.update(v=bool(v)))
            if installed["v"]:
                break
            _spin(50)
        if not installed["v"]:
            raise RuntimeError("mermaid proxy 安装超时")

    def _run_js_sync(self, expr: str, cb) -> None:
        """同步跑一段 JS 表达式；cb 在拿到结果（或 2s 超时）后被回调一次。"""
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        got = {"v": None}

        def wrap(v) -> None:
            got["v"] = v
            loop.quit()

        self._view.page().runJavaScript(expr, 0, wrap)
        QTimer.singleShot(2000, loop.quit)
        if hasattr(loop, "exec_"):
            loop.exec_()
        else:
            loop.exec()
        cb(got["v"])

    def render(self, source: str, *, timeout_ms: int = 4000) -> RenderResult:
        page = self._view.page()
        page.runJavaScript("window.__renderMermaidProxy({0})".format(json.dumps(source)))

        ok_svg: Optional[str] = None
        err: Optional[str] = None
        end = time.time() + max(0.6, timeout_ms / 1000)
        while time.time() < end:
            done = {"v": False}
            self._run_js_sync("(window.__cb_done === true)", lambda v: done.update(v=bool(v)))
            if done["v"]:
                got = {"s": None}
                self._run_js_sync(
                    "JSON.stringify(window.__cb_result)", lambda v: got.update(s=v)
                )
                if got["s"]:
                    try:
                        obj = json.loads(got["s"])
                    except Exception as ex:
                        return RenderResult(False, error="mermaid.js 返回无效 JSON：" + str(ex))
                    if obj.get("ok"):
                        ok_svg = obj["svg"]
                    else:
                        err = obj.get("message") or "mermaid.js 编译错误"
                break
            _spin(30)

        if not ok_svg:
            return RenderResult(False, error=err or "QtWebEngine 渲染超时")

        raster = self._rasterize(ok_svg, scale=2.0)
        png: Optional[bytes] = None
        width: Optional[int] = None
        height: Optional[int] = None
        if raster and raster.get("ok"):
            data_url = str(raster.get("dataUrl") or "")
            prefix = "data:image/png;base64,"
            if data_url.startswith(prefix):
                png = base64.b64decode(data_url[len(prefix):])
                w0 = raster.get("width")
                h0 = raster.get("height")
                width = int(w0) if isinstance(w0, (int, float)) and w0 > 0 else None
                height = int(h0) if isinstance(h0, (int, float)) and h0 > 0 else None
        if png is None:
            # Chromium canvas 栅格化失败时退路：用 QtSvg 解析 SVG（可能丢部分 CSS
            # 样式但保证有 PNG）。viewBox 0 0 W H 取 W/H。
            size = re.search(rb'<svg[^>]*viewBox="[^"]*\s([\d.]+)\s([\d.]+)"', ok_svg.encode("utf-8"))
            width = int(float(size.group(1))) if size else None
            height = int(float(size.group(2))) if size else None
            try:
                png = svg_to_png(ok_svg.encode("utf-8"), width or 960, height or 540)
            except Exception:
                png = None
        return RenderResult(
            True,
            svg=ok_svg.encode("utf-8"),
            png=png,
            width=width,
            height=height,
            backend="web-mermaid-js",
        )

    def _rasterize(self, svg_str: str, *, scale: float = 2.0) -> Optional[dict]:
        page = self._view.page()
        page.runJavaScript(
            "window.__rasterizeProxy({0}, {1})".format(json.dumps(svg_str), scale)
        )
        end = time.time() + 5
        while time.time() < end:
            done = {"v": False}
            self._run_js_sync("(window.__cb_done2 === true)", lambda v: done.update(v=bool(v)))
            if done["v"]:
                got = {"s": None}
                self._run_js_sync(
                    "JSON.stringify(window.__cb_result2)", lambda v: got.update(s=v)
                )
                if got["s"]:
                    try:
                        obj = json.loads(got["s"])
                    except Exception:
                        return None
                    return obj if isinstance(obj, dict) else None
            _spin(30)
        return None


def _disable(reason: str) -> None:
    global _DISABLED, _DISABLED_REASON
    _DISABLED = True
    _DISABLED_REASON = reason


def web_disabled_reason() -> Optional[str]:
    """若本进程已永久禁用 web 渲染，返回原因用于 UI 状态栏提示；未禁用时返回 None。"""
    return _DISABLED_REASON if _DISABLED else None


def web_available() -> bool:
    """不触发初始化前提下：能否进入 web 渲染路径（找到 bundle 且能 import QtWebEngine）。

    仅用于 UI 提示与条件分支；真正尝试渲染前请直接调用 render_web。
    """
    if _DISABLED or _env_disabled():
        return False
    if not _bundle_path():
        return False
    try:
        if importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None:
            return False
    except Exception:
        return False
    return True


def _ensure_engine() -> Optional["_WebMermaidEngine"]:
    global _RENDERER
    if _DISABLED:
        return None
    if _env_disabled():
        _disable("已用环境变量 DOCTOOL_MERMAID_WEB 关闭 web 渲染")
        return None
    if _RENDERER is not None:
        return _RENDERER
    bundle = _bundle_path()
    if not bundle:
        _disable("未找到 mermaid.min.js（请运行 npm install --prefix tools/mermaid-cli）")
        return None
    try:
        engine = _WebMermaidEngine(bundle)
    except Exception as exc:  # noqa: BLE001
        _disable("QtWebEngine 初始化失败：{0}".format(exc))
        return None
    _RENDERER = engine
    return _RENDERER


def render_web(source: str, *, timeout_ms: int = 4000) -> Optional[RenderResult]:
    """尝试用官方 mermaid.js 渲染；不可用（或永久禁用）返回 None，调用方回退其它后端。

    返回 RenderResult（无论成功/失败）表示已尝试；返回 None 表示不可用。
    """
    engine = _ensure_engine()
    if engine is None:
        return None
    try:
        result = engine.render(source, timeout_ms=timeout_ms)
    except Exception as exc:  # noqa: BLE001
        _disable("QtWebEngine 渲染抛错：{0}".format(exc))
        global _RENDERER
        _RENDERER = None
        return None
    if not result.ok:
        # 超时类失败通常是环境级（如沙箱挡 Chromium IPC），永久禁用避免反复阻塞。
        message = result.error or ""
        if message.endswith("超时") or "QtWebEngine" in message or "未就绪" in message:
            _disable(message)
            _RENDERER = None
            return None
    return result