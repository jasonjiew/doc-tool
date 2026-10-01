"""Bounded chapter recovery points; metadata is recoverable without the index."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from doc_tool.application.content.changes import render_unified_diff
from doc_tool.application.content.writer import (
    PathOutsideContentError, _resolve_inside, atomic_write, atomic_write_bytes,
)


@dataclass(frozen=True)
class LocalHistoryEntry:
    snapshot_id: str
    rel_path: str
    created_at: str
    sha256: str
    size_bytes: int
    operation: str


class LocalHistoryStore:
    def __init__(self, content_root: Path, state_dir: Path, *, writable=True,
                 max_entries=20, max_bytes=50 * 1024 * 1024):
        self.content_root = Path(content_root).resolve()
        self.project_root = Path(state_dir).absolute().parent.resolve()
        self.root = Path(state_dir).absolute() / "local_history"
        self.writable = writable
        self.max_entries = max(1, max_entries)
        self.max_bytes = max(1, max_bytes)
        self.warnings = []

    def _inside(self, path: Path) -> Path:
        for candidate in (path, *path.parents):
            if candidate == self.project_root:
                break
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                raise PathOutsideContentError("历史路径含链接，拒绝访问：{0}".format(candidate))
        resolved = path.resolve()
        try:
            resolved.relative_to(self.project_root)
            resolved.relative_to(self.root.resolve())
            self.root.resolve().relative_to(self.project_root)
        except ValueError as exc:
            raise PathOutsideContentError("历史路径越出项目：{0}".format(path)) from exc
        return resolved

    def _relative(self, rel_path: str) -> str:
        if not rel_path or Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
            raise PathOutsideContentError("非法正文路径：{0}".format(rel_path))
        target = _resolve_inside(self.content_root, rel_path)
        return target.relative_to(self.content_root).as_posix()

    def _folder(self, rel_path: str) -> Path:
        rel = self._relative(rel_path)
        # Windows treats case variants as the same chapter.
        import os
        key = hashlib.sha256(os.path.normcase(rel).encode("utf-8")).hexdigest()
        return self._inside(self.root / key)

    def _snapshot_folder(self, rel_path: str, snapshot_id: str) -> Path:
        if not re.fullmatch(r"[0-9TZ]+-[0-9a-f]{32}", snapshot_id):
            raise ValueError("非法历史标识")
        return self._inside(self._folder(rel_path) / snapshot_id)

    def _require_writable(self):
        if not self.writable:
            raise PermissionError("只读项目不能写入或恢复历史")

    def capture(self, rel_path: str, data: bytes, operation="save") -> LocalHistoryEntry:
        self._require_writable()
        rel = self._relative(rel_path)
        now = datetime.now(timezone.utc)
        entry = LocalHistoryEntry(now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex,
                                  rel, now.isoformat(), hashlib.sha256(data).hexdigest(),
                                  len(data), operation)
        folder = self._snapshot_folder(rel, entry.snapshot_id)
        folder.mkdir(parents=True)
        atomic_write_bytes(self._inside(folder / "content.md"), data)
        atomic_write(self._inside(folder / "metadata.json"),
                     json.dumps({"schemaVersion": 1, **asdict(entry)}, ensure_ascii=False, indent=2))
        if self.read_bytes(rel, entry.snapshot_id) != data:
            raise OSError("历史快照回读校验失败")
        try:
            self.rebuild_index(rel)
        except (OSError, ValueError) as exc:
            self.warnings.append("历史索引写入失败，快照已保留，可重建：{0}".format(exc))
        if entry.size_bytes > self.max_bytes:
            self.warnings.append("必要恢复点超过历史体积上限，已保留：{0} bytes".format(entry.size_bytes))
        return entry

    def _load_entry(self, rel_path: str, folder: Path) -> LocalHistoryEntry:
        data = json.loads(self._inside(folder / "metadata.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schemaVersion") != 1:
            raise ValueError("不支持的历史元数据")
        entry = LocalHistoryEntry(**{key: data[key] for key in LocalHistoryEntry.__dataclass_fields__})
        if (entry.rel_path != self._relative(rel_path) or entry.snapshot_id != folder.name
                or not isinstance(entry.size_bytes, int) or entry.size_bytes < 0
                or not isinstance(entry.created_at, str) or not isinstance(entry.operation, str)):
            raise ValueError("历史元数据与正文路径不一致")
        self._snapshot_folder(rel_path, entry.snapshot_id)
        content = self._inside(folder / "content.md").read_bytes()
        if len(content) != entry.size_bytes or hashlib.sha256(content).hexdigest() != entry.sha256:
            raise ValueError("历史内容损坏")
        return entry

    def list_entries(self, rel_path: str, *, include_backup=True):
        """Read-only discovery; a broken index never hides valid metadata."""
        folder = self._folder(rel_path)
        entries = []
        if folder.exists():
            index = self._inside(folder / "index.json")
            if index.exists():
                try:
                    data = json.loads(index.read_text(encoding="utf-8"))
                    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or not isinstance(data.get("entries"), list):
                        raise ValueError("索引格式无效")
                except (OSError, ValueError) as exc:
                    self.warnings.append("历史索引损坏，已从快照读取：{0}".format(exc))
            for item in folder.iterdir():
                if not item.is_dir():
                    continue
                try:
                    entries.append(self._load_entry(rel_path, item))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.warnings.append("不可读取历史项 {0}：{1}".format(item.name, exc))
        if include_backup:
            try:
                target = _resolve_inside(self.content_root, self._relative(rel_path))
                backup = _resolve_inside(self.content_root, self._relative(rel_path) + ".bak")
                if backup.is_file():
                    raw = backup.read_bytes()
                    entries.append(LocalHistoryEntry("legacy-bak", target.relative_to(self.content_root).as_posix(),
                        datetime.fromtimestamp(backup.stat().st_mtime, timezone.utc).isoformat(),
                        hashlib.sha256(raw).hexdigest(), len(raw), "legacy-backup"))
            except (OSError, ValueError) as exc:
                self.warnings.append("兼容备份不可读取，其他历史仍可查看：{0}".format(exc))
        return sorted(entries, key=lambda e: (e.created_at, e.snapshot_id), reverse=True)

    def read_bytes(self, rel_path: str, snapshot_id: str) -> bytes:
        if snapshot_id == "legacy-bak":
            path = _resolve_inside(self.content_root, self._relative(rel_path) + ".bak")
        else:
            folder = self._snapshot_folder(rel_path, snapshot_id)
            self._load_entry(rel_path, folder)
            path = self._inside(folder / "content.md")
        return path.read_bytes()

    def preview(self, rel_path: str, snapshot_id: str) -> str:
        return self.read_bytes(rel_path, snapshot_id).decode("utf-8")

    def diff(self, rel_path: str, snapshot_id: str, newer_id=None) -> str:
        old = self.preview(rel_path, snapshot_id)
        new = (self.preview(rel_path, newer_id) if newer_id else
               _resolve_inside(self.content_root, self._relative(rel_path)).read_text(encoding="utf-8"))
        return render_unified_diff(old, new)

    def rebuild_index(self, rel_path: str):
        self._require_writable()
        entries = self.list_entries(rel_path, include_backup=False)
        folder = self._folder(rel_path)
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write(self._inside(folder / "index.json"), json.dumps(
            {"schemaVersion": 1, "entries": [asdict(e) for e in entries]}, ensure_ascii=False, indent=2))

    def prune(self, rel_path: str, *, protected=()):
        """Called only after successful writes; keep newest and latest pre-restore point."""
        self._require_writable()
        entries = self.list_entries(rel_path, include_backup=False)
        if not entries:
            return
        keep = set(protected) | {entries[0].snapshot_id}
        restore = next((e for e in entries if e.operation == "restore"), None)
        if restore:
            keep.add(restore.snapshot_id)
        remaining = list(entries)
        size = sum(e.size_bytes for e in remaining)
        for entry in reversed(entries):
            if len(remaining) <= self.max_entries and size <= self.max_bytes:
                break
            if entry.snapshot_id in keep:
                continue
            folder = self._snapshot_folder(rel_path, entry.snapshot_id)
            # Resolve every child before recursive removal; never follow a malicious link.
            for child in folder.rglob("*"):
                self._inside(child)
                if child.is_symlink():
                    raise PathOutsideContentError("历史项含符号链接，拒绝清理")
            shutil.rmtree(folder)
            remaining.remove(entry)
            size -= entry.size_bytes
        if len(remaining) > self.max_entries or size > self.max_bytes:
            self.warnings.append("必要恢复点保留，历史暂时超过配额：{0} bytes".format(size))
        self.rebuild_index(rel_path)

    def restore(self, rel_path: str, snapshot_id: str, writer, *, confirmed=False,
                expected_sha256=None):
        self._require_writable()
        if not confirmed:
            return None
        if writer.content_root != self.content_root or writer.local_history.root != self.root:
            raise ValueError("历史与写入器不属于同一项目")
        target = _resolve_inside(self.content_root, self._relative(rel_path))
        if expected_sha256 is not None:
            actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
            if actual != expected_sha256:
                raise ValueError("正文已变化，请刷新差异后恢复")
        # Read the selected legacy backup before write_text refreshes .bak.
        text = self.preview(rel_path, snapshot_id)
        return writer.write_text(rel_path, text, operation="restore")
