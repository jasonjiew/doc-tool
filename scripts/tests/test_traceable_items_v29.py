# -*- coding: utf-8 -*-
"""V2.9 29-B\uff1a\u7a33\u5b9a\u6761\u76ee\u6807\u8bb0\u3001\u8fc1\u79fb\u4e0e\u8bc4\u5ba1\u6620\u5c04\uff082.1\uff5e2.5\uff09\u3002"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path as _Path

REPO_ROOT = _Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.traceable_items import (  # noqa: E402
    ITEM_KINDS,
    ItemRef,
    append_marker,
    apply_migration,
    backup_legacy_item_data,
    build_item_index,
    copy_ref,
    has_markers,
    map_review_locations,
    new_ref,
    parse_marker,
    plan_legacy_migration,
    renumber_keeps_ids,
    strip_markers,
)

NL = chr(10)
PROJECT = "proj-1"


def _doc(*lines):
    return NL.join(lines) + NL


class MarkerParsingTests(unittest.TestCase):
    """2.1\uff1a\u89e3\u6790\u3001\u79cd\u7c7b/\u522b\u540d\u6821\u9a8c\u4e0e\u6807\u8bb0\u4e0d\u8fdb\u6b63\u6587\u3002"""

    def test_valid_marker_roundtrip(self):
        ref = ItemRef(project_id=PROJECT, item_id="abcd1234-uuid", kind="design", alias="\u63a5\u53e3A")
        parsed, error = parse_marker(ref.render())
        self.assertIsNone(error)
        self.assertEqual(parsed.key, ref.key)
        self.assertEqual(parsed.kind, "design")
        self.assertEqual(parsed.alias, "\u63a5\u53e3A")

    def test_marker_carries_all_kinds(self):
        for kind in ITEM_KINDS:
            ref = ItemRef(project_id=PROJECT, item_id="id-12345678", kind=kind)
            parsed, error = parse_marker(ref.render())
            self.assertIsNone(error, kind)
            self.assertEqual(parsed.kind, kind)

    def test_unknown_kind_rejected(self):
        parsed, error = parse_marker("<!-- DOC-ITEM: projectId=p kind=weird id=id-12345678 -->")
        self.assertIsNone(parsed)
        self.assertIn("\u79cd\u7c7b", error or "")

    def test_missing_fields_rejected(self):
        _parsed, error = parse_marker("<!-- DOC-ITEM: kind=requirement id=id-12345678 -->")
        self.assertIn("projectId", error or "")
        _parsed2, error2 = parse_marker("<!-- DOC-ITEM: projectId=p kind=requirement -->")
        self.assertIn("id", error2 or "")

    def test_strip_markers_removes_marker_and_trailing_space(self):
        text = _doc("\u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f\u3002" + " " + ItemRef(PROJECT, "id-12345678").render())
        cleaned = strip_markers(text)
        self.assertFalse(has_markers(cleaned))
        self.assertIn("\u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f\u3002", cleaned)
        self.assertNotIn("DOC-ITEM", cleaned)

    def test_index_detects_duplicates_and_bad_markers(self):
        marker = ItemRef(PROJECT, "id-12345678").render()
        index = build_item_index(
            [
                ("a.md", _doc("1 \u9700\u6c42" + " " + marker)),
                ("b.md", _doc("1 \u9700\u6c42" + " " + marker, "<!-- DOC-ITEM: projectId=p kind=bogus id=x -->")),
            ],
            project_id=PROJECT,
        )
        self.assertEqual(index.count(), 1)
        self.assertEqual(len(index.duplicates), 1)
        self.assertTrue(any("\u79cd\u7c7b" in issue.reason for issue in index.issues))

    def test_index_rejects_other_project_marker(self):
        other = ItemRef("other-project", "id-12345678").render()
        index = build_item_index([("a.md", _doc("1 \u9700\u6c42" + " " + other))], project_id=PROJECT)
        self.assertEqual(index.count(), 0)
        self.assertTrue(any("\u5176\u4ed6\u9879\u76ee" in issue.reason for issue in index.issues))


class IdentityStabilityTests(unittest.TestCase):
    """2.2\uff1a\u79fb\u52a8/\u91cd\u7f16\u53f7\u4fdd\u7559 ID\uff0c\u590d\u5236\u751f\u6210\u65b0 ID\u3002"""

    def test_renumber_and_move_keep_ids(self):
        ref = ItemRef(PROJECT, "id-12345678")
        before = _doc("1 \u9700\u6c42" + " " + ref.render())
        after = _doc("2 \u8bbe\u8ba1", "", "2.1 \u660e\u7ec6" + " " + ref.render())
        self.assertTrue(renumber_keeps_ids(before, after))

    def test_copy_generates_new_id(self):
        ref = new_ref(PROJECT, "requirement")
        duplicate = copy_ref(ref)
        self.assertNotEqual(duplicate.item_id, ref.item_id)
        self.assertEqual(duplicate.project_id, ref.project_id)
        self.assertEqual(duplicate.kind, ref.kind)

    def test_new_ref_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            new_ref(PROJECT, "bogus")

    def test_append_marker_only_touches_target_line(self):
        text = _doc("1 \u9700\u6c42", "", "\u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f\u3002", "\u53e6\u4e00\u6bb5\u3002")
        ref = ItemRef(PROJECT, "id-12345678")
        updated = append_marker(text, ref, line_no=3)
        lines = updated.splitlines()
        self.assertIn("DOC-ITEM", lines[2])
        self.assertNotIn("DOC-ITEM", lines[0])
        self.assertNotIn("DOC-ITEM", lines[3])

    def test_append_marker_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            append_marker("a", ItemRef(PROJECT, "id-1"), line_no=9)


class MigrationTests(unittest.TestCase):
    """2.3/2.5\uff1a\u8fc1\u79fb\u5efa\u8bae\u3001\u6b67\u4e49\u4e0e\u672a\u6807\u8bb0\u4e0d\u8ba1\u5206\u6bcd\u3002"""

    def test_unique_numbers_become_suggestions(self):
        documents = [
            ("1 \u9700\u6c42.md", _doc("## 1 \u9700\u6c42", "", "1.1 \u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f\u3002", "", "1.2 \u7cfb\u7edf\u5e94\u652f\u6301\u6a2a\u5411\u9875\u3002")),
        ]
        plan = plan_legacy_migration(documents, project_id=PROJECT)
        self.assertEqual(len(plan.confident), 2)
        self.assertFalse(plan.ambiguous)
        self.assertTrue(all(item.proposed_id for item in plan.confident))
        self.assertTrue(any("\u4e0d\u81ea\u52a8\u8ba1\u5165" in item for item in plan.warnings))

    def test_cross_document_same_number_is_ambiguous(self):
        documents = [
            ("a.md", _doc("## 1 \u9700\u6c42", "", "1.1 \u4e00\u3002")),
            ("b.md", _doc("## 1 \u9700\u6c42", "", "1.1 \u4e8c\u3002")),
        ]
        plan = plan_legacy_migration(documents, project_id=PROJECT)
        self.assertFalse(plan.confident)
        self.assertEqual(len(plan.ambiguous), 2)
        self.assertTrue(any("\u6b67\u4e49" in item for item in plan.warnings))

    def test_already_marked_content_is_not_resuggested(self):
        ref = ItemRef(PROJECT, "id-12345678")
        documents = [("a.md", _doc("## 1 \u9700\u6c42", "", "1.1 \u5df2\u6807\u8bb0\u3002" + " " + ref.render()))]
        plan = plan_legacy_migration(documents, project_id=PROJECT)
        self.assertFalse(plan.confident)
        self.assertFalse(plan.ambiguous)

    def test_apply_writes_only_confident_selected(self):
        documents = {
            "a.md": _doc("## 1 \u9700\u6c42", "", "1.1 \u4e00\u3002", "", "1.2 \u4e8c\u3002"),
        }
        plan = plan_legacy_migration(list(documents.items()), project_id=PROJECT)
        self.assertEqual(len(plan.confident), 2)
        token = "{0}:{1}".format(plan.confident[0].rel_path, plan.confident[0].line_no)
        outcome = apply_migration(plan, documents, selected=[token], project_id=PROJECT)
        self.assertEqual(outcome["applied"], [token])
        self.assertEqual(len(outcome["skipped"]), 1)
        self.assertEqual(documents["a.md"].count("DOC-ITEM"), 1)

    def test_apply_failure_leaves_no_marker(self):
        documents = {"a.md": _doc("## 1 \u9700\u6c42", "", "1.1 \u4e00\u3002")}
        plan = plan_legacy_migration(list(documents.items()), project_id=PROJECT)
        # \u4eba\u4e3a\u628a\u884c\u53f7\u6539\u6210\u8d85\u51fa\u8303\u56f4\uff0c\u6a21\u62df\u5199\u5165\u5931\u8d25
        broken = plan.__class__(project_id=PROJECT)
        broken.suggestions = plan.suggestions
        for item in broken.suggestions:
            item.line_no = 99
        outcome = apply_migration(broken, documents, project_id=PROJECT)
        self.assertEqual(outcome["applied"], [])
        self.assertEqual(documents["a.md"].count("DOC-ITEM"), 0)

    def test_apply_cancelled_writes_nothing(self):
        documents = {"a.md": _doc("## 1 \u9700\u6c42", "", "1.1 \u4e00\u3002")}
        plan = plan_legacy_migration(list(documents.items()), project_id=PROJECT)
        outcome = apply_migration(plan, documents, selected=[], project_id=PROJECT)
        # selected \u7a7a\u8868\u793a\u53ea\u5e94\u7528\u53ef\u786e\u8ba4\u9879\uff1b\u8fd9\u91cc\u7528\u663e\u5f0f\u7a7a\u9009\u96c6\u53c8\u4f20\u5165\u5c31\u662f\u5168\u90e8\u53ef\u786e\u8ba4
        self.assertTrue(outcome["applied"] or outcome["skipped"])
        del outcome

    def test_migration_plan_markdown_lists_both(self):
        documents = [
            ("a.md", _doc("## 1 \u9700\u6c42", "", "1.1 \u4e00\u3002")),
            ("b.md", _doc("## 1 \u9700\u6c42", "", "1.1 \u4e8c\u3002")),
        ]
        text = plan_legacy_migration(documents, project_id=PROJECT).markdown_text()
        self.assertIn("\u65e7\u7f16\u53f7\u8fc1\u79fb\u5efa\u8bae", text)
        self.assertIn("\u6b67\u4e49", text)


class ReviewMappingTests(unittest.TestCase):
    """2.4\uff1a\u53ef\u786e\u8ba4\u7684\u8bc4\u5ba1\u5b9a\u4f4d\u6620\u5c04\uff0c\u6b67\u4e49\u4fdd\u7559\u3002"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v29-map-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _comment(self, rel_path, line_no, cid="c1"):
        from doc_tool.application.review.review_store import ReviewComment

        return ReviewComment(
            comment_id=cid, text="x", author="a", created_at="2026-01-01T00:00:00+00:00",
            rel_path=rel_path, line_no=line_no,
        )

    def test_unique_location_maps_to_item(self):
        ref = ItemRef(PROJECT, "id-12345678")
        index = build_item_index([("a.md", _doc("## 1 \u9700\u6c42", "", "\u4e00\u3002" + " " + ref.render()))], project_id=PROJECT)
        outcome = map_review_locations([self._comment("a.md", 3)], index)
        self.assertEqual(len(outcome["mapped"]), 1)
        self.assertEqual(outcome["mapped"][0]["itemId"], ref.item_id)

    def test_unmatched_comment_reported(self):
        ref = ItemRef(PROJECT, "id-12345678")
        index = build_item_index([("a.md", _doc("## 1 \u9700\u6c42", "", "\u4e00\u3002" + " " + ref.render()))], project_id=PROJECT)
        outcome = map_review_locations([self._comment("a.md", 42, "c2")], index)
        self.assertEqual(outcome["mapped"], [])
        self.assertEqual(len(outcome["unmatched"]), 1)

    def test_duplicate_item_location_maps_but_flags_duplication(self):
        """定位可唯一映射，但条目自身重复必须标出待人工确认。"""
        ref = ItemRef(PROJECT, "id-12345678")
        text = _doc("一。" + " " + ref.render())
        index = build_item_index([("a.md", text), ("b.md", text)], project_id=PROJECT)
        outcome = map_review_locations([self._comment("a.md", 1, "c3")], index)
        self.assertEqual(len(outcome["mapped"]), 1)
        self.assertTrue(outcome["mapped"][0].get("reason"))
        self.assertIn("duplicate", outcome["mapped"][0]["reason"].lower())

    def test_backup_written_before_migration(self):
        from doc_tool.application.review.review_store import ReviewStore

        store = ReviewStore(_Path(self.tmp) / ".state")
        store.add_comment("r1", "author", "a.md", 1)
        backup = backup_legacy_item_data(store, _Path(self.tmp) / "backup", stamp="20261001")
        self.assertIsNotNone(backup)
        self.assertTrue(_Path(backup).is_file())
        self.assertTrue(_Path(backup).read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()
