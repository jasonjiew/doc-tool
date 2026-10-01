# -*- coding: utf-8 -*-
"""\u663e\u5f0f\u5173\u7cfb\u56fe\uff08V2.9 29-C / 3.1\u30013.2\u30013.3\uff09\u3002

``relations.yml`` schema 1\uff1a**\u663e\u5f0f\u58f0\u660e**\u6761\u76ee\u4e4b\u95f4\u7684\u591a\u5bf9\u591a\u5173\u7cfb\uff0c\u4e0d\u7528\u76f8\u540c\u7f16\u53f7\u63a8\u65ad\u3002

    schemaVersion: 1
    relations:
      - relationId: <uuid>
        type: satisfies | verifies | depends_on
        from: {projectId: ..., itemId: ...}
        to:   {projectId: ..., itemId: ...}
        note: ""

\u8fb9\u754c\uff1a\u7aef\u70b9\u5fc5\u987b\u5b58\u5728\uff08\u5426\u5219\u4e3a\u60ac\u7a7a\uff09\uff1b\u540c\u5411\u91cd\u590d\u8fb9\u53bb\u91cd\uff1b\u81ea\u73af\u4e0e\u73af\u8def\u88ab\u68c0\u51fa\uff1b
\u635f\u574f\u6587\u4ef6\u53ea\u8bfb\u62d2\u7edd\u800c\u4e0d\u9759\u9ed8\u4e22\u5f03\uff1b\u53ea\u8bfb\u9879\u76ee\u7981\u6b62\u5199\u5165\u3002
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

import yaml

#: \u5173\u7cfb\u6587\u4ef6\u540d\u4e0e\u683c\u5f0f\u7248\u672c\u3002
RELATIONS_NAME = "relations.yml"
RELATIONS_SCHEMA_VERSION = 1
#: \u5173\u7cfb\u7c7b\u578b\u767d\u540d\u5355\uff08\u4e0e spec \u4e00\u81f4\uff09\u3002
RELATION_TYPES = ("satisfies", "verifies", "depends_on")
#: \u7aef\u70b9\u5c5e\u6027\u540d\u3002
_ENDPOINT_KEYS = ("projectId", "itemId")


@dataclass(frozen=True)
class Endpoint:
    """\u5173\u7cfb\u7aef\u70b9\u8eab\u4efd\uff08\u4e0e\u6761\u76ee\u8eab\u4efd\u4e00\u81f4\uff09\u3002"""

    project_id: str
    item_id: str

    @property
    def key(self) -> Tuple[str, str]:
        return (self.project_id, self.item_id)

    def to_dict(self) -> dict:
        return {"projectId": self.project_id, "itemId": self.item_id}

    def render(self) -> str:
        return "{0}/{1}".format(self.project_id, self.item_id)


@dataclass
class Relation:
    """\u4e00\u6761\u663e\u5f0f\u5173\u7cfb\u3002"""

    relation_id: str
    type: str
    source: Endpoint
    target: Endpoint
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "relationId": self.relation_id,
            "type": self.type,
            "from": self.source.to_dict(),
            "to": self.target.to_dict(),
            "note": self.note,
        }

    @property
    def edge_key(self) -> Tuple[str, Tuple[str, str], Tuple[str, str]]:
        return (self.type, self.source.key, self.target.key)


@dataclass
class RelationIssue:
    """\u5173\u7cfb\u7ea7\u95ee\u9898\u3002"""

    relation_id: str
    reason: str
    severity: str = "warning"

    def to_dict(self) -> dict:
        return {"relationId": self.relation_id, "reason": self.reason, "severity": self.severity}


@dataclass
class RelationGraph:
    """\u5173\u7cfb\u56fe\uff08\u53ea\u8bfb\u89c6\u56fe + \u6821\u9a8c\u7ed3\u679c\uff09\u3002"""

    relations: List[Relation] = field(default_factory=list)
    issues: List[RelationIssue] = field(default_factory=list)
    schema_version: int = RELATIONS_SCHEMA_VERSION

    def by_source(self, endpoint: Endpoint, type_: str = "") -> List[Relation]:
        return [
            item for item in self.relations
            if item.source.key == endpoint.key and (not type_ or item.type == type_)
        ]

    def by_target(self, endpoint: Endpoint, type_: str = "") -> List[Relation]:
        return [
            item for item in self.relations
            if item.target.key == endpoint.key and (not type_ or item.type == type_)
        ]

    @property
    def dangling(self) -> List[RelationIssue]:
        return [issue for issue in self.issues if "\u60ac\u7a7a" in issue.reason]

    @property
    def cycles(self) -> List[RelationIssue]:
        return [issue for issue in self.issues if "\u73af" in issue.reason]

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "count": len(self.relations),
            "relations": [item.to_dict() for item in self.relations],
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u5173\u7cfb\u56fe",
            "",
            "- \u5173\u7cfb\u6570\uff1a{0}\uff1b\u95ee\u9898\uff1a{1}".format(len(self.relations), len(self.issues)),
        ]
        if self.relations:
            lines.append("")
            lines.append("| \u7c7b\u578b | \u6e90 | \u76ee\u6807 | \u5907\u6ce8 |")
            lines.append("|------|----|------|------|")
            for item in self.relations:
                lines.append(
                    "| {0} | {1} | {2} | {3} |".format(
                        item.type, item.source.render(), item.target.render(), item.note or "\u2014"
                    )
                )
        if self.issues:
            lines.append("")
            lines.append("**\u95ee\u9898\uff1a**")
            lines.extend("- {0}\uff1a{1}".format(item.relation_id or "\u2014", item.reason) for item in self.issues)
        return "\n".join(lines)


def load_relations(path: Union[str, Path]) -> RelationGraph:
    """\u52a0\u8f7d\u5173\u7cfb\u6587\u4ef6\uff08\u53ea\u8bfb\uff09\uff1b\u635f\u574f\u6216\u7248\u672c\u4e0d\u652f\u6301\u65f6**\u62d2\u7edd**\u800c\u4e0d\u9759\u9ed8\u4e22\u5f03\u3002"""
    target = Path(path)
    if not target.is_file():
        return RelationGraph()
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError, OSError) as exc:
        raise ValueError("\u5173\u7cfb\u6587\u4ef6\u89e3\u6790\u5931\u8d25\uff1a{0}".format(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("\u5173\u7cfb\u6587\u4ef6\u683c\u5f0f\u4e0d\u6b63\u786e\uff1a\u6839\u8282\u70b9\u5e94\u4e3a\u6620\u5c04\u3002")
    try:
        schema_version = int(data.get("schemaVersion", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("\u5173\u7cfb\u6587\u4ef6 schemaVersion \u5fc5\u987b\u662f\u6574\u6570\u3002") from exc
    if schema_version != RELATIONS_SCHEMA_VERSION:
        raise ValueError("\u4e0d\u652f\u6301\u7684\u5173\u7cfb\u6587\u4ef6\u7248\u672c\uff1a{0}".format(schema_version))
    graph = RelationGraph(schema_version=schema_version)
    for raw in data.get("relations") or []:
        if not isinstance(raw, dict):
            graph.issues.append(RelationIssue("", "\u5173\u7cfb\u6761\u76ee\u5e94\u4e3a\u6620\u5c04\uff0c\u5df2\u8df3\u8fc7\u3002", "error"))
            continue
        relation, error = _parse_relation(raw)
        if relation is None:
            graph.issues.append(RelationIssue(str(raw.get("relationId", "") or ""), error or "\u5173\u7cfb\u65e0\u6548", "error"))
            continue
        graph.relations.append(relation)
    return graph


def _parse_relation(raw: dict) -> Tuple[Optional[Relation], Optional[str]]:
    relation_type = str(raw.get("type", "") or "").strip()
    if relation_type not in RELATION_TYPES:
        return None, "\u672a\u77e5\u5173\u7cfb\u7c7b\u578b\uff1a{0}\u3002".format(relation_type or "(\u7a7a)")
    source = _parse_endpoint(raw.get("from"))
    target = _parse_endpoint(raw.get("to"))
    if source is None or target is None:
        return None, "\u5173\u7cfb\u7aef\u70b9\u5fc5\u987b\u540c\u65f6\u5305\u542b projectId \u4e0e itemId\u3002"
    relation_id = str(raw.get("relationId", "") or "").strip() or str(uuid.uuid4())
    return (
        Relation(
            relation_id=relation_id,
            type=relation_type,
            source=source,
            target=target,
            note=str(raw.get("note", "") or ""),
        ),
        None,
    )


def _parse_endpoint(raw) -> Optional[Endpoint]:
    if not isinstance(raw, dict):
        return None
    project_id = str(raw.get("projectId", "") or "").strip()
    item_id = str(raw.get("itemId", "") or "").strip()
    if not project_id or not item_id:
        return None
    return Endpoint(project_id, item_id)


def validate_graph(
    graph: RelationGraph,
    *,
    known_items: Optional[Iterable[Tuple[str, str]]] = None,
) -> RelationGraph:
    """\u6821\u9a8c\uff1a\u91cd\u590d\u8fb9\u3001\u81ea\u73af\u3001\u60ac\u7a7a\u7aef\u70b9\u4e0e\u73af\u8def\u3002\u8fd4\u56de\u540c\u4e00\u56fe\uff08\u8ffd\u52a0 issues\uff09\u3002"""
    issues = list(graph.issues)
    seen_edges: Dict[Tuple[str, Tuple[str, str], Tuple[str, str]], str] = {}
    for item in graph.relations:
        if item.source.key == item.target.key:
            issues.append(RelationIssue(item.relation_id, "\u81ea\u73af\u5173\u7cfb\uff1a\u6e90\u4e0e\u76ee\u6807\u4e3a\u540c\u4e00\u6761\u76ee\u3002", "error"))
        if item.edge_key in seen_edges:
            issues.append(
                RelationIssue(
                    item.relation_id,
                    "\u91cd\u590d\u5173\u7cfb\uff08\u4e0e {0} \u76f8\u540c\u7c7b\u578b\u4e0e\u7aef\u70b9\uff09\u3002".format(seen_edges[item.edge_key]),
                    "error",
                )
            )
        else:
            seen_edges[item.edge_key] = item.relation_id
    if known_items is not None:
        known: Set[Tuple[str, str]] = {tuple(key) for key in known_items}
        for item in graph.relations:
            for endpoint in (item.source, item.target):
                if endpoint.key not in known:
                    issues.append(
                        RelationIssue(item.relation_id, "\u60ac\u7a7a\u7aef\u70b9\uff1a{0} \u4e0d\u5b58\u5728\u3002".format(endpoint.render()), "error")
                    )
    for cycle in find_cycles(graph):
        issues.append(RelationIssue("", "\u5b58\u5728\u73af\u8def\uff1a{0}\u3002".format(" \u2192 ".join(cycle)), "warning"))
    graph.issues = issues
    return graph


def find_cycles(graph: RelationGraph) -> List[List[str]]:
    """\u5728 ``depends_on`` \u56fe\u4e0a\u67e5\u627e\u73af\u8def\uff08visited \u9632\u6b62\u65e0\u9650\u5faa\u73af\uff09\u3002"""
    adjacency: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    for item in graph.relations:
        if item.type != "depends_on":
            continue
        adjacency.setdefault(item.source.key, []).append(item.target.key)
    cycles: List[List[str]] = []
    state: Dict[Tuple[str, str], int] = {}
    stack: List[Tuple[str, str]] = []

    def _visit(node: Tuple[str, str]) -> None:
        state[node] = 1
        stack.append(node)
        for neighbour in adjacency.get(node, []):
            if state.get(neighbour, 0) == 1:
                index = stack.index(neighbour)
                cycles.append([" ".join(item) for item in stack[index:] + [neighbour]])
            elif state.get(neighbour, 0) == 0:
                _visit(neighbour)
        stack.pop()
        state[node] = 2

    for node in list(adjacency):
        if state.get(node, 0) == 0:
            _visit(node)
    return cycles


def save_relations(
    path: Union[str, Path],
    graph: RelationGraph,
    *,
    writable: bool = True,
) -> Path:
    """\u539f\u5b50\u5199\u5165\u5173\u7cfb\u6587\u4ef6\uff1b\u53ea\u8bfb\u9879\u76ee\u62d2\u7edd\u5199\u5165\u3002"""
    if not writable:
        raise PermissionError("\u53ea\u8bfb\u9879\u76ee\u4e0d\u53ef\u4fee\u6539\u5173\u7cfb\u3002")
    target = Path(path)
    payload = {
        "schemaVersion": RELATIONS_SCHEMA_VERSION,
        "relations": [item.to_dict() for item in graph.relations],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".yml.tmp")
    tmp.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        os.replace(str(tmp), str(target))
    except OSError:
        shutil.move(str(tmp), str(target))
    return target


def add_relation(
    graph: RelationGraph,
    *,
    relation_type: str,
    source: Endpoint,
    target: Endpoint,
    note: str = "",
) -> Tuple[Optional[Relation], Optional[str]]:
    """\u65b0\u589e\u5173\u7cfb\uff08\u5e42\u7b49\uff1a\u540c\u7c7b\u578b\u540c\u7aef\u70b9\u5df2\u5b58\u5728\u65f6\u8fd4\u56de\u539f\u6709\u8fb9\uff09\u3002"""
    type_key = str(relation_type or "").strip()
    if type_key not in RELATION_TYPES:
        return None, "\u672a\u77e5\u5173\u7cfb\u7c7b\u578b\uff1a{0}\u3002".format(relation_type or "(\u7a7a)")
    if source.key == target.key:
        return None, "\u4e0d\u5141\u8bb8\u521b\u5efa\u81ea\u73af\u5173\u7cfb\u3002"
    for item in graph.relations:
        if item.type == type_key and item.source.key == source.key and item.target.key == target.key:
            return item, "\u8be5\u5173\u7cfb\u5df2\u5b58\u5728\uff0c\u672a\u91cd\u590d\u6dfb\u52a0\u3002"
    relation = Relation(
        relation_id=str(uuid.uuid4()),
        type=type_key,
        source=source,
        target=target,
        note=str(note or ""),
    )
    graph.relations.append(relation)
    return relation, None


def remove_relation(graph: RelationGraph, relation_id: str) -> bool:
    """\u5220\u9664\u5173\u7cfb\uff1b\u8fd4\u56de\u662f\u5426\u5220\u9664\u3002"""
    before = len(graph.relations)
    graph.relations = [item for item in graph.relations if item.relation_id != relation_id]
    return len(graph.relations) != before


def migrate_legacy_graph(
    legacy: Dict[Tuple[str, str], Sequence[Tuple[str, str]]],
    *,
    pairs: Optional[Sequence[Tuple[str, str, str]]] = None,
) -> RelationGraph:
    """\u628a\u65e7\u7684\u201c\u7f16\u53f7\u5bf9\u5e94\u201d\u8f6c\u6210\u663e\u5f0f\u5173\u7cfb\uff08**\u4e0d\u63a8\u65ad**\uff1a\u53ea\u63a5\u53d7\u660e\u786e\u4f20\u5165\u7684\u5bf9\uff09\u3002

    ``pairs`` \u4e3a ``[(type, "\u6e90projectId/itemId", "\u76ee\u6807projectId/itemId"), ...]``\uff0c\u7531\u4eba\u5de5\u786e\u8ba4\u540e\u4f20\u5165\u3002
    """
    graph = RelationGraph()
    for relation_type, source_text, target_text in pairs or []:
        source = _endpoint_from_text(source_text)
        target = _endpoint_from_text(target_text)
        if source is None or target is None:
            graph.issues.append(RelationIssue("", "\u8fc1\u79fb\u5bf9\u65e0\u6548\uff1a{0} \u2192 {1}".format(source_text, target_text), "error"))
            continue
        _relation, error = add_relation(
            graph, relation_type=relation_type, source=source, target=target
        )
        if error and "\u5df2\u5b58\u5728" not in error:
            graph.issues.append(RelationIssue("", error, "error"))
    if not pairs:
        graph.issues.append(RelationIssue("", "\u672a\u63d0\u4f9b\u4eba\u5de5\u786e\u8ba4\u7684\u5173\u7cfb\u5bf9\uff0c\u4e0d\u81ea\u52a8\u63a8\u65ad\u5173\u7cfb\u3002", "warning"))
    return graph


def relation_sources(graph: RelationGraph, relation_id: str) -> List[dict]:
    """\u8fd4\u56de\u5173\u7cfb\u4e24\u7aef\u7684\u4f4d\u7f6e\u63cf\u8ff0\uff08\u4f9b UI \u5b9a\u4f4d\uff09\u3002"""
    for item in graph.relations:
        if item.relation_id == relation_id:
            return [
                {"role": "from", **item.source.to_dict()},
                {"role": "to", **item.target.to_dict()},
            ]
    return []


def _endpoint_from_text(text: str) -> Optional[Endpoint]:
    raw = str(text or "").strip()
    if "/" not in raw:
        return None
    project_id, _, item_id = raw.partition("/")
    if not project_id or not item_id:
        return None
    return Endpoint(project_id.strip(), item_id.strip())