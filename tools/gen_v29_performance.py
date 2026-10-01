# -*- coding: utf-8 -*-
"""V2.9 8.2 \u6027\u80fd\u5939\u5177\uff1a3 \u6587\u6863 / 300 \u7ae0\u8282 / 1000 \u6761\u76ee\u3002

\u5b9e\u6d4b\u6784\u56fe\u3001\u77e9\u9635\u4e0e\u5f71\u54cd\u8ba1\u7b97\u8017\u65f6\uff0c\u5e76\u628a\u73af\u5883\u3001\u7ed3\u679c\u5199\u5165\u8bc1\u636e\u76ee\u5f55\u3002
\u4e0d\u4f7f\u7528 mock\uff1a\u771f\u5b9e\u6784\u5efa\u6761\u76ee\u3001\u5173\u7cfb\u4e0e\u77e9\u9635\u3002
"""

from __future__ import annotations

import json
import sys
import time
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NL = chr(10)
DOCUMENTS = 3
CHAPTERS_PER_DOC = 100
REQUIREMENTS = 600
DESIGNS = 300
TESTS = 100


def _build_items():
    from doc_tool.application.content.traceable_items import ItemRef

    items = []
    for index in range(REQUIREMENTS):
        items.append(ItemRef("proj-req", "req-{0:05d}".format(index), "requirement"))
    for index in range(DESIGNS):
        items.append(ItemRef("proj-design", "des-{0:05d}".format(index), "design"))
    for index in range(TESTS):
        items.append(ItemRef("proj-test", "tst-{0:05d}".format(index), "test"))
    return items


def _build_graph(items):
    from doc_tool.application.content.relations import RelationGraph, add_relation
    from doc_tool.application.content.trace_matrix import endpoint_for

    graph = RelationGraph()
    requirements = [item for item in items if item.kind == "requirement"]
    designs = [item for item in items if item.kind == "design"]
    tests = [item for item in items if item.kind == "test"]
    for index, design in enumerate(designs):
        target = requirements[index % len(requirements)]
        add_relation(graph, relation_type="satisfies", source=endpoint_for(design), target=endpoint_for(target))
    for index, test in enumerate(tests):
        target = requirements[index % len(requirements)]
        add_relation(graph, relation_type="verifies", source=endpoint_for(test), target=endpoint_for(target))
    return graph


def main() -> int:
    from doc_tool.application.content.impact import compute_impact
    from doc_tool.application.content.trace_matrix import build_coverage
    from doc_tool.application.content.traceable_items import build_item_index

    started = time.perf_counter()
    documents = []
    for doc_index in range(DOCUMENTS):
        lines = []
        for chapter in range(CHAPTERS_PER_DOC):
            lines.append("## {0}.{1} \u7ae0\u8282".format(doc_index + 1, chapter + 1))
            lines.append("")
            lines.append("{0}.{1}.1 \u6761\u76ee\u6b63\u6587\u3002".format(doc_index + 1, chapter + 1))
            lines.append("")
        documents.append(("doc{0}.md".format(doc_index + 1), NL.join(lines)))
    index_build = time.perf_counter()

    index = build_item_index(documents, project_id="")
    index_done = time.perf_counter()

    items = _build_items()
    graph = _build_graph(items)
    graph_done = time.perf_counter()

    coverage = build_coverage(items, graph)
    coverage_done = time.perf_counter()

    changed = {items[0].key: "\u6b63\u6587\u8bed\u4e49\u53d8\u5316"}
    impact = compute_impact(changed, graph)
    impact_done = time.perf_counter()

    record = {
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "machine": platform.machine(),
        },
        "fixture": {
            "documents": DOCUMENTS,
            "chapters": DOCUMENTS * CHAPTERS_PER_DOC,
            "items": len(items),
            "requirements": REQUIREMENTS,
            "designs": DESIGNS,
            "tests": TESTS,
            "relations": len(graph.relations),
        },
        "timingsSeconds": {
            "documentGeneration": round(index_build - started, 4),
            "itemIndex": round(index_done - index_build, 4),
            "graphBuild": round(graph_done - index_done, 4),
            "matrix": round(coverage_done - graph_done, 4),
            "impact": round(impact_done - coverage_done, 4),
            "total": round(impact_done - started, 4),
        },
        "results": {
            "chaptersMarked": len(index.headings),
            "coverageApplicable": coverage.applicable,
            "designCoverage": coverage.design_coverage,
            "testCoverage": coverage.test_coverage,
            "impactEntries": len(impact.entries),
        },
        "thresholdsSeconds": {"matrix": 5.0, "impact": 5.0, "itemIndex": 5.0},
    }
    record["passed"] = (
        record["timingsSeconds"]["matrix"] <= 5.0
        and record["timingsSeconds"]["impact"] <= 5.0
        and record["timingsSeconds"]["itemIndex"] <= 5.0
    )
    target = ROOT / "docs" / "release" / "evidence" / "v29-performance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\u5df2\u751f\u6210", target)
    print(json.dumps(record["timingsSeconds"], ensure_ascii=False))
    print("passed:", record["passed"])
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())