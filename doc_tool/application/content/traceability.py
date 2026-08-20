# -*- coding: utf-8 -*-
"""Requirement, design, interface, and acceptance traceability."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from doc_tool.application.content.references import leading_number
from doc_tool.domain.content_index import REF_LINK, REF_SECTION, ContentIndex


_ID_RE = re.compile(r"\b(?:RQ|REQ|DES|DS|IF|TC|AC)-\d+\b", re.I)
_NUMBER_REF_RE = re.compile(
    r"(?:\u89c1|\u53c2\u89c1|\u8be6\u89c1|\u53c2\u8003|\u5bf9\u5e94|\u6765\u81ea)\s*"
    r"(?:\u9700\u6c42|\u8bbe\u8ba1|\u63a5\u53e3|\u9a8c\u6536|\u7ae0\u8282)?\s*"
    r"(\d+(?:\.\d+)+)"
)


@dataclass(frozen=True)
class TraceItem:
    item_id: str
    kind: str
    title: str
    rel_path: str
    line_no: int
    references: List[str] = field(default_factory=list)


@dataclass
class TraceMatrix:
    rows: List[dict]
    requirement_coverage: float
    design_coverage: float
    unmapped_requirements: List[TraceItem]
    unmapped_designs: List[TraceItem]

    def to_dict(self) -> dict:
        return {
            "rows": self.rows,
            "coverage": {
                "requirementToDesign": self.requirement_coverage,
                "designToInterfaceAcceptance": self.design_coverage,
            },
            "unmappedRequirements": [asdict(item) for item in self.unmapped_requirements],
            "unmappedDesigns": [asdict(item) for item in self.unmapped_designs],
        }


def _classify(text: str, document_type: str) -> str:
    lowered = text.lower()
    # 文档类型优先：requirement 文档内的标题一律算需求；design 文档内再按
    # 关键词细分接口/验收子项。原实现关键词优先，design 文档标题只要带
    # 「需求」字样（如「需求分析」）就会被误归 requirement，矩阵错位。
    if document_type == "requirement":
        return "requirement"
    if document_type == "design":
        if "\u9a8c\u6536" in text or lowered.startswith(("tc-", "ac-")):
            return "acceptance"
        if "\u63a5\u53e3" in text or lowered.startswith("if-"):
            return "interface"
        return "design"
    # 未知/通用文档类型：退回标题关键词启发式。
    if "\u9a8c\u6536" in text or lowered.startswith(("tc-", "ac-")):
        return "acceptance"
    if "\u63a5\u53e3" in text or lowered.startswith("if-"):
        return "interface"
    if "\u9700\u6c42" in text or lowered.startswith(("rq-", "req-")):
        return "requirement"
    if "\u8bbe\u8ba1" in text or lowered.startswith(("des-", "ds-")):
        return "design"
    return "unclassified"


class TraceabilityService:
    """Build and persist a trace matrix from an existing content index."""

    def __init__(self, index: ContentIndex, state_dir: Optional[Path] = None) -> None:
        self.index = index
        self.file = Path(state_dir) / "traceability.json" if state_dir is not None else None

    def parse_items(self) -> List[TraceItem]:
        items: List[TraceItem] = []
        for rel_path in self.index.all_files():
            entry = self.index.files[rel_path]
            lines = self.index.lines.get(rel_path, [])
            headings_in_file = self.index.headings.get(rel_path, [])
            for heading in headings_in_file:
                start = max(0, heading.line_no - 1)
                # 引用窗口（标题行起 4 行内）不得跨越到下一个标题：下一标题的
                # 编号/引用属于其自身条目，混入会让上游条目 references 误增。
                window_end = heading.line_no + 4
                next_line = min(
                    (h.line_no for h in headings_in_file if h.line_no > heading.line_no),
                    default=None,
                )
                if next_line is not None:
                    window_end = min(window_end, next_line - 1)
                context = "\n".join(lines[start: window_end])
                # 条目编号优先取标题自身的前置编号（如 1.1）；标题无编号时才
                # 看标题文本内的 RQ-102 形式。正文里的 RQ/编号引用只进 references，
                # 不能抢占条目自己的编号，否则「1.1 需求概述」会被误注册为正文
                # 里某个 RQ id，导致矩阵关联错位。
                heading_number = leading_number(heading.text)
                heading_ids = [value.upper() for value in _ID_RE.findall(heading.text)]
                item_id = heading_number or (heading_ids[0] if heading_ids else "")
                references = [value.upper() for value in _ID_RE.findall(context)]
                references.extend(_NUMBER_REF_RE.findall(context))
                items.append(
                    TraceItem(
                        item_id=item_id,
                        kind=_classify(heading.text, entry.document_type),
                        title=heading.text,
                        rel_path=rel_path,
                        line_no=heading.line_no,
                        references=sorted(set(ref for ref in references if ref != item_id)),
                    )
                )
        return items

    def rebuild(self) -> TraceMatrix:
        items = self.parse_items()
        matrix = build_matrix(items)
        if self.file is not None:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.file.with_suffix(".json.tmp")
            payload = {
                "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "items": [asdict(item) for item in items],
                "matrix": matrix.to_dict(),
            }
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                os.replace(str(temporary), str(self.file))
            except OSError:
                shutil.move(str(temporary), str(self.file))
        return matrix

    def impact_analysis(self, changed_paths: Iterable[str]) -> List[dict]:
        changed = set(changed_paths)
        impacts: List[dict] = []
        for source, references in self.index.references.items():
            for reference in references:
                if reference.kind not in (REF_SECTION, REF_LINK):
                    continue
                # 悬空引用（目标已删除/无法解析）本身就是「受影响/悬空」下游：
                # 在 fresh index 下章节删除后 target_rel_path 会变成 None，若只按
                # changed 匹配会漏报，因此悬空引用一律列为影响项。
                dangling = bool(
                    reference.dangling
                    or reference.target_rel_path is None
                    or reference.target_rel_path not in self.index.files
                )
                if dangling or reference.target_rel_path in changed:
                    impacts.append(
                        {
                            "source": source,
                            "line": reference.source_line,
                            "target": reference.target_rel_path,
                            "dangling": dangling,
                        }
                    )
        return sorted(impacts, key=lambda item: (item["source"], item["line"]))


def build_matrix(items: Iterable[TraceItem]) -> TraceMatrix:
    all_items = list(items)
    requirements = [item for item in all_items if item.kind == "requirement" and item.item_id]
    designs = [item for item in all_items if item.kind == "design" and item.item_id]
    children = [item for item in all_items if item.kind in ("interface", "acceptance")]
    mapped_requirements = set()
    mapped_designs = set()
    rows: List[dict] = []
    for requirement in requirements:
        linked_designs = [item for item in designs if requirement.item_id in item.references]
        if linked_designs:
            mapped_requirements.add(requirement.item_id)
        for design in linked_designs or [None]:
            linked_children = [
                item for item in children
                if design is not None and design.item_id and design.item_id in item.references
            ]
            if design is not None and linked_children:
                mapped_designs.add(design.item_id)
            rows.append(
                {
                    "requirement": asdict(requirement),
                    "design": asdict(design) if design else None,
                    "interfaces": [asdict(item) for item in linked_children if item.kind == "interface"],
                    "acceptance": [asdict(item) for item in linked_children if item.kind == "acceptance"],
                }
            )
    return TraceMatrix(
        rows=rows,
        requirement_coverage=round(100.0 * len(mapped_requirements) / len(requirements), 2) if requirements else 0.0,
        design_coverage=round(100.0 * len(mapped_designs) / len(designs), 2) if designs else 0.0,
        unmapped_requirements=[item for item in requirements if item.item_id not in mapped_requirements],
        unmapped_designs=[item for item in designs if item.item_id not in mapped_designs],
    )


def render_matrix_markdown(matrix: TraceMatrix) -> str:
    lines = [
        "# \u9700\u6c42\u8ffd\u8e2a\u77e9\u9635",
        "",
        "- \u9700\u6c42\u2192\u8bbe\u8ba1\u8986\u76d6\u7387\uff1a{0:.2f}%".format(matrix.requirement_coverage),
        "- \u8bbe\u8ba1\u2192\u63a5\u53e3/\u9a8c\u6536\u8986\u76d6\u7387\uff1a{0:.2f}%".format(matrix.design_coverage),
        "",
        "| \u9700\u6c42 | \u8bbe\u8ba1 | \u63a5\u53e3 | \u9a8c\u6536 |",
        "| --- | --- | --- | --- |",
    ]
    for row in matrix.rows:
        requirement = row["requirement"]["item_id"]
        design = row["design"]["item_id"] if row["design"] else "\u672a\u6620\u5c04"
        interfaces = "\u3001".join(item["item_id"] or item["title"] for item in row["interfaces"]) or "-"
        acceptance = "\u3001".join(item["item_id"] or item["title"] for item in row["acceptance"]) or "-"
        lines.append("| {0} | {1} | {2} | {3} |".format(requirement, design, interfaces, acceptance))
    if matrix.unmapped_requirements:
        lines.extend(["", "## \u672a\u6620\u5c04\u9700\u6c42", ""])
        lines.extend("- {0} ({1}:{2})".format(item.item_id, item.rel_path, item.line_no) for item in matrix.unmapped_requirements)
    if matrix.unmapped_designs:
        lines.extend(["", "## \u65e0\u63a5\u53e3/\u9a8c\u6536\u6620\u5c04\u7684\u8bbe\u8ba1", ""])
        lines.extend("- {0} ({1}:{2})".format(item.item_id, item.rel_path, item.line_no) for item in matrix.unmapped_designs)
    if not matrix.rows and not matrix.unmapped_requirements and not matrix.unmapped_designs:
        lines.extend(["", "> \u672a\u89e3\u6790\u5230\u9700\u6c42/\u8bbe\u8ba1\u6761\u76ee\uff08\u8986\u76d6\u7387\u4e0d\u9002\u7528\uff09\u3002", ""])
    return "\n".join(lines) + "\n"
