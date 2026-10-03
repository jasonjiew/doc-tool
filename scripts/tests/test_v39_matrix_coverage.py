# -*- coding: utf-8 -*-
"""39-A 1.3 / 39-C：矩阵真实分母、N/A 与分页统计口径一致。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application import rd_surface as surface  # noqa: E402
from doc_tool.application.content.relations import (  # noqa: E402
    Endpoint,
    add_relation,
)
from doc_tool.application.content.traceable_items import (  # noqa: E402
    ItemIndex,
    ItemRef,
)


def _ref(item_id: str, kind: str = "requirement", project: str = "P1") -> ItemRef:
    return ItemRef(project_id=project, item_id=item_id, kind=kind, alias=item_id)


def _endpoint(item_id: str, project: str = "P1") -> Endpoint:
    return Endpoint(project, item_id)


class MatrixCoverageTests(unittest.TestCase):
    def _index_with(self, count: int) -> ItemIndex:
        """声明 count 个需求 + count 个设计条目（设计是覆盖关系的来源）。"""
        index = ItemIndex()
        for number in range(count):
            index.items[("P1", "req-{0}".format(number))] = _ref("req-{0}".format(number))
            index.items[("P1", "des-{0}".format(number))] = _ref(
                "des-{0}".format(number), "design",
            )
        return index

    def _graph(self, covered: int):
        graph = surface.empty_graph()
        for number in range(covered):
            add_relation(
                graph, relation_type="satisfies",
                source=_endpoint("des-{0}".format(number)),
                target=_endpoint("req-{0}".format(number)),
            )
        return graph

    def test_metrics_use_full_denominator_across_pages(self):
        items = list(self._index_with(25).items.values())
        graph = self._graph(10)
        first = surface.matrix_view(items, graph, page=1, page_size=10)
        second = surface.matrix_view(items, graph, page=2, page_size=10)
        third = surface.matrix_view(items, graph, page=3, page_size=10)
        self.assertEqual(first["totalRequirements"], 25)
        for payload in (second, third):
            self.assertEqual(payload["totalRequirements"], 25)
            self.assertEqual(payload["coverage"], first["coverage"])
            self.assertEqual(
                [m["value"] for m in payload["metrics"]],
                [m["value"] for m in first["metrics"]],
            )
        # 分页行数：10/10/5，合计等于分母
        counts = [len(p["page"]["rows"]) for p in (first, second, third)]
        self.assertEqual(counts, [10, 10, 5])
        self.assertEqual(first["page"]["total"], 25)

    def test_no_declared_requirements_is_na_not_zero(self):
        empty = surface.matrix_view([], surface.empty_graph(), page=1, page_size=10)
        self.assertFalse(empty["applicable"])
        self.assertEqual(empty["totalRequirements"], 0)
        for metric in empty["metrics"]:
            if metric["key"] == "total":
                self.assertEqual(metric["value"], "0")
            else:
                self.assertEqual(metric["value"], "N/A", metric)
        self.assertIn("N/A", empty["message"])

    def test_partial_coverage_is_reported_honestly(self):
        items = list(self._index_with(10).items.values())
        payload = surface.matrix_view(items, self._graph(4), page=1, page_size=10)
        self.assertTrue(payload["applicable"])
        self.assertEqual(payload["totalRequirements"], 10)
        # 4/10 需求有设计覆盖；未覆盖设计 6 条如实列出
        self.assertEqual(payload["coverage"]["design"], "40.0%")
        self.assertEqual(len(payload["uncoveredDesign"]), 6)
        # 没有测试条目：测试覆盖按真实分母算 0%，不显示 N/A；未复核数量为 0
        self.assertEqual(payload["coverage"]["test"], "0.0%")
        self.assertEqual(payload["report"]["linked"], 0)
        self.assertEqual(payload["report"]["dangling"], [])


if __name__ == "__main__":
    unittest.main()