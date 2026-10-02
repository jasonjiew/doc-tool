# -*- coding: utf-8 -*-
"""首用写作布局：纯数据 + 纯判定，供主窗口摆放 Dock。

设计要点（UI 包 2.2）：

- 默认写作布局以**正文**为主体：章节树保留但收窄，工具面板与空闲的任务/结果
  Dock 收起，预览按需展开；用户主动打开的面板不被普通后台事件关闭。
- 有效旧会话优先：``layout_chosen`` / ``dockVisibility`` / ``dockState`` 任一存在
  即视为用户已有布局偏好，不再套用首用默认。
- 缺失或损坏会话（``has_layout_preference`` 为假）才套用首用默认。
- 「恢复写作布局」只重设显隐与尺寸，不动正文、草稿、标签、滚动与主题。

本模块刻意不含 Qt 依赖，可以在纯服务测试里直接断言默认布局的取值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

#: Dock 对象名（与 main_window 的 QDockWidget.setObjectName 一致）。
DOCK_TASK = "taskDock"
DOCK_TREE = "chapterTreeDock"
DOCK_PANELS = "panelsDock"

#: Dock 中文标题（用于状态栏/提示）。
DOCK_LABELS = {
    DOCK_TASK: "任务 / 结果",
    DOCK_TREE: "章节树",
    DOCK_PANELS: "工具面板",
}


@dataclass(frozen=True)
class DockLayout:
    """一个 Dock 的目标布局：是否可见 + 可选宽度限制。"""

    visible: bool
    minimum_width: Optional[int] = None
    maximum_width: Optional[int] = None


@dataclass(frozen=True)
class WritingLayout:
    """首用写作布局：以正文为主体，工具/任务 Dock 收敛。"""

    docks: Mapping[str, DockLayout]

    @property
    def visibility(self) -> Dict[str, bool]:
        return {name: item.visible for name, item in self.docks.items()}

    def describe_restored(self) -> str:
        shown = [
            DOCK_LABELS.get(name, name) for name, item in self.docks.items() if item.visible
        ]
        hidden = [
            DOCK_LABELS.get(name, name) for name, item in self.docks.items() if not item.visible
        ]
        parts = []
        if shown:
            parts.append("已显示：" + "、".join(shown))
        if hidden:
            parts.append("已收起：" + "、".join(hidden))
        return "已恢复写作布局（正文优先）：" + "；".join(parts) if parts else "已恢复写作布局"


def default_writing_layout() -> WritingLayout:
    """首用默认：章节树可见但收窄；工具面板与空闲任务/结果 Dock 收起。"""
    return WritingLayout(
        docks={
            DOCK_TREE: DockLayout(visible=True, minimum_width=180, maximum_width=240),
            DOCK_TASK: DockLayout(visible=False, minimum_width=230, maximum_width=460),
            DOCK_PANELS: DockLayout(visible=False),
        }
    )


def should_apply_default_layout(session) -> bool:
    """是否对该会话套用首用写作默认布局。

    ``session`` 可为 ``None``（无会话文件）或 ``SessionState``。已有显式布局
    偏好（``has_layout_preference``）时一律优先用户选择。
    """
    if session is None:
        return True
    has_preference = getattr(session, "has_layout_preference", None)
    if callable(has_preference):
        return not bool(has_preference())
    # 兼容旧对象：按字段判定。
    return not bool(
        getattr(session, "layout_chosen", False)
        or getattr(session, "dock_visibility", None)
        or getattr(session, "dock_state", "")
    )


def restored_layout_session_flags() -> Dict[str, object]:
    """显式恢复布局后要写回的会话字段（只影响布局显隐/尺寸）。"""
    return {
        "dock_visibility": default_writing_layout().visibility,
        "layout_chosen": True,
    }


__all__ = [
    "DOCK_LABELS",
    "DOCK_PANELS",
    "DOCK_TASK",
    "DOCK_TREE",
    "DockLayout",
    "WritingLayout",
    "default_writing_layout",
    "restored_layout_session_flags",
    "should_apply_default_layout",
]