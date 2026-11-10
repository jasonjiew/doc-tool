# -*- coding: utf-8 -*-
"""导出“待刷新”原因回归：同一项目在不同机器/设置下必须能说明为什么没刷新。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts"), str(REPO_ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


class PendingReasonHelperTests(unittest.TestCase):
    def test_skip_notes_cover_all_reasons(self):
        from doc_tool.application.project_export import _refresh_skip_note

        self.assertIn(
            "导出设置未启用",
            _refresh_skip_note(
                requested=False, skipped_by_caller=False, available=False
            ),
        )
        self.assertIn(
            "按参数跳过",
            _refresh_skip_note(
                requested=False, skipped_by_caller=True, available=False
            ),
        )
        self.assertIn(
            "WPS 接管",
            _refresh_skip_note(
                requested=True,
                skipped_by_caller=False,
                available=False,
                probe_reason="WPS 接管了 Word.Application（注册表 CLSID 不是 Microsoft Word）",
            ),
        )
        self.assertEqual(
            _refresh_skip_note(
                requested=True, skipped_by_caller=False, available=True
            ),
            "",
        )

    def test_readiness_reports_wps_hijack(self):
        from doc_tool.application import project_export

        with patch(
            "doc_tool.application.word_check.is_wps_replacing_word",
            return_value=True,
        ):
            available, reason = project_export._word_refresh_readiness()
        self.assertFalse(available)
        self.assertIn("WPS", reason)

    def test_readiness_reports_word_unavailable_reasons(self):
        from doc_tool.application import project_export

        report = SimpleNamespace(available=False, reasons=["未安装 pywin32（COM 支持）。"])
        with patch(
            "doc_tool.application.word_check.is_wps_replacing_word",
            return_value=False,
        ), patch(
            "doc_tool.application.word_check.check_word_available",
            return_value=report,
        ):
            available, reason = project_export._word_refresh_readiness()
        self.assertFalse(available)
        self.assertIn("pywin32", reason)

    def test_readiness_available_has_no_reason(self):
        from doc_tool.application import project_export

        report = SimpleNamespace(available=True, reasons=[])
        with patch(
            "doc_tool.application.word_check.is_wps_replacing_word",
            return_value=False,
        ), patch(
            "doc_tool.application.word_check.check_word_available",
            return_value=report,
        ):
            self.assertEqual(project_export._word_refresh_readiness(), (True, ""))


class RunDocxPendingReasonTests(unittest.TestCase):
    """用最小快照验证 _run_docx 会把原因写进结果 message。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="export-pending-reason-"))
        self.work = self.root / "project"
        self.work.mkdir()
        (self.work / "output").mkdir()
        self.destination = self.root / "out"
        self.destination.mkdir()
        self.fake_output = self.work / "output" / "fake.docx"
        self.fake_output.write_bytes(b"PK\x03\x04fake-docx")
        from test_project_build import _make_manifest

        self.manifest = _make_manifest(str(self.work))
        self.snapshot = SimpleNamespace(workDir=str(self.work), unsavedChapters=[])
        self.request = SimpleNamespace(refresh=True, strict=False, document_version=None)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, *, refresh=True, skip_word_refresh=False, word_available=False, result=None):
        from doc_tool.application import project_export
        from doc_tool.application.intake_contract import FORMAT_DOCX, STATUS_PENDING_REFRESH

        if result is None:
            result = SimpleNamespace(
                success=True,
                output_path=str(self.fake_output),
                pending_output_path=None,
                events=[],
                error_code="",
                wordRefresh={},
                word_skip_reason="",
                last_stage=None,
            )
        with patch(
            "doc_tool.domain.manifest.ProjectManifest.load",
            return_value=self.manifest,
        ), patch(
            "doc_tool.application.pipeline.run_pipeline",
            return_value=result,
        ), patch.object(
            project_export, "is_formal_docx", return_value=False
        ), patch.object(
            project_export, "_apply_layout", return_value=None
        ):
            outcome, _path = project_export._run_docx(
                self.snapshot,
                self.request,
                self.destination,
                "stem",
                refresh=refresh,
                skip_word_refresh=skip_word_refresh,
                cancel_token=None,
                progress=None,
                word_available=word_available,
            )
        self.assertEqual(outcome.format, FORMAT_DOCX)
        self.assertEqual(outcome.status, STATUS_PENDING_REFRESH)
        return outcome

    def test_word_unavailable_reason_is_visible(self):
        outcome = self._run(word_available=False)
        self.assertIn("本机 Word 不可用", outcome.message)
        self.assertIn("本机 Word 不可用", "\n".join(outcome.warnings))

    def test_setting_disabled_reason_is_visible(self):
        outcome = self._run(refresh=False, skip_word_refresh=False)
        self.assertIn("导出设置未启用", outcome.message)

    def test_skip_parameter_reason_is_visible(self):
        outcome = self._run(refresh=False, skip_word_refresh=True)
        self.assertIn("按参数跳过", outcome.message)

    def test_refresh_failure_reason_includes_error_code(self):
        failed = SimpleNamespace(
            stage="word_refresh",
            status="failed",
            error_code="E3004",
            detail="目标文档存在 Word 忙锁",
            metrics={},
        )
        result = SimpleNamespace(
            success=False,
            output_path=str(self.fake_output),
            pending_output_path=str(self.fake_output),
            events=[failed],
            error_code="E3004",
            wordRefresh={},
            word_skip_reason="",
            last_stage=failed,
        )
        outcome = self._run(result=result, word_available=True)
        self.assertIn("Word 刷新失败", outcome.message)
        self.assertIn("E3004", outcome.message)
        self.assertIn("忙锁", outcome.message)

    def test_patched_word_probe_wrapper_is_honored(self):
        """测试/调用方打桩 _word_available 时不得绕过（否则会拉起真实 Word）。"""
        from doc_tool.application import project_export

        with patch.object(project_export, "_word_available", return_value=False):
            outcome = self._run(word_available=None)
        self.assertIn("本机 Word 不可用", outcome.message)

    def test_wps_pipeline_skip_reason_is_visible(self):
        result = SimpleNamespace(
            success=True,
            output_path=str(self.fake_output),
            pending_output_path=None,
            events=[],
            error_code="",
            wordRefresh={},
            word_skip_reason="wps",
            last_stage=None,
        )
        outcome = self._run(result=result, word_available=True)
        self.assertIn("WPS", outcome.message)


if __name__ == "__main__":
    unittest.main()
