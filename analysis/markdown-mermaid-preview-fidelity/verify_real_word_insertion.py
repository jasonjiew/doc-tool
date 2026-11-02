# -*- coding: utf-8 -*-
"""验证真实 Word (Office 16) 插入高保真 Mermaid PNG（Task 9.3：REQ-MM-05）。"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    renderer = get_official_mermaid_renderer()
    if not renderer._page_ready:
        loop = QEventLoop()
        renderer._view.loadFinished.connect(lambda ok: loop.quit())
        QTimer.singleShot(6000, loop.quit)
        loop.exec()

    source = """flowchart TD
        subgraph 支付结算中台 [核心业务系统]
            A["客户提交付款指令<br/>(含汇率结算)"] --> B{"风险合规引擎<br/><b>实时决策</b>"}
            B -- 合规通过 --> C[调拨资金头寸]
            B -- 拦截告警 --> D[触发反洗钱复核]
            C --> E[更新总账分户账]
        end
        style A fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
        style C fill:#e8f8f5,stroke:#2ecc71,stroke-width:2px;
    """

    res = renderer.render(source, want_png=True, theme="default")
    assert res.ok, f"Render failed: {res.error}"
    assert res.png, "Missing PNG"

    img_path = HERE / "word_verified_mermaid.png"
    img_path.write_bytes(res.png)
    print(f"Generated official PNG: {img_path} ({len(res.png)} bytes), logical: {res.width}x{res.height}")

    # 使用 docx 写入包含图片引用的测试文档
    import docx
    from docx.shared import Inches, Pt

    doc = docx.Document()
    doc.add_heading("Mermaid 真实 Word 插入保真度验证报告", level=1)
    doc.add_paragraph("本章节验证官方 Mermaid 11.16.1 离线生成的 PNG 图片在 Microsoft Word 16.0 中的显示效果。")
    doc.add_paragraph(f"图形逻辑尺寸：{res.width} pt × {res.height} pt；图片像素大小：{len(res.png)} 字节。")

    # 按照 72 pt = 1 inch 换算逻辑尺寸插入
    doc.add_picture(str(img_path), width=Pt(res.width), height=Pt(res.height))
    doc.add_paragraph("图 1：支付结算中台核心流程图（官方 Mermaid 高保真渲染）")

    docx_path = HERE / "word_insertion_verified.docx"
    doc.save(str(docx_path))
    print(f"Saved DOCX: {docx_path}")

    # 调用真实 Word COM 验证文档无损打开、内嵌图形与尺寸
    import win32com.client
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    try:
        word_doc = word.Documents.Open(str(docx_path.resolve()))
        shape_count = word_doc.InlineShapes.Count
        print(f"Real Word opened document successfully. InlineShapes count: {shape_count}")
        assert shape_count >= 1, "Word document should contain at least 1 inline shape"
        shape = word_doc.InlineShapes(1)
        w_pt = round(shape.Width, 1)
        h_pt = round(shape.Height, 1)
        print(f"Real Word shape layout dimensions: {w_pt} pt x {h_pt} pt (expected: {res.width} x {res.height})")
        # 尺寸误差小于 1 pt
        assert abs(w_pt - res.width) < 1.0, f"Width mismatch: {w_pt} vs {res.width}"
        assert abs(h_pt - res.height) < 1.0, f"Height mismatch: {h_pt} vs {res.height}"
        word_doc.Close(False)
        print("REAL_WORD_VERIFICATION_PASSED")
    finally:
        word.Quit()

if __name__ == "__main__":
    main()
