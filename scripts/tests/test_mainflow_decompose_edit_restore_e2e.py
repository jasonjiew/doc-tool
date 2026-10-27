# -*- coding: utf-8 -*-
"""Mainflow End-to-End Regression Suite (Task 4.2).

全面验证从「分解/导入 -> 编辑/增表/修订 -> 格式还原/导出」的 6 大核心闭环场景：
1. test_e2e_1_general_project_cover_and_header_sync:
   general 模板封面信息表、页眉 DOCPROPERTY 及 custom.xml 同义属性同步更新且校验通过；
2. test_e2e_2_complex_table_proxy_edit_and_row_append_never_crashes:
   复杂表格代理（含跨列合并与跨行继续），修改普通/合并单元格、末尾追加行及损坏容错降级；
3. test_e2e_3_post_refresh_validation_soft_warning_preserves_docx:
   后刷新校验软警告不阻断正式输出，硬错误时保留待刷新中间稿；
4. test_e2e_4_retain_pre_title_body_no_duplication:
   首个 Heading 1 前正文提取到 01-前言.md，模板生成时排重不发生二次重复；
5. test_e2e_5_non_contiguous_chapter_numbers_and_inline_headings_build_cleanly:
   不连续章节编号（跳号）与行内小节自动平移，构建顺利产出合法 docx；
6. test_e2e_6_cli_decompose_inspect_edit_export_full_chain:
   CLI 全流程闭环：decompose -> inspect-properties -> 修改 -> export -D。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
for p in (ROOT, SCRIPTS_DIR, SCRIPTS_DIR / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from doc_tool.adapters.kernel import build_with_project, validate_with_project
from doc_tool.application.cli_commands import import_command
from doc_tool.application.import_project import ImportRequest, import_first_time
from doc_tool.application.intake_contract import (
    FORMAT_DOCX,
    SCOPE_PROJECT,
    SOURCE_MODE_SAVED,
    STATUS_FAILED,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
    ExportRequest,
    ExportScope,
)
from doc_tool.application.pipeline import (
    STAGE_VALIDATE_POST,
    run_pipeline,
)
from doc_tool.application.project_export import run_project_export
from doc_tool.cli import main as cli_main
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.smart_features import (
    apply_complex_table_proxy_edits,
    extract_complex_table_proxy_rows,
    format_complex_table_proxy_lines,
)
from scripts.tests import core_fixtures as fixtures

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
}


def _update_docx_xml_parts(docx_path: Path, part_updates: dict) -> None:
    temp_zip = docx_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(docx_path, "r") as zin, zipfile.ZipFile(temp_zip, "w") as zout:
        for item in zin.infolist():
            if item.filename in part_updates:
                zout.writestr(item.filename, part_updates[item.filename])
            else:
                zout.writestr(item, zin.read(item.filename))
        for filename, content in part_updates.items():
            if filename not in zin.namelist():
                zout.writestr(filename, content)
    shutil.move(temp_zip, docx_path)


class MainflowDecomposeEditRestoreE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="e2e_mainflow_"))

    def tearDown(self) -> None:
        try:
            fixtures.cleanup(self.tmp_dir)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Scenario 1: general 项目封面、页眉及 custom.xml 同义属性同步更新且软校验通过
    # ------------------------------------------------------------------
    def test_e2e_1_general_project_cover_and_header_sync(self) -> None:
        proj_dir = fixtures.two_chapter_project(self.tmp_dir / "proj1", document_type="general")
        paths = ProjectPaths(proj_dir)
        manifest = ProjectManifest.load(paths.manifest_file)

        # 1. 注入封面信息表与页眉属性到 template.docx
        template_docx = paths.template_docx
        custom_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="文档编号"><vt:lpwstr>DOC-001</vt:lpwstr></property>
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="3" name="版本"><vt:lpwstr>1.0</vt:lpwstr></property>
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="4" name="文档名称"><vt:lpwstr>初始文档</vt:lpwstr></property>
</Properties>"""

        # 在 document.xml 中放置含文档编号、版本号、文档名称的封面表格
        with zipfile.ZipFile(template_docx, "r") as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")

        cover_tbl = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '  <w:tr>'
            '    <w:tc><w:p><w:r><w:t>文档编号</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>DOC-001</w:t></w:r></w:p></w:tc>'
            '  </w:tr>'
            '  <w:tr>'
            '    <w:tc><w:p><w:r><w:t>版本号</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>1.0</w:t></w:r></w:p></w:tc>'
            '  </w:tr>'
            '  <w:tr>'
            '    <w:tc><w:p><w:r><w:t>文档名称</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>初始文档</w:t></w:r></w:p></w:tc>'
            '  </w:tr>'
            '</w:tbl>'
        )
        insert_idx = doc_xml.find("<w:body>") + len("<w:body>")
        doc_xml = doc_xml[:insert_idx] + cover_tbl + doc_xml[insert_idx:]

        header1_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:r><w:t>通用设计说明书 - 版本: 1.0</w:t></w:r>
    <w:fldSimple w:instr=" DOCPROPERTY &quot;版本&quot; "><w:r><w:t>1.0</w:t></w:r></w:fldSimple>
  </w:p>
</w:hdr>"""

        _update_docx_xml_parts(template_docx, {
            "docProps/custom.xml": custom_xml.encode("utf-8"),
            "word/document.xml": doc_xml.encode("utf-8"),
            "word/header1.xml": header1_xml.encode("utf-8"),
        })

        # 2. 写入修订记录 _revision_record.md 并指定版本 V2.3
        rev_md = paths.resolve(manifest.relative_content_root()) / "_revision_record.md"
        rev_md.write_text(
            "## 修订记录\n\n"
            "| 版本 | 日期 | 修订人 | 说明 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1.0 | 2026-01-01 | tester | 初稿 |\n"
            "| V2.3 | 2026-10-27 | tester | 闭环回归 |\n",
            encoding="utf-8",
        )
        manifest.documentVersion = "V2.3"
        manifest.save(paths.manifest_file)

        out_docx = paths.output_dir / "out_e2e_1.docx"
        paths.output_dir.mkdir(parents=True, exist_ok=True)

        # 3. 执行 build_with_project
        build_res = build_with_project(
            manifest,
            paths,
            output_override=out_docx,
        )
        self.assertTrue(out_docx.exists(), "导出 docx 应该存在")

        # 4. 验证生成的 DOCX 内的封面、页眉及 docProps/custom.xml
        with zipfile.ZipFile(out_docx, "r") as z:
            out_doc_xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("2.3", out_doc_xml, "封面版本号应同步更新为 2.3")
            if "word/header1.xml" in z.namelist():
                out_hdr_xml = z.read("word/header1.xml").decode("utf-8")
                self.assertIn("2.3", out_hdr_xml, "页眉版本号应同步更新为 2.3")
            if "docProps/custom.xml" in z.namelist():
                out_custom_xml = z.read("docProps/custom.xml").decode("utf-8")
                self.assertIn("2.3", out_custom_xml, "custom.xml 版本属性应同步更新为 2.3")
                self.assertIn("DOC-001", out_custom_xml)

        # 5. 验证 validate_with_project(require_refreshed=True) 能够软通过 (不报硬错误)
        val_ok = validate_with_project(
            manifest,
            paths,
            output_override=out_docx,
            require_refreshed=True,
        )
        self.assertTrue(val_ok, "Word 刷新后页眉静态文本/同义属性软差异不应使整体校验失败")

    # ------------------------------------------------------------------
    # Scenario 2: 复杂表格代理编辑与动态追加行不崩溃，损坏降级
    # ------------------------------------------------------------------
    def test_e2e_2_complex_table_proxy_edit_and_row_append_never_crashes(self) -> None:
        tbl_xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '  <w:tr>'
            '    <w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>表头合并</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>说明</w:t></w:r></w:p></w:tc>'
            '  </w:tr>'
            '  <w:tr>'
            '    <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>跨行组</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>细项1</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>备注1</w:t></w:r></w:p></w:tc>'
            '  </w:tr>'
            '  <w:tr>'
            '    <w:tc><w:tcPr><w:vMerge w:val="continue"/></w:tcPr><w:p><w:r><w:t/></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>细项2</w:t></w:r></w:p></w:tc>'
            '    <w:tc><w:p><w:r><w:t>备注2</w:t></w:r></w:p></w:tc>'
            '  </w:tr>'
            '</w:tbl>'
        )
        tbl_el = ET.fromstring(tbl_xml)
        rows, meta = extract_complex_table_proxy_rows(tbl_el)
        self.assertEqual(len(rows), 3)

        # 场景 A: 修改普通单元格 + 修改跨行占位单元格
        rows_edited = [
            ["表头合并", "", "修改后的说明"],
            ["跨行组", "细项1已更新", "备注1"],
            ["跨行组", "细项2已更新", "备注2"],
        ]
        cnt = apply_complex_table_proxy_edits(tbl_el, rows_edited)
        self.assertTrue(cnt)
        after_xml = ET.tostring(tbl_el, encoding="utf-8").decode("utf-8")
        self.assertIn("细项1已更新", after_xml)

        # 场景 B: 在末尾动态追加一行 (Task 2.1 容错扩展)
        rows_appended = list(rows_edited)
        rows_appended.append(["新分组", "追加细项3", "追加备注3"])
        cnt_append = apply_complex_table_proxy_edits(tbl_el, rows_appended)
        self.assertTrue(cnt_append)
        appended_xml = ET.tostring(tbl_el, encoding="utf-8").decode("utf-8")
        self.assertIn("追加细项3", appended_xml)

        # 场景 C: 损坏的 proxy 字符串在 build_docx 中自动降级
        proj_dir = fixtures.two_chapter_project(self.tmp_dir / "proj_tbl", document_type="general")
        paths = ProjectPaths(proj_dir)
        manifest = ProjectManifest.load(paths.manifest_file)
        ch1 = paths.resolve(manifest.relative_content_root()) / "01-概述.md"
        ch1.write_text(
            "# 第一章 概述\n\n"
            "<!-- COMPLEX_TABLE_PROXY:tbl_corrupted rows=2,cols=2 -->\n"
            "| 坏头1 | 坏头2 |\n"
            "| --- | --- |\n"
            "| 数据A | 数据B |\n\n"
            "段落说明\n",
            encoding="utf-8",
        )
        out_docx = paths.output_dir / "out_proxy_fallback.docx"
        res = build_with_project(manifest, paths, output_override=out_docx)
        self.assertTrue(out_docx.exists())

    # ------------------------------------------------------------------
    # Scenario 3: 后刷新软警告不阻断输出，硬错误保留待刷新文件
    # ------------------------------------------------------------------
    def test_e2e_3_post_refresh_validation_soft_warning_preserves_docx(self) -> None:
        proj_dir = fixtures.two_chapter_project(self.tmp_dir / "proj_soft", document_type="general")
        paths = ProjectPaths(proj_dir)
        manifest = ProjectManifest.load(paths.manifest_file)

        req = ExportRequest(
            project_root=str(proj_dir),
            formats=[FORMAT_DOCX],
            scope=ExportScope(kind=SCOPE_PROJECT),
            source_mode=SOURCE_MODE_SAVED,
            destination=str(paths.output_dir),
            refresh=False,
        )

        # 模拟 validate_with_project 仅报软警告 (warn_only=True)
        with patch("doc_tool.adapters.kernel.validate_with_project", return_value=True):
            result = run_project_export(req)
            self.assertTrue(
                any(r.status in (STATUS_READY, STATUS_PENDING_REFRESH) for r in result.results),
                "只有软警告时导出应当成功",
            )
            self.assertTrue(paths.output_dir.exists())
            docx_files = list(paths.output_dir.glob("*.docx"))
            self.assertGreater(len(docx_files), 0, "输出目录中应有正式 docx")

        # 模拟 STAGE_VALIDATE_POST 硬失败时，待刷新输出被 _preserve_pending_output 暂存保留
        def mock_validate_post(*args, **kwargs):
            if kwargs.get("require_refreshed"):
                return False
            return True

        pending_dir = paths.output_dir / "待刷新"
        with patch("doc_tool.adapters.kernel.refresh_with_project", return_value=(True, "")), \
             patch("doc_tool.adapters.kernel.validate_with_project", side_effect=mock_validate_post):
            pipe_res = run_pipeline(manifest, paths, skip_word_refresh=False)
            self.assertFalse(pipe_res.success)
            self.assertTrue(pending_dir.exists(), "待刷新目录应当存在")
            preserved = list(pending_dir.glob("*.docx"))
            self.assertGreater(len(preserved), 0, "即使后校验硬错误，刷新/暂存稿也必须在待刷新目录中保留")

    # ------------------------------------------------------------------
    # Scenario 4: 首个 Heading 1 前正文提取到 01-前言.md，排重不重复
    # ------------------------------------------------------------------
    def test_e2e_4_retain_pre_title_body_no_duplication(self) -> None:
        src_docx = self.tmp_dir / "pre_title_source.docx"
        fixtures.build_docx(src_docx, [
            ("p", "前言引言段落一"),
            ("p", "前言引言段落二"),
            ("h1", "第一章 核心系统"),
            ("p", "第一章正文内容"),
        ])

        target_proj = self.tmp_dir / "proj_pre_title"
        req = ImportRequest(
            source_docx=src_docx,
            target_project_root=target_proj,
            document_type="general",
            document_no="DOC-PRE-01",
            document_name="前言测试项目",
            document_version="1.0",
            decide_pre_title_body=True,
            pre_title_chapter_title="前言",
            allow_missing_headings=True,
            ignore_roundtrip_block=True,
        )
        res = import_first_time(req)
        self.assertTrue(res.success, "导入应成功")

        paths = ProjectPaths(target_proj)
        manifest = ProjectManifest.load(paths.manifest_file)
        content_root = paths.resolve(manifest.relative_content_root())
        pre_title_files = [p for p in content_root.rglob("*.md") if "前言" in str(p)]
        self.assertGreater(len(pre_title_files), 0, "应生成前言章节 Markdown")
        combined_text = "".join(p.read_text(encoding="utf-8") for p in pre_title_files)
        self.assertIn("前言引言段落一", combined_text)
        self.assertIn("前言引言段落二", combined_text)

        out_docx = paths.output_dir / "restored.docx"
        build_with_project(manifest, paths, output_override=out_docx)
        self.assertTrue(out_docx.exists())

        with zipfile.ZipFile(out_docx, "r") as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            count_p1 = doc_xml.count("前言引言段落一")
            self.assertEqual(count_p1, 1, "前言正文在还原文档中应出现且仅出现 1 次，不发生重复")

    # ------------------------------------------------------------------
    # Scenario 5: 不连续章节编号（跳号）与内部小节构建平稳通过
    # ------------------------------------------------------------------
    def test_e2e_5_non_contiguous_chapter_numbers_and_inline_headings_build_cleanly(self) -> None:
        proj_dir = fixtures.two_chapter_project(self.tmp_dir / "proj_gap", document_type="general")
        paths = ProjectPaths(proj_dir)
        manifest = ProjectManifest.load(paths.manifest_file)
        content_dir = paths.resolve(manifest.relative_content_root())

        for item in content_dir.iterdir():
            if item.name.startswith("0") or item.name.startswith("1") or item.name.startswith("第"):
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        (content_dir / "01-前言.md").write_text("# 1 前言\n\n前言正文说明。\n", encoding="utf-8")
        (content_dir / "03-系统架构.md").write_text(
            "# 3 系统架构\n\n总体架构描述。\n\n## 内部微服务小节\n\n微服务说明与接口。\n",
            encoding="utf-8",
        )

        out_docx = paths.output_dir / "gap_out.docx"
        build_res = build_with_project(manifest, paths, output_override=out_docx)
        self.assertTrue(out_docx.exists())

        with zipfile.ZipFile(out_docx, "r") as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("前言正文说明", doc_xml)
            self.assertIn("总体架构描述", doc_xml)
            self.assertIn("内部微服务小节", doc_xml)

    # ------------------------------------------------------------------
    # Scenario 6: CLI 端到端闭环 decompose -> inspect -> edit -> export -D
    # ------------------------------------------------------------------
    def test_e2e_6_cli_decompose_inspect_edit_export_full_chain(self) -> None:
        work_dir = self.tmp_dir / "cli_e2e_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        src_docx = work_dir / "source_cli.docx"

        fixtures.build_docx(src_docx, [
            ("p", "引言概述段落"),
            ("h1", "第一章 系统方案"),
            ("p", "方案正文内容"),
        ])

        custom_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="文档编号"><vt:lpwstr>SRC-E2E-001</vt:lpwstr></property>
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="3" name="版本"><vt:lpwstr>1.0</vt:lpwstr></property>
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="4" name="文档名称"><vt:lpwstr>CLI源文档</vt:lpwstr></property>
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="5" name="项目"><vt:lpwstr>初始项目</vt:lpwstr></property>
</Properties>"""
        _update_docx_xml_parts(src_docx, {
            "docProps/custom.xml": custom_xml.encode("utf-8"),
        })

        proj_name = "cli_proj"
        proj_dir = work_dir / proj_name

        # 1. 运行 CLI decompose
        code_decomp = cli_main([
            "decompose",
            "--docx", str(src_docx),
            "--name", proj_name,
            "--target-dir", str(work_dir),
            "--retain-pre-title",
            "--json",
        ])
        self.assertEqual(code_decomp, 0, "decompose 应当返回 0")
        self.assertTrue(proj_dir.exists(), "decompose 应成功生成项目目录")

        paths = ProjectPaths(proj_dir)
        manifest = ProjectManifest.load(paths.manifest_file)
        self.assertEqual(manifest.documentNo, "SRC-E2E-001")
        self.assertEqual(manifest.documentVersion, "1.0")

        # 2. 运行 CLI export --inspect-properties
        code_inspect = cli_main([
            "export",
            "--project", str(proj_dir),
            "--inspect-properties",
            "--json",
        ])
        self.assertEqual(code_inspect, 0, "export --inspect-properties 应当返回 0")

        # 3. 编辑部分章节和 _revision_record.md
        rev_md = paths.resolve(manifest.relative_content_root()) / "_revision_record.md"
        rev_md.write_text(
            "## 修订记录\n\n"
            "| 版本 | 日期 | 修订人 | 说明 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1.0 | 2026-01-01 | Alice | 初版 |\n"
            "| 5.0 | 2026-10-27 | Bob | 闭环升级 |\n",
            encoding="utf-8",
        )

        # 4. 运行 CLI export 还原为正式 Word
        code_export = cli_main([
            "export",
            "--project", str(proj_dir),
            "--no-refresh",
            "--document-no", "CLI-999",
            "--document-name", "全流程文档",
            "--document-version", "5.0",
            "-D", "项目=CLI闭环项目",
            "--json",
        ])
        self.assertEqual(code_export, 0, "export 应当返回 0")

        expected_output = paths.output_dir / "CLI-999 全流程文档(5.0).docx"
        self.assertTrue(expected_output.exists(), f"预期文件应存在: {expected_output}")

        with zipfile.ZipFile(expected_output, "r") as z:
            out_custom = z.read("docProps/custom.xml").decode("utf-8")
            self.assertIn("CLI-999", out_custom)
            self.assertIn("全流程文档", out_custom)
            self.assertIn("5.0", out_custom)
            self.assertIn("CLI闭环项目", out_custom)


if __name__ == "__main__":
    unittest.main()
