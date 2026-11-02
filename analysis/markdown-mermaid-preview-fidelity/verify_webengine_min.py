# -*- coding: utf-8 -*-
"""最小离线 WebEngine 页面与 PNG 捕获验证脚本

验证 Task 1.3 与 Task 1.4:
- 1.3: 离线 WebEngine 页面加载、加载/完成信号、官方 Mermaid SVG 生成
- 1.4: 无 Node/npm 环境下浏览器直接生成 PNG，覆盖中文、多行、foreignObject、裁切与逻辑尺寸
"""

import json
import os
import sys
from pathlib import Path

# 确保 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from PySide6.QtCore import QByteArray, QEventLoop, QObject, QRect, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

class TestBridge(QObject):
    def __init__(self):
        super().__init__()
        self.result_data = None
        self.loop = None

    @Slot(str)
    def onMermaidRendered(self, data_json: str):
        self.result_data = json.loads(data_json)
        if self.loop:
            self.loop.quit()

def run_verification():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    out_dir = Path(__file__).resolve().parent
    preview_html_path = (Path(__file__).resolve().parent.parent.parent / "doc_tool" / "resources" / "web_preview" / "preview.html").resolve()
    
    print(f"[1.3] 离线页面资源定位: {preview_html_path}")
    assert preview_html_path.exists(), f"未找到 preview.html: {preview_html_path}"

    view = QWebEngineView()
    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

    channel = QWebChannel(view.page())
    bridge = TestBridge()
    channel.registerObject('testBridge', bridge)
    view.page().setWebChannel(channel)

    page_loaded = False
    load_status = None

    def on_load_finished(ok: bool):
        nonlocal page_loaded, load_status
        page_loaded = True
        load_status = ok
        print(f"[1.3] QWebEngineView.loadFinished: ok={ok}")

    view.loadFinished.connect(on_load_finished)
    view.load(QUrl.fromLocalFile(str(preview_html_path)))

    view.resize(1024, 768)
    view.show()

    loop = QEventLoop()
    view.loadFinished.connect(lambda ok: loop.quit())
    QTimer.singleShot(10000, loop.quit)
    loop.exec()

    if not load_status:
        print("[ERROR] preview.html 加载失败！")
        return False

    print("[1.3] preview.html 加载成功，初始化 WebChannel 并执行官方 Mermaid SVG 渲染...")

    mermaid_code = """graph TD
    subgraph 接入层 [客户端接入网关]
        A["第一行：用户界面提交请求<br/>第二行：多行中文说明<br/>第三行：foreignObject验证"] --> B[鉴权中心]
    end
    subgraph 核心层 [渲染与业务集群]
        B --> C{校验是否通过?}
        C -->|通过| D[生成官方矢量图形]
        C -->|失败| E[返回降级提示]
    end
    style A fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style D fill:#e8f8f5,stroke:#2ecc71,stroke-width:2px;
"""

    inject_js = f"""
    (function() {{
        function initAndRender() {{
            new QWebChannel(qt.webChannelTransport, async function(ch) {{
                const tb = ch.objects.testBridge;
                try {{
                    if (typeof mermaid === 'undefined') {{
                        tb.onMermaidRendered(JSON.stringify({{ error: 'mermaid not defined' }}));
                        return;
                    }}
                    mermaid.initialize({{
                        startOnLoad: false,
                        theme: 'default',
                        securityLevel: 'loose',
                        htmlLabels: true
                    }});
                    const id = 'render_test_' + Date.now();
                    const source = {json.dumps(mermaid_code)};
                    const {{ svg }} = await mermaid.render(id, source);
                    
                    let container = document.getElementById('test-mermaid-container');
                    if (!container) {{
                        container = document.createElement('div');
                        container.id = 'test-mermaid-container';
                        container.style.position = 'absolute';
                        container.style.top = '0';
                        container.style.left = '0';
                        container.style.background = '#ffffff';
                        container.style.padding = '10px';
                        document.body.appendChild(container);
                    }}
                    container.innerHTML = svg;
                    const svgEl = container.querySelector('svg');
                    const bbox = svgEl.getBoundingClientRect();
                    tb.onMermaidRendered(JSON.stringify({{
                        svg: svg,
                        width: bbox.width,
                        height: bbox.height,
                        hasForeignObject: svg.indexOf('<foreignObject') !== -1
                    }}));
                }} catch (err) {{
                    tb.onMermaidRendered(JSON.stringify({{ error: String(err && err.message ? err.message : err) }}));
                }}
            }});
        }}

        if (typeof QWebChannel === 'undefined') {{
            const s = document.createElement('script');
            s.src = 'qrc:///qtwebchannel/qwebchannel.js';
            s.onload = initAndRender;
            document.head.appendChild(s);
        }} else {{
            initAndRender();
        }}
    }})();
    """

    loop_render = QEventLoop()
    bridge.loop = loop_render
    view.page().runJavaScript(inject_js)
    QTimer.singleShot(10000, loop_render.quit)
    loop_render.exec()

    js_result = bridge.result_data
    if not js_result or "error" in js_result:
        print(f"[ERROR] Mermaid 渲染失败: {js_result}")
        return False

    svg_content = js_result.get("svg", "")
    width = int(js_result.get("width", 0))
    height = int(js_result.get("height", 0))
    has_fo = js_result.get("hasForeignObject", False)

    print(f"[1.3] 官方 Mermaid 渲染完成: 逻辑宽={width}, 逻辑高={height}, foreignObject={has_fo}")
    svg_path = out_dir / "verify_min_mermaid.svg"
    svg_path.write_text(svg_content, encoding="utf-8")
    print(f"[1.3] SVG 保存成功: {svg_path} (大小: {svg_path.stat().st_size} bytes)")

    # 1.4 测试无 Node/npm 浏览器 PNG 生成
    print("[1.4] 开始测试浏览器无 Node/npm PNG 捕获生成...")
    
    pad = 20
    target_w = max(width + pad * 2, 200)
    target_h = max(height + pad * 2, 100)
    view.resize(target_w, target_h)

    loop_paint = QEventLoop()
    QTimer.singleShot(400, loop_paint.quit)
    loop_paint.exec()

    pixmap = view.grab(QRect(0, 0, target_w, target_h))
    png_path = out_dir / "verify_min_mermaid.png"
    ok = pixmap.save(str(png_path), "PNG")
    if not ok or not png_path.exists():
        print(f"[ERROR] PNG 保存失败: {png_path}")
        return False

    png_size = png_path.stat().st_size
    print(f"[1.4] PNG 生成成功: {png_path}")
    print(f"      像素尺寸: {pixmap.width()}x{pixmap.height()}, 文件大小: {png_size} bytes")

    img = pixmap.toImage()
    non_white_pixels = 0
    for y in range(0, img.height(), 4):
        for x in range(0, img.width(), 4):
            pixel = img.pixelColor(x, y)
            if pixel.red() < 240 or pixel.green() < 240 or pixel.blue() < 240:
                non_white_pixels += 1

    print(f"[1.4] 像素保真度检测: 采样深色/图形像素数={non_white_pixels}")
    assert non_white_pixels > 50, "生成的图片近乎纯白，渲染内容可能缺失！"

    print("==========================================")
    print("Task 1.3 & 1.4 最小链路验证通过！")
    print(f"运行环境: Python {sys.version.split()[0]}, PySide6 {view.__module__}")
    print(f"资源来源: 离线本地文件 {preview_html_path}")
    print(f"产物核对:")
    print(f"  - SVG: {svg_path} ({svg_path.stat().st_size} bytes)")
    print(f"  - PNG: {png_path} ({png_size} bytes)")
    print("==========================================")
    return True

if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
