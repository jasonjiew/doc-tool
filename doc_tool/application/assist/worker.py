# -*- coding: utf-8 -*-
"""资料索引的后台分批构建（V3.3 1.3）。

界面检索本身允许“没有索引也能读文本”（坏缓存/无缓存回退），因此索引重建不该占用
编辑线程。本模块把索引构建包装成可放进既有 ``TaskRunner`` 的普通函数：分批、可取消、
可报进度，完成后即可让检索命中缓存（速度更快、状态为 fresh/rebuilt）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

DEFAULT_BATCH_SIZE = 40


@dataclass
class IndexStageEvent:
    """TaskRunner 可识别的阶段事件。"""

    stage: str = ""
    status: str = ""
    detail: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)


def build_index_task(
    project_root,
    *,
    cache_dir=None,
    refresh: bool = False,
    refresh_stale: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_event: Optional[Callable[[Any], None]] = None,
    cancel_token=None,
) -> Dict[str, Any]:
    """在后台构建/刷新资料索引；返回机器可读结果（不做界面操作）。

    ``on_event`` 与 ``cancel_token`` 由 ``TaskRunner`` 自动注入，因此可以直接作为
    ``TaskSpec.target`` 使用。
    """
    root = Path(project_root)

    def _emit(stage: str, detail: str = "", **metrics) -> None:
        if on_event is None:
            return
        try:
            on_event(IndexStageEvent(stage=stage, status="running", detail=detail, metrics=dict(metrics)))
        except Exception:  # noqa: BLE001 - 进度回调失败不影响构建
            pass

    _emit("index", "开始建立资料索引")
    from doc_tool.application.assist.service import build_assistant

    try:
        assistant = build_assistant(root, cache_dir=cache_dir)
    except TypeError:  # 兼容不接受 cache_dir 的旧签名
        assistant = build_assistant(root)
    service = getattr(assistant, "search_service", None)
    if service is None:
        return {"ok": False, "message": "该写作辅助服务不支持直接构建索引", "documents": 0}
    batches = {"count": 0}

    def _progress(done: int, total: int) -> None:
        batches["count"] += 1
        _emit("index", "已处理 {0}/{1}".format(done, total), done=done, total=total)

    status = service.ensure_index(
        refresh=bool(refresh),
        refresh_stale=bool(refresh_stale),
        cancel_token=cancel_token,
        progress=_progress,
        batch_size=max(1, int(batch_size or DEFAULT_BATCH_SIZE)),
    )
    pending = getattr(status, "pending", 0) if hasattr(status, "pending") else 0
    documents = len(getattr(service, "documents", {}) or {})
    _emit("index", "索引完成：{0} 份文档".format(documents), documents=documents)
    return {
        "ok": True,
        "projectRoot": str(root),
        "documents": documents,
        "cacheStatus": str(getattr(status, "cache_status", "") or ""),
        "skipped": list(getattr(status, "skipped", []) or [])[:10],
        "batches": batches["count"],
        "cancelled": bool(getattr(status, "cancelled", False)),
        "path": str(getattr(service, "cache_file", "") or ""),
    }


__all__ = ["DEFAULT_BATCH_SIZE", "IndexStageEvent", "build_index_task"]