# -*- coding: utf-8 -*-
"""样式映射向导后端测试。

任务 3.1-3.6 / 4.6：非标准 Heading 文档的样式普查、映射校验、映射驱动导入/
构建/校验一致、同一样式单级别、缺 H1/层级跳跃拒绝、持久化回读。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)

from doc_tool.adapters.preflight import (  # noqa: E402
    census_paragraph_styles,
    preflight,
    validate_heading_mapping,
)
from doc_tool.application.import_project import (  # noqa: E402
    ImportRequest,
    import_first_time,
)
from doc_tool.domain.errors import (  # noqa: E402
    HeadingHierarchyError,
    MissingHeading1Error,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _qn(tag):
    return W_NS + tag


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="{ct}">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/settings.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
    '<Override PartName="/word/numbering.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    '</Types>'
).format(ct=CT_NS)

STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="{w}">'
    '<w:style w:type="paragraph" w:styleId="ChapterTitle"><w:name w:val="章标题"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="SectionTitle"><w:name w:val="节标题"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="ItemTitle"><w:name w:val="条目"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '</w:styles>'
).format(w=W_NS).encode("utf-8")

SETTINGS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:settings xmlns:w="{0}"/>'
).format(W_NS).encode("utf-8")

NUMBERING = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:numbering xmlns:w="{0}"/>'
).format(W_NS).encode("utf-8")

RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="{0}"/>'
).format(PR_NS).encode("utf-8")


def _p(style_id, text):
    return '<w:p><w:pPr><w:pStyle w:val="{0}"/></w:pPr><w:r><w:t>{1}</w:t></w:r></w:p>'.format(
        style_id, text
    )


def _body(text):
    return "<w:p><w:r><w:t>{0}</w:t></w:r></w:p>".format(text)


def _custom_body():
    return "".join([
        _p("ChapterTitle", "引言"),
        _body("本章正文。"),
        _p("SectionTitle", "目的"),
        _body("说明目的。"),
        _p("ChapterTitle", "详细设计"),
        _body("第二章正文。"),
        _p("SectionTitle", "接口设计"),
        _p("ItemTitle", "接口契约"),
        _body("接口契约正文。"),
    ])


def write_custom_style_docx(path, body_xml=None):
    """写入使用非标准标题样式的合成 DOCX（章标题/节标题/条目）。"""
    body_xml = body_xml if body_xml is not None else _custom_body()
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{0}" xmlns:r="{1}">'
        '<w:body>{2}<w:sectPr/></w:body></w:document>'
    ).format(W_NS, R_NS, body_xml).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", STYLES)
        zf.writestr("word/settings.xml", SETTINGS)
        zf.writestr("word/numbering.xml", NUMBERING)
        zf.writestr("word/_rels/document.xml.rels", RELS)
    return path


MAPPING = {"ChapterTitle": 1, "SectionTitle": 2, "ItemTitle": 3}


class CensusTests(unittest.TestCase):
    def test_census_lists_custom_heading_styles_with_usage(self):
        with tempfile.TemporaryDirectory(prefix="census-") as work:
            src = os.path.join(work, "src.docx")
            write_custom_style_docx(src)
            from doc_tool.domain.ooxml import read_docx_package

            with read_docx_package(src) as package:
                parts = package.read_xml_parts()
            census = census_paragraph_styles(parts)
            self.assertIn("ChapterTitle", census)
            self.assertEqual(census["ChapterTitle"].name, "章标题")
            self.assertEqual(census["ChapterTitle"].usage_count, 2)
            self.assertTrue(census["ChapterTitle"].suspected_heading)
            self.assertEqual(census["SectionTitle"].usage_count, 2)
            self.assertEqual(census["ItemTitle"].usage_count, 1)
            self.assertFalse(census["Normal"].suspected_heading)

    def test_standard_heading_not_marked_suspected(self):
        from doc_tool.adapters.preflight import _looks_like_heading

        self.assertFalse(_looks_like_heading("heading 1"))
        self.assertFalse(_looks_like_heading("标题 2"))
        self.assertTrue(_looks_like_heading("章标题"))
        self.assertTrue(_looks_like_heading("节标题"))
        self.assertFalse(_looks_like_heading("Normal"))
        self.assertFalse(_looks_like_heading("正文"))


class PreflightMappingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="map-preflight-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_preflight_without_mapping_rejects_missing_h1(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        with self.assertRaises(MissingHeading1Error):
            preflight(src)

    def test_preflight_lenient_returns_preview_with_census(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        preview = preflight(src, allow_missing_headings=True)
        self.assertFalse(preview.has_heading1)
        self.assertIn("ChapterTitle", preview.style_census)
        # 保真扫描仍随预览返回
        self.assertIsNotNone(preview.fidelity)

    def test_preflight_with_mapping_succeeds(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        preview = preflight(src, heading_style_map=MAPPING)
        self.assertTrue(preview.has_heading1)
        self.assertEqual(preview.heading_level_counts.get(1), 2)
        self.assertEqual(preview.heading_level_counts.get(2), 2)
        self.assertEqual(preview.heading_level_counts.get(3), 1)

    def test_validate_mapping_missing_h1_rejected(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        error = validate_heading_mapping(src, {"SectionTitle": 2, "ItemTitle": 3})
        self.assertIn("级别 1", error)

    def test_validate_mapping_hierarchy_jump_rejected(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        # 缺级别 2：H1 直接跳到 H3
        error = validate_heading_mapping(src, {"ChapterTitle": 1, "ItemTitle": 3})
        self.assertIn("跳跃", error)

    def test_validate_mapping_unused_h1_rejected(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        error = validate_heading_mapping(src, {"Normal": 1, "SectionTitle": 2})
        self.assertNotEqual(error, "")

    def test_validate_mapping_valid_passes(self):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        self.assertEqual(validate_heading_mapping(src, MAPPING), "")


class MappingDrivenImportTests(unittest.TestCase):
    """任务 3.4-3.6：映射驱动导入、清单写入、构建/校验一致、持久化回读。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="map-import-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _import(self, mapping=None):
        src = write_custom_style_docx(os.path.join(self._tmp, "src.docx"))
        target = os.path.join(self._tmp, "映射项目")
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type="general",
            document_no="",
            document_name="自定义样式文档",
            document_version="",
            heading_style_map=mapping,
        )
        return src, target, import_first_time(request)

    def test_import_without_mapping_fails(self):
        src, target, result = self._import(mapping=None)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, MissingHeading1Error.code)
        self.assertFalse(os.path.exists(target))

    def test_import_with_mapping_succeeds_and_writes_manifest(self):
        src, target, result = self._import(mapping=MAPPING)
        self.assertTrue(result.success, "带映射的导入应成功：{0}".format(
            [(e.stage, e.status, e.detail) for e in result.events if e.status == "failed"]))
        manifest = yaml.safe_load(Path(target, "project.yml").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["headingStyles"],
            {"1": "ChapterTitle", "2": "SectionTitle", "3": "ItemTitle"},
        )

    def test_import_with_invalid_mapping_fails(self):
        src, target, result = self._import(mapping={"SectionTitle": 2})
        self.assertFalse(result.success)
        self.assertFalse(os.path.exists(target))

    def test_build_and_validate_use_mapping(self):
        src, target, result = self._import(mapping=MAPPING)
        self.assertTrue(result.success)
        from doc_tool.adapters.kernel import build_with_project, validate_with_project
        from doc_tool.domain.manifest import ProjectManifest

        loaded = ProjectManifest.load(target)
        self.assertEqual(loaded.headingStyles, {1: "ChapterTitle", 2: "SectionTitle", 3: "ItemTitle"})
        paths = loaded.resolve_paths(target)
        output = build_with_project(loaded, paths)
        self.assertTrue(Path(output).exists())
        self.assertTrue(
            validate_with_project(loaded, paths),
            "按映射构建的文档应通过校验",
        )

    def test_mapping_persistence_readback(self):
        """映射写入 project.yml 后可回读并继续驱动构建（持久化回读）。"""
        src, target, result = self._import(mapping=MAPPING)
        self.assertTrue(result.success)
        from doc_tool.domain.manifest import ProjectManifest

        # 重新加载项目（模拟后续打开）
        loaded = ProjectManifest.load(target)
        self.assertEqual(loaded.headingStyles, {1: "ChapterTitle", 2: "SectionTitle", 3: "ItemTitle"})
        # 修改映射（用户可修改持久化映射）后仍可构建
        loaded.headingStyles = {1: "ChapterTitle", 2: "SectionTitle"}
        from doc_tool.adapters.kernel import config_from_project

        paths = loaded.resolve_paths(target)
        config = config_from_project(loaded, paths)
        self.assertEqual(config["headingStyles"], {1: "ChapterTitle", 2: "SectionTitle"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
