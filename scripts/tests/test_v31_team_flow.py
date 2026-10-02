# -*- coding: utf-8 -*-
"""V3.1 31-E 串联流程测试：两目录交接模拟、冲突跳过、结果页与离屏双入口。"""

from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.command_registry import CommandContext, CommandRegistry  # noqa: E402
from doc_tool.application.content.team_entry import (  # noqa: E402
    CMD_HANDOFF_EXPORT, CMD_MY_TODOS, register_team_commands,
)
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402
from doc_tool.application.content.team_flow import run_team_flow  # noqa: E402


class TeamFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = fixtures.scratch_dir("team-flow")
        cls.source_project = fixtures.two_chapter_project(cls.shared / "source")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("team-flow-case")
        self.author = self.work / "author"
        self.receiver = self.work / "receiver"
        shutil.copytree(str(self.source_project), str(self.author))
        shutil.copytree(str(self.source_project), str(self.receiver))

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _chapter(self, project: Path, rel: str) -> Path:
        return project / "content" / "general" / rel

    def _first_two_chapters(self, project: Path):
        from doc_tool.application.effective_snapshot import discover_chapters

        rels = [rel for rel, _path in discover_chapters(project / "content" / "general")]
        self.assertGreaterEqual(len(rels), 2, rels)
        return rels[0], rels[1]

    def test_two_directory_handoff_partial_apply_skips_conflicts(self):
        """两目录/两作者模拟：作者改一章后导出，接收方在冲突章保留本地内容。"""
        first, second = self._first_two_chapters(self.author)
        # 双方共同基准 = 导入后的原始内容（作者改前的版本）
        baseline = {
            rel: self._chapter(self.author, rel).read_text(encoding="utf-8")
            for rel in (first, second)
        }
        # 作者侧两章都改，导出交接包
        self._chapter(self.author, first).write_text("作者侧修改后的内容。\n", encoding="utf-8")
        self._chapter(self.author, second).write_text("作者侧第二章新内容。\n", encoding="utf-8")
        page = run_team_flow(
            self.author, chapters=[first, second], handoff_dir=self.work / "handoff",
            baseline_texts=baseline,
        )
        self.assertTrue(page.hasUsableOutcome, page.summary_lines())
        self.assertTrue(page.artifacts, page.summary_lines())
        package = Path(page.artifacts[0])
        self.assertTrue(package.is_file())

        # 接收方在 first 章本地改过（制造冲突），second 章未改（应成功应用）
        self._chapter(self.receiver, first).write_text("接收方本地内容。\n", encoding="utf-8")
        applied = run_team_flow(self.receiver, package=package)
        self.assertFalse(applied.blocked, applied.summary_lines())
        # 一章冲突跳过、另一章应用成功
        self.assertTrue(any("已应用" in item for item in applied.processed), applied.to_dict())
        self.assertTrue(applied.conflicts or applied.skipped, applied.to_dict())
        self.assertEqual(
            self._chapter(self.receiver, second).read_text(encoding="utf-8"),
            "作者侧第二章新内容。\n",
        )
        # 冲突章保留本地内容（不被覆盖）
        self.assertEqual(
            self._chapter(self.receiver, first).read_text(encoding="utf-8"),
            "接收方本地内容。\n",
        )
        # 结果页结构完整且可序列化
        data = applied.to_dict()
        self.assertEqual(data["schemaVersion"], 1)
        for key in ("processed", "pending", "artifacts", "conflicts", "skipped", "steps"):
            self.assertIn(key, data)
        self.assertTrue(applied.summary_lines())

    def test_no_git_project_still_completes_and_reports_fallback(self):
        """无 Git 场景：仍可导出/应用，结果页说明使用本地历史，不整批阻断。"""
        first, _second = self._first_two_chapters(self.author)
        page = run_team_flow(self.author, chapters=[first], handoff_dir=self.work / "no-git-handoff")
        self.assertTrue(page.hasUsableOutcome, page.summary_lines())
        if not page.gitAvailable:
            self.assertTrue(any("本地历史" in line or "无 Git" in line for line in page.summary_lines()))
        steps = {item.name: item.status for item in page.steps}
        self.assertIn("handoff-export", steps)
        self.assertNotEqual(steps.get("handoff-export"), "failed")

    def test_result_page_lists_artifacts_and_pending_without_batch_block(self):
        first, second = self._first_two_chapters(self.author)
        page = run_team_flow(self.author, chapters=[first, second],
                             handoff_dir=self.work / "page-handoff", apply_selected=[first])
        self.assertFalse(page.blocked)
        self.assertTrue(page.artifacts)
        self.assertTrue(page.processed or page.pending)
        self.assertIsInstance(page.moduleSources, list)
        self.assertIsInstance(page.variantScope, list)

    def test_broken_project_is_blocked_with_reason(self):
        broken = self.work / "broken"
        broken.mkdir()
        page = run_team_flow(broken)
        self.assertTrue(page.blocked)
        self.assertTrue(page.warnings)
        self.assertFalse(page.hasUsableOutcome)


class NoGitHandoffTests(unittest.TestCase):
    """6.2：无 Git 目录下的两作者交接（夹具放在仓库之外的临时目录真实模拟）。"""

    def setUp(self):
        import shutil
        import tempfile

        self.root = Path(tempfile.mkdtemp(prefix="doc-tool-nogit-"))
        self.author = fixtures.two_chapter_project(self.root / "author")
        self.receiver = self.root / "receiver"
        shutil.copytree(str(self.author), str(self.receiver))

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.root), ignore_errors=True)

    def _rel(self, rel: str) -> Path:
        return self.author / "content" / "general" / rel

    def test_no_git_two_author_handoff_conflict_and_idempotency(self):
        from doc_tool.application.content.chapter_history import ChapterHistoryService
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(self.author)
        paths = ProjectPaths(self.author)
        service = ChapterHistoryService(
            self.author, paths.resolve(manifest.relative_content_root()), paths.state_dir,
        )
        self.assertIsNone(service.git_root(), "夹具应位于 Git 仓库之外（无 Git 场景）")

        rels = [rel for rel, _path in discover_chapters(self.author / "content" / "general")]
        first, second = rels[0], rels[1]
        baseline = {rel: self._rel(rel).read_text(encoding="utf-8") for rel in (first, second)}
        self._rel(first).write_text("作者侧修改（无 Git）。\n", encoding="utf-8")
        self._rel(second).write_text("作者侧第二章（无 Git）。\n", encoding="utf-8")

        exported = run_team_flow(
            self.author, chapters=[first, second],
            handoff_dir=self.root / "handoff", baseline_texts=baseline,
        )
        self.assertTrue(exported.artifacts, exported.summary_lines())
        self.assertFalse(exported.gitAvailable)
        self.assertTrue(
            any("本地历史" in line or "无 Git" in line for line in exported.summary_lines())
            or any("Git" in item for item in exported.warnings),
            exported.summary_lines(),
        )

        package = exported.artifacts[0]
        (self.receiver / "content" / "general" / first).write_text(
            "接收方本地内容（无 Git）。\n", encoding="utf-8",
        )
        applied = run_team_flow(self.receiver, package=package)
        self.assertFalse(applied.blocked, applied.summary_lines())
        self.assertTrue(any("已应用" in item for item in applied.processed), applied.to_dict())
        self.assertTrue(applied.conflicts or applied.skipped, applied.to_dict())
        # 冲突章保留接收方本地内容
        self.assertEqual(
            (self.receiver / "content" / "general" / first).read_text(encoding="utf-8"),
            "接收方本地内容（无 Git）。\n",
        )
        # 无冲突章应用成功
        self.assertEqual(
            (self.receiver / "content" / "general" / second).read_text(encoding="utf-8"),
            "作者侧第二章（无 Git）。\n",
        )

        # 重复导入幂等：内容不变、不重复写入
        again = run_team_flow(self.receiver, package=package)
        self.assertFalse(again.blocked)
        self.assertEqual(
            (self.receiver / "content" / "general" / second).read_text(encoding="utf-8"),
            "作者侧第二章（无 Git）。\n",
        )
        self.assertFalse(
            any("已应用：{0}".format(second) in item for item in again.processed),
            again.to_dict(),
        )


class OffscreenEntryTests(unittest.TestCase):
    """5.4：命令注册表可直接生成 Qt 菜单/面板并触发同一 handler（离屏）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("team-ui")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_menu_action_and_palette_item_share_handler(self):
        from PySide6.QtWidgets import QMenu

        registry = register_team_commands(CommandRegistry(self.work / "cfg"), self.project)
        context = CommandContext(projectOpen=True, writable=True)
        menu = QMenu()
        actions = {}
        for item in registry.menu_items(context):
            action = menu.addAction(item["title"])
            action.setEnabled(bool(item["available"]))
            actions[item["commandId"]] = (action, item)
        self.assertIn(CMD_MY_TODOS, actions)
        # 菜单动作触发 → 统一回调 → 真实服务
        result = registry.handle_item(actions[CMD_MY_TODOS][1], context)
        self.assertTrue(result.ok, result.message)
        self.assertIn("counts", result.value)
        # 面板条目与菜单项同状态
        palette = {item["commandId"]: item for item in registry.palette_items(context)}
        self.assertEqual(palette[CMD_MY_TODOS]["available"], actions[CMD_MY_TODOS][1]["available"])
        self.assertIn(CMD_HANDOFF_EXPORT, palette)
        menu.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)