# -*- coding: utf-8 -*-
"""CORE-D 测试：章节范围、命名映射预设、Word/Markdown 文件批次。

对应验收 C-3/C-8 与任务 4.1-4.4。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    HeadingDecision, IntakePlan, IntakePolicy, PlannedTarget, SectionCandidate,
)
from doc_tool.application.intake_batch import (  # noqa: E402
    ITEM_FAILED, ITEM_OK, ITEM_PENDING_CONVERT, ITEM_SKIPPED,
    retry_word_batch, run_markdown_batch, run_word_batch,
)
from doc_tool.application.intake_entries import run_intake  # noqa: E402
from doc_tool.application.intake_presets import (  # noqa: E402
    IntakePresets, preset_file,
)
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.application.intake_scope import (  # noqa: E402
    chapter_dir_matches, prune_content_tree, selection_from_ids,
    selection_from_titles,
)


def _plan() -> IntakePlan:
    return IntakePlan(
        sections=[
            SectionCandidate("c1", "总述", level=1, order=0),
            SectionCandidate("c1-1", "接口", level=2, parent_id="c1", order=1),
            SectionCandidate("c2", "详述", level=1, order=2),
            SectionCandidate("c2-1", "参数", level=2, parent_id="c2", order=3),
        ]
    )


class ScopeTests(unittest.TestCase):
    def test_selection_keeps_ancestors_and_source_order(self):
        plan = _plan()
        selection = selection_from_titles(plan, ["参数"])
        self.assertEqual(selection.selected_titles, ["详述", "参数"])
        self.assertEqual(selection.added_ancestor_ids, ["c2"])
        self.assertFalse(selection.is_full)
        # 未选正文不会被自动加入
        self.assertNotIn("接口", selection.selected_titles)

    def test_missing_title_is_reported_not_silently_ignored(self):
        plan = _plan()
        selection_from_titles(plan, ["不存在的章节"])
        self.assertTrue(any("未匹配到章节" in item for item in plan.warnings))

    def test_directory_matching_tolerates_numbering_and_spaces(self):
        self.assertTrue(chapter_dir_matches("第1章 总述", "总述"))
        self.assertTrue(chapter_dir_matches("第2章详述", "详 述"))
        self.assertFalse(chapter_dir_matches("第2章 详述", "总述"))

    def test_prune_removes_unselected_and_notes_dangling(self):
        work = fixtures.scratch_dir("prune")
        try:
            content = work / "content"
            assets = work / "assets" / "general" / "images"
            assets.mkdir(parents=True, exist_ok=True)
            (content / "第1章 总述").mkdir(parents=True)
            (content / "第1章 总述" / "_index.md").write_text(
                "见第2章。\n\n![图](images/a.png)\n", encoding="utf-8",
            )
            (content / "第2章 详述").mkdir(parents=True)
            (content / "第2章 详述" / "_index.md").write_text("详述正文。\n", encoding="utf-8")
            selection = selection_from_ids(_plan(), ["c1"])
            result = prune_content_tree(content, selection, assets_root=assets)
            self.assertIn("第1章 总述", result.kept)
            self.assertIn("第2章 详述", result.removed)
            self.assertFalse((content / "第2章 详述").exists())
            self.assertTrue(any("第2章" in item for item in result.dangling_references))
            self.assertTrue(any("images/a.png" in item for item in result.missing_resources))
            self.assertTrue(any("未纳入范围" in line for line in result.summary_lines()))
        finally:
            fixtures.cleanup(work)

    def test_run_intake_with_selection_limits_chapters(self):
        work = fixtures.scratch_dir("scope-run")
        try:
            out = work / "out"
            out.mkdir(parents=True, exist_ok=True)
            source = fixtures.jump_level_docx(work / "范围.docx")
            full = run_intake(source, parent_dir=out)
            self.assertTrue(full.ok, full.errors)
            titles = [item.title for item in full.plan.sections]
            self.assertIn("详述", titles)
            partial = run_intake(
                source, parent_dir=out, target_name="范围项目",
                selected_sections=["详述"],
            )
            self.assertTrue(partial.ok, partial.errors)
            dirs = sorted(p.name for p in (Path(partial.project_root) / "content").rglob("*") if p.is_dir())
            self.assertTrue(any("详述" in name for name in dirs), dirs)
            self.assertFalse(any("总述" in name for name in dirs), dirs)
            self.assertTrue(any("范围：纳入" in item for item in partial.plan.warnings))
        finally:
            fixtures.cleanup(work)


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("preset")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_save_resolve_and_partial_match(self):
        store = IntakePresets(self.work)
        preset = store.save(
            "通用需求模板",
            {"Heading1": 1, "Custom9": 2},
            style_names={"Custom9": "自定义小节"},
        )
        self.assertEqual(preset_file(self.work).name, "intake-presets.json")
        self.assertNotEqual(preset_file(self.work).name, "template-fill-recipes.json")
        reloaded = IntakePresets(self.work)
        resolved = reloaded.resolve(reloaded.find("通用需求模板"), {
            "Heading1": "heading 1", "Other": "自定义小节",
        })
        self.assertEqual(resolved.mapping, {"Heading1": 1, "Other": 2})
        self.assertEqual(resolved.unmatched, [])
        self.assertIn("全部", resolved.summary_line())

    def test_unmatched_falls_back_and_is_reported(self):
        store = IntakePresets(self.work)
        store.save("旧预设", {"Gone1": 1})
        resolved = IntakePresets(self.work).resolve(store.find("旧预设"), {"Heading1": "heading 1"})
        self.assertTrue(resolved.used_fallback)
        self.assertFalse(resolved.has_mapping)
        self.assertTrue(any("失配" in item for item in resolved.warnings))

    def test_damaged_preset_file_is_quarantined(self):
        path = preset_file(self.work)
        path.write_text("{not json", encoding="utf-8")
        store = IntakePresets(self.work)
        self.assertEqual(store.presets, [])
        self.assertTrue(store.warnings)
        self.assertTrue(list(self.work.glob("intake-presets.json.damaged-*")))
        store.save("新预设", {"Heading1": 1})
        self.assertEqual(len(IntakePresets(self.work).presets), 1)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("batch")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_word_batch_partial_success_and_safe_names(self):
        first = fixtures.standard_docx(self.work / "同名.docx")
        second = fixtures.no_heading_docx(self.work / "同名.docx")
        # 两个不同目录下的同名文件：批次内项目名冲突要用安全后缀
        other = self.work / "sub"
        other.mkdir()
        second = fixtures.no_heading_docx(other / "同名.docx")
        broken = fixtures.broken_docx(self.work / "坏包.docx")
        result = run_word_batch([first, second, broken], parent_dir=self.out)
        statuses = [item.status for item in result.items]
        self.assertEqual(statuses.count(ITEM_OK), 2, result.summary_lines())
        self.assertEqual(statuses.count(ITEM_FAILED), 1)
        roots = [Path(item.project_root).name for item in result.succeeded]
        self.assertEqual(len(set(roots)), 2, roots)
        self.assertTrue(all(Path(item.project_root).is_dir() for item in result.succeeded))
        # 失败项可单独重试，成功项不重复登记
        retried = retry_word_batch(result)
        self.assertEqual([item.status for item in retried.items].count(ITEM_OK), 2)
        self.assertTrue(retried.retryable)
        self.assertTrue(any(item.attempts == 2 for item in retried.retryable))

    def test_word_batch_cancel_keeps_completed(self):
        from doc_tool.domain.cancellation import CancellationToken

        first = fixtures.standard_docx(self.work / "a.docx")
        second = fixtures.standard_docx(self.work / "b.docx")
        token = CancellationToken()

        def on_item(item):
            token.request_cancel()

        result = run_word_batch(
            [first, second], parent_dir=self.out, cancel_token=token, on_item=on_item,
        )
        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.succeeded), 1)
        cancelled_items = [item for item in result.items if item.status == "cancelled"]
        self.assertEqual(len(cancelled_items), 1)
        self.assertTrue(Path(result.succeeded[0].project_root).is_dir())

    def test_word_batch_marks_doc_pending_when_word_missing(self):
        doc = self.work / "旧格式.doc"
        doc.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
        good = fixtures.standard_docx(self.work / "good.docx")
        result = run_word_batch(
            [doc, good], parent_dir=self.out, word_available=False,
        )
        statuses = {Path(item.source).name: item.status for item in result.items}
        self.assertEqual(statuses["旧格式.doc"], ITEM_PENDING_CONVERT)
        self.assertEqual(statuses["good.docx"], ITEM_OK)

    def test_markdown_batch_builds_single_project_in_order(self):
        first = self.work / "1 概述.md"
        first.write_text("# 概述\n\n正文。\n![图](images/a.png)\n", encoding="utf-8")
        second = self.work / "2 设计.md"
        second.write_text("# 设计\n\n正文。\n", encoding="utf-8")
        assets = self.work / "res" / "images"
        assets.mkdir(parents=True)
        (assets / "a.png").write_bytes(b"png-bytes")
        missing = self.work / "3 缺失.md"
        result = run_markdown_batch(
            [first, second, missing], parent_dir=self.out,
            asset_roots=[self.work / "res"], document_name="合并项目",
        )
        statuses = [item.status for item in result.items]
        self.assertEqual(statuses.count(ITEM_OK), 1)
        self.assertEqual(statuses.count(ITEM_SKIPPED), 1)
        root = Path(result.succeeded[0].project_root)
        manifest_text = (root / "project.yml").read_text(encoding="utf-8")
        self.assertLess(manifest_text.index("1 概述.md"), manifest_text.index("2 设计.md"))
        # MAIN-A 1.3：Markdown 建项的资源根目录统一为 assets/<文档类型>/。
        self.assertTrue((root / "assets" / "general" / "images" / "a.png").is_file())
        self.assertEqual(
            ProjectManifest.load(root).paths.get("assetRoot"), "assets/general"
        )

    def test_batch_result_serializes_settings_for_retry(self):
        source = fixtures.standard_docx(self.work / "c.docx")
        result = run_word_batch([source], parent_dir=self.out)
        payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
        self.assertEqual(payload["settings"]["parentDir"], str(self.out))
        self.assertEqual(len(payload["succeeded"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)