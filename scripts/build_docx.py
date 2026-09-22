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
import urllib.parse
import zipfile
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree
from PIL import Image

from docx_common import (
    AutomationError,
    ImageReference,
    find_revision_table_info,
    map_revision_columns,
    is_revision_footer_row,
    OOXMLSecurityError,
    discover_document_types,
    error_location,
    format_location,
    iter_chapter_entries,
    load_config,
    neutralize_dangling_hyperlinks,
    neutralize_hyperlink_fields,
    parse_image_reference,
    parse_markdown_table,
    parse_xml_safe,
    read_docx_package,
    resolve_resource,
    validate_content_tree,
)

from doc_tool.domain.markdown_structure import (
    META_SYNTAX_HINT,
    parse_table_meta as _table_meta,
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
    """将包含行内样式（粗体、斜体、代码）的文本切分为 (text, style) 元组列表。
    
    规则：
    1. 不破坏代码块内部格式
    2. 支持 **加粗**、*斜体*、`代码`
    3. 修复 CommonMark 兼容：公式乘号、路径分隔符、脱敏多星号掩码不得误触发格式化
    """
    if text.strip().startswith("```"):
        return [(text, "")]
    tokens: List[Tuple[str, str]] = []
    cursor = 0
    plain_start = 0
    while cursor < len(text):
        if text[cursor] == "*":
            # 连续 4 个及以上星号（如 ****, ****** 等）为脱敏掩码或分隔线，一律作为普通纯文本
            s_end = cursor
            while s_end < len(text) and text[s_end] == "*":
                s_end += 1
            if s_end - cursor >= 4:
                cursor = s_end
                continue

        marker = None
        style = ""
        width = 0
        if text.startswith("`", cursor):
            marker, style, width = "`", "code", 1
        elif text.startswith("***", cursor):
            marker, style, width = "***", "bold_italic", 3
        elif text.startswith("**", cursor):
            marker, style, width = "**", "bold", 2
        elif text.startswith("*", cursor):
            marker, style, width = "*", "italic", 1
        elif text.startswith("~~", cursor):
            marker, style, width = "~~", "strike", 2
        if marker is None:
            cursor += 1
            continue

        prev_ch = text[cursor - 1] if cursor > 0 else ""
        next_ch = text[cursor + width] if cursor + width < len(text) else ""

        # 保护公式乘号、通配符、独立星号不被误判为斜体：
        if marker == "*":
            if next_ch == "*":
                cursor += 1
                continue
            # * 紧邻空格或换行 -> 不能作为开始定界符 (CommonMark 规范)
            if not next_ch or next_ch.isspace():
                cursor += 1
                continue
            # * 紧跟数字 (如 *0.5, *10) 或位于操作数之间 (如 2*3, 长度*0.5) -> 算术乘号，不得作为斜体定界符
            is_mul = False
            if next_ch.isdigit():
                is_mul = True
            elif prev_ch.isdigit() and ((next_ch.isascii() and next_ch.isalpha()) or next_ch in "([（"):
                is_mul = True
            elif prev_ch and prev_ch in ")]）" and (next_ch.isdigit() or (next_ch.isascii() and next_ch.isalpha()) or next_ch in "([（"):
                is_mul = True
            if is_mul or next_ch == ".":
                cursor += 1
                continue

        # 保护通配符、脱敏星号掩码不被误判为粗体：
        if marker in ("**", "***"):
            # ** 紧邻空格或换行 -> 不能作为开始定界符 (CommonMark 规范)
            if not next_ch or next_ch.isspace():
                cursor += 1
                continue
            # 通配符模式：路径分隔符或通配符扩展名 (如 /** 或 **/ 或 \** 或 **\ 或 **.ext 或 ***.ext)
            if prev_ch in ("/", chr(92)) or next_ch in ("/", chr(92), "."):
                cursor += 1
                continue
            if next_ch == "*" and cursor + width + 1 < len(text) and text[cursor + width + 1] in (".", "/", chr(92)):
                cursor += 1
                continue

        closing = text.find(marker, cursor + width)
        # 空跨度（如 **** 或 ``）不能作为加粗/代码跨度
        if (
            closing < 0
            or closing == cursor + width
            or chr(10) in text[cursor + width:closing]
            or "<br" in text[cursor + width:closing].lower()
        ):
            cursor += width
            continue

        span = text[cursor + width:closing]
        if not span or all(c == "*" for c in span):
            cursor += width
            continue

        # 检查闭合处的星号连续长度：若闭合处连续星号 >= 4，则说明是掩码，不得闭合
        if marker in ("*", "**", "***"):
            c_start = closing
            while c_start > 0 and text[c_start - 1] == "*":
                c_start -= 1
            c_end = closing
            while c_end < len(text) and text[c_end] == "*":
                c_end += 1
            if c_end - c_start >= 4:
                cursor += width
                continue

        # 针对斜体 * 的闭合定界符防误判保护：
        if marker == "*":
            # 闭合 * 紧跟在空格后面或紧随星号 -> 不能作为闭合定界符
            if text[closing - 1].isspace() or (closing + 1 < len(text) and text[closing + 1] == "*"):
                cursor += width
                continue
            # 斜体跨度不宜过长或跨越多句标点
            if len(span) > 100 or span.count("。") > 1:
                cursor += width
                continue

        # 针对粗体 ** 的闭合定界符防误判保护：
        if marker in ("**", "***"):
            # 闭合 ** 紧跟在空格后面 -> 不能作为闭合定界符
            if text[closing - 1].isspace():
                cursor += width
                continue
            prev_close = text[closing - 1] if closing > 0 else ""
            next_close = text[closing + width] if closing + width < len(text) else ""
            # 通配符/路径保护：闭合定界符前后不能是路径分隔符或通配符扩展名
            if prev_close in ("/", chr(92)) or next_close in ("/", chr(92), "."):
                cursor += width
                continue
            if prev_close == "*":
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


RPR_CHILD_TAGS = [
    qn("rStyle"),
    qn("rFonts"),
    qn("b"),
    qn("bCs"),
    qn("i"),
    qn("iCs"),
    qn("caps"),
    qn("smallCaps"),
    qn("strike"),
    qn("dstrike"),
    qn("outline"),
    qn("shadow"),
    qn("emboss"),
    qn("imprint"),
    qn("noProof"),
    qn("snapToGrid"),
    qn("vanish"),
    qn("webHidden"),
    qn("color"),
    qn("spacing"),
    qn("w"),
    qn("kern"),
    qn("position"),
    qn("sz"),
    qn("szCs"),
    qn("highlight"),
    qn("u"),
    qn("effect"),
    qn("bdr"),
    qn("shd"),
    qn("fitText"),
    qn("vertAlign"),
    qn("rtl"),
    qn("cs"),
    qn("em"),
    qn("lang"),
    qn("eastAsianLayout"),
    qn("specVanish"),
    qn("oMath"),
]
RPR_TAG_INDEX = {tag: idx for idx, tag in enumerate(RPR_CHILD_TAGS)}


def _normalize_rpr_order(rpr) -> None:
    """按 OOXML CT_RPr XSD 规范对 rPr 下子元素严格升序排列，避免 Word 样式解析异常。"""
    children = list(rpr)
    if len(children) <= 1:
        return
    sorted_children = sorted(children, key=lambda el: RPR_TAG_INDEX.get(el.tag, 999))
    if sorted_children != children:
        for child in children:
            rpr.remove(child)
        for child in sorted_children:
            rpr.append(child)


def _append_styled_run(
    parent,
    value: str,
    style: str = "",
    is_hyperlink: bool = False,
    hyperlink_style_id: str = "Hyperlink",
) -> None:
    run = etree.SubElement(parent, qn("r"))
    if is_hyperlink or style:
        rpr = etree.SubElement(run, qn("rPr"))
        if is_hyperlink:
            etree.SubElement(rpr, qn("rStyle")).set(qn("val"), hyperlink_style_id)
        if style == "bold":
            etree.SubElement(rpr, qn("b"))
        elif style == "italic":
            etree.SubElement(rpr, qn("i"))
        elif style == "bold_italic":
            etree.SubElement(rpr, qn("b"))
            etree.SubElement(rpr, qn("i"))
        elif style == "strike":
            etree.SubElement(rpr, qn("strike"))
        elif style == "code":
            fonts = etree.SubElement(rpr, qn("rFonts"))
            for attribute in ("ascii", "hAnsi", "eastAsia"):
                fonts.set(qn(attribute), "Consolas")
        if is_hyperlink:
            etree.SubElement(rpr, qn("color")).set(qn("val"), "0563C1")
            etree.SubElement(rpr, qn("u")).set(qn("val"), "single")
        _normalize_rpr_order(rpr)
    append_text(run, value)


def append_inline(
    paragraph,
    text: str,
    expressions=None,
    source_path: str = "",
    line_no: int = 0,
    is_hyperlink: bool = False,
    hyperlink_style_id: str = "Hyperlink",
) -> None:
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
        _append_styled_run(
            paragraph,
            value,
            style,
            is_hyperlink=is_hyperlink,
            hyperlink_style_id=hyperlink_style_id,
        )


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


def _chinese_to_int(s: str):
    """将中文数字（一至九百九十九）或纯阿拉伯数字字符串解析为整数。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    cn_digits = {
        "零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3,
        "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
        "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
    }
    val = 0
    temp = 0
    for ch in s:
        if ch in cn_digits:
            temp = cn_digits[ch]
        elif ch in ("百", "佰"):
            val += (temp if temp != 0 else 1) * 100
            temp = 0
        elif ch in ("十", "拾"):
            val += (temp if temp != 0 else 1) * 10
            temp = 0
        else:
            return None
    val += temp
    return val if (val > 0 or s == "零") else None


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
        existing_ids = []
        if isinstance(items, dict):
            for part_name, part_bytes in items.items():
                if part_name.startswith("word/") and part_name.endswith(".xml"):
                    try:
                        part_tree = _parse_xml_safe(part_bytes, part_name)
                        for node in part_tree.iter(qn("bookmarkStart")):
                            node_id = node.get(qn("id"))
                            if node_id and node_id.isdigit():
                                existing_ids.append(int(node_id))
                            name = node.get(qn("name"))
                            if name:
                                self.bookmark_names.add(name)
                    except Exception:
                        pass
        self.next_bookmark_id = (max(existing_ids) + 1) if existing_ids else 1
        self.next_rid = max(
            [int((node.get("Id") or "rId0")[3:]) for node in relationships if (node.get("Id") or "").startswith("rId") and (node.get("Id") or "")[3:].isdigit()]
            or [0]
        ) + 1
        self.footnote_defs: Dict[str, str] = {}
        self.footnote_ids: Dict[str, int] = {}
        self.warnings: List[str] = []
        self.hyperlink_style_id = "Hyperlink"
        styles_xml = items.get("word/styles.xml") if isinstance(items, dict) else None
        if styles_xml:
            try:
                styles_root = _parse_xml_safe(styles_xml, "word/styles.xml")
                for s in styles_root.findall(qn("style")):
                    if s.get(qn("type")) == "character":
                        name_el = s.find(qn("name"))
                        if name_el is not None and (name_el.get(qn("val")) or "").lower() == "hyperlink":
                            self.hyperlink_style_id = s.get(qn("styleId")) or "Hyperlink"
                            break
                else:
                    for s in styles_root.findall(qn("style")):
                        if s.get(qn("type")) == "character":
                            if (s.get(qn("styleId")) or "").lower() == "hyperlink":
                                self.hyperlink_style_id = s.get(qn("styleId")) or "Hyperlink"
                                break
            except Exception:
                pass
        self.path_by_abs = {}
        root = os.path.abspath(entries[0][0].path) if entries else ""
        for entry, markdown_path in entries:
            if markdown_path:
                self.path_by_abs[os.path.abspath(markdown_path)] = markdown_path
            if getattr(entry, "kind", "") == "dir":
                self.path_by_abs[os.path.abspath(entry.path)] = entry.path
        # 站内链接按文件名反查索引：覆盖内容根相对（章节树「复制 Markdown 引用」
        # 生成的 ``requirement/xxx.md`` 形式）与裸文件名两种链接写法。
        self._abs_by_name: Dict[str, str] = {}
        for abs_path in self.path_by_abs:
            self._abs_by_name.setdefault(os.path.basename(abs_path), abs_path)

        # 章节编号与大纲序号快速反查 Word 书签
        self.section_number_map: Dict[str, str] = {}
        self.section_title_map: Dict[str, str] = {}
        self.chapter_bookmark_by_source: Dict[str, str] = {}
        current_chapter_bm = None
        for entry, markdown_path in entries:
            key = os.path.abspath(markdown_path) if markdown_path else os.path.abspath(entry.path)
            bm_name = self.register_bookmark(key)
            if getattr(entry, "depth", 0) == 1:
                current_chapter_bm = bm_name
            if current_chapter_bm:
                if markdown_path:
                    self.chapter_bookmark_by_source[os.path.abspath(markdown_path)] = current_chapter_bm
                self.chapter_bookmark_by_source[os.path.abspath(entry.path)] = current_chapter_bm

            if markdown_path and getattr(entry, "kind", "") == "dir":
                self.bookmarks.setdefault(os.path.abspath(entry.path), bm_name)
                self.bookmarks.setdefault(os.path.abspath(entry.path).replace("\\", "/"), bm_name)
            if getattr(entry, "number", None):
                num_str = ".".join(str(n) for n in entry.number)
                self.section_number_map[num_str] = bm_name
                if getattr(entry, "depth", 0) == 1:
                    self.section_number_map["第{0}章".format(entry.number[0])] = bm_name
                    self.section_number_map[str(entry.number[0])] = bm_name
            if getattr(entry, "title", None):
                t = entry.title.strip()
                if t:
                    self.section_title_map[t] = bm_name
                    self.section_title_map[re.sub(r"\s+", "", t)] = bm_name
                    if getattr(entry, "number", None):
                        full_t = "{0} {1}".format(num_str, t)
                        self.section_title_map[full_t] = bm_name
                        self.section_title_map[re.sub(r"\s+", "", full_t)] = bm_name
                        if getattr(entry, "depth", 0) == 1:
                            chap_t = "第{0}章 {1}".format(entry.number[0], t)
                            self.section_title_map[chap_t] = bm_name
                            self.section_title_map[re.sub(r"\s+", "", chap_t)] = bm_name

    def get_chapter_bookmark_for_source(self, source_path: str) -> Optional[str]:
        """根据当前 Markdown 源文件路径解析其所属的第1级大章节书签。"""
        if not source_path:
            return None
        abs_src = os.path.abspath(source_path)
        if abs_src in self.chapter_bookmark_by_source:
            return self.chapter_bookmark_by_source[abs_src]
        return self.bookmarks.get(abs_src)

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
        hyperlink.set(qn("history"), "1")
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
            unquoted_target = urllib.parse.unquote(target).strip()
            path_target, _, anchor = unquoted_target.partition("#")
            clean_anchor = anchor.strip()
            clean_path = path_target.strip()
            bookmark = None

            # 情况 A: 目标带有锚点 (如 "#3.2.1", "#蓝牙配对", "file.md#sec", "#本章", "#本节")
            if clean_anchor:
                # A1. 若指定了文件路径，优先在目标文件的书签中查找
                if clean_path:
                    resolved = self._resolve_internal_abs(source_path, clean_path)
                    if resolved is not None:
                        bookmark = (
                            self.bookmarks.get(resolved + "#" + clean_anchor)
                            or self.bookmarks.get(resolved + "#" + anchor)
                        )
                # A2. 未指定文件路径时，优先在源文件自身书签查找
                if bookmark is None and source_path:
                    src_abs = os.path.abspath(source_path)
                    bookmark = (
                        self.bookmarks.get(src_abs + "#" + clean_anchor)
                        or self.bookmarks.get(src_abs + "#" + anchor)
                    )
                # A3. 按锚点 slug 跨文档与段落反查
                if bookmark is None and hasattr(self, "bookmarks"):
                    anchor_slug = re.sub(r"\s+", "-", re.sub(r"[^\w\s一-鿿\.\-]+", "", clean_anchor.lower(), flags=re.UNICODE)).strip("-")
                    anchor_slug_nodot = re.sub(r"\s+", "-", re.sub(r"[^\w\s一-鿿\-]+", "", clean_anchor.lower(), flags=re.UNICODE)).strip("-")
                    for b_key, b_val in self.bookmarks.items():
                        if "#" in b_key:
                            b_frag = b_key.split("#", 1)[1]
                            b_frag_clean = urllib.parse.unquote(b_frag).strip()
                            if b_frag_clean in (clean_anchor, anchor_slug, anchor_slug_nodot):
                                bookmark = b_val
                                break
                # A4. 查找章节号与小节标题映射（支持 cross-chapter / section 锚点如 #3.2.1）
                if bookmark is None and hasattr(self, "find_bookmark_for_section"):
                    bookmark = self.find_bookmark_for_section(clean_anchor)
                # A5. “本章” / “本节” 语义解析
                if bookmark is None and clean_anchor in ("top", "本章", "本章节", "本节"):
                    if clean_anchor != "本节" and hasattr(self, "get_chapter_bookmark_for_source"):
                        bookmark = self.get_chapter_bookmark_for_source(source_path)
                    if bookmark is None and source_path:
                        bookmark = self.bookmarks.get(os.path.abspath(source_path))
                # A6. 若指定了文件路径但未命中锚点，降级至该目标文件的起始书签
                if bookmark is None and clean_path:
                    resolved = self._resolve_internal_abs(source_path, clean_path)
                    if resolved is not None:
                        bookmark = self.bookmarks.get(resolved)

            # 情况 B: 无锚点 (如 target="#", "", ".", "3.4", "3.4.md", "第3章", "本章")
            else:
                # B1. “跳转本章节” / 本章 / 本节 / "#" / "." / "" 快捷语法
                if not clean_path or clean_path in (".", "#", "本章", "本章节", "本节"):
                    if clean_path != "本节" and hasattr(self, "get_chapter_bookmark_for_source"):
                        bookmark = self.get_chapter_bookmark_for_source(source_path)
                    if bookmark is None and source_path:
                        bookmark = self.bookmarks.get(os.path.abspath(source_path))
                # B2. 文件路径精确解析
                if bookmark is None and clean_path:
                    resolved = self._resolve_internal_abs(source_path, clean_path)
                    if resolved is not None:
                        bookmark = self.bookmarks.get(resolved)
                # B3. 章节号或标题匹配
                if bookmark is None and clean_path and hasattr(self, "find_bookmark_for_section"):
                    bookmark = self.find_bookmark_for_section(clean_path)

            # 情况 C: 根据超链接文本 label 智能反查书签
            if bookmark is None and hasattr(self, "find_bookmark_for_section") and label:
                clean_label = label.strip()
                if clean_label in ("本章", "本章节") and hasattr(self, "get_chapter_bookmark_for_source"):
                    bookmark = self.get_chapter_bookmark_for_source(source_path)
                if bookmark is None:
                    bookmark = self.find_bookmark_for_section(clean_label)
                if bookmark is None and clean_label in ("本章", "本章节", "本节") and source_path:
                    bookmark = self.bookmarks.get(os.path.abspath(source_path))

            if bookmark is None:
                self.warnings.append("{0}:{1} 目标不存在：{2}".format(source_path, line_no, target))
                paragraph.remove(hyperlink)
                append_inline(paragraph, label, None)
                return
            hyperlink.set(qn("anchor"), bookmark)

        append_inline(
            hyperlink,
            label,
            None,
            is_hyperlink=True,
            hyperlink_style_id=getattr(self, "hyperlink_style_id", "Hyperlink"),
        )

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

    def find_bookmark_for_section(self, token: str) -> Optional[str]:
        """按章节编号（如 3.4、4.8.4、第3章、第三章）或小节标题文本查找对应的 Word 书签名称。"""
        cleaned = token.strip()
        if not cleaned:
            return None
        if cleaned in self.bookmarks:
            return self.bookmarks[cleaned]

        # 剥离开头的 #、外层包裹括号与末尾标点、以及 .md 后缀
        norm_token = cleaned.lstrip("#").strip()
        if norm_token.lower().endswith((".md", ".markdown")):
            norm_token = norm_token.rsplit(".", 1)[0].strip()
        norm_token = re.sub(r"^[\(（\[【]+|[\)）\]】]+$", "", norm_token).strip().rstrip(".。、:：")
        if not norm_token:
            norm_token = cleaned

        token_spaces = re.sub(r"[-_]+", " ", norm_token).strip()

        # 0. 尝试直接在 section_title_map 中匹配（全词、去空格、下划线/短横转空格）
        if hasattr(self, "section_title_map"):
            for cand in (norm_token, token_spaces, cleaned):
                if cand in self.section_title_map:
                    return self.section_title_map[cand]
                cand_no_space = re.sub(r"\s+", "", cand)
                if cand_no_space in self.section_title_map:
                    return self.section_title_map[cand_no_space]

        # 1. 尝试匹配多级章节号（如 3.4、4.8.4、10.1.1、4.5.1.1.3）
        m_num = re.match(r"^(\d+(?:\.\d+)+)", norm_token) or re.match(r"^(\d+(?:\.\d+)+)", token_spaces)
        if m_num and hasattr(self, "section_number_map"):
            num_str = m_num.group(1)
            # 1.1 精确章节号匹配
            if num_str in self.section_number_map:
                return self.section_number_map[num_str]
            # 1.2 若带标题，尝试多级标题匹配
            rest_title = norm_token[m_num.end():].strip(" .、:：-_")
            if rest_title and hasattr(self, "section_title_map"):
                for t_cand in (rest_title, re.sub(r"\s+", "", rest_title)):
                    if t_cand in self.section_title_map:
                        return self.section_title_map[t_cand]
            # 1.3 前缀降级匹配（如 4.5.1.1.3 -> 4.5.1.1 -> 4.5.1）
            parts = num_str.split(".")
            for l in range(len(parts) - 1, 1, -1):
                parent_prefix = ".".join(parts[:l])
                if parent_prefix in self.section_number_map:
                    return self.section_number_map[parent_prefix]
            if len(parts) > 1:
                ch_key = "第{0}章".format(parts[0])
                if ch_key in self.section_number_map:
                    return self.section_number_map[ch_key]
                if parts[0] in self.section_number_map:
                    return self.section_number_map[parts[0]]

        # 2. 尝试大章节匹配（如 第3章、第三章、第 3 章、第3节、第3、3章）
        chap_match = (
            re.match(r"^第\s*([0-9一二三四五六七八九十百]+)\s*[章节]?(?:\s+(.+))?$", norm_token)
            or re.match(r"^第?\s*([0-9一二三四五六七八九十百]+)\s*[章节](?:\s+(.+))?$", norm_token)
            or re.match(r"^第\s*([0-9一二三四五六七八九十百]+)\s*[章节]?(?:\s+(.+))?$", token_spaces)
            or re.match(r"^第?\s*([0-9一二三四五六七八九十百]+)\s*[章节](?:\s+(.+))?$", token_spaces)
        )
        if chap_match and hasattr(self, "section_number_map"):
            cn_digits = chap_match.group(1)
            num_val = _chinese_to_int(cn_digits)
            if num_val is not None:
                ch_key = "第{0}章".format(num_val)
                if ch_key in self.section_number_map:
                    return self.section_number_map[ch_key]
                if str(num_val) in self.section_number_map:
                    return self.section_number_map[str(num_val)]

        # 3. 尝试单数字大章匹配（如 "1" 或 "1 概述" 或 "1.0"，注意排除 "1.1" 等多级小节）
        if re.match(r"^\d+\.0+$", norm_token):
            ch_k = norm_token.split(".")[0]
            if hasattr(self, "section_number_map"):
                if "第{0}章".format(ch_k) in self.section_number_map:
                    return self.section_number_map["第{0}章".format(ch_k)]
                if ch_k in self.section_number_map:
                    return self.section_number_map[ch_k]

        m_single_lbl = re.match(r"^(\d+)(?!\.\d)(?:[\.、\s]+(.*)|$)", norm_token)
        if m_single_lbl and hasattr(self, "section_number_map"):
            ch_k = m_single_lbl.group(1)
            ch_title = (m_single_lbl.group(2) or "").strip()
            # 若带有标题，优先匹配标题
            if ch_title and hasattr(self, "section_title_map"):
                if ch_title in self.section_title_map:
                    return self.section_title_map[ch_title]
                if re.sub(r"\s+", "", ch_title) in self.section_title_map:
                    return self.section_title_map[re.sub(r"\s+", "", ch_title)]
            if "第{0}章".format(ch_k) in self.section_number_map:
                return self.section_number_map["第{0}章".format(ch_k)]
            if ch_k in self.section_number_map:
                return self.section_number_map[ch_k]

        # 4. 中文数字单章（如 "一"、"三"、"叁"、"拾"）
        num_val = _chinese_to_int(norm_token)
        if num_val is not None and hasattr(self, "section_number_map"):
            ch_key = "第{0}章".format(num_val)
            if ch_key in self.section_number_map:
                return self.section_number_map[ch_key]
            if str(num_val) in self.section_number_map:
                return self.section_number_map[str(num_val)]

        # 5. 遍历已注册书签匹配（兼容 _index.md 上级目录、标题锚点、slug、stem编号前缀）
        cleaned_no_space = re.sub(r"\s+", "", cleaned)
        norm_no_space = re.sub(r"\s+", "", norm_token)
        for key, bookmark_name in self.bookmarks.items():
            base = os.path.basename(key.split("#")[0])
            if base.lower() in ("_index.md", "_index.markdown", "_index"):
                base = os.path.basename(os.path.dirname(key.split("#")[0]))
            if base.lower().endswith((".md", ".markdown")):
                stem = base.rsplit(".", 1)[0]
            else:
                stem = base
            stem_no_space = re.sub(r"\s+", "", stem)
            if cleaned_no_space == stem_no_space or cleaned == stem or norm_no_space == stem_no_space or norm_token == stem:
                return bookmark_name
            m_prefix = re.match(r"^(\d+(?:\.\d+)+)", stem)
            if m_prefix and m_prefix.group(1) in (cleaned, norm_token, cleaned_no_space, norm_no_space):
                return bookmark_name
            m_chap_stem = re.match(r"^第?\s*([0-9一二三四五六七八九十百]+)\s*章", stem)
            if m_chap_stem:
                c_val = _chinese_to_int(m_chap_stem.group(1))
                if c_val is not None and "第{0}章".format(c_val) in (cleaned, norm_token, cleaned_no_space, norm_no_space):
                    return bookmark_name
            if "#" in key:
                heading = key.split("#", 1)[1].strip()
                h_no_space = re.sub(r"\s+", "", heading)
                if heading in (cleaned, norm_token, token_spaces) or h_no_space in (cleaned_no_space, norm_no_space):
                    return bookmark_name

        return None


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

    def has_num(self, num_id: int) -> bool:
        """``numbering.xml`` 里是否定义了该 ``w:num``（编号实例）。

        引用未定义的 numId 会产出非法文档（Word 里编号不显示，校验器报
        「列表 numId 不存在」），所以套用模板既有编号前必须先问一句。
        """
        target = str(num_id)
        return any(
            node.get(qn("numId")) == target for node in self.root.findall(qn("num"))
        )

    def save(self) -> None:
        self.items["word/numbering.xml"] = etree.tostring(
            self.root, xml_declaration=True, encoding="UTF-8", standalone=True
        )


# 模板标题自动编号约定：numId 1 是与标题样式关联的多级列表
# （``第%1章`` / ``%1.%2`` …，各级 ``w:pStyle`` 指向标题样式）。
HEADING_NUM_ID = 1


def _heading_num_id(numbering: Optional[NumberingManager]) -> Optional[int]:
    """标题该套用的编号实例；模板没有该定义时返回 None（不发 ``w:numPr``）。

    模板不含 numId 1 时（例如没有任何列表的极简模板）硬套编号，会让每个标题
    都引用不存在的编号实例，产出非法文档且校验直接失败。这种模板一般自带
    标题样式编号或压根不需要编号，跳过即可。
    """
    if numbering is None or not numbering.has_num(HEADING_NUM_ID):
        return None
    return HEADING_NUM_ID


def parse_list_line(line: str):
    unordered = re.match(r"^(\s*)[-*]\s+(.+)$", line)
    if unordered:
        return "bullet", min(8, len(unordered.group(1).replace("\t", "    ")) // 2), 1, unordered.group(2)
    ordered = re.match(r"^(\s*)(\d{1,3})[.、]\s+(.+)$", line)
    if ordered:
        return "decimal", min(8, len(ordered.group(1).replace("\t", "    ")) // 2), int(ordered.group(2)), ordered.group(3)
    return None


def make_heading(
    style_map: Dict[int, str], text: str, level: int, *, num_id: Optional[int] = None, list_level: int = 0, expressions=None, bookmark_key: str = ""
):
    style_id = style_map.get(level)
    if not style_id:
        available = [k for k in style_map if isinstance(k, int) and k <= level]
        if available:
            style_id = style_map[max(available)]
        elif style_map:
            style_id = style_map[min(style_map.keys())]
        else:
            style_id = "Heading{0}".format(level)
    paragraph = make_paragraph(style_id, text, expressions=expressions, num_id=num_id, list_level=list_level)
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
    if col_widths:
        widths = [max(int(w), 200) for w in col_widths[:column_count]]
        if len(widths) < column_count:
            widths.extend([2400] * (column_count - len(widths)))
    else:
        widths = [2400] * column_count

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


def update_custom_properties(items: Dict[str, bytes], config: Dict) -> None:
    """自动将文档编号、版本号、文档名称同步更新到 docProps/custom.xml 与 core.xml。

    保证在 Word 中更新域（按 F9 或打开自动刷新）时，DOCPROPERTY 域从
    custom.xml 重新计算的值始终与当前构建参数一致，绝不回退为模板老旧版本。
    """
    doc_no = str(config.get("documentNo", "")).strip()
    doc_ver = str(config.get("documentVersion", "")).strip()
    doc_name = str(config.get("documentName", "")).strip()

    # 若 _revision_record.md 存在，尝试自动读取末行最新版本号作为真实版本
    rev_path = config.get("paths", {}).get("revision_record")
    if rev_path and os.path.isfile(rev_path):
        try:
            rev_rows = _parse_revision_markdown(rev_path)
            if rev_rows and rev_rows[-1] and rev_rows[-1][0]:
                latest_ver = str(rev_rows[-1][0]).strip()
                if latest_ver.upper().startswith("V"):
                    latest_ver = latest_ver[1:].strip()
                if latest_ver:
                    doc_ver = latest_ver
                    config["documentVersion"] = latest_ver
        except Exception:
            pass

    custom_props = {
        "文档编号": doc_no,
        "版本": doc_ver,
        "文件名称": doc_name,
    }

    CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
    VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
    FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"

    if "docProps/custom.xml" in items:
        try:
            root = _parse_xml_safe(items["docProps/custom.xml"], "docProps/custom.xml")
        except Exception:
            root = etree.Element("{{{0}}}Properties".format(CUSTOM_NS), nsmap={None: CUSTOM_NS, "vt": VT_NS})
    else:
        root = etree.Element("{{{0}}}Properties".format(CUSTOM_NS), nsmap={None: CUSTOM_NS, "vt": VT_NS})

    existing_pids = []
    prop_by_name = {}
    for p in root.findall("{{{0}}}property".format(CUSTOM_NS)):
        pid_str = p.get("pid")
        if pid_str and pid_str.isdigit():
            existing_pids.append(int(pid_str))
        name = p.get("name")
        if name:
            prop_by_name[name] = p

    next_pid = max(existing_pids or [1]) + 1

    for name, value in custom_props.items():
        if not value:
            continue
        if name in prop_by_name:
            p = prop_by_name[name]
            # 关键：清除原有的全部子节点（如 <vt:r8>、<vt:i4> 等），统一设为 Unicode 字符串 <vt:lpwstr>
            for child in list(p):
                p.remove(child)
            lpwstr = etree.SubElement(p, "{{{0}}}lpwstr".format(VT_NS))
            lpwstr.text = value
        else:
            p = etree.SubElement(root, "{{{0}}}property".format(CUSTOM_NS))
            p.set("fmtid", FMTID)
            p.set("pid", str(next_pid))
            p.set("name", name)
            next_pid += 1
            lpwstr = etree.SubElement(p, "{{{0}}}lpwstr".format(VT_NS))
            lpwstr.text = value

    items["docProps/custom.xml"] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    # 确保 [Content_Types].xml 中声明了 docProps/custom.xml
    if "[Content_Types].xml" in items:
        try:
            ct_root = _parse_xml_safe(items["[Content_Types].xml"], "[Content_Types].xml")
            custom_ct = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
            has_override = False
            for node in ct_root.findall(CT_NS + "Override"):
                if (node.get("PartName") or "").lower() == "/docprops/custom.xml":
                    has_override = True
                    break
            if not has_override:
                node = etree.SubElement(ct_root, CT_NS + "Override")
                node.set("PartName", "/docProps/custom.xml")
                node.set("ContentType", custom_ct)
                items["[Content_Types].xml"] = etree.tostring(
                    ct_root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
        except Exception:
            pass

    # 确保 _rels/.rels 中建立了 docProps/custom.xml 的关系
    if "_rels/.rels" in items:
        try:
            rels_root = _parse_xml_safe(items["_rels/.rels"], "_rels/.rels")
            CUSTOM_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
            has_rel = False
            rids = []
            for node in rels_root.findall(RP_NS + "Relationship"):
                target = (node.get("Target") or "").replace("\\", "/")
                rel_type = node.get("Type") or ""
                if target == "docProps/custom.xml" or rel_type == CUSTOM_REL_TYPE:
                    has_rel = True
                    break
                rid = node.get("Id") or ""
                if rid.startswith("rId") and rid[3:].isdigit():
                    rids.append(int(rid[3:]))
            if not has_rel:
                next_rid = "rId{0}".format(max(rids or [0]) + 1)
                node = etree.SubElement(rels_root, RP_NS + "Relationship")
                node.set("Id", next_rid)
                node.set("Type", CUSTOM_REL_TYPE)
                node.set("Target", "docProps/custom.xml")
                items["_rels/.rels"] = etree.tostring(
                    rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
        except Exception:
            pass

    if "docProps/core.xml" in items:
        try:
            core_root = _parse_xml_safe(items["docProps/core.xml"], "docProps/core.xml")
            DC_NS = "http://purl.org/dc/elements/1.1/"
            for tag in ("{{{0}}}title".format(DC_NS), "{{{0}}}subject".format(DC_NS)):
                node = core_root.find(tag)
                if node is not None and doc_name:
                    node.text = doc_name
            items["docProps/core.xml"] = etree.tostring(
                core_root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        except Exception:
            pass


def update_cover(root, config: Dict) -> None:
    expected = {
        "文件编号": ("text", str(config["documentNo"])),
        "版本号": ("text", str(config["documentVersion"])),
        "页数": ("field", "NUMPAGES \\* MERGEFORMAT"),
    }
    found = set()
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

    # 同步更新封面段落中的 DOCPROPERTY 域缓存文本
    doc_no = str(config.get("documentNo", ""))
    doc_ver = str(config.get("documentVersion", ""))
    doc_name = str(config.get("documentName", ""))
    flat_runs = [(run, run.getparent()) for run in root.iter(qn("r"))]
    fld_stack = []
    for r_node, _ in flat_runs:
        fld_char = r_node.find(qn("fldChar"))
        fld_type = fld_char.get(qn("fldCharType")) if fld_char is not None else None
        if fld_type == "begin":
            fld_stack.append({"separate": False, "instr": []})
        elif fld_type == "separate":
            if fld_stack:
                fld_stack[-1]["separate"] = True
        elif fld_type == "end":
            if fld_stack:
                fld_stack.pop()
        elif fld_stack and not fld_stack[-1]["separate"]:
            for t in r_node.iter(qn("instrText")):
                fld_stack[-1]["instr"].append(t.text or "")
        elif fld_stack and fld_stack[-1]["separate"]:
            full_instr = "".join(fld_stack[-1]["instr"]).upper()
            if "DOCPROPERTY" in full_instr:
                for t in r_node.iter(qn("t")):
                    if "版本" in full_instr or "VERSION" in full_instr:
                        if doc_ver:
                            t.text = doc_ver
                    elif "文件编号" in full_instr or "文档编号" in full_instr or "DOCNO" in full_instr:
                        if doc_no:
                            t.text = doc_no
                    elif "文件名称" in full_instr or "文档名称" in full_instr:
                        if doc_name:
                            t.text = doc_name


def update_headers(items, config):
    """Automatically update document number and version in page headers."""
    doc_no = str(config.get("documentNo", ""))
    doc_ver = str(config.get("documentVersion", ""))
    doc_name = str(config.get("documentName", ""))
    doc_no_pattern = re.compile(r"^[a-zA-Z0-9_-]+-\d+-\d+-\d+$")
    ver_pattern = re.compile(r"^\d+\.\d+(\.\d+)?$")
    header_names = sorted(
        name for name in items
        if name.startswith("word/header") and name.endswith(".xml")
    )
    if not header_names:
        return
    for hdr_name in header_names:
        hdr_root = _parse_xml_safe(items[hdr_name], hdr_name)
        modified = False

        # 1. 扫描更新 DOCPROPERTY 域缓存值
        flat_runs = [(run, run.getparent()) for run in hdr_root.iter(qn("r"))]
        fld_stack = []
        for r_node, _ in flat_runs:
            fld_char = r_node.find(qn("fldChar"))
            fld_type = fld_char.get(qn("fldCharType")) if fld_char is not None else None
            if fld_type == "begin":
                fld_stack.append({"separate": False, "instr": []})
            elif fld_type == "separate":
                if fld_stack:
                    fld_stack[-1]["separate"] = True
            elif fld_type == "end":
                if fld_stack:
                    fld_stack.pop()
            elif fld_stack and not fld_stack[-1]["separate"]:
                for t in r_node.iter(qn("instrText")):
                    fld_stack[-1]["instr"].append(t.text or "")
            elif fld_stack and fld_stack[-1]["separate"]:
                full_instr = "".join(fld_stack[-1]["instr"]).upper()
                if "DOCPROPERTY" in full_instr:
                    for t in r_node.iter(qn("t")):
                        if "版本" in full_instr or "VERSION" in full_instr:
                            if doc_ver and t.text != doc_ver:
                                t.text = doc_ver
                                modified = True
                        elif "文件编号" in full_instr or "文档编号" in full_instr or "DOCNO" in full_instr:
                            if doc_no and t.text != doc_no:
                                t.text = doc_no
                                modified = True
                        elif "文件名称" in full_instr or "文档名称" in full_instr or "TITLE" in full_instr:
                            if doc_name and t.text != doc_name:
                                t.text = doc_name
                                modified = True

        # 2. 扫描普通文本节点
        for t_node in hdr_root.iter(qn("t")):
            if t_node.text is None:
                continue
            text = t_node.text.strip()
            if not text:
                continue
            if doc_no_pattern.match(text) and doc_no:
                t_node.text = doc_no
                modified = True
            elif ver_pattern.match(text) and doc_ver:
                t_node.text = doc_ver
                modified = True
        if modified:
            items[hdr_name] = etree.tostring(
                hdr_root, xml_declaration=True, encoding="UTF-8", standalone=True
            )


def _find_revision_record_table(body):
    """Find the revision record table in the document body."""
    info = find_revision_table_info(body)
    return info[0] if info is not None else None


def _parse_revision_markdown(file_path, return_header=False):
    """Parse revision record markdown table, return data rows."""
    from docx_common import parse_markdown_table
    with open(file_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    table_lines = []
    in_table = False
    for line in lines:
        if line.strip().startswith("|"):
            in_table = True
            table_lines.append(line)
        elif in_table:
            break
    if not table_lines:
        return ([], []) if return_header else []
    rows = parse_markdown_table(table_lines)
    header_row = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []
    if return_header:
        return header_row, data_rows
    return data_rows


def _make_revision_cell(cell_index, text, is_summary=False):
    cell = etree.Element(qn("tc"))
    tc_pr = etree.SubElement(cell, qn("tcPr"))
    tc_w = etree.SubElement(tc_pr, qn("tcW"))
    widths = [1600, 5500, 1800, 1350]
    tc_w.set(qn("w"), str(widths[cell_index]) if cell_index < len(widths) else "1500")
    tc_w.set(qn("type"), "dxa")
    etree.SubElement(tc_pr, qn("vAlign")).set(qn("val"), "center")
    paragraph = etree.SubElement(cell, qn("p"))
    ppr = etree.SubElement(paragraph, qn("pPr"))
    etree.SubElement(ppr, qn("jc")).set(qn("val"), "left" if (is_summary or cell_index == 1) else "center")
    run = etree.SubElement(paragraph, qn("r"))
    t_node = etree.SubElement(run, qn("t"))
    t_node.text = text
    t_node.set(XML_NS + "space", "preserve")
    return cell


def _set_revision_cell_text(cell, text) -> None:
    paragraphs = cell.findall(qn("p"))
    if paragraphs:
        paragraph = paragraphs[0]
        for extra in paragraphs[1:]:
            cell.remove(extra)
    else:
        paragraph = etree.SubElement(cell, qn("p"))
    run_properties = None
    first_run = paragraph.find(qn("r"))
    if first_run is not None:
        existing = first_run.find(qn("rPr"))
        if existing is not None:
            run_properties = copy.deepcopy(existing)
    for node in list(paragraph):
        if node.tag != qn("pPr"):
            paragraph.remove(node)
    run = etree.SubElement(paragraph, qn("r"))
    if run_properties is not None:
        run.append(run_properties)
    # 支持换行与 <br> 标签
    raw_lines = str(text).splitlines() or [""]
    all_lines: List[str] = []
    for raw in raw_lines:
        for sub in re.split(r"<br\s*/?>", raw, flags=re.IGNORECASE):
            all_lines.append(sub)
    for index, line in enumerate(all_lines or [""]):
        if index:
            etree.SubElement(run, qn("br"))
        t_node = etree.SubElement(run, qn("t"))
        t_node.text = line
        t_node.set(XML_NS + "space", "preserve")


def _set_revision_summary_cell(cell, text, expressions=None) -> None:
    """写入修订摘要单元格；为识别到的章节编号生成内部超链接。"""
    paragraphs = cell.findall(qn("p"))
    if paragraphs:
        paragraph = paragraphs[0]
        for extra in paragraphs[1:]:
            cell.remove(extra)
    else:
        paragraph = etree.SubElement(cell, qn("p"))
    run_properties = None
    first_run = paragraph.find(qn("r"))
    if first_run is not None:
        existing = first_run.find(qn("rPr"))
        if existing is not None:
            run_properties = copy.deepcopy(existing)
    for node in list(paragraph):
        if node.tag != qn("pPr"):
            paragraph.remove(node)

    def append_plain(parent, plain_text):
        if not plain_text:
            return
        r = etree.SubElement(parent, qn("r"))
        if run_properties is not None:
            r.append(copy.deepcopy(run_properties))
        t = etree.SubElement(r, qn("t"))
        t.text = plain_text
        t.set(XML_NS + "space", "preserve")

    hl_style_id = getattr(expressions, "hyperlink_style_id", "Hyperlink") if expressions else "Hyperlink"

    def append_link(parent, link_text, bookmark):
        if not link_text:
            return
        leading_ws = link_text[: len(link_text) - len(link_text.lstrip())]
        trailing_ws = link_text[len(link_text.rstrip()) :]
        clean_text = link_text.strip()
        if leading_ws:
            append_plain(parent, leading_ws)
        if not clean_text:
            if trailing_ws:
                append_plain(parent, trailing_ws)
            return

        hl = etree.SubElement(parent, qn("hyperlink"))
        hl.set(qn("anchor"), bookmark)
        hl.set(qn("history"), "1")
        r = etree.SubElement(hl, qn("r"))
        rpr = etree.SubElement(r, qn("rPr"))
        if run_properties is not None:
            for child in run_properties:
                if child.tag not in (qn("u"), qn("color"), qn("rStyle")):
                    rpr.append(copy.deepcopy(child))
        etree.SubElement(rpr, qn("rStyle")).set(qn("val"), hl_style_id)
        etree.SubElement(rpr, qn("color")).set(qn("val"), "0563C1")
        etree.SubElement(rpr, qn("u")).set(qn("val"), "single")
        _normalize_rpr_order(rpr)
        t = etree.SubElement(r, qn("t"))
        t.text = clean_text
        t.set(XML_NS + "space", "preserve")
        if trailing_ws:
            append_plain(parent, trailing_ws)

    md_link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    sec_num_pattern = re.compile(
        r"(第\s*[0-9一二三四五六七八九十百]+\s*[章节]|第?\s*[0-9一二三四五六七八九十百]+\s*章|(?<![0-9a-zA-Z\.])\d+(?:\.\d+)+)"
    )

    def render_plain_segment(parent, seg):
        if not seg:
            return
        if expressions is None:
            append_plain(parent, seg)
            return
        plain_num_pattern = re.compile(
            r"(第\s*[0-9一二三四五六七八九十百]+\s*[章节]|第?\s*[0-9一二三四五六七八九十百]+\s*章|(?<![0-9a-zA-Z\.])\d+(?:\.\d+)+|(?<![0-9a-zA-Z\.])\d+(?=[\s\.、]))"
        )
        pos = 0
        for m in plain_num_pattern.finditer(seg):
            s_start, s_end = m.span()
            if s_start < pos:
                continue
            tok = m.group(0)
            bm = None
            if tok.isdigit() and "." not in tok:
                if hasattr(expressions, "find_bookmark_for_section"):
                    cand_bm = expressions.find_bookmark_for_section(tok)
                    if cand_bm:
                        rest_clean = seg[s_end:].lstrip(" .、\t")
                        is_title_match = False
                        if hasattr(expressions, "section_title_map"):
                            for check_len in (8, 6, 4, 2):
                                sub = rest_clean[:check_len].strip()
                                if sub and (f"{tok} {sub}" in expressions.section_title_map or sub in expressions.section_title_map):
                                    is_title_match = True
                                    break
                        if is_title_match:
                            bm = cand_bm
            else:
                if hasattr(expressions, "find_bookmark_for_section"):
                    bm = expressions.find_bookmark_for_section(tok)

            if bm:
                if s_start > pos:
                    append_plain(parent, seg[pos:s_start])
                append_link(parent, tok, bm)
                pos = s_end
        if pos < len(seg):
            append_plain(parent, seg[pos:])

    def render_line(parent, line_text):
        if not line_text:
            return

        # 支持 Markdown 形式 [文本](目标路径)
        if md_link_re.search(line_text):
            pos = 0
            for match in md_link_re.finditer(line_text):
                start, end = match.span()
                if start > pos:
                    render_plain_segment(parent, line_text[pos:start])
                label, target = match.groups()
                bm = None
                frag_part = ""
                if expressions is not None:
                    unquoted_target = urllib.parse.unquote(target).replace("\\", "/")
                    path_part, _, frag_part = unquoted_target.partition("#")
                    target_clean = path_part.rstrip("/")
                    if target_clean.lower().endswith((".md", ".markdown")):
                        target_stem = os.path.basename(target_clean).rsplit(".", 1)[0]
                    else:
                        target_stem = os.path.basename(target_clean) if target_clean else ""

                    # 1. 优先按锚点与章节编号/小节名称查找文档内书签（避免直接链接到外部文件）
                    # 1.1 若存在 #frag 锚点，优先在 bookmarks 中寻找精确内部书签或通过 find_bookmark_for_section 查找
                    if frag_part:
                        frag_clean = urllib.parse.unquote(frag_part).strip()
                        if hasattr(expressions, "bookmarks"):
                            for b_key, b_name in expressions.bookmarks.items():
                                b_norm = b_key.replace("\\", "/").rstrip("/")
                                if (
                                    b_norm == unquoted_target
                                    or b_norm.endswith("/" + unquoted_target)
                                    or (frag_clean and (b_norm.endswith("#" + frag_clean) or b_norm.endswith("#" + urllib.parse.quote(frag_clean))))
                                ):
                                    bm = b_name
                                    break
                        if not bm and hasattr(expressions, "find_bookmark_for_section"):
                            bm = expressions.find_bookmark_for_section(frag_clean)
                            if not bm:
                                m_num_frag = sec_num_pattern.search(frag_clean)
                                if m_num_frag:
                                    bm = expressions.find_bookmark_for_section(m_num_frag.group(0))

                    # 1.2 优先从 label 中识别章节编号或小节标题进行书签反查
                    if not bm and hasattr(expressions, "find_bookmark_for_section"):
                        if label:
                            m_lbl = sec_num_pattern.search(label)
                            if m_lbl:
                                bm = expressions.find_bookmark_for_section(m_lbl.group(0))
                            if not bm:
                                m_top_lbl = re.match(r"^(\d+)(?:[\.、\s]+|$)", label.strip())
                                if m_top_lbl:
                                    bm = expressions.find_bookmark_for_section(m_top_lbl.group(1))
                            if not bm:
                                bm = expressions.find_bookmark_for_section(label)
                        if not bm and target_stem:
                            m_stem = sec_num_pattern.search(target_stem)
                            if m_stem:
                                bm = expressions.find_bookmark_for_section(m_stem.group(0))
                            if not bm:
                                m_top_stem = re.match(r"^(\d+)(?:[\.、\s]+|$)", target_stem.strip())
                                if m_top_stem:
                                    bm = expressions.find_bookmark_for_section(m_top_stem.group(1))
                            if not bm:
                                bm = expressions.find_bookmark_for_section(target_stem)

                    # 2. 兜底匹配 bookmarks 中的内部文件路径（外部协议 URL 不匹配文件书签）
                    if not bm and hasattr(expressions, "bookmarks"):
                        is_external_url = unquoted_target.lower().startswith(("http://", "https://", "ftp://", "file://", "mailto:"))
                        if not is_external_url:
                            for b_key, b_name in expressions.bookmarks.items():
                                b_norm = b_key.replace("\\", "/").rstrip("/")
                                if b_norm == unquoted_target or b_norm.endswith("/" + unquoted_target):
                                    bm = b_name
                                    break
                            if not bm and target_clean:
                                for b_key, b_name in expressions.bookmarks.items():
                                    b_norm = b_key.replace("\\", "/").rstrip("/")
                                    if (
                                        b_norm == target_clean
                                        or b_norm.endswith("/" + target_clean)
                                        or (target_stem and b_norm.endswith("/" + target_stem + ".md"))
                                    ):
                                        bm = b_name
                                        break

                # 3. 渲染超链接文本：若 label 中包含章节/小节编号，严格仅为章节号加超链接，其余文字保持普通正文
                matches = list(sec_num_pattern.finditer(label)) if (expressions is not None) else []
                if not matches and expressions is not None:
                    m_single = re.match(r"^(\s*)(\d+)([\.、\s]+.*)?$", label)
                    if m_single:
                        ch_digit = m_single.group(2)
                        ch_bm = expressions.find_bookmark_for_section(ch_digit)
                        if ch_bm or bm:
                            lead_sp = m_single.group(1)
                            rest_txt = m_single.group(3) or ""
                            if lead_sp:
                                append_plain(parent, lead_sp)
                            append_link(parent, ch_digit, ch_bm or bm)
                            if rest_txt:
                                append_plain(parent, rest_txt)
                            pos = end
                            continue
                if matches:
                    l_pos = 0
                    for lm in matches:
                        ls, le = lm.span()
                        if ls > l_pos:
                            append_plain(parent, label[l_pos:ls])
                        tok = lm.group(0)
                        tok_bm = None
                        if hasattr(expressions, "find_bookmark_for_section"):
                            tok_bm = expressions.find_bookmark_for_section(tok)
                        if frag_part and bm:
                            link_bm = bm
                        else:
                            link_bm = tok_bm or bm
                        if link_bm:
                            append_link(parent, tok, link_bm)
                        else:
                            append_plain(parent, tok)
                        l_pos = le
                    if l_pos < len(label):
                        append_plain(parent, label[l_pos:])
                else:
                    if bm:
                        append_link(parent, label, bm)
                    else:
                        append_plain(parent, label)
                pos = end
            if pos < len(line_text):
                render_plain_segment(parent, line_text[pos:])
        else:
            render_plain_segment(parent, line_text)

    raw_lines = str(text).splitlines()
    line_idx = 0
    for raw_line in raw_lines:
        sub_lines = re.split(r"<br\s*/?>", raw_line, flags=re.IGNORECASE)
        for sub_line in sub_lines:
            if line_idx > 0:
                br_run = etree.SubElement(paragraph, qn("r"))
                etree.SubElement(br_run, qn("br"))
            render_line(paragraph, sub_line)
            line_idx += 1


def _clone_revision_row(prototype, values, expressions=None, summary_col_idx=None):
    """按模板数据行原型克隆一行并只替换文本；原型不可用时退回自建单元格。

    对长修订摘要移除 w:cantSplit，允许长内容跨页自然拆分，杜绝边框穿透页脚。
    """
    if summary_col_idx is None:
        summary_col_idx = 1
    if prototype is not None:
        row = copy.deepcopy(prototype)
        summary_text = str(values[summary_col_idx]) if len(values) > summary_col_idx else ""
        is_long = len(summary_text.splitlines()) >= 3 or len(summary_text) > 150
        tr_pr = row.find(qn("trPr"))
        if tr_pr is not None and is_long:
            for cant_split in tr_pr.findall(qn("cantSplit")):
                tr_pr.remove(cant_split)
            for tr_h in tr_pr.findall(qn("trHeight")):
                tr_h.set(qn("hRule"), "atLeast")
        cells = row.findall(qn("tc"))
        if len(cells) == len(values):
            # w14:paraId/textId 是段落唯一标识，克隆后必须去掉，避免整表重复 ID。
            for node in row.iter():
                for name in list(node.attrib):
                    if name.rpartition("}")[2] in ("paraId", "textId"):
                        del node.attrib[name]
            for idx, (cell, text) in enumerate(zip(cells, values)):
                tc_pr = cell.find(qn("tcPr"))
                if tc_pr is not None:
                    tc_borders = tc_pr.find(qn("tcBorders"))
                    if tc_borders is not None and tc_borders.find(qn("bottom")) is None:
                        etree.SubElement(tc_borders, qn("bottom"), {
                            qn("val"): "single",
                            qn("sz"): "4",
                            qn("space"): "0",
                            qn("color"): "auto",
                        })
                if idx == summary_col_idx and expressions is not None:
                    _set_revision_summary_cell(cell, text, expressions)
                else:
                    _set_revision_cell_text(cell, text)
            return row
    row = etree.Element(qn("tr"))
    for index, text in enumerate(values):
        if index == summary_col_idx and expressions is not None:
            cell = _make_revision_cell(index, "", is_summary=(index == summary_col_idx))
            _set_revision_summary_cell(cell, text, expressions)
            row.append(cell)
        else:
            row.append(_make_revision_cell(index, text, is_summary=(index == summary_col_idx)))
    return row


def update_revision_record(document_root, config, expressions=None):
    """用 ``_revision_record.md`` 的数据行替换模板修订记录表，返回写入行数（尊重列语义与多行表头/尾行保留）。"""
    rev_path = config.get("paths", {}).get("revision_record")
    if not rev_path or not os.path.isfile(rev_path):
        return 0
    header_row, data_rows = _parse_revision_markdown(rev_path, return_header=True)
    if not data_rows:
        return 0
    body = document_root.find(qn("body"))
    if body is None:
        return 0
    tbl_info = find_revision_table_info(body)
    if tbl_info is None:
        return 0
    tbl, header_row_idx, (v_col, s_col, d_col, a_col) = tbl_info
    rows = tbl.findall(qn("tr"))
    if len(rows) <= header_row_idx:
        return 0
    header_rows = rows[:header_row_idx + 1]
    # 确保表头具有 tblHeader，以便跨页时自动重复表头
    for hr in header_rows:
        tr_pr = hr.find(qn("trPr"))
        if tr_pr is None:
            tr_pr = etree.SubElement(hr, qn("trPr"))
        if tr_pr.find(qn("tblHeader")) is None:
            etree.SubElement(tr_pr, qn("tblHeader"))

    remaining_rows = rows[header_row_idx + 1:]
    # 先剔除表格末尾纯空行，避免截断尾部审批/说明行 (footer_rows) 识别
    while remaining_rows:
        last_texts = [_cell_text(c).strip() for c in remaining_rows[-1].findall(qn("tc"))]
        if not any(last_texts):
            tbl.remove(remaining_rows.pop())
        else:
            break

    # 识别尾部非版本审批/说明行 (footer_rows) 保留不删
    footer_rows = []
    data_candidate_rows = []
    in_footer = True
    for r in reversed(remaining_rows):
        r_texts = [_cell_text(cell).strip() for cell in r.findall(qn("tc"))]
        if in_footer and is_revision_footer_row(r_texts, v_col):
            footer_rows.insert(0, r)
        else:
            in_footer = False
            data_candidate_rows.insert(0, r)

    # 选取用于克隆样式的原型行（仅从真实数据行中选取，杜绝克隆尾部审批/备注行的合并单元格与样式）
    prototypes = [copy.deepcopy(row) for row in data_candidate_rows] if data_candidate_rows else []

    for row in data_candidate_rows:
        tbl.remove(row)

    # 确定目标表格总列数（若有原型行优先以原型行实际单元格数为准，保证样式克隆能匹配到每个单元格）
    header_cells = header_rows[-1].findall(qn("tc"))
    if prototypes and len(prototypes[0].findall(qn("tc"))) > 0:
        col_count = len(prototypes[0].findall(qn("tc")))
    else:
        col_count = len(header_cells) if header_cells else 4

    # 解析 Markdown 表格的列头映射，支持非标准列顺序或附加列
    md_v_col, md_s_col, md_d_col, md_a_col = (0, 1, 2, 3)
    if header_row:
        mv, ms, md, ma = map_revision_columns(header_row)
        if mv is not None:
            md_v_col = mv
        if ms is not None:
            md_s_col = ms
        if md is not None:
            md_d_col = md
        if ma is not None:
            md_a_col = ma

    insert_after = header_rows[-1]
    for index, row_data in enumerate(data_rows):
        # Markdown 表格语义列: [version, summary, date, author]
        v_val = row_data[md_v_col] if (md_v_col < len(row_data)) else ""
        s_val = row_data[md_s_col] if (md_s_col < len(row_data)) else ""
        d_val = row_data[md_d_col] if (md_d_col < len(row_data)) else ""
        a_val = row_data[md_a_col] if (md_a_col < len(row_data)) else ""
        md_vals = [v_val, s_val, d_val, a_val]
        # 按模板表格列语义重排成目标 Word 行的数据列表
        word_values = [""] * col_count
        if v_col is not None and v_col < col_count:
            word_values[v_col] = md_vals[0]
        if s_col is not None and s_col < col_count:
            word_values[s_col] = md_vals[1]
        if d_col is not None and d_col < col_count:
            word_values[d_col] = md_vals[2]
        if a_col is not None and a_col < col_count:
            word_values[a_col] = md_vals[3]

        # 对未被映射到版本/摘要/日期/作者的其余列，若表头为序号/编号列，自动填入序号
        for c in range(col_count):
            if c not in (v_col, s_col, d_col, a_col):
                # 检查所有表头行在该列的文本（兼容多行表头与纵向合并 w:vMerge）
                h_parts = []
                for hr in header_rows:
                    hr_cells = hr.findall(qn("tc"))
                    if c < len(hr_cells):
                        h_parts.append("".join(hr_cells[c].itertext()).strip().lower())
                h_text = " ".join(p for p in h_parts if p)
                if any(k in h_text for k in ("序号", "no.", "no")):
                    word_values[c] = str(index + 1)

        prototype = None
        if prototypes:
            cand = prototypes[min(index, len(prototypes) - 1)]
            if len(cand.findall(qn("tc"))) == col_count:
                prototype = cand
            elif len(prototypes[0].findall(qn("tc"))) == col_count:
                prototype = prototypes[0]
        row = _clone_revision_row(
            prototype, word_values, expressions=expressions, summary_col_idx=s_col
        )
        insert_after.addnext(row)
        insert_after = row
    return len(data_rows)



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


def _markdown_error(
    path: str, line_no: int, message: str, hint: str = "", rule: str = ""
) -> AutomationError:
    """构造带结构化位置的正文插入阶段错误。

    消息仍以 ``路径:行号`` 开头（旧日志与报告解析依赖该形状），同时
    把位置以 ``locations`` 传给上层，避免只能从文本里反推。
    """
    entry = error_location(path, line_no, message, hint, rule)
    return AutomationError(format_location(entry), locations=[entry])


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
                raise _markdown_error(
                    path,
                    index + 1,
                    "复杂表格标记缺少 XML 文件名",
                    "正确写法形如 <!-- TABLE:1:table_0001.xml -->。",
                    "complex_table_syntax",
                )
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
            raise _markdown_error(
                path,
                index + 1,
                "表格元数据语法无效",
                META_SYNTAX_HINT,
                "table_meta_syntax",
            )
        if table_meta is not None:
            if index + 1 >= len(lines) or not lines[index + 1].strip().startswith("|"):
                raise _markdown_error(
                    path,
                    index + 1,
                    "表格元数据的下一行不是表格（必须紧跟以 | 开头的表头行）。",
                    "如果中间有空行请删除；如果这里本来没有表格，请删除这条元数据注释。",
                    "table_meta_orphan",
                )
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
            heading_text = re.sub(r"<br\s*/?>", "\n", heading.group(2).strip(), flags=re.IGNORECASE)
            insert_element(
                insert_before,
                make_heading(
                    config["headingStyles"],
                    heading_text,
                    len(heading.group(1)),
                    num_id=_heading_num_id(numbering),
                    list_level=len(heading.group(1)) - 1,
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
    update_custom_properties(items, config)
    if doc_type in ("requirement", "design"):
        update_cover(document_root, config)
        update_headers(items, config)

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
                h_text = re.sub(r"<br\s*/?>", "\n", heading.group(1).strip(), flags=re.IGNORECASE)
                h_bm = expressions.register_bookmark(absolute + "#" + h_text)
                slug_text = re.sub(r"\s+", "-", re.sub(r"[^\w\s一-鿿]+", "", h_text.lower(), flags=re.UNICODE)).strip("-")
                if slug_text:
                    slug_key = absolute + "#" + slug_text
                    if slug_key not in expressions.bookmarks:
                        expressions.bookmarks[slug_key] = h_bm
                m_hnum = re.match(r"^(\d+(?:\.\d+)+)", h_text)
                if m_hnum and hasattr(expressions, "section_number_map"):
                    expressions.section_number_map.setdefault(m_hnum.group(1), h_bm)
                    sub_title = h_text[m_hnum.end():].strip()
                    if sub_title and hasattr(expressions, "section_title_map"):
                        expressions.section_title_map.setdefault(sub_title, h_bm)
                        expressions.section_title_map.setdefault(re.sub(r"\s+", "", sub_title), h_bm)
                m_hchap = re.match(r"^第?\s*([0-9一二三四五六七八九十百]+)\s*[章节]", h_text)
                if m_hchap and hasattr(expressions, "section_number_map"):
                    ch_val = _chinese_to_int(m_hchap.group(1))
                    if ch_val is not None:
                        expressions.section_number_map.setdefault("第{0}章".format(ch_val), h_bm)
                        expressions.section_number_map.setdefault(str(ch_val), h_bm)
                m_single_ch = re.match(r"^(\d+)(?:\s+|$)", h_text)
                if m_single_ch and hasattr(expressions, "section_number_map"):
                    ch_val = int(m_single_ch.group(1))
                    expressions.section_number_map.setdefault("第{0}章".format(ch_val), h_bm)
                    expressions.section_number_map.setdefault(str(ch_val), h_bm)
                if hasattr(expressions, "section_title_map"):
                    expressions.section_title_map.setdefault(h_text, h_bm)
                    expressions.section_title_map.setdefault(re.sub(r"\s+", "", h_text), h_bm)

    inserted = 0
    images = 0
    tables = 0
    for entry, markdown_path in chapter_entries:
        if config.get("is_headless") and entry.depth == 1 and entry.title in ("正文", "01-正文"):
            pass
        else:
            insert_element(
                section_properties,
                make_heading(
                config["headingStyles"],
                entry.title,
                entry.depth,
                num_id=_heading_num_id(numbering),
                list_level=entry.depth - 1,
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

    revision_rows = update_revision_record(document_root, config, expressions)
    if revision_rows:
        print("[{0}] 修订记录: 写入 {1} 行".format(doc_type, revision_rows))

    # 模板修订/导航表与复杂表格资源中可能内嵌 HYPERLINK 域与悬空超链接，
    # 指向模板书签；重建文档不生成这些书签，统一解除为静态文本。
    hyperlink_fields = neutralize_hyperlink_fields(document_root)
    dangling_hyperlinks = neutralize_dangling_hyperlinks(document_root)
    total_hyperlinks = hyperlink_fields + dangling_hyperlinks
    if total_hyperlinks:
        print("[{0}] 解除 HYPERLINK 域 {1} 个（目标书签不存在，转为静态文本）".format(
            doc_type, total_hyperlinks
        ))
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
