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


BUILTIN_SNIPPETS = (
    Snippet('研发-功能验收', '功能与可测试验收要点', '## ${1:功能名称}\n${2:功能描述}\n\n### 验收要点\n- 给定 ${3:前置条件}，当 ${4:操作}，应 ${5:结果}。\n'),
    Snippet('研发-接口字段', '接口与字段表', '## ${1:接口名称}\n方法：${2:POST} ${3:/api/path}\n\n| 字段 | 类型 | 必填 | 约束 |\n|---|---|---|---|\n| ${4:field} | ${5:string} | ${6:是} | ${7:说明} |\n'),
    Snippet('研发-异常边界', '异常与边界处理', '### ${1:异常与边界}\n- 触发：${2:输入或状态}\n- 处理：${3:用户提示与恢复动作}\n- 保留：${4:已有数据}\n'),
    Snippet('研发-修订', '修订说明', '| 版本 | 日期 | 修改说明 |\n|---|---|---|\n| ${1:版本} | ${2:日期} | ${3:修改说明} |\n'),
    Snippet('研发-流程', '可编辑 Mermaid 流程源码', '```mermaid\nflowchart TD\n  A[${1:开始}] --> B[${2:处理}]\n  B --> C[${3:结束}]\n```\n'),
    Snippet('研发-时序', '可编辑 Mermaid 时序源码', '```mermaid\nsequenceDiagram\n  participant A as ${1:调用方}\n  participant B as ${2:服务}\n  A->>B: ${3:请求}\n  B-->>A: ${4:响应}\n```\n'),
)


def decode_library(text):
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('schemaVersion') != 1 or not isinstance(data.get('snippets'), list):
        raise ValueError('片段库必须是 schemaVersion 1 JSON')
    values = []
    seen = set()
    for row in data['snippets']:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ('trigger', 'description', 'body')):
            raise ValueError('片段字段必须是文本')
        if not row['trigger'].strip() or row['trigger'] in seen: raise ValueError('触发词为空或重复')
        seen.add(row['trigger'])
        values.append(Snippet(row['trigger'], row['description'], row['body']))
    return values


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
        previous = self._snippets
        self._snippets = []
        self._load_error = False
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
            self._snippets = previous
            self._load_error = os.path.exists(self._path)

    def snippets(self) -> List[Snippet]:
        return list(self._snippets)

    def library(self, query=''):
        users = {s.trigger for s in self._snippets}
        values = self._snippets + [s for s in BUILTIN_SNIPPETS if s.trigger not in users]
        return [s for s in values if query.casefold() in (s.trigger + ' ' + s.description).casefold()]

    def is_builtin(self, snippet):
        return snippet in BUILTIN_SNIPPETS and not any(s.trigger == snippet.trigger for s in self._snippets)

    def export_library(self, selected):
        return json.dumps({'schemaVersion': 1, 'snippets': [s.__dict__ for s in selected]}, ensure_ascii=False, indent=2)

    def merge_library(self, incoming, *, conflicts='skip', confirmed=False):
        if not confirmed: return []
        if conflicts not in ('skip', 'rename', 'replace'): raise ValueError('非法冲突策略')
        values = {s.trigger: s for s in self._snippets}
        changed = []
        for snippet in incoming:
            trigger = snippet.trigger
            if trigger in values:
                if conflicts == 'skip': continue
                if conflicts == 'rename':
                    n = 1
                    while trigger in values:
                        trigger = snippet.trigger + '-' + str(n)
                        n += 1
            values[trigger] = Snippet(trigger, snippet.description, snippet.body)
            changed.append(trigger)
        original = self._snippets
        self._snippets = list(values.values())
        if not self.save():
            self._snippets = original
            raise OSError('片段库写入失败，原配置已保留')
        return changed

    def find(self, trigger: str) -> Optional[Snippet]:
        for snippet in self.library():
            if snippet.trigger == trigger:
                return snippet
        return None

    # --- 写 ---

    def save(self) -> bool:
        """原子写回磁盘（tmp + replace；失败静默，不影响编辑）。"""
        directory = os.path.dirname(self._path)
        payload = {
            "schemaVersion": 1,
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
            if directory:
                os.makedirs(directory, exist_ok=True)
            if self._load_error and os.path.exists(self._path):
                from uuid import uuid4
                import shutil
                shutil.copyfile(self._path, self._path + '.damaged-' + uuid4().hex)
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
            self._load_error = False
            return True
        except OSError:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return False

    def add(self, snippet: Snippet) -> bool:
        """新增片段；触发词重复时不覆盖（返回 False）。"""
        if not snippet.trigger.strip() or self.find(snippet.trigger) is not None:
            return False
        self._snippets.append(
            Snippet(snippet.trigger, snippet.description, snippet.body)
        )
        if self.save(): return True
        self._snippets.pop()
        return False

    def update(self, trigger: str, snippet: Snippet) -> bool:
        """按触发词更新片段；不存在返回 False。

        新触发词与其它条目重复时拒绝（返回 False），避免产生两个同触发词
        条目——否则删除任一相同触发词条目时 ``remove`` 的 ``!=`` 过滤会把
        两条一起删掉，静默丢失另一条片段。
        """
        if snippet.trigger != trigger and self.find(snippet.trigger) is not None:
            return False
        for index, existing in enumerate(self._snippets):
            if existing.trigger == trigger:
                self._snippets[index] = Snippet(
                    snippet.trigger, snippet.description, snippet.body
                )
                if self.save(): return True
                self._snippets[index] = existing
                return False
        return False

    def remove(self, trigger: str) -> bool:
        """删除片段；不存在返回 False。"""
        kept = [s for s in self._snippets if s.trigger != trigger]
        if len(kept) == len(self._snippets):
            return False
        original = self._snippets
        self._snippets = kept
        if self.save(): return True
        self._snippets = original
        return False
