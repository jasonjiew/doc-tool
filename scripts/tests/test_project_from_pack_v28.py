# -*- coding: utf-8 -*-
"""V2.8 5.1\uff1a\u4ece\u89c4\u8303\u5305\u8d77\u6b65\u5efa\u9879\uff08\u670d\u52a1\u5c42\uff09\u3002"""

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

from doc_tool.application.project_from_pack import create_project_from_pack  # noqa: E402
from doc_tool.application.standard_pack import STANDARDS_DIR, load_project_pack  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

PACKS = REPO_ROOT / "standards"
PACK = PACKS / "generic-requirement"


class CreateFromPackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-frompack-"))
        self.root = self.tmp / "new-project"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_manifest_chapters_and_quality(self):
        result = create_project_from_pack(
            PACK, self.root,
            document_name="\u65b0\u5efa\u9700\u6c42", document_no="GX-NEW-001",
        )
        self.assertTrue(result.ok, result.errors)
        manifest = ProjectManifest.load(self.root)
        self.assertEqual(manifest.schemaVersion, 2)
        self.assertEqual(manifest.standardPack.get("id"), "generic-requirement")
        self.assertTrue(manifest.chapters, "\u5e94\u628a\u9aa8\u67b6\u4f5c\u4e3a\u663e\u5f0f\u7ae0\u8282\u987a\u5e8f")
        for name in manifest.chapters:
            self.assertTrue((self.root / "content" / name).is_file(), name)
        self.assertTrue((self.root / "quality" / "variables.json").is_file())
        self.assertTrue((self.root / "quality" / "terms.json").is_file())
        self.assertTrue((self.root / "quality" / "rules.json").is_file())
        self.assertTrue((self.root / "template" / "template.docx").is_file())
        self.assertTrue((self.root / STANDARDS_DIR / "generic-requirement" / "1.0.0").is_dir())

    def test_variables_from_pack_reach_manifest(self):
        create_project_from_pack(PACK, self.root)
        manifest = ProjectManifest.load(self.root)
        self.assertIn("productName", manifest.variables)

    def test_project_reloads_and_pack_resolves(self):
        create_project_from_pack(PACK, self.root)
        manifest = ProjectManifest.load(self.root)
        pack, warnings = load_project_pack(self.root, manifest.standardPack)
        self.assertIsNotNone(pack)
        self.assertFalse([item for item in warnings if "hash" in item])

    def test_no_absolute_paths_in_project(self):
        create_project_from_pack(PACK, self.root)
        text = (self.root / "project.yml").read_text(encoding="utf-8")
        self.assertNotIn(str(self.tmp), text)
        self.assertNotIn(":\\", text.replace("documentNo", ""))

    def test_does_not_overwrite_existing_project(self):
        create_project_from_pack(PACK, self.root)
        before = (self.root / "project.yml").read_text(encoding="utf-8")
        second = create_project_from_pack(PACK, self.root)
        self.assertFalse(second.ok)
        self.assertTrue(any("\u5df2\u5b58\u5728" in item for item in second.errors))
        self.assertEqual((self.root / "project.yml").read_text(encoding="utf-8"), before)

    def test_invalid_pack_reports_errors_without_side_effects(self):
        bad = self.tmp / "bad-pack"
        bad.mkdir()
        result = create_project_from_pack(bad, self.root)
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)
        self.assertFalse((self.root / "project.yml").exists())

    def test_all_three_public_packs_create_usable_projects(self):
        for name in ("generic-requirement", "generic-design", "generic-test"):
            root = self.tmp / name
            result = create_project_from_pack(PACKS / name, root, document_name=name)
            self.assertTrue(result.ok, "{0}: {1}".format(name, result.errors))
            manifest = ProjectManifest.load(root)
            self.assertTrue(manifest.chapters, name)
            self.assertTrue(manifest.standardPack.get("hash"), name)

    def test_copy_of_project_still_resolves_pack(self):
        create_project_from_pack(PACK, self.root)
        clone = self.tmp / "\u53e6\u4e00\u53f0\u673a\u5668" / "proj"
        shutil.copytree(self.root, clone)
        manifest = ProjectManifest.load(clone)
        pack, _warnings = load_project_pack(clone, manifest.standardPack)
        self.assertIsNotNone(pack)


if __name__ == "__main__":
    unittest.main()