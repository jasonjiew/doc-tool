# -*- coding: utf-8 -*-
"""V3.2 4.2 补测：变体真正进入出稿内容与交付包。"""

from __future__ import annotations

import json
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402

TITLE_A = "第1章 引言"
TITLE_B = "第2章 设计"


class VariantExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v32-variant-export")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        (cls.project / "variants.yml").write_text(
            "schemaVersion: 1\n"
            "variants:\n"
            "  - variantId: lite\n"
            "    name: 精简版\n"
            "    variables:\n"
            "      productName: 精简版\n"
            "    exclude:\n"
            "      - '{0}'\n".format(TITLE_B),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _export(self, variant_id: str, destination: str):
        return run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / destination),
                variant_id=variant_id,
            ),
            skip_word_refresh=True,
        )

    def test_variant_limits_chapters_and_is_recorded(self):
        report = self._export("lite", "out-lite")
        self.assertTrue(report.variantId == "lite", report.to_dict().get("variantId"))
        self.assertTrue(report.variantApplied, "变体应真正应用到本轮出稿")
        chapters = [item["relPath"] if isinstance(item, dict) else item
                    for item in (report.to_dict().get("scope") or {}).get("chapters", [])]
        docx = report.result_for(FORMAT_DOCX)
        self.assertTrue(docx.usable, docx.message)
        with zipfile.ZipFile(docx.path) as archive:
            document = archive.read("word/document.xml").decode("utf-8", errors="replace")
        self.assertIn("目的正文", document, "变体应包含保留章节")
        self.assertNotIn("架构正文", document, "变体排除的章节不应出现在产物里")

    def test_without_variant_keeps_whole_project(self):
        report = self._export("", "out-full")
        self.assertEqual(report.variantId, "")
        self.assertFalse(report.variantApplied)
        docx = report.result_for(FORMAT_DOCX)
        with zipfile.ZipFile(docx.path) as archive:
            document = archive.read("word/document.xml").decode("utf-8", errors="replace")
        self.assertIn("目的正文", document)
        self.assertIn("架构正文", document, "不带变体时应出整份")

    def test_variant_effective_text_is_materialized_and_hashed(self):
        from unittest.mock import patch
        from doc_tool.application.effective_snapshot import capture_snapshot, discover_chapters
        from doc_tool.application.intake_contract import sha256_text
        rels = [rel for rel, _ in discover_chapters(self.project / "content/general")]

        def variant_texts(root, variant_id, snapshot, manifest):
            snapshot.variantApplied = True
            return {rel: "# 变体标题\n精简版的有效正文。\n" for rel in rels}

        with patch("doc_tool.application.effective_snapshot._variant_texts", side_effect=variant_texts):
            snapshot = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED, variant_id="lite")
        for chapter in snapshot.chapters:
            text = (Path(snapshot.workDir) / "content" / chapter.rel_path).read_text(encoding="utf-8")
            self.assertIn("精简版的有效正文", text)
            self.assertEqual(chapter.contentHash, sha256_text(text))

    def test_unknown_variant_falls_back_with_warning(self):
        report = self._export("nope", "out-unknown")
        self.assertFalse(report.variantApplied)
        text = " ".join(report.warnings or [])
        self.assertIn("未找到变体", text, report.warnings)
        docx = report.result_for(FORMAT_DOCX)
        with zipfile.ZipFile(docx.path) as archive:
            document = archive.read("word/document.xml").decode("utf-8", errors="replace")
        self.assertIn("架构正文", document, "未知变体按项目当前内容继续（不阻断出稿）")

    def test_package_records_variant_and_applied_flag(self):
        from doc_tool.application.delivery.snapshot_package import (
            PACKAGE_MANIFEST_NAME, build_delivery_package,
        )

        report = self._export("lite", "out-package")
        target = self.work / "pkg-lite.zip"
        outcome = build_delivery_package(report, target=target)
        self.assertTrue(outcome.ok, outcome.message)
        with zipfile.ZipFile(target) as archive:
            manifest = json.loads(archive.read(PACKAGE_MANIFEST_NAME).decode("utf-8"))
        origin = manifest.get("origin") or {}
        self.assertEqual(origin.get("variantId"), "lite")
        self.assertTrue(origin.get("variantApplied"), origin)

    def test_queue_job_carries_variant_into_request(self):
        from doc_tool.application.delivery.queue import DeliveryQueue

        queue = DeliveryQueue(str(self.work / "queue.json"))
        queue.enqueue(
            project_root=str(self.project), formats=[FORMAT_DOCX], refresh=False,
            destination=str(self.work / "out-queue"), variant_id="lite",
        )
        job = queue.jobs[0]
        self.assertEqual(job.request().variant_id, "lite")

        result = queue.run_pending(skip_word_refresh=True)
        self.assertTrue(result)
        report = result[0].report_obj()
        self.assertEqual(report.variantId, "lite")
        self.assertTrue(report.variantApplied)


if __name__ == "__main__":
    unittest.main(verbosity=2)
