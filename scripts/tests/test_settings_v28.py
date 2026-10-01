# -*- coding: utf-8 -*-
"""V2.8 4.3：项目设置模型与校验保存（服务层）。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_project_build as T  # noqa: E402
from doc_tool.application.settings import (  # noqa: E402
    load_settings,
    save_settings,
)
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402


class LoadSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-settings-"))
        self.root = Path(T._setup_project(str(self.tmp)))
        manifest = T._make_manifest(str(self.root))
        manifest.headingStyles = {1: "2", 2: "3"}
        manifest.bodyStyle = "4"
        manifest.variables = {"productName": "示例"}
        manifest.save(str(self.root))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_model_has_expected_sections(self):
        model = load_settings(self.root)
        self.assertTrue(model.writable)
        self.assertIn("基本信息", model.sections)
        self.assertIn("样式", model.sections)
        self.assertIn("变量", model.sections)
        self.assertIn("术语", model.sections)
        self.assertIn("规则", model.sections)
        self.assertIn("门禁", model.sections)
        data = model.to_dict()
        self.assertIn("sections", data)
        self.assertIn("writable", data)

    def test_heading_and_body_styles_exposed(self):
        model = load_settings(self.root)
        self.assertIsNotNone(model.field("样式", "bodyStyle"))
        self.assertIsNotNone(model.field("样式", "heading1"))
        self.assertEqual(model.field("样式", "heading1").value, "2")

    def test_schema_version_read_only_field(self):
        model = load_settings(self.root)
        self.assertFalse(model.field("基本信息", "schemaVersion").editable)

    def test_variables_listed(self):
        model = load_settings(self.root)
        keys = {item.key for item in model.sections["变量"]}
        self.assertIn("productName", keys)

    def test_readonly_project_warns(self):
        manifest = ProjectManifest.load(self.root)
        manifest.schemaVersion = 99
        manifest.save = lambda *a, **k: None  # 防止真实写入
        import yaml

        data = yaml.safe_load((self.root / "project.yml").read_text(encoding="utf-8"))
        data["schemaVersion"] = 99
        (self.root / "project.yml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        model = load_settings(self.root)
        self.assertFalse(model.writable)
        self.assertTrue(model.warnings)


class SaveSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-save-"))
        self.root = Path(T._setup_project(str(self.tmp)))
        T._make_manifest(str(self.root)).save(str(self.root))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_change_is_saved(self):
        outcome = save_settings(self.root, {"documentVersion": "2.5", "qualitySource": "project"})
        self.assertTrue(outcome.ok, outcome.message)
        manifest = ProjectManifest.load(self.root)
        self.assertEqual(manifest.documentVersion, "2.5")
        self.assertEqual(manifest.qualitySource, "project")

    def test_empty_version_rejected_without_writing(self):
        before = (self.root / "project.yml").read_text(encoding="utf-8")
        outcome = save_settings(self.root, {"documentVersion": "  "})
        self.assertFalse(outcome.ok)
        self.assertIn("documentVersion", outcome.errors)
        self.assertEqual((self.root / "project.yml").read_text(encoding="utf-8"), before)

    def test_invalid_quality_source_rejected(self):
        outcome = save_settings(self.root, {"qualitySource": "bogus"})
        self.assertFalse(outcome.ok)
        self.assertIn("qualitySource", outcome.errors)

    def test_invalid_terms_type_rejected(self):
        outcome = save_settings(self.root, {"terms": [1, 2]})
        self.assertFalse(outcome.ok)
        self.assertIn("terms", outcome.errors)

    def test_terms_saved_to_quality_directory(self):
        outcome = save_settings(self.root, {"terms": ["甲", "乙"]})
        self.assertTrue(outcome.ok, outcome.message)
        target = self.root / "quality" / "terms.json"
        self.assertTrue(target.is_file())
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["terms"], ["甲", "乙"])

    def test_rules_saved_to_quality_directory(self):
        outcome = save_settings(self.root, {"rules": [{"ruleId": "todo_residual"}]})
        self.assertTrue(outcome.ok, outcome.message)
        payload = json.loads((self.root / "quality" / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["rules"][0]["ruleId"], "todo_residual")

    def test_variables_roundtrip(self):
        outcome = save_settings(self.root, {"variables": {"team": "平台组"}})
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(ProjectManifest.load(self.root).variables.get("team"), "平台组")

    def test_readonly_project_refuses_save(self):
        outcome = save_settings(self.root, {"documentVersion": "9.9"}, writable=False)
        self.assertFalse(outcome.ok)
        self.assertIn("只读", outcome.message)
        self.assertNotEqual(ProjectManifest.load(self.root).documentVersion, "9.9")

    def test_no_partial_write_on_invalid_change(self):
        quality = self.root / "quality"
        self.assertFalse(quality.exists())
        outcome = save_settings(self.root, {"terms": ["ok"], "qualitySource": "bogus"})
        self.assertFalse(outcome.ok)
        self.assertFalse(quality.exists(), "校验失败不得留下任何写入")


if __name__ == "__main__":
    unittest.main()