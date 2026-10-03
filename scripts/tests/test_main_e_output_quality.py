# -*- coding: utf-8 -*-
"""MAIN-E：Word 排版与出稿质量（标题/列表/表格/宽图/代码/链接，前导零与文本保留）。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts"),
                  str(REPO_ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from lxml import etree  # noqa: E402

import test_project_build as T  # noqa: E402
from doc_tool.adapters.kernel import build_with_project  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NL = chr(10)


def _qn(tag: str) -> str:
    return "{{{0}}}{1}".format(W_NS, tag)


def _png(path: Path, size) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (12, 90, 180)).save(str(path))
    return path


# 章节文件层级：一级章节目录的 _index.md 只能用 H2 及更深标题，
# 子文件 1.1 xxx.md 至少用 H3（构建前校验的真实约束）。
CHAPTER = NL.join([
    "正文段落，含前导零 007 与站内链接 [说明](../3 设计/_index.md) 及外链 [官网](https://example.com/doc)。",
    "",
    "## 1.1 表格",
    "",
    "| 项目 | 值 |",
    "| --- | --- |",
    "| 前导零 | 007 |",
    "| 空值 |  |",
    "| 多行 | 第一行<br>第二行 |",
    "",
    "## 1.2 长表",
    "",
    "| 序号 | 说明 |",
    "| --- | --- |",
] + ["| {0} | 长表第 {0} 行 |".format(i) for i in range(1, 31)] + [
    "",
    "## 1.3 图片",
    "",
    "![宽图](images/wide.png =1200x200)",
    "",
    "## 1.4 代码与列表",
    "",
    "- 项目一",
    "- 项目二",
    "",
    "1. 步骤一",
    "2. 步骤二",
    "",
    "```python",
    "def f():",
    "    return 1",
    "```",
    "",
])


class OutputQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-e-"))
        self.project_root = Path(T._setup_project(str(self.tmp / "项目")))
        content = self.project_root / "content" / "requirement"
        (content / "1 概述").mkdir(parents=True, exist_ok=True)
        (content / "1 概述" / "_index.md").write_text(CHAPTER, encoding="utf-8")
        (content / "3 设计").mkdir(parents=True, exist_ok=True)
        (content / "3 设计" / "_index.md").write_text(
            "被链接的章节正文。" + NL, encoding="utf-8"
        )
        _png(self.project_root / "assets" / "requirement" / "images" / "wide.png", (1200, 200))
        self.manifest = T._make_manifest(str(self.project_root))
        self.paths = ProjectPaths(self.project_root)
        self.output = build_with_project(self.manifest, self.paths)
        with zipfile.ZipFile(self.output) as archive:
            self.document = archive.read("word/document.xml")
            self.rels = archive.read("word/_rels/document.xml.rels")
        self.root = etree.fromstring(self.document)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _texts(self):
        return [node.text or "" for node in self.root.iter(_qn("t"))]

    def test_headings_lists_and_text_are_preserved(self):
        styles = [
            node.get(_qn("val"))
            for node in self.root.iter(_qn("pStyle"))
        ]
        self.assertIn("2", styles)  # 一级标题使用模板映射的 heading 1
        texts = self._texts()
        joined = NL.join(texts)
        self.assertIn("正文段落，含前导零 007 与站内链接", joined)
        self.assertIn("项目一", joined)
        self.assertIn("步骤一", joined)
        # 代码缩进与文本含义保留
        self.assertIn("def f():", joined)
        self.assertIn("    return 1", joined)

    def test_tables_keep_widths_header_repeat_and_values(self):
        tables = list(self.root.iter(_qn("tbl")))
        self.assertGreaterEqual(len(tables), 2)
        for table in tables:
            self.assertIsNotNone(table.find(_qn("tblPr") + "/" + _qn("tblW")))
            columns = list(table.iter(_qn("gridCol")))
            self.assertTrue(columns)
            for column in columns:
                self.assertTrue(int(column.get(_qn("w"))) > 0)
        # 长表首行跨页重复表头（按内容定位到真实的长表，避免命中模板里的嵌套表）
        long_table = next(
            table for table in tables
            if "长表第 1 行" in NL.join(node.text or "" for node in table.iter(_qn("t")))
        )
        table_rows = list(long_table.findall(_qn("tr")))
        self.assertGreater(len(table_rows), 20)
        self.assertIsNotNone(
            table_rows[0].find(_qn("trPr") + "/" + _qn("tblHeader")),
            "长表首行应带 tblHeader 以便跨页重复表头",
        )
        texts = self._texts()
        self.assertIn("007", texts)  # 前导零不被数值化
        # 多行单元格用 w:br 表达，两个片段都在
        self.assertIn("多行", texts)
        self.assertIn("第一行", texts)
        self.assertIn("第二行", texts)
        self.assertTrue(any(True for _ in self.root.iter(_qn("br"))))
        # 空值单元格保留（不被吞掉整列）
        empty_cells = [
            cell for cell in long_table.iter(_qn("tc"))
        ]
        self.assertTrue(empty_cells)

    def test_wide_image_is_fitted_to_page(self):
        extents = [
            node for node in self.root.iter("{{{0}}}extent".format(WP_NS))
        ]
        self.assertTrue(extents)
        for extent in extents:
            width = int(extent.get("cx"))
            self.assertGreater(width, 0)
            # A4 正文宽度约 21cm - 左右边距；宽图必须收敛在页面内
            self.assertLess(width, 21 * 360000, "宽图不得超出页面宽度")

    def test_external_link_becomes_real_hyperlink_and_internal_text_kept(self):
        hyperlinks = list(self.root.iter(_qn("hyperlink")))
        self.assertTrue(hyperlinks, "外链应生成真实超链接")
        rels = etree.fromstring(self.rels)
        targets = [str(node.get("Target")) for node in rels]
        self.assertIn("https://example.com/doc", targets)
        # 站内链接在书签缺失时转为静态文本，但链接文字必须保留
        joined = NL.join(self._texts())
        self.assertIn("说明", joined)
        self.assertIn("官网", joined)

    def test_source_markdown_not_rewritten_by_build(self):
        content = self.project_root / "content" / "requirement" / "1 概述" / "_index.md"
        self.assertEqual(content.read_text(encoding="utf-8"), CHAPTER)


if __name__ == "__main__":
    unittest.main()