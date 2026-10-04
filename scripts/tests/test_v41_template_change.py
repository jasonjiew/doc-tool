# -*- coding: utf-8 -*-
"""V4.1 41-D：更换模板的差异预览、只改所选配置与固定包副本。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.template_sample import (  # noqa: E402
    RETAINED_PART_KEYS,
    apply_template_change,
    editable_copy,
    plan_template_change,
)

TEMPLATE_A = REPO_ROOT / "templates" / "requirement-template.docx"
TEMPLATE_B = REPO_ROOT / "templates" / "design-template.docx"
PACK = REPO_ROOT / "standards" / "generic-requirement"


class TemplateChangePlanTests(unittest.TestCase):
    """4.1：更换前展示真实身份、有效/失效映射、版式变化与保留部件边界。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-change-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_identities_use_real_source_and_summary(self):
        plan = plan_template_change(old_source=TEMPLATE_A, new_source=TEMPLATE_B)
        self.assertTrue(plan.ok, plan.warnings)
        self.assertNotEqual(plan.oldSummary, plan.newSummary, "不同底模摘要必须不同")
        self.assertIn("#", plan.oldIdentity)
        self.assertIn(str(TEMPLATE_A.name), plan.oldIdentity)
        self.assertIn(str(TEMPLATE_B.name), plan.newIdentity)
        self.assertFalse(plan.sameContent)

    def test_same_bytes_detected_but_config_change_visible(self):
        plan = plan_template_change(
            old_source=TEMPLATE_A, new_source=TEMPLATE_A,
            current_layout={"mode": "template"}, new_layout={"mode": "body-adaptive"},
        )
        self.assertTrue(plan.sameContent, "同一底模字节必须被识别")
        self.assertEqual(plan.layoutChanges, ["mode：template → body-adaptive"])
        text = "\n".join(plan.summary_lines())
        self.assertIn("配置变化但底模字节未变", text)

    def test_invalid_mapping_is_listed_as_dropped(self):
        plan = plan_template_change(
            old_source=TEMPLATE_A, new_source=TEMPLATE_B,
            current_mapping={"Heading1": 1, "Gone": 2, "Bad": 9},
            known_style_ids=["Heading1"],
        )
        self.assertEqual(plan.appliedMapping, {"Heading1": 1})
        self.assertTrue(plan.droppedMapping)
        joined = " ".join(plan.droppedMapping)
        self.assertIn("Gone", joined)
        self.assertIn("Bad", joined)
        self.assertIn("失效映射", "\n".join(plan.summary_lines()))

    def test_unsupported_declarations_are_not_claimed(self):
        plan = plan_template_change(
            old_source=TEMPLATE_A, new_source=TEMPLATE_B,
            current_layout={"mode": "template", "cover": "企业封面", "header": "页眉"},
        )
        self.assertEqual(sorted(plan.unsupported), ["cover", "header"])
        self.assertNotIn("cover", plan.newLayout)
        text = "\n".join(plan.summary_lines())
        self.assertIn("未支持声明", text)

    def test_retained_and_missing_parts_are_listed(self):
        plan = plan_template_change(
            old_source=PACK, new_source=TEMPLATE_B, new_pack_root=PACK,
        )
        self.assertTrue(plan.retainedParts, "应列出保留部件")
        self.assertTrue(set(plan.retainedParts) & set(RETAINED_PART_KEYS))
        self.assertEqual(plan.missingParts, [], "同一包不应有缺失部件")

    def test_missing_new_template_is_reported(self):
        plan = plan_template_change(old_source=TEMPLATE_A, new_source=self.work / "无.docx")
        self.assertFalse(plan.ok)
        self.assertTrue(plan.warnings)

    def test_missing_old_template_keeps_new_config_possible(self):
        plan = plan_template_change(old_source=self.work / "旧.docx", new_source=TEMPLATE_B)
        self.assertTrue(plan.ok)
        self.assertIn("旧模板已不存在", " ".join(plan.warnings))


class ApplyTemplateChangeTests(unittest.TestCase):
    """4.1/4.3：应用只改所选配置；固定包走制作副本。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-apply-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_apply_only_touches_selected_config(self):
        plan = plan_template_change(
            old_source=TEMPLATE_A, new_source=TEMPLATE_B,
            current_mapping={"Heading1": 1, "Gone": 2}, known_style_ids=["Heading1"],
            current_layout={"mode": "template"}, new_layout={"mode": "body-adaptive"},
        )
        outcome = apply_template_change(plan)
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertEqual(outcome.template, str(TEMPLATE_B))
        self.assertEqual(outcome.mapping, {"Heading1": 1})
        self.assertEqual(outcome.layout, {"mode": "body-adaptive"})
        text = "\n".join(outcome.summary_lines())
        self.assertIn("只改变模板配置", text)
        self.assertIn("新轮", text)

    @unittest.skipUnless(
        (PACK / "template.docx").is_file(),
        "规范包品牌底模不随仓库分发，跳过依赖它的用例",
    )
    def test_fixed_pack_creates_editable_copy_without_touching_original(self):
        original_files = sorted(
            path.relative_to(PACK).as_posix() for path in PACK.rglob("*") if path.is_file()
        )
        original_bytes = (PACK / "pack.yml").read_bytes()
        plan = plan_template_change(
            old_source=PACK, new_source=PACK / "template.docx", new_pack_root=PACK,
        )
        outcome = apply_template_change(
            plan, fixed_pack=True, drafts_dir=self.work / "drafts",
        )
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertTrue(outcome.draftPath, "固定包必须生成制作副本")
        draft = Path(outcome.draftPath)
        self.assertTrue(draft.is_dir())
        self.assertTrue((draft / "pack-draft.json").is_file(), "副本应带制作草稿记录")
        self.assertTrue((draft / "template.docx").is_file())
        # 原包一字未改
        after_files = sorted(
            path.relative_to(PACK).as_posix() for path in PACK.rglob("*") if path.is_file()
        )
        self.assertEqual(original_files, after_files)
        self.assertEqual((PACK / "pack.yml").read_bytes(), original_bytes)

    def test_copy_path_conflict_gets_new_name(self):
        plan = plan_template_change(
            old_source=PACK, new_source=TEMPLATE_B, new_pack_root=PACK,
        )
        drafts = self.work / "drafts"
        first, first_path, _ = editable_copy(PACK, drafts, name="副本")
        second, second_path, _ = editable_copy(PACK, drafts, name="副本")
        self.assertTrue(first is not None and second is not None)
        self.assertNotEqual(first_path, second_path, "同名副本必须换新名，不覆盖已有草稿")

    def test_apply_failed_plan_reports_reason(self):
        plan = plan_template_change(old_source=TEMPLATE_A, new_source=self.work / "无.docx")
        outcome = apply_template_change(plan)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.warnings)


class ReopenNavigationTests(unittest.TestCase):
    """4.3/4.4：更换前后不丢草稿与返回位置（服务层可重建事实）。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-nav-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_draft_survives_replan(self):
        """重复规划（用户来回切换模板）不产生副作用、草稿文件保持原样。"""
        drafts = self.work / "drafts"
        draft, path, error = editable_copy(PACK, drafts, name="草稿")
        self.assertEqual(error, "")
        marker = Path(path) / "pack-draft.json"
        before = marker.read_bytes()
        # 再次规划与查看差异都不应改动草稿
        for _ in range(3):
            plan = plan_template_change(
                old_source=TEMPLATE_B, new_source=TEMPLATE_A,
                new_pack_root=PACK,
            )
            plan_template_change(old_source=TEMPLATE_A, new_source=TEMPLATE_B)
        self.assertEqual(marker.read_bytes(), before, "规划不得改动既有制作草稿")
        payload = json.loads(marker.read_text(encoding="utf-8"))
        self.assertIn("packId", payload)

    def test_plan_is_repeatable_and_side_effect_free(self):
        first = plan_template_change(old_source=TEMPLATE_A, new_source=TEMPLATE_B)
        second = plan_template_change(old_source=TEMPLATE_A, new_source=TEMPLATE_B)
        self.assertEqual(first.to_dict(), second.to_dict(), "同一输入必须得到同一差异事实")


if __name__ == "__main__":
    unittest.main(verbosity=2)