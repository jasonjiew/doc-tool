# -*- coding: utf-8 -*-
"""代码片段纯服务：用户级配置的增删改、持久化与占位符解析。

``Snippet`` 由 触发词 / 描述 / 带占位符模板 组成。模板占位符形如
``${1:default}``（带默认值）或 ``${2}``（无默认值），序号决定 Tab 跳转顺序。

``SnippetStore`` 读写 ``QStandardPaths.AppDataLocation/snippets.json``
（用户级配置，跨项目共享；可注入目录/路径供测试），写入用原子替换避免
配置损坏。插入模板的文本展开与占位符定位由 ``expand_placeholders`` 提供，
编辑器 UI 据此在插入后依次选中占位符。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

# 占位符：${N} 或 ${N:default}。
_PLACEHOLDER_RE = re.compile(r"\$\{(\d+)(?::([^}]*))?\}")


@dataclass(frozen=True)
class Snippet:
    """一条代码片段。"""

    trigger: str
    description: str
    body: str


@dataclass(frozen=True)
class Placeholder:
    """展开后文本中的一处占位符。"""

    number: int  # 占位符序号（Tab 跳转顺序）
    start: int  # 在展开文本中的起位置（半开区间）
    end: int
    default: str


def expand_placeholders(body: str) -> Tuple[str, List[Placeholder]]:
    """把模板占位符替换为默认值，返回 (展开文本, 占位符位置列表)。

    占位符列表按序号升序（Tab 依次跳转）；无默认值的占位符展开为空串，
    位置为该空区间（光标停靠点）。
    """
    placeholders: List[Placeholder] = []
    parts: List[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(body):
        parts.append(body[cursor : match.start()])
        number = int(match.group(1))
        default = match.group(2) or ""
        start = sum(len(part) for part in parts)
        parts.append(default)
        end = start + len(default)
        placeholders.append(Placeholder(number, start, end, default))
        cursor = match.end()
    parts.append(body[cursor:])
    placeholders.sort(key=lambda item: item.number)
    return "".join(parts), placeholders


class SnippetStore:
    """代码片段配置存储：``snippets.json`` 原子读写。

    ``path`` 缺省时用 ``QStandardPaths.AppDataLocation/snippets.json``；
    测试可注入临时路径，避免污染真实用户配置。
    """

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            from PySide6.QtCore import QStandardPaths

            base = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            path = os.path.join(base, "snippets.json")
        self._path = path
        self._snippets: List[Snippet] = []
        self.load()

    @property
    def path(self) -> str:
        return self._path

    # --- 读取 ---

    def load(self) -> None:
        """从磁盘加载；缺失/损坏视为空配置，不抛异常。"""
        self._snippets = []
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            items = data.get("snippets", []) if isinstance(data, dict) else []
            loaded: List[Snippet] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                trigger = str(item.get("trigger", "")).strip()
                if not trigger:
                    continue
                loaded.append(
                    Snippet(
                        trigger=trigger,
                        description=str(item.get("description", "")),
                        body=str(item.get("body", "")),
                    )
                )
            self._snippets = loaded
        except (OSError, json.JSONDecodeError, UnicodeError):
            self._snippets = []

    def snippets(self) -> List[Snippet]:
        return list(self._snippets)

    def find(self, trigger: str) -> Optional[Snippet]:
        for snippet in self._snippets:
            if snippet.trigger == trigger:
                return snippet
        return None

    # --- 写 ---

    def save(self) -> None:
        """原子写回磁盘（tmp + replace；失败静默，不影响编辑）。"""
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "snippets": [
                {
                    "trigger": s.trigger,
                    "description": s.description,
                    "body": s.body,
                }
                for s in self._snippets
            ]
        }
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except OSError:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def add(self, snippet: Snippet) -> bool:
        """新增片段；触发词重复时不覆盖（返回 False）。"""
        if self.find(snippet.trigger) is not None:
            return False
        self._snippets.append(
            Snippet(snippet.trigger, snippet.description, snippet.body)
        )
        self.save()
        return True

    def update(self, trigger: str, snippet: Snippet) -> bool:
        """按触发词更新片段；不存在返回 False。"""
        for index, existing in enumerate(self._snippets):
            if existing.trigger == trigger:
                self._snippets[index] = Snippet(
                    snippet.trigger, snippet.description, snippet.body
                )
                self.save()
                return True
        return False

    def remove(self, trigger: str) -> bool:
        """删除片段；不存在返回 False。"""
        kept = [s for s in self._snippets if s.trigger != trigger]
        if len(kept) == len(self._snippets):
            return False
        self._snippets = kept
        self.save()
        return True
