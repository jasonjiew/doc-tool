# -*- coding: utf-8 -*-
"""V3.2 3.2/5.3 测试：交付包与选择归档复用 V2.9 集合包装与登记。"""

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
from doc_tool.application.delivery import collection_bridge  # noqa: E402
from doc_tool.application.delivery.result_index import (  # noqa: E402
    ARCHIVE_MANIFEST_NAME, archive_selection, build_result_index,
)
from doc_tool.application.delivery.snapshot_package import (  # noqa: E402
    PACKAGE_MANIFEST_NAME, build_delivery_package, read_delivery_package,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402


class CollectionBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("collection-bridge")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_bridge_builds_manifest_registers_and_exports_safe_zip(self):
        outcome = collection_bridge.bridge_directory(
            self.project, register=True, zip_target=self.work / "proj.zip",
        )
        self.assertTrue(outcome.ok, outcome.message)
        self.assertGreater(outcome.fileCount, 0)
        self.assertTrue(outcome.categories)
        self.assertTrue(outcome.complete)
        self.assertTrue(outcome.registrationPath, outcome.warnings)
        self.assertTrue(Path(outcome.registrationPath).is_file(), "集合登记应落盘（含 rename 回退）")
        self.assertTrue(Path(outcome.zipPath).is_file())
        with zipfile.ZipFile(outcome.zipPath) as archive:
            names = archive.namelist()
        self.assertFalse(any(".git" in name for name in names))
        self.assertFalse(any(name.endswith(".tmp") for name in names))
        self.assertTrue(any(name.startswith("content/") for name in names))

    def test_bridge_skips_git_and_caches(self):
        cache_dir = self.project / ".git"
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / "config").write_text("secret", encoding="utf-8")
        (self.project / "__pycache__").mkdir(exist_ok=True)
        (self.project / "__pycache__" / "x.pyc").write_bytes(b"cache")
        outcome = collection_bridge.bridge_directory(self.project)
        manifest = collection_bridge.collection_manifest_for(self.project)[0]
        rels = [str(item.relative_path) for item in manifest.files]
        self.assertFalse(any(rel.startswith(".git") for rel in rels))
        self.assertFalse(any("__pycache__" in rel for rel in rels))
        self.assertTrue(outcome.fileCount)


class DeliveryPackageCollectionTests(unittest.TestCase):
    """3.2：交付包内容索引复用集合格式。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("pkg-collection")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        cls.report = run_project_export(
            ExportRequest(
                project_root=str(cls.project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(cls.work / "out"),
            ),
            skip_word_refresh=True,
        )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_directory_package_contains_collection_manifest(self):
        target = self.work / "pkg-dir"
        outcome = build_delivery_package(self.report, target=target)
        self.assertTrue(outcome.ok, outcome.message)
        manifest = json.loads((target / PACKAGE_MANIFEST_NAME).read_text(encoding="utf-8"))
        collection = manifest.get("collection") or {}
        self.assertGreater(collection.get("fileCount", 0), 0, collection)
        self.assertTrue(collection.get("categories"))
        self.assertTrue((target / "collection-manifest.yml").is_file())
        # 包内路径全相对且不含 Git/凭据
        rels = [str(item.get("path") or "") for item in manifest.get("files") or []]
        self.assertFalse(any(rel.startswith("/") or ".." in rel.split("/") for rel in rels))

    def test_zip_package_includes_collection_manifest(self):
        target = self.work / "pkg.zip"
        outcome = build_delivery_package(self.report, target=target)
        self.assertTrue(outcome.ok, outcome.message)
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            data = json.loads(archive.read(PACKAGE_MANIFEST_NAME).decode("utf-8"))
        self.assertIn("collection-manifest.yml", names)
        self.assertTrue((data.get("collection") or {}).get("fileCount", 0) > 0)


class ArchiveSelectionRegistrationTests(unittest.TestCase):
    """5.3：选择归档 + 完整集合登记复用 V2.9，部分范围明确。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("archive-selection")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        report = run_project_export(
            ExportRequest(
                project_root=str(cls.project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(cls.work / "out"),
            ),
            skip_word_refresh=True,
        )
        cls.index = build_result_index([report.indexPath])

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_complete_selection_registers_collection(self):
        outcome = archive_selection(self.index, self.work / "complete.zip")
        self.assertTrue(outcome.ok, outcome.message)
        self.assertFalse(outcome.partial)
        collection = (outcome.manifest or {}).get("collection") or {}
        self.assertTrue(collection.get("complete"), collection)
        self.assertTrue(collection.get("registrationPath"), outcome.message)
        self.assertIn("完整集合", outcome.message)
        with zipfile.ZipFile(outcome.path) as archive:
            manifest = json.loads(archive.read(ARCHIVE_MANIFEST_NAME).decode("utf-8"))
        self.assertIn("collection", manifest)

    def test_partial_selection_is_marked_and_not_registered_as_complete(self):
        keys = [entry.key() for entry in self.index.usable_entries()]
        self.assertGreaterEqual(len(keys), 2, keys)
        outcome = archive_selection(self.index, self.work / "partial.zip", selection=[keys[0]])
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(outcome.partial)
        self.assertTrue(outcome.omitted)
        collection = (outcome.manifest or {}).get("collection") or {}
        self.assertFalse(collection.get("complete", False))
        self.assertIn("部分范围", outcome.message)
        lines = "\n".join(outcome.summary_lines())
        self.assertIn("部分范围", lines)

    def test_missing_paths_are_listed(self):
        broken = type(self.index)(sources=[])
        outcome = archive_selection(broken, self.work / "empty.zip")
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)