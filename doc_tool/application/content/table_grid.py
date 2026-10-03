# -*- coding: utf-8 -*-
"""普通 Markdown 表格模型、序列化与表格粘贴解析（V3.4 34-A/34-C）。

设计边界（与 [V3.4 设计](../../../openspec/changes/product-v34-table-authoring/design.md) 一致）：

- 只处理**受支持的普通管道表格**：首行表头、第二行分隔、矩形文本单元格；
- Markdown 仍是唯一内容源，本模块不写文件、不缓存第二份权威数据；
- 复杂 Word 原生保留表格、合并单元格、嵌套/富格式内容不在此转换，走既有保留路径；
- 单元格一律按**字符串**处理：前导零、日期文本和 ``=SUM(...)`` 公式文本原样保留。

支持的表达见 ``SUPPORT_MATRIX``；多行单元格用 ``<br/>`` 表达（预览与 Word 均验证）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from doc_tool.application.content.table_format import (
    calculate_display_width,
    format_markdown_table,
    is_separator_row,
    is_table_row,
    split_table_cells,
)

#: 单元格内换行的受支持表达：预览把 ``<br>`` 保留为换行，Word 走同一 H TML 内联解析。
MULTILINE_MARKER = "<br>"

#: 支持的表达/边界矩阵：供界面“支持范围”提示与文档引用。
SUPPORT_MATRIX = {
    "pipe": "支持：单元格内竖线用 \\| 转义",
    "backslash": "支持：反斜杠用 \\\\ 转义，往返不丢失",
    "empty": "支持：空单元格保留为空列，行尾空列不删除",
    "alignment": "支持：默认/左/居中/右对齐",
    "multiline": "支持：引号内换行转成 <br>（预览与 Word 都保留换行）",
    "leadingZero": "支持：0012 / 2026-10-01 / =SUM(A1:A2) 按文本保留",
    "ragged": "部分支持：非矩形输入补空单元格并提示，原始输入保留可复制",
    "merged": "不支持：合并单元格/嵌套表格/富格式，保持既有保留路径",
}

#: 粘贴预览默认展示行数（分页展示，不影响实际插入）。
PREVIEW_ROW_LIMIT = 20

_ALIGNMENT_TO_SEPARATOR = {
    "left": ":---",
    "right": "---:",
    "center": ":---:",
    "default": "---",
}


def escape_cell(text: str) -> str:
    """逻辑文本 → Markdown 单元格文本（转义反斜杠与竖线）。"""
    value = str(text if text is not None else "")
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", MULTILINE_MARKER)
    return value.replace("\\", "\\\\").replace("|", "\\|")


def unescape_cell(text: str) -> str:
    """Markdown 单元格文本 → 逻辑文本（与 ``escape_cell`` 互为逆运算）。"""
    out: List[str] = []
    chars = str(text if text is not None else "")
    index = 0
    while index < len(chars):
        char = chars[index]
        if char == "\\" and index + 1 < len(chars) and chars[index + 1] in ("\\", "|"):
            out.append(chars[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def fragment_digest(text: str) -> str:
    """片段摘要：用于判断网格打开后原表格是否已被其他编辑改变。"""
    normalized = "\n".join(line.rstrip() for line in str(text or "").splitlines()).strip("\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _alignment_for(separator_cell: str) -> str:
    cell = str(separator_cell or "").strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    if cell.endswith(":"):
        return "right"
    if cell.startswith(":"):
        return "left"
    return "default"


def alignment_for(separator_cell: str) -> str:
    """分隔单元格 → 对齐名（供界面显示）。"""
    return _alignment_for(separator_cell)


@dataclass
class TableModel:
    """受支持普通表格的窄模型（表头 + 数据行 + 对齐 + 原片段身份）。"""

    header: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    alignments: List[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    rel_path: str = ""
    warnings: List[str] = field(default_factory=list)
    raw_input: str = ""
    source_digest: str = ""
    supported: bool = True

    @property
    def column_count(self) -> int:
        return len(self.header) or max((len(row) for row in self.rows), default=0)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def matrix(self) -> List[List[str]]:
        return [list(self.header)] + [list(row) for row in self.rows]

    def ensure_shape(self) -> None:
        """把表头/数据行/对齐补齐成同一列数（不删除空列）。"""
        columns = max(
            [len(self.header)] + [len(row) for row in self.rows] + [len(self.alignments)] + [0]
        )
        for row in [self.header] + self.rows:
            while len(row) < columns:
                row.append("")
        while len(self.alignments) < columns:
            self.alignments.append("default")

    def serialize(self) -> str:
        """序列化为 Markdown 管道表格（复用既有对齐/宽度实现）。"""
        self.ensure_shape()
        separator = [
            _ALIGNMENT_TO_SEPARATOR.get(align, "---") for align in self.alignments
        ]
        raw_lines = [
            "| " + " | ".join(escape_cell(cell) for cell in self.header) + " |",
            "| " + " | ".join(separator) + " |",
        ]
        for row in self.rows:
            raw_lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
        return format_markdown_table(raw_lines)

    def to_dict(self) -> dict:
        return {
            "header": list(self.header),
            "rows": [list(row) for row in self.rows],
            "alignments": list(self.alignments),
            "startLine": self.start_line,
            "endLine": self.end_line,
            "relPath": self.rel_path,
            "warnings": list(self.warnings),
            "digest": fragment_digest(self.raw_input) if self.raw_input else "",
            "supported": self.supported,
            "rowCount": self.row_count,
            "columnCount": self.column_count,
        }


@dataclass
class TableParseResult:
    ok: bool
    model: Optional[TableModel] = None
    error: str = ""
    supported: bool = True

    def __bool__(self) -> bool:  # pragma: no cover - 便于调用方直接判断
        return bool(self.ok)


def parse_table(text_or_lines, *, rel_path: str = "", start_line: int = 0,
                source_digest: str = "") -> TableParseResult:
    """解析受支持的普通 Markdown 管道表格。

    非表格、缺少分隔行或列数不一致到无法表达时返回 ``ok=False`` 与原因；
    非矩形输入补空单元格并记录 ``warnings``，原始输入保留在 ``raw_input``。
    """
    if isinstance(text_or_lines, str):
        lines = text_or_lines.strip("\n").splitlines()
        raw = text_or_lines.strip("\n")
    else:
        lines = [str(line) for line in (text_or_lines or [])]
        raw = "\n".join(lines)
    lines = [line for line in lines if line.strip()]
    if len(lines) < 2:
        return TableParseResult(False, error="表格至少需要表头与分隔行两行")
    if not all(is_table_row(line) for line in lines):
        return TableParseResult(False, error="含有不是普通管道表格的行，已按原内容保留")
    separator_cells = split_table_cells(lines[1])
    if not is_separator_row(separator_cells):
        return TableParseResult(False, error="第二行不是表头分隔行，无法按普通表格编辑")

    parsed = [split_table_cells(line) for line in lines]
    columns = max(len(cells) for cells in parsed)
    if columns < 1:
        return TableParseResult(False, error="表格没有可编辑的列")
    alignments = [_alignment_for(cell) for cell in separator_cells]
    while len(alignments) < columns:
        alignments.append("default")

    model = TableModel(
        header=[unescape_cell(cell) for cell in parsed[0]],
        rows=[[unescape_cell(cell) for cell in row] for row in parsed[2:]],
        alignments=alignments,
        start_line=start_line or 1,
        end_line=(start_line or 1) + len(lines) - 1,
        rel_path=rel_path,
        raw_input=raw,
        source_digest=fragment_digest(raw) if not source_digest else source_digest,
    )
    # 非矩形补齐：保留空列，不删除用户内容。
    for index, line_cells in enumerate(parsed):
        if len(line_cells) != columns:
            row_no = index + 1
            model.warnings.append(
                "第 {0} 行有 {1} 列（表头 {2} 列），已补空单元格；原始输入保留可复制。".format(
                    row_no, len(line_cells), columns,
                )
            )
    model.ensure_shape()
    if model.alignments and _ALIGNMENT_TO_SEPARATOR.get(model.alignments[0]) is None:
        model.supported = False
        model.warnings.append("存在无法表达的对齐方式，已按默认对齐输出")
        model.alignments = ["default" if a not in _ALIGNMENT_TO_SEPARATOR else a for a in model.alignments]
    return TableParseResult(True, model=model)


@dataclass
class LocateResult:
    ok: bool
    start: int = 0
    end: int = 0
    matches: int = 0
    reason: str = ""


def locate_fragment(source: str, fragment: str, *, near_line: int = 0) -> LocateResult:
    """在源文本中唯一定位原片段（1-based 行号）；不唯一或缺失时给出原因。"""
    source_lines = str(source or "").splitlines()
    fragment_lines = [line.rstrip() for line in str(fragment or "").splitlines() if line.strip()]
    if not fragment_lines:
        return LocateResult(False, reason="原片段为空，无法定位")
    hits: List[Tuple[int, int]] = []
    span = len(fragment_lines)
    for start in range(0, len(source_lines) - span + 1):
        window = [line.rstrip() for line in source_lines[start:start + span]]
        if window == fragment_lines:
            hits.append((start + 1, start + span))
    if not hits:
        return LocateResult(False, matches=0, reason="原表格片段已不在当前缓冲中（可能已被其他编辑修改）")
    if len(hits) == 1:
        return LocateResult(True, start=hits[0][0], end=hits[0][1], matches=1)
    return LocateResult(
        False, matches=len(hits),
        reason="存在 {0} 处相同片段，无法唯一确定要替换的表格；请重新定位".format(len(hits)),
    )


def apply_fragment(source: str, fragment: str, replacement: str, *, near_line: int = 0):
    """把 ``fragment`` 唯一定位后替换为 ``replacement``；失败返回 ``(None, 原因)``。"""
    located = locate_fragment(source, fragment, near_line=near_line)
    if not located.ok:
        return None, located.reason
    lines = str(source or "").splitlines()
    new_lines = str(replacement or "").splitlines()
    updated = lines[: located.start - 1] + new_lines + lines[located.end:]
    text = "\n".join(updated)
    if str(source or "").endswith("\n"):
        text += "\n"
    return text, ""


@dataclass
class DelimitedResult:
    ok: bool
    rows: List[List[str]] = field(default_factory=list)
    source: str = ""
    warnings: List[str] = field(default_factory=list)
    error: str = ""
    has_header: bool = True
    multi_line_cells: int = 0
    raw_input: str = ""

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max((len(row) for row in self.rows), default=0)


def _looks_like_pipe_table(text: str) -> bool:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return all(is_table_row(line) for line in lines)


def parse_clipboard_text(text: str) -> DelimitedResult:
    """显式“粘贴为表格”的解析入口：优先 TSV，其次已有管道表格。

    引号感知：使用标准库 ``csv``，因此引号内的制表符/换行不会被拆开；
    单元格一律按字符串处理，前导零、日期与 ``=...`` 公式保持原样。
    """
    raw = str(text or "")
    if not raw.strip() and "\t" not in raw:
        return DelimitedResult(False, error="剪贴板没有可转换为表格的文本")
    if "\t" in raw:
        return _parse_tsv(raw)
    if _looks_like_pipe_table(raw):
        parsed = parse_table(raw)
        if not parsed.ok or parsed.model is None:
            return DelimitedResult(False, error=parsed.error or "管道表格无法解析")
        model = parsed.model
        return DelimitedResult(
            True, rows=model.matrix(), source="markdown",
            warnings=list(model.warnings), has_header=True, raw_input=raw,
        )
    return DelimitedResult(
        False, error="输入既不是制表符分隔文本，也不是普通管道表格；可用普通粘贴保留原文",
        raw_input=raw,
    )


def _parse_tsv(raw: str) -> DelimitedResult:
    reader = csv.reader(io.StringIO(raw), delimiter="\t", quotechar='"')
    rows: List[List[str]] = []
    warnings: List[str] = []
    multiline = 0
    try:
        for row in reader:
            rows.append([str(cell) for cell in row])
    except csv.Error as exc:
        return DelimitedResult(False, error="TSV 解析失败（第 {0} 行附近）：{1}".format(reader.line_num, exc), raw_input=raw)
    # csv.reader 不会把普通行尾换行多算一行；显式空记录是用户选中的数据。
    if not rows:
        return DelimitedResult(False, error="输入没有有效行", raw_input=raw)
    columns = max(len(row) for row in rows)
    for index, row in enumerate(rows, start=1):
        if len(row) != columns:
            warnings.append(
                "第 {0} 行有 {1} 列（共 {2} 列），已补空单元格；原始输入保留可复制。".format(
                    index, len(row), columns,
                )
            )
        while len(row) < columns:
            row.append("")
        for cell_index, cell in enumerate(row):
            if "\n" in cell or "\r" in cell:
                multiline += 1
                row[cell_index] = cell.replace("\r\n", "\n").replace("\r", "\n").replace("\n", MULTILINE_MARKER)
    if multiline:
        warnings.append(
            "引号内换行已转换为 {0}（预览与 Word 都保留换行）；如需保留原文可复制原始输入。".format(
                MULTILINE_MARKER,
            )
        )
    return DelimitedResult(
        True, rows=rows, source="tsv", warnings=warnings,
        has_header=True, multi_line_cells=multiline, raw_input=raw,
    )


def model_from_matrix(rows: Sequence[Sequence[str]], *, has_header: bool = True,
                      alignments: Optional[Sequence[str]] = None,
                      rel_path: str = "", start_line: int = 0) -> TableModel:
    """把二维文本转成表格模型（首行可选表头）。"""
    matrix = [list(row) for row in (rows or [])]
    if not matrix:
        return TableModel(rel_path=rel_path, start_line=start_line, supported=False)
    header = matrix[0] if has_header else ["" for _ in matrix[0]]
    body = matrix[1:] if has_header else matrix
    columns = max(len(row) for row in matrix)
    model = TableModel(
        header=list(header), rows=body,
        alignments=[str(item) for item in (alignments or [])] or ["default"] * columns,
        rel_path=rel_path, start_line=start_line,
    )
    model.ensure_shape()
    return model


def preview_rows(rows: Sequence[Sequence[str]], *, limit: int = PREVIEW_ROW_LIMIT):
    """分页预览：返回 ``(前若干行, 是否被截断, 总行数)``；不截断实际插入内容。"""
    total = len(rows or [])
    shown = list(rows or [])[: max(1, int(limit))]
    return shown, total > len(shown), total


def preview_page(
    rows: Sequence[Sequence[str]], *, page: int = 0, limit: int = PREVIEW_ROW_LIMIT
) -> Tuple[List[List[str]], int, int, int]:
    """返回 ``(当页行, 页码, 总页数, 总行数)``；只影响预览，不改完整数据。

    38-A 1.1：大表格（如 1000×20）需要翻页查看，插入时仍使用完整 ``rows``。
    """
    data = [list(row) for row in (rows or [])]
    size = max(1, int(limit))
    total = len(data)
    pages = max(1, (total + size - 1) // size)
    index = max(0, min(int(page), pages - 1))
    start = index * size
    return data[start:start + size], index, pages, total


def table_at_line(text: str, line_idx: int, *, rel_path: str = "") -> TableParseResult:
    """按 1-based 行号嗅探并解析所在普通表格。"""
    from doc_tool.application.content.table_format import find_table_range_at_line

    lines = str(text or "").splitlines()
    rng = find_table_range_at_line(lines, max(0, int(line_idx) - 1))
    if rng is None:
        return TableParseResult(False, error="光标所在行不是普通管道表格（复杂原生表格保持原保留方式）")
    start, end = rng
    fragment = "\n".join(lines[start:end + 1])
    return parse_table(fragment, rel_path=rel_path, start_line=start + 1)
