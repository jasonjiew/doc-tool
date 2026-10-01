# -*- coding: utf-8 -*-
"""V2.8 28-A：schema v2 字段、迁移预览、备份与只读边界（1.1～1.4）。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.migrate_schema_v2 import (  # noqa: E402
    build_upgrade_dict,
    migrate_project,
    preview_upgrade,
)
from doc_tool.domain.errors import IncompatibleSchemaError, ProjectManifestError  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.version import PROJECT_SCHEMA_VERSION  # noqa: E402


def _v1_manifest(root: Path) -> ProjectManifest:
    manifest = ProjectManifest(
        documentType="general",
        documentNo="GX-V28-001",
        documentName="v28 迁移样本",
        documentVersion="1.0",
        sourceSha256="",
        schemaVersion=1,
        paths={
            "templateDocx": "template/template.docx",
            "contentRoot": "content",
            "assetRoot": "assets",
            "tableRoot": "assets/tables",
        },
        headingStyles={1: "1", 2: "2"},
        bodyStyle="a",
    )
    (root / "template").mkdir(parents=True, exist_ok=True)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "tables").mkdir(parents=True, exist_ok=True)
    manifest.save(root)
    return ProjectManifest.load(root)


class V2FieldTests(unittest.TestCase):
    """1.1：v2 字段定义与容错。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-schema-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_v2_fields_roundtrip(self):
        manifest = _v1_manifest(self.tmp)
        manifest.schemaVersion = 2
        manifest.documentKind = "requirement"
        manifest.chapters = ["1 概述", "2 设计"]
        manifest.variables = {"productName": "示例产品"}
        manifest.standardPack = {"id": "generic-requirement", "version": "1.0.0", "hash": "abc"}
        manifest.qualitySource = "pack"
        manifest.save(self.tmp)
        loaded = ProjectManifest.load(self.tmp)
        self.assertEqual(loaded.schemaVersion, 2)
        self.assertEqual(loaded.documentKind, "requirement")
        self.assertEqual(loaded.chapters, ["1 概述", "2 设计"])
        self.assertEqual(loaded.variables["productName"], "示例产品")
        self.assertEqual(loaded.standardPack["id"], "generic-requirement")
        self.assertEqual(loaded.qualitySource, "pack")

    def test_v1_manifest_stays_v1_and_stays_writable(self):
        manifest = _v1_manifest(self.tmp)
        self.assertEqual(manifest.schemaVersion, 1)
        self.assertTrue(manifest.is_writable())
        self.assertTrue(PROJECT_SCHEMA_VERSION >= 2)

    def test_illegal_chapter_entries_skipped_with_warnings(self):
        manifest = _v1_manifest(self.tmp)
        manifest.schemaVersion = 2
        manifest.chapters = ["1 概述", "1 概述", "", "../越界", "/abs"]
        manifest.save(self.tmp)
        loaded = ProjectManifest.load(self.tmp)
        self.assertEqual(loaded.chapters, ["1 概述"])
        warnings = getattr(loaded, "chapterWarnings", [])
        self.assertTrue(any("重复" in item for item in warnings))
        self.assertTrue(any("越界" in item for item in warnings))

    def test_unknown_schema_readonly_and_save_rejected(self):
        """更高模式版本：可只读加载，但拒绝写入。"""
        import yaml

        data = {
            "schemaVersion": 99,
            "documentType": "general",
            "documentNo": "GX",
            "documentName": "future",
            "documentVersion": "1",
            "sourceSha256": "",
        }
        (self.tmp / "project.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
        loaded = ProjectManifest.load(self.tmp)
        self.assertEqual(loaded.schemaVersion, 99)
        self.assertFalse(loaded.is_writable())
        with self.assertRaises(IncompatibleSchemaError):
            loaded.save(self.tmp)

    def test_manifest_without_schema_version_is_rejected(self):
        import yaml

        data = {"documentType": "general", "documentName": "x"}
        (self.tmp / "project.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
        with self.assertRaises(ProjectManifestError):
            ProjectManifest.load(self.tmp)


class MigrationTests(unittest.TestCase):
    """1.2/1.3：预览、备份、原子提交与失败保留。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-migrate-"))
        self.manifest = _v1_manifest(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preview_does_not_write(self):
        before = (self.tmp / "project.yml").read_text(encoding="utf-8")
        result = migrate_project(self.tmp, apply=False)
        self.assertTrue(result.success)
        # 升级本身就是 schemaVersion 变化，因此预览必须报告该字段变更。
        self.assertTrue(result.preview.has_changes)
        changed_keys = [key for key, _b, _a in result.preview.changed]
        self.assertIn("schemaVersion", changed_keys)
        self.assertEqual(result.from_schema, 1)
        self.assertEqual(result.to_schema, 2)
        self.assertEqual((self.tmp / "project.yml").read_text(encoding="utf-8"), before)
        self.assertIn("模式版本", result.preview.markdown_text())

    def test_default_keeps_v1_until_applied(self):
        migrate_project(self.tmp)
        self.assertEqual(ProjectManifest.load(self.tmp).schemaVersion, 1)

    def test_apply_writes_v2_with_backup_and_log(self):
        result = migrate_project(self.tmp, apply=True)
        self.assertTrue(result.success, result.message)
        loaded = ProjectManifest.load(self.tmp)
        self.assertEqual(loaded.schemaVersion, 2)
        self.assertTrue(Path(result.backup_path).is_file())
        self.assertTrue(Path(result.log_path).is_file())
        backup_text = Path(result.backup_path).read_text(encoding="utf-8")
        self.assertIn("schemaVersion: 1", backup_text)
        # 升级不改变文档表达
        self.assertEqual(loaded.documentName, self.manifest.documentName)
        self.assertEqual(loaded.documentVersion, self.manifest.documentVersion)
        self.assertEqual(loaded.headingStyles, self.manifest.headingStyles)

    def test_apply_is_idempotent(self):
        first = migrate_project(self.tmp, apply=True)
        second = migrate_project(self.tmp, apply=True)
        self.assertTrue(second.success)
        self.assertIn("无需升级", second.message)
        self.assertEqual(first.to_schema, second.to_schema)

    def test_staging_failure_keeps_original_manifest(self):
        from unittest import mock

        original = (self.tmp / "project.yml").read_text(encoding="utf-8")
        # 注入失败发生在「站点文件已写、尚未替换正式清单」之后。
        real_from_dict = ProjectManifest.from_dict
        calls = {"count": 0}

        def _failing_on_second_call(data, project_root=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_from_dict(data, project_root)
            raise ProjectManifestError("注入失败")

        with mock.patch(
            "doc_tool.application.migrate_schema_v2.ProjectManifest.from_dict",
            side_effect=_failing_on_second_call,
        ):
            result = migrate_project(self.tmp, apply=True)
        self.assertFalse(result.success)
        self.assertIn("升级失败", result.message)
        self.assertEqual((self.tmp / "project.yml").read_text(encoding="utf-8"), original)
        self.assertTrue(Path(result.preserved_edit_path).is_file())

    def test_upgrade_dict_has_no_absolute_template_path(self):
        data = build_upgrade_dict(self.manifest)
        self.assertEqual(data["schemaVersion"], 2)
        for value in (data.get("paths") or {}).values():
            self.assertFalse(str(value).startswith("/"))
            self.assertNotIn(":", str(value))

    def test_preview_reports_added_fields_when_present(self):
        manifest = ProjectManifest.load(self.tmp)
        manifest.schemaVersion = 1
        manifest.chapters = ["1 概述"]
        preview = preview_upgrade(manifest)
        self.assertTrue(preview.has_changes)
        keys = [key for key, _value in preview.added] + [
            key for key, _b, _a in preview.changed
        ]
        self.assertIn("schemaVersion", keys)


if __name__ == "__main__":
    unittest.main()