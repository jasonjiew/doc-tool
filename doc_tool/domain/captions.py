# -*- coding: utf-8 -*-
"""题注与交叉引用共享注册表（V2.7 任务 4.1～4.3 / 设计 D3）。

三入口（正式项目构建、模板填充、评审稿）和内置预览共用同一份注册表，
因此「同一份 Markdown 得到同一组编号与引用结论」不需要各写一套。

契约：

- 图 ``![说明](assets/figure.png){#fig-login}``、表前题注
  ``Table: 参数表 {#tbl-params}``、引用 ``@fig-login`` / ``@tbl-params``。
- 编号按**全文出现顺序**独立分配（图与表各自从 1 开始）。
- 重复标识只在输出层唯一化（``fig-x-2``），不修改源码。
- 歧义（前缀匹配到多个）或缺失的引用保留可读文本并给出定位 warning，
  绝不猜测目标对象。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from doc_tool.domain.blocks import (
    KIND_COMPLEX_TABLE as BLOCK_KIND_COMPLEX_TABLE,
    KIND_IMAGE,
    KIND_TABLE as BLOCK_KIND_TABLE,
    REFERENCE_RE,
    ParsedDocument,
    SourceLocation,
)


from doc_tool.kernel_shared.docx_blocks import bookmark_name_for

KIND_FIGURE = "fig"
#: 表格题注条目类型（与 ``blocks.KIND_TABLE`` 的块种类不同：这里是题注维度）。
KIND_TABLE_CAPTION = "tbl"
#: 兼容别名：历史调用点使用 ``KIND_TABLE`` 表示题注类型。
KIND_TABLE = KIND_TABLE_CAPTION

#: 图/表题注在输出中的固定前缀。
FIGURE_PREFIX = "图"
TABLE_PREFIX = "表"

#: 歧义引用保留的可读占位（不生成已知失效域）。
AMBIGUOUS_PLACEHOLDER = "引用待确认（{0}）"
MISSING_PLACEHOLDER = "引用待确认（{0}）"


@dataclass
class CaptionEntry:
    """一个已登记题注对象。"""

    ident: str
    output_ident: str
    kind: str
    number: int
    label: str
    location: SourceLocation
    bookmark: str = ""
    duplicate: bool = False

    @property
    def display(self) -> str:
        prefix = FIGURE_PREFIX if self.kind == KIND_FIGURE else TABLE_PREFIX
        return "{0} {1} {2}".format(prefix, self.number, self.label).strip()


@dataclass
class ReferenceResolution:
    """一条正文引用的解析结论。"""

    kind: str
    ident: str
    location: SourceLocation
    entry: Optional[CaptionEntry] = None
    ambiguous: bool = False
    missing: bool = False
    candidates: Tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.entry is not None and not self.ambiguous and not self.missing

    @property
    def placeholder(self) -> str:
        token = "@{0}-{1}".format(self.kind, self.ident)
        return MISSING_PLACEHOLDER.format(token)

    @property
    def display_text(self) -> str:
        if self.resolved and self.entry is not None:
            return self.entry.display
        return self.placeholder


@dataclass
class CaptionRegistry:
    """按全文顺序登记题注并解析引用。"""

    entries: Dict[str, CaptionEntry] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    duplicates: List[Tuple[str, SourceLocation]] = field(default_factory=list)
    figure_count: int = 0
    table_count: int = 0
    _output_seen: Dict[str, int] = field(default_factory=dict)
    _sequential: Dict[str, int] = field(default_factory=dict)
    _all_entries: List[CaptionEntry] = field(default_factory=list)

    def _unique_output_ident(self, ident: str) -> Tuple[str, bool]:
        count = self._output_seen.get(ident, 0)
        self._output_seen[ident] = count + 1
        if count == 0:
            return ident, False
        return "{0}-{1}".format(ident, count + 1), True

    def register(
        self,
        ident: str,
        kind: str,
        label: str,
        location: SourceLocation,
    ) -> CaptionEntry:
        """登记题注；``ident`` 为空时按序号生成稳定标识。"""
        if kind == KIND_FIGURE:
            self.figure_count += 1
            number = self.figure_count
        else:
            self.table_count += 1
            number = self.table_count

        duplicate = ident in self.entries
        if not ident:
            ident = "{0}-auto-{1}".format("fig" if kind == KIND_FIGURE else "tbl", number)
        if duplicate:
            self.duplicates.append((ident, location))

        output_ident, rewritten = self._unique_output_ident(ident)
        entry = CaptionEntry(
            ident=ident,
            output_ident=output_ident,
            kind=kind,
            number=number,
            label=label,
            location=location,
            bookmark=bookmark_name_for(output_ident),
            duplicate=duplicate or rewritten,
        )
        # 首次登记的对象才是引用的目标；重复标识不再覆盖，避免引用漂移。
        # 每次登记都进入 _all_entries，保证编号与输出唯一化按出现顺序推进。
        self.entries.setdefault(ident, entry)
        self._all_entries.append(entry)
        self.order.append(ident)
        return entry

    def sequential_number(self, entry: CaptionEntry) -> int:
        """同一标识重复出现时按出现顺序递增编号（输出层唯一化，不改源码）。"""
        seen = self._sequential.get(entry.ident, 0) + 1
        self._sequential[entry.ident] = seen
        if entry.duplicate and seen > 1:
            return entry.number + seen - 1
        return entry.number

    def order_entries(self) -> List[CaptionEntry]:
        """按全文出现顺序返回每一次登记（重复标识也各占一项）。

        ``entries`` 只保留每个标识的首次登记（引用目标），``order_entries``
        保留全部登记，供编号与唯一化输出使用。
        """
        return list(self._all_entries)

    def get(self, ident: str) -> Optional[CaptionEntry]:
        return self.entries.get(ident)

    def find_candidates(self, token: str) -> List[str]:
        """前缀匹配候选（用于歧义引用判定，不用于猜测目标）。"""
        lowered = token.lower()
        return [
            ident
            for ident in self.entries
            if ident.lower().startswith(lowered + "-") or ident.lower().startswith(lowered + ".")
        ]

    def resolve_token(self, kind: str, token: str) -> str:
        """无位置的引用解析：返回显示文本（供预期事件与预览复用）。"""
        resolution = self.resolve(kind, token, SourceLocation("", 0, 0))
        return resolution.display_text

    def resolve(self, kind: str, token: str, location: SourceLocation) -> ReferenceResolution:
        """解析一条引用；歧义与缺失都不猜测目标。"""
        ident = "{0}-{1}".format(kind, token)
        entry = self.entries.get(ident)
        if entry is not None:
            return ReferenceResolution(kind=kind, ident=token, location=location, entry=entry)
        candidates = tuple(self.find_candidates(ident))
        if len(candidates) == 1:
            return ReferenceResolution(
                kind=kind,
                ident=token,
                location=location,
                entry=self.entries[candidates[0]],
                candidates=candidates,
            )
        if len(candidates) > 1:
            return ReferenceResolution(
                kind=kind,
                ident=token,
                location=location,
                ambiguous=True,
                candidates=candidates,
            )
        return ReferenceResolution(kind=kind, ident=token, location=location, missing=True)


def resolve_inline_references(text: str, registry: Optional[CaptionRegistry]) -> str:
    """把正文中的 ``@fig-x`` / ``@tbl-x`` 解析为可读显示文本。

    解析结论与构建侧完全一致（同一注册表、同一规则）：命中对象显示
    「图 2 标题」，歧义或缺失保留可读占位文本，不猜测目标。未提供注册表
    时保持源码原样，便于旧项目与不做校验的场景。
    """
    if registry is None or not text:
        return text

    def replace(match):
        return registry.resolve_token(match.group("kind"), match.group("slug"))

    return REFERENCE_RE.sub(replace, text)


def build_registry(documents: Iterable[ParsedDocument]) -> CaptionRegistry:
    """按文档顺序登记全部题注，得到全局编号。"""
    registry = CaptionRegistry()
    for document in documents:
        register_document(registry, document)
    return registry


def register_document(registry: CaptionRegistry, document: ParsedDocument) -> CaptionRegistry:
    """按块顺序登记一份文档中的图表题注。"""
    for block in document.blocks:
        if block.kind == KIND_IMAGE:
            # 图片即使没有显式标识也要登记：注册表按全文顺序分配编号（fig-auto-N），
            # 保证任何图片都能被正文引用并得到稳定显示编号。
            registry.register(
                getattr(block, "ident", "") or "",
                KIND_FIGURE,
                getattr(block, "caption", "") or getattr(block, "alt", "") or "",
                block.location,
            )
        elif block.kind in (BLOCK_KIND_TABLE, BLOCK_KIND_COMPLEX_TABLE):
            ident = getattr(block, "ident", "") or ""
            caption = getattr(block, "caption", "") or ""
            if not ident and not caption:
                continue
            registry.register(ident, KIND_TABLE_CAPTION, caption, block.location)
    return registry


def iter_reference_locations(text: str, path: str) -> List[Tuple[str, str, SourceLocation]]:
    """收集文本中的引用，返回 ``(类型, 标识, 位置)``。"""
    found: List[Tuple[str, str, SourceLocation]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in REFERENCE_RE.finditer(line):
            found.append(
                (
                    match.group("kind"),
                    match.group("slug"),
                    SourceLocation(path, line_no, line_no),
                )
            )
    return found


def reference_warnings(
    documents: Iterable[ParsedDocument], registry: CaptionRegistry
) -> List[Dict[str, object]]:
    """歧义/缺失引用的可定位提醒（不猜目标，也不阻断出稿）。

    位置取自共享块解析的 ``SourceLocation``（源文件 + 1-based 行号），
    与报告/问题中心定位一致；命中对象的引用不产生提醒。
    """
    warnings: List[Dict[str, object]] = []
    seen = set()
    for document in documents:
        for block in document.blocks:
            text = getattr(block, "text", "") or ""
            if block.kind in (BLOCK_KIND_TABLE, BLOCK_KIND_COMPLEX_TABLE):
                text = getattr(block, "caption", "") or ""
            if "@" not in text:
                continue
            line_no = block.location.start_line
            for match in REFERENCE_RE.finditer(text):
                kind = match.group("kind")
                token = match.group("slug")
                key = (document.path, line_no, kind, token)
                if key in seen:
                    continue
                seen.add(key)
                resolution = registry.resolve(
                    kind, token, SourceLocation(document.path, line_no, line_no)
                )
                if resolution.resolved:
                    continue
                if resolution.ambiguous:
                    warnings.append(
                        {
                            "path": document.path,
                            "line": line_no,
                            "rule": "caption_reference_ambiguous",
                            "message": "引用 @{0}-{1} 歧义，命中多个候选：{2}。".format(
                                kind, token, "、".join(resolution.candidates)
                            ),
                            "hint": "请把引用改为完整标识。",
                        }
                    )
                else:
                    warnings.append(
                        {
                            "path": document.path,
                            "line": line_no,
                            "rule": "caption_reference_missing",
                            "message": "引用 @{0}-{1} 未找到对应题注对象。".format(
                                kind, token
                            ),
                            "hint": "请确认图/表已添加 {#标识}，或修正引用名称。",
                        }
                    )
    return warnings


def registry_warnings(registry: CaptionRegistry) -> List[Dict[str, object]]:
    """重复标识的可定位提醒（供报告与问题中心复用）。"""
    warnings: List[Dict[str, object]] = []
    for ident, location in registry.duplicates:
        warnings.append(
            {
                "path": location.path,
                "line": location.start_line,
                "rule": "caption_duplicate_ident",
                "message": "题注标识 {0} 重复；输出层已分配唯一名称。".format(ident),
                "hint": "请为每个图表使用唯一标识，正文引用才能稳定指向同一对象。",
            }
        )
    return warnings


CAPTION_STYLE_CANDIDATES = ("Caption", "题注", "图表题注", "表题注", "图题注")


def resolve_caption_style(styles_root, preferred: str = "") -> str:
    """在模板样式表里挑一个可用的题注段落样式；都没有时返回空串。

    模板可能根本没有 Caption 样式（极简模板常见）。此时题注用正文样式
    输出并保持居中，而不是引用不存在的 styleId 产出非法文档。
    """
    if styles_root is None:
        return ""
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    available: Dict[str, str] = {}
    for style in styles_root.iter(w + "style"):
        if style.get(w + "type") != "paragraph":
            continue
        style_id = style.get(w + "styleId") or ""
        name_node = style.find(w + "name")
        name = (name_node.get(w + "val") if name_node is not None else "") or ""
        if style_id:
            available[style_id] = name
    if preferred and preferred in available:
        return preferred
    lowered = {key.lower(): key for key in available}
    for candidate in CAPTION_STYLE_CANDIDATES:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    for style_id, name in available.items():
        if "caption" in name.lower() or "题注" in name:
            return style_id
    return ""