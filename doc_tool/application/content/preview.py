# -*- coding: utf-8 -*-
"""md 结构渲染：把 .md 文本解析为可渲染块。

预览复用 build 合并链路所依据的同一类结构（标题分级/段落/表格/图片占位），
但以轻量自包含方式解析，不依赖 Word COM 内核，供编辑器侧边即时预览。

解析块：
- ``heading``：`#`~`######` 标题，含级别。
- ``paragraph``：普通文本行。
- ``table``：`|` 管道表格，rows 为单元格二维列表。
- ``image``：`![alt](path)`，含 alt 与路径。
- ``blank``：空段。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import List, Optional

# 表格指令注释（如 <!-- TBL:style=... -->），预览时跳过。
_HTML_COMMENT_RE = re.compile(r"^\s*<!--")
# 空段落标记（构建链路插入），预览时跳过。
_EMPTY_PAR_RE = re.compile(r"^\s*<EMPTY_PAR/>\s*$")
# 标题。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# 图片。
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+=(\d+)x(\d+))?")
_IMAGE_SIZE_SUFFIX_RE = re.compile(
    r"(!\[[^\]]*\]\([^\s)]+)\s+=\d+x\d+(\))"
)
_TABLE_SEPARATOR_CELL_RE = re.compile(r":?-+:?")
_IMAGE_INLINE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK_INLINE_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_INLINE_RE = re.compile(r"\*\*(.+?)\*\*")
_EMPHASIS_INLINE_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE_INLINE_RE = re.compile(r"`([^`\n]+)`")
_UNORDERED_LIST_RE = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED_LIST_RE = re.compile(r"^\d+[.)]\s+(.*)$")


@dataclass
class PreviewBlock:
    """渲染块。"""

    kind: str  # heading | paragraph | table | image | blank
    level: int = 0  # heading 级别 1-6
    text: str = ""
    rows: List[List[str]] = field(default_factory=list)  # table
    image_path: str = ""
    image_size: Optional[str] = None


def render_preview_blocks(md_text: str) -> List[PreviewBlock]:
    """把 md 文本解析为渲染块列表。"""
    blocks: List[PreviewBlock] = []
    table_rows: List[List[str]] = []
    in_table = False

    def flush_table() -> None:
        nonlocal table_rows, in_table
        if in_table:
            # 去掉表头分隔行（-- | --）
            body = [
                row
                for row in table_rows
                if not all(re.fullmatch(r":?-+:?", cell) for cell in row)
            ]
            if body:
                blocks.append(PreviewBlock(kind="table", rows=body))
        table_rows = []
        in_table = False

    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped or _EMPTY_PAR_RE.match(line) or _HTML_COMMENT_RE.match(line):
            flush_table()
            continue
        heading_match = _HEADING_RE.match(stripped)
        if heading_match is not None:
            flush_table()
            blocks.append(
                PreviewBlock(
                    kind="heading",
                    level=len(heading_match.group(1)),
                    text=heading_match.group(2),
                )
            )
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            table_rows.append(cells)
            in_table = True
            continue
        if in_table:
            flush_table()
        image_match = _IMAGE_RE.match(stripped)
        if image_match is not None:
            alt = image_match.group(1)
            path = image_match.group(2)
            size = None
            if image_match.group(3):
                size = "{0}x{1}".format(image_match.group(3), image_match.group(4))
            blocks.append(
                PreviewBlock(
                    kind="image",
                    text=alt,
                    image_path=path,
                    image_size=size,
                )
            )
            continue
        blocks.append(PreviewBlock(kind="paragraph", text=stripped))

    flush_table()
    return blocks


def normalize_markdown_for_preview(md_text: str) -> str:
    """转换项目扩展语法，使 Qt Markdown 渲染器可以直接显示。

    文档构建链路允许图片写成 ``![说明](images/example.png =640x480)``，
    但这不是 CommonMark 语法。预览时移除尺寸后缀，保留图片和说明；尺寸仍由
    Word 构建链路使用。``<EMPTY_PAR/>`` 是构建占位符，也不应出现在阅读预览中。
    """
    text = _IMAGE_SIZE_SUFFIX_RE.sub(r"\1\2", md_text)
    return "\n".join(
        line for line in text.splitlines() if not _EMPTY_PAR_RE.match(line)
    )


def render_markdown_html(md_text: str) -> str:
    """把项目 Markdown 转为 Qt 可稳定渲染的受控 HTML。

    Qt 原生 Markdown 解析器在长文档包含大量表格时会丢失后半部分内容。这里
    覆盖本项目使用的标题、段落、列表、表格、图片、链接和常见行内格式，避免该
    限制；正文先 HTML 转义，Markdown 文件中的任意原始 HTML 都不会执行。
    """
    parts: List[str] = []
    table_rows: List[List[str]] = []
    list_items: List[str] = []
    list_tag: Optional[str] = None
    code_lines: List[str] = []
    in_code = False

    def inline(text: str) -> str:
        escaped = html.escape(text, quote=True).replace("&lt;br&gt;", "<br/>")

        def image(match: re.Match) -> str:
            alt, path = match.groups()
            return '<img src="{0}" alt="{1}"/>'.format(
                html.escape(path, quote=True), html.escape(alt, quote=True)
            )

        def link(match: re.Match) -> str:
            label, target = match.groups()
            return '<a href="{0}">{1}</a>'.format(
                html.escape(target, quote=True), label
            )

        escaped = _IMAGE_INLINE_RE.sub(image, escaped)
        escaped = _LINK_INLINE_RE.sub(link, escaped)
        escaped = _CODE_INLINE_RE.sub(r"<code>\1</code>", escaped)
        escaped = _BOLD_INLINE_RE.sub(r"<b>\1</b>", escaped)
        return _EMPHASIS_INLINE_RE.sub(r"<i>\1</i>", escaped)

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        rows = [
            row
            for row in table_rows
            if not all(_TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in row)
        ]
        if rows:
            header, body = rows[0], rows[1:]
            parts.append('<table border="1" cellspacing="0" cellpadding="4" width="100%">')
            parts.append("<tr>{0}</tr>".format("".join("<th>{0}</th>".format(inline(cell)) for cell in header)))
            for row in body:
                parts.append("<tr>{0}</tr>".format("".join("<td>{0}</td>".format(inline(cell)) for cell in row)))
            parts.append("</table>")
        table_rows = []

    def flush_list() -> None:
        nonlocal list_items, list_tag
        if list_tag is not None:
            parts.append("<{0}>{1}</{0}>".format(list_tag, "".join(list_items)))
        list_items = []
        list_tag = None

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            parts.append("<pre>{0}</pre>".format(html.escape("\n".join(code_lines))))
        code_lines = []

    for raw_line in normalize_markdown_for_preview(md_text).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            flush_table()
            flush_list()
            if in_code:
                flush_code()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(raw_line)
            continue
        if _HTML_COMMENT_RE.match(raw_line):
            continue
        if stripped.startswith("|"):
            flush_list()
            table_rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
            continue
        flush_table()
        if not stripped:
            flush_list()
            continue

        heading = _HEADING_RE.match(stripped)
        if heading is not None:
            flush_list()
            level = len(heading.group(1))
            parts.append("<h{0}>{1}</h{0}>".format(level, inline(heading.group(2))))
            continue

        unordered = _UNORDERED_LIST_RE.match(stripped)
        ordered = _ORDERED_LIST_RE.match(stripped)
        if unordered is not None or ordered is not None:
            tag = "ul" if unordered is not None else "ol"
            item = (unordered or ordered).group(1)
            if list_tag is not None and list_tag != tag:
                flush_list()
            list_tag = tag
            list_items.append("<li>{0}</li>".format(inline(item)))
            continue

        flush_list()
        if stripped in ("---", "***", "___"):
            parts.append("<hr/>")
        elif stripped.startswith("> "):
            parts.append("<blockquote>{0}</blockquote>".format(inline(stripped[2:])))
        else:
            parts.append("<p>{0}</p>".format(inline(stripped)))

    flush_table()
    flush_list()
    if in_code:
        flush_code()
    return "<html><body>{0}</body></html>".format("\n".join(parts))


def preview_summary(md_text: str) -> str:
    """给出一段 md 的结构摘要（用于编辑器状态栏提示）。"""
    blocks = render_preview_blocks(md_text)
    counts = {"heading": 0, "paragraph": 0, "table": 0, "image": 0}
    for block in blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    return "标题 {0} · 段落 {1} · 表格 {2} · 图片 {3}".format(
        counts["heading"],
        counts["paragraph"],
        counts["table"],
        counts["image"],
    )
