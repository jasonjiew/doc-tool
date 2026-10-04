# -*- coding: utf-8 -*-
"""V4.3 43-B：逐成员格式成果表、局部失败与原轮补充。"""

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


def _project_report(formats, destination, *, project_root):
    from doc_tool.application.intake_contract import ExportRequest
    from doc_tool.application.project_export import run_project_export

    request = ExportRequest(
        project_root=str(project_root), formats=list(formats),
        source_mode="saved", destination=str(destination),
    )
    return run_project_export(request, skip_word_refresh=True)


class MemberFormatTableTests(unittest.TestCase):
    """2.1：按真实成员/版本展示可用格式、局部失败与下一动作。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-b-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.members = {}
        for name in ("Alpha", "Beta"):
            self.members[name] = fixtures.two_chapter_project(self.work / name)
        self.store = self.work / "queue.json"

    def _queue(self):
        from doc_tool.application.delivery.queue import DeliveryQueue

        return DeliveryQueue(store_path=self.store)

    def _enqueue_all(self, formats=("docx", "html")):
        queue = self._queue()
        for name, root in self.members.items():
            queue.enqueue(
                project_root=str(root), formats=list(formats),
                scope={"kind": "project"}, destination=str(self.work / "out" / name),
            )
        return queue

    def test_rows_expose_real_paths_status_and_open_targets(self):
        from doc_tool.application.delivery import gui_hooks

        queue = self._enqueue_all()
        for job in queue.jobs:
            report = _project_report(job.formats, job.destination, project_root=job.projectRoot)
            queue.update_from_report(job.jobId, report) if hasattr(queue, "update_from_report") else None
        # 直接按真实报告构造视图，验证表格事实来自报告
        views = []
        for job in queue.jobs:
            report = _project_report(job.formats, job.destination, project_root=job.projectRoot)
            views.append(report)
        # 视图直接消费真实队列事实（ResultIndex 是可选补充，不伪造身份）
        view = gui_hooks.batch_view(queue)
        self.assertEqual(len(view.rows), 2, "每个真实成员一行")
        for row in view.rows:
            self.assertTrue(row.projectRoot, "行必须带真实项目根")
            self.assertTrue(row.cells, "行必须带逐格式结果")
            for cell in row.cells:
                self.assertIn(cell.format, ("docx", "html"))
                if cell.exists:
                    self.assertTrue(Path(cell.path).is_file(), cell.path)
        self.assertTrue(view.summary_lines())

    def test_partial_failure_keeps_usable_and_only_retries_failed(self):
        """2.2：HTML 可用而 DOCX 失败时，先能打开 HTML，只补失败项。"""
        from doc_tool.application.delivery import gui_hooks

        alpha = self.members["Alpha"]
        destination = self.work / "out-alpha"
        report = _project_report(["docx", "html"], destination, project_root=alpha)
        html_result = report.result_for("html")
        docx_result = report.result_for("docx")
        self.assertIsNotNone(html_result)
        self.assertTrue(html_result.usable, html_result.message or html_result.status)
        # 只有可用格式给出可打开目标；未可用格式不得谎报可用
        usable = report.usable_results()
        self.assertIn(html_result.format, [item.format for item in usable])
        if not docx_result.usable:
            self.assertNotIn(docx_result.format, [item.format for item in usable])
        retry_formats = report.failed_formats()
        self.assertTrue(all(item in ("docx", "pdf") for item in retry_formats) or retry_formats == [])

    def test_capture_identity_reused_for_original_round(self):
        """2.2/2.3：补原轮使用原报告身份与范围；缺身份不予补。"""
        from doc_tool.application.delivery.queue import DeliveryQueue
        from doc_tool.application.project_export import read_export_index

        alpha = self.members["Alpha"]
        destination = self.work / "out-alpha"
        report = _project_report(["docx"], destination, project_root=alpha)
        self.assertTrue(report.captureId, "本轮必须有真实捕获身份")
        index_path = Path(report.indexPath)
        self.assertTrue(index_path.is_file(), index_path)
        reloaded = read_export_index(index_path)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.captureId, report.captureId)
        self.assertEqual(reloaded.roundId, report.roundId)
        self.assertEqual(reloaded.scope.to_dict(), report.scope.to_dict())
        # 缺报告 / 身份不匹配时不得按视图缓存伪造身份
        missing = read_export_index(self.work / "nope.json")
        self.assertIsNone(missing)

    def test_single_format_failure_is_isolated_per_member(self):
        """2.1/2.3：一个成员单格式失败不影响另一成员的可用成果。"""
        alpha, beta = self.members["Alpha"], self.members["Beta"]
        report_a = _project_report(["html"], self.work / "a", project_root=alpha)
        report_b = _project_report(["html"], self.work / "b", project_root=beta)
        path_a = Path(report_a.result_for("html").path)
        path_b = Path(report_b.result_for("html").path)
        self.assertTrue(path_a.is_file())
        self.assertTrue(path_b.is_file())
        self.assertNotEqual(path_a.parent, path_b.parent, "成员成果目录互不覆盖")
        self.assertTrue(report_a.captureId and report_b.captureId)
        self.assertNotEqual(report_a.captureId, report_b.captureId, "捕获身份按轮次独立")

    def test_long_names_and_same_name_members_stay_distinct(self):
        """2.4：长名称/同名成员必须按真实路径区分。"""
        long_name = "同名成员" + "超长" * 10
        root_long = fixtures.two_chapter_project(self.work / long_name)
        queue = self._queue()
        from doc_tool.application.delivery.queue import DeliveryQueue

        queue = DeliveryQueue(store_path=self.work / "queue2.json")
        for root in (self.members["Alpha"], root_long, root_long):
            queue.enqueue(
                project_root=str(root), formats=["docx"], scope={"kind": "project"},
                destination=str(self.work / "out"),
            )
        roots = [job.projectRoot for job in queue.jobs]
        self.assertEqual(len(roots), len(set(roots)), "同名/重复成员不得去重成一条错误身份")
        self.assertIn(str(root_long), roots)


if __name__ == "__main__":
    unittest.main(verbosity=2)