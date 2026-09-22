# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest

from lxml import etree


SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

from build_docx import (  # noqa: E402
    NumberingManager,
    ExpressionManager,
    build,
    make_paragraph,
    parse_inline_runs,
    parse_list_line,
    qn,
    stable_bookmark_name,
)
from docx_common import (  # noqa: E402
    AutomationError,
    iter_chapter_entries,
    neutralize_dangling_hyperlinks,
    neutralize_hyperlink_fields,
    parse_image_reference,
    parse_markdown_table,
    validate_content_tree,
)
from validate_docx import markdown_visible_text


class MarkdownContractTests(unittest.TestCase):
    def test_table_escaped_pipe_backslash_and_break(self):
        rows = parse_markdown_table(
            [
                r"| 字段 | 内容 | 路径 |",
                r"| --- | --- | --- |",
                r"| A | 左\|右<br>下一行 | C:\\data |",
            ]
        )
        self.assertEqual(rows[1], ["A", "左|右\n下一行", r"C:\data"])

    def test_image_dimensions_are_optional(self):
        natural = parse_image_reference("![截图](images/a.png)")
        explicit = parse_image_reference("![截图](images/a.png =800x600)")
        self.assertEqual((natural.width_px, natural.height_px), (None, None))
        self.assertEqual((explicit.width_px, explicit.height_px), (800, 600))

    def test_br_becomes_real_word_break(self):
        paragraph = make_paragraph("4", "A\nB")
        self.assertEqual(len(paragraph.findall(".//" + qn("br"))), 1)
        self.assertNotIn("<br>", "".join(paragraph.itertext()))

    def test_inline_bold_italic_and_code_runs(self):
        paragraph = make_paragraph("4", "前**粗体***斜体*`code`后")
        runs = paragraph.findall(".//" + qn("r"))
        self.assertEqual("".join(paragraph.itertext()), "前粗体斜体code后")
        self.assertIsNotNone(runs[1].find(".//" + qn("b")))
        self.assertIsNotNone(runs[2].find(".//" + qn("i")))
        self.assertEqual(
            runs[3].find(".//" + qn("rFonts")).get(qn("ascii")), "Consolas"
        )

    def test_unclosed_inline_marker_stays_literal(self):
        self.assertEqual(parse_inline_runs("未闭合 **粗体"), [("未闭合 **粗体", "")])

    def test_bold_wildcard_and_multistar_stay_literal(self):
        # 通配符模式（如 ***.edf、**.tmp、/**/ 等）不应被误判为粗体
        text = "路径为 DATALOG/***.edf；结果集为 /***.tmp。"
        self.assertEqual(parse_inline_runs(text), [(text, "")])
        glob_text = "path1: dir/**/a and path2: dir/**/b"
        self.assertEqual(parse_inline_runs(glob_text), [(glob_text, "")])
        # 粗体标记紧跟空格不得作为定界符
        self.assertEqual(parse_inline_runs("** 不粗体 **"), [("** 不粗体 **", "")])

    def test_bold_with_punctuation_and_multisentence(self):
        # 包含句号、分号等标点的粗体跨度应正常保留为粗体样式
        text = "**注意：请确认配置；否则操作失败。**"
        self.assertEqual(parse_inline_runs(text), [("注意：请确认配置；否则操作失败。", "bold")])
        multi = "**第 1 步：备份数据。第 2 步：执行升级。**"
        self.assertEqual(parse_inline_runs(multi), [("第 1 步：备份数据。第 2 步：执行升级。", "bold")])

    def test_inline_bold_italic_three_asterisks(self):
        # ***加粗斜体*** 解析为 bold_italic 样式文本
        text = "***加粗斜体***"
        self.assertEqual(parse_inline_runs(text), [("加粗斜体", "bold_italic")])
        text_mixed = "前***加粗斜体***后"
        self.assertEqual(parse_inline_runs(text_mixed), [("前", ""), ("加粗斜体", "bold_italic"), ("后", "")])

    def test_inline_italic_in_chinese_sentence(self):
        # 中文字符之间的星号不应误判为乘号，首尾标点及全角括号也应正确支持
        text = "中文*斜体*测试"
        self.assertEqual(parse_inline_runs(text), [("中文", ""), ("斜体", "italic"), ("测试", "")])
        text_combo = "前**粗体**中*斜体*后"
        self.assertEqual(parse_inline_runs(text_combo), [("前", ""), ("粗体", "bold"), ("中", ""), ("斜体", "italic"), ("后", "")])
        text_paren = "（注意）*斜体文本*"
        self.assertEqual(parse_inline_runs(text_paren), [("（注意）", ""), ("斜体文本", "italic")])
        text_formula = "2*3 和 (a+b)*(c+d)"
        self.assertEqual(parse_inline_runs(text_formula), [(text_formula, "")])

    def test_inline_italic_with_punctuation(self):
        # 斜体跨度内包含常见标点符号应正常支持
        text = "*带有逗号，的斜体*"
        self.assertEqual(parse_inline_runs(text), [("带有逗号，的斜体", "italic")])
        text2 = "*带有一个句号。的斜体*"
        self.assertEqual(parse_inline_runs(text2), [("带有一个句号。的斜体", "italic")])
        text_multi_period = "*带有两个句号。另一个句号。*"
        self.assertEqual(parse_inline_runs(text_multi_period), [(text_multi_period, "")])

    def test_list_parser_requires_whitespace_and_tracks_indent(self):
        self.assertEqual(parse_list_line("  - 子项"), ("bullet", 1, 1, "子项"))
        self.assertEqual(parse_list_line("3. 起始"), ("decimal", 0, 3, "起始"))
        self.assertIsNone(parse_list_line("1、说明"))
        self.assertIsNone(parse_list_line("2.1 业务编号"))

    def test_numbering_manager_creates_true_multilevel_list(self):
        items = {
            "[Content_Types].xml": (
                b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
            )
        }
        manager = NumberingManager(items)
        first = manager.new_list("decimal", 3)
        second = manager.new_list("decimal", 1)
        manager.save()
        self.assertNotEqual(first, second)
        root = etree.fromstring(items["word/numbering.xml"])
        self.assertEqual(len(root.findall(qn("abstractNum"))), 2)
        starts = root.findall(".//" + qn("start"))
        self.assertEqual(starts[0].get(qn("val")), "3")
        paragraph = make_paragraph("4", "项目", num_id=first, list_level=2)
        self.assertEqual(paragraph.find(".//" + qn("numId")).get(qn("val")), str(first))
        self.assertEqual(paragraph.find(".//" + qn("ilvl")).get(qn("val")), "2")

    def test_stable_bookmark_name_is_deterministic(self):
        value = "章节/3.7.5 设备管理.md#图1"
        self.assertEqual(stable_bookmark_name(value), stable_bookmark_name(value))
        self.assertTrue(stable_bookmark_name(value).startswith("doc_"))

    def test_external_and_internal_hyperlinks(self):
        from build_docx import RP_NS, R_NS

        relationships = etree.Element(RP_NS + "Relationships")
        manager = ExpressionManager({}, relationships, [])
        target = os.path.abspath("target.md")
        manager.register_bookmark(target)
        paragraph = etree.Element(qn("p"))
        manager.append_hyperlink(paragraph, "官网", "https://example.com", "source.md", 3)
        manager.append_hyperlink(paragraph, "站内", target, "", 4)
        links = paragraph.findall(qn("hyperlink"))
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0].get(R_NS + "id"))
        self.assertEqual(links[1].get(qn("anchor")), manager.bookmarks[target])

    def test_internal_link_resolves_root_relative_and_by_name(self):
        from build_docx import RP_NS

        Entry = type("Entry", (), {"path": ""})
        md_a = "content/requirement/3.7.5 设备管理.md"
        md_b = "content/design/2.1 概述.md"
        relationships = etree.Element(RP_NS + "Relationships")
        manager = ExpressionManager(
            {}, relationships, [(Entry(), md_a), (Entry(), md_b)]
        )
        target_abs = os.path.abspath(md_a)
        manager.register_bookmark(target_abs)
        # 章节树「复制 Markdown 引用」生成的内容根相对链接
        paragraph = etree.Element(qn("p"))
        manager.append_hyperlink(
            paragraph, "设备管理", "requirement/3.7.5 设备管理.md", md_b, 3
        )
        links = paragraph.findall(qn("hyperlink"))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get(qn("anchor")), manager.bookmarks[target_abs])
        # 跨目录裸文件名链接按文件名反查
        paragraph2 = etree.Element(qn("p"))
        manager.append_hyperlink(paragraph2, "设备管理", "3.7.5 设备管理.md", md_b, 4)
        links2 = paragraph2.findall(qn("hyperlink"))
        self.assertEqual(len(links2), 1)
        self.assertEqual(links2[0].get(qn("anchor")), manager.bookmarks[target_abs])
        # 真正缺失的目标给出可定位警告，不生成失效超链接
        paragraph3 = etree.Element(qn("p"))
        manager.append_hyperlink(paragraph3, "缺失", "不存在的文件.md", md_b, 5)
        self.assertEqual(paragraph3.findall(qn("hyperlink")), [])
        self.assertEqual(len(manager.warnings), 1)
        self.assertIn("不存在的文件.md", manager.warnings[0])

    def test_footnote_reference_and_part_generation(self):
        from build_docx import CT_NS, RP_NS

        items = {
            "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        }
        relationships = etree.Element(RP_NS + "Relationships")
        manager = ExpressionManager(items, relationships, [])
        manager.footnote_defs["注1"] = "术语说明"
        paragraph = etree.Element(qn("p"))
        manager.append_footnote_reference(paragraph, "注1", "a.md", 1)
        manager.append_footnote_reference(paragraph, "缺失", "a.md", 2)
        manager.save_footnotes()
        self.assertIn("word/footnotes.xml", items)
        self.assertEqual(paragraph.find(".//" + qn("footnoteReference")).get(qn("id")), "1")
        self.assertTrue(any("脚注未定义" in warning for warning in manager.warnings))

    def test_minimal_build_emits_expression_parts_deterministically(self):
        from validate_docx import DocxPackage, validate

        with tempfile.TemporaryDirectory() as root:
            content = os.path.join(root, "content")
            assets = os.path.join(root, "assets")
            tables = os.path.join(assets, "tables")
            os.makedirs(content)
            os.makedirs(tables)
            chapter = os.path.join(content, "1 表达扩展.md")
            with open(chapter, "w", encoding="utf-8") as handle:
                handle.write(
                    "## 锚点\n"
                    "**粗体**、*斜体*、`code` 与 [官网](https://example.com)。\n"
                    "参见 [本章](1 表达扩展.md#锚点)。[^注1]\n"
                    "- 项目一\n"
                    "  - 子项目\n"
                    "3. 起始三\n"
                    "[^注1]: 脚注内容\n"
                )
            config = {
                "documentType": "general",
                "paths": {
                    "content_root": content,
                    "asset_root": assets,
                    "table_root": tables,
                    "template": os.path.join(os.path.dirname(SCRIPTS), "templates", "requirement-template.docx"),
                    "output": os.path.join(root, "one.docx"),
                },
                "headingStyles": {1: "2", 2: "3", 3: "5"},
                "bodyStyle": "4",
                "_base": root,
            }
            first = build(config=config)
            config["paths"]["output"] = os.path.join(root, "two.docx")
            second = build(config=config)
            package_one = DocxPackage(first, heading_styles=config["headingStyles"])
            package_two = DocxPackage(second, heading_styles=config["headingStyles"])
            self.assertEqual(package_one.expression_errors(), [])
            self.assertEqual(package_two.expression_errors(), [])
            for part in ("word/document.xml", "word/numbering.xml", "word/footnotes.xml"):
                self.assertIn(part, package_one.items)
                self.assertEqual(package_one.items[part], package_two.items[part])
            self.assertTrue(validate(output_override=second, config=config))


class TreeContractTests(unittest.TestCase):
    def make_config(self, root):
        content = os.path.join(root, "content")
        assets = os.path.join(root, "assets")
        tables = os.path.join(assets, "tables")
        os.makedirs(content)
        os.makedirs(tables)
        template = os.path.join(root, "template.docx")
        open(template, "wb").close()
        return {
            "paths": {
                "content_root": content,
                "asset_root": assets,
                "table_root": tables,
                "template": template,
            },
            "headingStyles": {1: "1", 2: "2", 3: "3"},
        }

    def test_index_is_parent_body_before_child(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.make_config(root)
            chapter = os.path.join(config["paths"]["content_root"], "第1章 A")
            os.makedirs(chapter)
            index = os.path.join(chapter, "_index.md")
            child = os.path.join(chapter, "1.1 B.md")
            with open(index, "w", encoding="utf-8") as handle:
                handle.write("父正文")
            with open(child, "w", encoding="utf-8") as handle:
                handle.write("子正文")
            validate_content_tree(config)
            sequence = list(iter_chapter_entries(config))
            self.assertEqual(sequence[0][1], index)
            self.assertEqual(sequence[1][1], child)

    def test_numbering_gap_fails_with_exact_suggestion(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.make_config(root)
            chapter = os.path.join(config["paths"]["content_root"], "第1章 A")
            os.makedirs(chapter)
            with open(os.path.join(chapter, "1.1 B.md"), "w", encoding="utf-8") as handle:
                handle.write("B")
            with open(os.path.join(chapter, "1.3 C.md"), "w", encoding="utf-8") as handle:
                handle.write("C")
            with self.assertRaisesRegex(AutomationError, r"实际预期编号为 1\.2"):
                validate_content_tree(config)

    def test_missing_image_is_fatal(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.make_config(root)
            chapter = os.path.join(config["paths"]["content_root"], "第1章 A")
            os.makedirs(chapter)
            with open(os.path.join(chapter, "1.1 B.md"), "w", encoding="utf-8") as handle:
                handle.write("![缺图](missing.png)")
            with self.assertRaisesRegex(AutomationError, "图片不存在"):
                validate_content_tree(config)



class NeutralizeHyperlinkFieldsTests(unittest.TestCase):
    """docx_common.neutralize_hyperlink_fields：解除 HYPERLINK 域为静态文本。"""

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def _document(self, body_xml: str):
        xml = (
            '<w:document xmlns:w="{0}"><w:body>{1}</w:body></w:document>'
        ).format(self.W, body_xml)
        return etree.fromstring(xml.encode("utf-8"))

    def _text(self, document) -> str:
        return "".join(document.itertext())

    def _fldchar_count(self, document) -> int:
        return len(document.findall(".//" + qn("fldChar")))

    def test_simple_hyperlink_field_unlinked(self):
        body = (
            '<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText> HYPERLINK \l "_Toc123" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>可见链接文字</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 1)
        self.assertEqual(self._text(document), "可见链接文字")
        self.assertEqual(self._fldchar_count(document), 0)

    def test_end_run_in_next_paragraph(self):
        body = (
            '<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText> HYPERLINK \l "_Toc1" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>跨段链接</w:t></w:r>'
            '</w:p>'
            '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 1)
        self.assertEqual(self._text(document), "跨段链接")

    def test_nested_pageref_inside_toc_not_touched(self):
        body = (
            '<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText> TOC \o "1-3" \h \z \u </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>目录缓存</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText> PAGEREF _Toc1 \h </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>1</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 0)
        # TOC 域 3 个 fldChar + 嵌套 PAGEREF 域 3 个 = 6，全部保留。
        self.assertEqual(self._fldchar_count(document), 6)

    def test_fldsimple_hyperlink_unlinked(self):
        body = (
            '<w:p>'
            r'<w:fldSimple w:instr=" HYPERLINK \l &quot;_Toc9&quot; ">'
            '<w:r><w:t>简单链接</w:t></w:r>'
            '</w:fldSimple>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 1)
        self.assertEqual(self._text(document), "简单链接")
        self.assertEqual(len(document.findall(".//" + qn("fldSimple"))), 0)

    def test_field_runs_wrapped_in_hyperlink_element(self):
        # 域运行被 w:hyperlink 元素包裹（Word 修订表常见）：必须仍能配对解除。
        body = (
            '<w:p>'
            '<w:hyperlink w:anchor="_Toc7">'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText> HYPERLINK \l "_Toc7" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>包裹链接</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 1)
        self.assertEqual(self._text(document), "包裹链接")
        self.assertEqual(len(document.findall(".//" + qn("hyperlink"))), 1)
        self.assertEqual(self._fldchar_count(document), 0)

    def test_native_hyperlink_without_field_untouched(self):
        body = (
            '<w:p>'
            '<w:hyperlink w:anchor="_Toc3"><w:r><w:t>原生链接</w:t></w:r></w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 0)
        self.assertEqual(self._text(document), "原生链接")

    def test_non_hyperlink_field_untouched(self):
        body = (
            '<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText> NUMPAGES \* MERGEFORMAT </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>12</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_hyperlink_fields(document)
        self.assertEqual(removed, 0)
        self.assertEqual(self._text(document).strip(), "NUMPAGES \\* MERGEFORMAT 12")



class NeutralizeDanglingHyperlinksTests(unittest.TestCase):
    """docx_common.neutralize_dangling_hyperlinks 解除指向不存在书签的原生超链接。"""

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def _document(self, body_xml: str):
        xml = (
            '<w:document xmlns:w="{0}" xmlns:r="{1}"><w:body>{2}</w:body></w:document>'
        ).format(self.W, self.R, body_xml)
        return etree.fromstring(xml.encode("utf-8"))

    def _text(self, document) -> str:
        return "".join(document.itertext())

    def test_dangling_hyperlink_unlinked_when_bookmark_missing(self):
        body = (
            '<w:p>'
            '<w:hyperlink w:anchor="_Toc211330744">'
            '<w:r><w:t>6.2.3 漏气量、压力</w:t></w:r>'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 1)
        self.assertEqual(self._text(document), "6.2.3 漏气量、压力")
        self.assertEqual(len(document.findall(".//" + qn("hyperlink"))), 0)
        p = document.find(".//" + qn("p"))
        self.assertEqual(len(p.findall(qn("r"))), 1)

    def test_valid_hyperlink_preserved_when_bookmark_exists(self):
        body = (
            '<w:p>'
            '<w:bookmarkStart w:id="10" w:name="doc_valid_bm"/>'
            '<w:bookmarkEnd w:id="10"/>'
            '<w:hyperlink w:anchor="doc_valid_bm">'
            '<w:r><w:t>有效链接</w:t></w:r>'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 0)
        self.assertEqual(len(document.findall(".//" + qn("hyperlink"))), 1)

    def test_external_hyperlink_with_rid_preserved(self):
        body = (
            '<w:p>'
            '<w:hyperlink r:id="rId5">'
            '<w:r><w:t>外部链接</w:t></w:r>'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 0)
        self.assertEqual(len(document.findall(".//" + qn("hyperlink"))), 1)

    def test_custom_available_bookmarks_iterable(self):
        body = (
            '<w:p>'
            '<w:hyperlink w:anchor="bm1"><w:r><w:t>1</w:t></w:r></w:hyperlink>'
            '<w:hyperlink w:anchor="bm2"><w:r><w:t>2</w:t></w:r></w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document, available_bookmarks=["bm1"])
        self.assertEqual(removed, 1)
        hls = document.findall(".//" + qn("hyperlink"))
        self.assertEqual(len(hls), 1)
        self.assertEqual(hls[0].get(qn("anchor")), "bm1")

    def test_markdown_visible_text_preserves_multiplication_across_breaks(self):
        sample = (
            "单次呼气结束时漏气量计算：数据长度*0.5...<br>"
            "单次吸气结束时漏气量计算：数据长度*0.95..."
        )
        res = markdown_visible_text(sample)
        self.assertIn("数据长度*0.5", res)
        self.assertIn("数据长度*0.95", res)

        sample_crlf = "行1：a*b\r\n行2：c*d"
        res_crlf = markdown_visible_text(sample_crlf)
        self.assertIn("a*b", res_crlf)
        self.assertIn("c*d", res_crlf)

    def test_expression_manager_avoids_template_bookmark_id_collision(self):
        from build_docx import RP_NS
        body = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:bookmarkStart w:id="36" w:name="_TocExisting"/>'
            '<w:bookmarkEnd w:id="36"/>'
            '</w:body>'
            '</w:document>'
        )
        items = {"word/document.xml": body.encode("utf-8")}
        relationships = etree.Element(RP_NS + "Relationships")
        mgr = ExpressionManager(items, relationships, [])
        self.assertGreaterEqual(mgr.next_bookmark_id, 37)
        self.assertIn("_TocExisting", mgr.bookmark_names)

    def test_external_hyperlink_with_rid_and_anchor_preserved(self):
        # 外部链接同时包含 r:id 与 w:anchor（指向外部文档目标中的片段），不得误解为悬空本地书签
        body = (
            '<w:p>'
            '<w:hyperlink r:id="rId8" w:anchor="ext_sec">'
            '<w:r><w:t>外部文档锚点</w:t></w:r>'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 0)
        self.assertEqual(len(document.findall(".//" + qn("hyperlink"))), 1)

    def test_dangling_hyperlink_preserves_tail_text(self):
        # 解除悬空超链接时，必须完整保留 hl.tail 文本，避免 lxml remove 丢失后续内容
        body = (
            '<w:p>'
            '<w:hyperlink w:anchor="missing_bm">'
            '<w:r><w:t>主正文</w:t></w:r>'
            '</w:hyperlink>【后续说明】'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 1)
        self.assertIn("主正文", self._text(document))
        self.assertIn("【后续说明】", self._text(document))

    def test_dangling_hyperlink_with_direct_text(self):
        # 超链接节点若含直接 text 文本（非 run 子节点），解除时必须保留
        body = (
            '<w:p>'
            '<w:hyperlink w:anchor="missing_bm">直接文本'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 1)
        self.assertIn("直接文本", self._text(document))

    def test_empty_hyperlink_without_target_unlinked(self):
        # 既无 r:id 也无 anchor 的空超链接包装视为无效链接，安全解除
        body = (
            '<w:p>'
            '<w:hyperlink>'
            '<w:r><w:t>无目标链接</w:t></w:r>'
            '</w:hyperlink>'
            '</w:p>'
        )
        document = self._document(body)
        removed = neutralize_dangling_hyperlinks(document)
        self.assertEqual(removed, 1)
        self.assertEqual(self._text(document), "无目标链接")
        self.assertEqual(len(document.findall(".//" + qn("hyperlink"))), 0)

    def test_expression_manager_scans_all_parts_for_bookmark_ids(self):
        from build_docx import RP_NS
        doc_body = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:bookmarkStart w:id="10" w:name="_DocBm"/>'
            '<w:bookmarkEnd w:id="10"/>'
            '</w:body>'
            '</w:document>'
        )
        fn_body = (
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:footnote w:id="1">'
            '<w:bookmarkStart w:id="55" w:name="_FootnoteBm"/>'
            '<w:bookmarkEnd w:id="55"/>'
            '</w:footnote>'
            '</w:footnotes>'
        )
        items = {
            "word/document.xml": doc_body.encode("utf-8"),
            "word/footnotes.xml": fn_body.encode("utf-8"),
        }
        relationships = etree.Element(RP_NS + "Relationships")
        mgr = ExpressionManager(items, relationships, [])
        self.assertGreaterEqual(mgr.next_bookmark_id, 56)
        self.assertIn("_DocBm", mgr.bookmark_names)
        self.assertIn("_FootnoteBm", mgr.bookmark_names)

    def test_expression_errors_ignores_external_hyperlink_anchor(self):
        # 验证 DocxPackage.expression_errors：外部链接带锚点不被判定为缺失本地书签
        from validate_docx import DocxPackage
        doc_xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:body>'
            '<w:p><w:hyperlink r:id="rId1" w:anchor="remote_target"><w:r><w:t>外部锚点</w:t></w:r></w:hyperlink></w:p>'
            '</w:body></w:document>'
        ).encode("utf-8")
        rels_xml = (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            'Target="http://example.com/doc.html" TargetMode="External"/>'
            '</Relationships>'
        ).encode("utf-8")
        pkg = DocxPackage.__new__(DocxPackage)
        pkg.items = {"word/document.xml": doc_xml, "word/_rels/document.xml.rels": rels_xml}
        pkg.xml_roots = {
            "word/document.xml": etree.fromstring(doc_xml),
            "word/_rels/document.xml.rels": etree.fromstring(rels_xml),
        }
        pkg.document = pkg.xml_roots["word/document.xml"]
        pkg.relationship_map = {"rId1": "http://example.com/doc.html"}
        errors = pkg.expression_errors()
        self.assertEqual(errors, [])

    def test_header_footer_signatures_preserves_order_mixed_fields(self):
        # 验证 _header_footer_signatures 在 fldSimple 与 fldChar 混合时按文档顺序提取
        from validate_docx import _header_footer_signatures, DocxPackage
        # 模板态：instrText(DATE) -> fldSimple(PAGE) -> instrText(NUMPAGES)
        tpl_hdr = (
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> DATE </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>2026</w:t><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
            '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> NUMPAGES </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>10</w:t><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:p>'
            '</w:hdr>'
        ).encode("utf-8")
        # 刷新后态：Word 将 fldSimple(PAGE) 展开为标准的 fldChar(PAGE)
        refreshed_hdr = (
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> DATE </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>2026</w:t><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> PAGE </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>1</w:t><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> NUMPAGES </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>10</w:t><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:p>'
            '</w:hdr>'
        ).encode("utf-8")

        pkg_tpl = DocxPackage.__new__(DocxPackage)
        pkg_tpl.items = {"word/header1.xml": tpl_hdr}
        pkg_tpl.xml_roots = {"word/header1.xml": etree.fromstring(tpl_hdr)}

        pkg_ref = DocxPackage.__new__(DocxPackage)
        pkg_ref.items = {"word/header1.xml": refreshed_hdr}
        pkg_ref.xml_roots = {"word/header1.xml": etree.fromstring(refreshed_hdr)}

        sig_tpl = _header_footer_signatures(pkg_tpl, "word/header")
        sig_ref = _header_footer_signatures(pkg_ref, "word/header")
        self.assertEqual(sig_tpl, sig_ref)




class HyperlinkOOXMLStructureAndJumpTests(unittest.TestCase):
    """测试 Word 内部超链接 OOXML 标准结构、样式与跳转语法。"""

    def test_hyperlink_ooxml_structure_and_style(self):
        from build_docx import RP_NS, R_NS, qn

        relationships = etree.Element(RP_NS + "Relationships")
        manager = ExpressionManager({}, relationships, [])
        target = os.path.abspath("content/3.1.md")
        manager.register_bookmark(target)
        paragraph = etree.Element(qn("p"))

        manager.append_hyperlink(paragraph, "外部链接", "https://example.com", "source.md", 1)
        manager.append_hyperlink(paragraph, "站内章节", target, "source.md", 2)

        links = paragraph.findall(qn("hyperlink"))
        self.assertEqual(len(links), 2)

        # 1. 检验 w:history="1"
        self.assertEqual(links[0].get(qn("history")), "1")
        self.assertEqual(links[1].get(qn("history")), "1")

        # 2. 外部与内部目标规范
        self.assertTrue(links[0].get(R_NS + "id"))
        self.assertEqual(links[1].get(qn("anchor")), manager.bookmarks[target])

        # 3. 检验内部 run 的字符样式与格式
        for hl in links:
            runs = hl.findall(qn("r"))
            self.assertGreaterEqual(len(runs), 1)
            for r in runs:
                rpr = r.find(qn("rPr"))
                self.assertIsNotNone(rpr, "超链接 run 必须包含 rPr")
                rstyle = rpr.find(qn("rStyle"))
                self.assertIsNotNone(rstyle, "超链接 run 必须包含 rStyle")
                self.assertEqual(rstyle.get(qn("val")), manager.hyperlink_style_id)
                color = rpr.find(qn("color"))
                self.assertIsNotNone(color)
                self.assertEqual(color.get(qn("val")), "0563C1")
                u = rpr.find(qn("u"))
                self.assertIsNotNone(u)
                self.assertEqual(u.get(qn("val")), "single")

    def test_jump_to_current_chapter_and_section_fallbacks(self):
        from build_docx import RP_NS, qn

        relationships = etree.Element(RP_NS + "Relationships")
        manager = ExpressionManager({}, relationships, [])
        cur_file = os.path.abspath("content/3.2.md")
        cur_bm = manager.register_bookmark(cur_file)
        ch3_bm = manager.register_bookmark("content/ch3")
        sec34_bm = manager.register_bookmark("content/3.4")
        manager.section_number_map["第3章"] = ch3_bm
        manager.section_number_map["3"] = ch3_bm
        manager.section_number_map["3.4"] = sec34_bm

        p = etree.Element(qn("p"))

        # 1. 跳转本章节（使用 "#", ".", "本章节" 等语法）
        manager.append_hyperlink(p, "本章节", "#", cur_file, 1)
        manager.append_hyperlink(p, "跳转本章节", "本章节", cur_file, 2)
        manager.append_hyperlink(p, "本节", ".", cur_file, 3)

        # 2. 章节号与标题智能查找
        manager.append_hyperlink(p, "小节3.4", "3.4", cur_file, 4)
        manager.append_hyperlink(p, "第三章总览", "第3章", cur_file, 5)

        hls = p.findall(qn("hyperlink"))
        self.assertEqual(len(hls), 5)
        self.assertEqual(hls[0].get(qn("anchor")), cur_bm)
        self.assertEqual(hls[1].get(qn("anchor")), cur_bm)
        self.assertEqual(hls[2].get(qn("anchor")), cur_bm)
        self.assertEqual(hls[3].get(qn("anchor")), sec34_bm)
        self.assertEqual(hls[4].get(qn("anchor")), ch3_bm)

    def test_dynamic_hyperlink_style_id_from_styles_xml(self):
        from build_docx import RP_NS, qn

        # 模板样式 id 为 51 的情况
        styles_51 = (
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="character" w:styleId="51"><w:name w:val="Hyperlink"/></w:style>'
            '</w:styles>'
        ).encode('utf-8')
        m51 = ExpressionManager({"word/styles.xml": styles_51}, etree.Element(RP_NS + "Relationships"), [])
        self.assertEqual(m51.hyperlink_style_id, "51")

        # 模板样式 id 为 53 的情况
        styles_53 = (
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="character" w:styleId="53"><w:name w:val="Hyperlink"/></w:style>'
            '</w:styles>'
        ).encode('utf-8')
        m53 = ExpressionManager({"word/styles.xml": styles_53}, etree.Element(RP_NS + "Relationships"), [])
        self.assertEqual(m53.hyperlink_style_id, "53")

        # 默认无 styles.xml 回退
        m_def = ExpressionManager({}, etree.Element(RP_NS + "Relationships"), [])
        self.assertEqual(m_def.hyperlink_style_id, "Hyperlink")

    def test_revision_summary_cell_hyperlink_structure(self):
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpr:
            hyperlink_style_id = "51"
            bookmarks = {}
            def find_bookmark_for_section(self, tok):
                return "bm_ch3" if "3" in tok else None

        cell = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell, "新增：第3章 蓝牙交互", FakeExpr())

        hls = cell.findall(".//" + qn("hyperlink"))
        self.assertEqual(len(hls), 1)
        hl = hls[0]
        self.assertEqual(hl.get(qn("anchor")), "bm_ch3")
        self.assertEqual(hl.get(qn("history")), "1")

        r = hl.find(qn("r"))
        self.assertIsNotNone(r)
        rpr = r.find(qn("rPr"))
        self.assertIsNotNone(rpr)
        self.assertEqual(rpr.find(qn("rStyle")).get(qn("val")), "51")
        self.assertEqual(rpr.find(qn("color")).get(qn("val")), "0563C1")
        self.assertEqual(rpr.find(qn("u")).get(qn("val")), "single")


    def test_rpr_child_element_order_canonical_ooxml(self):
        """测试超链接与格式化文本的 rPr 子元素严格遵循 OOXML CT_RPr 顺序：rStyle -> rFonts/b/i -> color -> u。"""
        from build_docx import _append_styled_run, qn, RPR_TAG_INDEX

        parent = etree.Element(qn("p"))
        # 混合超链接 + 粗体
        _append_styled_run(parent, "加粗超链接", style="bold", is_hyperlink=True, hyperlink_style_id="51")
        r = parent.find(qn("r"))
        rpr = r.find(qn("rPr"))
        self.assertIsNotNone(rpr)
        children = list(rpr)
        tag_indices = [RPR_TAG_INDEX[c.tag] for c in children]
        self.assertEqual(tag_indices, sorted(tag_indices), f"rPr 子元素未按规范顺序排列: {[c.tag for c in children]}")
        self.assertEqual(children[0].tag, qn("rStyle"))
        self.assertEqual(children[0].get(qn("val")), "51")
        self.assertEqual(children[1].tag, qn("b"))
        self.assertEqual(children[2].tag, qn("color"))
        self.assertEqual(children[3].tag, qn("u"))

    def test_cross_file_and_section_anchor_resolution_not_swallowed(self):
        """测试锚点链接（如 #3.4、#第3章、#蓝牙配对）不会被当前文件起始书签错误吞噬。"""
        from build_docx import ExpressionManager, RP_NS, qn

        relationships = etree.Element(RP_NS + "Relationships")
        mgr = ExpressionManager({}, relationships, [])
        source_file = os.path.abspath("content/1.1.md")
        ch1_file = os.path.abspath("content/ch1.md")
        sec34_file = os.path.abspath("content/3.4.md")

        src_bm = mgr.register_bookmark(source_file)
        sec34_bm = mgr.register_bookmark(sec34_file)
        ch3_bm = mgr.register_bookmark("content/ch3")
        heading_bm = mgr.register_bookmark(source_file + "#配对说明")

        mgr.section_number_map["3.4"] = sec34_bm
        mgr.section_number_map["第3章"] = ch3_bm
        mgr.section_title_map["呼吸机同步时区"] = sec34_bm

        p = etree.Element(qn("p"))

        # 1. 跨小节锚点：#3.4 必须跳转到 3.4，不能落回 source_file 的书签
        mgr.append_hyperlink(p, "查看3.4", "#3.4", source_file, 1)
        # 2. 跨大章锚点：#第3章 必须跳转到 第3章
        mgr.append_hyperlink(p, "查看第3章", "#第3章", source_file, 2)
        # 3. 标题锚点：#配对说明 精确命中文件内标题
        mgr.append_hyperlink(p, "配对说明", "#配对说明", source_file, 3)
        # 4. 跨小节标题锚点：#呼吸机同步时区 命中 3.4
        mgr.append_hyperlink(p, "同步时区", "#呼吸机同步时区", source_file, 4)

        hls = p.findall(qn("hyperlink"))
        self.assertEqual(len(hls), 4)
        self.assertEqual(hls[0].get(qn("anchor")), sec34_bm)
        self.assertEqual(hls[1].get(qn("anchor")), ch3_bm)
        self.assertEqual(hls[2].get(qn("anchor")), heading_bm)
        self.assertEqual(hls[3].get(qn("anchor")), sec34_bm)

    def test_parent_chapter_bookmark_resolution_for_subsections(self):
        """测试多级目录下子文件通过 '#本章' 或 '本章节' 精确跳转到所属第1级父章节。"""
        from build_docx import ExpressionManager, RP_NS, qn
        from docx_common import ChapterEntry

        relationships = etree.Element(RP_NS + "Relationships")
        entries = [
            (ChapterEntry("dir", (1,), "引言", "D:/content/01_intro", 1), None),
            (ChapterEntry("file", (1, 1), "目的", "D:/content/01_intro/1.1_purpose.md", 2), "D:/content/01_intro/1.1_purpose.md"),
            (ChapterEntry("dir", (2,), "功能设计", "D:/content/02_design", 1), None),
            (ChapterEntry("file", (2, 1), "登录", "D:/content/02_design/2.1_login.md", 2), "D:/content/02_design/2.1_login.md"),
        ]
        mgr = ExpressionManager({}, relationships, entries)
        ch1_bm = mgr.bookmarks[os.path.abspath("D:/content/01_intro")]
        sub11_bm = mgr.bookmarks[os.path.abspath("D:/content/01_intro/1.1_purpose.md")]
        sub11_file = "D:/content/01_intro/1.1_purpose.md"

        p = etree.Element(qn("p"))
        # 本章 / 本章节 -> 父章节第1章
        mgr.append_hyperlink(p, "返回本章", "#本章", sub11_file, 1)
        mgr.append_hyperlink(p, "跳转本章节", "#本章节", sub11_file, 2)
        mgr.append_hyperlink(p, "顶部", "#", sub11_file, 3)
        # 本节 -> 子文件自身 1.1
        mgr.append_hyperlink(p, "回到本节", "#本节", sub11_file, 4)

        hls = p.findall(qn("hyperlink"))
        self.assertEqual(len(hls), 4)
        self.assertEqual(hls[0].get(qn("anchor")), ch1_bm)
        self.assertEqual(hls[1].get(qn("anchor")), ch1_bm)
        self.assertEqual(hls[2].get(qn("anchor")), ch1_bm)
        self.assertEqual(hls[3].get(qn("anchor")), sub11_bm)

    def test_find_bookmark_for_section_disambiguation(self):
        """测试 find_bookmark_for_section 不会把带标题的多级小节（如 '1.1 目的'、'3.4 同步'）误识别为第1章或第3章。"""
        from build_docx import ExpressionManager, RP_NS
        from docx_common import ChapterEntry

        entries = [
            (ChapterEntry("dir", (1,), "引言", "D:/content/ch1", 1), None),
            (ChapterEntry("file", (1, 1), "目的", "D:/content/ch1/1.1.md", 2), "D:/content/ch1/1.1.md"),
            (ChapterEntry("dir", (3,), "设备", "D:/content/ch3", 1), None),
            (ChapterEntry("file", (3, 4), "呼吸机同步时区", "D:/content/ch3/3.4.md", 2), "D:/content/ch3/3.4.md"),
        ]
        mgr = ExpressionManager({}, etree.Element(RP_NS + "Relationships"), entries)
        ch1_bm = mgr.section_number_map["第1章"]
        sub11_bm = mgr.section_number_map["1.1"]
        ch3_bm = mgr.section_number_map["第3章"]
        sub34_bm = mgr.section_number_map["3.4"]

        # 验证 1.1 与 1.1 目的 不会被截断为 1
        self.assertEqual(mgr.find_bookmark_for_section("1.1"), sub11_bm)
        self.assertEqual(mgr.find_bookmark_for_section("1.1 目的"), sub11_bm)
        self.assertEqual(mgr.find_bookmark_for_section("1.1 目的.md"), sub11_bm)
        self.assertEqual(mgr.find_bookmark_for_section("目的"), sub11_bm)

        # 验证 3.4 与 3.4 呼吸机同步时区 不会被截断为 3
        self.assertEqual(mgr.find_bookmark_for_section("3.4"), sub34_bm)
        self.assertEqual(mgr.find_bookmark_for_section("3.4 呼吸机同步时区"), sub34_bm)
        self.assertEqual(mgr.find_bookmark_for_section("3.4 呼吸机同步时区.md"), sub34_bm)
        self.assertEqual(mgr.find_bookmark_for_section("呼吸机同步时区"), sub34_bm)

        # 验证单数字与大章仍准确匹配大章
        self.assertEqual(mgr.find_bookmark_for_section("1"), ch1_bm)
        self.assertEqual(mgr.find_bookmark_for_section("第1章"), ch1_bm)
        self.assertEqual(mgr.find_bookmark_for_section("3"), ch3_bm)
        self.assertEqual(mgr.find_bookmark_for_section("第3章"), ch3_bm)


    def test_punctuation_and_range_normalization(self):
        """测试全角半角标点、数值区间波浪号与正负号等语义等价。"""
        from docx_common import _is_event_text_equivalent
        pairs = [
            ("取值范围：0～100", "取值范围: 0~100"),
            ("参数说明（可选）：中值", "参数说明(可选): 中值"),
            ("误差范围：-1－2", "误差范围: -1-2"),
            ("【注】详见通用响应数据包", "[注] 详见通用响应数据包"),
            ("数据长度 * 0.5", "数据长度*0.5"),
            ("2 * 3 = 6", "2*3=6"),
            ("系数 × 10", "系数 * 10"),
            ("状态: 正常；结果: 成功，耗时: 10ms", "状态：正常; 结果：成功, 耗时：10ms"),
        ]
        for a, b in pairs:
            self.assertTrue(_is_event_text_equivalent(a, b), f"Should be equivalent: {a} vs {b}")

    def test_strip_manual_prefix_letters_and_roman(self):
        """测试字母序号与罗马数字列表前缀识别剥离。"""
        from docx_common import _strip_manual_prefix
        cases = [
            ("a. 数据格式说明", "数据格式说明"),
            ("A. 数据格式说明", "数据格式说明"),
            ("b) 校验位计算", "校验位计算"),
            ("(c) 附录参考", "附录参考"),
            ("（d） 附录参考", "附录参考"),
            ("(i) 第一次迭代", "第一次迭代"),
            ("1.5 伏特电压", "1.5 伏特电压"),  # 小数不误剥离
            ("- 普通列表项", "普通列表项"),
            ("1. 正式条款", "正式条款"),
        ]
        for src, expected in cases:
            self.assertEqual(_strip_manual_prefix(src), expected)

    def test_output_filename_deduplication(self):
        """测试升级版本时避免重复拼接版本号括号（如 (1.6)(1.7).docx）。"""
        from doc_tool.domain.paths import build_output_filename
        # 场景 1：documentName 带旧版本 (1.6)，升级为 1.7
        fn1 = build_output_filename(
            "DOC-2090-4-003",
            "DOC-2090-4-003 设备通信协议说明书(1.6)",
            "1.7",
            "general",
        )
        self.assertEqual(fn1, "DOC-2090-4-003 设备通信协议说明书(1.7).docx")

        # 场景 2：documentName 已带当前版本 (1.7)
        fn2 = build_output_filename(
            "DOC-2090-4-003",
            "DOC-2090-4-003 设备通信协议说明书(1.7)",
            "1.7",
            "general",
        )
        self.assertEqual(fn2, "DOC-2090-4-003 设备通信协议说明书(1.7).docx")

        # 场景 3：无版本号后缀
        fn3 = build_output_filename(
            "DOC-2090-4-003",
            "设备通信协议说明书",
            "1.7",
            "general",
        )
        self.assertEqual(fn3, "DOC-2090-4-003 设备通信协议说明书(1.7).docx")

    def test_markdown_visible_text_italics_with_space(self):
        """测试 Markdown 行内斜体含空格时与 build_docx 生成的可见文本一致。"""
        from validate_docx import markdown_visible_text
        from build_docx import parse_inline_runs
        text = "这是 *Hello World* 说明，带公式 *0.5* 与 2*3=6 以及 `code` 和 **bold**"
        runs = parse_inline_runs(text)
        docx_text = "".join(t for t, _ in runs)
        vis_text = markdown_visible_text(text)
        self.assertEqual(docx_text, vis_text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
