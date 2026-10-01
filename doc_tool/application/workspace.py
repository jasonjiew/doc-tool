# -*- coding: utf-8 -*-
"""\u7814\u53d1\u6587\u6863\u5de5\u4f5c\u533a\uff08V2.9 29-A / 1.1\u30011.2\u30011.3\uff09\u3002

\u5de5\u4f5c\u533a\u662f**\u5916\u5c42\u5bb9\u5668**\uff1a``workspace.yml`` schema 1 \u8bb0\u5f55\u5de5\u4f5c\u533a\u8eab\u4efd\u3001\u540d\u79f0\u3001
\u96c6\u5408\u7248\u672c\u3001\u6210\u5458\u6587\u6863\u7684\u89d2\u8272/\u9879\u76ee\u8eab\u4efd/\u76f8\u5bf9\u8def\u5f84\uff0c\u4ee5\u53ca\u5173\u7cfb\u6587\u4ef6\u4f4d\u7f6e\u3002
\u5355\u9879\u76ee\u4ecd\u53ef\u8131\u79bb\u5de5\u4f5c\u533a\u6253\u5f00\uff1b\u672c\u6a21\u5757\u4e0d\u4fee\u6539\u6210\u5458\u9879\u76ee\u5185\u5bb9\u3002

\u8fb9\u754c\uff1a

- \u6210\u5458\u8def\u5f84\u5fc5\u987b\u5728\u5de5\u4f5c\u533a\u6839**\u5185\u90e8**\uff0c\u8d8a\u754c\u6216\u7edd\u5bf9\u8def\u5f84\u4e00\u5f8b\u8df3\u8fc7\u5e76\u62a5\u544a\uff1b
- \u6210\u5458\u9879\u76ee\u5fc5\u987b schema \u53ef\u8bfb\uff0c\u5426\u5219\u8df3\u8fc7\u800c\u4e0d\u963b\u65ad\u5176\u4ed6\u6210\u5458\uff08\u9ed8\u8ba4\u90e8\u5206\u6210\u679c\u7ee7\u7eed\uff09\uff1b
- \u91cd\u590d projectId \u6216\u8def\u5f84\u8fd0\u884c\u65f6\u53bb\u91cd\u5e76\u63d0\u793a\u6765\u6e90\uff1b
- \u5916\u90e8\u9879\u76ee\u53ea\u80fd**\u590d\u5236\u5bfc\u5165**\u5e76\u751f\u6210\u65b0 projectId\u3002
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import yaml

from doc_tool.domain.errors import ProjectManifestError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.version import APP_VERSION

#: \u5de5\u4f5c\u533a\u6587\u4ef6\u540d\u4e0e\u683c\u5f0f\u7248\u672c\u3002
WORKSPACE_NAME = "workspace.yml"
WORKSPACE_SCHEMA_VERSION = 1
#: \u6587\u6863\u89d2\u8272\uff08\u5141\u8bb8\u91cd\u590d\uff09\u3002
DOCUMENT_ROLES = ("requirement", "design", "test", "other")
#: \u5de5\u4f5c\u533a\u5185\u5173\u7cfb\u6587\u4ef6\u7684\u9ed8\u8ba4\u4f4d\u7f6e\u3002
DEFAULT_RELATIONS_PATH = "relations.yml"
#: \u590d\u5236\u5bfc\u5165\u76ee\u5f55\u3002
MEMBERS_DIR = "documents"


@dataclass
class WorkspaceMember:
    """\u4e00\u4e2a\u6210\u5458\u6587\u6863\u3002"""

    role: str
    project_id: str
    relative_path: str
    name: str = ""
    document_version: str = ""
    schema_version: int = 0

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "projectId": self.project_id,
            "path": self.relative_path,
            "name": self.name,
            "documentVersion": self.document_version,
            "schemaVersion": self.schema_version,
        }


@dataclass
class WorkspaceIssue:
    """\u6210\u5458\u7ea7\u95ee\u9898\uff08\u8df3\u8fc7\u539f\u56e0\uff09\u3002"""

    relative_path: str
    reason: str
    severity: str = "warning"

    def to_dict(self) -> dict:
        return {"path": self.relative_path, "reason": self.reason, "severity": self.severity}


@dataclass
class Workspace:
    """\u5de5\u4f5c\u533a\u5b9e\u4f53\u3002"""

    workspace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    collection_version: str = "1.0"
    schema_version: int = WORKSPACE_SCHEMA_VERSION
    relations_path: str = DEFAULT_RELATIONS_PATH
    members: List[WorkspaceMember] = field(default_factory=list)
    issues: List[WorkspaceIssue] = field(default_factory=list)
    root: Optional[Path] = None
    created_with_version: str = APP_VERSION

    # --- \u5e8f\u5217\u5316 ---

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "workspaceId": self.workspace_id,
            "name": self.name,
            "collectionVersion": self.collection_version,
            "relations": self.relations_path,
            "createdWithVersion": self.created_with_version,
            "documents": [
                {
                    "role": member.role,
                    "projectId": member.project_id,
                    "path": member.relative_path,
                }
                for member in self.members
            ],
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    @property
    def file(self) -> Optional[Path]:
        return (self.root / WORKSPACE_NAME) if self.root is not None else None

    def save(self, root: Union[str, Path, None] = None) -> Path:
        target_root = Path(root) if root is not None else self.root
        if target_root is None:
            raise ProjectManifestError("\u5de5\u4f5c\u533a\u6839\u76ee\u5f55\u672a\u77e5\uff0c\u65e0\u6cd5\u4fdd\u5b58\u3002")
        self.root = Path(target_root)
        target = self.root / WORKSPACE_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".yml.tmp")
        tmp.write_text(self.to_yaml(), encoding="utf-8")
        try:
            os.replace(str(tmp), str(target))
        except OSError:
            shutil.move(str(tmp), str(target))
        return target

    # --- \u67e5\u8be2 ---

    @property
    def valid_members(self) -> List[WorkspaceMember]:
        skipped = {issue.relative_path for issue in self.issues if issue.severity == "error"}
        return [member for member in self.members if member.relative_path not in skipped]

    def member_project_root(self, member: WorkspaceMember) -> Optional[Path]:
        if self.root is None:
            return None
        return self.root / member.relative_path

    def roles(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for member in self.valid_members:
            counts[member.role] = counts.get(member.role, 0) + 1
        return counts

    def by_role(self, role: str) -> List[WorkspaceMember]:
        return [member for member in self.valid_members if member.role == role]

    def has_requirement(self) -> bool:
        return bool(self.by_role("requirement"))

    def to_dict_summary(self) -> dict:
        return {
            "workspaceId": self.workspace_id,
            "name": self.name,
            "collectionVersion": self.collection_version,
            "schemaVersion": self.schema_version,
            "roles": self.roles(),
            "hasRequirement": self.has_requirement(),
            "members": [member.to_dict() for member in self.members],
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u5de5\u4f5c\u533a\u6982\u89c8",
            "",
            "- \u540d\u79f0\uff1a{0}".format(self.name or "\u672a\u547d\u540d"),
            "- \u96c6\u5408\u7248\u672c\uff1a{0}".format(self.collection_version),
            "- \u6a21\u5f0f\u7248\u672c\uff1av{0}".format(self.schema_version),
            "",
        ]
        if not self.has_requirement():
            lines.append("\u672a\u5305\u542b\u9700\u6c42\u6587\u6863\uff1a\u8986\u76d6\u7387\u5c06\u4ee5 N/A \u5448\u73b0\uff0c\u4e0d\u963b\u65ad\u7f16\u8f91\u4e0e\u5bfc\u51fa\u3002")
            lines.append("")
        lines.append("| \u89d2\u8272 | \u6587\u6863 | \u9879\u76ee\u8def\u5f84 | \u7248\u672c |")
        lines.append("|------|------|----------|------|")
        for member in self.members:
            lines.append(
                "| {0} | {1} | {2} | {3} |".format(
                    member.role,
                    member.name or "\u2014",
                    member.relative_path,
                    member.document_version or "\u2014",
                )
            )
        if self.issues:
            lines.append("")
            lines.append("**\u8df3\u8fc7\u7684\u6210\u5458\uff1a**")
            lines.extend(
                "- {0}\uff1a{1}".format(issue.relative_path, issue.reason) for issue in self.issues
            )
        return "\n".join(lines)


def load_workspace(root: Union[str, Path]) -> Workspace:
    """\u52a0\u8f7d ``workspace.yml`` \u5e76\u6821\u9a8c\u6210\u5458\uff08\u53ea\u8bfb\uff09\u3002

    \u4e0d\u5408\u6cd5\u6210\u5458\u8fdb ``issues`` \u5e76\u4ece ``valid_members`` \u6392\u9664\uff0c**\u4e0d\u963b\u65ad**\u5176\u4ed6\u6210\u5458\u3002
    """
    base = Path(root).resolve()
    target = base / WORKSPACE_NAME
    if not target.is_file():
        raise ProjectManifestError(
            "\u5de5\u4f5c\u533a\u6587\u4ef6\u4e0d\u5b58\u5728\uff1a{0}".format(WORKSPACE_NAME),
            suggested_action="\u8bf7\u786e\u8ba4\u9009\u62e9\u4e86\u6b63\u786e\u7684\u5de5\u4f5c\u533a\u76ee\u5f55\u3002",
        )
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError, OSError) as exc:
        raise ProjectManifestError("\u5de5\u4f5c\u533a\u6587\u4ef6\u89e3\u6790\u5931\u8d25\uff1a{0}".format(exc)) from exc
    if not isinstance(data, dict):
        raise ProjectManifestError("\u5de5\u4f5c\u533a\u6587\u4ef6\u683c\u5f0f\u4e0d\u6b63\u786e\uff1a\u6839\u8282\u70b9\u5e94\u4e3a\u6620\u5c04\u3002")
    try:
        schema_version = int(data.get("schemaVersion", 0))
    except (TypeError, ValueError) as exc:
        raise ProjectManifestError("\u5de5\u4f5c\u533a schemaVersion \u5fc5\u987b\u662f\u6574\u6570\u3002") from exc
    if schema_version != WORKSPACE_SCHEMA_VERSION:
        raise ProjectManifestError(
            "\u4e0d\u652f\u6301\u7684\u5de5\u4f5c\u533a\u6a21\u5f0f\u7248\u672c\uff1a{0}".format(schema_version),
            details={"schemaVersion": str(schema_version)},
        )

    workspace = Workspace(
        workspace_id=str(data.get("workspaceId", "") or str(uuid.uuid4())),
        name=str(data.get("name", "") or ""),
        collection_version=str(data.get("collectionVersion", "1.0") or "1.0"),
        schema_version=schema_version,
        relations_path=str(data.get("relations", DEFAULT_RELATIONS_PATH) or DEFAULT_RELATIONS_PATH),
        created_with_version=str(data.get("createdWithVersion", APP_VERSION) or APP_VERSION),
        root=base,
    )
    seen_ids: Dict[str, str] = {}
    seen_paths: Dict[str, str] = {}
    for raw in data.get("documents") or []:
        if not isinstance(raw, dict):
            workspace.issues.append(WorkspaceIssue("(\u975e\u6cd5\u6761\u76ee)", "\u6210\u5458\u6761\u76ee\u5e94\u4e3a\u6620\u5c04\uff0c\u5df2\u8df3\u8fc7\u3002", "error"))
            continue
        rel = _safe_relative(raw.get("path"))
        role = str(raw.get("role", "") or "").strip().lower()
        project_id = str(raw.get("projectId", "") or "").strip()
        label = rel or "(\u7f3a\u5c11\u8def\u5f84)"
        if rel is None:
            workspace.issues.append(WorkspaceIssue(label, "\u6210\u5458\u8def\u5f84\u8d8a\u754c\u3001\u7edd\u5bf9\u8def\u5f84\u6216\u7f3a\u5931\uff0c\u5df2\u8df3\u8fc7\u3002", "error"))
            continue
        if role not in DOCUMENT_ROLES:
            workspace.issues.append(WorkspaceIssue(rel, "\u672a\u77e5\u6587\u6863\u89d2\u8272\uff1a{0}\u3002".format(role or "(\u7a7a)"), "error"))
            continue
        if rel in seen_paths:
            workspace.issues.append(WorkspaceIssue(rel, "\u8def\u5f84\u91cd\u590d\uff08\u4e0e {0} \u51b2\u7a81\uff09\uff0c\u5df2\u53bb\u91cd\u3002".format(seen_paths[rel]), "warning"))
            continue
        if project_id and project_id in seen_ids:
            workspace.issues.append(WorkspaceIssue(rel, "projectId \u91cd\u590d\uff08\u4e0e {0} \u51b2\u7a81\uff09\uff0c\u5df2\u53bb\u91cd\u3002".format(seen_ids[project_id]), "warning"))
            continue
        member = WorkspaceMember(role=role, project_id=project_id, relative_path=rel)
        _enrich_member(base, member, workspace)
        if member.relative_path not in {issue.relative_path for issue in workspace.issues if issue.severity == "error"}:
            seen_paths[rel] = rel
            if project_id:
                seen_ids[project_id] = rel
        workspace.members.append(member)
    return workspace


def create_workspace(
    root: Union[str, Path],
    *,
    name: str = "",
    collection_version: str = "1.0",
) -> Workspace:
    """\u521b\u5efa\u7a7a\u5de5\u4f5c\u533a\uff08\u4e0d\u8986\u76d6\u5df2\u5b58\u5728\u7684\uff09\u3002"""
    base = Path(root)
    target = base / WORKSPACE_NAME
    if target.exists():
        raise ProjectManifestError(
            "\u5de5\u4f5c\u533a\u5df2\u5b58\u5728\uff1a{0}".format(target),
            suggested_action="\u8bf7\u76f4\u63a5\u6253\u5f00\u73b0\u6709\u5de5\u4f5c\u533a\uff0c\u6216\u9009\u62e9\u53e6\u4e00\u4e2a\u76ee\u5f55\u3002",
        )
    base.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(
        name=name or base.name,
        collection_version=collection_version,
        root=base,
    )
    return workspace


def add_project(
    workspace: Workspace,
    project_root: Union[str, Path],
    *,
    role: str,
    relative_path: str = "",
    copy_external: bool = True,
) -> Tuple[Optional[WorkspaceMember], bool]:
    """\u628a\u9879\u76ee\u52a0\u5165\u5de5\u4f5c\u533a\uff1b\u8fd4\u56de ``(member, copied)``\u3002

    - \u9879\u76ee\u5728\u5de5\u4f5c\u533a\u6839**\u5185\u90e8**\uff1a\u76f4\u63a5\u5f15\u7528\uff1b
    - \u5728\u5916\u90e8\uff1a\u53ea\u80fd**\u590d\u5236\u5bfc\u5165**\u5230 ``documents/<name>``\uff0c\u5e76\u4e3a\u526f\u672c\u751f\u6210**\u65b0 projectId**\uff08\u907f\u514d\u8eab\u4efd\u51b2\u7a81\uff09\u3002
    """
    if workspace.root is None:
        raise ProjectManifestError("\u5de5\u4f5c\u533a\u6839\u76ee\u5f55\u672a\u77e5\uff0c\u65e0\u6cd5\u52a0\u5165\u9879\u76ee\u3002")
    role_key = str(role or "").strip().lower()
    if role_key not in DOCUMENT_ROLES:
        raise ProjectManifestError(
            "\u672a\u77e5\u6587\u6863\u89d2\u8272\uff1a{0}\u3002".format(role or "(\u7a7a)"),
            details={"role": role_key},
        )
    source = Path(project_root).resolve()
    manifest = ProjectManifest.load(source)  # \u4e0d\u53ef\u8bfb\u65f6\u81ea\u7136\u629b\u51fa
    root = workspace.root.resolve()
    inside = _is_inside(source, root)
    copied = False
    if inside:
        rel = source.relative_to(root).as_posix()
    else:
        if not copy_external:
            raise ProjectManifestError(
                "\u5916\u90e8\u9879\u76ee\u5fc5\u987b\u590d\u5236\u5bfc\u5165\u540e\u624d\u80fd\u52a0\u5165\u5de5\u4f5c\u533a\u3002",
                details={"path": str(source)},
            )
        rel = relative_path or "{0}/{1}".format(MEMBERS_DIR, source.name)
        destination = root / rel
        if destination.exists():
            raise ProjectManifestError(
                "\u590d\u5236\u76ee\u6807\u5df2\u5b58\u5728\uff1a{0}".format(rel),
                suggested_action="\u8bf7\u6539\u540d\u6216\u5148\u79fb\u8d70\u540c\u540d\u76ee\u5f55\u3002",
            )
        shutil.copytree(source, destination)
        copied = True
        manifest = ProjectManifest.load(destination)
        manifest.projectId = str(uuid.uuid4())
        manifest.createdWithVersion = APP_VERSION
        manifest.save(destination)
        source = destination

    member = WorkspaceMember(
        role=role_key,
        project_id=manifest.projectId,
        relative_path=rel,
        name=manifest.documentName,
        document_version=manifest.documentVersion,
        schema_version=manifest.schemaVersion,
    )
    existing_paths = {item.relative_path for item in workspace.members}
    existing_ids = {item.project_id for item in workspace.members if item.project_id}
    if rel in existing_paths:
        workspace.issues.append(WorkspaceIssue(rel, "\u8be5\u8def\u5f84\u5df2\u5728\u5de5\u4f5c\u533a\u4e2d\uff0c\u672a\u91cd\u590d\u52a0\u5165\u3002", "warning"))
        return None, copied
    if member.project_id and member.project_id in existing_ids:
        workspace.issues.append(WorkspaceIssue(rel, "\u8be5\u9879\u76ee\u5df2\u5728\u5de5\u4f5c\u533a\u4e2d\uff0c\u672a\u91cd\u590d\u52a0\u5165\u3002", "warning"))
        return None, copied
    workspace.members.append(member)
    return member, copied


def workspace_overview(workspace: Workspace) -> dict:
    """\u805a\u5408\u5de5\u4f5c\u533a\u4e0e\u5404\u6587\u6863\u7248\u672c\uff08\u53ea\u8bfb\uff09\u3002

    \u5404\u6587\u6863\u7248\u672c**\u72ec\u7acb**\uff1a\u4e0d\u628a\u4e09\u4efd\u4fee\u8ba2\u8868\u6539\u6210\u96c6\u5408\u7248\u672c\u3002
    """
    documents = []
    for member in workspace.members:
        entry = member.to_dict()
        skipped = {issue.relative_path for issue in workspace.issues if issue.severity == "error"}
        entry["available"] = member.relative_path not in skipped
        documents.append(entry)
    coverage = "N/A" if not workspace.has_requirement() else "applicable"
    return {
        "workspaceId": workspace.workspace_id,
        "name": workspace.name,
        "collectionVersion": workspace.collection_version,
        "roles": workspace.roles(),
        "hasRequirement": workspace.has_requirement(),
        "coverage": coverage,
        "documents": documents,
        "issues": [issue.to_dict() for issue in workspace.issues],
        "independentOpenAllowed": True,
    }


def _enrich_member(base: Path, member: WorkspaceMember, workspace: Workspace) -> None:
    """\u8bfb\u53d6\u6210\u5458\u9879\u76ee\u5143\u6570\u636e\uff1b\u4e0d\u53ef\u8bfb\u65f6\u8bb0\u5f55\u5e76\u8df3\u8fc7\u8be5\u6210\u5458\u3002"""
    target = base / member.relative_path
    if not target.is_dir():
        workspace.issues.append(
            WorkspaceIssue(member.relative_path, "\u6210\u5458\u76ee\u5f55\u4e0d\u5b58\u5728\uff0c\u5df2\u8df3\u8fc7\u3002", "error")
        )
        return
    try:
        manifest = ProjectManifest.load(target)
    except Exception as exc:  # noqa: BLE001 - \u5355\u4e2a\u6210\u5458\u4e0d\u53ef\u8bfb\u4e0d\u963b\u65ad\u5176\u4ed6\u6210\u5458
        workspace.issues.append(
            WorkspaceIssue(member.relative_path, "\u6210\u5458\u9879\u76ee\u4e0d\u53ef\u8bfb\uff1a{0}".format(exc), "error")
        )
        return
    member.name = manifest.documentName
    member.document_version = manifest.documentVersion
    member.schema_version = manifest.schemaVersion
    if not member.project_id:
        member.project_id = manifest.projectId


def _safe_relative(value) -> Optional[str]:
    text = str(value or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or text.startswith("~"):
        return None
    if ":" in text.split("/")[0]:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False