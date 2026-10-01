# -*- coding: utf-8 -*-
"""\u53ef\u89e3\u91ca\u8986\u76d6\u7387\u77e9\u9635\uff08V2.9 29-D / 4.1\u30014.2\u30014.4\uff09\u3002

\u53d6\u820d\uff1a\u65b0\u589e**\u663e\u5f0f\u56fe**\u8ba1\u7b97\uff0c\u4e0d\u6539\u5199\u65e7\u7684 ``traceability.TraceabilityService``
\uff08\u5b83\u6309\u7f16\u53f7\u63a8\u65ad\uff0c\u4fdd\u7559\u4e3a\u53ea\u8bfb\u517c\u5bb9\uff09\u3002\u65b0\u8def\u5f84**\u4e0d\u7528\u76f8\u540c\u7f16\u53f7\u63a8\u65ad\u5173\u7cfb**\u3002

\u6307\u6807\uff1a

- \u9700\u6c42\u5206\u6bcd\uff1a\u4ec5\u7edf\u8ba1**\u5df2\u58f0\u660e\u4e3a requirement \u7684\u7a33\u5b9a\u6761\u76ee**\uff08\u672a\u6807\u8bb0\u5185\u5bb9\u4e0d\u8ba1\u5165\uff09\uff1b
- \u8bbe\u8ba1\u8986\u76d6\uff1a\u901a\u8fc7 ``satisfies`` \u6307\u5411\u9700\u6c42\u7684\u8bbe\u8ba1\u6761\u76ee\uff1b\u6d4b\u8bd5\u8986\u76d6\uff1a``verifies`` \u76f4\u63a5\u8986\u76d6 + \u7ecf\u8bbe\u8ba1\u4f20\u9012\u7684**\u95f4\u63a5**\u8986\u76d6\uff1b
- **N/A**\uff1a\u65e0\u9700\u6c42\u6761\u76ee\u65f6\u6bcd\u4e3a 0\uff0c\u8986\u76d6\u7387\u8fd4\u56de ``None``\uff08\u4e0d\u62a5 0%\uff0c\u907f\u514d\u5047\u8986\u76d6\uff09\uff1b
- \u5df2\u5173\u8054/\u5f85\u590d\u6838\uff1a\u6765\u81ea\u8bc4\u5ba1\u751f\u547d\u5468\u671f\uff08\u5f85\u590d\u6838\u8ba1\u5165\u5f85\u590d\u6838\u800c\u4e0d\u7b97\u901a\u8fc7\uff09\u3002
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from doc_tool.application.content.relations import Endpoint, RelationGraph
from doc_tool.application.content.traceable_items import ItemRef

ItemKey = Tuple[str, str]


@dataclass
class MatrixRow:
    """\u77e9\u9635\u4e00\u884c\uff08\u4e00\u6761\u9700\u6c42\uff09\u3002"""

    item: ItemRef
    designs: List[ItemRef] = field(default_factory=list)
    direct_tests: List[ItemRef] = field(default_factory=list)
    indirect_tests: List[ItemRef] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        return bool(self.direct_tests or self.indirect_tests)

    def to_dict(self) -> dict:
        return {
            "item": self.item.to_dict(),
            "designs": [ref.to_dict() for ref in self.designs],
            "directTests": [ref.to_dict() for ref in self.direct_tests],
            "indirectTests": [ref.to_dict() for ref in self.indirect_tests],
            "covered": self.covered,
        }


@dataclass
class CoverageReport:
    """\u53ef\u89e3\u91ca\u8986\u76d6\u7387\u62a5\u544a\u3002"""

    rows: List[MatrixRow] = field(default_factory=list)
    design_orphans: List[ItemRef] = field(default_factory=list)
    test_orphans: List[ItemRef] = field(default_factory=list)
    dangling: List[str] = field(default_factory=list)
    pending_review: int = 0
    linked: int = 0
    total_requirements: int = 0

    @property
    def applicable(self) -> bool:
        return self.total_requirements > 0

    def _ratio(self, numerator: int) -> Optional[float]:
        if not self.applicable:
            return None
        return round(numerator / float(self.total_requirements), 4)

    @property
    def design_coverage(self) -> Optional[float]:
        return self._ratio(sum(1 for row in self.rows if row.designs))

    @property
    def test_coverage(self) -> Optional[float]:
        return self._ratio(sum(1 for row in self.rows if row.covered))

    @property
    def direct_coverage(self) -> Optional[float]:
        return self._ratio(sum(1 for row in self.rows if row.direct_tests))

    @property
    def uncovered(self) -> List[ItemRef]:
        return [row.item for row in self.rows if not row.covered]

    @property
    def uncovered_design(self) -> List[ItemRef]:
        return [row.item for row in self.rows if not row.designs]

    @property
    def review_coverage(self) -> Optional[float]:
        return self._ratio(self.linked)

    def to_dict(self) -> dict:
        return {
            "applicable": self.applicable,
            "totalRequirements": self.total_requirements,
            "designCoverage": self.design_coverage,
            "testCoverage": self.test_coverage,
            "directTestCoverage": self.direct_coverage,
            "reviewCoverage": self.review_coverage,
            "linked": self.linked,
            "pendingReview": self.pending_review,
            "uncovered": [ref.to_dict() for ref in self.uncovered],
            "uncoveredDesign": [ref.to_dict() for ref in self.uncovered_design],
            "designOrphans": [ref.to_dict() for ref in self.design_orphans],
            "testOrphans": [ref.to_dict() for ref in self.test_orphans],
            "dangling": list(self.dangling),
            "rows": [row.to_dict() for row in self.rows],
        }

    def csv_text(self) -> str:
        """CSV\uff08\u5b9a\u4e49\u987a\u5e8f\u786e\u5b9a\uff0c\u4fbf\u4e8e\u5dee\u5f02\u6bd4\u8f83\uff09\u3002"""
        lines = ["requirementId,requirementAlias,designIds,directTestIds,indirectTestIds,covered"]
        for row in self.rows:
            lines.append(
                ",".join(
                    [
                        row.item.item_id,
                        _csv(row.item.alias),
                        _csv("|".join(ref.item_id for ref in row.designs)),
                        _csv("|".join(ref.item_id for ref in row.direct_tests)),
                        _csv("|".join(ref.item_id for ref in row.indirect_tests)),
                        "yes" if row.covered else "no",
                    ]
                )
            )
        return "\n".join(lines) + "\n"

    def markdown_text(self) -> str:
        def _pct(value: Optional[float]) -> str:
            return "N/A" if value is None else "{0:.1f}%".format(value * 100)

        lines = [
            "## \u9700\u6c42\u2014\u8bbe\u8ba1\u2014\u6d4b\u8bd5\u77e9\u9635",
            "",
            "- \u9700\u6c42\u6761\u76ee\uff1a{0}".format(self.total_requirements),
            "- \u8bbe\u8ba1\u8986\u76d6\uff1a{0}".format(_pct(self.design_coverage)),
            "- \u6d4b\u8bd5\u8986\u76d6\uff08\u542b\u95f4\u63a5\uff09\uff1a{0}".format(_pct(self.test_coverage)),
            "- \u76f4\u63a5\u6d4b\u8bd5\u8986\u76d6\uff1a{0}".format(_pct(self.direct_coverage)),
            "- \u5df2\u590d\u6838\u8986\u76d6\uff1a{0}\uff08\u5f85\u590d\u6838 {1} \u6761\uff09".format(
                _pct(self.review_coverage), self.pending_review
            ),
        ]
        if not self.applicable:
            lines.append("")
            lines.append("\u672a\u58f0\u660e\u9700\u6c42\u6761\u76ee\uff1a\u8986\u76d6\u7387\u4e3a **N/A**\uff08\u4e0d\u62a5 0%\uff09\u3002")
        if self.uncovered:
            lines.append("")
            lines.append("**\u672a\u8986\u76d6\u9700\u6c42\uff1a**")
            lines.extend("- {0}".format(ref.alias or ref.item_id) for ref in self.uncovered[:50])
        if self.design_orphans or self.test_orphans:
            lines.append("")
            lines.append(
                "**\u5b64\u7acb\u6761\u76ee\uff1a**\u8bbe\u8ba1 {0} \u4e2a\uff0c\u6d4b\u8bd5 {1} \u4e2a".format(
                    len(self.design_orphans), len(self.test_orphans)
                )
            )
        if self.dangling:
            lines.append("")
            lines.append("**\u60ac\u7a7a\u5173\u7cfb\uff1a**")
            lines.extend("- {0}".format(item) for item in self.dangling[:20])
        return "\n".join(lines)


def build_coverage(
    items: Sequence[ItemRef],
    graph: RelationGraph,
    *,
    pending_review_items: Optional[Sequence[ItemKey]] = None,
    confirmed_items: Optional[Sequence[ItemKey]] = None,
) -> CoverageReport:
    """\u6309\u663e\u5f0f\u56fe\u8ba1\u7b97\u77e9\u9635\u4e0e\u53ef\u89e3\u91ca\u8986\u76d6\u7387\u3002

    ``items`` \u662f\u5168\u90e8\u5df2\u58f0\u660e\u7684\u7a33\u5b9a\u6761\u76ee\uff08\u6765\u81ea ``traceable_items`` \u7d22\u5f15\uff09\uff1b
    **\u672a\u6807\u8bb0\u5185\u5bb9\u4e0d\u5728\u6b64\u5217\u8868\u4e2d\uff0c\u56e0\u6b64\u4e0d\u8ba1\u5165\u5206\u6bcd**\u3002
    """
    by_key: Dict[ItemKey, ItemRef] = {ref.key: ref for ref in items}
    requirements = [ref for ref in items if ref.kind == "requirement"]
    designs = {ref.key: ref for ref in items if ref.kind == "design"}
    tests = {ref.key: ref for ref in items if ref.kind == "test"}

    requirement_keys = {ref.key for ref in requirements}
    satisfies: Dict[ItemKey, Set[ItemKey]] = {}
    verifies_direct: Dict[ItemKey, Set[ItemKey]] = {}
    verifies_design: Dict[ItemKey, Set[ItemKey]] = {}
    dangling: List[str] = []
    for relation in graph.relations:
        source, target = relation.source.key, relation.target.key
        if source not in by_key or target not in by_key:
            dangling.append(
                "{0}: {1} \u2192 {2}".format(relation.type, relation.source.render(), relation.target.render())
            )
            continue
        if relation.type == "satisfies" and source in designs and target in {r.key for r in requirements}:
            satisfies.setdefault(target, set()).add(source)
        elif relation.type == "verifies":
            # 方向按端点种类判定：测试→需求为直接验证，设计↔测试为经设计传递的间接验证。
            if source in tests and target in requirement_keys:
                verifies_direct.setdefault(target, set()).add(source)
            elif source in tests and target in designs:
                verifies_design.setdefault(target, set()).add(source)
            elif source in designs and target in tests:
                verifies_design.setdefault(source, set()).add(target)

    rows: List[MatrixRow] = []
    covered_by_design: Set[ItemKey] = set()
    tests_used: Set[ItemKey] = set()
    designs_used: Set[ItemKey] = set()
    for requirement in requirements:
        design_keys = satisfies.get(requirement.key, set())
        direct = set(verifies_direct.get(requirement.key, set()))
        indirect: Set[ItemKey] = set()
        for design_key in design_keys:
            designs_used.add(design_key)
            for test_key in verifies_design.get(design_key, set()):
                if test_key not in direct:
                    indirect.add(test_key)
        if design_keys:
            covered_by_design.add(requirement.key)
        direct_refs = [tests.get(key) for key in sorted(direct) if key in tests]
        indirect_refs = [tests.get(key) for key in sorted(indirect) if key in tests]
        for key in sorted(direct | indirect):
            tests_used.add(key)
        rows.append(
            MatrixRow(
                item=requirement,
                designs=[designs[key] for key in sorted(design_keys) if key in designs],
                direct_tests=[ref for ref in direct_refs if ref is not None],
                indirect_tests=[ref for ref in indirect_refs if ref is not None],
            )
        )

    confirmed = set(confirmed_items or [])
    pending = set(pending_review_items or [])
    return CoverageReport(
        rows=rows,
        design_orphans=[designs[key] for key in sorted(set(designs) - designs_used)],
        test_orphans=[tests[key] for key in sorted(set(tests) - tests_used)],
        dangling=dangling,
        pending_review=len([key for key in pending if key in by_key]),
        linked=len([key for key in confirmed if key in by_key]),
        total_requirements=len(requirements),
    )


def export_report(report: CoverageReport, fmt: str = "markdown") -> str:
    """\u5bfc\u51fa\u77e9\u9635\uff08markdown / csv / json\uff09\uff0c\u4e0e CLI \u4e0e GUI \u540c\u6e90\u3002"""
    key = str(fmt or "markdown").strip().lower()
    if key in ("md", "markdown", "text"):
        return report.markdown_text()
    if key == "csv":
        return report.csv_text()
    if key == "json":
        import json

        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    raise ValueError("\u4e0d\u652f\u6301\u7684\u5bfc\u51fa\u683c\u5f0f\uff1a{0}".format(fmt))


def endpoint_for(ref: ItemRef) -> Endpoint:
    return Endpoint(ref.project_id, ref.item_id)


def _csv(value: str) -> str:
    text = str(value or "")
    if any(char in text for char in ',"\n'):
        return '"{0}"'.format(text.replace('"', '""'))
    return text


@dataclass
class MatrixPage:
    """矩阵 UI 所需的一页数据（含来源定位）。"""

    rows: List[MatrixRow] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    unlinked: List[ItemRef] = field(default_factory=list)
    orphans: List[ItemRef] = field(default_factory=list)
    dangling: List[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "pageSize": self.page_size,
            "pageCount": self.page_count,
            "total": self.total,
            "rows": [row.to_dict() for row in self.rows],
            "unlinked": [ref.to_dict() for ref in self.unlinked],
            "orphans": [ref.to_dict() for ref in self.orphans],
            "dangling": list(self.dangling),
        }


def build_matrix_page(
    report: CoverageReport,
    *,
    page: int = 1,
    page_size: int = 50,
    only_uncovered: bool = False,
) -> MatrixPage:
    """把覆盖率报告分页成 UI 可直接渲染的一页。

    顺序按报告自身确定顺序（需求条目排序），保证 GUI 与 CLI 一致。
    """
    rows = list(report.rows)
    if only_uncovered:
        rows = [row for row in rows if not row.covered]
    total = len(rows)
    size = max(1, int(page_size))
    current = max(1, int(page))
    start = (current - 1) * size
    return MatrixPage(
        rows=rows[start:start + size],
        total=total,
        page=current,
        page_size=size,
        unlinked=list(report.uncovered),
        orphans=list(report.design_orphans) + list(report.test_orphans),
        dangling=list(report.dangling),
    )


def locate_item(
    item_id: str,
    index,
    *,
    project_id: str = "",
) -> List[dict]:
    """按条目 ID 返回可定位的来源位置（relPath / 行号 / 章节号）。

    ``index`` 是 ``traceable_items.ItemIndex``；无匹配返回空列表（UI 不得自行猜测位置）。
    """
    found: list = []
    for key, ref in getattr(index, "items", {}).items():
        if project_id and ref.project_id != project_id:
            continue
        if ref.item_id != item_id:
            continue
        for place in index.locations.get(key, []):
            found.append(
                {
                    "relPath": place.rel_path,
                    "lineNo": place.line_no,
                    "headingNo": place.heading_no,
                    "projectId": ref.project_id,
                    "itemId": ref.item_id,
                }
            )
    return found
