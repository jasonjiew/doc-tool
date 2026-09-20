# -*- coding: utf-8 -*-
"""项目服务：打开项目、最近项目列表、项目摘要。

任务 6.4/6.6 的服务层：为 GUI 提供「打开已有项目」「最近项目列表」
「项目校验」「打开目录」等操作的统一入口。

最近项目列表存储在用户目录 ``~/.doctool/recent.json``，
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

from doc_tool.domain.branding import USER_CONFIG_DIR_NAME
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
    config_dir = home / ".{0}".format(USER_CONFIG_DIR_NAME)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "recent.json"


def _config_dir() -> Path:
    """返回用户级配置目录（与最近项目列表同目录）。"""
    config_dir = Path.home() / ".{0}".format(USER_CONFIG_DIR_NAME)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_window_geometry() -> Optional[dict]:
    """读取持久化的窗口几何信息（geometry 字符串 + 是否最大化）。"""
    path = _config_dir() / "geometry.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "geometry": str(data.get("geometry", "")),
                "maximized": bool(data.get("maximized", False)),
            }
    except (json.JSONDecodeError, OSError):
        return None
    return None


def save_window_geometry(geometry: str, maximized: bool) -> None:
    """原子保存窗口几何信息。空 geometry 视为无效，跳过写入。"""
    if not geometry:
        return
    path = _config_dir() / "geometry.json"
    data = {"geometry": geometry, "maximized": bool(maximized)}
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


@dataclass
class RecentEntry:
    """最近项目条目。"""

    path: str
    name: str  # 项目目录名
    document_name: str = ""
    document_no: str = ""
    # 文档类型（requirement/design/general）；旧版记录缺省为空，首页隐藏类型徽章，
    # 再次打开项目时由 add_recent_project 补写（向后兼容迁移）。
    document_type: str = ""
    last_opened: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "documentName": self.document_name,
            "documentNo": self.document_no,
            "documentType": self.document_type,
            "lastOpened": self.last_opened,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RecentEntry":
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "")),
            document_name=str(data.get("documentName", "")),
            document_no=str(data.get("documentNo", "")),
            document_type=str(data.get("documentType", "")),
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


def filter_validation_report_content(
    content: str,
    *,
    status_filter: str = "",
    keyword: str = "",
) -> tuple[str, int]:
    """按状态（FAIL/PASS/指标）及关键词筛选校验报告内容。

    Args:
        content: 校验报告 Markdown 原文。
        status_filter: 状态筛选，可选 'FAIL'、'PASS'、'METRICS'，或空字符串表示全量。
        keyword: 检索关键词（不区分大小写，支持多词空格联合检索）。

    Returns:
        (过滤后的报告文本, 匹配的条目数)
    """
    if not content:
        return "", 0
    kw = (keyword or "").strip().lower()
    words = kw.split() if kw else []
    sf = (status_filter or "").strip().upper()

    lines = content.splitlines()
    if not sf and not words:
        count = sum(1 for line in lines if line.strip().startswith("- ["))
        return content, count

    doc_title = ""
    sections: List[Tuple[Optional[str], List[str]]] = []
    cur_header: Optional[str] = None
    cur_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            doc_title = line
        elif stripped.startswith("##"):
            if cur_header is not None or cur_lines:
                sections.append((cur_header, cur_lines))
            cur_header = line
            cur_lines = []
        else:
            cur_lines.append(line)
    if cur_header is not None or cur_lines:
        sections.append((cur_header, cur_lines))

    result_lines: List[str] = []
    if doc_title:
        result_lines.append(doc_title)
        result_lines.append("")

    matched_count = 0
    for header, sec_lines in sections:
        header_name = header.strip() if header else ""
        is_metrics_sec = any(k in header_name for k in ("关键指标", "总结", "Metrics", "Summary"))

        if sf in ("FAIL", "PASS"):
            if is_metrics_sec:
                continue
        elif sf == "METRICS":
            if not is_metrics_sec:
                continue

        filtered_sec: List[str] = []
        for line in sec_lines:
            stripped = line.strip()
            if not stripped:
                continue
            is_fail = stripped.startswith("- [FAIL]")
            is_pass = stripped.startswith("- [PASS]")
            if sf == "FAIL" and not is_fail:
                continue
            if sf == "PASS" and not is_pass:
                continue
            if sf == "METRICS":
                if not (stripped.startswith("- ") or stripped.startswith("|")):
                    continue
            if words and not all(w in stripped.lower() for w in words):
                continue
            filtered_sec.append(line)
            matched_count += 1

        if filtered_sec:
            if header:
                result_lines.append(header)
                result_lines.append("")
            result_lines.extend(filtered_sec)
            result_lines.append("")

    return "\n".join(result_lines).strip() + "\n", matched_count


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
    # 过滤掉不存在的路径；单条坏路径只跳过该条，不让整表加载失败。
    kept: List[RecentEntry] = []
    for entry in entries:
        try:
            if Path(entry.path).exists():
                kept.append(entry)
        except (OSError, ValueError):
            continue
    # 有陈旧条目被过滤时，把清理结果写回文件（尽力而为），避免脏数据
    # 长期滞留，导致界面始终显示「暂无有效最近项目」。
    if len(kept) != len(entries):
        try:
            _save_recent_projects(kept)
        except OSError:
            pass
    return kept


def add_recent_project(project_root: str, manifest: ProjectManifest) -> None:
    """添加或更新最近项目条目。"""
    root = Path(project_root).resolve()
    entry = RecentEntry(
        path=str(root),
        name=root.name,
        document_name=manifest.documentName,
        document_no=manifest.documentNo,
        document_type=manifest.documentType,
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
    try:
        resolved_root = str(Path(project_root).resolve())
    except Exception:
        resolved_root = None
    target_norm = os.path.normcase(os.path.normpath(project_root))
    entries = load_recent_projects()

    def _matches(e: RecentEntry) -> bool:
        if e.path == project_root:
            return True
        if os.path.normcase(os.path.normpath(e.path)) == target_norm:
            return True
        if resolved_root is not None:
            try:
                if str(Path(e.path).resolve()) == resolved_root:
                    return True
            except Exception:
                pass
        return False

    entries = [e for e in entries if not _matches(e)]
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
