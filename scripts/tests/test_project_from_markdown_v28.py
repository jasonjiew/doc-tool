# -*- coding: utf-8 -*-
"""V2.8 5.3：以 Markdown 建项（服务层）。"""

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

from doc_tool.application.project_from_markdown import (  # noqa: E402
    create_project_from_markdown,
    describe_entry_point,
)
from doc_tool.application.standard_pack import STANDARDS_DIR, load_project_pack  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

NL = chr(10)
PACKS = REPO_ROOT / "standards"
PACK = PACKS / "generic-requirement"
TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"


class MarkdownProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-md-"))
        self.sources = self.tmp / "sources"
        self.assets = self.tmp / "assets-src"
        self.sources.mkdir()
        self.assets.mkdir()
        (self.assets / "fig-1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        (self.assets / "sub").mkdir()
        (self.assets / "sub" / "t.csv").write_text("a,b" + NL, encoding="utf-8")
        self.project = self.tmp / "project"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, body=None):
        target = self.sources / name
        text = "# " + name if body is None else body
        target.write_text(text + NL, encoding="utf-8")
        return target

    def test_file_order_becomes_chapter_order(self):
        second = self._write("2 设计.md")
        first = self._write("1 概述.md")
        third = self._write("3 附录.md")
        result = create_project_from_markdown(
            [first, second, third], self.project, document_name="MD 建项"
        )
        self.assertTrue(result.ok, result.errors)
        manifest = ProjectManifest.load(self.project)
        self.assertEqual(manifest.chapters, ["1 概述.md", "2 设计.md", "3 附录.md"])
        self.assertEqual(result.chapters, manifest.chapters)

    def test_explicit_order_overrides_and_appends_unlisted(self):
        first = self._write("1 概述.md")
        second = self._write("2 设计.md")
        result = create_project_from_markdown(
            [first, second], self.project, chapter_order=["2 设计.md"]
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.chapters, ["2 设计.md", "1 概述.md"])
        self.assertTrue(result.warnings)

    def test_resources_copied_and_deduplicated(self):
        self._write("1 概述.md")
        result = create_project_from_markdown(
            [self.sources / "1 概述.md"], self.project, asset_roots=[self.assets]
        )
        self.assertTrue(result.ok, result.errors)
        self.assertTrue((self.project / "assets" / "fig-1.png").is_file())
        self.assertTrue((self.project / "assets" / "sub" / "t.csv").is_file())
        self.assertIn("fig-1.png", result.copied_resources)

    def test_template_optional_with_warning(self):
        self._write("1 概述.md")
        result = create_project_from_markdown([self.sources / "1 概述.md"], self.project)
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(any("未指定底模" in item for item in result.warnings))

    def test_template_copied_when_given(self):
        self._write("1 概述.md")
        result = create_project_from_markdown(
            [self.sources / "1 概述.md"], self.project, template_path=TEMPLATE
        )
        self.assertTrue(result.ok, result.errors)
        self.assertTrue((self.project / "template" / "template.docx").is_file())

    def test_pack_selection_pins_version_and_kind(self):
        self._write("1 概述.md")
        result = create_project_from_markdown(
            [self.sources / "1 概述.md"], self.project, pack_source=PACK
        )
        self.assertTrue(result.ok, result.errors)
        manifest = ProjectManifest.load(self.project)
        self.assertEqual(manifest.standardPack.get("id"), "generic-requirement")
        self.assertEqual(manifest.documentKind, "requirement")
        self.assertEqual(manifest.qualitySource, "pack")
        self.assertTrue((self.project / STANDARDS_DIR / "generic-requirement" / "1.0.0").is_dir())
        pack, warnings = load_project_pack(self.project, manifest.standardPack)
        self.assertIsNotNone(pack)
        self.assertFalse([item for item in warnings if "hash" in item])

    def test_invalid_pack_warns_but_continues(self):
        self._write("1 概述.md")
        bad = self.tmp / "bad-pack"
        bad.mkdir()
        result = create_project_from_markdown(
            [self.sources / "1 概述.md"], self.project, pack_source=bad
        )
        self.assertTrue(result.ok, "可选规范包损坏不应阻断建项")
        self.assertTrue(result.warnings)

    def test_missing_source_skipped_others_continue(self):
        good = self._write("1 概述.md")
        result = create_project_from_markdown(
            [self.sources / "missing.md", good], self.project
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.chapters, ["1 概述.md"])
        self.assertTrue(result.skipped)

    def test_does_not_overwrite_existing_project(self):
        self._write("1 概述.md")
        create_project_from_markdown([self.sources / "1 概述.md"], self.project)
        before = (self.project / "project.yml").read_text(encoding="utf-8")
        second = create_project_from_markdown([self.sources / "1 概述.md"], self.project)
        self.assertFalse(second.ok)
        self.assertEqual((self.project / "project.yml").read_text(encoding="utf-8"), before)

    def test_no_absolute_paths_in_manifest(self):
        self._write("1 概述.md")
        create_project_from_markdown([self.sources / "1 概述.md"], self.project)
        text = (self.project / "project.yml").read_text(encoding="utf-8")
        self.assertNotIn(str(self.tmp), text)

    def test_entry_point_description_distinguishes_instant_fill(self):
        text = describe_entry_point()
        self.assertIn("fromMarkdown", text)
        self.assertIn("instantTemplateFill", text)
        self.assertIn("不建项目", text["instantTemplateFill"])
        self.assertIn("从规范包起步", text["fromPack"])


if __name__ == "__main__":
    unittest.main()