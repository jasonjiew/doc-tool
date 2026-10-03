# -*- coding: utf-8 -*-
"""MAIN-A 导入质量与资源完整性（1.1/1.2/1.3/1.4）。

覆盖真实入口：``run_intake``（Word / Markdown）、``run_markdown_batch``、
``ReimportService.reimport``，并核对正文、资源、身份与原件事实。
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from docx import Document  # noqa: E402
from lxml import etree  # noqa: E402

from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.reimport import ReimportService  # noqa: E402
from doc_tool.application.content.references import ReferenceScanner  # noqa: E402
from doc_tool.application.intake_entries import run_intake  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NL = chr(10)


def _valid_png(path: Path, size=(24, 16)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 120, 200)).save(str(path))
    return path


def _append_raw(document, xml: str) -> None:
    body = document.element.body
    element = etree.fromstring(
        '<w:p xmlns:w="{0}" xmlns:m="{1}" xmlns:r="{2}">{3}</w:p>'.format(
            W_NS, M_NS, R_NS, xml
        )
    )
    body.insert(len(body) - 1, element)


def _numbered(document, text: str, num_id: int = 1, ilvl: int = 0) -> None:
    document.add_paragraph(text)
    pPr = document.paragraphs[-1]._p.get_or_add_pPr()
    pPr.append(etree.fromstring(
        '<w:numPr xmlns:w="{0}"><w:ilvl w:val="{1}"/><w:numId w:val="{2}"/></w:numPr>'.format(
            W_NS, ilvl, num_id
        )
    ))


def build_mixed_docx(path: Path, image: Path) -> Path:
    """标题/列表/普通表格/图片/链接/代码/复杂对象共存的样例。"""
    document = Document()
    document.add_heading("引言", level=1)
    document.add_paragraph("本文档说明导入主流程。")
    document.add_heading("目的", level=2)
    document.add_paragraph("验证列表、表格、图片与代码的读回。")
    _numbered(document, "第一项")
    _numbered(document, "第二项")
    document.add_paragraph("1. 步骤一")
    document.add_paragraph("2. 步骤二")

    document.add_heading("表格与图", level=2)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "值"
    table.cell(1, 0).text = "前导零"
    table.cell(1, 1).text = "007"
    document.add_paragraph("表格后正文。")
    document.add_picture(str(image))
    document.add_paragraph("图后正文。")

    document.add_heading("代码与链接", level=2)
    document.add_paragraph("def f():")
    document.add_paragraph("    return 1")
    _append_raw(document, '<w:hyperlink r:id="rId99"><w:r><w:t>外链文字</w:t></w:r></w:hyperlink>')
    document.add_paragraph("行内 address = 0x00 保持原样。")

    document.add_heading("复杂对象", level=2)
    _append_raw(document, '<w:r><m:oMath><m:r><m:t>x=1</m:t></m:r></m:oMath></w:r>')
    _append_raw(
        document,
        '<w:r><w:txbxContent><w:p><w:r><w:t>文本框内容</w:t></w:r></w:p></w:txbxContent></w:r>',
    )
    document.add_paragraph("结束段。")
    document.save(str(path))
    return path


class MainAImportQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-a-"))
        self.out = self.tmp / "out"
        self.out.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- 工具 ---

    def _chapter_texts(self, root: Path) -> dict:
        result = {}
        for path in sorted((root / "content").rglob("*.md")):
            if path.name == "_revision_record.md":
                continue
            result[path.relative_to(root / "content").as_posix()] = path.read_text(encoding="utf-8")
        return result

    def _dangling(self, root: Path):
        index = ContentIndexService(root / "content").build()
        ReferenceScanner(index, assets_root=root / "assets").scan_all()
        return [
            (ref.source, ref.target)
            for refs in index.references.values()
            for ref in refs
            if ref.kind == "image" and ref.dangling
        ]

    # --- MAIN-A 1.1 / 1.2：Word 混合内容读回 ---

    def test_mixed_word_import_reads_back_structure(self):
        image = _valid_png(self.tmp / "fig.png")
        source = build_mixed_docx(self.tmp / "混合样例.docx", image)
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        outcome = run_intake(source, parent_dir=self.out, target_name="混合项目")
        self.assertTrue(outcome.ok, outcome.errors)
        root = Path(outcome.project_root)
        chapters = self._chapter_texts(root)
        joined = NL.join(chapters.values())

        # 标题层级 -> 章节目录 + 小节文件
        self.assertTrue(any("第1章 引言" in name for name in chapters), sorted(chapters))
        self.assertTrue(any("1.1 目的.md" in name for name in chapters), sorted(chapters))
        self.assertTrue(any("1.2 表格与图.md" in name for name in chapters), sorted(chapters))
        self.assertTrue(any("1.3 代码与链接.md" in name for name in chapters), sorted(chapters))

        # 列表：项目符号与编号列表都保留为可编辑 Markdown
        self.assertIn("- 第一项", joined)
        self.assertIn("- 第二项", joined)
        self.assertIn("1. 步骤一", joined)
        self.assertIn("2. 步骤二", joined)

        # 普通表格：Markdown 管道表 + 前导零原样
        self.assertIn("| 项目 | 值 |", joined)
        self.assertIn("| 前导零 | 007 |", joined)

        # 图片：落盘 + 相对引用可解析
        self.assertTrue((root / "assets" / "general" / "images" / "img_0001.png").is_file())
        self.assertIn("![img_0001](images/img_0001.png", joined)
        self.assertEqual(self._dangling(root), [])

        # 链接文字保留
        self.assertIn("外链文字", joined)
        # 代码缩进与文本含义保留
        self.assertIn("def f():", joined)
        self.assertIn("return 1", joined)
        self.assertIn("    return 1", joined)
        self.assertIn("行内 address = 0x00 保持原样。", joined)

        # 原件未被改写，且项目内保留原件
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertTrue((root / "original" / "source.docx").is_file())

    def test_complex_objects_keep_original_and_exact_location(self):
        document = Document()
        document.add_heading("第一章", level=1)
        document.add_paragraph("正文。")
        _append_raw(document, '<w:r><m:oMath><m:r><m:t>x=1</m:t></m:r></m:oMath></w:r>')
        _append_raw(
            document,
            '<w:r><w:txbxContent><w:p><w:r><w:t>文本框内容</w:t></w:r></w:p></w:txbxContent></w:r>',
        )
        document.add_paragraph("结束。")
        source = self.tmp / "复杂.docx"
        document.save(str(source))

        outcome = run_intake(source, parent_dir=self.out, target_name="复杂项目")
        self.assertTrue(outcome.ok, outcome.errors)
        root = Path(outcome.project_root)
        manifest_type = ProjectManifest.load(root).documentType

        findings = {
            item.feature: item for item in outcome.plan.preservationFindings
        }
        self.assertIn("formula", findings)
        self.assertIn("textbox", findings)
        for feature in ("formula", "textbox"):
            item = findings[feature]
            self.assertEqual(item.retained_path, "original/source.docx")
            # 定位到真实章节文件与文件内行号（不是拆分前的大文件行号）
            self.assertTrue(item.target_path, feature)
            self.assertTrue(str(item.target_path).endswith(".md"), item.target_path)
            # target_path 相对 contentRoot（content/general）
            real_path = root / "content" / manifest_type / str(item.target_path)
            self.assertTrue(real_path.is_file(), item.target_path)
            lines = real_path.read_text(encoding="utf-8").split(NL)
            self.assertIsNotNone(item.target_line)
            located = lines[int(item.target_line) - 1]
            self.assertIn("x=1" if feature == "formula" else "文本框内容", located)

    def test_no_heading_document_imports_without_template_or_numbering(self):
        document = Document()
        document.add_paragraph("无标题正文第一段。")
        document.add_paragraph("无标题正文第二段。")
        source = self.tmp / "无标题.docx"
        document.save(str(source))

        outcome = run_intake(source, parent_dir=self.out, target_name="无标题项目")
        self.assertTrue(outcome.ok, outcome.errors)
        root = Path(outcome.project_root)
        chapters = self._chapter_texts(root)
        self.assertEqual(len(chapters), 1, sorted(chapters))
        body = list(chapters.values())[0]
        self.assertIn("无标题正文第一段。", body)
        self.assertIn("无标题正文第二段。", body)
        # 未指定底模/编号，仍得到可编辑项目：清单可加载、模板兜底可用、正文可编辑
        manifest = ProjectManifest.load(root)
        self.assertEqual(manifest.documentType, "general")
        self.assertTrue(manifest.relative_content_root())
        self.assertTrue((root / "template" / "template.docx").is_file())
        self.assertTrue((root / "original" / "source.docx").is_file())

    # --- MAIN-A 1.4：批量部分成功与复导入局部应用 ---

    def test_markdown_batch_partial_success_continues_and_reports(self):
        from doc_tool.application.intake_batch import (
            ITEM_FAILED, ITEM_OK, ITEM_SKIPPED, run_markdown_batch,
        )

        good = self.tmp / "1 概述.md"
        good.write_text("# 概述" + NL + NL + "正文。" + NL, encoding="utf-8")
        missing = self.tmp / "2 缺失.md"
        result = run_markdown_batch(
            [good, missing], parent_dir=self.out, document_name="批量项目",
        )
        statuses = [item.status for item in result.items]
        self.assertIn(ITEM_SKIPPED, statuses)
        self.assertIn(ITEM_OK, statuses)
        self.assertNotIn(ITEM_FAILED, statuses)
        succeeded = result.succeeded
        self.assertEqual(len(succeeded), 1)
        root = Path(succeeded[0].project_root)
        self.assertTrue((root / "project.yml").is_file())
        # MAIN-A：正文首个 H1 成为章节名（构建内核按文件名写章节标题），正文不再重复标题
        self.assertEqual(self._chapter_texts(root), {"1 概述.md": "正文。" + NL})
        self.assertTrue(any("章节标题取自正文首个一级标题" in item for item in result.succeeded[0].warnings))

    def test_reimport_applies_non_conflicting_and_keeps_local_edit(self):
        first = self.tmp / "v1.docx"
        build_files = [
            ("h1", "引言"), ("p", "第一版目的正文。"),
            ("h1", "设计"), ("p", "第一版设计正文。"),
        ]
        _build_simple_docx(first, build_files)
        outcome = run_intake(first, parent_dir=self.out, target_name="复导入项目")
        self.assertTrue(outcome.ok, outcome.errors)
        root = Path(outcome.project_root)
        manifest = ProjectManifest.load(root)
        paths = ProjectPaths(root)

        # 本地修改「1.1 目的」（模拟未保存前的本地编辑），「设计」不动
        target_chapters = {
            rel: path for rel, path in (
                (p.relative_to(root / "content").as_posix(), p)
                for p in (root / "content").rglob("*.md")
            )
        }
        purpose = [p for rel, p in target_chapters.items() if "引言" in rel][0]
        original_purpose = purpose.read_text(encoding="utf-8")
        purpose.write_text(original_purpose + NL + "本地新增说明。" + NL, encoding="utf-8")

        # 新源：引言与设计都改
        second = self.tmp / "v2.docx"
        _build_simple_docx(second, [
            ("h1", "引言"), ("p", "第二版目的正文。"),
            ("h1", "设计"), ("p", "第二版设计正文。"),
        ])
        service = ReimportService(manifest, paths)
        result = service.reimport(second)
        self.assertTrue(result.success, result.message)

        after = {p.relative_to(root / "content").as_posix(): p for p in (root / "content").rglob("*.md")}
        design = [p for rel, p in after.items() if "设计" in rel][0]
        self.assertIn("第二版设计正文。", design.read_text(encoding="utf-8"))
        purpose_after = [p for rel, p in after.items() if "引言" in rel][0]
        text = purpose_after.read_text(encoding="utf-8")
        # 冲突项默认保留本地，不被新源覆盖
        self.assertIn("本地新增说明。", text)
        self.assertNotIn("第二版目的正文。", text)
        # 只应用明确选择后才覆盖
        service2 = ReimportService(ProjectManifest.load(root), ProjectPaths(root))
        chosen = {rel: True for rel in after if "引言" in rel}
        result2 = service2.reimport(second, choices=chosen)
        self.assertTrue(result2.success, result2.message)
        purpose_final = [p for rel, p in (
            (p.relative_to(root / "content").as_posix(), p) for p in (root / "content").rglob("*.md")
        ) if "引言" in rel][0]
        self.assertIn("第二版目的正文。", purpose_final.read_text(encoding="utf-8"))


def _build_simple_docx(path: Path, blocks) -> Path:
    from scripts.tests.core_fixtures import build_docx

    return build_docx(path, blocks)


if __name__ == "__main__":
    unittest.main()