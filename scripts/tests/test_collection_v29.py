# -*- coding: utf-8 -*-
"""V2.9 29-F\uff1a\u96c6\u5408\u57fa\u7ebf\u3001\u79df\u7ea6\u4e0e\u90e8\u5206\u6210\u679c\uff086.1\uff5e6.5\uff09\u3002"""

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

from doc_tool.application.collection import (  # noqa: E402
    BASELINE_CATEGORIES,
    COLLECTIONS_DIR,
    LEASE_NAME,
    CollectionManifest,
    LeaseError,
    MemberOutcome,
    acquire_lease,
    build_manifest,
    categorize,
    collect_files,
    list_manifests,
    load_manifest,
    project_lock_order,
    register_manifest,
    release_lease,
    sha256_file,
    verify_manifest,
)

NL = chr(10)


class BaselineTests(unittest.TestCase):
    """6.1\uff1a\u8986\u76d6\u8303\u56f4\u4e0e\u9010\u6587\u4ef6 SHA-256\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-collection-"))
        self.root = self.tmp / "delivery"
        (self.root / "content").mkdir(parents=True)
        (self.root / "assets" / "tables").mkdir(parents=True)
        (self.root / "standards" / "generic-requirement" / "skeleton").mkdir(parents=True)
        (self.root / "quality").mkdir(parents=True)
        (self.root / "logs").mkdir(parents=True)
        (self.root / "output").mkdir(parents=True)
        (self.root / "reviews").mkdir(parents=True)
        (self.root / "content" / "1 \u6982\u8ff0.md").write_text("# 1 \u6982\u8ff0" + NL, encoding="utf-8")
        (self.root / "assets" / "tables" / "t.csv").write_text("a,b" + NL, encoding="utf-8")
        (self.root / "template.docx").write_bytes(b"PK\x03\x04fake")
        (self.root / "standards" / "generic-requirement" / "pack.yml").write_text("schemaVersion: 1" + NL, encoding="utf-8")
        (self.root / "quality" / "rules.json").write_text("{}", encoding="utf-8")
        (self.root / "quality" / "terms.json").write_text("[]", encoding="utf-8")
        (self.root / "relations.yml").write_text("schemaVersion: 1" + NL + "relations: []" + NL, encoding="utf-8")
        (self.root / "reviews" / "comments.json").write_text("{}", encoding="utf-8")
        (self.root / "logs" / "general-validation.md").write_text("# report" + NL, encoding="utf-8")
        (self.root / "output" / "\u4ea7\u7269(1.0).docx").write_bytes(b"PK\x03\x04out")
        (self.root / "project.yml").write_text("schemaVersion: 2" + NL, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_categories_cover_required_kinds(self):
        files = collect_files(self.root)
        categories = {item.category for item in files}
        for expected in ("manifest", "content", "rules", "relations", "review", "report", "artifact", "standard", "table"):
            self.assertIn(expected, categories, expected)
        self.assertTrue(set(categories) <= set(BASELINE_CATEGORIES) | {"rules"})

    def test_every_file_has_sha256(self):
        manifest = build_manifest(self.root, version="1.0", label="\u9996\u6b21\u4ea4\u4ed8")
        self.assertTrue(manifest.files)
        for item in manifest.files:
            self.assertEqual(len(item.sha256), 64, item.relative_path)
            self.assertEqual(item.sha256, sha256_file(self.root / item.relative_path))
        self.assertIn("content", manifest.categories)

    def test_collect_skips_vcs_and_collections(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("x", encoding="utf-8")
        files = collect_files(self.root)
        self.assertFalse([item for item in files if item.relative_path.startswith(".git/")])
        self.assertFalse([item for item in files if item.relative_path.startswith(COLLECTIONS_DIR + "/")])

    def test_categorize_specific_paths(self):
        self.assertEqual(categorize("project.yml"), "manifest")
        self.assertEqual(categorize("relations.yml"), "relations")
        self.assertEqual(categorize("standards/pack/pack.yml"), "standard")
        self.assertEqual(categorize("output/a.docx"), "artifact")
        self.assertEqual(categorize("logs/a-validation.md"), "report")
        self.assertEqual(categorize("assets/tables/a.csv"), "table")


class PartialCollectionTests(unittest.TestCase):
    """6.3/6.5\uff1a\u90e8\u5206\u96c6\u5408\u53ef\u8bfb\u3001\u4e25\u683c\u7b56\u7565\u4e0e\u767b\u8bb0\u5931\u8d25\u4fdd\u7559\u6210\u679c\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-partial-"))
        self.root = self.tmp / "delivery"
        (self.root / "content").mkdir(parents=True)
        (self.root / "content" / "a.md").write_text("# a" + NL, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_member_failure_yields_partial_but_readable(self):
        manifest = build_manifest(
            self.root,
            version="1.0",
            members=[
                MemberOutcome(project_id="p1", role="requirement", relative_path="req", success=True),
                MemberOutcome(
                    project_id="p2", role="design", relative_path="design",
                    success=False, reason="\u7f3a\u5c11\u5e95\u6a21", missing=["template.docx"],
                ),
            ],
        )
        self.assertFalse(manifest.complete)
        self.assertTrue(manifest.missing)
        self.assertTrue(manifest.files, "\u90e8\u5206\u96c6\u5408\u5fc5\u987b\u4ecd\u6709\u53ef\u7528\u6210\u679c")
        text = manifest.markdown_text()
        self.assertIn("\u90e8\u5206", text)
        self.assertIn("\u7f3a\u5931\u6e05\u5355", text)
        self.assertIn("template.docx", text)

    def test_strict_policy_requires_all_members(self):
        manifest = build_manifest(
            self.root, version="1.0", strict=True,
            members=[MemberOutcome(project_id="p2", role="design", success=False, reason="x")],
        )
        self.assertFalse(manifest.complete)
        self.assertTrue(any("\u4e25\u683c" in item for item in manifest.warnings))

    def test_register_failure_keeps_results(self):
        manifest = build_manifest(self.root, version="1.0")
        before = [item.relative_path for item in manifest.files]
        from unittest import mock

        # 登记先尝试原子替换，跨设备/文件过滤层拒绝 rename 时回退 shutil.move；
        # 这里让两条路径都失败，验证“登记失败仍保留已有成果”。
        with mock.patch("os.replace", side_effect=OSError("disk")), mock.patch(
            "shutil.move", side_effect=OSError("disk")
        ):
            path, note = register_manifest(self.root, manifest)
        self.assertIsNone(path)
        self.assertIn("\u4ecd\u4fdd\u7559", note)
        self.assertEqual([item.relative_path for item in manifest.files], before)
        self.assertTrue((self.root / "content" / "a.md").is_file())

    def test_duplicate_version_saved_as_unique_snapshot(self):
        manifest = build_manifest(self.root, version="2.0")
        first, note1 = register_manifest(self.root, manifest)
        self.assertIsNotNone(first)
        self.assertFalse(note1)
        second = build_manifest(self.root, version="2.0")
        path2, note2 = register_manifest(self.root, second)
        self.assertIsNotNone(path2)
        self.assertNotEqual(first, path2)
        self.assertIn("\u53e6\u5b58\u5feb\u7167", note2)
        self.assertIn("\u65b0\u7248\u672c\u53f7", note2)

    def test_legacy_markdown_only_manifest_marked_partial(self):
        collections = self.root / COLLECTIONS_DIR
        collections.mkdir(parents=True, exist_ok=True)
        legacy = collections / "legacy.yml"
        legacy.write_text("schemaVersion: 1" + NL + "version: 0.9" + NL, encoding="utf-8")
        manifest = load_manifest(legacy)
        self.assertTrue(manifest.legacy_partial)
        self.assertFalse(manifest.complete)
        self.assertIn("legacy-partial", manifest.markdown_text())

    def test_verify_reports_missing_and_extra(self):
        manifest = build_manifest(self.root, version="1.0")
        (self.root / "content" / "a.md").write_text("# changed" + NL, encoding="utf-8")
        (self.root / "content" / "b.md").write_text("# b" + NL, encoding="utf-8")
        problems, extra = verify_manifest(self.root, manifest)
        self.assertTrue(any("\u4e0d\u4e00\u81f4" in item for item in problems))
        self.assertIn("content/b.md", extra)

    def test_list_manifests_sorted(self):
        for version in ("1.0", "0.9"):
            register_manifest(self.root, build_manifest(self.root, version=version))
        names = [item.name for item in list_manifests(self.root)]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 2)


class LeaseTests(unittest.TestCase):
    """6.2/6.4\uff1a\u79df\u7ea6\u3001\u9501\u987a\u5e8f\u4e0e\u53d6\u6d88\u91ca\u653e\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-lease-"))
        self.root = self.tmp / "delivery"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lease_blocks_service_level_write(self):
        acquire_lease(self.root, owner="first")
        with self.assertRaises(LeaseError):
            acquire_lease(self.root, owner="second")
        self.assertTrue((self.root / LEASE_NAME).is_file())

    def test_expired_lease_can_be_taken(self):
        acquire_lease(self.root, owner="first", ttl_seconds=0)
        time.sleep(0.01)
        lease = acquire_lease(self.root, owner="second", ttl_seconds=60)
        self.assertEqual(lease.owner, "second")

    def test_release_by_other_process_is_refused(self):
        acquire_lease(self.root, owner="first")
        path = self.root / LEASE_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["pid"] = 999999
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertFalse(release_lease(self.root))
        self.assertFalse(release_lease(self.root) )
        self.assertTrue(release_lease(self.root, force=True))

    def test_cancel_releases_lease(self):
        acquire_lease(self.root)
        self.assertTrue(release_lease(self.root))
        self.assertFalse((self.root / LEASE_NAME).is_file())
        acquire_lease(self.root, owner="next")

    def test_lock_order_is_deterministic(self):
        self.assertEqual(project_lock_order(["b", "a", "c", "a"]), ["a", "b", "c"])
        self.assertEqual(project_lock_order([]), [])


if __name__ == "__main__":
    unittest.main()