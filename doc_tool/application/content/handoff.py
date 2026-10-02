# -*- coding: utf-8 -*-
"""V3.1 31-C: offline content handoff package, diff plan, partial apply, idempotency.

Design boundaries (openspec/changes/product-v31-team-workflow/design.md D3 and
``specs/team-handoff-workflow/spec.md``):

- A package is a **self-contained ZIP** (chapter bodies + baseline hashes +
  referenced resources + the module/source index) plus a schema-1 manifest
  JSON. Exporting is a plain file write; nothing is ever pushed or sent.
- Applying is a **selected** operation aware of base / local / incoming: only
  selected entries without a local conflict are written. A conflicting chapter
  keeps the local file and the remaining legal entries still apply.
- Deletions are never selected by default and stay a soft delete when applied.
- Resources are disambiguated by content sha256: a same-named resource with
  different bytes is **never** substituted in place; it is written as a
  hash-suffixed sibling and reported.
- Repeated imports are idempotent per package + entry + incoming hash. An entry
  the receiver modified afterwards is re-compared and skipped, never restored.
- A package from another project can be imported as a **new copy**; the
  original project is left untouched.
- A missing/unknown baseline is stated explicitly instead of pretending the
  content is conflict-free, and a write failure rolls back this run's writes.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from doc_tool.application.content.changes import render_unified_diff
from doc_tool.application.content.writer import atomic_write, atomic_write_bytes

HANDOFF_SCHEMA = "doc-tool-handoff/v1"
HANDOFF_SCHEMA_VERSION = 1
MANIFEST_NAME = "handoff-manifest.json"
CONTENT_DIR = "content"
RESOURCE_DIR = "resources"
APPLIED_FILE_NAME = "handoff_applied.json"
DEFAULT_PACKAGE_NAME = "\u5185\u5bb9\u4ea4\u63a5\u5305.zip"

KIND_CHAPTER = "chapter"
KIND_RESOURCE = "resource"

BASELINE_KNOWN = "known"
BASELINE_UNKNOWN = "unknown"

STATUS_NEW = "new"
STATUS_UNCHANGED = "unchanged"
STATUS_MODIFIED = "modified"
STATUS_CONFLICT = "conflict"
STATUS_DELETED = "deleted"
STATUS_ALREADY_APPLIED = "already-applied"
STATUS_RESOURCE_MISMATCH = "resource-conflict"
STATUS_FOREIGN = "foreign-project"
STATUS_RESOURCE_MISSING = "resource-missing"

REASON_CONFLICT = "\u672c\u5730\u5185\u5bb9\u4e0e\u57fa\u51c6\u4e0d\u540c\uff0c\u5df2\u4fdd\u7559\u672c\u5730\u5e76\u5217\u4e3a\u5f85\u5904\u7406\u3002"
REASON_DESELECTED = "\u63a5\u6536\u65b9\u672a\u9009\u62e9\u8be5\u9879\u3002"
REASON_UNCHANGED = "\u672c\u5730\u5df2\u4e0e\u4ea4\u63a5\u5185\u5bb9\u4e00\u81f4\uff0c\u65e0\u9700\u5199\u5165\u3002"
REASON_ALREADY_APPLIED = "\u540c\u4e00\u4ea4\u63a5\u5305\u8be5\u9879\u5df2\u5e94\u7528\u4e14\u672c\u5730\u672a\u518d\u4fee\u6539\uff0c\u8df3\u8fc7\u91cd\u590d\u5199\u5165\u3002"
REASON_LOCAL_CHANGED = "\u8be5\u9879\u5e94\u7528\u540e\u672c\u5730\u53c8\u4fee\u6539\u8fc7\uff0c\u91cd\u65b0\u6bd4\u8f83\u800c\u4e0d\u8986\u76d6\u3002"
REASON_RESOURCE_MISMATCH = "\u540c\u540d\u8d44\u6e90\u5185\u5bb9\u4e0d\u540c\uff0c\u672a\u76f4\u63a5\u66ff\u4ee3\uff0c\u5df2\u53e6\u5b58\u526f\u672c\u3002"
REASON_RESOURCE_MISSING = "\u5305\u5185\u8d44\u6e90\u5185\u5bb9\u4e0d\u53ef\u83b7\u53d6\uff0c\u672c\u9879\u8df3\u8fc7\u3002"
REASON_BASELINE_UNKNOWN = "\u5305\u5185\u7f3a\u5c11\u5df2\u77e5\u57fa\u51c6\uff0c\u65e0\u6cd5\u8bc1\u660e\u65e0\u51b2\u7a81\uff0c\u9700\u4eba\u5de5\u786e\u8ba4\u3002"
REASON_FOREIGN = "\u5305\u6765\u81ea\u5176\u4ed6\u9879\u76ee\uff0c\u9700\u5bfc\u5165\u4e3a\u9879\u76ee\u526f\u672c\u3002"

FOREIGN_PROJECT_NOTICE = "\u4ea4\u63a5\u5305\u6765\u81ea\u5176\u4ed6\u9879\u76ee\uff08{0}\uff09\uff0c\u5df2\u6309\u65b0\u526f\u672c\u5bfc\u5165\uff0c\u539f\u9879\u76ee\u672a\u4fee\u6539\u3002"
UNKNOWN_BASELINE_NOTICE = "\u5305\u5185 {0} \u9879\u7f3a\u5c11\u5df2\u77e5\u57fa\u51c6\uff1a\u65e0\u6cd5\u8bc1\u660e\u4e0e\u672c\u5730\u65e0\u51b2\u7a81\uff0c\u8bf7\u4eba\u5de5\u786e\u8ba4\u540e\u518d\u5e94\u7528\u3002"
NO_BASELINE_NOTICE = "\u6ca1\u6709\u53ef\u7528\u57fa\u51c6\uff0c\u5df2\u6309\u65b0\u5185\u5bb9\u4ea4\u63a5\uff1b\u672a\u5ba3\u79f0\u65e0\u51b2\u7a81\u3002"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(str(text).encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 128), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(rel_path) -> str:
    raw = str(rel_path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return ""
    return candidate.as_posix().lstrip("./")


def _resolve_inside(root: Path, rel: str) -> Optional[Path]:
    if not rel:
        return None
    candidate = (Path(root) / rel).resolve()
    try:
        candidate.relative_to(Path(root).resolve())
    except ValueError:
        return None
    return candidate

@dataclass(frozen=True)
class HandoffEntry:
    """One package entry: a chapter body or a referenced resource."""

    entry_id: str
    kind: str
    rel_path: str
    name: str = ""
    title: str = ""
    base_hash: str = ""
    hash: str = ""
    size: int = 0
    archive_name: str = ""
    changed: bool = False
    module_of: str = ""

    def to_dict(self) -> dict:
        return {
            "entryId": self.entry_id,
            "kind": self.kind,
            "relPath": self.rel_path,
            "name": self.name,
            "title": self.title,
            "baseHash": self.base_hash,
            "hash": self.hash,
            "size": self.size,
            "archiveName": self.archive_name,
            "changed": self.changed,
            "moduleOf": self.module_of,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HandoffEntry":
        try:
            size = int(data.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        return cls(
            entry_id=str(data.get("entryId", "") or ""),
            kind=str(data.get("kind", KIND_CHAPTER) or KIND_CHAPTER),
            rel_path=_norm(data.get("relPath", "")),
            name=str(data.get("name", "") or ""),
            title=str(data.get("title", "") or ""),
            base_hash=str(data.get("baseHash", "") or ""),
            hash=str(data.get("hash", "") or ""),
            size=size,
            archive_name=str(data.get("archiveName", "") or ""),
            changed=bool(data.get("changed", False)),
            module_of=str(data.get("moduleOf", "") or ""),
        )


@dataclass
class HandoffPackage:
    """Package manifest (schema 1) plus the resolved package path."""

    package_path: str = ""
    package_id: str = ""
    schema: str = HANDOFF_SCHEMA
    schema_version: int = HANDOFF_SCHEMA_VERSION
    project_id: str = ""
    project_name: str = ""
    document_version: str = ""
    created_at: str = ""
    created_by: str = ""
    baseline_id: str = ""
    baseline_state: str = BASELINE_KNOWN
    chapters: List[HandoffEntry] = field(default_factory=list)
    resources: List[HandoffEntry] = field(default_factory=list)
    modules: List[dict] = field(default_factory=list)
    referenced_comments: List[str] = field(default_factory=list)
    source_index: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def entries(self) -> List[HandoffEntry]:
        return [*self.chapters, *self.resources]

    def entry(self, entry_id: str) -> Optional[HandoffEntry]:
        for item in self.entries:
            if item.entry_id == entry_id:
                return item
        return None

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "schemaVersion": self.schema_version,
            "packageId": self.package_id,
            "projectId": self.project_id,
            "projectName": self.project_name,
            "documentVersion": self.document_version,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "baselineId": self.baseline_id,
            "baselineState": self.baseline_state,
            "chapters": [item.to_dict() for item in self.chapters],
            "resources": [item.to_dict() for item in self.resources],
            "modules": list(self.modules),
            "referencedComments": list(self.referenced_comments),
            "sourceIndex": list(self.source_index),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict, *, package_path: str = "") -> "HandoffPackage":
        package = cls(package_path=package_path)
        package.schema = str(data.get("schema", "") or "")
        try:
            package.schema_version = int(data.get("schemaVersion", 0) or 0)
        except (TypeError, ValueError):
            package.schema_version = 0
        package.package_id = str(data.get("packageId", "") or "")
        package.project_id = str(data.get("projectId", "") or "")
        package.project_name = str(data.get("projectName", "") or "")
        package.document_version = str(data.get("documentVersion", "") or "")
        package.created_at = str(data.get("createdAt", "") or "")
        package.created_by = str(data.get("createdBy", "") or "")
        package.baseline_id = str(data.get("baselineId", "") or "")
        package.baseline_state = str(data.get("baselineState", BASELINE_KNOWN) or BASELINE_KNOWN)
        package.chapters = [HandoffEntry.from_dict(item)
                            for item in (data.get("chapters") or []) if isinstance(item, dict)]
        package.resources = [HandoffEntry.from_dict(item)
                             for item in (data.get("resources") or []) if isinstance(item, dict)]
        package.modules = [item for item in (data.get("modules") or []) if isinstance(item, dict)]
        package.referenced_comments = [str(item) for item in (data.get("referencedComments") or [])]
        package.source_index = [item for item in (data.get("sourceIndex") or [])
                                if isinstance(item, dict)]
        package.warnings = [str(item) for item in (data.get("warnings") or [])]
        return package


@dataclass
class HandoffPlanItem:
    """One row of the receiver-side apply plan."""

    entry_id: str
    kind: str
    rel_path: str
    title: str = ""
    status: str = ""
    selected: bool = False
    conflict: bool = False
    applicable: bool = False
    base_hash: str = ""
    local_hash: str = ""
    incoming_hash: str = ""
    reason: str = ""
    diff_text: str = ""

    def to_dict(self) -> dict:
        return {
            "entryId": self.entry_id,
            "kind": self.kind,
            "relPath": self.rel_path,
            "title": self.title,
            "status": self.status,
            "selected": self.selected,
            "conflict": self.conflict,
            "applicable": self.applicable,
            "baseHash": self.base_hash,
            "localHash": self.local_hash,
            "incomingHash": self.incoming_hash,
            "reason": self.reason,
            "diffText": self.diff_text,
        }


@dataclass
class HandoffApplyPlan:
    """Receiver-side plan: diff preview plus which selected items will apply."""

    package: HandoffPackage
    target_root: str = ""
    same_project: bool = True
    baseline_known: bool = True
    items: List[HandoffPlanItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    module_missing: List[str] = field(default_factory=list)
    module_conflicts: List[str] = field(default_factory=list)

    @property
    def applicable(self) -> List[HandoffPlanItem]:
        return [item for item in self.items if item.applicable]

    @property
    def conflicts(self) -> List[HandoffPlanItem]:
        return [item for item in self.items if item.conflict]

    @property
    def skipped(self) -> List[HandoffPlanItem]:
        return [item for item in self.items
                if not item.applicable and item.status != STATUS_UNCHANGED]

    def choices(self) -> Dict[str, bool]:
        return {item.entry_id: item.applicable for item in self.items}

    def counts(self) -> Dict[str, int]:
        result: Dict[str, int] = {"total": len(self.items), "applicable": 0,
                                  "conflict": 0, "unchanged": 0, "skipped": 0}
        for item in self.items:
            if item.applicable:
                result["applicable"] += 1
            if item.conflict:
                result["conflict"] += 1
            if item.status == STATUS_UNCHANGED:
                result["unchanged"] += 1
            if not item.applicable and item.status != STATUS_UNCHANGED:
                result["skipped"] += 1
        return result

    def markdown_text(self) -> str:
        counts = self.counts()
        lines = [
            "## \u4ea4\u63a5\u5e94\u7528\u8ba1\u5212",
            "",
            "- \u6761\u76ee {total}\uff0c\u53ef\u5e94\u7528 {applicable}\uff0c\u51b2\u7a81 {conflict}\uff0c"
            "\u65e0\u53d8\u5316 {unchanged}\uff0c\u8df3\u8fc7 {skipped}".format(**counts),
        ]
        if not self.same_project:
            lines.append("- \u8be5\u5305\u6765\u81ea\u5176\u4ed6\u9879\u76ee\uff0c\u8bf7\u4f7f\u7528\u300c\u5bfc\u5165\u65b0\u526f\u672c\u300d\u3002")
        if not self.baseline_known:
            lines.append("- \u7f3a\u5c11\u5df2\u77e5\u57fa\u51c6\uff1a{0}".format(NO_BASELINE_NOTICE))
        lines.extend("- \u63d0\u9192\uff1a{0}".format(item) for item in self.warnings)
        if self.items:
            lines.append("")
            lines.append("| \u6761\u76ee | \u72b6\u6001 | \u51b2\u7a81 | \u5c06\u5e94\u7528 | \u8bf4\u660e |")
            lines.append("|------|------|------|--------|------|")
            for item in self.items:
                lines.append(
                    "| {0} | {1} | {2} | {3} | {4} |".format(
                        item.rel_path or item.entry_id,
                        item.status,
                        "\u662f" if item.conflict else "\u5426",
                        "\u662f" if item.applicable else "\u5426",
                        item.reason.replace("|", "/"),
                    )
                )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "targetRoot": self.target_root,
            "sameProject": self.same_project,
            "moduleMissing": list(self.module_missing),
            "moduleConflicts": list(self.module_conflicts),
            "baselineKnown": self.baseline_known,
            "counts": self.counts(),
            "choices": self.choices(),
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "package": self.package.to_dict(),
        }


@dataclass
class HandoffApplyResult:
    """Outcome of one apply run."""

    success: bool = True
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    renamed_resources: List[Tuple[str, str]] = field(default_factory=list)
    rolled_back: bool = False
    message: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "applied": list(self.applied),
            "skipped": list(self.skipped),
            "conflicts": list(self.conflicts),
            "renamedResources": [list(item) for item in self.renamed_resources],
            "rolledBack": self.rolled_back,
            "message": self.message,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

_IMAGE_RE = r"!?\[[^\]]*\]\(([^)\s]+)"


def referenced_resources(text: str) -> List[str]:
    """Resource targets referenced from one chapter body (order preserved)."""
    found: List[str] = []
    for match in re.finditer(_IMAGE_RE, str(text or "")):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("data:"):
            continue
        if target not in found:
            found.append(target)
    return found


def _chapter_title(rel_path: str, text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return Path(rel_path).stem


def export_handoff_package(
    project_root,
    destination,
    *,
    chapters: Sequence[str],
    content_root=None,
    asset_roots: Sequence = (),
    project_id: str = "",
    project_name: str = "",
    document_version: str = "",
    baseline: Optional[Dict[str, str]] = None,
    baseline_id: str = "",
    baseline_state: Optional[str] = None,
    created_by: str = "",
    texts: Optional[Dict[str, str]] = None,
    package_name: str = DEFAULT_PACKAGE_NAME,
    comments: Sequence[object] = (),
    modules: Sequence[dict] = (),
    source_index: Sequence[dict] = (),
) -> HandoffPackage:
    """Write a self-contained handoff ZIP and return its manifest.

    ``chapters`` are ``content_root``-relative POSIX paths. ``texts`` supplies
    the *current* text per chapter (including unsaved buffers); anything absent
    is read from disk. ``baseline`` maps rel_path -> starting hash; without it
    ``baseline_state`` becomes ``unknown`` and the package states that no
    conflict-free claim is made.

    Referenced resources are packed from ``asset_roots`` (first match wins) or
    from ``content_root``; a resource that cannot be read becomes a warning
    instead of breaking the package.
    """
    root = Path(project_root).resolve()
    content = Path(content_root).resolve() if content_root is not None else root / "content"
    target_dir = Path(destination)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = str(package_name or DEFAULT_PACKAGE_NAME)
    target = target_dir / (name if name.endswith(".zip") else name + ".zip")

    baseline = dict(baseline or {})
    texts = {_norm(key): value for key, value in (texts or {}).items()}
    baseline_state = baseline_state or (BASELINE_KNOWN if baseline else BASELINE_UNKNOWN)
    package = HandoffPackage(
        package_path=str(target),
        package_id=str(uuid4()),
        project_id=str(project_id or ""),
        project_name=str(project_name or root.name),
        document_version=str(document_version or ""),
        created_at=_now(),
        created_by=str(created_by or ""),
        baseline_id=str(baseline_id or ""),
        baseline_state=baseline_state,
        modules=[dict(item) for item in modules],
        source_index=[dict(item) for item in source_index],
        referenced_comments=[str(getattr(item, "comment_id", "") or item) for item in comments],
    )
    if not baseline:
        package.warnings.append(NO_BASELINE_NOTICE)

    chapter_entries: List[HandoffEntry] = []
    resource_entries: List[HandoffEntry] = []
    payloads: List[Tuple[str, bytes]] = []
    seen_resources: Dict[str, str] = {}

    for rel_raw in chapters:
        rel = _norm(rel_raw)
        if not rel:
            package.warnings.append("\u8df3\u8fc7\u975e\u6cd5\u7ae0\u8282\u8def\u5f84\uff1a{0}".format(rel_raw))
            continue
        source = _resolve_inside(content, rel)
        if source is None:
            package.warnings.append("\u8df3\u8fc7\u8d8a\u51fa\u5185\u5bb9\u76ee\u5f55\u7684\u7ae0\u8282\uff1a{0}".format(rel))
            continue
        if rel in texts:
            data = str(texts[rel]).encode("utf-8")
        elif source.is_file():
            try:
                data = source.read_bytes()
            except OSError as exc:
                package.warnings.append("\u7ae0\u8282\u8bfb\u53d6\u5931\u8d25\uff0c\u5df2\u8df3\u8fc7\uff1a{0}\uff08{1}\uff09".format(rel, exc))
                continue
        else:
            package.warnings.append("\u7ae0\u8282\u4e0d\u5b58\u5728\uff0c\u5df2\u8df3\u8fc7\uff1a{0}".format(rel))
            continue
        current_hash = sha256_bytes(data)
        base_hash = str(baseline.get(rel, "") or "")
        text = data.decode("utf-8", errors="replace")
        archive_name = "{0}/{1}".format(CONTENT_DIR, rel)
        chapter_entries.append(
            HandoffEntry(
                entry_id="chapter:{0}".format(rel),
                kind=KIND_CHAPTER,
                rel_path=rel,
                name=Path(rel).name,
                title=_chapter_title(rel, text),
                base_hash=base_hash,
                hash=current_hash,
                size=len(data),
                archive_name=archive_name,
                changed=bool(base_hash) and base_hash != current_hash,
            )
        )
        payloads.append((archive_name, data))

        for ref in referenced_resources(text):
            res_name = Path(ref).name
            if not res_name:
                continue
            resolved = _find_resource(content, asset_roots, ref, res_name)
            if resolved is None:
                package.warnings.append("\u8d44\u6e90\u7f3a\u5931\uff0c\u672a\u6253\u5305\uff08\u7ae0\u8282\u5185\u5f15\u7528\u4fdd\u7559\uff09\uff1a{0}".format(ref))
                continue
            try:
                blob = resolved.read_bytes()
            except OSError as exc:
                package.warnings.append("\u8d44\u6e90\u8bfb\u53d6\u5931\u8d25\uff0c\u672a\u6253\u5305\uff1a{0}\uff08{1}\uff09".format(ref, exc))
                continue
            digest = sha256_bytes(blob)
            if res_name in seen_resources:
                if seen_resources[res_name] != digest:
                    package.warnings.append("\u540c\u540d\u8d44\u6e90\u5185\u5bb9\u4e0d\u540c\uff0c\u5df2\u6309 hash \u5206\u522b\u6807\u8bb0\uff1a{0}".format(res_name))
                    resource_entries.append(
                        HandoffEntry(
                            entry_id="resource:{0}:{1}".format(res_name, digest[:8]),
                            kind=KIND_RESOURCE,
                            rel_path=res_name,
                            name=res_name,
                            hash=digest,
                            size=len(blob),
                            archive_name="{0}/{1}.{2}".format(RESOURCE_DIR, digest[:8], res_name),
                            module_of=rel,
                        )
                    )
                    payloads.append(("{0}/{1}.{2}".format(RESOURCE_DIR, digest[:8], res_name), blob))
                continue
            seen_resources[res_name] = digest
            archive_name = "{0}/{1}".format(RESOURCE_DIR, res_name)
            resource_entries.append(
                HandoffEntry(
                    entry_id="resource:{0}".format(res_name),
                    kind=KIND_RESOURCE,
                    rel_path=res_name,
                    name=res_name,
                    hash=digest,
                    size=len(blob),
                    archive_name=archive_name,
                    module_of=rel,
                )
            )
            payloads.append((archive_name, blob))

    package.chapters = chapter_entries
    package.resources = resource_entries
    manifest = json.dumps(package.to_dict(), ensure_ascii=False, indent=2)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for archive_name, data in payloads:
            archive.writestr(archive_name, data)
        archive.writestr(MANIFEST_NAME, manifest)
    return package


def _find_resource(content: Path, asset_roots: Sequence, ref: str, name: str) -> Optional[Path]:
    """Locate a referenced resource: relative to content, then asset roots."""
    relative = _norm(ref)
    if relative:
        candidate = _resolve_inside(content, relative)
        if candidate is not None and candidate.is_file():
            return candidate
    for asset_root in asset_roots:
        base = Path(asset_root)
        if not base.is_dir():
            continue
        candidate = _resolve_inside(base, relative or name)
        if candidate is not None and candidate.is_file():
            return candidate
        for found in base.rglob(name):
            if found.is_file():
                return found
    return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_handoff_manifest(package_path) -> HandoffPackage:
    """Read the schema-1 manifest from a package; bad input never raises."""
    path = Path(package_path)
    if not path.is_file():
        return HandoffPackage(package_path=str(path),
                              warnings=["\u4ea4\u63a5\u5305\u4e0d\u5b58\u5728\uff1a{0}".format(path)])
    try:
        with zipfile.ZipFile(path, "r") as archive:
            try:
                raw = archive.read(MANIFEST_NAME)
            except KeyError:
                return HandoffPackage(
                    package_path=str(path),
                    warnings=["\u4ea4\u63a5\u5305\u7f3a\u5c11\u6e05\u5355\u6587\u4ef6\uff1a{0}".format(MANIFEST_NAME)],
                )
    except (OSError, zipfile.BadZipFile) as exc:
        return HandoffPackage(package_path=str(path),
                              warnings=["\u4ea4\u63a5\u5305\u65e0\u6cd5\u8bfb\u53d6\uff1a{0}".format(str(exc)[:160])])
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        return HandoffPackage(package_path=str(path),
                              warnings=["\u4ea4\u63a5\u5305\u6e05\u5355\u635f\u574f\uff1a{0}".format(str(exc)[:160])])
    if not isinstance(data, dict):
        return HandoffPackage(package_path=str(path),
                              warnings=["\u4ea4\u63a5\u5305\u6e05\u5355\u683c\u5f0f\u4e0d\u6b63\u786e\u3002"])
    package = HandoffPackage.from_dict(data, package_path=str(path))
    if package.schema != HANDOFF_SCHEMA:
        package.warnings.append("\u4ea4\u63a5\u5305\u5951\u7ea6\u4e0d\u5339\u914d\uff1a{0}".format(package.schema))
    if package.schema_version != HANDOFF_SCHEMA_VERSION:
        package.warnings.append(
            "\u4ea4\u63a5\u5305 schemaVersion \u4e0d\u53d7\u652f\u6301\uff1a{0}".format(package.schema_version)
        )
    return package


def read_handoff_entry(package_path, entry: HandoffEntry) -> Optional[bytes]:
    """Read one entry payload; missing/unreadable returns ``None``."""
    if entry is None or not entry.archive_name:
        return None
    try:
        with zipfile.ZipFile(Path(package_path), "r") as archive:
            return archive.read(entry.archive_name)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def handoff_entry_text(package_path, entry: HandoffEntry) -> str:
    data = read_handoff_entry(package_path, entry)
    if data is None:
        return ""
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Apply state (idempotency)
# ---------------------------------------------------------------------------


class HandoffApplyState:
    """Per-package apply ledger keyed by ``packageId + entryId + incomingHash``."""

    def __init__(self, state_dir) -> None:
        self.file = Path(state_dir) / APPLIED_FILE_NAME
        self._data: Dict[str, Dict[str, dict]] = {}
        self._load()

    def _load(self) -> None:
        self._data = {}
        if not self.file.is_file():
            return
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict) or raw.get("schemaVersion") != HANDOFF_SCHEMA_VERSION:
            return
        packages = raw.get("packages")
        if not isinstance(packages, dict):
            return
        for package_id, entries in packages.items():
            if isinstance(entries, dict):
                self._data[str(package_id)] = {
                    str(key): value for key, value in entries.items() if isinstance(value, dict)
                }

    def record(self, package_id: str, entry_id: str, *, incoming_hash: str,
               local_hash: str = "", path: str = "", status: str = STATUS_MODIFIED,
               stored_as: str = "") -> None:
        bucket = self._data.setdefault(str(package_id), {})
        bucket[str(entry_id)] = {
            "incomingHash": incoming_hash,
            "localHash": local_hash,
            "path": path,
            "storedAs": stored_as or path,
            "status": status,
            "appliedAt": _now(),
        }
        self.save()

    def get(self, package_id: str, entry_id: str) -> Optional[dict]:
        return self._data.get(str(package_id), {}).get(str(entry_id))

    def save(self) -> None:
        payload = {"schemaVersion": HANDOFF_SCHEMA_VERSION, "packages": self._data}
        self.file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.file, json.dumps(payload, ensure_ascii=False, indent=2))

    def to_dict(self) -> dict:
        return dict(self._data)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def _local_text(content_root: Path, rel: str) -> Optional[str]:
    target = _resolve_inside(content_root, rel)
    if target is None or not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _local_resource(roots: Sequence[Path], name: str) -> Tuple[Optional[Path], str]:
    for root in roots:
        target = _resolve_inside(root, name)
        if target is not None and target.is_file():
            try:
                return target, sha256_file(target)
            except OSError:
                return target, ""
    return None, ""


MODULE_MISSING_NOTICE = "\u5305\u5185\u56fa\u5b9a\u6a21\u5757\u7f3a\u5931\uff0c\u5df2\u4fdd\u7559\u539f\u5f15\u7528\u800c\u4e0d\u6539\u5176\u4ed6\u5f15\u7528\uff1a{0}"
MODULE_CONFLICT_NOTICE = "\u56fa\u5b9a\u6a21\u5757\u7248\u672c\u4e0e\u672c\u5730\u4e0d\u540c\uff0c\u539f\u5f15\u7528\u4e0d\u53d8\uff0c\u5df2\u5217\u4e3a\u5019\u9009\uff1a{0}"


def _collect_module_state(package: HandoffPackage, local_modules: Dict[str, str],
                          plan: HandoffApplyPlan) -> None:
    """Compare the package\'s fixed module snapshot with the receiver\'s.

    Modules are never rewritten by an apply: a missing one is reported so other
    references stay untouched, and a version/hash difference is listed as a
    candidate instead of silently replacing the local module.
    """
    for item in package.modules:
        if not isinstance(item, dict):
            continue
        module_id = str(item.get("id", "") or "")
        if not module_id:
            continue
        expected = str(item.get("hash", "") or item.get("version", "") or "")
        actual = str(local_modules.get(module_id, "") or "")
        if not actual:
            plan.module_missing.append(module_id)
            plan.warnings.append(MODULE_MISSING_NOTICE.format(module_id))
        elif expected and actual != expected:
            plan.module_conflicts.append(module_id)
            plan.warnings.append(MODULE_CONFLICT_NOTICE.format(module_id))


def _unknown_count(package: HandoffPackage) -> int:
    return sum(1 for item in package.entries if not item.base_hash)


def plan_handoff_apply(
    package_path,
    project_root,
    *,
    content_root=None,
    asset_roots: Sequence = (),
    project_id: str = "",
    selected: Optional[Sequence[str]] = None,
    include_deletions: bool = False,
    state_dir=None,
    buffer_texts: Optional[Dict[str, str]] = None,
    local_modules: Optional[Dict[str, str]] = None,
) -> HandoffApplyPlan:
    """Build the receiver-side diff plan (read-only; nothing is written).

    Selection defaults to "changed and not conflicting". ``selected`` (entry
    ids) overrides it, and an explicitly **empty** selection means the user
    cancelled: nothing becomes applicable. Deletions are never selected unless
    ``include_deletions=True``. An unsaved buffer supplied through
    ``buffer_texts`` participates in conflict detection.
    """
    root = Path(project_root).resolve()
    content = Path(content_root).resolve() if content_root is not None else root / "content"
    assets = [Path(item) for item in asset_roots] or [content, root / "assets"]
    state = HandoffApplyState(state_dir if state_dir is not None else root / ".state")
    package = read_handoff_manifest(package_path)
    plan = HandoffApplyPlan(package=package, target_root=str(root))
    plan.warnings.extend(package.warnings)
    plan.baseline_known = bool(package.baseline_state == BASELINE_KNOWN)
    if not plan.baseline_known:
        plan.warnings.append(UNKNOWN_BASELINE_NOTICE.format(_unknown_count(package)))
    explicit = selected is not None
    _collect_module_state(package, local_modules or {}, plan)
    selected_set = {str(item) for item in (selected or [])}
    known_project = str(project_id or "")
    plan.same_project = bool((not known_project) or (not package.project_id)
                             or (str(package.project_id) == known_project))
    if not plan.same_project:
        plan.warnings.append(REASON_FOREIGN)

    buffers = {_norm(key): value for key, value in (buffer_texts or {}).items()}

    for entry in package.chapters:
        if entry.rel_path in buffers:
            local_text = buffers[entry.rel_path]
        else:
            local_text = _local_text(content, entry.rel_path)
        local_hash = sha256_text(local_text) if local_text is not None else ""
        record = state.get(package.package_id, entry.entry_id)
        item = HandoffPlanItem(
            entry_id=entry.entry_id,
            kind=KIND_CHAPTER,
            rel_path=entry.rel_path,
            title=entry.title,
            base_hash=entry.base_hash,
            local_hash=local_hash,
            incoming_hash=entry.hash,
        )
        item.diff_text = render_unified_diff(local_text or "", handoff_entry_text(package_path, entry))
        if record and record.get("incomingHash") == entry.hash:
            if local_hash == str(record.get("localHash", "")):
                item.status = STATUS_ALREADY_APPLIED
                item.reason = REASON_ALREADY_APPLIED
                plan.items.append(item)
                continue
            item.status = STATUS_CONFLICT
            item.conflict = True
            item.reason = REASON_LOCAL_CHANGED
            plan.items.append(item)
            continue
        if not plan.same_project:
            item.status = STATUS_FOREIGN
            item.reason = REASON_FOREIGN
            plan.items.append(item)
            continue
        if local_text is None:
            if entry.base_hash:
                item.status = STATUS_CONFLICT
                item.conflict = True
                item.reason = "\u672c\u5730\u5df2\u65e0\u8be5\u7ae0\u8282\u800c\u57fa\u51c6\u5b58\u5728\uff0c\u4fdd\u7559\u672c\u5730\u72b6\u6001\u5e76\u5217\u4e3a\u5f85\u5904\u7406\u3002"
            else:
                item.status = STATUS_NEW
                item.reason = "\u672c\u5730\u65b0\u589e\u8be5\u7ae0\u8282\u3002"
        elif local_hash == entry.hash:
            item.status = STATUS_UNCHANGED
            item.reason = REASON_UNCHANGED
        elif entry.base_hash and local_hash != entry.base_hash:
            item.status = STATUS_CONFLICT
            item.conflict = True
            item.reason = REASON_CONFLICT
        elif not entry.base_hash:
            item.status = STATUS_CONFLICT
            item.conflict = True
            item.reason = REASON_BASELINE_UNKNOWN
        else:
            item.status = STATUS_MODIFIED
            item.reason = "\u672c\u5730\u4e0e\u57fa\u51c6\u4e00\u81f4\uff0c\u53ef\u5e94\u7528\u4ea4\u63a5\u5185\u5bb9\u3002"
        wanted = (entry.entry_id in selected_set) if explicit else \
            item.status in (STATUS_NEW, STATUS_MODIFIED)
        item.selected = bool(wanted and not item.conflict and item.status != STATUS_UNCHANGED)
        item.applicable = bool(item.selected)
        if not item.applicable and not item.conflict and item.status != STATUS_UNCHANGED:
            item.reason = REASON_DESELECTED
        plan.items.append(item)

    for entry in package.resources:
        _local_path, local_hash = _local_resource(assets, entry.name)
        record = state.get(package.package_id, entry.entry_id)
        incoming = read_handoff_entry(package_path, entry)
        item = HandoffPlanItem(
            entry_id=entry.entry_id,
            kind=KIND_RESOURCE,
            rel_path=entry.name,
            title=entry.name,
            base_hash=entry.base_hash,
            local_hash=local_hash,
            incoming_hash=entry.hash,
        )
        if incoming is None:
            item.status = STATUS_RESOURCE_MISSING
            item.reason = REASON_RESOURCE_MISSING
            plan.items.append(item)
            continue
        if local_hash and local_hash != entry.hash:
            item.status = STATUS_RESOURCE_MISMATCH
            item.conflict = True
            item.reason = REASON_RESOURCE_MISMATCH
            item.selected = entry.entry_id in selected_set
            item.applicable = bool(item.selected)
            plan.items.append(item)
            continue
        if local_hash == entry.hash:
            item.status = STATUS_UNCHANGED
            item.reason = REASON_UNCHANGED
            plan.items.append(item)
            continue
        if record and record.get("incomingHash") == entry.hash:
            item.status = STATUS_ALREADY_APPLIED
            item.reason = REASON_ALREADY_APPLIED
            plan.items.append(item)
            continue
        if not plan.same_project:
            item.status = STATUS_FOREIGN
            item.reason = REASON_FOREIGN
            plan.items.append(item)
            continue
        item.status = STATUS_NEW
        item.reason = "\u672c\u5730\u7f3a\u5c11\u8be5\u8d44\u6e90\uff0c\u53ef\u5199\u5165\u3002"
        item.selected = (entry.entry_id in selected_set) if explicit else True
        item.applicable = bool(item.selected)
        plan.items.append(item)
    return plan


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _snapshot(path: Optional[Path]) -> Optional[bytes]:
    if path is None or not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _restore(path: Optional[Path], data: Optional[bytes]) -> None:
    if path is None:
        return
    try:
        if data is None:
            if path.is_file():
                path.unlink()
        else:
            atomic_write_bytes(path, data)
    except OSError:
        pass


def _unique_sibling(directory: Path, name: str) -> Path:
    stem = Path(name).stem
    suffix = Path(name).suffix
    candidate = directory / "{0}.handoff{1}".format(stem, suffix)
    index = 2
    while candidate.exists():
        candidate = directory / "{0}.handoff{1}{2}".format(stem, index, suffix)
        index += 1
    return candidate


def apply_handoff_plan(
    plan: HandoffApplyPlan,
    *,
    project_root=None,
    content_root=None,
    asset_roots: Sequence = (),
    writer=None,
    writer_factory=None,
    state_dir=None,
) -> HandoffApplyResult:
    """Apply the selected, non-conflicting plan items with rollback.

    - A conflicting chapter keeps its local file; the remaining legal entries
      still apply.
    - A same-named resource with different bytes is written as a hash-suffixed
      sibling (never substituted in place) and reported in ``renamed_resources``.
    - Any write failure restores everything this run wrote and returns
      ``rolled_back=True``.
    - Applied entries are recorded per package + entry + incoming hash, so a
      second import of the same package writes nothing.
    """
    root = Path(project_root or plan.target_root).resolve()
    content = Path(content_root).resolve() if content_root is not None else root / "content"
    assets = [Path(item) for item in asset_roots] or [content, root / "assets"]
    state_path = Path(state_dir) if state_dir is not None else root / ".state"
    state = HandoffApplyState(state_path)
    result = HandoffApplyResult()
    result.warnings.extend(plan.warnings)
    package = plan.package

    if not plan.same_project:
        result.success = False
        result.message = REASON_FOREIGN
        return result

    if writer is None and writer_factory is None:
        from doc_tool.application.content.writer import ContentWriter
        writer = ContentWriter(content, state_path, assets_root=root / "assets")
    active_writer = writer
    undo: List[Tuple[Path, Optional[bytes]]] = []
    try:
        for item in plan.items:
            if not item.applicable:
                if item.status != STATUS_UNCHANGED:
                    result.skipped.append(item.entry_id)
                if item.conflict:
                    result.conflicts.append(item.entry_id)
                continue
            entry = package.entry(item.entry_id)
            if entry is None:
                result.skipped.append(item.entry_id)
                continue
            if item.kind == KIND_RESOURCE:
                _apply_resource(plan, item, entry, assets, state, result, undo)
                continue
            target = _resolve_inside(content, entry.rel_path)
            if target is None:
                result.skipped.append(item.entry_id)
                result.warnings.append("\u8df3\u8fc7\u8d8a\u754c\u7ae0\u8282\uff1a{0}".format(entry.rel_path))
                continue
            data = read_handoff_entry(package.package_path, entry)
            if data is None:
                result.skipped.append(item.entry_id)
                result.warnings.append(
                    "\u5305\u5185\u7ae0\u8282\u5185\u5bb9\u4e0d\u53ef\u83b7\u53d6\uff0c\u5df2\u8df3\u8fc7\uff1a{0}".format(entry.rel_path))
                continue
            if active_writer is None:
                active_writer = writer_factory()
            undo.append((target, _snapshot(target)))
            write_result = active_writer.write_text(entry.rel_path, data.decode("utf-8"))
            if getattr(write_result, "written", False) is not True:
                raise OSError(getattr(write_result, "error", "") or "\u5199\u5165\u672a\u6210\u529f")
            local_hash = sha256_bytes(target.read_bytes()) if target.is_file() else entry.hash
            state.record(package.package_id, entry.entry_id, incoming_hash=entry.hash,
                         local_hash=local_hash, path=entry.rel_path, status=STATUS_MODIFIED)
            result.applied.append(entry.entry_id)
    except Exception as exc:  # noqa: BLE001 - any failure rolls back this run
        for path, data in reversed(undo):
            _restore(path, data)
        result.success = False
        result.rolled_back = True
        result.applied = []
        result.message = "\u5e94\u7528\u5931\u8d25\u5df2\u56de\u6eda\u672c\u6b21\u8303\u56f4\uff1a{0}".format(str(exc)[:200])
        return result

    result.message = "\u5df2\u5e94\u7528 {0} \u9879\uff0c\u8df3\u8fc7 {1} \u9879\uff08\u51b2\u7a81 {2} \u9879\u5df2\u4fdd\u7559\u672c\u5730\uff09\u3002".format(
        len(result.applied), len(result.skipped), len(result.conflicts)
    )
    return result


def _apply_resource(plan, item, entry, assets, state, result, undo) -> None:
    """Write one resource entry; mismatched names get a hash-suffixed sibling."""
    incoming = read_handoff_entry(plan.package.package_path, entry)
    if incoming is None:
        result.skipped.append(item.entry_id)
        result.warnings.append(REASON_RESOURCE_MISSING + " " + entry.name)
        return
    directory = Path(assets[0]) if assets else Path(plan.target_root)
    directory.mkdir(parents=True, exist_ok=True)
    conflict = item.status == STATUS_RESOURCE_MISMATCH
    target = _unique_sibling(directory, entry.name) if conflict else directory / entry.name
    undo.append((target, _snapshot(target)))
    atomic_write_bytes(target, incoming)
    stored = target.name
    if conflict:
        result.renamed_resources.append((entry.name, stored))
        result.warnings.append(
            "\u540c\u540d\u8d44\u6e90\u5185\u5bb9\u4e0d\u540c\uff0c\u672a\u76f4\u63a5\u66ff\u4ee3\uff1a{0} \u2192 {1}".format(entry.name, stored)
        )
    state.record(plan.package.package_id, entry.entry_id, incoming_hash=entry.hash,
                 local_hash=sha256_bytes(incoming), path=entry.name, stored_as=stored,
                 status=STATUS_MODIFIED)
    result.applied.append(item.entry_id)


def import_handoff_as_new_copy(
    package_path,
    destination_root,
    *,
    selected: Optional[Sequence[str]] = None,
    include_resources: bool = True,
) -> dict:
    """Import a package from another project into a fresh directory copy.

    Only chapters (and optionally resources) are copied; the original project
    is never touched and nothing from its ``.state`` is carried over.
    """
    package = read_handoff_manifest(package_path)
    root = Path(destination_root)
    content = root / "content"
    resources = root / "resources"
    written: List[str] = []
    skipped: List[str] = []
    selected_set = {str(item) for item in (selected or [])}
    for entry in package.chapters:
        if selected_set and entry.entry_id not in selected_set:
            skipped.append(entry.entry_id)
            continue
        data = read_handoff_entry(package_path, entry)
        if data is None:
            skipped.append(entry.entry_id)
            continue
        target = _resolve_inside(content, entry.rel_path)
        if target is None:
            skipped.append(entry.entry_id)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, data)
        written.append(entry.rel_path)
    if include_resources:
        for entry in package.resources:
            if selected_set and entry.entry_id not in selected_set:
                continue
            data = read_handoff_entry(package_path, entry)
            if data is None:
                continue
            target = _resolve_inside(resources, entry.name)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, data)
            written.append("resources/" + entry.name)
    atomic_write(
        root / "\u4ea4\u63a5\u5bfc\u5165\u8bf4\u660e.md",
        FOREIGN_PROJECT_NOTICE.format(package.project_name) + "\n\n"
        + "\n".join("- {0}".format(item) for item in written) + "\n",
    )
    return {
        "success": bool(written),
        "root": str(root),
        "written": written,
        "skipped": skipped,
        "package": package.to_dict(),
        "message": FOREIGN_PROJECT_NOTICE.format(package.project_name),
    }


__all__ = [
    "APPLIED_FILE_NAME",
    "BASELINE_KNOWN",
    "BASELINE_UNKNOWN",
    "CONTENT_DIR",
    "DEFAULT_PACKAGE_NAME",
    "FOREIGN_PROJECT_NOTICE",
    "HANDOFF_SCHEMA",
    "HANDOFF_SCHEMA_VERSION",
    "KIND_CHAPTER",
    "KIND_RESOURCE",
    "MANIFEST_NAME",
    "NO_BASELINE_NOTICE",
    "REASON_ALREADY_APPLIED",
    "REASON_BASELINE_UNKNOWN",
    "REASON_CONFLICT",
    "REASON_DESELECTED",
    "REASON_FOREIGN",
    "REASON_LOCAL_CHANGED",
    "REASON_RESOURCE_MISMATCH",
    "REASON_RESOURCE_MISSING",
    "REASON_UNCHANGED",
    "RESOURCE_DIR",
    "STATUS_ALREADY_APPLIED",
    "STATUS_CONFLICT",
    "STATUS_DELETED",
    "STATUS_FOREIGN",
    "STATUS_MODIFIED",
    "STATUS_NEW",
    "STATUS_RESOURCE_MISMATCH",
    "STATUS_RESOURCE_MISSING",
    "STATUS_UNCHANGED",
    "UNKNOWN_BASELINE_NOTICE",
    "HandoffApplyPlan",
    "HandoffApplyResult",
    "HandoffApplyState",
    "HandoffEntry",
    "HandoffPackage",
    "HandoffPlanItem",
    "apply_handoff_plan",
    "export_handoff_package",
    "handoff_entry_text",
    "import_handoff_as_new_copy",
    "plan_handoff_apply",
    "read_handoff_entry",
    "read_handoff_manifest",
    "referenced_resources",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
]
