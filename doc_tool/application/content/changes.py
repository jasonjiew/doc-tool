# -*- coding: utf-8 -*-
"""改动汇总纯函数：把快照 diff + 改动清单转成改动面板的条目与 diff。

无 IO、无 Qt，纯数据推导，供改动面板渲染与测试复用（与 ``tree.py`` 同风格）。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ChangeItem:
    """改动面板中的单条改动。"""

    rel_path: str  # 当前路径（rename 后为新路径）
    status: str  # added | modified | deleted
    baseline_rel_path: str  # diff 基线路径（rename 为旧路径，其它同 rel_path）
    trash_path: Optional[str] = None  # 仅 deleted：回收站内绝对路径
    is_rename: bool = False  # 由改动清单 rename 条目叠加而来，不做单文件恢复


_STATUS_ORDER = {"added": 0, "modified": 1, "deleted": 2}


def build_change_items(
    status_map: Dict[str, str],
    *,
    rename_map: Optional[Dict[str, str]] = None,
    trash_map: Optional[Dict[str, str]] = None,
) -> List[ChangeItem]:
    """把快照状态映射转成排序后的改动项列表。

    ``status_map`` 来自 ``snapshot.diff`` + ``overlay_rename_status``（新路径
    标 modified）。``rename_map``（新路径→旧路径）与 ``trash_map``（deleted
    路径→回收站绝对路径）由调用方从改动清单推导。排序：added → modified →
    deleted，同状态按 rel_path 自然排序。
    """
    rename_map = rename_map or {}
    trash_map = trash_map or {}
    items: List[ChangeItem] = []
    for rel_path, status in status_map.items():
        old = rename_map.get(rel_path)
        is_rename = status == "modified" and old is not None
        items.append(
            ChangeItem(
                rel_path=rel_path,
                status=status,
                baseline_rel_path=old if is_rename else rel_path,
                trash_path=trash_map.get(rel_path),
                is_rename=is_rename,
            )
        )
    return sorted(
        items, key=lambda item: (_STATUS_ORDER.get(item.status, 9), item.rel_path)
    )


def render_unified_diff(old_text: str, new_text: str) -> str:
    """返回 old → new 的统一差异文本；无差异返回空串。"""
    if old_text == new_text:
        return ""
    lines = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile="基线",
        tofile="当前",
        lineterm="\n",
        n=1,
    )
    return "\n".join(lines)
