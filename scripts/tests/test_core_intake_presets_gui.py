# -*- coding: utf-8 -*-
"""CORE R5 界面入口补测：预设命令与向导预填。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class IntakePresetGuiEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("r5-gui")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def setUp(self):
        from doc_tool.application.intake_presets import IntakePresets

        self.presets = IntakePresets()
        existing = self.presets.find("R5-界面预设")
        if existing is not None:
            self.presets.delete(existing.presetId)
        self.presets.save("R5-界面预设", {"Heading1": 1}, style_names={"Heading1": "heading 1"})
        self._recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        self._recent.start()

    def tearDown(self):
        self._recent.stop()
        found = self.presets.find("R5-界面预设")
        if found is not None:
            self.presets.delete(found.presetId)

    def _window(self):
        from doc_tool.ui.main_window import MainWindow

        return MainWindow()

    def test_command_lists_and_stores_pending_preset(self):
        window = self._window()
        try:
            window._reset_command_registry()
            registry = window._ensure_command_registry()
            ids = [spec.commandId for spec in registry.commands()]
            self.assertIn("intake.presets", ids, ids)
            result = registry.invoke(
                "intake.presets", window._command_context(), {"applyPreset": "R5-界面预设"},
            )
            self.assertTrue(result.ok, getattr(result, "message", ""))
            names = [row["name"] for row in result.value["presets"]]
            self.assertIn("R5-界面预设", names)
            self.assertEqual(result.value["applied"], "R5-界面预设")
            self.assertEqual(window._pending_intake_preset, "R5-界面预设")
        finally:
            window.close()

    def test_unknown_preset_raises_clear_error(self):
        window = self._window()
        try:
            registry = window._ensure_command_registry()
            result = registry.invoke(
                "intake.presets", window._command_context(), {"applyPreset": "不存在的预设"},
            )
            self.assertFalse(result.ok)
            self.assertIn("未找到导入预设", str(getattr(result, "message", "")))
        finally:
            window.close()

    def test_wizard_receives_pending_preset(self):
        window = self._window()
        try:
            window._pending_intake_preset = "R5-界面预设"
            captured = {}

            class _FakeWizard:
                def __init__(self, *args, **kwargs):
                    self._intake_preset_name = ""
                    captured["instance"] = self

                def run(self):
                    return None

            with patch("doc_tool.ui.wizard.ImportWizard", _FakeWizard):
                window._on_new_project()
            self.assertEqual(captured["instance"]._intake_preset_name, "R5-界面预设")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)