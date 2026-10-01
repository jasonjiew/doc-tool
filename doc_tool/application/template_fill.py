# -*- coding: utf-8 -*-
"""模板填充：用户 Word 模板（底模）+ Markdown → 格式与模板一致的 DOCX。

复用项目出稿管线唯一的「按模板 styleId 精确装配」内核
（``scripts/build_docx.py::build``）：模板包（styles.xml、页眉页脚、封面、
节属性、标题多级编号）原样保留，仅向 document.xml 装配 Markdown 内容。

- 模板样式解析走 :mod:`doc_tool.domain.ooxml`（全仓库唯一事实源），
  正文样式推断复用导入器的 ``_find_body_style``；
- Markdown 先按标题层级拆成内核要求的「编号章节树」（拆分规则与
  ``importer.split_into_tree`` 一致：H1 → 第N章目录、H2 有子标题则目录
  否则独立文件、H3 独立文件、四级及以上保留在文件内），再交内核构建；
- 第一个标题之前若存在正文，先产出一个无标题的「正文」引导章节
  （内核 ``is_headless`` 约定：插入内容但不插标题段落）；
- ``documentType`` 固定 ``general``：不做需求/设计类型的封面字段表与
  页眉改写，模板封面页眉原样保留；模板无修订记录表时内核自动跳过；
- 图片复制进临时资源目录并随内核内嵌；缺失/远程图片降级为占位文本告警；
- 围栏代码块降级为 Consolas 等宽代码段落（内核方言没有代码块元素，
  有损降级：块内空行不保留）；引用块、行内图片等扩展语法按普通文本输出。

本模块不碰 COM、不碰 Qt：无 Word 机器也能离线出稿。
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.domain.errors import DocToolError, TemplateFillError, TextEncodingError
from doc_tool.domain.ooxml import (
    HEADING_LEVEL_MAX,
    HeadingStyleCandidate,
    OOXMLSecurityError,
    heading_style_candidates,
    heading_style_usage,
    parse_heading_styles,
    parse_xml_safe,
    read_docx_package,
    resolve_heading_styles,
)

# 与 importer 的章节拆分、docx_common 的标题解析保持同一套命名约定：
# 一级标题产出「第N章 标题」目录，其余产出「N.M 标题.md」。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
#: 共享块解析器同款的围栏开标记（允许 0-3 个前导空格）。
_FENCE_OPEN_RE = re.compile(r"^(?P<indent> {0,3})(?P<mark>`{3,}|~{3,})(?P<info>.*)$")
_REMOTE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

# 内容保真降级：行内图片拆出独立成行、引用块转缩进、水平线转空段。
_INLINE_IMAGE_SPLIT_RE = re.compile(r"(!\[[^\]]*\]\([^)]*\))")
_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_QUOTE_PREFIX_RE = re.compile(r"^(?:>\s?)+")
_CLOSING_HASHES_RE = re.compile(r"\s+#+\s*$")
_LIST_LINE_RE = re.compile(r"^(?:[-*]|\d{1,3}[.、])\s")
# GFM 任务列表：- [ ] / - [x] → Word 无复选框元素，转 ☐/☑ 符号列表项。
_TASK_ITEM_RE = re.compile(
    r"^(\s*(?:[-*]|\d{1,3}[.、])\s+)\[([ xX])\]\s*(.*)$"
)
# Setext 标题：纯文本段落的下一行是 === / -- 下划线 → 转 ATX（CommonMark 语义）。
_SETEXT_H1_RE = re.compile(r"^=+\s*$")
_SETEXT_H2_RE = re.compile(r"^-{2,}\s*$")
# 行内图片嵌在文本中时，整行不是合法图片引用（内核只认整行图片）：
# 把行内图片拆成独立行，文本段保持原顺序，图片不再退化为字面文本。
_EMPTY_PAR = "<EMPTY_PAR/>"  # 内核方言：插入一个空段落
_QUOTE_INDENT_MARKER = "<!-- P:left=720 -->"  # 内核方言：下一段左缩进
_FRONT_MATTER_DELIM = re.compile(r"^---\s*$")
_FRONT_MATTER_TITLE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)

_HEADLESS_TITLE = "正文"  # 内核 is_headless 约定：跳过该深度 1 章节的标题段落

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class StyleInfo:
    """模板中一个段落样式的展示信息（供手动映射兜底选择）。"""

    style_id: str
    name: str


@dataclass
class TemplateStyles:
    """用户模板的样式解析结论。"""

    # 实际从模板识别到的「级别→styleId」（未补齐，可能为空）。
    raw_heading_styles: Dict[int, str]
    # 补齐到 1~6 级后可直接作为内核 headingStyles 使用（缺失级别按最近可用
    # 级别回退，与内核 make_heading 的回退行为一致；全空时回退内置标题样式）。
    heading_styles: Dict[int, str]
    body_style: str
    # 全部标题样式候选（resolve_heading_styles 的判定依据，供界面展示）。
    candidates: List[HeadingStyleCandidate] = field(default_factory=list)
    # 全部段落样式（供标题样式无法自动识别时手动映射兜底）。
    paragraph_styles: List[StyleInfo] = field(default_factory=list)
    # 模板正文中标题样式段落的数量：>0 说明底模更像一份「完整文档」而非
    # 纯底模，直接填充会把旧正文带进产物，应提示用户清理（见
    # ``fill_markdown_with_template`` 的 ``clean_body_from_first_heading``）。
    body_heading_count: int = 0
    warnings: List[str] = field(default_factory=list)


@dataclass
class TemplateFillResult:
    """模板填充结果：产物路径、章节统计与降级/告警摘要。"""

    output: Path
    chapters: int = 0
    images: int = 0
    warnings: List[str] = field(default_factory=list)
    # True 表示文档以「无标题正文引导章节」开头（Markdown 首个标题前有正文）。
    headless_intro: bool = False
    # 域刷新状态：normal（未请求）/ ok / 刷新原因键（timeout 等，见 refresh_fields）。
    refresh_state: str = "normal"


def _pad_heading_styles(resolved: Dict[int, str]) -> Tuple[Dict[int, str], List[str]]:
    """把「级别→styleId」补齐到 1~6 级，回退方向与内核 make_heading 一致。

    validate_content_tree 以 ``max(headingStyles)`` 圈定章节深度上限，因此
    映射必须非空且覆盖到实际出现的层级；缺失级别优先借浅层样式（Word 中
    深层标题继承浅层排版是常见形态），没有浅层才借深层。
    """
    warnings: List[str] = []
    if not resolved:
        warnings.append(
            "模板未识别到任何标题样式，已回退 Word 内置「标题 1~6」样式；"
            "可在「样式映射」中手动指定模板样式。"
        )
        return {
            level: "Heading{0}".format(level)
            for level in range(1, HEADING_LEVEL_MAX + 1)
        }, warnings
    padded: Dict[int, str] = {}
    for level in range(1, HEADING_LEVEL_MAX + 1):
        if level in resolved:
            padded[level] = resolved[level]
            continue
        shallower = [key for key in resolved if key < level]
        deeper = [key for key in resolved if key > level]
        if shallower:
            padded[level] = resolved[max(shallower)]
        elif deeper:
            padded[level] = resolved[min(deeper)]
        else:
            padded[level] = "Heading{0}".format(level)
    missing = [level for level in range(1, HEADING_LEVEL_MAX + 1) if level not in resolved]
    if missing:
        warnings.append(
            "模板未定义全部标题样式（缺 {0} 级），缺失层级沿用相邻标题样式。".format(
                "、".join(str(level) for level in missing)
            )
        )
    return padded, warnings


def parse_template_styles(template_docx) -> TemplateStyles:
    """解析用户模板：标题级别→styleId、正文样式与段落样式清单。

    标题识别失败不抛错：返回空 ``raw_heading_styles`` 并携带告警，由调用方
    决定走内置样式回退还是让用户手动映射（``paragraph_styles`` 清单）。
    """
    from doc_tool.adapters.importer import _find_body_style

    path = Path(template_docx)
    with read_docx_package(path) as package:
        styles_xml = package.read("word/styles.xml")
        try:
            document_xml = package.read("word/document.xml")
        except OOXMLSecurityError:
            document_xml = b""
    styles_root = parse_xml_safe(styles_xml, "word/styles.xml")
    raw = resolve_heading_styles(styles_root)
    heading_styles, warnings = _pad_heading_styles(raw)
    # 模板正文里标题样式段落计数：区分「纯底模」与「忘了删正文的完整文档」。
    body_heading_count = 0
    if document_xml:
        try:
            document_root = parse_xml_safe(document_xml, "word/document.xml")
            usage = heading_style_usage(document_root)
            level_map = parse_heading_styles(styles_xml)
            body_heading_count = sum(
                count for style_id, count in usage.items() if style_id in level_map
            )
        except OOXMLSecurityError:
            body_heading_count = 0
    paragraph_styles: List[StyleInfo] = []
    for style in styles_root.iter(_W_NS + "style"):
        if style.get(_W_NS + "type") != "paragraph":
            continue
        style_id = style.get(_W_NS + "styleId") or ""
        if not style_id:
            continue
        name_elem = style.find(_W_NS + "name")
        name = (name_elem.get(_W_NS + "val") or "") if name_elem is not None else ""
        paragraph_styles.append(StyleInfo(style_id=style_id, name=name))
    return TemplateStyles(
        raw_heading_styles=dict(raw),
        heading_styles=heading_styles,
        body_style=_find_body_style(styles_xml),
        candidates=heading_style_candidates(styles_root),
        paragraph_styles=paragraph_styles,
        body_heading_count=body_heading_count,
        warnings=warnings,
    )


def validate_style_map(mapping: Dict[str, int]) -> List[str]:
    """校验用户「样式ID→级别」映射，返回错误消息列表（空列表即通过）。"""
    errors: List[str] = []
    if not mapping:
        return ["样式映射为空：请至少把一个样式映射到级别 1。"]
    seen_levels: Dict[int, str] = {}
    for style_id, level in mapping.items():
        if not isinstance(level, int) or not 1 <= level <= HEADING_LEVEL_MAX:
            errors.append("样式「{0}」的级别 {1!r} 无效：级别必须是 1~{2}。".format(
                style_id, level, HEADING_LEVEL_MAX
            ))
            continue
        if level in seen_levels:
            errors.append(
                "样式「{0}」与「{1}」都映射到级别 {2}：一个级别只能对应一个样式。".format(
                    seen_levels[level], style_id, level
                )
            )
        else:
            seen_levels[level] = style_id
    if seen_levels:
        if 1 not in seen_levels:
            errors.append("样式映射缺少级别 1：至少把一个样式映射到级别 1。")
        gaps = [
            level for level in range(1, max(seen_levels) + 1)
            if level not in seen_levels
        ]
        if gaps:
            errors.append(
                "样式映射存在层级跳跃：缺少 {0} 级的映射，标题层级无法连续。".format(
                    "、".join(str(level) for level in gaps)
                )
            )
    return errors


# --- Markdown 预处理：图片落资源目录 + 围栏代码块降级 ---------------------


class _Preprocessed:
    """单个 Markdown 源的预处理产物与统计。"""

    def __init__(self) -> None:
        self.images = 0
        self.code_blocks = 0
        self.missing_images = 0


def _strip_front_matter(text: str) -> Tuple[str, Optional[str]]:
    """剥离文件头 YAML front matter（``---`` 包裹块），并提取 ``title:`` 作文档名。

    front matter 是元数据不是正文；不剥离会被当成普通段落排进 Word。
    无 front matter 时原样返回 ``(text, None)``。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first = 0
    while first < len(lines) and not lines[first].strip():
        first += 1
    if first >= len(lines) or not _FRONT_MATTER_DELIM.match(lines[first].strip()):
        return text, None
    closing = None
    for idx in range(first + 1, len(lines)):
        if _FRONT_MATTER_DELIM.match(lines[idx].strip()):
            closing = idx
            break
    if closing is None:
        return text, None  # 没有闭合 --- ：不是 front matter，保持原样
    block = "\n".join(lines[first + 1:closing])
    title_match = _FRONT_MATTER_TITLE.search(block)
    title = title_match.group(1).strip("\"'") if title_match else None
    body = "\n".join(lines[closing + 1:])
    return body, (title or None)


def _preprocess_markdown(
    text: str,
    source_dir: Path,
    assets_root: Path,
    state: _Preprocessed,
    warnings: List[str],
    on_warning: Optional[Callable[[str], None]],
) -> List[str]:
    """逐行预处理：图片落资源目录（整行与行内）、围栏代码块与扩展语法降级。

    内核方言没有的 Markdown 结构在此统一降级为最接近的 Word 表达：
    行内图片拆出独立成行、引用块转左缩进段落、水平线转空段落、
    代码块空行以空段落保留。调用方须已执行 ``ensure_kernel_importable()``。
    """
    from docx_common import parse_image_reference

    def rewrite_image(image_ref) -> str:
        relative = image_ref.relative_path
        alt = image_ref.alt or relative
        if _REMOTE_URL_RE.match(relative):
            state.missing_images += 1
            _warn(
                warnings,
                "图片「{0}」是远程地址，模板填充不联网取图，已用占位文本替代。".format(relative),
                on_warning,
            )
            return "【图片缺失：{0}】".format(alt)
        candidate = source_dir / relative
        try:
            candidate.resolve().relative_to(source_dir.resolve())
        except ValueError:
            state.missing_images += 1
            _warn(warnings, "图片越界：{0}（已用占位文本替代）。".format(relative), on_warning)
            return "【图片越界：{0}】".format(alt)
        if not candidate.is_file():
            state.missing_images += 1
            _warn(
                warnings,
                "图片文件不存在：{0}（已用占位文本替代）。".format(relative),
                on_warning,
            )
            return "【图片缺失：{0}】".format(alt)
        state.images += 1
        target_name = "img_{0:03d}_{1}".format(state.images, Path(relative).name)
        shutil.copy2(str(candidate), str(assets_root / target_name))
        size_hint = (
            " ={0}x{1}".format(image_ref.width_px, image_ref.height_px)
            if image_ref.width_px and image_ref.height_px
            else ""
        )
        return "![{0}]({1}{2})".format(image_ref.alt, target_name, size_hint)

    def emit_text_segment(segment: str) -> Optional[str]:
        """把一个文本段写进输出；是纯正文段时返回其文本（供 Setext 判定）。"""
        stripped = segment.strip()
        if not stripped:
            return None
        if _HEADING_RE.match(stripped):
            # 标题行剥掉 CommonMark 闭合井号（"## 标题 ##"）。
            out.append(_CLOSING_HASHES_RE.sub("", stripped))
            return None
        if _HR_RE.match(stripped):
            out.append(_EMPTY_PAR)  # 水平线：内核无对应元素，转为空段落
            return None
        if stripped.startswith(">"):
            body = _QUOTE_PREFIX_RE.sub("", stripped).strip()
            if not body:
                return None
            out.append(_QUOTE_INDENT_MARKER)
            out.append(body)
            return None
        text = segment.rstrip()
        # 拆分行内图片后文本段会带分隔空格：剥掉前导空格，但列表项的
        # 缩进承载嵌套层级（parse_list_line 依赖），必须保留。
        without_lead = text.lstrip()
        if without_lead != text and not _LIST_LINE_RE.match(without_lead):
            text = without_lead
        out.append(text)
        if _LIST_LINE_RE.match(text):
            return None  # 列表项不是 Setext 意义上的正文段
        return text

    out: List[str] = []
    in_fence = False
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    total = len(lines)
    prev_plain: Optional[str] = None  # 上一行是纯正文段时的文本（Setext 判定用）
    index = 0
    while index < total:
        raw = lines[index]
        if in_fence:
            if _FENCE_RE.match(raw):
                # 围栏结束行也得交给内核：否则下游不知道代码块在哪里
                # 结束，块内的 ``# 注释`` 会被当成章节标题。
                out.append(raw)
                in_fence = False
                prev_plain = None
                index += 1
                continue
            if not raw.strip():
                # 代码块空行以空段落保留，块内版面不塌缩。
                out.append(_EMPTY_PAR)
            else:
                # 内容原样交给内核：缩进、Tab、空行与反引号都得保留，
                # 内核把围栏块输出为代码容器，不再在此降级为等宽段落。
                out.append(raw)
            index += 1
            continue
        if _FENCE_RE.match(raw):
            # 开标记同样保留，与结束行成对交给内核解析。
            out.append(raw)
            in_fence = True
            state.code_blocks += 1
            prev_plain = None
            index += 1
            continue

        stripped = raw.strip()
        if not stripped:
            prev_plain = None
            index += 1
            continue

        # GFM 任务列表：Word 无复选框元素，转 ☐/☑ 符号列表项（保留层级缩进）。
        task = _TASK_ITEM_RE.match(raw)
        if task is not None and "![" not in raw:
            prefix, mark, rest = task.groups()
            box = "☑" if mark.lower() == "x" else "☐"
            out.append("{0}{1} {2}".format(prefix, box, rest.strip()) if rest.strip() else "{0}{1}".format(prefix, box))
            prev_plain = None
            index += 1
            continue

        # Setext 标题（CommonMark）：紧跟纯正文段的 === / -- 下划线把该段变标题。
        if prev_plain is not None and "![" not in raw:
            if _SETEXT_H1_RE.match(stripped):
                out[-1] = "# {0}".format(prev_plain)
                prev_plain = None
                index += 1
                continue
            if _SETEXT_H2_RE.match(stripped):
                out[-1] = "## {0}".format(prev_plain)
                prev_plain = None
                index += 1
                continue

        if "![" in raw:
            # 行内图片拆出独立成行；文本段按各自语法（引用/水平线/正文）降级。
            parts = [part for part in _INLINE_IMAGE_SPLIT_RE.split(raw) if part]
            for part in parts:
                image_ref = parse_image_reference(part.strip())
                if image_ref is not None:
                    out.append(rewrite_image(image_ref))
                    prev_plain = None
                else:
                    plain = emit_text_segment(part)
                    prev_plain = plain if len(parts) == 1 else None
            index += 1
            continue

        image_ref = parse_image_reference(stripped)
        if image_ref is not None:
            out.append(rewrite_image(image_ref))
            prev_plain = None
            index += 1
            continue
        prev_plain = emit_text_segment(raw)
        index += 1
    return out


def _warn(warnings: List[str], message: str, on_warning: Optional[Callable[[str], None]]) -> None:
    warnings.append(message)
    if on_warning is not None:
        on_warning(message)


# --- Markdown → 编号章节树 -----------------------------------------------


class _Node:
    """章节树节点（与 importer._Node 同构：depth/title/content/children/num）。"""

    def __init__(self, depth: int, title: str) -> None:
        self.depth = depth
        self.title = title
        self.content: List[str] = []
        self.children: List[_Node] = []
        self.num: List[int] = []

    def is_dir(self) -> bool:
        if self.depth == 1:
            return True
        if self.depth == 2:
            return len(self.children) > 0
        return False

    def display_name(self) -> str:
        if self.depth == 1:
            return "第{0}章 {1}".format(self.num[0], self.title)
        return ".".join(str(value) for value in self.num) + " " + self.title


def _sanitize_title(title: str) -> str:
    from doc_tool.adapters.importer import _sanitize

    return _sanitize(title)


def _split_markdown(text: str) -> Tuple[List[str], List[_Node]]:
    """把一份 Markdown 拆成（首个标题前的正文, 章节树根列表）。

    拆分资格与 ``importer._parse_file`` 一致：H1 一定是章节；H2 需已有 H1
    祖先；H3 需已有 H2 父节点；其余标题行保留在所属章节正文里（内核
    ``process_markdown`` 会继续把它们渲染成对应级别的标题段落）。
    与导入拆分唯一的差异：首个标题之前的正文不丢弃，作为前置正文返回。
    """
    roots: List[_Node] = []
    stack: List[_Node] = []
    preamble: List[str] = []
    # 围栏代码块内的 ``# 注释`` 不是章节标题：这里与共享块解析器
    # （``doc_tool.domain.blocks``）保持同一套围栏规则，避免分章节时把代码
    # 内容拆成标题。
    fence = None
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip()
        fence_match = _FENCE_OPEN_RE.match(raw)
        if fence_match:
            mark = fence_match.group("mark")
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not fence_match.group("info").strip():
                fence = None
            target = stack[-1].content if stack else (roots[0].content if roots else preamble)
            target.append(raw)
            continue
        if fence is not None:
            target = stack[-1].content if stack else (roots[0].content if roots else preamble)
            target.append(raw)
            continue
        match = _HEADING_RE.match(stripped)
        split_ok = False
        if match:
            depth = len(match.group(1))
            if depth == 1:
                split_ok = True
            elif depth == 2:
                split_ok = bool(stack) and stack[0].depth == 1
            elif depth == 3:
                cand = list(stack)
                while cand and depth <= cand[-1].depth:
                    cand.pop()
                split_ok = bool(cand) and cand[-1].depth == 2
        if match and split_ok:
            depth = len(match.group(1))
            title = match.group(2).strip() or "未命名"
            node = _Node(depth, title)
            while stack and depth <= stack[-1].depth:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
            continue
        target = stack[-1].content if stack else (roots[0].content if roots else preamble)
        target.append(raw)
    return preamble, roots


def _assign_numbers(roots: List[_Node], chapter_start: int = 0) -> None:
    """顶层从 ``chapter_start + 1`` 起编号，子级嵌套父编号（与 importer 一致）。"""

    def walk(nodes: List[_Node], parent_num: List[int]) -> None:
        for index, node in enumerate(nodes, start=1):
            node.num = parent_num + [index]
            walk(node.children, node.num)

    for index, node in enumerate(roots, start=1):
        node.num = [chapter_start + index]
        walk(node.children, node.num)


def _count_chapters(roots: Sequence[_Node]) -> int:
    total = 0
    for node in roots:
        total += 1 + _count_chapters(node.children)
    return total


def _emit_tree(node: _Node, out_dir: Path) -> None:
    name = _sanitize_title(node.display_name())
    node_path = out_dir / name
    body = list(node.content)
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if node.is_dir():
        node_path.mkdir(parents=True, exist_ok=True)
        # 空章节也写 _index.md：validate_content_tree 要求目录非空或带子章节。
        (node_path / "_index.md").write_text(
            "\n".join(body) + "\n", encoding="utf-8", newline="\n"
        )
        for child in node.children:
            _emit_tree(child, node_path)
    else:
        # 章节编号含点（"1.1 目的"），不能用 Path.with_suffix。
        md_path = out_dir / (name + ".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            ("\n".join(body) + "\n") if body else "", encoding="utf-8", newline="\n"
        )


def _refresh_fields_with_word(docx_path: Path, timeout_seconds: float) -> Tuple[bool, str]:
    """用本机 Word 对独立 DOCX 执行 COM 域刷新（复用管线的监督刷新入口）。

    返回 ``(是否成功, 原因键)``；Word 不可用/超时/保存失败都不抛错，由调用
    方降级为「打开时刷新」告警。
    """
    from doc_tool.adapters.kernel import ensure_kernel_importable

    ensure_kernel_importable()
    from refresh_fields import supervise  # noqa: E402

    return supervise(output_path=str(docx_path), timeout=int(timeout_seconds))


# --- 底模记忆（~/.doctool/template_fill.json，与 recent.json 同一约定） ----


def _last_template_file() -> Path:
    from doc_tool.domain.branding import USER_CONFIG_DIR_NAME

    return Path.home() / ".{0}".format(USER_CONFIG_DIR_NAME) / "template_fill.json"


def load_last_template() -> Optional[str]:
    """读取上次使用的底模路径；无记录或读取失败返回 None。"""
    try:
        data = json.loads(_last_template_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = str(data.get("last_template") or "").strip()
    return value or None


def save_last_template(template: str) -> None:
    """记录上次使用的底模路径（尽力而为，失败静默）。"""
    try:
        path = _last_template_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"last_template": str(template)}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


# --- 服务入口 -------------------------------------------------------------


def fill_markdown_with_template(
    markdown_paths: Sequence,
    template_docx,
    output_path,
    *,
    heading_style_map: Optional[Dict[str, int]] = None,
    refresh_fields: bool = False,
    refresh_timeout_seconds: float = 300.0,
    clean_body_from_first_heading: bool = False,
    on_warning: Optional[Callable[[str], None]] = None,
) -> TemplateFillResult:
    """把一个或多个 Markdown 文档填充进用户 Word 模板，产出格式一致的 DOCX。

    多个 Markdown 按传入顺序合并为同一文档的连续章节。``refresh_fields`` 为
    True 且本机具备 Word 时出稿后执行 COM 域刷新（目录页码直接成品）；无
    Word 或刷新失败不阻断——产物保留 updateFields 标记由 Word 打开时刷新。
    ``clean_body_from_first_heading`` 用于「拿现成文档当底模」：检测到模板
    正文含标题内容时，复用导入器的 ``generate_template`` 从第一个标题 1 起
    移除正文（封面/页眉/样式原样保留），避免旧正文混进产物。
    失败抛 :class:`TemplateFillError`（E6009），不产出损坏产物。
    """
    from doc_tool.adapters.kernel import ensure_kernel_importable

    ensure_kernel_importable()

    md_paths = [Path(item) for item in markdown_paths]
    if not md_paths:
        raise TemplateFillError(user_message="没有给定任何 Markdown 文件。")
    for path in md_paths:
        if not path.is_file():
            raise TemplateFillError(user_message="Markdown 文件不存在：{0}".format(path))
    template = Path(template_docx)
    if not template.is_file():
        raise TemplateFillError(user_message="Word 模板不存在：{0}".format(template))
    if template.suffix.lower() != ".docx":
        raise TemplateFillError(
            user_message="Word 模板必须是 .docx 文件：{0}".format(template.name)
        )
    output = Path(output_path)

    try:
        styles = parse_template_styles(template)
    except (OOXMLSecurityError, OSError) as exc:
        raise TemplateFillError(user_message="Word 模板无法解析：{0}".format(exc)) from exc
    warnings: List[str] = list(styles.warnings)
    for message in warnings:
        if on_warning is not None:
            on_warning(message)

    heading_styles = styles.heading_styles
    if heading_style_map:
        errors = validate_style_map(heading_style_map)
        known = {info.style_id for info in styles.paragraph_styles}
        unknown = [style_id for style_id in heading_style_map if style_id not in known]
        if unknown:
            errors.append("映射的样式在模板中不存在：{0}。".format("、".join(unknown)))
        if errors:
            raise TemplateFillError(user_message="样式映射无效：\n- " + "\n- ".join(errors))
        heading_styles, pad_warnings = _pad_heading_styles(
            {level: style_id for style_id, level in heading_style_map.items()}
        )
        warnings.extend(pad_warnings)

    from doc_tool.application.markdown_word import read_markdown_text

    preprocessed: List[_Preprocessed] = []
    total_preamble: List[str] = []
    all_roots: List[_Node] = []
    front_matter_title: Optional[str] = None
    with tempfile.TemporaryDirectory(prefix="doc-tool-template-fill-") as workspace_name:
        workspace = Path(workspace_name)
        content_root = workspace / "content"
        assets_root = workspace / "assets"
        tables_root = workspace / "tables"
        for directory in (content_root, assets_root, tables_root):
            directory.mkdir(parents=True, exist_ok=True)

        build_template = template
        if clean_body_from_first_heading and styles.body_heading_count > 0:
            from doc_tool.adapters.importer import generate_template

            cleaned = workspace / "cleaned-template.docx"
            try:
                generate_template(template, cleaned)
            except DocToolError as exc:
                raise TemplateFillError(
                    user_message="清理底模正文失败：{0} {1}".format(
                        exc.user_message, exc.suggested_action
                    ),
                ) from exc
            build_template = cleaned
            _warn(
                warnings,
                "已从底模清理 {0} 个正文标题段（保留封面/页眉/样式）。".format(
                    styles.body_heading_count
                ),
                on_warning,
            )

        for source in md_paths:
            try:
                text = read_markdown_text(source)
            except TextEncodingError as exc:
                raise TemplateFillError(
                    user_message="{0}：{1} {2}".format(
                        source.name, exc.user_message, exc.suggested_action
                    ),
                ) from exc
            body, title = _strip_front_matter(text)
            if front_matter_title is None and title:
                front_matter_title = title
            state = _Preprocessed()
            lines = _preprocess_markdown(
                body, source.parent, assets_root, state, warnings, on_warning
            )
            preprocessed.append(state)
            preamble, roots = _split_markdown("\n".join(lines))
            if not roots and any(line.strip() for line in preamble):
                # 整份文档没有标题：整篇作为一个以文件名命名的章节。
                root = _Node(1, _sanitize_title(source.stem))
                root.content = list(preamble)
                roots = [root]
            elif not roots:
                continue  # 空文件：无前置正文也无章节
            if preamble:
                total_preamble.extend(preamble)
            all_roots.extend(roots)

        if not all_roots and not any(line.strip() for line in total_preamble):
            raise TemplateFillError(user_message="Markdown 内容为空，没有可填充的内容。")

        headless_intro = bool(total_preamble)
        # 前置正文占第 1 章（无标题），实际章节从其之后顺序编号。
        _assign_numbers(all_roots, 1 if headless_intro else 0)
        chapters = _count_chapters(all_roots) + (1 if headless_intro else 0)
        if headless_intro:
            intro = _Node(1, _HEADLESS_TITLE)
            intro.num = [1]
            intro.content = list(total_preamble)
            _emit_tree(intro, content_root)
        for node in all_roots:
            _emit_tree(node, content_root)

        document_name = front_matter_title or md_paths[0].stem or "文档"
        config: Dict = {
            "documentType": "general",
            "documentNo": "",
            "documentName": document_name,
            "documentVersion": "",
            "paths": {
                "template": str(build_template),
                "content_root": str(content_root),
                "asset_root": str(assets_root),
                "table_root": str(tables_root),
                "output": str(output),
            },
            "headingStyles": heading_styles,
            "is_headless": headless_intro,
            "allow_missing_headings": False,
            "bodyStyle": styles.body_style,
        }
        from build_docx import AutomationError, build  # noqa: E402

        try:
            build(config=config)
        except AutomationError as exc:
            raise TemplateFillError(user_message=str(exc)) from exc

        refreshed = "normal"
        if refresh_fields:
            ok, reason = _refresh_fields_with_word(output, refresh_timeout_seconds)
            refreshed = "ok" if ok else reason
            if not ok:
                _warn(
                    warnings,
                    "Word 域刷新未完成（{0}）：产物已保留打开时刷新目录的标记。".format(reason),
                    on_warning,
                )

    warnings.extend(item for item in config.get("_expressionWarnings", []))
    blocks = sum(state.code_blocks for state in preprocessed)
    if blocks:
        warnings.append(
            "检测到 {0} 处围栏代码块：内核方言没有代码块元素，"
            "已按 Consolas 等宽段落降级（块内空行以空段落保留）。".format(blocks)
        )
    known_warnings = set(styles.warnings)
    for message in warnings:
        if on_warning is not None and message not in known_warnings:
            on_warning(message)
    return TemplateFillResult(
        output=output,
        chapters=chapters,
        images=sum(state.images for state in preprocessed),
        warnings=warnings,
        headless_intro=headless_intro,
        refresh_state=refreshed,
    )
