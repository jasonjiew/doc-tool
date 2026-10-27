# -*- coding: utf-8 -*-
"""Regression tests for Patrol 5.3: 导出文档属性、封面、页眉页脚与 Word 刷新后校验联动巡检."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
from lxml import etree
from scripts.build_docx import update_headers, qn
from scripts.validate_docx import _normalize_header_fields, _header_footer_signatures, DocxPackage
from doc_tool.domain.paths import build_output_filename
from doc_tool.application.project_export import _output_stem
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.application.intake_contract import ExportRequest


class TestPatrol53FieldsAndHeaderFooterEdgeCases:
    def test_multi_run_split_docproperty_in_header_and_footer(self):
        r"""测试用例：页眉与页脚中存在跨多个 w:r/w:instrText 拆分且带 \* MERGEFORMAT 的 DOCPROPERTY 域时能准确识别并更新。"""
        # 构造跨 3 个 run 拆分的页眉 XML
        hdr_xml = """<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:p>
            <w:r><w:fldChar w:fldCharType="begin"/></w:r>
            <w:r><w:instrText xml:space="preserve"> DOCPROPERTY  "</w:instrText></w:r>
            <w:r><w:instrText>文件编号</w:instrText></w:r>
            <w:r><w:instrText xml:space="preserve">"  \\* MERGEFORMAT </w:instrText></w:r>
            <w:r><w:fldChar w:fldCharType="separate"/></w:r>
            <w:r><w:t>OLD-DOC-000</w:t></w:r>
            <w:r><w:fldChar w:fldCharType="end"/></w:r>
          </w:p>
        </w:hdr>"""
        # 构造简单域 w:fldSimple 的页脚 XML
        ftr_xml = """<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:p>
            <w:fldSimple w:instr=" DOCPROPERTY &quot;版本&quot;  \\* MERGEFORMAT ">
              <w:r><w:t>0.1</w:t></w:r>
            </w:fldSimple>
          </w:p>
        </w:ftr>"""

        items = {
            "word/header1.xml": hdr_xml.encode("utf-8"),
            "word/footer1.xml": ftr_xml.encode("utf-8"),
        }
        config = {
            "documentNo": "DOC-2026-PATROL",
            "documentVersion": "3.5",
            "documentName": "巡检测试报告",
        }

        # 执行页眉与页脚更新
        update_headers(items, config)

        # 验证页眉 DOCPROPERTY 缓存文本已更新为 DOC-2026-PATROL
        new_hdr = etree.fromstring(items["word/header1.xml"])
        hdr_texts = [t.text for t in new_hdr.iter(qn("t"))]
        assert "DOC-2026-PATROL" in hdr_texts
        assert "OLD-DOC-000" not in hdr_texts

        # 验证页脚 w:fldSimple 缓存文本已更新为 3.5
        new_ftr = etree.fromstring(items["word/footer1.xml"])
        ftr_texts = [t.text for t in new_ftr.iter(qn("t"))]
        assert "3.5" in ftr_texts
        assert "0.1" not in ftr_texts

    def test_validate_docx_normalizes_fldsimple_and_footers(self):
        """测试用例：validate_docx._normalize_header_fields 对 w:fldSimple 域和页脚进行归一化，比对不报虚假差异。"""
        ftr_xml = """<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:p>
            <w:fldSimple w:instr=" DOCPROPERTY &quot;文件编号&quot; ">
              <w:r><w:t>OLD-DOC</w:t></w:r>
            </w:fldSimple>
          </w:p>
        </w:ftr>"""
        root = etree.fromstring(ftr_xml.encode("utf-8"))
        config = {"documentNo": "NEW-DOC-999"}

        _normalize_header_fields(root, config)
        texts = [t.text for t in root.iter(qn("t"))]
        assert "NEW-DOC-999" in texts

    def test_safe_output_stem_with_duplicate_versions_and_special_chars(self, tmp_path):
        """测试用例：文档名已包含版本号括号 (V1.0)、特殊非法字符时，输出文件名生成与 _output_stem 安全且不重复版本。"""
        # 1. documentName 本身已包含旧版本号 (V1.0)
        fname = build_output_filename(
            document_no="DOC-100",
            document_name="研发规划文档(V1.0)",
            document_version="2.0",
            document_type="general",
        )
        # 应剥离旧的 (V1.0)，拼接最新的 (2.0)
        assert fname == "DOC-100 研发规划文档(2.0).docx"
        assert "(V1.0)" not in fname

        # 2. documentName 包含全角括号（v1.2）
        fname2 = build_output_filename(
            document_no="",
            document_name="需求规格说明书（v1.2）",
            document_version="3.0",
            document_type="general",
        )
        assert fname2 == "需求规格说明书(3.0).docx"

        # 3. documentNo 前缀去重：若文档名已带编号开头，不重复拼
        fname3 = build_output_filename(
            document_no="PRJ-001",
            document_name="PRJ-001 概要设计",
            document_version="1.0",
            document_type="general",
        )
        assert fname3 == "PRJ-001 概要设计(1.0).docx"
        assert "PRJ-001 PRJ-001" not in fname3
