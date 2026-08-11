# -*- coding: utf-8 -*-
"""写入安全：备份、原子写、改动清单与回滚。

所有内容写路径（编辑器保存、全局替换、重命名联动）统一经由本模块：
- 写前把原文件备份为 ``同目录/<文件>.bak``（覆盖式，保留最近一份）。
- 写入用 tmp 文件 + ``os.replace`` 原子替换，跨卷失败回退 ``shutil.move``，
  避免写入中断损坏文件（与 ``ProjectManifest.save`` 同一套路）。
- 会话改动清单落盘到项目 ``.state/``，供一键回滚。

回滚语义：
- ``edit`` 条目：用 ``.bak`` 恢复文件内容。
- ``rename`` 条目：把文件移回原名并恢复内容。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# 备份文件扩展名（追加在原名后，如 3.1.4 居民信息.md.bak）。
BACKUP_SUFFIX = ".bak"

# 会话改动清单文件名（相对项目 .state/ 目录）。
CHANGE_MANIFEST_NAME = "content_changes.json"

# 改动操作类型。
OP_EDIT = "edit"
OP_RENAME = "rename"


class PathOutsideContentError(ValueError):
    """目标路径越出 contentRoot。"""


def _backup_path_for(file_path: Path) -> Path:
    """备份路径：同目录下原名追加 .bak。"""
    return file_path.with_name(file_path.name + BACKUP_SUFFIX)


def _resolve_inside(content_root: Path, rel_path: str) -> Path:
    """把 rel_path 解析为 contentRoot 内绝对路径，越界抛错。"""
    target = (content_root / rel_path).resolve()
    try:
        target.relative_to(content_root.resolve())
    except ValueError:
        raise PathOutsideContentError(
            "目标路径越出内容目录：{0}".format(rel_path)
        )
    return target


def atomic_write(file_path: Path, text: str) -> None:
    """原子写入文本：tmp + os.replace，跨卷回退 shutil.move。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    try:
        os.replace(str(tmp_path), str(file_path))
    except OSError:
        shutil.move(str(tmp_path), str(file_path))


@dataclass
class ChangeEntry:
    """改动清单条目。"""

    operation: str  # OP_EDIT | OP_RENAME
    rel_path: str  # 目标文件（edit 为改动文件；rename 为新路径）
    backup_path: Optional[str] = None  # .bak 绝对路径（edit 必填，rename 可选）
    original_path: Optional[str] = None  # 原名（仅 rename）

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "relPath": self.rel_path,
            "backupPath": self.backup_path,
            "originalPath": self.original_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeEntry":
        return cls(
            operation=str(data.get("operation", OP_EDIT)),
            rel_path=str(data.get("relPath", "")),
            backup_path=data.get("backupPath"),
            original_path=data.get("originalPath"),
        )


@dataclass
class WriteResult:
    """写入结果。"""

    rel_path: str
    backup_path: Optional[str]  # 已创建备份路径（绝对路径）；未变化为 None
    written: bool
    error: Optional[str] = None
    path: str = ""  # 写入后的绝对路径


class ChangeManifest:
    """会话改动清单：JSON 落盘到项目 .state/，供一键回滚。"""

    def __init__(self, state_dir: Path) -> None:
        self._file: Path = Path(state_dir) / CHANGE_MANIFEST_NAME
        self._entries: List[ChangeEntry] = []

    @property
    def file(self) -> Path:
        return self._file

    @property
    def entries(self) -> List[ChangeEntry]:
        return list(self._entries)

    @property
    def empty(self) -> bool:
        return not self._entries

    def load(self) -> None:
        """从磁盘加载；缺失或损坏视为空清单。"""
        self._entries = []
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            items = data.get("entries", []) if isinstance(data, dict) else []
            self._entries = [
                ChangeEntry.from_dict(item) for item in items if isinstance(item, dict)
            ]
        except (json.JSONDecodeError, OSError):
            self._entries = []

    def save(self) -> None:
        """持久化清单到磁盘。"""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {"entries": [entry.to_dict() for entry in self._entries]}
        atomic_write(self._file, json.dumps(data, ensure_ascii=False, indent=2))

    def record(self, entry: ChangeEntry) -> None:
        """追加一条改动记录（去重后按 rel_path + operation 覆盖旧条目）。"""
        self._entries = [
            item
            for item in self._entries
            if not (
                item.operation == entry.operation
                and item.rel_path == entry.rel_path
            )
        ]
        self._entries.append(entry)
        self.save()

    def clear(self) -> None:
        """清空清单（回滚成功后调用）。"""
        self._entries = []
        if self._file.exists():
            try:
                self._file.unlink()
            except OSError:
                pass


class ContentWriter:
    """统一写入口：备份 + 原子写 + 改动清单记录。

    ``content_root`` 为 ``content/`` 目录；``state_dir`` 为项目 ``.state/``。
    每成功写入一个文件，自动记录 edit 条目到清单，便于一键回滚。
    """

    def __init__(self, content_root: Path, state_dir: Path) -> None:
        self._content_root: Path = Path(content_root).resolve()
        self._manifest = ChangeManifest(state_dir)

    @property
    def manifest(self) -> ChangeManifest:
        return self._manifest

    @property
    def content_root(self) -> Path:
        return self._content_root

    def resolve(self, rel_path: str) -> Path:
        """把 rel_path 解析为 contentRoot 内绝对路径（越界抛错）。"""
        return _resolve_inside(self._content_root, rel_path)

    def _backup(self, file_path: Path) -> Optional[str]:
        """写前备份；文件存在才备份，返回备份绝对路径。"""
        if not file_path.exists():
            return None
        backup_path = _backup_path_for(file_path)
        try:
            shutil.copy2(str(file_path), str(backup_path))
        except OSError:
            return None
        return str(backup_path)

    def write_text(self, rel_path: str, text: str) -> WriteResult:
        """写入文件内容（备份 + 原子写 + 记录 edit 条目）。

        写入失败时保留已建备份，返回 error。
        """
        try:
            target = _resolve_inside(self._content_root, rel_path)
        except PathOutsideContentError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        backup = self._backup(target)
        try:
            atomic_write(target, text)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=backup,
                written=False,
                error=str(exc),
            )
        self._manifest.record(
            ChangeEntry(operation=OP_EDIT, rel_path=rel_path, backup_path=backup)
        )
        return WriteResult(
            rel_path=rel_path,
            backup_path=backup,
            written=True,
            path=str(target),
        )

    def rename(self, rel_path: str, new_rel_path: str) -> WriteResult:
        """重命名文件（备份旧内容 + 移动 + 记录 rename 条目）。"""
        try:
            source = _resolve_inside(self._content_root, rel_path)
            target = _resolve_inside(self._content_root, new_rel_path)
        except PathOutsideContentError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        if not source.exists():
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error="源文件不存在：{0}".format(rel_path),
            )
        backup = self._backup(source)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=backup,
                written=False,
                error=str(exc),
            )
        self._manifest.record(
            ChangeEntry(
                operation=OP_RENAME,
                rel_path=new_rel_path,
                backup_path=backup,
                original_path=rel_path,
            )
        )
        return WriteResult(
            rel_path=new_rel_path,
            backup_path=backup,
            written=True,
            path=str(target),
        )

    # --- 回滚 ---

    def rollback(self) -> List[str]:
        """按改动清单反向恢复；返回操作失败的 rel_path 列表。

        成功后清空清单。edit 用备份恢复内容；rename 移回原名并恢复内容。
        """
        self._manifest.load()
        failures: List[str] = []
        for entry in reversed(self._manifest.entries):
            try:
                self._rollback_entry(entry)
            except OSError:
                failures.append(entry.rel_path)
        self._manifest.clear()
        return failures

    def _rollback_entry(self, entry: ChangeEntry) -> None:
        if entry.operation == OP_RENAME:
            current = _resolve_inside(self._content_root, entry.rel_path)
            original = _resolve_inside(self._content_root, entry.original_path)
            if current.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                current.rename(original)
        elif entry.operation == OP_EDIT:
            target = _resolve_inside(self._content_root, entry.rel_path)
            if entry.backup_path and Path(entry.backup_path).exists():
                shutil.copy2(entry.backup_path, str(target))
