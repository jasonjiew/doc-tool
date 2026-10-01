# -*- coding: utf-8 -*-
"""V2.8 2.2：章节排序事务与界面顺序（服务层）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.chapter_reorder import (  # noqa: E402
    apply_reorder,
    display_order,
    plan_reorder,
)


class DisplayOrderTests(unittest.TestCase):
    def test_display_order_matches_build_order_contract(self):
        discovered = ["3 附录.md", "1 概述.md", "2 设计.md"]
        order = display_order(discovered, ["1 概述.md", "2 设计.md"])
        self.assertEqual(order.ordered, ["1 概述.md", "2 设计.md", "3 附录.md"])

    def test_display_order_without_declaration_keeps_scan_order(self):
        discovered = ["2 设计.md", "1 概述.md"]
        self.assertEqual(display_order(discovered).ordered, discovered)


class RenumberPlanTests(unittest.TestCase):
    def test_plan_renumbers_by_target_order(self):
        plan = plan_reorder(["3 附录.md", "1 概述.md", "2 设计.md"])
        mapping = dict(plan.renames)
        # 目标顺序：3 附录 → 1、1 概述 → 2、2 设计 → 3
        self.assertEqual(mapping["3 附录.md"], "1 附录.md")
        self.assertEqual(mapping["1 概述.md"], "2 概述.md")
        self.assertEqual(mapping["2 设计.md"], "3 设计.md")

    def test_un_numbered_files_get_numbers(self):
        plan = plan_reorder(["结论.md"])
        self.assertEqual(dict(plan.renames)["结论.md"], "1 结论.md")

    def test_renumber_off_keeps_names(self):
        plan = plan_reorder(["2 设计.md", "1 概述.md"], renumber=False)
        self.assertFalse(plan.renames)
        self.assertEqual(plan.unchanged, ["2 设计.md", "1 概述.md"])

    def test_already_correct_order_reports_unchanged(self):
        plan = plan_reorder(["1 概述.md", "2 设计.md"])
        self.assertFalse(plan.renames)
        self.assertEqual(plan.unchanged, ["1 概述.md", "2 设计.md"])

    def test_subdirectory_paths_preserved(self):
        plan = plan_reorder(["a/2 设计.md", "a/1 概述.md"])
        mapping = dict(plan.renames)
        self.assertEqual(mapping["a/2 设计.md"], "a/1 设计.md")
        self.assertEqual(mapping["a/1 概述.md"], "a/2 概述.md")

    def test_reference_edits_counted_from_refactor_service(self):
        service = mock.Mock()
        service.compute_batch_rename_plan.return_value = mock.Mock(conflicts=[], edits=[1, 2, 3])
        plan = plan_reorder(["2 设计.md", "1 概述.md"], refactor_service=service)
        self.assertEqual(plan.reference_edits, 3)
        self.assertTrue(plan.can_apply)

    def test_conflict_from_refactor_service_blocks(self):
        service = mock.Mock()
        service.compute_batch_rename_plan.return_value = mock.Mock(conflicts=["目标文件已存在"], edits=[])
        plan = plan_reorder(["2 设计.md", "1 概述.md"], refactor_service=service)
        self.assertIn("目标文件已存在", plan.conflicts)
        self.assertFalse(plan.can_apply)

    def test_none_rename_plan_blocks(self):
        service = mock.Mock()
        service.compute_batch_rename_plan.return_value = None
        plan = plan_reorder(["2 设计.md", "1 概述.md"], refactor_service=service)
        self.assertTrue(plan.conflicts)

    def test_plan_markdown_lists_renames(self):
        text = plan_reorder(["2 设计.md", "1 概述.md"]).markdown_text()
        self.assertIn("章节排序计划", text)
        self.assertIn("2 设计.md", text)


class ApplyReorderTests(unittest.TestCase):
    def test_conflict_blocks_apply_without_touching_service(self):
        service = mock.Mock()
        plan = plan_reorder(["2 设计.md", "1 概述.md"])
        plan.conflicts = ["目标文件已存在"]
        outcome = apply_reorder(plan, service, mock.Mock())
        self.assertFalse(outcome["success"])
        self.assertIn("冲突", outcome["message"])
        service.compute_batch_rename_plan.assert_not_called()

    def test_no_renames_is_noop(self):
        service = mock.Mock()
        outcome = apply_reorder(plan_reorder(["1 概述.md"]), service, mock.Mock())
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["renamed"], [])
        service.compute_batch_rename_plan.assert_not_called()

    def test_apply_uses_refactor_transaction(self):
        writer = mock.Mock()
        service = mock.Mock()
        rename_plan = mock.Mock(can_apply=True, conflicts=[], edits=[1, 2])
        service.compute_batch_rename_plan.return_value = rename_plan
        plan = plan_reorder(["2 设计.md", "1 概述.md"])
        outcome = apply_reorder(plan, service, writer)
        self.assertTrue(outcome["success"], outcome["message"])
        self.assertEqual(outcome["referenceEdits"], 2)
        service.apply_rename_plan.assert_called_once_with(rename_plan, writer)

    def test_apply_reports_conflict_from_service_plan(self):
        service = mock.Mock()
        service.compute_batch_rename_plan.return_value = mock.Mock(
            can_apply=False, conflicts=["目标文件已存在"], edits=[]
        )
        plan = plan_reorder(["2 设计.md", "1 概述.md"])
        outcome = apply_reorder(plan, service, mock.Mock())
        self.assertFalse(outcome["success"])
        service.apply_rename_plan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
