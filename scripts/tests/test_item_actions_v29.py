# -*- coding: utf-8 -*-
"""V2.9 2.2\uff1a\u6761\u76ee\u521b\u5efa/\u590d\u5236/\u91cd\u7f16\u53f7\u52a8\u4f5c\uff08\u670d\u52a1\u5c42\uff09\u3002"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.item_actions import (  # noqa: E402
    duplicate_item,
    insert_item,
    item_line_numbers,
    renumber_item,
)
from doc_tool.application.content.traceable_items import (  # noqa: E402
    build_item_index,
    renumber_keeps_ids,
)

NL = chr(10)
P = "proj-1"


class InsertTests(unittest.TestCase):
    def test_insert_appends_new_item_with_body(self):
        text = NL.join(["## 1 \u9700\u6c42", "", "\u73b0\u6709\u6bb5\u843d\u3002"]) + NL
        result = insert_item(text, project_id=P, body="\u65b0\u9700\u6c42\u3002")
        self.assertTrue(result.ok, result.message)
        self.assertTrue(result.item)
        self.assertEqual(result.item.kind, "requirement")
        index = build_item_index([("a.md", result.text)], project_id=P)
        self.assertEqual(index.count(), 1)
        self.assertIn("\u65b0\u9700\u6c42\u3002", result.text)

    def test_insert_at_specific_line(self):
        text = NL.join(["## 1 \u9700\u6c42", "", "\u7b2c\u4e00\u6bb5\u3002", "\u7b2c\u4e8c\u6bb5\u3002"]) + NL
        result = insert_item(text, project_id=P, line_no=3, body="\u63d2\u5165\u6bb5\u3002")
        self.assertTrue(result.ok)
        lines = result.text.splitlines()
        self.assertIn("DOC-ITEM", lines[3])
        self.assertNotIn("DOC-ITEM", lines[2])

    def test_insert_rejects_unknown_kind(self):
        result = insert_item("a", project_id=P, kind="bogus")
        self.assertFalse(result.ok)

    def test_insert_writes_through_writer(self):
        writer = mock.Mock()
        result = insert_item("a" + NL, project_id=P, body="b", writer=writer, rel_path="a.md")
        self.assertTrue(result.written)
        writer.write.assert_called_once()
        self.assertEqual(writer.write.call_args[0][0], "a.md")


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.base = insert_item(
            NL.join(["## 1 \u9700\u6c42", "", "\u539f\u59cb\u9700\u6c42\u3002"]) + NL,
            project_id=P, body="\u539f\u59cb\u9700\u6c42\u3002",
        )
        self.assertTrue(self.base.ok)

    def test_duplicate_creates_new_id_and_marker_only_on_new_line(self):
        source_line = item_line_numbers(self.base.text, P)[0][0]
        result = duplicate_item(self.base.text, source_line=source_line)
        self.assertTrue(result.ok, result.message)
        self.assertNotEqual(result.item.item_id, self.base.item.item_id)
        index = build_item_index([("a.md", result.text)], project_id=P)
        self.assertEqual(index.count(), 2, "\u539f\u6761\u76ee\u4e0e\u526f\u672c\u5404\u81ea\u552f\u4e00")
        self.assertFalse(index.duplicates)
        self.assertEqual(result.text.count("DOC-ITEM"), 2)

    def test_duplicate_with_alias(self):
        source_line = item_line_numbers(self.base.text, P)[0][0]
        result = duplicate_item(self.base.text, source_line=source_line, alias="\u526f\u672c")
        self.assertTrue(result.ok)
        self.assertEqual(result.item.alias, "\u526f\u672c")

    def test_duplicate_without_marker_rejected(self):
        result = duplicate_item("## 1" + NL + NL + "\u65e0\u6807\u8bb0\u3002", source_line=3)
        self.assertFalse(result.ok)

    def test_duplicate_line_out_of_range_rejected(self):
        result = duplicate_item(self.base.text, source_line=99)
        self.assertFalse(result.ok)


class RenumberTests(unittest.TestCase):
    def test_renumber_keeps_item_id(self):
        base = insert_item(
            NL.join(["## 1 \u9700\u6c42", "", "1.1 \u539f\u59cb\u9700\u6c42\u3002"]) + NL,
            project_id=P, line_no=3,
        )
        self.assertTrue(base.ok)
        before_ids = [ref.item_id for _line, ref in item_line_numbers(base.text, P)]
        line = item_line_numbers(base.text, P)[0][0]
        result = renumber_item(base.text, line_no=line, new_number="3.4.5")
        self.assertTrue(result.ok, result.message)
        after_ids = [ref.item_id for _line, ref in item_line_numbers(result.text, P)]
        self.assertEqual(before_ids, after_ids)
        self.assertIn("3.4.5", result.text)
        self.assertTrue(renumber_keeps_ids(base.text, result.text))

    def test_renumber_rejects_empty_number(self):
        base = insert_item("a" + NL, project_id=P, body="b")
        result = renumber_item(base.text, line_no=base.line_no, new_number="  ")
        self.assertFalse(result.ok)


class InventoryTests(unittest.TestCase):
    def test_item_line_numbers_filters_other_projects(self):
        from doc_tool.application.content.traceable_items import ItemRef

        other = ItemRef("other-project", "id-12345678")
        mine = ItemRef(P, "id-87654321")
        text = NL.join(["a " + mine.render(), "b " + other.render()]) + NL
        found = item_line_numbers(text, P)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1].project_id, P)
        self.assertEqual(len(item_line_numbers(text)), 2)


if __name__ == "__main__":
    unittest.main()