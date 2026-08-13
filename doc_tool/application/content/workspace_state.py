# -*- coding: utf-8 -*-
"""工作区会话状态：Dock 布局/主题/打开标签/当前文件/预览/滚动位置的持久化。

纯模型 ``SessionState`` + 原子读写 ``WorkspaceStateStore``，存放于项目
``.state/workspace.json``，沿用 ``ChangeManifest`` 的 JSON 原子写套路
（``atomic_write``）。缺失/损坏回退为默认会话；无会话数据时不生成空文件，
避免状态目录残留无意义数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from doc_tool.application.content.writer import atomic_write

# 会话状态文件名（相对项目 .state/ 目录）。
WORKSPACE_STATE_NAME = "workspace.json"

DEFAULT_THEME = "light"


@dataclass
class SessionState:
    """一次工作区会话的完整状态快照。"""

    dock_visibility: Dict[str, bool] = field(default_factory=dict)
    dock_state: str = ""  # QMainWindow.saveState() base64（Dock 排列）
    theme: str = DEFAULT_THEME
    open_tabs: List[str] = field(default_factory=list)
    current_file: Optional[str] = None
    preview_enabled: Dict[str, bool] = field(default_factory=dict)
    scroll_positions: Dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """无会话数据 → 不写空文件。

        主题 / Dock 布局 / Dock 显隐是用户自定义的持久化状态，即使没有打开
        任何标签也不能在保存时被丢弃；只有全部字段都为空（或默认）时才视为
        ``empty``，允许清理陈旧文件。
        """
        return (
            not self.open_tabs
            and self.current_file is None
            and not self.dock_visibility
            and not self.dock_state
            and self.theme == DEFAULT_THEME
            and not self.preview_enabled
            and not self.scroll_positions
        )

    def to_dict(self) -> dict:
        return {
            "dockVisibility": self.dock_visibility,
            "dockState": self.dock_state,
            "theme": self.theme,
            "openTabs": self.open_tabs,
            "currentFile": self.current_file,
            "previewEnabled": self.preview_enabled,
            "scrollPositions": self.scroll_positions,
        }

    @classmethod
    def from_dict(cls, data) -> "SessionState":
        """从字典构造；缺键/错型字段安全回退默认。"""
        if not isinstance(data, dict):
            return cls()
        return cls(
            dock_visibility=_str_bool_dict(data.get("dockVisibility")),
            dock_state=str(data.get("dockState") or ""),
            theme=str(data.get("theme") or DEFAULT_THEME),
            open_tabs=_str_list(data.get("openTabs")),
            current_file=_opt_str(data.get("currentFile")),
            preview_enabled=_str_bool_dict(data.get("previewEnabled")),
            scroll_positions=_str_int_dict(data.get("scrollPositions")),
        )


class WorkspaceStateStore:
    """会话状态的 JSON 原子读写。"""

    def __init__(self, state_dir) -> None:
        self._file: Path = Path(state_dir) / WORKSPACE_STATE_NAME

    @property
    def file(self) -> Path:
        return self._file

    def load(self) -> SessionState:
        """从磁盘读取会话；缺失/损坏回退默认。"""
        if not self._file.exists():
            return SessionState()
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return SessionState.from_dict(data)
        except (json.JSONDecodeError, OSError, UnicodeError):
            return SessionState()

    def save(self, session: SessionState) -> None:
        """原子写会话；无会话数据时不生成文件（并清理陈旧文件）。"""
        if session.empty:
            self._discard()
            return
        self._file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self._file,
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
        )

    def _discard(self) -> None:
        try:
            self._file.unlink(missing_ok=True)
        except OSError:
            pass


def _str_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _opt_str(value) -> Optional[str]:
    return str(value) if isinstance(value, str) and value else None


def _str_bool_dict(value) -> Dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): bool(val) for key, val in value.items() if isinstance(val, bool)
    }


def _str_int_dict(value) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, val in value.items():
        if isinstance(val, int):
            result[str(key)] = val
    return result
