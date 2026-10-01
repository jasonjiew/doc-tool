# -*- coding: utf-8 -*-
"""\u7ae0\u8282\u62d6\u62fd\u6392\u5e8f\u4e0e\u56fe/\u9884\u89c8\u987a\u5e8f\uff08V2.8 28-B / 2.2\uff09\u3002

\u8bbe\u8ba1\u8981\u70b9\uff1a

- **\u6392\u5e8f\u53ea\u6539\u7f16\u53f7\u4e0e\u987a\u5e8f**\uff0c\u4e0d\u6539\u5185\u5bb9\u8bed\u4e49\uff1b
- \u9700\u8981\u91cd\u7f16\u53f7\u7684\u5f15\u7528\u66f4\u65b0**\u590d\u7528** ``RefactorService.compute_batch_rename_plan``
  \u4e0e ``apply_rename_plan``\uff08\u542b\u51b2\u7a81\u6821\u9a8c\u3001\u5907\u4efd\u4e0e\u56de\u6eda\uff09\uff0c\u4e0d\u81ea\u5df1\u5199\u4e00\u5957\u6539\u540d\u5f15\u64ce\uff1b
- \u6811/\u5feb\u901f\u6253\u5f00/\u9884\u89c8\u4e00\u5f8b\u7528 ``display_order``\uff0c\u4fdd\u8bc1\u754c\u9762\u4e0e\u6784\u5efa\u540c\u4e00\u987a\u5e8f\u3002
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from doc_tool.application.chapter_order import ChapterOrder, resolve_chapter_order

#: \u7ae0\u8282\u6587\u4ef6\u540d\u7684\u524d\u5bfc\u7f16\u53f7\uff08\u5982 ``1`` / ``1.2``\uff09\u3002
_LEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*[.\u3001\s]*")
#: \u7ae0\u8282\u6587\u4ef6\u540d\u540e\u7f00\u3002
_CHAPTER_SUFFIX = ".md"


@dataclass
class ReorderPlan:
    """\u6392\u5e8f\u8ba1\u5212\uff08\u53ea\u8bfb\uff0c\u542b\u5c06\u53d1\u751f\u7684\u91cd\u547d\u540d\uff09\u3002"""

    renames: List[Tuple[str, str]] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    reference_edits: int = 0

    @property
    def can_apply(self) -> bool:
        return bool(self.renames) and not self.conflicts

    def to_dict(self) -> dict:
        return {
            "renames": [{"from": old, "to": new} for old, new in self.renames],
            "conflicts": list(self.conflicts),
            "unchanged": list(self.unchanged),
            "referenceEdits": self.reference_edits,
            "canApply": self.can_apply,
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u7ae0\u8282\u6392\u5e8f\u8ba1\u5212",
            "",
            "- \u91cd\u547d\u540d\uff1a{0} \u9879\uff1b\u5f15\u7528\u4fee\u6b63\uff1a{1} \u5904".format(
                len(self.renames), self.reference_edits
            ),
        ]
        if self.conflicts:
            lines.append("")
            lines.append("**\u51b2\u7a81\uff1a**")
            lines.extend("- {0}".format(item) for item in self.conflicts)
        if self.renames:
            lines.append("")
            lines.append("| \u539f\u8def\u5f84 | \u65b0\u8def\u5f84 |")
            lines.append("|--------|--------|")
            for old, new in self.renames:
                lines.append("| {0} | {1} |".format(old, new))
        return "\n".join(lines)


def display_order(
    discovered: Sequence[str],
    declared: Optional[Sequence[str]] = None,
) -> ChapterOrder:
    """\u754c\u9762\uff08\u6811/\u5feb\u901f\u6253\u5f00/\u9884\u89c8\uff09\u5e94\u4f7f\u7528\u7684\u552f\u4e00\u987a\u5e8f\u3002

    \u76f4\u63a5\u59d4\u6d3e\u7ed9 ``resolve_chapter_order``\uff0c\u907f\u514d\u754c\u9762\u4e0e\u6784\u5efa\u5404\u81ea\u7b97\u4e00\u5957\u987a\u5e8f\u3002
    """
    return resolve_chapter_order(discovered, declared)


def plan_reorder(
    ordered_paths: Sequence[str],
    *,
    renumber: bool = True,
    refactor_service=None,
) -> ReorderPlan:
    """\u6839\u636e\u76ee\u6807\u987a\u5e8f\u7b97\u51fa\u91cd\u547d\u540d\u4e0e\u5f15\u7528\u4fee\u6b63\uff08**\u4e0d\u5199\u5165**\uff09\u3002

    ``ordered_paths`` \u662f\u62d6\u62fd\u540e\u7684\u76ee\u6807\u987a\u5e8f\uff08\u76f8\u5bf9\u8def\u5f84\uff09\u3002
    ``renumber=False`` \u65f6\u53ea\u6821\u9a8c\u987a\u5e8f\uff0c\u4e0d\u6539\u540d\u3002
    """
    plan = ReorderPlan()
    normalized = [str(item).replace("\\", "/") for item in ordered_paths]
    if not renumber:
        plan.unchanged = list(normalized)
        return plan
    proposed: List[Tuple[str, str]] = []
    for index, relative in enumerate(normalized, start=1):
        target = _renumber_path(relative, index)
        if target == relative:
            plan.unchanged.append(relative)
            continue
        proposed.append((relative, target))
    plan.renames = proposed
    if refactor_service is not None and proposed:
        rename_plan = refactor_service.compute_batch_rename_plan(proposed)
        if rename_plan is None:
            plan.conflicts.append("\u91cd\u547d\u540d\u8ba1\u5212\u65e0\u6cd5\u7f16\u5236\uff08\u6e90\u8def\u5f84\u4e0d\u5728\u7d22\u5f15\u4e2d\uff09\u3002")
        else:
            plan.conflicts.extend(rename_plan.conflicts)
            plan.reference_edits = len(getattr(rename_plan, "edits", []) or [])
    return plan


def apply_reorder(plan: ReorderPlan, refactor_service, writer) -> dict:
    """\u5e94\u7528\u6392\u5e8f\uff1a**\u590d\u7528** ``RefactorService`` \u7684\u4e8b\u52a1\u4e0e\u56de\u6eda\u80fd\u529b\u3002

    \u8fd4\u56de ``{"success", "renamed", "referenceEdits", "message"}``\u3002
    """
    if plan.conflicts:
        return {
            "success": False,
            "renamed": [],
            "referenceEdits": 0,
            "message": "\u5b58\u5728\u51b2\u7a81\uff0c\u672a\u5e94\u7528\uff1a{0}".format("\uff1b".join(plan.conflicts)),
        }
    if not plan.renames:
        return {"success": True, "renamed": [], "referenceEdits": 0, "message": "\u65e0\u9700\u91cd\u547d\u540d\u3002"}
    rename_plan = refactor_service.compute_batch_rename_plan(plan.renames)
    if rename_plan is None:
        return {"success": False, "renamed": [], "referenceEdits": 0, "message": "\u91cd\u547d\u540d\u8ba1\u5212\u65e0\u6548\u3002"}
    if not rename_plan.can_apply:
        return {
            "success": False,
            "renamed": [],
            "referenceEdits": 0,
            "message": "\u51b2\u7a81\uff1a{0}".format("\uff1b".join(rename_plan.conflicts)),
        }
    refactor_service.apply_rename_plan(rename_plan, writer)
    return {
        "success": True,
        "renamed": ["{0} \u2192 {1}".format(old, new) for old, new in plan.renames],
        "referenceEdits": len(getattr(rename_plan, "edits", []) or []),
        "message": "\u5df2\u5e94\u7528 {0} \u9879\u91cd\u547d\u540d\u3002".format(len(plan.renames)),
    }


def _renumber_path(relative: str, index: int) -> str:
    """\u628a ``2 \u8bbe\u8ba1.md`` \u91cd\u7f16\u4e3a ``<index> \u8bbe\u8ba1.md``\uff1b\u65e0\u7f16\u53f7\u7684\u6807\u9898\u524d\u8865\u7f16\u53f7\u3002"""
    path = Path(relative)
    stem = path.stem
    match = _LEADING_NUMBER_RE.match(stem)
    if match:
        rest = stem[match.end():].strip() or match.group(1)
        new_stem = "{0} {1}".format(index, rest)
    else:
        new_stem = "{0} {1}".format(index, stem.strip())
    parent = path.parent.as_posix()
    name = new_stem + (path.suffix or _CHAPTER_SUFFIX)
    if parent in ("", "."):
        return name
    return "{0}/{1}".format(parent, name)