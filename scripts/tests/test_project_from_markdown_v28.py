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
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.references import ReferenceScanner  # noqa: E402
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

    def test_duplicate_source_names_do_not_overwrite_renamed_chapters(self):
        first = self._write("a-3.md", "first")
        second = self._write("a.md", "second")
        other = self.tmp / "other"
        other.mkdir()
        third = other / "a.md"
        third.write_text("third" + NL, encoding="utf-8")
        result = create_project_from_markdown([first, second, third], self.project)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(len(result.chapters), 3)
        self.assertEqual(len(set(result.chapters)), 3)
        texts = [(self.project / "content" / name).read_text(encoding="utf-8") for name in result.chapters]
        self.assertEqual(texts, ["first" + NL, "second" + NL, "third" + NL])

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
        # MAIN-A 1.3：资源根目录与 assets_dir()/扫描/粘贴写入一致（assets/<类型>/）。
        self.assertTrue((self.project / "assets" / "general" / "fig-1.png").is_file())
        self.assertTrue((self.project / "assets" / "general" / "sub" / "t.csv").is_file())
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


    # --- MAIN-A 1.3 多来源资源身份与引用映射 ---

    def _png(self, path, marker):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32 + marker)

    def test_same_name_in_different_dirs_both_kept(self):
        """a/logo.png 与 b/logo.png 各自保留，不按 basename 丢弃后到者。"""
        source = self.sources / "1 概述.md"
        source.write_text(
            "# 概述" + NL + NL + "![](a/logo.png)" + NL + NL + "![](b/logo.png)" + NL,
            encoding="utf-8",
        )
        self._png(self.assets / "a" / "logo.png", b"A")
        self._png(self.assets / "b" / "logo.png", b"B")
        result = create_project_from_markdown([source], self.project, asset_roots=[self.assets])
        self.assertTrue(result.ok, result.errors)
        asset_root = self.project / "assets" / "general"
        self.assertTrue((asset_root / "a" / "logo.png").is_file())
        self.assertTrue((asset_root / "b" / "logo.png").is_file())
        self.assertNotEqual(
            (asset_root / "a" / "logo.png").read_bytes(),
            (asset_root / "b" / "logo.png").read_bytes(),
        )
        self.assertFalse(
            [item for item in result.warnings if "同名资源已存在" in item],
            "同名不同目录资源不应再被判为重名丢弃",
        )

    def test_two_sources_image_png_not_crossed(self):
        """两个来源各自的 image.png 保留为不同文件，只有冲突章节的引用被改写。"""
        first = self.sources / "1 概述.md"
        first.write_text("# 概述" + NL + NL + "![](image.png)" + NL, encoding="utf-8")
        other = self.tmp / "other-src"
        other.mkdir()
        second = other / "2 设计.md"
        second.write_text("# 设计" + NL + NL + "![](image.png)" + NL, encoding="utf-8")
        self._png(self.sources / "image.png", b"FIRST")
        self._png(other / "image.png", b"SECOND")

        result = create_project_from_markdown(
            [first, second], self.project, asset_roots=[self.sources, other]
        )
        self.assertTrue(result.ok, result.errors)
        asset_root = self.project / "assets" / "general"
        marker = len(b"\x89PNG\r\n\x1a\n") + 32
        self.assertEqual((asset_root / "image.png").read_bytes()[marker:], b"FIRST")
        self.assertEqual((asset_root / "image-2.png").read_bytes()[marker:], b"SECOND")
        first_text = (self.project / "content" / "1 概述.md").read_text(encoding="utf-8")
        second_text = (self.project / "content" / "2 设计.md").read_text(encoding="utf-8")
        self.assertIn("![](image.png)", first_text)
        self.assertIn("![](image-2.png)", second_text)
        # 原来源文件不被改写
        self.assertIn("![](image.png)", first.read_text(encoding="utf-8"))
        self.assertIn("![](image.png)", second.read_text(encoding="utf-8"))

    def test_identical_resource_content_reused(self):
        """同内容资源只保留一份，两个章节共用同一路径。"""
        first = self.sources / "1 概述.md"
        first.write_text("# 概述" + NL + NL + "![](pic.png)" + NL, encoding="utf-8")
        other = self.tmp / "dup-src"
        other.mkdir()
        second = other / "2 设计.md"
        second.write_text("# 设计" + NL + NL + "![](pic.png)" + NL, encoding="utf-8")
        self._png(self.sources / "pic.png", b"SAME")
        self._png(other / "pic.png", b"SAME")
        result = create_project_from_markdown(
            [first, second], self.project, asset_roots=[self.sources, other]
        )
        self.assertTrue(result.ok, result.errors)
        asset_root = self.project / "assets" / "general"
        self.assertEqual(sorted(path.name for path in asset_root.glob("*.png")), ["pic.png"])
        for name in ("1 概述.md", "2 设计.md"):
            self.assertIn(
                "![](pic.png)",
                (self.project / "content" / name).read_text(encoding="utf-8"),
            )

    def test_referenced_resource_copied_without_explicit_asset_root(self):
        """未显式指定资源目录时，来源同级目录里被引用的资源仍会带入项目。"""
        source = self.sources / "1 概述.md"
        source.write_text("# 概述" + NL + NL + "![](images/a.png)" + NL, encoding="utf-8")
        self._png(self.sources / "images" / "a.png", b"ONLY")
        result = create_project_from_markdown([source], self.project)
        self.assertTrue(result.ok, result.errors)
        self.assertTrue((self.project / "assets" / "general" / "images" / "a.png").is_file())
        index = ContentIndexService(self.project / "content").build()
        ReferenceScanner(index, assets_root=self.project / "assets").scan_all()
        dangling = [
            ref.target
            for refs in index.references.values()
            for ref in refs
            if ref.kind == "image" and ref.dangling
        ]
        self.assertEqual(dangling, [])

    def test_chapter_links_are_not_copied_as_resources(self):
        """章节之间的 .md 链接不进入资源目录，只处理真实资源。"""
        first = self.sources / "1 概述.md"
        first.write_text("# 概述" + NL + NL + "见[设计](2 设计.md)" + NL, encoding="utf-8")
        second = self.sources / "2 设计.md"
        second.write_text("# 设计" + NL, encoding="utf-8")
        result = create_project_from_markdown(
            [first, second], self.project, asset_roots=[self.sources]
        )
        self.assertTrue(result.ok, result.errors)
        asset_root = self.project / "assets" / "general"
        self.assertFalse((asset_root / "2 设计.md").exists())
        self.assertFalse((asset_root / "1 概述.md").exists())

    def test_project_copy_offline_keeps_resources_readable(self):
        """项目副本离开来源目录后，合法资源仍可读（清单不写来源目录）。"""
        source = self.sources / "1 概述.md"
        source.write_text("# 概述" + NL + NL + "![](a/logo.png)" + NL, encoding="utf-8")
        self._png(self.assets / "a" / "logo.png", b"COPY")
        result = create_project_from_markdown([source], self.project, asset_roots=[self.assets])
        self.assertTrue(result.ok, result.errors)
        moved = self.tmp / "moved-project"
        shutil.copytree(self.project, moved)
        shutil.rmtree(self.sources)
        shutil.rmtree(self.assets)
        index = ContentIndexService(moved / "content").build()
        ReferenceScanner(index, assets_root=moved / "assets").scan_all()
        dangling = [
            ref.target
            for refs in index.references.values()
            for ref in refs
            if ref.kind == "image" and ref.dangling
        ]
        self.assertEqual(dangling, [])
        self.assertNotIn(str(self.tmp), (moved / "project.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
