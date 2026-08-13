# -*- coding: utf-8 -*-
"""Build company DOCX files from template + chapter tree + Markdown assets.

Daily use:
    python scripts/build_docx.py requirement
    python scripts/build_docx.py design
    python scripts/build_docx.py all

The build is fail-fast and atomic per document: an invalid chapter number,
missing image/table, malformed OOXML or packaging error never overwrites the
last known-good output.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
import posixpath
import re
import sys
import tempfile
import zipfile
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree
from PIL import Image

from docx_common import (
    AutomationError,
    ImageReference,
    OOXMLSecurityError,
    discover_document_types,
    iter_chapter_entries,
    load_config,
    parse_image_reference,
    parse_markdown_table,
    parse_xml_safe,
    read_docx_package,
    resolve_resource,
    validate_content_tree,
)


def _parse_xml_safe(data: bytes, part_name: str = ""):
    """安全解析 XML 部件；OOXML 安全错误映射为构建侧 AutomationError。"""
    try:
        return parse_xml_safe(data, part_name)
    except OOXMLSecurityError as exc:
        raise AutomationError("OOXML 解析失败 {0}: {1}".format(part_name or "部件", exc)) from exc


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
RP_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PIC_NS = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
WP_NS = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"

IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
HYPERLINK_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
FOOTNOTES_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
NUMBERING_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}


def qn(tag: str) -> str:
    return W_NS + tag


def append_text(run, text: str) -> None:
    """Append text with real Word line breaks/tabs, never literal ``<br>``."""
    parts = re.split(r"(\n|\t)", text)
    for part in parts:
        if part == "\n":
            etree.SubElement(run, qn("br"))
        elif part == "\t":
            etree.SubElement(run, qn("tab"))
        elif part:
            node = etree.SubElement(run, qn("t"))
            node.text = part
            node.set(XML_NS + "space", "preserve")


def parse_inline_runs(text: str) -> List[Tuple[str, str]]:
    """把基础 Markdown 行内标记拆成 ``(文本, 样式)``，未闭合标记按原文。"""
    if text.strip().startswith("```"):
        return [(text, "")]
    tokens: List[Tuple[str, str]] = []
    cursor = 0
    plain_start = 0
    while cursor < len(text):
        marker = None
        style = ""
        width = 0
        if text.startswith("`", cursor):
            marker, style, width = "`", "code", 1
        elif text.startswith("**", cursor):
            marker, style, width = "**", "bold", 2
        elif text.startswith("*", cursor):
            marker, style, width = "*", "italic", 1
        if marker is None:
            cursor += 1
            continue
        closing = text.find(marker, cursor + width)
        if closing < 0 or "\n" in text[cursor + width:closing]:
            cursor += width
            continue
        if cursor > plain_start:
            tokens.append((text[plain_start:cursor], ""))
        tokens.append((text[cursor + width:closing], style))
        cursor = closing + width
        plain_start = cursor
    if plain_start < len(text):
        tokens.append((text[plain_start:], ""))
    return tokens or [(text, "")]


def _append_styled_run(parent, value: str, style: str = "") -> None:
    run = etree.SubElement(parent, qn("r"))
    if style:
        rpr = etree.SubElement(run, qn("rPr"))
        if style == "bold":
            etree.SubElement(rpr, qn("b"))
        elif style == "italic":
            etree.SubElement(rpr, qn("i"))
        elif style == "code":
            fonts = etree.SubElement(rpr, qn("rFonts"))
            for attribute in ("ascii", "hAnsi", "eastAsia"):
                fonts.set(qn(attribute), "Consolas")
    append_text(run, value)


def append_inline(paragraph, text: str, expressions=None, source_path: str = "", line_no: int = 0) -> None:
    if expressions is not None:
        cursor = 0
        pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\[\^([^\]]+)\]")
        for match in pattern.finditer(text):
            if match.start() > cursor:
                append_inline(paragraph, text[cursor:match.start()], None)
            if match.group(3) is not None:
                expressions.append_footnote_reference(
                    paragraph, match.group(3), source_path, line_no
                )
            else:
                expressions.append_hyperlink(
                    paragraph, match.group(1), match.group(2), source_path, line_no
                )
            cursor = match.end()
        if cursor:
            if cursor < len(text):
                append_inline(paragraph, text[cursor:], None)
            return
    for value, style in parse_inline_runs(text):
        _append_styled_run(paragraph, value, style)


def apply_para_fmt(ppr, fmt: Optional[str]) -> None:
    if not fmt:
        return
    pairs: Dict[str, str] = {}
    for value in fmt.split(";"):
        if "=" in value:
            key, item = value.split("=", 1)
            pairs[key.strip()] = item.strip()
    spacing_keys = ("line", "lr", "b", "a")
    if any(key in pairs for key in spacing_keys):
        spacing = etree.SubElement(ppr, qn("spacing"))
        for key, attribute in {"line": "line", "lr": "lineRule", "b": "before", "a": "after"}.items():
            if key in pairs:
                spacing.set(qn(attribute), pairs[key])
    indent_keys = ("first", "left", "hang", "right")
    if any(key in pairs for key in indent_keys):
        indent = etree.SubElement(ppr, qn("ind"))
        for key, attribute in {
            "first": "firstLine",
            "left": "left",
            "hang": "hanging",
            "right": "right",
        }.items():
            if key in pairs:
                indent.set(qn(attribute), pairs[key])


def make_paragraph(
    style_id: Optional[str],
    text: str,
    fmt: Optional[str] = None,
    *,
    num_id: Optional[int] = None,
    list_level: int = 0,
    expressions=None,
    source_path: str = "",
    line_no: int = 0,
):
    paragraph = etree.Element(qn("p"))
    if style_id or fmt or num_id is not None:
        ppr = etree.SubElement(paragraph, qn("pPr"))
        if style_id:
            style = etree.SubElement(ppr, qn("pStyle"))
            style.set(qn("val"), style_id)
        apply_para_fmt(ppr, fmt)
        if num_id is not None:
            num_pr = etree.SubElement(ppr, qn("numPr"))
            etree.SubElement(num_pr, qn("ilvl")).set(qn("val"), str(list_level))
            etree.SubElement(num_pr, qn("numId")).set(qn("val"), str(num_id))
    append_inline(paragraph, text, expressions, source_path, line_no)
    return paragraph


def stable_bookmark_name(value: str) -> str:
    readable = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_")[:24] or "section"
    return "doc_{0}_{1}".format(readable, hashlib.sha1(value.encode("utf-8")).hexdigest()[:10])


class ExpressionManager:
    """管理稳定书签、超链接关系、脚注定义及可定位警告。"""

    def __init__(self, items, relationships, entries) -> None:
        self.items = items
        self.relationships = relationships
        self.bookmarks: Dict[str, str] = {}
        self.bookmark_names = set()
        self.emitted_bookmark_keys = set()
        self.next_bookmark_id = 1
        self.next_rid = max(
            [int((node.get("Id") or "rId0")[3:]) for node in relationships if (node.get("Id") or "").startswith("rId") and (node.get("Id") or "")[3:].isdigit()]
            or [0]
        ) + 1
        self.footnote_defs: Dict[str, str] = {}
        self.footnote_ids: Dict[str, int] = {}
        self.warnings: List[str] = []
        self.path_by_abs = {}
        root = os.path.abspath(entries[0][0].path) if entries else ""
        for entry, markdown_path in entries:
            if markdown_path:
                self.path_by_abs[os.path.abspath(markdown_path)] = markdown_path
        # 站内链接按文件名反查索引：覆盖内容根相对（章节树「复制 Markdown 引用」
        # 生成的 ``requirement/xxx.md`` 形式）与裸文件名两种链接写法。
        self._abs_by_name: Dict[str, str] = {}
        for abs_path in self.path_by_abs:
            self._abs_by_name.setdefault(os.path.basename(abs_path), abs_path)

    def register_bookmark(self, key: str) -> str:
        if key in self.bookmarks:
            return self.bookmarks[key]
        base = stable_bookmark_name(key)
        name = base
        suffix = 2
        while name in self.bookmark_names:
            name = "{0}_{1}".format(base[:35], suffix)
            suffix += 1
        self.bookmark_names.add(name)
        self.bookmarks[key] = name
        return name

    def wrap_bookmark(self, paragraph, key: str) -> str:
        name = self.register_bookmark(key)
        # A directory entry and its `_index.md` may resolve to the same key.
        # Word requires bookmark names to be unique, so only the first rendered
        # paragraph owns the target; subsequent occurrences still resolve to it.
        if key in self.emitted_bookmark_keys:
            return name
        self.emitted_bookmark_keys.add(key)
        bookmark_id = str(self.next_bookmark_id)
        self.next_bookmark_id += 1
        start = etree.Element(qn("bookmarkStart"))
        start.set(qn("id"), bookmark_id)
        start.set(qn("name"), name)
        end = etree.Element(qn("bookmarkEnd"))
        end.set(qn("id"), bookmark_id)
        paragraph.insert(1 if paragraph.find(qn("pPr")) is not None else 0, start)
        paragraph.append(end)
        return name

    def _resolve_internal_abs(self, source_path: str, path_target: str) -> Optional[str]:
        """把站内链接目标解析为目标 markdown 文件的绝对路径。

        与引用层 ``_resolve_content_file`` 语义对齐：先按源文件相对路径解析
        （同目录/裸文件名写法），再按文件名反查（覆盖内容根相对写法）。
        """
        if not path_target:
            return os.path.abspath(source_path)
        candidate = os.path.abspath(
            os.path.normpath(os.path.join(os.path.dirname(source_path), path_target))
        )
        if candidate in self.bookmarks:
            return candidate
        return self._abs_by_name.get(os.path.basename(path_target))

    def append_hyperlink(self, paragraph, label, target, source_path, line_no) -> None:
        hyperlink = etree.SubElement(paragraph, qn("hyperlink"))
        if re.match(r"^(?:https?|mailto):", target, re.IGNORECASE):
            rid = "rId{0}".format(self.next_rid)
            self.next_rid += 1
            relationship = etree.SubElement(self.relationships, RP_NS + "Relationship")
            relationship.set("Id", rid)
            relationship.set("Type", HYPERLINK_REL_TYPE)
            relationship.set("Target", target)
            relationship.set("TargetMode", "External")
            hyperlink.set(R_NS + "id", rid)
        else:
            path_target, _, anchor = target.partition("#")
            resolved = self._resolve_internal_abs(source_path, path_target)
            if resolved is None:
                self.warnings.append("{0}:{1} 链接目标不存在：{2}".format(source_path, line_no, target))
                paragraph.remove(hyperlink)
                append_inline(paragraph, label, None)
                return
            base = resolved + (("#" + anchor) if anchor else "")
            bookmark = self.bookmarks.get(base) or self.bookmarks.get(resolved)
            if bookmark is None:
                self.warnings.append("{0}:{1} 链接目标不存在：{2}".format(source_path, line_no, target))
                paragraph.remove(hyperlink)
                append_inline(paragraph, label, None)
                return
            hyperlink.set(qn("anchor"), bookmark)
        append_inline(hyperlink, label, None)

    def collect_footnotes(self, entries) -> None:
        definition = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
        for _entry, path in entries:
            if not path:
                continue
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            for line in lines:
                match = definition.match(line.strip())
                if match and match.group(1) not in self.footnote_defs:
                    self.footnote_defs[match.group(1)] = match.group(2)

    def append_footnote_reference(self, paragraph, key, source_path, line_no) -> None:
        if key not in self.footnote_defs:
            self.warnings.append("{0}:{1} 脚注未定义：{2}".format(source_path, line_no, key))
            append_inline(paragraph, "[^" + key + "]", None)
            return
        footnote_id = self.footnote_ids.setdefault(key, len(self.footnote_ids) + 1)
        run = etree.SubElement(paragraph, qn("r"))
        # 脚注引用需上标（Word 的 Footnote Reference 字符样式默认即上标）；
        # 缺 vertAlign 时引用标记以正文字号内联显示，视觉异常。
        rpr = etree.SubElement(run, qn("rPr"))
        vert_align = etree.SubElement(rpr, qn("vertAlign"))
        vert_align.set(qn("val"), "superscript")
        etree.SubElement(run, qn("footnoteReference")).set(qn("id"), str(footnote_id))

    def save_footnotes(self) -> None:
        if not self.footnote_ids:
            return
        root = etree.Element(qn("footnotes"), nsmap={"w": W_NS[1:-1]})
        for special_id, special_type in ((-1, "separator"), (0, "continuationSeparator")):
            note = etree.SubElement(root, qn("footnote"))
            note.set(qn("id"), str(special_id))
            note.set(qn("type"), special_type)
            etree.SubElement(etree.SubElement(etree.SubElement(note, qn("p")), qn("r")), qn(special_type))
        for key, footnote_id in sorted(self.footnote_ids.items(), key=lambda item: item[1]):
            note = etree.SubElement(root, qn("footnote"))
            note.set(qn("id"), str(footnote_id))
            paragraph = etree.SubElement(note, qn("p"))
            # 脚注定义文本同样做行内解析（粗体/斜体/代码），否则 ``**粗体**``
            # 会原样显示在脚注里。
            append_inline(paragraph, self.footnote_defs[key], None)
        self.items["word/footnotes.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        if not any(node.get("Type") == FOOTNOTES_REL_TYPE for node in self.relationships):
            relationship = etree.SubElement(self.relationships, RP_NS + "Relationship")
            relationship.set("Id", "rId{0}".format(self.next_rid))
            relationship.set("Type", FOOTNOTES_REL_TYPE)
            relationship.set("Target", "footnotes.xml")
            self.next_rid += 1
        content_types = _parse_xml_safe(self.items["[Content_Types].xml"], "[Content_Types].xml")
        if not any(node.get("PartName") == "/word/footnotes.xml" for node in content_types):
            override = etree.SubElement(content_types, CT_NS + "Override")
            override.set("PartName", "/word/footnotes.xml")
            override.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml")
            self.items["[Content_Types].xml"] = etree.tostring(content_types, xml_declaration=True, encoding="UTF-8")


def _ensure_numbering_relationship(relationships) -> None:
    """确保 document.xml.rels 有指向 numbering.xml 的关系（幂等）。

    模板缺失 numbering.xml、由构建新建该部件时调用：只有 [Content_Types] 登记
    而缺关系时，Word 无法解析列表编号，列表项会显示为空白。
    """
    if any(node.get("Type") == NUMBERING_REL_TYPE for node in relationships):
        return
    next_rid = max(
        [
            int((node.get("Id") or "rId0")[3:])
            for node in relationships
            if (node.get("Id") or "").startswith("rId") and (node.get("Id") or "")[3:].isdigit()
        ]
        or [0]
    ) + 1
    relationship = etree.SubElement(relationships, RP_NS + "Relationship")
    relationship.set("Id", "rId{0}".format(next_rid))
    relationship.set("Type", NUMBERING_REL_TYPE)
    relationship.set("Target", "numbering.xml")


class NumberingManager:
    """在模板 numbering.xml 后追加独立多级列表定义与实例。"""

    def __init__(self, items: Dict[str, bytes], relationships=None) -> None:
        name = "word/numbering.xml"
        if name in items:
            self.root = _parse_xml_safe(items[name], name)
        else:
            self.root = etree.Element(qn("numbering"), nsmap={"w": W_NS[1:-1]})
            items[name] = etree.tostring(self.root, xml_declaration=True, encoding="UTF-8")
            content_types = _parse_xml_safe(items["[Content_Types].xml"], "[Content_Types].xml")
            if not any(node.get("PartName") == "/word/numbering.xml" for node in content_types):
                override = etree.SubElement(content_types, CT_NS + "Override")
                override.set("PartName", "/word/numbering.xml")
                override.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml")
                items["[Content_Types].xml"] = etree.tostring(content_types, xml_declaration=True, encoding="UTF-8")
            if relationships is not None:
                # Word 靠 document.xml.rels 里的 numbering 关系解析列表编号；
                # 模板缺 numbering.xml 时若不补关系，列表项编号/项目符号不显示。
                _ensure_numbering_relationship(relationships)
        self.items = items
        self.next_abstract = max(
            [int(node.get(qn("abstractNumId"))) for node in self.root.findall(qn("abstractNum")) if (node.get(qn("abstractNumId")) or "").isdigit()]
            or [-1]
        ) + 1
        self.next_num = max(
            [int(node.get(qn("numId"))) for node in self.root.findall(qn("num")) if (node.get(qn("numId")) or "").isdigit()]
            or [0]
        ) + 1

    def new_list(self, kind: str, start: int = 1) -> int:
        abstract_id = self.next_abstract
        self.next_abstract += 1
        # OOXML 模式要求 numbering.xml 内全部 abstractNum 先于全部 num；模板
        # 通常尾部已有 num，直接 append 会把新 abstractNum 插到 num 之后，被
        # 严格消费者（如 Open XML SDK）拒绝。把新定义插到第一个 num 之前。
        abstract = etree.Element(qn("abstractNum"))
        first_num = self.root.find(qn("num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            self.root.append(abstract)
        abstract.set(qn("abstractNumId"), str(abstract_id))
        etree.SubElement(abstract, qn("multiLevelType")).set(qn("val"), "multilevel")
        for level in range(9):
            lvl = etree.SubElement(abstract, qn("lvl"))
            lvl.set(qn("ilvl"), str(level))
            etree.SubElement(lvl, qn("start")).set(qn("val"), str(start if level == 0 else 1))
            etree.SubElement(lvl, qn("numFmt")).set(qn("val"), "bullet" if kind == "bullet" else "decimal")
            etree.SubElement(lvl, qn("lvlText")).set(qn("val"), "•" if kind == "bullet" else "%{0}.".format(level + 1))
            etree.SubElement(lvl, qn("lvlJc")).set(qn("val"), "left")
            ppr = etree.SubElement(lvl, qn("pPr"))
            indent = etree.SubElement(ppr, qn("ind"))
            indent.set(qn("left"), str(720 * (level + 1)))
            indent.set(qn("hanging"), "360")
        num_id = self.next_num
        self.next_num += 1
        num = etree.SubElement(self.root, qn("num"))
        num.set(qn("numId"), str(num_id))
        etree.SubElement(num, qn("abstractNumId")).set(qn("val"), str(abstract_id))
        return num_id

    def save(self) -> None:
        self.items["word/numbering.xml"] = etree.tostring(
            self.root, xml_declaration=True, encoding="UTF-8", standalone=True
        )


def parse_list_line(line: str):
    unordered = re.match(r"^(\s*)[-*]\s+(.+)$", line)
    if unordered:
        return "bullet", min(8, len(unordered.group(1).replace("\t", "    ")) // 2), 1, unordered.group(2)
    ordered = re.match(r"^(\s*)(\d{1,3})[.、]\s+(.+)$", line)
    if ordered:
        return "decimal", min(8, len(ordered.group(1).replace("\t", "    ")) // 2), int(ordered.group(2)), ordered.group(3)
    return None


def make_heading(
    style_map: Dict[int, str], text: str, level: int, *, expressions=None, bookmark_key: str = ""
):
    if level not in style_map:
        raise AutomationError("缺少 Heading {0} 的 Word 样式映射".format(level))
    paragraph = make_paragraph(style_map[level], text, expressions=expressions)
    if expressions is not None and bookmark_key:
        expressions.wrap_bookmark(paragraph, bookmark_key)
    return paragraph


def _append_cell_text(cell, text: str) -> None:
    paragraph = etree.SubElement(cell, qn("p"))
    run = etree.SubElement(paragraph, qn("r"))
    append_text(run, text)


def make_table_from_md(
    rows: List[List[str]],
    style_id: Optional[str] = None,
    col_widths: Optional[Sequence[int]] = None,
    table_width_type: Optional[str] = None,
    table_width: Optional[int] = None,
    row_height: Optional[int] = None,
    extra: Optional[Dict[str, str]] = None,
):
    if not rows:
        raise AutomationError("Markdown 表格没有数据行")
    extra = extra or {}
    column_count = max(len(row) for row in rows)
    rows = [row + [""] * (column_count - len(row)) for row in rows]
    widths = list(col_widths[:column_count]) if col_widths and len(col_widths) >= column_count else [2400] * column_count

    table = etree.Element(qn("tbl"))
    table_properties = etree.SubElement(table, qn("tblPr"))
    if style_id:
        etree.SubElement(table_properties, qn("tblStyle")).set(qn("val"), style_id)
    width = etree.SubElement(table_properties, qn("tblW"))
    if table_width_type == "auto":
        width.set(qn("w"), "0")
        width.set(qn("type"), "auto")
    elif table_width_type == "pct":
        width.set(qn("w"), str(table_width or 5000))
        width.set(qn("type"), "pct")
    else:
        width.set(qn("w"), str(sum(widths)))
        width.set(qn("type"), "dxa")

    if extra.get("ind"):
        values = extra["ind"].split(":")
        indent = etree.SubElement(table_properties, qn("tblInd"))
        indent.set(
            qn("w"),
            values[0] if values and values[0] not in ("", "None") else "0",
        )
        indent.set(
            qn("type"),
            values[1] if len(values) > 1 and values[1] not in ("", "None") else "dxa",
        )
    if extra.get("bd"):
        values = extra["bd"].split(":")
        borders = etree.SubElement(table_properties, qn("tblBorders"))
        for edge_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
            edge = etree.SubElement(borders, qn(edge_name))
            edge.set(qn("val"), values[0])
            for index, attribute in ((1, "color"), (2, "sz"), (3, "space")):
                if (
                    len(values) > index
                    and values[index]
                    and values[index] != "None"
                ):
                    edge.set(qn(attribute), values[index])
    if extra.get("lay") and extra["lay"] not in ("", "None"):
        etree.SubElement(table_properties, qn("tblLayout")).set(qn("type"), extra["lay"])
    if extra.get("cm"):
        cell_margins = etree.SubElement(table_properties, qn("tblCellMar"))
        for tag, value in zip(("top", "left", "bottom", "right"), extra["cm"].split(",")):
            edge = etree.SubElement(cell_margins, qn(tag))
            edge.set(qn("w"), value)
            edge.set(qn("type"), "dxa")

    header_rows = {int(value) for value in extra.get("hdr", "").split(",") if value.isdigit()}
    no_split_rows = {int(value) for value in extra.get("cs", "").split(",") if value.isdigit()}
    tc_margin_values = extra.get("tcm", "").split(",") if extra.get("tcm") else None
    vertical_align = extra.get("va")

    grid = etree.SubElement(table, qn("tblGrid"))
    for value in widths:
        etree.SubElement(grid, qn("gridCol")).set(qn("w"), str(value))

    for row_index, values in enumerate(rows):
        row = etree.SubElement(table, qn("tr"))
        if row_height or row_index in header_rows or row_index in no_split_rows:
            row_properties = etree.SubElement(row, qn("trPr"))
            if row_height:
                height = etree.SubElement(row_properties, qn("trHeight"))
                height.set(qn("val"), str(row_height))
                height.set(qn("hRule"), "atLeast")
            if row_index in header_rows:
                etree.SubElement(row_properties, qn("tblHeader"))
            if row_index in no_split_rows:
                etree.SubElement(row_properties, qn("cantSplit"))
        for column_index, value in enumerate(values):
            cell = etree.SubElement(row, qn("tc"))
            cell_properties = etree.SubElement(cell, qn("tcPr"))
            cell_width = etree.SubElement(cell_properties, qn("tcW"))
            cell_width.set(qn("w"), str(widths[column_index]))
            cell_width.set(qn("type"), "dxa")
            if tc_margin_values:
                cell_margins = etree.SubElement(cell_properties, qn("tcMar"))
                for tag, margin in zip(("top", "left", "bottom", "right"), tc_margin_values):
                    edge = etree.SubElement(cell_margins, qn(tag))
                    edge.set(qn("w"), margin)
                    edge.set(qn("type"), "dxa")
            if vertical_align:
                etree.SubElement(cell_properties, qn("vAlign")).set(qn("val"), vertical_align)
            _append_cell_text(cell, value)
    return table


def insert_element(insert_before, element) -> None:
    if element.tag == qn("tbl"):
        previous = insert_before.getprevious()
        if previous is not None and previous.tag == qn("tbl"):
            insert_before.addprevious(etree.Element(qn("p")))
    insert_before.addprevious(element)


def _owner_part_for_rels(rels_name: str) -> str:
    if rels_name == "_rels/.rels":
        return ""
    directory, filename = posixpath.split(rels_name)
    if not directory.endswith("/_rels") or not filename.endswith(".rels"):
        return ""
    owner_directory = directory[: -len("/_rels")]
    return posixpath.join(owner_directory, filename[:-5])


def _resolve_relationship_target(owner_part: str, target: str) -> str:
    owner_directory = posixpath.dirname(owner_part)
    return posixpath.normpath(posixpath.join(owner_directory, target)).lstrip("/")


def deduplicate_media_parts(items: Dict[str, bytes]) -> int:
    """Deduplicate identical media after remapping every package relationship."""
    groups: Dict[str, List[str]] = {}
    for name, data in items.items():
        if name.startswith("word/media/"):
            groups.setdefault(hashlib.sha256(data).hexdigest(), []).append(name)
    duplicate_to_canonical: Dict[str, str] = {}
    for names in groups.values():
        if len(names) > 1:
            canonical = sorted(names)[0]
            for duplicate in sorted(names)[1:]:
                duplicate_to_canonical[duplicate] = canonical
    if not duplicate_to_canonical:
        return 0

    for rels_name in [name for name in list(items) if name.endswith(".rels")]:
        owner = _owner_part_for_rels(rels_name)
        try:
            root = _parse_xml_safe(items[rels_name], rels_name)
        except Exception:
            continue
        changed = False
        for relationship in root:
            if relationship.get("TargetMode") == "External":
                continue
            target = relationship.get("Target", "")
            resolved = _resolve_relationship_target(owner, target)
            canonical = duplicate_to_canonical.get(resolved)
            if canonical:
                base = posixpath.dirname(owner)
                relationship.set("Target", posixpath.relpath(canonical, base or "."))
                changed = True
        if changed:
            items[rels_name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    referenced = set()
    for rels_name, data in list(items.items()):
        if not rels_name.endswith(".rels"):
            continue
        owner = _owner_part_for_rels(rels_name)
        try:
            root = _parse_xml_safe(data, rels_name)
        except Exception:
            continue
        for relationship in root:
            if relationship.get("TargetMode") != "External":
                referenced.add(_resolve_relationship_target(owner, relationship.get("Target", "")))
    removed = 0
    for duplicate in duplicate_to_canonical:
        if duplicate not in referenced and duplicate in items:
            del items[duplicate]
            removed += 1
    return removed


class ImageManager:
    def __init__(self, items: Dict[str, bytes], relationship_root):
        self.items = items
        self.relationship_root = relationship_root
        self.existing_ids = {relationship.get("Id") for relationship in relationship_root}
        self.counter = 0
        self.part_by_hash: Dict[str, List[str]] = {}
        self.rid_by_part: Dict[str, List[str]] = {}
        for name, data in items.items():
            if name.startswith("word/media/"):
                self.part_by_hash.setdefault(hashlib.sha256(data).hexdigest(), []).append(name)
        for relationship in relationship_root:
            if relationship.get("Type") == IMAGE_REL_TYPE and relationship.get("TargetMode") != "External":
                part = _resolve_relationship_target("word/document.xml", relationship.get("Target", ""))
                self.rid_by_part.setdefault(part, []).append(relationship.get("Id"))

    def _new_rid(self) -> str:
        while True:
            self.counter += 1
            candidate = "rIdBuild{0}".format(self.counter)
            if candidate not in self.existing_ids:
                self.existing_ids.add(candidate)
                return candidate

    def _add_relationship(self, part: str) -> str:
        rid = self._new_rid()
        relationship = etree.SubElement(self.relationship_root, RP_NS + "Relationship")
        relationship.set("Id", rid)
        relationship.set("Type", IMAGE_REL_TYPE)
        relationship.set("Target", posixpath.relpath(part, "word"))
        self.rid_by_part.setdefault(part, []).append(rid)
        return rid

    def add_or_reuse(self, data: bytes, extension: str) -> Tuple[str, str, bool]:
        digest = hashlib.sha256(data).hexdigest()
        existing_parts = sorted(self.part_by_hash.get(digest, []))
        if existing_parts:
            part = existing_parts[0]
            rids = sorted(self.rid_by_part.get(part, []))
            return (rids[0] if rids else self._add_relationship(part), part, True)

        extension = extension.lower().lstrip(".")
        if extension not in CONTENT_TYPES:
            raise AutomationError("不支持的图片扩展名: .{0}".format(extension))
        part = "word/media/build_{0}.{1}".format(digest[:16], extension)
        suffix = 1
        while part in self.items and self.items[part] != data:
            part = "word/media/build_{0}_{1}.{2}".format(digest[:16], suffix, extension)
            suffix += 1
        self.items[part] = data
        self.part_by_hash.setdefault(digest, []).append(part)
        return self._add_relationship(part), part, False


def ensure_content_type(items: Dict[str, bytes], extension: str) -> None:
    extension = extension.lower().lstrip(".")
    content_type = CONTENT_TYPES.get(extension)
    if not content_type:
        raise AutomationError("不支持的图片扩展名: .{0}".format(extension))
    root = _parse_xml_safe(items["[Content_Types].xml"], "[Content_Types].xml")
    for node in root.findall(CT_NS + "Default"):
        if (node.get("Extension") or "").lower() == extension:
            return
    node = etree.SubElement(root, CT_NS + "Default")
    node.set("Extension", extension)
    node.set("ContentType", content_type)
    items["[Content_Types].xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def usable_page_width_emu(section_properties) -> int:
    page_size = section_properties.find(qn("pgSz"))
    margins = section_properties.find(qn("pgMar"))
    if page_size is None or margins is None:
        return 6_000_000
    width_twips = int(page_size.get(qn("w"), "12240"))
    left = int(margins.get(qn("left"), "1440"))
    right = int(margins.get(qn("right"), "1440"))
    return max((width_twips - left - right) * 635, 1)


def image_size_emu(path: str, reference: ImageReference, max_width: int) -> Tuple[int, int]:
    with Image.open(path) as image:
        pixel_width, pixel_height = image.size
        dpi_value = image.info.get("dpi", (96, 96))
    if pixel_width <= 0 or pixel_height <= 0:
        raise AutomationError("图片尺寸无效: {0}".format(path))
    if reference.width_px and reference.height_px:
        width = reference.width_px * 9525
        height = reference.height_px * 9525
    else:
        try:
            dpi_x, dpi_y = float(dpi_value[0]), float(dpi_value[1])
        except (TypeError, ValueError, IndexError):
            dpi_x = dpi_y = 96.0
        if not 36 <= dpi_x <= 600:
            dpi_x = 96.0
        if not 36 <= dpi_y <= 600:
            dpi_y = 96.0
        width = int(round(pixel_width / dpi_x * 914400))
        height = int(round(pixel_height / dpi_y * 914400))
    if width > max_width:
        scale = max_width / float(width)
        width = max_width
        height = max(1, int(round(height * scale)))
    return width, height


def make_image_paragraph(rid: str, name: str, alt: str, width: int, height: int, object_id: int):
    paragraph = etree.Element(qn("p"))
    run = etree.SubElement(paragraph, qn("r"))
    drawing = etree.SubElement(run, qn("drawing"))
    inline = etree.SubElement(drawing, WP_NS + "inline")
    for attribute in ("distT", "distB", "distL", "distR"):
        inline.set(attribute, "0")
    extent = etree.SubElement(inline, WP_NS + "extent")
    extent.set("cx", str(width))
    extent.set("cy", str(height))
    properties = etree.SubElement(inline, WP_NS + "docPr")
    properties.set("id", str(object_id))
    properties.set("name", name)
    if alt:
        properties.set("descr", alt)
    frame = etree.SubElement(inline, WP_NS + "cNvGraphicFramePr")
    etree.SubElement(frame, A_NS + "graphicFrameLocks").set("noChangeAspect", "1")
    graphic = etree.SubElement(inline, A_NS + "graphic")
    graphic_data = etree.SubElement(graphic, A_NS + "graphicData")
    graphic_data.set("uri", "http://schemas.openxmlformats.org/drawingml/2006/picture")
    picture = etree.SubElement(graphic_data, PIC_NS + "pic")
    non_visual = etree.SubElement(picture, PIC_NS + "nvPicPr")
    cnv = etree.SubElement(non_visual, PIC_NS + "cNvPr")
    cnv.set("id", str(object_id))
    cnv.set("name", name)
    locks = etree.SubElement(etree.SubElement(non_visual, PIC_NS + "cNvPicPr"), A_NS + "picLocks")
    locks.set("noChangeAspect", "1")
    fill = etree.SubElement(picture, PIC_NS + "blipFill")
    etree.SubElement(fill, A_NS + "blip").set(R_NS + "embed", rid)
    etree.SubElement(etree.SubElement(fill, A_NS + "stretch"), A_NS + "fillRect")
    shape = etree.SubElement(picture, PIC_NS + "spPr")
    transform = etree.SubElement(shape, A_NS + "xfrm")
    offset = etree.SubElement(transform, A_NS + "off")
    offset.set("x", "0")
    offset.set("y", "0")
    size = etree.SubElement(transform, A_NS + "ext")
    size.set("cx", str(width))
    size.set("cy", str(height))
    geometry = etree.SubElement(shape, A_NS + "prstGeom")
    geometry.set("prst", "rect")
    etree.SubElement(geometry, A_NS + "avLst")
    return paragraph


def _cell_text(cell) -> str:
    return "".join(node.text or "" for node in cell.iter(qn("t"))).strip()


def _replace_cell_text(cell, text: str) -> None:
    paragraphs = cell.findall(qn("p"))
    paragraph = paragraphs[0] if paragraphs else etree.SubElement(cell, qn("p"))
    for child in list(paragraph):
        if child.tag != qn("pPr"):
            paragraph.remove(child)
    run = etree.SubElement(paragraph, qn("r"))
    append_text(run, text)
    for extra in paragraphs[1:]:
        cell.remove(extra)


def _replace_cell_with_field(cell, instruction: str, cached_value: str = "0") -> None:
    paragraphs = cell.findall(qn("p"))
    paragraph = paragraphs[0] if paragraphs else etree.SubElement(cell, qn("p"))
    for child in list(paragraph):
        if child.tag != qn("pPr"):
            paragraph.remove(child)
    begin_run = etree.SubElement(paragraph, qn("r"))
    etree.SubElement(begin_run, qn("fldChar")).set(qn("fldCharType"), "begin")
    instruction_run = etree.SubElement(paragraph, qn("r"))
    instruction_node = etree.SubElement(instruction_run, qn("instrText"))
    instruction_node.set(XML_NS + "space", "preserve")
    instruction_node.text = " {0} ".format(instruction)
    separate_run = etree.SubElement(paragraph, qn("r"))
    etree.SubElement(separate_run, qn("fldChar")).set(qn("fldCharType"), "separate")
    value_run = etree.SubElement(paragraph, qn("r"))
    append_text(value_run, cached_value)
    end_run = etree.SubElement(paragraph, qn("r"))
    etree.SubElement(end_run, qn("fldChar")).set(qn("fldCharType"), "end")
    for extra in paragraphs[1:]:
        cell.remove(extra)


def update_cover(root, config: Dict) -> None:
    expected = {
        "文件编号": ("text", str(config["documentNo"])),
        "版本号": ("text", str(config["documentVersion"])),
        "页数": ("field", "NUMPAGES \\* MERGEFORMAT"),
    }
    found = set()
    # Only the cover summary table contains all three labels.  Restricting the
    # edit prevents similarly named cells in document-property tables from
    # being overwritten.
    cover_tables = []
    for table in root.iter(qn("tbl")):
        labels = {_cell_text(cell).rstrip("：:").strip() for cell in table.iter(qn("tc"))}
        if set(expected).issubset(labels):
            cover_tables.append(table)
    if len(cover_tables) != 1:
        raise AutomationError("模板封面字段表数量异常，预期 1，实际 {0}".format(len(cover_tables)))
    for table in cover_tables:
        for row in table.findall(qn("tr")):
            cells = row.findall(qn("tc"))
            texts = [_cell_text(cell).rstrip("：:").strip() for cell in cells]
            for index, label in enumerate(texts[:-1]):
                if label not in expected:
                    continue
                kind, value = expected[label]
                if kind == "field":
                    _replace_cell_with_field(cells[index + 1], value)
                else:
                    _replace_cell_text(cells[index + 1], value)
                found.add(label)
    missing = sorted(set(expected) - found)
    if missing:
        raise AutomationError("模板封面缺少字段: {0}".format(", ".join(missing)))


def set_update_fields(items: Dict[str, bytes], document_root) -> None:
    for node in list(document_root):
        if node.tag == qn("updateFields"):
            document_root.remove(node)
    if "word/settings.xml" not in items:
        raise AutomationError("模板缺少 word/settings.xml")
    settings = _parse_xml_safe(items["word/settings.xml"], "word/settings.xml")
    nodes = settings.findall(qn("updateFields"))
    target = nodes[0] if nodes else etree.SubElement(settings, qn("updateFields"))
    target.set(qn("val"), "true")
    for duplicate in nodes[1:]:
        settings.remove(duplicate)
    items["word/settings.xml"] = etree.tostring(
        settings, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _table_meta(line: str):
    match = re.fullmatch(
        r"<!--\s*TBL:style=([\w.]*)\s+type=(\w+)\s+tw=(\d+)(?:\s+trh=(\d+))?\s+"
        r"cols=([\d,]*)((?:\s+(?:cm|ind|lay|bd|hdr|cs|tcm|va)=[\w:,\-\.]*)*)\s*-->",
        line,
    )
    if match:
        extras = {
            item.group(1): item.group(2)
            for item in re.finditer(r"(cm|ind|lay|bd|hdr|cs|tcm|va)=([\w:,\-\.]*)", match.group(6) or "")
        }
        return (
            match.group(1) or None,
            [int(value) for value in match.group(5).split(",") if value] or None,
            match.group(2),
            int(match.group(3)),
            int(match.group(4)) if match.group(4) else None,
            extras,
        )
    legacy = re.fullmatch(r"<!--\s*TBL:style=([\w.]*)\s+cols=([\d,]*)\s*-->", line)
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


def _relationship_ids(element) -> List[str]:
    values: List[str] = []
    for node in element.iter():
        for attribute in (R_NS + "embed", R_NS + "link", R_NS + "id"):
            value = node.get(attribute)
            if value:
                values.append(value)
    return values


def process_markdown(
    path: str,
    insert_before,
    items: Dict[str, bytes],
    relationships,
    image_manager: ImageManager,
    config: Dict,
    max_image_width: int,
    next_object_id,
    numbering: Optional[NumberingManager] = None,
    expressions: Optional[ExpressionManager] = None,
) -> Tuple[int, int, int]:
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    inserted = 0
    image_count = 0
    table_count = 0
    pending_format: Optional[str] = None
    relationship_map = {relationship.get("Id"): relationship for relationship in relationships}
    index = 0
    active_list = None
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        list_info = parse_list_line(line)
        if list_info is None:
            active_list = None

        if re.match(r"^\[\^[^\]]+\]:\s*", stripped):
            index += 1
            continue

        complex_table = re.fullmatch(r"<!--\s*TABLE:(\d+):?([\w.\-]+)?\s*-->", stripped)
        if complex_table:
            filename = complex_table.group(2)
            if not filename:
                raise AutomationError("{0}:{1} 复杂表格缺少 XML 文件名".format(path, index + 1))
            table_path = resolve_resource(config["paths"]["table_root"], filename, "复杂表格")
            try:
                with open(table_path, "rb") as table_file:
                    table_element = _parse_xml_safe(table_file.read(), filename)
            except Exception as exc:
                raise AutomationError("复杂表格 XML 无法解析 {0}: {1}".format(table_path, exc))
            if table_element.tag != qn("tbl"):
                raise AutomationError("复杂表格 XML 根节点不是 w:tbl: {0}".format(table_path))
            for rid in _relationship_ids(table_element):
                relationship = relationship_map.get(rid)
                if relationship is None:
                    raise AutomationError("复杂表格关系不存在: {0} -> {1}".format(table_path, rid))
                if relationship.get("TargetMode") != "External":
                    target = _resolve_relationship_target("word/document.xml", relationship.get("Target", ""))
                    if target not in items:
                        raise AutomationError("复杂表格关系目标不存在: {0} -> {1}".format(rid, target))
            insert_element(insert_before, table_element)
            inserted += 1
            table_count += 1
            index += 1
            continue

        image_ref = parse_image_reference(stripped)
        if image_ref is not None:
            image_path = resolve_resource(config["paths"]["asset_root"], image_ref.relative_path, "图片")
            try:
                with open(image_path, "rb") as handle:
                    data = handle.read()
                with Image.open(image_path) as image:
                    image.verify()
            except Exception as exc:
                raise AutomationError("图片损坏或无法读取 {0}: {1}".format(image_path, exc))
            extension = os.path.splitext(image_path)[1].lower().lstrip(".")
            rid, media_part, reused = image_manager.add_or_reuse(data, extension)
            if not reused:
                ensure_content_type(items, extension)
            width, height = image_size_emu(image_path, image_ref, max_image_width)
            object_id = next_object_id()
            paragraph = make_image_paragraph(
                rid, posixpath.basename(media_part), image_ref.alt, width, height, object_id
            )
            insert_element(insert_before, paragraph)
            inserted += 1
            image_count += 1
            index += 1
            continue

        table_meta = _table_meta(stripped)
        if stripped.startswith("<!-- TBL:") and table_meta is None:
            raise AutomationError("{0}:{1} 表格元数据语法无效".format(path, index + 1))
        if table_meta is not None:
            if index + 1 >= len(lines) or not lines[index + 1].strip().startswith("|"):
                raise AutomationError("{0}:{1} 表格元数据后缺少 Markdown 表格".format(path, index + 1))
            block: List[str] = []
            cursor = index + 1
            while cursor < len(lines) and lines[cursor].strip().startswith("|"):
                block.append(lines[cursor])
                cursor += 1
            rows = parse_markdown_table(block)
            insert_element(insert_before, make_table_from_md(rows, *table_meta))
            inserted += 1
            table_count += 1
            index = cursor
            continue

        if stripped.startswith("|"):
            block = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            insert_element(insert_before, make_table_from_md(parse_markdown_table(block)))
            inserted += 1
            table_count += 1
            continue

        heading = re.match(r"^(#{1,9})\s+(.+)$", stripped)
        if heading:
            heading_text = heading.group(2).strip()
            insert_element(
                insert_before,
                make_heading(
                    config["headingStyles"],
                    heading_text,
                    len(heading.group(1)),
                    expressions=expressions,
                    bookmark_key=os.path.abspath(path) + "#" + heading_text,
                ),
            )
            inserted += 1
            index += 1
            continue

        if list_info is not None:
            kind, level, start, item_text = list_info
            item_text = re.sub(r"<br\s*/?>", "\n", item_text.strip(), flags=re.IGNORECASE)
            if numbering is None:
                numbering = NumberingManager(items, relationships)
            if active_list is None or active_list[0] != kind:
                active_list = (kind, numbering.new_list(kind, start))
            insert_element(
                insert_before,
                make_paragraph(
                    config.get("bodyStyle"),
                    item_text,
                    num_id=active_list[1],
                    list_level=level,
                    expressions=expressions,
                    source_path=path,
                    line_no=index + 1,
                ),
            )
            inserted += 1
            index += 1
            continue

        paragraph_format = re.fullmatch(r"<!--\s*P:(.*?)\s*-->", stripped)
        if paragraph_format:
            pending_format = paragraph_format.group(1)
            index += 1
            continue
        if stripped == "<EMPTY_PAR/>":
            insert_element(insert_before, etree.Element(qn("p")))
            inserted += 1
            index += 1
            continue
        if stripped:
            # HTML break syntax is allowed in ordinary Markdown text as a real Word break.
            paragraph_text = re.sub(r"<br\s*/?>", "\n", stripped, flags=re.IGNORECASE)
            insert_element(
                insert_before,
                make_paragraph(
                    config.get("bodyStyle"),
                    paragraph_text,
                    pending_format,
                    expressions=expressions,
                    source_path=path,
                    line_no=index + 1,
                ),
            )
            pending_format = None
            inserted += 1
        index += 1
    return inserted, image_count, table_count


def _validate_zip_xml(items: Dict[str, bytes]) -> None:
    required = (
        "[Content_Types].xml",
        "word/document.xml",
        "word/settings.xml",
        "word/styles.xml",
        "word/_rels/document.xml.rels",
    )
    for name in required:
        if name not in items:
            raise AutomationError("DOCX 缺少必需部件: {0}".format(name))
    for name, data in items.items():
        if name.endswith(".xml") or name.endswith(".rels"):
            try:
                _parse_xml_safe(data, name)
            except Exception as exc:
                raise AutomationError("OOXML 无法解析 {0}: {1}".format(name, exc))


def build(
    doc_type: Optional[str] = None,
    output_override: Optional[str] = None,
    config: Optional[Dict] = None,
) -> str:
    """Build a DOCX from a template + chapter tree + Markdown assets.

    ``config`` allows the caller to pass a project-context configuration dict
    (as produced by ``docx_common.load_config`` or
    ``doc_tool.adapters.kernel.config_from_project``).  When ``config`` is
    omitted, ``doc_type`` is used to load the legacy ``config/<doc>.yml``.
    """
    if config is None:
        if doc_type is None:
            raise AutomationError("必须提供 doc_type 或 config 参数")
        config = load_config(doc_type)
    doc_type = config["documentType"]
    validate_content_tree(config)
    template_path = config["paths"]["template"]
    output_path = os.path.abspath(output_override or config["paths"]["output"])
    try:
        with read_docx_package(template_path) as package:
            items = package.read_all()
    except OOXMLSecurityError as exc:
        # 统一入口抛中性异常；构建侧按契约映射为 AutomationError（保持 CLI
        # 与旧「模板 ZIP 校验失败」一致的干净错误消息，而非裸异常 traceback）。
        raise AutomationError("模板 OOXML 校验失败: {0}".format(exc)) from exc

    deduplicated = deduplicate_media_parts(items)
    _validate_zip_xml(items)
    document_root = _parse_xml_safe(items["word/document.xml"], "word/document.xml")
    body = document_root.find(qn("body"))
    if body is None:
        raise AutomationError("模板 document.xml 缺少 w:body")
    section_properties = body.find(qn("sectPr"))
    if section_properties is None:
        raise AutomationError("模板正文末尾缺少 w:sectPr")
    # 需求/详细设计预设启用封面字段同步；通用大文档不得
    # 假设存在“文件编号/版本号/页数”表格，原封面随模板保留。
    if doc_type in ("requirement", "design"):
        update_cover(document_root, config)

    relationship_root = _parse_xml_safe(items["word/_rels/document.xml.rels"], "word/_rels/document.xml.rels")
    image_manager = ImageManager(items, relationship_root)
    numbering = NumberingManager(items, relationship_root)
    max_image_width = usable_page_width_emu(section_properties)
    max_object_id = max(
        [int(node.get("id")) for node in document_root.iter(WP_NS + "docPr") if (node.get("id") or "").isdigit()]
        or [0]
    )

    def next_object_id() -> int:
        nonlocal max_object_id
        max_object_id += 1
        return max_object_id

    chapter_entries = list(iter_chapter_entries(config))
    expressions = ExpressionManager(items, relationship_root, chapter_entries)
    expressions.collect_footnotes(chapter_entries)
    # 先注册全部目标，支持链接指向后文标题。
    for _entry, markdown_path in chapter_entries:
        if not markdown_path:
            continue
        absolute = os.path.abspath(markdown_path)
        expressions.register_bookmark(absolute)
        with open(markdown_path, encoding="utf-8") as handle:
            markdown_lines = handle.read().splitlines()
        for line in markdown_lines:
            heading = re.match(r"^#{1,9}\s+(.+)$", line.strip())
            if heading:
                expressions.register_bookmark(absolute + "#" + heading.group(1).strip())

    inserted = 0
    images = 0
    tables = 0
    for entry, markdown_path in chapter_entries:
        insert_element(
            section_properties,
            make_heading(
                config["headingStyles"],
                entry.title,
                entry.depth,
                expressions=expressions,
                bookmark_key=os.path.abspath(markdown_path) if markdown_path else os.path.abspath(entry.path),
            ),
        )
        inserted += 1
        if markdown_path:
            count, image_count, table_count = process_markdown(
                markdown_path,
                section_properties,
                items,
                relationship_root,
                image_manager,
                config,
                max_image_width,
                next_object_id,
                numbering,
                expressions,
            )
            inserted += count
            images += image_count
            tables += table_count

    set_update_fields(items, document_root)
    numbering.save()
    expressions.save_footnotes()
    config["_expressionWarnings"] = list(expressions.warnings)
    # 缺失链接目标 / 未定义脚注等不阻断构建，但必须以可定位警告透出
    # （源文件:行号 形式），否则静默产出与源不一致的文档。
    for warning in expressions.warnings:
        print("[warn] {0}".format(warning), file=sys.stderr)
    items["word/_rels/document.xml.rels"] = etree.tostring(
        relationship_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    items["word/document.xml"] = etree.tostring(
        document_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    _validate_zip_xml(items)

    output_directory = os.path.dirname(output_path)
    os.makedirs(output_directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".docx-build-", suffix=".tmp", dir=output_directory)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as package:
            for name, data in items.items():
                info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                package.writestr(info, data)
        with zipfile.ZipFile(temporary_path, "r") as package:
            bad_part = package.testzip()
            if bad_part:
                raise AutomationError("生成 DOCX ZIP 校验失败: {0}".format(bad_part))
        os.replace(temporary_path, output_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)

    print("[{0}] 生成完成: {1}".format(doc_type, output_path))
    print(
        "[{0}] 插入元素={1}, 表格={2}, 图片={3}, 去重媒体={4}".format(
            doc_type, inserted, tables, images, deduplicated
        )
    )
    return output_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="从目录树生成公司 Word")
    available = discover_document_types()
    if not available:
        print("[FAIL] 未在 config/ 目录发现任何 .yml 配置", file=sys.stderr)
        return 1
    choices = tuple(available) + ("all",)
    parser.add_argument("document", choices=choices, nargs="?", default="all")
    parser.add_argument("--output", help="仅单文档时覆盖输出路径（用于隔离测试）")
    args = parser.parse_args(argv)
    if args.document == "all" and args.output:
        parser.error("--output 仅可用于单文档")
    targets = tuple(available) if args.document == "all" else (args.document,)
    try:
        for target in targets:
            build(target, args.output)
        return 0
    except (AutomationError, OSError, zipfile.BadZipFile, etree.LxmlError) as exc:
        print("[FAIL] {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
