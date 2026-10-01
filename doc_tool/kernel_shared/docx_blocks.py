# -*- coding: utf-8 -*-
"""共享 OOXML 输出辅助（V2.7 任务 1.4 / 设计 D1）。

正式项目构建、模板填充与评审稿此前各自实现代码块、题注、引用与分节，
同一份 Markdown 在不同入口得到不同的 OOXML。本模块集中这些输出辅助，
让三入口复用同一份实现；它只依赖 lxml，不导入任何应用层模块，
因此可以从 scripts/ 内核与 doc_tool 两侧安全导入。
"""

from __future__ import annotations

import copy as _copy
import hashlib
import re
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
RP_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"

#: 代码块等宽字体；与内核既有代码 run 保持一致。
CODE_FONT = "Consolas"
CODE_FONT_SIZE = 18  # half-points -> 9pt
CODE_BG = "F8FAFC"
CODE_BORDER = "E2E8F0"
CODE_TEXT = "1F2937"

_DTC_NSMAP = {"dtc": "urn:doc-tool:code:v1"}

ORIENT_PORTRAIT = "portrait"
ORIENT_LANDSCAPE = "landscape"

FIGURE_CAPTION_PREFIX = "图"
TABLE_CAPTION_PREFIX = "表"


def qn(tag: str) -> str:
    return W_NS + tag


def append_text(run: etree._Element, text: str) -> None:
    """写入文本：换行转 w:br，Tab 转 w:tab，保留前后空白。"""
    for part in re.split(r"(\n|\t)", text):
        if part == "\n":
            etree.SubElement(run, qn("br"))
        elif part == "\t":
            etree.SubElement(run, qn("tab"))
        elif part:
            node = etree.SubElement(run, qn("t"))
            node.text = part
            node.set(XML_NS + "space", "preserve")


def make_run(text: str = "", *, font: str = "", size: int = 0, color: str = "") -> etree._Element:
    """构造一个 w:r。"""
    run = etree.Element(qn("r"))
    if font or size or color:
        rpr = etree.SubElement(run, qn("rPr"))
        if font:
            fonts = etree.SubElement(rpr, qn("rFonts"))
            for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                fonts.set(qn(attribute), font)
        if color:
            etree.SubElement(rpr, qn("color")).set(qn("val"), color)
        if size:
            etree.SubElement(rpr, qn("sz")).set(qn("val"), str(size))
            etree.SubElement(rpr, qn("szCs")).set(qn("val"), str(size))
    append_text(run, text)
    return run


def make_code_container(
    code_lines: Sequence[str],
    *,
    max_width: int = 9360,
    background: str = CODE_BG,
    border_color: str = CODE_BORDER,
    text_color: str = CODE_TEXT,
    font: str = CODE_FONT,
    font_size: int = CODE_FONT_SIZE,
    cant_split: bool = False,
) -> etree._Element:
    """单格浅底代码容器：保留缩进/Tab/空行，长代码允许跨页分页。"""
    table = etree.Element(qn("tbl"))
    table_properties = etree.SubElement(table, qn("tblPr"))
    borders = etree.SubElement(table_properties, qn("tblBorders"))
    for edge_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = etree.SubElement(borders, qn(edge_name))
        edge.set(qn("val"), "single")
        edge.set(qn("sz"), "4")
        edge.set(qn("space"), "0")
        edge.set(qn("color"), border_color)
    width = etree.SubElement(table_properties, qn("tblW"))
    width.set(qn("w"), str(max_width))
    width.set(qn("type"), "dxa")
    layout = etree.SubElement(table_properties, qn("tblLayout"))
    layout.set(qn("type"), "fixed")
    cell_margins = etree.SubElement(table_properties, qn("tblCellMar"))
    for edge_name, value in (("top", "60"), ("left", "120"), ("bottom", "60"), ("right", "120")):
        edge = etree.SubElement(cell_margins, qn(edge_name))
        edge.set(qn("w"), value)
        edge.set(qn("type"), "dxa")

    grid = etree.SubElement(table, qn("tblGrid"))
    etree.SubElement(grid, qn("gridCol")).set(qn("w"), str(max_width))

    row = etree.SubElement(table, qn("tr"))
    if cant_split:
        etree.SubElement(etree.SubElement(row, qn("trPr")), qn("cantSplit"))
    cell = etree.SubElement(row, qn("tc"))
    cell_properties = etree.SubElement(cell, qn("tcPr"))
    cell_width = etree.SubElement(cell_properties, qn("tcW"))
    cell_width.set(qn("w"), str(max_width))
    cell_width.set(qn("type"), "dxa")
    shading = etree.SubElement(cell_properties, qn("shd"))
    shading.set(qn("val"), "clear")
    shading.set(qn("color"), "auto")
    shading.set(qn("fill"), background)

    lines = list(code_lines) if code_lines else [""]
    for index, line in enumerate(lines):
        paragraph = etree.SubElement(cell, qn("p"))
        ppr = etree.SubElement(paragraph, qn("pPr"), nsmap=_DTC_NSMAP)
        if index == 0:
            etree.SubElement(ppr, qn("keepNext")).set(qn("val"), "0")
        spacing = etree.SubElement(ppr, qn("spacing"))
        spacing.set(qn("before"), "0")
        spacing.set(qn("after"), "0")
        spacing.set(qn("line"), "240")
        spacing.set(qn("lineRule"), "auto")
        # 空行必须写成真实段落（否则 Word 会折叠），用空格保持行高。
        paragraph.append(make_run(line if line else " ", font=font, size=font_size, color=text_color))
    # 标记代码容器：校验/预览据此把代码块与用户表格区分开。
    from doc_tool.kernel_shared.code_marker import mark_code_paragraph

    mark_code_paragraph(cell.findall(qn("p"))[0])
    return table


def split_code_text(text: str) -> List[str]:
    """把代码块正文切成输出行：保留空行、Tab 与尾随空白语义。"""
    if text == "":
        return [""]
    return text.split("\n")


def make_field(instruction: str, cached: str = "", *, dirty: bool = True) -> List[etree._Element]:
    """构造域（fldChar begin + instrText + 缓存 + end）。

    返回**扁平的 run 列表**：OOXML 中 ``w:fldChar`` 必须作为 ``w:r`` 的子节点，
    而 ``w:r`` **不能嵌套 w:r**。早期实现把它们放进一个包装 ``w:r``，
    产出非法结构；Word 刷新时会修复它并拆分域代码，使 ``REF`` 无法解析。
    """
    runs: List[etree._Element] = []
    begin_run = etree.Element(qn("r"))
    begin = etree.SubElement(begin_run, qn("fldChar"))
    begin.set(qn("fldCharType"), "begin")
    if dirty:
        begin.set(qn("dirty"), "true")
    runs.append(begin_run)

    instruction_run = etree.Element(qn("r"))
    instruction_text = etree.SubElement(instruction_run, qn("instrText"))
    instruction_text.set(XML_NS + "space", "preserve")
    instruction_text.text = " {0} ".format(instruction)
    runs.append(instruction_run)

    separate_run = etree.Element(qn("r"))
    separate = etree.SubElement(separate_run, qn("fldChar"))
    separate.set(qn("fldCharType"), "separate")
    runs.append(separate_run)

    if cached != "":
        cached_run = etree.Element(qn("r"))
        cached_text = etree.SubElement(cached_run, qn("t"))
        cached_text.set(XML_NS + "space", "preserve")
        cached_text.text = cached
        runs.append(cached_run)

    end_run = etree.Element(qn("r"))
    end = etree.SubElement(end_run, qn("fldChar"))
    end.set(qn("fldCharType"), "end")
    runs.append(end_run)
    return runs


def make_caption_paragraph(
    *,
    prefix: str,
    label: str,
    number: int,
    style_id: Optional[str] = None,
    bookmark_name: str = "",
    bookmark_id: int = 0,
    field_instruction: str = "",
    align: str = "center",
) -> etree._Element:
    """生成题注段落：图 1 标题，可带书签与 SEQ 域。"""
    paragraph = etree.Element(qn("p"))
    ppr = etree.SubElement(paragraph, qn("pPr"))
    if style_id:
        etree.SubElement(ppr, qn("pStyle")).set(qn("val"), style_id)
    if align:
        etree.SubElement(ppr, qn("jc")).set(qn("val"), align)
    # 编号以 SEQ 域输出并带静态缓存值：未刷新时显示缓存编号，Word 刷新后
    # 按全文顺序重算；缓存值与构建侧写的题注文本完全一致。
    field_runs = make_field(
        instruction=field_instruction or "SEQ {0} \\* ARABIC".format(prefix or "图"),
        cached=str(number),
    )
    content_runs: List[etree._Element] = []
    if prefix:
        content_runs.append(make_run("{0} ".format(prefix)))
    content_runs.extend(field_runs)
    if label:
        content_runs.append(make_run(" {0}".format(label)))
    if bookmark_name and bookmark_id:
        # 书签包住**整条题注文本**（前缀 + 编号域 + 标签），
        # 这样 ``REF`` 取回的就是完整题注（如“表 1 用例表”）而非只有编号。
        start_node = etree.SubElement(paragraph, qn("bookmarkStart"))
        start_node.set(qn("id"), str(bookmark_id))
        start_node.set(qn("name"), bookmark_name)
        for run in content_runs:
            paragraph.append(run)
        etree.SubElement(paragraph, qn("bookmarkEnd")).set(qn("id"), str(bookmark_id))
    else:
        for run in content_runs:
            paragraph.append(run)
    return paragraph


def make_reference_runs(bookmark_name: str, cached: str, *, prefix: str = "") -> List[etree._Element]:
    """交叉引用输出：REF 域 + 静态可读缓存值（未刷新时仍可阅读）。"""
    runs: List[etree._Element] = []
    if prefix:
        runs.append(make_run(prefix))
    runs.extend(make_field("REF {0} \\h".format(bookmark_name), cached))
    return runs


def clone_section_properties(sect_pr: etree._Element, orientation: str) -> etree._Element:
    """复制模板 sectPr 并设置页面方向，保留页边距与页眉页脚引用。"""
    cloned = _copy.deepcopy(sect_pr)
    page_size = cloned.find(qn("pgSz"))
    if page_size is None:
        page_size = etree.SubElement(cloned, qn("pgSz"))
        page_size.set(qn("w"), "12240")
        page_size.set(qn("h"), "15840")
    try:
        width = int(page_size.get(qn("w"), "12240"))
        height = int(page_size.get(qn("h"), "15840"))
    except ValueError:
        width, height = 12240, 15840

    landscape = orientation == ORIENT_LANDSCAPE
    current_landscape = page_size.get(qn("orient"), ORIENT_PORTRAIT) == ORIENT_LANDSCAPE
    if landscape != current_landscape:
        page_size.set(qn("w"), str(height))
        page_size.set(qn("h"), str(width))
    page_size.set(qn("orient"), orientation)
    return cloned


def section_properties_orientation(sect_pr: etree._Element) -> str:
    page_size = sect_pr.find(qn("pgSz")) if sect_pr is not None else None
    if page_size is None:
        return ORIENT_PORTRAIT
    return page_size.get(qn("orient"), ORIENT_PORTRAIT)


def table_content_width(sect_pr: etree._Element, fallback: int = 9360) -> int:
    """按所在节版心返回表格可用宽度（twips）。"""
    if sect_pr is None:
        return fallback
    page_size = sect_pr.find(qn("pgSz"))
    if page_size is None:
        return fallback
    try:
        width = int(page_size.get(qn("w"), "12240"))
    except ValueError:
        width = 12240
    left = right = 1440
    margins = sect_pr.find(qn("pgMar"))
    if margins is not None:
        try:
            left = int(margins.get(qn("left"), "1440"))
            right = int(margins.get(qn("right"), "1440"))
        except ValueError:
            left = right = 1440
    available = width - left - right
    return available if available > 0 else fallback


def make_page_break_paragraph() -> etree._Element:
    paragraph = etree.Element(qn("p"))
    run = etree.SubElement(paragraph, qn("r"))
    etree.SubElement(run, qn("br")).set(qn("type"), "page")
    return paragraph


def fit_table_widths(widths: Sequence[int], column_count: int, available: int) -> List[int]:
    """把列宽缩放到节版心内，保持各列相对比例。"""
    values = [max(int(value), 1) for value in widths[:column_count]]
    if len(values) < column_count:
        values.extend([2400] * (column_count - len(values)))
    if available <= 0:
        return values
    total = sum(values)
    if total <= available or total <= 0:
        return values
    scale = available / float(total)
    scaled = [max(1, int(round(value * scale))) for value in values]
    overflow = sum(scaled) - available
    index = len(scaled) - 1
    while overflow > 0 and index >= 0:
        reducible = min(overflow, max(0, scaled[index] - 1))
        scaled[index] -= reducible
        overflow -= reducible
        index -= 1
    return scaled


def unique_output_ident(ident: str, seen: Dict[str, int]) -> Tuple[str, bool]:
    """输出层唯一化题注标识；返回 (最终标识, 是否被改写)。"""
    if ident not in seen:
        seen[ident] = 1
        return ident, False
    seen[ident] += 1
    return "{0}-{1}".format(ident, seen[ident]), True


def bookmark_name_for(ident: str, *, prefix: str = "cap") -> str:
    """题注标识 -> 稳定 Word 书签名。"""
    readable = re.sub(r"[^0-9A-Za-z_]+", "_", ident).strip("_")[:24] or "caption"
    digest = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:10]
    return "{0}_{1}_{2}".format(prefix, readable, digest)
