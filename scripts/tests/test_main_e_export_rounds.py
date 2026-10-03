# -*- coding: utf-8 -*-
"""MAIN-E 5.3/5.4：同轮多格式同源、目标占用换副本、单格式失败保留其余。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts"),
                  str(REPO_ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_project_build as T  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    SOURCE_MODE_SAVED,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
    ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402

NL = chr(10)


class ExportRoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-e-export-"))
        self.project = Path(T._setup_project(str(self.tmp / "项目")))
        T._make_manifest(str(self.project)).save(self.project)
        self.sources = {
            path.relative_to(self.project): path.read_text(encoding="utf-8")
            for path in (self.project / "content").rglob("*.md")
        }
        self.destination = self.tmp / "导出"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _export(self, destination=None, formats=(FORMAT_DOCX, FORMAT_HTML)):
        return run_project_export(
            ExportRequest(
                project_root=str(self.project),
                formats=list(formats),
                source_mode=SOURCE_MODE_SAVED,
                destination=str(destination or self.destination),
            ),
            skip_word_refresh=True,
        )

    def test_multi_format_shares_one_capture_and_keeps_sources(self):
        report = self._export()
        self.assertTrue(report.captureId)
        paths = {}
        for result in report.results:
            # 无 Word 刷新时 DOCX 是「可读待刷新」；HTML 直接可用。两者都必须落到真实文件。
            if result.format == FORMAT_DOCX:
                self.assertIn(
                    result.status, (STATUS_READY, STATUS_PENDING_REFRESH),
                    (result.format, result.message),
                )
            else:
                self.assertEqual(result.status, STATUS_READY, (result.format, result.message))
            paths[result.format] = Path(result.path)
        self.assertTrue(paths[FORMAT_DOCX].is_file())
        self.assertTrue(paths[FORMAT_HTML].is_file())
        # 同一轮捕获：两个格式来自同一 captureId 与同一份快照
        self.assertTrue(report.snapshotWorkDir)
        self.assertEqual(report.sourceMode, SOURCE_MODE_SAVED)
        # 源 Markdown 未被出稿改动
        for rel, text in self.sources.items():
            self.assertEqual((self.project / rel).read_text(encoding="utf-8"), text)

    def test_occupied_target_gets_a_fresh_copy_path(self):
        first = self._export()
        first_docx = next(
            Path(item.path) for item in first.results if item.format == FORMAT_DOCX
        )
        second = self._export()
        second_docx = next(
            Path(item.path) for item in second.results if item.format == FORMAT_DOCX
        )
        self.assertTrue(first_docx.is_file(), "上一轮成果必须保留")
        self.assertNotEqual(first_docx, second_docx)
        self.assertTrue(second_docx.is_file())

    def test_single_format_failure_keeps_other_results(self):
        from unittest.mock import patch

        from doc_tool.application import project_export as module

        original = module._run_html

        def _boom(*_args, **_kwargs):
            raise OSError("模拟 HTML 写入失败")

        with patch.object(module, "_run_html", side_effect=_boom):
            report = run_project_export(
                ExportRequest(
                    project_root=str(self.project),
                    formats=[FORMAT_HTML, FORMAT_DOCX],
                    source_mode=SOURCE_MODE_SAVED,
                    destination=str(self.destination),
                ),
                skip_word_refresh=True,
            )
        statuses = {item.format: item.status for item in report.results}
        self.assertIn(statuses[FORMAT_DOCX], (STATUS_READY, STATUS_PENDING_REFRESH))
        self.assertNotIn(statuses[FORMAT_HTML], (STATUS_READY, STATUS_PENDING_REFRESH))
        docx = next(item for item in report.results if item.format == FORMAT_DOCX)
        self.assertTrue(Path(docx.path).is_file())
        self.assertTrue(original is not None)

    def test_unwritable_destination_falls_back_or_reports(self):
        from doc_tool.application.intake_contract import (
            SCOPE_PROJECT,
            ExportScope,
            resolve_export_directory,
        )

        blocked = self.tmp / "blocked"
        blocked.write_text("不是目录", encoding="utf-8")
        destination, note = resolve_export_directory(
            blocked, [self.project / "output"]
        )
        self.assertNotEqual(Path(destination), blocked)
        self.assertTrue(Path(destination).is_dir())
        self.assertTrue(note)
        self.assertEqual(ExportScope().kind, SCOPE_PROJECT)


if __name__ == "__main__":
    unittest.main()