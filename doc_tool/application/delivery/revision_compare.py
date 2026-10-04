# -*- coding: utf-8 -*-
"""V4.3 43-C：两个真实版本的比较与可编辑修订说明。

复用既有集合服务（``collection_ops``）做事实比较，本模块只负责：

- **版本选择**：列出真实基线/快照（id、名称、时间、来源路径、完整性），同名集合按
  路径/身份区分，历史缺项标「不可比较」而不是「无变化」；
- **两版比较**：正文/资源/条目与关系/成果分组差异（来自原 ``compare_baselines``），
  并单独给出**来源章节文件**与**装配后内容**两套指纹差异；
- **修订说明**：从实际差异预填、可编辑；编辑**不改变**评审或正式状态。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: 不可比较原因的稳定文案。
NOT_COMPARABLE_MISSING = "缺少该版本的历史数据，无法比较"
NOT_COMPARABLE_LEGACY = "该版本为旧版部分基线，缺少完整文件清单"


@dataclass
class VersionOption:
    """一个可选的真实版本。"""

    version: str = ""
    path: str = ""
    name: str = ""
    createdAt: str = ""
    fileCount: int = 0
    complete: bool = True
    legacyPartial: bool = False
    source: str = ""

    @property
    def identity(self) -> str:
        """真实身份：路径 + 版本（同名不同路径不合并）。"""
        return "{0}#{1}".format(self.path, self.version)

    @property
    def comparable(self) -> bool:
        return not self.legacyPartial and bool(self.path) and Path(self.path).is_file()

    @property
    def notComparableReason(self) -> str:
        if self.legacyPartial:
            return NOT_COMPARABLE_LEGACY
        if not self.comparable:
            return NOT_COMPARABLE_MISSING
        return ""

    def label(self) -> str:
        tail = "" if self.comparable else "（不可比较：{0}）".format(self.notComparableReason)
        return "{0}｜{1}｜{2}｜{3} 个文件{4}".format(
            self.name or self.version, self.createdAt or "时间未知",
            self.version or "版本未知", self.fileCount, tail,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "version": self.version, "path": self.path, "name": self.name,
            "createdAt": self.createdAt, "fileCount": self.fileCount,
            "complete": self.complete, "legacyPartial": self.legacyPartial,
            "source": self.source, "identity": self.identity,
            "comparable": self.comparable,
            "notComparableReason": self.notComparableReason,
        }


def list_versions(root, *, name_of=None) -> List[VersionOption]:
    """列出根目录下的真实基线（按时间倒序）。名称可显式传入，避免按名字猜版本。"""
    from doc_tool.application.collection_ops import list_baselines

    options: List[VersionOption] = []
    for summary in list_baselines(root):
        path = str(getattr(summary, "path", "") or "")
        version = str(getattr(summary, "version", "") or "")
        name = ""
        if callable(name_of):
            name = str(name_of(summary) or "")
        if not name:
            name = Path(path).parent.name or version
        options.append(VersionOption(
            version=version, path=path, name=name,
            createdAt=str(getattr(summary, "created_at", "") or ""),
            fileCount=int(getattr(summary, "file_count", 0) or 0),
            complete=bool(getattr(summary, "complete", True)),
            legacyPartial=bool(getattr(summary, "legacy_partial", False)),
            source=str(root),
        ))
    options.sort(key=lambda item: item.createdAt, reverse=True)
    return options


def find_version(options: Sequence[VersionOption], identity: str) -> Optional[VersionOption]:
    """按真实身份（路径#版本）选择版本；不接受按显示名选择。"""
    wanted = str(identity or "")
    for item in options:
        if item.identity == wanted:
            return item
    return None


@dataclass
class VersionComparison:
    """两个真实版本的比较事实。"""

    known: bool = False
    reason: str = ""
    left: Optional[VersionOption] = None
    right: Optional[VersionOption] = None
    groups: Dict[str, List[dict]] = field(default_factory=dict)
    sourceChanges: List[Tuple[str, str]] = field(default_factory=list)
    assembledChanges: List[Tuple[str, str]] = field(default_factory=list)
    onlyInSource: List[str] = field(default_factory=list)
    onlyInAssembled: List[str] = field(default_factory=list)
    unavailableGroups: List[str] = field(default_factory=list)

    @property
    def changeCount(self) -> int:
        return sum(len(items) for items in self.groups.values())

    def summary_lines(self) -> List[str]:
        if not self.known:
            return ["版本比较：不可比较（{0}）".format(self.reason or "缺少历史数据")]
        lines = ["两版比较：{0} → {1}｜共 {2} 处变化".format(
            (self.left.version if self.left else "?"),
            (self.right.version if self.right else "?"),
            self.changeCount,
        )]
        for group, items in sorted(self.groups.items()):
            if items:
                lines.append("· {0}：{1} 处".format(group, len(items)))
        if self.sourceChanges:
            lines.append("来源章节文件变化：{0} 处".format(len(self.sourceChanges)))
        if self.assembledChanges:
            lines.append("装配后内容变化：{0} 处".format(len(self.assembledChanges)))
        if self.onlyInSource:
            lines.append("仅来源配置变化（章节文件未改）：{0}".format(
                "、".join(self.onlyInSource[:5])
            ))
        if self.onlyInAssembled:
            lines.append("仅装配内容变化：{0}".format("、".join(self.onlyInAssembled[:5])))
        for group in self.unavailableGroups:
            lines.append("· {0}：不可比较（缺少该部分历史数据）".format(group))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "known": self.known, "reason": self.reason,
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None,
            "groups": {key: list(value) for key, value in self.groups.items()},
            "changeCount": self.changeCount,
            "sourceChanges": [list(item) for item in self.sourceChanges],
            "assembledChanges": [list(item) for item in self.assembledChanges],
            "onlyInSource": list(self.onlyInSource),
            "onlyInAssembled": list(self.onlyInAssembled),
            "unavailableGroups": list(self.unavailableGroups),
        }


def _categorized(manifest_path: str) -> Dict[str, Dict[str, str]]:
    """从真实基线清单读回 ``分类 -> {相对路径: sha256}``。

    分类是**清单里的真实字段**（``categorize`` 的结果）：``standard``/``rules``
    归属来源配置，``content``/``resource``/``table`` 归属装配后的正文内容。缺清单
    或坏清单返回空字典，由调用方标「不可比较」而不是当作无变化。
    """
    target = Path(manifest_path)
    if not target.is_file():
        return {}
    try:
        # 基线清单是**YAML**（社区集合清单格式），不是 JSON。
        import yaml

        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 坏清单返回空，由调用方标不可比较
        return {}
    if not isinstance(payload, dict):
        return {}
    files = payload.get("files")
    if not isinstance(files, list):
        return {}
    result: Dict[str, Dict[str, str]] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        # 基线清单序列化用的键是 ``path``（历史写作 ``relativePath``）。
        rel = str(item.get("path") or item.get("relativePath") or "")
        if not rel:
            continue
        category = str(item.get("category") or "content")
        result.setdefault(category, {})[rel] = str(item.get("sha256") or "")
    return result


#: 来源配置类分类（与装配后的正文区分）。
SOURCE_CATEGORIES = ("standard", "rules", "manifest")


def _compare_category(left: Dict[str, str], right: Dict[str, str]) -> List[Tuple[str, str]]:
    changes: List[Tuple[str, str]] = []
    for rel in sorted(set(left) | set(right)):
        if rel not in left or rel not in right:
            changes.append((rel, "added" if rel in right else "removed"))
            continue
        if left[rel] != right[rel]:
            changes.append((rel, "modified"))
    return changes


def compare_versions(
    left_identity: str,
    right_identity: str,
    *,
    options: Sequence[VersionOption],
    baseline_root="",
) -> VersionComparison:
    """比较两个真实版本；缺历史数据只影响对应部分。"""
    left = find_version(options, left_identity)
    right = find_version(options, right_identity)
    comparison = VersionComparison(left=left, right=right)
    if left is None or right is None:
        comparison.reason = "所选版本不存在（必须按真实身份选择）"
        return comparison
    if not left.comparable or not right.comparable:
        comparison.reason = left.notComparableReason or right.notComparableReason
        return comparison
    if left.path == right.path:
        comparison.reason = "两侧选择了同一个版本，请选择不同版本"
        return comparison

    from doc_tool.application.collection_ops import COMPARE_GROUPS, compare_baselines

    report = compare_baselines(left.path, right.path)
    groups: Dict[str, List[dict]] = dict((group, []) for group in COMPARE_GROUPS)
    for entry in report.entries:
        groups.setdefault(entry.group, []).append({
            "relativePath": entry.relative_path, "change": entry.change,
            "leftHash": entry.left_hash, "rightHash": entry.right_hash,
        })
    comparison.groups = groups

    left_categories = _categorized(left.path)
    right_categories = _categorized(right.path)
    if not left_categories or not right_categories:
        comparison.unavailableGroups.append("文件清单")
    else:
        for category in SOURCE_CATEGORIES:
            changes = _compare_category(
                left_categories.get(category, {}), right_categories.get(category, {}),
            )
            comparison.sourceChanges.extend(changes)
        for category, items in sorted(left_categories.items()):
            if category in SOURCE_CATEGORIES:
                continue
            changes = _compare_category(items, right_categories.get(category, {}))
            comparison.assembledChanges.extend(changes)
        for category in sorted(set(right_categories) - set(left_categories)):
            if category in SOURCE_CATEGORIES:
                continue
            comparison.assembledChanges.extend(
                _compare_category({}, right_categories[category])
            )
        # 区分「来源配置变化」与「装配内容变化」
        source_changed = {rel for rel, _ in comparison.sourceChanges}
        assembled_changed = {rel for rel, _ in comparison.assembledChanges}
        comparison.onlyInSource = sorted(source_changed - assembled_changed)
        comparison.onlyInAssembled = sorted(assembled_changed - source_changed)
        for group in report_groups_without_data(comparison, left_categories, right_categories):
            comparison.unavailableGroups.append(group)
    comparison.known = True
    return comparison


def report_groups_without_data(comparison: VersionComparison, left_categories, right_categories) -> List[str]:
    """真实存在的分组里两侧都没有清单数据的部分（标注为不可比较）。"""
    missing: List[str] = []
    for group in ("content", "resource", "standard", "relations", "artifact"):
        if group not in left_categories and group not in right_categories:
            missing.append(group)
    return missing


def prefill_revision_note(comparison: VersionComparison, *, editable: bool = True) -> str:
    """从实际差异预填修订说明（纯文本，可编辑；不改任何评审/正式状态）。"""
    if not comparison.known:
        return "本次无法比较：{0}".format(comparison.reason or "缺少历史数据")
    lines = ["## 修订说明（自动预填，可编辑）", ""]
    lines.append("- 比较版本：{0} → {1}".format(
        (comparison.left.version if comparison.left else "?"),
        (comparison.right.version if comparison.right else "?"),
    ))
    for group, items in sorted(comparison.groups.items()):
        if not items:
            continue
        lines.append("- {0}：{1} 处变化".format(group, len(items)))
        for item in items[:10]:
            lines.append("  - {0}（{1}）".format(item.get("relativePath"), item.get("change")))
    if comparison.onlyInSource:
        lines.append("- 来源配置变化但章节文件未改：{0}".format("、".join(comparison.onlyInSource[:5])))
    if comparison.sourceChanges:
        lines.append("- 来源章节文件变化：{0} 处".format(len(comparison.sourceChanges)))
    if comparison.onlyInAssembled:
        lines.append("- 仅装配内容变化：{0}".format("、".join(comparison.onlyInAssembled[:5])))
    for group in comparison.unavailableGroups:
        lines.append("- 不可比较（缺少历史数据）：{0}".format(group))
    if editable:
        lines.append("")
        lines.append("（可直接修改上面的文字；保存不会改变条目复核或成果正式状态）")
    return "\n".join(lines)


@dataclass
class RevisionNote:
    """可编辑修订说明（只保存文字，不触发任何状态变更）。"""

    text: str = ""
    prefilled: str = ""
    edited: bool = False

    def update(self, text: str) -> None:
        self.text = str(text)
        self.edited = self.text != self.prefilled

    def to_dict(self) -> Dict[str, object]:
        return {"text": self.text, "prefilled": self.prefilled, "edited": self.edited}


def build_revision_note(comparison: VersionComparison, *, text: str = "") -> RevisionNote:
    prefilled = prefill_revision_note(comparison)
    note = RevisionNote(text=text or prefilled, prefilled=prefilled)
    note.edited = note.text != prefilled
    return note


__all__ = [
    "NOT_COMPARABLE_MISSING", "NOT_COMPARABLE_LEGACY",
    "VersionOption", "VersionComparison", "RevisionNote",
    "list_versions", "find_version", "compare_versions",
    "prefill_revision_note", "build_revision_note",
]
