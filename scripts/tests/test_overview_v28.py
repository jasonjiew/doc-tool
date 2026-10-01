# -*- coding: utf-8 -*-
"""项目概览聚合与建项入口（V2.8 28-E / 5.4、5.5）。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_project_build as T  # noqa: E402
from doc_tool.application.overview import build_overview  # noqa: E402


def _project(root: Path) -> str:
    T._setup_project(str(root))
    T._make_manifest(str(root)).save(str(root))
    return str(root)


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-overview-"))
        self.project = _project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_overview_has_all_required_sections(self):
        overview = build_overview(self.project)
        keys = {section.key for section in overview.sections}
        self.assertEqual(
            keys,
            {"version", "check", "content", "blocking", "review", "delivery"},
        )
        data = overview.to_dict()
        for key in (
            "projectRoot",
            "documentName",
            "documentVersion",
            "schemaVersion",
            "blockingCount",
            "pendingReviewCount",
            "checkStale",
            "sections",
            "nextActions",
        ):
            self.assertIn(key, data)
        self.assertTrue(overview.next_actions)

    def test_no_report_marks_check_stale_or_unchecked(self):
        overview = build_overview(self.project)
        section = {s.key: s for s in overview.sections}["check"]
        self.assertEqual(section.value, "未检查")
        self.assertTrue(overview.check_stale is False or overview.check_stale is True)
        self.assertTrue(any("检查" in action for action in overview.next_actions))

    def test_content_change_after_report_marks_stale(self):
        logs = Path(self.project) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        report = logs / "general-validation.md"
        report.write_text("# report", encoding="utf-8")
        chapter = next((Path(self.project) / "content").rglob("*.md"))
        time.sleep(0.01)
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n新增一行\n", encoding="utf-8")
        overview = build_overview(self.project)
        section = {s.key: s for s in overview.sections}["check"]
        self.assertEqual(section.value, "已过期")
        self.assertTrue(overview.check_stale)
        self.assertTrue(any("重新" in action for action in overview.next_actions))

    def test_report_newer_than_content_is_valid(self):
        chapter = next((Path(self.project) / "content").rglob("*.md"))
        time.sleep(0.01)
        logs = Path(self.project) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "general-validation.md").write_text("# report", encoding="utf-8")
        overview = build_overview(self.project)
        section = {s.key: s for s in overview.sections}["check"]
        self.assertEqual(section.value, "有效")
        self.assertFalse(overview.check_stale)
        del chapter

    def test_declared_chapter_missing_reported_but_not_fatal(self):
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(self.project)
        manifest.schemaVersion = 2
        manifest.chapters = ["2 不存在的章节.md"]
        manifest.save(self.project)
        overview = build_overview(self.project)
        section = {s.key: s for s in overview.sections}["content"]
        self.assertEqual(section.status, "warning")
        self.assertTrue(section.items)
        self.assertTrue(any("章节顺序" in action for action in overview.next_actions))

    def test_review_pending_default_does_not_block_publishing(self):
        from doc_tool.application.review.review_store import ReviewStore

        store = ReviewStore(Path(self.project) / ".state")
        store.add_comment("r1", "author", "content/requirement/1.md", 1)
        overview = build_overview(self.project)
        section = {s.key: s for s in overview.sections}["review"]
        self.assertEqual(section.status, "warning", "待评审默认只提醒，不阻断出稿")
        self.assertIn("默认带提醒", section.detail)

    def test_delivery_section_lists_latest_docx(self):
        output = Path(self.project) / "output"
        output.mkdir(parents=True, exist_ok=True)
        old = output / "旧产物(1.0).docx"
        new = output / "新产物(1.1).docx"
        old.write_bytes(b"a")
        time.sleep(0.01)
        new.write_bytes(b"b")
        overview = build_overview(self.project)
        section = {s.key: s for s in overview.sections}["delivery"]
        self.assertEqual(section.value, new.name)

    def test_overview_is_read_only(self):
        import hashlib

        chapter = next((Path(self.project) / "content").rglob("*.md"))
        before = hashlib.sha256(chapter.read_bytes()).hexdigest()
        build_overview(self.project)
        self.assertEqual(hashlib.sha256(chapter.read_bytes()).hexdigest(), before)

    def test_markdown_text_contains_sections_and_actions(self):
        text = build_overview(self.project).markdown_text()
        self.assertIn("项目概览", text)
        self.assertIn("下一步", text)
        self.assertIn("当前版本", text)


if __name__ == "__main__":
    unittest.main()