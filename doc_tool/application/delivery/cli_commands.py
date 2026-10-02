# -*- coding: utf-8 -*-
"""V3.2 32-F 批次 CLI 实现（结构化结果，打印由 ``cli.py`` 负责）。

命令与既有服务同源，未引入第二套编排：

- ``delivery-plan``：只读预览 schema 1 批次计划（成员/变体/格式/目标/成员级问题）。
- ``delivery-run``：读计划 → 入队（去重、已完成跳过）→ 串行执行；支持
  ``--continue``（继续未落定项）、``--retry-failed``（只补失败/待刷新项）、
  ``--cancel-after N``（达到成员上限后取消其余未开始项）、``--no-refresh``
  （本机不做 Word 刷新，逐项转待刷新）、``--strict``（显式严格策略）。
- ``delivery-status``：只读查询持久队列 + 结果索引（正常人读/JSON，不因任务失败改退出码）。
- ``delivery-retry``：对已有 store 只重试未完成项（可 ``--job-id`` 限定）。
- ``delivery-package``：把某一轮出稿结果 + 固定快照打成自足交付包（``.zip`` 或目录）。
- ``delivery-promote``：在有 Word 的环境按包内固定快照补刷新并本地登记。

退出码约定（与 design.md D5 / 任务 6.2 一致）：

- ``0``：至少得到一个所请求范围内的可用结果（可含部分失败/待刷新/可读稿），
  或 ``status`` 正常完成查询；
- ``1``：完全没有可用结果（或严格模式下阈值未满足）；
- ``2``：参数/输入非法（计划不可读、schema 不符、没有可执行成员、store 缺失等）。

``status`` 为只读查询：store 里有失败任务也返回 0，失败信息放在报告内。
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from doc_tool.application.delivery.contract import (
    BatchEntry,
    BatchPlan,
    load_plan_file,
    plan_report,
)
from doc_tool.application.delivery.queue import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_COMPLETED_WITH_WARNINGS,
    JOB_FAILED,
    JOB_QUEUED,
    BatchJob,
    DeliveryQueue,
    job_status_label,
)
from doc_tool.application.delivery.result_index import build_result_index
from doc_tool.application.delivery.snapshot_package import (
    build_delivery_package,
    formalize_package,
)
from doc_tool.application.intake_contract import format_label, utc_now_iso

COMMANDS = (
    "delivery-plan", "delivery-run", "delivery-status",
    "delivery-retry", "delivery-package", "delivery-promote",
)

EXIT_OK = 0
EXIT_NO_RESULT = 1
EXIT_INVALID = 2

#: 逐项退出码：该项自身是否有可用结果（未执行/取消单独给出）。
ITEM_OK = 0
ITEM_NO_RESULT = 1
ITEM_NOT_RUN = 2

STORE_HINT = "python doc_tool_cli.py delivery-status --store <store> --json"


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _output_mode(args) -> str:
    if getattr(args, "json", False):
        return "json"
    return getattr(args, "output", "human") or "human"


def _payload(
    command: str,
    exit_code: int,
    *,
    summary: Optional[Sequence[str]] = None,
    error: str = "",
    **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "command": command,
        "exitCode": int(exit_code),
        "success": int(exit_code) == EXIT_OK,
        "summary": list(summary or []),
    }
    if error:
        payload["error"] = error
    payload.update(extra)
    return payload


# --- 计划读取 ---


def _load_plan(args) -> BatchPlan:
    """按命令行参数读取计划并施加显式覆盖（``--strict`` 强制所有成员严格）。"""
    strict = True if getattr(args, "strict", False) else None
    plan = load_plan_file(
        getattr(args, "plan", "") or "",
        base_dir=getattr(args, "base_dir", "") or "",
        policy_overrides={"strict": strict},
    )
    plan.apply_overrides(
        strict=strict,
        destination=getattr(args, "destination", "") or "",
        formats=_split_csv(getattr(args, "formats", "")),
        variant_id=getattr(args, "variant", "") or "",
    )
    if getattr(args, "no_refresh", False):
        plan.warnings.append(
            "本轮不做 Word 刷新：执行时逐项转「待刷新」，可在有 Word 的环境补刷新。"
        )
    return plan


def _store_from_args(args) -> Optional[str]:
    return getattr(args, "store", "") or None


# --- 逐项退出码与整体判定 ---


def _job_exit_code(job: BatchJob) -> int:
    if job.status in (JOB_CANCELLED,):
        return ITEM_NOT_RUN
    if job.usable_results():
        return ITEM_OK
    if job.status == JOB_FAILED:
        return ITEM_NO_RESULT
    if not job.attemptCount:
        return ITEM_NOT_RUN
    return ITEM_NO_RESULT


def _scope_exit_code(jobs: Sequence[BatchJob], *, strict: bool) -> int:
    """范围内至少一个可用结果 → 0；完全没有 → 1；严格阈值未满足 → 1。"""
    if not jobs:
        return EXIT_NO_RESULT
    usable = [job for job in jobs if job.usable_results()]
    if not usable:
        return EXIT_NO_RESULT
    if strict:
        complete = all(
            job.is_completed() and not job.pending_formats() for job in jobs
        )
        if not complete:
            return EXIT_NO_RESULT
    return EXIT_OK


def _overall_status(jobs: Sequence[BatchJob], *, strict: bool) -> str:
    if not jobs:
        return "empty"
    usable = [job for job in jobs if job.usable_results()]
    if not usable:
        return "failed"
    if all(job.status in (JOB_COMPLETED, JOB_COMPLETED_WITH_WARNINGS) for job in jobs):
        if strict and any(job.pending_formats() for job in jobs):
            return "partial"
        if strict and any(job.status == JOB_COMPLETED_WITH_WARNINGS for job in jobs):
            return "partial"
        return "complete"
    return "partial"


def _job_reports(jobs: Sequence[BatchJob]) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for job in jobs:
        data = job.to_dict()
        data["exitCode"] = _job_exit_code(job)
        reports.append(data)
    return reports


def _job_line(job: BatchJob) -> str:
    results = job.results()
    usable = [item for item in results if item.usable]
    detail = "、".join(
        "{0}{1}".format(
            format_label(item.format), "" if item.status == "ready" else "（{0}）".format(item.status),
        )
        for item in usable
    ) or "（无可用格式）"
    head = "[{0}] {1}".format(job_status_label(job.status), job.projectRoot or job.jobId)
    tail = job.waitingReason or job.error
    return "{0}｜可用 {1}/{2}：{3}{4}".format(
        head, len(usable), len(results) or len(job.formats), detail,
        "｜" + tail if tail else "",
    )


# --- delivery-plan ---


def delivery_plan(args) -> Dict[str, Any]:
    """只读预览计划：列出成员/变体/格式/目标与成员级问题，不执行、不入队。"""
    plan = _load_plan(args)
    report = plan_report(plan)
    summary = list(plan.summary_lines())
    if not plan.ok:
        summary.append("处方：请修正计划文件（schema 1、entries 至少一项）。")
        return _payload(
            "delivery-plan", EXIT_INVALID, summary=summary, error="；".join(plan.problems),
            plan=report,
        )
    summary.append("说明：本命令只预览，不执行、不写入队列；执行请用 delivery-run。")
    return _payload("delivery-plan", EXIT_OK, summary=summary, plan=report)


# --- delivery-run ---


def _enqueue_plan(queue: DeliveryQueue, plan: BatchPlan) -> List[Dict[str, Any]]:
    enqueued: List[Dict[str, Any]] = []
    for entry in plan.executable_entries():
        result = queue.enqueue(
            project_root=entry.projectRoot,
            formats=entry.formats,
            scope=entry.scope_obj(),
            destination=entry.destination,
            output_name=entry.outputName,
            strict=entry.strict,
            refresh=entry.refresh,
            variant_id=entry.variantId,
            source_mode=entry.sourceMode,
            request_id=entry.requestId,
        )
        job = result.job
        policy_updated = False
        if result.reused and not result.skipped and not job.is_completed():
            # 复用未完成项时，本轮显式策略（--strict/--no-refresh 之外的计划声明）落到该任务，
            # 避免「本次要求严格」被上一次登记悄悄忽略。
            if bool(job.strict) != bool(entry.strict):
                job.strict = bool(entry.strict)
                policy_updated = True
            if bool(job.refresh) != bool(entry.refresh):
                job.refresh = bool(entry.refresh)
                policy_updated = True
            if policy_updated:
                job.updatedAt = utc_now_iso()
                queue.save()
        enqueued.append({
            "policyUpdated": policy_updated,
            "entryId": entry.entryId,
            "member": entry.member,
            "memberName": entry.memberName,
            "variantId": entry.variantId,
            "formats": list(entry.formats),
            "destination": entry.destination,
            "jobId": result.job.jobId,
            "reused": bool(result.reused),
            "skipped": bool(result.skipped),
            "reason": result.reason,
            "status": result.job.status,
            "statusLabel": job_status_label(result.job.status),
        })
    return enqueued


def _safe_folder(value: str) -> str:
    from doc_tool.application.intake_contract import sanitize_name_part

    return sanitize_name_part(str(value or "")) or "member"


def _split_shared_destinations(entries: Sequence["BatchEntry"]) -> List[str]:
    """同一目标目录的多个成员自动分到 ``<目标>/<成员名>``。

    统一出稿把一轮的索引固定在目标目录的 ``export-result.json``；多个成员共用同一
    目标目录时该索引会被后一个成员覆盖（失败的成员也可能留下没有可用产物的索引）。
    分目录后每个成员各自持有自己的报告与产物，包/索引/状态不再互相串。
    """
    counts: Dict[str, int] = {}
    for entry in entries:
        if entry.destination:
            counts[entry.destination] = counts.get(entry.destination, 0) + 1
    used = {
        entry.destination for entry in entries
        if entry.destination and counts[entry.destination] == 1
    }
    notes: List[str] = []
    for entry in entries:
        destination = entry.destination
        if not destination or counts[destination] <= 1:
            continue
        base = Path(destination)
        name = _safe_folder(entry.memberName)
        candidate = base / name
        order = 2
        while str(candidate) in used:
            candidate = base / "{0}-{1}".format(name, order)
            order += 1
        used.add(str(candidate))
        entry.destination = str(candidate)
        notes.append(
            "共用目标目录已按成员分目录：{0} → {1}".format(entry.memberName, candidate)
        )
    return notes


def _matched_jobs(queue: DeliveryQueue, enqueued: Sequence[Dict[str, Any]]) -> List[BatchJob]:
    jobs: List[BatchJob] = []
    for item in enqueued:
        job = queue.job(str(item.get("jobId") or ""))
        if job is not None:
            jobs.append(job)
    return jobs


def delivery_run(args) -> Dict[str, Any]:
    """入队并串行执行计划成员；单项失败/待刷新不影响其它成员。"""
    plan = _load_plan(args)
    if not plan.ok:
        return _payload(
            "delivery-run", EXIT_INVALID, summary=plan.summary_lines(),
            error="；".join(plan.problems) or "计划不可用", plan=plan_report(plan),
        )
    executable = plan.executable_entries()
    if not executable:
        return _payload(
            "delivery-run", EXIT_INVALID,
            summary=plan.summary_lines() + ["没有可执行成员：请修正成员路径或格式后重试。"],
            error="计划没有可执行成员（非法成员只影响该项，已逐条列出）",
            plan=plan_report(plan),
        )

    if bool(getattr(args, "continue_mode", False)) and bool(getattr(args, "retry_failed", False)):
        return _payload(
            "delivery-run", EXIT_INVALID,
            summary=["--continue 与 --retry-failed 互斥：请只选一个。"],
            error="参数冲突：--continue / --retry-failed", plan=plan_report(plan),
        )
    destination_notes = _split_shared_destinations(executable)
    queue = DeliveryQueue(_store_from_args(args), batch_id=plan.batchId)
    enqueued = _enqueue_plan(queue, plan)
    matched = _matched_jobs(queue, enqueued)
    skip_word = bool(getattr(args, "no_refresh", False))
    strict = bool(getattr(args, "strict", False) or plan.policy.strict)

    continue_mode = bool(getattr(args, "continue_mode", False))
    retry_mode = bool(getattr(args, "retry_failed", False))

    fresh_ids = [job.jobId for job in matched if job.status == JOB_QUEUED]
    retry_ids = [
        job.jobId for job in matched
        if job.is_retryable() and job.status != JOB_QUEUED
    ]
    mode = "run"
    if retry_mode:
        mode = "retry-failed"
        ordered = retry_ids + fresh_ids
    elif continue_mode:
        mode = "continue"
        ordered = [job.jobId for job in queue.jobs if job.is_pending()]
    else:
        ordered = list(fresh_ids)

    limit = getattr(args, "cancel_after", None)
    cancelled_rest: List[str] = []
    if limit is not None and limit >= 0 and len(ordered) > limit:
        keep = ordered[:limit]
        cancelled_rest = ordered[limit:]
        queue.cancel(
            job_ids=cancelled_rest,
            reason="--cancel-after {0}：达到成员上限，其余未开始项取消；已完成项保留".format(limit),
        )
        ordered = keep

    outcomes: List[BatchJob] = []
    scope_ids: List[str] = [job.jobId for job in matched] + list(cancelled_rest)
    if retry_mode and retry_ids:
        outcomes.extend(queue.retry_unfinished(
            skip_word_refresh=skip_word, only_job_ids=[item for item in retry_ids if item in ordered],
        ))
    if mode == "continue":
        outcomes.extend(queue.run_pending(skip_word_refresh=skip_word))
    elif fresh_ids:
        keep_fresh = [item for item in fresh_ids if item in ordered]
        if keep_fresh:
            outcomes.extend(queue.run_pending(skip_word_refresh=skip_word, only_job_ids=keep_fresh))

    scope_jobs: List[BatchJob] = []
    for job_id in scope_ids:
        job = queue.job(job_id)
        if job is not None and job not in scope_jobs:
            scope_jobs.append(job)
    exit_code = _scope_exit_code(scope_jobs, strict=strict)
    status = _overall_status(scope_jobs, strict=strict)

    from doc_tool.application.delivery.gui_hooks import batch_view

    view = batch_view(queue)
    summary = [
        "批次 {0}｜模式 {1}｜整体状态 {2}｜退出码 {3}".format(
            queue.batchId, mode, status, exit_code,
        ),
        "队列：{0}｜本轮入队 {1} 项（复用 {2}，已完成跳过 {3}）".format(
            queue.store_path, len(enqueued),
            len([item for item in enqueued if item["reused"] and not item["skipped"]]),
            len([item for item in enqueued if item["skipped"]]),
        ),
        "策略：严格 {0}｜本机做 Word 刷新 {1}".format(
            "开" if strict else "关", "否（逐项待刷新）" if skip_word else "是（Word 忙/不可用转待刷新）",
        ),
    ]
    summary.extend(destination_notes)
    for job in scope_jobs:
        summary.append("· " + _job_line(job))
    if cancelled_rest:
        summary.append("--cancel-after 生效：其余 {0} 项已取消（已完成结果保留）".format(
            len(cancelled_rest)
        ))
    if exit_code == EXIT_NO_RESULT:
        summary.append("结论：本范围内没有可用结果；可查看逐项原因后重试未完成项。")
    summary.append("查询/继续：python doc_tool_cli.py delivery-status --store \"{0}\" --json".format(
        queue.store_path
    ))

    return _payload(
        "delivery-run", exit_code, summary=summary,
        mode=mode, batchId=queue.batchId, storePath=str(queue.store_path),
        planPath=plan.planPath, strict=strict, skipWordRefresh=skip_word,
        destinationNotes=list(destination_notes),
        entries=_entry_job_links(plan, queue, enqueued),
        skippedEntries=[entry.to_dict() for entry in plan.skipped],
        enqueued=enqueued, counts=queue.counts(), overallStatus=status,
        jobs=_job_reports(scope_jobs), view=view.to_dict(),
        warnings=list(queue.warnings) + list(plan.warnings),
    )


def _entry_job_links(
    plan: BatchPlan, queue: DeliveryQueue, enqueued: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_entry = {str(item.get("entryId") or ""): item for item in enqueued}
    rows: List[Dict[str, Any]] = []
    for entry in plan.all_entries():
        data = entry.to_dict()
        link = by_entry.get(entry.entryId)
        data["jobId"] = str((link or {}).get("jobId") or "")
        data["reused"] = bool((link or {}).get("reused"))
        data["skipped"] = bool((link or {}).get("skipped"))
        data["enqueueReason"] = str((link or {}).get("reason") or "")
        rows.append(data)
    return rows


# --- delivery-status ---


def delivery_status(args) -> Dict[str, Any]:
    """只读查询：持久队列 + 结果索引；任务失败信息在报告内，退出码仍为 0。"""
    store_setting = getattr(args, "store", "") or ""
    queue = DeliveryQueue(store_setting or None)
    sources: List[str] = []
    missing_inputs: List[str] = []
    for item in getattr(args, "index", None) or []:
        if Path(item).exists():
            sources.append(item)
        else:
            missing_inputs.append(item)
    if store_setting and not Path(store_setting).is_file():
        missing_inputs.append(store_setting)
    if Path(queue.store_path).is_file():
        sources.append(str(queue.store_path))
    index = build_result_index(sources)
    from doc_tool.application.delivery.gui_hooks import batch_view, result_view

    view = batch_view(queue, index=index)

    if missing_inputs:
        return _payload(
            "delivery-status", EXIT_INVALID,
            summary=["输入不可用：" + "、".join(missing_inputs)],
            error="以下路径不存在：{0}".format("、".join(missing_inputs)),
            storePath=str(queue.store_path),
        )

    plan_data: Optional[Dict[str, Any]] = None
    if getattr(args, "plan", ""):
        plan = _load_plan(args)
        plan_data = plan_report(plan)
        if not plan.ok:
            return _payload(
                "delivery-status", EXIT_INVALID,
                summary=["计划不可读：" + "；".join(plan.problems)],
                error="；".join(plan.problems), plan=plan_data,
                storePath=str(queue.store_path),
            )

    summary = list(view.summary_lines())
    summary.append("结果索引：{0} 条｜整体状态 {1}｜来源 {2} 个".format(
        len(index.entries), index.overall_status(), len(index.sources),
    ))
    for line in index.summary_lines(limit=8)[1:]:
        summary.append(line)
    summary.append("下一步：只重试未完成项 → python doc_tool_cli.py delivery-retry --store \"{0}\"".format(
        queue.store_path
    ))
    return _payload(
        "delivery-status", EXIT_OK, summary=summary,
        batchId=queue.batchId, storePath=str(queue.store_path),
        storeExists=Path(queue.store_path).is_file(),
        counts=queue.counts(), overallStatus=view.overallStatus,
        jobs=[job.to_dict() for job in queue.jobs],
        view=view.to_dict(), resultView=result_view(index).to_dict(),
        index=index.to_dict(), plan=plan_data,
        warnings=list(queue.warnings) + list(index.warnings),
    )


# --- delivery-retry ---


def delivery_retry(args) -> Dict[str, Any]:
    """只重试失败/待刷新/部分完成项（复用该项原轮快照），不重走全部任务。"""
    store_setting = getattr(args, "store", "") or ""
    store_path = Path(store_setting) if store_setting else None
    if store_path is None or not store_path.is_file():
        return _payload(
            "delivery-retry", EXIT_INVALID,
            summary=["没有可重试的批次队列：请先用 delivery-run 生成 store。"],
            error="批次队列不存在：{0}".format(store_setting or "（未指定 --store）"),
        )
    queue = DeliveryQueue(store_setting)
    wanted = list(getattr(args, "job_id", None) or [])
    retryable = [
        job for job in queue.jobs
        if job.is_retryable() and (not wanted or job.jobId in wanted)
    ]
    unknown = [item for item in wanted if queue.job(item) is None]
    if unknown:
        return _payload(
            "delivery-retry", EXIT_INVALID,
            summary=["未知 jobId：" + "、".join(unknown)],
            error="store 中没有这些 jobId：{0}".format("、".join(unknown)),
            storePath=str(queue.store_path),
        )
    skip_word = bool(getattr(args, "no_refresh", False))
    outcomes = queue.retry_unfinished(
        skip_word_refresh=skip_word, only_job_ids=[job.jobId for job in retryable] or None,
    )
    scope_jobs = outcomes or [
        job for job in queue.jobs if not wanted or job.jobId in wanted
    ]
    strict = any(job.strict for job in scope_jobs)
    exit_code = _scope_exit_code(scope_jobs, strict=strict)
    status = _overall_status(scope_jobs, strict=strict)

    from doc_tool.application.delivery.gui_hooks import batch_view

    summary = [
        "批次 {0}｜重试 {1} 项｜整体状态 {2}｜退出码 {3}".format(
            queue.batchId, len(outcomes), status, exit_code,
        ),
    ]
    if not retryable:
        summary.append("没有失败/待刷新/未完成项：无需重试。")
    for job in scope_jobs:
        summary.append("· " + _job_line(job))
    return _payload(
        "delivery-retry", exit_code, summary=summary,
        batchId=queue.batchId, storePath=str(queue.store_path),
        retried=[job.jobId for job in outcomes], counts=queue.counts(),
        overallStatus=status, jobs=_job_reports(scope_jobs),
        view=batch_view(queue).to_dict(), warnings=list(queue.warnings),
    )


# --- delivery-package ---


def _package_source(args) -> Dict[str, Any]:
    """解析打包来源：``--from`` 或 ``--store``（+ 可选 ``--job-id``）。"""
    from_value = getattr(args, "source", "") or ""
    store_setting = getattr(args, "store", "") or ""
    job_id = getattr(args, "job_id", "") or ""
    if not store_setting:
        return {"source": from_value, "variantId": getattr(args, "variant", "") or "", "job": None}
    queue = DeliveryQueue(store_setting)
    job = queue.job(job_id) if job_id else None
    if job is None and not job_id:
        candidates = [item for item in queue.jobs if item.usable_results()]
        job = candidates[-1] if candidates else None
    if job is None:
        return {"source": "", "variantId": "", "job": None,
                "error": "store 中没有可用成员：{0}{1}".format(
                    store_setting, "（jobId {0}）".format(job_id) if job_id else "",
                )}
    if job.report_obj() is not None:
        # 优先用任务自身落盘的报告：目标目录共用时，导出索引可能属于另一个成员。
        source: Any = job.report_obj()
    elif job.indexPath and Path(job.indexPath).is_file():
        source = job.indexPath
    else:
        source = job.destination
    return {
        "source": source,
        "variantId": getattr(args, "variant", "") or job.variantId,
        "job": job,
    }


def _default_package_target(source: Any) -> Path:
    """默认包路径：与来源同目录，避免写进仓库或用户配置目录。"""
    if isinstance(source, (str, Path)):
        path = Path(source)
        base = path if path.is_dir() else path.parent
        return base / "delivery-package.zip"
    destination = str(getattr(source, "destination", "") or "")
    base = Path(destination) if destination else Path.cwd()
    return base / "delivery-package.zip"


def delivery_package(args) -> Dict[str, Any]:
    """生成自足交付包：包内一律相对路径，缺可读 DOCX 时明确拒绝。"""
    resolved = _package_source(args)
    if resolved.get("error"):
        return _payload(
            "delivery-package", EXIT_INVALID, summary=[str(resolved["error"])],
            error=str(resolved["error"]),
        )
    source = resolved.get("source")
    if not source or (isinstance(source, (str, Path)) and not Path(source).exists()):
        return _payload(
            "delivery-package", EXIT_INVALID,
            summary=["没有可打包来源：请给 --from <导出目录|export-result.json> 或 --store <队列>"],
            error="打包来源不存在或未给出",
        )
    target = getattr(args, "target", "") or ""
    if not target:
        target = str(_default_package_target(source))
    outcome = build_delivery_package(
        source, target=target, variant_id=resolved.get("variantId") or "",
        include_original=bool(getattr(args, "include_original", False)),
    )
    summary = list(outcome.summary_lines())
    if outcome.ok:
        summary.append("换机处理：python doc_tool_cli.py delivery-promote \"{0}\" --destination <目录>".format(
            outcome.path
        ))
    exit_code = EXIT_OK if outcome.ok else EXIT_NO_RESULT
    return _payload(
        "delivery-package", exit_code, summary=summary,
        package=outcome.to_dict(), target=str(outcome.path or target),
        variantId=resolved.get("variantId") or "",
        warnings=list(outcome.warnings),
    )


# --- delivery-promote ---


def delivery_promote(args) -> Dict[str, Any]:
    """在有 Word 的环境按包内固定快照补刷新并本地登记（不依赖原电脑项目路径）。"""
    package = getattr(args, "package", "") or ""
    if not Path(package).exists():
        return _payload(
            "delivery-promote", EXIT_INVALID,
            summary=["交付包不存在：{0}".format(package or "（未给出）")],
            error="交付包不存在：{0}".format(package or "（未给出）"),
        )
    mode = (getattr(args, "word_available", "auto") or "auto").lower()
    if mode == "yes":
        word_available: Optional[bool] = True
    elif mode == "no":
        word_available = False
    elif mode == "auto":
        word_available = None
    else:
        return _payload(
            "delivery-promote", EXIT_INVALID,
            summary=["--word-available 只支持 auto/yes/no"],
            error="参数非法：--word-available {0}".format(mode),
        )
    outcome = formalize_package(
        package,
        destination=getattr(args, "destination", "") or None,
        word_available=word_available,
        registry_path=getattr(args, "registry", "") or None,
        source_project_root=getattr(args, "source_project", "") or None,
    )
    summary = list(outcome.summary_lines())
    if outcome.status == "waiting-refresh":
        summary.append("说明：本机未形成正式结果，包与可读稿都保留；可在有 Word 的机器重跑本命令。")
    exit_code = EXIT_OK if outcome.ok else EXIT_NO_RESULT
    return _payload(
        "delivery-promote", exit_code, summary=summary,
        packagePath=str(package), formalize=outcome.to_dict(),
        warnings=list(outcome.warnings),
    )


# --- 分发与渲染 ---


def run(command: str, args) -> Dict[str, Any]:
    """按命令名执行；库内 stdout 噪声统一转到 stderr，保证 JSON 是单一 stdout 文档。"""
    handlers = {
        "delivery-plan": delivery_plan,
        "delivery-run": delivery_run,
        "delivery-status": delivery_status,
        "delivery-retry": delivery_retry,
        "delivery-package": delivery_package,
        "delivery-promote": delivery_promote,
    }
    handler = handlers.get(command)
    if handler is None:
        return _payload(command, EXIT_INVALID, summary=["未知批次命令：{0}".format(command)],
                        error="未知批次命令：{0}".format(command))
    with contextlib.redirect_stdout(sys.stderr):
        return handler(args)


def render(payload: Dict[str, Any], *, output: str = "human") -> str:
    """渲染为 JSON 或人读文本（JSON 为单一文档，日志在 stderr）。"""
    if output == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = list(payload.get("summary") or [])
    if payload.get("error"):
        lines.append("错误：{0}".format(payload["error"]))
    return "\n".join(str(line) for line in lines)


def main(args) -> int:
    """CLI 入口：打印报告并返回退出码。"""
    payload = run(args.command, args)
    print(render(payload, output=_output_mode(args)))
    return int(payload.get("exitCode", EXIT_INVALID))


__all__ = [
    "COMMANDS", "EXIT_OK", "EXIT_NO_RESULT", "EXIT_INVALID",
    "ITEM_OK", "ITEM_NO_RESULT", "ITEM_NOT_RUN", "STORE_HINT",
    "delivery_plan", "delivery_run", "delivery_status",
    "delivery_retry", "delivery_package", "delivery_promote",
    "run", "render", "main",
]
