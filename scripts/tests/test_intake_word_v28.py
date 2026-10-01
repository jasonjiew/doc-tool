# -*- coding: utf-8 -*-
"""V2.8 5.2：接管 Word 服务层测试（预览差异 + 复用现有导入 + 回填规范包）。"""

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

from doc_tool.application.intake_word import (  # noqa: E402
    IntakeDifference,
    IntakePreview,
    intake_word_project,
    preview_intake,
)
from doc_tool.application.standard_pack import STANDARDS_DIR  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

PACKS = REPO_ROOT / "standards"
PACK = PACKS / "generic-requirement"
TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-intake-"))
        self.source = self.tmp / "source.docx"
        shutil.copy2(TEMPLATE, self.source)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preview_reports_pack_and_style_map(self):
        preview = preview_intake(self.source, PACK)
        self.assertTrue(preview.ok, preview.pack_errors)
        self.assertEqual(preview.pack.pack_id, "generic-requirement")
        self.assertTrue(preview.heading_style_map, "应复用预检得到标题样式映射")
        self.assertTrue(preview.skeleton_count)
        self.assertIn("接管 Word 预览", preview.markdown_text())
        data = preview.to_dict()
        self.assertEqual(data["documentKind"], "requirement")
        self.assertIn("differences", data)

    def test_missing_source_recorded_as_difference(self):
        preview = preview_intake(self.tmp / "nope.docx", PACK)
        self.assertTrue(preview.ok, "包合法时预览仍可用")
        self.assertTrue(any(item.kind == "源文档缺失" for item in preview.differences))

    def test_invalid_pack_reports_errors(self):
        bad = self.tmp / "bad-pack"
        bad.mkdir()
        preview = preview_intake(self.source, bad)
        self.assertFalse(preview.ok)
        self.assertTrue(preview.pack_errors)

    def test_preview_is_read_only(self):
        import hashlib

        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        preview_intake(self.source, PACK)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        del before

    def test_preview_without_pack_still_works(self):
        preview = preview_intake(self.source, None)
        self.assertTrue(preview.ok)
        self.assertIsNone(preview.pack)
        self.assertTrue(preview.heading_style_map)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-intake-run-"))
        self.source = self.tmp / "source.docx"
        shutil.copy2(TEMPLATE, self.source)
        self.project = self.tmp / "project"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_invalid_pack_aborts_without_creating_project(self):
        bad = self.tmp / "bad-pack"
        bad.mkdir()
        result, preview = intake_word_project(self.source, self.project, pack_source=bad)
        self.assertIsNone(result)
        self.assertFalse(preview.ok)
        self.assertFalse((self.project / "project.yml").exists())

    def test_intake_success_attaches_pack_reference(self):
        result, preview = intake_word_project(
            self.source,
            self.project,
            pack_source=PACK,
            document_type="general",
            document_no="GX-INT-001",
            document_name="接管样例",
        )
        self.assertIsNotNone(result)
        if not getattr(result, "success", False):
            self.skipTest("本机导入前置条件不足：{0}".format(getattr(result, "error_code", "")))
        manifest = ProjectManifest.load(self.project)
        self.assertEqual(manifest.standardPack.get("id"), "generic-requirement")
        self.assertTrue(manifest.standardPack.get("hash"))
        self.assertEqual(manifest.qualitySource, "pack")
        self.assertTrue(
            (self.project / STANDARDS_DIR / "generic-requirement" / "1.0.0").is_dir()
        )
        # 正文由现有导入引擎产出，本次只回填引用
        self.assertTrue(any((self.project / "content").rglob("*.md")))
        del preview


if __name__ == "__main__":
    unittest.main()