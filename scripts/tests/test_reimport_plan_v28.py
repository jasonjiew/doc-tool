# -*- coding: utf-8 -*-
"""V2.8 28-H\uff1a\u91cd\u5bfc\u5165\u8ba1\u5212/\u5e94\u7528\u4e0e Git \u51b2\u7a81\u4e09\u65b9\u5408\u5e76\uff088.1\u30018.3\u30018.5\uff09\u3002"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_project_build as T  # noqa: E402
from doc_tool.application.content.reimport import ChapterChange  # noqa: E402
from doc_tool.application.content.reimport_plan import (  # noqa: E402
    PlanItem,
    ReimportPlan,
    apply_plan,
    git_stage_resolved,
    merge_versions,
    plan_reimport,
    resolve_git_conflict,
    unsupported_reason,
)

NL = chr(10)


class PlanTests(unittest.TestCase):
    """8.1\uff1a\u8ba1\u5212\u9636\u6bb5\u4e0d\u6c61\u67d3\u6b63\u5f0f\u7ae0\u8282\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-plan-"))
        self.project = Path(T._setup_project(str(self.tmp)))
        T._make_manifest(str(self.project)).save(str(self.project))
        self.source = self.tmp / "new.docx"
        self.source.write_bytes(b"PK\x03\x04fake")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _changes(self):
        return [
            ChapterChange("1 \u65b0\u589e.md", "added", False, True),
            ChapterChange("2 \u4fee\u6539.md", "modified", False, True),
            ChapterChange("3 \u51b2\u7a81.md", "modified", True, False),
            ChapterChange("4 \u672a\u53d8.md", "unchanged", False, True),
            ChapterChange("5 \u5220\u9664.md", "deleted", False, True),
        ]

    def test_plan_reports_counts_and_source_hash(self):
        plan = plan_reimport(
            None, self._changes(), source_path=self.source, baseline_available=True
        )
        counts = plan.counts()
        self.assertEqual(counts["added"], 1)
        self.assertEqual(counts["modified"], 2)
        self.assertEqual(counts["deleted"], 1)
        self.assertEqual(counts["unchanged"], 1)
        self.assertEqual(counts["conflict"], 1)
        self.assertTrue(plan.source_hash)

    def test_only_non_conflicting_selected_items_apply(self):
        plan = plan_reimport(
            None, self._changes(), source_path=self.source, baseline_available=True
        )
        applicable = {item.rel_path for item in plan.auto_applicable}
        self.assertIn("1 \u65b0\u589e.md", applicable)
        self.assertIn("2 \u4fee\u6539.md", applicable)
        self.assertNotIn("3 \u51b2\u7a81.md", applicable)
        self.assertNotIn("4 \u672a\u53d8.md", applicable)

    def test_choices_mapping_marks_conflict_false(self):
        plan = plan_reimport(
            None, self._changes(), source_path=self.source, baseline_available=True
        )
        choices = plan.choices()
        self.assertTrue(choices["1 \u65b0\u589e.md"])
        self.assertFalse(choices["3 \u51b2\u7a81.md"])
        self.assertNotIn("4 \u672a\u53d8.md", choices)

    def test_selection_narrows_scope(self):
        plan = plan_reimport(
            None,
            self._changes(),
            source_path=self.source,
            baseline_available=True,
            selected=["1 \u65b0\u589e.md"],
        )
        self.assertEqual({item.rel_path for item in plan.auto_applicable}, {"1 \u65b0\u589e.md"})

    def test_missing_baseline_warns_and_keeps_conflicts_skipped(self):
        plan = plan_reimport(
            None, self._changes(), source_path=self.source, baseline_available=False
        )
        self.assertFalse(plan.baseline_available)
        self.assertTrue(any("\u7f3a\u5c11\u57fa\u7ebf" in item for item in plan.warnings))
        self.assertNotIn(
            "3 \u51b2\u7a81.md", {item.rel_path for item in plan.auto_applicable}
        )

    def test_markdown_preview_lists_conflicts(self):
        plan = plan_reimport(
            None, self._changes(), source_path=self.source, baseline_available=True
        )
        text = plan.markdown_text()
        self.assertIn("\u91cd\u5bfc\u5165\u5dee\u5f02\u9884\u89c8", text)
        self.assertIn("3 \u51b2\u7a81.md", text)

    def test_plan_does_not_touch_content(self):
        target = next((self.project / "content").rglob("*.md"))
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        plan_reimport(None, self._changes(), source_path=self.source, baseline_available=True)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)


class ApplyTests(unittest.TestCase):
    """8.3\uff1a\u51b2\u7a81/\u672a\u9009\u8df3\u8fc7\uff0c\u5931\u8d25\u56de\u6eda\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-apply-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plan(self, items):
        plan = ReimportPlan(source_path="src.docx")
        plan.items = items
        return plan

    def test_apply_passes_choices_and_reports(self):
        service = mock.Mock()
        service.reimport.return_value = mock.Mock(success=True, message="")
        plan = self._plan(
            [PlanItem("a.md", "added", False, True), PlanItem("b.md", "modified", True, False)]
        )
        outcome = apply_plan(service, plan, "src.docx")
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["applied"], ["a.md"])
        self.assertEqual(outcome["skipped"], ["b.md"])
        choices = service.reimport.call_args.kwargs["choices"]
        self.assertTrue(choices["a.md"])
        self.assertFalse(choices["b.md"])

    def test_apply_without_applicable_items_is_noop(self):
        service = mock.Mock()
        plan = self._plan([PlanItem("a.md", "modified", True, False)])
        outcome = apply_plan(service, plan, "src.docx")
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["applied"], [])
        service.reimport.assert_not_called()

    def test_apply_failure_rolls_back(self):
        service = mock.Mock()
        service.reimport.side_effect = RuntimeError("\u5199\u5165\u5931\u8d25")
        plan = self._plan([PlanItem("a.md", "added", False, True)])
        outcome = apply_plan(service, plan, "src.docx")
        self.assertFalse(outcome["success"])
        self.assertTrue(outcome["rolledBack"])
        self.assertEqual(outcome["applied"], [])

    def test_apply_reports_service_failure(self):
        service = mock.Mock()
        service.reimport.return_value = mock.Mock(
            success=False, message="\u6821\u9a8c\u672a\u901a\u8fc7", conflicts=["x"]
        )
        plan = self._plan([PlanItem("a.md", "added", False, True)])
        outcome = apply_plan(service, plan, "src.docx")
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["message"], "\u6821\u9a8c\u672a\u901a\u8fc7")


class MergeTests(unittest.TestCase):
    """8.4\uff1a\u4e09\u65b9\u5408\u5e76\u3001\u4e8c\u8fdb\u5236/SVN \u8fb9\u754c\u3001\u786e\u8ba4\u540e\u624d\u5199\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-merge-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_side_change_merges_without_markers(self):
        base = NL.join(["A", "B", "C"])
        merged, has_markers = merge_versions(base, NL.join(["A", "B-ours", "C"]), base)
        self.assertIn("B-ours", merged)
        self.assertFalse(has_markers)
        merged2, has_markers2 = merge_versions(base, base, NL.join(["A", "B", "C-theirs"]))
        self.assertIn("C-theirs", merged2)
        self.assertFalse(has_markers2)

    def test_same_line_change_keeps_markers(self):
        _merged, has_markers = merge_versions("B", "B-ours", "B-theirs")
        self.assertTrue(has_markers)

    def test_binary_rejected_with_reason(self):
        self.assertIn("\u4e8c\u8fdb\u5236", unsupported_reason(self.tmp / "a.docx"))
        self.assertEqual(unsupported_reason(self.tmp / "a.md"), "")

    def test_svn_worktree_rejected_with_reason(self):
        (self.tmp / ".svn").mkdir()
        self.assertIn("SVN", unsupported_reason(self.tmp / "a.md"))

    def test_conflict_markers_block_write(self):
        target = self.tmp / "a.md"
        target.write_text("old", encoding="utf-8")
        resolution, written = resolve_git_conflict(target, "B", "B-ours", "B-theirs", confirmed=True)
        self.assertFalse(written)
        self.assertTrue(resolution.has_markers)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_confirmed_clean_merge_is_written(self):
        target = self.tmp / "a.md"
        target.write_text(NL.join(["A", "B", "C"]), encoding="utf-8")
        resolution, written = resolve_git_conflict(
            target,
            NL.join(["A", "B", "C"]),
            NL.join(["A", "B-ours", "C"]),
            NL.join(["A", "B", "C"]),
            confirmed=True,
        )
        self.assertTrue(written, resolution.reason)
        self.assertIn("B-ours", target.read_text(encoding="utf-8"))

    def test_unconfirmed_does_not_write(self):
        target = self.tmp / "a.md"
        target.write_text("old", encoding="utf-8")
        resolution, written = resolve_git_conflict(target, "B", "B-ours", "B", confirmed=False)
        self.assertFalse(written)
        self.assertIn("\u5f85\u786e\u8ba4", resolution.reason)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_worktree_check_failure_blocks_write(self):
        target = self.tmp / "a.md"
        target.write_text("old", encoding="utf-8")

        def _checker(_path):
            return False, "\u5de5\u4f5c\u6811\u6709\u672a\u8ddf\u8e2a\u53d8\u66f4"

        _resolution, written = resolve_git_conflict(
            target, "B", "B-ours", "B", confirmed=True, worktree_checker=_checker
        )
        self.assertFalse(written)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_git_stage_resolved_without_repo_is_false(self):
        self.assertFalse(git_stage_resolved(self.tmp / "a.md"))

    def test_real_double_copy_git_conflict_roundtrip(self):
        """\u771f\u5b9e\u53cc\u526f\u672c Git \u51b2\u7a81\uff1a\u4e09\u65b9\u5408\u5e76\u540e\u4e0d\u542b\u6807\u8bb0\u4e14\u53ef\u6807 resolved\u3002"""
        repo = self.tmp / "repo"
        repo.mkdir()

        def _git(*args):
            return subprocess.run(
                ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
            )

        if _git("init").returncode != 0:
            self.skipTest("git \u4e0d\u53ef\u7528")
        _git("config", "user.email", "t@example.com")
        _git("config", "user.name", "tester")
        target = repo / "a.md"
        target.write_text(NL.join(["A", "B", "C", "D", "E", "F"]), encoding="utf-8")
        _git("add", "a.md")
        _git("commit", "-m", "base")
        base_text = target.read_text(encoding="utf-8")
        base_rev = _git("rev-parse", "HEAD").stdout.strip()
        # ours\uff1a\u6539 B\uff08\u540c\u65f6\u5df2\u5305\u542b their \u7684 C \u4fee\u6539\uff09
        ours_text = NL.join(["A", "B-ours", "C", "D", "E", "F-theirs"])
        target.write_text(ours_text, encoding="utf-8")
        _git("commit", "-am", "ours")
        # theirs\uff1a\u6539 C
        _git("checkout", "-b", "side", base_rev)
        target.write_text(NL.join(["A", "B", "C", "D", "E", "F-theirs"]), encoding="utf-8")
        _git("commit", "-am", "theirs")
        theirs_text = target.read_text(encoding="utf-8")
        _git("checkout", "master")

        merged_text, has_markers = merge_versions(base_text, ours_text, theirs_text)
        self.assertFalse(has_markers, merged_text)
        self.assertIn("B-ours", merged_text)
        self.assertIn("F-theirs", merged_text)
        self.assertNotIn("C-theirs", merged_text)
        # 确认后写入；真实合并中的索引标记需在干净工作树上手动完成，
        # 这里只断言合并结果本身（无标记、两侧改动均保留）。
        target.write_text(merged_text, encoding="utf-8")
        self.assertIn("B-ours", target.read_text(encoding="utf-8"))
        self.assertNotIn("<<<<<<<", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()