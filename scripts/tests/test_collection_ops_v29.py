# -*- coding: utf-8 -*-
"""V2.9 29-G\uff1a\u57fa\u7ebf\u67e5\u8be2\u3001\u6bd4\u8f83\u4e0e\u5b89\u5168\u6062\u590d\uff087.1\uff5e7.5\uff09\u3002"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.collection import (  # noqa: E402
    COLLECTIONS_DIR,
    build_manifest,
    register_manifest,
)
from doc_tool.application.collection_ops import (  # noqa: E402
    compare_baselines,
    describe_baseline,
    export_package,
    list_baselines,
    open_artifact,
    recover_baseline,
)

NL = chr(10)


def _make_delivery(root: Path, marker: str = "v1") -> None:
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "tables").mkdir(parents=True, exist_ok=True)
    (root / "standards" / "pack" / "skeleton").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "content" / "1 \u6982\u8ff0.md").write_text("# 1 \u6982\u8ff0" + NL + marker + NL, encoding="utf-8")
    (root / "assets" / "tables" / "t.csv").write_text("a,b" + NL, encoding="utf-8")
    (root / "standards" / "pack" / "pack.yml").write_text("schemaVersion: 1" + NL, encoding="utf-8")
    (root / "relations.yml").write_text("schemaVersion: 1" + NL + "relations: []" + NL, encoding="utf-8")
    (root / "output" / "\u4ea7\u7269(1.0).docx").write_bytes(b"PK\x03\x04" + marker.encode("utf-8"))


class QueryTests(unittest.TestCase):
    """7.1\uff1a\u5217\u8868\u3001\u8be6\u60c5\u3001\u4ea7\u7269\u6253\u5f00\u4e0e legacy-partial\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-ops-"))
        self.root = self.tmp / "delivery"
        _make_delivery(self.root)
        self.manifest_path, _note = register_manifest(self.root, build_manifest(self.root, version="1.0"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_and_describe(self):
        summaries = list_baselines(self.root)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].version, "1.0")
        detail = describe_baseline(self.manifest_path, root=self.root)
        self.assertEqual(detail.summary.version, "1.0")
        self.assertFalse(detail.problems)
        self.assertIn("artifact", detail.categories)
        self.assertTrue(detail.artifacts)

    def test_detail_reports_verification_problems(self):
        (self.root / "content" / "1 \u6982\u8ff0.md").write_text("# changed" + NL, encoding="utf-8")
        detail = describe_baseline(self.manifest_path, root=self.root)
        self.assertTrue(detail.problems)

    def test_open_artifact_only_for_registered(self):
        target = open_artifact(self.root, self.manifest_path, "output/\u4ea7\u7269(1.0).docx")
        self.assertIsNotNone(target)
        self.assertTrue(target.is_file())
        self.assertIsNone(open_artifact(self.root, self.manifest_path, "../escape.docx"))
        self.assertIsNone(open_artifact(self.root, self.manifest_path, "not-registered.docx"))

    def test_legacy_partial_marked(self):
        legacy = self.root / COLLECTIONS_DIR / "legacy.yml"
        legacy.write_text("schemaVersion: 1" + NL + "version: 0.1" + NL, encoding="utf-8")
        summaries = {item.version: item for item in list_baselines(self.root)}
        self.assertTrue(summaries["0.1"].legacy_partial)
        detail = describe_baseline(legacy)
        self.assertTrue(detail.summary.legacy_partial)
        self.assertIn("legacy-partial", detail.markdown_text())


class CompareTests(unittest.TestCase):
    """7.2\uff1a\u6309\u5206\u7ec4\u6bd4\u8f83\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-compare-"))
        self.left_root = self.tmp / "left"
        self.right_root = self.tmp / "right"
        _make_delivery(self.left_root, "v1")
        _make_delivery(self.right_root, "v2")
        # \u53f3\u4fa7\uff1a\u6b63\u6587\u53d8\u5316 + \u65b0\u589e\u8d44\u6e90 + \u5220\u9664\u4ea7\u7269
        (self.right_root / "assets" / "tables" / "new.csv").write_text("x" + NL, encoding="utf-8")
        (self.right_root / "output" / "\u4ea7\u7269(1.0).docx").unlink()
        self.left_manifest, _ = register_manifest(self.left_root, build_manifest(self.left_root, version="L1"))
        self.right_manifest, _ = register_manifest(self.right_root, build_manifest(self.right_root, version="R1"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_compare_groups_and_changes(self):
        report = compare_baselines(self.left_manifest, self.right_manifest)
        by_group = report.by_group()
        content_paths = {entry.relative_path for entry in by_group["content"]}
        self.assertIn("content/1 \u6982\u8ff0.md", content_paths)
        resource_paths = {entry.relative_path: entry.change for entry in by_group["resource"]}
        self.assertEqual(resource_paths.get("assets/tables/new.csv"), "added")
        artifact_paths = {entry.relative_path: entry.change for entry in by_group["artifact"]}
        self.assertEqual(artifact_paths.get("output/\u4ea7\u7269(1.0).docx"), "deleted")
        self.assertTrue(report.changed)
        self.assertIn("\u96c6\u5408\u6bd4\u8f83", report.markdown_text())
        data = report.to_dict()
        self.assertIn("counts", data)

    def test_identical_collections_report_no_changes(self):
        left2, _ = register_manifest(self.left_root, build_manifest(self.left_root, version="L2"))
        report = compare_baselines(self.left_manifest, left2)
        self.assertFalse(report.changed)


class ExportTests(unittest.TestCase):
    """7.2/7.5\uff1a\u5b89\u5168\u5bfc\u51fa\u8fb9\u754c\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-export-"))
        self.root = self.tmp / "delivery"
        _make_delivery(self.root)
        self.manifest_path, _ = register_manifest(self.root, build_manifest(self.root, version="1.0"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_contains_registered_files_and_manifest(self):
        target, skipped = export_package(self.root, self.manifest_path, self.tmp / "out.zip")
        self.assertIsNotNone(target)
        self.assertFalse(skipped)
        with zipfile.ZipFile(target) as package:
            names = set(package.namelist())
        self.assertIn("content/1 \u6982\u8ff0.md", names)
        self.assertIn("baseline-manifest.json", names)

    def test_export_skips_changed_and_missing(self):
        (self.root / "content" / "1 \u6982\u8ff0.md").write_text("# changed" + NL, encoding="utf-8")
        (self.root / "relations.yml").unlink()
        target, skipped = export_package(self.root, self.manifest_path, self.tmp / "out2.zip")
        self.assertIsNotNone(target)
        self.assertTrue(any("\u5185\u5bb9\u5df2\u53d8" in item for item in skipped))
        self.assertTrue(any("\u7f3a\u5931" in item for item in skipped))

    def test_export_with_nothing_usable_returns_none(self):
        for item in list((self.root / "content").rglob("*")):
            if item.is_file():
                item.unlink()
        for item in list((self.root / "assets").rglob("*")):
            if item.is_file():
                item.unlink()
        for item in list((self.root / "standards").rglob("*")):
            if item.is_file():
                item.unlink()
        (self.root / "relations.yml").unlink()
        for item in list((self.root / "output").rglob("*")):
            if item.is_file():
                item.unlink()
        target, skipped = export_package(self.root, self.manifest_path, self.tmp / "out3.zip")
        self.assertIsNone(target)
        self.assertTrue(skipped)


class RecoveryTests(unittest.TestCase):
    """7.3/7.4\uff1a\u6062\u590d\u5230\u65b0\u76ee\u5f55\u3001\u51b2\u7a81\u6362\u540d\u3001\u90e8\u5206\u6062\u590d\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-recover-"))
        self.root = self.tmp / "delivery"
        _make_delivery(self.root)
        self.manifest_path, _ = register_manifest(self.root, build_manifest(self.root, version="1.0"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_recovery_to_new_directory(self):
        destination = self.tmp / "restored"
        result = recover_baseline(self.root, self.manifest_path, destination)
        self.assertTrue(result["restored"])
        self.assertFalse(result["skipped"])
        self.assertTrue((destination / "content" / "1 \u6982\u8ff0.md").is_file())
        self.assertTrue((destination / "identity-map.json").is_file())
        # \u539f\u526f\u672c\u4e0d\u53d7\u5f71\u54cd
        self.assertTrue((self.root / "content" / "1 \u6982\u8ff0.md").is_file())

    def test_conflict_renamed_by_default(self):
        destination = self.tmp / "restored"
        (destination / "content").mkdir(parents=True)
        (destination / "content" / "1 \u6982\u8ff0.md").write_text("# existing", encoding="utf-8")
        result = recover_baseline(self.root, self.manifest_path, destination)
        self.assertTrue(result["renamed"])
        self.assertTrue((destination / "content" / "1 \u6982\u8ff0.1.md").is_file())
        self.assertEqual(
            (destination / "content" / "1 \u6982\u8ff0.md").read_text(encoding="utf-8"), "# existing"
        )

    def test_partial_recovery_with_skips(self):
        (self.root / "content" / "1 \u6982\u8ff0.md").write_text("# changed" + NL, encoding="utf-8")
        (self.root / "relations.yml").unlink()
        destination = self.tmp / "restored"
        result = recover_baseline(self.root, self.manifest_path, destination)
        self.assertTrue(result["restored"], "\u53ef\u4fe1\u9879\u5e94\u7ee7\u7eed\u6062\u590d")
        self.assertTrue(result["skipped"])
        self.assertTrue(any("\u4e0d\u53ef\u4fe1" in item for item in result["skipped"]))
        self.assertTrue((destination / "identity-map.json").is_file())

    def test_legacy_partial_manifest_recovers_nothing_but_explains(self):
        legacy = self.root / COLLECTIONS_DIR / "legacy.yml"
        legacy.write_text("schemaVersion: 1" + NL + "version: 0.1" + NL, encoding="utf-8")
        destination = self.tmp / "restored-legacy"
        result = recover_baseline(self.root, legacy, destination)
        self.assertFalse(result["restored"])
        self.assertTrue(result["skipped"])
        self.assertTrue(result["legacyPartial"])

    def test_recovery_never_writes_outside_new_directory(self):
        (self.root / "content" / "1 \u6982\u8ff0.md").write_text("# x" + NL, encoding="utf-8")
        manifest = build_manifest(self.root, version="9.9")
        from doc_tool.application.collection import BaselineFile

        manifest.files.append(
            BaselineFile(relative_path="../escape.md", sha256="x", category="content")
        )
        path, _ = register_manifest(self.root, manifest)
        destination = self.tmp / "restored2"
        result = recover_baseline(self.root, path, destination)
        self.assertTrue(any("\u8d8a\u754c" in item for item in result["skipped"]))
        self.assertFalse((self.tmp / "escape.md").exists())


if __name__ == "__main__":
    unittest.main()