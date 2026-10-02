# -*- coding: utf-8 -*-
"""批次交付的界面任务适配（V3.2 32-E，Qt-free）。

把「计划预览 → 入队 → 串行执行 → 结果视图」包装成普通可调用对象，便于放进既有
``TaskRunner``（V3.2 2.2）而不在界面里写业务逻辑；GUI 只渲染 :mod:`gui_hooks` 给出的
状态与动作模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dataclasses import dataclass as _dataclass

from doc_tool.application.delivery import contract, gui_hooks
from doc_tool.application.delivery.queue import DeliveryQueue
from doc_tool.application.delivery.result_index import build_result_index


@_dataclass
class DeliveryStageEvent:
    """TaskRunner 能识别的阶段事件（stage/status/detail/metrics）。"""

    stage: str = ""
    status: str = ""
    detail: str = ""
    metrics: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metrics is None:
            self.metrics = {}


class _QueueProgressRelay:
    """把队列的 ``progress(job, stage, detail)`` 转成逐项阶段事件。

    审计发现（第十四轮）：界面传 ``kwargs={}``，队列的 per-item progress 永远为 None，
    Dock 只能看到任务级事件。现在由本中继把每个成员的开始/完成/失败/跳过都推给 UI。
    """

    def __init__(self, on_event=None, on_progress=None) -> None:
        self._on_event = on_event
        self._on_progress = on_progress
        self.count = 0

    def __call__(self, job, stage: str = "", detail: str = "") -> None:
        self.count += 1
        # BatchJob 没有 member 字段：成员名与 gui_hooks.member_row 保持同一来源
        member = ""
        try:
            member = str(gui_hooks.member_row(job).memberName or "")
        except Exception:  # noqa: BLE001 - 行构造失败时退回项目目录名
            member = ""
        if not member:
            member = Path(str(getattr(job, "projectRoot", "") or "")).name
        variant = getattr(job, "variantId", "") or ""
        label = member + (("｜变体 " + variant) if variant else "")
        payload = {
            "jobId": getattr(job, "jobId", ""),
            "member": member,
            "variantId": variant,
            "stage": stage,
            "detail": detail,
            "index": self.count,
        }
        if self._on_event is not None:
            try:
                self._on_event(DeliveryStageEvent(
                    stage="delivery:{0}".format(stage or "progress"),
                    status="running",
                    detail="{0}：{1}".format(label, detail) if detail else label,
                    metrics=payload,
                ))
            except Exception:  # noqa: BLE001 - 进度推送失败不影响执行
                pass
        if self._on_progress is not None:
            try:
                self._on_progress(label, stage, detail, payload)
            except Exception:  # noqa: BLE001
                pass


def _entry_payload(entry: contract.BatchEntry) -> Dict[str, Any]:
    return {
        "project_root": entry.projectRoot,
        "formats": list(entry.formats),
        "scope": entry.scope_obj(),
        "destination": entry.destination,
        "output_name": entry.outputName,
        "strict": bool(entry.strict),
        "refresh": bool(entry.refresh),
        "variant_id": entry.variantId,
        "source_mode": entry.sourceMode,
    }


def plan_preview(plan_path) -> Dict[str, Any]:
    """只读预览：可执行/无效成员与默认策略（不产生任何写入）。"""
    plan = contract.load_plan_file(plan_path)
    view = gui_hooks.plan_view(plan)
    return {
        "planPath": str(plan.planPath or plan_path),
        "batchId": plan.batchId,
        "report": contract.plan_report(plan),
        "view": view.to_dict(),
        "summary": view.summary_lines(),
        "executable": [row.to_dict() for row in view.executable_rows()],
        "invalid": [row.to_dict() for row in view.invalid_rows()],
    }


def _enqueue_plan(queue: DeliveryQueue, plan: contract.BatchPlan) -> List[Any]:
    jobs = []
    for entry in plan.executable_entries():
        result = queue.enqueue(**_entry_payload(entry))
        jobs.append(result)
    return jobs


def run_plan_task(
    plan_path,
    *,
    store_path: str = "",
    retry: bool = False,
    skip_word_refresh: bool = True,
    cancel_token=None,
    progress=None,
    on_event=None,
) -> Dict[str, Any]:
    """执行一批交付：入队后串行跑未完成项（重复入队幂等）。

    ``skip_word_refresh=True`` 是界面默认：先拿可读结果，Word 刷新/PDF 转换按包
    或稍后补；正式状态仍只由既有 ``OutputState`` 判定。
    """
    plan = contract.load_plan_file(plan_path)
    queue = DeliveryQueue(store_path or None, batch_id=plan.batchId or "")
    enqueued = _enqueue_plan(queue, plan)
    relay = _QueueProgressRelay(on_event=on_event, on_progress=progress)
    progress = relay
    if retry:
        jobs = queue.retry_unfinished(
            skip_word_refresh=skip_word_refresh, cancel_token=cancel_token, progress=progress,
        )
    else:
        jobs = queue.run_pending(
            skip_word_refresh=skip_word_refresh, cancel_token=cancel_token, progress=progress,
        )
    return _payload(queue, plan=plan, enqueued=enqueued, ran=jobs)


def retry_unfinished_task(
    store_path, *, skip_word_refresh: bool = True, cancel_token=None, progress=None,
    on_event=None,
) -> Dict[str, Any]:
    """只补未完成项（使用队列内原轮快照，不重走全部任务）。"""
    queue = DeliveryQueue(store_path or None)
    progress = _QueueProgressRelay(on_event=on_event, on_progress=progress)
    jobs = queue.retry_unfinished(
        skip_word_refresh=skip_word_refresh, cancel_token=cancel_token, progress=progress,
    )
    return _payload(queue, ran=jobs)


def status_snapshot(store_path="", *, index_paths: Sequence[str] = ()) -> Dict[str, Any]:
    """队列 + 结果索引的只读快照（供状态页/概览展示）。"""
    queue = DeliveryQueue(store_path or None)
    index = build_result_index(list(index_paths))
    return {
        "schemaVersion": 1,
        "queue": queue.machine_report(),
        "batch": gui_hooks.batch_view(queue, index=index).to_dict(),
        "result": gui_hooks.result_view(index).to_dict(),
    }


def _index_paths(queue: DeliveryQueue) -> List[str]:
    """收集所有已产出报告的索引路径（含待刷新项，便于结果页直接打开）。"""
    paths: List[str] = []
    jobs = getattr(queue, "jobs", None)
    if jobs is None:
        jobs = list(getattr(queue, "_jobs", {}).values()) if hasattr(queue, "_jobs") else []
    for job in list(jobs or []):
        report = getattr(job, "report_obj", None)
        if report is None:
            continue
        index_path = str(getattr(report, "indexPath", "") or "")
        if index_path and index_path not in paths:
            paths.append(index_path)
    return paths


def _payload(queue: DeliveryQueue, *, plan=None, enqueued=(), ran=()) -> Dict[str, Any]:
    index = build_result_index(_index_paths(queue))
    batch = gui_hooks.batch_view(queue, index=index)
    result = gui_hooks.result_view(index)
    return {
        "schemaVersion": 1,
        "planPath": str(getattr(plan, "planPath", "") or ""),
        "batchId": getattr(plan, "batchId", "") or queue.machine_report().get("batchId", ""),
        "enqueued": [
            item.to_dict() if hasattr(item, "to_dict") else {"jobId": getattr(item, "jobId", "")}
            for item in enqueued
        ],
        "ran": [getattr(item, "jobId", "") for item in ran],
        "queue": queue.machine_report(),
        "batch": batch.to_dict(),
        "result": result.to_dict(),
        "summary": batch.summary_lines() + result.summary_lines(),
        "memberRows": [row.to_dict() for row in batch.rows],
        # 结果页要能直接打开本轮产物：队列里各成员可用格式 + 结果索引里的包/索引文件
        "openTargets": _open_targets(queue, result),
    }


def _open_targets(queue: DeliveryQueue, result_view) -> List[Dict[str, Any]]:
    """可打开产物：优先队列内各成员可用格式，再补结果索引条目（去重保序）。"""
    targets: List[Dict[str, Any]] = []
    seen = set()
    jobs = getattr(queue, "jobs", None) or []
    for job in jobs:
        for item in list(getattr(job, "usable_results", lambda: [])() or []):
            path = str(getattr(item, "path", "") or "")
            if not path or path in seen:
                continue
            seen.add(path)
            targets.append({
                "kind": "artifact",
                "member": getattr(job, "memberName", "") or "",
                "format": getattr(item, "format", ""),
                "status": getattr(item, "status", ""),
                "path": path,
                "label": "{0}（{1}）".format(getattr(job, "memberName", ""), getattr(item, "format", "")),
            })
    for target in result_view.open_targets():
        data = target.to_dict()
        path = str(data.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        targets.append(data)
    return targets


__all__ = [
    "plan_preview", "run_plan_task", "retry_unfinished_task", "status_snapshot",
]