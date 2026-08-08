# -*- coding: utf-8 -*-
"""后台任务事件桥接。

任务 6.8：实现后台任务事件桥接、阶段进度/心跳、安全取消和完成通知。

GUI 线程不阻塞：所有长操作（导入、构建、校验、合并）在后台线程执行，
通过 ``queue.Queue`` 把阶段事件推回 UI 线程，UI 线程用 ``root.after()``
轮询队列并更新界面。

取消语义：用户点击「取消」后，``CancellationToken.request_cancel()`` 被调用，
管线在下一个阶段边界安全停止（临界区操作不受影响）。
"""

from __future__ import annotations

import os
import queue
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from doc_tool.domain.cancellation import CancellationToken
from doc_tool.domain.errors import CancelledError


# 轮询间隔（毫秒）：UI 线程检查事件队列的频率。
POLL_INTERVAL_MS = 100


@dataclass
class TaskEvent:
    """后台任务推送给 UI 的事件。"""

    kind: str  # started/stage/succeeded/failed/cancelled/progress/log
    stage: str = ""
    status: str = ""
    detail: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    progress: Optional[int] = None  # 0-100，None 表示不确定


@dataclass
class TaskSpec:
    """后台任务规格。"""

    name: str  # 任务名称（import/build/validate/merge）
    target: Callable[..., Any]  # 执行函数
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)


class TaskRunner:
    """后台任务执行器：线程 + 队列 + 取消。

    用法::

        runner = TaskRunner(root)
        runner.start(TaskSpec("build", run_pipeline, args=(manifest, paths), ...),
                      on_done=lambda result: update_ui(result))
        # UI 线程轮询事件
        root.after(POLL_INTERVAL_MS, runner.poll)
        # 用户取消
        runner.cancel()
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._token: Optional[CancellationToken] = None
        self._event_queue: queue.Queue[TaskEvent] = queue.Queue()
        self._on_done: Optional[Callable[[Any], None]] = None
        self._on_event: Optional[Callable[[TaskEvent], None]] = None
        self._result: Any = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_cancelled(self) -> bool:
        return self._token is not None and self._token.is_cancelled

    def start(
        self,
        spec: TaskSpec,
        on_event: Optional[Callable[[TaskEvent], None]] = None,
        on_done: Optional[Callable[[Any], None]] = None,
    ) -> bool:
        """启动后台任务。若已有任务在运行则返回 False。"""
        if self._is_running:
            return False
        self._token = CancellationToken()
        self._on_done = on_done
        self._on_event = on_event
        self._result = None
        self._is_running = True
        self._event_queue.put(TaskEvent(kind="started", stage=spec.name))

        self._thread = threading.Thread(
            target=self._run,
            args=(spec, self._token),
            daemon=True,
            name="doc-tool-task",
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        """请求取消当前任务（安全：在阶段边界生效）。"""
        if self._token is not None:
            self._token.request_cancel()

    def poll(self) -> None:
        """UI 线程调用：处理队列中的所有待处理事件。"""
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if self._on_event is not None:
                self._on_event(event)
            if event.kind in ("succeeded", "failed", "cancelled"):
                self._is_running = False
                if self._on_done is not None:
                    self._on_done(self._result)

    def _run(self, spec: TaskSpec, token: CancellationToken) -> None:
        """后台线程执行体。"""
        try:
            # 如果目标函数接受 cancel_token 参数，传入
            kwargs = dict(spec.kwargs)
            import inspect

            sig = inspect.signature(spec.target)
            if "cancel_token" in sig.parameters:
                kwargs["cancel_token"] = token
            if "app_version" in sig.parameters and "app_version" not in kwargs:
                from doc_tool.domain.version import APP_VERSION

                kwargs["app_version"] = APP_VERSION

            result = spec.target(*spec.args, **kwargs)
            self._result = result
            self._event_queue.put(TaskEvent(kind="succeeded", stage=spec.name))
        except CancelledError as exc:
            self._result = None
            self._event_queue.put(TaskEvent(
                kind="cancelled", stage=spec.name,
                detail=exc.user_message, error_code=exc.code,
            ))
        except Exception as exc:
            self._result = None
            detail = str(exc)[:200]
            self._event_queue.put(TaskEvent(
                kind="failed", stage=spec.name,
                detail=detail,
                error_code=getattr(exc, "code", "E9000"),
            ))

    def drain_events(self) -> List[TaskEvent]:
        """排空事件队列（测试用）。"""
        events: List[TaskEvent] = []
        while True:
            try:
                events.append(self._event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def join(self, timeout: Optional[float] = None) -> None:
        """等待后台线程结束（测试用）。"""
        if self._thread is not None:
            self._thread.join(timeout=timeout)
