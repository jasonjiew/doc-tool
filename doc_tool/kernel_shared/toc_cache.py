# -*- coding: utf-8 -*-
"""Refresh standard TOC field labels without inventing pagination.

Only the cached field result is replaced. Unsupported selectors or XML layouts
are left intact with a warning; Word remains responsible for real page numbers.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Callable, Sequence, Tuple

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
Heading = Tuple[int, str, str]  # level, visible label, existing bookmark name


def _toc_fields(root):
    """Pair complex fields in document order, including nested PAGEREFs."""
    stack = []
    for node in root.iter():
        if node.tag == W + "fldChar":
            kind = node.get(W + "fldCharType")
            if kind == "begin":
                stack.append([node, [], None])
            elif kind == "separate" and stack:
                stack[-1][2] = node
            elif kind == "end" and stack:
                begin, instruction, separator = stack.pop()
                instruction = "".join(instruction)
                if re.match(r"\s*TOC\b", instruction, re.I):
                    yield begin, separator, node, instruction
        elif node.tag == W + "instrText" and stack and stack[-1][2] is None:
            stack[-1][1].append(node.text or "")
    for begin, instruction, separator in stack:
        instruction = "".join(instruction)
        if re.match(r"\s*TOC\b", instruction, re.I):
            yield begin, separator, None, instruction


def _entry(level: int, label: str, bookmark: str, properties):
    paragraph = etree.Element(W + "p")
    if properties is not None:
        paragraph.append(deepcopy(properties))
    else:
        etree.SubElement(paragraph, W + "pPr")
    indent = paragraph[0].find(W + "ind")
    if indent is None and properties is None:
        indent = etree.SubElement(paragraph[0], W + "ind")
    if indent is not None:
        indent.set(W + "left", str(max(0, level - 1) * 360))
    hyperlink = etree.SubElement(paragraph, W + "hyperlink", {W + "anchor": bookmark})
    text = etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "t")
    text.text = label
    etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "tab")
    etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "fldChar", {W + "fldCharType": "begin"})
    instruction = etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "instrText", {XML_SPACE: "preserve"})
    instruction.text = ' PAGEREF {0} \\h '.format(bookmark)
    etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "fldChar", {W + "fldCharType": "separate"})
    # A static build cannot know pagination. Do not fabricate page 1 for all entries.
    etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "t").text = "?"
    etree.SubElement(etree.SubElement(hyperlink, W + "r"), W + "fldChar", {W + "fldCharType": "end"})
    return paragraph


def _replace_result(separator, end, paragraphs):
    """Validate every boundary before changing the tree; return an error or None."""
    if separator is None:
        return "目录域缺少 separate 标记"
    sep_run, end_run = separator.getparent(), end.getparent()
    if sep_run is None or end_run is None or sep_run.tag != W + "r" or end_run.tag != W + "r":
        return "目录域的边界不在独立 run 中"
    first, last = sep_run.getparent(), end_run.getparent()
    if first is None or last is None or first.tag != W + "p" or last.tag != W + "p" or first.getparent() is None or first.getparent() is not last.getparent():
        return "目录域跨越了不同的内容容器"
    if sep_run is end_run or any(
        child is not marker and child.tag != W + "rPr"
        for run, marker in ((sep_run, separator), (end_run, end)) for child in run
    ):
        return "目录边界 run 中混有其他内容"
    container = first.getparent()
    siblings = list(container)
    start_index, end_index = siblings.index(first), siblings.index(last)
    sep_index, close_index = list(first).index(sep_run), list(last).index(end_run)
    if end_index < start_index or (first is last and close_index <= sep_index):
        return "目录域边界顺序无效"
    if any(child.tag != W + "p" for child in siblings[start_index + 1:end_index + 1]):
        return "目录缓存包含非段落对象"
    if first is last:
        removed = list(first)[sep_index + 1:close_index]
    else:
        removed = list(first)[sep_index + 1:] + siblings[start_index + 1:end_index] + list(last)[:close_index]
    unsafe = {W + name for name in ("sectPr", "bookmarkStart", "bookmarkEnd", "drawing", "pict", "object", "tbl")}
    if first.find("./" + W + "pPr/" + W + "sectPr") is not None or any(
        node.tag in unsafe for part in removed for node in part.iter()
    ):
        return "目录缓存包含分节、书签或非文本对象，未自动重写"

    allowed = {W + name for name in (
        "p", "pPr", "r", "rPr", "t", "tab", "br", "cr", "hyperlink", "fldChar", "instrText", "fldSimple",
        "noBreakHyphen", "softHyphen", "lastRenderedPageBreak", "proofErr",
    )}
    if any(
        node.tag not in allowed and not any(parent.tag in {W + "pPr", W + "rPr"} for parent in node.iterancestors())
        for part in removed for node in part.iter()
    ):
        return "目录缓存包含非标准文本结构，未自动重写"

    suffix = list(last)[close_index:]
    for child in list(first)[sep_index + 1:]:
        first.remove(child)
    for paragraph in siblings[start_index + 1:end_index + 1]:
        container.remove(paragraph)
    if paragraphs:
        for child in list(paragraphs[0]):
            if child.tag != W + "pPr":
                first.append(child)
        for offset, paragraph in enumerate(paragraphs[1:], 1):
            container.insert(start_index + offset, paragraph)
    tail = paragraphs[-1] if len(paragraphs) > 1 else first
    for child in suffix:
        tail.append(child)
    return None


def update_static_toc_cache(
    root,
    headings: Sequence[Heading],
    warn: Callable[[str], None],
) -> int:
    """Update eligible TOC results and return the number of cached entries.

    ``headings`` must reference bookmarks already present in the document.
    No TOC is created in a template that has none.
    """
    fields = list(_toc_fields(root))
    updated = 0
    for begin, separator, end, instruction in fields:
        if end is None:
            warn("目录域缺少结束标记，静态缓存未改写，请用 Word 修复。")
            continue
        switches = {value.lower() for value in re.findall(r"\\([A-Za-z])", instruction)}
        if switches - {"o", "h", "z", "u"}:
            warn("目录域包含自定义筛选开关，静态缓存未改写，请用 Word 刷新。")
            continue
        match = re.search(r'\\o\s+"?(\d+)\s*-\s*(\d+)"?', instruction, re.I)
        if "o" in switches and match is None:
            warn("目录域级别范围无法识别，静态缓存未改写，请用 Word 刷新。")
            continue
        first_level, last_level = (int(match.group(1)), int(match.group(2))) if match else (1, 3)
        if not 1 <= first_level <= last_level <= 9:
            warn("目录域级别范围无效，静态缓存未改写，请用 Word 刷新。")
            continue
        properties = None
        if separator is not None and separator.getparent().getparent().tag == W + "p":
            properties = separator.getparent().getparent().find(W + "pPr")
        selected = [(level, label, bookmark) for level, label, bookmark in headings if first_level <= level <= last_level]
        paragraphs = [_entry(level, label, bookmark, properties) for level, label, bookmark in selected]
        error = _replace_result(separator, end, paragraphs)
        if error:
            warn(error + "；请用 Word 刷新目录。")
            continue
        begin.set(W + "dirty", "true")
        updated += len(selected)
    for field in root.iter(W + "fldSimple"):
        if re.match(r"\s*TOC\b", field.get(W + "instr", ""), re.I):
            warn("简单 TOC 域未自动重写静态缓存，请用 Word 刷新目录。")
    if updated:
        warn("已生成静态目录缓存；页码需 Word 刷新后更新。")
    return updated
