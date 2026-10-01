# -*- coding: utf-8 -*-
"""V2.8 28-D：共享规则/术语位置、旧格式迁移与容错回退（4.1、4.2、4.4、4.5）。"""

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

from doc_tool.application.content.quality_rules import QualityRule, QualityRulesConfig  # noqa: E402
from doc_tool.application.quality_location import (  # noqa: E402
    MIGRATION_BACKUP_DIR,
    QUALITY_DIR,
    load_terms_with_fallback,
    migrate_legacy_quality_files,
    quality_files_state,
    resolve_quality_location,
    safe_read_json,
)


class QualityLocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-quality-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prefers_project_quality_dir(self):
        (self.tmp / QUALITY_DIR).mkdir(parents=True)
        (self.tmp / QUALITY_DIR / "rules.json").write_text("{}", encoding="utf-8")
        (self.tmp / ".state").mkdir(parents=True)
        (self.tmp / ".state" / "quality_rules.json").write_text("{}", encoding="utf-8")
        location = resolve_quality_location(self.tmp, "rules.json", legacy_name="quality_rules.json")
        self.assertEqual(location.source, "project")
        self.assertIn(QUALITY_DIR, location.path.as_posix())

    def test_falls_back_to_legacy_state(self):
        (self.tmp / ".state").mkdir(parents=True)
        (self.tmp / ".state" / "quality_rules.json").write_text("{}", encoding="utf-8")
        location = resolve_quality_location(self.tmp, "rules.json", legacy_name="quality_rules.json")
        self.assertEqual(location.source, "legacy")
        self.assertTrue(location.exists)

    def test_none_when_absent(self):
        location = resolve_quality_location(self.tmp, "rules.json", legacy_name="quality_rules.json")
        self.assertEqual(location.source, "none")
        self.assertFalse(location.exists)

    def test_migration_creates_backup_and_does_not_overwrite(self):
        (self.tmp / ".state").mkdir(parents=True)
        legacy = self.tmp / ".state" / "quality_rules.json"
        legacy.write_text(json.dumps({"rules": []}), encoding="utf-8")
        moved = migrate_legacy_quality_files(self.tmp)
        self.assertEqual(len(moved), 1)
        backup = Path(moved[0][1])
        self.assertTrue(backup.is_file())
        self.assertIn(MIGRATION_BACKUP_DIR.replace("/", "\\"), str(backup))
        self.assertTrue((self.tmp / QUALITY_DIR / "rules.json").is_file())
        # 新位置已存在时再次迁移不覆盖
        before = (self.tmp / QUALITY_DIR / "rules.json").read_text(encoding="utf-8")
        (self.tmp / QUALITY_DIR / "rules.json").write_text(
            json.dumps({"rules": [], "shared": True}), encoding="utf-8"
        )
        migrate_legacy_quality_files(self.tmp)
        self.assertIn("shared", (self.tmp / QUALITY_DIR / "rules.json").read_text(encoding="utf-8"))
        self.assertNotEqual(before, "")

    def test_state_summary_reports_migration_need(self):
        (self.tmp / ".state").mkdir(parents=True)
        (self.tmp / ".state" / "terms.json").write_text("[]", encoding="utf-8")
        state = quality_files_state(self.tmp)
        self.assertTrue(state["needsMigration"])
        self.assertEqual(state["terms"]["source"], "legacy")


class SafeReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-safe-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_corrupt_json_returns_reason_not_raise(self):
        target = self.tmp / "broken.json"
        target.write_text("{ not json", encoding="utf-8")
        data, error = safe_read_json(target)
        self.assertIsNone(data)
        self.assertIn("损坏", error or "")

    def test_missing_file_reports_missing(self):
        data, error = safe_read_json(self.tmp / "nope.json")
        self.assertIsNone(data)
        self.assertIn("不存在", error or "")


class TermsFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-terms-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, payload: str, name: str = "terms.json") -> None:
        (self.tmp / QUALITY_DIR).mkdir(parents=True, exist_ok=True)
        (self.tmp / QUALITY_DIR / name).write_text(payload, encoding="utf-8")

    def test_valid_list_and_object_forms(self):
        self._write(json.dumps(["A", "B"], ensure_ascii=False))
        terms, warnings = load_terms_with_fallback(self.tmp)
        self.assertEqual(terms, ["A", "B"])
        self.assertFalse(warnings)
        self._write(json.dumps({"terms": [{"canonical": "C"}]}, ensure_ascii=False))
        terms, _ = load_terms_with_fallback(self.tmp)
        self.assertEqual(terms, ["C"])

    def test_corrupt_terms_continue_with_warning(self):
        self._write("{ broken")
        terms, warnings = load_terms_with_fallback(self.tmp)
        self.assertEqual(terms, [])
        self.assertTrue(any("回退" in item for item in warnings))

    def test_invalid_items_skipped_with_warning(self):
        self._write(json.dumps({"terms": ["A", 3, {"nope": 1}, "  "]}, ensure_ascii=False))
        terms, warnings = load_terms_with_fallback(self.tmp)
        self.assertEqual(terms, ["A"])
        self.assertTrue(any("跳过" in item for item in warnings))

    def test_missing_terms_is_silent(self):
        terms, warnings = load_terms_with_fallback(self.tmp)
        self.assertEqual(terms, [])
        self.assertFalse(warnings)


class ReadOnlyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-ro-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_readonly_config_cannot_save(self):
        config = QualityRulesConfig(self.tmp / ".state", "general", writable=False)
        with self.assertRaises(PermissionError):
            config.save([QualityRule("todo_residual")])

    def test_corrupt_rules_fall_back_to_defaults(self):
        state = self.tmp / ".state"
        state.mkdir(parents=True)
        (state / "quality_rules.json").write_text("{ broken", encoding="utf-8")
        config = QualityRulesConfig(state, "general", writable=True)
        rules = config.load()
        self.assertTrue(rules, "损坏时应回退内置默认规则")

    def test_empty_rule_list_is_respected(self):
        state = self.tmp / ".state"
        state.mkdir(parents=True)
        (state / "quality_rules.json").write_text(json.dumps({"rules": []}), encoding="utf-8")
        config = QualityRulesConfig(state, "general", writable=True)
        self.assertEqual(config.load(), [])


if __name__ == "__main__":
    unittest.main()