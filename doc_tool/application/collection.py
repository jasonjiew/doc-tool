# -*- coding: utf-8 -*-
"""\u5b8c\u6574\u96c6\u5408\u53d1\u5e03\u4e8b\u52a1\uff08V2.9 29-F / 6.1\uff5e6.4\uff09\u3002

\u4e09\u4ef6\u4e8b\uff1a

1. **\u57fa\u7ebf\u6e05\u5355**\uff08``collection.yml``\uff09\uff1a\u6bcf\u6587\u4ef6 SHA-256\uff0c\u8986\u76d6\u6e05\u5355/\u6b63\u6587/\u56fe\u7247/\u8868\u683c/\u89c4\u8303/
   \u89c4\u5219/\u5173\u7cfb/\u8bc4\u5ba1/\u62a5\u544a/\u6b63\u5f0f\u4ea7\u7269\uff1b``complete`` \u5982\u5b9e\u6807\u8bb0\u90e8\u5206\u96c6\u5408\u3002
2. **\u79df\u7ea6\u4e0e\u987a\u5e8f**\uff1a\u5de5\u4f5c\u533a\u79df\u7ea6\uff08\u5e26\u8fc7\u671f\u4e0e\u6301\u6709\u8005\uff09 + \u6309\u56fa\u5b9a ``projectId`` \u987a\u5e8f\u7684\u9879\u76ee\u9501\uff1b
   **\u5199\u9501\u5fc5\u987b\u5728\u670d\u52a1\u5c42\u751f\u6548**\uff0c\u4e0d\u80fd\u53ea\u9760 UI \u7981\u7528\u3002
3. **\u53ef\u7528\u90e8\u5206\u6210\u679c**\uff1a\u4e2a\u522b\u6210\u5458\u5931\u8d25/\u7f3a\u8d44\u6e90\u65f6\u4ecd\u8f93\u51fa**\u53ef\u7528\u90e8\u5206 + \u7f3a\u5931\u6e05\u5355**\uff08``complete=false``\uff09\uff1b
   \u4e25\u683c\u7b56\u7565\uff08\u663e\u5f0f\u9009\u62e9\uff09\u624d\u8981\u6c42\u6210\u5458\u9f50\u5168\uff1b\u767b\u8bb0\u5931\u8d25\u4e5f**\u4fdd\u7559\u6210\u679c**\uff1b\u65e7\u96c6\u5408\u4fdd\u6301\u53ef\u8bfb\u3002
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import yaml

from doc_tool.domain.version import APP_VERSION

#: \u96c6\u5408\u6e05\u5355\u540d\u4e0e schema \u7248\u672c\u3002
COLLECTION_NAME = "collection.yml"
COLLECTION_SCHEMA_VERSION = 1
#: \u96c6\u5408\u4ed3\u5e93\u76ee\u5f55\uff08\u5de5\u4f5c\u533a\u5185\uff09\u3002
COLLECTIONS_DIR = "collections"
#: \u79df\u7ea6\u6587\u4ef6\u3002
LEASE_NAME = "collection.lock.json"
#: \u57fa\u7ebf\u8986\u76d6\u7684\u8d44\u6e90\u5206\u7c7b\uff08\u4e0e spec \u4e00\u81f4\uff09\u3002
BASELINE_CATEGORIES = (
    "manifest", "content", "image", "table", "standard", "rules", "relations",
    "review", "report", "artifact",
)
#: \u6269\u5c55\u540d -> \u5206\u7c7b\u6620\u5c04\u3002
_SUFFIX_CATEGORY = {
    ".docx": "artifact",
    ".md": "content",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
}
#: \u79df\u7ea6\u9ed8\u8ba4\u8fc7\u671f\uff08\u79d2\uff09\u3002
LEASE_TTL_SECONDS = 900


@dataclass
class BaselineFile:
    """\u57fa\u7ebf\u4e2d\u7684\u4e00\u4e2a\u6587\u4ef6\u3002"""

    relative_path: str
    sha256: str
    category: str = "content"
    size: int = 0
    member: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "category": self.category,
            "size": self.size,
            "member": self.member,
        }


@dataclass
class MemberOutcome:
    """\u6210\u5458\u6784\u5efa\u7ed3\u679c\uff08\u4e0d\u6210\u529f\u4e5f\u8bb0\u5f55\u539f\u56e0\uff09\u3002"""

    project_id: str
    role: str = ""
    relative_path: str = ""
    document_version: str = ""
    success: bool = True
    reason: str = ""
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "role": self.role,
            "path": self.relative_path,
            "documentVersion": self.document_version,
            "success": self.success,
            "reason": self.reason,
            "missing": list(self.missing),
        }


@dataclass
class CollectionManifest:
    """\u96c6\u5408\u57fa\u7ebf\u6e05\u5355\u3002"""

    collection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: str = "1.0"
    label: str = ""
    created_at: str = ""
    created_with_version: str = APP_VERSION
    complete: bool = False
    files: List[BaselineFile] = field(default_factory=list)
    members: List[MemberOutcome] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    legacy_partial: bool = False

    def to_dict(self) -> dict:
        return {
            "schemaVersion": COLLECTION_SCHEMA_VERSION,
            "collectionId": self.collection_id,
            "version": self.version,
            "label": self.label,
            "createdAt": self.created_at,
            "createdWithVersion": self.created_with_version,
            "complete": self.complete,
            "legacyPartial": self.legacy_partial,
            "members": [item.to_dict() for item in self.members],
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "files": [item.to_dict() for item in self.files],
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    def by_category(self, category: str) -> List[BaselineFile]:
        return [item for item in self.files if item.category == category]

    @property
    def categories(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.files:
            counts[item.category] = counts.get(item.category, 0) + 1
        return counts

    def markdown_text(self) -> str:
        lines = [
            "## \u96c6\u5408\u57fa\u7ebf",
            "",
            "- \u96c6\u5408\u7248\u672c\uff1a{0}".format(self.version),
            "- \u5b8c\u6574\u6027\uff1a{0}".format("\u5b8c\u6574" if self.complete else "**\u90e8\u5206**"),
            "- \u6587\u4ef6\u6570\uff1a{0}".format(len(self.files)),
            "- \u65f6\u95f4\uff1a{0}".format(self.created_at or "\u2014"),
        ]
        if self.legacy_partial:
            lines.append("- \u65e7\u683c\u5f0f\u8bb0\u5f55\uff1a**legacy-partial**\uff08\u4ec5 Markdown\uff0c\u53ef\u90e8\u5206\u6062\u590d\uff09")
        if self.missing:
            lines.append("")
            lines.append("**\u7f3a\u5931\u6e05\u5355\uff1a**")
            lines.extend("- {0}".format(item) for item in self.missing[:50])
        if self.warnings:
            lines.append("")
            lines.extend("- \u63d0\u793a\uff1a{0}".format(item) for item in self.warnings[:20])
        if self.categories:
            lines.append("")
            lines.append("| \u5206\u7c7b | \u6587\u4ef6\u6570 |")
            lines.append("|------|--------|")
            for key in BASELINE_CATEGORIES:
                if self.categories.get(key):
                    lines.append("| {0} | {1} |".format(key, self.categories[key]))
        return "\n".join(lines)


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def categorize(relative_path: str) -> str:
    """\u6309\u8def\u5f84\u4e0e\u6269\u5c55\u540d\u5f52\u7c7b\u3002"""
    text = str(relative_path or "").replace("\\", "/").lower()
    name = text.rsplit("/", 1)[-1]
    if name in ("project.yml", "workspace.yml", COLLECTION_NAME):
        return "manifest"
    if name in ("rules.yml", "quality_rules.json", "terms.json"):
        return "rules"
    if name == "relations.yml":
        return "relations"
    if "/skeleton/" in text or name == "pack.yml" or text.startswith("standards/"):
        return "standard"
    if "/reviews/" in text or name.startswith("comments") or "signoff" in name:
        return "review"
    if "/logs/" in text or name.endswith("-validation.md") or name.endswith("report.md"):
        return "report"
    if "/output/" in text:
        return "artifact"
    if "/tables/" in text:
        return "table"
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    return _SUFFIX_CATEGORY.get(suffix, "content")


def collect_files(
    root: Union[str, Path],
    *,
    member: str = "",
    skip_dirs: Sequence[str] = (".git", ".svn", "__pycache__", ".venv", ".vendor"),
) -> List[BaselineFile]:
    """\u9012\u5f52\u6536\u96c6\u53ef\u5165\u57fa\u7ebf\u7684\u6587\u4ef6\uff08\u8df3\u8fc7\u7248\u672c\u63a7\u5236\u4e0e\u865a\u62df\u73af\u5883\uff09\u3002"""
    base = Path(root)
    results: List[BaselineFile] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if any(part in skip_dirs for part in relative.split("/")):
            continue
        if relative.endswith((".tmp", ".bak")) or ".staging" in relative:
            continue
        if relative.startswith(COLLECTIONS_DIR + "/") or relative == LEASE_NAME:
            continue
        try:
            size = path.stat().st_size
            digest = sha256_file(path)
        except OSError:
            continue
        results.append(
            BaselineFile(
                relative_path=relative,
                sha256=digest,
                category=categorize(relative),
                size=size,
                member=member,
            )
        )
    return results


def build_manifest(
    root: Union[str, Path],
    *,
    version: str = "1.0",
    label: str = "",
    members: Optional[Sequence[MemberOutcome]] = None,
    strict: bool = False,
    extra_files: Optional[Sequence[BaselineFile]] = None,
) -> CollectionManifest:
    """\u7528**\u4e00\u81f4\u8f93\u5165\u5feb\u7167**\u6784\u5efa\u57fa\u7ebf\u6e05\u5355\u3002

    ``members`` \u4e2d\u5931\u8d25\u6210\u5458\u4e0d\u4f1a\u4e2d\u65ad\u6574\u4f53\uff1a\u7ed3\u679c\u4e3a ``complete=False`` + ``missing`` \u6e05\u5355\uff1b
    ``strict=True``\uff08\u7528\u6237\u663e\u5f0f\u9009\u62e9\uff09\u65f6\u8fd4\u56de\u7684\u6e05\u5355 ``complete`` \u4e3a False \u4e14 ``warnings`` \u660e\u786e\u8981\u6c42\u6210\u5458\u9f50\u5168\u3002
    """
    manifest = CollectionManifest(
        version=str(version),
        label=str(label or ""),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        created_with_version=APP_VERSION,
        members=list(members or []),
    )
    manifest.files = collect_files(root)
    if extra_files:
        manifest.files.extend(extra_files)
    missing = [item for item in manifest.members if not item.success]
    if missing:
        manifest.missing.extend(
            "{0}\uff08{1}\uff09\uff1a{2}".format(item.role or "member", item.relative_path, item.reason or "\u6784\u5efa\u672a\u6210\u529f")
            for item in missing
        )
        manifest.missing.extend(
            "{0}: {1}".format(item.relative_path, path)
            for item in missing
            for path in item.missing
        )
    manifest.complete = not manifest.missing
    if strict and manifest.missing:
        manifest.warnings.append("\u4e25\u683c\u96c6\u5408\u7b56\u7565\u8981\u6c42\u6210\u5458\u9f50\u5168\uff0c\u5f53\u524d\u4e3a\u90e8\u5206\u96c6\u5408\u3002")
    if not manifest.files:
        manifest.warnings.append("\u672a\u6536\u96c6\u5230\u4efb\u4f55\u6587\u4ef6\uff0c\u8bf7\u786e\u8ba4\u6839\u76ee\u5f55\u3002")
    return manifest


def register_manifest(
    root: Union[str, Path],
    manifest: CollectionManifest,
    *,
    allow_duplicate_version: bool = False,
) -> Tuple[Optional[Path], str]:
    """\u539f\u5b50\u767b\u8bb0\u57fa\u7ebf\uff1b\u91cd\u590d\u7248\u672c\u9ed8\u8ba4**\u53e6\u5b58\u552f\u4e00\u5feb\u7167**\u5e76\u63d0\u793a\u65b0\u7248\u672c\u3002

    \u8fd4\u56de ``(path, note)``\uff1b\u767b\u8bb0\u5931\u8d25\u65f6 ``path=None``\uff0c\u4f46**\u4e0d\u5220\u9664\u5df2\u6709\u6210\u679c**\u3002
    """
    base = Path(root)
    store = base / COLLECTIONS_DIR
    store.mkdir(parents=True, exist_ok=True)
    target = store / "{0}.yml".format(manifest.version)
    note = ""
    if target.exists() and not allow_duplicate_version:
        snapshot = "{0}-{1}".format(
            manifest.version, datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        )
        target = store / "{0}.yml".format(snapshot)
        note = "\u7248\u672c {0} \u5df2\u5b58\u5728\uff0c\u5df2\u53e6\u5b58\u5feb\u7167 {1}\uff1b\u8bf7\u4e3a\u4e0b\u4e00\u6b21\u767b\u8bb0\u4f7f\u7528\u65b0\u7248\u672c\u53f7\u3002".format(
            manifest.version, snapshot
        )
        manifest.warnings.append(note)
    try:
        tmp = target.with_suffix(".yml.tmp")
        tmp.write_text(manifest.to_yaml(), encoding="utf-8")
        os.replace(str(tmp), str(target))
    except OSError as exc:
        return None, "\u767b\u8bb0\u5931\u8d25\uff08\u6210\u679c\u4ecd\u4fdd\u7559\uff09\uff1a{0}".format(exc)
    return target, note


def load_manifest(path: Union[str, Path]) -> CollectionManifest:
    """\u52a0\u8f7d\u57fa\u7ebf\u6e05\u5355\uff1b\u65e7\u683c\u5f0f\uff08\u65e0 ``files``\uff09\u8bb0\u4e3a **legacy-partial**\u3002"""
    target = Path(path)
    if not target.is_file():
        raise ValueError("\u96c6\u5408\u6e05\u5355\u4e0d\u5b58\u5728\uff1a{0}".format(path))
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError, OSError) as exc:
        raise ValueError("\u96c6\u5408\u6e05\u5355\u89e3\u6790\u5931\u8d25\uff1a{0}".format(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("\u96c6\u5408\u6e05\u5355\u683c\u5f0f\u4e0d\u6b63\u786e\u3002")
    manifest = CollectionManifest(
        collection_id=str(data.get("collectionId", "") or uuid.uuid4()),
        version=str(data.get("version", "1.0") or "1.0"),
        label=str(data.get("label", "") or ""),
        created_at=str(data.get("createdAt", "") or ""),
        created_with_version=str(data.get("createdWithVersion", "") or ""),
        complete=bool(data.get("complete", False)),
        legacy_partial=bool(data.get("legacyPartial", False)),
        missing=list(data.get("missing") or []),
        warnings=list(data.get("warnings") or []),
    )
    for raw in data.get("files") or []:
        if not isinstance(raw, dict):
            continue
        relative = str(raw.get("path", "") or "")
        if not relative:
            continue
        manifest.files.append(
            BaselineFile(
                relative_path=relative,
                sha256=str(raw.get("sha256", "") or ""),
                category=str(raw.get("category", "") or categorize(relative)),
                size=int(raw.get("size", 0) or 0),
                member=str(raw.get("member", "") or ""),
            )
        )
    for raw in data.get("members") or []:
        if not isinstance(raw, dict):
            continue
        manifest.members.append(
            MemberOutcome(
                project_id=str(raw.get("projectId", "") or ""),
                role=str(raw.get("role", "") or ""),
                relative_path=str(raw.get("path", "") or ""),
                document_version=str(raw.get("documentVersion", "") or ""),
                success=bool(raw.get("success", True)),
                reason=str(raw.get("reason", "") or ""),
                missing=list(raw.get("missing") or []),
            )
        )
    if not manifest.files and data.get("files") is None:
        manifest.legacy_partial = True
        manifest.complete = False
    return manifest


def verify_manifest(root: Union[str, Path], manifest: CollectionManifest) -> Tuple[List[str], List[str]]:
    """\u6821\u9a8c\u57fa\u7ebf\u4e0e\u73b0\u573a\u6587\u4ef6\uff1a\u8fd4\u56de ``(\u7f3a\u5931/\u4e0d\u4e00\u81f4, \u591a\u4f59)``\u3002"""
    base = Path(root)
    problems: List[str] = []
    present: set = set()
    for item in manifest.files:
        target = base / item.relative_path
        present.add(item.relative_path)
        if not target.is_file():
            problems.append("\u7f3a\u5931\uff1a{0}".format(item.relative_path))
            continue
        if item.sha256 and sha256_file(target) != item.sha256:
            problems.append("\u5185\u5bb9\u4e0d\u4e00\u81f4\uff1a{0}".format(item.relative_path))
    current = {item.relative_path for item in collect_files(base)}
    extra = sorted(current - present)
    return problems, extra


def list_manifests(root: Union[str, Path]) -> List[Path]:
    """\u5217\u51fa\u5df2\u767b\u8bb0\u7684\u96c6\u5408\u6e05\u5355\uff08\u6309\u7248\u672c\u540d\u6392\u5e8f\uff09\u3002"""
    store = Path(root) / COLLECTIONS_DIR
    if not store.is_dir():
        return []
    return sorted(item for item in store.glob("*.yml") if item.is_file())


@dataclass
class Lease:
    """\u5de5\u4f5c\u533a\u79df\u7ea6\u3002"""

    owner: str
    pid: int
    acquired_at: float
    ttl_seconds: int = LEASE_TTL_SECONDS

    def expired(self, now: Optional[float] = None) -> bool:
        if self.ttl_seconds <= 0:
            return True
        return (now or time.time()) - self.acquired_at > self.ttl_seconds

    def to_dict(self) -> dict:
        return {
            "owner": self.owner,
            "pid": self.pid,
            "acquiredAt": self.acquired_at,
            "ttlSeconds": self.ttl_seconds,
        }


class LeaseError(RuntimeError):
    """\u79df\u7ea6\u51b2\u7a81\uff08\u670d\u52a1\u5c42\u5f3a\u5236\uff09\u3002"""


def acquire_lease(
    root: Union[str, Path],
    *,
    owner: str = "",
    ttl_seconds: int = LEASE_TTL_SECONDS,
) -> Lease:
    """\u83b7\u53d6\u5de5\u4f5c\u533a\u79df\u7ea6\uff1b\u5df2\u6709\u672a\u8fc7\u671f\u79df\u7ea6\u65f6**\u62d2\u7edd**\u3002"""
    base = Path(root)
    path = base / LEASE_NAME
    current = _read_lease(path)
    if current is not None and current.ttl_seconds > 0 and not current.expired():
        raise LeaseError(
            "\u5de5\u4f5c\u533a\u5df2\u88ab {0} \u5360\u7528\uff08pid {1}\uff09\uff0c\u8bf7\u7b49\u5f85\u6216\u7b49\u5f85\u8fc7\u671f\u3002".format(
                current.owner, current.pid
            )
        )
    lease = Lease(
        owner=owner or "{0}@{1}".format(socket.gethostname(), os.getpid()),
        pid=os.getpid(),
        acquired_at=time.time(),
        # ttl=0 表示“立即过期”的测试场景，不能被默认值覆盖。
        ttl_seconds=max(0, int(ttl_seconds)),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lease.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return lease


def release_lease(root: Union[str, Path], *, force: bool = False) -> bool:
    """\u91ca\u653e\u79df\u7ea6\uff1b``force=False`` \u65f6\u53ea\u91ca\u653e\u672c\u8fdb\u7a0b\u6301\u6709\u7684\u79df\u7ea6\u3002"""
    path = Path(root) / LEASE_NAME
    if not path.is_file():
        return False
    if not force:
        current = _read_lease(path)
        if current is not None and current.pid != os.getpid():
            return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def project_lock_order(project_ids: Iterable[str]) -> List[str]:
    """\u6309\u56fa\u5b9a ``projectId`` \u987a\u5e8f\u6392\u5217\u9501\uff08\u907f\u514d\u4ea4\u53c9\u6b7b\u9501\uff09\u3002"""
    return sorted({str(item) for item in project_ids if str(item or "").strip()})


def _read_lease(path: Path) -> Optional[Lease]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return Lease(
        owner=str(data.get("owner", "") or ""),
        pid=int(data.get("pid", 0) or 0),
        acquired_at=float(data.get("acquiredAt", 0) or 0),
        ttl_seconds=int(
            LEASE_TTL_SECONDS
            if data.get("ttlSeconds") is None
            else data.get("ttlSeconds")
        ),
    )