# -*- coding: utf-8 -*-
"""V3.1 31-B: optional assignee / note on existing review items, and "my todos".

Design boundaries (openspec/changes/product-v31-team-workflow/design.md D2):

- Assignments are **collaboration hints**, not authentication and not edit
  permission. Without a configured owner everyone can still process the item
  and export the document; nothing here limits editing or 出稿.
- ``assignee``/``note``/``updatedAt`` are layered onto the *existing* review
  comment and relation-review objects. This module never builds a second
  "approved or not" conclusion: the pending/passed fact keeps coming from the
  V2.8 comment lifecycle and the V2.9 relation review records.
- A missing or broken ``team.yml`` falls back to the "unassigned" group and the
  local display name. Old records without the extra fields stay usable.
- FILTERING BY ASSIGNEE NEVER CHANGES REVIEW STATUS.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from doc_tool.application.content.writer import atomic_write

#: File name of the optional team config, relative to the project root.
TEAM_FILE_NAME = "team.yml"
#: File name of the assignment overlay, relative to the project ``.state`` dir.
ASSIGNMENTS_FILE_NAME = "assignments.json"
#: Assignment overlay schema version.
ASSIGNMENTS_SCHEMA_VERSION = 1
#: Team config schema version supported here.
TEAM_SCHEMA_VERSION = 1

#: Group label for items without an assignee.
UNASSIGNED = "未分配"  # noqa: RUF001 - user-visible label

#: Todo item sources.
SOURCE_COMMENT = "review-comment"
SOURCE_RELATION = "relation-review"
SOURCE_IMPACT = "impact-item"

#: Lifecycle statuses that still need work (mirrors V2.8 semantics; the fact
#: itself is read from the review objects, never recomputed here).
PENDING_LIFECYCLE = ("待修改", "待复核", "未确认")

TEAM_CONFIG_NOTICE = "团队配置不可用，已回退未分配分组与本地显示名。"
TEAM_CONFIG_MISSING = "未配置 team.yml，全部条目默认未分配。"


@dataclass(frozen=True)
class TeamMember:
    """One display-name member entry from ``team.yml``."""

    name: str
    role: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role}


@dataclass
class TeamConfig:
    """Optional project team config (display names only; no accounts)."""

    members: List[TeamMember] = field(default_factory=list)
    current_user: str = ""
    loaded: bool = False
    error: str = ""
    source: str = ""

    @property
    def names(self) -> List[str]:
        return [item.name for item in self.members if item.name]

    @property
    def display_name(self) -> str:
        """Current display identity; falls back to the local user name."""
        if self.current_user:
            return self.current_user
        return _local_display_name()

    def is_known(self, name: str) -> bool:
        if not name:
            return True
        return name in self.names or name == self.current_user

    def to_dict(self) -> dict:
        return {
            "members": [item.to_dict() for item in self.members],
            "currentUser": self.current_user,
            "loaded": self.loaded,
            "error": self.error,
            "source": self.source,
        }


def _local_display_name() -> str:
    """Local display name used when no team config is available."""
    for key in ("DOC_TOOL_AUTHOR", "USERNAME", "USER"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return "本地用户"


def load_team_config(project_root, *, path: Optional[Path] = None) -> TeamConfig:
    """Load ``team.yml``; a broken/missing config never raises.

    Returns a config whose ``loaded`` is False and ``error`` explains the
    fallback. Callers group those items under "unassigned".
    """
    root = Path(project_root).resolve()
    target = Path(path) if path is not None else root / TEAM_FILE_NAME
    config = TeamConfig(source=str(target))
    if not target.is_file():
        config.error = TEAM_CONFIG_MISSING
        return config
    try:
        import yaml  # local import: yaml is only needed on this path
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - any parse/IO failure falls back
        config.error = "team.yml 解析失败：{0}".format(str(exc)[:160])
        return config
    if not isinstance(data, dict):
        config.error = "team.yml 根节点应为映射。"
        return config
    try:
        schema = int(data.get("schemaVersion", TEAM_SCHEMA_VERSION))
    except (TypeError, ValueError):
        config.error = "team.yml schemaVersion 不是整数。"
        return config
    if schema != TEAM_SCHEMA_VERSION:
        config.error = "team.yml schemaVersion {0} 不受支持。".format(schema)
        return config
    members: List[TeamMember] = []
    raw_members = data.get("members")
    if raw_members is None:
        raw_members = []
    if not isinstance(raw_members, list):
        config.error = "team.yml members 应为列表。"
        return config
    for raw in raw_members:
        if isinstance(raw, str):
            name = raw.strip()
            role = ""
        elif isinstance(raw, dict):
            name = str(raw.get("name", "") or "").strip()
            role = str(raw.get("role", "") or "").strip()
        else:
            continue
        if name:
            members.append(TeamMember(name=name, role=role))
    config.members = members
    config.current_user = str(data.get("currentUser", "") or data.get("current", "") or "").strip()
    config.loaded = True
    return config


@dataclass(frozen=True)
class AssignmentRecord:
    """One assignment overlay entry (collaboration hint only)."""

    item_id: str
    source: str
    assignee: str = ""
    note: str = ""
    updated_at: str = ""
    updated_by: str = ""

    def to_dict(self) -> dict:
        return {
            "itemId": self.item_id,
            "source": self.source,
            "assignee": self.assignee,
            "note": self.note,
            "updatedAt": self.updated_at,
            "updatedBy": self.updated_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssignmentRecord":
        return cls(
            item_id=str(data.get("itemId", "") or ""),
            source=str(data.get("source", "") or ""),
            assignee=str(data.get("assignee", "") or "").strip(),
            note=str(data.get("note", "") or ""),
            updated_at=str(data.get("updatedAt", "") or ""),
            updated_by=str(data.get("updatedBy", "") or ""),
        )


class AssignmentStore:
    """Assignment overlay stored in project version-control data (``.state/``).

    The overlay is deliberately a side car: review JSON keeps its own shape, so
    old records without assignee fields stay readable and V2.8/V2.9 keep
    owning the review conclusion.
    """

    def __init__(self, state_dir) -> None:
        self.state_dir = Path(state_dir)
        self.file = self.state_dir / ASSIGNMENTS_FILE_NAME
        self.writable = True
        self.warnings: List[str] = []
        self._records: Dict[str, AssignmentRecord] = {}
        self.load()

    def load(self) -> None:
        """Load the overlay; a broken file degrades to "all unassigned"."""
        self._records = {}
        if not self.file.is_file():
            return
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.warnings.append("负责人记录不可读取，已按未分配处理：{0}".format(str(exc)[:160]))
            return
        if not isinstance(data, dict) or data.get("schemaVersion") != ASSIGNMENTS_SCHEMA_VERSION:
            self.warnings.append("负责人记录格式不匹配，已按未分配处理。")
            return
        items = data.get("assignments")
        if not isinstance(items, list):
            self.warnings.append("负责人记录缺少 assignments 列表，已按未分配处理。")
            return
        for raw in items:
            if not isinstance(raw, dict):
                continue
            record = AssignmentRecord.from_dict(raw)
            if record.item_id:
                self._records[record.item_id] = record

    def save(self) -> None:
        payload = {
            "schemaVersion": ASSIGNMENTS_SCHEMA_VERSION,
            "assignments": [item.to_dict() for item in self._records.values()],
        }
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.file, json.dumps(payload, ensure_ascii=False, indent=2))
        except (OSError, ValueError) as exc:
            # Some enterprise file filters reject the atomic replace step.
            # The overlay stays valid in memory for this session; report it
            # instead of failing the assignment.
            self.warnings.append("负责人记录落盘失败，本次会话内仍可用：{0}".format(str(exc)[:160]))

    def records(self) -> List[AssignmentRecord]:
        return list(self._records.values())

    def get(self, item_id: str) -> Optional[AssignmentRecord]:
        return self._records.get(str(item_id or ""))

    def assign(self, item_id: str, assignee: str, *, source: str = "",
               note: Optional[str] = None, by: str = "") -> AssignmentRecord:
        """Assign (or clear, with an empty assignee) one item.

        Returns the stored record. Raises ``PermissionError`` for read-only
        projects and ``ValueError`` for an empty item id.
        """
        key = str(item_id or "").strip()
        if not key:
            raise ValueError("待办标识不能为空。")
        if not self.writable:
            raise PermissionError("只读项目不能修改负责人。")
        previous = self._records.get(key)
        record = AssignmentRecord(
            item_id=key,
            source=source or (previous.source if previous else ""),
            assignee=str(assignee or "").strip(),
            note=previous.note if note is None and previous else (note or ""),
            updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            updated_by=str(by or ""),
        )
        self._records[key] = record
        self.save()
        return record

    def clear(self, item_id: str) -> bool:
        key = str(item_id or "").strip()
        if key not in self._records:
            return False
        self._records.pop(key, None)
        self.save()
        return True


@dataclass
class TodoItem:
    """One aggregated collaboration todo (status read from existing objects)."""

    item_id: str
    source: str
    title: str = ""
    rel_path: str = ""
    chapter_no: str = ""
    status: str = ""  # read from V2.8/V2.9, never recomputed here
    pending: bool = True
    assignee: str = ""
    note: str = ""
    updated_at: str = ""
    detail: str = ""

    @property
    def group(self) -> str:
        return self.assignee or UNASSIGNED

    def to_dict(self) -> dict:
        return {
            "itemId": self.item_id,
            "source": self.source,
            "title": self.title,
            "relPath": self.rel_path,
            "chapterNo": self.chapter_no,
            "status": self.status,
            "pending": self.pending,
            "assignee": self.assignee,
            "note": self.note,
            "updatedAt": self.updated_at,
            "detail": self.detail,
        }


@dataclass
class TodoBoard:
    """Aggregated todo board: unassigned / my todos / by source."""

    items: List[TodoItem] = field(default_factory=list)
    my_name: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def unassigned(self) -> List[TodoItem]:
        return [item for item in self.items if not item.assignee and item.pending]

    def mine(self, name: Optional[str] = None) -> List[TodoItem]:
        who = (name if name is not None else self.my_name) or ""
        return [item for item in self.items if item.pending and item.assignee == who and who]

    def by_source(self, source: str) -> List[TodoItem]:
        return [item for item in self.items if item.source == source]

    def pending(self) -> List[TodoItem]:
        return [item for item in self.items if item.pending]

    def counts(self) -> Dict[str, int]:
        pending = self.pending()
        return {
            "total": len(self.items),
            "pending": len(pending),
            "unassigned": len(self.unassigned),
            "mine": len(self.mine()),
        }

    def to_dict(self) -> dict:
        return {
            "myName": self.my_name,
            "counts": self.counts(),
            "warnings": list(self.warnings),
            "items": [item.to_dict() for item in self.items],
        }


def _comment_pending(comment) -> bool:
    """Read (never recompute) whether a review comment still needs work.

    The fact comes from the existing V2.8 lifecycle helper, so this module
    cannot drift into owning a second "passed or not" opinion.
    """
    from doc_tool.application.review.versioned_review import legacy_status

    try:
        lifecycle = legacy_status(comment)
    except Exception:  # noqa: BLE001 - a broken record must not break the board
        lifecycle = str(getattr(comment, "lifecycle_status", "") or "")
    return lifecycle in PENDING_LIFECYCLE


def _safe_comments(review_store) -> List[object]:
    if review_store is None:
        return []
    try:
        return list(review_store.comments())
    except Exception:  # noqa: BLE001 - a broken review store must not break todos
        return []


def _safe_relation_records(record_store) -> List[object]:
    if record_store is None:
        return []
    try:
        return list(record_store.pending())
    except Exception:  # noqa: BLE001
        return []


def build_todo_board(
    *,
    review_store=None,
    relation_store=None,
    impact_report=None,
    assignments: Optional[AssignmentStore] = None,
    team: Optional[TeamConfig] = None,
) -> TodoBoard:
    """Aggregate the existing pending items with their assignment overlay.

    ``review_store`` supplies V2.8 comments, ``relation_store`` the V2.9
    relation review records (``pending()`` already excludes ``通过``) and
    ``impact_report`` optionally contributes the impact warnings as
    needs-attention entries. The pass/fail fact is always read from those
    objects; assigning an owner changes nothing about it.
    """
    if assignments is None:
        assignments = AssignmentStore(Path(".") / ".state")
        assignments.writable = False
    board = TodoBoard(my_name=(team.display_name if team is not None else _local_display_name()))
    board.warnings.extend(assignments.warnings)
    if team is not None and team.error:
        board.warnings.append(team.error if team.loaded else TEAM_CONFIG_NOTICE)

    for comment in _safe_comments(review_store):
        item_id = "comment:{0}".format(getattr(comment, "comment_id", ""))
        record = assignments.get(item_id)
        pending = _comment_pending(comment)
        board.items.append(
            TodoItem(
                item_id=item_id,
                source=SOURCE_COMMENT,
                title=str(getattr(comment, "text", "") or "")[:80],
                rel_path=str(getattr(comment, "rel_path", "") or ""),
                chapter_no=str(getattr(comment, "chapter_no", "") or ""),
                status=str(getattr(comment, "lifecycle_status", "")
                           or getattr(comment, "confirm_status", "")
                           or getattr(comment, "status", "") or ""),
                pending=pending,
                assignee=(record.assignee if record else ""),
                note=(record.note if record else ""),
                updated_at=(record.updated_at if record else ""),
                detail="V2.8 意见（复核结论仍由原意见生命周期决定）",
            )
        )

    for raw in _safe_relation_records(relation_store):
        relation_id = str(getattr(raw, "relation_id", "") or "")
        item_id = "relation:{0}".format(relation_id)
        record = assignments.get(item_id)
        source_key = getattr(raw, "source", ("", ""))
        target_key = getattr(raw, "target", ("", ""))
        board.items.append(
            TodoItem(
                item_id=item_id,
                source=SOURCE_RELATION,
                title="{0} → {1}".format(_key_text(source_key), _key_text(target_key)),
                rel_path="",
                status=str(getattr(raw, "status", "") or ""),
                pending=True,  # record_store.pending() already filtered 通过
                assignee=(record.assignee if record else ""),
                note=(record.note if record else getattr(raw, "note", "") or ""),
                updated_at=(record.updated_at if record else ""),
                detail="V2.9 关系复核（未通过项）",
            )
        )

    if impact_report is not None:
        for index, warning in enumerate(list(getattr(impact_report, "warnings", []) or [])):
            item_id = "impact:{0}".format(index)
            record = assignments.get(item_id)
            board.items.append(
                TodoItem(
                    item_id=item_id,
                    source=SOURCE_IMPACT,
                    title=str(warning)[:80],
                    status="待处理",
                    pending=True,
                    assignee=(record.assignee if record else ""),
                    note=(record.note if record else ""),
                    updated_at=(record.updated_at if record else ""),
                    detail="V2.9 影响提示",
                )
            )
    return board


def _key_text(key) -> str:
    if isinstance(key, (tuple, list)) and len(key) == 2:
        return "{0}/{1}".format(key[0], key[1])
    return str(key or "")


def todos_for(
    board: TodoBoard,
    assignee: Optional[str] = None,
    *,
    source: Optional[str] = None,
    include_unassigned: bool = False,
) -> List[TodoItem]:
    """Filter a board by assignee/source **without touching review status**.

    ``assignee=None`` returns the current user's pending items; pass
    ``include_unassigned=True`` to add the unassigned group (the default
    behaviour when no team config exists).
    """
    who = board.my_name if assignee is None else assignee
    result: List[TodoItem] = []
    for item in board.items:
        if not item.pending:
            continue
        if source is not None and item.source != source:
            continue
        if item.assignee == who and who:
            result.append(item)
        elif include_unassigned and not item.assignee:
            result.append(item)
    return result


def assign_todo(assignments: AssignmentStore, item_id: str, assignee: str, *,
                source: str = "", note: Optional[str] = None, by: str = "") -> AssignmentRecord:
    """Assign one aggregated todo item (collaboration hint only)."""
    return assignments.assign(item_id, assignee, source=source, note=note, by=by)


def render_todo_board(board: TodoBoard, *, limit: int = 50) -> str:
    """Plain-text report for the overview panel / command output."""
    counts = board.counts()
    lines = [
        "## 我的待办",
        "",
        "- 当前显示身份：{0}".format(board.my_name or "(未命名)"),
        "- 待处理 {pending}，未分配 {unassigned}，我的 {mine}，合计 {total}".format(**counts),
    ]
    if board.warnings:
        lines.append("")
        lines.extend("- 提醒：{0}".format(item) for item in board.warnings)
    pending = board.pending()[:limit]
    if pending:
        lines.append("")
        lines.append("| 负责人 | 来源 | 状态 | 定位 | 内容 |")
        lines.append("|--------|------|------|------|------|")
        for item in pending:
            lines.append(
                "| {0} | {1} | {2} | {3} | {4} |".format(
                    item.group, item.source, item.status or "-",
                    item.rel_path or item.chapter_no or "-",
                    item.title.replace("|", "/"),
                )
            )
    return "\n".join(lines)


__all__ = [
    "ASSIGNMENTS_FILE_NAME",
    "ASSIGNMENTS_SCHEMA_VERSION",
    "SOURCE_COMMENT",
    "SOURCE_IMPACT",
    "SOURCE_RELATION",
    "TEAM_CONFIG_MISSING",
    "TEAM_CONFIG_NOTICE",
    "TEAM_FILE_NAME",
    "UNASSIGNED",
    "AssignmentRecord",
    "AssignmentStore",
    "TeamConfig",
    "TeamMember",
    "TodoBoard",
    "TodoItem",
    "assign_todo",
    "build_todo_board",
    "load_team_config",
    "render_todo_board",
    "todos_for",
]