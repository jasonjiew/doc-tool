# -*- coding: utf-8 -*-
"""V3.0 3.4 测试：正文复用展开接进共享预处理与快照（Word/HTML/预览同源）。"""

from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.content import reuse_commands as reuse  # noqa: E402
from doc_tool.application.content.reuse_hook import (  # noqa: E402
    build_project_resolver, has_module_markers, project_has_module_declarations,
)
from doc_tool.application.effective_snapshot import capture_snapshot, discover_chapters  # noqa: E402

FENCE = chr(96) * 3
MODULE_BODY = "架构正文。"


def _reference(module_id: str = "m-arch", version: str = "1.0.0", slot: str = "s1") -> str:
    return "{0}doc-module id={1} version={2} slot={3}\n{0}".format(FENCE, module_id, version, slot)


class ReusePipelineWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("reuse-wiring")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        content = cls.project / "content" / "general"
        cls.content = content
        cls.chapters = [rel for rel, _path in discover_chapters(content)]
        # 把第 2 章提取为公共模块，并在第 1 章插入固定引用
        context = reuse.load_context(cls.project)
        result = reuse.extract_chapter_module(
            context, cls.chapters[1], module_id="m-arch", version="1.0.0",
        )
        assert result.get("ok"), result
        first = content / cls.chapters[0]
        first.write_text(
            first.read_text(encoding="utf-8") + "\n" + _reference() + "\n", encoding="utf-8",
        )
        cls.reference_chapter = cls.chapters[0]

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_project_declares_modules_and_marker_detected(self):
        self.assertTrue(project_has_module_declarations(self.project))
        text = (self.content / self.reference_chapter).read_text(encoding="utf-8")
        self.assertTrue(has_module_markers(text))

    def test_resolver_expands_reference_and_keeps_original_body(self):
        resolver = build_project_resolver(self.project)
        self.assertIsNotNone(resolver)
        text = (self.content / self.reference_chapter).read_text(encoding="utf-8")
        resolved = resolver(self.reference_chapter, text)
        self.assertNotIn("doc-module", resolved)
        self.assertIn(MODULE_BODY, resolved)
        self.assertIn("目的正文", resolved)
        # 无标记文本原样返回（零开销路径）
        self.assertEqual(resolver(self.reference_chapter, "普通正文。\n"), "普通正文。\n")

    def test_project_without_declarations_has_no_resolver(self):
        plain = fixtures.two_chapter_project(self.work / "plain")
        self.assertFalse(project_has_module_declarations(plain))
        self.assertIsNone(build_project_resolver(plain))

    def test_pipeline_build_uses_resolved_content(self):
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        paths = ProjectPaths(self.project)
        manifest = ProjectManifest.load(self.project)
        result = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertTrue(result.success, (result.error_code, result.last_stage))
        output = result.output_path or result.pending_output_path
        self.assertTrue(output and Path(output).is_file())
        with zipfile.ZipFile(output) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
        self.assertIn(MODULE_BODY, document_xml, "构建产物应包含展开后的模块正文")
        self.assertNotIn("doc-module", document_xml, "构建产物不得残留引用标记")

    def test_snapshot_and_html_use_same_resolved_content(self):
        from doc_tool.application.intake_contract import (
            FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        snapshot = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED)
        chapter_text = (
            Path(snapshot.workDir) / "content" / self.reference_chapter
        ).read_text(encoding="utf-8")
        self.assertIn(MODULE_BODY, chapter_text)
        self.assertNotIn("doc-module", chapter_text)
        self.assertTrue(any("展开" in item for item in snapshot.warnings), snapshot.warnings)

        report = run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "html"),
            ),
            skip_word_refresh=True,
        )
        html = report.result_for(FORMAT_HTML)
        self.assertTrue(html.usable, html.message)
        page = Path(html.path).read_text(encoding="utf-8", errors="replace")
        self.assertIn(MODULE_BODY, page, "离线 HTML 应使用同一份展开内容")

    def test_reuse_does_not_bypass_structural_validation_failure(self):
        from unittest.mock import patch
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths
        paths = ProjectPaths(self.project)
        manifest = ProjectManifest.load(self.project)

        def reject(*args, **kwargs):
            paths.logs_dir.mkdir(parents=True, exist_ok=True)
            (paths.logs_dir / (manifest.documentType + "-validation.md")).write_text(
                "- [FAIL] Relationship Target 与引用完整 — broken target\n", encoding="utf-8",
            )
            return False

        with patch("doc_tool.adapters.kernel.validate_with_project", side_effect=reject):
            result = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertFalse(result.success)
        self.assertEqual(result.last_stage.stage, "validate_pre")

    def test_module_images_survive_pipeline_snapshot_and_html(self):
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.application.intake_contract import ExportRequest, FORMAT_HTML, SOURCE_MODE_SAVED
        from doc_tool.application.project_export import run_project_export
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths
        project = fixtures.two_chapter_project(self.work / "module-images")
        context = reuse.load_context(project)
        rel = context.discovered[0]
        image = fixtures.tiny_png(context.asset_root / "images" / "module.png")
        chapter = context.content_root / rel
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n![模块图](images/module.png)\n", encoding="utf-8")
        extracted = reuse.extract_chapter_module(context, rel, module_id="with-image", version="1.0.0")
        self.assertTrue(extracted.get("ok"), extracted)
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n" + _reference("with-image") + "\n", encoding="utf-8")
        other_chapter = context.content_root / context.discovered[1]
        other_chapter.write_text(other_chapter.read_text(encoding="utf-8") + "\n![宿主图](images/module.png)\n", encoding="utf-8")
        original = chapter.read_bytes()
        result = run_pipeline(ProjectManifest.load(project), ProjectPaths(project), skip_word_refresh=True)
        self.assertTrue(result.success, result.last_stage)
        with zipfile.ZipFile(result.output_path or result.pending_output_path) as archive:
            self.assertTrue(any(name.startswith("word/media/") for name in archive.namelist()))
        report = run_project_export(ExportRequest(project_root=str(project), formats=[FORMAT_HTML],
            source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "module-image-html")), skip_word_refresh=True)
        html = report.result_for(FORMAT_HTML)
        self.assertTrue(html.usable, html.message)
        self.assertFalse(any("图片缺失" in warning for warning in html.warnings), html.warnings)
        self.assertEqual(chapter.read_bytes(), original)
        self.assertTrue(image.is_file())
        (project / "variants.yml").write_text("schemaVersion: 1\nvariants:\n  - variantId: images\n    name: 带图变体\n", encoding="utf-8")
        variant = run_project_export(ExportRequest(project_root=str(project), formats=[FORMAT_HTML],
            source_mode=SOURCE_MODE_SAVED, variant_id="images", destination=str(self.work / "variant-images")), skip_word_refresh=True)
        self.assertTrue(variant.variantApplied)
        self.assertTrue(variant.result_for(FORMAT_HTML).usable)
        self.assertFalse(any("图片缺失" in warning for warning in variant.result_for(FORMAT_HTML).warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
