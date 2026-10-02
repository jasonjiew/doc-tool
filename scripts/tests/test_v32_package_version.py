# -*- coding: utf-8 -*-
"""V3.2 3.4/3.5 测试：包版本不符回退阅读/导出，以及旧包/同名/非法附件场景。"""

from __future__ import annotations

import json
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery import package_version  # noqa: E402
from doc_tool.application.delivery.snapshot_package import (  # noqa: E402
    PACKAGE_MANIFEST_NAME, build_delivery_package, formalize_package,
    read_delivery_package, verify_delivery_package,
)


class PackageVersionFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("pkg-version")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        cls.package = cls.work / "pkg"
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, SOURCE_MODE_SAVED, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        report = run_project_export(
            ExportRequest(
                project_root=str(cls.project), formats=[FORMAT_DOCX],
                source_mode=SOURCE_MODE_SAVED, destination=str(cls.work / "out"),
            ),
            skip_word_refresh=True,
        )
        cls.report = report
        outcome = build_delivery_package(report, target=cls.package)
        assert getattr(outcome, "ok", False), getattr(outcome, "message", outcome)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _variant_package(self, version: int, name: str) -> Path:
        """复制包并把清单的 schemaVersion 改成给定版本。"""
        import shutil

        target = self.work / name
        shutil.copytree(str(self.package), str(target))
        manifest_file = target / PACKAGE_MANIFEST_NAME
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        data["schemaVersion"] = version
        manifest_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def test_same_version_package_verifies_normally(self):
        self.assertIsNotNone(read_delivery_package(self.package))
        check = verify_delivery_package(self.package)
        self.assertTrue(check.ok, check.problems)
        self.assertFalse(check.readableOnly)
        fallback = package_version.version_fallback(self.package)
        self.assertFalse(fallback.readableOnly)

    def test_newer_version_falls_back_to_readable_only(self):
        package = self._variant_package(99, "pkg-v99")
        self.assertIsNone(
            read_delivery_package(package), "严格读取仍只接受当前 schema 版本",
        )
        fallback = package_version.version_fallback(package)
        self.assertTrue(fallback.readableOnly)
        self.assertIn("高于当前支持", fallback.reason)
        check = verify_delivery_package(package)
        self.assertTrue(check.ok, "版本不符应回退为可读/可导出而不是不可用")
        self.assertTrue(check.readableOnly)
        self.assertIn("回退", check.versionNote)
        artifacts = package_version.readable_artifacts(package)
        self.assertTrue(any(str(item["path"]).lower().endswith(".docx") for item in artifacts))
        # 可读产物确实存在且可打开
        docx = [item for item in artifacts if str(item["path"]).lower().endswith(".docx")][0]
        self.assertTrue((package / str(docx["path"])).is_file())

    def test_older_version_is_readable_but_formalize_refused(self):
        package = self._variant_package(0, "pkg-v0")
        check = verify_delivery_package(package)
        self.assertTrue(check.ok)
        self.assertTrue(check.readableOnly)
        outcome = formalize_package(package)
        self.assertNotEqual(outcome.status, "completed")
        self.assertEqual(outcome.status, "readable-only")
        self.assertTrue(outcome.message)
        self.assertTrue(outcome.warnings)

    def test_unrelated_kind_is_not_treated_as_fallback(self):
        broken = self.work / "broken"
        broken.mkdir(exist_ok=True)
        (broken / PACKAGE_MANIFEST_NAME).write_text(
            json.dumps({"schemaVersion": 3, "kind": "something-else", "files": []}),
            encoding="utf-8",
        )
        fallback = package_version.version_fallback(broken)
        self.assertFalse(fallback.readableOnly)
        check = verify_delivery_package(broken)
        self.assertFalse(check.ok)


class LegacyAndSafetyScenarioTests(unittest.TestCase):
    """3.5：旧包、同名资源、非法附件与离线（无网络）场景。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("pkg-safety")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_package_excludes_network_and_credentials(self):
        target = self.work / "safe-package"
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        report = run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "safe-out"),
            ),
            skip_word_refresh=True,
        )
        outcome = build_delivery_package(report, target=target)
        self.assertTrue(getattr(outcome, "ok", False), getattr(outcome, "message", ""))
        manifest = json.loads((target / PACKAGE_MANIFEST_NAME).read_text(encoding="utf-8"))
        rels = [str(item.get("path") or "") for item in manifest.get("files") or []]
        for rel in rels:
            self.assertFalse(rel.startswith("/") or ":" in rel.split("/")[0], rel)
            self.assertNotIn("..", rel.split("/"))
            self.assertNotIn(".git", rel)
        # 包内没有凭据/用户配置文件
        for forbidden in ("user.yml", "credentials.json", "token.json", "recent.json"):
            self.assertFalse(any(Path(rel).name == forbidden for rel in rels), forbidden)

    def test_zip_package_with_illegal_member_is_rejected(self):
        target = self.work / "illegal.zip"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr(PACKAGE_MANIFEST_NAME, json.dumps({
                "schemaVersion": 1, "kind": "doc-tool-delivery-package",
                "files": [{"path": "../escape.docx", "role": "output"}],
            }))
        check = verify_delivery_package(target)
        self.assertFalse(check.ok, "越界成员必须判为不可用")
        self.assertTrue(check.problems)

    def test_broken_zip_is_reported_not_raising(self):
        target = self.work / "broken.zip"
        target.write_bytes(b"not-a-zip")
        check = verify_delivery_package(target)
        self.assertFalse(check.ok)
        self.assertTrue(check.problems)
        fallback = package_version.version_fallback(target)
        self.assertFalse(fallback.readableOnly)


if __name__ == "__main__":
    unittest.main(verbosity=2)