# -*- coding: utf-8 -*-
"""V2.8 28-F：内容版本评审与修订记录预填（6.1～6.5）。"""

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

from doc_tool.application.review.review_store import ReviewStore  # noqa: E402
from doc_tool.application.review.versioned_review import (  # noqa: E402
    STATUS_PASSED,
    STATUS_PENDING_FIX,
    STATUS_PENDING_RECHECK,
    STATUS_STALE,
    ReviewGatePolicy,
    append_revision_atomically,
    apply_content_change,
    build_revision_draft,
    confirm_comment,
    content_hash,
    legacy_status,
    request_recheck,
    stale_comment_ids,
)


class NewReviewFieldsTests(unittest.TestCase):
    """6.1：字段与旧台账兼容。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-review-"))
        self.store = ReviewStore(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_fields_persist_and_roundtrip(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        self.assertEqual(comment.lifecycle_status, STATUS_PENDING_FIX)
        self.store.update_comment(
            comment.comment_id, content_hash="abc", baseline_id="b1", package_id="p1"
        )
        loaded = self.store.comments()[0]
        self.assertEqual(loaded.content_hash, "abc")
        self.assertEqual(loaded.baseline_id, "b1")
        self.assertEqual(loaded.package_id, "p1")

    def test_legacy_ledger_without_new_fields_still_loads(self):
        (self.tmp / "reviews").mkdir(parents=True, exist_ok=True)
        payload = {
            "comments": [
                {
                    "comment_id": "old-1",
                    "text": "旧意见",
                    "author": "a",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "rel_path": "a.md",
                    "line_no": 1,
                    "status": "resolved",
                    "confirm_status": "已确认",
                }
            ]
        }
        (self.tmp / "reviews" / "comments.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        items = self.store.comments()
        self.assertEqual(len(items), 1)
        self.assertEqual(legacy_status(items[0]), STATUS_PASSED)

    def test_resolved_no_longer_auto_passes(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        updated = self.store.set_resolved(comment.comment_id, True)
        self.assertEqual(updated.lifecycle_status, STATUS_PENDING_RECHECK)
        self.assertEqual(updated.confirm_status, "待复核")


class ContentVersionTests(unittest.TestCase):
    """6.2：内容变化后待复核/失效，纯重命名只映射位置。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-ver-"))
        self.store = ReviewStore(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_bind_does_not_invalidate(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        apply_content_change(self.store, {"a.md": content_hash("内容 v1")})
        loaded = self.store.comments()[0]
        self.assertEqual(loaded.content_hash, content_hash("内容 v1"))
        self.assertNotEqual(legacy_status(loaded), STATUS_STALE)
        del comment

    def test_content_change_moves_passed_to_stale(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        self.store.update_comment(
            comment.comment_id, content_hash=content_hash("v1")
        )
        confirm_comment(self.store, comment.comment_id)
        self.assertEqual(legacy_status(self.store.comments()[0]), STATUS_PASSED)
        apply_content_change(self.store, {"a.md": content_hash("v2")})
        loaded = self.store.comments()[0]
        self.assertEqual(legacy_status(loaded), STATUS_STALE)
        self.assertTrue(loaded.stale_reason)

    def test_content_change_moves_pending_to_recheck(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        self.store.update_comment(comment.comment_id, content_hash=content_hash("v1"))
        apply_content_change(self.store, {"a.md": content_hash("v2")})
        self.assertEqual(legacy_status(self.store.comments()[0]), STATUS_PENDING_RECHECK)

    def test_pure_rename_maps_location_only(self):
        comment = self.store.add_comment("r1", "author", "old.md", 1)
        self.store.update_comment(comment.comment_id, content_hash=content_hash("v1"))
        confirm_comment(self.store, comment.comment_id)
        result = apply_content_change(
            self.store,
            {"new.md": content_hash("v1")},
            renamed={"old.md": "new.md"},
        )
        loaded = self.store.comments()[0]
        self.assertEqual(loaded.rel_path, "new.md")
        self.assertEqual(legacy_status(loaded), STATUS_PASSED, "纯重命名不应使已通过失效")
        self.assertIn(loaded.comment_id, result["remapped"])

    def test_stale_detection_reports_ids(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        self.store.update_comment(comment.comment_id, content_hash="old")
        ids = stale_comment_ids(self.store.comments(), {"a.md": "new"})
        self.assertEqual(ids, [comment.comment_id])

    def test_unicode_normalization_ignores_trailing_whitespace(self):
        self.assertEqual(content_hash("a  \nb"), content_hash("a\nb"))


class GateTests(unittest.TestCase):
    """6.3：默认提醒不阻断，严格策略才限制。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-gate-"))
        self.store = ReviewStore(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_policy_allows_with_reasons(self):
        self.store.add_comment("r1", "author", "a.md", 1)
        allowed, reasons = ReviewGatePolicy(strict=False).evaluate(self.store)
        self.assertTrue(allowed, "默认带提醒继续出稿")
        self.assertTrue(reasons)

    def test_strict_policy_blocks_until_confirmed(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        allowed, _ = ReviewGatePolicy(strict=True).evaluate(self.store)
        self.assertFalse(allowed)
        confirm_comment(self.store, comment.comment_id)
        allowed_after, _ = ReviewGatePolicy(strict=True).evaluate(self.store)
        self.assertTrue(allowed_after)

    def test_strict_policy_blocks_on_stale(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        self.store.update_comment(comment.comment_id, content_hash="v1")
        confirm_comment(self.store, comment.comment_id)
        apply_content_change(self.store, {"a.md": "v2"})
        allowed, reasons = ReviewGatePolicy(strict=True).evaluate(self.store)
        self.assertFalse(allowed)
        self.assertTrue(any("失效" in item for item in reasons))

    def test_recheck_request_never_passes(self):
        comment = self.store.add_comment("r1", "author", "a.md", 1)
        confirm_comment(self.store, comment.comment_id)
        request_recheck(self.store, comment.comment_id, note="请再看一遍")
        loaded = self.store.comments()[0]
        self.assertEqual(legacy_status(loaded), STATUS_PENDING_RECHECK)
        self.assertEqual(loaded.review_note, "请再看一遍")


class RevisionDraftTests(unittest.TestCase):
    """6.4：预填与原子追加。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-rev-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_draft_with_git_subjects(self):
        draft = build_revision_draft(
            ["1 概述", "2 设计"],
            current_version="1.2",
            commit_subjects=["修正接口", "补充用例"],
        )
        self.assertEqual(draft.version, "1.2.1")
        self.assertEqual(draft.source, "git")
        self.assertIn("修正接口", draft.to_row())

    def test_draft_without_git_uses_local_fallback(self):
        draft = build_revision_draft(["1 概述"], current_version="1.2")
        self.assertEqual(draft.source, "local")
        self.assertIn("本地改动", draft.to_row())

    def test_append_requires_confirmation(self):
        record = self.tmp / "_revision_record.md"
        record.write_text("| 版本 | 章节 | 说明 |\n", encoding="utf-8")
        draft = build_revision_draft(["1 概述"], current_version="1.0")
        self.assertFalse(append_revision_atomically(record, draft, confirmed=False))
        self.assertNotIn("1.0.1", record.read_text(encoding="utf-8"))
        self.assertTrue(append_revision_atomically(record, draft, confirmed=True))
        self.assertIn("1.0.1", record.read_text(encoding="utf-8"))

    def test_append_missing_record_is_noop(self):
        draft = build_revision_draft(["1"], current_version="1.0")
        self.assertFalse(
            append_revision_atomically(self.tmp / "nope.md", draft, confirmed=True)
        )


if __name__ == "__main__":
    unittest.main()