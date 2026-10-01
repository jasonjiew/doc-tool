# -*- coding: utf-8 -*-
"""V2.9 4.3：矩阵分页与来源定位（服务层）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.relations import RelationGraph, add_relation  # noqa: E402
from doc_tool.application.content.trace_matrix import (  # noqa: E402
    build_coverage,
    build_matrix_page,
    endpoint_for,
    locate_item,
)
from doc_tool.application.content.traceable_items import (  # noqa: E402
    ItemRef,
    build_item_index,
)

P = "proj-req"
PD = "proj-design"
PT = "proj-test"
NL = chr(10)


def _ref(kind, name):
    return ItemRef(project_id={"requirement": P, "design": PD, "test": PT}[kind], item_id=name, kind=kind)


class MatrixPageTests(unittest.TestCase):
    def setUp(self):
        self.requirements = [_ref("requirement", "req-{0:03d}".format(i)) for i in range(120)]
        self.design = _ref("design", "des-000")
        self.test = _ref("test", "tst-000")
        graph = RelationGraph()
        add_relation(graph, relation_type="satisfies", source=endpoint_for(self.design), target=endpoint_for(self.requirements[0]))
        add_relation(graph, relation_type="verifies", source=endpoint_for(self.test), target=endpoint_for(self.requirements[0]))
        self.report = build_coverage(self.requirements + [self.design, self.test], graph)

    def test_pagination_is_stable_and_complete(self):
        first = build_matrix_page(self.report, page=1, page_size=50)
        self.assertEqual(first.total, 120)
        self.assertEqual(len(first.rows), 50)
        self.assertEqual(first.page_count, 3)
        second = build_matrix_page(self.report, page=2, page_size=50)
        third = build_matrix_page(self.report, page=3, page_size=50)
        seen = [row.item.item_id for page in (first, second, third) for row in page.rows]
        self.assertEqual(len(seen), 120)
        self.assertEqual(len(set(seen)), 120, "分页不得重复或遗漏")

    def test_overflow_page_returns_empty_not_error(self):
        page = build_matrix_page(self.report, page=99, page_size=50)
        self.assertEqual(page.rows, [])
        self.assertEqual(page.total, 120)

    def test_only_uncovered_filter(self):
        page = build_matrix_page(self.report, page=1, page_size=10, only_uncovered=True)
        self.assertEqual(page.total, 119)
        self.assertTrue(all(not row.covered for row in page.rows))

    def test_unlinked_and_orphans_exposed(self):
        page = build_matrix_page(self.report, page=1, page_size=5)
        self.assertEqual(len(page.unlinked), 119)
        data = page.to_dict()
        for key in ("page", "pageSize", "pageCount", "total", "rows", "unlinked", "orphans", "dangling"):
            self.assertIn(key, data)

    def test_zero_requirements_gives_empty_but_valid_page(self):
        report = build_coverage([self.design], RelationGraph())
        page = build_matrix_page(report, page=1, page_size=10)
        self.assertEqual(page.total, 0)
        self.assertEqual(page.rows, [])
        self.assertEqual(page.page_count, 1)


class LocateItemTests(unittest.TestCase):
    def test_locate_returns_all_positions(self):
        ref = ItemRef(P, "id-12345678")
        text = NL.join(["## 1 需求", "", "1.1 一。 " + ref.render(), "", "2.2 二。 " + ref.render()]) + NL
        index = build_item_index([("a.md", text)], project_id=P)
        found = locate_item("id-12345678", index)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["relPath"], "a.md")
        self.assertTrue(found[0]["lineNo"])
        self.assertEqual(found[0]["headingNo"], "1")

    def test_unknown_item_returns_empty(self):
        index = build_item_index([("a.md", "text" + NL)], project_id=P)
        self.assertEqual(locate_item("nope", index), [])

    def test_project_filter_applied(self):
        mine = ItemRef(P, "id-12345678")
        other = ItemRef("other", "id-12345678")
        text = NL.join(["a " + mine.render(), "b " + other.render()]) + NL
        index = build_item_index([("a.md", text)])
        self.assertEqual(len(locate_item("id-12345678", index, project_id=P)), 1)
        self.assertEqual(len(locate_item("id-12345678", index)), 2)


if __name__ == "__main__":
    unittest.main()