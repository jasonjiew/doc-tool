# -*- coding: utf-8 -*-
"""Export names and one-round Word document properties."""
from __future__ import annotations

import os
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "tests")]

from lxml import etree
from scripts.tests import core_fixtures as fixtures
from doc_tool.application.export.document_properties import inspect_document_properties
from doc_tool.application.intake_contract import ExportRequest, ExportScope, FORMAT_DOCX, SOURCE_MODE_CURRENT_BUFFER, SOURCE_MODE_SAVED
from doc_tool.application.project_export import run_project_export
from doc_tool.domain.manifest import ProjectManifest

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CP = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _add_template_fields(path: Path) -> None:
    from docx import Document
    from scripts.build_docx import update_custom_properties

    doc = Document(str(path))
    paragraph = doc.sections[0].header.paragraphs[0]
    field = etree.SubElement(paragraph._p, W + "fldSimple", {W + "instr": ' DOCPROPERTY "项目" '})
    etree.SubElement(etree.SubElement(field, W + "r"), W + "t").text = "原项目"
    doc.save(str(path))
    with zipfile.ZipFile(path) as archive:
        items = {name: archive.read(name) for name in archive.namelist()}
    update_custom_properties(items, {"documentNo": "TEST-001", "documentName": "原文件", "documentVersion": "1.0"})
    custom = etree.fromstring(items["docProps/custom.xml"])
    prop = etree.SubElement(custom, CP + "property", {"fmtid": "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}", "pid": "100", "name": "项目"})
    etree.SubElement(prop, VT + "lpwstr").text = "原项目"
    prop = etree.SubElement(custom, CP + "property", {"fmtid": "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}", "pid": "101", "name": "级别"})
    etree.SubElement(prop, VT + "i4").text = "2"
    items["docProps/custom.xml"] = etree.tostring(custom, xml_declaration=True, encoding="UTF-8", standalone=True)
    core = etree.fromstring(items["docProps/core.xml"])
    category = core.find("{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}category")
    if category is not None:
        core.remove(category)
    subject = core.find(DC + "subject")
    if subject is None:
        subject = etree.SubElement(core, DC + "subject")
    subject.text = "原主题"
    items["docProps/core.xml"] = etree.tostring(core, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in items.items():
            archive.writestr(name, data)


class ExportDocumentFieldsTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("export-document-fields")
        self.addCleanup(fixtures.cleanup, self.work)
        self.project = fixtures.two_chapter_project(self.work / "project")
        self.manifest = ProjectManifest.load(self.project)
        self.manifest.documentNo = "DOC-REQ-2026-001"
        self.manifest.documentName = "通用软件需求规格说明书"
        self.manifest.documentVersion = "1.0"
        self.manifest.save(self.project)
        self.content = self.project / self.manifest.relative_content_root()
        self.revision = self.content / "_revision_record.md"
        self.revision.write_text("| 版本 | 内容 |\n| --- | --- |\n| 3.8 | 修订 |\n", encoding="utf-8")
        self.template = self.project / self.manifest.relative_template_docx()
        _add_template_fields(self.template)

    def export(self, **kwargs):
        request = ExportRequest(project_root=str(self.project), formats=[FORMAT_DOCX],
                                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "out"), **kwargs)
        return run_project_export(request, skip_word_refresh=True)

    def test_default_filename_uses_captured_revision(self):
        report = self.export()
        self.assertTrue(report.result_for(FORMAT_DOCX).usable, report.summary_lines())
        self.assertEqual(Path(report.docxPath).name, "DOC-REQ-2026-001 通用软件需求规格说明书(3.8).docx")
        self.assertEqual(report.documentVersion, "3.8")
        self.assertEqual((Path(report.snapshotWorkDir) / "content" / "_revision_record.md").read_text(encoding="utf-8"), self.revision.read_text(encoding="utf-8"))

    def test_existing_positional_request_arguments_remain_compatible(self):
        request = ExportRequest("project", [FORMAT_DOCX], ExportScope(), SOURCE_MODE_SAVED, "out", "name", "template")
        self.assertEqual(request.layout_profile, "template")
        self.assertIsNone(request.document_version)

    def test_unsaved_revision_buffer_is_captured(self):
        request = ExportRequest(project_root=str(self.project), formats=[FORMAT_DOCX], source_mode=SOURCE_MODE_CURRENT_BUFFER,
                                destination=str(self.work / "buffer"))
        buffer = "| 版本 | 内容 |\n| --- | --- |\n| 3.9 | 编辑中 |\n"
        report = run_project_export(request, buffer_texts={"_revision_record.md": buffer}, skip_word_refresh=True)
        self.assertTrue(report.result_for(FORMAT_DOCX).usable, report.summary_lines())
        self.assertIn("(3.9).docx", Path(report.docxPath).name)
        self.assertIn("3.8", self.revision.read_text(encoding="utf-8"))

    def test_custom_filename_with_docx_suffix_is_not_duplicated(self):
        report = self.export(output_name="自定义.docx")
        self.assertTrue(report.result_for(FORMAT_DOCX).usable, report.summary_lines())
        self.assertEqual(Path(report.docxPath).name, "自定义.docx")

    def test_snapshot_detects_revision_added_after_capture(self):
        from doc_tool.application.effective_snapshot import capture_snapshot, mark_source_updated

        self.revision.unlink()
        snapshot = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED)
        self.assertFalse(mark_source_updated(snapshot))
        self.revision.write_text("| 版本 | 内容 |\n| --- | --- |\n| 4.0 | 新增 |\n", encoding="utf-8")
        self.assertTrue(mark_source_updated(snapshot))

    def test_custom_template_path_is_used_for_snapshot_and_properties(self):
        from doc_tool.application.export.document_properties import apply_document_properties

        custom_template = self.project / "custom-template" / "template.docx"
        custom_template.parent.mkdir()
        shutil.copy2(self.template, custom_template)
        apply_document_properties(custom_template, {"custom:项目": "自定义底模"})
        self.manifest.paths["templateDocx"] = "custom-template/template.docx"
        self.manifest.save(self.project)
        report = self.export()
        self.assertTrue(report.result_for(FORMAT_DOCX).usable, report.summary_lines())
        self.assertEqual(inspect_document_properties(report.docxPath)["custom:项目"]["value"], "自定义底模")

    def test_edit_fields_are_one_round_and_visible_in_word(self):
        original_template = self.template.read_bytes()
        original_manifest = (self.project / "project.yml").read_bytes()
        report = self.export(document_no="ABC-001", document_name="本次文件", document_version="4.2",
                             document_properties={"custom:项目": "本次项目", "custom:级别": "3", "core:subject": "本次主题", "core:category": "本次分类"})
        result = report.result_for(FORMAT_DOCX)
        self.assertTrue(result.usable, report.summary_lines())
        self.assertEqual(Path(result.path).name, "ABC-001 本次文件(4.2).docx")
        self.assertEqual(report.documentVersion, "4.2")
        props = inspect_document_properties(result.path)
        self.assertEqual(props["custom:项目"]["value"], "本次项目")
        self.assertEqual(props["custom:级别"]["value"], "3")
        self.assertEqual(props["core:subject"]["value"], "本次主题")
        self.assertEqual(props["core:category"]["value"], "本次分类")
        with zipfile.ZipFile(result.path) as archive:
            headers = [archive.read(n).decode("utf-8") for n in archive.namelist() if n.startswith("word/header") and n.endswith(".xml")]
        self.assertTrue(any("本次项目" in header for header in headers))
        self.assertEqual(self.template.read_bytes(), original_template)
        self.assertEqual((self.project / "project.yml").read_bytes(), original_manifest)
        self.assertIn("3.8", self.revision.read_text(encoding="utf-8"))
        self.assertIn("3.8", (Path(report.snapshotWorkDir) / "content" / "_revision_record.md").read_text(encoding="utf-8"))

    def test_invalid_typed_property_is_rejected(self):
        with self.assertRaises(ValueError):
            self.export(document_properties={"custom:级别": "not-an-integer"})

    def test_invalid_xml_character_in_text_property_is_rejected(self):
        with self.assertRaises(ValueError):
            self.export(document_properties={"custom:项目": "无效\x00文本"})

    def test_output_stem_graceful_fallback_on_manifest_error(self):
        from doc_tool.application.project_export import _output_stem
        from doc_tool.application.intake_contract import ExportRequest

        broken_manifest = ProjectManifest(
            documentType="general", documentNo="", documentName="降级文档",
            documentVersion="", sourceSha256=""
        )
        # 强制制造异常场景（例如非通用文档缺少编号）
        broken_manifest.documentType = "requirement"
        broken_manifest.documentNo = ""
        stem = _output_stem(broken_manifest, ExportRequest(), None)
        self.assertEqual(stem, "降级文档")

    def test_export_request_normalizes_none_properties(self):
        req = ExportRequest(document_properties=None)
        self.assertEqual(req.document_properties, {})

    def test_prepare_snapshot_document_handles_missing_template(self):
        from doc_tool.application.project_export import _prepare_snapshot_document
        from doc_tool.application.effective_snapshot import EffectiveSnapshot
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            m = ProjectManifest(documentType="general", documentNo="G-1", documentName="测试", documentVersion="1.0", sourceSha256="")
            m.save(root)
            snap = EffectiveSnapshot(workDir=str(root))
            req = ExportRequest(document_properties={"custom:项目": "值"})
            # 没有 template.docx 时不应崩溃抛出 FileNotFoundError
            updated_m = _prepare_snapshot_document(snap, req)
            self.assertEqual(updated_m.documentNo, "G-1")

    def test_retry_uses_original_fields_after_source_changes(self):
        first = self.export(document_no="OLD-001", document_name="原轮", document_version="4.2",
                            document_properties={"custom:项目": "原轮项目"})
        self.assertTrue(first.result_for(FORMAT_DOCX).usable, first.summary_lines())
        self.revision.write_text("| 版本 | 内容 |\n| --- | --- |\n| 9.9 | 新轮 |\n", encoding="utf-8")
        changed = ExportRequest(project_root=str(self.project), formats=[FORMAT_DOCX], destination=str(self.work / "retry"),
                                document_no="NEW-001", document_name="新轮", document_version="9.9",
                                document_properties={"custom:项目": "新轮项目"})
        retry = run_project_export(changed, prior=first, only_formats=[FORMAT_DOCX], skip_word_refresh=True)
        result = retry.result_for(FORMAT_DOCX)
        self.assertTrue(result.usable, retry.summary_lines())
        self.assertEqual(Path(result.path).name, "OLD-001 原轮(4.2).docx")
        self.assertEqual(inspect_document_properties(result.path)["custom:项目"]["value"], "原轮项目")


if __name__ == "__main__":
    unittest.main(verbosity=2)
