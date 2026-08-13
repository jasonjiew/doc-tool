# -*- coding: utf-8 -*-
"""保真扫描单元测试。

任务 2.1 / 4.3：覆盖各类 Word 特性的正反例计数与分级，含跨行 ``w:ins``、
外部链接图片、批注部件兜底与 preflight 集成。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)

from doc_tool.adapters.fidelity import (  # noqa: E402
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    FidelityFinding,
    scan_fidelity,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
O_NS = "urn:schemas-microsoft-com:office:office"

W = "{" + W_NS + "}"
R = "{" + R_NS + "}"


def _qn(tag):
    return W + tag


def _scan(document_body, extra_parts=None):
    """把 document.xml body 片段打包为部件字典，运行保真扫描。"""
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{0}" xmlns:r="{1}"><w:body>{2}<w:sectPr/></w:body></w:document>'
    ).format(W_NS, R_NS, document_body)
    parts = {"word/document.xml": document.encode("utf-8")}
    if extra_parts:
        parts.update(extra_parts)
    return scan_fidelity(parts)


def _finding(report, feature):
    for finding in report.findings:
        if finding.feature == feature:
            return finding
    return None


class FidelityScanTests(unittest.TestCase):
    def test_empty_document_no_findings(self):
        report = _scan("<w:p><w:r><w:t>普通段落</w:t></w:r></w:p>")
        self.assertEqual(report.findings, ())
        self.assertFalse(report.has_block)

    def test_each_feature_count_and_severity(self):
        body = (
            '<w:p><w:hyperlink r:id="r1"><w:r><w:t>链接</w:t></w:r></w:hyperlink></w:p>'
            '<w:p><w:bookmarkStart w:id="0" w:name="_Toc1"/></w:p>'
            '<w:p><w:commentRangeStart w:id="1"/><w:r><w:t>批注体</w:t></w:r></w:p>'
            '<w:p><w:ins w:id="2"><w:r><w:t>修订</w:t></w:r></w:ins></w:p>'
            '<w:p><w:footnoteReference w:id="1"/></w:p>'
            '<w:p><m:oMath xmlns:m="{0}"><m:r><m:t>x</m:t></m:r></m:oMath></w:p>'
            '<w:p><w:pict><o:OLEObject xmlns:o="{1}" ProgID="Excel.Sheet.8"/></w:pict></w:p>'
            '<w:p><w:txbxContent><w:r><w:t>框</w:t></w:r></w:txbxContent></w:p>'
            '<w:p><w:sdt><w:sdtContent><w:r><w:t>控件</w:t></w:r></w:sdtContent></w:sdt></w:p>'
            '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> TOC \\o "1-3" </w:instrText></w:r></w:p>'
        ).format(M_NS, O_NS)
        report = _scan(body)
        expected = {
            "hyperlink": (1, SEVERITY_WARN),
            "bookmark": (1, SEVERITY_WARN),
            "comment": (1, SEVERITY_BLOCK),
            "revision": (1, SEVERITY_BLOCK),
            "footnote": (1, SEVERITY_BLOCK),
            "formula": (1, SEVERITY_BLOCK),
            "ole": (1, SEVERITY_BLOCK),
            "textbox": (1, SEVERITY_BLOCK),
            "sdt": (1, SEVERITY_WARN),
            "field": (2, SEVERITY_INFO),  # fldChar + instrText
        }
        for feature, (count, severity) in expected.items():
            finding = _finding(report, feature)
            self.assertIsNotNone(finding, feature)
            self.assertEqual(finding.count, count, feature)
            self.assertEqual(finding.severity, severity, feature)
        self.assertTrue(report.has_block)

    def test_chart_part_blocked(self):
        chart = etree.tostring(
            etree.Element("c", nsmap={"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}),
            encoding="UTF-8",
        )
        report = _scan("<w:p><w:r><w:t>正文</w:t></w:r></w:p>",
                       extra_parts={"word/charts/chart1.xml": chart})
        finding = _finding(report, "chart")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, SEVERITY_BLOCK)
        self.assertEqual(finding.samples, ("word/charts/chart1.xml",))

    def test_multi_line_revision_counted_once(self):
        # 单个 w:ins 跨多行包裹多个 run，仍按元素计数为 1（正则易漏）。
        body = (
            '<w:p><w:ins w:id="1">\n'
            '<w:r><w:t>第一行</w:t></w:r>\n'
            '<w:r><w:t>第二行</w:t></w:r>\n'
            '</w:ins></w:p>'
        )
        report = _scan(body)
        finding = _finding(report, "revision")
        self.assertEqual(finding.count, 1)
        self.assertEqual(finding.samples, ("body[0]",))

    def test_hyperlink_in_header_sampled_by_part(self):
        header = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:hdr xmlns:w="{0}" xmlns:r="{1}">'
            '<w:p><w:hyperlink r:id="r1"><w:r><w:t>页眉链接</w:t></w:r></w:hyperlink></w:p>'
            '</w:hdr>'
        ).format(W_NS, R_NS)
        report = _scan("<w:p><w:r><w:t>正文</w:t></w:r></w:p>",
                       extra_parts={"word/header1.xml": header.encode("utf-8")})
        finding = _finding(report, "hyperlink")
        self.assertEqual(finding.count, 1)
        self.assertEqual(finding.samples, ("word/header1.xml",))

    def test_comment_part_backstop_when_no_range_start(self):
        comments = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:comments xmlns:w="{0}"><w:comment w:id="1"><w:p><w:r><w:t>批注</w:t></w:r></w:p></w:comment></w:comments>'
        ).format(W_NS)
        report = _scan("<w:p><w:r><w:t>正文</w:t></w:r></w:p>",
                       extra_parts={"word/comments.xml": comments.encode("utf-8")})
        finding = _finding(report, "comment")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, SEVERITY_BLOCK)
        self.assertEqual(finding.count, 1)
        self.assertEqual(finding.samples, ("word/comments.xml",))

    def test_warn_only_does_not_block(self):
        body = (
            '<w:p><w:hyperlink r:id="r1"><w:r><w:t>链接</w:t></w:r></w:hyperlink></w:p>'
            '<w:p><w:sdt><w:sdtContent><w:r><w:t>控件</w:t></w:r></w:sdtContent></w:sdt></w:p>'
        )
        report = _scan(body)
        self.assertFalse(report.has_block)
        self.assertEqual(len(report.warn_findings), 2)

    def test_samples_capped_at_five(self):
        hyperlinks = "".join(
            '<w:p><w:hyperlink r:id="r{0}"><w:r><w:t>链接{0}</w:t></w:r></w:hyperlink></w:p>'.format(i)
            for i in range(8)
        )
        report = _scan(hyperlinks)
        finding = _finding(report, "hyperlink")
        self.assertEqual(finding.count, 8)
        self.assertEqual(len(finding.samples), 5)

    def test_external_link_image_not_misdetected(self):
        # 外部链接图片（r:link 指向远程）不是超链接/书签等特性，仅正文含图片，
        # 保真扫描不应误报任何特性。
        body = (
            '<w:p><w:r><w:drawing>'
            '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
            '<a:blip xmlns:a="{0}" r:link="rExt"/></wp:inline></w:drawing></w:r></w:p>'
        ).format(A_NS)
        report = _scan(body)
        self.assertEqual(report.findings, ())

    def test_summary_and_markdown_render(self):
        report = _scan('<w:p><w:ins w:id="1"><w:r><w:t>修订</w:t></w:r></w:ins></w:p>')
        self.assertIn("修订", report.summary_text())
        self.assertIn("BLOCK", report.summary_text())
        self.assertIn("修订", report.markdown_text())


class FidelityPreflightIntegrationTests(unittest.TestCase):
    """preflight 集成：ImportPreview.fidelity 携带分级报告。"""

    def _write_docx(self, path, document_body):
        styles = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="{0}">'
            '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/></w:style>'
            '</w:styles>'
        ).format(W_NS)
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="{0}" xmlns:r="{1}"><w:body>{2}<w:sectPr/></w:body></w:document>'
        ).format(W_NS, R_NS, document_body)
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        )
        content_types = (
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
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("word/document.xml", document.encode("utf-8"))
            zf.writestr("word/styles.xml", styles.encode("utf-8"))
            zf.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))

    def test_preflight_exposes_fidelity_report(self):
        from doc_tool.adapters.preflight import preflight

        body = (
            '<w:p><w:pPr><w:pStyle w:val="1"/></w:pPr><w:r><w:t>第一章 标题</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>正文</w:t></w:r></w:p>'
            '<w:p><w:commentRangeStart w:id="1"/><w:r><w:t>有批注</w:t></w:r></w:p>'
        )
        with tempfile.TemporaryDirectory(prefix="fidelity-preflight-") as work:
            docx = os.path.join(work, "source.docx")
            self._write_docx(docx, body)
            preview = preflight(docx)
            self.assertIsNotNone(preview.fidelity)
            self.assertTrue(preview.fidelity.has_block)
            comment = _finding(preview.fidelity, "comment")
            self.assertEqual(comment.count, 1)

    def test_preflight_clean_doc_has_no_block(self):
        from doc_tool.adapters.preflight import preflight

        body = (
            '<w:p><w:pPr><w:pStyle w:val="1"/></w:pPr><w:r><w:t>第一章 标题</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>只有正文</w:t></w:r></w:p>'
        )
        with tempfile.TemporaryDirectory(prefix="fidelity-preflight-") as work:
            docx = os.path.join(work, "source.docx")
            self._write_docx(docx, body)
            preview = preflight(docx)
            self.assertIsNotNone(preview.fidelity)
            self.assertFalse(preview.fidelity.has_block)
            self.assertEqual(preview.fidelity.findings, ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
