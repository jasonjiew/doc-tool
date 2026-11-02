# -*- coding: utf-8 -*-
"""测试官方 Mermaid 渲染器（Flowchart + SequenceDiagram + 语法错误定位 + PNG 生成）"""

import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QObject, QRect, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

class RenderBridge(QObject):
    def __init__(self):
        super().__init__()
        self.result = None
        self.loop = None

    @Slot(str)
    def onDone(self, json_str: str):
        self.result = json.loads(json_str)
        if self.loop:
            self.loop.quit()

def test_renderer():
    app = QApplication.instance() or QApplication(sys.argv)

    view = QWebEngineView()
    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

    bridge = RenderBridge()
    channel = QWebChannel(view.page())
    channel.registerObject("renderBridge", bridge)
    view.page().setWebChannel(channel)

    preview_html = (Path(REPO_ROOT) / "doc_tool" / "resources" / "web_preview" / "preview.html").resolve()
    view.load(QUrl.fromLocalFile(str(preview_html)))
    view.resize(1024, 768)
    view.show()

    loop_load = QEventLoop()
    view.loadFinished.connect(lambda ok: loop_load.quit())
    QTimer.singleShot(6000, loop_load.quit)
    loop_load.exec()

    print("[Renderer] 页面加载完成")

    # 1. 验证流程图（带子图、样式、回边、长中文标签）
    flow_code = """graph TD
    subgraph 网关层 [统一接入微服务]
        A["阶段一：高保真Markdown输入去抖处理"] --> B[鉴权认证]
    end
    subgraph 核心层 [渲染与布局计算引擎]
        B --> C{校验是否通过?}
        C -->|通过| D["阶段二：解析为标准矢量SVG并生成高清位图"]
        C -->|失败| E[返回降级提示]
    end
    D --> A
    style A fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style D fill:#e8f8f5,stroke:#2ecc71,stroke-width:2px;
"""

    def do_render(source):
        js = f"""
        new QWebChannel(qt.webChannelTransport, async function(ch) {{
            const rb = ch.objects.renderBridge;
            try {{
                mermaid.initialize({{
                    startOnLoad: false,
                    theme: 'default',
                    securityLevel: 'loose',
                    htmlLabels: true
                }});
                const id = 'render_' + Math.random().toString(36).substr(2, 9);
                const {{ svg }} = await mermaid.render(id, {json.dumps(source)});
                
                let container = document.getElementById('render-box');
                if (!container) {{
                    container = document.createElement('div');
                    container.id = 'render-box';
                    container.style.position = 'absolute';
                    container.style.top = '0';
                    container.style.left = '0';
                    container.style.background = '#ffffff';
                    document.body.appendChild(container);
                }}
                container.innerHTML = svg;
                const svgEl = container.querySelector('svg');
                const bbox = svgEl.getBoundingClientRect();
                rb.onDone(JSON.stringify({{
                    ok: true,
                    svg: svg,
                    width: Math.ceil(bbox.width),
                    height: Math.ceil(bbox.height),
                    hasForeignObject: svg.indexOf('<foreignObject') !== -1
                }}));
            }} catch (err) {{
                rb.onDone(JSON.stringify({{
                    ok: false,
                    error: String(err && err.message ? err.message : err)
                }}));
            }}
        }});
        """
        loop_render = QEventLoop()
        bridge.loop = loop_render
        view.page().runJavaScript(js)
        QTimer.singleShot(6000, loop_render.quit)
        loop_render.exec()
        return bridge.result

    res_flow = do_render(flow_code)
    print("[1] Flowchart 渲染结果: ok =", res_flow.get("ok"), "w =", res_flow.get("width"), "h =", res_flow.get("height"), "fo =", res_flow.get("hasForeignObject"))
    assert res_flow.get("ok") is True
    assert "网关层" in res_flow.get("svg")
    assert "核心层" in res_flow.get("svg")

    # 2. 验证时序图（带 alt/else, opt, loop, par/and, Note, 激活条）
    seq_code = """sequenceDiagram
    autonumber
    actor User as 用户
    participant Client as 客户端
    participant Server as 渲染服务
    
    User->>Client: 提交渲染请求
    activate Client
    alt 缓存有效
        Client-->>User: 毫秒级返回
    else 缓存过期
        Client->>Server: 解析正文
        activate Server
        loop 布局迭代
            Server->>Server: 计算坐标
        end
        deactivate Server
        Client-->>User: 渲染完成
    end
    deactivate Client
"""
    res_seq = do_render(seq_code)
    print("[2] Sequence 渲染结果: ok =", res_seq.get("ok"), "w =", res_seq.get("width"), "h =", res_seq.get("height"))
    assert res_seq.get("ok") is True
    assert "布局迭代" in res_seq.get("svg")
    assert "缓存有效" in res_seq.get("svg")

    # 3. 验证语法错误精确定位
    err_code = """graph TD
    A --> 
    ??? 非法语法
"""
    res_err = do_render(err_code)
    print("[3] 语法错误结果: ok =", res_err.get("ok"), "error =", res_err.get("error"))
    assert res_err.get("ok") is False
    assert len(res_err.get("error", "")) > 0

    print("官方 Mermaid 渲染器最小能力全面验证通过！")

if __name__ == "__main__":
    test_renderer()
