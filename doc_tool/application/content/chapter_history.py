# -*- coding: utf-8 -*-
"""V3.1 31-A: read-only chapter change history (Git) with local-history fallback.

Answers one question: "who changed this chapter, and when?"

Boundaries (openspec/changes/product-v31-team-workflow/design.md D1):

- The Git side is strictly read-only: only ``git log --follow`` / ``git show``
  style queries. No status/add/commit/checkout, and history is never rewritten.
- Commit text is read at the path the file had *at that commit*; the rename
  chain is walked commit by commit, so old paths reachable via ``--follow``
  stay readable.
- When Git is unavailable, the project is not in a repository, the clone is
  shallow, or a command fails, the service automatically falls back to the
  V2.6 ``LocalHistoryStore`` recovery points.
- With no records at all it returns the current on-disk content plus a source
  note, never raising an uncaught exception and never blocking editing.
- Comparing against the current *unsaved buffer* only reports facts (unsaved
  changes present / differs from the selected version). Author and time mean
  "commit source", never "current editor".
- Restoring old content goes through the existing ``ContentWriter`` (unsaved
  protection + bounded local history) and becomes a *new save*; Git history is
  untouched.

Pure Python application service: no Qt, no CLI dependency, directly callable
from the UI, the command palette and later queues.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from doc_tool.application.content.changes import render_unified_diff
from doc_tool.application.content.local_history import LocalHistoryStore
from doc_tool.application.content.vcs_changes import find_git_repo_root

#: Field separator between commit metadata and file status (ASCII US).
_FIELD_SEP = "\x1f"
#: Record separator between commits (ASCII RS).
_RECORD_SEP = "\x1e"
#: Default number of history records fetched per query (design.md D1: last 50).
DEFAULT_HISTORY_LIMIT = 50
#: git command timeout in seconds.
DEFAULT_TIMEOUT = 20.0

SOURCE_GIT = "git"
SOURCE_LOCAL = "local"
SOURCE_CURRENT = "current"

#: One-line git log format (``%x1f`` fields, ``%x1e`` records).
_LOG_FORMAT = _FIELD_SEP.join(("%H", "%an", "%aI", "%s")) + _RECORD_SEP

NO_HISTORY_NOTICE = "No readable history record found; showing current on-disk content."
LOCAL_FALLBACK_NOTICE = "Git history unavailable; fell back to local history."


@dataclass(frozen=True)
class ChapterCommit:
    """One chapter commit record (read-only; author/time mean commit source)."""

    version_id: str
    source: str
    author: str = ""
    committed_at: str = ""
    subject: str = ""
    path: str = ""
    original_path: str = ""
    changed_path: Optional[str] = None

    @property
    def content_path(self) -> str:
        """Path to use when reading this commit's text (``<commit>:<path>``)."""
        if self.changed_path:
            return self.changed_path
        return self.path or self.original_path

    @property
    def was_renamed(self) -> bool:
        """Whether this commit renamed the chapter.

        ``path`` is always the path the file had *at the commit* (the old path
        for a rename), so the rename fact is read from the changed path that the
        commit produced.
        """
        if self.changed_path and self.changed_path != self.original_path:
            return True
        return bool(self.original_path) and self.original_path != self.path

    def to_dict(self) -> dict:
        return {
            "versionId": self.version_id,
            "source": self.source,
            "author": self.author,
            "committedAt": self.committed_at,
            "subject": self.subject,
            "path": self.path,
            "originalPath": self.original_path,
            "changedPath": self.changed_path,
            "renamed": self.was_renamed,
        }


@dataclass(frozen=True)
class HistoryVersion:
    """Read-only result of opening one historical chapter text."""

    version_id: str
    source: str
    text: str = ""
    path: str = ""
    available: bool = True
    note: str = ""

    @property
    def images_unavailable_note(self) -> str:
        """Image note: history stores text only, never the then-current assets.

        Neither Git nor local history keeps the image binaries of that moment,
        so a historical preview never passes current assets off as the ones
        from back then (design.md D1).
        """
        if any(marker in self.text for marker in ("![", "](assets/", "](images/")):
            return (
                "History stores chapter text only; images may be current assets "
                "and do not represent the historical version."
            )
        return ""


@dataclass
class ChapterHistory:
    """Chapter history query result (plain data, directly displayable)."""

    rel_path: str
    source: str = SOURCE_CURRENT
    commits: List[ChapterCommit] = field(default_factory=list)
    total: int = 0
    truncated: bool = False
    current_text: str = ""
    note: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def has_commits(self) -> bool:
        return bool(self.commits)

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "source": self.source,
            "total": self.total,
            "truncated": self.truncated,
            "note": self.note,
            "warnings": list(self.warnings),
            "commits": [item.to_dict() for item in self.commits],
        }


@dataclass(frozen=True)
class BufferComparison:
    """Factual comparison of the editing buffer against a historical version."""

    version_id: str
    source: str
    buffer_changed: bool
    differs: bool
    disk_differs_from_version: bool
    buffer_text: str = ""
    version_text: str = ""
    disk_text: str = ""
    diff_text: str = ""

    def to_dict(self) -> dict:
        return {
            "versionId": self.version_id,
            "source": self.source,
            "bufferChanged": self.buffer_changed,
            "differs": self.differs,
            "diskDiffersFromVersion": self.disk_differs_from_version,
            "diffText": self.diff_text,
        }


@dataclass
class HistoryQuery:
    """Chapter history query parameters (all optional)."""

    rel_path: str
    limit: int = DEFAULT_HISTORY_LIMIT
    offset: int = 0
    buffer_text: Optional[str] = None


def parse_git_log_z(output: bytes) -> List[dict]:
    """Parse **one commit's** ``git show --name-status -z`` output.

    Output shape (``-z`` puts a NUL *before* every status entry, and the format
    line sits ahead of it)::

        <sha>\x1f<author>\x1f<ISO>\x1f<subject>\n\0M\0<path>\0
        <sha>\x1f<author>\x1f<ISO>\x1f<subject>\n\0R100\0<old>\0<new>\0

    Combining ``--format`` with ``--name-status -z`` over a *range* interleaves
    neighbouring commits\' status entries, so chapter history issues one query
    per commit instead and parses each answer with this function. That keeps the
    commit/status pairing exact while staying entirely read-only.
    Returns a one-element list (the parsed commit) or an empty list when the
    object id cannot be recognised.
    ``path`` is the path this file had *at that commit* (the old path for a
    rename), so the caller can walk the rename chain backwards.
    """
    text = (output or b"").decode("utf-8", errors="replace")
    head = text.split(_FIELD_SEP)
    if len(head) < 4:
        return []
    sha = head[0].strip("\0 \t\r\n\ufeff")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        return []
    author = head[1].strip()
    committed_at = head[2].strip()
    subject = head[3].split(_RECORD_SEP)[0].strip("\0 \t\r\n")
    status_blob = ""
    for chunk in head[3:]:
        if "\0" in chunk:
            status_blob = chunk
            break
    chunks = [
        chunk.strip(" \t\r\n") for chunk in status_blob.split("\0") if chunk.strip(" \t\r\n")
    ]
    changed_path = None
    old_path = None
    target = None
    index = 0
    while index < len(chunks):
        token = chunks[index]
        if token[:1] in ("R", "C") and len(token) > 1:
            if index + 2 >= len(chunks):
                break
            old_path = chunks[index + 1]
            changed_path = chunks[index + 2]
            target = old_path
            index += 3
            continue
        if len(token) == 1 and token.isalpha():
            if index + 1 >= len(chunks):
                break
            changed_path = chunks[index + 1]
            target = changed_path
            index += 2
            continue
        index += 1
    return [
        {
            "version_id": sha,
            "author": author,
            "committed_at": committed_at,
            "subject": subject,
            "path": (target or "").replace("\\", "/"),
            "original_path": (old_path or "").replace("\\", "/"),
            "changed_path": (changed_path or "").replace("\\", "/"),
        }
    ]


def _pick_entry(records: List[dict], repo_relative: str) -> List[dict]:
    """Keep the entry of a commit that concerns ``repo_relative``.

    ``git show --name-status`` lists every file of the commit, so the chapter's
    own entry is selected by new path, old path (rename) or changed path. When
    none matches (for instance a commit that only touched a file already known
    to follow this chapter), a synthetic record is returned with the tracked
    path: the commit still appears, but no unrelated file is ever attached to
    the chapter.
    """
    for item in records:
        paths = (item.get("path", ""), item.get("original_path", ""), item.get("changed_path", ""))
        if repo_relative in paths:
            return [item]
    if not records:
        return []
    head = dict(records[0])
    head["path"] = repo_relative
    head["original_path"] = repo_relative
    head["changed_path"] = repo_relative
    return [head]


class ChapterHistoryService:
    """Chapter history facade: read-only Git history, local fallback, restore."""

    def __init__(
        self,
        project_root: Path,
        content_root: Path,
        state_dir: Optional[Path] = None,
        *,
        git_executable: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        writable: bool = True,
        local_history: Optional[LocalHistoryStore] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.content_root = Path(content_root).resolve()
        self.state_dir = Path(state_dir) if state_dir is not None else self.project_root / ".state"
        self.timeout = float(timeout)
        self.writable = bool(writable)
        self.warnings: List[str] = []
        self._runner = runner
        self._git = git_executable or shutil.which("git") or "git"
        self._local = local_history or LocalHistoryStore(
            self.content_root, self.state_dir, writable=self.writable
        )

    @property
    def local_history(self) -> LocalHistoryStore:
        return self._local

    def _relative(self, rel_path: str) -> str:
        """Normalize a chapter relative path; invalid/escaping input -> ``""``."""
        raw = str(rel_path or "")
        if not raw.strip():
            return ""
        try:
            candidate = Path(raw.replace("\\", "/"))
            if candidate.is_absolute() or ".." in candidate.parts:
                return ""
            return candidate.as_posix()
        except (OSError, ValueError):
            return ""

    def _abs(self, rel: str) -> Path:
        return self.content_root / rel

    def _read_disk_text(self, rel: str) -> str:
        try:
            return self._abs(rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _run_git(self, args: Sequence[str], cwd: Path) -> Optional[subprocess.CompletedProcess]:
        """Run a read-only git command; unavailable/timeout/error -> ``None``."""
        if self._runner is not None:
            try:
                return self._runner(list(args), cwd=str(cwd))
            except Exception as exc:  # noqa: BLE001 - injected runner failure falls back
                self.warnings.append("git query failed: {0}".format(str(exc)[:160]))
                return None
        if shutil.which(self._git) is None:
            return None
        try:
            return subprocess.run(
                [self._git, *args],
                cwd=str(cwd),
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.warnings.append("git query failed: {0}".format(str(exc)[:160]))
            return None

    def git_root(self) -> Optional[Path]:
        """Repository root containing the project, or ``None`` when outside Git."""
        try:
            return find_git_repo_root(self.project_root)
        except (OSError, RuntimeError):
            return None

    def collect_git_history(self, rel: str, *, limit: int = DEFAULT_HISTORY_LIMIT,
                            offset: int = 0) -> Optional[List[ChapterCommit]]:
        """Read chapter commits (read-only). ``None`` means "fall back"."""
        repo_root = self.git_root()
        if repo_root is None:
            return None
        try:
            repo_relative = self._abs(rel).relative_to(repo_root).as_posix()
        except ValueError:
            self.warnings.append("chapter is outside the Git repository: {0}".format(rel))
            return None
        # 1) ordered object ids, rename-following, read-only
        list_args = [
            "-c", "core.quotepath=false",
            "log",
            "--follow",
            "--diff-filter=ACMR",
            "--no-color",
            "--format=%H",
        ]
        if offset:
            list_args.append("--skip={0}".format(max(0, int(offset))))
        if limit:
            list_args.append("-n{0}".format(max(1, int(limit))))
        list_args.extend(["--", repo_relative])
        proc = self._run_git(list_args, repo_root)
        if proc is None:
            return None
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            if "does not exist in" in stderr or "unknown revision" in stderr:
                # Valid repository, just no history for this path yet.
                return []
            if "no such path" in stderr.lower():
                return []
            self.warnings.append("git log failed: {0}".format(stderr.strip()[:160]))
            return None
        object_ids = [
            line.strip()
            for line in (proc.stdout or b"").decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        # 2) one read-only query per commit keeps commit/status pairs exact.
        commits: List[ChapterCommit] = []
        for object_id in object_ids:
            show = self._run_git(
                [
                    "-c", "core.quotepath=false",
                    "-c", "i18n.logOutputEncoding=UTF-8",
                    "show",
                    # ``-s`` cannot be combined with ``--name-status``;
                    # the format line already suppresses the patch body.
                    "--name-status",
                    "-z",
                    "--format=" + _LOG_FORMAT,
                    "--no-color",
                    object_id,
                ],
                repo_root,
            )
            if show is None or show.returncode != 0:
                self.warnings.append("git show failed for {0}".format(object_id[:12]))
                continue
            for item in _pick_entry(parse_git_log_z(show.stdout or b""), repo_relative):
                default = item.get("path") or repo_relative
                path = self._to_content_relative(repo_root, default)
                original = self._to_content_relative(repo_root, item.get("original_path") or "")
                changed = self._to_content_relative(repo_root, item.get("changed_path") or "")
                commits.append(
                    ChapterCommit(
                        version_id=item["version_id"],
                        source=SOURCE_GIT,
                        author=item.get("author", ""),
                        committed_at=item.get("committed_at", ""),
                        subject=item.get("subject", ""),
                        path=path,
                        original_path=original,
                        changed_path=changed or None,
                    )
                )
        return commits

    def _to_content_relative(self, repo_root: Path, repo_relative: str) -> str:
        """Repository-relative path -> content_root-relative path."""
        if not repo_relative:
            return ""
        try:
            return (repo_root / repo_relative).resolve().relative_to(self.content_root).as_posix()
        except (ValueError, OSError):
            return repo_relative.replace("\\", "/")

    def _to_repo_relative(self, repo_root: Path, rel: str) -> str:
        try:
            return (self.content_root / rel).resolve().relative_to(repo_root).as_posix()
        except (ValueError, OSError):
            return ""

    def read_git_version(self, version_id: str, path: str) -> Optional[str]:
        """Read historical text at ``<commit>:<path>``; ``None`` when unavailable."""
        repo_root = self.git_root()
        if repo_root is None or not version_id or not path:
            return None
        repo_relative = self._to_repo_relative(repo_root, path)
        if not repo_relative:
            return None
        proc = self._run_git(
            ["-c", "core.quotepath=false", "show", "{0}:{1}".format(version_id, repo_relative)],
            repo_root,
        )
        if proc is None or proc.returncode != 0:
            return None
        return (proc.stdout or b"").decode("utf-8", errors="replace")

    def local_commits(self, rel: str, *, limit: int = DEFAULT_HISTORY_LIMIT,
                      offset: int = 0) -> List[ChapterCommit]:
        """Read local recovery points (broken index never raises)."""
        try:
            entries = self._local.list_entries(rel)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.warnings.append("local history unreadable: {0}".format(str(exc)[:160]))
            return []
        for message in self._local.warnings:
            if message not in self.warnings:
                self.warnings.append(message)
        window = entries[offset:] if not limit else entries[offset: offset + max(1, limit)]
        result: List[ChapterCommit] = []
        for entry in window:
            result.append(
                ChapterCommit(
                    version_id=entry.snapshot_id,
                    source=SOURCE_LOCAL,
                    author="local record",
                    committed_at=entry.created_at,
                    subject="content before local save ({0})".format(entry.operation),
                    path=entry.rel_path,
                    original_path=entry.rel_path,
                )
            )
        return result

    def read_local_version(self, rel: str, snapshot_id: str) -> Optional[str]:
        try:
            return self._local.preview(rel, snapshot_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.warnings.append("local history read failed: {0}".format(str(exc)[:160]))
            return None

    def collect(self, query) -> ChapterHistory:
        """Chapter history query (Git -> local -> current), never raises."""
        if isinstance(query, str):
            query = HistoryQuery(rel_path=query)
        rel = self._relative(query.rel_path)
        current_text = self._read_disk_text(rel) if rel else ""
        if not rel:
            return ChapterHistory(
                rel_path=str(getattr(query, "rel_path", "") or ""),
                source=SOURCE_CURRENT,
                current_text=current_text,
                note="Chapter path is invalid or outside the content root.",
            )
        commits = self.collect_git_history(rel, limit=query.limit, offset=query.offset)
        source = SOURCE_GIT
        note = ""
        if commits is None:
            source = SOURCE_LOCAL
            note = LOCAL_FALLBACK_NOTICE
            if self.git_root() is None:
                note = "{0} Project is not inside a Git repository.".format(LOCAL_FALLBACK_NOTICE)
            commits = self.local_commits(rel, limit=query.limit, offset=query.offset)
            if not commits:
                return ChapterHistory(
                    rel_path=rel,
                    source=SOURCE_CURRENT,
                    current_text=current_text,
                    note="{0} {1}".format(note, NO_HISTORY_NOTICE),
                    warnings=list(self.warnings),
                )
        elif not commits:
            local = self.local_commits(rel, limit=query.limit, offset=query.offset)
            if local:
                commits = local
                source = SOURCE_LOCAL
                note = "No Git commit for this chapter; fell back to local history."
            else:
                return ChapterHistory(
                    rel_path=rel,
                    source=SOURCE_CURRENT,
                    current_text=current_text,
                    note=NO_HISTORY_NOTICE,
                    warnings=list(self.warnings),
                )
        return ChapterHistory(
            rel_path=rel,
            source=source,
            commits=commits,
            total=len(commits) + int(query.offset or 0),
            truncated=bool(query.limit) and len(commits) >= int(query.limit),
            current_text=current_text,
            note=note,
            warnings=list(self.warnings),
        )

    def read_version(self, rel_path: str, version_id: str,
                     source: str = SOURCE_GIT) -> HistoryVersion:
        """Open a historical chapter text read-only; missing -> unavailable+note."""
        rel = self._relative(rel_path)
        if not rel:
            return HistoryVersion(version_id, source, available=False,
                                  note="Invalid chapter path.")
        if source == SOURCE_LOCAL:
            text = self.read_local_version(rel, version_id)
            if text is None:
                return HistoryVersion(
                    version_id, source, path=rel, available=False,
                    note="Local history record is unreadable (pruned or damaged).",
                )
            return HistoryVersion(version_id, source, text=text, path=rel,
                                  note="Opened a local recovery point read-only.")
        if source == SOURCE_CURRENT:
            return HistoryVersion(version_id, source, text=self._read_disk_text(rel),
                                  path=rel, note=NO_HISTORY_NOTICE)
        commits = self.collect_git_history(rel, limit=DEFAULT_HISTORY_LIMIT)
        if commits is None:
            return HistoryVersion(
                version_id, source, path=rel, available=False,
                note="Git history unavailable or the commit is not reachable.",
            )
        for commit in commits:
            if commit.version_id == version_id:
                lookup = commit.content_path or rel
                text = self.read_git_version(version_id, lookup)
                if text is None:
                    return HistoryVersion(
                        version_id, source, path=lookup, available=False,
                        note="Historical text unavailable (shallow clone or missing path).",
                    )
                return HistoryVersion(version_id, source, text=text, path=lookup)
        return HistoryVersion(
            version_id, source, path=rel, available=False,
            note="Commit is outside the currently readable history range.",
        )

    def compare_current(self, rel_path: str, version_id: str,
                        buffer_text: Optional[str] = None,
                        source: str = SOURCE_GIT) -> BufferComparison:
        """Compare current content (including the unsaved buffer) with a version."""
        rel = self._relative(rel_path)
        disk_text = self._read_disk_text(rel) if rel else ""
        version = self.read_version(rel_path, version_id, source) if rel else HistoryVersion(
            version_id, source, available=False, note="Invalid chapter path."
        )
        buffer = disk_text if buffer_text is None else str(buffer_text)
        return BufferComparison(
            version_id=version_id,
            source=source,
            buffer_changed=buffer != disk_text,
            differs=buffer != version.text,
            disk_differs_from_version=disk_text != version.text,
            buffer_text=buffer,
            version_text=version.text,
            disk_text=disk_text,
            diff_text=render_unified_diff(version.text, buffer),
        )

    def snapshot_current(self, rel_path: str, *, operation: str = "manual") -> Optional[str]:
        """Record current on-disk content as a local recovery point."""
        rel = self._relative(rel_path)
        if not rel:
            return None
        target = self._abs(rel)
        if not target.is_file():
            return None
        try:
            entry = self._local.capture(rel, target.read_bytes(), operation)
        except (OSError, ValueError, PermissionError) as exc:
            self.warnings.append("local history capture failed: {0}".format(str(exc)[:160]))
            return None
        return entry.snapshot_id

    def restore_local_version(self, rel_path: str, snapshot_id: str, writer,
                              *, confirmed: bool = False,
                              expected_sha256: Optional[str] = None):
        """Restore a local recovery point as a **new save** (Git history intact).

        ``writer`` is the existing ``ContentWriter``: unsaved protection, the
        pre-write recovery point and the session change manifest are all reused;
        this module never writes to disk itself.
        """
        rel = self._relative(rel_path)
        if not rel:
            raise ValueError("Invalid chapter path, cannot restore: {0}".format(rel_path))
        if expected_sha256 is None:
            target = self._abs(rel)
            try:
                expected_sha256 = (
                    hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ""
                )
            except OSError:
                expected_sha256 = ""
        return self._local.restore(rel, snapshot_id, writer,
                                   confirmed=confirmed, expected_sha256=expected_sha256)


def chapter_history(
    project_root: Path,
    content_root: Path,
    rel_path: str,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    offset: int = 0,
    state_dir: Optional[Path] = None,
    buffer_text: Optional[str] = None,
) -> ChapterHistory:
    """Convenience wrapper: one chapter history query."""
    service = ChapterHistoryService(project_root, content_root, state_dir)
    return service.collect(HistoryQuery(rel_path=rel_path, limit=limit, offset=offset,
                                        buffer_text=buffer_text))


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "SOURCE_CURRENT",
    "SOURCE_GIT",
    "SOURCE_LOCAL",
    "LOCAL_FALLBACK_NOTICE",
    "NO_HISTORY_NOTICE",
    "BufferComparison",
    "ChapterCommit",
    "ChapterHistory",
    "ChapterHistoryService",
    "HistoryQuery",
    "HistoryVersion",
    "chapter_history",
    "parse_git_log_z",
]