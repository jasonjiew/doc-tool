# -*- coding: utf-8 -*-
"""\u57fa\u7ebf\u67e5\u8be2\u3001\u6bd4\u8f83\u4e0e\u5b89\u5168\u6062\u590d\uff08V2.9 29-G / 7.1\uff5e7.4\uff09\u3002

\u56db\u4ef6\u4e8b\uff1a

1. **\u67e5\u8be2**\uff1a\u5217\u51fa/\u8be6\u60c5/\u4ea7\u7269\u6253\u5f00\u9879\uff1b\u65e7 Markdown-only \u8bb0\u5f55\u6807 ``legacy-partial``\u3002
2. **\u6bd4\u8f83**\uff1a\u6309\u6b63\u6587/\u8d44\u6e90/\u6a21\u677f\u89c4\u5219/\u5173\u7cfb/\u4ea7\u7269\u5206\u7c7b\u7ed9\u51fa\u5dee\u5f02\uff08\u65b0\u589e/\u79fb\u9664/\u53d8\u5316\uff09\u3002
3. **\u5bfc\u51fa**\uff1a\u628a\u57fa\u7ebf\u5185\u5df2\u767b\u8bb0\u6587\u4ef6\u6253\u6210 ZIP\uff1b**\u8d8a\u754c\u6216\u7f3a\u5931\u9879\u8df3\u8fc7\u5e76\u5217\u6e05\u5355**\uff0c\u4e0d\u8bfb\u53d6\u76ee\u6807\u4e4b\u5916\u3002
4. **\u6062\u590d**\uff1a\u6062\u590d\u5230**\u65b0\u76ee\u5f55**\uff1b\u76ee\u6807\u51b2\u7a81\u9ed8\u8ba4**\u6362\u540d**\uff1b\u53ef\u4fe1\u9879\u4e0d\u8db3\u65f6\u4ecd\u53ef\u90e8\u5206\u6062\u590d\uff1b
   **\u539f\u526f\u672c\u4e0e\u5386\u53f2\u53ea\u8bfb**\uff08\u672c\u6a21\u5757\u4ece\u4e0d\u4fee\u6539\u6e90\uff09\u3002
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from doc_tool.application.collection import (
    COLLECTIONS_DIR,
    BaselineFile,
    CollectionManifest,
    list_manifests,
    load_manifest,
    sha256_file,
    verify_manifest,
)

#: \u6bd4\u8f83\u5206\u7ec4\uff08\u7528\u6237\u53ef\u8bfb\uff09\u3002
COMPARE_GROUPS = ("content", "resource", "standard", "relations", "artifact")
#: \u5206\u7c7b -> \u6bd4\u8f83\u5206\u7ec4\u3002
_CATEGORY_GROUP = {
    "content": "content",
    "image": "resource",
    "table": "resource",
    "standard": "standard",
    "rules": "standard",
    "relations": "relations",
    "artifact": "artifact",
    "manifest": "content",
    "review": "content",
    "report": "content",
}


@dataclass
class BaselineSummary:
    """\u57fa\u7ebf\u5217\u8868\u9879\u3002"""

    version: str
    path: str
    complete: bool
    legacy_partial: bool
    created_at: str
    file_count: int

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "path": self.path,
            "complete": self.complete,
            "legacyPartial": self.legacy_partial,
            "createdAt": self.created_at,
            "fileCount": self.file_count,
        }


@dataclass
class BaselineDetail:
    """\u57fa\u7ebf\u8be6\u60c5\uff08\u542b\u53ef\u6253\u5f00\u4ea7\u7269\u4e0e\u6821\u9a8c\uff09\u3002"""

    summary: BaselineSummary
    categories: Dict[str, int] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            **self.summary.to_dict(),
            "categories": dict(self.categories),
            "artifacts": list(self.artifacts),
            "missing": list(self.missing),
            "problems": list(self.problems),
            "extra": list(self.extra),
            "warnings": list(self.warnings),
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u57fa\u7ebf\u8be6\u60c5",
            "",
            "- \u7248\u672c\uff1a{0}".format(self.summary.version),
            "- \u5b8c\u6574\u6027\uff1a{0}".format("\u5b8c\u6574" if self.summary.complete else "\u90e8\u5206"),
            "- \u6587\u4ef6\u6570\uff1a{0}".format(self.summary.file_count),
        ]
        if self.summary.legacy_partial:
            lines.append("- \u65e7\u683c\u5f0f\u8bb0\u5f55\uff1a**legacy-partial**\uff08\u4ec5\u53ef\u90e8\u5206\u6062\u590d\uff09")
        if self.problems:
            lines.append("")
            lines.append("**\u6821\u9a8c\u95ee\u9898\uff1a**")
            lines.extend("- {0}".format(item) for item in self.problems[:50])
        if self.artifacts:
            lines.append("")
            lines.append("**\u53ef\u6253\u5f00\u4ea7\u7269\uff1a**")
            lines.extend("- {0}".format(item) for item in self.artifacts[:50])
        return "\n".join(lines)


@dataclass
class CompareEntry:
    """\u4e00\u6761\u6bd4\u8f83\u5dee\u5f02\u3002"""

    group: str
    relative_path: str
    change: str
    left_hash: str = ""
    right_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "path": self.relative_path,
            "change": self.change,
            "leftHash": self.left_hash,
            "rightHash": self.right_hash,
        }


@dataclass
class CompareReport:
    """\u4e24\u4e2a\u96c6\u5408\u7684\u6bd4\u8f83\u7ed3\u679c\u3002"""

    left_version: str = ""
    right_version: str = ""
    entries: List[CompareEntry] = field(default_factory=list)

    def by_group(self) -> Dict[str, List[CompareEntry]]:
        result: Dict[str, List[CompareEntry]] = {group: [] for group in COMPARE_GROUPS}
        for entry in self.entries:
            result.setdefault(entry.group, []).append(entry)
        return result

    @property
    def changed(self) -> List[CompareEntry]:
        return [entry for entry in self.entries if entry.change != "unchanged"]

    def to_dict(self) -> dict:
        return {
            "leftVersion": self.left_version,
            "rightVersion": self.right_version,
            "counts": {
                group: len(items) for group, items in self.by_group().items()
            },
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u96c6\u5408\u6bd4\u8f83",
            "",
            "- \u5de6\uff1a{0}\uff1b\u53f3\uff1a{1}".format(self.left_version, self.right_version),
            "- \u5dee\u5f02\u9879\uff1a{0}".format(len(self.changed)),
        ]
        for group, items in self.by_group().items():
            if not items:
                continue
            lines.append("")
            lines.append("**{0}**".format(group))
            lines.append("")
            lines.append("| \u6587\u4ef6 | \u53d8\u5316 |")
            lines.append("|------|------|")
            for entry in items:
                lines.append("| {0} | {1} |".format(entry.relative_path, entry.change))
        return "\n".join(lines)


def list_baselines(root: Union[str, Path]) -> List[BaselineSummary]:
    """\u5217\u51fa\u57fa\u7ebf\uff08\u6309\u6e05\u5355\u540d\u6392\u5e8f\uff09\u3002"""
    summaries: List[BaselineSummary] = []
    for path in list_manifests(root):
        try:
            manifest = load_manifest(path)
        except ValueError:
            continue
        summaries.append(_summary(path, manifest))
    return summaries


def describe_baseline(path: Union[str, Path], *, root: Optional[Union[str, Path]] = None) -> BaselineDetail:
    """\u57fa\u7ebf\u8be6\u60c5\uff08\u542b\u6821\u9a8c\u4e0e\u53ef\u6253\u5f00\u4ea7\u7269\uff09\u3002"""
    manifest = load_manifest(path)
    summary = _summary(Path(path), manifest)
    detail = BaselineDetail(summary=summary, categories=manifest.categories)
    detail.artifacts = [item.relative_path for item in manifest.by_category("artifact")]
    detail.missing = list(manifest.missing)
    detail.warnings = list(manifest.warnings)
    if root is not None:
        problems, extra = verify_manifest(root, manifest)
        detail.problems = problems
        detail.extra = extra
    return detail


def compare_baselines(
    left: Union[str, Path],
    right: Union[str, Path],
) -> CompareReport:
    """\u6309\u5206\u7ec4\u6bd4\u8f83\u4e24\u4e2a\u96c6\u5408\u7684\u6e05\u5355\u3002"""
    left_manifest = load_manifest(left)
    right_manifest = load_manifest(right)
    report = CompareReport(left_version=left_manifest.version, right_version=right_manifest.version)
    left_map = _file_map(left_manifest)
    right_map = _file_map(right_manifest)
    for key in sorted(set(left_map) | set(right_map)):
        group = _group_for(key, left_map, right_map)
        if key not in left_map:
            report.entries.append(CompareEntry(group, key, "added", "", right_map[key].sha256))
        elif key not in right_map:
            report.entries.append(CompareEntry(group, key, "deleted", left_map[key].sha256, ""))
        elif left_map[key].sha256 != right_map[key].sha256:
            report.entries.append(
                CompareEntry(group, key, "modified", left_map[key].sha256, right_map[key].sha256)
            )
    return report


def export_package(
    root: Union[str, Path],
    manifest_path: Union[str, Path],
    destination: Union[str, Path],
) -> Tuple[Optional[Path], List[str]]:
    """\u628a\u57fa\u7ebf\u5185\u5df2\u767b\u8bb0\u6587\u4ef6\u5bfc\u51fa\u4e3a ZIP\uff1b\u8fd4\u56de ``(zip, \u8df3\u8fc7\u6e05\u5355)``\u3002

    \u8d8a\u754c\u3001\u7f3a\u5931\u6216 hash \u4e0d\u4e00\u81f4\u7684\u9879**\u8df3\u8fc7\u5e76\u8bb0\u5f55**\uff1b\u4e0d\u8bfb\u53d6\u57fa\u7ebf\u76ee\u5f55\u4e4b\u5916\u7684\u4efb\u4f55\u8def\u5f84\u3002
    """
    base = Path(root).resolve()
    manifest = load_manifest(manifest_path)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    skipped: List[str] = []
    written: List[str] = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
        for item in manifest.files:
            source = _resolve_inside(base, item.relative_path)
            if source is None:
                skipped.append("\u8d8a\u754c\uff1a{0}".format(item.relative_path))
                continue
            if not source.is_file():
                skipped.append("\u7f3a\u5931\uff1a{0}".format(item.relative_path))
                continue
            if item.sha256 and sha256_file(source) != item.sha256:
                skipped.append("\u5185\u5bb9\u5df2\u53d8\uff1a{0}".format(item.relative_path))
                continue
            package.write(source, item.relative_path)
            written.append(item.relative_path)
        package.writestr(
            "baseline-manifest.json",
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        )
    if not written:
        try:
            target.unlink()
        except OSError:
            pass
        return None, skipped or ["\u6ca1\u6709\u53ef\u5bfc\u51fa\u7684\u5185\u5bb9"]
    return target, skipped


def recover_baseline(
    root: Union[str, Path],
    manifest_path: Union[str, Path],
    destination: Union[str, Path],
    *,
    overwrite: bool = False,
) -> dict:
    """\u6062\u590d\u5230**\u65b0\u76ee\u5f55**\uff1b\u76ee\u6807\u51b2\u7a81\u9ed8\u8ba4\u6362\u540d\uff0c\u539f\u526f\u672c\u4e0e\u5386\u53f2\u53ea\u8bfb\u3002

    - \u53ef\u4fe1\u9879\uff08hash \u5339\u914d\uff09\u624d\u5199\u5165\uff1b\u4e0d\u53ef\u4fe1\u9879**\u8df3\u8fc7\u5e76\u5217\u6e05\u5355**\uff1b
    - ``legacy-partial``\u3001\u7f3a\u9879\u3001\u635f\u574f\u90fd\u4e0d\u963b\u65ad\u5176\u4f59\u9879\u6062\u590d\uff1b
    - **\u53ea\u5728\u672c\u6b21\u65b0\u76ee\u5f55\u5185\u64cd\u4f5c**\uff1b\u5931\u8d25\u4e0d\u52a8\u539f\u526f\u672c\u3002
    """
    base = Path(root).resolve()
    manifest = load_manifest(manifest_path)
    target_root = Path(destination)
    result = {
        "restored": [],
        "skipped": [],
        "renamed": [],
        "destination": str(target_root),
        "legacyPartial": manifest.legacy_partial,
        "complete": manifest.complete,
    }
    if not manifest.files:
        result["skipped"].append("\u6e05\u5355\u4e2d\u6ca1\u6709\u53ef\u6062\u590d\u7684\u6587\u4ef6\u8bb0\u5f55\u3002")
        return result
    target_root.mkdir(parents=True, exist_ok=True)
    for item in manifest.files:
        source = _resolve_inside(base, item.relative_path)
        if source is None or not source.is_file():
            result["skipped"].append("\u7f3a\u5931\u6216\u8d8a\u754c\uff1a{0}".format(item.relative_path))
            continue
        if item.sha256 and sha256_file(source) != item.sha256:
            result["skipped"].append("\u4e0d\u53ef\u4fe1\uff08hash \u4e0d\u5339\u914d\uff09\uff1a{0}".format(item.relative_path))
            continue
        target = _resolve_inside(target_root, item.relative_path)
        if target is None:
            result["skipped"].append("\u76ee\u6807\u8def\u5f84\u8d8a\u754c\uff1a{0}".format(item.relative_path))
            continue
        if target.exists() and not overwrite:
            renamed = _unique_name(target)
            result["renamed"].append(
                "{0} \u2192 {1}".format(item.relative_path, renamed.relative_to(target_root).as_posix())
            )
            target = renamed
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError as exc:
            result["skipped"].append("\u5199\u5165\u5931\u8d25\uff1a{0}\uff08{1}\uff09".format(item.relative_path, exc))
            continue
        result["restored"].append(item.relative_path)
    if result["restored"]:
        _write_identity_map(manifest, target_root, result)
    return result


def _write_identity_map(manifest: CollectionManifest, target_root: Path, result: dict) -> None:
    """\u6062\u590d\u540e\u5199\u5165\u8eab\u4efd\u6620\u5c04\u8bf4\u660e\uff08\u5173\u7cfb/\u8bc4\u5ba1\u53ef\u636e\u6b64\u91cd\u5b9a\u5411\uff09\u3002"""
    mapping = {
        "collectionId": manifest.collection_id,
        "version": manifest.version,
        "members": [item.to_dict() for item in manifest.members],
        "note": "itemId \u4fdd\u7559\uff1bprojectId \u4ee5\u5404\u6210\u5458\u9879\u76ee\u5185\u7684 project.yml \u4e3a\u51c6\u3002",
        "renamed": list(result.get("renamed", [])),
        "skipped": list(result.get("skipped", [])),
    }
    target = target_root / "identity-map.json"
    try:
        target.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def open_artifact(root: Union[str, Path], manifest_path: Union[str, Path], relative_path: str) -> Optional[Path]:
    """\u8fd4\u56de\u53ef\u76f4\u63a5\u6253\u5f00\u7684\u4ea7\u7269\u8def\u5f84\uff08\u4ec5\u9650\u57fa\u7ebf\u767b\u8bb0\u4e14\u5b58\u5728\uff09\u3002"""
    base = Path(root).resolve()
    manifest = load_manifest(manifest_path)
    wanted = str(relative_path or "").replace("\\", "/")
    for item in manifest.files:
        if item.relative_path != wanted:
            continue
        target = _resolve_inside(base, item.relative_path)
        return target if target is not None and target.is_file() else None
    return None


def _summary(path: Path, manifest: CollectionManifest) -> BaselineSummary:
    return BaselineSummary(
        version=manifest.version,
        path=str(path),
        complete=manifest.complete,
        legacy_partial=manifest.legacy_partial,
        created_at=manifest.created_at,
        file_count=len(manifest.files),
    )


def _file_map(manifest: CollectionManifest) -> Dict[str, BaselineFile]:
    return {item.relative_path: item for item in manifest.files}


def _group_for(key: str, left: Dict[str, BaselineFile], right: Dict[str, BaselineFile]) -> str:
    item = left.get(key) or right.get(key)
    category = item.category if item is not None else "content"
    return _CATEGORY_GROUP.get(category, "content")


def _resolve_inside(base: Path, relative: str) -> Optional[Path]:
    text = str(relative or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ".." in text.split("/"):
        return None
    candidate = (base / text).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def _unique_name(target: Path) -> Path:
    for index in range(1, 1000):
        candidate = target.with_name("{0}.{1}{2}".format(target.stem, index, target.suffix))
        if not candidate.exists():
            return candidate
    return target.with_name("{0}.new{1}".format(target.stem, target.suffix))