# -*- coding: utf-8 -*-
"""纯 Python OOXML 评审稿与评审纪要构建器（零 Word 依赖）。

提供：
1. ``build_review_draft_docx``：组装改动章节会议评审稿（去除 w:numPr 杜绝跳号、
   改动摘要框、文末附带空白 9 列表格）。
2. ``build_review_minutes_docx``：导出横向 A4 标准评审纪要 DOCX 与配套 Markdown。
3. ``extract_comments_from_docx``：从 DOCX 中反向提取末尾评审表格（支持 Word 与 WPS）。
4. ``generate_evidence_for_comment``：基于基线与当前 Markdown 差异自动计算行级证据。
"""

from __future__ import annotations

import difflib
import io
import os
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from lxml import etree

from doc_tool.application.review.review_store import ReviewComment
from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe, read_docx_package

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"


def qn(tag: str) -> str:
    return W_NS + tag


# 常用表头别名映射 -> 字段名
HEADER_MAPPING: Dict[str, str] = {
    "序号": "seq",
    "编号": "seq",
    "提出人": "author",
    "评审人": "author",
    "作者": "author",
    "提出者": "author",
    "章节": "chapter_no",
    "章节号": "chapter_no",
    "关联章节": "chapter_no",
    "评审问题": "text",
    "问题": "text",
    "问题描述": "text",
    "意见": "text",
    "评审意见": "text",
    "意见描述": "text",
    "责任人": "assignee",
    "整改人": "assignee",
    "落实人": "assignee",
    "计划完成时间": "planned_date",
    "完成时间": "planned_date",
    "计划时间": "planned_date",
    "更改确认": "confirm_status",
    "确认": "confirm_status",
    "状态": "confirm_status",
    "确认状态": "confirm_status",
    "评审记录": "review_note",
    "讨论结论": "review_note",
    "会议记录": "review_note",
    "更改结果与证据": "evidence",
    "更改结果": "evidence",
    "修改证据": "evidence",
    "证据": "evidence",
    "遗留问题": "open_issue",
    "遗留项": "open_issue",
}


def _match_header_field(text: str) -> Optional[str]:
    """根据表头文本匹配字段名，精确匹配优先，按关键词长度降序模糊匹配。"""
    normalized = text.replace(" ", "").replace("\n", "").strip()
    if not normalized:
        return None
    if normalized in HEADER_MAPPING:
        return HEADER_MAPPING[normalized]
    # 关键词降序匹配，防止“问题”优先于“遗留问题”或“评审问题”命中
    for kw in sorted(HEADER_MAPPING.keys(), key=len, reverse=True):
        if kw in normalized:
            return HEADER_MAPPING[kw]
    return None


def _append_text_run(
    paragraph: etree._Element,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    strike: bool = False,
    color: Optional[str] = None,
    font_size: Optional[int] = None,
    font_name: str = "Microsoft YaHei",
) -> etree._Element:
    """向段落追加一个带格式的 run。"""
    run = etree.SubElement(paragraph, qn("r"))
    rpr = etree.SubElement(run, qn("rPr"))
    if bold:
        etree.SubElement(rpr, qn("b"))
    if italic:
        etree.SubElement(rpr, qn("i"))
    if strike:
        etree.SubElement(rpr, qn("strike"))
    if color:
        etree.SubElement(rpr, qn("color")).set(qn("val"), color)
    if font_size is not None:
        etree.SubElement(rpr, qn("sz")).set(qn("val"), str(font_size))
    if font_name:
        rfonts = etree.SubElement(rpr, qn("rFonts"))
        rfonts.set(qn("ascii"), font_name)
        rfonts.set(qn("hAnsi"), font_name)
        rfonts.set(qn("eastAsia"), font_name)

    parts = re.split(r"(\n|\t)", text)
    for part in parts:
        if part == "\n":
            etree.SubElement(run, qn("br"))
        elif part == "\t":
            etree.SubElement(run, qn("tab"))
        elif part:
            t = etree.SubElement(run, qn("t"))
            t.text = part
            t.set(XML_NS + "space", "preserve")
    return run


INLINE_MD_PATTERN = re.compile(
    r"(\*\*(?P<bold_text>.+?)\*\*)|"
    r"((?<!\*)\*(?!\*)(?P<italic_text>.+?)(?<!\*)\*(?!\*))|"
    r"(`(?P<code_text>[^`]+)`)|"
    r"(\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)]+)\))|"
    r"(<br\s*/?>)"
)


def _append_markdown_inline_runs(
    paragraph: etree._Element,
    text: str,
    *,
    default_bold: bool = False,
    default_italic: bool = False,
    default_strike: bool = False,
    default_color: Optional[str] = None,
    default_font_size: Optional[int] = None,
    default_font_name: str = "Microsoft YaHei",
) -> None:
    """解析行内 Markdown 标记（加粗/斜体/行内代码/超链接/<br>换行）并向段落追加 run。"""
    if not text:
        return

    cursor = 0
    for match in INLINE_MD_PATTERN.finditer(text):
        start, end = match.span()
        if start > cursor:
            plain_part = text[cursor:start]
            _append_text_run(
                paragraph,
                plain_part,
                bold=default_bold,
                italic=default_italic,
                strike=default_strike,
                color=default_color,
                font_size=default_font_size,
                font_name=default_font_name,
            )

        gd = match.groupdict()
        bold_text = gd.get("bold_text")
        italic_text = gd.get("italic_text")
        code_text = gd.get("code_text")
        link_text = gd.get("link_text")

        if bold_text is not None:
            _append_text_run(
                paragraph,
                bold_text,
                bold=True,
                italic=default_italic,
                strike=default_strike,
                color=default_color,
                font_size=default_font_size,
                font_name=default_font_name,
            )
        elif italic_text is not None:
            _append_text_run(
                paragraph,
                italic_text,
                bold=default_bold,
                italic=True,
                strike=default_strike,
                color=default_color,
                font_size=default_font_size,
                font_name=default_font_name,
            )
        elif code_text is not None:
            _append_text_run(
                paragraph,
                code_text,
                bold=default_bold,
                strike=default_strike,
                font_name="Consolas",
                color="B91C1C",
                font_size=(default_font_size - 2) if default_font_size else 18,
            )
        elif link_text is not None:
            _append_text_run(
                paragraph,
                link_text,
                bold=default_bold,
                italic=default_italic,
                strike=default_strike,
                color="2563EB",
                font_size=default_font_size,
                font_name=default_font_name,
            )
        else:  # <br>
            run = etree.SubElement(paragraph, qn("r"))
            etree.SubElement(run, qn("br"))

        cursor = end

    if cursor < len(text):
        _append_text_run(
            paragraph,
            text[cursor:],
            bold=default_bold,
            italic=default_italic,
            strike=default_strike,
            color=default_color,
            font_size=default_font_size,
            font_name=default_font_name,
        )


def _render_diff_text(
    paragraph: etree._Element,
    old_text: str,
    new_text: str,
    *,
    default_bold: bool = False,
    default_italic: bool = False,
    default_font_size: Optional[int] = None,
    default_font_name: str = "Microsoft YaHei",
) -> None:
    """对单行内文本做细粒度差异比对：未变动文字正常显示，旧文字删除线灰色，新文字加粗标红。"""
    old_tokens = re.findall(r"[\u4e00-\u9fa5]|\w+|[^\w\s]|\s+", old_text)
    new_tokens = re.findall(r"[\u4e00-\u9fa5]|\w+|[^\w\s]|\s+", new_text)
    sm = difflib.SequenceMatcher(None, old_tokens, new_tokens)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        old_part = "".join(old_tokens[i1:i2])
        new_part = "".join(new_tokens[j1:j2])

        if tag == "equal":
            _append_markdown_inline_runs(
                paragraph,
                new_part,
                default_bold=default_bold,
                default_italic=default_italic,
                default_font_size=default_font_size,
                default_font_name=default_font_name,
            )
        elif tag == "insert":
            _append_markdown_inline_runs(
                paragraph,
                new_part,
                default_bold=True,
                default_color="DC2626",
                default_font_size=default_font_size,
                default_font_name=default_font_name,
            )
        elif tag == "replace":
            _append_text_run(
                paragraph,
                old_part,
                strike=True,
                color="9CA3AF",
                font_size=default_font_size,
                font_name=default_font_name,
            )
            _append_markdown_inline_runs(
                paragraph,
                new_part,
                default_bold=True,
                default_color="DC2626",
                default_font_size=default_font_size,
                default_font_name=default_font_name,
            )
        elif tag == "delete":
            _append_text_run(
                paragraph,
                old_part,
                strike=True,
                color="EF4444",
                font_size=default_font_size,
                font_name=default_font_name,
            )


def _build_annotated_diff_lines(
    base_content: Optional[str], curr_content: str
) -> List[Tuple[str, str, Optional[str]]]:
    """生成带差异标注的行列表：[(line_text, diff_type, old_line_or_none)]。
    diff_type: 'equal' | 'insert' | 'replace' | 'delete'
    """
    if not base_content:
        return [(line, "equal", None) for line in curr_content.splitlines()]

    base_lines = base_content.splitlines()
    curr_lines = curr_content.splitlines()

    sm = difflib.SequenceMatcher(None, base_lines, curr_lines)
    annotated: List[Tuple[str, str, Optional[str]]] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for l in curr_lines[j1:j2]:
                annotated.append((l, "equal", None))
        elif tag == "insert":
            for l in curr_lines[j1:j2]:
                annotated.append((l, "insert", None))
        elif tag == "replace":
            old_chunk = base_lines[i1:i2]
            new_chunk = curr_lines[j1:j2]
            if len(old_chunk) == len(new_chunk):
                for old_l, new_l in zip(old_chunk, new_chunk):
                    annotated.append((new_l, "replace", old_l))
            else:
                for old_l in old_chunk:
                    annotated.append((old_l, "delete", None))
                for new_l in new_chunk:
                    annotated.append((new_l, "insert", None))
        elif tag == "delete":
            for old_l in base_lines[i1:i2]:
                annotated.append((old_l, "delete", None))

    return annotated


def _create_paragraph(
    text: str = "",
    *,
    style_id: Optional[str] = None,
    align: Optional[str] = None,
    bold: bool = False,
    italic: bool = False,
    color: Optional[str] = None,
    font_size: Optional[int] = None,
    font_name: str = "Microsoft YaHei",
    spacing_before: Optional[int] = None,
    spacing_after: Optional[int] = None,
    line_spacing: Optional[int] = None,
) -> etree._Element:
    """构建独立段落。"""
    p = etree.Element(qn("p"))
    ppr = etree.SubElement(p, qn("pPr"))
    if style_id:
        etree.SubElement(ppr, qn("pStyle")).set(qn("val"), style_id)
    if align:
        etree.SubElement(ppr, qn("jc")).set(qn("val"), align)
    if spacing_before is not None or spacing_after is not None or line_spacing is not None:
        sp = etree.SubElement(ppr, qn("spacing"))
        if spacing_before is not None:
            sp.set(qn("before"), str(spacing_before))
        if spacing_after is not None:
            sp.set(qn("after"), str(spacing_after))
        if line_spacing is not None:
            sp.set(qn("line"), str(line_spacing))
            sp.set(qn("lineRule"), "auto")

    if text:
        _append_text_run(
            p,
            text,
            bold=bold,
            italic=italic,
            color=color,
            font_size=font_size,
            font_name=font_name,
        )
    return p


def _apply_table_borders(tbl_pr: etree._Element, color: str = "D1D5DB", sz: str = "4") -> None:
    """为表格添加全网格边框。"""
    borders = etree.SubElement(tbl_pr, qn("tblBorders"))
    for edge_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = etree.SubElement(borders, qn(edge_name))
        edge.set(qn("val"), "single")
        edge.set(qn("sz"), sz)
        edge.set(qn("space"), "0")
        edge.set(qn("color"), color)


def _create_cell(
    text: str,
    width_dxa: int,
    *,
    bold: bool = False,
    bg_color: Optional[str] = None,
    text_color: Optional[str] = None,
    align: str = "left",
    valign: str = "center",
    font_size: int = 18,  # 9pt
) -> etree._Element:
    """构建单元格。"""
    tc = etree.Element(qn("tc"))
    tc_pr = etree.SubElement(tc, qn("tcPr"))
    tc_w = etree.SubElement(tc_pr, qn("tcW"))
    tc_w.set(qn("w"), str(width_dxa))
    tc_w.set(qn("type"), "dxa")
    if bg_color:
        shd = etree.SubElement(tc_pr, qn("shd"))
        shd.set(qn("val"), "clear")
        shd.set(qn("color"), "auto")
        shd.set(qn("fill"), bg_color)
    if valign:
        etree.SubElement(tc_pr, qn("vAlign")).set(qn("val"), valign)

    p = _create_paragraph(
        text,
        align=align,
        bold=bold,
        color=text_color,
        font_size=font_size,
    )
    tc.append(p)
    return tc


# =========================================================================
# 1. 会议评审稿生成（纯内核装配，无 Word 依赖）
# =========================================================================

def build_review_draft_docx(
    *,
    template_path: Optional[Union[str, Path]],
    output_path: Union[str, Path],
    document_name: str,
    document_version: str,
    changed_items: Sequence[Dict],
    baseline_time: str = "",
    include_blank_table: bool = True,
    blank_rows_count: int = 10,
    heading_style: str = "1",
    highlight_changes: bool = True,
) -> Path:
    """生成会议评审稿 Word 文档。

    仅包含勾选的改动章节，移除 w:numPr 保证文字编号不跳号，正文每节上方
    带有浅灰改动摘要框，支持改动部分红色高亮对照，文末附带空白 9 列表格。
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    items: Dict[str, bytes] = {}
    if template_path and Path(template_path).exists():
        try:
            with read_docx_package(template_path) as package:
                items = package.read_all()
        except (OOXMLSecurityError, OSError):
            items = {}

    if not items or "word/document.xml" not in items:
        # 回退创建基础 DOCX 包
        items = _create_blank_package()

    doc_xml_bytes = items["word/document.xml"]
    doc_tree = parse_xml_safe(doc_xml_bytes, "word/document.xml")
    body = doc_tree.find(qn("body"))
    if body is None:
        body = etree.SubElement(doc_tree, qn("body"))

    sect_pr = body.find(qn("sectPr"))
    if sect_pr is not None:
        sect_pr_copy = etree.fromstring(etree.tostring(sect_pr))
    else:
        sect_pr_copy = etree.Element(qn("sectPr"))
        pg_sz = etree.SubElement(sect_pr_copy, qn("pgSz"))
        pg_sz.set(qn("w"), "11906")
        pg_sz.set(qn("h"), "16838")
        pg_mar = etree.SubElement(sect_pr_copy, qn("pgMar"))
        for attr, val in (("top", "1440"), ("bottom", "1440"), ("left", "1440"), ("right", "1440")):
            pg_mar.set(qn(attr), val)

    body.clear()

    # 1. 顶部标题说明区
    title_p = _create_paragraph(
        f"《{document_name} - 修订评审稿》",
        align="center",
        bold=True,
        font_size=36,  # 18pt
        spacing_before=240,
        spacing_after=120,
    )
    body.append(title_p)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    sub_text = (
        f"文档版本: v{document_version}   |   生成时间: {now_str}   |   "
        f"基线说明: {baseline_time or '已冻结基线'}"
    )
    body.append(_create_paragraph(sub_text, align="center", color="6B7280", font_size=20, spacing_after=180))

    hint_text = (
        "【说明】本评审稿仅提取本次发生修改/新增的章节内容及文末空白评审表，供技术评审会议讨论使用；"
        "章节号保持原文不变，会议提出的意见可直接在文末表格录入。"
    )
    if highlight_changes:
        hint_text += (
            "【修订对照】改动内容已用红色字体突出显示（新增与修改内容为加粗红字，被替换的旧文字带删除线），"
            "便于评审人员快速定位和检视变动点。"
        )
    hint_p = _create_paragraph(
        hint_text,
        color="374151",
        italic=True,
        font_size=20,
        spacing_after=240,
    )
    body.append(hint_p)

    # 改动章节速查清单表
    if changed_items:
        body.append(_create_paragraph("本次评审改动章节清单：", bold=True, font_size=22, spacing_after=80))
        overview_tbl = etree.Element(qn("tbl"))
        tbl_pr = etree.SubElement(overview_tbl, qn("tblPr"))
        _apply_table_borders(tbl_pr, "CBD5E1", "4")
        etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), "9600")
        etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")

        h_tr = etree.SubElement(overview_tbl, qn("tr"))
        h_tr_pr = etree.SubElement(h_tr, qn("trPr"))
        etree.SubElement(h_tr_pr, qn("tblHeader"))
        etree.SubElement(h_tr_pr, qn("cantSplit"))
        h_tr.append(_create_cell("序号", 800, bold=True, bg_color="F1F5F9", align="center"))
        h_tr.append(_create_cell("章节编号与标题", 4800, bold=True, bg_color="F1F5F9", align="left"))
        h_tr.append(_create_cell("变更类型", 1600, bold=True, bg_color="F1F5F9", align="center"))
        h_tr.append(_create_cell("变动规模", 2400, bold=True, bg_color="F1F5F9", align="center"))

        status_labels = {
            "added": "新增章节",
            "modified": "内容修改",
            "deleted": "章节删除",
            "normal": "未变动",
        }
        for seq_i, item in enumerate(changed_items, 1):
            r_tr = etree.SubElement(overview_tbl, qn("tr"))
            r_tr_pr = etree.SubElement(r_tr, qn("trPr"))
            etree.SubElement(r_tr_pr, qn("cantSplit"))
            st = item.get("status", "modified")
            st_text = status_labels.get(st, st)
            ch_no = item.get("chapter_no", "")
            title = item.get("title", "")
            diff = item.get("diff_summary", "")

            r_tr.append(_create_cell(str(seq_i), 800, align="center"))
            r_tr.append(_create_cell(f"{ch_no} {title}".strip(), 4800, align="left"))
            r_tr.append(_create_cell(st_text, 1600, align="center"))
            r_tr.append(_create_cell(diff or "-", 2400, align="center"))

        body.append(overview_tbl)
        body.append(_create_paragraph("", spacing_after=240))

    # 2. 改动章节正文装配
    for item in changed_items:
        ch_no = item.get("chapter_no", "")
        title = item.get("title", "")
        status = item.get("status", "modified")
        diff_summary = item.get("diff_summary", "")
        rel_path = item.get("rel_path", "")
        content = item.get("markdown_content", "")
        base_content = item.get("base_content")

        # 章节标题：固定文字编号，关闭 Word w:numPr
        full_title = f"{ch_no} {title}".strip()
        heading_p = _create_paragraph(
            full_title,
            style_id=heading_style,
            bold=True,
            font_size=28,  # 14pt
            spacing_before=280,
            spacing_after=100,
        )
        body.append(heading_p)

        # 改动摘要框（浅灰底色 callout box）
        summary_tbl = etree.Element(qn("tbl"))
        tbl_pr = etree.SubElement(summary_tbl, qn("tblPr"))
        _apply_table_borders(tbl_pr, "CBD5E1", "4")
        etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), "8600")
        etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")
        row = etree.SubElement(summary_tbl, qn("tr"))
        summary_text = (
            f"【改动摘要】状态: {status_labels.get(status, status)}   |   "
            f"变动: {diff_summary or '内容已更新'}   |   "
            f"源文件: {rel_path}"
        )
        row.append(_create_cell(summary_text, 8600, bg_color="F8FAFC", text_color="4B5563", font_size=18))
        body.append(summary_tbl)
        body.append(_create_paragraph("", spacing_after=80))

        # 正文内容
        if status == "deleted":
            del_note = _create_paragraph(
                "【注】本节在当前最新版本中已被删除。以下为基线快照备份内容，供评审人员确认删除合理性：",
                color="DC2626",
                italic=True,
                font_size=18,
            )
            body.append(del_note)

        # Markdown 正文渲染与改动对比
        _render_markdown_lines(
            body,
            content,
            base_content=base_content,
            is_entirely_new=(status == "added"),
            highlight_changes=highlight_changes,
        )
        body.append(_create_paragraph("", spacing_after=200))

    # 3. 附录：空白评审记录表
    if include_blank_table:
        body.append(_create_paragraph("附录：评审意见记录表", bold=True, font_size=28, spacing_before=360, spacing_after=80))
        body.append(
            _create_paragraph(
                "（供会议现场评委与记录员就地填写，会议结束后可直接在 doc-tool 点击「导入 Word 评审表」自动提取）",
                color="6B7280",
                italic=True,
                font_size=18,
                spacing_after=120,
            )
        )
        blank_table = _build_blank_review_table(blank_rows_count)
        body.append(blank_table)

    body.append(sect_pr_copy)

    # 序列化写回 ZIP
    items["word/document.xml"] = etree.tostring(doc_tree, encoding="utf-8", xml_declaration=True)
    _write_docx_zip(items, output_path)
    return output_path


def _parse_md_table_rows(lines: List[str]) -> List[List[str]]:
    """解析 Markdown 表格行为二维单元格文本列表，自动过滤分隔线行。"""
    rows: List[List[str]] = []
    for line in lines:
        content = line.strip()
        if content.startswith("|"):
            content = content[1:]
        if content.endswith("|"):
            content = content[:-1]
        cells = [c.strip() for c in content.split("|")]
        # 过滤分隔行形如 :--- 或 :---: 或 ---
        if cells and all(re.match(r"^:?-+:?$", c) for c in cells if c):
            continue
        rows.append(cells)
    if not rows:
        return []
    max_w = max(len(r) for r in rows)
    return [r + [""] * (max_w - len(r)) for r in rows]


def _create_markdown_table(
    rows: List[List[str]],
    custom_col_widths: Optional[Sequence[int]] = None,
    max_width: int = 9600,
) -> etree._Element:
    """将 Markdown 表格渲染为美观的标准 Word 表格。"""
    if not rows:
        return etree.Element(qn("tbl"))
    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return etree.Element(qn("tbl"))

    if custom_col_widths and len(custom_col_widths) >= col_count:
        raw_sum = sum(custom_col_widths[:col_count]) or 1
        col_widths = [int(w * max_width / raw_sum) for w in custom_col_widths[:col_count]]
        col_widths[-1] += max_width - sum(col_widths)
    else:
        col_w = max_width // col_count
        col_widths = [col_w] * col_count
        col_widths[-1] += max_width - sum(col_widths)

    table = etree.Element(qn("tbl"))
    tbl_pr = etree.SubElement(table, qn("tblPr"))
    _apply_table_borders(tbl_pr, "CBD5E1", "4")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), str(max_width))
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")

    grid = etree.SubElement(table, qn("tblGrid"))
    for w in col_widths:
        etree.SubElement(grid, qn("gridCol")).set(qn("w"), str(w))

    for row_idx, row_cells in enumerate(rows):
        tr = etree.SubElement(table, qn("tr"))
        tr_pr = etree.SubElement(tr, qn("trPr"))
        etree.SubElement(tr_pr, qn("cantSplit"))
        is_header = (row_idx == 0)
        if is_header:
            etree.SubElement(tr_pr, qn("tblHeader"))

        bg = "F1F5F9" if is_header else ("FFFFFF" if row_idx % 2 != 0 else "F8FAFC")
        for col_idx in range(col_count):
            cell_text = row_cells[col_idx].strip() if col_idx < len(row_cells) else ""
            tc = etree.SubElement(tr, qn("tc"))
            tc_pr = etree.SubElement(tc, qn("tcPr"))
            etree.SubElement(tc_pr, qn("tcW")).set(qn("w"), str(col_widths[col_idx]))
            etree.SubElement(tc_pr, qn("tcW")).set(qn("type"), "dxa")
            if bg:
                shd = etree.SubElement(tc_pr, qn("shd"))
                shd.set(qn("val"), "clear")
                shd.set(qn("color"), "auto")
                shd.set(qn("fill"), bg)

            # 单元格内边距
            tc_mar = etree.SubElement(tc_pr, qn("tcMar"))
            for edge, val in (("top", "120"), ("bottom", "120"), ("left", "160"), ("right", "160")):
                m = etree.SubElement(tc_mar, qn(edge))
                m.set(qn("w"), val)
                m.set(qn("type"), "dxa")

            p = etree.SubElement(tc, qn("p"))
            ppr = etree.SubElement(p, qn("pPr"))
            sp = etree.SubElement(ppr, qn("spacing"))
            sp.set(qn("before"), "0")
            sp.set(qn("after"), "0")
            sp.set(qn("line"), "240")
            sp.set(qn("lineRule"), "auto")

            align = "center" if is_header else "left"
            jc = etree.SubElement(ppr, qn("jc"))
            jc.set(qn("val"), align)

            _append_markdown_inline_runs(
                p,
                cell_text,
                default_bold=is_header,
                default_font_size=19 if is_header else 18,
            )

    return table


def _build_diff_markdown_table(
    table_annotated_lines: List[Tuple[str, str, Optional[str]]],
    custom_col_widths: Optional[Sequence[int]] = None,
    max_width: int = 9600,
) -> Optional[etree._Element]:
    """解析表格行（包含差异状态）并生成带差异标红的 Word 表格。"""
    rows_data: List[Tuple[List[str], str, Optional[List[str]]]] = []

    for raw_l, diff_type, old_l in table_annotated_lines:
        content = raw_l.strip()
        if content.startswith("|"):
            content = content[1:]
        if content.endswith("|"):
            content = content[:-1]
        cells = [c.strip() for c in content.split("|")]
        if cells and all(re.match(r"^:?-+:?$", c) for c in cells if c):
            continue

        old_cells = None
        if diff_type == "replace" and old_l and old_l.strip().startswith("|"):
            o_content = old_l.strip()
            if o_content.startswith("|"):
                o_content = o_content[1:]
            if o_content.endswith("|"):
                o_content = o_content[:-1]
            old_cells = [c.strip() for c in o_content.split("|")]

        rows_data.append((cells, diff_type, old_cells))

    if not rows_data:
        return None

    col_count = max(len(r[0]) for r in rows_data)
    if col_count == 0:
        return None

    if custom_col_widths and len(custom_col_widths) >= col_count:
        raw_sum = sum(custom_col_widths[:col_count]) or 1
        col_widths = [int(w * max_width / raw_sum) for w in custom_col_widths[:col_count]]
        col_widths[-1] += max_width - sum(col_widths)
    else:
        col_w = max_width // col_count
        col_widths = [col_w] * col_count
        col_widths[-1] += max_width - sum(col_widths)

    table = etree.Element(qn("tbl"))
    tbl_pr = etree.SubElement(table, qn("tblPr"))
    _apply_table_borders(tbl_pr, "CBD5E1", "4")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), str(max_width))
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")

    grid = etree.SubElement(table, qn("tblGrid"))
    for w in col_widths:
        etree.SubElement(grid, qn("gridCol")).set(qn("w"), str(w))

    for row_idx, (row_cells, diff_type, old_cells) in enumerate(rows_data):
        tr = etree.SubElement(table, qn("tr"))
        tr_pr = etree.SubElement(tr, qn("trPr"))
        etree.SubElement(tr_pr, qn("cantSplit"))
        is_header = (row_idx == 0)
        if is_header:
            etree.SubElement(tr_pr, qn("tblHeader"))

        # 新增行浅红高亮背景，普通行斑马纹
        if diff_type == "insert":
            bg = "FEF2F2"
        elif is_header:
            bg = "F1F5F9"
        else:
            bg = "FFFFFF" if row_idx % 2 != 0 else "F8FAFC"

        for col_idx in range(col_count):
            cell_text = row_cells[col_idx].strip() if col_idx < len(row_cells) else ""
            old_cell_text = old_cells[col_idx].strip() if old_cells and col_idx < len(old_cells) else ""

            tc = etree.SubElement(tr, qn("tc"))
            tc_pr = etree.SubElement(tc, qn("tcPr"))
            etree.SubElement(tc_pr, qn("tcW")).set(qn("w"), str(col_widths[col_idx]))
            etree.SubElement(tc_pr, qn("tcW")).set(qn("type"), "dxa")
            if bg:
                shd = etree.SubElement(tc_pr, qn("shd"))
                shd.set(qn("val"), "clear")
                shd.set(qn("color"), "auto")
                shd.set(qn("fill"), bg)

            tc_mar = etree.SubElement(tc_pr, qn("tcMar"))
            for edge, val in (("top", "120"), ("bottom", "120"), ("left", "160"), ("right", "160")):
                m = etree.SubElement(tc_mar, qn(edge))
                m.set(qn("w"), val)
                m.set(qn("type"), "dxa")

            p = etree.SubElement(tc, qn("p"))
            ppr = etree.SubElement(p, qn("pPr"))
            sp = etree.SubElement(ppr, qn("spacing"))
            sp.set(qn("before"), "0")
            sp.set(qn("after"), "0")
            sp.set(qn("line"), "240")
            sp.set(qn("lineRule"), "auto")

            align = "center" if is_header else "left"
            jc = etree.SubElement(ppr, qn("jc"))
            jc.set(qn("val"), align)

            if diff_type == "insert":
                _append_markdown_inline_runs(
                    p, cell_text, default_bold=True, default_color="DC2626", default_font_size=19 if is_header else 18
                )
            elif diff_type == "replace" and old_cell_text and old_cell_text != cell_text:
                _render_diff_text(p, old_cell_text, cell_text, default_bold=is_header, default_font_size=19 if is_header else 18)
            else:
                _append_markdown_inline_runs(
                    p, cell_text, default_bold=is_header, default_font_size=19 if is_header else 18
                )

    return table


def _create_code_block_box(code_lines: List[str], max_width: int = 9600, is_new: bool = False) -> etree._Element:
    """为多行代码块构建专用代码框（等宽字体、浅灰背景与精细边框）。"""
    border_color = "F87171" if is_new else "E2E8F0"
    bg_color = "FEF2F2" if is_new else "F8FAFC"
    text_color = "DC2626" if is_new else "1F2937"

    table = etree.Element(qn("tbl"))
    tbl_pr = etree.SubElement(table, qn("tblPr"))
    _apply_table_borders(tbl_pr, border_color, "4")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), str(max_width))
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")

    tr = etree.SubElement(table, qn("tr"))
    tr_pr = etree.SubElement(tr, qn("trPr"))
    etree.SubElement(tr_pr, qn("cantSplit"))

    tc = etree.SubElement(tr, qn("tc"))
    tc_pr = etree.SubElement(tc, qn("tcPr"))
    etree.SubElement(tc_pr, qn("tcW")).set(qn("w"), str(max_width))
    etree.SubElement(tc_pr, qn("tcW")).set(qn("type"), "dxa")

    shd = etree.SubElement(tc_pr, qn("shd"))
    shd.set(qn("val"), "clear")
    shd.set(qn("color"), "auto")
    shd.set(qn("fill"), bg_color)

    tc_mar = etree.SubElement(tc_pr, qn("tcMar"))
    for edge, val in (("top", "120"), ("bottom", "120"), ("left", "180"), ("right", "180")):
        m = etree.SubElement(tc_mar, qn(edge))
        m.set(qn("w"), val)
        m.set(qn("type"), "dxa")

    for line in (code_lines or [""]):
        p = etree.SubElement(tc, qn("p"))
        ppr = etree.SubElement(p, qn("pPr"))
        sp = etree.SubElement(ppr, qn("spacing"))
        sp.set(qn("before"), "0")
        sp.set(qn("after"), "0")
        sp.set(qn("line"), "240")
        sp.set(qn("lineRule"), "auto")
        _append_text_run(p, line or " ", font_name="Consolas", font_size=18, color=text_color)

    return table


def _render_markdown_lines(
    body: etree._Element,
    content: str,
    *,
    base_content: Optional[str] = None,
    is_entirely_new: bool = False,
    highlight_changes: bool = True,
) -> None:
    """把 Markdown 正文深度解析并渲染为结构化 OOXML 元素，支持 HTML 注释过滤及变动标红对照。"""
    if not content and not base_content:
        return

    if highlight_changes and base_content:
        annotated = _build_annotated_diff_lines(base_content, content)
    elif highlight_changes and is_entirely_new:
        annotated = [(line, "insert", None) for line in content.splitlines()]
    else:
        annotated = [(line, "equal", None) for line in content.splitlines()]

    i = 0
    pending_col_widths: Optional[List[int]] = None

    while i < len(annotated):
        raw_line, diff_type, old_line = annotated[i]
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 1. 过滤 HTML 注释 (如 <!-- TBL:... -->, <!-- P:... --> 等)
        if stripped.startswith("<!--"):
            cols_match = re.search(r"cols=([\d,]+)", stripped)
            if cols_match:
                try:
                    pending_col_widths = [int(w) for w in cols_match.group(1).split(",") if w]
                except ValueError:
                    pass

            if "-->" in stripped:
                i += 1
                continue
            else:
                while i < len(annotated) and "-->" not in annotated[i][0]:
                    i += 1
                if i < len(annotated):
                    i += 1
                continue

        # 2. 过滤特殊占位符 <EMPTY_PAR/>
        if stripped == "<EMPTY_PAR/>":
            body.append(_create_paragraph("", spacing_after=100))
            i += 1
            continue

        # 3. 忽略 Markdown 水平分割线 --- / ***
        if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", stripped):
            i += 1
            continue

        # 4. 删除行独立显示（删除线灰色/暗红）
        if diff_type == "delete":
            p = _create_paragraph("", spacing_after=60)
            _append_text_run(p, f"~[已删除] {stripped}~", strike=True, color="9CA3AF", italic=True)
            body.append(p)
            i += 1
            continue

        # 5. 代码块 ```
        if stripped.startswith("```"):
            code_lines = []
            is_code_new = (diff_type == "insert")
            i += 1
            while i < len(annotated) and not annotated[i][0].strip().startswith("```"):
                code_lines.append(annotated[i][0])
                if annotated[i][1] == "insert":
                    is_code_new = True
                i += 1
            if i < len(annotated):  # 跳过闭合 ```
                i += 1
            body.append(_create_code_block_box(code_lines, is_new=is_code_new))
            body.append(_create_paragraph("", spacing_after=60))
            continue

        # 6. Markdown 表格 | ... |
        if stripped.startswith("|"):
            table_lines: List[Tuple[str, str, Optional[str]]] = []
            while i < len(annotated) and annotated[i][0].strip().startswith("|"):
                table_lines.append(annotated[i])
                i += 1

            tbl_el = _build_diff_markdown_table(table_lines, custom_col_widths=pending_col_widths)
            pending_col_widths = None
            if tbl_el is not None:
                body.append(tbl_el)
                body.append(_create_paragraph("", spacing_after=80))
            continue

        # 7. 图片标记 ![alt](path)
        img_match = re.match(r"^!\[(.*?)\]\((.*?)\)$", stripped)
        if img_match:
            alt_text = img_match.group(1).strip() or "示意图"
            img_path = img_match.group(2).strip()
            p = _create_paragraph("", align="center", spacing_before=100, spacing_after=100)
            img_color = "DC2626" if diff_type == "insert" else "4B5563"
            _append_text_run(p, f"📷 [图片: {alt_text} ({img_path})]", bold=True, color=img_color, font_size=18)
            body.append(p)
            i += 1
            continue

        # 8. 标题 (##, ###, ####, etc.)
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            h_text = heading_match.group(2).strip()
            if level == 1:
                sz, before, after, col = 24, 200, 80, "1F2937"
            elif level == 2:
                sz, before, after, col = 22, 160, 60, "374151"
            elif level == 3:
                sz, before, after, col = 20, 120, 40, "4B5563"
            else:
                sz, before, after, col = 19, 100, 30, "4B5563"

            p = _create_paragraph("", spacing_before=before, spacing_after=after)
            if diff_type == "insert":
                _append_markdown_inline_runs(p, h_text, default_bold=True, default_font_size=sz, default_color="DC2626")
            elif diff_type == "replace" and old_line:
                old_h_m = re.match(r"^(#{1,6})\s+(.*)$", old_line.strip())
                old_h_text = old_h_m.group(2).strip() if old_h_m else old_line.strip()
                _render_diff_text(p, old_h_text, h_text, default_bold=True, default_font_size=sz)
            else:
                _append_markdown_inline_runs(p, h_text, default_bold=True, default_font_size=sz, default_color=col)
            body.append(p)
            i += 1
            continue

        # 9. 无序列表 (- , * , + )
        ul_match = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if ul_match:
            indent_spaces = len(ul_match.group(1).replace("\t", "    "))
            level = min(indent_spaces // 2, 4)
            item_text = ul_match.group(2).strip()

            p = etree.Element(qn("p"))
            ppr = etree.SubElement(p, qn("pPr"))
            ind = etree.SubElement(ppr, qn("ind"))
            left_w = 400 + level * 280
            ind.set(qn("left"), str(left_w))
            ind.set(qn("hanging"), "240")
            sp = etree.SubElement(ppr, qn("spacing"))
            sp.set(qn("after"), "40")
            sp.set(qn("line"), "240")
            sp.set(qn("lineRule"), "auto")

            bullet_col = "DC2626" if diff_type == "insert" else "374151"
            _append_text_run(p, "•  ", bold=True, color=bullet_col)

            if diff_type == "insert":
                _append_markdown_inline_runs(p, item_text, default_color="DC2626", default_bold=True)
            elif diff_type == "replace" and old_line:
                old_ul_m = re.match(r"^(\s*)[-*+]\s+(.*)$", old_line)
                old_item_text = old_ul_m.group(2).strip() if old_ul_m else old_line.strip()
                _render_diff_text(p, old_item_text, item_text)
            else:
                _append_markdown_inline_runs(p, item_text)
            body.append(p)
            i += 1
            continue

        # 10. 有序列表 (1. , 2. )
        ol_match = re.match(r"^(\s*)(\d+)[.、]\s+(.*)$", line)
        if ol_match:
            indent_spaces = len(ol_match.group(1).replace("\t", "    "))
            level = min(indent_spaces // 2, 4)
            num_str = ol_match.group(2)
            item_text = ol_match.group(3).strip()

            p = etree.Element(qn("p"))
            ppr = etree.SubElement(p, qn("pPr"))
            ind = etree.SubElement(ppr, qn("ind"))
            left_w = 400 + level * 280
            ind.set(qn("left"), str(left_w))
            ind.set(qn("hanging"), "280")
            sp = etree.SubElement(ppr, qn("spacing"))
            sp.set(qn("after"), "40")
            sp.set(qn("line"), "240")
            sp.set(qn("lineRule"), "auto")

            num_col = "DC2626" if diff_type == "insert" else "374151"
            _append_text_run(p, f"{num_str}. ", bold=True, color=num_col)

            if diff_type == "insert":
                _append_markdown_inline_runs(p, item_text, default_color="DC2626", default_bold=True)
            elif diff_type == "replace" and old_line:
                old_ol_m = re.match(r"^(\s*)(\d+)[.、]\s+(.*)$", old_line)
                old_item_text = old_ol_m.group(3).strip() if old_ol_m else old_line.strip()
                _render_diff_text(p, old_item_text, item_text)
            else:
                _append_markdown_inline_runs(p, item_text)
            body.append(p)
            i += 1
            continue

        # 11. 引用块 (> )
        if stripped.startswith(">"):
            quote_text = stripped.lstrip(">").strip()
            p = etree.Element(qn("p"))
            ppr = etree.SubElement(p, qn("pPr"))
            ind = etree.SubElement(ppr, qn("ind"))
            ind.set(qn("left"), "360")
            pBdr = etree.SubElement(ppr, qn("pBdr"))
            left_bdr = etree.SubElement(pBdr, qn("left"))
            left_bdr.set(qn("val"), "single")
            left_bdr.set(qn("sz"), "18")
            left_bdr.set(qn("space"), "12")
            border_col = "DC2626" if diff_type == "insert" else "94A3B8"
            left_bdr.set(qn("color"), border_col)
            sp = etree.SubElement(ppr, qn("spacing"))
            sp.set(qn("after"), "60")

            if diff_type == "insert":
                _append_markdown_inline_runs(p, quote_text, default_italic=True, default_color="DC2626", default_bold=True)
            elif diff_type == "replace" and old_line:
                old_q = old_line.strip().lstrip(">").strip()
                _render_diff_text(p, old_q, quote_text, default_italic=True)
            else:
                _append_markdown_inline_runs(p, quote_text, default_italic=True, default_color="4B5563")
            body.append(p)
            i += 1
            continue

        # 12. 普通正文段落
        p = _create_paragraph("", spacing_after=80, line_spacing=240)
        if diff_type == "insert":
            _append_markdown_inline_runs(p, stripped, default_color="DC2626", default_bold=True)
        elif diff_type == "replace" and old_line:
            _render_diff_text(p, old_line.strip(), stripped)
        else:
            _append_markdown_inline_runs(p, stripped)
        body.append(p)
        i += 1


def _build_blank_review_table(row_count: int = 10) -> etree._Element:
    """创建供现场填写的标准空白 9 列表格（含章节列）。"""
    table = etree.Element(qn("tbl"))
    tbl_pr = etree.SubElement(table, qn("tblPr"))
    _apply_table_borders(tbl_pr, "94A3B8", "4")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), "9600")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")

    # 列宽定义（总宽 ~9600 dxa）
    cols = [
        ("序号", 600, "center"),
        ("提出人", 900, "center"),
        ("章节", 800, "center"),
        ("评审问题", 2200, "left"),
        ("责任人", 900, "center"),
        ("计划完成时间", 1100, "center"),
        ("更改确认", 900, "center"),
        ("评审记录", 1100, "left"),
        ("更改结果与证据", 1100, "left"),
    ]

    # 表头行
    h_tr = etree.SubElement(table, qn("tr"))
    h_tr_pr = etree.SubElement(h_tr, qn("trPr"))
    etree.SubElement(h_tr_pr, qn("tblHeader"))
    etree.SubElement(h_tr_pr, qn("cantSplit"))
    for name, width, align in cols:
        h_tr.append(_create_cell(name, width, bold=True, bg_color="1F4E79", text_color="FFFFFF", align=align))

    # 空白待填数据行
    for seq in range(1, max(1, row_count) + 1):
        tr = etree.SubElement(table, qn("tr"))
        tr_pr = etree.SubElement(tr, qn("trPr"))
        etree.SubElement(tr_pr, qn("cantSplit"))
        tr_h = etree.SubElement(tr_pr, qn("trHeight"))
        tr_h.set(qn("val"), "360")  # 稍高单元格便于手写或打字
        tr_h.set(qn("hRule"), "atLeast")

        bg = "F8FAFC" if seq % 2 == 0 else "FFFFFF"
        tr.append(_create_cell(str(seq), cols[0][1], bg_color=bg, align="center"))
        for _, width, align in cols[1:]:
            tr.append(_create_cell("", width, bg_color=bg, align=align))

    return table


# =========================================================================
# 2. 正式《评审纪要》生成（横向 A4 9 列表格 DOCX + Markdown）
# =========================================================================

def build_review_minutes_docx(
    *,
    output_path: Union[str, Path],
    document_name: str,
    document_no: str,
    document_version: str,
    review_date: str,
    comments: Sequence[ReviewComment],
    organizer: str = "",
    stats: Optional[Dict[str, int]] = None,
) -> Tuple[Path, Path]:
    """生成公司标准 A4 横向 9 列表格《评审纪要》DOCX 及同源 Markdown 文件。"""
    docx_path = Path(output_path).resolve()
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    md_path = docx_path.with_suffix(".md")

    total = len(comments)
    confirmed = sum(1 for c in comments if c.confirm_status == "已确认" or c.status == "confirmed")
    open_issues = sum(1 for c in comments if c.confirm_status == "遗留" or (c.open_issue and c.open_issue.strip() not in ("", "无")))
    unconfirmed = total - confirmed - open_issues

    stats_summary = f"共 {total} 条（已确认 {confirmed} 条，待确认 {unconfirmed} 条，遗留 {open_issues} 条）"

    # --- 1. 生成 DOCX ---
    items = _create_blank_package()
    doc_tree = parse_xml_safe(items["word/document.xml"], "word/document.xml")
    body = doc_tree.find(qn("body"))
    if body is None:
        body = etree.SubElement(doc_tree, qn("body"))
    body.clear()

    # 标题
    title_p = _create_paragraph(
        f"《{document_name} - 评审纪要》",
        align="center",
        bold=True,
        font_size=36,
        spacing_before=180,
        spacing_after=120,
    )
    body.append(title_p)

    # 纪要元数据卡片 (2 列精简信息盒)
    meta_tbl = etree.Element(qn("tbl"))
    m_pr = etree.SubElement(meta_tbl, qn("tblPr"))
    _apply_table_borders(m_pr, "D1D5DB", "4")
    etree.SubElement(m_pr, qn("tblW")).set(qn("w"), "14570")
    etree.SubElement(m_pr, qn("tblW")).set(qn("type"), "dxa")

    meta_rows = [
        [("文档名称", document_name), ("文档编号", document_no or "—")],
        [("评审版本", f"v{document_version}"), ("评审日期", review_date or datetime.now().strftime("%Y-%m-%d"))],
        [("组织人/纪要", organizer or "项目组"), ("闭环进度", stats_summary)],
    ]
    for row_data in meta_rows:
        tr = etree.SubElement(meta_tbl, qn("tr"))
        for label, val in row_data:
            tr.append(_create_cell(label, 1800, bold=True, bg_color="F3F4F6", align="center"))
            tr.append(_create_cell(val, 5485, align="left"))
    body.append(meta_tbl)
    body.append(_create_paragraph("", spacing_after=160))

    # 正文 10 列表格 (A4 横向总可用宽度: 16838 - 1134*2 = 14570 dxa)
    columns = [
        ("序号", 600, "center"),
        ("提出人", 1000, "center"),
        ("章节", 900, "center"),
        ("评审问题", 2800, "left"),
        ("责任人", 1000, "center"),
        ("计划完成时间", 1200, "center"),
        ("更改确认", 1100, "center"),
        ("评审记录", 1800, "left"),
        ("更改结果与证据", 2970, "left"),
        ("遗留问题", 1200, "left"),
    ]

    main_tbl = etree.Element(qn("tbl"))
    tbl_pr = etree.SubElement(main_tbl, qn("tblPr"))
    _apply_table_borders(tbl_pr, "CBD5E1", "4")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("w"), "14570")
    etree.SubElement(tbl_pr, qn("tblW")).set(qn("type"), "dxa")

    # 表头行 (商务蓝 #1F4E79，纯白加粗文本，w:tblHeader 跨页自动重复)
    h_tr = etree.SubElement(main_tbl, qn("tr"))
    h_tr_pr = etree.SubElement(h_tr, qn("trPr"))
    etree.SubElement(h_tr_pr, qn("tblHeader"))
    etree.SubElement(h_tr_pr, qn("cantSplit"))
    for name, width, align in columns:
        h_tr.append(_create_cell(name, width, bold=True, bg_color="1F4E79", text_color="FFFFFF", align=align))

    # 数据行 (斑马纹奇偶行白/灰交替)
    for idx, c in enumerate(comments, start=1):
        tr = etree.SubElement(main_tbl, qn("tr"))
        tr_pr = etree.SubElement(tr, qn("trPr"))
        etree.SubElement(tr_pr, qn("cantSplit"))

        bg = "F8FAFC" if idx % 2 == 0 else "FFFFFF"
        status_text = c.confirm_status or ("已确认" if c.status == "resolved" else "未确认")
        st_color = "166534" if status_text == "已确认" else ("92400E" if status_text == "待确认" else "6B21A8")

        tr.append(_create_cell(str(c.seq or idx), columns[0][1], bg_color=bg, align="center"))
        tr.append(_create_cell(c.author or "", columns[1][1], bg_color=bg, align="center"))
        tr.append(_create_cell(c.chapter_no or "", columns[2][1], bg_color=bg, align="center"))
        tr.append(_create_cell(c.text or "", columns[3][1], bg_color=bg, align="left"))
        tr.append(_create_cell(c.assignee or "", columns[4][1], bg_color=bg, align="center"))
        tr.append(_create_cell(c.planned_date or "", columns[5][1], bg_color=bg, align="center"))
        tr.append(_create_cell(status_text, columns[6][1], bold=True, bg_color=bg, text_color=st_color, align="center"))
        tr.append(_create_cell(c.review_note or "", columns[7][1], bg_color=bg, align="left"))
        tr.append(_create_cell(c.evidence or "", columns[8][1], bg_color=bg, align="left"))
        tr.append(_create_cell(c.open_issue or "无", columns[9][1], bg_color=bg, align="left"))

    if not comments:
        tr = etree.SubElement(main_tbl, qn("tr"))
        tr.append(_create_cell("（暂无评审意见）", 14570, align="center", text_color="9CA3AF"))

    body.append(main_tbl)

    # 横向 A4 页面设置 (Landscape: 297mm x 210mm = 16838 x 11906 dxa, 页边距 20mm = 1134 dxa)
    sect_pr = etree.SubElement(body, qn("sectPr"))
    pg_sz = etree.SubElement(sect_pr, qn("pgSz"))
    pg_sz.set(qn("w"), "16838")
    pg_sz.set(qn("h"), "11906")
    pg_sz.set(qn("orient"), "landscape")
    pg_mar = etree.SubElement(sect_pr, qn("pgMar"))
    pg_mar.set(qn("top"), "1134")
    pg_mar.set(qn("bottom"), "1134")
    pg_mar.set(qn("left"), "1134")
    pg_mar.set(qn("right"), "1134")
    pg_mar.set(qn("header"), "720")
    pg_mar.set(qn("footer"), "720")
    pg_mar.set(qn("gutter"), "0")

    items["word/document.xml"] = etree.tostring(doc_tree, encoding="utf-8", xml_declaration=True)
    _write_docx_zip(items, docx_path)

    # --- 2. 生成同源 Markdown 备份 ---
    md_lines = [
        f"# 《{document_name} - 评审纪要》\n",
        f"- **文档编号**：{document_no or '—'}",
        f"- **评审版本**：v{document_version}",
        f"- **评审日期**：{review_date or datetime.now().strftime('%Y-%m-%d')}",
        f"- **组织人员**：{organizer or '项目组'}",
        f"- **闭环状态**：{stats_summary}\n",
        "| 序号 | 提出人 | 章节 | 评审问题 | 责任人 | 计划完成时间 | 更改确认 | 评审记录 | 更改结果与证据 | 遗留问题 |",
        "| :---: | :---: | :---: | :--- | :---: | :---: | :---: | :--- | :--- | :--- |",
    ]
    for idx, c in enumerate(comments, start=1):
        seq = c.seq or idx
        author = c.author.replace("|", "/")
        ch = c.chapter_no.replace("|", "/")
        text = c.text.replace("|", "/").replace("\n", "<br>")
        assignee = c.assignee.replace("|", "/")
        date_str = c.planned_date or ""
        confirm = c.confirm_status or ("已确认" if c.status == "resolved" else "未确认")
        note = c.review_note.replace("|", "/").replace("\n", "<br>")
        evidence = c.evidence.replace("|", "/").replace("\n", "<br>")
        open_issue = (c.open_issue or "无").replace("|", "/")
        md_lines.append(
            f"| {seq} | {author} | {ch} | {text} | {assignee} | {date_str} | {confirm} | {note} | {evidence} | {open_issue} |"
        )

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return docx_path, md_path


# =========================================================================
# 3. 意见回流机制：提取 Word 末尾表格（纯 Python ZIP + lxml）
# =========================================================================

def extract_comments_from_docx(docx_path: Union[str, Path]) -> List[ReviewComment]:
    """从外部 Word 文档中识别并提取末尾评审表格（零 Word 依赖，抗 WPS 格式兼容）。"""
    path = Path(docx_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            doc_xml_bytes = archive.read("word/document.xml")
    except Exception as exc:
        raise ValueError(f"无法读取 Word 文件: {exc}") from exc

    doc_tree = parse_xml_safe(doc_xml_bytes, "word/document.xml")
    tables = doc_tree.findall(".//" + qn("tbl"))
    if not tables:
        return []

    # 寻找最佳匹配评审表（若有多个表格，优先按表头关键字命中，否则默认最后一个表）
    target_table = None
    best_mapping: Dict[int, str] = {}

    for tbl in reversed(tables):
        rows = tbl.findall(qn("tr"))
        if not rows:
            continue
        first_row_cells = [_extract_cell_text(cell).strip() for cell in rows[0].findall(qn("tc"))]
        col_map: Dict[int, str] = {}
        for col_idx, text in enumerate(first_row_cells):
            field = _match_header_field(text)
            if field:
                col_map[col_idx] = field
        # 命中关键列（如“评审问题”或“提出人”）
        if "text" in col_map.values() or "author" in col_map.values():
            target_table = tbl
            best_mapping = col_map
            break

    if target_table is None:
        target_table = tables[-1]
        # 回退第一行构建列映射
        rows = target_table.findall(qn("tr"))
        if not rows:
            return []
        first_row_cells = [_extract_cell_text(cell).strip() for cell in rows[0].findall(qn("tc"))]
        for col_idx, text in enumerate(first_row_cells):
            field = _match_header_field(text)
            if field:
                best_mapping[col_idx] = field

    rows = target_table.findall(qn("tr"))
    if len(rows) <= 1:
        return []

    extracted: List[ReviewComment] = []
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row_idx, tr in enumerate(rows[1:], start=1):
        cells = tr.findall(qn("tc"))
        data: Dict[str, str] = {}
        for col_idx, cell in enumerate(cells):
            field_name = best_mapping.get(col_idx)
            if field_name:
                data[field_name] = _extract_cell_text(cell).strip()

        question_text = data.get("text", "").strip()
        author = data.get("author", "").strip()

        # 过滤完全空白行（如导出的预留空白填报行）
        if not question_text and not author:
            continue

        raw_seq = data.get("seq", "")
        seq_num = int(raw_seq) if raw_seq.isdigit() else row_idx
        status = data.get("confirm_status", "未确认")
        resolved = "已确认" in status

        comment = ReviewComment(
            comment_id=str(uuid.uuid4()),
            text=question_text,
            author=author or "评审人",
            created_at=now_ts,
            rel_path="",
            line_no=1,
            seq=seq_num,
            chapter_no=data.get("chapter_no", ""),
            assignee=data.get("assignee", ""),
            planned_date=data.get("planned_date", ""),
            confirm_status=status or "未确认",
            review_note=data.get("review_note", ""),
            evidence=data.get("evidence", ""),
            open_issue=data.get("open_issue", ""),
            status="resolved" if resolved else "unresolved",
            resolved_at=now_ts if resolved else "",
        )
        extracted.append(comment)

    return extracted


def _extract_cell_text(cell: etree._Element) -> str:
    """提取单元格内的全部纯文本，多段落以换行连接。"""
    paragraphs = cell.findall(qn("p"))
    if not paragraphs:
        return "".join(cell.itertext()).strip()
    texts = []
    for p in paragraphs:
        t = "".join(node.text for node in p.findall(".//" + qn("t")) if node.text)
        texts.append(t)
    return "\n".join(texts).strip()


# =========================================================================
# 4. 更改结果与证据自动采集
# =========================================================================

def generate_evidence_for_comment(
    comment: ReviewComment,
    content_root: Union[str, Path],
    snapshot,
    today_str: str = "",
) -> str:
    """比对基线快照与当前文件差异，自动生成第 8 列「更改结果与证据」描述文本。"""
    content_root = Path(content_root).resolve()
    today = today_str or datetime.now().strftime("%Y-%m-%d")

    target_rel_path = comment.rel_path
    chapter_display = comment.chapter_no or "对应"

    # 若无直接 rel_path，尝试根据 chapter_no 在 content_root 下扫描匹配
    if not target_rel_path and comment.chapter_no:
        clean_no = comment.chapter_no.strip()
        for root, _, files in os.walk(content_root):
            for file in files:
                if file.endswith(".md") and clean_no in file:
                    target_rel_path = Path(os.path.join(root, file)).relative_to(content_root).as_posix()
                    break
            if target_rel_path:
                break

    if not target_rel_path:
        return f"【已整改】{chapter_display}章节已按意见完成修改 ({today})"

    curr_file = content_root / target_rel_path
    if not curr_file.exists():
        return f"【章节已移除】{chapter_display}章节源文件已删除 ({today})"

    try:
        curr_text = curr_file.read_text(encoding="utf-8")
    except OSError:
        return f"【已整改】{chapter_display}章节已修改 ({today})"

    base_text = snapshot.content_of(target_rel_path) if snapshot else None
    if base_text is None:
        lines = len(curr_text.splitlines())
        return f"【新增章节】{chapter_display}节已新增（共 {lines} 行），完成时间: {today}"

    diff = list(difflib.unified_diff(base_text.splitlines(), curr_text.splitlines(), lineterm=""))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    deleted = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

    if added == 0 and deleted == 0:
        return f"【未变动】{chapter_display}节当前内容与基线一致 ({today})"

    return f"【已修改】{chapter_display}节已修改（新增 {added} 行，删减 {deleted} 行），确认时间: {today}"


# =========================================================================
# 5. 内部辅助：基础空 DOCX 包模板
# =========================================================================

def _create_blank_package() -> Dict[str, bytes]:
    """内存中生成最小合法 DOCX 包。"""
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        b'  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        b'  <Default Extension="xml" ContentType="application/xml"/>\n'
        b'  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        b'</Types>'
    )
    rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        b'  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        b'</Relationships>'
    )
    doc_rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    document_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        b'  <w:body>\n'
        b'    <w:sectPr>\n'
        b'      <w:pgSz w:w="11906" w:h="16838"/>\n'
        b'      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>\n'
        b'    </w:sectPr>\n'
        b'  </w:body>\n'
        b'</w:document>'
    )
    return {
        "[Content_Types].xml": content_types,
        "_rels/.rels": rels,
        "word/_rels/document.xml.rels": doc_rels,
        "word/document.xml": document_xml,
    }


def _write_docx_zip(items: Dict[str, bytes], output_path: Path) -> None:
    """原子写入 ZIP 文件。"""
    temp_path = output_path.with_name(f"{output_path.stem}.tmp_{uuid.uuid4().hex[:8]}.docx")
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in items.items():
                info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
