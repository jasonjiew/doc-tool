# -*- coding: utf-8 -*-
"""V4.2 42-D：规则试跑不隐式保存、成组修正与个人视图。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content import quality_workbench as qw  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.lint import ContentLinter  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402


class _Issue:
    def __init__(self, rel_path, line_no, rule_id, severity="warning", message="问题"):
        self.rel_path = rel_path
        self.line_no = line_no
        self.rule_id = rule_id
        self.rule = rule_id
        self.severity = severity
        self.message = message
        self.suggested_action = "按建议修正"


class RuleTrialTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-trial-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.work / ".state").mkdir(exist_ok=True)
        (self.content / "1 a.md").write_text("# A\n\nTODO: 待办\n", encoding="utf-8")
        (self.content / "2 b.md").write_text("# B\n\n正文。\n", encoding="utf-8")
        self.config = QualityRulesConfig(self.work / ".state", "general")
        self.index = ContentIndexService(self.content).build()
        self.baseline = ContentLinter(
            self.index, self.config, use_result_cache=False
        ).check_all([])

    def _trial(self, *, rule_id="todo_residual", field="enabled", value=False):
        def _factory():
            # 试跑用临时配置：不写盘、不改正式配置
            config = QualityRulesConfig(self.work / ".state", "general")
            rules = list(config.load())
            for rule in rules:
                if rule.rule_id == rule_id:
                    setattr(rule, field, value)
            from doc_tool.application.content.lint import ContentLinter as _Linter

            class _Cfg:
                def rule_map(self_inner):
                    return {rule.rule_id: rule for rule in rules}

            return _Linter(self.index, _Cfg(), use_result_cache=False)

        return qw.trial_rule(
            _factory, rule_id=rule_id, field=field, value=value,
            before_value="True", baseline_issues=self.baseline,
        )

    def test_trial_compares_real_change_without_saving(self):
        before_rules = {rule.rule_id: rule.enabled for rule in self.config.load()}
        trial = self._trial(value=False)
        self.assertTrue(trial.executed)
        self.assertTrue(trial.known)
        self.assertFalse(trial.comparison.known is False)
        # 关闭 todo 规则后该规则的问题应消失
        self.assertTrue(trial.comparison.removed, "关闭规则应让相关问题消失")
        self.assertEqual(trial.comparison.added, [])
        after_rules = {rule.rule_id: rule.enabled for rule in self.config.load()}
        self.assertEqual(before_rules, after_rules, "试跑不得隐式保存")
        text = "\n".join(trial.summary_lines())
        self.assertIn("未保存设置前不会改变正式规则", text)

    def test_unsupported_field_is_not_executed(self):
        trial = self._trial(field="params", value={"x": 1})
        self.assertFalse(trial.executed)
        self.assertIn("不支持试跑", trial.reason)
        self.assertIn("未执行", "\n".join(trial.summary_lines()))

    def test_missing_baseline_is_unknown(self):
        def _factory():
            return ContentLinter(self.index, self.config, use_result_cache=False)

        trial = qw.trial_rule(
            _factory, rule_id="todo_residual", field="enabled", value=False,
            baseline_issues=None,
        )
        self.assertFalse(trial.known)
        self.assertIn("未知", "\n".join(trial.summary_lines()))

    def test_severity_change_is_supported(self):
        trial = self._trial(field="severity", value="error")
        self.assertTrue(trial.executed)
        self.assertTrue(trial.known)

    def test_unsupported_rule_fields_reported(self):
        class _Rule:
            rule_id = "r"
            enabled = True
            severity = "warning"
            params = {"threshold": 3}

        reported = qw.unsupported_rule_fields(_Rule())
        self.assertIn("threshold", reported, "未知参数应被列出而不是静默丢弃")


class GroupedFixTests(unittest.TestCase):
    def test_plan_groups_by_chapter_and_skips_conflicts(self):
        plan = qw.GroupedFixPlan(items=[
            qw.GroupedFixItem("1 a.md", 3, "##标题", "## 标题", ruleId="heading_format"),
            qw.GroupedFixItem("1 a.md", 9, "```", "```\nx", ruleId="markdown_structure"),
            qw.GroupedFixItem("2 b.md", 1, "-x", "- x", ruleId="markdown_structure"),
        ])
        plan.skipped.append(qw.GroupedFixItem(
            "2 b.md", 5, "旧", "新", ruleId="todo_residual",
            applicable=False, reason="正文已变化",
        ))
        grouped = plan.by_chapter()
        self.assertEqual(sorted(grouped), ["1 a.md", "2 b.md"])
        self.assertEqual(len(grouped["1 a.md"]), 2)
        text = "\n".join(plan.summary_lines())
        self.assertIn("可应用 3 项，跳过 1 项", text)
        self.assertIn("正文已变化", text)
        self.assertEqual(plan.items[0].diff_lines(), ["- ##标题", "+ ## 标题"])

    def test_undo_marker(self):
        plan = qw.GroupedFixPlan(items=[qw.GroupedFixItem("1 a.md", 3, "a", "b")])
        plan.undone = True
        self.assertIn("撤销", "\n".join(plan.summary_lines()))

    def test_personal_view_hides_only_in_view(self):
        issues = [
            _Issue("1 a.md", 3, "todo_residual"),
            _Issue("1 a.md", 9, "markdown_structure"),
        ]
        result = qw.personal_view(issues, [("1 a.md", 3, "todo_residual")])
        self.assertEqual(len(result["visible"]), 1)
        self.assertEqual(len(result["suppressed"]), 1)
        self.assertEqual(result["total"], 2, "正式报告口径总量不变")
        self.assertIn("正式报告仍保留全部 2 条", result["note"])
        self.assertEqual(len(issues), 2, "原集合不得被改写")


if __name__ == "__main__":
    unittest.main(verbosity=2)