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
    parse_image_reference,
    parse_markdown_table,
    validate_content_tree,
)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
