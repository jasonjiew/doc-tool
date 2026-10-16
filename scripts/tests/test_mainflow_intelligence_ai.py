# -*- coding: utf-8 -*-
"""Optional-AI consent and candidate tests. All providers/transports here are synthetic."""
import dataclasses
import io
from email.message import Message
import urllib.request
import urllib.response
from doc_tool.application.assist.provider import ProviderError
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtWidgets import QApplication
from doc_tool.application.assist.models import (
    ENHANCE_CANCELLED, ENHANCE_DISABLED, ENHANCE_OK, INSERT_MODE_COPY_TEXT,
    PROVIDER_HTTP, PROVIDER_LOCAL_COMMAND, PURPOSE_REVISION_SUMMARY, PURPOSE_TERM,
)
from doc_tool.application.assist.provider import HttpProvider, LocalCommandProvider, ProviderConfig, ProviderGateway
from doc_tool.application.assist.service import AuthoringAssistant
APP = QApplication.instance() or QApplication([])


class SyntheticProvider:
    def __init__(self):
        self.calls = []

    def response(self, purpose):
        return {"schemaVersion": 1, "purpose": purpose,
                "suggestions": [{"text": "候选一"}, {"text": "候选二"}]}

    def suggest_revision(self, context):
        self.calls.append(dict(context))
        return self.response(PURPOSE_REVISION_SUMMARY)

    def suggest_terms(self, context):
        self.calls.append(dict(context))
        return self.response(PURPOSE_TERM)


class PreviewTests(unittest.TestCase):
    def config(self, **extra):
        values = dict(enabled=True, provider=PROVIDER_LOCAL_COMMAND, command="synthetic-never-executed", max_chars=200)
        values.update(extra)
        return ProviderConfig(**values)

    def gateway(self, config=None, provider=None):
        provider = provider or SyntheticProvider()
        # Even a broken guard cannot cause a real transport/process in these tests.
        return ProviderGateway(config or self.config(), provider=provider, provider_factory=lambda _cfg: provider), provider

    def test_preparing_resolves_no_provider_and_makes_no_calls(self):
        factory = Mock(side_effect=AssertionError("preview cannot resolve provider"))
        gateway = ProviderGateway(self.config(), provider_factory=factory)
        preview = gateway.prepare(PURPOSE_TERM, context_text="接口正文")
        self.assertTrue(preview.can_send)
        factory.assert_not_called()
        self.assertEqual(gateway.provider_call_count, 0)
        self.assertEqual(gateway.request_log, [])

    def test_frozen_preview_cannot_be_mutated_via_display_dictionary(self):
        gateway, _ = self.gateway()
        preview = gateway.prepare(PURPOSE_TERM, context_text="原来选定的正文")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            preview.text = "hidden replacement"
        preview.wire_payload()["context"]["text"] = "not applied"
        self.assertEqual(preview.text, "原来选定的正文")

    def test_http_transport_receives_exact_previewed_payload_after_truncation(self):
        config = self.config(provider=PROVIDER_HTTP, endpoint="https://example.invalid/synthetic", model="mock-model")
        captured = []
        def transport(endpoint, payload, headers, timeout):
            captured.append((endpoint, payload))
            return json.dumps(SyntheticProvider().response(PURPOSE_TERM))
        provider = HttpProvider(config, transport=transport)
        gateway, _ = self.gateway(config, provider)
        preview = gateway.prepare(PURPOSE_TERM, context_text="接口" * 300,
                                  evidence_ids=["local-ref-a"], scope_label="选定合成样例")
        self.assertTrue(preview.truncated)
        result = gateway.enhance(PURPOSE_TERM, context_text="THIS MUST NOT REPLACE THE PREVIEW", prepared=preview)
        self.assertEqual(result.status, ENHANCE_OK)
        self.assertEqual(captured[0][1], preview.wire_payload())
        self.assertEqual(result.requested_chars, preview.requested_chars)
        self.assertEqual(result.truncated, preview.truncated)

    def test_local_command_receives_the_same_json_envelope(self):
        config = self.config()
        captured = []
        def runner(argv, payload, timeout):
            captured.append(json.loads(payload))
            return json.dumps(SyntheticProvider().response(PURPOSE_REVISION_SUMMARY))
        provider = LocalCommandProvider(config, runner=runner)
        gateway, _ = self.gateway(config, provider)
        preview = gateway.prepare(PURPOSE_REVISION_SUMMARY, context_text="明确选定的合成变更")
        gateway.enhance(preview.purpose, context_text="ignored", prepared=preview)
        self.assertEqual(captured, [preview.wire_payload()])

    def test_configuration_change_requires_a_new_preview(self):
        gateway, provider = self.gateway()
        preview = gateway.prepare(PURPOSE_TERM, context_text="selected")
        gateway.set_config(self.config(command="another-synthetic-command"))
        result = gateway.enhance(preview.purpose, context_text="ignored", prepared=preview)
        self.assertEqual(result.status, ENHANCE_CANCELLED)
        self.assertEqual(provider.calls, [])
        self.assertEqual(gateway.provider_call_count, 0)

    def test_cancel_before_call_is_zero_requests(self):
        gateway, provider = self.gateway()
        preview = gateway.prepare(PURPOSE_TERM, context_text="selected")
        result = gateway.enhance(preview.purpose, context_text="ignored", prepared=preview,
                                 cancel_token=SimpleNamespace(is_cancelled=True))
        self.assertEqual(result.status, ENHANCE_CANCELLED)
        self.assertEqual(provider.calls, [])

    def test_cancelled_late_response_never_becomes_an_adoptable_candidate(self):
        token = SimpleNamespace(is_cancelled=False)
        provider = SyntheticProvider()
        original = provider.suggest_terms
        def response(context):
            value = original(context)
            token.is_cancelled = True
            return value
        provider.suggest_terms = response
        gateway, _ = self.gateway(provider=provider)
        preview = gateway.prepare(PURPOSE_TERM, context_text="selected", local_candidates=["本地候选"])
        result = gateway.enhance(preview.purpose, context_text="ignored", prepared=preview, cancel_token=token)
        self.assertEqual(result.status, ENHANCE_CANCELLED)
        self.assertEqual(result.enhanced, [])
        self.assertTrue(result.used_local_candidates)

    def test_default_disabled_stays_zero_calls(self):
        gateway, provider = self.gateway(ProviderConfig())
        preview = gateway.prepare(PURPOSE_TERM, context_text="selected", local_candidates=["本地候选"])
        result = gateway.enhance(preview.purpose, context_text="ignored", prepared=preview)
        self.assertEqual(result.status, ENHANCE_DISABLED)
        self.assertEqual(provider.calls, [])

    def test_context_and_credential_values_stay_out_of_request_logs_and_preview_config(self):
        config = self.config(provider=PROVIDER_HTTP, endpoint="https://example.invalid/synthetic",
                             credential_env="DOC_TOOL_SYNTHETIC_TEST_CREDENTIAL")
        gateway, _ = self.gateway(config)
        with patch.dict(os.environ, {"DOC_TOOL_SYNTHETIC_TEST_CREDENTIAL": "DUMMY-NOT-A-REAL-CREDENTIAL"}):
            preview = gateway.prepare(PURPOSE_TERM, context_text="PRIVATE-SYNTHETIC-CONTEXT")
            gateway.enhance(preview.purpose, context_text="ignored", prepared=preview)
            self.assertNotIn("DUMMY-NOT-A-REAL-CREDENTIAL", json.dumps(preview.to_dict()))
            self.assertNotIn("DUMMY-NOT-A-REAL-CREDENTIAL", gateway.request_log_text())
            self.assertNotIn("PRIVATE-SYNTHETIC-CONTEXT", gateway.request_log_text())

    def test_error_diagnostics_redact_auth_and_url_secrets_not_only_log_metadata(self):
        from doc_tool.application.assist.provider import ProviderError
        config = self.config(provider=PROVIDER_HTTP,
            endpoint="https://synthetic-user:synthetic-pass@example.invalid/path?token=synthetic-query-secret",
            credential_env="DOC_TOOL_SYNTHETIC_ERROR_AUTH")
        provider = SyntheticProvider()
        provider.suggest_terms = Mock(side_effect=ProviderError(
            "failure DUMMY-SYNTHETIC-ERROR-AUTH synthetic-user synthetic-pass synthetic-query-secret"))
        gateway, _ = self.gateway(config, provider)
        with patch.dict(os.environ, {"DOC_TOOL_SYNTHETIC_ERROR_AUTH": "DUMMY-SYNTHETIC-ERROR-AUTH"}):
            preview = gateway.prepare(PURPOSE_TERM, context_text="synthetic selected context", local_candidates=["本地候选"])
            result = gateway.enhance(preview.purpose, context_text="ignored", prepared=preview)
        diagnostic = json.dumps(result.to_dict(), ensure_ascii=False)
        for secret in ["DUMMY-SYNTHETIC-ERROR-AUTH", "synthetic-user", "synthetic-pass", "synthetic-query-secret"]:
            self.assertNotIn(secret, diagnostic)
        self.assertTrue(result.used_local_candidates)
        self.assertEqual(gateway.provider_call_count, 1)

    def test_local_error_diagnostics_redact_configured_argument_values(self):
        from doc_tool.application.assist.provider import ProviderError
        config = self.config(args=["--api-key", "synthetic-argv-secret", "--other=synthetic-equals-secret"])
        def runner(argv, payload, timeout):
            raise ProviderError("synthetic stderr: synthetic-argv-secret --other=synthetic-equals-secret")
        provider = LocalCommandProvider(config, runner=runner)
        gateway, _ = self.gateway(config, provider)
        preview = gateway.prepare(PURPOSE_TERM, context_text="synthetic selected context", local_candidates=["本地候选"])
        result = gateway.enhance(preview.purpose, context_text="ignored", prepared=preview)
        diagnostic = json.dumps(result.to_dict(), ensure_ascii=False)
        self.assertNotIn("synthetic-argv-secret", diagnostic)
        self.assertNotIn("synthetic-equals-secret", diagnostic)
        self.assertTrue(result.used_local_candidates)

    def test_endpoint_description_redacts_url_credentials_and_query_values(self):
        config = self.config(provider=PROVIDER_HTTP,
            endpoint="https://synthetic-user:synthetic-pass@example.invalid/path?token=synthetic-token")
        target = config.target_description()
        self.assertIn("example.invalid/path", target)
        self.assertNotIn("synthetic-user", target)
        self.assertNotIn("synthetic-pass", target)
        self.assertNotIn("synthetic-token", target)


class CandidateUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mainflow-ai-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "sample.md").write_text("# 合成项目\n接口的当前正文\n", encoding="utf-8")
        self.panels = []

    def tearDown(self):
        for panel in self.panels:
            panel.close()

    def assistant(self, enabled=True, provider=None, read_only=False):
        provider = provider or SyntheticProvider()
        config = ProviderConfig(enabled=enabled, provider=PROVIDER_LOCAL_COMMAND if enabled else "disabled",
                                command="synthetic-never-executed", timeout_seconds=1)
        assistant = AuthoringAssistant.from_project(self.root, provider_config=config, provider=provider,
            cache_enabled=False, cache_dir=self.root / "unused-cache", read_only=read_only)
        assistant.gateway._provider_factory = lambda _cfg: provider
        assistant.revision_summary_texts = Mock(return_value=["本地合成变更事实"])
        return assistant, provider

    def panel(self, assistant, confirm=None):
        from doc_tool.ui.assist_panel import AssistPanel
        panel = AssistPanel(assistant, confirm_enhancement=confirm)
        self.panels.append(panel)
        return panel

    def test_preview_dialog_displays_exact_body_without_requests(self):
        from doc_tool.ui.enhancement_preview import EnhancementPreviewDialog
        assistant, provider = self.assistant()
        preview = assistant.preview_enhance(PURPOSE_TERM)
        dialog = EnhancementPreviewDialog(preview)
        self.addCleanup(dialog.close)
        self.assertEqual(json.loads(dialog.payload_view.toPlainText()), preview.wire_payload())
        self.assertEqual(provider.calls, [])

    def test_cancelled_confirmation_is_zero_calls_and_keeps_local_candidates(self):
        assistant, provider = self.assistant()
        confirm = Mock(return_value=False)
        panel = self.panel(assistant, confirm)
        result = panel.enhance(PURPOSE_REVISION_SUMMARY, background=False)
        self.assertEqual(result.status, ENHANCE_CANCELLED)
        self.assertEqual(provider.calls, [])
        self.assertEqual(panel._enhancement_candidates.count(), 1)
        confirm.assert_called_once()

    def test_disabled_provider_never_even_asks_for_confirmation(self):
        assistant, provider = self.assistant(enabled=False)
        confirm = Mock(side_effect=AssertionError("disabled provider has nothing to send"))
        panel = self.panel(assistant, confirm)
        result = panel.enhance(PURPOSE_REVISION_SUMMARY)
        self.assertEqual(result.status, ENHANCE_DISABLED)
        confirm.assert_not_called()
        self.assertEqual(provider.calls, [])

    def test_multiple_summary_candidates_emit_nothing_until_one_is_selected(self):
        assistant, provider = self.assistant()
        panel = self.panel(assistant, lambda _p: True)
        emitted = []
        panel.summary_candidate.connect(emitted.append)
        result = panel.enhance(PURPOSE_REVISION_SUMMARY, background=False)
        self.assertEqual(result.status, ENHANCE_OK)
        self.assertEqual(emitted, [])
        self.assertEqual(panel._enhancement_candidates.count(), 2)
        self.assertIn("无本地出处", panel._enhancement_candidates.item(0).text())
        panel._enhancement_candidates.setCurrentRow(1)
        self.assertTrue(panel.adopt_enhancement_selected())
        self.assertEqual(emitted, ["候选二"])

    def test_term_choice_is_explicit_insertion_not_a_dictionary_write(self):
        assistant, _ = self.assistant()
        panel = self.panel(assistant, lambda _p: True)
        emitted = []
        panel.insert_requested.connect(lambda text, mode: emitted.append((text, mode)))
        before = (self.root / "sample.md").read_bytes()
        panel.enhance(PURPOSE_TERM, background=False)
        self.assertEqual(emitted, [])
        self.assertTrue(panel.adopt_enhancement_selected())
        self.assertEqual(emitted, [("候选一", INSERT_MODE_COPY_TEXT)])
        self.assertEqual((self.root / "sample.md").read_bytes(), before)
        self.assertFalse((self.root / "quality" / "terms.json").exists())

    def test_read_only_can_view_copy_but_not_adopt(self):
        assistant, _ = self.assistant(read_only=True)
        panel = self.panel(assistant, lambda _p: True)
        emitted = []
        panel.summary_candidate.connect(emitted.append)
        panel.enhance(PURPOSE_REVISION_SUMMARY, background=False)
        self.assertFalse(panel.adopt_enhancement_selected())
        self.assertEqual(emitted, [])
        self.assertFalse(panel._adopt_enhancement_button.isEnabled())

    def test_changing_assistant_clears_previous_project_candidates(self):
        assistant, _ = self.assistant()
        panel = self.panel(assistant, lambda _p: True)
        panel.enhance(PURPOSE_REVISION_SUMMARY, background=False)
        self.assertGreater(panel._enhancement_candidates.count(), 0)
        replacement, _ = self.assistant()
        panel.set_assistant(replacement)
        self.assertEqual(panel._enhancement_candidates.count(), 0)
        self.assertFalse(panel.adopt_enhancement_selected())

    def test_background_call_reuses_runner_blocks_duplicates_and_discards_cancelled_response(self):
        entered, release = threading.Event(), threading.Event()
        provider = SyntheticProvider()
        original = provider.suggest_revision
        def blocking(context):
            value = original(context)
            entered.set()
            release.wait(3)
            return value
        provider.suggest_revision = blocking
        assistant, _ = self.assistant(provider=provider)
        confirm = Mock(return_value=True)
        panel = self.panel(assistant, confirm)
        self.addCleanup(release.set)
        emitted = []
        panel.summary_candidate.connect(emitted.append)
        self.assertIsNone(panel.enhance(PURPOSE_REVISION_SUMMARY))
        self.assertTrue(entered.wait(2), "synthetic background provider must start")
        panel.enhance(PURPOSE_REVISION_SUMMARY)
        confirm.assert_called_once()
        self.assertEqual(len(provider.calls), 1)
        panel.cancel_enhancement()
        release.set()
        deadline = time.monotonic() + 5
        while panel._enhance_runner.is_running and time.monotonic() < deadline:
            APP.processEvents()
            panel._poll_enhancement()
            time.sleep(0.01)
        panel._poll_enhancement()
        self.assertFalse(panel._enhance_runner.is_running)
        self.assertEqual(panel._enhancement_result.status, ENHANCE_CANCELLED)
        self.assertEqual(emitted, [])
        self.assertTrue(panel._enhancement_result.used_local_candidates)


class BuiltinHttpConsentTests(unittest.TestCase):
    def exercise(self, *, redirect_code=None, redirect_target='https://unconfirmed.invalid/collect'):
        calls = []
        approved = 'https://approved.invalid/v1'
        payload = {'schemaVersion': 1, 'context': {'text': '纯合成正文，不含真实资料'}}
        reply = json.dumps({'purpose': 'term', 'suggestions': []}).encode('utf-8')

        class MemoryHttps(urllib.request.BaseHandler):
            handler_order = 0

            def https_open(self, request):
                calls.append({'url': request.full_url, 'method': request.get_method(),
                              'body': request.data, 'headers': dict(request.header_items())})
                headers = Message()
                code = 200
                if redirect_code is not None and request.full_url == approved:
                    code = redirect_code
                    headers['Location'] = redirect_target
                response = urllib.response.addinfourl(io.BytesIO(reply if code == 200 else b''),
                                                     headers, request.full_url, code)
                response.msg = 'OK' if code == 200 else 'Synthetic redirect'
                return response

        handler = MemoryHttps()
        builder = urllib.request.build_opener
        opener = builder(handler)
        error = None
        body = None
        # Both legacy global urlopen and the corrected private opener are intercepted.
        # The socket guards prevent accidental fallback to a real connection.
        with patch('urllib.request._opener', opener), \
             patch('urllib.request.build_opener', side_effect=lambda *handlers: builder(handler, *handlers)), \
             patch('socket.create_connection', side_effect=AssertionError('real network forbidden')), \
             patch('socket.socket.connect', side_effect=AssertionError('real network forbidden')):
            try:
                body = HttpProvider._urllib_transport(approved, payload,
                    {'Content-Type': 'application/json', 'Authorization': 'Bearer DUMMY-SYNTHETIC-REDIRECT-AUTH'}, 1)
            except ProviderError as exc:
                error = exc
        return calls, body, error, payload, approved

    def test_redirect_cannot_make_an_unconfirmed_second_request(self):
        for status in (301, 302, 303, 307, 308):
            for target in ('https://unconfirmed.invalid/collect', 'https://approved.invalid/other'):
                with self.subTest(status=status, target=target):
                    calls, _body, error, _payload, approved = self.exercise(redirect_code=status, redirect_target=target)
                    self.assertEqual(len(calls), 1, 'a redirect must not send a second request, body, or auth header')
                    self.assertEqual(calls[0]['url'], approved)
                    self.assertIsNotNone(error, 'redirect should become a local-candidate fallback, not auto-follow')
                    self.assertIn(str(status), str(error))

    def test_non_redirect_uses_one_exact_json_post_and_expected_header(self):
        calls, body, error, payload, approved = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['url'], approved)
        self.assertEqual(calls[0]['method'], 'POST')
        self.assertEqual(calls[0]['body'], json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        self.assertEqual(dict((key.lower(), value) for key, value in calls[0]['headers'].items())['authorization'],
                         'Bearer DUMMY-SYNTHETIC-REDIRECT-AUTH')
        self.assertEqual(json.loads(body)['suggestions'], [])


if __name__ == "__main__":
    unittest.main()
