# -*- coding: utf-8 -*-
"""往返差异门禁单元测试。

任务 2.4 / 4.4：一致通过、段落/标题/图片差异为 BLOCK、表格表示差异为 WARN。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)

from doc_tool.adapters.roundtrip import SEVERITY_BLOCK, SEVERITY_WARN, roundtrip_diff  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

W = "{" + W_NS + "}"


def _qn(tag):
    return W + tag


# 1x1 PNG（与 test_import_preflight 一致，内联构造避免依赖磁盘文件）。
PNG1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\x00\x05\xfe\xd4\x00\x00\x00\x00IEND\xaeB`\x82"
)
# 不同内容的 1x1 PNG（保证哈希不同）。
PNG2 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\x00\x05\xfe\xd4\x00\x00\x00\x00IEND\xaeB`\x82"
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/settings.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
    '</Types>'
)

STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="{0}">'
    '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 2"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '</w:styles>'
).format(W_NS).encode("utf-8")

SETTINGS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:settings xmlns:w="{0}"><w:updateFields w:val="true"/></w:settings>'
).format(W_NS).encode("utf-8")


def _paragraph(style_id, text):
    return (
        '<w:p><w:pPr><w:pStyle w:val="{0}"/></w:pPr><w:r><w:t>{1}</w:t></w:r></w:p>'
    ).format(style_id, text)


def _plain(text):
    return "<w:p><w:r><w:t>{0}</w:t></w:r></w:p>".format(text)


def _table(cell_text):
    return (
        "<w:tbl><w:tr><w:tc>{0}</w:tc></w:tr></w:tbl>".format(_plain(cell_text))
    )


def _image_paragraph(rid):
    return (
        '<w:p><w:r><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<a:blip xmlns:a="{0}" r:embed="{1}"/>'
        '</wp:inline></w:drawing></w:r></w:p>'
    ).format(A_NS, rid)


def _list_item(text, ilvl="0", num_id="1"):
    """自动编号列表项段落（含 numPr，body_events 识别为 L 事件）。"""
    return (
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="{1}"/>'
        '<w:numId w:val="{2}"/></w:numPr></w:pPr>'
        '<w:r><w:t>{0}</w:t></w:r></w:p>'
    ).format(text, ilvl, num_id)


def _hyperlink_paragraph(text, anchor="bm1"):
    """超链接段落（含 w:hyperlink，body_events 识别为 X 事件）。"""
    return (
        '<w:p><w:hyperlink w:anchor="{1}"><w:r><w:t>{0}</w:t></w:r></w:hyperlink></w:p>'
    ).format(text, anchor)


def build_package(path, body_children, image_bytes=None):
    """写入一个最小化 DOCX（含 body_events 所需的全部部件）。"""
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{0}">'
        '<Relationship Id="rImg" Type="{1}/image" Target="media/image1.png"/>'
        '</Relationships>'
    ).format(PR_NS, R_NS)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{0}" xmlns:r="{1}">'
        '<w:body>{2}<w:sectPr/></w:body></w:document>'
    ).format(W_NS, R_NS, "".join(body_children))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("word/document.xml", document.encode("utf-8"))
        zf.writestr("word/styles.xml", STYLES)
        zf.writestr("word/settings.xml", SETTINGS)
        zf.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        if image_bytes is not None:
            zf.writestr("word/media/image1.png", image_bytes)


class RoundtripDiffTests(unittest.TestCase):
    def _diff(self, source_children, rebuilt_children, source_image=None, rebuilt_image=None):
        with tempfile.TemporaryDirectory(prefix="roundtrip-") as work:
            source = os.path.join(work, "source.docx")
            rebuilt = os.path.join(work, "rebuilt.docx")
            build_package(source, source_children, image_bytes=source_image)
            build_package(rebuilt, rebuilt_children, image_bytes=rebuilt_image)
            return roundtrip_diff(source, rebuilt)

    def test_identical_documents_pass(self):
        body = [
            _paragraph("1", "第一章 需求"),
            _plain("正文段落"),
            _table("表格单元格"),
            _paragraph("2", "第一节 功能"),
            _plain("后续正文"),
        ]
        report = self._diff(body, body)
        self.assertFalse(report.has_block)
        self.assertEqual(report.issues, ())
        self.assertEqual(report.source_count, report.rebuilt_count)

    def test_missing_paragraph_is_block(self):
        source = [_paragraph("1", "第一章"), _plain("正文一"), _plain("正文二")]
        rebuilt = [_paragraph("1", "第一章"), _plain("正文一")]  # 丢失一段
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("不一致", report.block_issues[0].message)

    def test_heading_level_change_is_block(self):
        source = [_paragraph("1", "第一章"), _paragraph("2", "第一节"), _plain("正文")]
        rebuilt = [_paragraph("1", "第一章"), _paragraph("3", "第一节"), _plain("正文")]  # H2 变 H3
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("标题层级或文本变化", report.block_issues[0].message)

    def test_heading_only_doc_without_h1_is_block_by_count(self):
        # body_events 在首个 H1 前不采集正文；重建文档丢失全部 H1 时按数量差异阻止。
        source = [_paragraph("1", "第一章"), _plain("正文")]
        rebuilt = [_paragraph("2", "第一章"), _plain("正文")]  # 无 H1，重建无业务事件
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("不一致", report.block_issues[0].message)

    def test_heading_text_change_is_block(self):
        source = [_paragraph("1", "第一章 原标题"), _plain("正文")]
        rebuilt = [_paragraph("1", "第一章 新标题"), _plain("正文")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("标题层级或文本变化", report.block_issues[0].message)

    def test_image_hash_change_is_block(self):
        source = [_paragraph("1", "第一章"), _plain("正文"), _image_paragraph("rImg")]
        rebuilt = [_paragraph("1", "第一章"), _plain("正文"), _image_paragraph("rImg")]
        report = self._diff(source, rebuilt, source_image=PNG1, rebuilt_image=PNG2)
        self.assertTrue(report.has_block)
        self.assertIn("图片对象缺失或变化", report.block_issues[0].message)

    def test_table_text_difference_is_warn(self):
        source = [_paragraph("1", "第一章"), _table("单元格A")]
        rebuilt = [_paragraph("1", "第一章"), _table("单元格B")]
        report = self._diff(source, rebuilt)
        self.assertFalse(report.has_block)
        self.assertEqual(len(report.warn_issues), 1)
        self.assertIn("表示差异", report.warn_issues[0].message)

    def test_paragraph_text_change_is_block(self):
        source = [_paragraph("1", "第一章"), _plain("原始正文")]
        rebuilt = [_paragraph("1", "第一章"), _plain("被篡改正文")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("正文段落丢失或文本变化", report.block_issues[0].message)

    def test_literal_numbered_paragraph_rebuilt_as_list_is_warn(self):
        # 源 Word 里「1. 概述」是无 numPr 的字面编号段落（P 事件）；经 markdown
        # ``1. 概述`` 重建后成为自动编号列表项（L 事件）。去掉 P 端字面编号前缀
        # 后文本一致 → 内容保留，降级 WARN 放行，不得误 BLOCK 合法文档。
        source = [_paragraph("1", "第一章"), _plain("1. 概述")]
        rebuilt = [_paragraph("1", "第一章"), _list_item("概述")]
        report = self._diff(source, rebuilt)
        self.assertFalse(report.has_block)
        self.assertEqual(len(report.warn_issues), 1)
        self.assertIn("自动编号列表重建", report.warn_issues[0].message)

    def test_literal_number_paragraph_text_mismatch_is_block(self):
        # 反向：去掉编号前缀后文本仍不一致 = 真实内容丢失，必须 BLOCK。
        source = [_paragraph("1", "第一章"), _plain("1. 概述")]
        rebuilt = [_paragraph("1", "第一章"), _list_item("完全不同的内容")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("正文段落丢失或文本变化", report.block_issues[0].message)

    def test_bullet_list_prefixes_rebuilt_as_list_are_warn(self):
        # 支持无序列表符号前缀（- , * , • , + ），经重建后内容保留降为 WARN 放行。
        bullets = ["- 项目一", "• 项目二", "* 项目三", "+ 项目四"]
        for bullet in bullets:
            expected_text = bullet[2:]
            source = [_paragraph("1", "第一章"), _plain(bullet)]
            rebuilt = [_paragraph("1", "第一章"), _list_item(expected_text)]
            report = self._diff(source, rebuilt)
            self.assertFalse(report.has_block, f"Prefix '{bullet[:2]}' should be WARN, not BLOCK")
            self.assertEqual(len(report.warn_issues), 1)
            self.assertIn("自动编号列表重建", report.warn_issues[0].message)

    def test_negative_number_not_stripped_and_mismatch_is_block(self):
        # 负数（如 -5 摄氏度）开头的段落因无后导空格不得剥离负号，与重建内容不符时必须 BLOCK。
        source = [_paragraph("1", "第一章"), _plain("-5 摄氏度")]
        rebuilt = [_paragraph("1", "第一章"), _list_item("5 摄氏度")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("正文段落丢失或文本变化", report.block_issues[0].message)

    def test_hyperlink_paragraph_degraded_to_plain_is_warn(self):
        # X 事件（超链接段落）退化为 P 事件（普通段落），但文本一致时降为 WARN 放行。
        source = [_paragraph("1", "第一章"), _hyperlink_paragraph("访问官方文档")]
        rebuilt = [_paragraph("1", "第一章"), _plain("访问官方文档")]
        report = self._diff(source, rebuilt)
        self.assertFalse(report.has_block)
        self.assertEqual(len(report.warn_issues), 1)
        self.assertIn("表示差异", report.warn_issues[0].message)

    def test_list_item_text_tampering_is_block(self):
        # 回归测试：同为 L 事件但正文被篡改时，必须判定为 BLOCK（旧实现错误按 left_kind==right_kind 放行为 WARN）。
        source = [_paragraph("1", "第一章"), _list_item("原始规程条款")]
        rebuilt = [_paragraph("1", "第一章"), _list_item("被篡改的规程条款")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("正文段落丢失或文本变化", report.block_issues[0].message)

    def test_hyperlink_paragraph_text_tampering_is_block(self):
        # 回归测试：同为 X 事件但正文被篡改时，必须判定为 BLOCK（旧实现错误按 left_kind==right_kind 放行为 WARN）。
        source = [_paragraph("1", "第一章"), _hyperlink_paragraph("原始超链接文本")]
        rebuilt = [_paragraph("1", "第一章"), _hyperlink_paragraph("被篡改的超链接文本")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        self.assertIn("正文段落丢失或文本变化", report.block_issues[0].message)

    def test_list_item_ilvl_diff_same_text_is_warn(self):
        # 同为 L 事件且文本相同，仅层级不同，属于表示差异应为 WARN。
        source = [_paragraph("1", "第一章"), _list_item("相同条款", ilvl="0")]
        rebuilt = [_paragraph("1", "第一章"), _list_item("相同条款", ilvl="1")]
        report = self._diff(source, rebuilt)
        self.assertFalse(report.has_block)
        self.assertEqual(len(report.warn_issues), 1)
        self.assertIn("表示差异", report.warn_issues[0].message)

    def test_chinese_numbering_without_space_is_warn(self):
        # 中文顿号编号（1、项目背景）与全角句点（1．项目背景）无空格写法重建为列表项放行
        cases = ["1、项目背景", "1、 项目背景", "1．项目背景", "1. 项目背景", "1.项目背景"]
        for prefix_text in cases:
            source = [_paragraph("1", "第一章"), _plain(prefix_text)]
            rebuilt = [_paragraph("1", "第一章"), _list_item("项目背景")]
            report = self._diff(source, rebuilt)
            self.assertFalse(
                report.has_block,
                f"Prefix '{prefix_text}' should strip to '项目背景' and WARN, not BLOCK"
            )
            self.assertEqual(len(report.warn_issues), 1)
            self.assertIn("自动编号列表重建", report.warn_issues[0].message)

    def test_decimal_and_multilevel_not_stripped_and_tamper_is_block(self):
        # 小数（1.5 摄氏度）与多级标题（1.2.3 节）开头的段落不得误剥离数字部分
        source = [_paragraph("1", "第一章"), _plain("1.5 摄氏度")]
        rebuilt = [_paragraph("1", "第一章"), _list_item("5 摄氏度")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)

        source2 = [_paragraph("1", "第一章"), _plain("1.2.3 节")]
        rebuilt2 = [_paragraph("1", "第一章"), _list_item("2.3 节")]
        report2 = self._diff(source2, rebuilt2)
        self.assertTrue(report2.has_block)

    def test_roundtrip_issue_to_dict_includes_source_and_rebuilt(self):
        # 差异条目包含结构化 source 与 rebuilt 字段
        source = [_paragraph("1", "第一章"), _plain("原始正文条款")]
        rebuilt = [_paragraph("1", "第一章"), _plain("篡改后条款")]
        report = self._diff(source, rebuilt)
        self.assertTrue(report.has_block)
        issue_dict = report.block_issues[0].to_dict()
        self.assertEqual(issue_dict["severity"], "BLOCK")
        self.assertEqual(issue_dict["position"], "#1")
        self.assertIn("source", issue_dict)
        self.assertIn("rebuilt", issue_dict)
        self.assertIn("原始正文条款", issue_dict["source"])
        self.assertIn("篡改后条款", issue_dict["rebuilt"])

    def test_classify_error_bounds_and_unknown_kind_fail_closed(self):
        # 边界与未知类型：越界索引安全处理，未知元素类型 fail-closed 为 BLOCK
        from doc_tool.adapters.roundtrip import _classify_error, SEVERITY_BLOCK
        from validate_docx import Event
        ev_a = Event("Z", "未知A", "body[0]")
        ev_b = Event("Z", "未知B", "body[0]")
        issue_oob = _classify_error("#99 基线内容/位置不一致: a vs b", [ev_a], [ev_b])
        self.assertEqual(issue_oob.severity, SEVERITY_BLOCK)

        issue_unknown = _classify_error("#0 基线内容/位置不一致: a vs b", [ev_a], [ev_b])
        self.assertEqual(issue_unknown.severity, SEVERITY_BLOCK)
        self.assertIn("元素类型变化", issue_unknown.message)

    def test_summary_and_markdown_render(self):
        source = [_paragraph("1", "第一章"), _plain("正文")]
        rebuilt = [_paragraph("1", "第一章")]
        report = self._diff(source, rebuilt)
        self.assertIn("BLOCK", report.summary_text())
        self.assertIn("往返差异", report.markdown_text())
        clean = self._diff([_paragraph("1", "第一章")], [_paragraph("1", "第一章")])
        self.assertIn("一致", clean.summary_text())


class NumberingSignatureTests(unittest.TestCase):
    """validate_docx._numbering_signature：只统计被 num 引用的 abstractNum。"""

    def _fake_package(self, numbering_xml, styles_xml):
        from lxml import etree

        sys.path.insert(0, SCRIPTS)  # validate_docx 位于 scripts/，与 roundtrip 内部一致
        from validate_docx import _numbering_signature

        styles = etree.fromstring(styles_xml.encode("utf-8"))
        numbering = etree.fromstring(numbering_xml.encode("utf-8"))

        class _FakePackage:
            def __init__(self):
                self.xml_roots = {"word/numbering.xml": numbering}
                self.styles = styles

        return _numbering_signature(_FakePackage()), etree, numbering

    def test_orphan_abstract_num_excluded_and_both_serializations_recognized(self):
        # abstractNum 0 被 num 1 以子元素（<w:abstractNumId w:val="0"/>）引用；
        # abstractNum 1 被 num 2 以属性（w:abstractNumId="1"）引用；
        # abstractNum 2 无任何 num 引用（孤立）——Word 保存时常裁剪，不计入签名。
        numbering_xml = (
            '<w:numbering xmlns:w="{0}">'
            '<w:abstractNum w:abstractNumId="0">'
            '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
            '<w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
            '<w:abstractNum w:abstractNumId="1">'
            '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="upperRoman"/>'
            '<w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
            '<w:abstractNum w:abstractNumId="2">'
            '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="lowerRoman"/>'
            '<w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
            '<w:num w:numId="2" w:abstractNumId="1"/>'
            '</w:numbering>'
        ).format(W_NS)
        styles_xml = (
            '<w:styles xmlns:w="{0}"><w:style w:type="paragraph" w:styleId="Normal">'
            '<w:name w:val="Normal"/></w:style></w:styles>'
        ).format(W_NS)
        signature, etree, numbering = self._fake_package(numbering_xml, styles_xml)
        # 两种序列化引用的定义都计入（2 个不同签名）；孤立定义不计入（无 3 个）。
        self.assertEqual(len(signature), 2)
        fmt_values = {
            level[2]
            for levels in signature.elements()
            for level in levels
        }
        self.assertEqual(fmt_values, {"decimal", "upperRoman"})
        self.assertNotIn("lowerRoman", fmt_values)



class TocLabelKeyTests(unittest.TestCase):
    """validate_docx._toc_label_key：TOC 条目归一化比对（尾部页码只剥离缓存侧）。"""

    def _key(self, text, **kwargs):
        sys.path.insert(0, SCRIPTS)
        from validate_docx import _toc_label_key

        return _toc_label_key(text, **kwargs)

    def test_cached_strips_page_number(self):
        # Word TOC 缓存条目 = 标题 + 制表符 + 页码（paragraph_text 把 w:tab 转 \t）。
        self.assertEqual(self._key("1.4项目背景与目标\t16"), "项目背景与目标")
        self.assertEqual(self._key("第 1 章引言\t16"), "引言")
        self.assertEqual(self._key("2.1 接口说明V1\t16"), "接口说明V1")

    def test_expected_keeps_trailing_title_digits(self):
        # 标题以数字结尾时，预期侧不得剥离尾部数字（缓存侧剥离页码后仍能对齐）。
        self.assertEqual(self._key("2.1 接口说明V1", strip_page=False), "接口说明V1")
        self.assertEqual(self._key("第1章 引言", strip_page=False), "引言")

    def test_cached_and_expected_align_for_digit_ending_title(self):
        # 旧实现两侧都剥离尾部数字：缓存「接口说明V1\t16」→「接口说明V1」，
        # 预期「接口说明V1」→「接口说明V」，导致误报 TOC 不一致。
        cached = self._key("2.1接口说明V1\t16", strip_page=True)
        expected = self._key("2.1 接口说明V1", strip_page=False)
        self.assertEqual(cached, expected)
if __name__ == "__main__":
    unittest.main(verbosity=2)
