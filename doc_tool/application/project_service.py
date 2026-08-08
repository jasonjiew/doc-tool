# -*- coding: utf-8 -*-
"""项目服务：打开项目、最近项目列表、项目摘要。

任务 6.4/6.6 的服务层：为 GUI 提供「打开已有项目」「最近项目列表」
「项目校验」「打开目录」等操作的统一入口。

最近项目列表存储在用户目录 ``~/.konsung-doc-tool/recent.json``，
仅记录项目绝对路径和最后打开时间，不存储项目内容。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from doc_tool.domain.errors import (
    IncompatibleSchemaError,
    ProjectManifestError,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.version import can_write_schema


# 最近项目列表文件上限
MAX_RECENT_PROJECTS = 20

# 最近项目列表存储位置
def _recent_file() -> Path:
    """返回最近项目列表文件路径（用户目录下）。"""
    home = Path.home()
    config_dir = home / ".konsung-doc-tool"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "recent.json"


@dataclass
class RecentEntry:
    """最近项目条目。"""

    path: str
    name: str  # 项目目录名
    document_name: str = ""
    document_no: str = ""
    last_opened: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "documentName": self.document_name,
            "documentNo": self.document_no,
            "lastOpened": self.last_opened,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RecentEntry":
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "")),
            document_name=str(data.get("documentName", "")),
            document_no=str(data.get("documentNo", "")),
            last_opened=str(data.get("lastOpened", "")),
        )


@dataclass
class ProjectSummary:
    """项目摘要：用于主窗口展示。"""

    manifest: ProjectManifest
    paths: ProjectPaths
    project_root: Path
    is_writable: bool
    source_exists: bool
    template_exists: bool
    content_exists: bool
    output_exists: bool
    lock_info: Optional[dict] = None


def open_project(project_root: str) -> ProjectSummary:
    """打开已有项目，返回摘要。

    Raises:
        ProjectManifestError: 清单不存在或损坏。
        IncompatibleSchemaError: 模式版本不兼容。
    """
    root = Path(project_root).resolve()
    manifest = ProjectManifest.load(root)
    paths = manifest.resolve_paths(root)
    source_path = paths.resolve(manifest.relative_source_docx())
    template_path = paths.resolve(manifest.relative_template_docx())
    content_path = paths.resolve(manifest.relative_content_root())

    # 检查锁状态
    from doc_tool.domain.project_lock import inspect_lock

    lock = inspect_lock(paths)
    lock_info = None
    if lock is not None:
        lock_info = {
            "host": lock.host,
            "pid": lock.pid,
            "taskType": lock.task_type,
            "startTime": lock.start_time,
            "isAlive": lock.is_alive(),
        }

    return ProjectSummary(
        manifest=manifest,
        paths=paths,
        project_root=root,
        is_writable=manifest.is_writable() and can_write_schema(manifest.schemaVersion),
        source_exists=source_path.exists(),
        template_exists=template_path.exists(),
        content_exists=content_path.exists(),
        output_exists=paths.output_dir.exists(),
        lock_info=lock_info,
    )


def read_validation_report_summary(report_path: Path) -> dict:
    """读取严格校验报告的计数和失败项，供 GUI 展示。"""
    summary = {
        "exists": False,
        "passCount": 0,
        "failCount": 0,
        "failures": [],
        "updatedAt": "",
    }
    try:
        text = Path(report_path).read_text(encoding="utf-8")
        modified = datetime.fromtimestamp(
            Path(report_path).stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
    except (OSError, UnicodeError):
        return summary
    pattern = re.compile(r"^- \[(PASS|FAIL)\]\s*(.+)$", re.MULTILINE)
    matches = pattern.findall(text)
    failures = [detail.strip() for status, detail in matches if status == "FAIL"]
    summary.update({
        "exists": True,
        "passCount": sum(1 for status, _ in matches if status == "PASS"),
        "failCount": len(failures),
        "failures": failures,
        "updatedAt": modified,
    })
    return summary


def load_recent_projects() -> List[RecentEntry]:
    """加载最近项目列表。"""
    recent_path = _recent_file()
    if not recent_path.exists():
        return []
    try:
        data = json.loads(recent_path.read_text(encoding="utf-8"))
        entries = [RecentEntry.from_dict(item) for item in data if isinstance(item, dict)]
    except (json.JSONDecodeError, OSError):
        return []
    # 过滤掉不存在的路径
    return [e for e in entries if Path(e.path).exists()]


def add_recent_project(project_root: str, manifest: ProjectManifest) -> None:
    """添加或更新最近项目条目。"""
    root = Path(project_root).resolve()
    entry = RecentEntry(
        path=str(root),
        name=root.name,
        document_name=manifest.documentName,
        document_no=manifest.documentNo,
        last_opened=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    entries = load_recent_projects()
    # 移除重复
    entries = [e for e in entries if e.path != entry.path]
    entries.insert(0, entry)
    entries = entries[:MAX_RECENT_PROJECTS]
    _save_recent_projects(entries)


def remove_recent_project(project_root: str) -> None:
    """从最近项目列表移除一条。"""
    root = str(Path(project_root).resolve())
    entries = load_recent_projects()
    entries = [e for e in entries if e.path != root]
    _save_recent_projects(entries)


def _save_recent_projects(entries: List[RecentEntry]) -> None:
    recent_path = _recent_file()
    data = [e.to_dict() for e in entries]
    tmp = recent_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.replace(str(tmp), str(recent_path))
    except OSError:
        import shutil

        shutil.move(str(tmp), str(recent_path))
