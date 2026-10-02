# -*- coding: utf-8 -*-
"""V3.2 2.2/5.1 补测：逐项进度事件与逐成员明细渲染。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class DeliveryProgressTests(unittest.TestCase):
    """2.2：队列逐项进度必须转成阶段事件（此前 GUI 传 kwargs={} → 永远没有逐项进度）。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v32-progress")
        members = cls.work / "members"
        for name in ("Alpha", "Beta"):
            fixtures.two_chapter_project(members / name)
        plan = {
            "schemaVersion": 1, "batchId": "batch-progress",
            "defaults": {"formats": ["docx"], "destination": str(cls.work / "out"),
                         "sourceMode": "saved", "refresh": False},
            "entries": [
                {"id": "a", "member": "members/Alpha", "kind": "project", "formats": ["docx"]},
                {"id": "b", "member": "members/Beta", "kind": "project", "formats": ["docx"]},
            ],
        }
        cls.plan_path = cls.work / "batch.json"
        cls.plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_queue_progress_becomes_stage_events(self):
        from doc_tool.application.delivery import gui_tasks

        events = []
        result = gui_tasks.run_plan_task(
            self.plan_path, store_path=str(self.work / "queue.json"),
            on_event=events.append,
        )
        self.assertTrue(events, "应产生逐项阶段事件")
        stages = [getattr(event, "stage", "") for event in events]
        self.assertTrue(any(stage.startswith("delivery:") for stage in stages), stages)
        details = " ".join(getattr(event, "detail", "") for event in events)
        self.assertIn("Alpha", details)
        self.assertIn("Beta", details)
        metrics = [getattr(event, "metrics", {}) for event in events]
        self.assertTrue(all("jobId" in item for item in metrics), metrics)
        # 成员明细行随负载返回，供界面渲染
        self.assertEqual(len(result["memberRows"]), 2, result["memberRows"])
        for row in result["memberRows"]:
            self.assertTrue(row["memberName"] or row["member"])
            self.assertTrue(row["cells"])
            self.assertTrue(any(cell.get("path") for cell in row["cells"]))

    def test_retry_also_reports_progress(self):
        from doc_tool.application.delivery import gui_tasks

        gui_tasks.run_plan_task(self.plan_path, store_path=str(self.work / "queue2.json"))
        events = []
        result = gui_tasks.retry_unfinished_task(
            str(self.work / "queue2.json"), on_event=events.append,
        )
        self.assertIsInstance(result, dict)
        self.assertTrue(all(hasattr(event, "stage") for event in events))


class DeliveryResultRenderingTests(unittest.TestCase):
    """5.1：结果页/计划预览必须渲染逐成员、变体、格式、状态、路径。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v32-render")
        fixtures.two_chapter_project(cls.work / "members" / "Alpha")
        plan = {
            "schemaVersion": 1, "batchId": "batch-render",
            "defaults": {"formats": ["docx"], "destination": str(cls.work / "out"),
                         "sourceMode": "saved", "refresh": False},
            "entries": [
                {"id": "a", "member": "members/Alpha", "kind": "project",
                 "variantId": "standard", "formats": ["docx", "html"]},
            ],
        }
        cls.plan_path = cls.work / "batch.json"
        cls.plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_result_dialog_shows_member_format_status_path(self):
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.delivery import gui_tasks
        from doc_tool.ui.main_window import MainWindow

        payload = gui_tasks.run_plan_task(self.plan_path, store_path=str(self.work / "queue.json"))
        captured = {}

        class _Box:
            ButtonRole = QMessageBox.ButtonRole

            def __init__(self, parent=None):
                self._buttons = {}

            def setWindowTitle(self, value):
                pass

            def setText(self, value):
                captured["text"] = value

            def setDetailedText(self, value):
                captured["detail"] = value

            def addButton(self, text, role=None):
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                return self._buttons.get("关闭")

        recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        recent.start()
        try:
            window = MainWindow()
            with patch("doc_tool.ui.main_window.QMessageBox", _Box):
                window._on_delivery_done(payload)
            window.close()
        finally:
            recent.stop()

        detail = captured.get("detail") or ""
        self.assertIn("Alpha", detail, detail)
        self.assertIn("docx", detail)
        self.assertIn("html", detail)
        self.assertIn(str(self.work / "out"), detail, "明细应含产物路径")
        self.assertTrue("可用" in detail or "待刷新" in detail, detail)

    def test_plan_preview_lists_members(self):
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.delivery import gui_tasks
        from doc_tool.ui.main_window import MainWindow

        captured = {}

        class _Box:
            ButtonRole = QMessageBox.ButtonRole

            def __init__(self, parent=None):
                self._buttons = {}

            def setWindowTitle(self, value):
                pass

            def setText(self, value):
                captured["text"] = value

            def setDetailedText(self, value):
                captured["detail"] = value

            def addButton(self, text, role=None):
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                return self._buttons.get("取消")

        preview = gui_tasks.plan_preview(self.plan_path)
        self.assertTrue(preview.get("view", {}).get("rows"))
        recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        recent.start()
        try:
            window = MainWindow()
            with patch("doc_tool.ui.main_window.QMessageBox", _Box), patch(
                "doc_tool.ui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(self.plan_path), ""),
            ):
                window._on_delivery_batch()
            window.close()
        finally:
            recent.stop()
        detail = captured.get("detail") or ""
        self.assertIn("Alpha", detail, detail)
        self.assertIn("standard", detail, "计划明细应含变体")
        self.assertIn("docx", detail)


class TaskRunnerProgressInjectionTests(unittest.TestCase):
    """2.2 端到端：GUI 用 TaskSpec 启动时，逐项进度事件应进入 TaskRunner 事件队列。"""

    def test_task_runner_injects_on_event_and_forwards_item_stages(self):
        from doc_tool.application.delivery import gui_tasks
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        work = fixtures.scratch_dir("v32-progress-runner")
        try:
            fixtures.two_chapter_project(work / "members" / "Alpha")
            plan = {
                "schemaVersion": 1, "batchId": "batch-runner",
                "defaults": {"formats": ["docx"], "destination": str(work / "out"),
                             "sourceMode": "saved", "refresh": False},
                "entries": [{"id": "a", "member": "members/Alpha", "kind": "project",
                             "formats": ["docx"]}],
            }
            plan_path = work / "batch.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            spec = TaskSpec(
                name="delivery-run", target=gui_tasks.run_plan_task,
                args=(str(plan_path),), kwargs={"store_path": str(work / "queue.json")},
                timeout_seconds=600,
            )
            runner = TaskRunner()
            self.assertTrue(runner.start(spec))
            runner.join(timeout=600)
            events = runner.drain_events()
            stages = [getattr(event, "stage", "") for event in events]
            self.assertTrue(
                any(stage.startswith("delivery:") for stage in stages),
                "TaskRunner 应把逐项进度转成阶段事件：{0}".format(stages[:10]),
            )
            self.assertTrue(any(getattr(event, "kind", "") == "succeeded" for event in events))
        finally:
            fixtures.cleanup(work)


if __name__ == "__main__":
    unittest.main(verbosity=2)