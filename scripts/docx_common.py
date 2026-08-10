# -*- coding: utf-8 -*-
"""Shared, deterministic input rules for the DOCX automation workflow.

This module intentionally contains only configuration, chapter-tree and
Markdown/resource parsing.  DOCX generation and DOCX validation remain
separate so that the validator can inspect generated OOXML independently.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml
from lxml import etree
from PIL import Image


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AutomationError(RuntimeError):
    """A user-actionable build/validation error."""


@dataclass(frozen=True)
class ChapterEntry:
    kind: str
    number: Tuple[int, ...]
    title: str
    path: str
    depth: int


@dataclass(frozen=True)
class ImageReference:
    alt: str
    relative_path: str
    width_px: Optional[int]
    height_px: Optional[int]


FULLWIDTH_REV = {
    "\uff0f": "/",
    "\uff1a": ":",
    "\uff0a": "*",
    "\uff1f": "?",
    "\u201d": '"',
    "\uff1c": "<",
    "\uff1e": ">",
    "\uff5c": "|",
    "\uff3c": "\\",
}


def display_number(number: Sequence[int]) -> str:
    return ".".join(str(value) for value in number)


def parse_title(name: str) -> Tuple[Optional[Tuple[int, ...]], str]:
    """Parse a chapter-number prefix while restoring filename-safe glyphs."""
    text = "".join(FULLWIDTH_REV.get(char, char) for char in name)
    match = re.fullmatch(r"第(\d+)章\s+(.+)", text)
    if match:
        return (int(match.group(1)),), match.group(2).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)*)\s+(.+)", text)
    if match:
        return tuple(int(part) for part in match.group(1).split(".")), match.group(2).strip()
    return None, text.strip()


def _format_config_value(value, values):
    if isinstance(value, str):
        return value.format_map(values)
    return value


def discover_document_types(base: str = BASE) -> List[str]:
    """扫描 ``config/`` 目录下的 ``.yml`` 文件，返回类型名（文件主名）列表。

    通用大文档改造后，构建/校验/刷新 CLI 不再硬编码 ``requirement``/``design``，
    而是根据 ``config/`` 实际存在的配置文件动态决定可选类型，新增类型只需放入
    一个新的 ``config/<type>.yml`` 即可被识别。返回结果按文件名排序，保证 CLI
    ``choices`` 与 ``all`` 展开顺序稳定。``config/`` 目录不存在或为空时返回空列表，
    由调用方决定如何处理（CLI 通常会以非零退出码报错）。
    """
    config_dir = os.path.join(base, "config")
    if not os.path.isdir(config_dir):
        return []
    names = [
        os.path.splitext(name)[0]
        for name in os.listdir(config_dir)
        if name.lower().endswith(".yml")
        and not name.startswith(".")
        and os.path.isfile(os.path.join(config_dir, name))
    ]
    return sorted(names)


def load_config(doc_type: str, base: str = BASE) -> Dict:
    config_path = os.path.join(base, "config", doc_type + ".yml")
    if not os.path.isfile(config_path):
        raise AutomationError("配置不存在: {0}".format(config_path))
    with open(config_path, encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    required = ("documentType", "documentNo", "documentName", "documentVersion")
    missing = [key for key in required if not str(config.get(key, "")).strip()]
    if missing:
        raise AutomationError("配置缺少必填项: {0}".format(", ".join(missing)))
    if config["documentType"] != doc_type:
        raise AutomationError("配置 documentType 与命令参数不一致: {0}".format(config["documentType"]))

    values = dict(config)
    config_dir = os.path.dirname(config_path)

    def resolve(value: str) -> str:
        formatted = _format_config_value(value, values)
        return os.path.abspath(os.path.normpath(os.path.join(config_dir, formatted)))

    try:
        paths = {
            "template": resolve(config["template"]["file"]),
            "content_root": resolve(config["contentRoot"]["path"]),
            "asset_root": resolve(config["assetRoot"]),
            "table_root": resolve(config["tableRoot"]),
            "output": resolve(config["output"]["file"]),
        }
    except (KeyError, TypeError) as exc:
        raise AutomationError("配置路径项不完整: {0}".format(exc))
    baseline = config.get("baseline", {}).get("file") if isinstance(config.get("baseline"), dict) else None
    if baseline:
        paths["baseline"] = resolve(baseline)

    config["_config_path"] = config_path
    config["_base"] = base
    config["paths"] = paths
    config["headingStyles"] = {
        int(level): str(style_id) for level, style_id in (config.get("headingStyles") or {}).items()
    }
    if not config["headingStyles"]:
        raise AutomationError("headingStyles 不能为空")
    return config


def scan_entries(directory: str, depth: int) -> List[ChapterEntry]:
    entries: List[ChapterEntry] = []
    invalid: List[str] = []
    for name in os.listdir(directory):
        if name.startswith(".") or name.startswith("_"):
            continue
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            stem = name
            kind = "dir"
        elif os.path.isfile(path) and name.lower().endswith(".md"):
            stem = name[:-3]
            kind = "md"
        else:
            invalid.append(path)
            continue
        number, title = parse_title(stem)
        if number is None:
            invalid.append(path)
            continue
        entries.append(ChapterEntry(kind, number, title, path, depth))
    if invalid:
        raise AutomationError(
            "章节目录只能包含带编号的文件夹/Markdown；以下条目无效:\n- " + "\n- ".join(invalid)
        )
    entries.sort(key=lambda entry: entry.number)
    return entries


_IMAGE_WITH_INNER_SIZE = re.compile(
    r"^!\[([^\]]*)\]\(\s*(.+?)\s+=(\d+)x(\d+)\s*\)\s*$"
)
_IMAGE_WITH_OUTER_SIZE = re.compile(
    r"^!\[([^\]]*)\]\(\s*(.+?)\s*\)\s*=(\d+)x(\d+)\s*$"
)
_IMAGE_NO_SIZE = re.compile(r"^!\[([^\]]*)\]\(\s*(.+?)\s*\)\s*$")


def parse_image_reference(line: str) -> Optional[ImageReference]:
    stripped = line.strip()
    match = _IMAGE_WITH_INNER_SIZE.fullmatch(stripped) or _IMAGE_WITH_OUTER_SIZE.fullmatch(stripped)
    if match:
        return ImageReference(
            match.group(1), match.group(2).strip(), int(match.group(3)), int(match.group(4))
        )
    match = _IMAGE_NO_SIZE.fullmatch(stripped)
    if match:
        return ImageReference(match.group(1), match.group(2).strip(), None, None)
    return None


def _inside_root(root: str, candidate: str) -> bool:
    try:
        return os.path.commonpath((os.path.abspath(root), os.path.abspath(candidate))) == os.path.abspath(root)
    except ValueError:
        return False


def resolve_resource(root: str, relative_path: str, label: str) -> str:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", relative_path):
        raise AutomationError("{0}不支持远程 URL: {1}".format(label, relative_path))
    candidate = os.path.abspath(os.path.normpath(os.path.join(root, relative_path)))
    if not _inside_root(root, candidate):
        raise AutomationError("{0}路径越出资源目录: {1}".format(label, relative_path))
    return candidate


def split_markdown_table_row(line: str) -> List[str]:
    r"""Split a pipe table row without treating ``\|`` as a delimiter.

    Only the two escapes required by the project are decoded here:
    ``\|`` becomes ``|`` and ``\\`` becomes ``\``.  Other backslashes are
    preserved because they may be business data, Windows paths or regex text.
    """
    value = line.strip()
    if not value.startswith("|"):
        raise AutomationError("Markdown 表格行必须以 | 开头: {0}".format(line))
    cells: List[str] = []
    current: List[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value) and value[index + 1] in ("|", "\\"):
            current.append(value[index + 1])
            index += 2
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current))
    if cells and not cells[0].strip():
        cells.pop(0)
    if cells and not cells[-1].strip():
        cells.pop()
    return [re.sub(r"<br\s*/?>", "\n", cell.strip(), flags=re.IGNORECASE) for cell in cells]


def parse_markdown_table(lines: Iterable[str]) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in lines:
        cells = split_markdown_table_row(line)
        if cells and all(re.fullmatch(r":?-{1,}:?", cell or "") for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return rows
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def _validate_markdown(path: str, depth: int, config: Dict, errors: List[str]) -> None:
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        heading = re.match(r"^(#{1,9})\s+(.+)$", stripped)
        if heading and len(heading.group(1)) <= depth:
            errors.append(
                "{0}:{1} 内部标题层级必须深于文件章节层级 H{2}: {3}".format(
                    path, line_number, depth, stripped
                )
            )

        table_marker = re.fullmatch(r"<!--\s*TABLE:(\d+):?([\w.\-]+)?\s*-->", stripped)
        if stripped.startswith("<!-- TABLE:") and not table_marker:
            errors.append("{0}:{1} 复杂表格标记语法无效: {2}".format(path, line_number, stripped))
        if table_marker:
            filename = table_marker.group(2)
            if not filename:
                errors.append("{0}:{1} 复杂表格标记缺少 XML 文件名".format(path, line_number))
            else:
                table_path = resolve_resource(config["paths"]["table_root"], filename, "复杂表格")
                if not os.path.isfile(table_path):
                    errors.append("{0}:{1} 复杂表格 XML 不存在: {2}".format(path, line_number, table_path))
                else:
                    try:
                        etree.parse(table_path)
                    except Exception as exc:  # lxml exposes several parse exception types
                        errors.append("{0}:{1} 复杂表格 XML 无法解析: {2}".format(path, line_number, exc))

        image_ref = parse_image_reference(stripped)
        if stripped.startswith("![") and image_ref is None:
            errors.append("{0}:{1} 图片 Markdown 语法无效: {2}".format(path, line_number, stripped))
        if image_ref is not None:
            image_path = resolve_resource(config["paths"]["asset_root"], image_ref.relative_path, "图片")
            if not os.path.isfile(image_path):
                errors.append("{0}:{1} 图片不存在: {2}".format(path, line_number, image_path))
            else:
                try:
                    with Image.open(image_path) as image:
                        image.verify()
                except Exception as exc:
                    errors.append("{0}:{1} 图片损坏或格式不支持: {2}".format(path, line_number, exc))


def validate_content_tree(config: Dict) -> List[ChapterEntry]:
    """Validate numbering, hierarchy and required resources before building."""
    root = config["paths"]["content_root"]
    if not os.path.isdir(root):
        raise AutomationError("contentRoot 目录不存在: {0}".format(root))
    for key in ("template", "asset_root", "table_root"):
        path = config["paths"][key]
        if key == "template" and not os.path.isfile(path):
            raise AutomationError("模板不存在: {0}".format(path))
        if key != "template" and not os.path.isdir(path):
            raise AutomationError("资源目录不存在: {0}".format(path))

    errors: List[str] = []
    flattened: List[ChapterEntry] = []
    max_heading = max(config["headingStyles"])

    def walk(directory: str, parent: Tuple[int, ...], depth: int) -> None:
        if depth > max_heading:
            errors.append("章节层级 H{0} 超过 headingStyles 配置范围: {1}".format(depth, directory))
            return
        try:
            entries = scan_entries(directory, depth)
        except AutomationError as exc:
            errors.append(str(exc))
            return
        for position, entry in enumerate(entries, start=1):
            expected = parent + (position,)
            if len(entry.number) != depth or entry.number[:-1] != parent or entry.number != expected:
                expected_number = display_number(expected)
                actual_number = display_number(entry.number)
                suffix = "" if entry.kind == "dir" else ".md"
                errors.append(
                    "{0}: 编号 {1} 与层级/顺序不一致；实际预期编号为 {2}，请改为“{2} {3}{4}”".format(
                        entry.path, actual_number, expected_number, entry.title, suffix
                    )
                )
            flattened.append(entry)
            if entry.kind == "dir":
                index_path = os.path.join(entry.path, "_index.md")
                if os.path.isfile(index_path):
                    _validate_markdown(index_path, depth, config, errors)
                walk(entry.path, entry.number, depth + 1)
                try:
                    child_entries = scan_entries(entry.path, depth + 1)
                except AutomationError:
                    child_entries = []
                if not child_entries and not os.path.isfile(index_path):
                    errors.append("空章节目录既没有 _index.md 也没有子章节: {0}".format(entry.path))
            else:
                _validate_markdown(entry.path, depth, config, errors)

    walk(root, tuple(), 1)
    if errors:
        raise AutomationError("构建前检查失败:\n- " + "\n- ".join(errors))
    return flattened


def iter_chapter_entries(config: Dict) -> Iterable[Tuple[ChapterEntry, Optional[str]]]:
    """Yield headings in document order and the Markdown file attached to each."""
    root = config["paths"]["content_root"]

    def walk(directory: str, depth: int):
        for entry in scan_entries(directory, depth):
            if entry.kind == "dir":
                index_path = os.path.join(entry.path, "_index.md")
                yield entry, index_path if os.path.isfile(index_path) else None
                yield from walk(entry.path, depth + 1)
            else:
                yield entry, entry.path

    yield from walk(root, 1)


def normalize_business_text(text: str) -> str:
    """Normalize representation-only differences, not business characters.

    CR/LF, HTML break markers from the migration Markdown, non-breaking spaces,
    repeated layout whitespace and a leading Word bullet glyph are formatting
    representations.  Punctuation and non-whitespace business characters stay
    strict.  These are the only normalization rules used by the validator.
    """
    value = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    value = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")).strip()
    value = re.sub(r"^[\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043]\s*", "", value)
    return value
