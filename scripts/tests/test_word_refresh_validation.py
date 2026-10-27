# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)

from doc_tool.application.pipeline import run_pipeline
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from validate_docx import Check, Report, _header_footer_signatures


class TestWordRefreshValidation(unittest.TestCase):
    def test_report_warn_only(self):
        report = Report(doc_type="general", output="out.docx")
        report.row_check(name="严格必须通过项", ok=True)
        report.row_check(name="非致命差异警告项", ok=False, detail="轻微样式重排", warn_only=True)
        self.assertTrue(report.passed)
        rendered = report.render()
        self.assertIn("[PASS] 严格必须通过项", rendered)
        self.assertIn("[WARN] 非致命差异警告项", rendered)
        self.assertIn("结论: **通过**", rendered)

        # 真正硬失败应导致 passed 为 False
        report.row_check(name="致命文件损坏项", ok=False, detail="ZIP损坏", warn_only=False)
        self.assertFalse(report.passed)
        rendered2 = report.render()
        self.assertIn("[FAIL] 致命文件损坏项", rendered2)
        self.assertIn("结论: **失败**", rendered2)

    def test_stage_validate_post_failure_preserves_docx(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = ProjectManifest(
                schemaVersion=2,
                documentType="general",
                documentName="测试测试",
                documentNo="TST-001",
                documentVersion="1.0",
                chapters=[],
                sourceSha256="fake_sha256",
            )
            paths = ProjectPaths(tmp_path)
            paths.output_dir.mkdir(parents=True, exist_ok=True)
            paths.logs_dir.mkdir(parents=True, exist_ok=True)
            manifest.save(tmp_path)

            # 模拟在 STAGE_VALIDATE_POST 中校验失败
            with patch("doc_tool.adapters.kernel.build_with_project") as mock_build, \
                 patch("doc_tool.adapters.kernel.validate_with_project") as mock_val, \
                 patch("doc_tool.adapters.kernel.refresh_with_project") as mock_refresh:

                def fake_build(man, pth, **kwargs):
                    out_path = Path(kwargs["output_override"])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("fake docx content", encoding="utf-8")
                    return str(out_path)

                def fake_refresh(man, pth, **kwargs):
                    out_path = Path(kwargs["output_override"])
                    out_path.write_text("refreshed fake docx", encoding="utf-8")
                    return True, None

                mock_build.side_effect = fake_build
                mock_refresh.side_effect = fake_refresh
                # 刷新前通过，刷新后失败
                mock_val.side_effect = [True, False]

                result = run_pipeline(manifest, paths, skip_word_refresh=False, word_available=True)
                self.assertFalse(result.success)
                # 产物绝不能被删除，应该已保留到 待刷新 目录下
                self.assertTrue(result.pending_output_path)
                preserved_file = Path(result.pending_output_path)
                self.assertTrue(preserved_file.is_file())
                self.assertEqual(preserved_file.read_text(encoding="utf-8"), "refreshed fake docx")


if __name__ == "__main__":
    unittest.main()
