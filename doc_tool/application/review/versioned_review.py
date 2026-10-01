# -*- coding: utf-8 -*-
"""内容版本评审与修订记录预填（V2.8 28-F / 6.1、6.2、6.3、6.4）。

设计要点：

- 评审意见与**内容版本**绑定（``content_hash``），并记录 ``baseline_id`` / ``package_id``；
- 内容变化后旧意见进入**待复核**（不会自动通过）；纯重命名（仅路径变）只映射位置；
- 状态迁移：``待修改 → 待复核 → 通过``，内容变化后已通过的转为**失效**；
- **默认待复核只提醒不阻断出稿**，严格交付（显式选择）才按真实状态限制；
- 修订记录预填：改动章节 + 可获取提交主题 + 建议版本，作者确认后**原子追加**；无 Git 时用本地改动兜底。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: 评审状态生命周期（与旧字段兼容）。
STATUS_PENDING_FIX = "待修改"
STATUS_PENDING_RECHECK = "待复核"
STATUS_PASSED = "通过"
STATUS_STALE = "失效"

LIFECYCLE = (STATUS_PENDING_FIX, STATUS_PENDING_RECHECK, STATUS_PASSED, STATUS_STALE)

#: 从旧的 ``status`` / ``confirm_status`` 推导生命周期状态。
_LEGACY_MAP = {
    "resolved": STATUS_PENDING_RECHECK,
    "unresolved": STATUS_PENDING_FIX,
    "confirmed": STATUS_PASSED,
    "open": STATUS_PENDING_FIX,
}


@dataclass
class ReviewLifecycle:
    """一条意见的版本化状态。"""

    comment_id: str
    status: str = STATUS_PENDING_FIX
    content_hash: str = ""
    baseline_id: str = ""
    package_id: str = ""
    stale_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "commentId": self.comment_id,
            "status": self.status,
            "contentHash": self.content_hash,
            "baselineId": self.baseline_id,
            "packageId": self.package_id,
            "staleReason": self.stale_reason,
        }


def content_hash(text: str) -> str:
    """内容指纹（去除行尾空白后计算，避免无关空白导致失效）。"""
    normalized = "\n".join(line.rstrip() for line in str(text or "").splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def legacy_status(item) -> str:
    """从旧记录推导生命周期状态（保证旧台账可读）。"""
    explicit = str(getattr(item, "lifecycle_status", "") or "").strip()
    if explicit in LIFECYCLE:
        return explicit
    confirm = str(getattr(item, "confirm_status", "") or "").strip()
    if confirm == "已确认":
        return STATUS_PASSED
    if confirm == "待复核":
        return STATUS_PENDING_RECHECK
    return _LEGACY_MAP.get(str(getattr(item, "status", "") or "").strip(), STATUS_PENDING_FIX)


def stale_comment_ids(
    comments: Sequence[object],
    current_hashes: Dict[str, str],
) -> List[str]:
    """找出因内容变化而应转为待复核/失效的意见。

    ``current_hashes`` 是 ``{rel_path: hash}``；路径不再存在的意见也算失效。
    """
    stale: List[str] = []
    for item in comments:
        rel_path = str(getattr(item, "rel_path", "") or "")
        recorded = str(getattr(item, "content_hash", "") or "")
        if not rel_path:
            continue
        current = current_hashes.get(rel_path)
        if current is None or (recorded and recorded != current):
            stale.append(str(getattr(item, "comment_id", "")))
    return stale


def apply_content_change(
    store,
    current_hashes: Dict[str, str],
    *,
    renamed: Optional[Dict[str, str]] = None,
) -> dict:
    """内容变化后更新评审状态（不自动通过）。

    - 纯重命名：仅映射 ``rel_path``，不改状态（保留已通过结论）；
    - 内容变化：已通过 → **失效**，其余 → **待复核**；
    - 总是记录当前内容指纹，供下一次比对。
    """
    comments = store.comments()
    renamed = {str(k): str(v) for k, v in (renamed or {}).items()}
    changed: List[str] = []
    remapped: List[str] = []
    rebound: List[str] = []
    for item in comments:
        rel_path = str(getattr(item, "rel_path", "") or "")
        if rel_path in renamed:
            item.rel_path = renamed[rel_path]
            item.association_changed = True
            remapped.append(item.comment_id)
            rel_path = item.rel_path
        current = current_hashes.get(rel_path)
        if current is None:
            continue
        recorded = str(getattr(item, "content_hash", "") or "")
        if not recorded:
            # 首次绑定内容版本：不算失效，避免对旧台账误伤；但必须写入。
            item.content_hash = current
            rebound.append(item.comment_id)
            continue
        if recorded == current:
            continue
        state = legacy_status(item)
        if state == STATUS_PASSED:
            item.lifecycle_status = STATUS_STALE
            if hasattr(item, "stale_reason"):
                item.stale_reason = "内容已变化，原通过结论失效"
        else:
            item.lifecycle_status = STATUS_PENDING_RECHECK
            if hasattr(item, "stale_reason"):
                item.stale_reason = "内容已变化，需重新复核"
        item.content_hash = current
        changed.append(item.comment_id)
    if changed or remapped or rebound:
        store.save_comments(comments)
    return {"changed": changed, "remapped": remapped, "rebound": rebound}


def confirm_comment(store, comment_id: str, *, evidence: str = "") -> object:
    """复核确认：待复核 → 通过，并保存当前证据。"""
    comments = store.comments()
    for item in comments:
        if item.comment_id != comment_id:
            continue
        item.lifecycle_status = STATUS_PASSED
        item.status = "resolved"
        item.resolved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        item.confirm_status = "已确认"
        if evidence:
            item.evidence = evidence
        item.stale_reason = ""
        store.save_comments(comments)
        return item
    raise KeyError(comment_id)


def request_recheck(store, comment_id: str, *, note: str = "") -> object:
    """修改并请求复核：任何状态 → 待复核（不自动通过）。"""
    comments = store.comments()
    for item in comments:
        if item.comment_id != comment_id:
            continue
        item.lifecycle_status = STATUS_PENDING_RECHECK
        item.status = "unresolved"
        item.resolved_at = ""
        item.confirm_status = "待复核"
        if note:
            item.review_note = note
        store.save_comments(comments)
        return item
    raise KeyError(comment_id)


@dataclass
class ReviewGatePolicy:
    """评审门禁策略：默认带提醒继续，严格交付才限制。"""

    strict: bool = False

    def evaluate(self, store) -> Tuple[bool, List[str]]:
        """返回 ``(allowed, reasons)``。"""
        comments = store.comments()
        pending = [
            item for item in comments
            if legacy_status(item) in (STATUS_PENDING_FIX, STATUS_PENDING_RECHECK)
        ]
        stale = [item for item in comments if legacy_status(item) == STATUS_STALE]
        reasons: List[str] = []
        if pending:
            reasons.append("存在 {0} 条待修改/待复核意见。".format(len(pending)))
        if stale:
            reasons.append("存在 {0} 条失效意见。".format(len(stale)))
        if not self.strict:
            return True, reasons
        return (not pending and not stale), reasons


@dataclass
class RevisionDraft:
    """修订记录预填草案（需作者确认）。"""

    version: str = ""
    chapters: List[str] = field(default_factory=list)
    commit_subjects: List[str] = field(default_factory=list)
    source: str = "local"

    def to_row(self) -> str:
        subject = "；".join(self.commit_subjects) if self.commit_subjects else "本地改动"
        chapters = "、".join(self.chapters[:5]) if self.chapters else "—"
        return "| {0} | {1} | {2} |".format(self.version, chapters, subject)


def build_revision_draft(
    changed_chapters: Sequence[str],
    *,
    current_version: str,
    commit_subjects: Optional[Sequence[str]] = None,
    bump: str = "patch",
) -> RevisionDraft:
    """预填改动章节、提交主题与建议版本。

    无 Git（``commit_subjects`` 为空）时用本地改动兜底，不阻断出稿。
    """
    from doc_tool.domain.manifest import increment_version

    try:
        suggested = increment_version(current_version or "1.0", bump)
    except ValueError:
        suggested = current_version or "1.0"
    subjects = [str(item).strip() for item in (commit_subjects or []) if str(item).strip()]
    return RevisionDraft(
        version=suggested,
        chapters=[str(item) for item in (changed_chapters or [])],
        commit_subjects=subjects,
        source="git" if subjects else "local",
    )


def append_revision_atomically(record_path: Path, draft: RevisionDraft, *, confirmed: bool = False) -> bool:
    """作者确认后原子追加修订记录行。

    未确认或路径不存在时返回 False（不写盘，不静默修改作者文件）。
    """
    if not confirmed or not record_path.is_file():
        return False
    from doc_tool.application.content.writer import atomic_write

    text = record_path.read_text(encoding="utf-8")
    row = draft.to_row()
    if not text.endswith("\n"):
        text += "\n"
    atomic_write(record_path, text + row + "\n")
    return True