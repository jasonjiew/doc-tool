# -*- coding: utf-8 -*-
"""MAIN2-E 5.4：最终成品与范围一致（离线包可移走、两轮独立、边界可见）。"""

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

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class OfflineHtmlRoundTests(unittest.TestCase):
    """离线 HTML：一轮一目录、脱离源目录仍可打开。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2e-html-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.paths = ProjectPaths(self.project)
        self.manifest = ProjectManifest.load(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())
        self.assets_root = self.paths.resolve(self.manifest.relative_asset_root())

    def _write_chapter(self, rel_path: str, text: str) -> Path:
        target = self.content_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def _export_html(self, destination: Path, **kwargs):
        from doc_tool.application.export.readonly_html import export_readonly_html

        return export_readonly_html(
            self.content_root, self.assets_root, destination, "",
            document_assets=True, **kwargs
        )

    def test_two_rounds_use_independent_directories_and_content(self):
        chapter = self._write_chapter("第1章 引言/1.1 目的.md", "# 目的\n\n第一轮正文标记。\n")
        destination = self.work / "out"
        first = self._export_html(destination)
        second = self._export_html(destination)
        self.assertNotEqual(first.directory, second.directory, "两轮必须各自独立目录")
        first_doc = (first.directory / "index.html").read_text(encoding="utf-8")
        second_doc = (second.directory / "index.html").read_text(encoding="utf-8")
        self.assertIn("第一轮正文标记", first_doc)
        self.assertIn("第一轮正文标记", second_doc)
        # 第二轮换正文：第一轮目录必须保持原内容，不被覆盖
        chapter.write_text("# 目的\n\n第二轮正文标记。\n", encoding="utf-8")
        third = self._export_html(destination)
        self.assertNotIn("第二轮正文标记", (first.directory / "index.html").read_text(encoding="utf-8"))
        self.assertIn("第二轮正文标记", (third.directory / "index.html").read_text(encoding="utf-8"))
        # 每轮都有自己的清单，来源与摘要来自当轮
        for snapshot in (first, second, third):
            manifest = json.loads((snapshot.directory / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["kind"], "readonly-html")
            self.assertTrue(manifest["sources"], "清单必须记录当轮真实来源")
            self.assertTrue(manifest["savedContent"])

    def test_offline_package_survives_moving_away_from_source(self):
        image = fixtures.tiny_png(self.work / "图.png")
        # document_assets=True：资源根就是 assets 本身，图片放在 assets/images/
        (self.assets_root / "images").mkdir(parents=True, exist_ok=True)
        shutil.copy2(image, self.assets_root / "images" / "img_0001.png")
        self._write_chapter(
            "第1章 引言/1.1 目的.md",
            "# 目的\n\n正文与图片。\n\n![示意图](images/img_0001.png)\n",
        )
        snapshot = self._export_html(self.work / "out")
        document = (snapshot.directory / "index.html").read_text(encoding="utf-8")
        self.assertIn("assets/", document, "图片必须复制进包内")
        # 移走包，并让源项目不可用
        moved = self.work / "moved-package"
        shutil.move(str(snapshot.directory), str(moved))
        shutil.rmtree(self.content_root, ignore_errors=True)
        shutil.rmtree(self.assets_root, ignore_errors=True)
        moved_doc = (moved / "index.html").read_text(encoding="utf-8")
        self.assertIn("正文与图片", moved_doc, "移走后仍应能读到正文")
        self.assertIn("assets/", moved_doc, "包内资源引用保持相对路径")
        # 包内资源文件真实存在（不是指向源目录的绝对路径）
        asset_files = [p for p in (moved / "assets").rglob("*") if p.is_file()]
        self.assertTrue(asset_files, "包内应有真实资源文件")
        self.assertNotIn(str(self.content_root), moved_doc, "不得残留源目录绝对路径")

    def test_missing_image_is_marked_with_boundary(self):
        self._write_chapter(
            "第1章 引言/1.1 目的.md",
            "# 目的\n\n![缺图](images/does-not-exist.png)\n",
        )
        snapshot = self._export_html(self.work / "out")
        document = (snapshot.directory / "index.html").read_text(encoding="utf-8")
        self.assertIn("图片待补", document, "缺图必须就地标明而不是静默丢弃")
        manifest = json.loads((snapshot.directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["warnings"], "缺图必须进入清单提醒")
        self.assertIn(manifest["status"], ("带提醒完成", "部分完成"), manifest["status"])


class ScopedExportBoundaryTests(unittest.TestCase):
    """所选范围成果只含所选章节，范围外只说明边界。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2e-scope-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")

    def _export(self, formats, scope=None):
        from doc_tool.application.intake_contract import ExportRequest
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(self.project), formats=formats,
            source_mode="saved", destination=str(self.work / "out"), scope=scope,
        )
        return run_project_export(request, skip_word_refresh=True)

    def test_selected_chapter_html_excludes_other_chapters(self):
        from doc_tool.application.intake_contract import (
            FORMAT_HTML, SCOPE_CHAPTERS, ExportScope,
        )

        report = self._export(
            [FORMAT_HTML], scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=["第1章 引言/1.1 目的.md"]),
        )
        html_result = report.result_for(FORMAT_HTML)
        self.assertIsNotNone(html_result)
        self.assertEqual(html_result.status, "ready")
        document = Path(html_result.path).read_text(encoding="utf-8")
        self.assertIn("目的", document)
        # 范围外章节的正文标记不得出现在成果里（不悄悄扩大范围）
        self.assertNotIn("2.1 架构", document)
        self.assertEqual(report.scope.kind, SCOPE_CHAPTERS)
        self.assertEqual(list(report.scope.chapters), ["第1章 引言/1.1 目的.md"])

    def test_out_of_scope_mention_is_not_a_fake_local_link(self):
        """范围外引用只说明边界，不生成指向包内不存在文件的本地链接。"""
        from doc_tool.application.intake_contract import (
            FORMAT_HTML, SCOPE_CHAPTERS, ExportScope,
        )
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        paths = ProjectPaths(self.project)
        manifest = ProjectManifest.load(self.project)
        content_root = paths.resolve(manifest.relative_content_root())
        (content_root / "第1章 引言" / "1.1 目的.md").write_text(
            "# 目的\n\n见《2.1 架构》章节。\n\n[跳转](../第2章 设计/2.1 架构.md)\n",
            encoding="utf-8",
        )
        report = self._export(
            [FORMAT_HTML], scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=["第1章 引言/1.1 目的.md"]),
        )
        document = Path(report.result_for(FORMAT_HTML).path).read_text(encoding="utf-8")
        package = Path(report.result_for(FORMAT_HTML).path).parent
        # 范围外章节没有自己的 section（不悄悄扩大范围）
        self.assertNotIn('data-rel-path="第2章 设计/2.1 架构.md"', document)
        self.assertIn("架构", document, "范围外说明应保留可读文字")
        # 指向范围外的相对路径不得被当成包内真实文件（不存在同名文件）
        self.assertFalse(
            (package / "第2章 设计" / "2.1 架构.md").exists(),
            "包内不得出现范围外章节文件",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)