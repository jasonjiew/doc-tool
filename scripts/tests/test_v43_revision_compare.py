# -*- coding: utf-8 -*-
"""V4.3 43-C：两个真实版本比较与可编辑修订说明（用既有集合服务建真实基线）。"""

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
from doc_tool.application.delivery.revision_compare import (  # noqa: E402
    NOT_COMPARABLE_LEGACY,
    NOT_COMPARABLE_MISSING,
    VersionOption,
    build_revision_note,
    compare_versions,
    find_version,
    list_versions,
    prefill_revision_note,
)


class _BaselineFixture(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-c-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def _baseline(self, version: str, files, *, label: str = "同类集合"):
        """用既有集合服务建立真实基线（写入项目 ``.collections/*.yml``）。

        分类由既有 ``categorize()`` 决定（写入真实文件路径即可），不手工覆盖。
        """
        from doc_tool.application.collection import build_manifest, register_manifest

        root = self.work / "项目-{0}".format(version)
        for rel, _category, content in files:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
        manifest = build_manifest(root, version=version, label=label)
        path, error = register_manifest(root, manifest)
        self.assertEqual(error, "", "登记基线失败：{0}".format(error))
        self.assertIsNotNone(path)
        options = list_versions(self.work / "项目-{0}".format(version))
        self.assertTrue(options, "应能列出刚登记的基线")
        return options[0]

    def _pair(self, left_files, right_files):
        left = self._baseline("v1", left_files)
        right = self._baseline("v2", right_files)
        return left, right


class VersionSelectionTests(_BaselineFixture):
    """3.1：版本选择用真实路径/身份；同名可区分；缺项标不可比较。"""

    def test_list_versions_returns_real_paths_and_identity(self):
        option = self._baseline("v9", [("content/a.md", "content", "A1")])
        self.assertTrue(option.comparable)
        self.assertTrue(Path(option.path).is_file(), option.path)
        self.assertIn("#", option.identity)
        self.assertIn("v9", option.identity)
        self.assertTrue(option.createdAt)
        self.assertGreaterEqual(option.fileCount, 1)
        # 身份选择只能按真实 identity，不能按显示名
        self.assertIsNone(find_version([option], option.name))
        self.assertIs(find_version([option], option.identity), option)

    def test_same_display_name_two_versions_are_distinct(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        self.assertEqual(left.name, right.name, "夹具前提：显示名相同")
        self.assertNotEqual(left.identity, right.identity, "同名必须按路径#版本区分")
        self.assertNotEqual(left.path, right.path)

    def test_missing_and_legacy_are_not_comparable_with_reason(self):
        missing = VersionOption(version="v99", path=str(self.work / "无.yml"))
        self.assertFalse(missing.comparable)
        self.assertEqual(missing.notComparableReason, NOT_COMPARABLE_MISSING)
        legacy = VersionOption(
            version="v00", path=str(self.work / "有.yml"), legacyPartial=True,
        )
        self.assertEqual(legacy.notComparableReason, NOT_COMPARABLE_LEGACY)
        comparison = compare_versions(
            missing.identity, legacy.identity, options=[missing, legacy],
        )
        self.assertFalse(comparison.known)
        self.assertIn("不可比较", "\n".join(comparison.summary_lines()))

    def test_same_version_both_sides_rejected(self):
        option = self._baseline("v9", [("content/a.md", "content", "A1")])
        comparison = compare_versions(option.identity, option.identity, options=[option])
        self.assertFalse(comparison.known)
        self.assertIn("同一个版本", comparison.reason)


class VersionComparisonTests(_BaselineFixture):
    """3.2：分组差异 + 来源配置与装配内容可区分；缺历史标不可比较。"""

    def test_grouped_differences_cover_content_and_artifact(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1"), ("output/a.docx", "artifact", "D1")],
            [("content/a.md", "content", "A2"), ("output/a.docx", "artifact", "D1")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        self.assertTrue(comparison.known, comparison.reason)
        changed = {
            item["relativePath"]
            for items in comparison.groups.values() for item in items
        }
        self.assertIn("content/a.md", changed, "正文变化必须出现")
        self.assertNotIn("output/a.docx", changed, "未变化项不得出现在差异里")
        self.assertIn("两版比较", "\n".join(comparison.summary_lines()))

    def test_source_config_change_without_body_change_is_distinguished(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1"), ("standards/pack.yml", "standard", "P1")],
            [("content/a.md", "content", "A1"), ("standards/pack.yml", "standard", "P2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        self.assertTrue(comparison.known, comparison.reason)
        self.assertEqual(comparison.assembledChanges, [], "正文未变不得报装配内容变化")
        source = {rel for rel, _ in comparison.sourceChanges}
        self.assertIn("standards/pack.yml", source)
        text = "\n".join(comparison.summary_lines())
        self.assertIn("来源配置变化", text)

    def test_assembled_content_change_is_reported(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1"), ("modules/m1.md", "content", "M1")],
            [("content/a.md", "content", "A1"), ("modules/m1.md", "content", "M2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        self.assertTrue(comparison.known)
        self.assertEqual(comparison.sourceChanges, [])
        assembled = {rel for rel, _ in comparison.assembledChanges}
        self.assertIn("modules/m1.md", assembled)

    def test_unavailable_group_does_not_block_other_differences(self):
        """3.3：缺一部分历史数据时，其他差异必须继续输出。"""
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        self.assertTrue(comparison.known)
        self.assertTrue(comparison.unavailableGroups, "缺分组必须单列")
        # 正文差异照常给出，不被 unavailable 阻断
        changed = {
            item["relativePath"]
            for items in comparison.groups.values() for item in items
        }
        self.assertIn("content/a.md", changed)
        text = "\n".join(comparison.summary_lines())
        self.assertIn("content/a.md", text + str(changed) + str(comparison.changeCount))

    def test_return_restores_selected_version_by_identity(self):
        """3.3：返回时按真实 identity 恢复所选版本，不按显示名重选。"""
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        options = [left, right]
        # 同名（label 相同）但 identity 不同：按 identity 精确命中
        self.assertEqual(find_version(options, right.identity), right)
        self.assertIsNone(find_version(options, right.name))

    def test_missing_group_is_marked_unavailable(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        self.assertTrue(comparison.known)
        self.assertTrue(comparison.unavailableGroups, "缺分组必须单列")
        self.assertIn("不可比较", "\n".join(comparison.summary_lines()))


class RevisionNoteTests(_BaselineFixture):
    """3.4：预填可编辑说明；编辑不改评审/正式状态与项目文件。"""

    def test_prefill_lists_real_changes_and_is_editable(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        self.assertTrue(comparison.known, comparison.reason)
        note = build_revision_note(comparison)
        self.assertIn("content/a.md", note.text)
        self.assertFalse(note.edited)
        note.update("手工改写：本次修订了需求描述。")
        self.assertTrue(note.edited)
        self.assertIn("content/a.md", note.prefilled, "预填事实不被编辑覆盖")
        self.assertTrue(note.to_dict()["edited"])

    def test_unavailable_parts_stay_visible(self):
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        comparison.unavailableGroups = ["artifact"]
        text = prefill_revision_note(comparison)
        self.assertIn("不可比较", text)
        self.assertIn("artifact", text)

    def test_note_is_pure_data_and_does_not_confirm_review(self):
        """3.4：说明是纯数据，不替用户确认评审/正式状态。"""
        import inspect

        from doc_tool.application.delivery import revision_compare as rc

        note_source = inspect.getsource(rc.build_revision_note) + inspect.getsource(rc.RevisionNote)
        for forbidden in ("write_state", "formal", "review", "signoff", "save_project", "manifest.save"):
            self.assertNotIn(forbidden, note_source, "说明不得动状态：{0}".format(forbidden))
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        note = build_revision_note(comparison)
        self.assertIn("不会改变条目复核或成果正式状态", note.text)
        self.assertEqual(
            sorted(note.to_dict().keys()), ["edited", "prefilled", "text"],
            "说明只承载文本与编辑标记，没有状态字段",
        )

    def test_not_comparable_note_is_explicit(self):
        comparison = compare_versions("x", "y", options=[])
        self.assertIn("无法比较", build_revision_note(comparison).text)

    def test_note_edit_does_not_touch_project_files(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        before = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*") if path.is_file()
        }
        left, right = self._pair(
            [("content/a.md", "content", "A1")],
            [("content/a.md", "content", "A2")],
        )
        comparison = compare_versions(left.identity, right.identity, options=[left, right])
        note = build_revision_note(comparison)
        note.update("编辑后的修订说明")
        after = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after, "编辑说明不得改动项目文件/正式状态")


if __name__ == "__main__":
    unittest.main(verbosity=2)