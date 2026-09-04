# -*- coding: utf-8 -*-
"""Markdown 表格智能格式化与对齐引擎。

提供中英文字宽自适应计算（基于 Unicode East Asian Width）、表格各列管道符对齐、
对齐指示符（:---:, ---:, :---）保持、以及连续表格区间自动嗅探。
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple, Union


def calculate_display_width(text: str) -> int:
    """计算文本在等宽字体下的字符显示宽度。

    全角字符（中文汉字、全角标点、韩文、日文假名等）计为 2 列宽；
    半角 ASCII 字符计为 1 列宽；零宽控制字符计为 0。
    """
    width = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Me", "Cf"):
            continue
        east = unicodedata.east_asian_width(ch)
        if east in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def _count_trailing_backslashes(s: str) -> int:
    count = 0
    for ch in reversed(s):
        if ch == "\\":
            count += 1
        else:
            break
    return count


def split_table_cells(line: str) -> List[str]:
    """拆分单个表格行中的各个单元格（支持 \\| 转义管道符与转义反斜杠）。"""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    # 仅当末尾管道符未被转义（前置偶数个反斜杠）时切除外围闭合管道符
    if stripped.endswith("|") and _count_trailing_backslashes(stripped[:-1]) % 2 == 0:
        stripped = stripped[:-1]

    cells: List[str] = []
    current: List[str] = []
    escaped = False

    for ch in stripped:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
            current.append(ch)
        elif ch == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


def is_table_row(line: str) -> bool:
    """判断一行是否为 Markdown 表格行（需以 | 开头且至少含有 2 个未转义管道符）。"""
    s = line.strip()
    if not s.startswith("|"):
        return False
    unescaped_pipes = 0
    escaped = False
    for ch in s:
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            unescaped_pipes += 1
    return unescaped_pipes >= 2


def is_separator_row(cells: List[str]) -> bool:
    """判断拆分出的单元格行是否全为表头分隔行标记（如 :---, ---:, :---:, ---）。"""
    if not cells:
        return False
    sep_pattern = re.compile(r"^:?-+:?$")
    return all(bool(cell and sep_pattern.match(cell)) for cell in cells)


def find_table_range_at_line(lines: List[str], line_idx: int) -> Optional[Tuple[int, int]]:
    """在文本行列表中嗅探给定行索引所属的连续 Markdown 表格行范围 [start, end]（含两端）。

    若目标行不属于表格或不构成合法表格（至少需要 2 行且包含分隔行），返回 None。
    """
    if line_idx < 0 or line_idx >= len(lines):
        return None
    if not is_table_row(lines[line_idx]):
        return None

    start = line_idx
    while start > 0 and is_table_row(lines[start - 1]):
        start -= 1

    end = line_idx
    while end < len(lines) - 1 and is_table_row(lines[end + 1]):
        end += 1

    if end - start < 1:
        return None

    # 检查其中是否包含合法表头分隔行（必须在首行之后）
    has_sep = False
    for i in range(start + 1, end + 1):
        cells = split_table_cells(lines[i])
        if is_separator_row(cells):
            has_sep = True
            break
    if not has_sep:
        return None

    return start, end


def format_markdown_table(table_text_or_lines: Union[str, List[str]]) -> str:
    """格式化一个连续的 Markdown 表格字符串或行列表，返回对齐后的表格文本。"""
    if isinstance(table_text_or_lines, str):
        raw_lines = table_text_or_lines.strip().splitlines()
    else:
        raw_lines = [line.strip() for line in table_text_or_lines if line.strip()]

    if not raw_lines:
        return ""

    parsed_rows: List[List[str]] = [split_table_cells(line) for line in raw_lines]
    if not parsed_rows:
        return "\n".join(raw_lines)

    max_cols = max(len(row) for row in parsed_rows)
    for row in parsed_rows:
        while len(row) < max_cols:
            row.append("")

    sep_row_idx = -1
    for i, row in enumerate(parsed_rows):
        if is_separator_row(row):
            sep_row_idx = i
            break

    # 解析各列对齐方式: "left", "right", "center", "default"
    alignments: List[str] = ["default"] * max_cols
    if sep_row_idx >= 0:
        for c, cell in enumerate(parsed_rows[sep_row_idx]):
            cell_s = cell.strip()
            if cell_s.startswith(":") and cell_s.endswith(":"):
                alignments[c] = "center"
            elif cell_s.endswith(":"):
                alignments[c] = "right"
            elif cell_s.startswith(":"):
                alignments[c] = "left"
            else:
                alignments[c] = "default"

    # 计算每列的最大显示宽度（最小为 3，预留 --- 或 :--）
    col_widths: List[int] = [3] * max_cols
    for i, row in enumerate(parsed_rows):
        if i == sep_row_idx:
            continue
        for c, cell in enumerate(row):
            w = calculate_display_width(cell)
            if w > col_widths[c]:
                col_widths[c] = w

    formatted_lines: List[str] = []
    for i, row in enumerate(parsed_rows):
        if i == sep_row_idx:
            # 格式化分隔行
            sep_cells: List[str] = []
            for c in range(max_cols):
                w = col_widths[c]
                align = alignments[c]
                if align == "center":
                    sep_cells.append(":" + "-" * max(1, w - 2) + ":")
                elif align == "right":
                    sep_cells.append("-" * max(2, w - 1) + ":")
                elif align == "left":
                    sep_cells.append(":" + "-" * max(2, w - 1))
                else:
                    sep_cells.append("-" * w)
            formatted_lines.append("| " + " | ".join(sep_cells) + " |")
        else:
            # 格式化普通数据行 / 表头
            data_cells: List[str] = []
            for c in range(max_cols):
                cell = row[c]
                w = calculate_display_width(cell)
                align = alignments[c]
                pad = max(0, col_widths[c] - w)
                if align == "right":
                    padded = " " * pad + cell
                elif align == "center":
                    left_pad = pad // 2
                    right_pad = pad - left_pad
                    padded = " " * left_pad + cell + " " * right_pad
                else:
                    padded = cell + " " * pad
                data_cells.append(padded)
            formatted_lines.append("| " + " | ".join(data_cells) + " |")

    return "\n".join(formatted_lines)
