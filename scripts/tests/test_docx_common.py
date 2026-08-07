# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest

from lxml import etree


SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

from build_docx import make_paragraph, qn  # noqa: E402
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
