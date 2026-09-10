# -*- coding: utf-8 -*-
"""图表大图查看器与预览交互测试（全套交互与边界防呆）。"""


from __future__ import annotations
import json
from unittest.mock import patch
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from doc_tool.application.content.preview import render_markdown_html
from doc_tool.ui.content.diagram_viewer import DiagramViewerDialog
from doc_tool.ui.content.editor_panel import EditorPanel, _PreviewBrowser


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


def setUpModule():
    _get_app()


def _make_test_pixmap(w=400, h=300):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("blue"))
    p.drawRect(10, 10, w - 20, h - 20)
    p.drawText(w // 2 - 20, h // 2, "Test Diagram")
    p.end()
    return QPixmap.fromImage(img)


class DiagramViewerInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_diagram_viewer_dialog_initialization(self):
        pix = _make_test_pixmap(600, 400)
        dialog = DiagramViewerDialog(
            pix,
            title="测试图表查看",
            mermaid_source="flowchart TD\nA-->B",
            on_edit_source=lambda: None,
        )
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.windowTitle(), "测试图表查看")
        self.assertIn("600 × 400", dialog.info_label.text())

    def test_diagram_viewer_small_image_no_upscale(self):
        """测试原图小于视口时，适应窗口默认保持 100% (1.0)，不盲目拉伸产生马赛克。"""
        pix = _make_test_pixmap(200, 150)
        dialog = DiagramViewerDialog(pix)
        dialog.resize(1000, 700)
        dialog._fit_to_window()
        self.assertLessEqual(dialog._zoom_factor, 1.0)
        self.assertEqual(dialog.label_zoom.text(), "100%")

    def test_diagram_viewer_drag_pan(self):
        """测试鼠标抓手拖拽平移。"""
        pix = _make_test_pixmap(2000, 1500)
        dialog = DiagramViewerDialog(pix)
        dialog._reset_zoom()  # 1:1 展示，出现滚动条
        
        scroll_area = dialog.scroll_area
        initial_h = scroll_area.horizontalScrollBar().value()
        initial_v = scroll_area.verticalScrollBar().value()

        # 模拟鼠标按下
        p1 = QPoint(100, 100)
        press_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            p1,
            p1,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        scroll_area.mousePressEvent(press_ev)
        self.assertTrue(scroll_area._dragging)

        # 模拟鼠标拖拽 50px
        p2 = QPoint(50, 50)
        move_ev = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            p2,
            p2,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        scroll_area.mouseMoveEvent(move_ev)

        # 模拟鼠标释放
        release_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            p2,
            p2,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        scroll_area.mouseReleaseEvent(release_ev)
        self.assertFalse(scroll_area._dragging)

    def test_preview_browser_image_hit_and_mermaid_detect(self):
        """测试 _PreviewBrowser 的 _image_at 命中与 Mermaid 识别（基于 ImageAltText 属性）。"""
        tb = _PreviewBrowser()
        html = '<p><a name="line-12" href="#line-12"><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" width="200" height="150" alt="Mermaid 图" /></a></p>'
        tb.setHtml(html)
        tb.resize(400, 300)
        tb.show()
        self.app.processEvents()

        info = tb._image_at(QPoint(100, 50))
        self.assertIsNotNone(info)
        self.assertEqual(info.line_no, 12)
        self.assertTrue(info.is_mermaid)
        self.assertFalse(info.pixmap.isNull())
        tb.close()

    def test_editor_panel_mermaid_block_extraction_tolerance(self):
        """测试 EditorPanel 源码块提取与容错。"""
        class DummyWriter:
            def resolve(self, path):
                from pathlib import Path
                return Path(path)

        panel = EditorPanel(DummyWriter(), writable=True)
        sample_md = """# 标题

正文段落。

```mermaid
flowchart LR
    A --> B
```

结尾。
"""
        panel._editor.setPlainText(sample_md)
        # 边界行命中
        block_exact = panel.get_mermaid_block_at_line(5)
        self.assertIsNotNone(block_exact)
        self.assertEqual(block_exact.start_line, 5)

        # 容错命中（空行微小误差）
        block_tol = panel.get_mermaid_block_at_line(4)
        self.assertIsNotNone(block_tol)
        self.assertEqual(block_tol.start_line, 5)



    def test_diagram_viewer_save_button_present(self):
        """测试沉浸式查看器包含本地保存图片按钮。"""
        pix = _make_test_pixmap(300, 200)
        dialog = DiagramViewerDialog(pix)
        self.assertTrue(hasattr(dialog, "btn_save"))
        self.assertEqual(dialog.btn_save.text(), "保存图片")

    def test_web_preview_browser_json_payload_extraction(self):
        """测试 WebPreviewBrowser 处理前端传来的 JSON (含 SVG 与源码) 格式。"""
        from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser
        browser = WebPreviewBrowser()
        received = []
        browser.mermaidViewRequested.connect(lambda s: received.append(s))

        svg_sample = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50"/></svg>'
        payload = json.dumps({"source": "flowchart TD\nA-->B", "svg": svg_sample})
        
        # 拦截 DiagramViewerDialog.exec，防止阻塞单测
        with unittest.mock.patch("doc_tool.ui.content.diagram_viewer.DiagramViewerDialog.exec", return_value=0):
            browser._on_mermaid_view_requested(payload)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], "flowchart TD\nA-->B")

    def test_scroll_to_heading_throttle(self):
        """测试标题滚动定位防抖节流，同一标题不重复下发脚本。"""
        from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser
        browser = WebPreviewBrowser()
        browser._page_ready = True

        calls = []
        browser.page().runJavaScript = lambda js: calls.append(js)

        browser.scroll_to_heading("1.1 背景")
        self.assertEqual(len(calls), 1)

        # 连续滚动在同一标题区域，应被节流拦截，不重复调用 JS
        browser.scroll_to_heading("1.1 背景")
        self.assertEqual(len(calls), 1)

        # 跨入新标题区域，正常触发一次
        browser.scroll_to_heading("1.2 目标")
        self.assertEqual(len(calls), 2)



    def test_editor_panel_jump_to_heading(self):
        """测试从预览标题反向跳转编辑器并定位到正确行号。"""
        class DummyWriter:
            def resolve(self, path):
                from pathlib import Path
                return Path(path)

        panel = EditorPanel(DummyWriter(), writable=True)
        sample_md = "# 第一章 概述\n\n内容正文\n\n## 1.1 架构设计\n\n架构详细内容"
        panel._editor.setPlainText(sample_md)

        # 反向定位
        panel.jump_to_heading("1.1 架构设计")
        cursor = panel._editor.textCursor()
        # 1.1 架构设计 在第 5 行
        self.assertEqual(cursor.block().blockNumber() + 1, 5)

    def test_editor_panel_locate_mermaid_source_with_crlf_tolerance(self):
        """测试反向定位 Mermaid 源码（具备 Windows CRLF / LF 差异容错）。"""
        class DummyWriter:
            def resolve(self, path):
                from pathlib import Path
                return Path(path)

        panel = EditorPanel(DummyWriter(), writable=True)
        sample_md = "前言\r\n\r\n```mermaid\r\nflowchart TD\r\n    A-->B\r\n```\r\n后语"
        panel._editor.setPlainText(sample_md)

        # 模拟浏览器传回的 LF 源码
        browser_source = "flowchart TD\n    A-->B"
        panel.locate_mermaid_source(browser_source)
        cursor = panel._editor.textCursor()
        # Mermaid 块起始行号是第 3 行
        self.assertEqual(cursor.block().blockNumber() + 1, 3)

    def test_diagram_viewer_safe_timer_resets(self):
        """测试查看器在关闭或销毁时定时器回调不会引发 C++ 内部对象已删除异常。"""
        pix = _make_test_pixmap(100, 80)
        dialog = DiagramViewerDialog(pix)
        # 显式触发安全复位
        dialog._reset_copy_btn("复制图片")
        dialog._reset_save_btn("保存图片")
        self.assertEqual(dialog.btn_copy.text(), "复制图片")
        self.assertEqual(dialog.btn_save.text(), "保存图片")


if __name__ == "__main__":
    unittest.main()
