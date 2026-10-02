# -*- coding: utf-8 -*-
"""补测独立复核发现的两处不可达：面板打开即加载建议（含模块更新）；后台索引可被轮询。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from scripts.tests.test_v33_module_update_cancel import _project_with_outdated_module  # noqa: E402


class PanelReachabilityTests(unittest.TestCase):
    """独立复核（第二十四轮）发现的“库级可用但应用内不可达”回归用例。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v33-panel-reach")
        cls.project = _project_with_outdated_module(cls.work)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_panel_loads_suggestions_including_module_update(self):
        from doc_tool.application.assist.models import KIND_MODULE_UPDATE
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        assistant = build_assistant(self.project)
        panel = AssistPanel(assistant, project_root=self.project)
        rows = [
            panel._suggestions_list.item(row).data(0x0100)
            for row in range(panel._suggestions_list.count())
        ]
        self.assertTrue(rows, "打开面板即应有建议，而不是空收件区")
        kinds = {getattr(item, "kind", "") for item in rows if item is not None}
        self.assertIn(KIND_MODULE_UPDATE, kinds, kinds)
        # 手动刷新同样可用
        refreshed = panel.load_all_suggestions()
        self.assertIsNotNone(refreshed)
        self.assertTrue(refreshed.of_kind(KIND_MODULE_UPDATE))

    def test_background_index_is_polled_by_panel_timer(self):
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        assistant = build_assistant(self.project, cache_dir=self.work / "panel-cache")
        panel = AssistPanel(assistant, project_root=self.project)
        self.assertTrue(panel.index_in_background())
        timer = getattr(panel, "_index_timer", None)
        self.assertIsNotNone(timer, "界面必须有轮询定时器，否则完成回调永不触发")
        self.assertTrue(timer.isActive(), "后台索引期间定时器应在运行")
        panel.wait_background_index(timeout=120)
        panel._poll_background_index()
        self.assertFalse(timer.isActive(), "索引结束后应停止轮询")
        self.assertIsInstance(panel.background_index_result(), dict)

    def test_new_kind_keeps_display_order(self):
        from doc_tool.application.assist.models import KIND_MODULE_UPDATE
        from doc_tool.application.assist.suggestions import _KIND_ORDER

        self.assertIn(KIND_MODULE_UPDATE, _KIND_ORDER, _KIND_ORDER)


if __name__ == "__main__":
    unittest.main(verbosity=2)