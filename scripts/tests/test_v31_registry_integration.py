# -*- coding: utf-8 -*-
"""V3.1 4.2 / V3.3 5.3 补测：命令注册表真的接入了应用（菜单 + 命令面板同源）。

审计发现（第十四轮）：注册表此前仅库级可用，`main_window` 从不实例化它，命令面板是
硬编码列表，`menu_items()`/`palette_items()` 为同一函数导致等价性断言空转。本用例锁定
修复后的行为：窗口构建注册表、菜单与面板都由注册表渲染、点击经注册表统一派发、
不可用项在面板显示原因。
"""

from __future__ import annotations

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


class RegistryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("registry-integration")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def setUp(self):
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        self._recent.start()
        self.window = MainWindow()
        self.window._project_summary = type(
            "S", (), {"project_root": self.project, "is_writable": True, "document_type": "general"}
        )()
        # 模拟真实路径：项目打开后重建注册表与「命令」菜单
        self.window._reset_command_registry()
        self.window._refresh_registry_menu()

    def tearDown(self):
        self._recent.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass

    def test_window_builds_registry_with_team_and_assist_commands(self):
        registry = self.window._ensure_command_registry()
        ids = [spec.commandId for spec in registry.commands()]
        self.assertTrue(ids, "窗口应构建命令注册表")
        for expected in ("team.chapter-history", "team.my-todos", "assist.search", "assist.provider"):
            self.assertIn(expected, ids, ids)

    def test_palette_items_come_from_registry_and_dispatch_through_it(self):
        items = self.window._registry_palette_items()
        titles = [item.title for item in items]
        self.assertTrue(items, "面板应含注册表命令")
        self.assertTrue(any("章节历史" in title or "历史" in title for title in titles), titles)
        self.assertTrue(any("资料" in title or "搜索" in title for title in titles), titles)

        dispatched = {}
        registry = self.window._ensure_command_registry()
        original = registry.handle_item

        def _record(item, context=None, payload=None):
            dispatched["commandId"] = (item or {}).get("commandId")
            return original(item, context, payload)

        target = next(item for item in items if item.payload and item.payload.get("commandId") == "team.my-todos")
        with patch.object(registry, "handle_item", _record):
            registry.handle_item = _record  # 面板回调持有 registry，直接替换即可
            target.callback()
        self.assertEqual(dispatched.get("commandId"), "team.my-todos")

    def test_unavailable_commands_show_reason_in_palette_but_not_menu(self):
        from doc_tool.application.command_registry import CommandContext

        registry = self.window._ensure_command_registry()
        readonly = CommandContext(projectOpen=True, writable=False)
        palette_rows = registry.palette_items(readonly)
        menu_rows = registry.menu_items(readonly)
        menu_ids = {row["commandId"] for row in menu_rows}
        blocked = [
            row for row in palette_rows
            if not row.get("available") and row.get("reason")
        ]
        self.assertTrue(blocked, "只读上下文中应有带原因的不可用项")
        for row in blocked:
            self.assertNotIn(row["commandId"], menu_ids, "不可用项不应出现在菜单里")
            self.assertTrue(row.get("searchText"), "面板条目应可搜索")

    def test_registry_menu_is_populated(self):
        menu = self.window._registry_menu_object()
        self.assertIsNotNone(menu, "应存在「命令」菜单")
        # 注意：QAction.menu() 每次返回新包装对象，重复调用会在 GC 时误删子菜单
        # （PySide6 所有权陷阱），因此每条动作只取一次。
        categories = []
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None:
                categories.append(submenu)
        self.assertTrue(categories, "「命令」菜单应有分类子菜单")
        titles = [
            action.text()
            for submenu in categories
            for action in submenu.actions()
        ]
        self.assertTrue(any("历史" in title for title in titles), titles)


if __name__ == "__main__":
    unittest.main(verbosity=2)