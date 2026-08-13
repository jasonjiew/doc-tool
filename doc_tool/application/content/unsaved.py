# -*- coding: utf-8 -*-
"""未保存内容的保护决策：纯枚举 + 纯收集 + 可注入决策函数。

``collect_unsaved`` 返回有未保存编辑的 rel_path 列表；``UnsavedChoice``
描述三态决策；``UnsavedResolver`` 是「向用户确认后返回决策」的函数签名，
默认实现弹 QMessageBox（见 ``ui/content/unsaved_prompt.py``），离屏测试
注入返回预设值的桩即可替换真实对话框。
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, List


class UnsavedChoice(str, Enum):
    """未保存内容的处理决策。"""

    SAVE = "save"        # 先保存全部再继续
    DISCARD = "discard"  # 放弃未保存内容直接继续
    CANCEL = "cancel"    # 中止当前操作


# 决策函数：给定未保存 rel_paths 与场景上下文，返回用户选择。
# context 取值："exit" | "switch" | "delete" | "rename"。
UnsavedResolver = Callable[[List[str], str], UnsavedChoice]


def collect_unsaved(editors) -> List[str]:
    """返回有未保存编辑的编辑器 rel_path 列表（保持打开顺序）。

    ``editors`` 是含 ``current_rel_path()`` / ``is_dirty()`` 的编辑器集合
    （``TabsHost.editors()`` 提供）。只收脏标签；无脏标签返回空列表。
    """
    result = []
    for editor in editors:
        rel_path = editor.current_rel_path()
        if rel_path is not None and editor.is_dirty():
            result.append(rel_path)
    return result
