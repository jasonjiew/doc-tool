# -*- coding: utf-8 -*-
"""V3.1 5.1 补测：串联流程必须从 CLI 与命令注册表（应用内）可达。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class TeamFlowEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v31-flow-entry")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_cli_team_flow_exports_handoff_and_reports(self):
        handoff = self.work / "交接"
        proc = subprocess.run(
            [sys.executable, "-m", "doc_tool.cli", "team-flow",
             "--project", str(self.project), "--handoff", str(handoff), "--json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        self.assertEqual(proc.returncode, 0, (proc.stdout or "")[-400:] + (proc.stderr or "")[-400:])
        start = (proc.stdout or "").find("{")
        payload = json.loads((proc.stdout or "")[start:])
        self.assertEqual(payload.get("schemaVersion"), 1)
        self.assertTrue(payload.get("summary"), payload)
        self.assertTrue(payload.get("artifacts"), payload)
        self.assertTrue(any(Path(str(item)).exists() for item in payload["artifacts"]), payload["artifacts"])

    def test_cli_team_flow_usage_error_is_code_two(self):
        proc = subprocess.run(
            [sys.executable, "-m", "doc_tool.cli", "team-flow", "--project", str(self.work / "不存在")],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr[-200:])

    def test_registry_exposes_team_flow_command(self):
        from doc_tool.application.command_registry import CommandContext, CommandRegistry
        from doc_tool.application.content.team_entry import CMD_TEAM_FLOW, register_team_commands

        registry = register_team_commands(CommandRegistry(self.work / "cfg"), self.project)
        ids = [spec.commandId for spec in registry.commands()]
        self.assertIn(CMD_TEAM_FLOW, ids, ids)
        context = CommandContext(projectOpen=True, writable=True)
        rows = registry.palette_items(context)
        self.assertTrue(any(row["commandId"] == CMD_TEAM_FLOW for row in rows), rows)
        result = registry.invoke(CMD_TEAM_FLOW, context, {"handoffDir": str(self.work / "交接2")})
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.value.get("schemaVersion"), 1)
        self.assertTrue(result.value.get("summary"))

    def test_window_menu_and_palette_expose_team_flow(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QApplication

        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.ui.main_window import MainWindow
        from types import SimpleNamespace

        QApplication.instance() or QApplication([])
        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            window = MainWindow()
        try:
            window._project_summary = SimpleNamespace(
                project_root=self.project, is_writable=True,
                manifest=ProjectManifest.load(self.project), paths=ProjectPaths(self.project),
            )
            window._reset_command_registry()
            window._refresh_registry_menu()
            items = window._registry_palette_items()
            self.assertTrue(
                any("team.flow" == (item.payload or {}).get("commandId") for item in items),
                [item.title for item in items][:8],
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)