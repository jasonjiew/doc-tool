# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET

from doc_tool.application.cli_commands import CommandResult, ProjectCommandResult
from doc_tool.application.issues import IssueRecord
from doc_tool.cli import main
from doc_tool.cli_serializers import serialize_junit, serialize_sarif


def _issue(severity="error"):
    return IssueRecord(
        source="lint", issue_type="todo_residual", document_type="requirement",
        severity=severity, rel_path="chapter.md", line_no=3, error_code="E2002",
        message="待办残留", suggested_action="修正", generated_at="2026-08-12T00:00:00+00:00",
    )


class MachineCliTests(unittest.TestCase):
    def test_json_schema_and_stdout_is_single_document(self):
        result = CommandResult("status", [ProjectCommandResult("p", True, data={"ok": True})])
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("doc_tool.application.cli_commands.status_command", return_value=result), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["status", "--project", ".", "--output", "json"])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(set(data), {"schemaVersion", "command", "success", "errorCode", "results"})
        self.assertEqual(data["command"], "status")

    def test_sarif_and_junit_are_parseable(self):
        result = CommandResult("validate", [
            ProjectCommandResult(".", False, "E2002", issues=[_issue()]),
        ])
        sarif = json.loads(serialize_sarif(result))
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"], 3)
        junit = ET.fromstring(serialize_junit(result))
        self.assertEqual(junit.attrib["failures"], "1")
        self.assertIsNotNone(junit.find("./testsuite/testcase/failure"))

    def test_batch_partial_success_exit_code(self):
        result = CommandResult("status", [
            ProjectCommandResult("a", True), ProjectCommandResult("b", False, "E4003"),
        ])
        self.assertEqual(result.exit_code, 3)

    def test_invalid_arguments_exit_two_and_usage_on_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            main(["validate"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("usage:", err.getvalue().lower())

    def test_real_status_search_and_lint_commands(self):
        from doc_tool.domain.manifest import ProjectManifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content" / "requirement"
            content.mkdir(parents=True)
            (content / "1.1 intro.md").write_text("# 标题\nTODO KSHC\n", encoding="utf-8")
            manifest = ProjectManifest(
                documentType="requirement", documentNo="REQ-1", documentName="测试",
                documentVersion="1.0", sourceSha256="x",
                paths={"contentRoot": "content/requirement"},
            )
            manifest.save(root, backup=False)
            for argv in (
                ["status", "--project", str(root), "--output", "json"],
                ["search", "--project", str(root), "--query", "TODO", "--output", "json"],
                ["lint", "--project", str(root), "--format", "sarif"],
            ):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    code = main(argv)
                self.assertIn(code, (0, 1))
                json.loads(out.getvalue())


if __name__ == "__main__":
    unittest.main()
