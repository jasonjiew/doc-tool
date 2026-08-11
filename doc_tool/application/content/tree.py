# -*- coding: utf-8 -*-
"""章节树模型：从内容索引推导 `第X章 → X.Y → X.Y.Z` 层级。

纯数据推导（不依赖 tkinter），供章节树面板渲染与测试复用。
"""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional

# 文档类型中文标签（与主窗口 DOC_TYPE_LABELS 保持一致的缺省映射）。
DEFAULT_TYPE_LABELS = {
    "general": "通用大文档",
    "requirement": "需求文档",
    "design": "详细设计文档",
}

_NATURAL_PART_RE = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> tuple:
    """返回章节/文件名的自然排序键，如 ``3.7.2`` 排在 ``3.7.10`` 前。"""
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _NATURAL_PART_RE.split(value)
    )


def _path_sort_key(rel_path: str) -> tuple:
    return tuple(natural_sort_key(part) for part in rel_path.split("/"))


@dataclass
class TreeItem:
    """树节点：用相对路径作唯一 id。"""

    node_id: str  # 目录节点为类型/目录路径，文件节点为 rel_path
    text: str  # 显示文本（目录段名 / 文件名）
    parent_id: Optional[str]  # 父节点 id；根为 None
    rel_path: Optional[str]  # 文件节点为 rel_path；目录/类型节点为 None
    is_file: bool


def build_tree(
    files: List[str],
    type_labels: Optional[Dict[str, str]] = None,
) -> List[TreeItem]:
    """从 rel_path 列表推导章节树（扁平列表，含 parent_id 引用）。

    ``files`` 通常来自 ``index.all_files()``（已稳定排序）。类型目录作为
    顶层组，章节目录与文件按层级嵌套。
    """
    labels = dict(DEFAULT_TYPE_LABELS)
    if type_labels:
        labels.update(type_labels)

    items: List[TreeItem] = []
    seen_dir_ids: set = set()

    # 按文档类型分组，保持稳定顺序。
    by_type: Dict[str, List[str]] = {}
    for rel in files:
        document_type = rel.split("/", 1)[0]
        by_type.setdefault(document_type, []).append(rel)

    for document_type in sorted(by_type):
        type_id = document_type
        items.append(
            TreeItem(
                node_id=type_id,
                text=labels.get(document_type, document_type),
                parent_id=None,
                rel_path=None,
                is_file=False,
            )
        )
        seen_dir_ids.add(type_id)
        for rel in sorted(by_type[document_type], key=_path_sort_key):
            parts = rel.split("/")
            dirs = parts[1:-1]
            file_name = parts[-1]
            parent = type_id
            for segment in dirs:
                dir_id = parent + "/" + segment
                if dir_id not in seen_dir_ids:
                    seen_dir_ids.add(dir_id)
                    items.append(
                        TreeItem(
                            node_id=dir_id,
                            text=segment,
                            parent_id=parent,
                            rel_path=None,
                            is_file=False,
                        )
                    )
                parent = dir_id
            items.append(
                TreeItem(
                    node_id=rel,
                    text=file_name,
                    parent_id=parent,
                    rel_path=rel,
                    is_file=True,
                )
            )
    return items


def filter_tree_items(items: List[TreeItem], query: str) -> List[TreeItem]:
    """筛选章节树，保留命中文件及其父级目录。

    目录自身命中时保留其完整子树，便于按模块名（如 ``KSOA``）浏览；文件命中时
    仅显示该文件和从文档类型到章节的祖先路径。
    """
    needle = query.strip().casefold()
    if not needle:
        return list(items)

    included: set = set()
    by_id = {item.node_id: item for item in items}

    def include_with_ancestors(node_id: str) -> None:
        current = by_id.get(node_id)
        while current is not None:
            included.add(current.node_id)
            current = by_id.get(current.parent_id) if current.parent_id else None

    for item in items:
        haystack = "{0}\n{1}".format(item.text, item.rel_path or item.node_id).casefold()
        if needle not in haystack:
            continue
        include_with_ancestors(item.node_id)
        if not item.is_file:
            prefix = item.node_id + "/"
            included.update(
                descendant.node_id
                for descendant in items
                if descendant.node_id.startswith(prefix)
            )

    return [item for item in items if item.node_id in included]


def ancestors(node_id: str, items: List[TreeItem]) -> List[str]:
    """返回从根到父级的祖先节点 id 列表（不含自身）。"""
    by_id = {item.node_id: item for item in items}
    chain: List[str] = []
    current = by_id.get(node_id)
    while current is not None and current.parent_id is not None:
        chain.append(current.parent_id)
        current = by_id.get(current.parent_id)
    return list(reversed(chain))


_NUM_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _numeric_prefix(name: str) -> Optional[tuple]:
    """提取文件名/目录名开头的数字段（如 3.7.10 → (3, 7, 10)），无则 None。"""
    match = _NUM_PREFIX_RE.match(name)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def next_chapter_rel_path(dir_rel_path: str, files: List[str], title: str) -> str:
    """返回新章节文件 rel_path：递增最大兄弟编号；无编号从目录编号 .1 起；兜底标题。

    1) 只统计 dir 下的直接子文件，取数字前缀最大者的最后一段 +1（3.7.2→3.7.3）。
    2) 无编号兄弟时，用目录名数字段起 .1（3.7 KSOA → 3.7.1）。
    3) 目录名也无数字段时，直接用标题做文件名。
    """
    prefix = dir_rel_path + "/"
    max_num: Optional[tuple] = None
    for rel in files:
        if not rel.startswith(prefix):
            continue
        rest = rel[len(prefix):]
        if "/" in rest:
            continue  # 只考虑直接子文件，忽略更深层
        num = _numeric_prefix(Path(rest).stem)
        if num is not None and (max_num is None or num > max_num):
            max_num = num
    if max_num is not None:
        base = list(max_num)
        base[-1] += 1
        number = ".".join(str(part) for part in base)
    else:
        dir_num = _numeric_prefix(dir_rel_path.rsplit("/", 1)[-1])
        number = (
            ".".join(str(part) for part in dir_num) + ".1"
            if dir_num is not None
            else ""
        )
    head = number + " " if number else ""
    return prefix + head + title + ".md"
