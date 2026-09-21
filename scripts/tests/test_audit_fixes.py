# -*- coding: utf-8 -*-
"""Regression tests for issues identified during line-by-line code audit."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from lxml import etree

from doc_tool.adapters.roundtrip import _classify_error, _strip_manual_prefix
from doc_tool.application.content.revision_record import last_revision_version
from doc_tool.application.import_project import _seed_reimport_base
from doc_tool.application.project_service import add_recent_project, load_recent_projects, open_project
from doc_tool.domain.errors import ProjectManifestError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths, normalize_document_version
from doc_tool.ui.window_registry import WindowRegistry
from scripts.build_docx import _set_revision_cell_text, update_revision_record
from docx_common import (
    _cell_text,
    _wqn,
    find_revision_table_info,
    is_revision_footer_row,
    map_revision_columns,
    score_revision_header_row,
)


class AuditFixesTests(unittest.TestCase):
    """验证逐行代码审计中发现并修复的问题。"""

    def _make_table_xml(self, rows_text):
        tbl = etree.Element(_wqn("tbl"))
        for r_texts in rows_text:
            tr = etree.SubElement(tbl, _wqn("tr"))
            for t in r_texts:
                tc = etree.SubElement(tr, _wqn("tc"))
                p = etree.SubElement(tc, _wqn("p"))
                r = etree.SubElement(p, _wqn("r"))
                t_node = etree.SubElement(r, _wqn("t"))
                t_node.text = t
        return tbl

    def _make_doc_xml(self, tbl):
        doc = etree.Element(_wqn("document"))
        body = etree.SubElement(doc, _wqn("body"))
        body.append(tbl)
        return doc

    def test_score_revision_header_row_with_colon(self):
        """表头单元格带冒号或简短标签时得分必须大于 0，不得被误判为说明句。"""
        sc = score_revision_header_row(["版本", "修改内容", "日期:"])
        self.assertGreater(sc, 0)

        sc2 = score_revision_header_row(["版本号：", "修改说明", "编写人：", "更改日期："])
        self.assertGreater(sc2, 0)

        # 包含长说明句或'如下'的行仍应得 0
        sc_desc = score_revision_header_row(["文档修订历史如下：", "请参阅下表并按要求填写修订记录"])
        self.assertEqual(sc_desc, 0)

    def test_score_revision_header_row_requires_distinct_columns(self):
        """单列同时命中版本与摘要关键词（如'修订版本'）时，不得判定为有效表头。"""
        # 没有摘要列，只有'修订版本'同时匹配了版本和摘要关键字
        sc_single = score_revision_header_row(["序号", "修订版本", "发布日期", "编制人"])
        self.assertEqual(sc_single, 0)

        # 具备独立的版本和摘要列时得分应大于 0
        sc_valid = score_revision_header_row(["序号", "版本", "修改内容", "发布日期", "编制人"])
        self.assertGreater(sc_valid, 0)

    def test_map_revision_columns_prefers_non_index(self):
        """兜底映射列时，非序号/单号列优先被映射到版本与修改摘要。"""
        v_col, s_col, d_col, a_col = map_revision_columns(["序号", "修改内容", "发布日期", "编制人", "版本"])
        self.assertEqual(v_col, 4)
        self.assertEqual(s_col, 1)
        self.assertEqual(d_col, 2)
        self.assertEqual(a_col, 3)

    def test_is_revision_footer_row_notes(self):
        """尾部备注/说明行（即使版本列在非第 0 列或内容在第 0 列）也能被识别为 footer_row。"""
        self.assertTrue(is_revision_footer_row(["注：本修订记录由质量部维护", "", "", "", ""], v_col=1))
        self.assertTrue(is_revision_footer_row(["说明：修改前请先确认权限", "", "", "", ""], v_col=1))
        self.assertTrue(is_revision_footer_row(["备注：本页仅供内部使用", "", "", "", ""], v_col=1))
        self.assertFalse(is_revision_footer_row(["", "", "", ""], v_col=1))
        self.assertFalse(is_revision_footer_row(["1.0", "初版", "2024-01-01", "张三"], v_col=0))

    def test_is_revision_footer_row_chinese_versions(self):
        """中文版本名称（如'初始发布'、'第一次修订'、'基线一'）不得被误判为 footer_row。"""
        self.assertFalse(is_revision_footer_row(["初始发布", "系统初始化", "2024-01-01", "张三"], v_col=0))
        self.assertFalse(is_revision_footer_row(["第一次修订", "修改架构", "2024-01-02", "李四"], v_col=0))
        self.assertFalse(is_revision_footer_row(["基线一", "完成基线定义", "2024-01-03", "王五"], v_col=0))
        self.assertFalse(is_revision_footer_row(["正式发布", "正式上线", "2024-01-04", "赵六"], v_col=0))

    def test_is_revision_footer_row_approval_standalone_and_english(self):
        """审批/签名等独立标签行（含首列空、英文审核人等）能被正确识别为 footer_row。"""
        self.assertTrue(is_revision_footer_row(["", "审核", "张三", "批准", "李四"], v_col=0))
        self.assertTrue(is_revision_footer_row(["审核", "John", "批准", "Alice"], v_col=1))
        self.assertTrue(is_revision_footer_row(["", "编制", "张三", "审核", "李四"], v_col=0))

        # 修改说明中提及审核但为普通修改记录的行，不得被误判为 footer_row
        self.assertFalse(is_revision_footer_row(["V1.0", "修复审核流程提出的缺陷", "2024-01-01", "张三"], v_col=0))

    def test_multi_row_header_support(self):
        """多行表头时，合并前后两行表头能够识别出完整列映射。"""
        rows = [
            ["版本", "修改内容", "变更签署", ""],
            ["", "", "修改人", "修改时间"],
            ["1.0", "初始版本", "张三", "2024-01-01"],
        ]
        tbl = self._make_table_xml(rows)
        doc = self._make_doc_xml(tbl)
        info = find_revision_table_info(doc)
        self.assertIsNotNone(info)
        matched_tbl, header_row_idx, (v_col, s_col, d_col, a_col) = info
        self.assertEqual(header_row_idx, 1)
        self.assertEqual(v_col, 0)
        self.assertEqual(s_col, 1)
        self.assertEqual(a_col, 2)
        self.assertEqual(d_col, 3)

    def test_roundtrip_chinese_parentheses_prefixes(self):
        """全角右括号与中文数字编号在往返门禁中能被正确剥离前缀。"""
        self.assertEqual(_strip_manual_prefix("1） 概述"), "概述")
        self.assertEqual(_strip_manual_prefix("2） 架构说明"), "架构说明")
        self.assertEqual(_strip_manual_prefix("一） 背景"), "背景")
        self.assertEqual(_strip_manual_prefix("一) 需求说明"), "需求说明")
        self.assertEqual(_strip_manual_prefix("二） 核心设计"), "核心设计")

    def test_roundtrip_manual_prefix_brackets_and_circled(self):
        """方括号编号（[1]、[一]、大括号、带圈数字1-20）在往返门禁中能被正确剥离。"""
        self.assertEqual(_strip_manual_prefix("[1] 概述"), "概述")
        self.assertEqual(_strip_manual_prefix("【1】 架构说明"), "架构说明")
        self.assertEqual(_strip_manual_prefix("【一】 背景"), "背景")
        self.assertEqual(_strip_manual_prefix("① 引言"), "引言")
        self.assertEqual(_strip_manual_prefix("⑩ 附录"), "附录")
        self.assertEqual(_strip_manual_prefix("⑪ 扩展说明"), "扩展说明")
        self.assertEqual(_strip_manual_prefix("⑳ 总结"), "总结")

    def test_roundtrip_classify_error_various_formats(self):
        """_classify_error 支持基线及非基线位置不一致差异格式，正确提取 position。"""
        issue1 = _classify_error("#0 内容/位置不一致: expected=A, actual=B", [], [])
        self.assertEqual(issue1.position, "#0")

        issue2 = _classify_error("#3 基线内容/位置不一致: source A; rebuild B", [], [])
        self.assertEqual(issue2.position, "#3")

    def test_last_revision_version_with_sequence_column(self):
        """当修订记录表第一列为序号、第二列为版本时，能提取到正确的版本号而非序号数字。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            rev_file = tmp_dir / "_revision_record.md"
            lines = [
                "# 修订记录",
                "",
                "| 序号 | 版本 | 修改摘要 | 修改时间 | 修改人 |",
                "|---|---|---|---|---|",
                "| 1 | 1.0 | 初版 | 2024-01-01 | 张三 |",
                "| 2 | 1.1 | 修正错别字 | 2024-01-02 | 李四 |",
                "",
            ]
            rev_file.write_text("\n".join(lines), encoding="utf-8")
            v = last_revision_version(rev_file)
            self.assertEqual(v, "1.1")
        finally:
            shutil.rmtree(tmp_dir)

    def test_last_revision_version_no_version_column(self):
        """当修订记录表无真实版本列（仅有'序号'与'版本说明/修改说明'）时，返回 None 而不误用序号。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            rev_file = tmp_dir / "_revision_record.md"
            lines = [
                "# 修订记录",
                "",
                "| 序号 | 版本说明 | 修改时间 | 修改人 |",
                "|---|---|---|---|",
                "| 1 | 初版完成并提交评审 | 2024-01-01 | 张三 |",
                "| 2 | 根据评审修改 | 2024-01-02 | 李四 |",
                "",
            ]
            rev_file.write_text("\n".join(lines), encoding="utf-8")
            v = last_revision_version(rev_file)
            self.assertIsNone(v)
        finally:
            shutil.rmtree(tmp_dir)

    def test_set_revision_cell_text_br_tags(self):
        """_set_revision_cell_text 将 <br> 标签转换为 w:br 节点。"""
        cell = etree.Element(_wqn("tc"))
        _set_revision_cell_text(cell, "张三<br>李四<br/>王五")
        br_nodes = cell.findall(".//" + _wqn("br"))
        self.assertEqual(len(br_nodes), 2)
        t_nodes = cell.findall(".//" + _wqn("t"))
        texts = [t.text for t in t_nodes]
        self.assertEqual(texts, ["张三", "李四", "王五"])

    def test_update_revision_record_cleans_trailing_empty_rows(self):
        """更新修订记录表时，表格末尾纯空行被自动剔除且不破坏上方 footer 审批行的保留。"""
        rows = [
            ["版本", "修改内容", "日期", "作者"],
            ["1.0", "初始版本", "2024-01-01", "张三"],
            ["审核：李四", "", "", ""],
            ["", "", "", ""],  # 尾部空行
        ]
        tbl = self._make_table_xml(rows)
        doc = self._make_doc_xml(tbl)

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            rev_file = tmp_dir / "_revision_record.md"
            rev_file.write_text(
                "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n|---|---|---|---|\n| 2.0 | 全新发布 | 2024-02-01 | 王五 |\n",
                encoding="utf-8",
            )
            config = {"paths": {"revision_record": str(rev_file)}}
            count = update_revision_record(doc, config)
            self.assertEqual(count, 1)

            # 验证结果表格中保留了表头、新写入的 2.0 行、以及审批 footer 行
            final_rows = tbl.findall(_wqn("tr"))
            self.assertEqual(len(final_rows), 3)  # header + new data + footer
            footer_text = _cell_text(final_rows[-1].find(_wqn("tc")))
            self.assertEqual(footer_text, "审核：李四")
        finally:
            shutil.rmtree(tmp_dir)

    def test_normalize_document_version_none(self):
        """None 传给 normalize_document_version 或 ProjectManifest 不会变为字符串 'None'。"""
        self.assertEqual(normalize_document_version(None), "")
        self.assertEqual(normalize_document_version("V2.5"), "2.5")

        manifest = ProjectManifest(
            documentType="general",
            documentNo=None,
            documentName="测试手册",
            documentVersion=None,
            sourceSha256="abc",
        )
        self.assertEqual(manifest.documentNo, "")
        self.assertEqual(manifest.documentName, "测试手册")
        self.assertEqual(manifest.documentVersion, "")

    def test_manifest_load_and_open_project_empty_path(self):
        """ProjectManifest.load 与 open_project 传入空路径时直接抛出 ProjectManifestError。"""
        with self.assertRaises(ProjectManifestError):
            ProjectManifest.load("")
        with self.assertRaises(ProjectManifestError):
            ProjectManifest.load("   ")
        with self.assertRaises(ProjectManifestError):
            open_project("")
        with self.assertRaises(ProjectManifestError):
            open_project("   ")

    def test_add_recent_project_deduplication_windows(self):
        """在 Windows 大小写与不同斜杠下，add_recent_project 能正确去重。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            mock_config_dir = tmp_dir / "config"
            mock_config_dir.mkdir(parents=True)
            proj_dir = tmp_dir / "ProjectAlpha"
            proj_dir.mkdir(parents=True)
            with mock.patch("doc_tool.application.project_service._config_dir", return_value=mock_config_dir):
                m = ProjectManifest(
                    documentType="general",
                    documentNo="DOC-01",
                    documentName="项目A",
                    documentVersion="1.0",
                    sourceSha256="123",
                )
                proj_path = str(proj_dir)
                add_recent_project(proj_path.upper(), m)
                add_recent_project(proj_path.lower(), m)
                add_recent_project(proj_path.replace("\\", "/"), m)

                entries = load_recent_projects()
                self.assertEqual(len(entries), 1)
        finally:
            shutil.rmtree(tmp_dir)

    def test_window_registry_empty_string_does_not_match(self):
        """空字符串或 None 在 window_for_project 中不会误匹配到当前工作目录。"""
        reg = WindowRegistry()
        mock_win = mock.MagicMock()
        mock_summary = mock.MagicMock()
        mock_summary.project_root = Path.cwd()
        mock_win._project_summary = mock_summary
        mock_win._closed = False
        reg.register(mock_win)

        self.assertIsNone(reg.window_for_project(""))
        self.assertIsNone(reg.window_for_project(None))
        self.assertIsNone(reg.window_for_project("   "))
        self.assertIs(reg.window_for_project(str(Path.cwd())), mock_win)

    def test_seed_reimport_base_preserves_index_md(self):
        """_seed_reimport_base 保留 _index.md，且必须排除 _revision_record.md。"""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            content_dir = tmp_dir / "content" / "general"
            content_dir.mkdir(parents=True)
            (content_dir / "_index.md").write_text("# Overview", encoding="utf-8")
            (content_dir / "chapter1.md").write_text("# Chapter 1", encoding="utf-8")
            (content_dir / "_revision_record.md").write_text("# Revision", encoding="utf-8")

            paths = ProjectPaths(tmp_dir)
            _seed_reimport_base(paths, "general")

            base_json = tmp_dir / ".state" / "reimport_base.json"
            self.assertTrue(base_json.is_file())
            data = json.loads(base_json.read_text(encoding="utf-8"))
            files = data.get("files", {})
            self.assertIn("_index.md", files)
            self.assertIn("chapter1.md", files)
            self.assertNotIn("_revision_record.md", files)
        finally:
            shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    unittest.main()
