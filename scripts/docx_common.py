# -*- coding: utf-8 -*-
"""Shared, deterministic input rules for the DOCX automation workflow.

This module intentionally contains only configuration, chapter-tree and
Markdown/resource parsing.  DOCX generation and DOCX validation remain
separate so that the validator can inspect generated OOXML independently.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml
from lxml import etree
from PIL import Image


REPO_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 环境变量存在但为空（CI/环境文件常见写法）时须回退仓库根，否则 ``""`` 会让
# ``config/`` 相对当前目录解析，CLI 报「未发现配置」。
BASE = os.environ.get("DOC_TOOL_TEST_BASE") or REPO_BASE

# --- 统一安全 OOXML 解析入口（薄适配） ---
# doc_tool/domain/ooxml.py 是全链路安全解析单一事实源（包体量上限/CRC/DTD 禁用/
# 良构校验）；scripts 侧经此处转发，保持自包含。首次导入时把仓库根加入 sys.path
# （migration 薄壳本已如此），幂等。
if REPO_BASE not in sys.path:
    sys.path.insert(0, REPO_BASE)

from doc_tool.domain.ooxml import (  # noqa: E402
    OOXMLSecurityError,
    parse_xml_safe,
    read_docx_package,
)


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
    try:
        config["headingStyles"] = {
            int(level): str(style_id)
            for level, style_id in (config.get("headingStyles") or {}).items()
        }
    except (TypeError, ValueError) as exc:
        # 非法级别键（如 "H1"）直接 int() 会裸 ValueError traceback；
        # 转成结构化配置错误提示。
        raise AutomationError("headingStyles 级别必须是整数: {0}".format(exc))
    if not config["headingStyles"]:
        raise AutomationError("headingStyles 不能为空")
    return config


def scan_entries(directory: str, depth: int) -> List[ChapterEntry]:
    entries: List[ChapterEntry] = []
    invalid: List[str] = []
    for name in os.listdir(directory):
        if name.startswith(".") or name.startswith("_"):
            continue
        if name.endswith(".bak") or name.endswith(".tmp"):
            # 工具备份/临时文件（编辑器写前 .md.bak、原子写 .tmp），非内容，跳过。
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


def encode_markdown_cell(value: str) -> str:
    r"""把任意文本编码成可安全放进 Markdown 表格单元格的一段文字。

    ``split_markdown_table_row`` 的逆运算：先转义 ``\`` 再转义 ``|``（顺序反了
    会把新加的反斜杠再转义一次），换行编码成 ``<br>``——表格单元格不能跨行，
    但换行是修订摘要这类内容的有效信息，直接丢掉就会挤成一行。
    """
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return re.sub(r"\r\n|\r|\n", "<br>", text)


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
                        with open(table_path, "rb") as table_file:
                            # 统一安全解析入口：禁止 DTD/实体、良构失败报告，
                            # 仓库内不保留第二条可被业务代码直接调用的解析路径。
                            parse_xml_safe(table_file.read(), os.path.basename(table_path))
                    except (OOXMLSecurityError, OSError) as exc:
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


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _wqn(tag: str) -> str:
    return W_NS + tag


def neutralize_hyperlink_fields(document_root) -> int:
    """把文档中的 ``HYPERLINK`` 域转为纯文本（unlink），返回解除数量。

    模板修订/导航表与复杂表格资源（``assets/*/tables/*.xml``）可能内嵌
    ``{ HYPERLINK \\l "_xxx" }`` 域，指向 ``_xxx`` 书签；重建文档的书签命名是
    ``doc_...`` 体系，模板锚点对应书签不会存在，Word 刷新渲染域后会留下悬空锚点
    导致刷新后校验报「超链接书签目标不存在」。构建侧在输出前解除为静态文本（保留
    可见文字），校验侧对复杂表格预期 XML 施加同一变换以保持一致。

    Word 序列化域时，若域结果结束于段落边界，``end`` 运行会落在下一段落开头
    （修订表里跨段落的超链接域即如此），因此必须跨段落配对 begin/separate/end，
    不能按单段落处理。做法：把 ``w:r`` 拍平成文档顺序列表，用栈配对嵌套域
    （TOC 域内的 PAGEREF 等不影响外层配对），仅解除 HYPERLINK 域。
    """
    qn = _wqn
    removed = 0

    def is_hyperlink_instruction(instruction: str) -> bool:
        return bool(instruction) and "HYPERLINK" in instruction.upper()

    # fldSimple：整域即指令属性。
    for field in list(document_root.iter(qn("fldSimple"))):
        if is_hyperlink_instruction(field.get(qn("instr")) or ""):
            parent = field.getparent()
            index = parent.index(field)
            for child in list(field):
                parent.insert(index, child)
                index += 1
            parent.remove(field)
            removed += 1

    # 直接按文档顺序迭代全部 `w:r`（含被 `w:hyperlink` / `w:ins` /
    # `w:sdt` 等内容控件包裹的运行）：按段落 `findall` 只找段落的直接子
    # 运行，漏掉包裹内的 begin/end，会导致域配对失败、悬空书签残留。owner 记
    # 录运行的实际父元素，删除时直接从中移除（begin 与 end 可能不在同一段落）。
    flat = [(run, run.getparent()) for run in document_root.iter(qn("r"))]
    fields = []
    stack = []
    for index, (run, _owner) in enumerate(flat):
        field_char = run.find(qn("fldChar"))
        field_type = field_char.get(qn("fldCharType")) if field_char is not None else None
        if field_type == "begin":
            stack.append({"begin": index, "separate": None, "parts": []})
        elif field_type == "separate":
            if stack and stack[-1]["separate"] is None:
                stack[-1]["separate"] = index
        elif field_type == "end":
            if stack:
                field = stack.pop()
                fields.append(
                    (field["begin"], field["separate"], index, "".join(field["parts"]))
                )
        elif stack and stack[-1]["separate"] is None:
            # 指令文本归属栈顶域；域 separate 之后（缓存结果）与嵌套域内的
            # 文本不收集，避免把缓存内容误并入指令。
            stack[-1]["parts"].extend(node.text or "" for node in run.iter(qn("instrText")))
    for begin, separate, end, instruction in fields:
        if separate is None or not is_hyperlink_instruction(instruction):
            continue
        # 移除 begin..separate 与 end 运行，保留 separate 与 end 之间的缓存结果
        # 运行（域的可见文字）。end 运行可能位于下一段落，按所属段落逐个移除。
        targets = list(range(begin, separate + 1)) + [end]
        for target in targets:
            run, owner = flat[target]
            owner.remove(run)
        removed += 1
    return removed


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
