# -*- coding: utf-8 -*-
"""Pure presentation state for the PySide6 desktop workbench.

The objects in this module contain no Qt widgets.  They translate existing
project, task, Word, filesystem and pipeline-stage facts into labels, action
availability and step-checklist states so the menu bar, project bar and the
right task/result dock cannot drift apart.

The module stays importable in pure-service tests (no QApplication required);
heavy Qt imports are deferred to the widget layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


class WorkView(str, Enum):
    """Main-content view states: empty / idle / running / result."""

    EMPTY = "empty"
    IDLE = "idle"
    RUNNING = "running"
    RESULT = "result"


# Step statuses mirror the pipeline stage/status vocabulary.
STEP_STATUS_PENDING = "pending"
STEP_STATUS_RUNNING = "running"
STEP_STATUS_SUCCESS = "success"
STEP_STATUS_SKIPPED = "skipped"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True)
class ActionState:
    """Availability and adjacent explanation for one workbench action."""

    enabled: bool
    reason: str = ""


@dataclass(frozen=True)
class WorkbenchState:
    """Testable snapshot rendered by :class:`MainWindow`."""

    view: str
    project_name: str = ""
    project_path: str = ""
    document_type: str = ""
    access_text: str = "未打开项目"
    readiness_text: str = "请选择或新建项目"
    status_tone: str = "neutral"
    reasons: tuple[str, ...] = ()
    actions: Dict[str, ActionState] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultState:
    """Persistent task result shown until the next task or project switch."""

    status: str = "idle"
    task: str = ""
    title: str = "尚无任务结果"
    summary: str = "完成校验或构建后，可在这里继续打开产物和报告。"
    advice: str = ""
    error_code: str = ""
    stage: str = ""
    exception_summary: str = ""
    output_path: Optional[Path] = None
    report_path: Optional[Path] = None
    log_path: Optional[Path] = None
    project_root: Optional[Path] = None
    # 已格式化的出错位置行（``文件:行号 说明 建议``），内核给出结构化
    # 位置时填充。失败卡片与技术详情直接展示，用户不必去日志里翻。
    locations: Tuple[str, ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.status in ("success", "failure", "cancelled")


@dataclass(frozen=True)
class StepItem:
    """One row of the step checklist (derived from pipeline stage events)."""

    stage: str
    label: str
    status: str = STEP_STATUS_PENDING
    detail: str = ""
    error_code: Optional[str] = None


@dataclass(frozen=True)
class DetailState:
    """Log/result detail pane state kept testable without widgets."""

    expanded: bool = False
    pending_unread: int = 0
    log_path: Optional[Path] = None


def derive_workbench_state(
    project,
    *,
    running: bool,
    task_label: str = "",
    word_available: Optional[bool] = None,
    report_path: Optional[Path] = None,
    result_available: bool = False,
) -> WorkbenchState:
    """Derive all high-frequency action states from existing application facts."""
    if project is None:
        disabled = ActionState(False, "请先打开项目")
        return WorkbenchState(
            view=WorkView.EMPTY,
            actions={
                "validate": disabled,
                "merge": disabled,
                "diag_build": disabled,
                "content": disabled,
                "output": disabled,
                "report": disabled,
                "logs": disabled,
            },
        )

    writable = bool(getattr(project, "is_writable", False))
    manifest = getattr(project, "manifest", None)
    paths = getattr(project, "paths", None)
    project_root = getattr(project, "project_root", None)
    report_exists = bool(report_path and Path(report_path).is_file())
    reasons = []

    content_exists = True
    output_exists = bool(getattr(project, "output_exists", True))
    if manifest is not None and paths is not None:
        try:
            content_exists = paths.resolve(manifest.relative_content_root()).is_dir()
        except Exception:
            content_exists = False
        try:
            output_exists = paths.output_dir.is_dir()
        except Exception:
            output_exists = False

    if running:
        reasons.append("{0}正在运行，项目操作暂不可用".format(task_label or "后台任务"))
    if not writable:
        reasons.append("项目模式版本高于当前应用支持版本，仅可只读查看")
    if writable and word_available is False:
        reasons.append("Microsoft Word 不可用；正式合并需要 Word，诊断构建仍可使用")
    if not output_exists:
        reasons.append("尚未生成输出目录")
    if not report_exists:
        reasons.append("尚未生成校验报告")

    write_reason = ""
    if running:
        write_reason = "已有任务正在运行"
    elif not writable:
        write_reason = "项目为只读"

    merge_reason = write_reason
    if not merge_reason and word_available is False:
        merge_reason = "Microsoft Word 不可用"

    actions = {
        "validate": ActionState(writable and not running, write_reason),
        "merge": ActionState(
            writable and not running and word_available is not False,
            merge_reason,
        ),
        "diag_build": ActionState(writable and not running, write_reason),
        "content": ActionState(content_exists, "内容目录不存在"),
        "output": ActionState(output_exists, "尚未生成输出目录"),
        "report": ActionState(report_exists, "尚未生成校验报告"),
        # The existing command deliberately creates this project-owned directory.
        "logs": ActionState(True),
    }

    if running:
        readiness = "任务运行中：{0}".format(task_label or "处理中")
        tone = "warning"
    elif not writable:
        readiness = "只读项目：构建与校验不可用"
        tone = "warning"
    elif word_available is True:
        readiness = "已具备正式合并条件"
        tone = "success"
    elif word_available is False:
        readiness = "可诊断构建；正式合并缺少 Microsoft Word"
        tone = "warning"
    else:
        readiness = "正式合并将在启动时检查 Microsoft Word"
        tone = "neutral"

    # Four-view mapping: running drives the "running" view; a persistent result
    # of the current project drives the "result" view; otherwise the IDE idles.
    if running:
        view = WorkView.RUNNING
    elif result_available:
        view = WorkView.RESULT
    else:
        view = WorkView.IDLE

    document_name = getattr(manifest, "documentName", "") if manifest else ""
    document_type = getattr(manifest, "documentType", "") if manifest else ""
    root_name = getattr(project_root, "name", "") if project_root else ""
    return WorkbenchState(
        view=view,
        project_name=document_name or root_name,
        project_path=str(project_root or ""),
        document_type=document_type,
        access_text="可写" if writable else "只读（版本不兼容）",
        readiness_text=readiness,
        status_tone=tone,
        reasons=tuple(reasons),
        actions=actions,
    )


def derive_step_list(
    events: Sequence[Tuple[str, str, str, Optional[str]]],
    *,
    fallback_label: str = "",
) -> List[StepItem]:
    """Derive the step checklist from ordered stage events.

    ``events`` is a sequence of ``(stage, status, detail, error_code)`` tuples in
    the order they were received.  The step order comes from the pipeline stage
    table (single data source), so UI cannot drift from the pipeline.  A
    heartbeat-only task (no pipeline stage referenced) collapses into a single
    running step labelled ``fallback_label``; it never fabricates a percentage.

    Status derivation is last-write-wins per stage: ``started`` -> running,
    ``succeeded`` -> success, ``skipped`` -> skipped, ``failed`` -> failed,
    ``cancelled`` -> cancelled.  Steps never started stay pending.
    """
    if not events:
        return []

    from doc_tool.application.pipeline import (
        PIPELINE_STAGE_LABELS,
        PIPELINE_STAGE_ORDER,
        stage_percent_table,
    )

    percent = stage_percent_table()
    ordered = sorted(
        PIPELINE_STAGE_ORDER,
        key=lambda stage: percent.get(stage, (9999, 9999))[0],
    )
    involved = [stage for stage in ordered if any(ev[0] == stage for ev in events)]
    if not involved:
        # Heartbeat-only task: a single in-progress step, no fake percentage.
        return [
            StepItem(
                stage="",
                label=fallback_label or "处理中",
                status=STEP_STATUS_RUNNING,
            )
        ]

    # 全量管线步骤：未收到事件的阶段保持待处理（“未执行保持待处理”），
    # 使总体进度 = 完成数/全管线步骤数，阶段顺序单一来自 stage_percent_table。
    steps: Dict[str, StepItem] = {
        stage: StepItem(
            stage=stage,
            label=PIPELINE_STAGE_LABELS.get(stage, stage),
            status=STEP_STATUS_PENDING,
        )
        for stage in ordered
    }
    for ev in events:
        stage = ev[0]
        if stage not in steps:
            continue
        status = ev[1] if len(ev) > 1 else ""
        detail = ev[2] if len(ev) > 2 else ""
        error_code = ev[3] if len(ev) > 3 else None
        current = steps[stage]
        if status == "started":
            steps[stage] = StepItem(
                stage=stage, label=current.label, status=STEP_STATUS_RUNNING
            )
        elif status == "succeeded":
            steps[stage] = StepItem(
                stage=stage, label=current.label, status=STEP_STATUS_SUCCESS,
                detail=detail,
            )
        elif status == "skipped":
            steps[stage] = StepItem(
                stage=stage, label=current.label, status=STEP_STATUS_SKIPPED,
                detail=detail,
            )
        elif status == "failed":
            steps[stage] = StepItem(
                stage=stage, label=current.label, status=STEP_STATUS_FAILED,
                detail=detail, error_code=error_code,
            )
        elif status == "cancelled":
            steps[stage] = StepItem(
                stage=stage, label=current.label, status=STEP_STATUS_CANCELLED,
                detail=detail,
            )

    return [steps[stage] for stage in ordered]


def error_presentation(error_code: str, detail: str = "") -> tuple[str, str]:
    """Return user-facing reason and advice for a stable task error code.

    ``detail`` 是阶段事件给出的具体原因（已包含文件与行号），存在时
    优先展示它：旧行为不论真实原因是什么都只显示错误类的固定文案
    （如「Word 文档构建失败」），用户必须去日志里翻才知道改哪里。建议
    仍按错误类给出（它描述的是处理路径，不会因具体原因而变）。
    """
    from doc_tool.domain import errors

    classes = (
        errors.BuildError,
        errors.ValidationError,
        errors.WordNotAvailableError,
        errors.WordRefreshTimeoutError,
        errors.WordSaveFailedError,
        errors.ProjectLockBusyError,
        errors.IncompatibleSchemaError,
        errors.ProjectManifestError,
        errors.PathEscapeError,
        errors.ResourceNotFoundError,
        errors.CancelledError,
    )
    safe_detail = " ".join((detail or "").split())[:300]
    for error_type in classes:
        if error_type.code == error_code:
            return (
                safe_detail or error_type.user_message,
                error_type.suggested_action,
            )
    if error_code == "E9009":
        return "任务运行超时。", "请检查 Word 或系统状态后重试，并查看日志了解最后阶段。"
    reason = "任务未成功完成。"
    if safe_detail and error_code and error_code != "E9000":
        reason = safe_detail
    return reason, "请查看日志和技术详情；如问题持续，请联系维护人员。"


def format_stage_locations(events, limit: int = 20) -> Tuple[str, ...]:
    """从阶段事件的 ``metrics["locations"]`` 提取可读的出错位置行。

    构建前检查一次报全部问题，这里把它们渲染成
    ``文件:行号 说明 建议``，供失败卡片与技术详情直接列出。
    """
    lines: List[str] = []
    for event in events or ():
        if getattr(event, "status", "") not in ("failed", "cancelled"):
            continue
        metrics = getattr(event, "metrics", None) or {}
        for item in metrics.get("locations") or ():
            if not isinstance(item, dict):
                continue
            where = str(item.get("relPath") or item.get("path") or "")
            if item.get("line") is not None:
                where = "{0}:{1}".format(where, item["line"])
            parts = [where, str(item.get("message") or ""), str(item.get("hint") or "")]
            text = " ".join(part for part in parts if part).strip()
            if text:
                lines.append(text)
            if len(lines) >= limit:
                return tuple(lines)
    return tuple(lines)
