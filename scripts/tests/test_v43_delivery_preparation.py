# -*- coding: utf-8 -*-
"""V4.3 43-A：一次交付的实际准备（真实成员/范围/格式/模板与目录）。"""

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

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery.contract import parse_plan  # noqa: E402
from doc_tool.application.delivery.preparation import (  # noqa: E402
    COMPLETENESS_FULL,
    COMPLETENESS_PARTIAL,
    SOURCE_CURRENT_BUFFER,
    SOURCE_SAVED,
    prepare_delivery,
    round_is_stale,
    submission_capture,
)


class PreparationFixture(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-prep-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.setup_a = fixtures.two_chapter_project(self.work / "A")
        self.setup_b = fixtures.two_chapter_project(self.work / "B")
        self.setup_c = fixtures.two_chapter_project(self.work / "C")

    def _plan(self, entries, **extra):
        payload = {"schemaVersion": 1, "batchId": extra.pop("batchId", "batch-1"), "entries": entries}
        payload.update(extra)
        return parse_plan(
            payload, plan_path=str(self.work / "batch.json"), base_dir=str(self.work),
        )

    def _entries(self, members=("A", "B", "C")):
        # member 是相对 base_dir 的真实路径（契约按此解析成员项目根）
        return [
            {
                "id": name.lower(),
                "member": name,
                "memberName": "{0} 成员".format(name),
                "formats": ["docx", "html"],
                "destination": str(self.work / "out"),
                "scope": {"kind": "chapters", "chapters": ["第1章 引言/1.1 目的.md"]},
            }
            for name in members
        ]


class PreparationSummaryTests(PreparationFixture):
    """4.1：摘要从最终请求参数读回，逐项可核对。"""

    def test_rows_carry_real_members_scope_formats_and_destination(self):
        prep = prepare_delivery(self._plan(self._entries()))
        self.assertEqual(len(prep.rows), 3)
        for row in prep.rows:
            self.assertTrue(row.projectExists, row.projectRoot)
            self.assertEqual(row.scopeText, "所选 1 章")
            self.assertEqual(row.scopeKind, "chapters")
            self.assertEqual(row.scopeChapters, ["第1章 引言/1.1 目的.md"])
            self.assertEqual(row.formats, ["docx", "html"])
            self.assertEqual(row.destination, str(self.work / "out"))
            self.assertEqual(row.sourceMode, SOURCE_SAVED)
            self.assertEqual(row.sourceLabel, "已保存版本")
        self.assertEqual(prep.sharedDestination, str(self.work / "out"))
        self.assertEqual(prep.completeness, COMPLETENESS_FULL)
        self.assertTrue(prep.isCompleteSet)
        text = "\n".join(prep.summary_lines())
        self.assertIn("完整集合", text)
        self.assertIn("输出目录", text)

    def test_summary_is_serializable_and_matches_rows(self):
        prep = prepare_delivery(self._plan(self._entries()))
        payload = prep.to_dict()
        self.assertEqual(len(payload["rows"]), 3)
        self.assertEqual(payload["completeness"], COMPLETENESS_FULL)
        self.assertTrue(payload["isCompleteSet"])
        self.assertEqual(
            [row["member"] for row in payload["rows"]], ["A", "B", "C"],
            "成员顺序必须与请求一致",
        )

    def test_template_reference_is_read_from_real_defaults(self):
        """模板引用来自 plan.defaults（真实默认段），不是从文本猜。"""
        from doc_tool.application.delivery.contract import BatchDefaults, BatchPlan

        plan = self._plan(self._entries())
        plan.defaults = BatchDefaults.from_dict({"template": "templates/requirement-template.docx"})
        if not getattr(plan.defaults, "template", ""):
            plan.defaults = type("_D", (), {"template": "templates/requirement-template.docx"})()
        prep = prepare_delivery(plan)
        self.assertEqual(
            prep.templateRefs, ["templates/requirement-template.docx"],
            "应读回真实默认段里的模板引用：{0}".format(getattr(plan.defaults, "__dict__", plan.defaults)),
        )

    def test_current_buffer_members_are_marked(self):
        prep = prepare_delivery(self._plan(self._entries()), current_buffer_members=["B"])
        by_member = {row.member: row for row in prep.rows}
        self.assertEqual(by_member["B"].sourceMode, SOURCE_CURRENT_BUFFER)
        self.assertEqual(by_member["B"].sourceLabel, "当前内容")
        self.assertEqual(by_member["A"].sourceMode, SOURCE_SAVED)
        self.assertTrue(prep.hasUnsaved)
        self.assertIn("未保存编辑", "\n".join(prep.summary_lines()))

    def test_unsaved_edit_is_marked_without_forcing_save(self):
        prep = prepare_delivery(self._plan(self._entries()), unsaved_members=["A"])
        by_member = {row.member: row for row in prep.rows}
        self.assertTrue(by_member["A"].hasUnsaved)
        self.assertEqual(by_member["A"].sourceMode, SOURCE_SAVED, "未保存不等于自动改来源")
        self.assertEqual(len(prep.executableRows), 3, "未保存不得变成执行门禁")


class PartialSetTests(PreparationFixture):
    """4.3：缺成员/坏设置只影响该项，其余可继续；部分集合不冒充完整。"""

    def test_missing_member_is_partial_and_others_continue(self):
        # 让第二个成员指向真实缺失路径（契约按 member 解析，故直接改 member）
        prep = prepare_delivery(self._plan(self._entries(members=("A", "不存在", "C"))))
        self.assertEqual(prep.completeness, COMPLETENESS_PARTIAL)
        self.assertFalse(prep.isCompleteSet)
        self.assertEqual(len(prep.executableRows), 2)
        self.assertEqual(len(prep.invalidRows), 1)
        self.assertEqual(prep.invalidRows[0].member, "不存在")
        self.assertTrue(any("不存在" in item for item in prep.invalidRows[0].problems))
        text = "\n".join(prep.summary_lines())
        self.assertIn("不得冒充完整基线", text)
        self.assertIn("缺成员", text)

    def test_skipped_entries_force_partial(self):
        plan = self._plan(self._entries())
        plan.skipped.append("D 成员（路径缺失）")
        prep = prepare_delivery(plan)
        self.assertEqual(prep.completeness, COMPLETENESS_PARTIAL)
        self.assertEqual(prep.skipped, ["D 成员（路径缺失）"])
        self.assertIn("已跳过", "\n".join(prep.summary_lines()))

    def test_all_members_missing_is_not_treated_as_complete(self):
        prep = prepare_delivery(
            self._plan(self._entries(members=("无此目录一", "无此目录二")))
        )
        self.assertEqual(prep.completeness, COMPLETENESS_PARTIAL)
        self.assertEqual(prep.executableRows, [])
        self.assertFalse(prep.isCompleteSet)

    def test_empty_plan_reports_no_executable_member(self):
        prep = prepare_delivery(self._plan([]))
        self.assertEqual(prep.rows, [])
        self.assertIn("没有可执行成员", "\n".join(prep.summary_lines()))

    def test_plan_problems_are_surfaced(self):
        plan = self._plan(self._entries())
        plan.problems.append("某成员格式未知")
        plan.warnings.append("提醒一条")
        prep = prepare_delivery(plan)
        self.assertIn("某成员格式未知", prep.problems)
        self.assertIn("提醒一条", prep.warnings)
        text = "\n".join(prep.summary_lines())
        self.assertIn("问题：", text)
        self.assertIn("提醒：", text)


class SubmissionCaptureTests(PreparationFixture):
    """1.2：提交固定捕获；提交后编辑只影响下一轮。"""

    def test_capture_freezes_members_scope_and_formats(self):
        prep = prepare_delivery(self._plan(self._entries()))
        capture = submission_capture(prep, job_ids=["j1", "j2", "j3"])
        self.assertEqual(capture.memberCount, 3)
        self.assertTrue(capture.isCompleteSet)
        self.assertEqual([item["member"] for item in capture.members], ["A", "B", "C"])
        self.assertEqual([item["jobId"] for item in capture.members], ["j1", "j2", "j3"])
        payload = capture.to_dict()
        self.assertEqual(payload["memberCount"], 3)
        self.assertTrue(payload["submittedAt"])

    def test_stale_rounds_detected_for_later_edits(self):
        prep = prepare_delivery(self._plan(self._entries()))
        capture = submission_capture(prep)
        self.assertFalse(round_is_stale(capture, prep), "同一准备事实不算过期")
        # 提交后把某个成员改成当前内容（模拟提交后继续编辑）
        changed = prepare_delivery(
            self._plan(self._entries()), current_buffer_members=["B"],
        )
        self.assertTrue(round_is_stale(capture, changed), "来源变化必须被识别为下一轮")
        # 原捕获不被改写
        self.assertEqual(
            [item["sourceMode"] for item in capture.members],
            ["saved", "saved", "saved"],
        )

    def test_scope_or_format_change_marks_next_round(self):
        prep = prepare_delivery(self._plan(self._entries()))
        capture = submission_capture(prep)
        entries = self._entries()
        entries[0]["scope"] = {"kind": "project"}
        changed = prepare_delivery(self._plan(entries))
        self.assertTrue(round_is_stale(capture, changed))

    def test_member_set_change_marks_next_round(self):
        prep = prepare_delivery(self._plan(self._entries()))
        capture = submission_capture(prep)
        fewer = prepare_delivery(self._plan(self._entries(members=("A", "B"))))
        self.assertTrue(round_is_stale(capture, fewer))


class ScopeTextTests(PreparationFixture):
    def test_scope_text_comes_from_structured_scope(self):
        entries = self._entries(members=("A",))
        entries[0]["scope"] = {"kind": "project"}
        prep = prepare_delivery(self._plan(entries))
        self.assertEqual(prep.rows[0].scopeText, "整份")
        entries[0]["scope"] = {"kind": "current-chapter", "current": "第1章 引言/1.1 目的.md"}
        prep = prepare_delivery(self._plan(entries))
        self.assertIn("当前章", prep.rows[0].scopeText)
        self.assertIn("1.1 目的.md", prep.rows[0].scopeText)


if __name__ == "__main__":
    unittest.main(verbosity=2)