# -*- coding: utf-8 -*-
"""改动汇总纯函数：把快照 diff + 改动清单转成改动面板的条目与 diff。

无 IO、无 Qt，纯数据推导，供改动面板渲染与测试复用（与 ``tree.py`` 同风格）。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ChangeItem:
    """改动面板中的单条改动。"""

    rel_path: str  # 当前路径（rename 后为新路径）
    status: str  # added | modified | deleted
    baseline_rel_path: str  # diff 基线路径（rename 为旧路径，其它同 rel_path）
    trash_path: Optional[str] = None  # 仅 deleted：回收站内绝对路径
    is_rename: bool = False  # 由改动清单 rename 条目叠加而来，不做单文件恢复
    restorable: bool = True  # False：仅展示（如 project.yml），不做单文件恢复


_STATUS_ORDER = {"added": 0, "modified": 1, "deleted": 2}


def build_change_items(
    status_map: Dict[str, str],
    *,
    rename_map: Optional[Dict[str, str]] = None,
    trash_map: Optional[Dict[str, str]] = None,
    non_restorable: Optional[Sequence[str]] = None,
) -> List[ChangeItem]:
    """把快照状态映射转成排序后的改动项列表。

    ``status_map`` 来自 ``snapshot.diff`` + ``overlay_rename_status``（新路径
    标 modified）。``rename_map``（新路径→旧路径）与 ``trash_map``（deleted
    路径→回收站绝对路径）由调用方从改动清单推导。``non_restorable`` 中的
    路径仅展示、禁用单文件恢复（如 Git/SVN 检测出的 ``project.yml`` 变更）。
    排序：added → modified → deleted，同状态按 rel_path 自然排序。
    """
    rename_map = rename_map or {}
    trash_map = trash_map or {}
    non_restorable = set(non_restorable or ())
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
                restorable=rel_path not in non_restorable,
            )
        )
    from doc_tool.domain.content_index import path_natural_sort_key

    return sorted(
        items,
        key=lambda item: (
            _STATUS_ORDER.get(item.status, 9),
            path_natural_sort_key(item.rel_path),
        ),
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


@dataclass(frozen=True)
class DiffSpan:
    """行内字符级差异区间。"""

    start: int
    end: int
    tag: str  # 'equal' | 'delete' | 'insert' | 'replace'


def compute_word_diff_spans(
    old_line: str, new_line: str
) -> Tuple[List[DiffSpan], List[DiffSpan]]:
    """对比两行文本的字符/单词级差异，返回 (old_spans, new_spans)。

    仅保留非 equal 的变动区间供高亮加深底色使用。
    """
    matcher = difflib.SequenceMatcher(None, old_line, new_line, autojunk=False)
    old_spans: List[DiffSpan] = []
    new_spans: List[DiffSpan] = []
    for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
        if tag in ("delete", "replace") and alo < ahi:
            old_spans.append(DiffSpan(start=alo, end=ahi, tag=tag))
        if tag in ("insert", "replace") and blo < bhi:
            new_spans.append(DiffSpan(start=blo, end=bhi, tag=tag))
    return old_spans, new_spans


@dataclass(frozen=True)
class SideBySideLine:
    """分栏对比视图的单行对齐数据。"""

    old_line_no: Optional[int]
    old_text: str
    new_line_no: Optional[int]
    new_text: str
    change_type: str  # 'equal' | 'delete' | 'insert' | 'replace'
    old_spans: Tuple[DiffSpan, ...] = ()
    new_spans: Tuple[DiffSpan, ...] = ()


def render_side_by_side_diff(old_text: str, new_text: str) -> List[SideBySideLine]:
    """生成左右两栏对齐的比对行数据（含字级别差异高亮区间）。"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    results: List[SideBySideLine] = []

    for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
        if tag == "equal":
            for i in range(ahi - alo):
                results.append(
                    SideBySideLine(
                        old_line_no=alo + i + 1,
                        old_text=old_lines[alo + i],
                        new_line_no=blo + i + 1,
                        new_text=new_lines[blo + i],
                        change_type="equal",
                    )
                )
        elif tag == "replace":
            count = max(ahi - alo, bhi - blo)
            for i in range(count):
                o_idx = alo + i if i < (ahi - alo) else None
                n_idx = blo + i if i < (bhi - blo) else None
                o_text = old_lines[o_idx] if o_idx is not None else ""
                n_text = new_lines[n_idx] if n_idx is not None else ""
                o_spans: Tuple[DiffSpan, ...] = ()
                n_spans: Tuple[DiffSpan, ...] = ()
                if o_idx is not None and n_idx is not None:
                    s_o, s_n = compute_word_diff_spans(o_text, n_text)
                    o_spans, n_spans = tuple(s_o), tuple(s_n)
                elif o_idx is not None:
                    o_spans = (DiffSpan(start=0, end=len(o_text), tag="delete"),) if o_text else ()
                elif n_idx is not None:
                    n_spans = (DiffSpan(start=0, end=len(n_text), tag="insert"),) if n_text else ()

                results.append(
                    SideBySideLine(
                        old_line_no=o_idx + 1 if o_idx is not None else None,
                        old_text=o_text,
                        new_line_no=n_idx + 1 if n_idx is not None else None,
                        new_text=n_text,
                        change_type="replace",
                        old_spans=o_spans,
                        new_spans=n_spans,
                    )
                )
        elif tag == "delete":
            for i in range(alo, ahi):
                txt = old_lines[i]
                results.append(
                    SideBySideLine(
                        old_line_no=i + 1,
                        old_text=txt,
                        new_line_no=None,
                        new_text="",
                        change_type="delete",
                        old_spans=(DiffSpan(start=0, end=len(txt), tag="delete"),) if txt else (),
                    )
                )
        elif tag == "insert":
            for i in range(blo, bhi):
                txt = new_lines[i]
                results.append(
                    SideBySideLine(
                        old_line_no=None,
                        old_text="",
                        new_line_no=i + 1,
                        new_text=txt,
                        change_type="insert",
                        new_spans=(DiffSpan(start=0, end=len(txt), tag="insert"),) if txt else (),
                    )
                )
    return results

