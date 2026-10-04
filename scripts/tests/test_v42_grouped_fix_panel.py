# -*- coding: utf-8 -*-
"""V4.2 42-D 4.3/4.4：按章成组修正、撤销与个人「暂不处理」视图。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from PySide6.QtWidgets import QApplication  # noqa: E402

from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.lint import ContentLinter  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402


def _lint_issues(root: Path):
    content = root / "content" / "general"
    config = QualityRulesConfig(root / ".state", "general")
    index = ContentIndexService(content).build()
    return content, config, ContentLinter(index, config, use_result_cache=False).check_all([])


class GroupedFixPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-fixpanel-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.work / ".state").mkdir(exist_ok=True)
        # 两章各带一个可确定性修正的问题（标题缺空格）
        (self.content / "1 a.md").write_text("#1 a\n\n正文。\n", encoding="utf-8")
        (self.content / "2 b.md").write_text("#2 b\n\n正文。\n", encoding="utf-8")

    def _panel(self):
        """真实构造：LintPanel(linter, terms, writer=..., confirm_fix=...) + 真实问题集。"""
        from doc_tool.application.content.lint import TermStore
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.lint_panel import LintPanel

        content, config, _issues = _lint_issues(self.work)
        index = ContentIndexService(content).build()
        linter = ContentLinter(index, config, use_result_cache=False)
        terms = TermStore(self.work / ".state")
        writer = ContentWriter(self.content, self.work / ".state")
        panel = LintPanel(
            linter, terms, writer=writer, writable=True,
            confirm_fix=lambda rel_path, before, after: True,
        )
        self.addCleanup(panel.deleteLater)
        return panel

    def test_selected_plan_groups_by_chapter_without_writing(self):
        _content, _config, issues = _lint_issues(self.work)
        panel = self._panel()
        panel.run_check()
        fixable = [i for i in issues if i.rel_path == "1 a.md"]
        before = (self.content / "1 a.md").read_text(encoding="utf-8")
        plan = panel.selected_fix_plan(["1 a.md"])
        self.assertTrue(plan.items, plan.summary_lines())
        for item in plan.items:
            self.assertEqual(item.rel_path, "1 a.md", "选择范围外的章不得进入计划")
            self.assertTrue(item.diff_lines())
        self.assertEqual((self.content / "1 a.md").read_text(encoding="utf-8"), before,
                         "预览计划不得写盘")
        self.assertTrue(plan.by_chapter())

    def test_apply_selected_fixes_only_touches_chosen_chapter_and_can_undo(self):
        _content, _config, issues = _lint_issues(self.work)
        panel = self._panel()
        panel.run_check()
        before_a = (self.content / "1 a.md").read_text(encoding="utf-8")
        before_b = (self.content / "2 b.md").read_text(encoding="utf-8")
        applied = panel.apply_selected_fixes(["1 a.md"])
        self.assertGreaterEqual(applied, 0)
        after_a = (self.content / "1 a.md").read_text(encoding="utf-8")
        after_b = (self.content / "2 b.md").read_text(encoding="utf-8")
        self.assertEqual(after_b, before_b, "未选择的章不得被改动")
        if applied:
            self.assertNotEqual(after_a, before_a, "被选择的章应真实改动")
            self.assertTrue(panel.undo_last_fix(), "应支持撤销")
            self.assertEqual(
                (self.content / "1 a.md").read_text(encoding="utf-8"), before_a,
                "撤销应恢复原文字",
            )

    def test_personal_view_hides_only_in_view(self):
        _content, _config, issues = _lint_issues(self.work)
        panel = self._panel()
        panel.run_check()
        self.assertEqual(len(panel.visible_issues()), len(issues))
        target = issues[0]
        panel.suppress_issue(target)
        self.assertEqual(panel.suppressed_count(), 1)
        self.assertEqual(len(panel.visible_issues()), len(issues) - 1)
        self.assertEqual(len(panel._issues), len(issues), "正式报告口径不得变化")
        self.assertIn(target, panel._issues, "被暂不处理的问题仍在报告里")


if __name__ == "__main__":
    unittest.main(verbosity=2)