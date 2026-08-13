# -*- coding: utf-8 -*-
"""Review comments, append-only signoffs, packages, and approval gate."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from doc_tool.application.content.writer import atomic_write


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ReviewComment:
    comment_id: str
    text: str
    author: str
    created_at: str
    rel_path: str
    line_no: int
    status: str = "unresolved"
    resolved_at: str = ""
    association_changed: bool = False


@dataclass(frozen=True)
class Signoff:
    signoff_id: str
    author: str
    role: str
    created_at: str
    note: str = ""


class ReviewStore:
    def __init__(self, state_dir: Path) -> None:
        self.root = Path(state_dir) / "reviews"
        self.comments_file = self.root / "comments.json"
        self.signoffs_file = self.root / "signoffs.json"

    def _read(self, path: Path, key: str) -> list:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get(key, []) if isinstance(payload, dict) else []
        except (OSError, ValueError, TypeError):
            return []

    def comments(self) -> List[ReviewComment]:
        return [ReviewComment(**item) for item in self._read(self.comments_file, "comments") if isinstance(item, dict)]

    def signoffs(self) -> List[Signoff]:
        return [Signoff(**item) for item in self._read(self.signoffs_file, "signoffs") if isinstance(item, dict)]

    def _save_comments(self, comments: Sequence[ReviewComment]) -> None:
        atomic_write(self.comments_file, json.dumps({"comments": [asdict(item) for item in comments]}, ensure_ascii=False, indent=2))

    def add_comment(self, text: str, author: str, rel_path: str, line_no: int) -> ReviewComment:
        if not str(text).strip() or not str(author).strip():
            raise ValueError("评审意见和作者不能为空。")
        item = ReviewComment(str(uuid.uuid4()), text.strip(), author.strip(), _now(), rel_path, max(1, int(line_no)))
        comments = self.comments()
        comments.append(item)
        self._save_comments(comments)
        return item

    def delete_comment(self, comment_id: str) -> bool:
        comments = self.comments()
        kept = [item for item in comments if item.comment_id != comment_id]
        if len(kept) == len(comments):
            return False
        self._save_comments(kept)
        return True

    def set_resolved(self, comment_id: str, resolved: bool) -> ReviewComment:
        comments = self.comments()
        for item in comments:
            if item.comment_id == comment_id:
                item.status = "resolved" if resolved else "unresolved"
                item.resolved_at = _now() if resolved else ""
                self._save_comments(comments)
                return item
        raise KeyError(comment_id)

    def mark_association_changes(self, existing_paths: Iterable[str], renamed: Optional[dict] = None) -> None:
        existing = set(existing_paths)
        renamed = renamed or {}
        comments = self.comments()
        for item in comments:
            if item.rel_path in renamed:
                item.rel_path = str(renamed[item.rel_path])
                item.association_changed = True
            elif item.rel_path not in existing:
                item.association_changed = True
        self._save_comments(comments)

    def append_signoff(self, author: str, role: str, note: str = "") -> Signoff:
        if not str(author).strip() or not str(role).strip():
            raise ValueError("签字人和角色不能为空。")
        item = Signoff(str(uuid.uuid4()), author.strip(), role.strip(), _now(), note.strip())
        signoffs = self.signoffs()
        signoffs.append(item)
        atomic_write(self.signoffs_file, json.dumps({"signoffs": [asdict(value) for value in signoffs]}, ensure_ascii=False, indent=2))
        return item

    @property
    def unresolved_count(self) -> int:
        return sum(item.status != "resolved" for item in self.comments())


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    skipped: bool
    reasons: List[str]
    history_note: str = ""


def approval_gate(
    comments: Sequence[ReviewComment],
    signoffs: Sequence[Signoff],
    *,
    required_roles: Sequence[str] = (),
    skip: bool = False,
) -> GateResult:
    reasons = []
    unresolved = sum(item.status != "resolved" for item in comments)
    if unresolved:
        reasons.append("存在 {0} 条未解决评审意见".format(unresolved))
    signed_roles = {item.role for item in signoffs}
    missing = [role for role in required_roles if role not in signed_roles]
    if missing:
        reasons.append("缺少签字角色：{0}".format("、".join(missing)))
    if reasons and skip:
        return GateResult(True, True, reasons, "跳过审批：" + "；".join(reasons))
    return GateResult(not reasons, False, reasons)


class ReviewPackageBuilder:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir) / "review"

    def build(self, store: ReviewStore, snapshot: dict, diff_summary: dict, version: str) -> Path:
        """导出评审包到 ``<output>/review/<版本>_<时间戳>/`` 单目录。

        目录内含 comments.json / signoffs.json / snapshot.json /
        diff_summary.json / manifest.json，未解决意见在 comments.json 中
        ``unresolved`` 键单列。返回评审包目录路径。
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / "review-package-{0}-{1}".format(
            version, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        target.mkdir(parents=True, exist_ok=True)
        comments = store.comments()
        payloads = {
            "comments.json": {
                "comments": [asdict(item) for item in comments],
                "unresolved": [asdict(item) for item in comments if item.status != "resolved"],
            },
            "signoffs.json": {"signoffs": [asdict(item) for item in store.signoffs()]},
            "snapshot.json": dict(snapshot),
            "diff_summary.json": dict(diff_summary),
            "manifest.json": {
                "version": version,
                "generatedAt": _now(),
            },
        }
        for name, payload in payloads.items():
            atomic_write(target / name, json.dumps(payload, ensure_ascii=False, indent=2))
        return target
