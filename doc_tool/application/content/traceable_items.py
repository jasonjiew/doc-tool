# -*- coding: utf-8 -*-
"""\u7a33\u5b9a\u6761\u76ee\uff08DOC-ITEM\uff09\u4e0e\u65e7\u7f16\u53f7\u8fc1\u79fb\uff08V2.9 29-B / 2.1\uff5e2.5\uff09\u3002

\u6761\u76ee\u6807\u8bb0\u5f62\u5f0f\uff08\u884c\u5185\uff0c\u7d27\u8ddf\u5728\u6761\u76ee\u6587\u672c\u4e4b\u540e\uff09\uff1a

    \u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f\u3002<!-- DOC-ITEM: projectId=abc kind=requirement id=7f3c... -->

\u8bbe\u8ba1\u8981\u70b9\uff1a

- \u6807\u8bb0**\u4e0d\u8fdb\u5165\u6b63\u5f0f\u6b63\u6587**\uff1a\u6e32\u67d3/\u9884\u89c8\u524d\u7edf\u4e00\u5265\u79bb\uff1b
- \u8eab\u4efd\u662f ``(projectId, itemId)``\uff0c**\u4e0d\u4f9d\u8d56\u7ae0\u8282\u7f16\u53f7**\uff1a\u79fb\u52a8/\u91cd\u7f16\u53f7\u4e0d\u6539 ID\uff0c\u590d\u5236\u751f\u6210\u65b0 ID\uff1b
- \u79cd\u7c7b\uff08kind\uff09\u4e0e\u522b\u540d\u6821\u9a8c\uff0c\u540c ID \u51fa\u73b0\u591a\u6b21\u4e3a\u91cd\u590d\uff1b
- \u65e7\u7f16\u53f7\u8fc1\u79fb\uff1a\u7ed9\u5efa\u8bae\u4e0e\u6b67\u4e49\u5217\u8868\uff0c\u7ecf ``ContentWriter`` \u4e8b\u52a1\u5199\u5165\uff1b\u672a\u6807\u8bb0\u5185\u5bb9**\u4e0d\u81ea\u52a8\u8ba1\u5165\u5206\u6bcd**\u3002
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

#: \u6761\u76ee\u6807\u8bb0\u6b63\u5219\uff08\u5141\u8bb8\u5c5e\u6027\u987a\u5e8f\u4e0d\u540c\uff09\u3002
DOC_ITEM_RE = re.compile(r"<!--\s*DOC-ITEM:(?P<body>[^>]*?)-->")
_ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s]+)")
#: \u5408\u6cd5\u79cd\u7c7b\u3002
ITEM_KINDS = ("requirement", "design", "test", "other")
#: \u4e0d\u5f97\u8fdb\u5165\u6b63\u6587\u7684\u5185\u90e8\u6807\u8bb0\u524d\u7f00\u3002
MARKER_PREFIX = "DOC-ITEM"
#: 条目身份键（projectId, itemId）。
ItemKey = Tuple[str, str]


@dataclass(frozen=True)
class ItemRef:
    """\u4e00\u4e2a\u7a33\u5b9a\u6761\u76ee\u5f15\u7528\u3002"""

    project_id: str
    item_id: str
    kind: str = "requirement"
    alias: str = ""

    @property
    def key(self) -> Tuple[str, str]:
        return (self.project_id, self.item_id)

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "itemId": self.item_id,
            "kind": self.kind,
            "alias": self.alias,
        }

    def render(self) -> str:
        parts = [
            "projectId={0}".format(self.project_id),
            "kind={0}".format(self.kind),
            "id={0}".format(self.item_id),
        ]
        if self.alias:
            parts.append("alias={0}".format(self.alias))
        return "<!-- {0}: {1} -->".format(MARKER_PREFIX, " ".join(parts))


@dataclass
class ItemLocation:
    """\u6761\u76ee\u5728\u6587\u6863\u4e2d\u7684\u4f4d\u7f6e\uff08\u4ec5\u4f9b\u5b9a\u4f4d\u4e0e\u6821\u9a8c\uff0c\u4e0d\u4f5c\u4e3a\u8eab\u4efd\uff09\u3002"""

    rel_path: str
    line_no: int
    heading_no: str = ""

    def to_dict(self) -> dict:
        return {"relPath": self.rel_path, "lineNo": self.line_no, "headingNo": self.heading_no}


@dataclass
class ItemIssue:
    """\u6761\u76ee\u7ea7\u95ee\u9898\u3002"""

    rel_path: str
    line_no: int
    reason: str
    severity: str = "warning"

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "lineNo": self.line_no,
            "reason": self.reason,
            "severity": self.severity,
        }


@dataclass
class ItemIndex:
    """``(projectId, itemId)`` \u7d22\u5f15\u3002"""

    items: Dict[Tuple[str, str], ItemRef] = field(default_factory=dict)
    locations: Dict[Tuple[str, str], List[ItemLocation]] = field(default_factory=dict)
    issues: List[ItemIssue] = field(default_factory=list)
    headings: Dict[str, List[str]] = field(default_factory=dict)

    def add(self, ref: ItemRef, location: ItemLocation) -> None:
        self.items.setdefault(ref.key, ref)
        self.locations.setdefault(ref.key, []).append(location)

    @property
    def duplicates(self) -> List[Tuple[str, str]]:
        return [key for key, places in self.locations.items() if len(places) > 1]

    def get(self, project_id: str, item_id: str) -> Optional[ItemRef]:
        return self.items.get((project_id, item_id))

    def of_kind(self, kind: str) -> List[ItemRef]:
        return [ref for ref in self.items.values() if ref.kind == kind]

    def count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict:
        return {
            "count": self.count(),
            "items": [ref.to_dict() for ref in self.items.values()],
            "duplicates": ["{0}/{1}".format(*key) for key in self.duplicates],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def strip_markers(text: str) -> str:
    """\u79fb\u9664\u6807\u8bb0\uff08\u7528\u4e8e\u6b63\u6587\u6e32\u67d3\u3001\u9884\u89c8\u4e0e\u672c\u6587\u6bd4\u5bf9\uff09\u3002"""
    cleaned = DOC_ITEM_RE.sub("", str(text or ""))
    return re.sub(r"[ \t]+\n", "\n", cleaned)


def has_markers(text: str) -> bool:
    return bool(DOC_ITEM_RE.search(str(text or "")))


def parse_marker(marker: str) -> Tuple[Optional[ItemRef], Optional[str]]:
    """\u89e3\u6790\u5355\u4e2a\u6807\u8bb0\uff1b\u8fd4\u56de ``(ref, \u9519\u8bef\u8bf4\u660e)``\u3002"""
    match = DOC_ITEM_RE.search(marker)
    if match is None:
        return None, "\u4e0d\u662f\u5408\u6cd5\u7684 DOC-ITEM \u6807\u8bb0\u3002"
    attrs = {key: value for key, value in _ATTR_RE.findall(match.group("body"))}
    project_id = attrs.get("projectId", "").strip()
    item_id = attrs.get("id", "").strip()
    kind = attrs.get("kind", "").strip().lower() or "requirement"
    alias = attrs.get("alias", "").strip()
    if not project_id:
        return None, "\u6807\u8bb0\u7f3a\u5c11 projectId\u3002"
    if not item_id:
        return None, "\u6807\u8bb0\u7f3a\u5c11 id\u3002"
    if kind not in ITEM_KINDS:
        return None, "\u672a\u77e5\u6761\u76ee\u79cd\u7c7b\uff1a{0}\u3002".format(kind)
    if not _is_uuid_like(item_id):
        return None, "\u6761\u76ee id \u5e94\u4e3a UUID\uff1a{0}\u3002".format(item_id)
    return ItemRef(project_id=project_id, item_id=item_id, kind=kind, alias=alias), None


def build_item_index(
    documents: Sequence[Tuple[str, str]],
    *,
    project_id: str = "",
) -> ItemIndex:
    """\u4ece ``[(rel_path, text)]`` \u6784\u5efa\u7d22\u5f15\uff1b\u540c ID \u591a\u6b21\u51fa\u73b0\u8bb0\u4e3a\u91cd\u590d\u3002"""
    index = ItemIndex()
    for rel_path, text in documents:
        heading_no = ""
        for line_no, line in enumerate(str(text or "").splitlines(), start=1):
            heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
            if heading_match:
                heading_no = _leading_number(heading_match.group(1))
                if heading_no:
                    index.headings.setdefault(rel_path, []).append(heading_no)
            for match in DOC_ITEM_RE.finditer(line):
                ref, error = parse_marker(match.group(0))
                location = ItemLocation(rel_path=rel_path, line_no=line_no, heading_no=heading_no)
                if ref is None:
                    index.issues.append(ItemIssue(rel_path, line_no, error or "\u6807\u8bb0\u65e0\u6548", "error"))
                    continue
                if project_id and ref.project_id != project_id:
                    index.issues.append(
                        ItemIssue(rel_path, line_no, "\u6807\u8bb0\u5c5e\u4e8e\u5176\u4ed6\u9879\u76ee\uff1a{0}\u3002".format(ref.project_id), "error")
                    )
                    continue
                index.add(ref, location)
    for key in index.duplicates:
        for place in index.locations[key]:
            index.issues.append(
                ItemIssue(place.rel_path, place.line_no, "\u6761\u76ee ID \u91cd\u590d\uff1a{0}/{1}\u3002".format(*key), "error")
            )
    return index


def new_ref(project_id: str, kind: str = "requirement", alias: str = "") -> ItemRef:
    """\u521b\u5efa\u65b0\u6761\u76ee\u3002"""
    kind_key = str(kind or "requirement").strip().lower()
    if kind_key not in ITEM_KINDS:
        raise ValueError("\u672a\u77e5\u6761\u76ee\u79cd\u7c7b\uff1a{0}".format(kind))
    return ItemRef(project_id=str(project_id), item_id=str(uuid.uuid4()), kind=kind_key, alias=str(alias or ""))


def copy_ref(ref: ItemRef, project_id: str = "") -> ItemRef:
    """\u590d\u5236\u6761\u76ee\uff1a\u751f\u6210**\u65b0 ID**\uff08\u522b\u540d\u53ef\u7ee7\u627f\uff09\u3002"""
    return ItemRef(
        project_id=project_id or ref.project_id,
        item_id=str(uuid.uuid4()),
        kind=ref.kind,
        alias=ref.alias,
    )


def append_marker(text: str, ref: ItemRef, *, line_no: int) -> str:
    """\u5728\u6307\u5b9a\u884c\u672b\u8ffd\u52a0\u6807\u8bb0\uff08\u4e0d\u6539\u5176\u4ed6\u884c\uff09\u3002"""
    lines = str(text or "").splitlines()
    if line_no < 1 or line_no > len(lines):
        raise ValueError("\u884c\u53f7\u8d85\u51fa\u8303\u56f4\uff1a{0}".format(line_no))
    lines[line_no - 1] = lines[line_no - 1].rstrip() + " " + ref.render()
    return "\n".join(lines) + ("\n" if str(text or "").endswith("\n") else "")


def renumber_keeps_ids(before: str, after: str) -> bool:
    """\u91cd\u7f16\u53f7/\u79fb\u52a8\u540e\u6761\u76ee\u96c6\u5408\u662f\u5426\u4e0d\u53d8\uff08\u53ea\u770b ID\uff09\u3002"""
    return _marker_keys(before) == _marker_keys(after)


def _marker_keys(text: str) -> List[Tuple[str, str]]:
    keys: List[Tuple[str, str]] = []
    for match in DOC_ITEM_RE.finditer(str(text or "")):
        ref, _error = parse_marker(match.group(0))
        if ref is not None:
            keys.append(ref.key)
    return sorted(keys)


@dataclass
class MigrationSuggestion:
    """\u65e7\u7f16\u53f7 \u2192 \u7a33\u5b9a\u6761\u76ee\u7684\u5efa\u8bae\u3002"""

    rel_path: str
    line_no: int
    legacy_no: str
    proposed_id: str
    confident: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "lineNo": self.line_no,
            "legacyNo": self.legacy_no,
            "proposedId": self.proposed_id,
            "confident": self.confident,
            "reason": self.reason,
        }


@dataclass
class MigrationPlan:
    """\u8fc1\u79fb\u8ba1\u5212\uff08\u5efa\u8bae + \u6b67\u4e49\uff09\u3002"""

    project_id: str = ""
    suggestions: List[MigrationSuggestion] = field(default_factory=list)
    ambiguous: List[MigrationSuggestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def confident(self) -> List[MigrationSuggestion]:
        return [item for item in self.suggestions if item.confident]

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "confident": [item.to_dict() for item in self.confident],
            "ambiguous": [item.to_dict() for item in self.ambiguous],
            "warnings": list(self.warnings),
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u65e7\u7f16\u53f7\u8fc1\u79fb\u5efa\u8bae",
            "",
            "- \u53ef\u786e\u8ba4\uff1a{0} \u9879\uff1b\u6b67\u4e49\u5f85\u4eba\u5de5\u590d\u6838\uff1a{1} \u9879".format(
                len(self.confident), len(self.ambiguous)
            ),
        ]
        if self.warnings:
            lines.append("")
            lines.extend("- \u63d0\u9192\uff1a{0}".format(item) for item in self.warnings)
        if self.confident:
            lines.append("")
            lines.append("| \u7ae0\u8282 | \u884c | \u65e7\u7f16\u53f7 | \u5efa\u8bae\u6761\u76ee ID |")
            lines.append("|------|----|--------|--------------|")
            for item in self.confident:
                lines.append(
                    "| {0} | {1} | {2} | {3} |".format(item.rel_path, item.line_no, item.legacy_no, item.proposed_id)
                )
        if self.ambiguous:
            lines.append("")
            lines.append("**\u6b67\u4e49\uff08\u9700\u4eba\u5de5\u9009\u62e9\uff0c\u4e0d\u81ea\u52a8\u5199\u5165\uff09\uff1a**")
            lines.extend(
                "- {0}:{1} \u65e7\u7f16\u53f7 {2}\uff1a{3}".format(
                    item.rel_path, item.line_no, item.legacy_no, item.reason
                )
                for item in self.ambiguous
            )
        return "\n".join(lines)


def plan_legacy_migration(
    documents: Sequence[Tuple[str, str]],
    *,
    project_id: str,
) -> MigrationPlan:
    """\u4e3a\u672a\u6807\u8bb0\u7684\u65e7\u7f16\u53f7\u6761\u76ee\u751f\u6210\u8fc1\u79fb\u5efa\u8bae\u3002

    \u53ea\u5efa\u8bae**\u53ef\u552f\u4e00\u5b9a\u4f4d**\u7684\u6761\u76ee\uff08\u7f16\u53f7\u5728\u5168\u96c6\u5408\u5185\u552f\u4e00\uff09\uff1b
    \u540c\u53f7\u8de8\u6587\u6863\u51fa\u73b0\u5219\u8fdb\u5165\u6b67\u4e49\u5217\u8868\uff0c\u4e0d\u81ea\u52a8\u5199\u5165\u3002
    """
    plan = MigrationPlan(project_id=project_id)
    seen: Dict[str, List[Tuple[str, int]]] = {}
    candidates: List[Tuple[str, int, str]] = []
    for rel_path, text in documents:
        heading_no = ""
        for line_no, line in enumerate(str(text or "").splitlines(), start=1):
            heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
            if heading_match:
                heading_no = _leading_number(heading_match.group(1))
                continue
            if DOC_ITEM_RE.search(line):
                continue
            legacy = _leading_number(line)
            if not legacy:
                continue
            key = "{0}@{1}".format(heading_no, legacy)
            seen.setdefault(key, []).append((rel_path, line_no))
            candidates.append((rel_path, line_no, legacy))

    for rel_path, line_no, legacy in candidates:
        heading_no = _nearest_heading(documents, rel_path, line_no)
        key = "{0}@{1}".format(heading_no, legacy)
        places = seen.get(key, [])
        if len(places) > 1:
            plan.ambiguous.append(
                MigrationSuggestion(
                    rel_path=rel_path,
                    line_no=line_no,
                    legacy_no=legacy,
                    proposed_id="",
                    confident=False,
                    reason="\u540c\u4e00\u7f16\u53f7\u5728 {0} \u5904\u51fa\u73b0\uff0c\u65e0\u6cd5\u552f\u4e00\u5b9a\u4f4d\u3002".format(len(places)),
                )
            )
            continue
        plan.suggestions.append(
            MigrationSuggestion(
                rel_path=rel_path,
                line_no=line_no,
                legacy_no=legacy,
                proposed_id=str(uuid.uuid4()),
                confident=True,
                reason="\u7f16\u53f7\u5728\u96c6\u5408\u5185\u552f\u4e00",
            )
        )
    if not candidates:
        plan.warnings.append("\u672a\u53d1\u73b0\u53ef\u8fc1\u79fb\u7684\u65e7\u7f16\u53f7\u6761\u76ee\u3002")
    if plan.ambiguous:
        plan.warnings.append(
            "\u6709 {0} \u9879\u6b67\u4e49\u9700\u4eba\u5de5\u590d\u6838\uff0c\u672c\u6b21\u4e0d\u5199\u5165\u3002".format(len(plan.ambiguous))
        )
    plan.warnings.append("\u672a\u6807\u8bb0\u5185\u5bb9\u4e0d\u81ea\u52a8\u8ba1\u5165\u8986\u76d6\u7387\u5206\u6bcd\u3002")
    return plan


def apply_migration(
    plan: MigrationPlan,
    documents: Dict[str, str],
    *,
    selected: Optional[Sequence[str]] = None,
    writer=None,
    project_id: str = "",
) -> dict:
    """\u628a\u5df2\u786e\u8ba4\u7684\u5efa\u8bae\u5199\u5165\uff08\u901a\u8fc7 ``ContentWriter`` \u4e8b\u52a1\uff09\u3002

    ``selected`` \u4e3a ``"relPath:lineNo"`` \u96c6\u5408\uff1b\u7f3a\u7701\u65f6\u53ea\u5e94\u7528\u201c\u53ef\u786e\u8ba4\u201d\u9879\u3002
    \u4efb\u4f55\u5199\u5165\u5931\u8d25\u4e0d\u4f1a\u4ea7\u751f\u90e8\u5206\u5199\u5165\uff08\u4ea4\u7ed9 writer \u4e8b\u52a1\uff09\u3002
    """
    selected_set = {str(item) for item in (selected or [])}
    applied: List[str] = []
    skipped: List[str] = []
    for suggestion in plan.confident:
        token = "{0}:{1}".format(suggestion.rel_path, suggestion.line_no)
        if selected_set and token not in selected_set:
            skipped.append(token)
            continue
        text = documents.get(suggestion.rel_path)
        if text is None:
            skipped.append(token)
            continue
        ref = ItemRef(
            project_id=project_id or plan.project_id,
            item_id=suggestion.proposed_id,
            kind="requirement",
        )
        try:
            updated = append_marker(text, ref, line_no=suggestion.line_no)
        except ValueError:
            skipped.append(token)
            continue
        documents[suggestion.rel_path] = updated
        applied.append(token)
        if writer is not None:
            writer.write(suggestion.rel_path, updated)
    for item in plan.ambiguous:
        skipped.append("{0}:{1}".format(item.rel_path, item.line_no))
    return {"applied": applied, "skipped": skipped}


def map_review_locations(
    comments: Sequence[object],
    index: ItemIndex,
    *,
    duplicates: Optional[Sequence[Tuple[str, str]]] = None,
) -> dict:
    """\u628a\u53ef\u786e\u8ba4\u7684\u65e7\u8bc4\u5ba1\u5b9a\u4f4d\u6620\u5c04\u5230\u7a33\u5b9a\u6761\u76ee\uff1b\u6b67\u4e49\u4fdd\u7559\u5f85\u4eba\u5de5\u590d\u6838\u3002

    \u8fd4\u56de ``{"mapped": [...], "ambiguous": [...], "unmatched": [...]}``\u3002
    """
    mapped: List[dict] = []
    ambiguous: List[dict] = []
    unmatched: List[dict] = []
    dup_keys = set(duplicates) if duplicates else set(index.duplicates)
    # 同一 (relPath, lineNo) 上的所有条目（跨 key）：匹配到多个就是歧义。
    by_location: Dict[Tuple[str, int], List[Tuple[Tuple[str, str], ItemRef]]] = {}
    for key, ref in index.items.items():
        for place in index.locations.get(key, []):
            by_location.setdefault((place.rel_path, place.line_no), []).append((key, ref))
    for comment in comments:
        rel_path = str(getattr(comment, "rel_path", "") or "")
        line_no = int(getattr(comment, "line_no", 0) or 0)
        candidates = by_location.get((rel_path, line_no), [])
        payload = {
            "commentId": str(getattr(comment, "comment_id", "") or ""),
            "relPath": rel_path,
            "lineNo": line_no,
        }
        if len(candidates) == 1:
            payload["itemId"] = candidates[0][1].item_id
            payload["projectId"] = candidates[0][1].project_id
            if candidates[0][0] in dup_keys:
                payload["reason"] = (
                    "duplicate item id：条目 ID 在集合中重复，请确认唯一性。"
                )
            mapped.append(payload)
        elif len(candidates) > 1:
            payload["reason"] = "\u540c\u4e00\u4f4d\u7f6e\u5339\u914d\u5230\u591a\u4e2a\u6761\u76ee\u3002"
            ambiguous.append(payload)
        else:
            payload["reason"] = "\u672a\u627e\u5230\u5bf9\u5e94\u7a33\u5b9a\u6761\u76ee\uff08\u53ef\u80fd\u5c1a\u672a\u8fc1\u79fb\uff09\u3002"
            unmatched.append(payload)
    return {"mapped": mapped, "ambiguous": ambiguous, "unmatched": unmatched}


def backup_legacy_item_data(
    store,
    backup_dir: Path,
    *,
    stamp: str = "",
) -> Optional[str]:
    """\u8fc1\u79fb\u524d\u5907\u4efd\u65e7\u8bc4\u5ba1\u53f0\u8d26\uff08\u4fdd\u7559\u53ef\u56de\u9000\u526f\u672c\uff09\u3002"""
    import shutil
    from datetime import datetime, timezone

    source = Path(getattr(store, "comments_file", ""))
    if not source.is_file():
        return None
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp_value = stamp or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target = target_dir / "comments.{0}.bak.json".format(stamp_value)
    shutil.copy2(source, target)
    return str(target)


def _is_uuid_like(value: str) -> bool:
    text = str(value or "")
    if len(text) < 8:
        return False
    return all(char.isalnum() or char in "-_" for char in text)


def _leading_number(text: str) -> str:
    match = re.match(r"^\s*(?:[-*+]\s+)?(\d+(?:\.\d+)*)", str(text or ""))
    return match.group(1) if match else ""


def _nearest_heading(documents: Sequence[Tuple[str, str]], rel_path: str, line_no: int) -> str:
    for path, text in documents:
        if path != rel_path:
            continue
        heading = ""
        for index, line in enumerate(str(text or "").splitlines(), start=1):
            if index > line_no:
                break
            match = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
            if match:
                number = _leading_number(match.group(1))
                if number:
                    heading = number
        return heading
    return ""