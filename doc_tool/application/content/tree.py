# -*- coding: utf-8 -*-
"""章节树模型：从内容索引推导 `第X章 → X.Y → X.Y.Z` 层级。

纯数据推导（不依赖 tkinter），供章节树面板渲染与测试复用。
"""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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


def strip_number_prefix(name: str) -> str:
    """去掉开头的编号段与随后的空格（3.7.5 设备管理 → 设备管理）。"""
    match = _NUM_PREFIX_RE.match(name)
    if match is None:
        return name
    return name[match.end():].lstrip(" ")


def _format_num(num_tuple) -> str:
    return ".".join(str(part) for part in num_tuple)


class ChapterMoveError(ValueError):
    """章节移动目标非法或无法生成无冲突计划。"""


def _parent_rel(rel_path: str) -> str:
    parent = Path(rel_path).parent.as_posix()
    return "" if parent == "." else parent


def _join_rel(parent: str, name: str) -> str:
    return parent + "/" + name if parent else name


def _direct_child_nodes(parent: str, files: Iterable[str]) -> List[str]:
    """返回 parent 下可排序的直接文件/目录节点 id。"""
    prefix = parent + "/" if parent else ""
    children = set()
    for rel_path in files:
        if not rel_path.startswith(prefix):
            continue
        rest = rel_path[len(prefix):]
        if not rest:
            continue
        first = rest.split("/", 1)[0]
        children.add(_join_rel(parent, first))
    return sorted(children, key=_path_sort_key)


def _renumbered_name(name: str, number: Optional[Tuple[int, ...]]) -> str:
    suffix = Path(name).suffix if Path(name).suffix.lower() in (".md", ".markdown") else ""
    stem = name[: -len(suffix)] if suffix else name
    title = strip_number_prefix(stem)
    if number is None:
        return name
    numbered = _format_num(number) + ((" " + title) if title else "")
    return numbered + suffix


def _rewrite_descendant_path(
    rel_path: str,
    old_node: str,
    new_node: str,
    old_prefix: Optional[Tuple[int, ...]],
    new_prefix: Optional[Tuple[int, ...]],
) -> str:
    """重写目录子树路径及各层编号前缀，保持内部相对顺序。"""
    suffix = rel_path[len(old_node):].lstrip("/")
    if not suffix:
        return new_node
    parts = suffix.split("/")
    rewritten = []
    for part in parts:
        extension = Path(part).suffix if Path(part).suffix.lower() in (".md", ".markdown") else ""
        stem = part[: -len(extension)] if extension else part
        number = _numeric_prefix(stem)
        if (
            number is not None
            and old_prefix is not None
            and new_prefix is not None
            and number[: len(old_prefix)] == old_prefix
        ):
            number = new_prefix + number[len(old_prefix):]
            part = _renumbered_name(part, number)
        rewritten.append(part)
    return new_node + "/" + "/".join(rewritten)


def chapter_move_renumber_plan(
    source_node: str,
    target_parent: str,
    files: Sequence[str],
    *,
    before_node: Optional[str] = None,
    allow_cross_type: bool = False,
) -> List[Tuple[str, str]]:
    """生成文件/目录拖拽后的批量 ``(旧 rel_path, 新 rel_path)`` 计划。

    ``source_node`` 可为文件或目录；``target_parent`` 为释放后的父目录，
    ``before_node`` 为目标父目录中的插入参照节点，None 表示末尾追加。目录移动
    会重写整棵子树的编号前缀。返回值按目标路径自然排序，且仅包含实际变化。
    """
    normalized = sorted({str(path).replace("\\", "/") for path in files})
    source_node = source_node.replace("\\", "/").rstrip("/")
    target_parent = target_parent.replace("\\", "/").rstrip("/")
    before_node = before_node.replace("\\", "/") if before_node else None
    is_file = source_node in normalized
    is_directory = any(path.startswith(source_node + "/") for path in normalized)
    if not is_file and not is_directory:
        raise ChapterMoveError("移动源不存在：{0}".format(source_node))
    if target_parent == source_node or target_parent.startswith(source_node + "/"):
        raise ChapterMoveError("不能移动到自身子目录")

    source_type = source_node.split("/", 1)[0]
    target_type = target_parent.split("/", 1)[0] if target_parent else source_type
    explicit_types = set(DEFAULT_TYPE_LABELS)
    if (
        source_type in explicit_types
        and target_type in explicit_types
        and source_type != target_type
        and not allow_cross_type
    ):
        raise ChapterMoveError("不允许跨文档类型移动")

    source_parent = _parent_rel(source_node)
    affected_parents = {source_parent, target_parent}
    children_by_parent = {
        parent: _direct_child_nodes(parent, normalized) for parent in affected_parents
    }
    source_children = children_by_parent[source_parent]
    if source_node not in source_children:
        raise ChapterMoveError("移动源不是可排序的直接子节点")
    source_children.remove(source_node)
    target_children = children_by_parent[target_parent]
    if source_parent != target_parent:
        target_children = [node for node in target_children if node != source_node]
        children_by_parent[target_parent] = target_children
    if before_node is not None:
        if _parent_rel(before_node) != target_parent or before_node not in target_children:
            raise ChapterMoveError("插入位置不属于目标目录")
        insert_at = target_children.index(before_node)
    else:
        insert_at = len(target_children)
    target_children.insert(insert_at, source_node)

    node_mapping: Dict[str, str] = {}
    for parent in sorted(affected_parents):
        parent_number = _numeric_prefix(Path(parent).name) if parent else None
        for position, node in enumerate(children_by_parent[parent], start=1):
            old_name = Path(node).name
            old_number = _numeric_prefix(old_name)
            # 既有编号体系才参与连续重编号；无编号根保持文件名不变。
            number = parent_number + (position,) if parent_number is not None else old_number
            new_node = _join_rel(parent, _renumbered_name(old_name, number))
            node_mapping[node] = new_node

    # 被移动节点需要先切换到目标父目录，再使用目标位置计算出的名字。
    moved_name = Path(node_mapping[source_node]).name
    target_number = _numeric_prefix(moved_name)
    target_parent_number = _numeric_prefix(Path(target_parent).name) if target_parent else None
    if target_parent_number is not None:
        target_number = target_parent_number + (insert_at + 1,)
        moved_name = _renumbered_name(Path(source_node).name, target_number)
    node_mapping[source_node] = _join_rel(target_parent, moved_name)

    result: Dict[str, str] = {}
    for rel_path in normalized:
        matching = [
            node for node in node_mapping
            if rel_path == node or rel_path.startswith(node + "/")
        ]
        if not matching:
            continue
        old_node = max(matching, key=len)
        new_node = node_mapping[old_node]
        old_prefix = _numeric_prefix(Path(old_node).name)
        new_prefix = _numeric_prefix(Path(new_node).name)
        new_path = (
            new_node
            if rel_path == old_node
            else _rewrite_descendant_path(
                rel_path, old_node, new_node, old_prefix, new_prefix
            )
        )
        if new_path != rel_path:
            result[rel_path] = new_path

    targets = list(result.values())
    if len(targets) != len(set(targets)):
        raise ChapterMoveError("移动计划产生重复目标路径")
    occupied = set(normalized) - set(result)
    conflicts = sorted(set(targets) & occupied)
    if conflicts:
        raise ChapterMoveError("目标路径已存在：{0}".format(conflicts[0]))
    return sorted(result.items(), key=lambda pair: _path_sort_key(pair[1]))


def renumber_plan_after_delete(
    deleted_rel_path: str, files: List[str]
) -> List[tuple]:
    """删除中间编号后，返回把后续同级直接子文件递减重编号的 (旧, 新) 列表。

    按新编号升序排列：每步的目标号正好是上一步让出的槽位（或已删除的空槽），
    避免目标冲突。无编号 / 末尾删除 / 深层子文件均不产生重编号。
    """
    prefix = str(Path(deleted_rel_path).parent.as_posix()) + "/"
    deleted_num = _numeric_prefix(Path(deleted_rel_path).stem)
    if deleted_num is None:
        return []
    parent_segments = deleted_num[:-1]
    deleted_last = deleted_num[-1]
    renames: List[tuple] = []
    for rel in files:
        if not rel.startswith(prefix) or rel == deleted_rel_path:
            continue
        rest = rel[len(prefix):]
        if "/" in rest:
            continue  # 只考虑直接子文件
        num = _numeric_prefix(Path(rest).stem)
        if (
            num is None
            or num[: len(parent_segments)] != parent_segments
            or num[-1] <= deleted_last
        ):
            continue
        new_num = tuple(list(num[:-1]) + [num[-1] - 1])
        new_stem = (
            _format_num(new_num)
            + " "
            + strip_number_prefix(Path(rest).stem)
        )
        renames.append((rel, prefix + new_stem + ".md"))
    renames.sort(key=lambda pair: _numeric_prefix(Path(pair[1]).stem))
    return renames


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
