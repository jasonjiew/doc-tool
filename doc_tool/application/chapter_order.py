# -*- coding: utf-8 -*-
"""章节编排与共用变量解析（V2.8 28-B / 2.1、2.3、2.4）。

设计要点（D3）：

- v2 的显式 ``chapters`` 是构建/树/预览/快速打开/索引的**共同顺序**；
- v1（无 ``chapters``）保持原扫描排序，行为不变；
- 缺失章节输出可读说明，未列入的章节给 warning 并保留（默认继续合法章节）；
- 变量 ``{{name}}`` 共用于预处理与预览，代码/围栏/OOXML/资源路径不替换；
  未定义变量用声明默认或可读字面值继续，并给定位 warning。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


#: ``{{name}}：只允许字母、数字、下划线与点（避免误吞正文）。
VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")
#: 未定义变量的可读字面值形式：「待确认：name」。
UNDEFINED_TEMPLATE = "待确认：{0}"
#: 不做变量替换的资源路径扩展名。
RESOURCE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp",
    ".docx", ".xlsx", ".csv", ".pdf", ".drawio",
)


@dataclass
class ChapterOrder:
    """章节顺序解析结果。"""

    ordered: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    unlisted: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.missing or self.unlisted)


def resolve_chapter_order(
    discovered: Sequence[str],
    declared: Optional[Sequence[str]] = None,
) -> ChapterOrder:
    """把「实际扫描到的章节」与「清单声明的顺序」合成唯一顺序。

    ``declared`` 为空（v1）时原样返回 ``discovered``，保证旧项目行为不变。
    声明了但未扫到的进 ``missing``；扫到但未声明的进 ``unlisted``，
    按原相对顺序追加在末尾，不丢内容。
    """
    discovered_list = [str(item) for item in (discovered or [])]
    if not declared:
        return ChapterOrder(ordered=discovered_list)

    normalized_discovered = {_key(item): item for item in discovered_list}
    ordered: List[str] = []
    missing: List[str] = []
    warnings: List[str] = []
    for item in declared:
        entry = str(item or "").strip()
        if not entry:
            continue
        matched = _match_discovered(entry, discovered_list, normalized_discovered)
        if matched is None:
            missing.append(entry)
            warnings.append("声明的章节未找到，已跳过：{0}".format(entry))
            continue
        if matched in ordered:
            warnings.append("章节重复声明已去重：{0}".format(entry))
            continue
        ordered.append(matched)

    unlisted = [item for item in discovered_list if item not in ordered]
    if unlisted:
        warnings.append(
            "未列入顺序的章节已追加在末尾：{0}".format("、".join(unlisted[:5]))
        )
    return ChapterOrder(
        ordered=ordered + unlisted,
        missing=missing,
        unlisted=unlisted,
        warnings=warnings,
    )


def _key(value: str) -> str:
    return str(value).replace("\\\\", "/").strip().strip("/").casefold()


def _match_discovered(entry: str, discovered: List[str], mapping: Dict[str, str]) -> Optional[str]:
    """把声明项匹配到实际章节（允许带/不带扩展名与目录前缀）。"""
    normalized = _key(entry)
    if normalized in mapping:
        return mapping[normalized]
    stem = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
    for candidate in discovered:
        candidate_key = _key(candidate)
        if candidate_key == normalized or candidate_key.rsplit(".", 1)[0] == stem:
            return candidate
        if candidate_key.endswith("/" + normalized) or candidate_key.endswith("/" + stem):
            return candidate
    return None


@dataclass
class VariableResolution:
    """变量解析结果。"""

    text: str
    used: Dict[str, str] = field(default_factory=dict)
    undefined: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def resolve_variables(
    text: str,
    variables: Optional[Dict[str, str]] = None,
    defaults: Optional[Dict[str, str]] = None,
) -> VariableResolution:
    """共用变量解析：代码围栏与资源路径不替换。

    - 已定义变量直接替换；
    - 未定义但有 ``defaults`` 时用默认值；
    - 否则用可读字面值 ``待确认：name`` 继续并记录未定义；
    - 值不递归展开（避免循环引用）。
    """
    values: Dict[str, str] = {}
    for key, value in (variables or {}).items():
        values[str(key)] = "" if value is None else str(value)
    fallback: Dict[str, str] = {}
    for key, value in (defaults or {}).items():
        fallback[str(key)] = "" if value is None else str(value)

    used: Dict[str, str] = {}
    undefined: List[str] = []
    warnings: List[str] = []

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name in values:
            used[name] = values[name]
            return values[name]
        if name in fallback:
            used[name] = fallback[name]
            warnings.append("变量 {0} 未定义，已使用声明默认值".format(name))
            return fallback[name]
        undefined.append(name)
        warnings.append("变量 {0} 未定义，已用可读占位继续".format(name))
        return UNDEFINED_TEMPLATE.format(name)

    lines = str(text).splitlines(keepends=True)
    output: List[str] = []
    in_fence = False
    fence_marker = ""
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            output.append(line)
            continue
        if in_fence:
            output.append(line)
            continue
        output.append(VARIABLE_RE.sub(_replace, line))
    return VariableResolution(
        text="".join(output),
        used=used,
        undefined=undefined,
        warnings=warnings,
    )


def is_resource_path(value: str) -> bool:
    """判定是否为资源路径（这类字符串不参与变量替换）。"""
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith(("http://", "https://")):
        return False
    return text.endswith(RESOURCE_SUFFIXES) or "/" in text or "\\\\" in text