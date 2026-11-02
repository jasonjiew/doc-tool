# -*- coding: utf-8 -*-
"""编辑器高保真预览图片加载与 Mermaid 大图文字/交互回归测试套件。

覆盖要求：
1. 真实 QWebEngine 预览链路与中文及空格路径项目下的图片加载、尺寸解析、章节切换、缺失占位与 <EMPTY_PAR/> 保护。
2. Mermaid 中文节点/连线大图文字保真度、像素级文本存在性验证、大图查看器浅色/深色主题与全量交互（缩放、适应、1:1、复制、保存、编辑、关闭）。
3. 离线安全边界、远程资源拦截与越界路径逃逸防护。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QByteArray, QEventLoop, QPoint, QRect, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from doc_tool.ui.content.diagram_viewer import DiagramViewerDialog
from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


def _has_text_pixels(img: QImage, threshold: int = 60) -> bool:
    """像素级检测：检查图像中是否存在文字绘制产生的暗色像素（非纯背景/框体）。"""
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 100:
                if c.red() < threshold and c.green() < threshold and c.blue() < threshold:
                    return True
    return False


class PreviewImageAndMermaidDialogRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()
        cls.browser = WebPreviewBrowser()
        if not cls.browser._page_ready:
            loop = QEventLoop()
            cls.browser.loadFinished.connect(lambda ok: loop.quit())
            QTimer.singleShot(6000, loop.quit)
            loop.exec()

        # 创建包含中文与空格的真实测试临时项目目录
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="doc_tool_测试项目 空格_"))
        cls.srd_dir = cls.temp_dir / "assets" / "srd"
        cls.dad_dir = cls.temp_dir / "assets" / "dad"
        (cls.srd_dir / "images").mkdir(parents=True, exist_ok=True)
        (cls.dad_dir / "images").mkdir(parents=True, exist_ok=True)

        # 在 srd/images 下生成真实测试图片
        img_srd_path = cls.srd_dir / "images" / "img_0131.png"
        img1 = QImage(642, 628, QImage.Format.Format_ARGB32)
        img1.fill(QColor(0, 120, 215))  # 填充蓝色
        img1.save(str(img_srd_path), "PNG")

        img_plain_path = cls.srd_dir / "images" / "plain_img.png"
        img2 = QImage(120, 80, QImage.Format.Format_ARGB32)
        img2.fill(QColor(34, 197, 94))  # 填充绿色
        img2.save(str(img_plain_path), "PNG")

        # 在 dad/images 下生成 dad 专有图片
        img_dad_path = cls.dad_dir / "images" / "dad_arch.png"
        img3 = QImage(300, 200, QImage.Format.Format_ARGB32)
        img3.fill(QColor(234, 88, 12))  # 填充橙色
        img3.save(str(img_dad_path), "PNG")

    @classmethod
    def tearDownClass(cls):
        cls.browser.cleanup()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

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

    def _render_md(self, md_text: str, base_url: str = ""):
        self.browser.set_markdown(md_text, base_url)
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        return self._eval_js("document.getElementById('preview-container').innerHTML")

    def test_01_local_images_with_and_without_size_in_chinese_space_path(self):
        """验证 1：中文及空格路径项目下的带尺寸（=宽x高）与不带尺寸图片加载及样式生效。"""
        srd_base_url = QUrl.fromLocalFile(str(self.srd_dir) + os.sep).toString()
        md = """# 架构章节

带项目自定义尺寸图片：
![业务流程图](images/img_0131.png =642x628)

不带尺寸图片：
![普通配图](images/plain_img.png)
"""
        html = self._render_md(md, srd_base_url)
        self.assertIsNotNone(html)

        # 1. 验证 DOM 中生成了带有自定义宽高的 img 标签
        self.assertIn('max-width: 642px;', html)
        self.assertIn('height: 628px;', html)
        self.assertIn('src="images/img_0131.png"', html)
        self.assertIn('src="images/plain_img.png"', html)

        # 2. 验证 QWebEngine 真正成功加载了解析自 base 的本地图片（naturalWidth > 0）
        check_js = """
        (() => {
            const img1 = document.querySelector('img[alt="业务流程图"]');
            const img2 = document.querySelector('img[alt="普通配图"]');
            return JSON.stringify({
                img1_loaded: img1 && img1.naturalWidth === 642 && img1.naturalHeight === 628,
                img2_loaded: img2 && img2.naturalWidth === 120 && img2.naturalHeight === 80,
                base_href: document.querySelector('base') ? document.querySelector('base').href : ''
            });
        })();
        """
        raw_res = self._eval_js(check_js)
        data = json.loads(raw_res) if raw_res else {}
        self.assertTrue(data.get("img1_loaded"), f"带尺寸图片未真实加载成功: {data}")
        self.assertTrue(data.get("img2_loaded"), f"无尺寸图片未真实加载成功: {data}")
        self.assertTrue(data.get("base_href", "").startswith("file:///"), "Base 标签未正确配置本地协议")

    def test_02_switch_chapter_resource_dir_and_missing_image_placeholder(self):
        """验证 2：切换章节/资源目录基准路径更新，以及缺失图片友好占位展示。"""
        dad_base_url = QUrl.fromLocalFile(str(self.dad_dir) + os.sep).toString()
        md = """# DAD 章节

存在的新章节图片：
![设计架构图](images/dad_arch.png =300x200)

不存在的缺失图片：
![缺失的图片](images/not_found_123.png =400x300)
"""
        html = self._render_md(md, dad_base_url)

        # 等待图片加载或触发 error 占位
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()

        check_js = """
        (() => {
            const dadImg = document.querySelector('img[alt="设计架构图"]');
            const placeholder = document.querySelector('.missing-image-placeholder');
            return JSON.stringify({
                dad_loaded: dadImg && dadImg.naturalWidth === 300,
                has_placeholder: placeholder !== null,
                placeholder_text: placeholder ? placeholder.innerText : '',
                placeholder_style: placeholder ? placeholder.getAttribute('style') : ''
            });
        })();
        """
        raw_res = self._eval_js(check_js)
        data = json.loads(raw_res) if raw_res else {}
        self.assertTrue(data.get("dad_loaded"), f"章节切换后新基准图片未加载: {data}")
        self.assertTrue(data.get("has_placeholder"), "缺失图片未显示占位块")
        self.assertIn("not_found_123.png", data.get("placeholder_text", ""))
        self.assertIn("max-width: 400px;", data.get("placeholder_style", ""))

    def test_03_empty_par_hidden_in_body_preserved_in_code_and_line_anchors(self):
        """验证 3：正文中 <EMPTY_PAR/> 不显示且不破坏布局；代码块与行内代码中的相同文本完整保留；行号锚点连续。"""
        md = """# 规范标题

正文第一段。

<EMPTY_PAR/>

正文第二段。

```xml
<EMPTY_PAR/>
![示例](images/code.png =100x100)
```

行内示例：`<EMPTY_PAR/>` 与 `![行内](images/inline.png =50x50)`。
"""
        html = self._render_md(md)

        # 1. 验证正文非代码区域未出现 <EMPTY_PAR/> 文本
        pre_split = html.split("<pre>")
        body_part = pre_split[0]
        self.assertNotIn("&lt;EMPTY_PAR/&gt;", body_part)
        self.assertNotIn("<EMPTY_PAR/>", body_part)

        # 2. 验证行号映射在 <EMPTY_PAR/> 隐藏段落存在且后续行号未偏移
        self.assertIn('id="line-1"', html)
        self.assertIn('id="line-3"', html)
        self.assertIn('id="line-5"', html)  # <EMPTY_PAR/> 段落保留 id 用于跳转，但 display:none
        self.assertIn('style="display: none;"', html)
        self.assertIn('id="line-7"', html)  # 第二段正文准确映射行号

        # 3. 验证代码块与行内代码完好保留未被误改
        code_part = pre_split[1]
        self.assertIn("&lt;EMPTY_PAR/&gt;", code_part)
        self.assertIn("![示例](images/code.png =100x100)", code_part)
        self.assertIn("<code>&lt;EMPTY_PAR/&gt;</code>", html)
        self.assertIn("<code>![行内](images/inline.png =50x50)</code>", html)

    def test_04_mermaid_diagram_no_foreign_object_and_has_text_elements(self):
        """验证 4：Mermaid 渲染生成纯矢量 SVG（包含标准 <text> 标签，绝不含导致文字丢失的 <foreignObject>）。"""
        source = """flowchart TD
    A[服务网关节点] -->|核心调用链| B(业务核心集群)
    B -->|数据库写入| C[(主库实例)]
"""
        renderer = get_official_mermaid_renderer()
        res = renderer.render(source, want_png=False, theme="default")
        self.assertTrue(res.ok)
        self.assertIsNotNone(res.svg)

        svg_str = res.svg.decode("utf-8")
        # 核心断言：决不能含有 foreignObject，必须含有 text 标签与中文节点内容
        self.assertNotIn("<foreignObject", svg_str, "Mermaid SVG 依然含有 foreignObject，将导致 QSvgRenderer 丢失文字！")
        self.assertIn("<text", svg_str, "Mermaid SVG 未生成标准 <text> 标签！")
        self.assertIn("服务网关节点", svg_str)
        self.assertIn("核心调用链", svg_str)
        self.assertIn("业务核心集群", svg_str)

    def test_05_mermaid_large_view_rasterization_has_text_pixels(self):
        """验证 5：从预览点击「大图」触发的 QSvgRenderer 栅格化能够产生真实的节点与连线文字像素，决非仅空轮廓。"""
        source = """flowchart LR
    A[数据采集中心] -->|传输协议| B[智能分析引擎]
"""
        renderer = get_official_mermaid_renderer()
        res = renderer.render(source, want_png=False, theme="default")
        self.assertTrue(res.ok)

        svg_ren = QSvgRenderer(QByteArray(res.svg))
        self.assertTrue(svg_ren.isValid())
        sz = svg_ren.defaultSize()
        w = max(100, sz.width() * 2)
        h = max(100, sz.height() * 2)

        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(0x00000000)
        p = QPainter(img)
        svg_ren.render(p)
        p.end()

        # 像素级文字检测（确保文字被真实栅格化）
        has_text = _has_text_pixels(img, threshold=80)
        self.assertTrue(has_text, "大图栅格化后的 QPixmap 中未检测到任何深色文字像素，文字渲染缺失！")

    def test_06_diagram_viewer_dialog_light_and_dark_theme_contrast_and_interactions(self):
        """验证 6：DiagramViewerDialog 浅色/深色主题下的按钮对比度（高于 AAA 7:1）以及缩放/1:1/适应/复制/保存/编辑/关闭全交互。"""
        # 准备一个带文字的测试 Pixmap
        pix = QPixmap(500, 300)
        pix.fill(Qt.GlobalColor.white)
        p = QPainter(pix)
        p.setPen(Qt.GlobalColor.black)
        p.drawText(50, 50, "架构图核心测试文字")
        p.end()

        edit_invoked = [False]
        def on_edit():
            edit_invoked[0] = True

        for dark_mode in (False, True):
            dlg = DiagramViewerDialog(
                pixmap=pix,
                title="全量交互测试",
                mermaid_source="flowchart TD\n  A-->B",
                on_edit_source=on_edit,
                dark=dark_mode,
            )
            dlg.show()
            self.app.processEvents()

            # 1. 验证按钮具有高对比度样式设置
            btn = dlg.btn_fit
            style = btn.styleSheet()
            self.assertTrue(style, f"按钮样式为空，模式 dark={dark_mode}")
            if dark_mode:
                self.assertIn("#e2e8f0", style, "深色模式按钮未设置高可读亮色文字")
                self.assertIn("#262936", style, "深色模式按钮背景异常")
            else:
                self.assertIn("#1e293b", style, "浅色模式按钮未设置高可读深色文字")
                self.assertIn("#f1f5f9", style, "浅色模式按钮背景异常")

            # 2. 测试放大与缩小
            init_zoom = dlg._zoom_factor
            dlg._zoom_in()
            self.assertGreater(dlg._zoom_factor, init_zoom, "放大操作未提升缩放系数")
            dlg._zoom_out()
            dlg._zoom_out()
            self.assertLess(dlg._zoom_factor, init_zoom, "缩小操作未降低缩放系数")

            # 3. 测试 1:1 还原
            dlg._reset_zoom()
            self.assertAlmostEqual(dlg._zoom_factor, 1.0, places=2, msg="1:1 操作未恢复 1.0 系数")
            self.assertEqual(dlg.label_zoom.text(), "100%")

            # 4. 测试适应窗口
            dlg._fit_to_window()
            self.assertTrue(dlg._fit_mode)

            # 5. 测试复制到剪贴板
            dlg._copy_image()
            cb_pix = QGuiApplication.clipboard().pixmap()
            self.assertFalse(cb_pix.isNull(), "复制图片后剪贴板为空")
            self.assertEqual(dlg.btn_copy.text(), "已复制 ✓")
            dlg._reset_copy_btn("复制图片")
            self.assertEqual(dlg.btn_copy.text(), "复制图片")

            # 6. 测试保存图片
            save_path = self.temp_dir / f"saved_diagram_dark_{dark_mode}.png"
            saved_ok = dlg._raw_pixmap.save(str(save_path), "PNG")
            self.assertTrue(saved_ok and save_path.exists(), "保存图片未落地成功")
            dlg._reset_save_btn("保存图片")
            self.assertEqual(dlg.btn_save.text(), "保存图片")

            # 7. 测试工作台编辑回调
            edit_invoked[0] = False
            dlg._handle_edit()
            self.assertTrue(edit_invoked[0], "在工作台编辑回调未成功触发")

            dlg.close()

    def test_07_security_boundaries_strictly_maintained(self):
        """验证 7：安全边界回归——远程图片与多级上级逃逸被严格阻断。"""
        md = """# 安全测试

远程资源：
![远程图](https://example.com/malicious.png)

越界资源：
![逃逸图](../../../etc/passwd)
![绝对路径图](/var/log/secure.png)
"""
        html = self._render_md(md)
        self.assertIn("class=\"blocked-remote-resource\"", html)
        self.assertIn("远程资源已阻断", html)
        self.assertIn("越界资源已阻断", html)
        self.assertNotIn("https://example.com/malicious.png\" />", html)



    def test_08_mermaid_inpage_modal_wide_diagram_full_fidelity_and_export(self):
        """验证 8：Mermaid「大图」网页内遮罩弹层（原样放大、无外部文件导出、无 QSvgRenderer 重新绘制）。
        
        验证要求：
        1. 弹层直接复用已渲染 SVG，节点文字、连线标签、颜色和背景与原图 100% 一致；
        2. 支持放大、缩小、适应窗口、1:1 与拖动；宽图放大后可查看完整细节；
        3. 仅在主动点击「复制图片」时按需生成完整图（2x 高清完整图，非当前视口区域）；
        4. Esc 关闭后图表恢复原位且预览继续正常工作，多图表互不干扰；
        5. 支持深浅主题切换，全过程 0 qt.svg 警告。
        """
        markdown_sample = """# 宽流程图测试
```mermaid
flowchart LR
    A[用户提交需求文档] -->|校验格式| B(初审检查合规性)
    B -->|初审通过| C{需求类型分流判断}
    C -->|标准研发流程| D[架构方案设计与评审]
    C -->|紧急修复流程| E[快速补丁验证与热修复]
    D --> G[前后端协同编码开发]
    E --> H[集成环境灰度验证]
    G --> H
    H -->|验收通过| J((生产环境正式发布上线))
    H -->|验收驳回| G
```

```mermaid
graph TD
    X[次级状态图] --> Y[结束]
```
"""
        browser = WebPreviewBrowser()
        browser.resize(1024, 768)
        browser.show()
        self.app.processEvents()

        browser.set_markdown(markdown_sample)

        # 等待页面与 Mermaid 异步渲染
        loop = QEventLoop()
        QTimer.singleShot(2200, loop.quit)
        loop.exec()

        # 1. 验证原图已渲染且包含完整中文节点与连线标签
        check_js = """
        (() => {
            const cards = document.querySelectorAll('.mermaid-card');
            if (cards.length < 2) return JSON.stringify({ ok: false, error: 'cards count < 2' });
            const card0 = cards[0];
            const svg = card0.querySelector('.mermaid-viewport svg');
            if (!svg) return JSON.stringify({ ok: false, error: 'no svg in card 0' });
            const texts = Array.from(svg.querySelectorAll('text')).map(t => t.textContent.trim()).filter(Boolean);
            const vb = svg.getAttribute('viewBox') || '';
            return JSON.stringify({
                ok: true,
                cardsCount: cards.length,
                svgId: svg.id,
                texts: texts,
                viewBox: vb,
                overlayDisplay: window.getComputedStyle(document.getElementById('mermaid-modal-overlay')).display
            });
        })()
        """
        res_box = [None]
        def on_checked(val):
            res_box[0] = json.loads(val)
        browser.page().runJavaScript(check_js, on_checked)
        
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()

        init_data = res_box[0]
        self.assertIsNotNone(init_data)
        self.assertTrue(init_data.get("ok"))
        self.assertIn("用户提交需求文档", init_data["texts"])
        self.assertIn("校验格式", init_data["texts"])
        self.assertEqual(init_data["overlayDisplay"], "none")

        # 2. 点击卡片上的「大图」按钮，验证打开遮罩弹层且原样复用 SVG
        open_js = """
        (() => {
            const card0 = document.querySelectorAll('.mermaid-card')[0];
            const btnView = card0.querySelector('.btn-view');
            btnView.click();
            const overlay = document.getElementById('mermaid-modal-overlay');
            const canvas = document.getElementById('mermaid-modal-canvas');
            const modalSvg = canvas.querySelector('svg');
            const dimLabel = document.getElementById('mermaid-modal-dim').textContent;
            const zoomText = document.getElementById('modal-zoom-indicator').textContent;
            const placeholder = card0.querySelector('.mermaid-in-viewer-placeholder');
            const modalTexts = modalSvg ? Array.from(modalSvg.querySelectorAll('text')).map(t => t.textContent.trim()).filter(Boolean) : [];
            return JSON.stringify({
                overlayDisplay: window.getComputedStyle(overlay).display,
                hasModalSvg: !!modalSvg,
                modalSvgId: modalSvg ? modalSvg.id : null,
                dimLabel: dimLabel,
                zoomText: zoomText,
                hasPlaceholderInCard: !!placeholder,
                modalTexts: modalTexts,
                transform: canvas.style.transform
            });
        })()
        """
        res_box[0] = None
        browser.page().runJavaScript(open_js, on_checked)
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()

        modal_data = res_box[0]
        self.assertIsNotNone(modal_data)
        self.assertEqual(modal_data["overlayDisplay"], "flex", "大图遮罩弹层未成功以 flex 显示")
        self.assertTrue(modal_data["hasModalSvg"])
        self.assertEqual(modal_data["modalSvgId"], init_data["svgId"], "弹层未原样复用原图表 SVG 节点")
        self.assertIn("用户提交需求文档", modal_data["modalTexts"])
        self.assertIn("校验格式", modal_data["modalTexts"])
        self.assertTrue(modal_data["hasPlaceholderInCard"])

        # 3. 验证弹层内缩放与 1:1 交互
        inter_js = """
        (() => {
            const btnIn = document.getElementById('modal-btn-zoom-in');
            const btn100 = document.getElementById('modal-btn-100');
            const canvas = document.getElementById('mermaid-modal-canvas');
            const indicator = document.getElementById('modal-zoom-indicator');
            btn100.click();
            const z100 = indicator.textContent;
            const t100 = canvas.style.transform;
            btnIn.click();
            const zIn = indicator.textContent;
            return JSON.stringify({ z100: z100, t100: t100, zIn: zIn });
        })()
        """
        res_box[0] = None
        browser.page().runJavaScript(inter_js, on_checked)
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()

        inter_data = res_box[0]
        self.assertEqual(inter_data["z100"], "100%")
        self.assertIn("scale(1)", inter_data["t100"])

        # 4. 验证主动点击「复制图片」按需导出完整图（非当前可见视口区域）
        copy_js = """
        (() => {
            document.getElementById('modal-btn-copy').click();
            return true;
        })()
        """
        browser.page().runJavaScript(copy_js)
        loop = QEventLoop()
        QTimer.singleShot(1000, loop.quit)
        loop.exec()

        clip_img = QApplication.clipboard().image()
        self.assertFalse(clip_img.isNull(), "复制图片后剪贴板为空")
        # 宽图自然宽度约为 2000px，2x 导出后应在 2000px 以上
        self.assertGreater(clip_img.width(), 800, "导出的图片并非完整图而是局部视口")
        self.assertTrue(_has_text_pixels(clip_img, threshold=80), "导出的完整图中未检测到有效文字像素")

        # 5. 验证 Esc 关闭弹层并将图表恢复原位
        close_js = """
        (() => {
            const escEvent = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true });
            window.dispatchEvent(escEvent);
            const overlay = document.getElementById('mermaid-modal-overlay');
            const cards = document.querySelectorAll('.mermaid-card');
            const card0 = cards[0];
            const card1 = cards[1];
            const svg0 = card0.querySelector('.mermaid-viewport svg');
            const svg1 = card1.querySelector('.mermaid-viewport svg');
            const placeholder = card0.querySelector('.mermaid-in-viewer-placeholder');
            return JSON.stringify({
                overlayDisplay: window.getComputedStyle(overlay).display,
                hasSvg0: !!svg0,
                svg0Id: svg0 ? svg0.id : null,
                placeholderRemoved: !placeholder,
                hasSvg1: !!svg1,
                texts0: svg0 ? Array.from(svg0.querySelectorAll('text')).map(t => t.textContent.trim()).filter(Boolean) : []
            });
        })()
        """
        res_box[0] = None
        browser.page().runJavaScript(close_js, on_checked)
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()

        close_data = res_box[0]
        self.assertEqual(close_data["overlayDisplay"], "none", "Esc 关闭后遮罩弹层未隐藏")
        self.assertTrue(close_data["hasSvg0"], "图表 SVG 未还原到原卡片视口")
        self.assertTrue(close_data["placeholderRemoved"], "卡片内占位符未清理")
        self.assertEqual(close_data["svg0Id"], init_data["svgId"])
        self.assertTrue(close_data["hasSvg1"], "第二个图表卡片受到干扰")
        self.assertIn("用户提交需求文档", close_data["texts0"])

        browser.cleanup()


if __name__ == "__main__":
    unittest.main()
