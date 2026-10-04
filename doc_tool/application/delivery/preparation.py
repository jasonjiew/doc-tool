# -*- coding: utf-8 -*-
"""V4.3 43-A：一次交付的**准备视图**（复用 delivery/CORE，不建第二批量执行器）。

准备阶段只做事实汇总，不执行、不写成果：

- 成员：名字、来源路径、真实项目/工作区身份、捕获来源模式（已保存/当前内容）；
- 范围：整份/所选章节（来自真实结构化 scope，不从文本反解析）；
- 格式：每成员请求的格式；
- 模板/预设与目录：真实引用路径与输出目录；
- 摘要：从**最终请求参数**读回，逐项可核对；
- 局部失效：缺成员/坏设置只影响该项，其余成员仍可执行（子集不得冒充完整基线）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from doc_tool.application.delivery.contract import (
    ENTRY_INVALID,
    ENTRY_READY,
    ENTRY_WARNING,
    BatchEntry,
    BatchPlan,
)

#: 交付集合的完整性口径（区别于“部分结果”）。
COMPLETENESS_FULL = "full"
COMPLETENESS_PARTIAL = "partial"
COMPLETENESS_EMPTY = "empty"

#: 来源模式（与 CORE 一致）。
SOURCE_SAVED = "saved"
SOURCE_CURRENT_BUFFER = "current-buffer"


@dataclass
class PreparationRow:
    """准备视图中的一行成员。"""

    entryId: str = ""
    member: str = ""
    memberName: str = ""
    memberKind: str = ""
    projectRoot: str = ""
    projectExists: bool = False
    sourceMode: str = SOURCE_SAVED
    hasUnsaved: bool = False
    scopeKind: str = ""
    scopeText: str = ""
    scopeChapters: List[str] = field(default_factory=list)
    formats: List[str] = field(default_factory=list)
    destination: str = ""
    templateRef: str = ""
    outputName: str = ""
    strict: bool = False
    refresh: bool = True
    executable: bool = True
    problems: List[str] = field(default_factory=list)

    @property
    def sourceLabel(self) -> str:
        return "当前内容" if self.sourceMode == SOURCE_CURRENT_BUFFER else "已保存版本"

    def to_dict(self) -> Dict[str, object]:
        return {
            "entryId": self.entryId, "member": self.member, "memberName": self.memberName,
            "memberKind": self.memberKind, "projectRoot": self.projectRoot,
            "projectExists": self.projectExists, "sourceMode": self.sourceMode,
            "sourceLabel": self.sourceLabel, "hasUnsaved": self.hasUnsaved,
            "scopeKind": self.scopeKind, "scopeText": self.scopeText,
            "scopeChapters": list(self.scopeChapters), "formats": list(self.formats),
            "destination": self.destination, "templateRef": self.templateRef,
            "outputName": self.outputName, "strict": self.strict, "refresh": self.refresh,
            "executable": self.executable, "problems": list(self.problems),
        }

    def summary_line(self) -> str:
        tail = "（{0}）".format("；".join(self.problems)) if self.problems else ""
        return "{0}｜{1}｜{2}｜{3}｜{4}{5}".format(
            self.memberName or self.member, self.memberKind or "项目",
            self.sourceLabel, self.scopeText or "整份",
            "、".join(self.formats) or "未指定格式", tail,
        )


@dataclass
class DeliveryPreparation:
    """一次交付的准备事实（提交前可核对）。"""

    planId: str = ""
    baseDir: str = ""
    completeness: str = COMPLETENESS_EMPTY
    rows: List[PreparationRow] = field(default_factory=list)
    templateRefs: List[str] = field(default_factory=list)
    sharedDestination: str = ""
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def executableRows(self) -> List[PreparationRow]:
        return [row for row in self.rows if row.executable]

    @property
    def invalidRows(self) -> List[PreparationRow]:
        return [row for row in self.rows if not row.executable]

    @property
    def hasUnsaved(self) -> bool:
        return any(row.hasUnsaved or row.sourceMode == SOURCE_CURRENT_BUFFER for row in self.rows)

    @property
    def isCompleteSet(self) -> bool:
        return self.completeness == COMPLETENESS_FULL

    def completenessLabel(self) -> str:
        return {
            COMPLETENESS_FULL: "完整集合",
            COMPLETENESS_PARTIAL: "部分集合（不得冒充完整基线）",
            COMPLETENESS_EMPTY: "没有可执行成员",
        }.get(self.completeness, self.completeness)

    def summary_lines(self) -> List[str]:
        lines = ["本次交付：{0} 个成员｜可执行 {1}｜{2}".format(
            len(self.rows), len(self.executableRows), self.completenessLabel(),
        )]
        lines.append("输出目录：{0}".format(self.sharedDestination or "（按成员各自目录）"))
        for row in self.rows:
            lines.append("· " + row.summary_line())
        if self.templateRefs:
            lines.append("模板/预设：{0}".format("；".join(self.templateRefs)))
        if self.hasUnsaved:
            lines.append("包含未保存编辑：按明确所选来源进入本轮捕获；提交后继续编辑只影响下一轮")
        for item in self.problems:
            lines.append("问题：" + item)
        for item in self.warnings:
            lines.append("提醒：" + item)
        for item in self.skipped:
            lines.append("已跳过：" + item)
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "planId": self.planId, "baseDir": self.baseDir,
            "completeness": self.completeness,
            "completenessLabel": self.completenessLabel(),
            "isCompleteSet": self.isCompleteSet,
            "sharedDestination": self.sharedDestination,
            "templateRefs": list(self.templateRefs),
            "rows": [row.to_dict() for row in self.rows],
            "problems": list(self.problems), "warnings": list(self.warnings),
            "skipped": list(self.skipped),
        }


def _scope_dict(entry) -> dict:
    """成员的**结构化范围**：契约里是 dict；兼容 ExportScope 形态。"""
    scope = getattr(entry, "scope", None)
    if isinstance(scope, dict):
        return scope
    if scope is None:
        return {}
    return {
        "kind": str(getattr(scope, "kind", "") or ""),
        "chapters": [str(item) for item in (getattr(scope, "chapters", None) or [])],
        "current": str(getattr(scope, "current", "") or ""),
    }


def _scope_text(scope) -> str:
    """结构化范围 → 可读文本（不从字符串反解析）。"""
    kind = str(scope.get("kind") or "") if isinstance(scope, dict) else str(getattr(scope, "kind", "") or "")
    if kind == "chapters":
        chapters = scope.get("chapters") if isinstance(scope, dict) else (getattr(scope, "chapters", None) or [])
        return "所选 {0} 章".format(len(list(chapters or [])))
    if kind == "current-chapter":
        current = str(
            (scope.get("current") if isinstance(scope, dict) else getattr(scope, "current", "")) or ""
        )
        return "当前章" + ("（{0}）".format(Path(current).name) if current else "")
    return "整份"


def _template_ref(plan: BatchPlan, entry: BatchEntry) -> str:
    """模板/预设引用：优先成员自身声明，其次批次 default 段。"""
    for attr in ("template", "preset", "templateRef"):
        value = getattr(entry, attr, None)
        if value:
            return str(value)
    defaults = getattr(plan, "defaults", None)
    if isinstance(defaults, dict):
        for key in ("template", "preset", "templateRef"):
            if defaults.get(key):
                return str(defaults[key])
        return ""
    for attr in ("template", "preset", "templateRef"):
        value = getattr(defaults, attr, None)
        if value:
            return str(value)
    return ""


def prepare_delivery(
    plan: BatchPlan,
    *,
    unsaved_members: Sequence[str] = (),
    current_buffer_members: Sequence[str] = (),
) -> DeliveryPreparation:
    """把批次计划转成准备视图（不执行）。

    ``unsaved_members``：当前有未保存编辑的成员（只影响该成员来源标注）；
    ``current_buffer_members``：本轮明确选择“当前内容”作为来源的成员。
    """
    prep = DeliveryPreparation(
        planId=str(getattr(plan, "batchId", "") or ""),
        baseDir=str(getattr(plan, "baseDir", "") or ""),
    )
    unsaved = {str(item).replace("\\", "/") for item in (unsaved_members or ())}
    buffers = {str(item).replace("\\", "/") for item in (current_buffer_members or ())}

    # 契约解析会把**不可执行成员**放进 plan.skipped（那是成员项，不是“已跳过项”
    # 文本），准备视图必须同时展示它们，否则界面上“缺成员”会凭空消失。
    entries = list(plan.all_entries()) if hasattr(plan, "all_entries") else []
    if not entries:
        entries = list(getattr(plan, "entries", []) or []) + list(getattr(plan, "skipped", []) or [])
    destinations: List[str] = []
    for entry in entries:
        scope = _scope_dict(entry)
        problems = [str(item) for item in (getattr(entry, "problems", None) or [])]
        root = str(getattr(entry, "projectRoot", "") or "")
        exists = bool(root) and Path(root).is_dir()
        if root and not exists:
            problems.append("成员路径不存在：{0}".format(root))
        status = str(getattr(entry, "status", ENTRY_READY) or ENTRY_READY)
        executable = status != ENTRY_INVALID and bool(root) and exists
        if status == ENTRY_WARNING and not problems:
            problems.append("该项带提醒，仍可执行")
        source_mode = str(getattr(entry, "sourceMode", "") or SOURCE_SAVED)
        member = str(getattr(entry, "member", "") or "")
        if member in buffers:
            source_mode = SOURCE_CURRENT_BUFFER
        elif source_mode not in (SOURCE_SAVED, SOURCE_CURRENT_BUFFER):
            source_mode = SOURCE_SAVED
        destination = str(getattr(entry, "destination", "") or "")
        if destination:
            destinations.append(destination)
        prep.rows.append(PreparationRow(
            entryId=str(getattr(entry, "entryId", "") or ""),
            member=member,
            memberName=str(getattr(entry, "memberName", "") or "") or member,
            memberKind=str(getattr(entry, "kind", "") or ""),
            projectRoot=root,
            projectExists=exists,
            sourceMode=source_mode,
            hasUnsaved=member in unsaved,
            scopeKind=str(scope.get("kind") or ""),
            scopeText=_scope_text(scope),
            scopeChapters=[str(item) for item in (scope.get("chapters") or [])],
            formats=[str(item) for item in (getattr(entry, "formats", None) or [])],
            destination=destination,
            templateRef=_template_ref(plan, entry),
            outputName=str(getattr(entry, "outputName", "") or ""),
            strict=bool(getattr(entry, "strict", False)),
            refresh=bool(getattr(entry, "refresh", True)),
            executable=executable,
            problems=problems,
        ))

    prep.sharedDestination = destinations[0] if destinations and len(set(destinations)) == 1 else ""
    prep.templateRefs = sorted({row.templateRef for row in prep.rows if row.templateRef})
    # 文本型“已跳过项”（非成员项）单列；成员项已在上面的 rows 中体现。
    prep.skipped = [
        item for item in (getattr(plan, "skipped", None) or [])
        if isinstance(item, str)
    ]
    prep.problems = [str(item) for item in (getattr(plan, "problems", None) or [])]
    prep.warnings = [str(item) for item in (getattr(plan, "warnings", None) or [])]

    if not prep.rows:
        prep.completeness = COMPLETENESS_EMPTY
    elif prep.executableRows and not prep.invalidRows and not prep.skipped:
        prep.completeness = COMPLETENESS_FULL
    else:
        # 有失效成员/跳过项 → 部分集合，界面不得自称完整基线。
        prep.completeness = COMPLETENESS_PARTIAL
        missing = [row.memberName for row in prep.invalidRows]
        if missing:
            prep.warnings.append("缺成员：{0}（其余成员可继续）".format("、".join(missing)))
        if prep.skipped:
            prep.warnings.append("已跳过 {0} 项，部分结果不冒充完整基线".format(len(prep.skipped)))
    return prep


__all__ = [
    "COMPLETENESS_FULL", "COMPLETENESS_PARTIAL", "COMPLETENESS_EMPTY",
    "SOURCE_SAVED", "SOURCE_CURRENT_BUFFER",
    "PreparationRow", "DeliveryPreparation", "prepare_delivery",
    "SubmissionCapture", "submission_capture", "round_is_stale",
]

# --- V4.3 43-A：提交后编辑只影响下一轮（捕获身份固定在提交时） -----------------


@dataclass
class SubmissionCapture:
    """一次提交的固定捕获事实（提交后编辑不得改写它）。"""

    batchId: str = ""
    requestId: str = ""
    submittedAt: str = ""
    members: List[Dict[str, object]] = field(default_factory=list)
    sourceDigests: Dict[str, str] = field(default_factory=dict)
    isCompleteSet: bool = False
    problems: List[str] = field(default_factory=list)

    @property
    def memberCount(self) -> int:
        return len(self.members)

    def source_digest_for(self, member: str) -> str:
        return str(self.sourceDigests.get(str(member), ""))

    def to_dict(self) -> Dict[str, object]:
        return {
            "batchId": self.batchId, "requestId": self.requestId,
            "submittedAt": self.submittedAt, "memberCount": self.memberCount,
            "members": [dict(item) for item in self.members],
            "sourceDigests": dict(self.sourceDigests),
            "isCompleteSet": self.isCompleteSet,
            "problems": list(self.problems),
        }


def submission_capture(prep: DeliveryPreparation, *, job_ids: Sequence[str] = ()) -> SubmissionCapture:
    """把准备事实固化为**提交捕获**（提交后编辑不改写它）。"""
    from datetime import datetime, timezone
    import hashlib

    capture = SubmissionCapture(
        batchId=prep.planId,
        requestId="{0}-{1}".format(prep.planId or "batch", len(prep.executableRows)),
        submittedAt=datetime.now(timezone.utc).isoformat(),
        isCompleteSet=prep.isCompleteSet,
        problems=list(prep.problems),
    )
    for index, row in enumerate(prep.rows):
        capture.members.append({
            "entryId": row.entryId,
            "member": row.member,
            "memberName": row.memberName,
            "projectRoot": row.projectRoot,
            "sourceMode": row.sourceMode,
            "scopeKind": row.scopeKind,
            "scopeText": row.scopeText,
            "scopeChapters": list(row.scopeChapters),
            "formats": list(row.formats),
            "destination": row.destination,
            "executable": row.executable,
            "jobId": job_ids[index] if index < len(job_ids) else "",
        })
        if row.projectRoot:
            try:
                payload = json.dumps({
                    "member": row.member, "scope": row.scopeChapters,
                    "formats": row.formats, "sourceMode": row.sourceMode,
                }, ensure_ascii=False, sort_keys=True)
                capture.sourceDigests[row.member] = hashlib.sha256(
                    payload.encode("utf-8")
                ).hexdigest()
            except (TypeError, ValueError):
                pass
    return capture


def round_is_stale(capture: SubmissionCapture, prep_now: DeliveryPreparation) -> bool:
    """提交后准备事实是否已变化（变化只影响**下一轮**，不改写本轮）。"""
    current = {row.member: row for row in prep_now.rows}
    if set(current) != {str(item.get("member") or "") for item in capture.members}:
        return True
    for item in capture.members:
        row = current.get(str(item.get("member") or ""))
        if row is None:
            return True
        if row.scopeChapters != list(item.get("scopeChapters") or []):
            return True
        if list(row.formats) != list(item.get("formats") or []):
            return True
        if row.sourceMode != str(item.get("sourceMode") or ""):
            return True
    return False
