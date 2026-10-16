# -*- coding: utf-8 -*-
"""Current-content checks and cross-panel edits must not mislead or lose drafts."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core_fixtures as fixtures
from doc_tool.application.assist.adoption import AdoptionOutcome, AdoptionTransaction
from doc_tool.application.assist.models import APPLY_REPLACE, KIND_TERM
from doc_tool.application.assist.provider import ProviderConfig
from doc_tool.application.assist.service import AuthoringAssistant
from doc_tool.application.assist.suggestions import Suggestion
from doc_tool.application.intake_contract import ExportRequest
from doc_tool.domain.manifest import ProjectManifest


class SafetyFixture(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("intelligence-safety")
        self.addCleanup(fixtures.cleanup, self.work)
        self.project = fixtures.two_chapter_project(self.work / "project")
        self.manifest = ProjectManifest.load(self.project)
        self.paths = self.manifest.resolve_paths(self.project)
        self.rel = "第1章 引言/1.1 目的.md"

    def assistant(self, text):
        assistant = AuthoringAssistant.from_project(
            self.project, cache_enabled=False, provider_config=ProviderConfig(),
        )
        assistant.set_buffers({self.rel: text})
        return assistant

    def suggestion(self):
        return Suggestion(
            suggestion_id="wording-one", kind=KIND_TERM, title="术语",
            target_rel_path=self.rel, start_line=2, before="APIv1", after="APIv2",
            apply_mode=APPLY_REPLACE,
        )


class DailyCheckTests(SafetyFixture):
    def test_f5_uses_live_content_checker_not_previous_word(self):
        from doc_tool.ui.main_window import MainWindow
        live = Mock(return_value=True)
        window = SimpleNamespace(
            _project_summary=SimpleNamespace(manifest=self.manifest, paths=self.paths),
            runner=SimpleNamespace(is_running=False),
            _content_workspace=SimpleNamespace(run_lint=live),
            _run_source_content_check=Mock(), _start_task=Mock(),
            _show_status_message=Mock(), _append_log=Mock(),
            _refresh_mainflow_advice=Mock(),
        )
        MainWindow._on_validate(window)
        live.assert_called_once()
        window._start_task.assert_not_called()
        window._run_source_content_check.assert_not_called()

    def test_quality_regressions_are_in_default_runner(self):
        path = Path(__file__).with_name("run_tests.py")
        spec = importlib.util.spec_from_file_location("intelligence_runner_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn("test_mainflow_quality.py", module.DEFAULT_TESTS)
        self.assertEqual(len(module.DEFAULT_TESTS), len(set(module.DEFAULT_TESTS)))


class RegistrationTests(SafetyFixture):
    def test_final_registration_failure_keeps_file_but_never_formal(self):
        from doc_tool.application import project_export as exporter
        from doc_tool.application.effective_snapshot import capture_snapshot
        snapshot = capture_snapshot(self.project, work_root=self.work / "capture")
        source = self.paths.template_docx
        pipeline = SimpleNamespace(
            success=True, output_path=str(source), pending_output_path="",
            error_code="", events=[], last_stage=None,
        )
        destination = self.work / "out"
        destination.mkdir()
        request = ExportRequest(project_root=str(self.project), formats=["docx"])
        with patch("doc_tool.application.pipeline.run_pipeline", return_value=pipeline), patch.object(
            exporter, "is_formal_docx", return_value=True
        ), patch.object(exporter, "_apply_layout", return_value=None), patch(
            "doc_tool.domain.output_state.write_state", side_effect=OSError("registration unavailable")
        ):
            result, path = exporter._run_docx(
                snapshot, request, destination, "result", refresh=True,
                cancel_token=None, progress=None, word_available=True,
            )
        self.assertTrue(Path(path).is_file())
        self.assertTrue(result.sha256)
        self.assertTrue(result.usable)
        self.assertFalse(result.formal, "state-write failure cannot be formal success")
        self.assertEqual(result.status, "pending-registration")
        self.assertIn("登记", result.message)


class LiveAdoptionTests(SafetyFixture):
    def test_adoption_uses_latest_buffer_and_keeps_later_prose(self):
        original = "# 目的\nAPIv1\n"
        latest = original + "作者刚刚追加的未保存段落\n"
        assistant = self.assistant(original)
        assistant.buffer_provider = lambda: {self.rel: latest}
        outcome = assistant.adopt(["wording-one"], suggestions=[self.suggestion()], refresh=False)
        self.assertIn("APIv2", outcome.buffer_updates[self.rel])
        self.assertIn("作者刚刚追加", outcome.buffer_updates[self.rel])

    def test_assistant_undo_never_erases_edits_after_adoption(self):
        original = "# 目的\nAPIv1\n"
        assistant = self.assistant(original)
        live = {self.rel: original}
        assistant.buffer_provider = lambda: dict(live)
        outcome = assistant.adopt(["wording-one"], suggestions=[self.suggestion()], refresh=False)
        live[self.rel] = outcome.buffer_updates[self.rel] + "采纳后新的作者内容\n"
        done, restored, detail = assistant.undo(outcome)
        self.assertFalse(done)
        self.assertFalse(restored)
        self.assertIn("变化", detail)
        self.assertIn("采纳后新的作者内容", live[self.rel])
        self.assertFalse(outcome.transaction.undone)

    def test_panel_emits_only_changed_chapters(self):
        from doc_tool.ui.assist_panel import AssistPanel
        outcome = AdoptionOutcome(
            buffer_updates={self.rel: "new"},
            transaction=AdoptionTransaction("tx", before_texts={self.rel: "old"}),
        )
        assistant = Mock()
        assistant.adopt.return_value = outcome
        assistant.current_texts.return_value = {self.rel: "new", "unrelated.md": "stale"}
        panel = SimpleNamespace(
            _assistant=assistant, _suggestions=[self.suggestion()],
            checked_suggestion_ids=lambda: ["wording-one"],
            summary_candidate=Mock(), buffers_changed=Mock(), set_status=Mock(),
        )
        AssistPanel.adopt_selected(panel)
        panel.buffers_changed.emit.assert_called_once_with({self.rel: "new"})

    def test_host_rejects_stale_expected_text_before_writing_editor(self):
        from PySide6.QtWidgets import QApplication, QPlainTextEdit
        from doc_tool.ui.main_window import MainWindow
        app = QApplication.instance() or QApplication([])
        editor = QPlainTextEdit()
        self.addCleanup(editor.deleteLater)
        editor.setPlainText("作者当前新稿")
        panel = SimpleNamespace(_editor=editor)
        workspace = SimpleNamespace(tabs_host=SimpleNamespace(editor_for=lambda key: panel))
        window = SimpleNamespace(
            _content_workspace=workspace,
            _project_summary=SimpleNamespace(manifest=SimpleNamespace(documentType="general")),
            _normalize_buffer_rel_path=lambda value: value,
            _refresh_interaction_state=Mock(), _show_status_message=Mock(),
        )
        MainWindow._on_assist_buffers_changed(
            window, {"a.md": "来自旧预览的结果"}, expected_texts={"a.md": "作者旧稿"},
        )
        self.assertEqual(editor.toPlainText(), "作者当前新稿")
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
