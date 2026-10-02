# -*- coding: utf-8 -*-
"""大纲整理计划：标题决定、跳级整理、标题前正文范围与章节候选（CORE-B 2.2/2.3）。

预览与最终提取共用本模块产出的决定（design D2）：界面展示的层级整理结果、
章节候选与范围，就是 :class:`~doc_tool.application.intake_contract.IntakePlan`
里落盘的那一份，避免“预览一套、导入另一套”。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.intake_contract import (
    HeadingDecision,
    IntakePlan,
    IntakePolicy,
    PlannedTarget,
    SectionCandidate,
    sha256_file,
)

#: 标题来源说明。
SOURCE_STYLE = "style"
SOURCE_OUTLINE = "outline"
SOURCE_HEURISTIC = "heuristic"
SOURCE_SINGLE = "single-chapter"

#: 标题前正文处置方式。
PRE_TITLE_RETAIN = "retain"            #: 作为独立“前言”章节保留
PRE_TITLE_TEMPLATE = "template-covered"  #: 判定为封面/目录，底模已提供
PRE_TITLE_NONE = "none"                #: 没有标题前正文

PRE_TITLE_CHAPTER_TITLE = "前言"


@dataclass
class OutlineDecision:
    """一次层级整理决定（供预览与记录）。"""

    title: str
    original_level: int
    final_level: int
    style_id: str = ""
    action: str = "kept"        #: kept / remapped / flattened / single
    reason: str = ""
    source_index: int = 0

    @property
    def changed(self) -> bool:
        return self.final_level != self.original_level


@dataclass
class OutlinePlan:
    """大纲整理结果：标题决定 + 章节候选 + 标题前正文范围。"""

    decisions: List[HeadingDecision] = field(default_factory=list)
    adjustments: List[OutlineDecision] = field(default_factory=list)
    sections: List[SectionCandidate] = field(default_factory=list)
    normalized_style_map: Dict[str, int] = field(default_factory=dict)
    single_chapter: bool = False
    pre_title_mode: str = PRE_TITLE_NONE
    pre_title_note: str = ""
    has_weak_candidates: bool = False
    jump_levels: List[str] = field(default_factory=list)

    @property
    def remapped_count(self) -> int:
        return sum(1 for item in self.adjustments if item.changed)

    def preview_lines(self, limit: int = 12) -> List[str]:
        """大纲预览：先给最终层级，再列整理动作。"""
        lines: List[str] = []
        if self.single_chapter:
            lines.append("未找到可用标题样式：按单章接管全部可读正文。")
        for decision in self.decisions[:limit]:
            prefix = "  " * max(0, decision.level - 1)
            marker = "（按单章）" if decision.source == SOURCE_SINGLE else ""
            lines.append("{0}{1}. {2}{3}".format(prefix, decision.level, decision.title, marker))
        if len(self.decisions) > limit:
            lines.append("…共 {0} 个标题，其余在详情中查看".format(len(self.decisions)))
        for item in self.adjustments:
            if item.changed:
                lines.append(
                    "层级整理：{0}（{1} → {2}）{3}".format(
                        item.title, item.original_level, item.final_level,
                        ("｜" + item.reason) if item.reason else "",
                    )
                )
        if self.has_weak_candidates:
            lines.append("存在弱推断候选标题：仅作建议，可在「调整章节」中确认。")
        if self.pre_title_note:
            lines.append(self.pre_title_note)
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "singleChapter": self.single_chapter,
            "preTitleMode": self.pre_title_mode,
            "preTitleNote": self.pre_title_note,
            "normalizedStyleMap": dict(self.normalized_style_map),
            "hasWeakCandidates": self.has_weak_candidates,
            "jumpLevels": list(self.jump_levels),
            "decisions": [item.to_dict() for item in self.decisions],
            "adjustments": [
                {
                    "title": item.title, "originalLevel": item.original_level,
                    "finalLevel": item.final_level, "styleId": item.style_id,
                    "action": item.action, "reason": item.reason,
                }
                for item in self.adjustments
            ],
        }


def heading_decisions_from_preview(preview) -> List[HeadingDecision]:
    """把预检标题列表转成标题决定（明确样式与弱推断分开）。"""
    decisions: List[HeadingDecision] = []
    for index, heading in enumerate(getattr(preview, "headings", []) or []):
        style_id = str(getattr(heading, "style_id", "") or "")
        decisions.append(HeadingDecision(
            title=str(getattr(heading, "text", "") or "").strip() or "（未命名标题）",
            level=int(getattr(heading, "level", 1) or 1),
            style_id=style_id,
            source=SOURCE_STYLE if style_id else SOURCE_HEURISTIC,
            action="kept",
            confidence=1.0 if style_id else 0.5,
            source_index=int(getattr(heading, "body_index", index) or index),
        ))
    return decisions


def weak_candidates_from_census(preview, decisions: Sequence[HeadingDecision]) -> List[HeadingDecision]:
    """疑似标题样式只作为候选：已在标题树中的样式不再重复建议。"""
    known = {item.style_id for item in decisions if item.style_id}
    known.update(str(key) for key in (getattr(preview, "heading_style_map", None) or {}))
    candidates: List[HeadingDecision] = []
    census = getattr(preview, "style_census", None) or {}
    for style_id, info in sorted(census.items()):
        if style_id in known:
            continue
        if not getattr(info, "suspected_heading", False):
            continue
        # 只把“正文真的用到”的疑似样式作为候选：仅定义未使用的内置标题样式
        # 不应出现在用户可见的候选清单里。
        if int(getattr(info, "usage_count", 0) or 0) <= 0:
            continue
        candidates.append(HeadingDecision(
            title=str(getattr(info, "name", "") or style_id),
            level=2,
            style_id=str(style_id),
            source=SOURCE_HEURISTIC,
            action="candidate",
            confidence=0.4,
            note="疑似标题样式（{0} 处，示例：{1}）".format(
                getattr(info, "usage_count", 0), getattr(info, "sample_text", "") or "—"
            ),
        ))
    return candidates


def normalize_levels(
    decisions: Sequence[HeadingDecision],
    *,
    allow_flatten: bool = True,
) -> Tuple[List[HeadingDecision], List[OutlineDecision], List[str]]:
    """把跳级序列压平成连续层级，保留标题文本与文档顺序。

    规则：第一个标题落到 1 级；后续标题若比当前层级深超过 1 级，压到
    ``当前层级 + 1``；若比当前层级浅，直接采用（回到已有祖先层级）。
    ``allow_flatten`` 为 False 时只记录建议、不改变层级。
    """
    normalized: List[HeadingDecision] = []
    adjustments: List[OutlineDecision] = []
    jumps: List[str] = []
    current = 0
    for decision in decisions:
        original = int(decision.level or 1)
        title = decision.title
        if current == 0:
            final = 1
        elif original > current + 1:
            final = current + 1
        else:
            final = original
        action = "kept"
        reason = ""
        if final != original:
            jumps.append("{0}：{1} → {2}".format(title, original, final))
            if allow_flatten:
                action = "flattened"
                reason = "原文缺少 {0} 级标题，已补上级结构".format(original - 1)
            else:
                final = original
                action = "candidate"
                reason = "原文跳级（{0} 级缺 {1} 级），可整理为 {2} 级".format(
                    original, original - 1, current + 1
                )
        new_decision = HeadingDecision(
            title=title,
            level=final,
            style_id=decision.style_id,
            source=decision.source,
            action=action,
            confidence=decision.confidence,
            note=decision.note,
            source_index=decision.source_index,
        )
        normalized.append(new_decision)
        adjustments.append(OutlineDecision(
            title=title, original_level=original, final_level=final,
            style_id=decision.style_id, action=action, reason=reason,
            source_index=decision.source_index,
        ))
        current = final
    return normalized, adjustments, jumps


def strict_level_gaps(normalized: Sequence[HeadingDecision]) -> List[str]:
    """返回仍存在的层级跳跃描述（严格模式据此拒绝发布）。"""
    gaps: List[str] = []
    for index, decision in enumerate(normalized):
        if index == 0:
            if decision.level != 1:
                gaps.append("{0} 起始层级为 {1}".format(decision.title, decision.level))
            continue
        previous = normalized[index - 1].level
        if decision.level > previous + 1:
            gaps.append("{0}：{1} → {2}".format(decision.title, previous, decision.level))
    return gaps


def decision_style_map(decisions: Sequence[HeadingDecision]) -> Dict[str, int]:
    """按标题决定生成 styleId -> 级别映射（供模板/提取按同一份决定执行）。"""
    mapping: Dict[str, int] = {}
    for decision in decisions:
        if not decision.style_id:
            continue
        mapping.setdefault(decision.style_id, decision.level)
    return mapping


def sections_from_decisions(
    decisions: Sequence[HeadingDecision],
    *,
    chapter_prefix: str = "c",
) -> List[SectionCandidate]:
    """按标题决定生成可勾选章节：父级为最近的更浅层级标题。"""
    sections: List[SectionCandidate] = []
    stack: List[Tuple[int, str]] = []
    for index, decision in enumerate(decisions):
        chapter_id = "{0}{1}".format(chapter_prefix, index + 1)
        while stack and decision.level <= stack[-1][0]:
            stack.pop()
        parent_id = stack[-1][1] if stack else ""
        sections.append(SectionCandidate(
            chapter_id=chapter_id,
            title=decision.title,
            level=decision.level,
            parent_id=parent_id,
            order=index,
        ))
        stack.append((decision.level, chapter_id))
    return sections


def single_chapter_plan(preview, *, title: str = "") -> OutlinePlan:
    """无可用标题样式：按单章接管全部可读正文。"""
    chapter_title = title or _first_body_text(preview) or "正文"
    decision = HeadingDecision(
        title=chapter_title, level=1, style_id="", source=SOURCE_SINGLE,
        action="single", confidence=0.3, source_index=0,
        note="未找到标题样式，按单章接管",
    )
    return OutlinePlan(
        decisions=[decision],
        adjustments=[OutlineDecision(
            title=chapter_title, original_level=0, final_level=1,
            action="single", reason="源文档没有可用标题样式",
        )],
        sections=[SectionCandidate("c1", chapter_title, level=1, order=0)],
        single_chapter=True,
        pre_title_mode=PRE_TITLE_NONE,
        pre_title_note="无标题样式：全部可读正文归入单章，不要求先指定一级标题。",
    )


def _first_body_text(preview) -> str:
    for heading in getattr(preview, "headings", []) or []:
        text = str(getattr(heading, "text", "") or "").strip()
        if text:
            return text
    return ""


_COVER_IMAGE_HINT = re.compile(r"^(封面|cover|目录|contents|toc)$", re.IGNORECASE)


def decide_pre_title_mode(blocks: Sequence[Dict[str, object]]) -> Tuple[str, str]:
    """决定标题前正文的处置方式（明确范围，不默默丢弃）。

    ``blocks`` 为标题前正文的摘要块：``{"kind": "p"|"image"|"table"|"heading", "text": ...}``。
    - 只有图片（典型封面）→ 判定底模已提供封面（template-covered）；
    - 有可读正文段落 → 作为“前言”章节保留；
    - 没有任何内容 → none。
    """
    if not blocks:
        return PRE_TITLE_NONE, ""
    text_blocks = [
        str(item.get("text") or "").strip() for item in blocks
        if item.get("kind") in ("p", "heading")
    ]
    text_blocks = [item for item in text_blocks if item]
    images = [item for item in blocks if item.get("kind") == "image"]
    tables = [item for item in blocks if item.get("kind") == "table"]
    if not text_blocks and (images or tables):
        return PRE_TITLE_TEMPLATE, "标题前仅有图片/表格，按底模封面处理（原件仍保留）。"
    if len(text_blocks) == 1 and _COVER_IMAGE_HINT.match(text_blocks[0]):
        return PRE_TITLE_TEMPLATE, "标题前只有封面/目录标题，按底模封面处理。"
    return PRE_TITLE_RETAIN, "标题前正文将作为「{0}」章节保留。".format(PRE_TITLE_CHAPTER_TITLE)


def build_plan(
    preview,
    *,
    source: Path,
    target: PlannedTarget,
    policy: Optional[IntakePolicy] = None,
    document_type: str = "general",
    pre_title_blocks: Sequence[Dict[str, object]] = (),
    normalize: bool = True,
) -> Tuple[IntakePlan, OutlinePlan]:
    """由预检结果构造导入计划（预览与提取共用）。"""
    effective_policy = policy or IntakePolicy.normal()
    decisions = heading_decisions_from_preview(preview)
    weak = weak_candidates_from_census(preview, decisions)
    if not decisions:
        outline = single_chapter_plan(preview)
    else:
        normalized, adjustments, jumps = normalize_levels(
            decisions, allow_flatten=normalize and not effective_policy.is_strict
        )
        outline = OutlinePlan(
            decisions=normalized,
            adjustments=adjustments,
            sections=sections_from_decisions(normalized),
            normalized_style_map=decision_style_map(normalized),
            jump_levels=jumps,
        )
        if effective_policy.is_strict:
            gaps = strict_level_gaps(normalized)
            if gaps:
                outline.jump_levels = list(gaps)
    outline.has_weak_candidates = bool(weak)
    mode, note = decide_pre_title_mode(pre_title_blocks)
    outline.pre_title_mode = mode
    outline.pre_title_note = note

    plan = IntakePlan(
        source=str(source),
        sourceHash=sha256_file(source) if Path(source).is_file() else "",
        sourceKind=(Path(source).suffix.lower().lstrip(".") or "docx"),
        documentType=document_type,
        policy=effective_policy,
        target=target,
        headingDecisions=list(outline.decisions) + list(weak),
        sections=list(outline.sections),
        unavailableComparisons=[],
    )
    if outline.jump_levels and not effective_policy.is_strict:
        plan.warnings.append("原文存在跳级标题，已按层级整理计划处理。")
    if outline.single_chapter:
        plan.warnings.append("未找到可用标题样式：按单章接管全部可读正文。")
    if outline.pre_title_note:
        plan.warnings.append(outline.pre_title_note)
    if outline.has_weak_candidates:
        plan.warnings.append("存在弱推断候选标题，仅作建议，不自动采用。")
    return plan, outline


__all__ = [
    "SOURCE_STYLE", "SOURCE_OUTLINE", "SOURCE_HEURISTIC", "SOURCE_SINGLE",
    "PRE_TITLE_RETAIN", "PRE_TITLE_TEMPLATE", "PRE_TITLE_NONE", "PRE_TITLE_CHAPTER_TITLE",
    "OutlineDecision", "OutlinePlan", "heading_decisions_from_preview",
    "weak_candidates_from_census", "normalize_levels", "strict_level_gaps",
    "decision_style_map", "sections_from_decisions", "single_chapter_plan",
    "decide_pre_title_mode", "build_plan",
]