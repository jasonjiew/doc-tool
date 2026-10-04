# -*- coding: utf-8 -*-
"""验收执行器（verify_runbook）的回归：结构、幂等只读、依赖项齐备。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


#: 归档前置核对依赖 openspec CLI；CI 未安装该工具，此时无法执行该检查，
#: 应跳过而不是判失败（与 test_frozen_smoke 对冻结产物的处理一致）。
OPENSPEC_CLI = shutil.which("openspec") or shutil.which("openspec.cmd")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT = REPO_ROOT / "scripts" / "release" / "verify_runbook.py"


class RunbookVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.release.verify_runbook import collect

        cls.payload = collect(with_tests=False, with_word=False)

    def test_local_steps_have_required_fields(self):
        rows = self.payload["local"]
        self.assertGreaterEqual(len(rows), 4, "本机集合应包含归档核对/主机自检/冻结自检/高DPI")
        ids = {row["id"] for row in rows}
        for expected in ("A1-A4", "C2", "C3", "C5"):
            self.assertIn(expected, ids)
        for row in rows:
            for key in ("id", "label", "kind", "ok", "detail"):
                self.assertIn(key, row)
            self.assertIsInstance(row["ok"], bool)

    @unittest.skipUnless(
        OPENSPEC_CLI,
        "需要 openspec CLI（CI 未安装），跳过归档前置核对",
    )
    def test_archive_dry_run_passes_and_does_not_modify_repo(self):
        tasks = REPO_ROOT / "openspec" / "changes" / "product-core-import-export" / "tasks.md"
        before = tasks.stat().st_mtime_ns
        row = next(item for item in self.payload["local"] if item["id"] == "A1-A4")
        self.assertTrue(row["ok"], row)
        self.assertEqual(tasks.stat().st_mtime_ns, before, "核对步骤不得改动仓库")

    def test_frozen_env_check_reports_state_with_reason(self):
        row = next(
            item for item in self.payload["local"]
            if item["id"] == "C2" and item["kind"] == "env"
        )
        # 环境不同结论不同：要么通过，要么必须给出受限原因与建议
        if not row["ok"]:
            self.assertTrue(row.get("pending"))
            self.assertTrue(row.get("detail"), row)
            detail = str(row.get("detail"))
            # 受限期必须同时给出「原因 + 建议」：或说明信任策略，或指引先构建冻结产物
            # （CI 测试阶段早于构建阶段，此时这是唯一合法状态）。
            self.assertTrue(
                "信任" in detail or "冻结" in detail or "advice" in row,
                row,
            )

    def test_manual_items_cover_authorization_human_and_environment(self):
        kinds = {row["kind"] for row in self.payload["manual"]}
        self.assertEqual(kinds, {"authorization", "human", "env"})
        ids = {row["id"] for row in self.payload["manual"]}
        # C5（Mermaid）现在属于本机可验证项，见 test_local_steps_have_required_fields
        for expected in ("A1-A4", "B1", "B2", "C2", "C3", "C4"):
            self.assertIn(expected, ids)

    def test_cli_json_output_is_parseable(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900,
        )
        start = proc.stdout.find("{")
        self.assertGreaterEqual(start, 0, proc.stderr[-300:])
        payload = json.loads(proc.stdout[start:])
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertTrue(payload["local"])

    def test_verification_doc_is_linked(self):
        runbook = (REPO_ROOT / "docs" / "product-v3-acceptance-runbook.md").read_text(encoding="utf-8")
        self.assertIn("product-v3-runbook-verification.md", runbook)


if __name__ == "__main__":
    unittest.main(verbosity=2)