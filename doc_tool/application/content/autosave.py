# -*- coding: utf-8 -*-
"""自动草稿存储：未保存编辑内容的安全落盘与恢复。

草稿按 ``rel_path`` 镜像写入项目 ``.state/autosave/`` 目录，每文件仅保留
最近一份（覆盖即替换）。草稿目录位于 contentRoot 之外，内容索引/构建/校验
天然不可见；正式 Markdown 由 ``ContentWriter`` 统一管理，二者严格隔离——
草稿恢复始终经用户显式确认，且恢复后保持未保存状态，不静默覆盖正式内容。

复用 ``atomic_write`` 与 ``_resolve_inside`` 保证原子写与越界防护。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from doc_tool.application.content.writer import (
    _resolve_inside,
    atomic_write,
)

# 草稿目录名（相对项目 .state/ 目录）。
AUTOSAVE_DIR_NAME = "autosave"


class AutoSaveStore:
    """草稿存储：write/clear/clear_all/list_drafts/read。

    越界 ``rel_path``（逃出草稿目录）在写入时抛 ``PathOutsideContentError``；
    ``clear``/``read`` 对越界路径静默不动作（无副作用即安全）。
    """

    def __init__(self, state_dir) -> None:
        self._state_dir: Path = Path(state_dir).resolve()
        self._drafts_dir: Path = self._state_dir / AUTOSAVE_DIR_NAME

    @property
    def drafts_dir(self) -> Path:
        return self._drafts_dir

    def write(self, rel_path: str, text: str) -> None:
        """原子写入草稿（覆盖即只保留最近一份）；越界拒绝。"""
        target = _resolve_inside(self._drafts_dir, rel_path)
        atomic_write(target, text)

    def clear(self, rel_path: str) -> Optional[str]:
        """删除某文件草稿；越界或不存在静默成功。

        Returns:
            None 成功；删除失败（文件被占用/权限）返回错误文本——调用方
            （退出/切换「不保存」、关闭脏标签等）据此提示，避免草稿残留导致
            下次打开误弹「恢复自草稿」。
        """
        try:
            target = _resolve_inside(self._drafts_dir, rel_path)
        except ValueError:
            return None
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            return "无法清除草稿 {0}: {1}".format(rel_path, exc)
        return None

    def clear_all(self) -> List[str]:
        """清空全部草稿（目录保留）；返回清除失败的 rel_path 列表。"""
        if not self._drafts_dir.is_dir():
            return []
        failed: List[str] = []
        for child in self._drafts_dir.rglob("*"):
            if child.is_file():
                try:
                    child.unlink(missing_ok=True)
                except OSError:
                    failed.append(child.relative_to(self._drafts_dir).as_posix())
        return failed

    def list_drafts(self) -> List[str]:
        """返回现有草稿的 rel_path 列表（POSIX 分隔、按路径排序）。"""
        if not self._drafts_dir.is_dir():
            return []
        rels = []
        for path in sorted(self._drafts_dir.rglob("*")):
            if path.is_file():
                rels.append(path.relative_to(self._drafts_dir).as_posix())
        return rels

    def read(self, rel_path: str) -> Optional[str]:
        """读取草稿内容；不存在返回 None，越界返回 None。"""
        try:
            target = _resolve_inside(self._drafts_dir, rel_path)
        except ValueError:
            return None
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    def has(self, rel_path: str) -> bool:
        """是否存在该文件的草稿。"""
        return self.read(rel_path) is not None
