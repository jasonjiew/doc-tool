# -*- coding: utf-8 -*-
"""共享 Markdown 块模型与解析契约（V2.7 任务 1.3 / 设计 D1）。

正式项目构建（``scripts/build_docx.py``）、模板填充、评审稿、内置预览与
内容检查都需要「同一份 Markdown 得到同一组块」的结论。此前每条渲染路径
各自用正则扫描行，代码围栏、题注和分节语义在入口之间漂移（例如构建内核
把围栏行当普通段落，模板填充另做去缩进处理）。

本模块是这些块语义的单一事实源：

- ``Block`` 及子类描述块的种类与属主属性，每个块都带 ``SourceLocation``
  （源文件 + 1-based 起止行）。
- ``parse_blocks`` 把 Markdown 文本解析为块序列。
- ``parse_blocks_file`` 读取文件后再解析；不可读时返回带提醒的空结果，
  让调用方按「没有可读内容」处理，而不是抛异常中断整篇构建。

设计约束（见 openspec/changes/product-v27-reliable-delivery）：

- 只修复解析结果，绝不改写用户源码。
- 未闭合围栏/分节默认在当前输入末尾补闭合，并产出可定位 warning。
- 未支持或无法解析的内容一律降级为普通段落，不猜测语义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.domain.markdown_structure import (
    is_separator_row,
    parse_table_meta,
    split_table_row,
)


# --- 块种类 ---------------------------------------------------------------

KIND_HEADING = "heading"
KIND_PARAGRAPH = "paragraph"
KIND_CODE = "code"
KIND_IMAGE = "image"
KIND_TABLE = "table"
KIND_COMPLEX_TABLE = "complex_table"
KIND_LIST_ITEM = "list_item"
KIND_SECTION = "section"
KIND_PAGEBREAK = "pagebreak"
KIND_EMPTY_PARAGRAPH = "empty_paragraph"
KIND_FOOTNOTE_DEF = "footnote_definition"

#: 块种类 -> 中文说明（报告与预览复用同一份文案）。
BLOCK_KIND_LABELS = {
    KIND_HEADING: "标题",
    KIND_PARAGRAPH: "段落",
    KIND_CODE: "代码块",
    KIND_IMAGE: "图片",
    KIND_TABLE: "表格",
    KIND_COMPLEX_TABLE: "复杂表格",
    KIND_LIST_ITEM: "列表项",
    KIND_SECTION: "分节标记",
    KIND_PAGEBREAK: "分页标记",
    KIND_EMPTY_PARAGRAPH: "空段",
    KIND_FOOTNOTE_DEF: "脚注定义",
}

_SECTION_START_RE = re.compile(r"^<!--\s*LANDSCAPE\s*-->$", re.I)
_SECTION_END_RE = re.compile(r"^<!--\s*(?:END_LANDSCAPE|LANDSCAPE_END)\s*-->$", re.I)
_PAGEBREAK_RE = re.compile(r"^<!--\s*(?:PAGEBREAK|PAGE_BREAK)\s*-->$", re.I)
_PARAGRAPH_FORMAT_RE = re.compile(r"^<!--\s*P:(.*?)\s*-->$")
_COMPLEX_TABLE_RE = re.compile(r"^<!--\s*TABLE:(\d+):?([\w.\-]+)?\s*-->$")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
_HEADING_RE = re.compile(r"^(#{1,9})\s+(.+)$")
_LIST_RE = re.compile(r"^(\s*)[-*]\s+(.+)$")
_ORDERED_LIST_RE = re.compile(r"^(\s*)(\d{1,3})[.、]\s+(.+)$")

#: 表格题注：``Table: 参数表 {#tbl-params}`` / ``表: 参数表 {#tbl-params}``。
_TABLE_CAPTION_RE = re.compile(
    r"^(?:Table|表|表格)\s*[:：]\s*(?P<label>.*?)\s*\{#(?P<ident>[A-Za-z0-9_\-:.]+)\}\s*$"
)
#: 图题注：``Figure: 登录流程 {#fig-login}``。
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:Figure|图|插图)\s*[:：]\s*(?P<label>.*?)\s*\{#(?P<ident>[A-Za-z0-9_\-:.]+)\}\s*$"
)
#: 仅标识写法：``{#tbl-params} 参数表``。
_BARE_IDENT_RE = re.compile(r"^\{#(?P<ident>[A-Za-z0-9_\-:.]+)\}\s*(?P<label>.*)$")

#: 围栏开标记（CommonMark 允许 0-3 个前导空格）。
_FENCE_OPEN_RE = re.compile(r"^(?P<indent> {0,3})(?P<mark>`{3,}|~{3,})(?P<info>.*)$")

#: 正文交叉引用语法：``@fig-login`` / ``@tbl-params``。
REFERENCE_RE = re.compile(r"@(?P<kind>fig|tbl)-(?P<slug>[A-Za-z0-9_\-:.]+)")
INLINE_IDENT_RE = re.compile(r"\{#(?P<ident>[A-Za-z0-9_\-:.]+)\}\s*$")

#: 图片行（含可选 ``=WxH`` 与 ``{#fig-id}``）。
_IMAGE_LINE_RE = re.compile(
    r"^!\[(?P<alt>[^\]]*)\]\((?P<target>.+?)\)\s*(?:=(?P<w>\d+)x(?P<h>\d+))?\s*$"
)


@dataclass(frozen=True)
class SourceLocation:
    """块在用户源文件中的位置（1-based，首尾均含）。"""

    path: str
    start_line: int
    end_line: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "line": self.start_line,
            "endLine": self.end_line,
        }

    def __str__(self) -> str:
        if self.start_line == self.end_line:
            return "{0}:{1}".format(self.path, self.start_line)
        return "{0}:{1}-{2}".format(self.path, self.start_line, self.end_line)


@dataclass(frozen=True)
class ParseWarning:
    """解析期的可定位提醒；默认不阻断出稿。"""

    location: SourceLocation
    rule: str
    message: str
    hint: str = ""

    def to_dict(self) -> Dict[str, object]:
        data = {
            "path": self.location.path,
            "line": self.location.start_line,
            "endLine": self.location.end_line,
            "rule": self.rule,
            "message": self.message,
            "hint": self.hint,
        }
        return data

    def as_text(self) -> str:
        return "{0} {1}".format(self.location, self.message)


@dataclass
class Block:
    """块基类：所有块都携带源位置与种类。"""

    location: SourceLocation
    kind: str = ""

    @property
    def line_no(self) -> int:
        return self.location.start_line

    @property
    def path(self) -> str:
        return self.location.path


@dataclass
class Heading(Block):
    level: int = 1
    text: str = ""
    kind: str = KIND_HEADING


@dataclass
class Paragraph(Block):
    text: str = ""
    paragraph_format: Optional[str] = None
    kind: str = KIND_PARAGRAPH


@dataclass
class CodeBlock(Block):
    """代码块：保留原始缩进、Tab、空行与反引号。"""

    text: str = ""
    language: str = ""
    fence: str = "```"
    closed: bool = True
    indent: str = ""
    kind: str = KIND_CODE

    @property
    def is_mermaid(self) -> bool:
        return self.language.strip().lower() == "mermaid"


@dataclass
class Figure(Block):
    """图片块；``ident`` 来自 ``{#fig-...}`` 或紧随其后的图题注行。"""

    alt: str = ""
    relative_path: str = ""
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    ident: str = ""
    caption: str = ""
    kind: str = KIND_IMAGE


@dataclass
class TableBlock(Block):
    rows: List[List[str]] = field(default_factory=list)
    meta: Optional[tuple] = None
    meta_line: Optional[int] = None
    caption_line: Optional[int] = None
    caption_prefix: str = ""
    ident: str = ""
    caption: str = ""
    kind: str = KIND_TABLE


@dataclass
class ComplexTable(Block):
    index: int = 0
    filename: str = ""
    ident: str = ""
    caption: str = ""
    kind: str = KIND_COMPLEX_TABLE


@dataclass
class ListItem(Block):
    list_kind: str = "bullet"
    level: int = 0
    start: int = 1
    text: str = ""
    kind: str = KIND_LIST_ITEM


@dataclass
class SectionMarker(Block):
    """``landscape`` / ``end`` 显式横向节标记。"""

    marker: str = ""
    nested: bool = False
    orphan: bool = False
    implicit: bool = False
    kind: str = KIND_SECTION


@dataclass
class PageBreak(Block):
    kind: str = KIND_PAGEBREAK


@dataclass
class EmptyParagraph(Block):
    kind: str = KIND_EMPTY_PARAGRAPH


@dataclass
class FootnoteDefinition(Block):
    name: str = ""
    text: str = ""
    kind: str = KIND_FOOTNOTE_DEF


@dataclass
class ParsedDocument:
    """一份 Markdown 的解析结果。"""

    path: str
    blocks: List[Block] = field(default_factory=list)
    warnings: List[ParseWarning] = field(default_factory=list)

    def of_kind(self, *kinds: str) -> List[Block]:
        wanted = set(kinds)
        return [block for block in self.blocks if block.kind in wanted]

    @property
    def code_blocks(self) -> List[CodeBlock]:
        return [block for block in self.blocks if block.kind == KIND_CODE]

    @property
    def figures(self) -> List[Figure]:
        return [block for block in self.blocks if block.kind == KIND_IMAGE]

    @property
    def warning_texts(self) -> List[str]:
        return [warning.as_text() for warning in self.warnings]

    @property
    def warnings_as_locations(self) -> List[Dict[str, object]]:
        return [warning.to_dict() for warning in self.warnings]


def _location(path: str, start: int, end: int) -> SourceLocation:
    return SourceLocation(path=path, start_line=start, end_line=end)


def split_caption_ident(text: str) -> Tuple[str, str]:
    """把行尾 ``{#ident}`` 拆出来，返回 ``(正文, ident)``。"""
    match = INLINE_IDENT_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()].rstrip(), match.group("ident")


def parse_table_caption(line: str) -> Optional[Tuple[str, str, str]]:
    """解析表格题注行，返回 ``(前缀, 标签, 标识)``；不是题注返回 None。"""
    stripped = line.strip()
    match = _TABLE_CAPTION_RE.match(stripped)
    if match:
        label, _extra = split_caption_ident(match.group("label"))
        separator = ":" if ":" in stripped else ("：" if "：" in stripped else "")
        prefix = stripped.split(separator, 1)[0] if separator else ""
        return prefix, label, match.group("ident")
    match = _BARE_IDENT_RE.match(stripped)
    if match and not match.group("ident").startswith("fig-"):
        label = split_caption_ident(match.group("label"))[0]
        if label:
            return "", label, match.group("ident")
    return None


def parse_figure_caption(line: str) -> Optional[Tuple[str, str]]:
    """解析图题注行，返回 ``(标签, 标识)``；不是题注返回 None。"""
    stripped = line.strip()
    match = _FIGURE_CAPTION_RE.match(stripped)
    if match:
        label, _extra = split_caption_ident(match.group("label"))
        return label, match.group("ident")
    match = _BARE_IDENT_RE.match(stripped)
    if match and match.group("ident").startswith("fig-"):
        return split_caption_ident(match.group("label"))[0], match.group("ident")
    return None


def parse_image_line(line: str) -> Optional[Figure]:
    """把图片行解析成 :class:`Figure`（支持 ``{#fig-id}`` 与 ``=WxH``）。

    两种尺寸写法都必须支持：
    - ``![说明](images/a.png =800x600)``（括号内，导出/工具写入的现行写法）
    - ``![说明](images/a.png) =800x600``（括号外，导入器与旧文档的历史写法）
    """
    stripped = line.strip()
    stripped, inline_ident = split_caption_ident(stripped)
    match = _IMAGE_LINE_RE.match(stripped)
    if match is None:
        return None
    alt = match.group("alt")
    target = match.group("target").strip()
    width = int(match.group("w")) if match.group("w") else None
    height = int(match.group("h")) if match.group("h") else None
    if not width or not height:
        # 尺寸可能写在括号内路径尾部（``![alt](path =WxH)``），
        # 也可能写在括号外（``![alt](path) =WxH``）。两者都解析，
        # 否则路径会带上 ``=WxH`` 后缀导致图片读取失败。
        inner = re.match(
            r"^(?P<target>.+?)\s*=(?P<w>\d+)x(?P<h>\d+)$", target
        )
        if inner:
            target = inner.group("target").strip()
            width = int(inner.group("w"))
            height = int(inner.group("h"))
        else:
            outer = re.match(
                r"^!\[(?P<alt>[^\]]*)\]\((?P<target>.+?)\)\s*=(?P<w>\d+)x(?P<h>\d+)$",
                stripped,
            )
            if outer:
                alt = outer.group("alt")
                target = outer.group("target").strip()
                width = int(outer.group("w"))
                height = int(outer.group("h"))
    return Figure(
        location=SourceLocation("", 0, 0),
        alt=alt,
        relative_path=target,
        width_px=width,
        height_px=height,
        ident=inline_ident,
    )


def _parse_list(line: str) -> Optional[Tuple[str, int, int, str]]:
    unordered = _LIST_RE.match(line)
    if unordered:
        level = min(8, len(unordered.group(1).replace("\t", "    ")) // 2)
        return "bullet", level, 1, unordered.group(2)
    ordered = _ORDERED_LIST_RE.match(line)
    if ordered:
        level = min(8, len(ordered.group(1).replace("\t", "    ")) // 2)
        return "decimal", level, int(ordered.group(2)), ordered.group(3)
    return None



def parse_pipe_table(block_lines):
    r"""把连续管道行解析为二维单元格矩阵。

    表格方言与构建内核一致（``\|`` 与 ``\\`` 不当作分隔符，
    ``<br>`` 还原为换行，分隔行不进入矩阵）；未抛出异常，无法拆分的
    行按普通行处理。本函数由 domain 自身实现，避免 domain 反向依赖
    ``scripts/`` 内核。
    """
    rows = []
    for line in block_lines:
        try:
            cells = split_table_row(line)
        except Exception:
            continue
        if is_separator_row(cells):
            continue
        rows.append(cells)
    return rows

def parse_blocks(text: str, path: str = "") -> ParsedDocument:
    """解析 Markdown 文本为块序列。

    Args:
        text: Markdown 原文。
        path: 源文件路径，仅用于位置记录与 warning 文案。

    Returns:
        ``ParsedDocument``；解析不抛异常，无法识别的行降级为段落。
    """
    lines = text.split("\n")
    document = ParsedDocument(path=path)
    index = 0
    total = len(lines)
    pending_format: Optional[str] = None
    landscape_depth = 0
    landscape_open_line = 0
    seen_idents: Dict[str, int] = {}

    def _warn(start: int, end: int, rule: str, message: str, hint: str = "") -> None:
        document.warnings.append(
            ParseWarning(_location(path, start, end), rule, message, hint)
        )

    def _register_ident(ident: str, line_no: int, what: str) -> str:
        """重复标识只在输出层唯一化；这里登记并给出可定位提醒。"""
        if not ident:
            return ident
        if ident in seen_idents:
            _warn(
                line_no,
                line_no,
                "caption_duplicate_ident",
                "{0}标识 {1} 与第 {2} 行重复；输出层会分配唯一名称。".format(
                    what, ident, seen_idents[ident]
                ),
                "请为每个图表使用唯一标识，正文引用才能稳定指向同一对象。",
            )
            return ident
        seen_idents[ident] = line_no
        return ident

    def _skip_blanks(start: int) -> int:
        """跳过空行（题注与表格之间允许空行，与既有检查规则一致）。"""
        cursor = start
        while cursor < total and not lines[cursor].strip():
            cursor += 1
        return cursor

    while index < total:
        raw = lines[index]
        stripped = raw.strip()
        line_no = index + 1

        # --- 显式横向节 ---
        if _SECTION_START_RE.match(stripped):
            if landscape_depth > 0:
                _warn(
                    line_no,
                    line_no,
                    "landscape_nested",
                    "横向节嵌套开启（第 {0} 行已开启），本次重复开启被忽略。".format(
                        landscape_open_line
                    ),
                    "请先关闭当前横向节再开启新的。",
                )
                index += 1
                continue
            landscape_depth = 1
            landscape_open_line = line_no
            document.blocks.append(
                SectionMarker(location=_location(path, line_no, line_no), marker="landscape")
            )
            index += 1
            continue
        if _SECTION_END_RE.match(stripped):
            if landscape_depth == 0:
                _warn(
                    line_no,
                    line_no,
                    "landscape_orphan_end",
                    "出现孤立的横向节结束标记（此前没有开启）。",
                    "请删除该标记或补上对应的开启标记。",
                )
                document.blocks.append(
                    SectionMarker(
                        location=_location(path, line_no, line_no), marker="end", orphan=True
                    )
                )
                index += 1
                continue
            landscape_depth = 0
            document.blocks.append(
                SectionMarker(location=_location(path, line_no, line_no), marker="end")
            )
            index += 1
            continue
        if _PAGEBREAK_RE.match(stripped):
            document.blocks.append(PageBreak(location=_location(path, line_no, line_no)))
            index += 1
            continue

        # --- 脚注定义：正文不插入，由 ExpressionManager 收集 ---
        footnote = _FOOTNOTE_DEF_RE.match(stripped)
        if footnote:
            document.blocks.append(
                FootnoteDefinition(
                    location=_location(path, line_no, line_no),
                    name=footnote.group(1),
                    text=footnote.group(2),
                )
            )
            index += 1
            continue

        # --- 围栏代码块（含 mermaid） ---
        fence = _FENCE_OPEN_RE.match(raw)
        if fence:
            mark = fence.group("mark")
            info = fence.group("info").strip()
            body: List[str] = []
            cursor = index + 1
            closed = False
            closer = re.compile(
                r"^ {0,3}" + re.escape(mark[0]) + r"{" + str(len(mark)) + r",}\s*$"
            )
            while cursor < total:
                if closer.match(lines[cursor]):
                    closed = True
                    break
                body.append(lines[cursor])
                cursor += 1
            end_line = cursor + 1 if closed else total
            if not closed:
                _warn(
                    line_no,
                    line_no,
                    "code_fence_unclosed",
                    "代码围栏未闭合，已在当前输入末尾自动闭合。",
                    "请补上 {0} 结束标记。".format(mark),
                )
            document.blocks.append(
                CodeBlock(
                    location=_location(path, line_no, end_line),
                    text="\n".join(body),
                    language=info,
                    fence=mark,
                    closed=closed,
                    indent=fence.group("indent"),
                )
            )
            index = cursor + 1 if closed else total
            continue

        # --- 复杂表格标记 ---
        complex_table = _COMPLEX_TABLE_RE.match(stripped)
        if complex_table:
            block = ComplexTable(
                location=_location(path, line_no, line_no),
                index=int(complex_table.group(1)),
                filename=complex_table.group(2) or "",
            )
            if index + 1 < total:
                caption = parse_table_caption(lines[index + 1])
                if caption is not None:
                    block.ident = _register_ident(caption[2], index + 2, "表格题注")
                    block.caption = caption[1]
                    block.location = _location(path, line_no, index + 2)
                    index += 1
            document.blocks.append(block)
            index += 1
            continue

        # --- 表格元数据 ---
        if stripped.startswith("<!-- TBL:"):
            meta = parse_table_meta(stripped)
            if meta is None:
                document.blocks.append(
                    Paragraph(location=_location(path, line_no, line_no), text=stripped)
                )
                index += 1
                continue
            cursor = index + 1
            if cursor < total and lines[cursor].strip().startswith("|"):
                block_lines: List[str] = []
                while cursor < total and lines[cursor].strip().startswith("|"):
                    block_lines.append(lines[cursor])
                    cursor += 1
                document.blocks.append(
                    TableBlock(
                        location=_location(path, line_no, cursor),
                        rows=parse_pipe_table(block_lines),
                        meta=meta,
                        meta_line=line_no,
                    )
                )
                index = cursor
                continue
            document.blocks.append(
                Paragraph(location=_location(path, line_no, line_no), text=stripped)
            )
            index += 1
            continue

        # --- 表前题注（下一行是表格/复杂表格） ---
        caption = parse_table_caption(stripped)
        if caption is not None:
            nxt_index = _skip_blanks(index + 1)
            nxt = lines[nxt_index].strip() if nxt_index < total else ""
            if nxt.startswith("|") or _COMPLEX_TABLE_RE.match(nxt):
                ident = _register_ident(caption[2], line_no, "表格题注")
                cursor = nxt_index
                if _COMPLEX_TABLE_RE.match(nxt):
                    marker = _COMPLEX_TABLE_RE.match(nxt)
                    document.blocks.append(
                        ComplexTable(
                            location=_location(path, line_no, cursor + 1),
                            index=int(marker.group(1)),
                            filename=marker.group(2) or "",
                            ident=ident,
                            caption=caption[1],
                        )
                    )
                    index = cursor + 1
                    continue
                block_lines = []
                while cursor < total and lines[cursor].strip().startswith("|"):
                    block_lines.append(lines[cursor])
                    cursor += 1
                document.blocks.append(
                    TableBlock(
                        location=_location(path, line_no, cursor),
                        rows=parse_pipe_table(block_lines),
                        ident=ident,
                        caption=caption[1],
                        caption_prefix=caption[0],
                        caption_line=line_no,
                    )
                )
                index = cursor
                continue

        # --- 表格 ---
        if stripped.startswith("|"):
            cursor = index
            block_lines = []
            while cursor < total and lines[cursor].strip().startswith("|"):
                block_lines.append(lines[cursor])
                cursor += 1
            block = TableBlock(
                location=_location(path, line_no, cursor),
                rows=parse_pipe_table(block_lines),
            )
            if cursor < total:
                trailing = parse_table_caption(lines[cursor])
                if trailing is not None:
                    block.ident = _register_ident(trailing[2], cursor + 1, "表格题注")
                    block.caption = trailing[1]
                    block.caption_prefix = trailing[0]
                    block.caption_line = cursor + 1
                    cursor += 1
            document.blocks.append(block)
            index = cursor
            continue

        # --- 图片 ---
        figure = parse_image_line(raw)
        if figure is not None:
            figure.location = _location(path, line_no, line_no)
            cursor = index + 1
            if figure.ident:
                _register_ident(figure.ident, line_no, "图题注")
            else:
                caption_index = _skip_blanks(index + 1)
                fig_caption = (
                    parse_figure_caption(lines[caption_index])
                    if caption_index < total
                    else None
                )
                cursor = caption_index
                if fig_caption is not None:
                    figure.ident = _register_ident(fig_caption[1], cursor + 1, "图题注")
                    figure.caption = fig_caption[0]
                    figure.location = _location(path, line_no, cursor + 1)
                    cursor += 1
                else:
                    cursor = index + 1
            document.blocks.append(figure)
            index = cursor
            continue

        # --- 标题 ---
        heading = _HEADING_RE.match(stripped)
        if heading:
            document.blocks.append(
                Heading(
                    location=_location(path, line_no, line_no),
                    level=len(heading.group(1)),
                    text=re.sub(r"<br\s*/?>", "\n", heading.group(2).strip(), flags=re.I),
                )
            )
            index += 1
            continue

        # --- 列表 ---
        list_info = _parse_list(raw)
        if list_info is not None:
            kind, level, start, item_text = list_info
            document.blocks.append(
                ListItem(
                    location=_location(path, line_no, line_no),
                    list_kind=kind,
                    level=level,
                    start=start,
                    text=re.sub(r"<br\s*/?>", "\n", item_text.strip(), flags=re.I),
                )
            )
            index += 1
            continue

        # --- 段落格式标记 ---
        paragraph_format = _PARAGRAPH_FORMAT_RE.match(stripped)
        if paragraph_format:
            pending_format = paragraph_format.group(1)
            index += 1
            continue

        if stripped == "<EMPTY_PAR/>":
            document.blocks.append(EmptyParagraph(location=_location(path, line_no, line_no)))
            index += 1
            continue

        if stripped:
            document.blocks.append(
                Paragraph(
                    location=_location(path, line_no, line_no),
                    text=re.sub(r"<br\s*/?>", "\n", stripped, flags=re.I),
                    paragraph_format=pending_format,
                )
            )
            pending_format = None
            index += 1
            continue

        index += 1

    if landscape_depth and landscape_open_line:
        _warn(
            landscape_open_line,
            total,
            "landscape_unclosed",
            "横向节在第 {0} 行开启但未闭合，已在当前输入末尾自动关闭。".format(
                landscape_open_line
            ),
            "请在横向内容之后补上结束标记。",
        )
        document.blocks.append(
            SectionMarker(
                location=_location(path, total, total), marker="end", implicit=True
            )
        )
    elif landscape_depth:
        _warn(1, total, "landscape_unclosed", "横向节未闭合，已在输入末尾自动关闭。")
        document.blocks.append(
            SectionMarker(
                location=_location(path, max(total, 1), max(total, 1)),
                marker="end",
                implicit=True,
            )
        )
    return document


def parse_blocks_file(path: str) -> ParsedDocument:
    """读取并解析 Markdown 文件；不可读时返回带提醒的空结果。"""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        document = ParsedDocument(path=path)
        document.warnings.append(
            ParseWarning(
                SourceLocation(path, 0, 0),
                "markdown_unreadable",
                "Markdown 无法读取：{0}".format(exc),
                "请确认文件存在且为 UTF-8 编码。",
            )
        )
        return document
    return parse_blocks(text, path)


def collect_references(text: str) -> List[Tuple[str, str, int]]:
    """收集正文中的 ``@fig-x`` / ``@tbl-x`` 引用，返回 ``(类型, 标识, 行号)``。"""
    found: List[Tuple[str, str, int]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in REFERENCE_RE.finditer(line):
            found.append((match.group("kind"), match.group("slug"), line_no))
    return found


def iter_source_locations(document: ParsedDocument) -> Sequence[SourceLocation]:
    return [block.location for block in document.blocks]