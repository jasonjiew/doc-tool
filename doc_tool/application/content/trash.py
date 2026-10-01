"""Independent soft-delete records and explicit, boundary-checked recovery."""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from doc_tool.application.content.changes import render_unified_diff
from doc_tool.application.content.writer import _resolve_inside, atomic_write, atomic_write_bytes


@dataclass
class TrashEntry:
    operation_id: str
    rel_path: str
    deleted_at: str
    kind: str
    trash_path: str


class TrashStore:
    def __init__(self, writer):
        self.writer = writer
        self.root = writer._trash_dir

    def safe(self, path):
        path = Path(path)
        current = path
        while current != self.writer.local_history.project_root and current != current.parent:
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ValueError("回收站路径不能经过链接")
            current = current.parent
        path.resolve().relative_to(self.root.resolve())
        self.root.resolve().relative_to(self.writer.local_history.project_root)
        return path

    def list_entries(self):
        entries = []
        if self.root.exists():
            for metadata in self.root.glob("*/record.json"):
                try:
                    data = json.loads(self.safe(metadata).read_text(encoding="utf-8"))
                    entry = TrashEntry(**data)
                    self.safe(entry.trash_path)
                    root, rel = self.writer._split_root(entry.rel_path)
                    _resolve_inside(root, rel)
                    if Path(entry.trash_path).is_file():
                        entries.append(entry)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        self.writer.manifest.load()
        known = {e.trash_path for e in entries}
        for entry in self.writer.manifest.entries:
            if entry.operation == "delete" and entry.trash_path and entry.trash_path not in known:
                try:
                    path = self.safe(entry.trash_path)
                    if path.is_file():
                        entries.append(TrashEntry("legacy:" + entry.rel_path, entry.rel_path,
                            "未记录", "resource" if entry.rel_path.startswith("assets/") else "content", str(path)))
                except (OSError, ValueError):
                    pass
        return sorted(entries, key=lambda e: e.deleted_at, reverse=True)

    def preview(self, entry):
        raw = self.safe(entry.trash_path).read_bytes()
        return raw.decode("utf-8", errors="replace") if entry.kind == "content" else "资源文件：{0} bytes".format(len(raw))

    def diff(self, entry):
        root, rel = self.writer._split_root(entry.rel_path)
        target = _resolve_inside(root, rel)
        if entry.kind == "resource":
            return "原位置{0}文件；覆盖前会备份当前资源。".format("已有" if target.exists() else "没有")
        return render_unified_diff(target.read_text(encoding="utf-8") if target.exists() else "", self.preview(entry))

    def restore(self, entry, *, mode="copy", confirmed=False, expected_sha256=None):
        if not self.writer._writable:
            raise PermissionError("只读项目不能恢复")
        if not confirmed:
            return None
        if mode not in ("copy", "overwrite"):
            raise ValueError("无效恢复方式")
        source = self.safe(entry.trash_path)
        root, rel = self.writer._split_root(entry.rel_path)
        target = _resolve_inside(root, rel)
        if expected_sha256 is not None:
            import hashlib
            current = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
            if current != expected_sha256:
                raise ValueError("目标已变化，请重新查看差异")
        if target.exists() and mode == "copy":
            base = target
            number = 1
            while target.exists():
                target = _resolve_inside(root, str(base.relative_to(root).with_name(
                    base.stem + "-恢复副本-" + str(number) + base.suffix)))
                number += 1
        raw = source.read_bytes()
        if entry.kind == "content":
            result = self.writer.write_text(target.relative_to(root).as_posix(), raw.decode("utf-8"), operation="restore")
            if not result.written:
                raise OSError(result.error)
        else:
            if target.exists():
                backup = self.safe(source.parent / ("before-overwrite-" + uuid4().hex + ".bin"))
                atomic_write_bytes(backup, target.read_bytes())
                if backup.read_bytes() != target.read_bytes():
                    raise OSError("资源备份校验失败")
            atomic_write_bytes(target, raw)
        # Keep the immutable deletion payload, allowing another copy restoration.
        return ("assets/" if entry.kind == "resource" else "") + target.relative_to(root).as_posix()

    def clean(self, entries, *, confirmed=False):
        if not self.writer._writable:
            raise PermissionError("只读项目不能清理")
        if not confirmed:
            return
        paths = [self.safe(e.trash_path) for e in entries]
        for path in paths:
            path.unlink()

    def prepare(self, rel_path):
        operation_id = uuid4().hex
        target = self.safe(self.root / operation_id / "payload" / rel_path)
        entry = TrashEntry(operation_id, rel_path, datetime.now(timezone.utc).isoformat(),
                           "resource" if rel_path.startswith("assets/") else "content", str(target))
        atomic_write(self.safe(self.root / operation_id / "record.json"), json.dumps(entry.__dict__, ensure_ascii=False))
        return entry
