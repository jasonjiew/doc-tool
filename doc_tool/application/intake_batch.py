# -*- coding: utf-8 -*-
"""导入文件批次：Word 一文件一项目、Markdown 多文件一份项目（CORE-D 4.3/4.4）。

- 串行执行、每文件独立事务：一份失败/待转换不影响其它文档；
- 项目名称冲突默认安全后缀；成功项立即可打开；
- 取消停止未开始项，已完成项目与用户输入/设置保留；
- 失败/待转换项可只重试失败部分；重复调用不会重复登记已成功项；
- Markdown 多文件按用户确认顺序建立**一份**项目，支持资源根与底模。

服务与既有 ``TaskRunner`` 兼容（``run_*`` 是普通可调用对象，可放进
``TaskSpec(target=...)``）；进度通过回调暴露，不在本模块内自建 UI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.intake_contract import (
    IntakePolicy,
    PlannedTarget,
    unique_directory,
)
from doc_tool.application.intake_entries import (
    ACTION_CREATE,
    ACTION_PENDING_CONVERT,
    KIND_MARKDOWN,
    detect_intake_kind,
    plan_target,
    run_intake,
)
from doc_tool.domain.cancellation import CancellationToken

#: 批次项状态。
ITEM_OK = "ok"
ITEM_FAILED = "failed"
ITEM_PENDING_CONVERT = "pending-convert"
ITEM_SKIPPED = "skipped"
ITEM_CANCELLED = "cancelled"


@dataclass
class BatchItemResult:
    """一个输入的处理结果。"""

    source: str
    kind: str = ""
    status: str = ITEM_FAILED
    project_root: str = ""
    message: str = ""
    error_code: str = ""
    warnings: List[str] = field(default_factory=list)
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.status == ITEM_OK

    @property
    def retryable(self) -> bool:
        return self.status in (ITEM_FAILED, ITEM_PENDING_CONVERT)

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source, "kind": self.kind, "status": self.status,
            "projectRoot": self.project_root, "message": self.message,
            "errorCode": self.error_code, "warnings": list(self.warnings),
            "attempts": self.attempts,
        }


@dataclass
class BatchResult:
    """批次结果（含取消状态与输入设置快照）。"""

    items: List[BatchItemResult] = field(default_factory=list)
    parent_dir: str = ""
    cancelled: bool = False
    startedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finishedAt: str = ""
    settings: Dict[str, object] = field(default_factory=dict)

    @property
    def succeeded(self) -> List[BatchItemResult]:
        return [item for item in self.items if item.status == ITEM_OK]

    @property
    def failed(self) -> List[BatchItemResult]:
        return [item for item in self.items if item.status == ITEM_FAILED]

    @property
    def pending(self) -> List[BatchItemResult]:
        return [item for item in self.items if item.status == ITEM_PENDING_CONVERT]

    @property
    def retryable(self) -> List[BatchItemResult]:
        return [item for item in self.items if item.retryable]

    def summary_lines(self) -> List[str]:
        lines = ["批次完成 {0} 份，失败 {1} 份，待转换 {2} 份".format(
            len(self.succeeded), len(self.failed), len(self.pending),
        )]
        for item in self.succeeded:
            lines.append("· 可打开：{0}".format(Path(item.project_root).name if item.project_root else item.source))
        for item in self.failed:
            lines.append("· 失败：{0}（{1}）".format(Path(item.source).name, item.message[:80]))
        for item in self.pending:
            lines.append("· 待转换：{0}（{1}）".format(Path(item.source).name, item.message[:80]))
        if self.cancelled:
            lines.append("已取消：未开始项未执行，已完成项目保留")
        for item in self.items:
            for warning in item.warnings[:1]:
                lines.append("提醒：{0}".format(warning))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "parentDir": self.parent_dir,
            "cancelled": self.cancelled,
            "startedAt": self.startedAt,
            "finishedAt": self.finishedAt,
            "settings": dict(self.settings),
            "items": [item.to_dict() for item in self.items],
            "succeeded": [item.project_root for item in self.succeeded],
            "failed": [item.source for item in self.failed],
            "pending": [item.source for item in self.pending],
        }


def _cancelled(cancel_token) -> bool:
    """兼容 CancellationToken 的属性/方法两种暴露方式。"""
    value = getattr(cancel_token, "is_cancelled", False)
    return bool(value() if callable(value) else value)


def _snapshot_settings(
    parent_dir, policy, document_no, document_version, entry: Dict[str, object]
) -> Dict[str, object]:
    """批次输入/设置快照：取消或重试后无需重新选择。"""
    return {
        "parentDir": str(parent_dir),
        "policy": (policy or IntakePolicy.normal()).mode,
        "documentNo": document_no,
        "documentVersion": document_version,
        "entry": dict(entry or {}),
    }


def run_word_batch(
    sources: Sequence[object],
    *,
    parent_dir,
    policy: Optional[IntakePolicy] = None,
    document_no: str = "",
    document_version: str = "1.0",
    cancel_token: Optional[CancellationToken] = None,
    progress: Optional[Callable[[int, int, BatchItemResult], None]] = None,
    on_item: Optional[Callable[[BatchItemResult], None]] = None,
    word_available: Optional[bool] = None,
) -> BatchResult:
    """串行接管多份 Word：一文件一项目，失败/待转换项单独可重试。"""
    effective_policy = policy or IntakePolicy.normal()
    result = BatchResult(
        parent_dir=str(parent_dir),
        settings=_snapshot_settings(parent_dir, effective_policy, document_no, document_version, {}),
    )
    files = [Path(item) for item in sources]
    total = len(files)
    for index, source in enumerate(files, start=1):
        if cancel_token is not None and _cancelled(cancel_token):
            result.cancelled = True
            remaining = files[index - 1:]
            for item in remaining:
                record = BatchItemResult(
                    source=str(item), kind=detect_intake_kind(item),
                    status=ITEM_CANCELLED, message="批次已取消，未开始处理",
                )
                result.items.append(record)
            break
        item = _run_one_word(
            source, parent_dir=parent_dir, policy=effective_policy,
            document_no=document_no, document_version=document_version,
            cancel_token=cancel_token, word_available=word_available,
        )
        result.items.append(item)
        if progress is not None:
            progress(index, total, item)
        if on_item is not None:
            on_item(item)
    result.finishedAt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result


def _run_one_word(
    source: Path,
    *,
    parent_dir,
    policy: IntakePolicy,
    document_no: str,
    document_version: str,
    cancel_token: Optional[CancellationToken],
    word_available: Optional[bool],
) -> BatchItemResult:
    kind = detect_intake_kind(source)
    if kind not in ("docx", "doc"):
        return BatchItemResult(
            source=str(source), kind=kind, status=ITEM_SKIPPED,
            message="Word 批次只处理 .docx/.doc 输入",
        )
    outcome = run_intake(
        source, parent_dir=parent_dir, policy=policy, document_no=document_no,
        document_version=document_version, cancel_token=cancel_token,
        word_available=word_available,
    )
    if outcome.ok and outcome.project_root is not None:
        return BatchItemResult(
            source=str(source), kind=kind, status=ITEM_OK,
            project_root=str(outcome.project_root),
            warnings=list(outcome.warnings)[:5],
        )
    if outcome.pending:
        return BatchItemResult(
            source=str(source), kind=kind, status=ITEM_PENDING_CONVERT,
            message=outcome.pending[0], error_code=outcome.error_code,
            warnings=list(outcome.warnings)[:5],
        )
    return BatchItemResult(
        source=str(source), kind=kind, status=ITEM_FAILED,
        message="；".join(outcome.errors) or "导入未完成",
        error_code=outcome.error_code, warnings=list(outcome.warnings)[:5],
    )


def retry_word_batch(
    previous: BatchResult,
    *,
    policy: Optional[IntakePolicy] = None,
    cancel_token: Optional[CancellationToken] = None,
    progress: Optional[Callable[[int, int, BatchItemResult], None]] = None,
) -> BatchResult:
    """只重试上一轮的失败/待转换项，不重复登记已成功项目。"""
    retry_sources = [item.source for item in previous.retryable]
    settings = dict(previous.settings or {})
    effective_policy = policy or IntakePolicy(
        mode=str(settings.get("policy") or "normal"),
    )
    result = run_word_batch(
        retry_sources,
        parent_dir=settings.get("parentDir") or previous.parent_dir,
        policy=effective_policy,
        document_no=str(settings.get("documentNo") or ""),
        document_version=str(settings.get("documentVersion") or "1.0"),
        cancel_token=cancel_token,
        progress=progress,
    )
    # 保留上一轮成功项，形成完整批次视图
    merged = list(previous.succeeded) + result.items
    result.items = merged
    for item in result.items:
        if item.status in (ITEM_FAILED, ITEM_PENDING_CONVERT):
            item.attempts = 2
    return result


def _merge_batch_into(previous: BatchResult, result: BatchResult) -> BatchResult:
    """把一次补做的结果合并回原批次视图（保留成功项与取消事实）。"""
    ordered: List[BatchItemResult] = []
    replaced = {item.source: item for item in result.items}
    for item in previous.items:
        ordered.append(replaced.pop(item.source, item))
    ordered.extend(replaced.values())
    result.items = ordered
    result.cancelled = bool(previous.cancelled or result.cancelled)
    if not result.settings:
        result.settings = dict(previous.settings or {})
    return result


def retry_selected_word_items(
    previous: BatchResult,
    sources: Sequence[object],
    *,
    policy: Optional[IntakePolicy] = None,
    cancel_token: Optional[CancellationToken] = None,
    progress: Optional[Callable[[int, int, BatchItemResult], None]] = None,
) -> BatchResult:
    """只补做**所选**失败/待转换/未开始项，保留已完成项目与输入设置。

    与 :func:`retry_word_batch` 的差别：这里允许用户只挑其中几项接续（例如
    只重试一个被占用的文件），不会重复创建已成功的项目，也不会丢掉其余未选项。
    """
    wanted = [str(item) for item in sources]
    selected = [
        item for item in previous.items
        if item.source in wanted and item.status != ITEM_OK
    ]
    settings = dict(previous.settings or {})
    effective_policy = policy or IntakePolicy(
        mode=str(settings.get("policy") or "normal"),
    )
    if not selected:
        merged = BatchResult(
            items=list(previous.items),
            parent_dir=str(previous.parent_dir or settings.get("parentDir") or ""),
            cancelled=bool(previous.cancelled),
            settings=settings,
        )
        merged.finishedAt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return merged
    result = run_word_batch(
        [item.source for item in selected],
        parent_dir=settings.get("parentDir") or previous.parent_dir,
        policy=effective_policy,
        document_no=str(settings.get("documentNo") or ""),
        document_version=str(settings.get("documentVersion") or "1.0"),
        cancel_token=cancel_token,
        progress=progress,
    )
    for item in result.items:
        if item.status in (ITEM_FAILED, ITEM_PENDING_CONVERT, ITEM_CANCELLED):
            item.attempts = 2
    return _merge_batch_into(previous, result)


def run_markdown_batch(
    sources: Sequence[object],
    *,
    parent_dir,
    asset_roots: Sequence[object] = (),
    template_path: Optional[object] = None,
    document_name: str = "",
    document_no: str = "",
    document_version: str = "1.0",
    cancel_token: Optional[CancellationToken] = None,
) -> BatchResult:
    """多份 Markdown 按确认顺序建立**一份**项目（顺序即章节顺序）。"""
    files = [Path(item) for item in sources]
    result = BatchResult(
        parent_dir=str(parent_dir),
        settings=_snapshot_settings(parent_dir, None, document_no, document_version, {
            "assetRoots": [str(item) for item in asset_roots],
            "template": str(template_path or ""),
        }),
    )
    if not files:
        result.finishedAt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return result
    missing = [str(item) for item in files if not Path(item).is_file()]
    usable = [item for item in files if Path(item).is_file()]
    for item in missing:
        result.items.append(BatchItemResult(
            source=item, kind=KIND_MARKDOWN, status=ITEM_SKIPPED,
            message="文件不存在，已跳过（其它文件继续）",
        ))
    if not usable:
        result.finishedAt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return result
    if cancel_token is not None and _cancelled(cancel_token):
        result.cancelled = True
        result.finishedAt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return result
    outcome = run_intake(
        usable[0], parent_dir=parent_dir, markdown_sources=usable,
        asset_roots=asset_roots, template_path=template_path,
        target_name=document_name, document_no=document_no,
        document_version=document_version, cancel_token=cancel_token,
    )
    if outcome.ok and outcome.project_root is not None:
        result.items.append(BatchItemResult(
            source=str(usable[0]), kind=KIND_MARKDOWN, status=ITEM_OK,
            project_root=str(outcome.project_root),
            message="已合并 {0} 份 Markdown 为一份项目".format(len(usable)),
            warnings=list(outcome.warnings)[:5],
        ))
    else:
        result.items.append(BatchItemResult(
            source=str(usable[0]), kind=KIND_MARKDOWN, status=ITEM_FAILED,
            message="；".join(outcome.errors) or "Markdown 建项未完成",
            error_code=outcome.error_code, warnings=list(outcome.warnings)[:5],
        ))
    result.finishedAt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result


__all__ = [
    "ITEM_OK", "ITEM_FAILED", "ITEM_PENDING_CONVERT", "ITEM_SKIPPED", "ITEM_CANCELLED",
    "BatchItemResult", "BatchResult", "run_word_batch", "retry_word_batch",
    "retry_selected_word_items", "run_markdown_batch",
]