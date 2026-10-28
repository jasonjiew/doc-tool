# -*- coding: utf-8 -*-
"""Frozen CLI end-to-end regression tests (Batch 5 verification)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_EXE = REPO_ROOT / "dist" / "DocTool" / "doc-tool-cli.exe"


@unittest.skipUnless(CLI_EXE.is_file(), "Frozen doc-tool-cli.exe does not exist in dist/DocTool")
class FrozenCliEndToEndTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [str(CLI_EXE), *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    def test_frozen_capabilities(self):
        res = self.run_cli("capabilities", "--format", "json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["command"], "capabilities")
        self.assertEqual(data["tool"]["appVersion"], APP_VERSION)
        self.assertEqual(data["tool"]["commit"], "83094d0a0eb3")
        self.assertTrue(data["tool"]["frozen"])
        self.assertEqual(data["tool"]["buildSource"], "devflow-portable-package")
        cmd_names = [c["name"] for c in data["commands"]]
        for expected in ("capabilities", "baseline-check", "item-list", "item-show", "review-status", "trace-plan", "change-report"):
            self.assertIn(expected, cmd_names)

    def test_frozen_baseline_check_conflict(self):
        hcp_req = Path("D:/ai_flow_space/sample-docs/requirements/DOC-REQ-2026-001 通用软件需求规格说明书")
        hcp_readme = Path("D:/ai_flow_space/sample-docs/README.md")
        if not hcp_req.is_dir() or not hcp_readme.is_file():
            self.skipTest("sample-docs path not present")

        res = self.run_cli("baseline-check", "--project", str(hcp_req), "--declare-file", str(hcp_readme), "--format", "json")
        self.assertEqual(res.returncode, 1, "Baseline conflict should yield exit code 1")
        data = json.loads(res.stdout)
        self.assertTrue(data["conflict"])
        self.assertFalse(data["allPassed"])
        proj = data["projects"][0]
        self.assertEqual(proj["manifestVersion"], "3.8")
        self.assertEqual(proj["declaredVersions"][0]["declaredVersion"], "3.10")

    def test_frozen_item_list_and_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            temp_path = Path(td)
            proj_dir = temp_path / "proj"
            proj_dir.mkdir()
            manifest_file = proj_dir / "project.yml"
            manifest_file.write_text(
                "schemaVersion: 1\nprojectId: p1\ndocumentName: 样本项目\ndocumentVersion: '1.0'\npaths:\n  contentRoot: content\n",
                encoding="utf-8",
            )
            content_dir = proj_dir / "content"
            content_dir.mkdir()
            chap_file = content_dir / "01.md"
            from doc_tool.application.content.traceable_items import new_ref
            ref1 = new_ref("p1", alias="REQ-01")
            ref2 = new_ref("p1", alias="REQ-02")
            chap_file.write_text(
                f"# Header\n\n"
                f"{ref1.render()}\n"
                f"Item 1 content\n\n"
                f"{ref2.render()}\n"
                f"Item 2 content\n",
                encoding="utf-8",
            )

            # Record hash before
            hash_before = hashlib.sha256(chap_file.read_bytes()).hexdigest()
            mtime_before = chap_file.stat().st_mtime_ns

            # Run item-list
            res = self.run_cli("item-list", "--project", str(proj_dir), "--format", "json")
            self.assertEqual(res.returncode, 0, res.stderr)
            items_data = json.loads(res.stdout)
            self.assertEqual(items_data["total"], 2)
            self.assertEqual(items_data["items"][0]["alias"], "REQ-01")
            self.assertEqual(items_data["items"][1]["alias"], "REQ-02")

            # Verify read-only guarantee
            hash_after = hashlib.sha256(chap_file.read_bytes()).hexdigest()
            mtime_after = chap_file.stat().st_mtime_ns
            self.assertEqual(hash_before, hash_after)
            self.assertEqual(mtime_before, mtime_after)

            # Test item-show by alias
            res_show = self.run_cli("item-show", "--project", str(proj_dir), "--item", "REQ-01", "--format", "json")
            self.assertEqual(res_show.returncode, 0, res_show.stderr)
            show_data = json.loads(res_show.stdout)
            self.assertTrue(show_data["found"])
            self.assertEqual(show_data["item"]["alias"], "REQ-01")
            self.assertIn("tool", show_data)

    def test_frozen_change_report_with_manifest_passed(self):
        with tempfile.TemporaryDirectory() as td:
            temp_path = Path(td)
            junit_file = temp_path / "junit.xml"
            junit_file.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<testsuite name="suite1" tests="2" failures="0" errors="0" skipped="0">\n'
                '  <testcase classname="test_mod" name="test_one" time="0.01"/>\n'
                '  <testcase classname="test_mod" name="test_two" time="0.02"/>\n'
                '</testsuite>',
                encoding="utf-8",
            )

            manifest_data = {
                "change_id": "CHG-FROZEN-PASS",
                "openspec_change_id": "devflow-cli-and-portable-delivery",
                "gitlab_mr": "!1042",
                "affected_doc_items": ["p1/REQ-01"],
                "repositories": [{
                    "repo_name": "repo_core",
                    "repo_path": str(temp_path),
                    "head_commit": "11112222",
                    "base_commit": "00001111",
                    "diff_stat": "2 files changed, 10 insertions(+)",
                    "changed_files": ["foo.py", "bar.py"],
                }],
                "junit": [str(junit_file)],
                "manual_acceptance": [{
                    "item": "Manual check on secure workstation",
                    "verifier": "Zhang",
                    "status": "passed",
                    "evidence": "Verified all dialogs in-place",
                }],
            }
            manifest_file = temp_path / "manifest.json"
            manifest_file.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8")

            rpt_file = temp_path / "report.md"
            res = self.run_cli("change-report", "--manifest", str(manifest_file), "--format", "markdown", "--report-file", str(rpt_file))
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(rpt_file.is_file())
            content = rpt_file.read_text(encoding="utf-8")
            self.assertIn("CHG-FROZEN-PASS", content)
            self.assertIn("repo_core", content)
            self.assertIn("Manual check on secure workstation", content)
            self.assertIn("`PASSED`", content)

    def test_frozen_change_report_skipped_junit_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            temp_path = Path(td)
            junit_file = temp_path / "junit_skipped.xml"
            junit_file.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<testsuite name="suite1" tests="2" failures="0" errors="0" skipped="1">\n'
                '  <testcase classname="test_mod" name="test_one" time="0.01"/>\n'
                '  <testcase classname="test_mod" name="test_two">\n'
                '    <skipped message="Word COM not available"/>\n'
                '  </testcase>\n'
                '</testsuite>',
                encoding="utf-8",
            )

            manifest_data = {
                "change_id": "CHG-FROZEN-SKIP",
                "affected_doc_items": ["p1/REQ-01"],
                "repositories": [{
                    "repo_name": "repo_core",
                    "repo_path": str(temp_path),
                    "head_commit": "11112222",
                    "base_commit": "00001111",
                    "diff_stat": "1 file changed",
                }],
                "junit": [str(junit_file)],
                "manual_acceptance": [{
                    "item": "Check",
                    "verifier": "Tester",
                    "status": "passed",
                    "evidence": "OK",
                }],
            }
            manifest_file = temp_path / "manifest.json"
            manifest_file.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8")

            res = self.run_cli("change-report", "--manifest", str(manifest_file), "--format", "json")
            self.assertEqual(res.returncode, 1, "Skipped test should result in non-zero exit code")
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "incomplete")
            self.assertTrue(any("skipped" in gap for gap in data["gapsAndRisks"]))


if __name__ == "__main__":
    unittest.main()
