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
# GitHub 级 Callout 警告块标记行：>[!NOTE] 等
_CALLOUT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:\s*(.*))?$", re.IGNORECASE)

_CALLOUT_META = {
    "note": ("ℹ️ NOTE", "#3b82f6", "#eff6ff", "#1d4ed8", "#1e293b", "#60a5fa"),
    "tip": ("💡 TIP", "#16a34a", "#f0fdf4", "#15803d", "#064e3b", "#4ade80"),
    "warning": ("⚠️ WARNING", "#d97706", "#fffbeb", "#b45309", "#451a03", "#fbbf24"),
    "important": ("📌 IMPORTANT", "#7c3aed", "#f5f3ff", "#6d28d9", "#2e1065", "#c084fc"),
    "caution": ("🛑 CAUTION", "#dc2626", "#fef2f2", "#b91c1c", "#450a0a", "#f87171"),
}

_CSS_LIGHT = """
body {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 10pt;
    line-height: 1.6;
    color: #1f2328;
    background-color: #ffffff;
    margin: 8px 12px;
}
h1, h2, h3, h4, h5, h6 {
    color: #0f172a;
    font-weight: 600;
    margin-top: 18px;
    margin-bottom: 8px;
}
h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
    color: inherit;
    text-decoration: none;
}
h1 a:hover, h2 a:hover, h3 a:hover, h4 a:hover, h5 a:hover, h6 a:hover {
    color: #2563eb;
}
h1 { font-size: 16pt; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }
h2 { font-size: 13pt; border-bottom: 1px solid #f1f5f9; padding-bottom: 4px; }
h3 { font-size: 11.5pt; }
h4 { font-size: 10.5pt; }
p { margin-top: 6px; margin-bottom: 8px; }
a { color: #2563eb; text-decoration: none; }
table.doc-table {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
    border: 1px solid #cbd5e1;
}
table.doc-table th {
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 600;
    padding: 6px 10px;
    border: 1px solid #cbd5e1;
}
table.doc-table td {
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
    color: #1e293b;
}
pre {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 12px;
    font-family: Consolas, monospace;
    font-size: 9.5pt;
    color: #1e293b;
    margin: 8px 0;
}
code {
    background-color: #f1f5f9;
    color: #b91c1c;
    font-family: Consolas, monospace;
    font-size: 9.5pt;
    padding: 2px 4px;
    border-radius: 3px;
}
blockquote {
    border-left: 4px solid #94a3b8;
    background-color: #f8fafc;
    margin: 8px 0;
    padding: 6px 12px;
    color: #475569;
}
hr {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 16px 0;
}
"""

_CSS_DARK = """
body {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 10pt;
    line-height: 1.6;
    color: #e5e7eb;
    background-color: #26272e;
    margin: 8px 12px;
}
h1, h2, h3, h4, h5, h6 {
    color: #f3f4f6;
    font-weight: 600;
    margin-top: 18px;
    margin-bottom: 8px;
}
h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
    color: inherit;
    text-decoration: none;
}
h1 a:hover, h2 a:hover, h3 a:hover, h4 a:hover, h5 a:hover, h6 a:hover {
    color: #60a5fa;
}
h1 { font-size: 16pt; border-bottom: 1px solid #3a3b44; padding-bottom: 6px; }
h2 { font-size: 13pt; border-bottom: 1px solid #32333b; padding-bottom: 4px; }
h3 { font-size: 11.5pt; }
h4 { font-size: 10.5pt; }
p { margin-top: 6px; margin-bottom: 8px; }
a { color: #60a5fa; text-decoration: none; }
table.doc-table {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
    border: 1px solid #3a3b44;
}
table.doc-table th {
    background-color: #1e1f24;
    color: #f3f4f6;
    font-weight: 600;
    padding: 6px 10px;
    border: 1px solid #3a3b44;
}
table.doc-table td {
    padding: 6px 10px;
    border: 1px solid #3a3b44;
    color: #e5e7eb;
}
pre {
    background-color: #1b1c21;
    border: 1px solid #3a3b44;
    border-radius: 6px;
    padding: 10px 12px;
    font-family: Consolas, monospace;
    font-size: 9.5pt;
    color: #e5e7eb;
    margin: 8px 0;
}
code {
    background-color: #1e1f24;
    color: #f87171;
    font-family: Consolas, monospace;
    font-size: 9.5pt;
    padding: 2px 4px;
    border-radius: 3px;
}
blockquote {
    border-left: 4px solid #4b5563;
    background-color: #1e1f24;
    margin: 8px 0;
    padding: 6px 12px;
    color: #9ca3af;
}
hr {
    border: none;
    border-top: 1px solid #3a3b44;
    margin: 16px 0;
}
"""


_PY_KEYWORDS = {
    "def", "class", "import", "from", "return", "if", "elif", "else", "while",
    "for", "in", "try", "except", "finally", "with", "as", "lambda", "yield",
    "none", "true", "false", "is", "not", "and", "or", "pass", "break", "continue",
    "async", "await", "self"
}
_SQL_KEYWORDS = {
    "select", "from", "where", "insert", "into", "values", "update", "set",
    "delete", "join", "left", "right", "inner", "outer", "on", "group", "by",
    "order", "having", "limit", "create", "table", "drop", "alter", "index",
    "and", "or", "not", "in", "is", "null", "as", "union", "all", "distinct",
    "case", "when", "then", "end", "primary", "key", "foreign", "references"
}
_JSON_KEYWORDS = {"true", "false", "null"}
_CPP_KEYWORDS = {
    "int", "void", "char", "float", "double", "bool", "class", "struct", "template",
    "typename", "public", "private", "protected", "virtual", "const", "if", "else",
    "for", "while", "return", "new", "delete", "namespace", "using", "include", "auto"
}
_SH_KEYWORDS = {
    "echo", "cd", "ls", "mkdir", "rm", "cp", "mv", "if", "then", "else", "elif",
    "fi", "for", "do", "done", "while", "case", "esac", "export", "set", "exit"
}
_YAML_KEYWORDS = {"true", "false", "yes", "no", "null"}

_LANG_SPECS = {
    "py": (_PY_KEYWORDS, r"#.*$"),
    "python": (_PY_KEYWORDS, r"#.*$"),
    "sql": (_SQL_KEYWORDS, r"--.*$|/\*[\s\S]*?\*/"),
    "json": (_JSON_KEYWORDS, None),
    "cpp": (_CPP_KEYWORDS, r"//.*$|/\*[\s\S]*?\*/"),
    "c": (_CPP_KEYWORDS, r"//.*$|/\*[\s\S]*?\*/"),
    "sh": (_SH_KEYWORDS, r"#.*$"),
    "bash": (_SH_KEYWORDS, r"#.*$"),
    "shell": (_SH_KEYWORDS, r"#.*$"),
    "yaml": (_YAML_KEYWORDS, r"#.*$"),
    "yml": (_YAML_KEYWORDS, r"#.*$"),
    "xml": (set(), r"<!--[\s\S]*?-->"),
    "html": (set(), r"<!--[\s\S]*?-->"),
}


def highlight_code_html(source: str, lang: str = "", dark: bool = False) -> str:
    """轻量代码语法高亮：输出带内联样式的 HTML。

    支持多行三引号字符串、跨行块注释、单行注释、关键字与数字染色。
    """
    lang = (lang or "").strip().lower()
    spec = _LANG_SPECS.get(lang)
    if not spec:
        return html.escape(source)

    keywords, comment_pat = spec
    c_kw = "#79c0ff" if dark else "#0550ae"
    c_str = "#7ee787" if dark else "#116329"
    c_cmt = "#8b949e" if dark else "#6e7781"
    c_num = "#a5d6ff" if dark else "#0550ae"

    patterns = [
        r'(?P<STR>"""(?:\\.|[\s\S])*?"""|\'\'\'(?:\\.|[\s\S])*?\'\'\'|"(?:\\.|[^"\n\\])*"|\'(?:\\.|[^\'\n\\])*\')'
    ]
    if comment_pat:
        patterns.append(r'(?P<CMT>' + comment_pat + r')')
    patterns.append(r'(?P<WORD>\b[a-zA-Z_]\w*\b)')
    patterns.append(r'(?P<NUM>\b(?:0[xX][0-9a-fA-F]+|0[bB][01]+|\d+(?:\.\d+)?)\b)')

    token_re = re.compile("|".join(patterns), re.MULTILINE)

    parts: List[str] = []
    last_idx = 0
    for match in token_re.finditer(source):
        start, end = match.span()
        if start > last_idx:
            parts.append(html.escape(source[last_idx:start]))
        last_idx = end

        group_name = match.lastgroup
        val = match.group(0)
        if group_name == "CMT":
            parts.append(
                f'<span style="color: {c_cmt}; font-style: italic;">{html.escape(val)}</span>'
            )
        elif group_name == "STR":
            parts.append(
                f'<span style="color: {c_str};">{html.escape(val)}</span>'
            )
        elif group_name == "NUM":
            parts.append(
                f'<span style="color: {c_num};">{html.escape(val)}</span>'
            )
        elif group_name == "WORD":
            if val.lower() in keywords:
                parts.append(
                    f'<span style="color: {c_kw}; font-weight: bold;">{html.escape(val)}</span>'
                )
            else:
                parts.append(html.escape(val))
        else:
            parts.append(html.escape(val))

    if last_idx < len(source):
        parts.append(html.escape(source[last_idx:]))

    return "".join(parts)



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


def render_markdown_html(
    md_text: str,
    *,
    use_cli: bool = False,
    dark: bool = False,
) -> str:
    """把项目 Markdown 转为 Qt 可稳定渲染的受控 HTML。

    Qt 原生 Markdown 解析器在长文档包含大量表格时会丢失后半部分内容。这里
    覆盖本项目使用的标题、段落、列表、表格、图片、链接和常见行内格式，避免该
    限制；正文先 HTML 转义，Markdown 文件中的任意原始 HTML 都不会执行。

    ``use_cli`` 默认 False：实时预览用内置渲染器（mermaid 不启动 mmdc 子进程，
    避免 UI 线程被最长 30s 的同步 CLI 渲染冻结）。导出等后台路径可传 True
    以使用 mermaid-cli 的高质量渲染。
    ``dark`` 默认 False：控制是否注入深色主题 CSS 样式。

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
    quote_lines: List[tuple[int, str]] = []
    code_lines: List[str] = []
    in_code = False
    code_language = ""
    code_start_line = 0

    def inline(text: str) -> str:
        escaped = html.escape(text, quote=True).replace("&lt;br&gt;", "<br/>")

        def image(match: re.Match) -> str:
            alt, path = match.groups()
            return '<img src="{0}" alt="{1}"/>'.format(path, alt)

        def link(match: re.Match) -> str:
            label, target = match.groups()
            return '<a href="{0}">{1}</a>'.format(target, label)

        escaped = _IMAGE_INLINE_RE.sub(image, escaped)
        escaped = _LINK_INLINE_RE.sub(link, escaped)
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
            parts.append('<table class="doc-table" border="1" cellspacing="0" cellpadding="5" width="100%">')
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

    def flush_quote() -> None:
        nonlocal quote_lines
        if not quote_lines:
            return
        start_line, first_text = quote_lines[0]
        m = _CALLOUT_RE.match(first_text.strip())
        if m:
            kind = m.group(1).lower()
            inline_tail = m.group(2) or ""
            meta = _CALLOUT_META.get(kind, _CALLOUT_META["note"])
            title_text = meta[0]
            border_color = meta[1]
            bg_color = meta[4] if dark else meta[2]
            title_color = meta[5] if dark else meta[3]

            body_lines = []
            if inline_tail.strip():
                body_lines.append((start_line, inline_tail.strip()))
            for q_ln, q_text in quote_lines[1:]:
                body_lines.append((q_ln, q_text))

            body_html = "<br/>".join(
                '<a name="line-{0}" href="#line-{0}">{1}</a>'.format(ln, inline(lt))
                for ln, lt in body_lines
            ) if body_lines else ""

            content_html = (
                '<div class="callout callout-{0}" style="border-left: 4px solid {1}; background-color: {2}; padding: 8px 12px; margin: 10px 0; border-radius: 4px;">'
                '<div class="callout-title" style="color: {3}; font-weight: bold; margin-bottom: 4px;">'
                '<a name="line-{4}" href="#line-{4}" style="color: {3}; text-decoration: none;">{5}</a>'
                '</div>'
                '{6}'
                '</div>'
            ).format(
                kind,
                border_color,
                bg_color,
                title_color,
                start_line,
                title_text,
                ('<div class="callout-body">' + body_html + '</div>') if body_html else "",
            )
            parts.append(content_html)
        else:
            inner = "<br/>".join(
                '<a name="line-{0}" href="#line-{0}">{1}</a>'.format(ln, inline(lt))
                for ln, lt in quote_lines
            )
            parts.append('<blockquote>{0}</blockquote>'.format(inner))
        quote_lines = []

    def flush_code() -> None:
        nonlocal code_lines, code_language, code_start_line
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
                parts.append(
                    '<pre><a name="line-{0}"></a>{1}</pre>'.format(
                        code_start_line, html.escape(source)
                    )
                )
            else:
                parts.append(
                    '<p><a name="line-{0}" href="#line-{0}"><b>Mermaid 渲染失败：</b> {1}</a></p>'.format(
                        code_start_line, html.escape(result.error or "未知原因")
                    )
                )
        else:
            highlighted = highlight_code_html(source, code_language, dark=dark)
            parts.append(
                '<pre class="code-block language-{0}"><a name="line-{1}"></a>{2}</pre>'.format(
                    html.escape(code_language or "text"), code_start_line, highlighted
                )
            )
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
            flush_quote()
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
            flush_quote()
            table_rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
            continue
        flush_table()
        if not stripped:
            flush_list()
            flush_quote()
            continue

        heading = _HEADING_RE.match(stripped)
        if heading is not None:
            flush_list()
            flush_quote()
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
            flush_quote()
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
            flush_quote()
            parts.append('<hr id="line-{0}"/>'.format(source_line))
        elif stripped.startswith("> "):
            quote_lines.append((source_line, stripped[2:]))
        else:
            flush_quote()
            parts.append(
                '<p><a name="line-{0}" href="#line-{0}">{1}</a></p>'.format(
                    source_line, inline(stripped)
                )
            )

    flush_table()
    flush_list()
    flush_quote()
    if in_code:
        flush_code()
    css = _CSS_DARK if dark else _CSS_LIGHT
    return "<html><head><style>{0}</style></head><body>{1}</body></html>".format(
        css, "\n".join(parts)
    )


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
