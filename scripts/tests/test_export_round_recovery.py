# -*- coding: utf-8 -*-
"""EX-1～3：原轮局部恢复、捕获身份和部分范围的新轮闭环。"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tests import core_fixtures as fixtures
from doc_tool.application.effective_snapshot import discover_chapters
from doc_tool.application.intake_contract import (
    FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF, FORMAT_SOURCE_ZIP,
    SCOPE_CHAPTERS, SCOPE_CURRENT_CHAPTER, SOURCE_MODE_SAVED,
    STATUS_PENDING_CONVERT, STATUS_PENDING_REFRESH, STATUS_READY,
    STATUS_FAILED,
    ExportRequest, ExportScope, FormatResult, sha256_file,
)
from doc_tool.application.project_export import (
    read_export_index, retry_export_formats, run_project_export, write_export_index,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.ui.export_rounds import round_view_from_report


def _cleanup(path):
    assert Path(path).resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(path)


class _ProjectCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = fixtures.scratch_dir("export-recovery-shared")
        cls.shared_project = fixtures.two_chapter_project(cls.shared / "proj")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls.shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("export-recovery")
        self.project = self.work / "proj"
        shutil.copytree(self.shared_project, self.project)
        self.manifest = ProjectManifest.load(self.project)
        self.content = self.project / self.manifest.relative_content_root()
        self.chapters = [rel for rel, _ in discover_chapters(self.content)]
        self.assertGreaterEqual(len(self.chapters), 2)
        self.selected, self.other = self.chapters[0], self.chapters[-1]
        for rel, marker in ((self.selected, "原轮所选正文标记"), (self.other, "未选章节正文标记")):
            chapter = self.content / rel
            chapter.write_text(chapter.read_text(encoding="utf-8") + "\n" + marker + "\n", encoding="utf-8")

    def tearDown(self):
        _cleanup(self.work)

    def _export(self, scope=None):
        return run_project_export(ExportRequest(
            project_root=str(self.project), formats=[FORMAT_HTML],
            source_mode=SOURCE_MODE_SAVED, scope=scope or ExportScope(),
            destination=str(self.work / "output"),
        ), skip_word_refresh=True)

    def _old_docx(self, report):
        path = fixtures.build_docx(self.work / "output" / "原轮.docx", [("p", "原轮 Word 正文")])
        result = FormatResult(
            format=FORMAT_DOCX, status=STATUS_PENDING_REFRESH,
            path=str(path), sha256=sha256_file(path), backend="kernel",
        )
        return replace(report, docxPath=str(path), results=report.results + [result])

    def _missing_capture(self, report):
        return replace(report, snapshotWorkDir=str(self.work / "missing-capture"))


class OriginalRoundRecoveryTests(_ProjectCase):
    def test_missing_capture_keeps_old_results_without_reading_current_content(self):
        first = self._missing_capture(self._export())
        old_html = first.result_for(FORMAT_HTML)
        old_bytes = Path(old_html.path).read_bytes()
        with patch("doc_tool.application.project_export.capture_snapshot", side_effect=AssertionError("不得捕获当前正文")):
            retried = retry_export_formats(first, [FORMAT_SOURCE_ZIP], buffer_texts={self.selected: "新正文"})
        self.assertEqual(retried.captureId, first.captureId)
        self.assertEqual(retried.roundId, first.roundId)
        self.assertEqual(retried.result_for(FORMAT_HTML).path, old_html.path)
        self.assertEqual(Path(old_html.path).read_bytes(), old_bytes)
        self.assertFalse(retried.result_for(FORMAT_SOURCE_ZIP).usable)
        self.assertIn("新轮", retried.result_for(FORMAT_SOURCE_ZIP).message)

    def test_missing_capture_can_convert_verified_original_word(self):
        first = self._missing_capture(self._old_docx(self._export()))
        converted = self.work / "output" / "补出的.pdf"
        converted.write_bytes(b"%PDF-1.4\n")
        outcome = FormatResult(format=FORMAT_PDF, status=STATUS_READY, path=str(converted), sha256=sha256_file(converted))
        with patch("doc_tool.application.project_export.capture_snapshot", side_effect=AssertionError("不得重新捕获")), patch(
            "doc_tool.application.project_export._run_pdf", return_value=outcome,
        ) as convert:
            retried = retry_export_formats(first, [FORMAT_PDF])
        self.assertEqual(convert.call_args.args[0], first.docxPath)
        self.assertEqual(retried.captureId, first.captureId)
        self.assertEqual(retried.roundId, first.roundId)
        self.assertEqual(retried.result_for(FORMAT_PDF).path, str(converted))
        self.assertEqual(retried.result_for(FORMAT_DOCX), first.result_for(FORMAT_DOCX))

    def test_tampered_word_does_not_enter_original_round_conversion(self):
        first = self._missing_capture(self._old_docx(self._export()))
        Path(first.docxPath).write_bytes(b"Changed outside the original round")
        with patch("doc_tool.application.project_export.capture_snapshot", side_effect=AssertionError("不得重新捕获")), patch(
            "doc_tool.application.project_export._run_pdf",
        ) as convert:
            retried = retry_export_formats(first, [FORMAT_PDF])
        convert.assert_not_called()
        self.assertEqual(retried.result_for(FORMAT_PDF).status, STATUS_PENDING_CONVERT)
        self.assertIn("新轮", retried.result_for(FORMAT_PDF).message)
        self.assertTrue(Path(first.docxPath).is_file())

    def test_missing_identity_is_not_replaced_by_fresh_capture(self):
        first = replace(self._old_docx(self._export()), captureId="")
        with patch("doc_tool.application.project_export.capture_snapshot", side_effect=AssertionError("不得重新捕获")), patch(
            "doc_tool.application.project_export._run_pdf", side_effect=AssertionError("未知来源不得转换"),
        ) as convert:
            retried = retry_export_formats(first, [FORMAT_PDF, FORMAT_SOURCE_ZIP])
        convert.assert_not_called()
        self.assertEqual(retried.captureId, "")
        self.assertFalse(retried.result_for(FORMAT_SOURCE_ZIP).usable)

    def test_explicit_capture_mismatch_cannot_use_original_snapshot(self):
        first = self._export()
        request = ExportRequest(project_root=str(self.project), capture_id="different-capture", destination=first.destination)
        with patch("doc_tool.application.project_export.capture_snapshot", side_effect=AssertionError("不得重新捕获")):
            retried = retry_export_formats(first, [FORMAT_SOURCE_ZIP], request=request)
        self.assertFalse(retried.result_for(FORMAT_SOURCE_ZIP).usable)
        self.assertEqual(retried.captureId, first.captureId)

    def test_available_snapshot_retries_old_text_and_keeps_round_identity(self):
        first = self._export(ExportScope(kind=SCOPE_CHAPTERS, chapters=[self.selected]))
        chapter = self.content / self.selected
        chapter.write_text("当前磁盘已改变，不能用于补原轮", encoding="utf-8")
        retried = retry_export_formats(first, [FORMAT_HTML], buffer_texts={self.selected: "当前缓冲也不能混入"})
        text = Path(retried.result_for(FORMAT_HTML).path).read_text(encoding="utf-8")
        self.assertIn("原轮所选正文标记", text)
        self.assertNotIn("当前磁盘已改变", text)
        self.assertNotIn("当前缓冲也不能混入", text)
        self.assertNotIn("未选章节正文标记", text)
        self.assertEqual(retried.roundId, first.roundId)
        self.assertEqual(retried.captureId, first.captureId)
        self.assertEqual(retried.result_for(FORMAT_HTML).attempts, 2)

    def test_current_project_unavailable_still_allows_snapshot_retry(self):
        first = replace(self._export(), projectRoot=str(self.work / "unavailable-project"))
        retried = retry_export_formats(first, [FORMAT_SOURCE_ZIP])
        self.assertTrue(retried.result_for(FORMAT_SOURCE_ZIP).usable)
        self.assertEqual(retried.captureId, first.captureId)

    def test_missing_capture_keeps_readable_word_when_refresh_cannot_run(self):
        first = self._missing_capture(self._old_docx(self._export()))
        with patch("doc_tool.application.project_export.capture_snapshot", side_effect=AssertionError("不得重新捕获")):
            retried = retry_export_formats(first, [FORMAT_DOCX, FORMAT_SOURCE_ZIP])
        word = retried.result_for(FORMAT_DOCX)
        self.assertTrue(word.usable)
        self.assertEqual(word.path, first.docxPath)
        self.assertEqual(word.status, STATUS_PENDING_REFRESH)
        self.assertFalse(word.formal)
        self.assertFalse(retried.result_for(FORMAT_SOURCE_ZIP).usable)

    def test_rebuild_failure_keeps_word_and_allows_its_pdf_conversion(self):
        first = self._old_docx(self._export())
        failed = FormatResult(format=FORMAT_DOCX, status=STATUS_FAILED, message="内核临时失败")
        pending = FormatResult(format=FORMAT_PDF, status=STATUS_PENDING_CONVERT, message="Word 暂不可用")
        with patch("doc_tool.application.project_export._run_docx", return_value=(failed, "")), patch(
            "doc_tool.application.project_export._run_pdf", return_value=pending,
        ) as convert:
            retried = retry_export_formats(first, [FORMAT_DOCX, FORMAT_PDF])
        self.assertEqual(convert.call_args.args[0], first.docxPath)
        word = retried.result_for(FORMAT_DOCX)
        self.assertEqual(word.path, first.docxPath)
        self.assertTrue(word.usable)
        self.assertEqual(word.status, STATUS_PENDING_REFRESH)
        self.assertEqual(word.attempts, 2)
        self.assertIn("内核临时失败", word.message)


class RoundIdentityTests(unittest.TestCase):
    def test_known_capture_requires_matching_nonempty_report_identity(self):
        from doc_tool.application.project_export import ExportReport
        from doc_tool.ui.main_window import MainWindow

        report = ExportReport(roundId="original-round", captureId="original-capture")
        view = round_view_from_report(report)
        self.assertTrue(MainWindow._round_identity_matches(view, report))
        for altered in (replace(report, captureId=""), replace(report, captureId="other"), replace(report, roundId="other")):
            self.assertFalse(MainWindow._round_identity_matches(view, altered))
        self.assertTrue(MainWindow._round_identity_matches(replace(view, capture_id=""), report))
        self.assertFalse(MainWindow._round_identity_matches(replace(view, capture_id=""), replace(report, captureId="")))

    def test_reading_legacy_index_does_not_fabricate_missing_round_id(self):
        from doc_tool.application.project_export import ExportReport

        work = fixtures.scratch_dir("legacy-round")
        try:
            path = write_export_index(ExportReport(captureId="capture", destination=str(work)))
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["roundId"]
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(read_export_index(path).roundId, "")
        finally:
            _cleanup(work)


class RoundRegenerationTests(_ProjectCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])
        super().setUpClass()

    def setUp(self):
        super().setUp()
        from doc_tool.application.content.unsaved import UnsavedChoice
        from doc_tool.ui.main_window import MainWindow

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            self.window = MainWindow(unsaved_resolver=lambda *_: UnsavedChoice.DISCARD)
        self.window._project_summary = SimpleNamespace(
            project_root=str(self.project), manifest=self.manifest,
            paths=ProjectPaths(self.project), is_writable=True,
        )

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        super().tearDown()

    def _new_round(self, kind):
        scope = ExportScope(kind=kind, chapters=[self.selected] if kind == SCOPE_CHAPTERS else [], current=self.selected if kind == SCOPE_CURRENT_CHAPTER else "")
        first = self._export(scope)
        self.window._refresh_export_results(first)
        view = self.window._task_dock.results_view().current_round()
        old_bytes = (self.content / self.selected).read_bytes()
        self.window._content_current_file = self.other
        self.window._collect_buffer_texts = lambda: {self.selected: "# 修改正文\n新轮未保存正文标记\n"}
        captured = []
        self.window._on_export_task_done = lambda report: captured.append(report)
        self.window._task_dock.results_view()._regenerate_btn.click()
        deadline = time.monotonic() + 30
        while self.window.runner.is_running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertEqual(len(captured), 1)
        second = captured[0]
        text = Path(second.result_for(FORMAT_HTML).path).read_text(encoding="utf-8")
        self.assertIn("新轮未保存正文标记", text)
        self.assertNotIn("未选章节正文标记", text)
        self.assertEqual(second.scope.to_dict(), first.scope.to_dict())
        self.assertNotEqual(second.captureId, first.captureId)
        self.assertNotEqual(second.roundId, first.roundId)
        self.assertEqual((self.content / self.selected).read_bytes(), old_bytes)
        if os.environ.get("PRODUCT_EXPORT_FIX_EVIDENCE") == "1":
            evidence = ROOT / "analysis" / "product-export-fixes-20261003" / "scoped-regeneration" / kind
            evidence.mkdir(parents=True, exist_ok=True)
            for label, report in (("original", first), ("regenerated", second)):
                shutil.copytree(Path(report.result_for(FORMAT_HTML).path).parent, evidence / label, dirs_exist_ok=True)
            (evidence / "result.json").write_text(json.dumps({
                "platform": "Qt offscreen", "entry": "成果页按当前修改重新生成按钮",
                "originalRoundId": first.roundId, "newRoundId": second.roundId,
                "originalCaptureId": first.captureId, "newCaptureId": second.captureId,
                "scope": second.scope.to_dict(), "sourceMode": second.sourceMode,
                "html": "regenerated/index.html",
                "includesUnsavedMarker": "新轮未保存正文标记" in text,
                "excludesUnselectedMarker": "未选章节正文标记" not in text,
                "diskHashBefore": hashlib.sha256(old_bytes).hexdigest(),
                "diskHashAfter": sha256_file(self.content / self.selected),
                "realWordTrial": False,
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_selected_chapter_regeneration_creates_actual_scoped_html(self):
        self._new_round(SCOPE_CHAPTERS)

    def test_current_chapter_regeneration_keeps_original_chapter_after_navigation(self):
        self._new_round(SCOPE_CURRENT_CHAPTER)

    def test_view_retains_scope_for_new_round_when_latest_index_is_overwritten(self):
        first = self._export(ExportScope(kind=SCOPE_CHAPTERS, chapters=[self.selected]))
        view = self.window._record_export_round(first)
        self._export()  # 最新索引属于另一轮，不能用来补原轮。
        self.assertIsNone(self.window._report_for_round(view))
        submissions = []
        self.window._run_export_task = lambda **task: submissions.append(task)
        self.window._on_regenerate_round(view)
        self.assertEqual(submissions[0]["args"][0].scope.to_dict(), first.scope.to_dict())

    def test_removed_chapter_opens_settings_without_starting_full_export(self):
        first = self._export(ExportScope(kind=SCOPE_CHAPTERS, chapters=[self.selected]))
        view = self.window._record_export_round(first)
        (self.content / self.selected).unlink()
        submissions, settings = [], []
        self.window._run_export_task = lambda **task: submissions.append(task)
        self.window._on_export_settings = lambda preset, **kwargs: settings.append((preset, kwargs))
        self.window._on_regenerate_round(view)
        self.assertEqual(submissions, [])
        self.assertEqual(len(settings), 1)
        self.assertEqual(settings[0][0].scope.to_dict(), first.scope.to_dict())
        self.assertIn("实际范围", settings[0][1]["notice"])

    def test_legacy_unknown_scope_opens_visible_settings(self):
        from doc_tool.ui.export_rounds import ExportRoundView, RoundFormatView

        view = ExportRoundView(round_id="legacy", project_root=str(self.project), scope_text="所选 1 章", formats=[RoundFormatView(format=FORMAT_HTML, status=STATUS_READY)])
        submissions, settings = [], []
        self.window._run_export_task = lambda **task: submissions.append(task)
        self.window._on_export_settings = lambda preset, **kwargs: settings.append((preset, kwargs))
        self.window._on_regenerate_round(view)
        self.assertEqual(submissions, [])
        self.assertEqual(len(settings), 1)
        self.assertIn("原范围缺失", settings[0][1]["notice"])

    def test_change_directory_preserves_selected_range(self):
        first = self._export(ExportScope(kind=SCOPE_CHAPTERS, chapters=[self.selected]))
        view = self.window._record_export_round(first)
        submissions = []
        self.window._run_export_task = lambda **task: submissions.append(task)
        chosen = str(self.work / "another-output")
        with patch("doc_tool.ui.main_window.QFileDialog.getExistingDirectory", return_value=chosen):
            self.window._on_change_export_destination(view)
        self.assertEqual(submissions[0]["args"][0].scope.to_dict(), first.scope.to_dict())
        self.assertEqual(submissions[0]["args"][0].destination, chosen)

    def test_retry_missing_capture_id_does_not_submit_backend_task(self):
        first = self._old_docx(self._export())
        view = self.window._record_export_round(first)
        write_export_index(replace(first, captureId=""))
        submissions, messages = [], []
        self.window._run_export_task = lambda **task: submissions.append(task)
        self.window._show_status_message = lambda message: messages.append(message)
        self.window._on_retry_export_round(view)
        self.assertEqual(submissions, [])
        self.assertTrue(messages)
        self.assertTrue(Path(first.docxPath).is_file())

    def test_current_scope_prefill_uses_original_chapter(self):
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog

        dialog = ExportSettingsDialog(chapters=self.chapters, current_chapter=self.other)
        try:
            request = ExportRequest(scope=ExportScope(kind=SCOPE_CURRENT_CHAPTER, current=self.selected))
            dialog.apply_request(request)
            self.assertEqual(dialog.request().scope.current, self.selected)
            self.assertIn(Path(self.selected).name, dialog._scope_combo.currentText())
        finally:
            dialog.deleteLater()

    def test_index_missing_scope_opens_settings_instead_of_assuming_full(self):
        first = self._export(ExportScope(kind=SCOPE_CHAPTERS, chapters=[self.selected]))
        data = first.to_dict()
        del data["scope"]
        Path(first.indexPath).write_text(json.dumps(data), encoding="utf-8")
        loaded = read_export_index(first.indexPath)
        view = round_view_from_report(loaded)
        self.assertIn("范围记录缺失", view.scope_text)
        submissions, settings = [], []
        self.window._run_export_task = lambda **task: submissions.append(task)
        self.window._on_export_settings = lambda preset, **kwargs: settings.append((preset, kwargs))
        self.window._on_regenerate_round(view)
        self.assertEqual(submissions, [])
        self.assertEqual(len(settings), 1)
        self.assertIn("原范围缺失", settings[0][1]["notice"])

    def test_missing_current_chapter_notice_and_cancel_keep_source_and_artifact(self):
        from PySide6.QtWidgets import QDialog
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog

        first = self._export(ExportScope(kind=SCOPE_CURRENT_CHAPTER, current=self.selected))
        view = self.window._record_export_round(first)
        artifact = Path(first.result_for(FORMAT_HTML).path)
        old_bytes = artifact.read_bytes()
        (self.content / self.selected).unlink()
        buffers = {self.selected: "仍在编辑器的未保存内容"}
        self.window._collect_buffer_texts = lambda: dict(buffers)
        submissions, notices = [], []
        self.window._run_export_task = lambda **task: submissions.append(task)

        def cancel(dialog):
            notices.append((dialog._recovery_notice.text(), dialog._chapter_hint.text()))
            return QDialog.DialogCode.Rejected

        with patch.object(ExportSettingsDialog, "exec", cancel):
            self.window._on_regenerate_round(view)
        self.assertEqual(submissions, [])
        self.assertIn("原范围缺失", notices[0][0])
        self.assertIn("当前章已不可用", notices[0][1])
        self.assertEqual(self.window._collect_buffer_texts(), buffers)
        self.assertEqual(artifact.read_bytes(), old_bytes)
        self.assertEqual(read_export_index(first.indexPath).captureId, first.captureId)


if __name__ == "__main__":
    unittest.main(verbosity=2)
