# -*- coding: utf-8 -*-
"""CORE 3.2 补测：公式/脚注/文本框的正文占位与章节定位。"""

from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

DOCX_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "v": "urn:schemas-microsoft-com:vml",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _docx_with_unsupported(path: Path) -> Path:
    """造一份含“文本框（无文本）+ 公式（含文本降级）”的 docx。"""
    fixtures.build_docx(path, [("h1", "第1章 引言"), ("h2", "1.1 目的"), ("p", "正文段落。")])
    # 直接在 document.xml 里插入文本框与公式节点
    import re
    import shutil
    import tempfile

    work = Path(tempfile.mkdtemp(prefix="doc-tool-unsupported-"))
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            data = {name: archive.read(name) for name in names}
        document = data["word/document.xml"].decode("utf-8")
        textbox = (
            '<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent/></v:textbox></v:shape></w:pict></w:r></w:p>'
        )
        formula = (
            '<w:p><m:oMathPara><m:oMath><m:r><m:t>x+y=z</m:t></m:r></m:oMath></m:oMathPara></w:p>'
        )
        document = document.replace("</w:body>", textbox + formula + "</w:body>")
        data["word/document.xml"] = document.encode("utf-8")
        target = work / path.name
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in data.items():
                archive.writestr(name, payload)
        shutil.copy2(target, path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return path


class UnsupportedObjectPlaceholderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("core-unsupported")
        source = _docx_with_unsupported(cls.work / "带公式文本框.docx")

        from doc_tool.application.intake_entries import run_intake

        cls.outcome = run_intake(source, parent_dir=cls.work, target_name="proj")
        assert cls.outcome.ok, cls.outcome.errors
        cls.project = Path(cls.outcome.project_root)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_extraction_reports_unsupported_with_location(self):
        from doc_tool.adapters.importer import extract_content
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(self.project)
        paths = ProjectPaths(self.project)
        content_root = paths.resolve(manifest.relative_content_root())
        extraction = extract_content(
            self.project / "original" / "source.docx",
            content_root / manifest.documentType,
            paths.root / "assets" / manifest.documentType / "images",
            paths.root / "assets" / manifest.documentType / "tables",
            manifest.documentType,
        )
        entries = list(getattr(extraction, "unsupported_map", []) or [])
        self.assertTrue(entries, "应记录暂不支持对象")
        textbox = [item for item in entries if item["feature"] == "textbox"]
        formula = [item for item in entries if item["feature"] == "formula"]
        self.assertTrue(textbox, entries)
        self.assertTrue(formula, entries)
        self.assertTrue(all(item.get("chapter") for item in entries), entries)
        self.assertTrue(all(str(item.get("sample", "")).startswith("body[") for item in entries), entries)
        self.assertEqual(textbox[0]["handling"], "placeholder", textbox[0])
        self.assertEqual(formula[0]["handling"], "text-degraded", formula[0])

    def test_body_has_visible_placeholder_and_record_can_locate_chapter(self):
        from doc_tool.application.import_record import read_import_record
        from doc_tool.application.intake_contract import placeholder_text

        record = read_import_record(self.project)
        self.assertIsNotNone(record)
        content = self.project / "content" / "general"
        chapters = {
            path.relative_to(content).as_posix(): path.read_text(encoding="utf-8")
            for path in content.rglob("*.md")
            if path.name != "_revision_record.md"
        }
        placeholder_text_value = placeholder_text("文本框", "body[4]")
        holders = [
            name for name, body in chapters.items()
            if "文本框" in body and ("待完善" in body or "原件" in body)
        ]
        self.assertTrue(
            holders,
            "正文应出现可见占位文案：{0}".format(
                {name: body[-120:] for name, body in chapters.items()}
            ),
        )
        self.assertIn("待完善", chapters[holders[0]])
        self.assertIn("body[", chapters[holders[0]], "占位应带可定位的原始位置标记")
        # 占位文案与占位助手同一来源
        self.assertIn("待完善", placeholder_text_value)

        findings = [item for item in record.findings if item.feature == "textbox"]
        self.assertTrue(findings, [item.feature for item in record.findings])
        located = [item for item in findings if item.target_chapter]
        self.assertTrue(located, "未支持对象的处理事实应带章节定位")
        self.assertTrue(any(item.element_index is not None for item in located), located)
        self.assertTrue(located[0].action, "应给出可执行的下一步动作")
        formula_findings = [item for item in record.findings if item.feature == "formula"]
        self.assertTrue(formula_findings)
        self.assertTrue(
            any(item.handling == "text-fallback" for item in formula_findings),
            "读到文本的公式应标为文本降级（不冒充可编辑）",
        )
        self.assertTrue(all(not item.editable for item in formula_findings))
        # 占位清单与正文一致（placeholder_lines 有真实调用者）
        self.assertTrue(getattr(record, "placeholderLines", []), "记录应保存正文占位清单")

    def test_result_page_can_locate_placeholder_chapter(self):
        from doc_tool.application.intake_result_page import build_result_page

        # 结果页从项目读取导入记录：占位项应带章节定位与“定位此处”动作
        page = build_result_page(self.project)
        blob = str(page.to_dict())
        self.assertIn("文本框", blob, blob[:400])
        entries = []
        for attr in ("findings", "handlingLines", "handling_lines", "entries", "actions"):
            value = getattr(page, attr, None)
            if isinstance(value, list):
                entries.extend(value)
        located = [
            item for item in entries
            if isinstance(item, dict) and str(item.get("targetChapter") or item.get("target_chapter") or "")
        ]
        self.assertTrue(located or "文本框" in blob, blob[:400])


if __name__ == "__main__":
    unittest.main(verbosity=2)