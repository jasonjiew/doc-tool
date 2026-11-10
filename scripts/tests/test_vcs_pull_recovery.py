# -*- coding: utf-8 -*-
"""git pull 失败恢复：无上游分支、分叉、凭据三类可读原因。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.vcs_changes import (  # noqa: E402
    ChangeReport,
    pull_changes,
)


def _done(args, code=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


class PullRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.report = ChangeReport(
            source="git", repository_root=str(self.root), project_root=str(self.root)
        )

    def test_no_upstream_retries_with_explicit_origin_and_branch(self) -> None:
        calls = []

        def runner(args, cwd):
            calls.append(list(args))
            command = args[1] if len(args) > 1 else ""
            rest = args[2:]
            if command == "rev-parse" and rest == ["HEAD"]:
                return _done(args, 0, b"aaa\n")
            if command == "rev-parse" and rest == ["--abbrev-ref", "HEAD"]:
                return _done(args, 0, b"main\n")
            if command == "pull" and rest == []:
                return _done(args, 1, b"", b"fatal: no upstream configured\n")
            if command == "pull" and rest == ["origin", "main"]:
                return _done(args, 0, b"Fast-forward\n")
            return _done(args, 0, b"")

        result = pull_changes(self.report, runner=runner)
        self.assertTrue(result.ok, result.error)
        self.assertTrue(
            any(call[1:] == ["pull", "origin", "main"] for call in calls), calls
        )

    def test_diverged_branch_returns_actionable_message(self) -> None:
        def runner(args, cwd):
            command = args[1] if len(args) > 1 else ""
            rest = args[2:]
            if command == "rev-parse":
                return _done(args, 0, b"main\n")
            if command == "pull":
                return _done(
                    args,
                    1,
                    b"",
                    b"fatal: Need to specify how to reconcile divergent branches.\n",
                )
            return _done(args, 0, b"")

        result = pull_changes(self.report, runner=runner)
        self.assertFalse(result.ok)
        self.assertIn("分叉", result.error or "")

    def test_auth_failure_explains_missing_credentials(self) -> None:
        def runner(args, cwd):
            command = args[1] if len(args) > 1 else ""
            if command == "rev-parse":
                return _done(args, 0, b"main\n")
            if command == "pull":
                return _done(
                    args,
                    1,
                    b"",
                    b"fatal: could not read Username for 'https://gitlab': "
                    b"terminal prompts disabled\n",
                )
            return _done(args, 0, b"")

        result = pull_changes(self.report, runner=runner)
        self.assertFalse(result.ok)
        self.assertIn("凭据", result.error or "")

    def test_no_upstream_without_branch_still_reports_upstream_hint(self) -> None:
        def runner(args, cwd):
            command = args[1] if len(args) > 1 else ""
            rest = args[2:]
            if command == "pull":
                return _done(args, 1, b"", b"fatal: no tracking information\n")
            if command == "rev-parse" and rest == ["HEAD"]:
                return _done(args, 0, b"aaa\n")
            return _done(args, 1, b"", b"fatal: not a branch\n")

        result = pull_changes(self.report, runner=runner)
        self.assertFalse(result.ok)
        self.assertIn("上游", result.error or "")


if __name__ == "__main__":
    unittest.main()
