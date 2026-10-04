# -*- coding: utf-8 -*-
"""V4.3 43-A 1.3/1.4：复用原队列与单文档直出，不建第二批量执行器。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery.contract import parse_plan  # noqa: E402
from doc_tool.application.delivery.preparation import (  # noqa: E402
    COMPLETENESS_FULL,
    COMPLETENESS_PARTIAL,
    prepare_delivery,
    round_is_stale,
    submission_capture,
)


class DeliveryQueueReuseTests(unittest.TestCase):
    """1.3：缺成员只影响该项；执行仍走既有 DeliveryQueue。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-queue-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.members = {}
        for name in ("A", "B"):
            self.members[name] = fixtures.two_chapter_project(self.work / name)

    def _plan(self):
        return parse_plan(
            {
                "schemaVersion": 1, "batchId": "batch-43",
                "defaults": {"formats": ["docx"], "destination": str(self.work / "out")},
                "entries": [
                    {"id": "a", "member": "A", "formats": ["docx"]},
                    {"id": "b", "member": "B", "formats": ["docx"]},
                ],
            },
            plan_path=str(self.work / "batch.json"), base_dir=str(self.work),
        )

    def test_preparation_does_not_create_second_executor(self):
        source = Path(
            sys.modules["doc_tool.application.delivery.preparation"].__file__
        ).read_text(encoding="utf-8")
        for forbidden in ("DeliveryQueue", "threading.Thread", "multiprocessing", "subprocess"):
            self.assertNotIn(forbidden, source, "准备视图不得自建执行器：{0}".format(forbidden))

    def test_missing_member_is_partial_but_queue_still_runs_others(self):
        from doc_tool.application.delivery.queue import DeliveryQueue

        plan = parse_plan(
            {
                "schemaVersion": 1, "batchId": "batch-43b",
                "defaults": {"formats": ["docx"]},
                "entries": [
                    {"id": "a", "member": "A", "formats": ["docx"]},
                    {"id": "ghost", "member": "无此成员", "formats": ["docx"]},
                ],
            },
            plan_path=str(self.work / "batch2.json"), base_dir=str(self.work),
        )
        prep = prepare_delivery(plan)
        self.assertEqual(prep.completeness, COMPLETENESS_PARTIAL)
        self.assertEqual([row.member for row in prep.executableRows], ["A"])
        self.assertTrue(prep.invalidRows, "缺成员必须单列")

        # 执行走既有队列：只登记可执行成员，不重复建执行器
        queue = DeliveryQueue(store_path=self.work / "delivery-queue.json")
        for row in prep.executableRows:
            result = queue.enqueue(
                project_root=row.projectRoot, formats=row.formats,
                scope={"kind": "project"}, destination=row.destination or str(self.work / "out"),
                source_mode=row.sourceMode,
            )
            self.assertIsNotNone(result.job)
        self.assertEqual(len(queue.jobs), 1, "只登记可执行成员")
        self.assertTrue(queue.jobs[0].projectRoot.endswith("A"))

    def test_capture_identity_is_fixed_at_submit(self):
        """1.4：提交后修改成员正文只影响下一轮，本轮捕获不变。"""
        plan = self._plan()
        prep = prepare_delivery(plan)
        self.assertEqual(prep.completeness, COMPLETENESS_FULL)
        capture = submission_capture(prep, job_ids=["j1", "j2"])
        self.assertEqual([item["member"] for item in capture.members], ["A", "B"])
        # 提交后把 B 改成当前内容（模拟继续编辑）
        changed = prepare_delivery(plan, current_buffer_members=["B"])
        self.assertTrue(round_is_stale(capture, changed), "提交后编辑应属于下一轮")
        self.assertEqual(
            [item["sourceMode"] for item in capture.members], ["saved", "saved"],
            "原捕获不得被提交后的编辑改写",
        )


class SingleDocumentDirectExportTests(unittest.TestCase):
    """1.4：普通单文档流程保持直接出稿，不强制进入研发工作区/交付准备。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-single-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")

    def test_single_project_exports_without_delivery_queue(self):
        from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX],
            source_mode="saved", destination=str(self.work / "out"),
        )
        report = run_project_export(request, skip_word_refresh=True)
        result = report.result_for(FORMAT_DOCX)
        self.assertIsNotNone(result)
        self.assertTrue(result.usable, result.message)
        self.assertTrue(Path(result.path).is_file())
        # 全程不产生交付队列文件
        self.assertFalse((self.work / "delivery-queue.json").exists())
        self.assertFalse(list(self.work.rglob("delivery-queue.json")))

    def test_delivery_preparation_is_opt_in(self):
        """准备视图只在显式调用时产生事实；普通导出路径不引用它。"""
        source = Path(
            sys.modules["doc_tool.application.project_export"].__file__
        ).read_text(encoding="utf-8")
        self.assertNotIn("prepare_delivery", source, "普通出稿不得依赖交付准备")


if __name__ == "__main__":
    unittest.main(verbosity=2)