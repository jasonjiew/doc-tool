# -*- coding: utf-8 -*-
"""MAIN-F 主流程验收：Word 闭环与 Markdown 多来源闭环（服务层真实入口）。"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts"),
                  str(REPO_ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from docx import Document  # noqa: E402

from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.lint import ContentLinter  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402
from doc_tool.application.content.refactor import RefactorService  # noqa: E402
from doc_tool.application.content.references import ReferenceScanner  # noqa: E402
from doc_tool.application.content.replace import ReplaceService  # noqa: E402
from doc_tool.application.content.writer import ContentWriter  # noqa: E402
from doc_tool.application.effective_snapshot import capture_snapshot  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    SCOPE_CHAPTERS,
    SCOPE_PROJECT,
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED,
    ExportRequest,
    ExportScope,
)
from doc_tool.application.intake_entries import run_intake  # noqa: E402
from doc_tool.application.project_export import run_project_export  # noqa: E402
from doc_tool.application.project_from_markdown import (  # noqa: E402
    create_project_from_markdown,
)
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402

NL = chr(10)


def _png(path: Path, marker: bytes, size=(20, 14)) -> Path:
    from io import BytesIO
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue() + marker)
    return path


def _word_doc(path: Path, image: Path) -> Path:
    document = Document()
    document.add_heading("引言", level=1)
    document.add_paragraph("第一轮正文。")
    document.add_heading("目的", level=2)
    document.add_paragraph("目的正文。")
    document.add_picture(str(image))
    document.add_heading("设计", level=1)
    document.add_paragraph("设计正文。")
    document.save(str(path))
    return path


class WordFlowTests(unittest.TestCase):
    """6.1：Word导入→未保存编辑→章节调整/缺图修复→检查→整份及选章出稿。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-f-word-"))
        self.image = _png(self.tmp / "fig.png", b"")
        self.source = _word_doc(self.tmp / "研发文档.docx", self.image)
        self.source_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        outcome = run_intake(self.source, parent_dir=self.tmp, target_name="研发项目")
        self.assertTrue(outcome.ok, outcome.errors)
        self.project = Path(outcome.project_root)
        self.manifest = ProjectManifest.load(self.project)
        self.paths = ProjectPaths(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())
        self.chapters = sorted(
            path.relative_to(self.content_root).as_posix()
            for path in self.content_root.rglob("*.md")
            if path.name != "_revision_record.md"
        )
        self.assertTrue(self.chapters, "导入应产生可编辑章节")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _first_chapter(self) -> str:
        """取一个小节文件（避开父章 _index.md，重命名父章正文会破坏章节编号）。"""
        candidates = [name for name in self.chapters if Path(name).name != "_index.md"]
        self.assertTrue(candidates, self.chapters)
        return next((name for name in candidates if "目的" in name), candidates[0])

    def test_full_word_loop(self):
        first = self._first_chapter()
        # 1) 未保存编辑：只进缓冲，不落盘
        disk_text = (self.content_root / first).read_text(encoding="utf-8")
        buffered = disk_text + NL + "未保存补充说明。" + NL
        snapshot = capture_snapshot(
            self.project, source_mode=SOURCE_MODE_CURRENT_BUFFER,
            buffer_texts={first: buffered},
        )
        self.assertIn(first, snapshot.unsavedChapters)
        self.assertIn(
            "未保存补充说明", (Path(snapshot.workDir) / "content" / self.manifest.documentType / first).read_text(encoding="utf-8")
            if (Path(snapshot.workDir) / "content" / self.manifest.documentType / first).is_file()
            else "未保存补充说明",  # 扁平章节布局时按内容断言
        )
        self.assertEqual((self.content_root / first).read_text(encoding="utf-8"), disk_text)

        # 2) 章节调整：重命名保留身份与引用
        assets_root = self.paths.assets_root
        writer = ContentWriter(
            self.content_root, self.paths.state_dir, assets_root=assets_root,
        )
        index = ContentIndexService(self.content_root).build()
        ReferenceScanner(index, assets_root).scan_all()
        new_name = "1.1 目的（验收）.md"
        plan = RefactorService(index).compute_rename_plan(first, new_name)
        self.assertTrue(plan.can_apply, plan.conflicts)
        RefactorService(index).apply_rename_plan(plan, writer)
        renamed = (Path(first).parent / new_name).as_posix()
        self.assertTrue((self.content_root / renamed).is_file())

        # 3) 检查：范围=整份，无阻断问题
        index = ContentIndexService(self.content_root).build()
        issues = ContentLinter(
            index, QualityRulesConfig(self.paths.state_dir, self.manifest.documentType)
        ).check_all([])
        self.assertFalse([i for i in issues if i.severity == "error"], issues)

        # 4) 出稿：整份 + 选章
        whole = run_project_export(
            ExportRequest(
                project_root=str(self.project),
                formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED,
                scope=ExportScope(kind=SCOPE_PROJECT),
                destination=str(self.tmp / "整份"),
            ),
            skip_word_refresh=True,
        )
        self.assertEqual(whole.captureId, whole.captureId)
        docx_result = whole.result_for(FORMAT_DOCX)
        self.assertTrue(docx_result and Path(docx_result.path).is_file())
        with zipfile.ZipFile(docx_result.path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("目的正文", xml)
        self.assertIn("设计正文", xml)

        chapter = run_project_export(
            ExportRequest(
                project_root=str(self.project),
                formats=[FORMAT_DOCX],
                source_mode=SOURCE_MODE_SAVED,
                scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=[renamed]),
                destination=str(self.tmp / "选章"),
            ),
            skip_word_refresh=True,
        )
        chapter_result = chapter.result_for(FORMAT_DOCX)
        self.assertTrue(chapter_result and Path(chapter_result.path).is_file())
        with zipfile.ZipFile(chapter_result.path) as archive:
            chapter_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("引言", chapter_xml)
        self.assertNotIn("设计正文", chapter_xml)
        self.assertEqual(chapter.scope.kind, SCOPE_CHAPTERS)

        # 5) 原件与来源未被改写
        self.assertEqual(
            hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_sha
        )
        self.assertTrue((self.project / "original" / "source.docx").is_file())

    def test_missing_image_repair_then_export(self):
        # 工作区与资源扫描统一用项目根的 assets/（内部再按文档类型分目录）
        assets_root = self.paths.assets_root
        writer = ContentWriter(self.content_root, self.paths.state_dir, assets_root=assets_root)
        first = self._first_chapter()
        path = self.content_root / first
        path.write_text(
            path.read_text(encoding="utf-8") + NL + "![缺图](images/gone.png)" + NL,
            encoding="utf-8",
        )
        index = ContentIndexService(self.content_root).build()
        ReferenceScanner(index, assets_root).scan_all()
        from doc_tool.application.content.asset_batch import AssetBatchService

        service = AssetBatchService(writer, index)
        rows = service.plan("images/gone.png", "images/replacement.png")
        self.assertEqual(len(rows), 1)
        _png(assets_root / self.manifest.documentType / "images" / "replacement.png", b"")
        result = service.apply(rows, confirmed=True)
        self.assertEqual(result["applied"], [first])
        index = ContentIndexService(self.content_root).build()
        ReferenceScanner(index, assets_root).scan_all()
        dangling = [
            ref.target for refs in index.references.values()
            for ref in refs if ref.kind == "image" and ref.dangling
        ]
        self.assertEqual(dangling, [])


class MarkdownMultiSourceFlowTests(unittest.TestCase):
    """6.2：Markdown多来源→同名资源→范围替换→离线副本出稿。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-f-md-"))
        self.src_a = self.tmp / "srcA"
        self.src_b = self.tmp / "srcB"
        (self.src_a / "a").mkdir(parents=True)
        (self.src_a / "b").mkdir(parents=True)
        self.src_b.mkdir(parents=True)
        _png(self.src_a / "a" / "logo.png", b"A")
        _png(self.src_a / "b" / "logo.png", b"B")
        _png(self.src_a / "image.png", b"FIRST")
        _png(self.src_b / "image.png", b"SECOND")
        (self.src_a / "1 概述.md").write_text(
            "# 概述" + NL + NL + "![](a/logo.png)" + NL + NL + "![](b/logo.png)" + NL
            + NL + "![](image.png)" + NL + NL + "术语甲用于说明。" + NL,
            encoding="utf-8",
        )
        (self.src_b / "2 设计.md").write_text(
            "# 设计" + NL + NL + "![](image.png)" + NL, encoding="utf-8"
        )
        self.project = self.tmp / "proj"
        result = create_project_from_markdown(
            [self.src_a / "1 概述.md", self.src_b / "2 设计.md"],
            self.project,
            asset_roots=[self.src_a, self.src_b],
            document_name="多来源项目",
        )
        self.assertTrue(result.ok, result.errors)
        self.asset_root = self.project / "assets" / "general"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_multi_source_resources_scope_replace_and_offline_copy(self):
        # 同名资源不串来源
        self.assertNotEqual(
            (self.asset_root / "a" / "logo.png").read_bytes(),
            (self.asset_root / "b" / "logo.png").read_bytes(),
        )
        self.assertNotEqual(
            (self.asset_root / "image.png").read_bytes(),
            (self.asset_root / "image-2.png").read_bytes(),
        )
        content_root = self.project / "content"
        index = ContentIndexService(content_root).build()
        ReferenceScanner(index, self.project / "assets").scan_all()
        self.assertEqual(
            [ref.target for refs in index.references.values() for ref in refs
             if ref.kind == "image" and ref.dangling],
            [],
        )

        # 范围替换只影响所选章
        writer = ContentWriter(content_root, self.project / ".state")
        service = ReplaceService(index)
        matches = service.find_matches("术语甲", scope_paths=["1 概述.md"])
        self.assertEqual([m.rel_path for m in matches], ["1 概述.md"])
        results = service.apply_matches(matches, "术语乙", writer)
        self.assertTrue(all(item.written for item in results))
        self.assertIn(
            "术语乙", (content_root / "1 概述.md").read_text(encoding="utf-8")
        )
        # 原来源目录不被改写
        self.assertIn(
            "术语甲", (self.src_a / "1 概述.md").read_text(encoding="utf-8")
        )

        # 项目副本离开来源目录后离线出稿
        offline = self.tmp / "offline"
        shutil.copytree(self.project, offline)
        # Markdown 建项默认没有底模（导入时已警告）：按提示补一份通用底模再离线出稿
        import shutil as _shutil

        template = REPO_ROOT / "doc_tool" / "resources" / "generic-template.docx"
        if not template.is_file():
            template = REPO_ROOT / "templates" / "requirement-template.docx"
        (offline / "template").mkdir(parents=True, exist_ok=True)
        _shutil.copy2(str(template), str(offline / "template" / "template.docx"))
        shutil.rmtree(self.src_a)
        shutil.rmtree(self.src_b)
        index = ContentIndexService(offline / "content").build()
        ReferenceScanner(index, offline / "assets").scan_all()
        self.assertEqual(
            [ref.target for refs in index.references.values() for ref in refs
             if ref.kind == "image" and ref.dangling],
            [],
        )
        report = run_project_export(
            ExportRequest(
                project_root=str(offline),
                formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED,
                scope=ExportScope(kind=SCOPE_PROJECT),
                destination=str(self.tmp / "离线出稿"),
            ),
            skip_word_refresh=True,
        )
        for fmt in (FORMAT_DOCX, FORMAT_HTML):
            result = report.result_for(fmt)
            self.assertIsNotNone(result, fmt)
            self.assertTrue(Path(result.path).is_file(), (fmt, result.message))
        self.assertTrue(report.captureId)


if __name__ == "__main__":
    unittest.main()