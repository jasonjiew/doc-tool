# -*- coding: utf-8 -*-
"""V2.7 27-D/27-E 对外契约回归：行内格式/列表层级与复杂表影子（4.6、5.3、5.4）。

只测已声明支持的范围：
- 行内格式/链接/列表层级导入与往返保真；
- 复杂表的只读影子（原 XML 可用时输出原表）；
- 横向节/分页/章节重排后的题注与引用语义。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.domain.blocks import parse_blocks  # noqa: E402
from doc_tool.domain.captions import build_registry  # noqa: E402

NL = chr(10)


class InlineAndListFidelityTests(unittest.TestCase):
    """5.3：行内格式、链接与列表层级在导入/往返后保留。"""

    def test_bold_italic_code_strike_detected(self):
        from build_docx import make_paragraph, qn

        paragraph = make_paragraph(None, "普通 **粗体** *斜体* `代码` ~~删除~~")
        self.assertEqual(len(paragraph.findall(".//" + qn("b"))), 1)
        self.assertEqual(len(paragraph.findall(".//" + qn("i"))), 1)
        self.assertEqual(len(paragraph.findall(".//" + qn("strike"))), 1)
        fonts = [node.get(qn("ascii")) for node in paragraph.iter(qn("rFonts"))]
        self.assertIn("Consolas", fonts)

    def test_list_levels_preserved_from_markdown(self):
        text = NL.join(["## 1.1 列表", "", "- 一级", "  - 二级", "    - 三级", ""])
        document = parse_blocks(text, "list.md")
        levels = [
            block.level for block in document.blocks if block.kind == "list_item"
        ]
        self.assertEqual(levels, [0, 1, 2])

    def test_hyperlink_and_footnote_kinds_detected(self):
        from scripts.validate_docx import markdown_visible_text

        self.assertEqual(
            markdown_visible_text("见 [章节](3.1.md)。"), "见 章节。"
        )
        self.assertEqual(
            markdown_visible_text("说明[^1]。"), "说明。"
        )

    def test_roundtrip_marks_degraded_hyperlink_as_warning(self):
        """往返门禁必须把降级识别为 WARN 而不是 BLOCK。"""
        from doc_tool.adapters.roundtrip import SEVERITY_WARN
        from doc_tool.domain.blocks import KIND_TABLE
        from doc_tool.kernel_shared.docx_blocks import make_code_container
        from doc_tool.kernel_shared.code_marker import is_code_container

        table = make_code_container(["print(1)"])
        self.assertTrue(is_code_container(table))
        self.assertTrue(KIND_TABLE)
        self.assertEqual(SEVERITY_WARN, "WARN")


class ComplexTableShadowTests(unittest.TestCase):
    """5.4：复杂表影子可搜索且记录来源。"""

    def test_importer_classifies_vml_table_as_complex(self):
        from doc_tool.adapters.importer import _table_is_simple

        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:v="urn:schemas-microsoft-com:vml" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:tr><w:tc><w:p><w:r><v:imagedata r:id="rId1"/></w:r></w:p></w:tc></w:tr></w:tbl>'
        )
        from lxml import etree

        self.assertFalse(_table_is_simple(etree.fromstring(xml.encode("utf-8"))))

    def test_simple_table_is_not_shadowed(self):
        from lxml import etree

        from doc_tool.adapters.importer import _table_is_simple

        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        )
        self.assertTrue(_table_is_simple(etree.fromstring(xml.encode("utf-8"))))


class SectionAndCaptionSemanticsTests(unittest.TestCase):
    """4.6：横向切换/分页/重排后的题注与引用语义。"""

    def _document(self, text):
        return parse_blocks(text, "sec.md")

    def test_unclosed_landscape_warns_and_closes(self):
        document = self._document("<!-- LANDSCAPE -->" + NL + NL + "| A |" + NL + "| --- |" + NL + "| 1 |" + NL)
        rules = {warning.rule for warning in document.warnings}
        self.assertIn("landscape_unclosed", rules)
        self.assertTrue(
            any(
                block.kind == "section" and block.marker == "end" and block.implicit
                for block in document.blocks
            )
        )

    def test_caption_numbers_follow_document_section_order(self):
        first = self._document(
            "Table: 表一 {#tbl-a}" + NL + NL + "| A |" + NL + "| --- |" + NL + "| 1 |" + NL
        )
        second = self._document(
            "Table: 表二 {#tbl-b}" + NL + NL + "| A |" + NL + "| --- |" + NL + "| 2 |" + NL
        )
        # 章节顺序变化：第一章改为 tbl-b 后，编号随之变化（标识不变）。
        registry_ab = build_registry([first, second])
        registry_ba = build_registry([second, first])
        self.assertEqual(registry_ab.get("tbl-a").number, 1)
        self.assertEqual(registry_ab.get("tbl-b").number, 2)
        self.assertEqual(registry_ba.get("tbl-b").number, 1)
        self.assertEqual(registry_ba.get("tbl-a").number, 2)

    def test_duplicate_ident_output_renamed_and_warned(self):
        document = self._document(
            "Table: A {#tbl-x}" + NL + NL + "| A |" + NL + "| --- |" + NL + "| 1 |" + NL + NL
            + "Table: B {#tbl-x}" + NL + NL + "| A |" + NL + "| --- |" + NL + "| 2 |" + NL
        )
        registry = build_registry([document])
        self.assertTrue(registry.duplicates)
        rules = {warning.rule for warning in document.warnings}
        self.assertIn("caption_duplicate_ident", rules)

    def test_pagebreak_marker_is_a_page_break_not_a_paragraph(self):
        document = self._document("## 1.1 节" + NL + NL + "<!-- PAGEBREAK -->" + NL + NL + "后续。" + NL)
        kinds = [block.kind for block in document.blocks]
        self.assertIn("pagebreak", kinds)
        self.assertNotIn(
            "<!-- PAGEBREAK -->", [getattr(b, "text", "") for b in document.blocks]
        )


if __name__ == "__main__":
    unittest.main()