# -*- coding: utf-8 -*-
"""CORE R5 补测：命名导入映射预设的服务/CLI 生产入口。"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class IntakePresetServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("r5-presets")
        cls.source = fixtures.build_docx(
            cls.work / "s.docx",
            [("h1", "第1章 引言"), ("h2", "1.1 目的"), ("p", "正文。")],
        )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _cleanup_preset(self, name: str) -> None:
        from doc_tool.application.intake_presets import IntakePresets

        presets = IntakePresets()
        preset = presets.find(name)
        if preset is not None:
            presets.delete(preset.presetId)

    def test_save_then_apply_preset(self):
        from doc_tool.application.intake_entries import run_intake
        from doc_tool.application.intake_presets import IntakePresets

        name = "R5-服务预设"
        self._cleanup_preset(name)
        try:
            saved = run_intake(
                self.source, parent_dir=self.work / "a", target_name="p1", save_preset=name,
            )
            self.assertTrue(saved.ok, saved.errors)
            self.assertEqual(saved.saved_preset, name, saved.warnings)
            self.assertTrue(any("已保存导入预设" in item for item in saved.warnings), saved.warnings)
            stored = IntakePresets().find(name)
            self.assertIsNotNone(stored, "保存后应能在预设表中找到")
            self.assertTrue(stored.mapping, stored)

            applied = run_intake(
                self.source, parent_dir=self.work / "b", target_name="p2", preset_name=name,
            )
            self.assertTrue(applied.ok, applied.errors)
            self.assertEqual(applied.preset.get("name"), name, applied.preset)
            self.assertTrue(applied.preset.get("mapping"), applied.preset)
            self.assertTrue(
                any("已应用导入预设" in item for item in applied.warnings), applied.warnings
            )
        finally:
            self._cleanup_preset(name)

    def test_unknown_preset_warns_and_continues(self):
        from doc_tool.application.intake_entries import run_intake

        outcome = run_intake(
            self.source, parent_dir=self.work / "c", target_name="p3",
            preset_name="绝不存在的预设名",
        )
        self.assertTrue(outcome.ok, outcome.errors)
        self.assertTrue(
            any("未找到导入预设" in item for item in outcome.warnings), outcome.warnings
        )
        self.assertEqual(outcome.preset, {})

    def test_import_request_carries_preset_fields(self):
        from doc_tool.application.import_project import ImportRequest, import_first_time
        from doc_tool.application.intake_presets import IntakePresets

        presets = IntakePresets()
        existing = presets.find("R5-请求预设")
        if existing is not None:
            presets.delete(existing.presetId)
        try:
            request = ImportRequest(
                source_docx=self.source,
                target_project_root=self.work / "d" / "proj",
                document_type="general", document_no="", document_name="预设项目",
                document_version="1.0",
                intakeSavePreset="R5-请求预设",
            )
            result = import_first_time(request)
            self.assertTrue(result.success, [event.detail for event in result.events])
            self.assertEqual(result.savedPreset, "R5-请求预设", result.warnings)
            self.assertTrue(any("已保存导入预设" in item for item in result.warnings))
        finally:
            found = IntakePresets().find("R5-请求预设")
            if found is not None:
                IntakePresets().delete(found.presetId)


class IntakePresetCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("r5-presets-cli")
        cls.source = fixtures.build_docx(
            cls.work / "s.docx", [("h1", "第1章 引言"), ("p", "正文。")],
        )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "doc_tool.cli", *args],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )

    def test_cli_save_list_show_and_delete(self):
        name = "R5-CLI预设"
        proc = self._cli(
            "import", "--docx", str(self.source), "--name", "CliProj",
            "--target-dir", str(self.work / "out"), "--save-preset", name, "--output", "json",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        payload = json.loads(proc.stdout[proc.stdout.find("{"):])
        item = payload["results"][0]
        self.assertEqual(item["data"]["savedPreset"], name, item["data"].get("presetWarnings"))
        self.assertTrue(
            any("已保存导入预设" in str(text) for text in item["data"]["presetWarnings"]),
            item["data"]["presetWarnings"],
        )

        listing = self._cli("intake-presets", "list")
        self.assertEqual(listing.returncode, 0, listing.stderr[-200:])
        self.assertIn(name, listing.stdout)

        shown = self._cli("intake-presets", "show", name)
        self.assertEqual(shown.returncode, 0, shown.stderr[-200:])
        self.assertIn("Heading1", shown.stdout)

        deleted = self._cli("intake-presets", "delete", name)
        self.assertEqual(deleted.returncode, 0, deleted.stderr[-200:])
        missing = self._cli("intake-presets", "show", name)
        self.assertEqual(missing.returncode, 2, missing.stdout)

    def test_cli_import_applies_preset(self):
        name = "R5-CLI应用预设"
        saved = self._cli(
            "import", "--docx", str(self.source), "--name", "ApplyBase",
            "--target-dir", str(self.work / "out2"), "--save-preset", name, "--output", "json",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr[-200:])
        applied = self._cli(
            "import", "--docx", str(self.source), "--name", "ApplyUse",
            "--target-dir", str(self.work / "out3"), "--preset", name, "--output", "json",
        )
        self.assertEqual(applied.returncode, 0, applied.stderr[-300:])
        payload = json.loads(applied.stdout[applied.stdout.find("{"):])
        data = payload["results"][0]["data"]
        self.assertEqual(data["preset"].get("name"), name, data.get("preset"))
        self.assertTrue(data["preset"].get("mapping"), data.get("preset"))
        self.assertTrue(
            any("已应用导入预设" in str(text) for text in data["presetWarnings"]),
            data["presetWarnings"],
        )
        self._cli("intake-presets", "delete", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)