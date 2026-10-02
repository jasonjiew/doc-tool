# -*- coding: utf-8 -*-
"""V3.3 5.3 测试：写作辅助接入 V3.1 共享命令与集中概览提示。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.assist.commands import (  # noqa: E402
    CMD_ASSIST_ADOPT, CMD_ASSIST_OVERVIEW, CMD_ASSIST_PROVIDER, CMD_ASSIST_SEARCH,
    CMD_ASSIST_SUGGEST, CMD_ASSIST_UNDO, ENHANCE_NOT_RUN,
    build_assist_overview, register_assist_commands,
)
from doc_tool.application.command_registry import (  # noqa: E402
    CommandContext, CommandRegistry,
)
from doc_tool.application.content.team_entry import (  # noqa: E402
    CMD_TEAM_REPORT, register_team_commands,
)


class AssistRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("assist-registry")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _registry(self):
        return register_assist_commands(CommandRegistry(self.work / "cfg"), self.project)

    def test_commands_share_one_registry_with_team_commands(self):
        registry = register_team_commands(CommandRegistry(self.work / "cfg"), self.project)
        register_assist_commands(registry, self.project)
        ids = [spec.commandId for spec in registry.commands()]
        for expected in (CMD_ASSIST_SEARCH, CMD_ASSIST_SUGGEST, CMD_ASSIST_ADOPT,
                         CMD_ASSIST_UNDO, CMD_ASSIST_PROVIDER, CMD_ASSIST_OVERVIEW,
                         CMD_TEAM_REPORT):
            self.assertIn(expected, ids)
        context = CommandContext(projectOpen=True, writable=True)
        # 菜单与命令面板同状态（V3.1 注册表保证）
        self.assertEqual(
            [item["commandId"] for item in registry.menu_items(context)],
            [item["commandId"] for item in registry.palette_items(context)],
        )

    def test_search_and_suggest_return_sources_without_model(self):
        registry = self._registry()
        context = CommandContext(projectOpen=True, writable=True)
        search = registry.invoke(CMD_ASSIST_SEARCH, context, {"query": "正文"})
        self.assertTrue(search.ok, search.message)
        self.assertIn("hits", search.value)
        self.assertIn("scope", search.value)
        self.assertIn("stale", search.value)
        for hit in search.value["hits"][:3]:
            self.assertIn("relPath", hit)
        suggest = registry.invoke(CMD_ASSIST_SUGGEST, context)
        self.assertTrue(suggest.ok, suggest.message)
        # 建议集序列化为 camelCase：覆盖说明在 coverageNotes，且明确“不构成证据”
        self.assertIn("coverageNotes", suggest.value)
        self.assertTrue(suggest.value["coverageNotes"])
        self.assertIn("factsNote", suggest.value)

    def test_adopt_requires_writable_and_selection(self):
        registry = self._registry()
        readonly = registry.invoke(
            CMD_ASSIST_ADOPT, CommandContext(projectOpen=True, writable=False)
        )
        self.assertFalse(readonly.ok)
        self.assertTrue(readonly.message)
        no_selection = registry.invoke(
            CMD_ASSIST_ADOPT, CommandContext(projectOpen=True, writable=True)
        )
        self.assertFalse(no_selection.ok)
        self.assertIn("采纳", no_selection.message)
        undo = registry.invoke(
            CMD_ASSIST_UNDO, CommandContext(projectOpen=True, writable=True)
        )
        self.assertFalse(undo.ok)
        self.assertTrue(undo.message)

    def test_overview_states_enhance_not_run_explicitly(self):
        overview = build_assist_overview(self.project)
        data = overview.to_dict()
        self.assertEqual(data["schemaVersion"], 1)
        self.assertIn("scope", data)
        self.assertFalse(data["enhanceAvailable"])
        self.assertIn("增强", data["enhanceReason"])
        lines = "\n".join(overview.summary_lines())
        self.assertIn("资料范围", lines)
        self.assertIn("陈旧", lines)
        self.assertTrue(data["enhanceReason"] == ENHANCE_NOT_RUN or "未执行" in data["enhanceReason"])
        registry = self._registry()
        invoked = registry.invoke(CMD_ASSIST_OVERVIEW, CommandContext(projectOpen=True))
        self.assertTrue(invoked.ok, invoked.message)
        self.assertEqual(invoked.value["schemaVersion"], 1)

    def test_overview_covers_stale_and_scope_notes(self):
        overview = build_assist_overview(self.project)
        self.assertIsInstance(overview.staleSources, int)
        self.assertIsInstance(overview.suggestionCoverage, list)
        self.assertIsInstance(overview.scope, list)
        self.assertTrue(overview.summary_lines())


if __name__ == "__main__":
    unittest.main(verbosity=2)