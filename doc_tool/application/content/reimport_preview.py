# -*- coding: utf-8 -*-
"""\u91cd\u5bfc\u5165\u9884\u89c8\u4f1a\u8bdd\uff08V2.8 28-H / 8.2 \u670d\u52a1\u5c42\uff09\u3002

\u754c\u9762\u53ea\u9700\u63d0\u4f9b\u201c\u9009\u4e2d/\u53d6\u6d88\u201d\u4e0e\u810f\u7f16\u8f91\u5668\u72b6\u6001\uff1b\u672c\u6a21\u5757\u8d1f\u8d23\uff1a

- \u6253\u5f00\u4f1a\u8bdd\u65f6\u62ff\u5230**\u53ea\u8bfb\u8ba1\u5212 + \u9010\u9879 diff**\uff08\u4e0d\u6c61\u67d3\u6b63\u5f0f\u7ae0\u8282\uff09\uff1b
- **\u810f\u5185\u5bb9\u9879\u9ed8\u8ba4\u4e0d\u53c2\u4e0e**\uff08\u672a\u4fdd\u5b58\u7f16\u8f91\u4e0d\u88ab\u8986\u76d6\uff09\uff1b
- \u53d6\u6d88\u53ea\u4e22\u5f03\u4f1a\u8bdd\uff0c**\u4e0d\u5199\u5165\u4efb\u4f55\u5185\u5bb9**\uff1b
- \u5e94\u7528\u65f6\u590d\u7528 ``reimport_plan.apply_plan``\u3002
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from doc_tool.application.content.reimport_plan import ReimportPlan, apply_plan, plan_reimport


@dataclass
class PreviewEntry:
    """\u9884\u89c8\u4e2d\u7684\u4e00\u9879\u7ae0\u8282\u53d8\u5316\uff08\u542b diff\uff09\u3002"""

    rel_path: str
    change: str
    conflict: bool
    selected: bool
    dirty: bool = False
    blocked_reason: str = ""
    diff_lines: List[str] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return self.selected and not self.conflict and not self.dirty

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "change": self.change,
            "conflict": self.conflict,
            "selected": self.selected,
            "dirty": self.dirty,
            "blockedReason": self.blocked_reason,
            "applicable": self.applicable,
            "diff": list(self.diff_lines),
        }


@dataclass
class PreviewSession:
    """\u91cd\u5bfc\u5165\u9884\u89c8\u4f1a\u8bdd\uff08\u7eaf\u6570\u636e + \u53d7\u63a7\u5e94\u7528\uff09\u3002"""

    plan: ReimportPlan
    entries: List[PreviewEntry] = field(default_factory=list)
    closed: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def applicable(self) -> List[PreviewEntry]:
        return [item for item in self.entries if item.applicable]

    @property
    def blocked(self) -> List[PreviewEntry]:
        return [item for item in self.entries if item.conflict or item.dirty]

    def counts(self) -> Dict[str, int]:
        return {
            "total": len(self.entries),
            "applicable": len(self.applicable),
            "conflict": len([item for item in self.entries if item.conflict]),
            "dirty": len([item for item in self.entries if item.dirty]),
        }

    def to_dict(self) -> dict:
        return {
            "counts": self.counts(),
            "closed": self.closed,
            "warnings": list(self.warnings),
            "entries": [item.to_dict() for item in self.entries],
        }

    def markdown_text(self) -> str:
        counts = self.counts()
        lines = [
            "## \u91cd\u5bfc\u5165\u9884\u89c8",
            "",
            "- \u53ef\u5e94\u7528\uff1a{applicable}\uff1b\u51b2\u7a81\uff1a{conflict}\uff1b\u810f\u5185\u5bb9\uff1a{dirty}".format(**counts),
        ]
        if self.warnings:
            lines.append("")
            lines.extend("- \u63d0\u9192\uff1a{0}".format(item) for item in self.warnings)
        if self.entries:
            lines.append("")
            lines.append("| \u7ae0\u8282 | \u53d8\u5316 | \u51b2\u7a81 | \u810f | \u5c06\u5e94\u7528 |")
            lines.append("|------|------|------|----|--------|")
            for item in self.entries:
                lines.append(
                    "| {0} | {1} | {2} | {3} | {4} |".format(
                        item.rel_path,
                        item.change,
                        "\u662f" if item.conflict else "\u5426",
                        "\u662f" if item.dirty else "\u5426",
                        "\u662f" if item.applicable else "\u5426",
                    )
                )
        return "\n".join(lines)


def open_preview(
    changes: Sequence[object],
    *,
    service=None,
    source_path: Union[str, Path] = "",
    baseline_available: Optional[bool] = None,
    selected: Optional[Sequence[str]] = None,
    dirty_paths: Optional[Sequence[str]] = None,
    local_contents: Optional[Dict[str, str]] = None,
    incoming_contents: Optional[Dict[str, str]] = None,
) -> PreviewSession:
    """\u6253\u5f00\u9884\u89c8\u4f1a\u8bdd\uff08**\u4e0d\u5199\u5165**\uff09\u3002

    - ``dirty_paths``\uff1a\u754c\u9762\u62a5\u544a\u7684\u672a\u4fdd\u5b58\u7f16\u8f91\u9879\uff0c\u9ed8\u8ba4**\u4e0d\u53c2\u4e0e\u5e94\u7528**\uff1b
    - ``local_contents`` / ``incoming_contents``\uff1a\u4f9b\u9010\u9879 diff\uff1b\u7f3a\u5931\u65f6\u4e0d\u963b\u65ad\uff0c\u53ea\u6807\u6ce8\u65e0 diff\u3002
    """
    plan = plan_reimport(
        service,
        changes,
        source_path=source_path,
        baseline_available=baseline_available,
        selected=selected,
    )
    dirty = {str(item).replace("\\", "/") for item in (dirty_paths or [])}
    session = PreviewSession(plan=plan, warnings=list(plan.warnings))
    for item in plan.items:
        entry = PreviewEntry(
            rel_path=item.rel_path,
            change=item.change,
            conflict=item.conflict,
            selected=item.selected,
            dirty=item.rel_path in dirty,
        )
        if entry.dirty:
            entry.blocked_reason = "\u5b58\u5728\u672a\u4fdd\u5b58\u7f16\u8f91\uff0c\u8df3\u8fc7\u4ee5\u907f\u514d\u8986\u76d6"
        elif entry.conflict:
            entry.blocked_reason = item.reason or "\u51b2\u7a81\u9879\u9700\u4eba\u5de5\u786e\u8ba4"
        if entry.dirty or entry.conflict:
            # 被阻止的项在数据模型里就不预选：界面与 apply_session 看到同一事实。
            entry.selected = False
        if local_contents and incoming_contents:
            old = local_contents.get(item.rel_path)
            new = incoming_contents.get(item.rel_path)
            if old is not None and new is not None:
                entry.diff_lines = list(
                    difflib.unified_diff(
                        old.splitlines(), new.splitlines(),
                        fromfile="\u5f53\u524d/" + item.rel_path,
                        tofile="\u65b0\u6e90/" + item.rel_path,
                        lineterm="",
                        n=2,
                    )
                )
        session.entries.append(entry)
    if session.applicable:
        session.warnings.append(
            "\u5c06\u5e94\u7528 {0} \u9879\uff1b\u51b2\u7a81 {1} \u9879\u4e0e\u810f\u5185\u5bb9 {2} \u9879\u4fdd\u7559\u672c\u5730\u3002".format(
                len(session.applicable), session.counts()["conflict"], session.counts()["dirty"]
            )
        )
    return session


def toggle_selection(session: PreviewSession, rel_path: str, selected: bool) -> bool:
    """\u52fe\u9009/\u53d6\u6d88\u52fe\u9009\u4e00\u9879\uff1b\u51b2\u7a81\u4e0e\u810f\u5185\u5bb9\u4e0d\u53ef\u9009\u4e2d\u3002"""
    for item in session.entries:
        if item.rel_path != rel_path:
            continue
        if (item.conflict or item.dirty) and selected:
            return False
        item.selected = bool(selected)
        return True
    return False


def apply_session(session: PreviewSession, service, new_source: Union[str, Path]) -> dict:
    """\u5e94\u7528\u4f1a\u8bdd\uff1a\u628a\u9009\u4e2d\u4e14\u672a\u88ab\u963b\u7684\u9879\u4ea4\u7ed9**\u73b0\u6709**\u5e94\u7528\u903b\u8f91\uff08\u542b\u4e8b\u52a1\u4e0e\u56de\u6eda\uff09\u3002"""
    if session.closed:
        return {"success": False, "applied": [], "skipped": [], "rolledBack": False, "message": "\u4f1a\u8bdd\u5df2\u53d6\u6d88\u3002"}
    allowed = {item.rel_path for item in session.entries if item.applicable}
    for item in session.plan.items:
        item.selected = item.rel_path in allowed and not item.conflict
    outcome = apply_plan(service, session.plan, new_source)
    outcome["blocked"] = [item.rel_path for item in session.blocked]
    return outcome


def cancel_session(session: PreviewSession) -> None:
    """\u53d6\u6d88\u4f1a\u8bdd\uff1a**\u4e0d\u5199\u5165\u4efb\u4f55\u5185\u5bb9**\u3002"""
    session.closed = True
    for item in session.entries:
        item.selected = False