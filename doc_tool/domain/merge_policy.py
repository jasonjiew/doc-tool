# -*- coding: utf-8 -*-
"""正式文档合并策略（MergePolicy）：容错重排、行内标题平移、题号合成与范围裁剪。

方向 1 / 方向 2 / 方向 5 的核心领域模型：
1. ``MergePolicy``：统一收敛章节树扫描容错（``renumber_mode``）、行内标题自动平移
   （``auto_shift_inline_headings``）、标题编号合成策略（``heading_number_mode``）、
   显式章节编排（``respect_chapter_order``）、局部章节范围合并（``chapter_scope``）
   与静态域缓存写入（``synthesize_static_fields``）。
2. 内置预设档位：
   - ``strict``：严格模式（默认，与既有内核 100% 兼容，要求编号连续、行内标题 > depth）。
   - ``tolerant``：容错合入模式（允许删减章节断号、无编号文件、中文章节号，自动顺延重排并平移越界行内标题）。
   - ``scoped``：局部章节合并模式（支持按 ``chapter_scope`` 仅合并指定章节/子目录并自动重排连续编号）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from doc_tool.domain.markdown_structure import prose_lines

_CN_NUM_MAP = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100,
}
_CN_CHAPTER_RE = re.compile(r"^第\s*([零〇一二两三四五六七八九十百\d]+)\s*[章节篇部]\s*(.+)$")
_CN_ENUM_RE = re.compile(r"^(?:([零〇一二两三四五六七八九十百]+)[、.．\s]+|[（(]([零〇一二两三四五六七八九十百\d]+)[)）]\s*)(.+)$")
_APPENDIX_PREFIX_RE = re.compile(r"^附录\s*([A-Za-z0-9一二三四五六七八九十]+)?\s*(.*)$")


def _cn_to_int(token: str) -> Optional[int]:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if len(token) == 1 and token in _CN_NUM_MAP:
        return _CN_NUM_MAP[token]
    total = 0
    current = 0
    for ch in token:
        val = _CN_NUM_MAP.get(ch)
        if val is None:
            return None
        if val >= 10:
            if current == 0:
                current = 1
            total += current * val
            current = 0
        else:
            current = val
    return total + current


def parse_heading_number_prefix(text: str) -> Optional[Tuple[Tuple[int, ...], str, str]]:
    """解析扩展中文章节号/公文序号/附录前缀，返回 ``(逻辑编号元组, 标题文本, 类型)``。"""
    s = text.strip()
    m_ch = _CN_CHAPTER_RE.match(s)
    if m_ch:
        num = _cn_to_int(m_ch.group(1))
        rest = m_ch.group(2).strip()
        if num is not None and rest:
            return (num,), rest, "cn_chapter"
    m_enum = _CN_ENUM_RE.match(s)
    if m_enum:
        raw_num = m_enum.group(1) or m_enum.group(2) or ""
        num = _cn_to_int(raw_num)
        rest = m_enum.group(3).strip()
        if num is not None and rest:
            return (num,), rest, "cn_enum"
    m_app = _APPENDIX_PREFIX_RE.match(s)
    if m_app:
        code = (m_app.group(1) or "").strip()
        rest = (m_app.group(2) or "").strip()
        title = rest if rest else s
        if code and len(code) == 1 and code.upper().isalpha():
            idx = ord(code.upper()) - ord("A") + 1
            return (idx,), title, "appendix"
        num = _cn_to_int(code) if code else None
        if num is not None:
            return (num,), title, "appendix"
    return None


MERGE_PROFILE_STRICT = "strict"
MERGE_PROFILE_TOLERANT = "tolerant"
MERGE_PROFILE_SCOPED = "scoped"
MERGE_PROFILE_CUSTOM = "custom"

RENUMBER_STRICT = "strict"
RENUMBER_AUTO_CONTIGUOUS = "auto_contiguous"
RENUMBER_PRESERVE = "preserve"

HEADING_NUM_TEMPLATE = "template_num"
HEADING_NUM_LITERAL = "literal_prefix"
HEADING_NUM_AUTO = "auto_detect"

TOP_FORMAT_CHAPTER = "chapter"
TOP_FORMAT_DECIMAL = "decimal"

_STANDARD_CHAPTER_RE = re.compile(r"^第(\d+)章\s+(.+)$")
_STANDARD_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")
_SLUG_PREFIX_RE = re.compile(r"^0*(\d+)[-_]\s*(.+)$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_HEADING_RE = re.compile(r"^(#{1,9})(\s+.+)$")


@dataclass(frozen=True)
class MergePolicy:
    """正式文件合并策略配置。"""

    profile: str = MERGE_PROFILE_STRICT
    renumber_mode: str = RENUMBER_STRICT
    auto_shift_inline_headings: bool = False
    heading_number_mode: str = HEADING_NUM_TEMPLATE
    top_level_format: str = TOP_FORMAT_CHAPTER
    respect_chapter_order: bool = True
    chapter_scope: Tuple[str, ...] = ()
    synthesize_static_fields: bool = True

    def effective_renumber_mode(self) -> str:
        """若启用了局部章节范围（chapter_scope）且未显式改用 preserve，自动启用连续顺延编号。"""
        if self.chapter_scope and self.renumber_mode == RENUMBER_STRICT:
            return RENUMBER_AUTO_CONTIGUOUS
        return self.renumber_mode

    def allow_extended_titles(self) -> bool:
        return self.effective_renumber_mode() in (
            RENUMBER_AUTO_CONTIGUOUS,
            RENUMBER_PRESERVE,
        )

    def allow_unnumbered_titles(self) -> bool:
        return self.effective_renumber_mode() in (
            RENUMBER_AUTO_CONTIGUOUS,
            RENUMBER_PRESERVE,
        )

    def with_scope(self, chapter_scope: Sequence[str]) -> "MergePolicy":
        cleaned = tuple(str(s).strip().replace("\\", "/") for s in chapter_scope if str(s).strip())
        if not cleaned:
            return self
        return replace(
            self,
            profile=MERGE_PROFILE_SCOPED if self.profile == MERGE_PROFILE_STRICT else self.profile,
            chapter_scope=cleaned,
            renumber_mode=(
                RENUMBER_AUTO_CONTIGUOUS
                if self.renumber_mode == RENUMBER_STRICT
                else self.renumber_mode
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "renumberMode": self.renumber_mode,
            "autoShiftInlineHeadings": self.auto_shift_inline_headings,
            "headingNumberMode": self.heading_number_mode,
            "topLevelFormat": self.top_level_format,
            "respectChapterOrder": self.respect_chapter_order,
            "chapterScope": list(self.chapter_scope),
            "synthesizeStaticFields": self.synthesize_static_fields,
        }

    @classmethod
    def from_profile(cls, profile: str) -> "MergePolicy":
        key = (profile or MERGE_PROFILE_STRICT).strip().lower()
        if key == MERGE_PROFILE_TOLERANT:
            return TOLERANT_MERGE_POLICY
        if key == MERGE_PROFILE_SCOPED:
            return SCOPED_MERGE_POLICY
        return STRICT_MERGE_POLICY

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MergePolicy":
        if not data or not isinstance(data, dict):
            return STRICT_MERGE_POLICY
        if isinstance(data, MergePolicy):
            return data
        profile = str(data.get("profile", MERGE_PROFILE_STRICT) or MERGE_PROFILE_STRICT).strip().lower()
        base = cls.from_profile(profile)
        raw_scope = data.get("chapterScope", data.get("chapter_scope", base.chapter_scope)) or ()
        scope = tuple(
            str(item).strip().replace("\\", "/")
            for item in raw_scope
            if str(item).strip()
        )
        return cls(
            profile=profile,
            renumber_mode=str(
                data.get("renumberMode", data.get("renumber_mode", base.renumber_mode))
                or base.renumber_mode
            ),
            auto_shift_inline_headings=bool(
                data.get(
                    "autoShiftInlineHeadings",
                    data.get("auto_shift_inline_headings", base.auto_shift_inline_headings),
                )
            ),
            heading_number_mode=str(
                data.get(
                    "headingNumberMode",
                    data.get("heading_number_mode", base.heading_number_mode),
                )
                or base.heading_number_mode
            ),
            top_level_format=str(
                data.get(
                    "topLevelFormat",
                    data.get("top_level_format", base.top_level_format),
                )
                or base.top_level_format
            ),
            respect_chapter_order=bool(
                data.get(
                    "respectChapterOrder",
                    data.get("respect_chapter_order", base.respect_chapter_order),
                )
            ),
            chapter_scope=scope,
            synthesize_static_fields=bool(
                data.get(
                    "synthesizeStaticFields",
                    data.get("synthesize_static_fields", base.synthesize_static_fields),
                )
            ),
        )


STRICT_MERGE_POLICY = MergePolicy(
    profile=MERGE_PROFILE_STRICT,
    renumber_mode=RENUMBER_STRICT,
    auto_shift_inline_headings=False,
    heading_number_mode=HEADING_NUM_TEMPLATE,
    top_level_format=TOP_FORMAT_CHAPTER,
    respect_chapter_order=True,
    chapter_scope=(),
    synthesize_static_fields=True,
)

TOLERANT_MERGE_POLICY = MergePolicy(
    profile=MERGE_PROFILE_TOLERANT,
    renumber_mode=RENUMBER_AUTO_CONTIGUOUS,
    auto_shift_inline_headings=True,
    heading_number_mode=HEADING_NUM_AUTO,
    top_level_format=TOP_FORMAT_CHAPTER,
    respect_chapter_order=True,
    chapter_scope=(),
    synthesize_static_fields=True,
)

SCOPED_MERGE_POLICY = MergePolicy(
    profile=MERGE_PROFILE_SCOPED,
    renumber_mode=RENUMBER_AUTO_CONTIGUOUS,
    auto_shift_inline_headings=True,
    heading_number_mode=HEADING_NUM_AUTO,
    top_level_format=TOP_FORMAT_CHAPTER,
    respect_chapter_order=True,
    chapter_scope=(),
    synthesize_static_fields=True,
)

DEFAULT_MERGE_POLICY = MergePolicy(
    profile=MERGE_PROFILE_TOLERANT,
    renumber_mode=RENUMBER_PRESERVE,
    auto_shift_inline_headings=True,
    heading_number_mode=HEADING_NUM_AUTO,
    top_level_format=TOP_FORMAT_CHAPTER,
    respect_chapter_order=True,
    chapter_scope=(),
    synthesize_static_fields=True,
)


def resolve_merge_policy(config: Optional[Dict[str, Any]] = None) -> MergePolicy:
    """从内核 config 字典解析生效的 ``MergePolicy``。"""
    if not config or not isinstance(config, dict):
        return DEFAULT_MERGE_POLICY
    raw = config.get("mergePolicy") or config.get("merge_policy")
    if isinstance(raw, MergePolicy):
        policy = raw
    elif isinstance(raw, dict):
        policy = MergePolicy.from_dict(raw)
    elif isinstance(raw, str):
        policy = MergePolicy.from_profile(raw)
    else:
        policy = DEFAULT_MERGE_POLICY
    extra_scope = config.get("chapterScope") or config.get("chapter_scope")
    if extra_scope:
        policy = policy.with_scope(extra_scope)
    return policy


def parse_merge_title(
    text: str,
    *,
    parent_number: Tuple[int, ...] = (),
    allow_extended: bool = False,
    allow_unnumbered: bool = False,
) -> Tuple[Optional[Tuple[int, ...]], str]:
    """解析章节目录/文件名的编号与标题。

    - 严格模式下仅识别 ``第N章 标题`` 与 ``N.M 标题``（保持与原 ``parse_title`` 一致）。
    - 扩展模式下额外识别中文数字章/节（如 ``第一章 引言``、``一、总体设计``、``第一节 背景``）、
      ``01-标题`` 前缀，以及无编号文件名（返回 ``(None, 标题)`` 交由上层按位置顺延编号）。
    """
    cleaned = text.strip()
    match = _STANDARD_CHAPTER_RE.match(cleaned)
    if match:
        return (int(match.group(1)),), match.group(2).strip()
    match = _STANDARD_SECTION_RE.match(cleaned)
    if match:
        number = tuple(int(part) for part in match.group(1).split("."))
        return number, match.group(2).strip()

    if allow_extended:
        slug_match = _SLUG_PREFIX_RE.match(cleaned)
        if slug_match:
            idx = int(slug_match.group(1))
            return parent_number + (idx,), slug_match.group(2).strip()

        ext = parse_heading_number_prefix(cleaned)
        if ext is not None:
            num_tuple, rest_title, _kind = ext
            if rest_title:
                if len(num_tuple) == 1 and parent_number:
                    return parent_number + num_tuple, rest_title.strip()
                return num_tuple, rest_title.strip()

    if allow_unnumbered and cleaned:
        return None, cleaned
    return None, cleaned


def shift_inline_headings_for_depth(
    markdown_text: str,
    depth: int,
    *,
    enabled: bool = False,
) -> Tuple[str, int]:
    """Shift prose headings below the file depth, preserving code and comments."""
    if not enabled or not markdown_text:
        return markdown_text, 0
    lines = markdown_text.splitlines(keepends=True)
    eligible = {number for number, _ in prose_lines(markdown_text)}
    levels = [
        len(match.group(1))
        for number, line in enumerate(lines, 1)
        if number in eligible
        for match in [_INLINE_HEADING_RE.match(line.rstrip("\r\n"))]
        if match
    ]
    if not levels or min(levels) > depth:
        return markdown_text, 0
    shift = depth + 1 - min(levels)
    for number in eligible:
        line = lines[number - 1]
        stripped = line.rstrip("\r\n")
        match = _INLINE_HEADING_RE.match(stripped)
        if match:
            lines[number - 1] = "#" * min(9, len(match.group(1)) + shift) + match.group(2) + line[len(stripped):]
    return "".join(lines), shift


def format_heading_with_number(
    title: str,
    number: Sequence[int],
    *,
    top_level_format: str = TOP_FORMAT_CHAPTER,
) -> str:
    """将逻辑编号合成为显式标题前缀（幂等，若已带相同前缀则不重复添加）。"""
    clean_title = title.strip()
    if not number:
        return clean_title
    if len(number) == 1:
        if top_level_format == TOP_FORMAT_CHAPTER:
            prefix = "第{0}章".format(number[0])
            if re.match(r"^第\s*{0}\s*章\b".format(number[0]), clean_title):
                return clean_title
            return "{0} {1}".format(prefix, clean_title).strip()
        prefix = str(number[0])
        if re.match(r"^{0}(?:\s+|[.、])".format(re.escape(prefix)), clean_title):
            return clean_title
        return "{0} {1}".format(prefix, clean_title).strip()
    prefix = ".".join(str(part) for part in number)
    if clean_title.startswith(prefix + " ") or clean_title == prefix:
        return clean_title
    return "{0} {1}".format(prefix, clean_title).strip()


def matches_chapter_scope(rel_path: str, scope: Sequence[str]) -> bool:
    """判断相对 ``content_root`` 的路径是否命中 ``chapter_scope``。

    支持：
    1. 精确相对路径匹配（含或不含 ``.md``）
    2. 目录前缀匹配（选中父章时自动包含其全部子节）
    3. 祖先目录匹配（选中某个子节时自动保留其外层章目录节点）
    4. 章节号/文件名前缀匹配（如 ``"第2章"`` 或 ``"2.1"``）
    """
    if not scope:
        return True
    norm_path = rel_path.strip().replace("\\", "/").strip("/")
    if not norm_path:
        return True
    path_no_ext = norm_path[:-3] if norm_path.lower().endswith(".md") else norm_path
    parts = norm_path.split("/")
    basename = parts[-1]
    stem = basename[:-3] if basename.lower().endswith(".md") else basename

    for raw_target in scope:
        target = str(raw_target).strip().replace("\\", "/").strip("/")
        if not target:
            continue
        target_no_ext = target[:-3] if target.lower().endswith(".md") else target
        # 1. 完全相等（含或不含 .md）
        if norm_path == target or path_no_ext == target_no_ext:
            return True
        # 2. 当前路径位于目标目录内
        if norm_path.startswith(target_no_ext + "/"):
            return True
        # 3. 当前目录是目标路径的祖先目录
        if target_no_ext.startswith(path_no_ext + "/"):
            return True
        # Numeric scopes must retain container ancestors, not sibling sections.
        if re.fullmatch(r"\d+(?:\.\d+)*", target_no_ext):
            wanted = tuple(int(part) for part in target_no_ext.split("."))
            numbers = []
            for segment in parts:
                segment = segment[:-3] if segment.lower().endswith(".md") else segment
                number, _ = parse_merge_title(segment)
                if number:
                    numbers.append(number)
            if any(number[:len(wanted)] == wanted for number in numbers):
                return True
            is_container = not norm_path.lower().endswith(".md") or stem == "_index"
            if is_container and numbers and wanted[:len(numbers[-1])] == numbers[-1]:
                return True
            continue
        # 4. 顶层或当前节点前缀匹配（如 "第2章"、"2.1"）
        if "/" not in target:
            for seg in (parts[0], basename, stem):
                if seg == target or seg == target_no_ext or seg.startswith(target_no_ext + " "):
                    return True
    return False
