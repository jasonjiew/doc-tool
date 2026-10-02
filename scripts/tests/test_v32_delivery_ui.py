# -*- coding: utf-8 -*-
"""V3.2 32-E/2.2 测试：批次交付服务适配 + 界面入口走 TaskRunner。"""

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


def _plan_payload(base: Path, members, *, formats=("docx", "html"), batch_id="batch-ui") -> dict:
    return {
        "schemaVersion": 1,
        "batchId": batch_id,
        "policy": {"execution": "serial", "wordBusy": "waiting-refresh", "onPartial": "keep-useful"},
        "defaults": {
            "formats": list(formats), "destination": str(base / "out"),
            "sourceMode": "saved", "refresh": False,
        },
        "entries": [
            {"id": name, "member": "members/{0}".format(name), "kind": "project",
             "formats": list(formats)}
            for name in members
        ],
    }


class DeliveryTaskAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("delivery-task")
        cls.members = ["Alpha", "Beta"]
        for name in cls.members:
            fixtures.two_chapter_project(cls.work / "members" / name)
        plan = _plan_payload(cls.work, cls.members)
        cls.plan_path = cls.work / "batch.json"
        cls.plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        cls.store = cls.work / "queue.json"

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_plan_preview_lists_executable_members(self):
        from doc_tool.application.delivery import gui_tasks

        preview = gui_tasks.plan_preview(self.plan_path)
        self.assertEqual(len(preview["executable"]), len(self.members))
        self.assertEqual(preview["invalid"], [])
        self.assertTrue(preview["summary"])

    def test_run_plan_serially_keeps_useful_results(self):
        from doc_tool.application.delivery import gui_tasks

        result = gui_tasks.run_plan_task(self.plan_path, store_path=str(self.store))
        self.assertEqual(len(result["enqueued"]), len(self.members))
        counts = result["queue"]["counts"]
        self.assertEqual(counts["total"], len(self.members))
        self.assertEqual(counts["failed"], 0)
        self.assertTrue(result["openTargets"], result["summary"])
        for target in result["openTargets"]:
            self.assertTrue(Path(target["path"]).is_file(), target)
        # 重复执行幂等：不重复登记成员
        again = gui_tasks.run_plan_task(self.plan_path, store_path=str(self.store))
        self.assertEqual(again["queue"]["counts"]["total"], len(self.members))

    def test_retry_unfinished_reuses_original_round(self):
        from doc_tool.application.delivery import gui_tasks

        first = gui_tasks.run_plan_task(self.plan_path, store_path=str(self.store))
        retried = gui_tasks.retry_unfinished_task(str(self.store))
        self.assertEqual(retried["queue"]["counts"]["total"], first["queue"]["counts"]["total"])
        # 已完成/待刷新项不重复执行；只补未完成项
        self.assertLessEqual(len(retried["ran"]), len(first["ran"]))

    def test_status_snapshot_has_batch_and_result_views(self):
        from doc_tool.application.delivery import gui_tasks

        snapshot = gui_tasks.status_snapshot(str(self.store))
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertIn("rows", snapshot["batch"])
        self.assertIn("rows", snapshot["result"])

    def test_invalid_member_is_reported_not_executed(self):
        from doc_tool.application.delivery import gui_tasks

        plan = _plan_payload(self.work, ["Alpha"], batch_id="batch-invalid")
        plan["entries"].append({"id": "missing", "member": "members/Missing", "kind": "project"})
        path = self.work / "batch-invalid.json"
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        preview = gui_tasks.plan_preview(path)
        self.assertTrue(preview["invalid"])
        result = gui_tasks.run_plan_task(path, store_path=str(self.work / "queue-invalid.json"))
        self.assertEqual(len(result["enqueued"]), 1)


class DeliveryEntryUiTests(unittest.TestCase):
    """2.2/5.1/5.2/5.4：入口存在，执行走既有 TaskRunner，结果页给直接动作。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("delivery-ui")
        fixtures.two_chapter_project(cls.work / "members" / "Alpha")
        plan = _plan_payload(cls.work, ["Alpha"], formats=("docx",), batch_id="batch-gui")
        cls.plan_path = cls.work / "batch.json"
        cls.plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def setUp(self):
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        self._recent.start()
        self.window = MainWindow()

    def tearDown(self):
        self._recent.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass

    def test_entry_exists_and_uses_task_runner(self):
        self.assertTrue(hasattr(self.window, "_delivery_action"))
        captured = {}

        class _Box:
            ButtonRole = None

            def __init__(self, parent=None):
                self._buttons = {}

            def setWindowTitle(self, value):
                pass

            def setText(self, value):
                captured["text"] = value

            def setDetailedText(self, value):
                captured["detail"] = value

            def addButton(self, text, role=None):
                captured.setdefault("buttons", []).append(text)
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                return self._buttons.get("开始交付")

        started = {}

        def _fake_start(spec, on_done=None):
            started["spec"] = spec
            started["on_done"] = on_done

        from PySide6.QtWidgets import QMessageBox

        _Box.ButtonRole = QMessageBox.ButtonRole
        self.window._start_task = _fake_start
        # UI 包 4.1 入口先询问「新建批次 / 打开已有计划」；这里明确选择打开已有计划，
        # 后续的预览对话框与确认语义保持与旧入口一致。
        self.window._ask_delivery_mode = lambda: "open"
        with patch("doc_tool.ui.main_window.QFileDialog.getOpenFileName",
                   return_value=(str(self.plan_path), "")), patch(
            "doc_tool.ui.main_window.QMessageBox", _Box
        ):
            self.window._on_delivery_batch()
        self.assertIn("开始交付", captured.get("buttons", []))
        self.assertIn("spec", started, "确认后应通过 _start_task 启动后台任务")
        self.assertEqual(started["spec"].name, "delivery-run")
        self.assertTrue(callable(started["spec"].target))

    def test_result_page_offers_open_and_retry(self):
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.delivery import gui_tasks

        payload = gui_tasks.run_plan_task(self.plan_path, store_path=str(self.work / "queue-gui.json"))
        captured = {}
        opened = []
        retried = []

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
                captured.setdefault("buttons", []).append(text)
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                return self._buttons.get("只重试未完成项")

        self.window._on_open_result_output = lambda path: opened.append(path)
        self.window._retry_delivery_unfinished = lambda payload: retried.append(payload)
        with patch("doc_tool.ui.main_window.QMessageBox", _Box):
            self.window._on_delivery_done(payload)
        self.assertIn("打开首个产物", captured.get("buttons", []))
        self.assertIn("只重试未完成项", captured.get("buttons", []))
        self.assertIn("补刷新（正式稿）", captured.get("buttons", []))
        self.assertTrue(retried, "点「只重试未完成项」应进入补跑路径")

    def test_refresh_action_runs_with_word_refresh(self):
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.delivery import gui_tasks

        payload = gui_tasks.run_plan_task(self.plan_path, store_path=str(self.work / "queue-refresh.json"))
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
                captured.setdefault("buttons", []).append(text)
                self._buttons[text] = {"text": text}
                return self._buttons[text]

            def exec(self):
                return 0

            def clickedButton(self):
                return self._buttons.get("补刷新（正式稿）")

        started = {}
        self.window._start_task = lambda spec, on_done=None: started.update({"spec": spec})
        with patch("doc_tool.ui.main_window.QMessageBox", _Box):
            self.window._on_delivery_done(payload)
        self.assertIn("spec", started, "补刷新应通过 TaskRunner 启动")
        self.assertEqual(started["spec"].kwargs.get("skip_word_refresh"), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)