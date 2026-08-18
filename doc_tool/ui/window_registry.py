# -*- coding: utf-8 -*-
"""窗口注册表：保存所有打开的主窗口强引用，避免被 Python GC 回收。

职责（轻量，不承载任何业务项目状态）：
- 保存窗口强引用（``MainWindow`` 是顶层无父窗口，仅靠局部变量会飘）；
- 知道当前打开哪些窗口；
- 窗口关闭后自动移除引用（QObject.destroyed 信号）；
- 提供「按项目根查找窗口」，供重复打开保护（激活已有窗口）。

原则（需求第十条）：Project Context 属于窗口实例，绝不进入本注册表。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple


class WindowRegistry:
    """主窗口强引用注册表。"""

    def __init__(self) -> None:
        # 强引用列表：防止顶层窗口被 GC（PySide6 顶层窗口不持有 parent）。
        self._windows: List[object] = []

    # --- 注册 / 注销 ---

    def register(self, window) -> None:
        """注册窗口并监听其销毁信号；重复注册忽略。"""
        if window in self._windows:
            return
        self._windows.append(window)
        try:
            window.destroyed.connect(lambda _obj=None, w=window: self.unregister(w))
        except (RuntimeError, AttributeError):
            pass

    def unregister(self, window) -> None:
        """窗口销毁/关闭后移除引用。"""
        try:
            if window in self._windows:
                self._windows.remove(window)
        except (RuntimeError, ValueError):
            pass

    # --- 查询 ---

    def windows(self) -> Tuple:
        """当前注册的全部窗口（存活者）。"""
        alive = []
        for window in self._windows:
            try:
                if window is not None:
                    alive.append(window)
            except RuntimeError:
                continue
        return tuple(alive)

    def count(self) -> int:
        return len(self.windows())

    def primary(self):
        """主窗口（第一个注册的存活窗口）；无则 None。"""
        windows = self.windows()
        return windows[0] if windows else None

    def window_for_project(self, project_root) -> Optional[object]:
        """返回已打开指定项目根的窗口；未打开返回 None。

        ``project_root`` 可为 str/Path；比较前做 resolve 归一化，
        避免同一目录的「./proj」与绝对路径被视为不同项目。
        """
        target = str(Path(str(project_root)).resolve()).casefold()
        for window in self.windows():
            # 已关闭（closeEvent accept）的窗口不再参与匹配。
            if getattr(window, "_closed", False):
                continue
            summary = self._project_summary_of(window)
            if summary is None:
                continue
            root = getattr(summary, "project_root", None)
            if root is None:
                continue
            if str(Path(str(root)).resolve()).casefold() == target:
                return window
        return None

    @staticmethod
    def _project_summary_of(window):
        try:
            return getattr(window, "_project_summary", None)
        except RuntimeError:
            return None

    # --- 生命周期 ---

    def close_all(self) -> None:
        """关闭全部窗口（每个窗口自行处理未保存内容与任务取消）。"""
        for window in list(self.windows()):
            try:
                window.close()
            except RuntimeError:
                continue
