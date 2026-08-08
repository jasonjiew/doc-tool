# -*- coding: utf-8 -*-
"""Word 导入预检正负向测试。

任务 3.7：为改名 DOCX、无标题样式、损坏关系和中文长路径增加预检正负向测试。

测试用最小化 DOCX（直接构造 ZIP + XML）覆盖各预检分支，不依赖真实公司文档。
"""

from __future__ import annotations

import io
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from lxml import etree

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)

from doc_tool.adapters.preflight import (  # noqa: E402
    HeadingInfo,
    ImportPreview,
    preflight,
)
from doc_tool.domain.errors import (  # noqa: E402
    BrokenRelationshipError,
    HeadingHierarchyError,
    InvalidDocxError,
    MissingHeading1Error,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --- OOXML 命名空间 ---

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

W = "{" + W_NS + "}"
R = "{" + R_NS + "}"


def _qn(tag: str) -> str:
    return W + tag


# --- 最小 DOCX 构造器 ---


CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '</Types>'
)


def _style(style_id: str, name: str) -> str:
    return (
        '<w:style w:type="paragraph" w:styleId="{0}">'
        '<w:name w:val="{1}"/>'
        '</w:style>'
    ).format(style_id, name)


def build_styles_xml(include_headings: bool = True) -> bytes:
    """构造 styles.xml，可选择是否包含 Heading 样式。"""
    styles = []
    if include_headings:
        for level in range(1, 7):
            styles.append(_style(str(level), "heading {0}".format(level)))
        # 正文样式
        styles.append(_style("4", "Normal"))
    else:
        styles.append(_style("Normal", "Normal"))
    body = "".join(styles)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="{ns}">{body}</w:styles>'
    ).format(ns=W_NS, body=body).encode("utf-8")


def build_paragraph(style_id: str, text: str) -> str:
    """构造一个带样式和文本的段落。"""
    return (
        '<w:p><w:pPr><w:pStyle w:val="{0}"/></w:pPr>'
        '<w:r><w:t>{1}</w:t></w:r></w:p>'
    ).format(style_id, text)


def build_document_xml(paragraphs_xml: str, media_image_rid: str = None) -> bytes:
    """构造 document.xml，可选包含一个图片引用。"""
    image_block = ""
    if media_image_rid:
        image_block = (
            '<w:p><w:r><w:drawing>'
            '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
            '<a:blip xmlns:a="{a_ns}" r:embed="{rid}"/>'
            '</wp:inline></w:drawing></w:r></w:p>'
        ).format(a_ns=A_NS, rid=media_image_rid)
    body_content = paragraphs_xml + image_block
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{w_ns}" xmlns:r="{r_ns}">'
        '<w:body>{body}<w:sectPr/></w:body>'
        '</w:document>'
    ).format(w_ns=W_NS, r_ns=R_NS, body=body_content).encode("utf-8")


def build_rels_xml(rid_target_pairs=None) -> bytes:
    """构造 document.xml.rels。"""
    if rid_target_pairs is None:
        rid_target_pairs = []
    rels = []
    for rid, target, rtype_suffix in rid_target_pairs:
        rels.append(
            '<Relationship Id="{0}" Type="{1}{2}" Target="{3}"/>'.format(
                rid, PR_NS, rtype_suffix, target
            )
        )
    body = "".join(rels)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{pr_ns}">{body}</Relationships>'
    ).format(pr_ns=PR_NS, body=body).encode("utf-8")


def build_table_xml(rows=2, cols=2) -> str:
    """构造一个简单表格 XML。"""
    cells = "".join(
        '<w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc>' for _ in range(cols)
    )
    tr = "<w:tr>{0}</w:tr>".format(cells)
    return "<w:tbl>{0}</w:tbl>".format(tr * rows)


def write_docx(
    path: str,
    paragraphs_xml: str = "",
    include_headings: bool = True,
    rels_pairs=None,
    include_media: bool = False,
    table_xml: str = "",
) -> str:
    """写入一个最小化 DOCX 文件。"""
    document_xml = build_document_xml(paragraphs_xml + table_xml)
    styles_xml = build_styles_xml(include_headings)
    rels_xml = build_rels_xml(rels_pairs)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", styles_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        if include_media:
            # 1x1 PNG
            png = (
                b'\x89PNG\r\n\x1a\n'
                b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
                b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01'
                b'\x00\x05\xfe\xd4\x00\x00\x00\x00IEND\xaeB`\x82'
            )
            zf.writestr("word/media/image1.png", png)
    return path


def write_encrypted_docx(path: str) -> str:
    """写入一个模拟加密 DOCX（仅含 EncryptedPackage 条目）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("EncryptedPackage", b"\x00" * 64)
    return path


def write_corrupted_xml_docx(path: str) -> str:
    """写入一个 document.xml 良构性损坏的 DOCX。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("word/document.xml", b"<w:document><broken")
        zf.writestr("word/styles.xml", build_styles_xml(True))
        zf.writestr("word/_rels/document.xml.rels", build_rels_xml())
    return path


# --- 测试用例 ---


class PackageValidationTests(unittest.TestCase):
    """任务 3.1：扩展名、ZIP、CRC、XML 和加密/损坏检测。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-preflight-pkg-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_non_docx_extension_rejected(self):
        """非 .docx 扩展名被拒绝。"""
        path = os.path.join(self._tmp, "report.txt")
        with open(path, "wb") as f:
            f.write(b"not a docx")
        with self.assertRaises(InvalidDocxError) as ctx:
            preflight(path)
        self.assertIn("E1001", ctx.exception.code)

    def test_corrupted_zip_rejected(self):
        """非 ZIP 文件被拒绝。"""
        path = os.path.join(self._tmp, "fake.docx")
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04 broken content")
        with self.assertRaises(InvalidDocxError):
            preflight(path)

    def test_encrypted_docx_rejected(self):
        """加密 DOCX 被拒绝。"""
        path = os.path.join(self._tmp, "encrypted.docx")
        write_encrypted_docx(path)
        with self.assertRaises(InvalidDocxError) as ctx:
            preflight(path)
        self.assertIn("加密", ctx.exception.user_message)

    def test_corrupted_xml_rejected(self):
        """XML 良构性损坏被拒绝。"""
        path = os.path.join(self._tmp, "badxml.docx")
        write_corrupted_xml_docx(path)
        with self.assertRaises(InvalidDocxError) as ctx:
            preflight(path)
        self.assertIn("XML", ctx.exception.user_message)

    def test_zip_uncompressed_size_limit_rejected_before_read(self):
        path = os.path.join(self._tmp, "oversized.docx")
        write_docx(path, build_paragraph("1", "第一章"))
        with patch(
            "doc_tool.adapters.preflight.MAX_TOTAL_UNCOMPRESSED_BYTES", 1
        ):
            with self.assertRaises(InvalidDocxError) as ctx:
                preflight(path)
        self.assertIn("安全上限", ctx.exception.user_message)

    def test_xml_doctype_and_entity_are_rejected(self):
        path = os.path.join(self._tmp, "doctype.docx")
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            + (" " * 5000)
            + '<!DOCTYPE w:document [<!ENTITY x "unsafe">]>'
            '<w:document xmlns:w="{0}"><w:body><w:p><w:r><w:t>&x;</w:t>'
            '</w:r></w:p></w:body></w:document>'
        ).format(W_NS).encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
            zf.writestr("word/document.xml", document_xml)
            zf.writestr("word/styles.xml", build_styles_xml())
            zf.writestr("word/_rels/document.xml.rels", build_rels_xml())
        with self.assertRaises(InvalidDocxError) as ctx:
            preflight(path)
        self.assertIn("DTD", ctx.exception.user_message)


class HeadingStyleTests(unittest.TestCase):
    """任务 3.3-3.4：标题样式映射和层级校验。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-preflight-h-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_valid_heading_tree_parsed(self):
        """有效的 H1/H2/H3 树被正确解析。"""
        paras = (
            build_paragraph("1", "第1章 概述")
            + build_paragraph("2", "1.1 背景")
            + build_paragraph("3", "1.1.1 详细")
            + build_paragraph("1", "第2章 详细设计")
        )
        path = os.path.join(self._tmp, "valid.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertEqual(len(preview.headings), 4)
        self.assertEqual(preview.heading_level_counts[1], 2)
        self.assertEqual(preview.heading_level_counts[2], 1)
        self.assertEqual(preview.heading_level_counts[3], 1)
        self.assertTrue(preview.has_heading1)

    def test_no_heading_styles_rejected(self):
        """无 Heading 样式定义的文档被 fail-closed 拒绝。"""
        paras = build_paragraph("Normal", "普通正文")
        path = os.path.join(self._tmp, "noheadings.docx")
        write_docx(path, paras, include_headings=False)
        with self.assertRaises(MissingHeading1Error) as ctx:
            preflight(path)
        self.assertIn("E1002", ctx.exception.code)

    def test_heading_hierarchy_jump_rejected(self):
        """标题层级跳跃（H1 后直接 H3）被拒绝。"""
        paras = (
            build_paragraph("1", "第1章 概述")
            + build_paragraph("3", "1.1.1 跳级")
        )
        path = os.path.join(self._tmp, "jump.docx")
        write_docx(path, paras)
        with self.assertRaises(HeadingHierarchyError) as ctx:
            preflight(path)
        self.assertIn("E1003", ctx.exception.code)


class RelationshipTests(unittest.TestCase):
    """任务 3.2：关系目标完整性及正文资源引用预检。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-preflight-rel-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_broken_relationship_target_rejected(self):
        """关系目标不存在于包内被拒绝。"""
        paras = build_paragraph("1", "第1章 概述")
        rels_pairs = [("rId1", "media/missing.png", "/image")]
        path = os.path.join(self._tmp, "brokenrel.docx")
        write_docx(path, paras, rels_pairs=rels_pairs, include_media=False)
        with self.assertRaises(BrokenRelationshipError) as ctx:
            preflight(path)
        self.assertIn("E1004", ctx.exception.code)

    def test_valid_image_reference_accepted(self):
        """正文引用的图片关系目标存在时通过。"""
        paras = build_paragraph("1", "第1章 概述")
        rels_pairs = [("rId1", "media/image1.png", "/image")]
        path = os.path.join(self._tmp, "hasimage.docx")
        write_docx(
            path, paras, rels_pairs=rels_pairs, include_media=True,
        )
        # 需要在正文中引用 rId1
        document_xml = build_document_xml(paras, media_image_rid="rId1")
        # 重写 document.xml
        with zipfile.ZipFile(path, "r") as zf:
            items = {n: zf.read(n) for n in zf.namelist()}
        items["word/document.xml"] = document_xml
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for n, d in items.items():
                zf.writestr(n, d)
        preview = preflight(path)
        self.assertEqual(preview.image_count, 1)
        self.assertEqual(preview.media_count, 1)

    def test_body_references_missing_rid_rejected(self):
        """正文引用的 rId 不在关系表中被拒绝。"""
        paras = build_paragraph("1", "第1章 概述")
        document_xml = build_document_xml(paras, media_image_rid="rId99")
        path = os.path.join(self._tmp, "orphanrid.docx")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
            zf.writestr("word/document.xml", document_xml)
            zf.writestr("word/styles.xml", build_styles_xml(True))
            zf.writestr("word/_rels/document.xml.rels", build_rels_xml())
        with self.assertRaises(BrokenRelationshipError):
            preflight(path)

    def test_external_image_uri_without_target_mode_rejected(self):
        """缺失 TargetMode 的 file URI 图片仍按外链图片拒绝。"""
        paras = build_paragraph("1", "第1章 概述")
        document_xml = build_document_xml(paras, media_image_rid="rId1")
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="{0}">'
            '<Relationship Id="rId1" Type="{0}/image" '
            'Target="file:///C:/outside/image.png"/>'
            '</Relationships>'
        ).format(PR_NS).encode("utf-8")
        path = os.path.join(self._tmp, "external-image.docx")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
            zf.writestr("word/document.xml", document_xml)
            zf.writestr("word/styles.xml", build_styles_xml(True))
            zf.writestr("word/_rels/document.xml.rels", rels_xml)
        with self.assertRaises(BrokenRelationshipError) as ctx:
            preflight(path)
        self.assertIn("外部链接", ctx.exception.user_message)


class PreviewModelTests(unittest.TestCase):
    """任务 3.5-3.6：文档类型建议和导入预览模型。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-preflight-prev-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_preview_contains_counts_and_first_last_headings(self):
        """预览模型包含标题计数、首尾标题、图片/表格数量。"""
        paras = "".join(
            build_paragraph("1", "第{0}章 概述{0}".format(i)) for i in range(1, 8)
        )
        path = os.path.join(self._tmp, "preview.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertEqual(len(preview.headings), 7)
        self.assertEqual(len(preview.first_headings), 5)
        self.assertEqual(len(preview.last_headings), 5)
        self.assertEqual(preview.first_headings[0].text, "第1章 概述1")
        self.assertEqual(preview.last_headings[-1].text, "第7章 概述7")
        self.assertEqual(preview.table_count, 0)
        self.assertGreater(preview.file_size_bytes, 0)

    def test_table_count_in_preview(self):
        """预览模型正确统计表格数量。"""
        paras = build_paragraph("1", "第1章 概述")
        table_xml = build_table_xml(3, 2)
        path = os.path.join(self._tmp, "table.docx")
        write_docx(path, paras, table_xml=table_xml)
        preview = preflight(path)
        self.assertEqual(preview.table_count, 1)

    def test_requirement_type_suggestion_high_confidence(self):
        """包含"需求"关键字的文档高置信度建议为 requirement。"""
        paras = (
            build_paragraph("1", "康尚健康云软件需求说明书")
            + build_paragraph("2", "1.1 背景")
        )
        path = os.path.join(self._tmp, "req.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertIsNotNone(preview.document_type_suggestion)
        self.assertEqual(preview.document_type_suggestion.document_type, "requirement")
        self.assertEqual(preview.document_type_suggestion.confidence, "high")

    def test_design_type_suggestion_high_confidence(self):
        """包含"详细设计"关键字的文档高置信度建议为 design。"""
        paras = (
            build_paragraph("1", "康尚健康云系统详细设计说明书")
            + build_paragraph("2", "2.1 架构")
        )
        path = os.path.join(self._tmp, "design.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertIsNotNone(preview.document_type_suggestion)
        self.assertEqual(preview.document_type_suggestion.document_type, "design")
        self.assertEqual(preview.document_type_suggestion.confidence, "high")

    def test_low_confidence_suggestion_not_auto_decided(self):
        """无关键字的文档返回低置信度建议。"""
        paras = build_paragraph("1", "第一章 概述")
        path = os.path.join(self._tmp, "generic.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertEqual(preview.document_type_suggestion.confidence, "low")


class RenamedAndSpecialPathTests(unittest.TestCase):
    """任务 3.7：改名 DOCX 和中文长路径。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-preflight-special-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_renamed_docx_accepted(self):
        """文件名与历史基线不同的合法 DOCX 仍通过预检。"""
        paras = build_paragraph("1", "第1章 概述")
        # 任意文件名，不含历史基线编号
        path = os.path.join(self._tmp, "我的文档(v2.5)-最终版.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertEqual(preview.file_name, "我的文档(v2.5)-最终版.docx")
        self.assertTrue(preview.has_heading1)

    def test_chinese_long_path_accepted(self):
        """中文长路径下的 DOCX 通过预检。"""
        deep_dir = os.path.join(
            self._tmp,
            "康尚健康云项目",
            "需求文档",
            "2.3.0版本",
            "JD接入改造",
        )
        os.makedirs(deep_dir)
        paras = build_paragraph("1", "第1章 概述")
        path = os.path.join(deep_dir, "测试需求说明书.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertTrue(preview.has_heading1)
        self.assertIn("测试需求说明书", preview.file_name)

    def test_space_bracket_ampersand_path_accepted(self):
        """含空格、括号、& 的路径下 DOCX 通过预检。"""
        special_dir = os.path.join(self._tmp, "项目(1.0) & 验证")
        os.makedirs(special_dir)
        paras = build_paragraph("1", "第1章 概述")
        path = os.path.join(special_dir, "需求 & 设计.docx")
        write_docx(path, paras)
        preview = preflight(path)
        self.assertTrue(preview.has_heading1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
