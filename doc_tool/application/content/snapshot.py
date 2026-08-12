# -*- coding: utf-8 -*-
"""内容快照基线：识别所有真实变动（含外部编辑），供章节树徽标。

基线在「项目打开」或「清除标记」时记录 content 根下每个 .md 文件的
size + mtime + sha1，之后刷新时对比当前文件 → added / modified / deleted。
不依赖 git/SVN：任何来源的改动（工具写路径、外部编辑器、同事 checkout）
都能被识别，有没有版本控制行为完全一致。

与 ``writer.ChangeManifest`` 分工：
- 本模块只回答「相对基线有什么变动」，驱动徽标。
- 改动清单仍是回滚账本（.bak 恢复、回收站恢复），与徽标解耦，
  只在真正回滚时被消费。

``.bak`` 文件天然排除：基线与对比都用 .md 文件列表（``*.md`` 不匹配
``*.md.bak``），由调用方用 ``ContentIndexService.discover_files()`` 提供。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence

from doc_tool.application.content.writer import (
    OP_RENAME,
    ChangeEntry,
    atomic_write,
)

# 基线文件名（相对项目 .state/ 目录）。
BASELINE_FILE_NAME = "content_baseline.json"

# 基线内容副本目录名（相对项目 .state/ 目录）。改动面板的「基线 vs 当前」
# diff 需要原文，打基线时把每个 .md 复制到该目录。
BASELINE_CONTENT_DIR_NAME = "baseline"


@dataclass(frozen=True)
class FileSnapshot:
    """基线中单个文件的快照记录。"""

    rel_path: str
    size: int
    mtime_ns: int
    sha1: str

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "size": self.size,
            "mtimeNs": self.mtime_ns,
            "sha1": self.sha1,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileSnapshot":
        return cls(
            rel_path=str(data.get("relPath", "")),
            size=int(data.get("size", 0)),
            mtime_ns=int(data.get("mtimeNs", 0)),
            sha1=str(data.get("sha1", "")),
        )


def _sha1_of(file_path: Path) -> str:
    """文件内容 sha1（对比语义：字节级一致才算未变）。"""
    return hashlib.sha1(file_path.read_bytes()).hexdigest()


class ContentSnapshot:
    """内容快照基线：打基线、对比、持久化到项目 .state/。"""

    def __init__(self, state_dir: Path) -> None:
        self._file: Path = Path(state_dir) / BASELINE_FILE_NAME
        self._content_dir: Path = Path(state_dir) / BASELINE_CONTENT_DIR_NAME
        self._entries: Dict[str, FileSnapshot] = {}

    @property
    def file(self) -> Path:
        return self._file

    @property
    def entries(self) -> Dict[str, FileSnapshot]:
        return dict(self._entries)

    def load(self) -> None:
        """从磁盘加载；缺失或损坏视为无基线（下次打开会重新打基线）。"""
        self._entries = {}
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            items = data.get("baseline", []) if isinstance(data, dict) else []
            entries: Dict[str, FileSnapshot] = {}
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                snap = FileSnapshot.from_dict(raw)
                if snap.rel_path:
                    entries[snap.rel_path] = snap
            self._entries = entries
        except (json.JSONDecodeError, OSError):
            self._entries = {}

    def save(self) -> None:
        """持久化基线到磁盘（原子写，与改动清单同套路）。"""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {"baseline": [snap.to_dict() for snap in self._entries.values()]}
        atomic_write(self._file, json.dumps(data, ensure_ascii=False, indent=2))

    def take(self, content_root: Path, files: Sequence[str]) -> None:
        """把当前文件快照记为基线（跳过缺失文件，避免与磁盘瞬时状态竞争）。

        同时把每个文件内容复制到 baseline 目录，供改动面板做「基线 vs 当前」
        diff；单文件复制失败跳过，不阻断打基线。
        """
        content_root = Path(content_root).resolve()
        entries: Dict[str, FileSnapshot] = {}
        for rel_path in files:
            target = content_root / rel_path
            try:
                st = target.stat()
                sha1 = _sha1_of(target)
            except OSError:
                # stat 与读取之间文件被锁/删除：统一跳过，不中断整个打基线。
                continue
            entries[rel_path] = FileSnapshot(
                rel_path=rel_path,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                sha1=sha1,
            )
        self._entries = entries
        self._write_content_copies(content_root, files)

    # --- 基线内容副本 ---

    def _content_copy_path(self, rel_path: str) -> Path:
        return self._content_dir / rel_path

    def _write_content_copies(self, content_root: Path, files: Sequence[str]) -> None:
        """把当前文件内容复制到 baseline 目录（尽力而为，失败跳过）。"""
        content_root = Path(content_root).resolve()
        for rel_path in files:
            src = content_root / rel_path
            dst = self._content_copy_path(rel_path)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            except OSError:
                continue

    def content_of(self, rel_path: str) -> Optional[str]:
        """读基线内容副本；缺失（升级前项目或复制失败）返回 None。"""
        try:
            return self._content_copy_path(rel_path).read_text(encoding="utf-8")
        except OSError:
            return None

    def ensure_baseline_content(self, content_root: Path, files: Sequence[str]) -> None:
        """升级兜底：元数据已有但内容副本缺失的文件补拷当前内容。

        旧项目升级到「基线内容副本」特性后首次打开时调用；副本已存在则跳过。
        """
        content_root = Path(content_root).resolve()
        for rel_path in files:
            if rel_path not in self._entries:
                continue
            if self._content_copy_path(rel_path).exists():
                continue
            src = content_root / rel_path
            dst = self._content_copy_path(rel_path)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            except OSError:
                continue

    def diff(self, content_root: Path, files: Sequence[str]) -> Dict[str, str]:
        """对比当前文件与基线 → {rel_path: added | modified | deleted}。

        快路径：size 与 mtime 均相同视为未变，跳过哈希；否则算 sha1 再比对。
        改回基线内容的文件（mtime 变但 sha1 同）不会误标。基线有而当前缺失
        的文件标 deleted（树中不渲染，与改动清单语义一致）。
        """
        content_root = Path(content_root).resolve()
        current = set(files)
        status: Dict[str, str] = {}
        for rel_path in files:
            base = self._entries.get(rel_path)
            target = content_root / rel_path
            try:
                st = target.stat()
            except OSError:
                continue  # 列表中但瞬时缺失，按未处理跳过
            if (
                base is not None
                and base.size == st.st_size
                and base.mtime_ns == st.st_mtime_ns
            ):
                continue
            try:
                sha1 = _sha1_of(target)
            except OSError:
                continue
            if base is None:
                status[rel_path] = "added"
            elif sha1 != base.sha1:
                status[rel_path] = "modified"
        for rel_path in self._entries:
            if rel_path not in current:
                status[rel_path] = "deleted"
        return status


def overlay_rename_status(
    status: Dict[str, str], entries: Sequence[ChangeEntry]
) -> Dict[str, str]:
    """在快照 diff 上叠加改动清单的 rename：新路径标 modified，旧路径不标。

    快照 diff 把工具内重命名视为「新路径 added + 旧路径 deleted」；叠加清单的
    rename 条目后，重命名收敛为新路径 modified（绿色→黄色），旧路径不再标
    deleted（文件已不存在，且树本就不渲染被删文件）。非 rename 条目忽略；
    新路径不在 diff 中（已重打基线或已被删）时不追加、也不误清其他条目。
    """
    result = dict(status)
    for entry in entries:
        if entry.operation != OP_RENAME:
            continue
        result.pop(entry.original_path, None)
        if entry.rel_path in result:
            result[entry.rel_path] = "modified"
    return result
