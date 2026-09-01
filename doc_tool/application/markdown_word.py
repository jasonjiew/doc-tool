# -*- coding: utf-8 -*-
"""Markdown → Word 用 HTML（含排版样式表）。

为什么不复用 ``application.content.preview.render_markdown_html``：那个渲染器是为
工作台预览服务的，会给每一块塞 ``<a name="line-N">`` 跳转锚点，导进 Word 会变成
一片无用书签；它的分块模型（``render_preview_blocks``）也没有列表、代码块与引用。
导出这条路要的是「语义干净的 HTML + 一套面向 Word 的样式表」，因此单独实现。

排版样式（按 Word 的 HTML 导入器行为取舍）：
- 中西文分设字体：中文宋体、西文 Times New Roman，正文 10.5pt（五号）、1.5 倍行距；
- 标题走 ``<h1>``~``<h6>``，Word 导入时映射到内置「标题 1~6」，保留大纲级别与目录；
- 表格统一 0.5pt 灰边框、表头浅灰底纹加粗居中；代码块等宽 + 浅底 + 细边框；
- 图片按版心宽度等比缩放（Pillow 读原尺寸），避免超出页宽被裁；
- 构建链路的排版注记（``<!-- P: -->``、``<!-- TBL: -->``、``<EMPTY_PAR/>``）对读者
  无意义，导出时整体丢弃。
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# A4 纵向：版心宽 = 21cm - 左右页边距（各 3.0cm）= 15cm。图片按此上限缩放。
PAGE_TEXT_WIDTH_MM = 150.0

_UL_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+\-#.]*)\s*$")
_IMAGE_ONLY_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+=(\d+)x(\d+))?\)\s*$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+=(\d+)x(\d+))?\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_EMPHASIS_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_HR_RE = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_EMPTY_PAR_RE = re.compile(r"^\s*<EMPTY_PAR/>\s*$")
_COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")

# mm → 屏幕像素（96dpi），用于把版心宽度换算成 img width。
_MM_TO_PX = 96.0 / 25.4

WORD_STYLE_CSS = """
@page { size: 21.0cm 29.7cm; margin: 2.54cm 3.0cm; }
html { font-family: 'Times New Roman','宋体',SimSun,serif; }
body { font-family: 'Times New Roman','宋体',SimSun,serif; font-size: 10.5pt;
       line-height: 1.5; color: #000; margin: 0; }
p { margin: 0 0 6.0pt 0; text-align: justify; orphans: 2; widows: 2; }
h1, h2, h3, h4, h5, h6 {
    font-family: '微软雅黑','黑体',SimHei,'Times New Roman',sans-serif;
    color: #1F3864; page-break-after: avoid; line-height: 1.3;
    margin: 12.0pt 0 6.0pt 0; text-align: left; }
h1 { font-size: 18pt; }
h2 { font-size: 15pt; }
h3 { font-size: 13pt; }
h4 { font-size: 12pt; color: #2E5395; }
h5 { font-size: 11pt; color: #404040; }
h6 { font-size: 10.5pt; color: #595959; }
ul, ol { margin: 0 0 6.0pt 0; padding-left: 21.0pt; }
li { margin: 0 0 3.0pt 0; line-height: 1.4; }
table { border-collapse: collapse; width: 100%; margin: 0 0 8.0pt 0; }
th, td { border: 0.5pt solid #8C8C8C; padding: 3.0pt 5.4pt; font-size: 10pt;
         line-height: 1.3; vertical-align: center; }
th { background: #E8EDF5; font-weight: bold; text-align: center;
     font-family: '微软雅黑','黑体',SimHei,sans-serif; }
tr { page-break-inside: avoid; }
pre { font-family: Consolas,'Courier New',monospace; font-size: 9pt;
      background: #F5F5F5; border: 0.5pt solid #D0D0D0; padding: 6.0pt;
      margin: 0 0 8.0pt 0; line-height: 1.2; white-space: pre-wrap;
      page-break-inside: avoid; }
code { font-family: Consolas,'Courier New',monospace; font-size: 9.5pt; }
blockquote { margin: 0 0 8.0pt 0; padding: 2.0pt 0 2.0pt 12.0pt;
             border-left: 2.25pt solid #BFBFBF; color: #404040; }
img { border: none; }
hr { border: none; border-top: 0.75pt solid #BFBFBF; margin: 12.0pt 0; }
a { color: #000; text-decoration: none; }
.caption { font-size: 9pt; color: #595959; text-align: center; margin: 0 0 8.0pt 0; }
""".strip()


@dataclass
class _ListItem:
    text: str
    indent: int
    ordered: bool


def _fit_image_width(declared: Optional[Tuple[int, int]], path: Path) -> Optional[int]:
    """返回不超过版心的显示宽度（px），拿不到尺寸时返回 None。"""
    max_px = int(PAGE_TEXT_WIDTH_MM * _MM_TO_PX)
    if declared:
        return min(max_px, declared[0])
    try:
        from PIL import Image

        with Image.open(str(path)) as image:
            width = int(image.width)
    except Exception:
        return None
    return min(max_px, width)


def _resolve_image(
    raw: str, base_dir: Path, declared: Optional[Tuple[int, int]]
) -> Tuple[Optional[str], Optional[int]]:
    """把 Markdown 里的图片引用解析成绝对 file URI + 显示宽度。

    Word 导入 HTML 时按 HTML 文件所在位置解析相对路径，而 HTML 落在临时目录，
    所以这里必须给绝对地址。远程图片原样交给 Word（内网环境通常拉不到，
    由调用方的产物说明兜底）。
    """
    if raw.startswith(("http://", "https://", "file:", "data:")):
        return raw, None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base_dir / raw.replace("\\", "/")
    if not candidate.is_file():
        return None, None
    resolved = candidate.resolve()
    return resolved.as_uri(), _fit_image_width(declared, resolved)


def _inline(text: str, base_dir: Path) -> str:
    """行内元素：先摘行内代码占位，再转义，最后按序替换图片/链接/强调。

    图片 ``<img>`` 与链接 ``<a>`` 标签生成后要占位暂存——URL 里常见下划线
    （如 ``手册_assets/tables/tbl_0001.xml``），裸留在文本里会被强调正则
    ``_..._`` 当成斜体切烂，这是复现过的真实产物损坏。
    """
    guarded: List[str] = []
    tags: List[str] = []

    def _guard_code(match: re.Match) -> str:
        guarded.append(match.group(1))
        return "\x00{0}\x00".format(len(guarded) - 1)

    def _stash(tag: str) -> str:
        tags.append(tag)
        return "\x01{0}\x01".format(len(tags) - 1)

    out = _html.escape(_CODE_RE.sub(_guard_code, text), quote=False)

    def _image(match: re.Match) -> str:
        alt = match.group(1)
        declared = None
        if match.group(3) and match.group(4):
            declared = (int(match.group(3)), int(match.group(4)))
        href, width = _resolve_image(match.group(2), base_dir, declared)
        if href is None:
            # 取不到图片：保留可见的替代文字，绝不静默丢内容。
            return "[{0}]".format(alt)
        attrs = 'src="{0}" alt="{1}"'.format(_html.escape(href, quote=True), alt)
        if width:
            attrs += ' width="{0}"'.format(width)
        return _stash("<img {0}/>".format(attrs))

    def _link(match: re.Match) -> str:
        return _stash('<a href="{0}">{1}</a>'.format(
            _html.escape(match.group(2), quote=True), match.group(1)
        ))

    out = _IMAGE_RE.sub(_image, out)
    out = _LINK_RE.sub(_link, out)
    out = _BOLD_RE.sub(lambda m: "<b>{0}</b>".format(m.group(1) or m.group(2)), out)
    out = _EMPHASIS_RE.sub(lambda m: "<i>{0}</i>".format(m.group(1) or m.group(2)), out)
    out = _STRIKE_RE.sub(lambda m: "<s>{0}</s>".format(m.group(1)), out)
    for index, tag in enumerate(tags):
        out = out.replace("\x01{0}\x01".format(index), tag)
    for index, code in enumerate(guarded):
        out = out.replace(
            "\x00{0}\x00".format(index),
            "<code>{0}</code>".format(_html.escape(code, quote=False)),
        )
    return out


def _is_separator_row(cells: Sequence[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-+:?|", cell) for cell in cells)


def _alignments(cells: Sequence[str]) -> List[str]:
    out: List[str] = []
    for cell in cells:
        if cell.startswith(":") and cell.endswith(":"):
            out.append("center")
        elif cell.endswith(":"):
            out.append("right")
        else:
            out.append("left")
    return out


def _render_table(table_lines: Sequence[str]) -> str:
    header: List[str] = []
    body: List[List[str]] = []
    aligns: List[str] = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if _is_separator_row(cells):
            aligns = _alignments(cells)
            continue
        if not header and not body:
            header = cells
        else:
            body.append(cells)
    if not header and not body:
        return ""
    if len(aligns) < len(header):
        aligns = aligns + ["left"] * (len(header) - len(aligns))
    parts: List[str] = ["<table>"]
    parts.append("<thead><tr>")
    parts.extend(
        "<th>{0}</th>".format(_inline(cell, Path())) for cell in header
    )
    parts.append("</tr></thead>")
    if body:
        parts.append("<tbody>")
        for row in body:
            parts.append("<tr>")
            for index, cell in enumerate(row):
                align = aligns[index] if index < len(aligns) else "left"
                style = "" if align == "left" else ' style="text-align:{0}"'.format(align)
                parts.append("<td{0}>{1}</td>".format(style, _inline(cell, Path())))
            parts.append("</tr>")
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)


def _render_list(items: Sequence[_ListItem], base_dir: Path) -> str:
    """渲染同层列表；比当前层更深的连续项作为上一项的嵌套列表递归下去。"""
    if not items:
        return ""
    top = min(item.indent for item in items)
    tag = "ol" if items[0].ordered else "ul"
    out: List[str] = ["<{0}>".format(tag)]
    index = 0
    while index < len(items):
        item = items[index]
        if item.indent > top:
            group: List[_ListItem] = []
            while index < len(items) and items[index].indent > top:
                group.append(items[index])
                index += 1
            # 嵌套块必然紧跟在刚输出的一个 <li>…</li> 之后。
            out[-1] = out[-1][: -len("</li>")] + _render_list(group, base_dir) + "</li>"
            continue
        out.append("<li>{0}</li>".format(_inline(item.text, base_dir)))
        index += 1
    out.append("</{0}>".format(tag))
    return "".join(out)


def read_markdown_text(path: Path) -> str:
    """读取 Markdown 源文本：UTF-8（含 BOM）优先，失败回退 GBK。

    与 ``text_convert.read_text_file`` 同一策略——绝不 ``errors="replace"``
    静默产出乱码（GBK 的 .md 曾被替换成乱码继续转换）；两种编码都解不出时
    抛 ``TextEncodingError``（E6007），由调用方折算成单文件失败。
    """
    from doc_tool.application.text_convert import read_text_file

    return read_text_file(path)


def markdown_to_word_html(md_text: str, base_dir: Path, title: str = "") -> str:
    """把 Markdown 渲染成供 Word 导入的完整 HTML 文档（内嵌排版样式）。"""
    base_dir = Path(base_dir)
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body: List[str] = []
    paragraph: List[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(part.strip() for part in paragraph).strip()
            del paragraph[:]
            if text:
                body.append("<p>{0}</p>".format(_inline(text, base_dir)))

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped or _EMPTY_PAR_RE.match(raw):
            flush_paragraph()
            index += 1
            continue
        if _COMMENT_RE.match(raw):
            flush_paragraph()
            index += 1
            continue

        fence = _FENCE_RE.match(raw)
        if fence:
            flush_paragraph()
            marker = fence.group(1)[:3]
            language = fence.group(2)
            code: List[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(marker):
                code.append(lines[index])
                index += 1
            index += 1  # 跳过结束围栏；缺失时按文件尾处理
            attrs = ' class="language-{0}"'.format(language) if language else ""
            # 行之间用 <br/>：实测裸换行会被 Word 拆成多个段落，块内出现段间距。
            body.append("<pre><code{0}>{1}</code></pre>".format(
                attrs,
                "<br/>".join(_html.escape(line, quote=False) for line in code),
            ))
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            body.append("<h{0}>{1}</h{0}>".format(
                level, _inline(heading.group(2), base_dir)))
            index += 1
            continue

        if _HR_RE.match(stripped) and "|" not in stripped:
            flush_paragraph()
            body.append("<hr/>")
            index += 1
            continue

        if stripped.startswith("|"):
            flush_paragraph()
            table_lines: List[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            table = _render_table(table_lines)
            if table:
                body.append(table)
            continue

        if _QUOTE_RE.match(raw):
            flush_paragraph()
            quoted: List[str] = []
            while index < len(lines):
                match = _QUOTE_RE.match(lines[index])
                if match is None:
                    break
                quoted.append(match.group(1))
                index += 1
            body.append("<blockquote><p>{0}</p></blockquote>".format(
                _inline(" ".join(part.strip() for part in quoted).strip(), base_dir)))
            continue

        if _UL_RE.match(raw) or _OL_RE.match(raw):
            flush_paragraph()
            items: List[_ListItem] = []
            while index < len(lines):
                bullet = _UL_RE.match(lines[index])
                number = _OL_RE.match(lines[index]) if bullet is None else None
                if bullet is None and number is None:
                    break
                match = bullet or number
                items.append(_ListItem(
                    text=match.group(3),
                    indent=len(match.group(1).replace("\t", "    ")),
                    ordered=number is not None,
                ))
                index += 1
            body.append(_render_list(items, base_dir))
            continue

        image_only = _IMAGE_ONLY_RE.match(stripped)
        if image_only:
            flush_paragraph()
            alt = image_only.group(1)
            declared = None
            if image_only.group(3) and image_only.group(4):
                declared = (int(image_only.group(3)), int(image_only.group(4)))
            href, width = _resolve_image(image_only.group(2), base_dir, declared)
            if href is None:
                body.append("<p>{0}</p>".format(
                    _html.escape("[{0}]".format(alt) if alt else stripped, quote=False)))
            else:
                attrs = 'src="{0}" alt="{1}"'.format(_html.escape(href, quote=True), alt)
                if width:
                    attrs += ' width="{0}"'.format(width)
                body.append(
                    '<p style="text-align:center"><img {0}/></p>'.format(attrs)
                )
                if alt:
                    body.append('<p class="caption">{0}</p>'.format(alt))
            index += 1
            continue

        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    head = "<title>{0}</title>".format(_html.escape(title, quote=True)) if title else ""
    return (
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:w="urn:schemas-microsoft-com:office:word" '
        'xmlns="http://www.w3.org/TR/REC-html40">'
        '<head>{head}<meta charset="utf-8"/>'
        "<style>{css}</style></head><body>{body}</body></html>"
    ).format(head=head, css=WORD_STYLE_CSS, body="".join(body))


def markdown_word_summary(md_text: str) -> str:
    """导出前的一句话摘要（标题/表格行/代码块/图片），供界面回显体量。"""
    lines = md_text.splitlines()
    headings = sum(1 for line in lines if _HEADING_RE.match(line.strip()))
    table_rows = sum(1 for line in lines if line.strip().startswith("|"))
    blocks = sum(1 for line in lines if _FENCE_RE.match(line)) // 2
    images = len(_IMAGE_RE.findall(md_text))
    return "标题 {0} 个、表格 {1} 行、代码块 {2} 个、图片 {3} 张".format(
        headings, table_rows, blocks, images
    )
