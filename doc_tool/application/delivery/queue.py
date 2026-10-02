# -*- coding: utf-8 -*-
"""持久批次队列（V3.2 32-B）。

一个用户级、路径可注入的批次 job store（独立 schema 1，本地 JSON）：

- ``enqueue`` 登记项目/变体/范围/格式。同项目+变体+范围+格式的**未完成项复用**
  （重复点击不重复登记），已完成项默认跳过，同 ``requestId`` 幂等。
- ``run_pending`` / ``resume`` 串行调用既有统一出稿服务
  （:func:`doc_tool.application.project_export.run_project_export`），逐项写回
  状态、产物路径与 attempt 历史；单成员失败不停止其它合法成员。
- Word 忙或不可用时该项转 ``waiting-refresh``（可读 DOCX 保留），其它离线成员继续；
  不操作用户自己的 Word 会话。
- ``cancel`` 结束本任务执行并保留已完成成果；``retry_unfinished`` 只补
  失败/待刷新/待转换项，并复用该项原轮快照（没有快照时按当轮重新捕获）。
- 启动时把未知 ``running`` 视为 ``interrupted``；store 损坏时隔离坏文件后继续可用。

本模块不重新定义正式成功事实：逐项状态来自统一出稿的 ``FormatResult``，
正式级别仍只由 :mod:`doc_tool.domain.output_state` 判定。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.writer import atomic_write
from doc_tool.application.intake_contract import (
    FORMAT_DOCX,
    SOURCE_MODE_SAVED,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING_CONVERT,
    STATUS_PENDING_REFRESH,
    STATUS_SKIPPED,
    ExportRequest,
    ExportScope,
    FormatResult,
    normalize_formats,
    utc_now_iso,
)
from doc_tool.application.project_export import ExportReport

#: job store 文件名与 schema（独立于项目 schema，不升级项目模式版本）。
STORE_NAME = "delivery-queue.json"
STORE_SCHEMA_VERSION = 1

#: 逐项状态（design.md D1）。
JOB_QUEUED = "queued"
JOB_PREPARING = "preparing"
JOB_RUNNING = "running"
JOB_WAITING_REFRESH = "waiting-refresh"
JOB_COMPLETED = "completed"
JOB_COMPLETED_WITH_WARNINGS = "completed-with-warnings"
JOB_PARTIAL = "partial"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
JOB_INTERRUPTED = "interrupted"

JOB_STATUSES = (
    JOB_QUEUED, JOB_PREPARING, JOB_RUNNING, JOB_WAITING_REFRESH, JOB_COMPLETED,
    JOB_COMPLETED_WITH_WARNINGS, JOB_PARTIAL, JOB_FAILED, JOB_CANCELLED, JOB_INTERRUPTED,
)

#: 已完成（默认跳过，不重复登记）。
COMPLETED_JOB_STATUSES = (JOB_COMPLETED, JOB_COMPLETED_WITH_WARNINGS)
#: 未落定论：``run_pending`` 继续执行的范围。
PENDING_JOB_STATUSES = (JOB_QUEUED, JOB_PREPARING, JOB_INTERRUPTED)
#: 未完成：``retry_unfinished`` 只补失败/待刷新/待转换项。
RETRYABLE_JOB_STATUSES = (
    JOB_QUEUED, JOB_PREPARING, JOB_INTERRUPTED, JOB_FAILED, JOB_PARTIAL, JOB_WAITING_REFRESH,
)

JOB_STATUS_LABELS = {
    JOB_QUEUED: "待执行",
    JOB_PREPARING: "准备中",
    JOB_RUNNING: "执行中",
    JOB_WAITING_REFRESH: "待刷新",
    JOB_COMPLETED: "已完成",
    JOB_COMPLETED_WITH_WARNINGS: "已完成（有提醒）",
    JOB_PARTIAL: "部分完成",
    JOB_FAILED: "失败",
    JOB_CANCELLED: "已取消",
    JOB_INTERRUPTED: "已中断",
}

#: 提醒：默认自动重试限幂等临时故障一次（2.4）。
AUTO_RETRY_LIMIT = 1


def job_status_label(status: str) -> str:
    return JOB_STATUS_LABELS.get(status, status or "未知")


def _default_store_path() -> Path:
    """默认用户级 store 位置（可被参数覆盖，便于测试与自定义）。"""
    try:
        from doc_tool.application.project_service import _config_dir

        return Path(_config_dir()) / "delivery" / STORE_NAME
    except Exception:  # noqa: BLE001 - 配置目录不可用时退回用户主目录
        return Path.home() / ".doctool" / "delivery" / STORE_NAME


def _norm_key(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    try:
        return os.path.normcase(str(Path(text).resolve()))
    except OSError:  # pragma: no cover - 极端路径不可解析时退回原文
        return os.path.normcase(text)


def _default_word_probe() -> Tuple[bool, str]:
    """默认 Word 探测：复用既有可用性检查（不启动用户自己的 Word 会话之外的操作）。"""
    try:
        from doc_tool.application.word_check import check_word_available

        report = check_word_available()
        if report.available:
            return True, ""
        return False, "；".join(report.reasons) or "未检测到可用的 Microsoft Word"
    except Exception as exc:  # noqa: BLE001 - 探测失败按不可用兜底
        return False, "Word 探测失败：{0}".format(exc)


def _report_from_dict(data: Optional[Dict[str, object]]) -> Optional[ExportReport]:
    """把落盘的报告字典还原为 :class:`ExportReport`（复用统一出稿的既有模型）。"""
    if not isinstance(data, dict) or not data:
        return None
    return ExportReport(
        roundId=str(data.get("roundId") or ""),
        captureId=str(data.get("captureId") or ""),
        createdAt=str(data.get("createdAt") or utc_now_iso()),
        scope=ExportScope.from_dict(data.get("scope")),
        sourceMode=str(data.get("sourceMode") or SOURCE_MODE_SAVED),
        destination=str(data.get("destination") or ""),
        outputName=str(data.get("outputName") or ""),
        variantId=str(data.get("variantId") or ""),
        variantApplied=bool(data.get("variantApplied", False)),
        projectRoot=str(data.get("projectRoot") or ""),
        strict=bool(data.get("strict", False)),
        documentType=str(data.get("documentType") or "general"),
        documentVersion=str(data.get("documentVersion") or ""),
        results=[FormatResult.from_dict(item) for item in data.get("results") or []],
        snapshotWorkDir=str(data.get("snapshotWorkDir") or ""),
        docxPath=str(data.get("docxPath") or ""),
        indexPath=str(data.get("indexPath") or ""),
        warnings=[str(item) for item in data.get("warnings") or []],
        unsavedChapters=[str(item) for item in data.get("unsavedChapters") or []],
        omittedChapters=[str(item) for item in data.get("omittedChapters") or []],
        sourceUpdated=bool(data.get("sourceUpdated", False)),
        readonlyProject=bool(data.get("readonlyProject", False)),
    )

def _new_id(prefix: str) -> str:
    return "{0}-{1}".format(prefix, uuid.uuid4().hex[:10])


@dataclass
class BatchJob:
    """批次中的一项任务：项目/变体 + 范围 + 目标格式 + 轮次设置。"""

    jobId: str = field(default_factory=lambda: _new_id("j"))
    batchId: str = ""
    requestId: str = ""
    projectRoot: str = ""
    variantId: str = ""
    formats: List[str] = field(default_factory=lambda: [FORMAT_DOCX])
    scope: Dict[str, object] = field(
        default_factory=lambda: {"kind": "project", "chapters": [], "current": ""}
    )
    sourceMode: str = SOURCE_MODE_SAVED
    destination: str = ""
    outputName: str = ""
    strict: bool = False
    refresh: bool = True
    status: str = JOB_QUEUED
    attempts: List[Dict[str, object]] = field(default_factory=list)
    report: Dict[str, object] = field(default_factory=dict)
    error: str = ""
    errorCode: str = ""
    waitingReason: str = ""
    notes: List[str] = field(default_factory=list)
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    finishedAt: str = ""

    # --- 查询 ---

    def scope_obj(self) -> ExportScope:
        return ExportScope.from_dict(self.scope)

    def dedupe_key(self) -> str:
        """去重键：项目 + 变体 + 范围 + 格式（重复点击复用未完成项）。"""
        scope = self.scope_obj()
        return "|".join((
            _norm_key(self.projectRoot),
            self.variantId or "",
            scope.kind,
            scope.current or "",
            ",".join(sorted(scope.chapters or [])),
            ",".join(sorted(normalize_formats(self.formats))),
        ))

    def report_obj(self) -> Optional[ExportReport]:
        return _report_from_dict(self.report)

    def results(self) -> List[FormatResult]:
        report = self.report_obj()
        return list(report.results) if report is not None else []

    def usable_results(self) -> List[FormatResult]:
        return [item for item in self.results() if item.usable]

    def pending_formats(self) -> List[str]:
        """本项还需补的格式：失败/待转换/待刷新；无结果时按登记格式全量。"""
        report = self.report_obj()
        if report is None:
            return list(normalize_formats(self.formats))
        pending: List[str] = []
        for item in report.results:
            if item.status in (STATUS_FAILED, STATUS_PENDING_CONVERT, STATUS_PENDING_REFRESH):
                if item.format not in pending:
                    pending.append(item.format)
        return pending

    @property
    def attemptCount(self) -> int:
        return len(self.attempts)

    @property
    def docxPath(self) -> str:
        report = self.report_obj()
        if report is None:
            return ""
        if report.docxPath and Path(report.docxPath).is_file():
            return report.docxPath
        for item in report.results:
            if item.format == FORMAT_DOCX and item.path and Path(item.path).is_file():
                return item.path
        return report.docxPath or ""

    @property
    def indexPath(self) -> str:
        report = self.report_obj()
        return report.indexPath if report is not None else ""

    @property
    def captureId(self) -> str:
        report = self.report_obj()
        return report.captureId if report is not None else ""

    @property
    def snapshotWorkDir(self) -> str:
        report = self.report_obj()
        return report.snapshotWorkDir if report is not None else ""

    # --- 状态 ---

    def is_completed(self) -> bool:
        return self.status in COMPLETED_JOB_STATUSES

    def is_pending(self) -> bool:
        return self.status in PENDING_JOB_STATUSES

    def is_retryable(self) -> bool:
        return self.status in RETRYABLE_JOB_STATUSES

    def request(self) -> ExportRequest:
        return ExportRequest(
            project_root=self.projectRoot,
            formats=list(normalize_formats(self.formats) or [FORMAT_DOCX]),
            scope=self.scope_obj(),
            source_mode=self.sourceMode,
            destination=self.destination,
            output_name=self.outputName,
            refresh=bool(self.refresh),
            strict=bool(self.strict),
            variant_id=str(self.variantId or ""),
        )

    def summary_line(self) -> str:
        results = self.results()
        usable = [item for item in results if item.usable]
        member = Path(self.projectRoot).name or self.projectRoot or "（未指定项目）"
        variant = "｜变体 {0}".format(self.variantId) if self.variantId else ""
        detail = ""
        if self.waitingReason:
            detail = "（{0}）".format(self.waitingReason)
        elif self.error:
            detail = "（{0}）".format(self.error)
        total = len(results) or len(self.formats)
        return "[{0}] {1}{2}｜{3}｜{4}/{5} 个格式可用{6}".format(
            job_status_label(self.status), member, variant,
            "、".join(self.formats), len(usable), total, detail,
        )

    # --- 序列化 ---

    def to_dict(self) -> Dict[str, object]:
        return {
            "jobId": self.jobId,
            "batchId": self.batchId,
            "requestId": self.requestId,
            "projectRoot": self.projectRoot,
            "variantId": self.variantId,
            "formats": list(self.formats),
            "scope": dict(self.scope),
            "sourceMode": self.sourceMode,
            "destination": self.destination,
            "outputName": self.outputName,
            "strict": bool(self.strict),
            "refresh": bool(self.refresh),
            "status": self.status,
            "statusLabel": job_status_label(self.status),
            "attempts": [dict(item) for item in self.attempts],
            "attemptCount": len(self.attempts),
            "report": dict(self.report),
            "results": [item.to_dict() for item in self.results()],
            "usableFormats": [item.format for item in self.usable_results()],
            "pendingFormats": self.pending_formats(),
            "docxPath": self.docxPath,
            "indexPath": self.indexPath,
            "captureId": self.captureId,
            "snapshotWorkDir": self.snapshotWorkDir,
            "error": self.error,
            "errorCode": self.errorCode,
            "waitingReason": self.waitingReason,
            "notes": list(self.notes),
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
            "finishedAt": self.finishedAt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "BatchJob":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        payload = {k: v for k, v in (data or {}).items() if k in known}
        payload["formats"] = normalize_formats(payload.get("formats") or [FORMAT_DOCX])
        if not isinstance(payload.get("scope"), dict):
            payload["scope"] = {"kind": "project", "chapters": [], "current": ""}
        for key in ("attempts", "notes"):
            value = payload.get(key)
            payload[key] = value if isinstance(value, list) else []
        if not isinstance(payload.get("report"), dict):
            payload["report"] = {}
        return cls(**payload)


@dataclass
class EnqueueResult:
    """入队结果：是否复用已有登记、是否因已完成跳过。"""

    job: BatchJob
    reused: bool = False
    skipped: bool = False
    reason: str = ""

    @property
    def jobId(self) -> str:
        return self.job.jobId

    def summary_line(self) -> str:
        head = "已入队" if not self.reused else ("已完成，跳过" if self.skipped else "复用未完成项")
        return "{0}：{1}{2}".format(
            head, self.job.summary_line(), "（{0}）".format(self.reason) if self.reason else "",
        )

class DeliveryQueue:
    """本地持久批次队列（schema 1）。

    参数：
        store_path: job store 路径；默认用户配置目录 ``delivery/delivery-queue.json``。
        runner: 出稿执行服务，默认 :func:`run_project_export`；测试可注入替身。
        word_probe: ``() -> (available, reason)``，默认复用既有 Word 可用性检查。
    """

    def __init__(
        self,
        store_path=None,
        *,
        batch_id: str = "",
        runner: Optional[Callable[..., object]] = None,
        word_probe: Optional[Callable[[], Tuple[bool, str]]] = None,
    ) -> None:
        self.store_path = Path(store_path) if store_path else _default_store_path()
        self.batchId = batch_id or _new_id("batch")
        self.createdAt = utc_now_iso()
        self.jobs: List[BatchJob] = []
        self.warnings: List[str] = []
        self._runner = runner
        self._word_probe = word_probe
        self.load()

    # --- 持久化 ---

    def load(self) -> "DeliveryQueue":
        """读取 store：新实例/新进程即可看到既有结果。"""
        self.jobs = []
        self.warnings = []
        path = self.store_path
        if not path.is_file():
            return self
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._quarantine_store(exc)
            return self
        if not isinstance(data, dict) or data.get("schemaVersion") != STORE_SCHEMA_VERSION:
            self._quarantine_store(ValueError("批次队列 schema 不兼容或结构非法"))
            return self
        self.batchId = str(data.get("batchId") or self.batchId)
        self.createdAt = str(data.get("createdAt") or self.createdAt)
        for item in data.get("jobs") or []:
            if isinstance(item, dict):
                self.jobs.append(BatchJob.from_dict(item))
        if self._recover_interrupted():
            self.save()
        return self

    def _quarantine_store(self, exc: object) -> None:
        """坏 store 不阻断使用：隔离坏文件并留下提醒，已生成结果不受影响。"""
        target = self.store_path.with_name(self.store_path.name + ".corrupt")
        moved = False
        try:
            if target.exists():
                target.unlink()
            os.replace(str(self.store_path), str(target))
            moved = True
        except OSError:
            import shutil

            try:
                shutil.move(str(self.store_path), str(target))
                moved = True
            except OSError:
                moved = False
        self.warnings.append("批次队列文件损坏，已隔离{0}：{1}".format(
            "为 " + target.name if moved else "（原文件保留）", exc,
        ))

    def _recover_interrupted(self) -> bool:
        """启动核对：未知 running/preparing 视为 interrupted，不无条件重复登记。"""
        changed = False
        for job in self.jobs:
            if job.status in (JOB_RUNNING, JOB_PREPARING):
                job.status = JOB_INTERRUPTED
                job.waitingReason = "程序中断：上次执行未落定论，可继续未完成范围"
                job.notes.append("启动核对：running → interrupted（已完成结果保持可用）")
                job.updatedAt = utc_now_iso()
                changed = True
        return changed

    def save(self) -> Path:
        payload = {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "batchId": self.batchId,
            "createdAt": self.createdAt,
            "updatedAt": utc_now_iso(),
            "jobs": [job.to_dict() for job in self.jobs],
        }
        atomic_write(self.store_path, json.dumps(payload, ensure_ascii=False, indent=2))
        return self.store_path

    # --- 登记 ---

    def job(self, job_id: str) -> Optional[BatchJob]:
        for item in self.jobs:
            if item.jobId == job_id:
                return item
        return None

    def enqueue(
        self,
        *,
        project_root,
        formats,
        scope=None,
        destination="",
        output_name="",
        strict: bool = False,
        refresh: bool = True,
        variant_id: str = "",
        source_mode: str = SOURCE_MODE_SAVED,
        request_id: str = "",
    ) -> EnqueueResult:
        """登记一项任务；不重复登记同项目/变体/范围/格式的未完成项。"""
        normalized = normalize_formats(formats) or [FORMAT_DOCX]
        scope_obj = scope if isinstance(scope, ExportScope) else ExportScope.from_dict(scope)
        if request_id:
            for job in self.jobs:
                if job.requestId and job.requestId == request_id:
                    return EnqueueResult(
                        job=job, reused=True, skipped=job.is_completed(),
                        reason="同一次提交（requestId 去重），不重复登记",
                    )
        candidate = BatchJob(
            batchId=self.batchId,
            requestId=str(request_id or ""),
            projectRoot=str(project_root or ""),
            variantId=str(variant_id or ""),
            formats=normalized,
            scope=scope_obj.to_dict(),
            sourceMode=str(source_mode or SOURCE_MODE_SAVED),
            destination=str(destination or ""),
            outputName=str(output_name or ""),
            strict=bool(strict),
            refresh=bool(refresh),
        )
        key = candidate.dedupe_key()
        for job in self.jobs:
            if job.dedupe_key() != key:
                continue
            if job.is_completed():
                return EnqueueResult(
                    job=job, reused=True, skipped=True,
                    reason="已完成成员默认跳过；如需补齐请选择「重试未完成项」",
                )
            return EnqueueResult(
                job=job, reused=True,
                reason="同项目/范围/格式的未完成项已存在，复用原登记（不重复登记）",
            )
        self.jobs.append(candidate)
        self.save()
        return EnqueueResult(job=candidate)

    def cancel(self, *, job_ids: Optional[Sequence[str]] = None, reason: str = "已取消：已完成项保留") -> int:
        """取消未完成任务；已完成成果保持可用，不被撤销。"""
        wanted = set(job_ids) if job_ids else None
        count = 0
        for job in self.jobs:
            if wanted is not None and job.jobId not in wanted:
                continue
            if job.is_completed():
                continue
            job.status = JOB_CANCELLED
            job.waitingReason = reason
            job.notes.append(reason)
            job.updatedAt = utc_now_iso()
            count += 1
        if count:
            self.save()
        return count
    # --- 执行 ---

    def run_pending(
        self,
        *,
        skip_word_refresh: bool = False,
        cancel_token=None,
        progress=None,
        only_job_ids: Optional[Sequence[str]] = None,
    ) -> List[BatchJob]:
        """串行执行未落定论的项（queued/interrupted）；单项失败不停止其它项。"""
        allowed = set(only_job_ids) if only_job_ids else None
        targets = [
            job for job in self.jobs
            if job.is_pending() and (allowed is None or job.jobId in allowed)
        ]
        return self._run_jobs(
            targets, skip_word_refresh=skip_word_refresh,
            cancel_token=cancel_token, progress=progress, retry=False,
        )

    def resume(self, **kwargs) -> List[BatchJob]:
        """重启后继续：先读同一 store，再只处理未完成范围。"""
        self.load()
        return self.run_pending(**kwargs)

    def retry_unfinished(
        self,
        *,
        skip_word_refresh: bool = False,
        cancel_token=None,
        progress=None,
        only_job_ids: Optional[Sequence[str]] = None,
    ) -> List[BatchJob]:
        """只补失败/待刷新/待转换项；复用该项原轮快照，不重走全部任务。"""
        allowed = set(only_job_ids) if only_job_ids else None
        targets = [
            job for job in self.jobs
            if job.is_retryable() and (allowed is None or job.jobId in allowed)
        ]
        return self._run_jobs(
            targets, skip_word_refresh=skip_word_refresh,
            cancel_token=cancel_token, progress=progress, retry=True,
        )

    def _run_jobs(
        self,
        jobs: Sequence[BatchJob],
        *,
        skip_word_refresh: bool,
        cancel_token,
        progress,
        retry: bool,
    ) -> List[BatchJob]:
        if not jobs:
            return []
        runner = self._runner_fn()
        outcomes: List[BatchJob] = []
        for job in jobs:
            if cancel_token is not None and getattr(cancel_token, "is_cancelled", False):
                job.status = JOB_CANCELLED
                job.waitingReason = "已取消：本任务停止执行，已完成项保留"
                job.updatedAt = utc_now_iso()
                outcomes.append(job)
                continue

            prior = job.report_obj() if retry else None
            pending = job.pending_formats()
            if retry and prior is not None and not pending:
                job.updatedAt = utc_now_iso()
                outcomes.append(job)
                continue

            job.status = JOB_RUNNING
            job.error = ""
            job.errorCode = ""
            job.waitingReason = ""
            word_slot_acquired = False
            attempt: Dict[str, object] = {
                "attemptId": _new_id("a"),
                "startedAt": utc_now_iso(),
                "status": JOB_RUNNING,
                "formats": list(pending if (retry and prior is not None) else job.formats),
            }
            job.attempts.append(attempt)
            job.updatedAt = utc_now_iso()
            self.save()
            self._notify(progress, job, "started", "")

            effective_skip = bool(skip_word_refresh)
            word_applied = True
            reason = ""
            if job.refresh and skip_word_refresh:
                # 调用方（CLI/诊断）明确要求跳过 Word：本项按待刷新记录。
                word_applied = False
                reason = "按要求跳过 Word 刷新（诊断构建）：本项转待刷新，可稍后补刷新"
            elif job.refresh:
                available, why = self._word_available()
                if not available:
                    # Word 忙/不可用：本项转待刷新（可读 DOCX 仍保留），其它成员继续。
                    effective_skip = True
                    word_applied = False
                    reason = "Word 忙或不可用：{0}；本项转待刷新，其它成员继续".format(
                        why or "未检测到可用的 Microsoft Word"
                    )
                else:
                    # 真正要驱动 Word：先登记跨进程占用标记（V3.2 2.3）。
                    acquired, why_busy = self._acquire_word_slot(job)
                    if not acquired:
                        effective_skip = True
                        word_applied = False
                        reason = (
                            "本应用其它进程正在使用 Word：{0}；本项转待刷新，可稍后补刷新"
                        ).format(why_busy or "占用标记存在")
                    else:
                        word_slot_acquired = True

            kwargs: Dict[str, object] = {
                "buffer_texts": None,
                "cancel_token": cancel_token,
                "skip_word_refresh": effective_skip,
                "progress": self._progress_bridge(progress, job),
            }
            if prior is not None and pending:
                kwargs["prior"] = prior
                kwargs["only_formats"] = pending

            try:
                produced, run_error, auto_retries = self._call_runner_with_retry(
                    runner, job, kwargs, progress=progress,
                )
            finally:
                if word_slot_acquired:
                    self._release_word_slot()
                    word_slot_acquired = False
            if auto_retries:
                attempt["autoRetries"] = auto_retries
                attempt["retryReason"] = "临时故障自动重试一次"
            if run_error is not None:
                exc = run_error
                job.status = JOB_FAILED
                job.error = str(exc) or type(exc).__name__
                job.errorCode = str(getattr(exc, "code", "") or "")
                attempt.update({
                    "status": JOB_FAILED, "finishedAt": utc_now_iso(), "error": job.error,
                })
                job.updatedAt = utc_now_iso()
                job.finishedAt = job.updatedAt
                self.save()
                self._notify(progress, job, "failed", job.error)
                outcomes.append(job)
                continue

            payload = produced.to_dict() if hasattr(produced, "to_dict") else dict(produced or {})
            job.report = payload
            cancelled = bool(cancel_token is not None and getattr(cancel_token, "is_cancelled", False))
            job.status = _classify_job(
                job, word_applied=word_applied,
                refresh_wanted=bool(job.refresh), cancelled=cancelled,
            )
            if reason:
                if job.status == JOB_WAITING_REFRESH:
                    job.waitingReason = reason
                else:
                    job.notes.append(reason)
            if cancelled:
                job.notes.append("取消：本项停止执行，已完成结果保留")
            if job.status in (JOB_FAILED, JOB_PARTIAL):
                failures = [
                    item for item in job.results()
                    if item.status in (STATUS_FAILED, STATUS_PENDING_CONVERT, STATUS_SKIPPED)
                ]
                if failures:
                    job.error = "；".join(
                        "{0}：{1}".format(item.format, item.message or item.status)
                        for item in failures[:3]
                    )
                    job.errorCode = next(
                        (item.error_code for item in failures if item.error_code), "",
                    )
                elif job.status == JOB_FAILED:
                    job.error = job.error or "本轮没有可用产物"
            attempt.update({
                "status": job.status,
                "finishedAt": utc_now_iso(),
                "usableFormats": [item.format for item in job.usable_results()],
                "docxPath": job.docxPath,
                "indexPath": job.indexPath,
            })
            job.updatedAt = utc_now_iso()
            job.finishedAt = job.updatedAt
            self.save()
            self._notify(progress, job, job.status, job.waitingReason or job.error)
            outcomes.append(job)
        return outcomes

    # --- 执行依赖 ---

    def _runner_fn(self):
        if self._runner is not None:
            return self._runner
        from doc_tool.application.project_export import run_project_export

        return run_project_export

    def _word_available(self) -> Tuple[bool, str]:
        """Word 可用性：显式注入的探测优先；否则先看跨进程占用标记，再探测本机 Word。"""
        probe = self._word_probe
        if probe is None:
            try:
                from doc_tool.application.delivery.word_busy import status as _busy_status

                busy = _busy_status()
                if busy.busy:
                    return False, busy.reason
            except Exception:  # noqa: BLE001 - 标记不可读时退回本机探测
                pass
            probe = _default_word_probe
        try:
            available, reason = probe()
        except Exception as exc:  # noqa: BLE001 - 探测失败按不可用兜底
            return False, "Word 探测失败：{0}".format(exc)
        return bool(available), str(reason or "")

    def _acquire_word_slot(self, job) -> Tuple[bool, str]:
        """登记本应用跨进程 Word 占用（失败不抛，交给调用方转待刷新）。"""
        try:
            from doc_tool.application.delivery import word_busy

            return word_busy.acquire("delivery:{0}".format(job.jobId or job.member or "job"))
        except Exception as exc:  # noqa: BLE001 - 标记不可用时按“可继续”处理
            return True, ""

    def _release_word_slot(self) -> None:
        try:
            from doc_tool.application.delivery import word_busy

            word_busy.release()
        except Exception:  # noqa: BLE001 - 释放失败由 TTL 兜底
            pass

    def _call_runner_with_retry(self, runner, job, kwargs, *, progress):
        """调用执行服务；仅对可重试且幂等的临时故障自动重试一次。

        返回 ``(produced, error, auto_retries)``。只重试 OSError/TimeoutError 这类
        临时故障（文件被占用、临时不可写等）；内容/参数类失败不重试，避免反复出错。
        """
        auto_retries = 0
        while True:
            try:
                return runner(job.request(), **kwargs), None, auto_retries
            except (OSError, TimeoutError) as exc:
                if auto_retries >= AUTO_RETRY_LIMIT:
                    return None, exc, auto_retries
                auto_retries += 1
                job.notes.append(
                    "临时故障自动重试一次（{0}）：{1}".format(
                        type(exc).__name__, str(exc)[:120] or "无详细信息",
                    )
                )
                job.updatedAt = utc_now_iso()
                self.save()
                self._notify(progress, job, "retrying", "临时故障自动重试一次")
            except Exception as exc:  # noqa: BLE001 - 其它异常不自动重试
                return None, exc, auto_retries

    def _progress_bridge(self, progress, job: BatchJob):
        if progress is None:
            return None

        def forward(stage: str, detail: str = "") -> None:
            self._notify(progress, job, stage, detail)

        return forward

    @staticmethod
    def _notify(progress, job: BatchJob, stage: str, detail: str) -> None:
        if progress is None:
            return
        try:
            progress(job, stage, detail)
        except Exception:  # noqa: BLE001 - 进度回调失败不影响批次执行
            pass

    # --- 结果视图 ---

    def unfinished_jobs(self) -> List[BatchJob]:
        return [
            job for job in self.jobs
            if not job.is_completed() and job.status != JOB_CANCELLED
        ]

    def completed_jobs(self) -> List[BatchJob]:
        return [job for job in self.jobs if job.is_completed()]

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {status: 0 for status in JOB_STATUSES}
        for job in self.jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
        counts["total"] = len(self.jobs)
        return counts

    def summary_lines(self, limit: int = 8) -> List[str]:
        counts = self.counts()
        lines = ["批次 {0}：{1} 项｜已完成 {2}｜待刷新 {3}｜失败 {4}｜其它 {5}".format(
            self.batchId, counts["total"],
            counts[JOB_COMPLETED] + counts[JOB_COMPLETED_WITH_WARNINGS],
            counts[JOB_WAITING_REFRESH], counts[JOB_FAILED],
            counts[JOB_QUEUED] + counts[JOB_PARTIAL] + counts[JOB_INTERRUPTED] + counts[JOB_CANCELLED],
        )]
        for job in self.jobs[: max(0, int(limit))]:
            lines.append("· " + job.summary_line())
        if len(self.jobs) > limit:
            lines.append("其余 {0} 项见机器报告".format(len(self.jobs) - limit))
        for note in self.warnings:
            lines.append("提醒：" + note)
        return lines

    def machine_report(self) -> Dict[str, object]:
        """JSON 报告：逐项状态/路径/尝试历史（部分完成不标 complete）。"""
        return {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "batchId": self.batchId,
            "storePath": str(self.store_path),
            "jobCount": len(self.jobs),
            "counts": self.counts(),
            "unfinishedJobIds": [job.jobId for job in self.unfinished_jobs()],
            "jobs": [job.to_dict() for job in self.jobs],
            "warnings": list(self.warnings),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.machine_report(), ensure_ascii=False, indent=indent)

def _classify_job(job: BatchJob, *, word_applied: bool, refresh_wanted: bool, cancelled: bool) -> str:
    """把一轮出稿结果映射为逐项状态；正式级别不在此提升。"""
    report = job.report_obj()
    if report is None:
        return JOB_CANCELLED if cancelled else JOB_FAILED
    has_cancelled = any(item.status == STATUS_CANCELLED for item in report.results)
    if cancelled and (has_cancelled or not report.usable_results()):
        return JOB_CANCELLED
    if not report.usable_results():
        return JOB_FAILED
    if job.strict and report.strict_violations():
        return JOB_FAILED
    results = report.results
    pending_refresh = any(item.status == STATUS_PENDING_REFRESH for item in results)
    incomplete = any(
        item.status in (STATUS_FAILED, STATUS_PENDING_CONVERT, STATUS_CANCELLED, "skipped")
        for item in results
    )
    if pending_refresh and refresh_wanted and not word_applied:
        return JOB_WAITING_REFRESH
    if incomplete:
        return JOB_PARTIAL
    if pending_refresh:
        return JOB_COMPLETED_WITH_WARNINGS
    if any(item.warnings for item in results):
        return JOB_COMPLETED_WITH_WARNINGS
    return JOB_COMPLETED


__all__ = [
    "STORE_NAME", "STORE_SCHEMA_VERSION", "AUTO_RETRY_LIMIT",
    "JOB_QUEUED", "JOB_PREPARING", "JOB_RUNNING", "JOB_WAITING_REFRESH", "JOB_COMPLETED",
    "JOB_COMPLETED_WITH_WARNINGS", "JOB_PARTIAL", "JOB_FAILED", "JOB_CANCELLED",
    "JOB_INTERRUPTED", "JOB_STATUSES", "JOB_STATUS_LABELS", "COMPLETED_JOB_STATUSES",
    "PENDING_JOB_STATUSES", "RETRYABLE_JOB_STATUSES", "job_status_label",
    "BatchJob", "EnqueueResult", "DeliveryQueue",
]