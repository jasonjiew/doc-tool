# -*- coding: utf-8 -*-
"""位置后退/前进历史（UI2-C 3.2）：只记录导航位置，不保存正文。

规则（与验收 U2-3 一致）：

- 主动导航（章节树、标签选择、搜索结果、问题、资料来源）产生一条记录，
  保存相对路径、光标、滚动与来源说明；
- 相邻重复位置合并（同一文件且光标接近），连续同位置不刷屏；
- 最多 50 条；新导航清空前进支路；
- 重放（后退/前进）带抑制标记，不二次入栈；
- 跨项目隔离：项目身份变化即清空。

本模块**不保存也不回放正文**，只还原位置；脏 EditorPanel 由原保存/撤销逻辑负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

#: 会话内最多保留的位置数。
MAX_HISTORY = 50
#: 同一文件内光标差异不超过该值视为同一位置（合并用）。
MERGE_CURSOR_TOLERANCE = 3


@dataclass
class NavLocation:
    """一个可还原的位置。"""

    rel_path: str
    cursor: int = 0
    scroll: int = 0
    source: str = ""
    project_root: str = ""

    def same_place(self, other: "NavLocation") -> bool:
        return (
            self.rel_path == other.rel_path
            and abs(int(self.cursor) - int(other.cursor)) <= MERGE_CURSOR_TOLERANCE
        )

    def describe(self) -> str:
        return "{0}（{1}）".format(self.rel_path or "（无文件）", self.source or "导航")


class NavigationHistory:
    """按项目隔离的后退/前进栈。"""

    def __init__(self, project_root: str = "", limit: int = MAX_HISTORY) -> None:
        self._limit = max(1, int(limit))
        self._project_root = str(project_root or "")
        self._entries: List[NavLocation] = []
        self._index = -1
        #: 期望中的下一次到达（重放目标）。只有到达该位置才跳过入栈；
        #: 其它位置视为新的主动导航（避免一次重放把后续导航全部吃掉）。
        self._pending: Optional[NavLocation] = None
        self._suppressed = 0

    # --- 查询 ---

    @property
    def project_root(self) -> str:
        return self._project_root

    def entries(self) -> List[NavLocation]:
        return list(self._entries)

    def current(self) -> Optional[NavLocation]:
        if 0 <= self._index < len(self._entries):
            return self._entries[self._index]
        return None

    def can_back(self) -> bool:
        return self._index > 0

    def can_forward(self) -> bool:
        return 0 <= self._index < len(self._entries) - 1

    # --- 写入 ---

    def set_project(self, project_root: str) -> bool:
        """切换项目身份：不同项目直接清空历史（项目隔离）。"""
        new_root = str(project_root or "")
        if new_root == self._project_root:
            return False
        self._project_root = new_root
        self.clear()
        return True

    def clear(self) -> None:
        self._entries = []
        self._index = -1

    def suppress_next(self, expected: Optional[NavLocation] = None) -> None:
        """标记「下一次到达该位置」为重放产生的（不入栈）。

        保存的是**快照**：还原过程会更新当前位置的光标/滚动，若直接持有条目
        引用，抑制判定会随之失效（审计发现的真实回归）。传 ``None`` 时对下一次
        任意到达生效（兼容旧调用）。
        """
        self._pending = None if expected is None else NavLocation(
            rel_path=expected.rel_path,
            cursor=expected.cursor,
            scroll=expected.scroll,
            source=expected.source,
            project_root=expected.project_root,
        )
        self._suppressed += 1

    @property
    def suppressed(self) -> int:
        return self._suppressed

    def clear_suppression(self) -> None:
        self._pending = None
        self._suppressed = 0

    def record(self, location: NavLocation) -> bool:
        """记录一次主动导航；返回是否真的产生了新记录。

        重放期间（``suppress_next``）只更新当前位置，不新增历史。
        """
        if not location.rel_path:
            return False
        if self._pending is not None and self._pending.rel_path == location.rel_path:
            # 重放到达同一文件：只同步光标/滚动，不入栈；抑制随即解除。
            # 这里只比对文件而不比对光标：重放本身就是为了还原光标，
            # 若沿用「相邻合并」的光标容差，抑制会因光标差异而失效
            # （审计发现的真实回归）。
            self._pending = None
            self._suppressed = 0
            current = self.current()
            if current is not None and current.rel_path == location.rel_path:
                current.cursor = location.cursor
                current.scroll = location.scroll
            return False
        if self._pending is not None:
            # 到达的不是重放目标：这是新的主动导航，抑制作废。
            self._pending = None
            self._suppressed = 0
        # 先截断前进支路：新导航（即使回到与当前相同的位置）也意味着不再有前进目标。
        if self._index < len(self._entries) - 1:
            del self._entries[self._index + 1:]
        current = self.current()
        if current is not None and current.same_place(location):
            # 相邻重复合并：只刷新滚动/来源，不新增条目
            current.cursor = location.cursor
            current.scroll = location.scroll
            if location.source:
                current.source = location.source
            return False
        self._entries.append(location)
        if len(self._entries) > self._limit:
            drop = len(self._entries) - self._limit
            del self._entries[:drop]
        self._index = len(self._entries) - 1
        return True

    # --- 重放 ---

    @staticmethod
    def _snapshot(location: NavLocation) -> NavLocation:
        return NavLocation(
            rel_path=location.rel_path,
            cursor=location.cursor,
            scroll=location.scroll,
            source=location.source,
            project_root=location.project_root,
        )

    def back(self) -> Optional[Tuple[NavLocation, str]]:
        """后退一步；返回 ``(目标位置, 说明)``，无可后退返回 None。"""
        if not self.can_back():
            return None
        self._index -= 1
        target = self._snapshot(self._entries[self._index])
        return target, "后退到 {0}".format(target.describe())

    def forward(self) -> Optional[Tuple[NavLocation, str]]:
        """前进一步；返回 ``(目标位置, 说明)``。"""
        if not self.can_forward():
            return None
        self._index += 1
        target = self._snapshot(self._entries[self._index])
        return target, "前进到 {0}".format(target.describe())


__all__ = [
    "MAX_HISTORY",
    "MERGE_CURSOR_TOLERANCE",
    "NavLocation",
    "NavigationHistory",
]