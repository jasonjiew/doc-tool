# -*- coding: utf-8 -*-
"""Markdown 表格结构契约：单一事实源。

构建内核（``scripts/docx_common.py`` 构建前检查、``scripts/build_docx.py``
正文插入）和内容检查（``doc_tool/application/content/lint.py``）共用本模块，
保证「合并前检查能查出来的问题」与「合并时会失败的问题」是同一套规则，
不会出现某一侧漏检、另一侧只丢一个错误码的情况。

两类结论：
- ``blocking=True``：构建内核必然 fail-fast（元数据语法无效、元数据后没有
  紧跟表格）。检查面板按规则配置的严重度报告，默认 error。
- ``blocking=False``：不阻断构建，但产物与作者意图不符（声明列宽数与实际
  列数不一致会让全部列宽退回默认值；行列数不齐会补空单元格；缺少分隔行
  会让表头不被识别）。一律按 warning 报告。

行内容全部按「构建内核看到的样子」判定：内核不处理代码栅栏，以 ``|`` 开头的
行一律当表格行，这里保持一致，避免检查通过却构建失败。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# 表格元数据注释前缀（``<!-- TBL:style=.. type=.. tw=.. cols=.. -->``）。
TABLE_META_PREFIX = "<!-- TBL:"

# 复杂表格标记前缀（``<!-- TABLE:序号:文件名.xml -->``），语法与资源存在性
# 由构建前检查负责，这里只用于把它与普通表格块区分开。
COMPLEX_TABLE_PREFIX = "<!-- TABLE:"

# 元数据语法（与 build_docx 的表格构造参数一一对应）。
_META_RE = re.compile(
    r"<!--\s*TBL:style=([\w.]*)\s+type=(\w+)\s+tw=(\d+)(?:\s+trh=(\d+))?\s+"
    r"cols=([\d,]*)((?:\s+(?:cm|ind|lay|bd|hdr|cs|tcm|va)=[\w:,\-\.]*)*)\s*-->"
)
_META_EXTRA_RE = re.compile(r"(cm|ind|lay|bd|hdr|cs|tcm|va)=([\w:,\-\.]*)")

# 早期导出的简化元数据（只有 style 与 cols）。
_LEGACY_META_RE = re.compile(r"<!--\s*TBL:style=([\w.]*)\s+cols=([\d,]*)\s*-->")

# Markdown 表格分隔行单元格（``---`` / ``:---`` / ``---:`` / ``:---:``）。
_SEPARATOR_CELL_RE = re.compile(r":?-{1,}:?")

# 元数据语法说明：报错时给出可照抄的最小正确写法。
META_SYNTAX_HINT = (
    "正确写法形如 <!-- TBL:style=43 type=auto tw=0 cols=1967,2556 -->；"
    "style/type/tw/cols 必需，trh 与 cm/ind/lay/bd/hdr/cs/tcm/va 可选。"
)


class TableRowSyntaxError(ValueError):
    """表格行不以 ``|`` 开头。"""


@dataclass(frozen=True)
class StructureFinding:
    """一条表格结构结论。

    Attributes:
        line_no: 1-based 行号，指向用户需要修改的那一行。
        rule: 稳定规则名，供筛选与测试断言。
        message: 面向用户的问题说明（含实际数值，不需要再去看源文件才能懂）。
        hint: 具体修法建议；空表示 message 已自解释。
        blocking: 是否会让构建 fail-fast。
    """

    line_no: int
    rule: str
    message: str
    hint: str = ""
    blocking: bool = False

    @property
    def text(self) -> str:
        """``message`` 与 ``hint`` 合并成一句可直接展示的说明。"""
        return "{0} {1}".format(self.message, self.hint).strip()


def split_table_row(line: str) -> List[str]:
    r"""把管道表格行拆成单元格，``\|`` 与 ``\\`` 不作分隔符。

    只解码项目需要的两个转义：``\|`` → ``|``、``\\`` → ``\``。其余反斜杠原样
    保留（可能是业务数据、Windows 路径或正则文本）。``<br>`` 还原为换行。

    Raises:
        TableRowSyntaxError: 行不以 ``|`` 开头。
    """
    value = line.strip()
    if not value.startswith("|"):
        raise TableRowSyntaxError("Markdown 表格行必须以 | 开头: {0}".format(line))
    cells: List[str] = []
    current: List[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value) and value[index + 1] in ("|", "\\"):
            current.append(value[index + 1])
            index += 2
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current))
    if cells and not cells[0].strip():
        cells.pop(0)
    if cells and not cells[-1].strip():
        cells.pop()
    return [
        re.sub(r"<br\s*/?>", "\n", cell.strip(), flags=re.IGNORECASE) for cell in cells
    ]


def is_separator_row(cells: Sequence[str]) -> bool:
    """整行都是 ``---`` 形态的分隔单元格。"""
    return bool(cells) and all(
        _SEPARATOR_CELL_RE.fullmatch(cell or "") for cell in cells
    )


def parse_table_meta(line: str):
    """解析表格元数据注释。

    Returns:
        ``(style_id, col_widths, width_type, table_width, row_height, extras)``；
        不是合法元数据返回 None。构建内核直接用该元组构造 ``w:tbl``，所以语法
        在本模块单点定义，检查与构建不会出现两套解释。
    """
    match = _META_RE.fullmatch(line)
    if match:
        extras = {
            item.group(1): item.group(2)
            for item in _META_EXTRA_RE.finditer(match.group(6) or "")
        }
        return (
            match.group(1) or None,
            [int(value) for value in match.group(5).split(",") if value] or None,
            match.group(2),
            int(match.group(3)),
            int(match.group(4)) if match.group(4) else None,
            extras,
        )
    legacy = _LEGACY_META_RE.fullmatch(line)
    if legacy:
        return (
            legacy.group(1) or None,
            [int(value) for value in legacy.group(2).split(",") if value] or None,
            "dxa",
            None,
            None,
            {},
        )
    return None


def _declared_column_count(line: str) -> Optional[int]:
    """元数据声明的列宽个数；无法解析返回 None。"""
    meta = parse_table_meta(line)
    if meta is None:
        return None
    widths = meta[1]
    return len(widths) if widths else None


def _collect_table_block(
    lines: Sequence[str], start: int
) -> Tuple[List[Tuple[int, List[str]]], int]:
    """从 ``start`` 收集连续表格行，返回 ``([(行号, 单元格)], 下一行下标)``。

    无法拆分的行（不以 ``|`` 开头）不会进入这里；块内解析异常按空块处理，
    交由调用方按「元数据后缺少表格」报告，避免检查自身抛异常中断整轮检查。
    """
    rows: List[Tuple[int, List[str]]] = []
    cursor = start
    while cursor < len(lines) and str(lines[cursor]).strip().startswith("|"):
        try:
            rows.append((cursor + 1, split_table_row(str(lines[cursor]))))
        except TableRowSyntaxError:
            break
        cursor += 1
    return rows, cursor


def _blank_gap(lines: Sequence[str], start: int) -> int:
    """``start`` 起连续空行数量。"""
    count = 0
    while start + count < len(lines) and not str(lines[start + count]).strip():
        count += 1
    return count


def check_table_structure(lines: Sequence[str]) -> List[StructureFinding]:
    """检查一份 Markdown 的表格结构契约，返回按行号排序的全部结论。

    一次扫描报出全部问题（而不是遇到第一个就停），这样作者改一轮就能全部
    修完，不必反复触发构建再逐个定位。
    """
    findings: List[StructureFinding] = []
    index = 0
    total = len(lines)
    while index < total:
        raw = str(lines[index])
        stripped = raw.strip()

        if stripped.startswith(TABLE_META_PREFIX):
            line_no = index + 1
            meta_valid = parse_table_meta(stripped) is not None
            if not meta_valid:
                findings.append(StructureFinding(
                    line_no=line_no,
                    rule="table_meta_syntax",
                    message="表格元数据语法无效：{0}".format(_excerpt(stripped)),
                    hint=META_SYNTAX_HINT,
                    blocking=True,
                ))
            next_is_table = (
                index + 1 < total and str(lines[index + 1]).strip().startswith("|")
            )
            if not next_is_table:
                gap = _blank_gap(lines, index + 1)
                after_gap_is_table = (
                    index + 1 + gap < total
                    and str(lines[index + 1 + gap]).strip().startswith("|")
                )
                if gap and after_gap_is_table:
                    hint = (
                        "元数据与表头之间有 {0} 个空行，删除这些空行即可"
                        "（元数据必须与表头紧邻）。".format(gap)
                    )
                else:
                    hint = (
                        "请在这一行下方紧接写出以 | 开头的表头行，"
                        "或删除这条没有表格的元数据注释。"
                    )
                findings.append(StructureFinding(
                    line_no=line_no,
                    rule="table_meta_orphan",
                    message="表格元数据的下一行不是表格（必须紧跟以 | 开头的表头行）。",
                    hint=hint,
                    blocking=True,
                ))
                index += 1
                continue
            declared = _declared_column_count(stripped) if meta_valid else None
            rows, cursor = _collect_table_block(lines, index + 1)
            findings.extend(_check_block(rows, declared, line_no))
            index = cursor
            continue

        if stripped.startswith("|"):
            rows, cursor = _collect_table_block(lines, index)
            findings.extend(_check_block(rows, None, None))
            index = max(cursor, index + 1)
            continue

        index += 1

    findings.sort(key=lambda item: (item.line_no, item.rule))
    return findings


def _check_block(
    rows: Sequence[Tuple[int, List[str]]],
    declared_columns: Optional[int],
    meta_line_no: Optional[int],
) -> List[StructureFinding]:
    """检查一个表格块：分隔行、列数一致性、与元数据声明的列宽数是否吻合。"""
    findings: List[StructureFinding] = []
    if not rows:
        return findings

    data_rows = [(line_no, cells) for line_no, cells in rows if not is_separator_row(cells)]
    if not data_rows:
        return findings

    header_line_no, header_cells = data_rows[0]
    # 构建内核按最宽行确定列数（``make_table_from_md`` 会把短行补空单元格）。
    column_count = max(len(cells) for _, cells in data_rows)

    if not any(is_separator_row(cells) for _, cells in rows):
        findings.append(StructureFinding(
            line_no=header_line_no,
            rule="table_missing_separator",
            message="表格缺少 | --- | 分隔行，首行不会被当作表头。",
            hint="请在表头行下方补一行 {0}。".format(
                "| " + " | ".join(["---"] * max(column_count, 1)) + " |"
            ),
        ))

    for line_no, cells in data_rows[1:]:
        if len(cells) != column_count:
            findings.append(StructureFinding(
                line_no=line_no,
                rule="table_ragged_rows",
                message="表格该行 {0} 列，与表格的 {1} 列不一致，缺少的单元格会补空。".format(
                    len(cells), column_count
                ),
                hint="请补齐或删除多余的 | 分隔符。",
            ))

    if declared_columns is not None and declared_columns != column_count:
        if declared_columns < column_count:
            impact = "声明数少于实际列数时，全部列宽都会退回默认值"
        else:
            impact = "多出的列宽会被忽略"
        findings.append(StructureFinding(
            line_no=meta_line_no if meta_line_no is not None else header_line_no,
            rule="table_column_mismatch",
            message="表格元数据声明 {0} 个列宽，表格实际 {1} 列；{2}。".format(
                declared_columns, column_count, impact
            ),
            hint="请把 cols= 改为 {0} 个宽度值。".format(column_count),
        ))

    return findings


def _excerpt(text: str, limit: int = 80) -> str:
    """截断过长原文，保证错误消息本身可读。"""
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[:limit] + "…"
