# -*- coding: utf-8 -*-
"""V3.2 1.4 测试：多项目/变体夹具 + 断网/无 Word/坏格式 + 原单项目入口兼容。"""

from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery import gui_tasks  # noqa: E402
from doc_tool.application.delivery.contract import load_plan_file  # noqa: E402
from doc_tool.application.delivery.queue import JOB_WAITING_REFRESH, DeliveryQueue  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402


class BatchFixtureTests(unittest.TestCase):
    """三项目（含一个坏格式）+ 两变体成员 + 断网/无 Word 场景。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v32-entry")
        members = cls.work / "members"
        cls.alpha = fixtures.two_chapter_project(members / "Alpha")
        cls.beta = fixtures.two_chapter_project(members / "Beta")
        cls.broken = members / "Broken"
        cls.broken.mkdir(parents=True, exist_ok=True)
        (cls.broken / "project.yml").write_text("this is: not: valid: yaml\n: :", encoding="utf-8")
        # 两个变体成员指向同一项目的两个变体（变体声明由 V3.0 服务读取，缺失时按整份处理）
        (cls.alpha / "variants.yml").write_text(
            "schemaVersion: 1\nvariants:\n"
            "  - variantId: standard\n    name: 标准型\n    chapters: []\n"
            "  - variantId: pro\n    name: 专业型\n    chapters: []\n",
            encoding="utf-8",
        )
        plan = {
            "schemaVersion": 1,
            "batchId": "batch-entry-fixture",
            "policy": {"execution": "serial", "wordBusy": "waiting-refresh",
                       "onPartial": "keep-useful", "strict": False},
            "defaults": {
                "formats": ["docx"], "destination": str(cls.work / "out"),
                "sourceMode": "saved", "refresh": False,
            },
            "entries": [
                {"id": "alpha", "member": "members/Alpha", "kind": "project", "formats": ["docx"]},
                {"id": "alpha-pro", "member": "members/Alpha", "kind": "project",
                 "variantId": "pro", "formats": ["docx", "html"]},
                {"id": "beta", "member": "members/Beta", "kind": "project", "formats": ["docx"]},
                {"id": "broken", "member": "members/Broken", "kind": "project", "formats": ["docx"]},
            ],
        }
        cls.plan_path = cls.work / "batch.json"
        cls.plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_plan_lists_all_members_and_bad_one_fails_in_isolation(self):
        """计划层列出全部成员；坏格式成员在执行时**单独失败**，其它成员继续。"""
        preview = gui_tasks.plan_preview(self.plan_path)
        self.assertEqual(len(preview["executable"]) + len(preview["invalid"]), 4, preview["summary"])
        result = gui_tasks.run_plan_task(
            self.plan_path, store_path=str(self.work / "queue-isolation.json"),
        )
        counts = result["queue"]["counts"]
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["failed"], 1, result["summary"])
        self.assertGreaterEqual(counts["completed"] + counts["completed-with-warnings"], 3)
        failed = [row for row in result["batch"]["rows"] if row.get("status") == "failed"]
        self.assertTrue(failed)
        self.assertIn("Broken", json.dumps(failed, ensure_ascii=False))

    def test_offline_run_succeeds_without_network(self):
        """断网：把 socket 连接直接判失败，批次仍应正常出稿（不依赖网络）。"""

        def _no_network(*_args, **_kwargs):
            raise OSError("network disabled in test")

        with patch.object(socket.socket, "connect", _no_network), patch.object(
            socket, "create_connection", _no_network,
        ), patch.object(socket.socket, "connect_ex", _no_network):
            result = gui_tasks.run_plan_task(
                self.plan_path, store_path=str(self.work / "queue-offline.json"),
            )
        counts = result["queue"]["counts"]
        # 只有坏格式成员失败；断网不影响其它成员的本地出稿
        self.assertEqual(counts["failed"], 1, result["summary"])
        self.assertGreaterEqual(counts["total"], 4)
        self.assertGreaterEqual(len(result["openTargets"]), 3, result["summary"])

    def test_no_word_run_marks_waiting_refresh_and_keeps_readable(self):
        plan = load_plan_file(self.plan_path)
        queue = DeliveryQueue(str(self.work / "queue-noword.json"))
        for entry in plan.executable_entries():
            if entry.projectRoot.endswith("Broken"):
                continue  # 坏格式成员另行验证，不混入无 Word 断言
            queue.enqueue(
                project_root=entry.projectRoot, formats=list(entry.formats),
                scope=entry.scope_obj(), destination=str(self.work / "noword-out"),
                refresh=True,
            )
        queue._word_probe = lambda: (False, "本机没有可用的 Microsoft Word")
        jobs = queue.run_pending(skip_word_refresh=False)
        self.assertTrue(jobs)
        for job in jobs:
            self.assertEqual(job.status, JOB_WAITING_REFRESH, job.status)
            self.assertTrue(job.usable_results())
            self.assertIn("Word", job.waitingReason)

    def test_single_project_entry_still_works(self):
        """原单项目入口（统一出稿）在批次包装之外保持兼容。"""
        report = run_project_export(
            ExportRequest(
                project_root=str(self.alpha), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "single"),
            ),
            skip_word_refresh=True,
        )
        usable = report.usable_results()
        self.assertTrue(usable, report.summary_lines())
        for item in usable:
            self.assertTrue(Path(item.path).is_file())
        # 坏格式项目走单项目入口时抛结构化错误（批次路径会捕获并只让该项失败）
        from doc_tool.domain.errors import DocToolError

        with self.assertRaises(DocToolError):
            run_project_export(
                ExportRequest(
                    project_root=str(self.broken), formats=[FORMAT_DOCX],
                    source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "broken-out"),
                ),
                skip_word_refresh=True,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)