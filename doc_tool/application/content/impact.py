# -*- coding: utf-8 -*-
"""\u53d8\u66f4\u5f71\u54cd\u4e0e\u590d\u6838\uff08V2.9 29-E / 5.1\uff5e5.4\uff09\u3002

- ``item_semantic_hash``\uff1a\u53ea\u770b**\u8bed\u4e49**\uff08\u6b63\u6587/\u6807\u9898\u8bed\u4e49/\u76f8\u5173\u8d44\u6e90\uff09\uff0c
  **\u6392\u9664\u4f4d\u7f6e\u4e0e\u7f16\u53f7\u53d8\u5316**\uff1b\u6587\u6863\u89c4\u8303\uff08\u6a21\u677f\uff09\u53d8\u5316**\u5355\u5217**\u4e3a\u4e00\u7c7b\u5f71\u54cd\u3002
- ``compute_impact``\uff1a\u6cbf\u5173\u7cfb\u56fe\u7b97**\u76f4\u63a5 + \u4f20\u9012**\u5f71\u54cd\uff0c\u7ed9\u51fa\u8def\u5f84\u89e3\u91ca\uff1b\u5220\u9664/\u60ac\u7a7a\u7aef\u70b9\u4e5f\u5217\u5165\uff1bvisited \u9632\u73af\u3002
- ``ReviewRecord``\uff1a\u4fdd\u5b58\u4e24\u7aef\u5f53\u524d hash\uff0c\u518d\u6b21\u4fee\u6539\u540e\u81ea\u52a8\u91cd\u65b0\u5f85\u590d\u6838\uff1b**\u4e0d\u81ea\u52a8\u4fee\u6539\u4e0b\u6e38\u6b63\u6587**\u3002
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from doc_tool.application.content.relations import Relation, RelationGraph
from doc_tool.application.content.traceable_items import ItemKey, ItemRef

#: \u5f71\u54cd\u7c7b\u578b\u3002
IMPACT_CONTENT = "content"
IMPACT_DELETED = "deleted"
IMPACT_DANGLING = "dangling"
IMPACT_SPEC = "spec"
#: \u89c4\u8303\uff08\u6a21\u677f/\u89c4\u5219\uff09\u56e0\u7d20\u7684\u8eab\u4efd\u540d\u3002
SPEC_FACTORS = ("template", "rules", "terms")


@dataclass
class ItemSnapshot:
    """\u4e00\u6761\u6761\u76ee\u7684\u8bed\u4e49\u5feb\u7167\u3002"""

    key: ItemKey
    title: str = ""
    body: str = ""
    resources: Tuple[str, ...] = ()

    def semantic_hash(self) -> str:
        return item_semantic_hash(self)


@dataclass
class ImpactEntry:
    """\u4e00\u6761\u5f71\u54cd\u8bb0\u5f55\u3002"""

    relation_id: str
    impact_type: str
    source: ItemKey
    target: Optional[ItemKey]
    path: List[ItemKey] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "relationId": self.relation_id,
            "impactType": self.impact_type,
            "source": "{0}/{1}".format(*self.source) if self.source else "",
            "target": "{0}/{1}".format(*self.target) if self.target else "",
            "path": ["{0}/{1}".format(*key) for key in self.path],
            "reason": self.reason,
        }


@dataclass
class ImpactReport:
    """\u53d8\u66f4\u5f71\u54cd\u62a5\u544a\u3002"""

    changed: Dict[ItemKey, str] = field(default_factory=dict)
    entries: List[ImpactEntry] = field(default_factory=list)
    spec_changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def affected(self) -> List[ItemKey]:
        seen: List[ItemKey] = []
        for entry in self.entries:
            if entry.target and entry.target not in seen:
                seen.append(entry.target)
        return seen

    @property
    def direct(self) -> List[ImpactEntry]:
        return [entry for entry in self.entries if len(entry.path) <= 2]

    @property
    def transitive(self) -> List[ImpactEntry]:
        return [entry for entry in self.entries if len(entry.path) > 2]

    def to_dict(self) -> dict:
        return {
            "changed": ["{0}/{1}".format(*key) for key in self.changed],
            "specChanges": list(self.spec_changes),
            "direct": [entry.to_dict() for entry in self.direct],
            "transitive": [entry.to_dict() for entry in self.transitive],
            "affected": ["{0}/{1}".format(*key) for key in self.affected],
            "warnings": list(self.warnings),
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u53d8\u66f4\u5f71\u54cd",
            "",
            "- \u53d8\u66f4\u6761\u76ee\uff1a{0}".format(len(self.changed)),
            "- \u76f4\u63a5\u5f71\u54cd\uff1a{0}\uff1b\u4f20\u9012\u5f71\u54cd\uff1a{1}".format(
                len(self.direct), len(self.transitive)
            ),
            "- \u53d7\u5f71\u54cd\u6761\u76ee\u5408\u8ba1\uff1a{0}".format(len(self.affected)),
        ]
        if self.spec_changes:
            lines.append("- \u89c4\u8303\u7ea7\u53d8\u5316\uff1a{0}".format("\u3001".join(self.spec_changes)))
        if self.entries:
            lines.append("")
            lines.append("| \u7c7b\u578b | \u6765\u6e90 | \u76ee\u6807 | \u8def\u5f84 | \u4f9d\u636e |")
            lines.append("|------|------|------|------|------|")
            for entry in self.entries:
                lines.append(
                    "| {0} | {1} | {2} | {3} | {4} |".format(
                        entry.impact_type,
                        "{0}/{1}".format(*entry.source),
                        "{0}/{1}".format(*entry.target) if entry.target else "\u2014",
                        " \u2192 ".join("{0}/{1}".format(*key) for key in entry.path) or "\u2014",
                        entry.reason,
                    )
                )
        if self.warnings:
            lines.append("")
            lines.extend("- \u63d0\u9192\uff1a{0}".format(item) for item in self.warnings)
        return "\n".join(lines)

    def export(self, fmt: str = "markdown") -> str:
        key = str(fmt or "markdown").strip().lower()
        if key in ("md", "markdown", "text"):
            return self.markdown_text()
        if key == "json":
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        raise ValueError("\u4e0d\u652f\u6301\u7684\u5bfc\u51fa\u683c\u5f0f\uff1a{0}".format(fmt))


def item_semantic_hash(snapshot: ItemSnapshot) -> str:
    """\u8bed\u4e49 hash\uff1a\u6b63\u6587 + \u6807\u9898\u8bed\u4e49 + \u76f8\u5173\u8d44\u6e90\u5185\u5bb9\u3002

    **\u4e0d\u5305\u542b\u4f4d\u7f6e\u3001\u7f16\u53f7\u3001\u884c\u53f7**\uff1b\u6807\u9898\u4e2d\u7684\u524d\u5bfc\u7f16\u53f7\u4f1a\u88ab\u5254\u9664\uff0c
    \u56e0\u6b64\u79fb\u52a8\u6216\u91cd\u7f16\u53f7\u4e0d\u4f1a\u89e6\u53d1\u5f71\u54cd\u3002
    """
    digest = hashlib.sha256()
    digest.update(_semantic_title(snapshot.title).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(_normalize_body(snapshot.body).encode("utf-8"))
    for resource in sorted(snapshot.resources or ()):
        digest.update(b"\x01")
        digest.update(str(resource).replace("\\", "/").encode("utf-8"))
    return digest.hexdigest()


def spec_factor_hash(values: Dict[str, str]) -> str:
    """\u89c4\u8303\u56e0\u7d20\uff08\u6a21\u677f/\u89c4\u5219/\u672f\u8bed\uff09\u7684\u5408\u5e76 hash\u3002"""
    digest = hashlib.sha256()
    for key in SPEC_FACTORS:
        digest.update(key.encode("utf-8"))
        digest.update(b"=")
        digest.update(str(values.get(key, "")).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def diff_snapshots(
    before: Dict[ItemKey, ItemSnapshot],
    after: Dict[ItemKey, ItemSnapshot],
    *,
    spec_before: Optional[Dict[str, str]] = None,
    spec_after: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[ItemKey, str], List[str]]:
    """\u6bd4\u5bf9\u5feb\u7167\uff0c\u8fd4\u56de ``(\u53d8\u66f4\u6761\u76ee -> \u539f\u56e0, \u89c4\u8303\u7ea7\u53d8\u5316)``\u3002

    - \u4ec5\u4f4d\u7f6e/\u7f16\u53f7\u53d8\u5316 \u2192 **\u4e0d\u8ba1\u5165\u53d8\u66f4**\uff08\u8bed\u4e49 hash \u76f8\u540c\uff09\uff1b
    - \u6b63\u6587\u6216\u8d44\u6e90\u53d8\u5316 \u2192 \u8ba1\u5165\uff1b
    - \u65b0\u589e \u2192 \u8ba1\u5165\uff08add\uff09\uff1b\u5220\u9664 \u2192 \u8ba1\u5165\uff08deleted\uff09\u3002
    """
    changed: Dict[ItemKey, str] = {}
    for key, snapshot in after.items():
        old = before.get(key)
        if old is None:
            changed[key] = "\u65b0\u589e\u6761\u76ee"
            continue
        if old.semantic_hash() == snapshot.semantic_hash():
            continue
        if _normalize_body(old.body) != _normalize_body(snapshot.body):
            changed[key] = "\u6b63\u6587\u8bed\u4e49\u53d8\u5316"
        elif _semantic_title(old.title) != _semantic_title(snapshot.title):
            changed[key] = "\u6807\u9898\u8bed\u4e49\u53d8\u5316"
        else:
            changed[key] = "\u76f8\u5173\u8d44\u6e90\u53d8\u5316"
    for key in before:
        if key not in after:
            changed[key] = "\u6761\u76ee\u5df2\u5220\u9664"
    spec_changes: List[str] = []
    if spec_before is not None and spec_after is not None:
        for factor in SPEC_FACTORS:
            if str(spec_before.get(factor, "")) != str(spec_after.get(factor, "")):
                spec_changes.append(factor)
    return changed, spec_changes


def compute_impact(
    changed: Dict[ItemKey, str],
    graph: RelationGraph,
    *,
    known_items: Optional[Iterable[ItemKey]] = None,
    max_depth: int = 8,
) -> ImpactReport:
    """\u6cbf\u5173\u7cfb\u56fe\u8ba1\u7b97\u76f4\u63a5/\u4f20\u9012\u5f71\u54cd\uff08\u5e26\u8def\u5f84\u4e0e visited \u9632\u73af\uff09\u3002

    \u65b9\u5411\uff1a\u6cbf\u5173\u7cfb\u7684**\u53cd\u5411**\u4f20\u64ad\u2014\u2014\u4e0a\u6e38\u53d8\u66f4\u5f71\u54cd\u4e0b\u6e38\u3002\u4e0d\u4f1a\u4fee\u6539\u4efb\u4f55\u6b63\u6587\u3002
    """
    known: Set[ItemKey] = set(known_items) if known_items is not None else set()
    adjacency: Dict[ItemKey, List[Relation]] = {}
    for relation in graph.relations:
        adjacency.setdefault(relation.target.key, []).append(relation)

    report = ImpactReport(changed=dict(changed))
    for key, reason in changed.items():
        if "删除" in reason:
            report.entries.append(
                ImpactEntry(
                    relation_id="",
                    impact_type=IMPACT_DELETED,
                    source=key,
                    target=key,
                    path=[key],
                    reason="条目已删除，下游关联需重新确认。",
                )
            )
        for entry in _walk(key, adjacency, known, max_depth):
            report.entries.append(entry)
    if not report.entries:
        report.warnings.append("\u672a\u53d1\u73b0\u4e0b\u6e38\u5f71\u54cd\uff08\u53ef\u80fd\u5c1a\u672a\u5efa\u7acb\u5173\u7cfb\uff09\u3002")
    return report


def _walk(
    origin: ItemKey,
    adjacency: Dict[ItemKey, List[Relation]],
    known: Set[ItemKey],
    max_depth: int,
) -> List[ImpactEntry]:
    entries: List[ImpactEntry] = []
    visited: Set[ItemKey] = {origin}
    queue: List[Tuple[ItemKey, List[ItemKey]]] = [(origin, [origin])]
    while queue:
        node, path = queue.pop(0)
        if len(path) > max_depth:
            continue
        for relation in adjacency.get(node, []):
            source = relation.source.key
            new_path = path + [source]
            if source in path:
                # \u73af\u8def\uff1a\u8bb0\u5f55\u4e00\u6b21\u4f9d\u636e\u540e\u505c\u6b62\uff0c\u907f\u514d\u65e0\u9650\u5faa\u73af
                entries.append(
                    ImpactEntry(
                        relation_id=relation.relation_id,
                        impact_type=IMPACT_DANGLING,
                        source=source,
                        target=node,
                        path=new_path,
                        reason="\u68c0\u6d4b\u5230\u73af\u8def\uff0c\u5df2\u622a\u65ad\u3002",
                    )
                )
                continue
            impact_type = IMPACT_CONTENT
            reason = "\u4e0a\u6e38\u6761\u76ee\u53d8\u66f4\uff08{0}\uff09".format(relation.type)
            if known and source not in known:
                impact_type = IMPACT_DANGLING
                reason = "\u5173\u8054\u7aef\u70b9\u4e0d\u5b58\u5728\uff08\u60ac\u7a7a\uff09"
            entries.append(
                ImpactEntry(
                    relation_id=relation.relation_id,
                    impact_type=impact_type,
                    source=source,
                    target=node,
                    path=new_path,
                    reason=reason,
                )
            )
            if source not in visited:
                visited.add(source)
                queue.append((source, new_path))
    return entries


@dataclass
class ReviewRecord:
    """\u5173\u7cfb\u7ea7\u590d\u6838\u8bb0\u5f55\uff08\u4e24\u7aef\u5f53\u524d hash\uff09\u3002"""

    relation_id: str
    source: ItemKey
    target: ItemKey
    source_hash: str = ""
    target_hash: str = ""
    status: str = "\u901a\u8fc7"
    reviewed_at: str = ""
    reviewer: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "relationId": self.relation_id,
            "source": "{0}/{1}".format(*self.source),
            "target": "{0}/{1}".format(*self.target),
            "sourceHash": self.source_hash,
            "targetHash": self.target_hash,
            "status": self.status,
            "reviewedAt": self.reviewed_at,
            "reviewer": self.reviewer,
            "note": self.note,
        }


class ReviewRecordStore:
    """\u590d\u6838\u8bb0\u5f55\u5b58\u50a8\uff08\u9010\u884c JSON\uff0c\u8ffd\u52a0\u5f0f\uff09\u3002"""

    def __init__(self, state_dir: Union[str, Path]) -> None:
        self.file = Path(state_dir) / "relation_reviews.json"

    def records(self) -> List[ReviewRecord]:
        if not self.file.is_file():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("reviews") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        result: List[ReviewRecord] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            source = _split_key(raw.get("source"))
            target = _split_key(raw.get("target"))
            if source is None or target is None:
                continue
            result.append(
                ReviewRecord(
                    relation_id=str(raw.get("relationId", "") or ""),
                    source=source,
                    target=target,
                    source_hash=str(raw.get("sourceHash", "") or ""),
                    target_hash=str(raw.get("targetHash", "") or ""),
                    status=str(raw.get("status", "") or "\u901a\u8fc7"),
                    reviewed_at=str(raw.get("reviewedAt", "") or ""),
                    reviewer=str(raw.get("reviewer", "") or ""),
                    note=str(raw.get("note", "") or ""),
                )
            )
        return result

    def save(self, records: Sequence[ReviewRecord]) -> Path:
        payload = {"reviews": [item.to_dict() for item in records]}
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        import os

        os.replace(str(tmp), str(self.file))
        return self.file

    def confirm(
        self,
        relation_id: str,
        source: ItemKey,
        target: ItemKey,
        *,
        source_hash: str,
        target_hash: str,
        reviewer: str = "",
        note: str = "",
    ) -> ReviewRecord:
        """\u786e\u8ba4\u590d\u6838\uff1a\u4fdd\u5b58\u4e24\u7aef**\u5f53\u524d** hash\u3002"""
        records = [item for item in self.records() if item.relation_id != relation_id]
        record = ReviewRecord(
            relation_id=relation_id,
            source=source,
            target=target,
            source_hash=source_hash,
            target_hash=target_hash,
            status="\u901a\u8fc7",
            reviewed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            reviewer=str(reviewer or ""),
            note=str(note or ""),
        )
        records.append(record)
        self.save(records)
        return record

    def stale_relations(
        self,
        hashes: Dict[ItemKey, str],
        *,
        missing: Optional[Iterable[ItemKey]] = None,
    ) -> List[ReviewRecord]:
        """\u518d\u6b21\u4fee\u6539\u540e\u4f7f\u590d\u6838\u5931\u6548\uff1a\u4efb\u4e00\u7aef hash \u53d8\u5316\u6216\u7aef\u70b9\u6d88\u5931\u3002"""
        missing_set = set(missing or ())
        stale: List[ReviewRecord] = []
        records = self.records()
        for record in records:
            if record.source in missing_set or record.target in missing_set:
                record.status = "\u5f85\u590d\u6838"
                stale.append(record)
                continue
            if hashes.get(record.source, "") != record.source_hash:
                record.status = "\u5f85\u590d\u6838"
                stale.append(record)
                continue
            if hashes.get(record.target, "") != record.target_hash:
                record.status = "待复核"
                stale.append(record)
        if stale:
            # 失效状态必须落盘，否则下一次读取仍显示“通过”。
            self.save(records)
        return stale

    def pending(self) -> List[ReviewRecord]:
        return [item for item in self.records() if item.status != "\u901a\u8fc7"]


def _split_key(value) -> Optional[ItemKey]:
    text = str(value or "")
    if "/" not in text:
        return None
    project_id, _, item_id = text.partition("/")
    if not project_id or not item_id:
        return None
    return (project_id, item_id)


def _semantic_title(title: str) -> str:
    """\u6807\u9898\u8bed\u4e49\uff1a\u53bb\u6389\u524d\u5bfc\u7f16\u53f7\u4e0e\u591a\u4f59\u7a7a\u767d\u3002"""
    text = re.sub(r"^\s*\d+(?:\.\d+)*[.\u3001\s]*", "", str(title or ""))
    return " ".join(text.split())


def _normalize_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in str(body or "").splitlines()).strip()