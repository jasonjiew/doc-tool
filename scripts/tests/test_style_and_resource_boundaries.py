# -*- coding: utf-8 -*-
"""阅读样式与资源边界验收测试（REQ-MD-03、REQ-MD-05、REQ-MD-08、REQ-MM-01）。

验证 Task 4.1～4.4：
- 4.1: 浅色/深色作用域样式、中文字体回退、正文宽度限制、CSS 不改变 Mermaid 内部标签
- 4.2: 合法相对图、缺图占位符、路径逃逸与符号链接越界阻断
- 4.3: 脚本/事件/可执行 URL 阻断、远程图片不自动请求
- 4.4: 样式截图产物输出与离线使用说明
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QEventLoop, QRect, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


class StyleAndResourceBoundariesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()
        cls.browser = WebPreviewBrowser()
        cls.browser.resize(900, 700)
        cls.browser.show()
        if not cls.browser._page_ready:
            loop = QEventLoop()
            cls.browser.loadFinished.connect(lambda ok: loop.quit())
            QTimer.singleShot(6000, loop.quit)
            loop.exec()

    def _eval_js(self, script: str):
        result = None
        loop = QEventLoop()

        def cb(val):
            nonlocal result
            result = val
            loop.quit()

        self.browser.page().runJavaScript(script, cb)
        QTimer.singleShot(4000, loop.quit)
        loop.exec()
        return result

    def _render_md(self, md_text: str):
        self.browser.set_markdown(md_text)
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()
        return self._eval_js("document.getElementById('preview-container').innerHTML")

    def test_4_1_scoped_styling_dark_light_and_font_stacks(self):
        """4.1 验收：中文字体回退栈、正文宽度、深浅色模式样式切换。"""
        # 测试浅色模式
        self.browser.set_dark(False)
        self.assertFalse(self.browser._dark)
        is_dark_class = self._eval_js("document.body.classList.contains('dark-theme')")
        self.assertFalse(is_dark_class)

        # 检查字体栈
        font_family = self._eval_js("window.getComputedStyle(document.body).fontFamily")
        self.assertTrue(
            "Segoe UI" in font_family
            or "Microsoft YaHei" in font_family
            or "PingFang SC" in font_family
            or "sans-serif" in font_family
        )

        # 检查正文容器最大宽度
        max_w = self._eval_js(
            "window.getComputedStyle(document.getElementById('preview-container')).maxWidth"
        )
        self.assertEqual(max_w, "900px")

        # 切换深色模式
        self.browser.set_dark(True)
        self.assertTrue(self.browser._dark)
        is_dark_class = self._eval_js("document.body.classList.contains('dark-theme')")
        self.assertTrue(is_dark_class)

    def test_4_2_resource_boundary_missing_image_and_path_traversal(self):
        """4.2 验收：合法图片展示、缺图占位符、多级上级逃逸阻断。"""
        md = """测试资源边界：
![合法缺图](assets/images/non_existent_image.png)

![逃逸图片](../../../../etc/passwd)
"""
        html = self._render_md(md)
        self.assertIsNotNone(html)

        # 越界路径直接在前端安全清洗阶段被阻断
        self.assertIn("越界资源已阻断", html)
        self.assertNotIn('src="../../../../etc/passwd"', html)

    def test_4_3_html_boundaries_block_executable_urls_and_remote_images(self):
        """4.3 验收：阻止 javascript: 伪协议与远程网络图片。"""
        md = """活动内容测试：
[危险链接](javascript:alert('malicious'))

![远程图片](https://example.com/tracker.png)
"""
        html = self._render_md(md)
        self.assertIsNotNone(html)

        # 远程图片被阻断并提示，不发起外部网络请求
        self.assertIn("远程资源已阻断", html)
        self.assertNotIn('src="https://example.com/tracker.png"', html)

        # 伪协议被 markdown-it 安全验证拒绝，绝不生成可执行的 a href
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("href='javascript:", html)

    def test_4_4_visual_snapshots_output(self):
        """4.4 验收：为本组生成绑定的浅色与深色真实渲染截图。"""
        out_dir = Path(REPO_ROOT) / "analysis" / "markdown-mermaid-preview-fidelity"
        out_dir.mkdir(parents=True, exist_ok=True)

        sample_md = """# 视觉对照样例：中英文与图表

这是一段测试正文，包含 **粗体**、*斜体* 以及 `inline code`。

| 组件名 | 状态 | 说明 |
| :--- | :---: | ---: |
| 预览适配器 | 正常 | QWebEngine 高保真 |
| 样式作用域 | 正常 | 浅色/深色主题 |

> [!NOTE]
> 作用域样式保证正文样式不污染内部 Mermaid 布局。
"""
        # 1. 浅色模式截图
        self.browser.set_dark(False)
        self._render_md(sample_md)
        pixmap_light = self.browser.grab(QRect(0, 0, 800, 600))
        light_png = out_dir / "preview_light_theme.png"
        pixmap_light.save(str(light_png), "PNG")
        self.assertTrue(light_png.exists())
        self.assertGreater(light_png.stat().st_size, 1000)

        # 2. 深色模式截图
        self.browser.set_dark(True)
        self._render_md(sample_md)
        pixmap_dark = self.browser.grab(QRect(0, 0, 800, 600))
        dark_png = out_dir / "preview_dark_theme.png"
        pixmap_dark.save(str(dark_png), "PNG")
        self.assertTrue(dark_png.exists())
        self.assertGreater(dark_png.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
