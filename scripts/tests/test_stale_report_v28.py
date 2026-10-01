# -*- coding: utf-8 -*-
"""V2.8 4.4：检查报告过期判定与只读边界（服务层）。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_project_build as T  # noqa: E402
from doc_tool.application.content.lint import TermStore  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRule, QualityRulesConfig  # noqa: E402
from doc_tool.application.overview import build_overview, check_report_is_stale  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

NL = chr(10)


class StaleReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-stale-"))
        self.root = Path(T._setup_project(str(self.tmp)))
        T._make_manifest(str(self.root)).save(str(self.root))
        self.logs = self.root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.report = self.logs / "general-validation.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_report(self):
        self.report.write_text("# report" + NL, encoding="utf-8")

    def test_missing_report_counts_as_stale(self):
        self.assertTrue(check_report_is_stale(self.root))

    def test_report_newer_than_sources_is_fresh(self):
        self._write_report()
        time.sleep(0.01)
        self.assertFalse(check_report_is_stale(self.root))

    def test_content_change_marks_stale(self):
        self._write_report()
        chapter = next((self.root / "content").rglob("*.md"))
        time.sleep(0.01)
        chapter.write_text(chapter.read_text(encoding="utf-8") + NL + "新增" + NL, encoding="utf-8")
        self.assertTrue(check_report_is_stale(self.root))

    def test_quality_config_change_marks_stale(self):
        """V2.8 4.4：配置修改后旧检查报告必须过期。"""
        self._write_report()
        quality = self.root / "quality"
        quality.mkdir(parents=True, exist_ok=True)
        time.sleep(0.01)
        (quality / "rules.json").write_text(json.dumps({"rules": []}), encoding="utf-8")
        self.assertTrue(check_report_is_stale(self.root))

    def test_legacy_terms_change_marks_stale(self):
        self._write_report()
        state = self.root / ".state"
        state.mkdir(parents=True, exist_ok=True)
        time.sleep(0.01)
        (state / "terms.json").write_text("[]", encoding="utf-8")
        self.assertTrue(check_report_is_stale(self.root))

    def test_relations_change_marks_stale(self):
        self._write_report()
        time.sleep(0.01)
        (self.root / "relations.yml").write_text("schemaVersion: 1" + NL + "relations: []" + NL, encoding="utf-8")
        self.assertTrue(check_report_is_stale(self.root))

    def test_explicit_report_path_honored(self):
        other = self.logs / "custom-report.md"
        other.write_text("# custom" + NL, encoding="utf-8")
        self.assertFalse(check_report_is_stale(self.root, report_path=other))
        self.assertTrue(check_report_is_stale(self.root, report_path=self.logs / "missing.md"))

    def test_overview_agrees_with_stale_helper(self):
        self._write_report()
        overview = build_overview(self.root)
        section = {item.key: item for item in overview.sections}["check"]
        self.assertEqual(section.value, "有效")
        self.assertFalse(check_report_is_stale(self.root))
        time.sleep(0.01)
        chapter = next((self.root / "content").rglob("*.md"))
        chapter.write_text("# changed" + NL, encoding="utf-8")
        self.assertTrue(check_report_is_stale(self.root))
        overview2 = build_overview(self.root)
        self.assertEqual({item.key: item for item in overview2.sections}["check"].value, "已过期")


class ReadOnlyBoundaryTests(unittest.TestCase):
    """4.4：只读项目在**服务层**禁写，不依赖界面禁用。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-ro-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_quality_rules_readonly_refuses_save(self):
        config = QualityRulesConfig(self.tmp / ".state", "general", writable=False)
        with self.assertRaises(PermissionError):
            config.save([QualityRule("todo_residual")])

    def test_term_store_writable_flag_is_enforced_by_caller(self):
        store = TermStore(self.tmp / ".state")
        self.assertFalse(store.file.exists())
        # 术语服务本身按状态目录定位；只读约束由上层以 writable=False 传入配置实现，
        # 这里断言路径不会越出状态目录。
        self.assertTrue(str(store.file).startswith(str(self.tmp)))

    def test_manifest_readonly_schema_refuses_save(self):
        from doc_tool.domain.errors import IncompatibleSchemaError

        root = self.tmp / "future"
        root.mkdir()
        import yaml

        (root / "project.yml").write_text(
            yaml.safe_dump(
                {
                    "schemaVersion": 99,
                    "documentType": "general",
                    "documentNo": "X",
                    "documentName": "future",
                    "documentVersion": "1",
                    "sourceSha256": "",
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        manifest = ProjectManifest.load(root)
        self.assertFalse(manifest.is_writable())
        with self.assertRaises(IncompatibleSchemaError):
            manifest.save(root)

    def test_relations_readonly_refuses_write(self):
        from doc_tool.application.content.relations import RelationGraph, save_relations

        with self.assertRaises(PermissionError):
            save_relations(self.tmp / "relations.yml", RelationGraph(), writable=False)


if __name__ == "__main__":
    unittest.main()