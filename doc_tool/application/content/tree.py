# -*- coding: utf-8 -*-
"""章节树模型：从内容索引推导 `第X章 → X.Y → X.Y.Z` 层级。

纯数据推导（不依赖 tkinter），供章节树面板渲染与测试复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

# 文档类型中文标签（与主窗口 DOC_TYPE_LABELS 保持一致的缺省映射）。
DEFAULT_TYPE_LABELS = {
    "general": "通用大文档",
    "requirement": "需求文档",
    "design": "详细设计文档",
}


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
        for rel in sorted(by_type[document_type]):
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


def ancestors(node_id: str, items: List[TreeItem]) -> List[str]:
    """返回从根到父级的祖先节点 id 列表（不含自身）。"""
    by_id = {item.node_id: item for item in items}
    chain: List[str] = []
    current = by_id.get(node_id)
    while current is not None and current.parent_id is not None:
        chain.append(current.parent_id)
        current = by_id.get(current.parent_id)
    return list(reversed(chain))
