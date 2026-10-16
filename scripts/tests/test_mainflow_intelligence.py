# -*- coding: utf-8 -*-
"""Offline advice, current scope and readonly CLI integration regressions."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from doc_tool.application.mainflow_advice import (
    ALLOWED_ACTIONS, CHECK_CURRENT, IMPORT_RESULT, NEW_EXPORT, RETRY_ROUND,
    RULE_SETTINGS, SHOW_PROGRESS, SHOW_RESULTS, FormatFact, MainflowFacts,
    NextStep, QualityFacts, derive_advice,
)
from PySide6.QtWidgets import QApplication
APP = QApplication.instance() or QApplication([])


def quality(**kwargs):
    report = {"complete": True, "executedCount": 4, "configuration": {"valid": True}}
    report.update(kwargs.pop("report", {}))
    return QualityFacts(report=report, **kwargs)


class AdviceTests(unittest.TestCase):
    def test_unknown_is_not_clean(self):
        report = derive_advice(MainflowFacts())
        self.assertEqual(report.facts.quality.state, "unknown")
        self.assertEqual(report.primary.action, CHECK_CURRENT)

    def test_zero_execution_is_not_a_pass(self):
        q = quality(report={"executedCount": 0})
        self.assertEqual(q.state, "not-run")
        self.assertEqual(derive_advice(MainflowFacts(quality=q)).primary.action, CHECK_CURRENT)

    def test_invalid_configuration_dominates_an_empty_list(self):
        q = quality(report={"configuration": {"valid": False}})
        self.assertEqual(derive_advice(MainflowFacts(quality=q)).primary.action, RULE_SETTINGS)

    def test_unavailable_live_scope_is_incomplete(self):
        self.assertEqual(quality(unavailable=("live unavailable",)).state, "incomplete")

    def test_stale_results_are_not_reused_as_clean(self):
        self.assertEqual(quality(stale=True).state, "stale")

    def test_running_only_offers_progress(self):
        report = derive_advice(MainflowFacts(running=True))
        self.assertEqual([s.action for s in report.steps], [SHOW_PROGRESS])

    def test_partial_exports_retain_usable_output_and_round_identity(self):
        report = derive_advice(MainflowFacts(quality=quality(), round_id="round-a",
            round_source_mode="saved", round_scope_text="所选 2 章",
            formats=(FormatFact("docx", "pending-registration", True, True, False),
                     FormatFact("pdf", "failed"))))
        steps = {s.action: s for s in report.steps}
        self.assertIn(SHOW_RESULTS, steps)
        self.assertIn(RETRY_ROUND, steps)
        self.assertEqual(steps[RETRY_ROUND].round_id, "round-a")
        self.assertEqual(steps[RETRY_ROUND].scope_text, "所选 2 章")
        self.assertIn(NEW_EXPORT, steps)

    def test_stale_file_path_is_not_reported_as_available(self):
        report = derive_advice(MainflowFacts(formats=(FormatFact("docx", "ready", True, False),)))
        reason = next(s.reason for s in report.steps if s.action == SHOW_RESULTS)
        self.assertIn("已失效", reason)
        self.assertNotIn("可先使用", reason)

    def test_narrow_check_does_not_certify_the_whole_document(self):
        q = quality(scope_kind="selected", scope_text="所选 2 章")
        report = derive_advice(MainflowFacts(quality=q))
        self.assertIn(CHECK_CURRENT, [s.action for s in report.steps])
        self.assertIn("不能", next(s.reason for s in report.steps if s.action == CHECK_CURRENT))

    def test_import_followup_and_source_change_are_derived(self):
        report = derive_advice(MainflowFacts(import_attention=41, source_changed=True))
        self.assertIn(IMPORT_RESULT, [s.action for s in report.steps])
        self.assertIn("revision-preview", [s.action for s in report.steps])

    def test_no_arbitrary_commands_are_accepted(self):
        with self.assertRaises(ValueError):
            NextStep("rm -rf project", "untrusted", 100)
        report = derive_advice(MainflowFacts())
        self.assertTrue(all(s.action in ALLOWED_ACTIONS for s in report.steps))

    def test_order_and_actions_are_stable_and_unique(self):
        facts = MainflowFacts(quality=quality(), import_attention=4)
        a, b = derive_advice(facts), derive_advice(facts)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(len(a.steps), len({s.action for s in a.steps}))


class LiveQualityTests(unittest.TestCase):
    def setUp(self):
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.lint import ContentLinter, TermStore
        self.tmp = tempfile.TemporaryDirectory(prefix="mainflow-scope-")
        self.root = Path(self.tmp.name)
        self.content = self.root / "content"
        self.content.mkdir()
        (self.content / "a.md").write_text("# 标题甲\n\n原稿\n", encoding="utf-8")
        (self.content / "b.md").write_text("# 标题乙\n\n另一章\n", encoding="utf-8")
        self.index_service = ContentIndexService(self.content)
        self.index = self.index_service.build()
        self.linter = ContentLinter(self.index)
        self.terms = TermStore(self.root / ".state")
        self.buffers = {}
        self.current = "a.md"
        self.selected = ["b.md"]
        self.panels = []

    def tearDown(self):
        for panel in self.panels:
            panel.close()
        self.tmp.cleanup()

    def make_panel(self, scoped=None):
        from doc_tool.ui.content.lint_panel import LintPanel
        if scoped is None:
            def scoped(paths, overrides):
                import copy
                from doc_tool.application.content.lint import ContentLinter
                idx = copy.deepcopy(self.index)
                for rel, text in overrides.items():
                    idx.lines[rel] = text.splitlines()
                if paths is not None:
                    for key in list(idx.lines):
                        if key not in paths:
                            idx.lines.pop(key)
                            idx.files.pop(key, None)
                            idx.headings.pop(key, None)
                return ContentLinter(idx)
        panel = LintPanel(self.linter, self.terms,
            scope_provider=lambda: ("current", self.current, self.selected),
            live_text_provider=lambda p: self.buffers.get(p), scoped_linter_provider=scoped)
        self.panels.append(panel)
        return panel

    def test_initial_empty_view_never_says_pass(self):
        panel = self.make_panel()
        panel._render_results()
        self.assertNotIn("检查通过", panel._status_label.text())
        self.assertEqual(panel.quality_facts().state, "unknown")

    def test_selected_scope_label_and_only_selected_live_issue(self):
        panel = self.make_panel()
        self.buffers = {"a.md": "# 标题甲\nTODO outside\n", "b.md": "# 标题乙\nTODO selected\n"}
        panel._scope_combo.setCurrentIndex(panel._scope_combo.findData("selected"))
        self.assertTrue(panel.run_check())
        self.assertEqual(panel.quality_facts().scope_text, "所选章")
        self.assertTrue(panel._issues)
        self.assertTrue(all(i.rel_path == "b.md" for i in panel._issues))
        self.assertEqual((self.content / "b.md").read_text(encoding="utf-8"), "# 标题乙\n\n另一章\n")

    def test_empty_current_scope_does_not_run_or_pass(self):
        panel = self.make_panel()
        self.current = None
        panel._scope_combo.setCurrentIndex(panel._scope_combo.findData("current"))
        self.assertFalse(panel.run_check())
        self.assertEqual(panel.quality_facts().state, "not-run")
        self.assertIn("未执行", panel._status_label.text())
        self.assertNotIn("✓", panel._status_label.text())

    def test_changed_live_text_marks_report_stale(self):
        panel = self.make_panel()
        self.assertTrue(panel.run_check())
        self.buffers["a.md"] = "# 标题甲\n新增正文\n"
        self.assertTrue(panel.quality_facts().stale)

    def test_failed_scope_does_not_look_like_clean_saved_content(self):
        def failed(*_args):
            raise OSError("injected scope failure")
        panel = self.make_panel(scoped=failed)
        self.buffers["a.md"] = "# 标题甲\nTODO live\n"
        self.assertFalse(panel.run_check())
        self.assertEqual(panel.quality_facts().state, "incomplete")
        self.assertNotIn("检查通过", panel._status_label.text())

    def test_live_buffer_read_failure_never_passes(self):
        panel = self.make_panel()
        panel._live_text_provider = Mock(side_effect=OSError("injected live failure"))
        self.assertFalse(panel.run_check())
        self.assertEqual(panel.quality_facts().state, "incomplete")


from test_mainflow_intelligence_safety import SafetyFixture as ImportedProjectCase


class ReadonlyCliTests(ImportedProjectCase):
    def tree_digest(self):
        return {p.relative_to(self.project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.project.rglob("*") if p.is_file()}

    def invoke(self, *extra):
        from doc_tool.cli import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["mainflow-advice", "--project", str(self.project), "--output", "json", *extra])
        return code, json.loads(out.getvalue())

    def test_saved_query_is_single_json_no_writes_word_or_model(self):
        before = self.tree_digest()
        with patch("doc_tool.application.project_export._word_available", side_effect=AssertionError("no Word")):
            with patch("doc_tool.application.assist.provider.ProviderGateway.enhance", side_effect=AssertionError("no model")):
                code, result = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(result["sourceMode"], "saved")
        self.assertTrue(result["readOnly"])
        self.assertEqual(before, self.tree_digest())

    def test_no_check_keeps_unknown(self):
        code, result = self.invoke("--no-check")
        self.assertEqual(code, 0)
        self.assertEqual(result["quality"]["state"], "unknown")

    def test_capability_contract_is_explicit(self):
        from doc_tool.application.capabilities import get_capabilities_report
        command = next(c for c in get_capabilities_report()["commands"] if c["name"] == "mainflow-advice")
        self.assertTrue(command["readOnly"])
        self.assertFalse(command["requiresWord"])
        self.assertFalse(command["requiresModel"])

    def test_gui_action_rechecks_running_and_refuses_old_action(self):
        from doc_tool.ui.main_window import MainWindow
        fake = Mock(spec=MainWindow)
        from types import SimpleNamespace
        fake._project_summary = SimpleNamespace(project_root=ROOT)
        fake._mainflow_facts.return_value = MainflowFacts(running=True)
        self.assertFalse(MainWindow._on_mainflow_action(fake, NEW_EXPORT, str(ROOT)))
        fake._on_export_settings.assert_not_called()

    def test_gui_action_uses_actual_existing_checker(self):
        from doc_tool.ui.main_window import MainWindow
        fake = Mock(spec=MainWindow)
        from types import SimpleNamespace
        fake._project_summary = SimpleNamespace(project_root=ROOT)
        fake._mainflow_facts.return_value = MainflowFacts()
        self.assertTrue(MainWindow._on_mainflow_action(fake, CHECK_CURRENT, str(ROOT)))
        fake._on_validate.assert_called_once_with()

    def test_gui_rejects_document_supplied_action(self):
        from doc_tool.ui.main_window import MainWindow
        fake = Mock(spec=MainWindow)
        self.assertFalse(MainWindow._on_mainflow_action(fake, "powershell -command untrusted"))
        fake._mainflow_facts.assert_not_called()


class AdviceActionContextTests(unittest.TestCase):
    """Exercise the actual host method without writing any project files."""

    def make_host(self, facts=None):
        from types import SimpleNamespace
        from doc_tool.ui.main_window import MainWindow
        host = Mock(spec=MainWindow)
        host._project_summary = SimpleNamespace(project_root=ROOT)
        host.runner = SimpleNamespace(is_running=False)
        host._mainflow_facts.return_value = facts or MainflowFacts()
        host._export_rounds = SimpleNamespace(latest=Mock(return_value=SimpleNamespace(round_id="round-a")))
        return host

    def pending(self, round_id="round-a"):
        return MainflowFacts(round_id=round_id,
            formats=(FormatFact("docx", "pending-refresh", True),))

    def invoke(self, host, action=RETRY_ROUND, project=None, round_id="round-a"):
        from doc_tool.ui.main_window import MainWindow
        return MainWindow._on_mainflow_action(host, action,
            str(ROOT) if project is None else project, round_id)

    def test_old_round_cannot_silently_retry_the_new_latest_round(self):
        host = self.make_host(self.pending("round-b"))
        host._export_rounds.latest.return_value.round_id = "round-b"
        self.assertFalse(self.invoke(host))
        host._on_retry_export_round.assert_not_called()

    def test_same_round_id_in_another_project_is_rejected(self):
        host = self.make_host(self.pending())
        self.assertFalse(self.invoke(host, project=str(ROOT / "another-project")))
        host._mainflow_facts.assert_not_called()
        host._on_retry_export_round.assert_not_called()

    def test_matching_project_and_round_reuse_existing_retry_handler(self):
        host = self.make_host(self.pending())
        self.assertTrue(self.invoke(host))
        host._on_retry_export_round.assert_called_once_with(host._export_rounds.latest.return_value)

    def test_missing_round_identity_never_retries_the_latest_implicitly(self):
        host = self.make_host(self.pending())
        self.assertFalse(self.invoke(host, round_id=""))
        host._on_retry_export_round.assert_not_called()

    def test_contextless_project_action_is_not_executed(self):
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host()
        self.assertFalse(MainWindow._on_mainflow_action(host, CHECK_CURRENT))
        host._on_validate.assert_not_called()

    def test_unreadable_facts_never_execute_the_displayed_request(self):
        host = self.make_host(self.pending())
        host._mainflow_facts.side_effect = OSError("facts unavailable")
        self.assertFalse(self.invoke(host))
        host._on_retry_export_round.assert_not_called()

    def test_round_is_checked_again_immediately_before_retry(self):
        host = self.make_host(self.pending())
        host._export_rounds.latest.return_value.round_id = "round-c"
        self.assertFalse(self.invoke(host))
        host._on_retry_export_round.assert_not_called()

    def test_old_results_action_cannot_open_a_different_round(self):
        host = self.make_host(self.pending("round-b"))
        self.assertFalse(self.invoke(host, action=SHOW_RESULTS))
        host._on_show_results.assert_not_called()

    def test_non_round_action_survives_unrelated_new_export_round(self):
        host = self.make_host(self.pending("round-b"))
        self.assertTrue(self.invoke(host, action=CHECK_CURRENT, round_id=""))
        host._on_validate.assert_called_once_with()

    def test_equivalent_project_paths_are_not_mistaken_for_a_switch(self):
        host = self.make_host(self.pending())
        self.assertTrue(self.invoke(host, project=str(ROOT / "doc_tool" / "..")))

    def test_panel_emits_the_project_and_round_that_were_displayed(self):
        from doc_tool.ui.mainflow_advice_panel import MainflowAdvicePanel
        panel = MainflowAdvicePanel()
        self.addCleanup(panel.deleteLater)
        report = derive_advice(self.pending())
        panel.set_report(report, str(ROOT))
        row = next(i for i, step in enumerate(report.steps) if step.action == RETRY_ROUND)
        panel._steps.setCurrentRow(row)
        requests = []
        panel.action_requested.connect(lambda *request: requests.append(request))
        panel._request()
        self.assertEqual(requests, [(RETRY_ROUND, str(ROOT), "round-a")])

    def test_primary_click_does_not_silently_choose_a_new_primary_action(self):
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host(self.pending("round-b"))
        host._mainflow_primary_request = (RETRY_ROUND, str(ROOT), "round-a")
        MainWindow._on_mainflow_primary(host)
        host._on_mainflow_action.assert_called_once_with(RETRY_ROUND, str(ROOT), "round-a")
        host._refresh_mainflow_advice.assert_not_called()

    def test_missing_primary_request_does_not_guess_a_new_action(self):
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host()
        host._mainflow_primary_request = None
        MainWindow._on_mainflow_primary(host)
        host._on_mainflow_action.assert_not_called()

    def test_refresh_failure_clears_old_actions_and_panel(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QToolButton, QMenu
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host()
        button, menu = QToolButton(), QMenu()
        self.addCleanup(button.deleteLater)
        self.addCleanup(menu.deleteLater)
        menu.addAction("old action")
        panel = Mock()
        host._mainflow_next_button, host._mainflow_next_menu = button, menu
        host._content_workspace = SimpleNamespace(_mainflow_advice_panel=panel)
        host._mainflow_primary_request = (CHECK_CURRENT, str(ROOT), "")
        host._mainflow_facts.side_effect = OSError("cannot read current facts")
        self.assertIsNone(MainWindow._refresh_mainflow_advice(host))
        self.assertIsNone(host._mainflow_primary_request)
        self.assertEqual(menu.actions(), [])
        self.assertFalse(button.isEnabled())
        panel.set_report.assert_called_once_with(None)

    def test_live_buffer_read_failure_is_not_reported_as_saved_content(self):
        from types import SimpleNamespace
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host()
        host._content_workspace = SimpleNamespace(_lint_panel=None)
        host._project_summary = SimpleNamespace(project_root=ROOT, is_writable=True,
            manifest=SimpleNamespace(), paths=SimpleNamespace())
        host._export_rounds.latest.return_value = None
        host._collect_buffer_texts.return_value = {}
        host._collect_assist_buffer_texts.side_effect = OSError("live buffer unreadable")
        with patch("doc_tool.application.import_record.read_import_record", return_value=None):
            with self.assertRaisesRegex(OSError, "live buffer unreadable"):
                MainWindow._mainflow_facts(host)
        host._collect_buffer_texts.assert_not_called()

    def test_project_path_read_failure_clears_the_displayed_request(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QToolButton, QMenu
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host()
        button, menu = QToolButton(), QMenu()
        self.addCleanup(button.deleteLater)
        self.addCleanup(menu.deleteLater)
        host._mainflow_next_button, host._mainflow_next_menu = button, menu
        host._content_workspace = SimpleNamespace(_mainflow_advice_panel=None)
        host._mainflow_primary_request = (CHECK_CURRENT, str(ROOT), "")
        with patch("doc_tool.ui.main_window.Path.resolve", side_effect=OSError("project unavailable")):
            self.assertIsNone(MainWindow._refresh_mainflow_advice(host))
        self.assertIsNone(host._mainflow_primary_request)
        self.assertFalse(button.isEnabled())

    def test_closed_project_rejects_a_request_from_the_old_project(self):
        host = self.make_host(self.pending())
        host._project_summary = None
        self.assertFalse(self.invoke(host))
        host._on_retry_export_round.assert_not_called()

    def test_open_project_remains_available_when_no_project_is_loaded(self):
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host(MainflowFacts(project_loaded=False))
        host._project_summary = None
        self.assertTrue(MainWindow._on_mainflow_action(host, "open-project"))
        host._on_open_project.assert_called_once_with()

    def test_invalidated_panel_cannot_emit_the_previous_request(self):
        from doc_tool.ui.mainflow_advice_panel import MainflowAdvicePanel
        panel = MainflowAdvicePanel()
        self.addCleanup(panel.deleteLater)
        panel.set_report(derive_advice(self.pending()), str(ROOT))
        requests = []
        panel.action_requested.connect(lambda *request: requests.append(request))
        panel.set_report(None)
        panel._request()
        self.assertEqual(requests, [])
        self.assertFalse(panel._execute.isEnabled())

    def test_menu_callback_keeps_its_displayed_project_and_round(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QToolButton, QMenu
        from doc_tool.ui.main_window import MainWindow
        host = self.make_host(self.pending())
        button, menu = QToolButton(), QMenu()
        self.addCleanup(button.deleteLater)
        self.addCleanup(menu.deleteLater)
        host._mainflow_next_button, host._mainflow_next_menu = button, menu
        host._content_workspace = SimpleNamespace(_mainflow_advice_panel=None)
        MainWindow._refresh_mainflow_advice(host)
        action = next(a for a in menu.actions() if a.text() == "补原轮未完成格式")
        host._project_summary.project_root = ROOT / "another-project"
        action.trigger()
        host._on_mainflow_action.assert_called_once_with(RETRY_ROUND, str(ROOT), "round-a")


class NativeWorkflowUiTests(ImportedProjectCase):
    def make_window(self):
        from types import SimpleNamespace
        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.content.unsaved_prompt import UnsavedChoice
        recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        recent.start()
        self.addCleanup(recent.stop)
        window = MainWindow(unsaved_resolver=lambda *_: UnsavedChoice.DISCARD)
        self.addCleanup(window.close)
        summary = SimpleNamespace(project_root=self.project, is_writable=True,
                                  manifest=self.manifest, paths=self.paths)
        window._project_summary = summary
        window._init_content_workspace(summary)
        import time
        deadline = time.monotonic() + 8
        while getattr(window._content_workspace, "_lint_panel", None) is None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertIsNotNone(getattr(window._content_workspace, "_lint_panel", None), "background index must finish")
        self.assertTrue(window._open_chapter_in_workspace(self.rel))
        return window

    def test_next_step_button_and_existing_tool_tab_are_reachable(self):
        window = self.make_window()
        report = window._refresh_mainflow_advice()
        self.assertIsNotNone(report, window._mainflow_next_button.toolTip())
        self.assertFalse(window._mainflow_next_button.isHidden())
        window._on_mainflow_panel()
        panel = window._content_workspace._mainflow_advice_panel
        self.assertGreater(panel._steps.count(), 0)
        self.assertIn("下一步", [window._content_workspace._panels.tabText(i)
                               for i in range(window._content_workspace._panels.count())])

    def test_real_f5_sees_dirty_text_without_saving_it(self):
        window = self.make_window()
        editor = window._content_workspace.tabs_host.editor_for(self.rel)
        if editor is None:
            editor = window._content_workspace.tabs_host.editor_for("general/" + self.rel)
        source_path = self.paths.content_root / editor.current_rel_path()
        original = source_path.read_text(encoding="utf-8")
        editor._editor.setPlainText(original + "\nTODO INTELLIGENCE-LIVE\n")
        window._on_validate()
        panel = window._content_workspace._lint_panel
        self.assertTrue(any("TODO" in i.message or i.rule_id == "todo_residual" for i in panel._issues),
                        (panel._quality_report, panel._issues, panel._scope_label.text(), editor.is_dirty(), panel._status_label.text()))
        self.assertEqual(source_path.read_text(encoding="utf-8"), original)
        self.assertTrue(editor.is_dirty())
        self.assertEqual(panel.quality_facts().source_mode, "current-buffer")

    def test_assistant_reloads_live_workspace_paths_before_real_adoption(self):
        from doc_tool.application.assist.service import AuthoringAssistant
        from doc_tool.application.assist.models import KIND_TERM
        from PySide6.QtCore import Qt
        window = self.make_window()
        tabs = window._content_workspace.tabs_host
        editor = tabs.editor_for(self.rel) or tabs.editor_for("general/" + self.rel)
        editor._editor.setPlainText("# 目的\n\nAPIv1\n")
        assistant = AuthoringAssistant.from_project(self.project, cache_enabled=False,
            terms=["APIv2"], term_aliases={"APIv1": "APIv2"})
        with patch("doc_tool.application.assist.service.build_assistant", return_value=assistant):
            window._on_assist_panel()
        panel = window._assist_dock.widget()
        collected = panel.load_suggestions([KIND_TERM])
        applicable = {s.suggestion_id for s in collected.suggestions if s.applicable}
        self.assertTrue(applicable)
        editor._editor.setPlainText(editor._editor.toPlainText() + "作者刚刚追加\n")
        for row in range(panel._suggestions_list.count()):
            item = panel._suggestions_list.item(row)
            suggestion = item.data(Qt.ItemDataRole.UserRole)
            if suggestion.suggestion_id in applicable:
                item.setCheckState(Qt.CheckState.Checked)
        outcome = panel.adopt_selected()
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.applied)
        self.assertIn("APIv2", editor._editor.toPlainText())
        self.assertIn("作者刚刚追加", editor._editor.toPlainText())
        self.assertEqual(len(outcome.buffer_updates), 1)


if __name__ == "__main__":
    unittest.main()
