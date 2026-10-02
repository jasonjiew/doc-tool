# -*- coding: utf-8 -*-
"""V3.1 31-D/5.3 测试：命令注册表、双入口同状态与团队协作报告。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.command_registry import (  # noqa: E402
    CONTEXT_GIT, CONTEXT_IDLE, CONTEXT_PROJECT, CONTEXT_SELECTION, CONTEXT_WRITABLE,
    RECENT_SCHEMA_VERSION, CommandContext, CommandRegistry, CommandSpec, recent_file,
)
from doc_tool.application.content.team_entry import (  # noqa: E402
    CMD_ASSIGN, CMD_CHAPTER_HISTORY, CMD_HANDOFF_APPLY, CMD_HANDOFF_EXPORT,
    CMD_MY_TODOS, CMD_TEAM_REPORT, build_team_report, register_team_commands,
)


def _spec(command_id="demo.run", **kwargs) -> CommandSpec:
    payload = dict(
        commandId=command_id, title="演示命令", handler=lambda: "ok",
        aliases=["demo"], contexts=[CONTEXT_PROJECT],
    )
    payload.update(kwargs)
    return CommandSpec(**payload)


class CommandRegistryTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("registry")
        self.registry = CommandRegistry(self.work)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_stable_id_alias_and_duplicate_registration(self):
        spec = self.registry.register(_spec())
        self.assertEqual(spec.commandId, "demo.run")
        self.assertEqual(self.registry.resolve("demo.run").commandId, "demo.run")
        self.assertEqual(self.registry.resolve("DEMO").commandId, "demo.run")
        self.assertIsNone(self.registry.resolve("不存在"))
        # 同 ID 重复注册是幂等的（覆盖），顺序不变
        self.registry.register(_spec(title="改名后的命令"))
        self.assertEqual(len(self.registry.commands()), 1)
        self.assertEqual(self.registry.get("demo.run").title, "改名后的命令")

    def test_alias_conflict_and_empty_id_are_rejected(self):
        self.registry.register(_spec())
        with self.assertRaises(ValueError):
            self.registry.register(_spec(command_id="other.run"))
        with self.assertRaises(ValueError):
            self.registry.register(CommandSpec(commandId="", title="x"))

    def test_availability_reports_reason_and_next_action(self):
        spec = self.registry.register(CommandSpec(
            commandId="team.assign", title="分配", handler=lambda: None,
            contexts=[CONTEXT_PROJECT, CONTEXT_WRITABLE, CONTEXT_IDLE, CONTEXT_SELECTION],
        ))
        availability = self.registry.availability(spec, CommandContext())
        self.assertFalse(availability.available)
        self.assertTrue(availability.reason)
        self.assertTrue(availability.nextAction)
        self.assertIn(CONTEXT_PROJECT, availability.missing)
        ready = self.registry.availability(
            spec, CommandContext(projectOpen=True, writable=True, hasSelection=True)
        )
        self.assertTrue(ready.available)

    def test_declared_fallback_degrades_instead_of_blocking(self):
        spec = self.registry.register(CommandSpec(
            commandId="team.history", title="历史", handler=lambda: None,
            contexts=[CONTEXT_PROJECT, CONTEXT_GIT],
            fallbacks={CONTEXT_GIT: "无 Git：改用本地历史"},
        ))
        availability = self.registry.availability(spec, CommandContext(projectOpen=True))
        self.assertTrue(availability.available)
        self.assertIn("本地历史", availability.fallbackNote)

    def test_invoke_records_recent_and_wraps_failures(self):
        self.registry.register(_spec())
        result = self.registry.invoke("demo", CommandContext(projectOpen=True))
        self.assertTrue(result.ok)
        self.assertEqual(result.value, "ok")
        self.assertEqual(self.registry.recent_ids(), ["demo.run"])
        # 不可用：返回原因，不抛
        blocked = self.registry.invoke("demo", CommandContext())
        self.assertFalse(blocked.ok)
        self.assertTrue(blocked.message)
        # 处理器异常被包装
        self.registry.register(_spec(command_id="demo.boom", aliases=["boom"],
                                     handler=lambda: (_ for _ in ()).throw(RuntimeError("坏了"))))
        boom = self.registry.invoke("boom", CommandContext(projectOpen=True))
        self.assertFalse(boom.ok)
        self.assertEqual(boom.message, "坏了")
        # 未接实现
        self.registry.register(_spec(command_id="demo.todo", aliases=["todo"], handler=None))
        pending = self.registry.invoke("todo", CommandContext(projectOpen=True))
        self.assertFalse(pending.ok)
        self.assertIn("未接实现", pending.message)
        self.assertIsNone(self.registry.invoke("nope", CommandContext(projectOpen=True)).value)

    def test_handler_arity_is_adapted(self):
        self.registry.register(_spec(command_id="a.none", aliases=["none"], handler=lambda: "none"))
        self.registry.register(_spec(command_id="a.ctx", aliases=["ctx"], handler=lambda ctx: ctx.projectOpen))
        self.registry.register(_spec(command_id="a.both", aliases=["both"],
                                     handler=lambda ctx, payload: payload.get("n")))
        ctx = CommandContext(projectOpen=True)
        self.assertEqual(self.registry.invoke("none", ctx).value, "none")
        self.assertTrue(self.registry.invoke("ctx", ctx).value)
        self.assertEqual(self.registry.invoke("both", ctx, {"n": 7}).value, 7)

    def test_recent_cache_schema_and_corruption_fallback(self):
        self.registry.register(_spec())
        self.registry.record("demo.run")
        path = recent_file(self.work)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], RECENT_SCHEMA_VERSION)
        self.assertEqual(set(data["recent"][0]), {"commandId", "at"})
        # 重新加载后仍按最近使用排序
        reloaded = CommandRegistry(self.work)
        self.assertEqual(reloaded.recent_ids(), ["demo.run"])
        # 坏缓存：隔离 + 默认顺序 + 提醒，不影响可用
        path.write_text("{not json", encoding="utf-8")
        broken = CommandRegistry(self.work)
        self.assertTrue(broken.warnings)
        self.assertEqual(broken.recent_ids(), [])
        self.assertTrue(list(self.work.glob("recent-commands.json.damaged-*")))

    def test_menu_and_palette_share_state_with_legacy_entries(self):
        self.registry.register(CommandSpec(
            commandId="team.assign", title="分配负责人", handler=lambda: "assigned",
            aliases=["assign"], category="协作", shortcut="Ctrl+Shift+A",
            contexts=[CONTEXT_PROJECT, CONTEXT_WRITABLE],
        ))
        self.registry.append_legacy(CommandSpec(commandId="legacy.old", title="旧入口"))
        context = CommandContext(projectOpen=True, writable=False)
        menu = self.registry.menu_items(context)
        palette = self.registry.palette_items(context)
        menu_ids = [item["commandId"] for item in menu]
        palette_ids = [item["commandId"] for item in palette]
        # 菜单只放可用正式入口；面板是它的超集（含不可用项与旧入口）
        self.assertNotIn("team.assign", menu_ids, "只读时不可用项不应进菜单")
        self.assertNotIn("legacy.old", menu_ids, "旧入口不进主菜单")
        self.assertIn("team.assign", palette_ids)
        self.assertIn("legacy.old", palette_ids)
        assign = next(item for item in palette if item["commandId"] == "team.assign")
        self.assertFalse(assign["available"])
        self.assertTrue(assign["reason"] and assign["nextAction"])
        self.assertTrue(assign["paletteOnly"], "不可用项应标为面板专属")
        self.assertTrue(assign["keywords"] and assign["searchText"], "面板条目需带搜索字段")
        # 菜单里出现的每条命令，在面板里有完全相同的可用性与下一步
        for row in menu:
            twin = next(item for item in palette if item["commandId"] == row["commandId"])
            self.assertEqual(twin["available"], row["available"])
            self.assertEqual(twin["reason"], row["reason"])
            self.assertEqual(twin["nextAction"], row["nextAction"])
        # 未迁移的旧入口在面板中保持可达
        legacy = next(item for item in palette if item["commandId"] == "legacy.old")
        self.assertTrue(legacy["available"])
        # 同一条目经统一回调执行
        result = self.registry.handle_item(
            next(item for item in palette if item["commandId"] == "team.assign"),
            CommandContext(projectOpen=True, writable=True),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.value, "assigned")
        # 搜索过滤
        self.assertEqual(len(self.registry.palette_items(context, query="旧")), 1)

    def test_recent_order_keeps_other_commands_reachable(self):
        for index in range(3):
            self.registry.register(_spec(command_id="c{0}".format(index), aliases=["c{0}".format(index)]))
        self.registry.record("c2")
        ordered = [spec.commandId for spec in self.registry.ordered()]
        self.assertEqual(ordered[0], "c2")
        self.assertEqual(sorted(ordered), ["c0", "c1", "c2"])


class TeamEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("team-entry")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_report_is_json_serializable_and_actionable(self):
        report = build_team_report(self.project)
        data = json.loads(report.to_json())
        self.assertEqual(data["schemaVersion"], 1)
        self.assertIn("history", data)
        self.assertIn("assignments", data)
        self.assertTrue(data["nextActions"])
        self.assertTrue(report.summary_lines())
        # 未配置团队成员时给出提醒，但不阻断
        self.assertTrue(any("团队" in item or "Git" in item for item in report.warnings)
                        or report.gitAvailable)

    def test_registered_commands_share_one_handler(self):
        registry = register_team_commands(CommandRegistry(self.work / "cfg"), self.project)
        ids = [spec.commandId for spec in registry.commands()]
        for expected in (CMD_CHAPTER_HISTORY, CMD_MY_TODOS, CMD_ASSIGN,
                         CMD_HANDOFF_EXPORT, CMD_HANDOFF_APPLY, CMD_TEAM_REPORT):
            self.assertIn(expected, ids)
        context = CommandContext(projectOpen=True, writable=True)
        report = registry.invoke(CMD_TEAM_REPORT, context)
        self.assertTrue(report.ok, report.message)
        self.assertEqual(report.value["schemaVersion"], 1)
        todos = registry.invoke(CMD_MY_TODOS, context)
        self.assertTrue(todos.ok, todos.message)
        self.assertIn("counts", todos.value)
        history = registry.invoke("chapter-history", context)
        self.assertTrue(history.ok, history.message)
        self.assertTrue(history.value["chapter"])
        # 双入口同源：菜单是面板的子集，且可用性/原因逐条一致
        menu_rows = registry.menu_items(context)
        palette_rows = registry.palette_items(context)
        palette_ids = [item["commandId"] for item in palette_rows]
        for row in menu_rows:
            self.assertIn(row["commandId"], palette_ids)
            twin = next(item for item in palette_rows if item["commandId"] == row["commandId"])
            self.assertEqual(twin["available"], row["available"])
            self.assertEqual(twin["reason"], row["reason"])
        for cmd_id in (CMD_TEAM_REPORT, CMD_MY_TODOS):
            row = next(item for item in palette_rows if item["commandId"] == cmd_id)
            result = registry.handle_item(row, context)
            self.assertTrue(result.ok, result.message)

    def test_assign_requires_target_and_handoff_needs_package(self):
        registry = register_team_commands(CommandRegistry(self.work / "cfg"), self.project)
        context = CommandContext(projectOpen=True, writable=True, hasSelection=True)
        missing = registry.invoke(CMD_ASSIGN, context)
        self.assertFalse(missing.ok)
        self.assertIn("分配", missing.message)
        no_package = registry.invoke(CMD_HANDOFF_APPLY, context)
        self.assertFalse(no_package.ok)
        self.assertIn("交接包", no_package.message)

    def test_handoff_export_writes_real_package(self):
        registry = register_team_commands(CommandRegistry(self.work / "cfg"), self.project)
        target_dir = self.work / "handoff"
        result = registry.invoke(
            CMD_HANDOFF_EXPORT,
            CommandContext(projectOpen=True, writable=True),
            {"outputDir": str(target_dir)},
        )
        self.assertTrue(result.ok, result.message)
        # 交接包真实落在给定目录，返回的是实际产物路径（既有服务把 destination 当目录）
        self.assertTrue(Path(result.value["path"]).is_file(), result.value)
        self.assertEqual(Path(result.value["path"]).parent, target_dir)
        self.assertTrue(result.value["chapters"])
        # 交接后仍可生成报告（服务级可解析、后续队列可调用）
        report = build_team_report(self.project)
        self.assertIn("chapters", report.handoff)


if __name__ == "__main__":
    unittest.main(verbosity=2)