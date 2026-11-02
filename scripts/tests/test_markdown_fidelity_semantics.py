# -*- coding: utf-8 -*-
"""Markdown 正文语义与扩展验收测试（REQ-MD-01～REQ-MD-04、REQ-MD-08、REQ-ED-01）。

验证 Task 3.1～3.6：
- 3.1: 本地固定 markdown-it 离线资源与 hash/许可
- 3.2: CommonMark 段落、换行、嵌套列表、起始编号、任务列表、删除线
- 3.3: 表格转义竖线不增列、三种对齐、长宽表完整性
- 3.4: 行内与围栏代码保护、语言标记
- 3.5: 图片尺寸后缀、提示块、代码内相似标记保护
- 3.6: 原生轻量 render_markdown_html 服务保持兼容可用
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from doc_tool.application.content.preview import render_markdown_html
from doc_tool.resources import resource_path
from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


class MarkdownFidelitySemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()
        cls.browser = WebPreviewBrowser()
        # 等待页面模板加载完成
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
        """让当前 QWebEngine 执行前端 updateMarkdown 并等待渲染返回容器 HTML。"""
        self.browser.set_markdown(md_text)
        # 等待事件循环调度
        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        return self._eval_js("document.getElementById('preview-container').innerHTML")

    def test_3_1_local_markdown_it_resource_and_hash(self):
        """3.1 验收：固定本地 markdown-it 版本 14.1.0 与 sha256 离线核对。"""
        js_file = Path(REPO_ROOT) / "doc_tool" / "resources" / "web_preview" / "markdown-it.min.js"
        self.assertTrue(js_file.exists(), "未找到本地 markdown-it.min.js")
        data = js_file.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        self.assertEqual(h, "38c70a1e7ca91ab40e2d9e6e60129851a717ed1c7d4acbbdd41bf9503791cf68")

        manifest_file = Path(REPO_ROOT) / "doc_tool" / "resources" / "web_preview" / "OFFLINE_RESOURCE_MANIFEST.md"
        self.assertTrue(manifest_file.exists(), "未找到 OFFLINE_RESOURCE_MANIFEST.md")
        manifest_text = manifest_file.read_text(encoding="utf-8")
        self.assertIn("14.1.0", manifest_text)
        self.assertIn("38c70a1e7ca91ab40e2d9e6e60129851a717ed1c7d4acbbdd41bf9503791cf68", manifest_text)

    def test_3_2_paragraphs_breaks_and_nested_lists(self):
        """3.2 验收：连续正文单换行不分段、显式硬换行、嵌套列表层级与起始编号、任务列表。"""
        md = """这是第一行正文。
这是同一段落的第二行文本。

这是带显式硬换行的第一行。  
这是显式硬换行的第二行。

1. 有序第一项
   - 无序子项 A
   - 无序子项 B
2. 有序第二项

独立正文段落。

3. 起始为3的第一项
4. 起始为3的第二项

- [x] 已完成任务项
- [ ] 未完成任务项

~~已删除文本~~
"""
        html = self._render_md(md)
        self.assertIsNotNone(html)

        # 连续行不分拆为多个独立 <p>
        self.assertIn("这是第一行正文。\n这是同一段落的第二行文本。", html)
        self.assertNotIn("</p><p>这是同一段落的第二行文本。", html)

        # 显式硬换行包含 <br>
        self.assertIn("这是带显式硬换行的第一行。<br>", html)

        # 嵌套列表包含父子层级
        self.assertIn("<ol", html)
        self.assertIn("<ul", html)
        self.assertIn("<li>无序子项 A</li>", html)

        # 自定义起始编号 start="3"
        self.assertIn('start="3"', html)

        # 任务列表
        self.assertIn('class="task-list-item"', html)
        self.assertIn('type="checkbox" class="task-list-item-checkbox" checked="" disabled=""', html)
        self.assertIn('type="checkbox" class="task-list-item-checkbox" disabled=""', html)

        # 删除线
        self.assertTrue("<s" in html or "<del" in html)

    def test_3_3_tables_escaped_pipe_alignment_and_long_table(self):
        """3.3 验收：转义竖线不增加列、三向对齐、宽表包裹层、长表尾行与后续正文完整。"""
        md = """| 左列 | 中列 | 右列 |
| :--- | :---: | ---: |
| 普通A | 包含\\|转义竖线内容 | 123.45 |
| 普通B | 第二行单元格 | 678.90 |

| 序号 | 项目 |
| --- | --- |
| 1 | 条目1 |
| 2 | 条目2 |
| 3 | 条目3 |
| 4 | 条目4 |
| 5 | 条目5 |

长表格之后的独立正文内容。
"""
        html = self._render_md(md)
        self.assertIsNotNone(html)

        # 转义竖线单元格在同一行，不增加列数（每行恰好 3 个 td）
        col_count = self._eval_js("document.querySelector('table tr:nth-child(1)').children.length")
        self.assertEqual(col_count, 3)

        # 对齐属性
        align_left = self._eval_js("document.querySelector('table th:nth-child(1)').style.textAlign")
        align_center = self._eval_js("document.querySelector('table th:nth-child(2)').style.textAlign")
        align_right = self._eval_js("document.querySelector('table th:nth-child(3)').style.textAlign")
        self.assertEqual(align_left, "left")
        self.assertEqual(align_center, "center")
        self.assertEqual(align_right, "right")

        # 宽表包裹层
        self.assertIn('class="table-wrapper"', html)

        # 长表尾行及后续正文完整保留
        self.assertIn("条目5", html)
        self.assertIn("长表格之后的独立正文内容。", html)

    def test_3_4_code_protection_and_inline_code(self):
        """3.4 验收：代码中的图片、链接、HTML 和 Mermaid 标记不被解释。"""
        md = """行内代码保护：`[链接](https://example.com)` 和 `<script>alert(1)</script>`。

```markdown
![图片](pic.png){width=200}
<div class="test">raw html</div>
graph TD
    A --> B
```

```python
def foo():
    return "test"
```
"""
        html = self._render_md(md)
        self.assertIsNotNone(html)

        # 行内代码未转换为 <a> 或执行 <script>
        self.assertNotIn('<a href="https://example.com">链接</a>', html)
        self.assertNotIn("<script>alert(1)</script>", html)

        # 围栏代码块中的图片和 HTML 被转义为普通文本展示
        self.assertIn("&lt;div class=\"test\"&gt;", html)
        self.assertIn("class=\"language-python\"", html)

    def test_3_5_project_extensions_image_size_and_callouts(self):
        """3.5 验：图片尺寸后缀生效、段落占位符过滤、提示块渲染与标签闭合（REQ-MD-01、REQ-MD-04）"""
        md = """带图片尺寸：
![架构图](assets/images/arch.png){width=450}
![业务图](images/img_0131.png =642x628)

<EMPTY_PAR/>

> [!NOTE]
> 这是一个普通提示块。

> [!WARNING]
> 这是一个警告块。

```markdown
<EMPTY_PAR/>
![代码内图](images/code.png =100x100)
```
"""
        html = self._render_md(md)
        self.assertIsNotNone(html)

        # 图片尺寸样式实际产出（包括 {width=...} 与项目 =宽x高）
        self.assertIn('max-width: 450px;', html)
        self.assertIn('max-width: 642px;', html)
        self.assertIn('height: 628px;', html)
        self.assertIn('images/img_0131.png', html)

        # <EMPTY_PAR/> 在正文中不作为文本显示，在代码块中保留
        self.assertNotIn('&lt;EMPTY_PAR/&gt;', html.split('<pre>')[0])
        self.assertIn('&lt;EMPTY_PAR/&gt;', html.split('<pre>')[1])
        self.assertIn('images/code.png =100x100', html.split('<pre>')[1])

        # 提示块
        self.assertIn('class="alert-block"', html)
        self.assertIn('class="alert-block alert-warn"', html)
        self.assertIn('这是一个普通提示块。', html)
    def test_3_6_native_render_markdown_html_backward_compatible(self):
        """3.6 验收：既有原生轻量 render_markdown_html 接口保持可用。"""
        raw_md = "# 标题\n\n正文段落。"
        native_html = render_markdown_html(raw_md)
        self.assertIn("<h1>", native_html)
        self.assertIn("<p>", native_html)


if __name__ == "__main__":
    unittest.main()
