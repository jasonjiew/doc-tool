# -*- coding: utf-8 -*-
"""归档执行器 dry-run 的回归：只核对，不改动仓库。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT = REPO_ROOT / "scripts" / "release" / "archive_changes.py"
CHANGES_DIR = REPO_ROOT / "openspec" / "changes"
ARCHIVE_DIR = CHANGES_DIR / "archive"


#: 归档前置核对依赖 openspec CLI；CI 未安装该工具，此时无法执行该检查，
#: 应跳过而不是判失败（与 test_frozen_smoke 对冻结产物的处理一致）。
OPENSPEC_CLI = shutil.which("openspec") or shutil.which("openspec.cmd")


@unittest.skipUnless(OPENSPEC_CLI, "需要 openspec CLI（CI 未安装），跳过归档 dry-run 核对")
class ArchiveRunnerDryRunTests(unittest.TestCase):
    def _snapshot(self):
        return sorted(
            path.relative_to(CHANGES_DIR).as_posix()
            for path in CHANGES_DIR.rglob("*")
            if path.is_file()
        )

    def test_dry_run_is_read_only_and_reports_all_changes(self):
        before = self._snapshot()
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        import json

        payload = json.loads(proc.stdout)
        self.assertTrue(payload["dryRun"])
        self.assertEqual(len(payload["changes"]), 5)
        for entry in payload["changes"]:
            self.assertTrue(entry["exists"])
            self.assertTrue(entry["valid"], entry)
            self.assertTrue(entry["remaining"], "归档前应如实列出剩余任务")
        self.assertEqual(self._snapshot(), before, "dry-run 不得改动仓库")
        self.assertFalse((ARCHIVE_DIR / "product-core-import-export").exists())

    def test_script_lists_expected_remaining_tasks(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        output = proc.stdout
        self.assertIn("dry-run", output)
        for change in (
            "product-core-import-export", "product-v30-content-reuse",
            "product-v31-team-workflow", "product-v32-batch-delivery",
            "product-v33-authoring-assistance",
        ):
            self.assertIn(change, output)


if __name__ == "__main__":
    unittest.main(verbosity=2)