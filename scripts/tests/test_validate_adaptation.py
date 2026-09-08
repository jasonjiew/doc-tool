# -*- coding: utf-8 -*-
"""测试独立校验自适应刷新状态功能。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from doc_tool.adapters.kernel import infer_require_refreshed, validate_with_project
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.output_state import OutputState, write_state


class TestValidateAdaptation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="doc-test-validate-adapt-")
        self.work = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_dummy_docx(self, path: Path, with_update_fields: bool) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        settings_content = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            + (b'<w:updateFields w:val="true"/>' if with_update_fields else b'')
            + b'</w:settings>'
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("word/settings.xml", settings_content)
            zf.writestr(
                "word/document.xml",
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
            )
        return path

    def test_infer_nonexistent_file(self):
        self.assertFalse(infer_require_refreshed(self.work / "not-exist.docx"))

    def test_infer_with_state_formal(self):
        docx_path = self._create_dummy_docx(self.work / "formal.docx", with_update_fields=False)
        write_state(str(docx_path), formal=True, diagnostic=False)
        self.assertTrue(infer_require_refreshed(docx_path))

    def test_infer_with_state_diagnostic(self):
        docx_path = self._create_dummy_docx(self.work / "diag.docx", with_update_fields=True)
        write_state(str(docx_path), formal=False, diagnostic=True)
        self.assertFalse(infer_require_refreshed(docx_path))

    def test_infer_fallback_without_update_fields(self):
        # 无 state 文件，但 DOCX 内无 updateFields（Word 已消费）
        docx_path = self._create_dummy_docx(self.work / "refreshed_no_state.docx", with_update_fields=False)
        self.assertTrue(infer_require_refreshed(docx_path))

    def test_infer_fallback_with_update_fields(self):
        # 无 state 文件，DOCX 内含 updateFields（未消费草稿）
        docx_path = self._create_dummy_docx(self.work / "draft_no_state.docx", with_update_fields=True)
        self.assertFalse(infer_require_refreshed(docx_path))

    @patch("validate_docx.validate")
    def test_validate_with_project_auto_detection_formal(self, mock_validate):
        mock_validate.return_value = True
        manifest = ProjectManifest(
            schemaVersion=1,
            documentType="requirement",
            documentNo="GX-TEST-001",
            documentName="测试项目",
            documentVersion="1.0",
            sourceSha256="0" * 64,
        )
        paths = manifest.resolve_paths(self.work)
        output_file = paths.output_dir / "GX-TEST-001 测试项目(1.0).docx"
        self._create_dummy_docx(output_file, with_update_fields=False)
        write_state(str(output_file), formal=True, diagnostic=False)

        # 显式不传 require_refreshed -> 自动推断为 True
        passed = validate_with_project(manifest, paths)
        self.assertTrue(passed)
        self.assertTrue(mock_validate.called)
        call_kwargs = mock_validate.call_args[1]
        self.assertTrue(call_kwargs["require_refreshed"])

    @patch("validate_docx.validate")
    def test_validate_with_project_auto_detection_draft(self, mock_validate):
        mock_validate.return_value = True
        manifest = ProjectManifest(
            schemaVersion=1,
            documentType="requirement",
            documentNo="GX-TEST-001",
            documentName="测试项目",
            documentVersion="1.0",
            sourceSha256="0" * 64,
        )
        paths = manifest.resolve_paths(self.work)
        output_file = paths.output_dir / "GX-TEST-001 测试项目(1.0).docx"
        self._create_dummy_docx(output_file, with_update_fields=True)
        write_state(str(output_file), formal=False, diagnostic=True)

        # 显式不传 require_refreshed -> 自动推断为 False
        passed = validate_with_project(manifest, paths)
        self.assertTrue(passed)
        self.assertTrue(mock_validate.called)
        call_kwargs = mock_validate.call_args[1]
        self.assertFalse(call_kwargs["require_refreshed"])

    @patch("validate_docx.validate")
    def test_validate_with_project_explicit_override(self, mock_validate):
        mock_validate.return_value = True
        manifest = ProjectManifest(
            schemaVersion=1,
            documentType="requirement",
            documentNo="GX-TEST-001",
            documentName="测试项目",
            documentVersion="1.0",
            sourceSha256="0" * 64,
        )
        paths = manifest.resolve_paths(self.work)
        output_file = paths.output_dir / "GX-TEST-001 测试项目(1.0).docx"
        self._create_dummy_docx(output_file, with_update_fields=False)
        write_state(str(output_file), formal=True, diagnostic=False)

        # 虽然产物是 formal=True，但显式指定 require_refreshed=False 时尊重入参
        passed = validate_with_project(manifest, paths, require_refreshed=False)
        self.assertTrue(passed)
        call_kwargs = mock_validate.call_args[1]
        self.assertFalse(call_kwargs["require_refreshed"])


if __name__ == "__main__":
    unittest.main()
