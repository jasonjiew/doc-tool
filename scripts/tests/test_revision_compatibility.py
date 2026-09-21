# -*- coding: utf-8 -*-
"""Regression and compatibility tests for revision record, import, open, check, and build workflows."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lxml import etree

from docx_common import (
    _cell_text,
    _wqn,
    find_revision_table_info,
    is_revision_footer_row,
    is_revision_header_row,
    map_revision_columns,
    score_revision_header_row,
)
from extract_revision_record import extract_revision_rows, rows_to_markdown
from build_docx import update_revision_record
from doc_tool.application.content.reimport import compare_chapters, _is_revision_record, ReimportService
from doc_tool.application.content.revision_record import (
    document_version_from_record,
    ensure_revision_record,
    last_revision_version,
)
from doc_tool.adapters.roundtrip import _strip_manual_prefix
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.application.project_service import open_project
from doc_tool.ui.window_registry import WindowRegistry


class RevisionCompatibilityTests(unittest.TestCase):
    """Test flexible header detection, keyword expansion, column mapping, and footer truncation."""

    def _make_table_xml(self, rows_data: list[list[str]]) -> etree._Element:
        tbl = etree.Element(_wqn("tbl"))
        for row_data in rows_data:
            tr = etree.SubElement(tbl, _wqn("tr"))
            for text in row_data:
                tc = etree.SubElement(tr, _wqn("tc"))
                p = etree.SubElement(tc, _wqn("p"))
                r = etree.SubElement(p, _wqn("r"))
                t = etree.SubElement(r, _wqn("t"))
                t.text = text
        return tbl

    def _make_doc_xml(self, tbl: etree._Element) -> etree._Element:
        doc = etree.Element(_wqn("document"))
        body = etree.SubElement(doc, _wqn("body"))
        body.append(tbl)
        return doc

    def test_single_row_header_detection(self):
        """单行表头无标题行场景能够正确识别。"""
        rows = [
            ["版次", "变更说明", "变更人", "变更日期"],
            ["1.0", "初始发布", "张三", "2024-01-01"],
        ]
        tbl = self._make_table_xml(rows)
        doc = self._make_doc_xml(tbl)
        info = find_revision_table_info(doc)
        self.assertIsNotNone(info)
        matched_tbl, header_row_idx, (v, s, d, a) = info
        self.assertEqual(header_row_idx, 0)
        self.assertEqual(v, 0)  # 版次
        self.assertEqual(s, 1)  # 变更说明
        self.assertEqual(a, 2)  # 变更人
        self.assertEqual(d, 3)  # 变更日期

    def test_multi_row_header_with_title_banner(self):
        """双行表头（第一行是标题/说明，第二行是真正列名行）。"""
        rows = [
            ["修订摘要", "当前文件版本描述如下：", "", ""],
            ["版本", "修订摘要", "修订时间", "修订人"],
            ["V1.0", "创建文档", "2024-01-01", "李四"],
        ]
        tbl = self._make_table_xml(rows)
        doc = self._make_doc_xml(tbl)
        info = find_revision_table_info(doc)
        self.assertIsNotNone(info)
        matched_tbl, header_row_idx, (v, s, d, a) = info
        self.assertEqual(header_row_idx, 1)  # 正确选中第二行而非第一行
        self.assertEqual(v, 0)
        self.assertEqual(s, 1)
        self.assertEqual(d, 2)
        self.assertEqual(a, 3)

    def test_inverted_columns_mapping(self):
        """列顺序颠倒（版本, 日期, 修改人, 修改说明）正确映射。"""
        headers = ["版本", "修改日期", "修改人", "修改说明"]
        v, s, d, a = map_revision_columns(headers)
        self.assertEqual(v, 0)
        self.assertEqual(d, 1)  # 修改日期
        self.assertEqual(a, 2)  # 修改人
        self.assertEqual(s, 3)  # 修改说明

    def test_expanded_keywords_detection(self):
        """扩展关键字支持：版次、修改、更改、变更、摘要、说明。"""
        headers = ["版次", "更改记录", "发布时间", "编制"]
        self.assertTrue(is_revision_header_row(headers))
        v, s, d, a = map_revision_columns(headers)
        self.assertEqual(v, 0)
        self.assertEqual(s, 1)
        self.assertEqual(d, 2)
        self.assertEqual(a, 3)

    def test_five_columns_with_sequence_number(self):
        """包含序号列的五列表格正确识别。"""
        headers = ["序号", "版本号", "修改内容", "编写人", "修改时间"]
        v, s, d, a = map_revision_columns(headers)
        self.assertEqual(v, 1)  # 版本号
        self.assertEqual(s, 2)  # 修改内容
        self.assertEqual(a, 3)  # 编写人
        self.assertEqual(d, 4)  # 修改时间

    def test_order_number_column_not_confused_with_summary(self):
        """修订单号/变更单号列不得被误识别为修改摘要列。"""
        headers = ["序号", "版次", "修订单号", "修改内容", "修改人", "修改日期"]
        v, s, d, a = map_revision_columns(headers)
        self.assertEqual(v, 1)  # 版次
        self.assertEqual(s, 3)  # 修改内容，而非修订单号(2)
        self.assertEqual(a, 4)  # 修改人
        self.assertEqual(d, 5)  # 修改日期

    def test_is_revision_footer_row(self):
        """非版本审批/说明尾行判定。"""
        self.assertTrue(is_revision_footer_row(["编制：张三", "", "审核：李四", ""]))
        self.assertTrue(is_revision_footer_row(["批准人：王五", "", "", ""]))
        self.assertTrue(is_revision_footer_row(["审核", "李四", "批准", "王五"]))
        self.assertTrue(is_revision_footer_row(["备注：受控文件", "", "", ""]))
        self.assertTrue(is_revision_footer_row(["张三", "技术部", "无", ""]))  # 全中文无数字且无版/稿
        # 正常数据行不能误判
        self.assertFalse(is_revision_footer_row(["V1.0", "初版", "2024-01-01", "张三"]))
        self.assertFalse(is_revision_footer_row(["1.2.3", "更新", "2024-02-01", "李四"]))
        self.assertFalse(is_revision_footer_row(["A", "Rev A", "2024-03-01", "王五"]))

    def test_chinese_version_terms_not_footer(self):
        """中文版本标识（初版、第一版、初稿等）绝不被误判为尾部审批行。"""
        self.assertFalse(is_revision_footer_row(["初版", "首次创建", "2024-01-01", "张三"], 0))
        self.assertFalse(is_revision_footer_row(["第一版", "初始发布", "2024-01-01", "李四"], 0))
        self.assertFalse(is_revision_footer_row(["初稿", "编写草案", "2024-01-01", "王五"], 0))
        self.assertFalse(is_revision_footer_row(["正式版", "定稿", "2024-05-01", "赵六"], 0))

    def test_document_version_from_record_ignores_footer(self):
        """document_version_from_record 能正确跳过末尾审批行提取最新版本号。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            md_path = tmp_dir / "_revision_record.md"
            md_path.write_text(
                "# 修订记录\n\n"
                "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
                "|---|---|---|---|\n"
                "| V1.0 | 初始创建 | 2024-01-01 | 张三 |\n"
                "| 2.5.1 | 增加模块 | 2024-03-15 | 李四 |\n"
                "| 审核 | 李四 | 批准 | 王五 |\n",
                encoding="utf-8",
            )
            # 必须提取 2.5.1 而不是 "审核"
            ver = document_version_from_record(md_path)
            self.assertEqual(ver, "2.5.1")
        finally:
            shutil.rmtree(tmp_dir)

    def test_compare_chapters_ignores_revision_record(self):
        """重新导入比对时，_revision_record.md 得到保护，不被误判为删除或冲突。"""
        tmp_curr = Path(tempfile.mkdtemp())
        tmp_in = Path(tempfile.mkdtemp())
        try:
            (tmp_curr / "chapter1.md").write_text("# Chapter 1\nContent", encoding="utf-8")
            (tmp_curr / "_revision_record.md").write_text("# Revision\nTable", encoding="utf-8")

            (tmp_in / "chapter1.md").write_text("# Chapter 1\nContent Modified", encoding="utf-8")
            # incoming 中没有 _revision_record.md（Word 导入自然拆分出的章节）

            changes = compare_chapters(tmp_curr, tmp_in)
            # changes 中必须只有 chapter1.md，绝不能有 _revision_record.md 被判 deleted
            rel_paths = [c.rel_path for c in changes]
            self.assertIn("chapter1.md", rel_paths)
            self.assertNotIn("_revision_record.md", rel_paths)
            self.assertEqual(len(changes), 1)
        finally:
            shutil.rmtree(tmp_curr)
            shutil.rmtree(tmp_in)

    def test_is_revision_record_helper(self):
        self.assertTrue(_is_revision_record("_revision_record.md"))
        self.assertTrue(_is_revision_record("_revision_record.markdown"))
        self.assertTrue(_is_revision_record("subfolder/_revision_record.md"))
        self.assertTrue(_is_revision_record(".hidden.md"))
        self.assertFalse(_is_revision_record("_index.md"))
        self.assertFalse(_is_revision_record("chapter1.md"))

    def test_open_project_with_manifest_path(self):
        """open_project 与 ProjectPaths 支持直接传入 project.yml 路径。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            manifest_file = tmp_dir / "project.yml"
            manifest_file.write_text(
                "schemaVersion: 1\n"
                "documentType: general\n"
                "documentName: 通用测试\n"
                "documentVersion: 1.0\n",
                encoding="utf-8",
            )
            (tmp_dir / "original").mkdir(parents=True)
            (tmp_dir / "template").mkdir(parents=True)
            (tmp_dir / "template" / "template.docx").write_bytes(b"mock")
            (tmp_dir / "original" / "source.docx").write_bytes(b"mock")

            # 1. open_project
            summary = open_project(str(manifest_file))
            self.assertEqual(summary.manifest.documentName, "通用测试")
            self.assertEqual(summary.project_root, tmp_dir)

            # 2. ProjectPaths
            paths = ProjectPaths(manifest_file)
            self.assertEqual(paths.root, tmp_dir)
            self.assertEqual(paths.manifest_file, manifest_file)

            # 3. ProjectManifest.load
            m = ProjectManifest.load(manifest_file)
            self.assertEqual(m.documentName, "通用测试")

            # 4. manifest.resolve_paths
            rp = m.resolve_paths(manifest_file)
            self.assertEqual(rp.root, tmp_dir)

            # 5. WindowRegistry 路径归一化匹配
            reg = WindowRegistry()
            mock_win = mock.MagicMock()
            mock_win._project_summary = summary
            mock_win._closed = False
            reg.register(mock_win)

            # 传入 project.yml 必须能够正确命中已有窗口
            matched = reg.window_for_project(manifest_file)
            self.assertIs(matched, mock_win)
        finally:
            shutil.rmtree(tmp_dir)

    def test_manifest_from_dict_general_without_doc_no(self):
        """通用大文档无需 documentNo，不报错。"""
        data = {
            "schemaVersion": 1,
            "documentType": "General ",  # 带空格与大写
            "documentName": "用户手册",
            "documentVersion": "2.0",
        }
        manifest = ProjectManifest.from_dict(data)
        self.assertEqual(manifest.documentType, "general")
        self.assertEqual(manifest.documentNo, "")
        self.assertEqual(manifest.documentVersion, "2.0")

    def test_five_columns_sequence_auto_fill_and_footer_protection(self):
        """测试 build_docx.update_revision_record 在含序号列与审批尾行时的兼容回填。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            rev_file = tmp_dir / "_revision_record.md"
            rev_file.write_text(
                "# 修订记录\n\n"
                "| 版本 | 修改内容 | 修改时间 | 修改人 |\n"
                "|---|---|---|---|\n"
                "| 1.0 | 初版说明 | 2024-01-01 | 张三 |\n"
                "| 1.1 | 修正错别字 | 2024-01-02 | 李四 |\n",
                encoding="utf-8",
            )
            # 构造模板表格：行 0 标题横幅，行 1 真正列头（5列），行 2 尾部审批
            rows = [
                ["文档修订历史描述如下：", "", "", "", ""],
                ["序号", "版次", "修改说明", "更改人", "更改日期"],
                ["审核人：", "王五", "", "批准人：", "赵六"],
            ]
            tbl = self._make_table_xml(rows)
            doc = self._make_doc_xml(tbl)
            config = {
                "paths": {"revision_record": str(rev_file)},
                "documentType": "general",
            }
            written = update_revision_record(doc, config)
            self.assertEqual(written, 2)

            # 验证新生成的表格行：
            # header 占 2 行 (rows[0], rows[1])，数据行占 2 行 (rows[2], rows[3])，审批行保留在末尾 (rows[4])
            tbl_rows = tbl.findall(_wqn("tr"))
            self.assertEqual(len(tbl_rows), 5)

            # 验证行 2 (第 1 条数据行): 序号=1, 版次=1.0, 修改说明=初版说明, 更改人=张三, 更改日期=2024-01-01
            r2_texts = [_cell_text(c).strip() for c in tbl_rows[2].findall(_wqn("tc"))]
            self.assertEqual(r2_texts[0], "1")
            self.assertEqual(r2_texts[1], "1.0")
            self.assertEqual(r2_texts[2], "初版说明")
            self.assertEqual(r2_texts[3], "张三")
            self.assertEqual(r2_texts[4], "2024-01-01")

            # 验证行 3 (第 2 条数据行): 序号=2
            r3_texts = [_cell_text(c).strip() for c in tbl_rows[3].findall(_wqn("tc"))]
            self.assertEqual(r3_texts[0], "2")
            self.assertEqual(r3_texts[1], "1.1")

            # 验证行 4 为未被篡改的原有审批行
            r4_texts = [_cell_text(c).strip() for c in tbl_rows[4].findall(_wqn("tc"))]
            self.assertEqual(r4_texts[0], "审核人：")
            self.assertEqual(r4_texts[1], "王五")
        finally:
            shutil.rmtree(tmp_dir)


class RoundtripPrefixTests(unittest.TestCase):
    """测试往返对齐时中文序号的前缀剥离。"""

    def test_strip_chinese_manual_prefixes(self):
        self.assertEqual(_strip_manual_prefix("（1） 概述"), "概述")
        self.assertEqual(_strip_manual_prefix("(2) 架构说明"), "架构说明")
        self.assertEqual(_strip_manual_prefix("1) 需求详情"), "需求详情")
        self.assertEqual(_strip_manual_prefix("① 流程定义"), "流程定义")
        self.assertEqual(_strip_manual_prefix("一、 背景"), "背景")
        self.assertEqual(_strip_manual_prefix("十二、 总结"), "总结")
        self.assertEqual(_strip_manual_prefix("1. 普通编号"), "普通编号")
        self.assertEqual(_strip_manual_prefix("1、 中文顿号"), "中文顿号")
        # 增强：括号中文数字与一.
        self.assertEqual(_strip_manual_prefix("（一）概述"), "概述")
        self.assertEqual(_strip_manual_prefix("(一) 概述"), "概述")
        self.assertEqual(_strip_manual_prefix("（二）项目背景"), "项目背景")
        self.assertEqual(_strip_manual_prefix("一. 项目背景"), "项目背景")
        # 正常业务文本不被误删
        self.assertEqual(_strip_manual_prefix("一体化设计理念"), "一体化设计理念")
        self.assertEqual(_strip_manual_prefix("一些需要关注的问题"), "一些需要关注的问题")



if __name__ == "__main__":
    unittest.main()
