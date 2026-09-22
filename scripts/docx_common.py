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

from doc_tool.domain.markdown_structure import (  # noqa: E402
    check_mermaid_structure,
    check_table_structure,
    is_separator_row,
    split_table_row,
)
from doc_tool.domain.ooxml import (  # noqa: E402
    OOXMLSecurityError,
    parse_xml_safe,
    read_docx_package,
)


class AutomationError(RuntimeError):
    """A user-actionable build/validation error.

    ``locations`` 携带机器可读的出错位置，让上层（管线、问题面板、CLI）
    能直接展示「哪个文件第几行、为什么、怎么改」，而不是只给一个错误码
    让用户自己去日志里翻。每项为稳定键的 dict：

    - ``path``：出错文件路径。
    - ``line``：1-based 行号；整文件级问题为 None。
    - ``message``：问题说明。
    - ``hint``：修法建议（可为空）。
    - ``rule``：稳定规则名，供筛选与测试断言。

    只有消息文本、没有结构化位置的旧调用点保持原样（``locations``
    为空），上层会退回从消息里解析 ``路径:行号``。
    """

    def __init__(self, message: str, locations: Optional[Iterable[Dict]] = None) -> None:
        super().__init__(message)
        self.locations: List[Dict] = [dict(item) for item in (locations or ())]


def error_location(
    path: str,
    line: Optional[int],
    message: str,
    hint: str = "",
    rule: str = "",
) -> Dict:
    """构造一条结构化出错位置。"""
    return {
        "path": str(path),
        "line": int(line) if line is not None else None,
        "message": message,
        "hint": hint,
        "rule": rule,
    }


def format_location(entry: Dict) -> str:
    """把一条位置渲染成 ``路径:行号 说明 建议`` 单行文本。

    保持与旧报告一致的 ``路径:行号`` 前缀：校验报告解析与现有
    测试都依赖这个形状定位文件。
    """
    head = entry["path"]
    if entry.get("line") is not None:
        head = "{0}:{1}".format(head, entry["line"])
    parts = [head, entry.get("message", "")]
    if entry.get("hint"):
        parts.append(entry["hint"])
    return " ".join(part for part in parts if part)


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

    拆分规则已收敛到 ``doc_tool.domain.markdown_structure``（构建与内容
    检查共用同一份契约）；这里只把异常类型转回 ``AutomationError``，
    保持内核对外的失败语义不变。
    """
    from doc_tool.domain.markdown_structure import TableRowSyntaxError

    try:
        return split_table_row(line)
    except TableRowSyntaxError as exc:
        raise AutomationError(str(exc)) from exc


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
        if is_separator_row(cells):
            continue
        rows.append(cells)
    if not rows:
        return rows
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def _validate_markdown(
    path: str,
    depth: int,
    config: Dict,
    errors: List[str],
    locations: Optional[List[Dict]] = None,
) -> None:
    """检查一份 Markdown 的构建前约束，一次收集全部问题。

    ``errors`` 收单行文本（兼容旧报告），``locations`` 收同一批问题的
    结构化位置，供上层直接跳转定位。
    """
    collected: List[Dict] = locations if locations is not None else []

    def add(line_no: Optional[int], message: str, hint: str = "", rule: str = "") -> None:
        entry = error_location(path, line_no, message, hint, rule)
        collected.append(entry)
        errors.append(format_location(entry))

    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    # 表格结构契约：元数据语法、元数据后是否紧跟表格。不阻断的结论
    # （列数不符、行列不齐、缺分隔行）不在构建时报，由内容检查面板负责。
    for finding in check_table_structure(lines):
        if finding.blocking:
            add(finding.line_no, finding.message, finding.hint, finding.rule)

    # Mermaid 流程图与图表语法校验：防止错误语法静默进入 Word。
    for finding in check_mermaid_structure(lines):
        if finding.blocking:
            add(finding.line_no, finding.message, finding.hint, finding.rule)

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        heading = re.match(r"^(#{1,9})\s+(.+)$", stripped)
        if heading and len(heading.group(1)) <= depth:
            add(
                line_number,
                "内部标题层级必须深于文件章节层级 H{0}: {1}".format(depth, stripped),
                "请把该标题至少多加一级 #（不浅于 H{0}）。".format(depth + 1),
                "heading_level",
            )

        table_marker = re.fullmatch(r"<!--\s*TABLE:(\d+):?([\w.\-]+)?\s*-->", stripped)
        if stripped.startswith("<!-- TABLE:") and not table_marker:
            add(
                line_number,
                "复杂表格标记语法无效: {0}".format(stripped),
                "正确写法形如 <!-- TABLE:1:table_0001.xml -->。",
                "complex_table_syntax",
            )
        if table_marker:
            filename = table_marker.group(2)
            if not filename:
                add(
                    line_number,
                    "复杂表格标记缺少 XML 文件名",
                    "请补上表格 XML 文件名，形如 <!-- TABLE:1:table_0001.xml -->。",
                    "complex_table_syntax",
                )
            else:
                table_path = resolve_resource(config["paths"]["table_root"], filename, "复杂表格")
                if not os.path.isfile(table_path):
                    add(
                        line_number,
                        "复杂表格 XML 不存在: {0}".format(table_path),
                        "请确认文件已放入表格目录，或修正标记中的文件名。",
                        "complex_table_missing",
                    )
                else:
                    try:
                        with open(table_path, "rb") as table_file:
                            # 统一安全解析入口：禁止 DTD/实体、良构失败报告，
                            # 仓库内不保留第二条可被业务代码直接调用的解析路径。
                            parse_xml_safe(table_file.read(), os.path.basename(table_path))
                    except (OOXMLSecurityError, OSError) as exc:
                        add(
                            line_number,
                            "复杂表格 XML 无法解析: {0}".format(exc),
                            "请用文本编辑器检查该 XML 是否完整且根节点为 w:tbl。",
                            "complex_table_parse",
                        )

        image_ref = parse_image_reference(stripped)
        if stripped.startswith("![") and image_ref is None:
            add(
                line_number,
                "图片 Markdown 语法无效: {0}".format(stripped),
                "正确写法形如 ![说明](images/a.png) 或 ![说明](images/a.png =800x600)。",
                "image_syntax",
            )
        if image_ref is not None:
            image_path = resolve_resource(config["paths"]["asset_root"], image_ref.relative_path, "图片")
            if not os.path.isfile(image_path):
                add(
                    line_number,
                    "图片不存在: {0}".format(image_path),
                    "请把图片放入资源目录，或修正链接中的相对路径。",
                    "image_missing",
                )
            else:
                try:
                    with Image.open(image_path) as image:
                        image.verify()
                except Exception as exc:
                    add(
                        line_number,
                        "图片损坏或格式不支持: {0}".format(exc),
                        "请用图片工具重新导出为 PNG/JPEG 后替换。",
                        "image_broken",
                    )


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
    locations: List[Dict] = []
    flattened: List[ChapterEntry] = []
    max_heading = max(config["headingStyles"])

    def add(
        target: str,
        line_no: Optional[int],
        message: str,
        hint: str = "",
        rule: str = "",
    ) -> None:
        entry = error_location(target, line_no, message, hint, rule)
        locations.append(entry)
        errors.append(format_location(entry))

    def walk(directory: str, parent: Tuple[int, ...], depth: int) -> None:
        if depth > max_heading:
            add(
                directory,
                None,
                "章节层级 H{0} 超过 headingStyles 配置范围".format(depth),
                "请减少目录嵌套层级，或在项目清单里扩展 headingStyles。",
                "chapter_depth",
            )
            return
        try:
            entries = scan_entries(directory, depth)
        except AutomationError as exc:
            add(directory, None, str(exc), "", "chapter_scan")
            return
        for position, entry in enumerate(entries, start=1):
            expected = parent + (position,)
            if len(entry.number) != depth or entry.number[:-1] != parent or entry.number != expected:
                expected_number = display_number(expected)
                actual_number = display_number(entry.number)
                suffix = "" if entry.kind == "dir" else ".md"
                add(
                    entry.path,
                    None,
                    "编号 {0} 与层级/顺序不一致；实际预期编号为 {1}".format(
                        actual_number, expected_number
                    ),
                    "请改为“{0} {1}{2}”。".format(expected_number, entry.title, suffix),
                    "chapter_numbering",
                )
            flattened.append(entry)
            if entry.kind == "dir":
                index_path = os.path.join(entry.path, "_index.md")
                if os.path.isfile(index_path):
                    _validate_markdown(index_path, depth, config, errors, locations)
                walk(entry.path, entry.number, depth + 1)
                try:
                    child_entries = scan_entries(entry.path, depth + 1)
                except AutomationError:
                    child_entries = []
                if not child_entries and not os.path.isfile(index_path):
                    add(
                        entry.path,
                        None,
                        "空章节目录既没有 _index.md 也没有子章节",
                        "请补上 _index.md 正文，或删除该空目录。",
                        "empty_chapter",
                    )
            else:
                _validate_markdown(entry.path, depth, config, errors, locations)

    walk(root, tuple(), 1)
    if errors:
        raise AutomationError(
            "构建前检查失败:\n- " + "\n- ".join(errors),
            locations=locations,
        )
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


def neutralize_dangling_hyperlinks(
    document_root, available_bookmarks: Optional[Iterable[str]] = None
) -> int:
    """把指向不存在书签的原生 ``<w:hyperlink>`` 元素解除为静态文本（保留内部运行），返回解除数量。

    注意：
    1. 若超链接包含 ``r:id``，表示其为外部链接或关系目标链接（其 ``w:anchor`` 指向外部目标中的片段），
       不属于当前文档书签引用，不得解除。
    2. 解除超链接包装时，必须完整保留被解除节点的内部子节点、``text`` 与 ``tail`` 文本，避免 OOXML 内容丢失。
    """
    qn = _wqn
    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    if available_bookmarks is None:
        available = {
            node.get(qn("name"))
            for node in document_root.iter(qn("bookmarkStart"))
            if node.get(qn("name"))
        }
    else:
        available = set(available_bookmarks)

    removed = 0
    for hl in list(document_root.iter(qn("hyperlink"))):
        rid = hl.get(r_ns + "id") or hl.get("r:id")
        anchor = hl.get(qn("anchor"))
        # 外部链接或带 r:id 关系的超链接不属于本地书签判定范畴
        if rid:
            continue
        # 若无 rid 且 (未设置 anchor 或 anchor 不在可用书签中)，则判定为悬空超链接
        if not anchor or anchor not in available:
            parent = hl.getparent()
            if parent is not None:
                index = parent.index(hl)
                children = list(hl)
                if hl.text:
                    if children:
                        first_child = children[0]
                        if first_child.tag == qn("r"):
                            t_node = first_child.find(qn("t"))
                            if t_node is not None:
                                t_node.text = hl.text + (t_node.text or "")
                            else:
                                t_node = etree.Element(qn("t"))
                                t_node.text = hl.text
                                first_child.insert(0, t_node)
                        else:
                            r = etree.Element(qn("r"))
                            t = etree.SubElement(r, qn("t"))
                            t.text = hl.text
                            children.insert(0, r)
                    else:
                        r = etree.Element(qn("r"))
                        t = etree.SubElement(r, qn("t"))
                        t.text = hl.text
                        children.append(r)

                for child in children:
                    parent.insert(index, child)
                    index += 1

                if hl.tail:
                    if children:
                        children[-1].tail = (children[-1].tail or "") + hl.tail
                    else:
                        prev = hl.getprevious()
                        if prev is not None:
                            prev.tail = (prev.tail or "") + hl.tail
                        else:
                            parent.text = (parent.text or "") + hl.tail

                parent.remove(hl)
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
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # 过滤零宽字符与文本方向标记
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u200e", "\u200f"):
        value = value.replace(ch, "")
    # 全角空格与各种 Unicode 空白字符归一化为半角空格
    for ch in ("\u3000", "\u00a0", "\u2002", "\u2003", "\u2009"):
        value = value.replace(ch, " ")
    # 逐行折叠连续空白并去除首尾空白
    value = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")).strip()
    value = re.sub(r"^[\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043]\s*", "", value)
    return value


def _normalize_event_text(s: str) -> str:
    """对事件文本执行表示层深度归一化，消除 Markdown 与 Word 的表示层差异。"""
    t = str(s).replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u200e", "\u200f"):
        t = t.replace(ch, "")
    for ch in ("\u3000", "\u00a0", "\u2002", "\u2003", "\u2009"):
        t = t.replace(ch, " ")
    # Markdown 常见转义字符还原
    t = t.replace(r"\|", "|").replace(r"\*", "*").replace(r"\_", "_").replace(r"\[", "[").replace(r"\]", "]").replace("`", "")
    # 剥离项目符号
    t = re.sub(r"^[\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043]\s*", "", t)
    # 逐行去除首尾空格并丢弃空行
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in t.split("\n")]
    return "\n".join(l for l in lines if l)


def _normalize_formula_text(s: str) -> str:
    """归一化公式/算式与常见标点的表示与空格差异（乘号、波浪号、正负号、全角半角标点等）。"""
    t = s.replace("×", "*").replace("～", "~")
    t = t.replace("－", "-").replace("–", "-").replace("—", "-")
    t = t.replace("／", "/").replace("％", "%").replace("＋", "+").replace("＝", "=")
    t = t.replace("＜", "<").replace("＞", ">")
    t = t.replace("（", "(").replace("）", ")")
    t = t.replace("【", "[").replace("】", "]")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("：", ":").replace("；", ";").replace("，", ",")
    t = re.sub(r"\s*([+\-*/=<>~:()[\]])\s*", r"\1", t)
    t = re.sub(r"([;,])\s*", r"\1 ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_event_text_equivalent(val1: object, val2: object) -> bool:
    """判断两个事件文本是否在语义上等价（放行格式表示层细节）。"""
    s1 = str(val1)
    s2 = str(val2)
    if s1 == s2:
        return True
    n1 = _normalize_event_text(s1)
    n2 = _normalize_event_text(s2)
    if n1 == n2:
        return True
    f1 = _normalize_formula_text(n1)
    f2 = _normalize_formula_text(n2)
    return f1 == f2


def _is_matrix_equivalent(m1, m2) -> bool:
    """判断两个表格文本矩阵是否等价。"""
    if len(m1) != len(m2):
        return False
    for r1, r2 in zip(m1, m2):
        if len(r1) != len(r2):
            return False
        for c1, c2 in zip(r1, r2):
            if not _is_event_text_equivalent(c1, c2):
                return False
    return True

_MANUAL_PREFIX_RE = re.compile(
    r"^(?:(?:\d{1,3}、\s*)|(?:\d{1,3}[.．](?!\d)\s*)|(?:[-*•+]\s+)|(?:[\(（\[【](?:\d{1,3}|[一二三四五六七八九十]+|[a-zA-Z]|[ivxIVX]+)[\)）\]】]\s*)|(?:[\u2460-\u2473①②③④⑤⑥⑦⑧⑨⑩]\s*)|(?:[一二三四五六七八九十]+[、.．]\s*)|(?:(?:\d{1,3}|[一二三四五六七八九十]+|[a-zA-Z]|[ivxIVX]+)[\)）]\s*)|(?:[a-zA-Z][.．](?!\w)\s*))"
)


def _strip_manual_prefix(text: str) -> str:
    """去掉开头的字面编号或列表符号（如 ``1. 概述``、``1、概述``、``- 列表项``），用于段落文本对齐。"""
    stripped = text.strip()
    return _MANUAL_PREFIX_RE.sub("", stripped).strip()


# --- 修订记录表（多行表头、语义列映射、尾部非版本截断） ---

REVISION_VERSION_KEYWORDS = ("版本号", "版次", "版本", "version", "rev", "ver")
REVISION_SUMMARY_KEYWORDS = (
    "修改摘要", "更新摘要", "修订摘要", "变更摘要", "更改摘要",
    "修改内容", "更新内容", "修订内容", "变更内容", "更改内容",
    "修改说明", "修订说明", "变更说明", "更改说明",
    "修改记录", "修订记录", "变更记录",
    "摘要", "修订", "修改", "更改", "变更", "内容", "说明",
    "summary", "description", "details", "change", "comment"
)
REVISION_DATE_KEYWORDS = (
    "修改时间", "修订时间", "变更时间", "更改时间",
    "修改日期", "修订日期", "变更日期", "更改日期",
    "发布日期", "更新日期", "时间", "日期", "date", "time"
)
REVISION_AUTHOR_KEYWORDS = (
    "修改人", "修订人", "变更人", "更改人",
    "修改者", "修订者", "变更者", "更改者",
    "编制人", "编写人", "起草人", "作者", "责任人",
    "编制", "编写", "起草", "author", "editor", "modifier", "writer"
)
REVISION_FOOTER_KEYWORDS = (
    "审核", "审批", "批准", "签批", "校对", "核对", "会签", "签字", "签名",
    "部门", "密级", "受控", "说明：", "说明:", "备注：", "备注:", "注：", "注:",
    "分发", "发放"
)


def _cell_text(cell) -> str:
    r"""提取单元格纯文本，保留段落与手动换行（w:br/w:cr）的换行结构。"""
    if cell is None:
        return ""
    lines: List[str] = []
    for paragraph in cell.iter(_wqn("p")):
        parts: List[str] = []
        for node in paragraph.iter():
            if node.tag == _wqn("t"):
                parts.append(node.text or "")
            elif node.tag in (_wqn("br"), _wqn("cr")):
                parts.append("\n")
            elif node.tag == _wqn("tab"):
                parts.append("\t")
        for line in "".join(parts).split("\n"):
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return "\n".join(lines)


def score_revision_header_row(cell_texts: Sequence[str]) -> int:
    """计算一行作为修订记录表列头行的可信度评分。"""
    if len(cell_texts) < 2:
        return 0
    non_empty = [t.strip() for t in cell_texts if t.strip()]
    if len(non_empty) < 2:
        return 0
    # 如果大部分单元格都是长说明句或含有句号/描述词，判定为说明句而非列头
    def _is_long_desc(t: str) -> bool:
        if len(t) > 25 or "如下" in t or "。" in t or "详见" in t or "请参阅" in t:
            return True
        if ("：" in t or ":" in t) and len(t) > 8:
            return True
        return False

    long_cells = sum(1 for t in non_empty if _is_long_desc(t))
    if len(non_empty) == 2 and long_cells >= 1:
        return 0
    if long_cells * 2 >= len(non_empty):
        return 0

    norm_texts = [re.sub(r"\s+", "", t).lower() for t in non_empty]
    v_indices = [
        i for i, t in enumerate(norm_texts)
        if any(vk in t for vk in REVISION_VERSION_KEYWORDS)
        and not any(sk in t for sk in ("说明", "摘要", "内容", "记录"))
    ]
    s_indices = [
        i for i, t in enumerate(norm_texts)
        if any(sk in t for sk in REVISION_SUMMARY_KEYWORDS)
    ]
    # 版本列与修改摘要列必须为不同的列
    if not any(v_i != s_i for v_i in v_indices for s_i in s_indices):
        return 0

    has_d = any(any(dk in t for dk in REVISION_DATE_KEYWORDS) for t in norm_texts)
    has_a = any(
        any(ak in t for ak in REVISION_AUTHOR_KEYWORDS)
        or ("人" in t and "时间" not in t and "日期" not in t)
        for t in norm_texts
    )

    score = 10
    if has_d:
        score += 10
    if has_a:
        score += 10
    score += len(non_empty)
    return score


def is_revision_header_row(cell_texts: Sequence[str]) -> bool:
    """判断一行文本是否为修订记录表的列头行。"""
    return score_revision_header_row(cell_texts) > 0


def map_revision_columns(
    header_texts: Sequence[str],
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """智能语义映射修订记录表列索引 -> (version_col, summary_col, date_col, author_col)。"""
    v_col: Optional[int] = None
    s_col: Optional[int] = None
    d_col: Optional[int] = None
    a_col: Optional[int] = None

    norm_texts = [re.sub(r"\s+", "", t).lower() for t in header_texts]

    # 1. 优先匹配修订日期列（优先匹配明确非审批的日期）
    for i, t in enumerate(norm_texts):
        if d_col is None and any(k in t for k in REVISION_DATE_KEYWORDS):
            if not any(ak in t for ak in ("审核", "审批", "批准", "签批", "会签")):
                d_col = i
                break
    if d_col is None:
        for i, t in enumerate(norm_texts):
            if any(k in t for k in REVISION_DATE_KEYWORDS):
                d_col = i
                break

    # 2. 匹配人员列（排除已确认为日期的列，优先非审批人）
    for i, t in enumerate(norm_texts):
        if i == d_col:
            continue
        if any(ak in t for ak in ("审核", "审批", "批准", "签批", "会签")):
            continue
        if a_col is None and (
            any(k in t for k in REVISION_AUTHOR_KEYWORDS)
            or (any(k in t for k in ("人", "者", "员")) and not any(k in t for k in ("时间", "日期")))
        ):
            a_col = i
            break
    if a_col is None:
        for i, t in enumerate(norm_texts):
            if i == d_col:
                continue
            if (
                any(k in t for k in REVISION_AUTHOR_KEYWORDS)
                or (any(k in t for k in ("人", "者", "员")) and not any(k in t for k in ("时间", "日期")))
            ):
                a_col = i
                break

    # 3. 匹配版本列（排除日期、人员）
    for i, t in enumerate(norm_texts):
        if i in (d_col, a_col):
            continue
        if v_col is None and any(k in t for k in REVISION_VERSION_KEYWORDS):
            if not any(sk in t for sk in ("说明", "摘要", "内容", "记录")):
                v_col = i
                break

    # 4. 匹配摘要/修改说明列（排除版本、日期、人员）
    # 单号/编号列（如"修订单号"、"变更单号"、"序号"）不得误判为修改摘要
    def _is_summary_candidate(text: str) -> bool:
        return not any(nk in text for nk in ("单号", "编号", "序号", "no.", "no"))

    # 4a. 高可信优先：匹配具体的多字词（修改内容、修订摘要、变更说明等）
    high_precision_summary = (
        "修改内容", "更新内容", "修订内容", "变更内容", "更改内容",
        "修改摘要", "更新摘要", "修订摘要", "变更摘要", "更改摘要",
        "修改说明", "修订说明", "变更说明", "更改说明",
        "修改记录", "修订记录", "变更记录",
        "摘要", "内容", "说明", "summary", "description", "details"
    )
    for i, t in enumerate(norm_texts):
        if i in (v_col, d_col, a_col):
            continue
        if s_col is None and _is_summary_candidate(t) and any(k in t for k in high_precision_summary):
            s_col = i
            break

    # 4b. 兜底匹配次级关键词
    if s_col is None:
        for i, t in enumerate(norm_texts):
            if i in (v_col, d_col, a_col):
                continue
            if _is_summary_candidate(t) and any(k in t for k in REVISION_SUMMARY_KEYWORDS):
                s_col = i
                break

    # 5. 兜底映射未匹配的角色（优先选择非序号/单号列映射到版本与摘要）
    used = {c for c in (v_col, s_col, d_col, a_col) if c is not None}
    available = [i for i in range(len(header_texts)) if i not in used]

    def _pick_available(prefer_non_index: bool = True) -> Optional[int]:
        if not available:
            return None
        if prefer_non_index:
            for idx in list(available):
                if not any(nk in norm_texts[idx] for nk in ("单号", "编号", "序号", "no.", "no")):
                    available.remove(idx)
                    return idx
        return available.pop(0)

    if v_col is None:
        v_col = _pick_available(prefer_non_index=True)
    if s_col is None:
        s_col = _pick_available(prefer_non_index=True)
    if d_col is None:
        d_col = _pick_available(prefer_non_index=False)
    if a_col is None:
        a_col = _pick_available(prefer_non_index=False)

    return v_col, s_col, d_col, a_col


def is_revision_footer_row(
    cell_texts: Sequence[str], v_col: Optional[int] = 0
) -> bool:
    """判断是否为修订记录表尾部的非版本说明/签批/审核行。"""
    if not cell_texts or not any(cell_texts):
        return False
    combined = "".join(cell_texts).strip()
    if any(k in combined for k in (
        "编制人", "审核人", "批准人", "签批人", "校对人", "复核人", "会签人",
        "审核：", "审核:", "批准：", "批准:", "编制：", "编制:", "签批：", "签批:",
        "校对：", "校对:", "会签：", "会签:",
        "说明：", "说明:", "备注：", "备注:", "注：", "注:", "受控", "密级",
    )):
        return True
    if combined.startswith(("说明", "备注", "注：", "注:", "提示")):
        return True

    # 检查单元格中是否存在独立的审批/说明/状态关键词（如 "审核", "批准", "编制", "会签" 等独立标签）
    approval_standalone = {
        "审核", "审批", "批准", "签批", "校对", "核对", "复核", "会签",
        "签字", "签名", "编制", "编写", "起草", "部门", "密级", "受控", "分发", "发放"
    }
    for t in cell_texts:
        stripped = t.strip()
        if not stripped:
            continue
        if stripped in approval_standalone:
            return True
        if any(stripped.startswith(k) for k in (
            "审核：", "审核:", "批准：", "批准:", "编制：", "编制:", "签批：", "签批:",
            "校对：", "校对:", "会签：", "会签:", "说明：", "说明:", "备注：", "备注:", "注：", "注:"
        )):
            return True

    v_idx = v_col if (v_col is not None and 0 <= v_col < len(cell_texts)) else 0
    v_text = cell_texts[v_idx].strip()
    if any(k in v_text for k in REVISION_FOOTER_KEYWORDS) and len(v_text) <= 15:
        return True

    # 版本特征：包含 ASCII 字母数字（如 1.0, V1, Rev A）或中文版本常用词（初版, 第一版, 初稿, 试行版, 正式版, 初始发布, 第一次修订, 基线一等）
    is_version_like = (
        any(c.isascii() and c.isalnum() for c in v_text)
        or any(k in v_text for k in ("版", "稿", "发布", "修订", "变更", "基线", "版本"))
        or (v_text.startswith("第") and any(k in v_text for k in ("次", "期", "卷", "批")))
    )
    if not is_version_like and v_text:
        return True
    return False


def find_revision_table_info(
    doc_root,
) -> Optional[Tuple[object, int, Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]]]:
    """在文档正文中查找修订记录表，并返回 (table_element, header_row_index, (v_col, s_col, d_col, a_col))。

    支持单行表头、多行表头（1~3行）、智能列语义识别。
    未找到时返回 None。
    """
    if doc_root is None:
        return None
    if doc_root.tag == _wqn("body"):
        body = doc_root
    else:
        body = doc_root.find(_wqn("body"))
        if body is None:
            body = doc_root

    for tbl in body.iter(_wqn("tbl")):
        rows = tbl.findall(_wqn("tr"))
        if len(rows) < 2:
            continue
        best_row_idx = None
        best_score = 0
        best_mapping = None
        # 在前 4 行中寻找评分最高的列头行（支持单行及多行表头组合识别）
        for row_idx, row in enumerate(rows[:4]):
            cells = row.findall(_wqn("tc"))
            header_texts = [_cell_text(c).strip() for c in cells]
            sc = score_revision_header_row(header_texts)
            if sc > best_score:
                best_score = sc
                best_row_idx = row_idx
                best_mapping = map_revision_columns(header_texts)

            # 多行表头支持：检查将前置行与当前行合并后的列头评分
            if row_idx > 0:
                prev_cells = rows[row_idx - 1].findall(_wqn("tc"))
                prev_texts = [_cell_text(c).strip() for c in prev_cells]
                if len(prev_texts) == len(header_texts):
                    combined_texts = [
                        "{0} {1}".format(p, h).strip()
                        for p, h in zip(prev_texts, header_texts)
                    ]
                    sc_comb = score_revision_header_row(combined_texts)
                    if sc_comb > best_score:
                        best_score = sc_comb
                        best_row_idx = row_idx
                        best_mapping = map_revision_columns(combined_texts)
        if best_row_idx is not None and best_score > 0:
            return tbl, best_row_idx, best_mapping
    return None


def is_baseline_error_blocking(error: str, source_events: Sequence, rebuilt_events: Sequence) -> bool:
    """判定基线差异是否属于内容丢失/层级变更等阻断性错误（BLOCK），放行安全的表示层 WARN。"""
    if error.startswith("业务元素数量不一致"):
        return True
    match = re.match(r"^#(\d+)\s+(?:基线)?(?:内容|类型)?(?:/位置)?不一致:\s*(.+)$", error)
    if not match:
        return True
    index = int(match.group(1))
    if index >= len(source_events) or index >= len(rebuilt_events):
        return True

    left_event = source_events[index]
    right_event = rebuilt_events[index]
    left_kind = left_event.kind
    right_kind = right_event.kind

    if left_kind == "H" or right_kind == "H":
        return True
    if left_kind == "I" or right_kind == "I":
        return True
    if left_kind in {"P", "L", "X"} and right_kind in {"P", "L", "X"}:
        left_val = left_event.value[0] if (left_kind == "L" and isinstance(left_event.value, tuple)) else str(left_event.value)
        right_val = right_event.value[0] if (right_kind == "L" and isinstance(right_event.value, tuple)) else str(right_event.value)
        if _is_event_text_equivalent(_strip_manual_prefix(left_val), _strip_manual_prefix(right_val)):
            return False  # 内容等价，降级 WARN
        return True  # 文本实质变化，BLOCK
    if left_kind in {"T", "C"} and right_kind in {"T", "C"}:
        return False  # 表格表示差异，降级 WARN
    return True
