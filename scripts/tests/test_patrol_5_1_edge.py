# -*- coding: utf-8 -*-
"""Regression tests for Patrol 5.1: 导入拆解边界与畸形 Word 容错巡检."""

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
from doc_tool.adapters.importer import (
    _is_toc_element,
    _find_pre_title_body_start,
    _find_first_heading1,
    _unwrap_block_sdts,
    _para_text_raw,
    _para_image_info,
)
from doc_tool.domain.smart_features import (
    _cell_visible_text,
    extract_complex_table_proxy_rows,
    format_complex_table_proxy_lines,
)


class TestPatrol51ImportEdgeCases:
    def test_sdt_toc_detected_accurately(self):
        """测试用例：使用 w:sdt 包装的标准 Word 目录结构能够被 _is_toc_element 准确识别。"""
        sdt_toc_xml = """<w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:sdtPr>
            <w:docPartObj>
              <w:docPartGallery w:val="Table of Contents"/>
            </w:docPartObj>
          </w:sdtPr>
          <w:sdtContent>
            <w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> TOC \\o "1-3" </w:instrText></w:r></w:p>
          </w:sdtContent>
        </w:sdt>"""
        el = etree.fromstring(sdt_toc_xml.encode("utf-8"))
        assert _is_toc_element(el) is True

    def test_body_sdt_content_controls_unwrapped(self):
        """测试用例：正文中被 w:sdt 内容控件包裹的 Heading 1 与表格在 _unwrap_block_sdts 展开后能被正确提取。"""
        body_with_sdt = """<w:body xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:sdt>
            <w:sdtPr><w:tag w:val="sec_header"/></w:sdtPr>
            <w:sdtContent>
              <w:p>
                <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
                <w:r><w:t>第1章 概述</w:t></w:r>
              </w:p>
              <w:p>
                <w:r><w:t>正文说明段落</w:t></w:r>
              </w:p>
            </w:sdtContent>
          </w:sdt>
        </w:body>"""
        body_el = etree.fromstring(body_with_sdt.encode("utf-8"))
        # 展开前，直接子节点为 sdt
        assert len(body_el) == 1
        assert etree.QName(body_el[0]).localname == "sdt"

        # 展开后，内部段落直接成为 body 子节点
        _unwrap_block_sdts(body_el)
        assert len(body_el) == 2
        assert etree.QName(body_el[0]).localname == "p"
        assert _find_first_heading1(list(body_el), {"Heading1": 1}) == 0

    def test_nested_table_in_cell_preserves_text_and_proxy(self):
        """测试用例：单元格中存在嵌套表格时，_cell_visible_text 与代理表提取能够提取子表格文本。"""
        nested_tbl_xml = """<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:tr>
            <w:tc>
              <w:p><w:r><w:t>外层单元格A</w:t></w:r></w:p>
              <w:tbl>
                <w:tr>
                  <w:tc><w:p><w:r><w:t>内层嵌套1</w:t></w:r></w:p></w:tc>
                  <w:tc><w:p><w:r><w:t>内层嵌套2</w:t></w:r></w:p></w:tc>
                </w:tr>
              </w:tbl>
            </w:tc>
            <w:tc>
              <w:p><w:r><w:t>外层单元格B</w:t></w:r></w:p>
            </w:tc>
          </w:tr>
        </w:tbl>"""
        tbl = etree.fromstring(nested_tbl_xml.encode("utf-8"))
        tc_a = tbl.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr")[0].findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc")[0]
        vis_txt = _cell_visible_text(tc_a)
        assert "外层单元格A" in vis_txt
        assert "内层嵌套1" in vis_txt
        assert "内层嵌套2" in vis_txt

        raw_rows, tc_rows = extract_complex_table_proxy_rows(tbl)
        assert len(raw_rows) == 1
        assert "内层嵌套1" in raw_rows[0][0]

    def test_floating_image_and_formula_extraction(self):
        """测试用例：浮动图片 (wp:anchor) 与数学公式 (m:oMath) 能够提取尺寸与文本。"""
        p_xml = """<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                         xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
                         xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                         xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
                         xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                         xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
          <w:r><w:t>质能转换方程：</w:t></w:r>
          <m:oMath><m:r><m:t>E=mc^2</m:t></m:r></m:oMath>
          <w:r>
            <w:drawing>
              <wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="251658240" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
                <wp:extent cx="8888" cy="9999"/>
                <a:graphic>
                  <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                    <pic:pic>
                      <pic:blipFill>
                        <a:blip r:embed="rIdFloating"/>
                      </pic:blipFill>
                    </pic:pic>
                  </a:graphicData>
                </a:graphic>
              </wp:anchor>
            </w:drawing>
          </w:r>
        </w:p>"""
        p_el = etree.fromstring(p_xml.encode("utf-8"))
        raw_text = _para_text_raw(p_el)
        assert "质能转换方程：" in raw_text
        assert "E=mc^2" in raw_text

        img_infos = _para_image_info(p_el)
        assert len(img_infos) == 1
        assert img_infos[0]["rid"] == "rIdFloating"
        assert img_infos[0]["cx"] == 8888
        assert img_infos[0]["cy"] == 9999

    def test_pre_title_boundary_with_cover_revision_and_toc(self):
        """测试用例：首个一级标题前同时包含封面表、修订记录表、TOC (w:sdt) 与分节符时切分点精准。"""
        doc_xml = """<w:body xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <!-- 0: 封面表 -->
          <w:tbl><w:tr><w:tc><w:p><w:r><w:t>文档名称</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          <!-- 1: 修订记录表 -->
          <w:tbl><w:tr><w:tc><w:p><w:r><w:t>修订历史</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          <!-- 2: 目录 TOC sdt -->
          <w:sdt>
            <w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>
            <w:sdtContent><w:p><w:pStyle w:val="TOC1"/><w:r><w:t>目录项 1</w:t></w:r></w:p></w:sdtContent>
          </w:sdt>
          <!-- 3: 分节符 -->
          <w:p><w:pPr><w:sectPr/></w:pPr></w:p>
          <!-- 4: 空白段落 -->
          <w:p/>
          <!-- 5: 引言正文 -->
          <w:p><w:r><w:t>这是项目的前言背景说明。</w:t></w:r></w:p>
          <!-- 6: 一级标题 -->
          <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第1章 范围</w:t></w:r></w:p>
        </w:body>"""
        body_el = etree.fromstring(doc_xml.encode("utf-8"))
        children = list(body_el)
        first_h1_idx = _find_first_heading1(children, {"Heading1": 1})
        assert first_h1_idx is not None

        start_idx = _find_pre_title_body_start(children, first_h1_idx)
        # 应准确跳过 封面表、修订表、TOC (w:sdt)、分节符及空行，锁定引言正文节点
        assert start_idx < first_h1_idx
        assert "这是项目的前言背景说明。" in etree.tostring(children[start_idx], encoding="utf-8").decode("utf-8")
