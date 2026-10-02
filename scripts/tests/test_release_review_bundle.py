# -*- coding: utf-8 -*-
"""审阅包生成器的回归：产物齐全、哈希可核、不动源仓库。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT = REPO_ROOT / "scripts" / "release" / "make_review_bundle.py"
CHANGES = (
    "product-core-import-export", "product-v30-content-reuse", "product-v31-team-workflow",
    "product-v32-batch-delivery", "product-v33-authoring-assistance",
)


class ReviewBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.tests import core_fixtures as fixtures

        cls.work = fixtures.scratch_dir("review-bundle")

    @classmethod
    def tearDownClass(cls):
        from scripts.tests import core_fixtures as fixtures

        fixtures.cleanup(cls.work)

    def _build(self, **kwargs):
        from scripts.release.make_review_bundle import build

        return build(self.work, **kwargs)

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def test_bundle_contains_all_deliverables_with_verifiable_hashes(self):
        manifest = self._build()
        root = Path(manifest["root"])
        self.assertTrue((root / "INDEX.md").is_file())
        self.assertTrue((root / "manifest.json").is_file())
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["kind"], "v3-review-bundle")

        for change in CHANGES:
            base = "openspec/changes/{0}".format(change)
            for name in ("proposal.md", "design.md", "tasks.md"):
                self.assertTrue((root / base / name).is_file(), "{0}/{1}".format(base, name))
        for rel in (
            "docs/product-v3-release-readiness.md",
            "docs/product-v3-audit-findings.md",
            "docs/product-v3-handoff.md",
            "docs/product-plan-v3-execution.md",
        ):
            self.assertTrue((root / rel).is_file(), rel)
        self.assertTrue((root / "evidence" / "git-status.txt").is_file())
        self.assertTrue((root / "evidence" / "frozen-artifacts.json").is_file())

        # 清单里的每个文件都能对上 sha256
        self.assertGreaterEqual(len(manifest["files"]), 30)
        for item in manifest["files"]:
            path = root / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(self._sha256(path), item["sha256"], item["path"])

        # 索引里给出进度与证据
        index = (root / "INDEX.md").read_text(encoding="utf-8")
        for change in CHANGES:
            self.assertIn(change, index)
        self.assertIn("全量回归证据", index)
        self.assertIn("待验收项", index)
        progress = manifest["taskProgress"]
        self.assertEqual(len(progress), 5)
        for change, (done, todo) in progress.items():
            self.assertGreater(done, 0, change)
            self.assertTrue(todo, "审阅包应如实列出剩余任务：" + change)

    def test_bundle_does_not_modify_repository_sources(self):
        tasks = REPO_ROOT / "openspec" / "changes" / "product-core-import-export" / "tasks.md"
        before = tasks.stat().st_mtime_ns
        self._build(make_zip=True)
        self.assertEqual(tasks.stat().st_mtime_ns, before, "生成审阅包不得改动源文件")

    def test_frozen_hashes_recorded_when_artifacts_exist(self):
        manifest = self._build()
        for item in manifest["frozenArtifacts"]:
            path = REPO_ROOT / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual(self._sha256(path), item["sha256"])

    def test_cli_default_output_is_deliverables(self):
        # 用显式 --out 指向临时目录，确认命令行入口可用且返回 0
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(self.work / "cli")],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertIn("审阅包", proc.stdout)
        self.assertTrue(list((self.work / "cli").glob("v3-review-*/INDEX.md")))


if __name__ == "__main__":
    unittest.main(verbosity=2)