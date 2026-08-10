# -*- coding: utf-8 -*-
"""Strict validator for generated company DOCX files.

Daily validation compares the generated Word against the current directory
tree/Markdown/resources.  ``--baseline`` additionally compares the generated
business body with the immutable migration source Word; it is intended for
migration acceptance, not future intentional content revisions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
import posixpath
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from docx_common import (
    AutomationError,
    iter_chapter_entries,
    load_config,
    normalize_business_text,
    parse_image_reference,
    parse_markdown_table,
    resolve_resource,
    validate_content_tree,
)


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
RP_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def qn(tag: str) -> str:
    return W_NS + tag


def owner_part_for_rels(rels_name: str) -> str:
    if rels_name == "_rels/.rels":
        return ""
    directory, filename = posixpath.split(rels_name)
    if not directory.endswith("/_rels") or not filename.endswith(".rels"):
        return ""
    return posixpath.join(directory[: -len("/_rels")], filename[:-5])


def resolve_relationship_target(owner_part: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target).lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner_part), target)).lstrip("/")


def paragraph_text(paragraph) -> str:
    parts: List[str] = []
    for node in paragraph.iter():
        if node.tag == qn("t"):
            parts.append(node.text or "")
        elif node.tag in (qn("br"), qn("cr")):
            parts.append("\n")
        elif node.tag == qn("tab"):
            parts.append("\t")
    return "".join(parts).strip()


def table_matrix(table) -> Tuple[Tuple[str, ...], ...]:
    rows: List[Tuple[str, ...]] = []
    for row in table.findall(qn("tr")):
        cells = []
        for cell in row.findall(qn("tc")):
            cells.append(" ".join(paragraph_text(p) for p in cell.findall(qn("p"))).strip())
        rows.append(tuple(cells))
    return tuple(rows)


def canonical_xml(element) -> bytes:
    node = copy.deepcopy(element)
    for item in node.iter():
        for attribute in list(item.attrib):
            if etree.QName(attribute).localname.startswith("rsid"):
                del item.attrib[attribute]
    return etree.tostring(node, method="c14n", exclusive=True, with_comments=True)


def normalize_matrix(matrix: Tuple[Tuple[str, ...], ...]) -> Tuple[Tuple[str, ...], ...]:
    return tuple(tuple(normalize_business_text(cell) for cell in row) for row in matrix)


@dataclass
class Event:
    kind: str
    value: object
    source: str
    xml: Optional[bytes] = None


class DocxPackage:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not os.path.isfile(self.path):
            raise AutomationError("DOCX 不存在: {0}".format(self.path))
        try:
            with zipfile.ZipFile(self.path, "r") as package:
                bad_part = package.testzip()
                if bad_part:
                    raise AutomationError("DOCX ZIP CRC 失败: {0}".format(bad_part))
                self.items = {name: package.read(name) for name in package.namelist()}
        except zipfile.BadZipFile as exc:
            raise AutomationError("DOCX 不是有效 ZIP: {0}".format(exc))
        self.xml_roots: Dict[str, object] = {}
        for name, data in self.items.items():
            if name.endswith(".xml") or name.endswith(".rels"):
                try:
                    self.xml_roots[name] = etree.fromstring(data)
                except Exception as exc:
                    raise AutomationError("XML 无法解析 {0}: {1}".format(name, exc))
        required = (
            "[Content_Types].xml",
            "word/document.xml",
            "word/settings.xml",
            "word/styles.xml",
            "word/_rels/document.xml.rels",
        )
        missing = [name for name in required if name not in self.items]
        if missing:
            raise AutomationError("DOCX 缺少必需部件: {0}".format(", ".join(missing)))
        self.document = self.xml_roots["word/document.xml"]
        self.styles = self.xml_roots["word/styles.xml"]
        self.settings = self.xml_roots["word/settings.xml"]
        self.relationships = self.xml_roots["word/_rels/document.xml.rels"]
        self.heading_styles = self._heading_style_map()
        self.relationship_map = {relationship.get("Id"): relationship for relationship in self.relationships}

    def _heading_style_map(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for style in self.styles.iter(qn("style")):
            if style.get(qn("type")) != "paragraph":
                continue
            name = style.find(qn("name"))
            if name is None:
                continue
            style_name = name.get(qn("val")) or ""
            match = re.match(r"(?i)heading\s*(\d+)", style_name)
            if not match:
                match = re.match(r"标题\s*(\d+)", style_name)
            if match:
                level = int(match.group(1))
                if 1 <= level <= 6:
                    result[style.get(qn("styleId"))] = level
        return result

    def paragraph_level(self, paragraph) -> Optional[int]:
        properties = paragraph.find(qn("pPr"))
        style = properties.find(qn("pStyle")) if properties is not None else None
        return self.heading_styles.get(style.get(qn("val"))) if style is not None else None

    def image_hashes(self, element) -> Tuple[str, ...]:
        hashes: List[str] = []
        for blip in element.iter(A_NS + "blip"):
            rid = blip.get(R_NS + "embed") or blip.get(R_NS + "link")
            relationship = self.relationship_map.get(rid)
            if relationship is None:
                hashes.append("MISSING_REL:" + str(rid))
                continue
            target = resolve_relationship_target("word/document.xml", relationship.get("Target", ""))
            data = self.items.get(target)
            hashes.append(hashlib.sha256(data).hexdigest() if data is not None else "MISSING_PART:" + target)
        return tuple(hashes)

    def body_events(self) -> List[Event]:
        body = self.document.find(qn("body"))
        if body is None:
            raise AutomationError("word/document.xml 缺少 w:body")
        events: List[Event] = []
        started = False
        for index, element in enumerate(body):
            local_name = etree.QName(element).localname
            if local_name == "p":
                level = self.paragraph_level(element)
                text = paragraph_text(element)
                if level == 1:
                    started = True
                if not started:
                    continue
                image_hashes = self.image_hashes(element)
                if level:
                    events.append(Event("H", (level, normalize_business_text(text)), "body[{0}]".format(index)))
                elif image_hashes:
                    events.append(Event("I", image_hashes, "body[{0}]".format(index)))
                elif text:
                    events.append(Event("P", normalize_business_text(text), "body[{0}]".format(index)))
            elif local_name == "tbl" and started:
                events.append(
                    Event(
                        "T",
                        normalize_matrix(table_matrix(element)),
                        "body[{0}]".format(index),
                        canonical_xml(element),
                    )
                )
        return events

    def relationship_errors(self) -> List[str]:
        errors: List[str] = []
        for rels_name, relationship_root in self.xml_roots.items():
            if not rels_name.endswith(".rels"):
                continue
            owner = owner_part_for_rels(rels_name)
            owner_root = self.xml_roots.get(owner)
            referenced_ids = set()
            if owner_root is not None:
                for node in owner_root.iter():
                    for attribute, value in node.attrib.items():
                        if attribute.startswith(R_NS):
                            referenced_ids.add(value)
            relationship_ids = {relationship.get("Id") for relationship in relationship_root}
            for rid in sorted(referenced_ids - relationship_ids):
                errors.append("{0} 引用了不存在的 relationship: {1}".format(owner, rid))
            for relationship in relationship_root:
                if relationship.get("TargetMode") == "External":
                    continue
                target = resolve_relationship_target(owner, relationship.get("Target", ""))
                if target not in self.items:
                    errors.append("{0}:{1} 的 Target 不存在: {2}".format(rels_name, relationship.get("Id"), target))
                if relationship.get("Type") == IMAGE_REL_TYPE and owner_root is not None:
                    if relationship.get("Id") not in referenced_ids:
                        errors.append("孤立图片 relationship: {0}:{1}".format(rels_name, relationship.get("Id")))
        return errors

    def media_metrics(self) -> Tuple[int, int, int]:
        media = [name for name in self.items if name.startswith("word/media/")]
        hashes = [hashlib.sha256(self.items[name]).hexdigest() for name in media]
        duplicate_files = len(hashes) - len(set(hashes))
        duplicate_bytes = 0
        seen = set()
        for name, digest in zip(media, hashes):
            if digest in seen:
                duplicate_bytes += len(self.items[name])
            else:
                seen.add(digest)
        return len(media), duplicate_files, duplicate_bytes

    def section_signatures(self) -> List[bytes]:
        return [canonical_xml(node) for node in self.document.iter(qn("sectPr"))]

    def toc_cached_paragraphs(self) -> List[str]:
        for sdt in self.document.iter(qn("sdt")):
            instruction = "".join(node.text or "" for node in sdt.iter(qn("instrText")))
            if "TOC" not in instruction.upper():
                continue
            result = []
            for paragraph in sdt.iter(qn("p")):
                paragraph_instruction = "".join(node.text or "" for node in paragraph.iter(qn("instrText")))
                if "PAGEREF" in paragraph_instruction.upper():
                    result.append(paragraph_text(paragraph))
            return result
        # Some company templates store the TOC as a plain complex field rather
        # than a content control (w:sdt).  Its cached entry paragraphs still
        # contain PAGEREF fields and are equally verifiable.
        result = []
        for paragraph in self.document.iter(qn("p")):
            instruction = "".join(node.text or "" for node in paragraph.iter(qn("instrText")))
            if "PAGEREF" in instruction.upper():
                result.append(paragraph_text(paragraph))
        return result


def _expected_table_xml(path: str):
    try:
        with open(path, "rb") as xml_file:
            root = etree.fromstring(xml_file.read())
    except Exception as exc:
        raise AutomationError("复杂表格 XML 无法解析 {0}: {1}".format(path, exc))
    if root.tag != qn("tbl"):
        raise AutomationError("复杂表格 XML 根节点不是 w:tbl: {0}".format(path))
    return root


def expected_markdown_events(path: str, config: Dict) -> List[Event]:
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    events: List[Event] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        source = "{0}:{1}".format(path, index + 1)
        complex_table = re.fullmatch(r"<!--\s*TABLE:(\d+):?([\w.\-]+)?\s*-->", stripped)
        if complex_table:
            filename = complex_table.group(2)
            if not filename:
                raise AutomationError("{0} 复杂表格标记缺少 XML 文件名".format(source))
            table_path = resolve_resource(config["paths"]["table_root"], filename, "复杂表格")
            element = _expected_table_xml(table_path)
            events.append(Event("C", normalize_matrix(table_matrix(element)), source, canonical_xml(element)))
            index += 1
            continue
        image = parse_image_reference(stripped)
        if image is not None:
            image_path = resolve_resource(config["paths"]["asset_root"], image.relative_path, "图片")
            with open(image_path, "rb") as image_file:
                image_hash = hashlib.sha256(image_file.read()).hexdigest()
            events.append(Event("I", (image_hash,), source))
            index += 1
            continue
        if stripped.startswith("<!-- TBL:"):
            index += 1
            block: List[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            events.append(Event("T", normalize_matrix(tuple(tuple(row) for row in parse_markdown_table(block))), source))
            continue
        if stripped.startswith("|"):
            block = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            events.append(Event("T", normalize_matrix(tuple(tuple(row) for row in parse_markdown_table(block))), source))
            continue
        heading = re.match(r"^(#{1,9})\s+(.+)$", stripped)
        if heading:
            events.append(Event("H", (len(heading.group(1)), normalize_business_text(heading.group(2))), source))
            index += 1
            continue
        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        if unordered:
            events.append(Event("P", normalize_business_text(unordered.group(1)), source))
            index += 1
            continue
        ordered = re.match(r"^(\d{1,3})[.、].*$", stripped)
        if ordered:
            events.append(Event("P", normalize_business_text(stripped), source))
            index += 1
            continue
        if re.fullmatch(r"<!--\s*P:.*?\s*-->", stripped) or stripped == "<EMPTY_PAR/>" or not stripped:
            index += 1
            continue
        events.append(Event("P", normalize_business_text(stripped), source))
        index += 1
    return events


def expected_content_events(config: Dict) -> List[Event]:
    events: List[Event] = []
    for entry, markdown_path in iter_chapter_entries(config):
        events.append(Event("H", (entry.depth, normalize_business_text(entry.title)), entry.path))
        if markdown_path:
            events.extend(expected_markdown_events(markdown_path, config))
    return events


def compare_expected_events(
    expected: List[Event], actual: List[Event], strict_complex_xml: bool = True
) -> List[str]:
    errors: List[str] = []
    if len(expected) != len(actual):
        errors.append("元素数量不一致: expected={0}, actual={1}".format(len(expected), len(actual)))
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left.kind == "C":
            if right.kind != "T":
                errors.append("#{0} 类型不一致: expected=复杂表格, actual={1}".format(index, right.kind))
            elif left.value != right.value:
                errors.append("#{0} 复杂表格文本不一致: {1} / {2}".format(index, left.source, right.source))
            elif strict_complex_xml and left.xml != right.xml:
                errors.append("#{0} 复杂表格 OOXML 不一致: {1} / {2}".format(index, left.source, right.source))
        elif left.kind != right.kind or left.value != right.value:
            errors.append(
                "#{0} 内容/位置不一致: expected {1}={2!r} ({3}); actual {4}={5!r} ({6})".format(
                    index, left.kind, left.value, left.source, right.kind, right.value, right.source
                )
            )
        if len(errors) >= 20:
            break
    return errors


def compare_baseline_events(source: List[Event], rebuilt: List[Event]) -> List[str]:
    """Compare business order while treating all tables as their text matrices."""
    def signature(event: Event):
        kind = "T" if event.kind in ("T", "C") else event.kind
        return kind, event.value

    errors: List[str] = []
    if len(source) != len(rebuilt):
        errors.append("业务元素数量不一致: source={0}, rebuild={1}".format(len(source), len(rebuilt)))
    for index, (left, right) in enumerate(zip(source, rebuilt)):
        if signature(left) != signature(right):
            errors.append(
                "#{0} 基线内容/位置不一致: source {1}={2!r}; rebuild {3}={4!r}".format(
                    index, left.kind, left.value, right.kind, right.value
                )
            )
        if len(errors) >= 20:
            break
    return errors


def normalized_part(package: DocxPackage, name: str, remove_update_fields: bool = False) -> Optional[bytes]:
    root = package.xml_roots.get(name)
    if root is None:
        return None
    node = copy.deepcopy(root)
    if remove_update_fields:
        for item in node.findall(qn("updateFields")):
            node.remove(item)
    return canonical_xml(node)


def template_preservation_errors(template: DocxPackage, output: DocxPackage) -> Dict[str, List[str]]:
    errors = {"styles": [], "numbering": [], "headers": [], "footers": [], "sections": [], "settings": []}
    for name, category in (
        ("word/styles.xml", "styles"),
        ("word/numbering.xml", "numbering"),
        ("word/fontTable.xml", "styles"),
        ("word/theme/theme1.xml", "styles"),
    ):
        if normalized_part(template, name) != normalized_part(output, name):
            errors[category].append("模板部件变化: {0}".format(name))
    for prefix, category in (("word/header", "headers"), ("word/footer", "footers")):
        names = sorted(
            name for name in set(template.items) | set(output.items) if name.startswith(prefix) and name.endswith(".xml")
        )
        for name in names:
            if normalized_part(template, name) != normalized_part(output, name):
                errors[category].append("模板部件变化: {0}".format(name))
    if template.section_signatures() != output.section_signatures():
        errors["sections"].append("Section 数量/页面尺寸/方向/边距/页眉页脚引用发生变化")
    if normalized_part(template, "word/settings.xml", True) != normalized_part(output, "word/settings.xml", True):
        errors["settings"].append("settings.xml 除 updateFields 外发生变化")
    return errors


def _style_id_names(package: DocxPackage) -> Dict[str, str]:
    result = {}
    for style in package.styles.findall(qn("style")):
        name = style.find(qn("name"))
        if name is not None:
            result[style.get(qn("styleId"))] = name.get(qn("val")) or ""
    return result


def _paragraph_style_names(package: DocxPackage) -> set:
    result = set()
    for style in package.styles.findall(qn("style")):
        if style.get(qn("type")) != "paragraph":
            continue
        name = style.find(qn("name"))
        if name is not None:
            result.add(name.get(qn("val")) or "")
    return result


def _numbering_signature(package: DocxPackage) -> Counter:
    style_names = _style_id_names(package)
    root = package.xml_roots.get("word/numbering.xml")
    if root is None:
        return Counter()
    signatures = []
    for abstract in root.findall(qn("abstractNum")):
        levels = []
        for level in abstract.findall(qn("lvl")):
            def value(tag):
                item = level.find(qn(tag))
                return item.get(qn("val")) if item is not None else None

            style_id = value("pStyle")
            levels.append(
                (
                    level.get(qn("ilvl")),
                    value("start"),
                    value("numFmt"),
                    value("lvlText"),
                    value("suff"),
                    value("lvlJc"),
                    style_names.get(style_id, style_id),
                )
            )
        signatures.append(tuple(levels))
    return Counter(signatures)


def _section_geometry(package: DocxPackage) -> List[Tuple]:
    result = []
    for section in package.document.iter(qn("sectPr")):
        parts = []
        for tag in ("pgSz", "pgMar", "cols"):
            item = section.find(qn(tag))
            attributes = []
            if item is not None:
                for attribute, value in item.attrib.items():
                    local = etree.QName(attribute).localname
                    if tag == "cols" and local == "num" and value == "1":
                        continue
                    attributes.append((local, value))
            parts.append((tag, tuple(sorted(attributes))))
        parts.append(("titlePg", section.find(qn("titlePg")) is not None))
        result.append(tuple(parts))
    return result


def _static_paragraph_text(paragraph) -> str:
    parts = []
    field_depth = 0
    result_depth = 0
    for node in paragraph.iter():
        if node.tag == qn("fldChar"):
            kind = node.get(qn("fldCharType"))
            if kind == "begin":
                field_depth += 1
            elif kind == "separate" and field_depth:
                result_depth = field_depth
            elif kind == "end" and field_depth:
                if result_depth == field_depth:
                    result_depth = 0
                field_depth -= 1
        elif node.tag == qn("t") and not result_depth:
            parts.append(node.text or "")
        elif node.tag in (qn("br"), qn("cr")) and not result_depth:
            parts.append("\n")
        elif node.tag == qn("tab") and not result_depth:
            parts.append("\t")
    return normalize_business_text("".join(parts))


def _part_image_hashes(package: DocxPackage, part_name: str, root) -> Tuple[str, ...]:
    directory, filename = posixpath.split(part_name)
    rels_name = posixpath.join(directory, "_rels", filename + ".rels")
    relationships = package.xml_roots.get(rels_name)
    relationship_map = {item.get("Id"): item for item in relationships} if relationships is not None else {}
    hashes = []
    for blip in root.iter(A_NS + "blip"):
        rid = blip.get(R_NS + "embed") or blip.get(R_NS + "link")
        relationship = relationship_map.get(rid)
        if relationship is None:
            hashes.append("MISSING:" + str(rid))
            continue
        target = resolve_relationship_target(part_name, relationship.get("Target", ""))
        data = package.items.get(target)
        hashes.append(hashlib.sha256(data).hexdigest() if data is not None else "MISSING:" + target)
    return tuple(hashes)


def _header_footer_signatures(package: DocxPackage, prefix: str) -> Counter:
    signatures = []
    for name in sorted(
        item for item in package.items if item.startswith(prefix) and item.endswith(".xml")
    ):
        root = package.xml_roots[name]
        paragraphs = tuple(
            text for text in (_static_paragraph_text(item) for item in root.iter(qn("p"))) if text
        )
        tables = tuple(
            tuple(
                tuple(
                    " ".join(_static_paragraph_text(p) for p in cell.findall(qn("p"))).strip()
                    for cell in row.findall(qn("tc"))
                )
                for row in table.findall(qn("tr"))
            )
            for table in root.iter(qn("tbl"))
        )
        # Word may split one field instruction across several instrText runs
        # when saving.  The concatenated instruction stream is stable.
        fields = normalize_business_text(
            " ".join(node.text or "" for node in root.iter(qn("instrText")) if (node.text or "").strip())
        )
        images = _part_image_hashes(package, name, root)
        signature = (paragraphs, tables, fields, images)
        if any(signature):
            signatures.append(signature)
    return Counter(signatures)


def _setting_enabled(root, tag: str) -> bool:
    item = root.find(qn(tag))
    if item is None:
        return False
    return (item.get(qn("val")) or "true").lower() not in ("0", "false", "off")


def word_semantic_preservation_errors(
    template: DocxPackage, output: DocxPackage, config: Dict
) -> Dict[str, List[str]]:
    """Validate stable format semantics after Microsoft Word normalizes OOXML.

    The pipeline already runs byte-strict template checks immediately before
    Word opens the file.  This second layer checks properties that must remain
    stable across Word's style-ID renumbering and removal of empty header parts.
    """
    errors = {"styles": [], "numbering": [], "headers": [], "footers": [], "sections": [], "settings": []}
    template_style_names = _style_id_names(template)
    output_paragraph_names = _paragraph_style_names(output)
    required_style_ids = [str(value) for value in config["headingStyles"].values()] + [str(config["bodyStyle"])]
    required_style_names = {template_style_names.get(style_id, "") for style_id in required_style_ids}
    if "" in required_style_names or not required_style_names.issubset(output_paragraph_names):
        errors["styles"].append("Word 刷新后配置的 Heading/正文段落样式缺失")
    required_levels = set(config["headingStyles"])
    if not required_levels.issubset(set(output.heading_styles.values())):
        errors["styles"].append("Word 刷新后缺少配置的 Heading 样式")
    a_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    template_theme_root = template.xml_roots.get("word/theme/theme1.xml")
    output_theme_root = output.xml_roots.get("word/theme/theme1.xml")
    template_theme = (
        template_theme_root.find(a_ns + "themeElements")
        if template_theme_root is not None else None
    )
    output_theme = (
        output_theme_root.find(a_ns + "themeElements")
        if output_theme_root is not None else None
    )
    if (template_theme is None) != (output_theme is None) or (
        template_theme is not None
        and canonical_xml(template_theme) != canonical_xml(output_theme)
    ):
        errors["styles"].append("Word 刷新后主题字体/颜色定义变化")
    # Word prunes unused duplicate abstract numbering definitions when saving.
    # Every retained definition must still be present with identical semantics.
    if _numbering_signature(output) - _numbering_signature(template):
        errors["numbering"].append("Word 刷新后保留的编号级别、格式或标题关联变化")
    if _section_geometry(template) != _section_geometry(output):
        errors["sections"].append("Word 刷新后 Section 数量、纸张、方向或页边距变化")
    if _header_footer_signatures(template, "word/header") != _header_footer_signatures(output, "word/header"):
        errors["headers"].append("Word 刷新后非空页眉的静态文本、域、表格或图片变化")
    if _header_footer_signatures(template, "word/footer") != _header_footer_signatures(output, "word/footer"):
        errors["footers"].append("Word 刷新后非空页脚的静态文本、域、表格或图片变化")
    for tag in ("evenAndOddHeaders", "mirrorMargins", "gutterAtTop", "bookFoldPrinting", "trackRevisions"):
        if _setting_enabled(template.settings, tag) != _setting_enabled(output.settings, tag):
            errors["settings"].append("Word 刷新后设置变化: {0}".format(tag))
    return errors


def cover_values(package: DocxPackage) -> Tuple[Dict[str, str], Dict[str, str]]:
    values: Dict[str, str] = {}
    fields: Dict[str, str] = {}
    expected = {"文件编号", "版本号", "页数"}
    tables = []
    for table in package.document.iter(qn("tbl")):
        labels = {_cell_text(cell).rstrip("：:").strip() for cell in table.iter(qn("tc"))}
        if expected.issubset(labels):
            tables.append(table)
    if len(tables) != 1:
        return values, fields
    for row in tables[0].findall(qn("tr")):
        cells = row.findall(qn("tc"))
        texts = [_cell_text(cell).rstrip("：:").strip() for cell in cells]
        for index, label in enumerate(texts[:-1]):
            if label in expected:
                cell = cells[index + 1]
                values[label] = _cell_text(cell)
                fields[label] = "".join(node.text or "" for node in cell.iter(qn("instrText"))).strip()
    return values, fields


def _cell_text(cell) -> str:
    return "".join(node.text or "" for node in cell.iter(qn("t"))).strip()


def expected_heading_titles(events: List[Event], max_level: int = 3) -> List[str]:
    return [event.value[1] for event in events if event.kind == "H" and event.value[0] <= max_level]


def expected_toc_labels(config: Dict, max_level: int = 3) -> List[str]:
    result = []
    for entry, _ in iter_chapter_entries(config):
        if entry.depth > max_level:
            continue
        if entry.depth == 1:
            prefix = "第{0}章".format(entry.number[0])
        else:
            prefix = ".".join(str(value) for value in entry.number)
        result.append(normalize_business_text(prefix + " " + entry.title))
    return result


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


class Report:
    def __init__(self, doc_type: str, output: str):
        self.doc_type = doc_type
        self.output = output
        self.checks: List[Check] = []
        self.metrics: Dict[str, object] = {}

    def row_check(self, *, name: str, ok: bool, detail: str = "") -> None:
        if type(ok) is not bool:
            raise TypeError("row_check(ok=...) 必须是 bool，实际为 {0}".format(type(ok).__name__))
        self.checks.append(Check(name, ok, detail))

    def render(self) -> str:
        lines = ["# {0} 严格校验报告".format(self.doc_type), "", "- 输出: `{0}`".format(self.output), ""]
        lines.extend(("## 校验结果", ""))
        for check in self.checks:
            lines.append("- [{0}] {1}{2}".format("PASS" if check.ok else "FAIL", check.name, " — " + check.detail if check.detail else ""))
        lines.extend(("", "## 关键指标", ""))
        for key, value in self.metrics.items():
            lines.append("- {0}: {1}".format(key, value))
        passes = sum(check.ok for check in self.checks)
        failures = len(self.checks) - passes
        lines.extend(("", "## 总结", "", "- PASS: {0}".format(passes), "- FAIL: {0}".format(failures)))
        lines.append("- 结论: **{0}**".format("通过" if failures == 0 else "失败"))
        return "\n".join(lines) + "\n"


def validate(
    doc_type: Optional[str] = None,
    output_override: Optional[str] = None,
    baseline: bool = False,
    require_refreshed: bool = False,
    report_override: Optional[str] = None,
    config: Optional[Dict] = None,
) -> bool:
    if config is None:
        if doc_type is None:
            raise AutomationError("必须提供 doc_type 或 config 参数")
        config = load_config(doc_type)
    doc_type = config["documentType"]
    entries = validate_content_tree(config)
    output_path = os.path.abspath(output_override or config["paths"]["output"])
    report = Report(doc_type, output_path)

    output = DocxPackage(output_path)
    template = DocxPackage(config["paths"]["template"])
    expected = expected_content_events(config)
    actual = output.body_events()
    event_errors = compare_expected_events(expected, actual, strict_complex_xml=not require_refreshed)

    relationship_errors = output.relationship_errors()
    media_count, duplicate_media, duplicate_bytes = output.media_metrics()
    illegal_update = list(output.document.findall(qn("updateFields")))
    settings_update = output.settings.findall(qn("updateFields"))
    root_children = [etree.QName(child).localname for child in output.document]
    legal_root = root_children.count("body") == 1 and all(name in ("background", "body") for name in root_children)
    body = output.document.find(qn("body"))
    legal_sectpr = body is not None and len(body) > 0 and body[-1].tag == qn("sectPr")

    headings_expected = [event.value for event in expected if event.kind == "H"]
    headings_actual = [event.value for event in actual if event.kind == "H"]
    paragraphs_expected = [event.value for event in expected if event.kind == "P"]
    paragraphs_actual = [event.value for event in actual if event.kind == "P"]
    normal_tables_expected = [event for event in expected if event.kind == "T"]
    complex_tables_expected = [event for event in expected if event.kind == "C"]
    tables_actual = [event for event in actual if event.kind == "T"]
    images_expected = [event.value for event in expected if event.kind == "I"]
    images_actual = [event.value for event in actual if event.kind == "I"]

    preservation = (
        word_semantic_preservation_errors(template, output, config)
        if require_refreshed
        else template_preservation_errors(template, output)
    )
    company_profile = doc_type in ("requirement", "design")
    cover_text, cover_fields = cover_values(output)
    cover_ok = not company_profile or (
        cover_text.get("文件编号") == str(config["documentNo"])
        and cover_text.get("版本号") == str(config["documentVersion"])
        and "NUMPAGES" in cover_fields.get("页数", "").upper()
    )
    toc_instruction = " ".join(node.text or "" for node in output.document.iter(qn("instrText")))
    has_toc = "TOC" in toc_instruction.upper()

    report.row_check(name="DOCX ZIP 与全部 XML 可解析", ok=True)
    report.row_check(
        name="Relationship Target 与引用完整",
        ok=not relationship_errors,
        detail="；".join(relationship_errors[:10]),
    )
    report.row_check(name="章节编号、层级与必需资源预检", ok=True, detail="章节条目 {0}".format(len(entries)))
    report.row_check(
        name="目录/Markdown 与 Word 元素顺序、上下文严格一致",
        ok=not event_errors,
        detail="；".join(event_errors[:5]),
    )
    report.row_check(name="Heading 数量、文本、层级、顺序一致", ok=headings_expected == headings_actual)
    report.row_check(name="正文文本与位置一致", ok=paragraphs_expected == paragraphs_actual)
    report.row_check(
        name="普通表格文本一致",
        ok=len(tables_actual) == len(normal_tables_expected) + len(complex_tables_expected) and not any("表格文本" in e for e in event_errors),
    )
    report.row_check(
        name="复杂表格 OOXML 一致",
        ok=not any("复杂表格" in error for error in event_errors),
        detail="复杂表格 {0}".format(len(complex_tables_expected)),
    )
    report.row_check(name="图片对象、内容哈希与位置一致", ok=images_expected == images_actual)
    report.row_check(
        name="媒体无重复打包",
        ok=duplicate_media == 0,
        detail="media={0}, duplicateFiles={1}, duplicateBytes={2}".format(media_count, duplicate_media, duplicate_bytes),
    )
    report.row_check(name="document.xml 根节点结构合法", ok=legal_root and legal_sectpr)
    update_fields_ok = not illegal_update and (
        (require_refreshed and len(settings_update) == 0)
        or (
            len(settings_update) == 1
            and settings_update[0].get(qn("val")) in ("1", "true", "on")
        )
    )
    report.row_check(
        name=("Word 已消费 updateFields 且 document.xml 无非法节点" if require_refreshed else "updateFields 仅位于 settings.xml"),
        ok=update_fields_ok,
    )
    phase = "Word 刷新后语义" if require_refreshed else ""
    report.row_check(name="Styles/Font/Theme {0}保持模板体系".format(phase), ok=not preservation["styles"], detail="；".join(preservation["styles"]))
    report.row_check(name="Numbering {0}保持模板体系".format(phase), ok=not preservation["numbering"], detail="；".join(preservation["numbering"]))
    report.row_check(name="Section/方向/页边距 {0}保持模板体系".format(phase), ok=not preservation["sections"], detail="；".join(preservation["sections"]))
    report.row_check(name="Header {0}保持模板体系".format(phase), ok=not preservation["headers"], detail="；".join(preservation["headers"]))
    report.row_check(name="Footer {0}保持模板体系".format(phase), ok=not preservation["footers"], detail="；".join(preservation["footers"]))
    report.row_check(name="settings.xml {0}保持模板体系".format(phase), ok=not preservation["settings"], detail="；".join(preservation["settings"]))
    if company_profile:
        report.row_check(name="封面编号、版本与 NUMPAGES 字段正确", ok=cover_ok, detail=str(cover_text))
        report.row_check(name="TOC 域存在", ok=has_toc)

    if require_refreshed and company_profile:
        toc_cached = output.toc_cached_paragraphs()
        toc_expected = expected_toc_labels(config, 3)
        cached_labels = [
            re.sub(r"\s+\d+\s*$", "", normalize_business_text(text)).strip()
            for text in toc_cached
        ]
        toc_ok = cached_labels == toc_expected
        page_cached = cover_text.get("页数", "")
        page_ok = page_cached.isdigit() and int(page_cached) > 0
        report.row_check(
            name="TOC 缓存已刷新且与 H1~H3 一致",
            ok=toc_ok,
            detail="expected={0}, cached={1}".format(len(toc_expected), len(toc_cached)),
        )
        report.row_check(name="封面总页数字段已刷新", ok=page_ok, detail="cached={0}".format(page_cached))

    if baseline:
        baseline_path = config["paths"].get("baseline")
        if not baseline_path:
            report.row_check(name="迁移基线已配置", ok=False, detail="config.baseline.file 缺失")
        else:
            source = DocxPackage(baseline_path)
            baseline_errors = compare_baseline_events(source.body_events(), actual)
            report.row_check(
                name="原 Word 与重建 Word 业务元素顺序/文本严格一致",
                ok=not baseline_errors,
                detail="；".join(baseline_errors[:5]),
            )
            source_headings = [event.value for event in source.body_events() if event.kind == "H"]
            report.row_check(name="原 Word Heading 层次未改变", ok=source_headings == headings_actual)

    md_count = sum(1 for directory, _, files in os.walk(config["paths"]["content_root"]) for name in files if name.lower().endswith(".md"))
    report.metrics.update(
        {
            "Markdown": md_count,
            "Heading": len(headings_actual),
            "正文段落(非空)": len(paragraphs_actual),
            "普通表格": len(normal_tables_expected),
            "复杂表格": len(complex_tables_expected),
            "Word 顶层表格": len(tables_actual),
            "图片": len(images_actual),
            "媒体部件": media_count,
            "重复媒体": duplicate_media,
            "DOCX 大小(字节)": os.path.getsize(output_path),
        }
    )
    text = report.render()
    report_path = report_override or os.path.join(config["_base"], "analysis", doc_type + "-validation.md")
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    failures = [check for check in report.checks if not check.ok]
    print("[{0}] 校验报告: {1}".format(doc_type, report_path))
    print("[{0}] PASS={1} FAIL={2}".format(doc_type, len(report.checks) - len(failures), len(failures)))
    for check in failures[:10]:
        print("[FAIL] {0}: {1}".format(check.name, check.detail), file=sys.stderr)
    return not failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="严格校验重建 Word")
    parser.add_argument("document", choices=("requirement", "design", "all"), nargs="?", default="all")
    parser.add_argument("--output", help="仅单文档时覆盖待校验输出路径")
    parser.add_argument("--report", help="仅单文档时覆盖报告路径")
    parser.add_argument("--baseline", action="store_true", help="同时与迁移原 Word 严格比较")
    parser.add_argument("--require-refreshed", action="store_true", help="要求 TOC/NUMPAGES 缓存已刷新")
    args = parser.parse_args(argv)
    if args.document == "all" and (args.output or args.report):
        parser.error("--output/--report 仅可用于单文档")
    targets = ("requirement", "design") if args.document == "all" else (args.document,)
    ok = True
    try:
        for target in targets:
            if not validate(
                target,
                output_override=args.output,
                baseline=args.baseline,
                require_refreshed=args.require_refreshed,
                report_override=args.report,
            ):
                ok = False
    except (AutomationError, OSError, zipfile.BadZipFile, etree.LxmlError, TypeError) as exc:
        print("[FAIL] Validator 异常: {0}".format(exc), file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
