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
from typing import Iterable, List, Optional, Tuple

# 备份文件扩展名（追加在原名后，如 3.1.4 居民信息.md.bak）。
BACKUP_SUFFIX = ".bak"

# 会话改动清单文件名（相对项目 .state/ 目录）。
CHANGE_MANIFEST_NAME = "content_changes.json"

# 改动操作类型。
OP_EDIT = "edit"
OP_RENAME = "rename"

# 改动操作类型（create 为新增文件；delete 为移入回收站的软删除）。
OP_CREATE = "create"
OP_DELETE = "delete"

# 回收站目录名（相对项目 .state/ 目录）。
TRASH_DIR_NAME = "trash"

# 资源文件在改动清单中的 rel_path 前缀：内容与资源共用回收站语义，用前缀区分根。
ASSET_PREFIX = "assets/"


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

    operation: str  # OP_EDIT | OP_RENAME | OP_CREATE | OP_DELETE
    rel_path: str  # edit 为改动文件；rename 为新路径；delete 为原路径
    backup_path: Optional[str] = None  # .bak 绝对路径（edit 必填，rename 可选）
    original_path: Optional[str] = None  # 原名（仅 rename）
    trash_path: Optional[str] = None  # 回收站内绝对路径（仅 delete）

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "relPath": self.rel_path,
            "backupPath": self.backup_path,
            "originalPath": self.original_path,
            "trashPath": self.trash_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeEntry":
        return cls(
            operation=str(data.get("operation", OP_EDIT)),
            rel_path=str(data.get("relPath", "")),
            backup_path=data.get("backupPath"),
            original_path=data.get("originalPath"),
            trash_path=data.get("trashPath"),
        )


@dataclass
class WriteResult:
    """写入结果。"""

    rel_path: str
    backup_path: Optional[str]  # 已创建备份路径（绝对路径）；未变化为 None
    written: bool
    error: Optional[str] = None
    backup_failed: bool = False  # 预期建立备份但失败（回滚不可用）
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

    def drop(self, operation: str, rel_path: str) -> None:
        """移除与 operation + rel_path 匹配的条目（单文件回滚后取消改动标记）。"""
        kept = [
            item
            for item in self._entries
            if not (item.operation == operation and item.rel_path == rel_path)
        ]
        if len(kept) != len(self._entries):
            self._entries = kept
            self.save()

    def entry_count(self) -> int:
        """返回当前清单条目数（从磁盘加载，保证新鲜）。

        供面板捕获「操作前」条目序号，实现按批次的定向回滚。
        """
        self.load()
        return len(self._entries)

    def keys(self) -> set:
        """返回当前清单的 (operation, rel_path) 键集合（从磁盘加载）。

        供批量操作（如重导入）捕获操作前键集合，配合 ``rollback_keys``
        实现不受位置影响（去重会移动同键条目）的整次回滚。
        """
        self.load()
        return {(entry.operation, entry.rel_path) for entry in self._entries}

    def truncate(self, keep: int) -> None:
        """仅保留前 keep 条条目（面板「回滚本次操作」定向回滚后调用）。"""
        keep = max(0, int(keep))
        if len(self._entries) <= keep:
            return
        self._entries = self._entries[:keep]
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

    def __init__(
        self,
        content_root: Path,
        state_dir: Path,
        assets_root: Optional[Path] = None,
    ) -> None:
        self._content_root: Path = Path(content_root).resolve()
        self._manifest = ChangeManifest(state_dir)
        self._trash_dir: Path = Path(state_dir).resolve() / TRASH_DIR_NAME
        self._assets_root: Optional[Path] = (
            Path(assets_root).resolve() if assets_root is not None else None
        )

    @property
    def manifest(self) -> ChangeManifest:
        return self._manifest

    @property
    def content_root(self) -> Path:
        return self._content_root

    @property
    def assets_root(self) -> Optional[Path]:
        return self._assets_root

    def resolve(self, rel_path: str) -> Path:
        """把 rel_path 解析为 contentRoot 内绝对路径（越界抛错）。"""
        return _resolve_inside(self._content_root, rel_path)

    def _split_root(self, rel_path: str):
        """按 ``assets/`` 前缀判定目标根：返回 (root, inner_rel)。

        - ``assets/requirement/images/img_0001.png`` → (assets_root, inner)
        - 其它 → (content_root, rel_path)

        用于删除/回滚把内容文件与资源文件各自解析到正确根目录。
        """
        if rel_path.startswith(ASSET_PREFIX):
            if self._assets_root is None:
                raise PathOutsideContentError(
                    "未配置资源目录：{0}".format(rel_path)
                )
            return self._assets_root, rel_path[len(ASSET_PREFIX):]
        return self._content_root, rel_path

    def _backup(self, file_path: Path) -> Tuple[Optional[str], bool]:
        """写前备份。

        Returns:
            (备份绝对路径, 是否预期备份但失败)。文件不存在时无需备份 →
            ``(None, False)``；复制失败 → ``(None, True)``（回滚不可用）。
        """
        if not file_path.exists():
            return None, False
        backup_path = _backup_path_for(file_path)
        try:
            shutil.copy2(str(file_path), str(backup_path))
        except OSError:
            return None, True
        return str(backup_path), False

    def _record_change(self, entry: ChangeEntry) -> Optional[str]:
        """记录改动清单；清单保存失败返回错误文本（不阻断内容写入）。

        清单只是会话回滚记账：内容写入已成功时，清单落盘失败不应让写入
        路径抛异常（否则编辑器保存槽会崩溃、文件已改但界面显示未保存）。
        """
        try:
            self._manifest.record(entry)
            return None
        except OSError as exc:
            return "改动清单保存失败（回滚记录不可用）：{0}".format(exc)

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
        backup, backup_failed = self._backup(target)
        try:
            atomic_write(target, text)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=backup,
                written=False,
                error=str(exc),
                backup_failed=backup_failed,
            )
        manifest_error = self._record_change(
            ChangeEntry(operation=OP_EDIT, rel_path=rel_path, backup_path=backup)
        )
        return WriteResult(
            rel_path=rel_path,
            backup_path=backup,
            written=True,
            error=manifest_error,
            backup_failed=backup_failed,
            path=str(target),
        )

    def rename(
        self, rel_path: str, new_rel_path: str, *, create_backup: bool = True
    ) -> WriteResult:
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
        if target.exists() and target != source:
            return WriteResult(
                rel_path=new_rel_path,
                backup_path=None,
                written=False,
                error="目标已存在：{0}".format(new_rel_path),
            )
        backup, backup_failed = (
            self._backup(source) if create_backup else (None, False)
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=backup,
                written=False,
                error=str(exc),
                backup_failed=backup_failed,
            )
        manifest_error = self._record_change(
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
            error=manifest_error,
            backup_failed=backup_failed,
            path=str(target),
        )

    def create_file(self, rel_path: str, text: str) -> WriteResult:
        """新建内容文件（越界/已存在检查 → 原子写 → 记 create 条目）。"""
        try:
            target = _resolve_inside(self._content_root, rel_path)
        except PathOutsideContentError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        if target.exists():
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error="目标已存在：{0}".format(rel_path),
            )
        try:
            atomic_write(target, text)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        manifest_error = self._record_change(
            ChangeEntry(operation=OP_CREATE, rel_path=rel_path)
        )
        return WriteResult(
            rel_path=rel_path,
            backup_path=None,
            written=True,
            error=manifest_error,
            path=str(target),
        )

    def delete_file(self, rel_path: str) -> WriteResult:
        """软删除：移动文件到 <state_dir>/trash/<rel_path> 并记 delete 条目。

        回收站镜像相对结构防同名冲突；文件移出 contentRoot 后构建/校验
        天然跳过。回滚经 trash_path 恢复。``assets/`` 前缀的 rel_path 解析到
        资源目录（资源清理同样走回收站语义，可回滚）。
        """
        try:
            root, inner = self._split_root(rel_path)
            source = _resolve_inside(root, inner)
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
                error="源文件不存在：{0}".format(inner),
            )
        trash_target = self._trash_dir / rel_path
        try:
            trash_target.parent.mkdir(parents=True, exist_ok=True)
            if trash_target.exists():
                # 上次软删除未回滚时槽位已被占用：先清掉旧回收站副本，
                # 保证"删除→重建→再删除"等重复删除能成功而非静默失败。
                trash_target.unlink()
            source.rename(trash_target)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        manifest_error = self._record_change(
            ChangeEntry(
                operation=OP_DELETE,
                rel_path=rel_path,
                trash_path=str(trash_target),
            )
        )
        return WriteResult(
            rel_path=rel_path,
            backup_path=None,
            written=True,
            error=manifest_error,
            path=str(trash_target),
        )

    def delete_asset(self, rel_path: str) -> WriteResult:
        """软删除资源文件（``rel_path`` 相对 assetsRoot）到回收站，可回滚。"""
        return self.delete_file(ASSET_PREFIX + rel_path)

    # --- 回滚 ---

    def rollback(self, since: Optional[int] = None) -> List[str]:
        """按改动清单反向恢复；返回操作失败的 rel_path 列表。

        ``since`` 为回滚起点条目序号：None 回滚全部会话条目；传面板在操作
        前捕获的条目序号则只回滚该序号之后新增的条目，避免把同会话更早的
        编辑/保存一并回滚。成功后清空/截断清单，并丢弃对应 .bak，避免备份
        残留在 contentRoot 阻断构建。
        """
        self._manifest.load()
        entries = self._manifest.entries
        scope = entries if since is None else entries[since:]
        failures: List[str] = []
        succeeded: List[ChangeEntry] = []
        for entry in reversed(scope):
            try:
                self._rollback_entry(entry)
                succeeded.append(entry)
            except (OSError, PathOutsideContentError):
                # 越界/不可恢复条目计入失败并继续，不回滚全部中断。
                failures.append(entry.rel_path)
        if failures:
            # 部分回滚失败：只移除成功条目，失败条目保留在清单中，供再次
            # 回滚或改动面板恢复，避免失败后仍清空清单而丢失恢复线索。
            for entry in succeeded:
                self._manifest.drop(entry.operation, entry.rel_path)
        elif since is None:
            self._manifest.clear()
        else:
            self._manifest.truncate(since)
        return failures

    def rollback_keys(self, keys: Iterable[Tuple[str, str]]) -> List[str]:
        """按 (operation, rel_path) 键集合回滚对应清单条目，返回失败路径列表。

        位置序号 ``since`` 回滚在 ``record`` 去重（同键旧条目移到末尾）时会漏掉
        批量操作重写的既有条目；本方法按键匹配，供重导入等批量操作做整次回滚。
        成功条目从清单移除，失败条目保留供再次回滚。
        """
        target = set(keys)
        self._manifest.load()
        entries = self._manifest.entries
        scoped = [entry for entry in entries if (entry.operation, entry.rel_path) in target]
        failures: List[str] = []
        succeeded: List[ChangeEntry] = []
        for entry in reversed(scoped):
            try:
                self._rollback_entry(entry)
                succeeded.append(entry)
            except (OSError, PathOutsideContentError):
                failures.append(entry.rel_path)
        for entry in succeeded:
            self._manifest.drop(entry.operation, entry.rel_path)
        return failures

    def restore_file(
        self,
        rel_path: str,
        *,
        status: str,
        baseline_text: Optional[str] = None,
        trash_path: Optional[str] = None,
    ) -> WriteResult:
        """按状态恢复单个文件（改动面板的单文件恢复）。

        - ``added``   → 删除该文件并移除 create 条目（撤销新增）。
        - ``deleted`` → 从回收站移回并移除 delete 条目（恢复删除）。
        - ``modified``→ 写回基线内容并移除 edit 条目、清理 .bak（恢复到基线；
          rename 的 modified 不接受本调用，走全局回滚）。

        成功后改动清单相应条目被移除；失败返回 ``written=False`` + error。
        """
        try:
            root, inner = self._split_root(rel_path)
            target = _resolve_inside(root, inner)
        except PathOutsideContentError as exc:
            return WriteResult(
                rel_path=rel_path, backup_path=None, written=False, error=str(exc)
            )

        if status == "added":
            if target.exists():
                try:
                    target.unlink()
                except OSError as exc:
                    return WriteResult(
                        rel_path=rel_path,
                        backup_path=None,
                        written=False,
                        error=str(exc),
                    )
            self._manifest.load()
            self._manifest.drop(OP_CREATE, rel_path)
            return WriteResult(
                rel_path=rel_path, backup_path=None, written=True, path=str(target)
            )

        if status == "deleted":
            if trash_path and Path(trash_path).exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    Path(trash_path).rename(target)
                except OSError as exc:
                    return WriteResult(
                        rel_path=rel_path,
                        backup_path=None,
                        written=False,
                        error=str(exc),
                    )
            elif not target.exists():
                return WriteResult(
                    rel_path=rel_path,
                    backup_path=None,
                    written=False,
                    error="回收站文件不存在：{0}".format(rel_path),
                )
            else:
                # 回收站副本缺失但目标文件仍存在：无法安全判定来源。报告失败
                # 并保留 delete 条目，而不是静默「成功」却什么都没恢复。
                return WriteResult(
                    rel_path=rel_path,
                    backup_path=None,
                    written=False,
                    error=(
                        "回收站文件不存在但目标文件仍存在，无法安全恢复：{0}".format(rel_path)
                    ),
                )
            self._manifest.load()
            self._manifest.drop(OP_DELETE, rel_path)
            return WriteResult(
                rel_path=rel_path, backup_path=None, written=True, path=str(target)
            )

        if status == "modified":
            if baseline_text is None:
                return WriteResult(
                    rel_path=rel_path,
                    backup_path=None,
                    written=False,
                    error="缺少基线内容，无法恢复到基线。",
                )
            try:
                atomic_write(target, baseline_text)
            except OSError as exc:
                return WriteResult(
                    rel_path=rel_path,
                    backup_path=None,
                    written=False,
                    error=str(exc),
                )
            self._manifest.load()
            self._manifest.drop(OP_EDIT, rel_path)
            self._discard_backup(_backup_path_for(target))
            return WriteResult(
                rel_path=rel_path, backup_path=None, written=True, path=str(target)
            )

        return WriteResult(
            rel_path=rel_path,
            backup_path=None,
            written=False,
            error="未知状态：{0}".format(status),
        )

    @staticmethod
    def _discard_backup(backup_path: Optional[str]) -> None:
        """回滚后丢弃备份文件（尽力而为，删除失败不阻断回滚）。"""
        if not backup_path:
            return
        try:
            Path(backup_path).unlink(missing_ok=True)
        except OSError:
            pass

    def _rollback_entry(self, entry: ChangeEntry) -> None:
        if entry.operation == OP_RENAME:
            current = _resolve_inside(self._content_root, entry.rel_path)
            original = _resolve_inside(self._content_root, entry.original_path)
            if current.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                current.rename(original)
                self._discard_backup(entry.backup_path)
            elif entry.backup_path and Path(entry.backup_path).exists():
                # 新名文件已不存在（被外部删除/崩溃）：从备份恢复原内容，
                # 避免回滚后只丢弃备份、原文件彻底丢失。
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry.backup_path, str(original))
                self._discard_backup(entry.backup_path)
            else:
                raise OSError(
                    "重命名回滚失败：新文件与备份均不可用：{0}".format(entry.rel_path)
                )
        elif entry.operation == OP_EDIT:
            target = _resolve_inside(self._content_root, entry.rel_path)
            if entry.backup_path and Path(entry.backup_path).exists():
                shutil.copy2(entry.backup_path, str(target))
                self._discard_backup(entry.backup_path)
            elif entry.backup_path:
                # 清单声明了备份但文件缺失：无法恢复，报告失败而非静默成功。
                raise OSError(
                    "编辑回滚失败：备份文件缺失：{0}".format(entry.backup_path)
                )
            # backup_path 为空（写入时原文件不存在）时无可恢复内容，静默成功。
        elif entry.operation == OP_CREATE:
            target = _resolve_inside(self._content_root, entry.rel_path)
            if target.exists():
                target.unlink()
        elif entry.operation == OP_DELETE:
            root, inner = self._split_root(entry.rel_path)
            target = _resolve_inside(root, inner)
            if entry.trash_path and Path(entry.trash_path).exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                Path(entry.trash_path).rename(target)
