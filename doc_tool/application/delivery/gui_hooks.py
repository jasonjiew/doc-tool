# -*- coding: utf-8 -*-
"""V3.2 32-E 界面服务层钩子（**纯服务层**，不导入任何 Qt 绑定）。

把持久队列（``delivery-queue.json``）与结果索引（``ResultIndex``）转成界面可以
直接渲染的**状态模型**与**动作模型**，并提供「打开产物/包」的路径解析：

- :class:`MemberRow` / :class:`BatchView`：逐成员/变体/格式/状态/路径 + 可用动作。
- :class:`ResultRow` / :class:`ResultView`：只看结果索引时的同形状视图。
- :class:`PlanView`：尚未执行的批次计划预览（成员/格式/目标/问题）。
- :class:`OpenTarget`：解析后的可打开目标（本地文件 / 目录 / 包内相对成员 / 缺失）。
- :class:`ActionModel` + :func:`run_action`：动作 id 与队列服务调用的唯一映射，
  界面只负责触发，不重造编排。

边界说明：本模块不创建任何 Qt 控件，也不连接信号；界面控件接线需要
``ui/main_window`` 会话，本批次未做（见 ``docs/product-v32-execution-entry.md``）。
正式状态不在这里判定，只透传 :mod:`doc_tool.domain.output_state` 与出稿结果的事实。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from doc_tool.application.delivery.contract import (
    ENTRY_INVALID,
    BatchEntry,
    BatchPlan,
)
from doc_tool.application.delivery.queue import (
    COMPLETED_JOB_STATUSES,
    JOB_CANCELLED,
    JOB_INTERRUPTED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_WAITING_REFRESH,
    BatchJob,
    DeliveryQueue,
    job_status_label,
)
from doc_tool.application.delivery.result_index import (
    ENTRY_STATUS_LABELS,
    ResultEntry,
    ResultIndex,
)
from doc_tool.application.intake_contract import format_label, utc_now_iso

# --- 打开目标 ---

OPEN_KIND_FILE = "file"
OPEN_KIND_DIRECTORY = "directory"
OPEN_KIND_PACKAGE_MEMBER = "package-member"
OPEN_KIND_MISSING = "missing"
OPEN_KIND_NONE = "none"

OPEN_KINDS = (
    OPEN_KIND_FILE, OPEN_KIND_DIRECTORY, OPEN_KIND_PACKAGE_MEMBER,
    OPEN_KIND_MISSING, OPEN_KIND_NONE,
)

# --- 视图整体状态（不冒充 complete）---

VIEW_EMPTY = "empty"
VIEW_COMPLETE = "complete"
VIEW_PARTIAL = "partial"
VIEW_INCOMPLETE = "incomplete"
VIEW_FAILED = "failed"

# --- 动作 id（界面按这些 id 触发，映射见 run_action）---

ACTION_RUN_PENDING = "run-pending"
ACTION_RESUME = "resume-interrupted"
ACTION_RETRY = "retry-unfinished"
ACTION_REFRESH = "refresh-pending"
ACTION_CANCEL = "cancel-unfinished"
ACTION_OPEN_RESULT = "open-result"
ACTION_OPEN_INDEX = "open-index"
ACTION_OPEN_PACKAGE = "open-package"

ACTION_LABELS = {
    ACTION_RUN_PENDING: "执行未完成项",
    ACTION_RESUME: "继续中断的成员",
    ACTION_RETRY: "只重试未完成项",
    ACTION_REFRESH: "补刷新（需 Word）",
    ACTION_CANCEL: "取消未完成项（保留已有结果）",
    ACTION_OPEN_RESULT: "打开产物",
    ACTION_OPEN_INDEX: "打开本轮索引",
    ACTION_OPEN_PACKAGE: "打开交付包",
}

#: 需要队列服务执行的动作（其余为界面侧「打开」动作）。
QUEUE_ACTIONS = (
    ACTION_RUN_PENDING, ACTION_RESUME, ACTION_RETRY, ACTION_REFRESH, ACTION_CANCEL,
)
OPEN_ACTIONS = (ACTION_OPEN_RESULT, ACTION_OPEN_INDEX, ACTION_OPEN_PACKAGE)


@dataclass
class OpenTarget:
    """一个可打开目标：界面只按 ``kind``/``path`` 决定用系统默认程序打开什么。"""

    kind: str = OPEN_KIND_NONE
    path: str = ""
    member: str = ""
    label: str = ""
    available: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "member": self.member,
            "label": self.label,
            "available": bool(self.available),
            "reason": self.reason,
        }

    def summary_line(self) -> str:
        if self.available:
            tail = "（包内 {0}）".format(self.member) if self.member else ""
            return "{0}：{1}{2}".format(self.label or self.kind, self.path, tail)
        return "{0}：不可打开（{1}）".format(self.label or self.kind, self.reason or "未找到路径")


def resolve_open_target(target: Any) -> OpenTarget:
    """把 ``结果条目 / 路径字符串`` 解析成可打开目标。

    - ``<包.zip>::docx/foo.docx``（结果索引对包内成员的既有写法）→ 包路径 + 包内成员；
    - 存在的文件 → ``file``；存在的目录（未打包的交付包）→ ``directory``；
    - 空路径 → ``none``；有路径但不存在 → ``missing``（不伪造可打开）。
    """
    if isinstance(target, ResultEntry):
        raw = str(target.path or "")
        label = "{0}｜{1}".format(target.member or "结果", target.label or target.format)
        return _resolve_raw(raw, label=label, source_kind=target.sourceKind)
    if isinstance(target, OpenTarget):
        return target
    return _resolve_raw(str(target or ""), label="")


def _resolve_raw(raw: str, *, label: str, source_kind: str = "") -> OpenTarget:
    text = str(raw or "").strip()
    if not text:
        return OpenTarget(kind=OPEN_KIND_NONE, label=label, reason="该条目没有产物路径")
    if "::" in text:
        package, member = text.split("::", 1)
        package_path = Path(package)
        if not package_path.is_file():
            return OpenTarget(
                kind=OPEN_KIND_MISSING, path=str(package_path), member=member,
                label=label, reason="交付包不存在（可能已被移动或删除）",
            )
        if not member:
            return OpenTarget(
                kind=OPEN_KIND_MISSING, path=str(package_path), label=label,
                reason="包内成员名为空",
            )
        return OpenTarget(
            kind=OPEN_KIND_PACKAGE_MEMBER, path=str(package_path), member=member,
            label=label or Path(member).name, available=True,
            reason="需先从包中取出该成员再打开",
        )
    path = Path(text)
    if path.is_dir():
        return OpenTarget(
            kind=OPEN_KIND_DIRECTORY, path=str(path), label=label or path.name, available=True,
        )
    if path.is_file():
        return OpenTarget(
            kind=OPEN_KIND_FILE, path=str(path), label=label or path.name, available=True,
        )
    return OpenTarget(
        kind=OPEN_KIND_MISSING, path=str(path), label=label,
        reason="路径不存在（未找到产物）",
    )


# --- 逐项/逐格式状态 ---


@dataclass
class FormatCell:
    """一个格式的结果：状态/路径/可用性（各格式状态独立）。"""

    format: str = ""
    label: str = ""
    status: str = ""
    statusLabel: str = ""
    path: str = ""
    exists: bool = False
    usable: bool = False
    formal: bool = False
    message: str = ""
    openTarget: OpenTarget = field(default_factory=OpenTarget)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format,
            "label": self.label,
            "status": self.status,
            "statusLabel": self.statusLabel,
            "path": self.path,
            "exists": bool(self.exists),
            "usable": bool(self.usable),
            "formal": bool(self.formal),
            "message": self.message,
            "openTarget": self.openTarget.to_dict(),
        }

    def summary_line(self) -> str:
        where = self.path or "（无产物）"
        return "{0}：{1}｜{2}{3}".format(
            self.label or self.format, self.statusLabel or self.status, where,
            "" if self.exists or not self.path else "（文件不存在）",
        )


@dataclass
class MemberRow:
    """界面一行：一个批次成员的变体/格式/状态/路径与可用动作。"""

    jobId: str = ""
    batchId: str = ""
    member: str = ""
    memberName: str = ""
    projectRoot: str = ""
    variantId: str = ""
    status: str = ""
    statusLabel: str = ""
    formats: List[str] = field(default_factory=list)
    cells: List[FormatCell] = field(default_factory=list)
    usableCount: int = 0
    totalCount: int = 0
    pendingFormats: List[str] = field(default_factory=list)
    docxPath: str = ""
    indexPath: str = ""
    captureId: str = ""
    waitingReason: str = ""
    error: str = ""
    attemptCount: int = 0
    updatedAt: str = ""
    scopeText: str = ""
    openTargets: List[OpenTarget] = field(default_factory=list)
    actions: List["ActionModel"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jobId": self.jobId,
            "batchId": self.batchId,
            "member": self.member,
            "memberName": self.memberName,
            "projectRoot": self.projectRoot,
            "variantId": self.variantId,
            "status": self.status,
            "statusLabel": self.statusLabel,
            "formats": list(self.formats),
            "cells": [item.to_dict() for item in self.cells],
            "usableCount": self.usableCount,
            "totalCount": self.totalCount,
            "pendingFormats": list(self.pendingFormats),
            "docxPath": self.docxPath,
            "indexPath": self.indexPath,
            "captureId": self.captureId,
            "waitingReason": self.waitingReason,
            "error": self.error,
            "attemptCount": self.attemptCount,
            "updatedAt": self.updatedAt,
            "scopeText": self.scopeText,
            "openTargets": [item.to_dict() for item in self.openTargets],
            "actions": [item.to_dict() for item in self.actions],
        }

    def summary_line(self) -> str:
        variant = "｜变体 {0}".format(self.variantId) if self.variantId else ""
        detail = self.waitingReason or self.error
        return "[{0}] {1}{2}｜{3}/{4} 个格式可用{5}".format(
            self.statusLabel or self.status, self.memberName or self.member, variant,
            self.usableCount, self.totalCount,
            "（{0}）".format(detail) if detail else "",
        )


@dataclass
class ActionModel:
    """界面动作：id + 是否可用 + 不可用原因 + 调用参数。"""

    actionId: str = ""
    label: str = ""
    kind: str = "queue"
    enabled: bool = False
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actionId": self.actionId,
            "label": self.label,
            "kind": self.kind,
            "enabled": bool(self.enabled),
            "reason": self.reason,
            "detail": dict(self.detail),
        }


def _action(
    action_id: str, *, enabled: bool, reason: str = "", detail: Optional[Dict[str, Any]] = None,
) -> ActionModel:
    kind = "queue" if action_id in QUEUE_ACTIONS else "open"
    return ActionModel(
        actionId=action_id, label=ACTION_LABELS.get(action_id, action_id), kind=kind,
        enabled=bool(enabled), reason="" if enabled else (reason or "当前没有可执行的对象"),
        detail=dict(detail or {}),
    )


def _cell_from_result(item) -> FormatCell:
    path = str(getattr(item, "path", "") or "")
    return FormatCell(
        format=str(getattr(item, "format", "") or ""),
        label=format_label(str(getattr(item, "format", "") or "")),
        status=str(getattr(item, "status", "") or ""),
        statusLabel=ENTRY_STATUS_LABELS.get(str(getattr(item, "status", "") or ""), ""),
        path=path,
        exists=bool(path) and Path(path).is_file(),
        usable=bool(getattr(item, "usable", False)),
        formal=bool(getattr(item, "formal", False)),
        message=str(getattr(item, "message", "") or ""),
        openTarget=resolve_open_target(path),
    )


def member_row(job: BatchJob) -> MemberRow:
    """把一个队列任务转成界面行（含逐格式单元与打开目标）。"""
    report = job.report_obj()
    results = list(report.results) if report is not None else []
    cells = [_cell_from_result(item) for item in results]
    by_format = {cell.format: cell for cell in cells}
    formats = list(job.formats) or [cell.format for cell in cells]
    for fmt in formats:
        if fmt not in by_format:
            cells.append(FormatCell(
                format=fmt, label=format_label(fmt), status=job.status,
                statusLabel=job_status_label(job.status), message=job.error or job.waitingReason,
                openTarget=resolve_open_target(""),
            ))
    usable = [cell for cell in cells if cell.usable]
    row = MemberRow(
        jobId=job.jobId,
        batchId=job.batchId,
        member=job.projectRoot,
        memberName=Path(job.projectRoot).name or job.projectRoot,
        projectRoot=job.projectRoot,
        variantId=job.variantId,
        status=job.status,
        statusLabel=job_status_label(job.status),
        formats=formats,
        cells=cells,
        usableCount=len(usable),
        totalCount=len(cells),
        pendingFormats=job.pending_formats(),
        docxPath=job.docxPath,
        indexPath=job.indexPath,
        captureId=job.captureId,
        waitingReason=job.waitingReason,
        error=job.error,
        attemptCount=job.attemptCount,
        updatedAt=job.updatedAt,
        scopeText=job.scope_obj().describe(),
    )
    row.openTargets = [cell.openTarget for cell in cells if cell.path]
    if row.docxPath:
        row.openTargets.append(resolve_open_target(row.docxPath))
    if row.indexPath:
        row.openTargets.append(resolve_open_target(row.indexPath))
    retryable = job.is_retryable()
    row.actions = [
        _action(
            ACTION_OPEN_RESULT, enabled=bool(row.docxPath) and Path(row.docxPath).is_file(),
            reason="本轮没有可打开的 DOCX", detail={"jobIds": [job.jobId], "path": row.docxPath},
        ),
        _action(
            ACTION_OPEN_INDEX, enabled=bool(row.indexPath) and Path(row.indexPath).is_file(),
            reason="本轮没有导出索引", detail={"jobIds": [job.jobId], "path": row.indexPath},
        ),
        _action(
            ACTION_RETRY, enabled=retryable,
            reason="该项已完成（如需补齐请显式重试）", detail={"jobIds": [job.jobId]},
        ),
        _action(
            ACTION_REFRESH, enabled=job.status == JOB_WAITING_REFRESH,
            reason="该项当前不是待刷新", detail={"jobIds": [job.jobId]},
        ),
    ]
    return row


def _view_status(rows: Sequence[MemberRow]) -> str:
    if not rows:
        return VIEW_EMPTY
    if any(row.usableCount for row in rows):
        if all(row.status in COMPLETED_JOB_STATUSES for row in rows):
            return VIEW_COMPLETE
        return VIEW_PARTIAL
    if any(row.status in (JOB_QUEUED, JOB_RUNNING, JOB_INTERRUPTED, JOB_CANCELLED) for row in rows):
        return VIEW_INCOMPLETE
    return VIEW_FAILED


@dataclass
class BatchView:
    """批次任务区视图（状态 + 动作），界面可直接渲染。"""

    batchId: str = ""
    storePath: str = ""
    overallStatus: str = VIEW_EMPTY
    counts: Dict[str, int] = field(default_factory=dict)
    rows: List[MemberRow] = field(default_factory=list)
    actions: List[ActionModel] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    resultRows: List["ResultRow"] = field(default_factory=list)
    generatedAt: str = field(default_factory=utc_now_iso)

    # --- 查询 ---

    def row(self, job_id: str) -> Optional[MemberRow]:
        for item in self.rows:
            if item.jobId == job_id:
                return item
        return None

    def rows_by_member(self) -> Dict[str, List[MemberRow]]:
        grouped: Dict[str, List[MemberRow]] = {}
        for item in self.rows:
            grouped.setdefault(item.memberName or item.member, []).append(item)
        return grouped

    def action(self, action_id: str) -> Optional[ActionModel]:
        for item in self.actions:
            if item.actionId == action_id:
                return item
        return None

    def enabled_actions(self) -> List[ActionModel]:
        return [item for item in self.actions if item.enabled]

    def open_targets(self) -> List[OpenTarget]:
        found: List[OpenTarget] = []
        for row in self.rows:
            for target in row.openTargets:
                if target.path and target not in found:
                    found.append(target)
        return found

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batchId": self.batchId,
            "storePath": self.storePath,
            "overallStatus": self.overallStatus,
            "counts": dict(self.counts),
            "rows": [item.to_dict() for item in self.rows],
            "actions": [item.to_dict() for item in self.actions],
            "warnings": list(self.warnings),
            "resultRows": [item.to_dict() for item in self.resultRows],
            "generatedAt": self.generatedAt,
        }

    def summary_lines(self) -> List[str]:
        lines = ["批次 {0}：{1} 个成员｜整体状态 {2}".format(
            self.batchId or "（未命名）", len(self.rows), self.overallStatus,
        )]
        for row in self.rows:
            lines.append("· " + row.summary_line())
        for action in self.actions:
            if not action.enabled and action.reason:
                lines.append("· 动作 {0} 不可用：{1}".format(action.label, action.reason))
        for item in self.warnings:
            lines.append("提醒：" + item)
        return lines


def _batch_actions(queue: DeliveryQueue) -> List[ActionModel]:
    pending = [job.jobId for job in queue.jobs if job.is_pending()]
    interrupted = [job.jobId for job in queue.jobs if job.status == JOB_INTERRUPTED]
    retryable = [job.jobId for job in queue.jobs if job.is_retryable()]
    waiting = [job.jobId for job in queue.jobs if job.status == JOB_WAITING_REFRESH]
    unfinished = [job.jobId for job in queue.unfinished_jobs()]
    return [
        _action(
            ACTION_RUN_PENDING, enabled=bool(pending),
            reason="没有待执行的成员", detail={"jobIds": pending},
        ),
        _action(
            ACTION_RESUME, enabled=bool(interrupted),
            reason="没有中断的成员", detail={"jobIds": interrupted},
        ),
        _action(
            ACTION_RETRY, enabled=bool(retryable),
            reason="没有失败/待刷新/未完成成员", detail={"jobIds": retryable},
        ),
        _action(
            ACTION_REFRESH, enabled=bool(waiting),
            reason="没有待刷新成员", detail={"jobIds": waiting},
        ),
        _action(
            ACTION_CANCEL, enabled=bool(unfinished),
            reason="没有未完成成员", detail={"jobIds": unfinished},
        ),
    ]


def batch_view(queue: DeliveryQueue, *, index: Optional[ResultIndex] = None) -> BatchView:
    """把队列（可选叠加结果索引）转成界面可渲染视图。"""
    rows = [member_row(job) for job in queue.jobs]
    view = BatchView(
        batchId=queue.batchId,
        storePath=str(queue.store_path),
        overallStatus=_view_status(rows),
        counts=queue.counts(),
        rows=rows,
        actions=_batch_actions(queue),
        warnings=list(queue.warnings),
    )
    if index is not None:
        view.resultRows = result_rows(index)
    return view


# --- 结果索引视图 ---


@dataclass
class ResultRow:
    """结果索引一行（成员/变体/格式/状态/路径 + 打开目标）。"""

    member: str = ""
    variantId: str = ""
    format: str = ""
    label: str = ""
    status: str = ""
    statusLabel: str = ""
    path: str = ""
    sourceKind: str = ""
    sourceRef: str = ""
    message: str = ""
    documentVersion: str = ""
    formal: bool = False
    exists: bool = False
    usable: bool = False
    openTarget: OpenTarget = field(default_factory=OpenTarget)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "member": self.member,
            "variantId": self.variantId,
            "format": self.format,
            "label": self.label,
            "status": self.status,
            "statusLabel": self.statusLabel,
            "path": self.path,
            "sourceKind": self.sourceKind,
            "sourceRef": self.sourceRef,
            "message": self.message,
            "documentVersion": self.documentVersion,
            "formal": bool(self.formal),
            "exists": bool(self.exists),
            "usable": bool(self.usable),
            "openTarget": self.openTarget.to_dict(),
        }

    def summary_line(self) -> str:
        where = self.path or "（无产物路径）"
        return "{0}{1}｜{2}｜{3}｜{4}".format(
            self.member or "（未命名成员）",
            "｜变体 {0}".format(self.variantId) if self.variantId else "",
            self.label or self.format, self.statusLabel or self.status, where,
        )


@dataclass
class ResultView:
    """结果索引视图（部分范围不冒充 complete）。"""

    overallStatus: str = VIEW_EMPTY
    rows: List[ResultRow] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    generatedAt: str = field(default_factory=utc_now_iso)

    def by_member(self) -> Dict[str, List[ResultRow]]:
        grouped: Dict[str, List[ResultRow]] = {}
        for item in self.rows:
            grouped.setdefault(item.member or "（未命名成员）", []).append(item)
        return grouped

    def open_targets(self) -> List[OpenTarget]:
        return [item.openTarget for item in self.rows if item.path]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overallStatus": self.overallStatus,
            "rows": [item.to_dict() for item in self.rows],
            "sources": list(self.sources),
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "generatedAt": self.generatedAt,
        }

    def summary_lines(self) -> List[str]:
        lines = ["结果视图：{0} 条｜整体状态 {1}".format(len(self.rows), self.overallStatus)]
        for item in self.rows:
            lines.append("· " + item.summary_line())
        if self.missing:
            lines.append("缺失 {0} 条路径".format(len(self.missing)))
        for note in self.warnings:
            lines.append("提醒：" + note)
        return lines


def result_rows(index: ResultIndex) -> List[ResultRow]:
    return [
        ResultRow(
            member=entry.member,
            variantId=entry.variantId,
            format=entry.format,
            label=entry.label,
            status=entry.status,
            statusLabel=entry.statusLabel,
            path=entry.path,
            sourceKind=entry.sourceKind,
            sourceRef=entry.sourceRef,
            message=entry.message,
            documentVersion=entry.documentVersion,
            formal=bool(entry.formal),
            exists=bool(entry.exists),
            usable=bool(entry.usable),
            openTarget=resolve_open_target(entry),
        )
        for entry in index.entries
    ]


def result_view(index: ResultIndex) -> ResultView:
    """把 :class:`ResultIndex` 转成界面视图。"""
    status = index.overall_status()
    mapped = {
        "complete": VIEW_COMPLETE,
        "partial": VIEW_PARTIAL,
        "failed": VIEW_FAILED,
        "empty": VIEW_EMPTY,
    }.get(status, VIEW_PARTIAL)
    return ResultView(
        overallStatus=mapped,
        rows=result_rows(index),
        sources=list(index.sources),
        missing=index.missing_paths(),
        warnings=list(index.warnings),
    )


# --- 计划预览视图 ---


@dataclass
class PlanRow:
    """未执行计划中的一行成员（含成员级问题）。"""

    entryId: str = ""
    member: str = ""
    memberName: str = ""
    kind: str = ""
    variantId: str = ""
    formats: List[str] = field(default_factory=list)
    destination: str = ""
    strict: bool = False
    refresh: bool = True
    status: str = ""
    problems: List[str] = field(default_factory=list)
    jobId: str = ""

    @property
    def executable(self) -> bool:
        return self.status != ENTRY_INVALID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entryId": self.entryId,
            "member": self.member,
            "memberName": self.memberName,
            "kind": self.kind,
            "variantId": self.variantId,
            "formats": list(self.formats),
            "destination": self.destination,
            "strict": bool(self.strict),
            "refresh": bool(self.refresh),
            "status": self.status,
            "problems": list(self.problems),
            "executable": self.executable,
            "jobId": self.jobId,
        }

    def summary_line(self) -> str:
        tail = "（{0}）".format("；".join(self.problems)) if self.problems else ""
        return "[{0}] {1}｜{2}｜{3}{4}".format(
            self.status, self.memberName or self.member, self.member,
            "、".join(self.formats), tail,
        )


@dataclass
class PlanView:
    """批次计划预览视图（不执行）。"""

    batchId: str = ""
    overallStatus: str = VIEW_EMPTY
    rows: List[PlanRow] = field(default_factory=list)
    actions: List[ActionModel] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    generatedAt: str = field(default_factory=utc_now_iso)

    def executable_rows(self) -> List[PlanRow]:
        return [row for row in self.rows if row.executable]

    def invalid_rows(self) -> List[PlanRow]:
        return [row for row in self.rows if not row.executable]

    def action(self, action_id: str) -> Optional[ActionModel]:
        for item in self.actions:
            if item.actionId == action_id:
                return item
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batchId": self.batchId,
            "overallStatus": self.overallStatus,
            "rows": [row.to_dict() for row in self.rows],
            "actions": [item.to_dict() for item in self.actions],
            "problems": list(self.problems),
            "warnings": list(self.warnings),
            "generatedAt": self.generatedAt,
        }

    def summary_lines(self) -> List[str]:
        lines = ["批次计划 {0}：{1} 个成员｜可执行 {2}".format(
            self.batchId or "（未命名）", len(self.rows), len(self.executable_rows()),
        )]
        for row in self.rows:
            lines.append("· " + row.summary_line())
        for item in self.problems:
            lines.append("计划问题：" + item)
        for item in self.warnings:
            lines.append("提醒：" + item)
        return lines


def plan_view(plan: BatchPlan, *, jobs: Sequence[BatchJob] = ()) -> PlanView:
    """把解析后的计划转成界面预览视图；``jobs`` 用于把已登记任务挂到成员行。"""
    rows: List[PlanRow] = []
    for entry in plan.all_entries():
        rows.append(PlanRow(
            entryId=entry.entryId,
            member=entry.member,
            memberName=entry.memberName,
            kind=entry.kind,
            variantId=entry.variantId,
            formats=list(entry.formats),
            destination=entry.destination,
            strict=bool(entry.strict),
            refresh=bool(entry.refresh),
            status=entry.status,
            problems=list(entry.problems),
            jobId=_matching_job_id(entry, jobs),
        ))
    executable = [row for row in rows if row.executable]
    if not rows:
        status = VIEW_EMPTY
    elif not executable:
        status = VIEW_FAILED
    elif len(executable) == len(rows):
        status = VIEW_COMPLETE
    else:
        status = VIEW_PARTIAL
    actions = [
        _action(
            ACTION_RUN_PENDING, enabled=bool(executable),
            reason="计划没有可执行成员", detail={"entryIds": [row.entryId for row in executable]},
        ),
    ]
    return PlanView(
        batchId=plan.batchId, overallStatus=status, rows=rows, actions=actions,
        problems=list(plan.problems), warnings=list(plan.warnings),
    )


def _matching_job_id(entry: BatchEntry, jobs: Sequence[BatchJob]) -> str:
    from doc_tool.application.delivery.contract import entry_matches

    for job in jobs or ():
        if entry_matches(entry, job):
            return job.jobId
    return ""


# --- 动作执行（服务层唯一映射）---


def run_action(
    queue: DeliveryQueue,
    action: Any,
    *,
    skip_word_refresh: bool = False,
    cancel_token: Any = None,
    progress: Any = None,
) -> List[BatchJob]:
    """按 :class:`ActionModel`（或动作 id）调用既有队列服务。

    界面只负责触发；``open-*`` 动作不在这里执行（由界面用
    :func:`resolve_open_target` 的结果打开文件），调用时返回空列表。
    """
    action_id = action.actionId if isinstance(action, ActionModel) else str(action or "")
    detail = action.detail if isinstance(action, ActionModel) else {}
    if isinstance(action, ActionModel) and not action.enabled:
        return []
    job_ids = detail.get("jobIds") or None
    if action_id == ACTION_RUN_PENDING:
        return queue.run_pending(
            skip_word_refresh=skip_word_refresh, cancel_token=cancel_token,
            progress=progress, only_job_ids=list(job_ids) if job_ids else None,
        )
    if action_id == ACTION_RESUME:
        # resume 会重载 store 后再执行未落定项；限定 job 时退回 run_pending。
        if job_ids:
            return queue.run_pending(
                skip_word_refresh=skip_word_refresh, cancel_token=cancel_token,
                progress=progress, only_job_ids=list(job_ids),
            )
        return queue.resume(
            skip_word_refresh=skip_word_refresh, cancel_token=cancel_token, progress=progress,
        )
    if action_id == ACTION_RETRY:
        return queue.retry_unfinished(
            skip_word_refresh=skip_word_refresh, cancel_token=cancel_token,
            progress=progress, only_job_ids=list(job_ids) if job_ids else None,
        )
    if action_id == ACTION_REFRESH:
        return queue.retry_unfinished(
            skip_word_refresh=False, cancel_token=cancel_token, progress=progress,
            only_job_ids=list(job_ids) if job_ids else None,
        )
    if action_id == ACTION_CANCEL:
        queue.cancel(job_ids=list(job_ids) if job_ids else None)
        return []
    return []


__all__ = [
    "OPEN_KIND_FILE", "OPEN_KIND_DIRECTORY", "OPEN_KIND_PACKAGE_MEMBER",
    "OPEN_KIND_MISSING", "OPEN_KIND_NONE", "OPEN_KINDS",
    "VIEW_EMPTY", "VIEW_COMPLETE", "VIEW_PARTIAL", "VIEW_INCOMPLETE", "VIEW_FAILED",
    "ACTION_RUN_PENDING", "ACTION_RESUME", "ACTION_RETRY", "ACTION_REFRESH",
    "ACTION_CANCEL", "ACTION_OPEN_RESULT", "ACTION_OPEN_INDEX", "ACTION_OPEN_PACKAGE",
    "ACTION_LABELS", "QUEUE_ACTIONS", "OPEN_ACTIONS",
    "OpenTarget", "resolve_open_target",
    "FormatCell", "MemberRow", "ActionModel", "BatchView", "batch_view", "member_row",
    "ResultRow", "ResultView", "result_view", "result_rows",
    "PlanRow", "PlanView", "plan_view",
    "run_action",
]
