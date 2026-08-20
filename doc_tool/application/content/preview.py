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
import base64
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
# 图片尺寸后缀的外部形式：![alt](path) =WxH。
_IMAGE_OUTER_SIZE_SUFFIX_RE = re.compile(
    r"(!\[[^\]]*\]\([^\s)]+\))\s+=\d+x\d+"
)
# 围栏行：3 个及以上反引号或波浪号（CommonMark 两种围栏均合法）。
_FENCE_LINE_RE = re.compile(r"^(?:`{3,}|~{3,})")


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


def render_markdown_html(md_text: str, *, use_cli: bool = False) -> str:
    """把项目 Markdown 转为 Qt 可稳定渲染的受控 HTML。

    Qt 原生 Markdown 解析器在长文档包含大量表格时会丢失后半部分内容。这里
    覆盖本项目使用的标题、段落、列表、表格、图片、链接和常见行内格式，避免该
    限制；正文先 HTML 转义，Markdown 文件中的任意原始 HTML 都不会执行。

    ``use_cli`` 默认 False：实时预览用内置渲染器（mermaid 不启动 mmdc 子进程，
    避免 UI 线程被最长 30s 的同步 CLI 渲染冻结）。导出等后台路径可传 True
    以使用 mermaid-cli 的高质量渲染。

    每个标题/段落/图片块把文本内容包进 ``<a name="line-N" href="#line-N">``
    锚点：预览点击块时 ``anchorClicked`` 携带 ``#line-N``，编辑器据此定位
    源行（预览点击→编辑）。锚点编号对应原始 Markdown 源行号（构建占位符
    行被跳过但仍累计行号）。列表/表格/分隔线不做内容包裹（保持结构稳定），
    仅在块首挂 ``name``/``id`` 锚点供 ``scrollToAnchor`` 使用。
    """
    parts: List[str] = []
    table_rows: List[List[str]] = []
    list_items: List[str] = []
    list_tag: Optional[str] = None
    list_line: Optional[int] = None
    code_lines: List[str] = []
    in_code = False
    code_language = ""
    code_start_line = 0

    def inline(text: str) -> str:
        escaped = html.escape(text, quote=True).replace("&lt;br&gt;", "<br/>")

        def image(match: re.Match) -> str:
            alt, path = match.groups()
            # alt/path 来自已整体转义后的文本；直接嵌入属性即可，二次转义
            # 会把含 & 的路径变成 &amp;amp;，导致预览图片/链接失效。
            return '<img src="{0}" alt="{1}"/>'.format(path, alt)

        def link(match: re.Match) -> str:
            label, target = match.groups()
            return '<a href="{0}">{1}</a>'.format(target, label)

        escaped = _IMAGE_INLINE_RE.sub(image, escaped)
        escaped = _LINK_INLINE_RE.sub(link, escaped)
        # 代码跨度先占位再还原：粗体/斜体正则会处理 <code> 内的 ``**x**``
        # 文本，把代码内容渲染成 `<code><b>x</b></code>`，与源码不符。
        code_spans: List[str] = []

        def capture_code(match: re.Match) -> str:
            code_spans.append(match.group(1))
            return "\x00DOC_TOOL_CODE_{0}\x00".format(len(code_spans) - 1)

        escaped = _CODE_INLINE_RE.sub(capture_code, escaped)
        escaped = _BOLD_INLINE_RE.sub(r"<b>\1</b>", escaped)
        escaped = _EMPHASIS_INLINE_RE.sub(r"<i>\1</i>", escaped)
        for index, span in enumerate(code_spans):
            escaped = escaped.replace(
                "\x00DOC_TOOL_CODE_{0}\x00".format(index),
                "<code>{0}</code>".format(span),
            )
        return escaped

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
        nonlocal list_items, list_tag, list_line
        if list_tag is not None:
            anchor = (
                '<a name="line-{0}"></a>'.format(list_line)
                if list_line is not None
                else ""
            )
            parts.append(
                "{0}<{1}>{2}</{1}>".format(
                    anchor, list_tag, "".join(list_items)
                )
            )
        list_items = []
        list_tag = None
        list_line = None

    def flush_code() -> None:
        nonlocal code_lines, code_language, code_start_line
        if code_lines:
            source = "\n".join(code_lines)
            if code_language == "mermaid":
                from doc_tool.application.content.mermaid import render

                result = render(source, use_cli=use_cli)
                if result.ok and result.png:
                    encoded = base64.b64encode(result.png).decode("ascii")
                    parts.append(
                        '<p><a name="line-{0}" href="#line-{0}">'
                        '<img src="data:image/png;base64,{1}" alt="Mermaid 图"/></a></p>'.format(
                            code_start_line, encoded
                        )
                    )
                elif result.svg and result.png is None:
                    # 有 SVG 但无 PNG（QtSvg 后端缺失或 CLI 栅格化失败）时
                    # 保守回退源码代码块，不影响普通预览。
                    parts.append("<pre>{0}</pre>".format(html.escape(source)))
                else:
                    parts.append(
                        '<p><a name="line-{0}" href="#line-{0}"><b>Mermaid 渲染失败：</b> {1}</a></p>'.format(
                            code_start_line, html.escape(result.error or "未知原因")
                        )
                    )
            else:
                parts.append("<pre>{0}</pre>".format(html.escape(source)))
        code_lines = []
        code_language = ""
        code_start_line = 0

    for source_line, raw_line in enumerate(md_text.splitlines(), start=1):
        # 构建占位符行跳过（不渲染），但源行号继续累计。
        if _EMPTY_PAR_RE.match(raw_line):
            continue
        # 移除项目图片尺寸后缀（内外部形式），使 Qt 图片渲染不残留 =WxH。
        processed = _IMAGE_SIZE_SUFFIX_RE.sub(r"\1\2", raw_line)
        processed = _IMAGE_OUTER_SIZE_SUFFIX_RE.sub(r"\1", processed)
        stripped = processed.strip()
        fence = _FENCE_LINE_RE.match(stripped)
        if fence:
            flush_table()
            flush_list()
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
                code_language = stripped[fence.end():].strip().lower()
                code_start_line = source_line
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
            parts.append(
                '<h{0}><a name="line-{1}" href="#line-{1}">{2}</a></h{0}>'.format(
                    level, source_line, inline(heading.group(2))
                )
            )
            continue

        unordered = _UNORDERED_LIST_RE.match(stripped)
        ordered = _ORDERED_LIST_RE.match(stripped)
        if unordered is not None or ordered is not None:
            tag = "ul" if unordered is not None else "ol"
            item = (unordered or ordered).group(1)
            if list_tag is not None and list_tag != tag:
                flush_list()
            list_tag = tag
            if list_line is None:
                list_line = source_line
            list_items.append("<li>{0}</li>".format(inline(item)))
            continue

        flush_list()
        if stripped in ("---", "***", "___"):
            parts.append('<hr id="line-{0}"/>'.format(source_line))
        elif stripped.startswith("> "):
            parts.append(
                '<blockquote><a name="line-{0}" href="#line-{0}">{1}</a></blockquote>'.format(
                    source_line, inline(stripped[2:])
                )
            )
        else:
            parts.append(
                '<p><a name="line-{0}" href="#line-{0}">{1}</a></p>'.format(
                    source_line, inline(stripped)
                )
            )

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
