# -*- coding: utf-8 -*-
"""CORE-H 8.1：project-export CLI 契约测试（help、退出码、机器报告、原轮补格式）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

CLI = str(REPO_ROOT / "doc_tool_cli.py")


def _run(*args, cwd=None):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", ""))))
    return subprocess.run(
        [sys.executable, CLI, *args], cwd=str(cwd or REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", check=False,
    )


class ProjectExportCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("cli-export")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        cls.out = cls.work / "out"
        cls.out.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_help_exposes_contract_options(self):
        result = _run("project-export", "--help")
        self.assertEqual(result.returncode, 0)
        for token in ("--formats", "--scope", "--chapters", "--destination",
                      "--source-mode", "--strict", "--retry-of", "--output"):
            self.assertIn(token, result.stdout)

    def test_template_fill_output_still_means_docx_path(self):
        result = _run("template-fill", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--output", result.stdout)
        self.assertIn("输出 DOCX 路径", result.stdout)

    def test_saved_mode_exports_and_reports_json(self):
        result = _run(
            "project-export", "--project", str(self.project),
            "--formats", "docx,html,source-zip", "--destination", str(self.out),
            "--no-refresh", "--output", "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["sourceMode"], "saved")
        self.assertIn("docx", report["usable"])
        self.assertIn("html", report["usable"])
        self.assertTrue(Path(report["indexPath"]).is_file())
        for item in report["results"]:
            if item["format"] in ("docx", "html", "source-zip"):
                self.assertTrue(Path(item["path"]).is_file(), item)

    def test_current_buffer_is_rejected_without_ui(self):
        result = _run(
            "project-export", "--project", str(self.project),
            "--source-mode", "current-buffer", "--no-refresh",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("current-buffer", result.stderr)
        self.assertIn("saved", result.stderr)

    def test_scope_chapters_only_outputs_selected(self):
        from doc_tool.application.effective_snapshot import discover_chapters

        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        target = rels[0]
        result = _run(
            "project-export", "--project", str(self.project),
            "--scope", "chapters", "--chapters", target,
            "--formats", "html", "--destination", str(self.work / "one"),
            "--no-refresh", "--output", "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["scope"]["kind"], "chapters")
        self.assertEqual(report["scope"]["chapters"], [target])
        html = [item for item in report["results"] if item["format"] == "html"][0]
        self.assertTrue(Path(html["path"]).is_file())
        text = Path(html["path"]).read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(rels[1].split("/")[-1].replace(".md", ""), text)

    def test_retry_of_reuses_original_round(self):
        first_out = self.work / "round1"
        first = _run(
            "project-export", "--project", str(self.project),
            "--formats", "docx,pdf", "--destination", str(first_out),
            "--no-refresh", "--output", "json",
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        report = json.loads(first.stdout)
        index = report["indexPath"]
        retry = _run(
            "project-export", "--project", str(self.project),
            "--retry-of", index, "--retry-formats", "pdf",
            "--no-refresh", "--output", "json",
        )
        self.assertEqual(retry.returncode, 0, retry.stderr)
        retried = json.loads(retry.stdout)
        self.assertEqual(retried["captureId"], report["captureId"])
        docx_first = [item for item in report["results"] if item["format"] == "docx"][0]
        docx_retry = [item for item in retried["results"] if item["format"] == "docx"][0]
        self.assertEqual(docx_first["path"], docx_retry["path"])

    def test_strict_returns_nonzero_when_format_not_ready(self):
        result = _run(
            "project-export", "--project", str(self.project),
            "--formats", "docx", "--destination", str(self.work / "strict"),
            "--no-refresh", "--strict", "--output", "json",
        )
        # --no-refresh 必然让 DOCX 处于待刷新（未正式）：严格模式按非零返回
        self.assertEqual(result.returncode, 2, result.stdout)
        report = json.loads(result.stdout)
        self.assertIn("docx", report["strictViolations"])

    def test_no_usable_result_returns_one(self):
        broken = self.work / "broken"
        (broken / "content").mkdir(parents=True, exist_ok=True)
        (broken / "project.yml").write_text(
            "schemaVersion: 1\ndocumentType: general\ndocumentNo: ''\n"
            "documentName: 空项目\ndocumentVersion: '1.0'\nsourceSha256: ''\n"
            "paths:\n  sourceDocx: original/source.docx\n  templateDocx: template/template.docx\n"
            "  contentRoot: content\n  assetRoot: assets\n  tableRoot: assets/tables\n",
            encoding="utf-8",
        )
        result = _run(
            "project-export", "--project", str(broken),
            "--formats", "docx,html", "--destination", str(self.work / "broken-out"),
            "--no-refresh", "--output", "json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
