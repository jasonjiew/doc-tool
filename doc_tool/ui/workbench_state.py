# -*- coding: utf-8 -*-
"""Pure presentation state for the internal desktop workbench.

The objects in this module contain no tkinter widgets.  They translate existing
project, task, Word and filesystem facts into labels and action availability so
menu entries and first-screen buttons cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


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


def derive_workbench_state(
    project,
    *,
    running: bool,
    task_label: str = "",
    word_available: Optional[bool] = None,
    report_path: Optional[Path] = None,
) -> WorkbenchState:
    """Derive all high-frequency action states from existing application facts."""
    if project is None:
        disabled = ActionState(False, "请先打开项目")
        return WorkbenchState(
            view="empty",
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

    document_name = getattr(manifest, "documentName", "") if manifest else ""
    document_type = getattr(manifest, "documentType", "") if manifest else ""
    root_name = getattr(project_root, "name", "") if project_root else ""
    return WorkbenchState(
        view="workbench",
        project_name=document_name or root_name,
        project_path=str(project_root or ""),
        document_type=document_type,
        access_text="可写" if writable else "只读（版本不兼容）",
        readiness_text=readiness,
        status_tone=tone,
        reasons=tuple(reasons),
        actions=actions,
    )


def error_presentation(error_code: str, detail: str = "") -> tuple[str, str]:
    """Return safe user reason and advice for a stable task error code."""
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
    for error_type in classes:
        if error_type.code == error_code:
            return error_type.user_message, error_type.suggested_action
    if error_code == "E9009":
        return "任务运行超时。", "请检查 Word 或系统状态后重试，并查看日志了解最后阶段。"
    safe_detail = (detail or "").strip()
    reason = "任务未成功完成。"
    if safe_detail and error_code and error_code != "E9000":
        reason = safe_detail[:200]
    return reason, "请查看日志和技术详情；如问题持续，请联系维护人员。"
