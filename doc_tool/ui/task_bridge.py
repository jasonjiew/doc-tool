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

import queue
import threading
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
    run_id: int = 0  # 单次运行标识，用于隔离超时后迟到的后台事件


@dataclass
class TaskSpec:
    """后台任务规格。"""

    name: str  # 任务名称（import/build/validate/merge）
    target: Callable[..., Any]  # 执行函数
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    # 最大运行时长（秒）。超过则由看门狗发布 failed(E9009) 事件并解锁 UI，
    # 避免后台线程卡死（如 Word COM 挂起）导致界面永久锁死。daemon 线程
    # 无法被强杀，看门狗只能保证 UI 不被单点任务拖死；真正卡死的内核仍
    # 会在下次进程退出时回收。None 表示不设看门狗。
    timeout_seconds: Optional[float] = None


# 看门狗默认超时（秒）：正式合并含 Word 刷新，留足余量。
DEFAULT_TASK_TIMEOUT_SECONDS = 1800

# 看门狗超时稳定错误码。
ERR_WATCHDOG_TIMEOUT = "E9009"


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
        # 看门狗：超时时间戳（time.monotonic 基准）。None 表示不启用。
        self._watchdog_deadline: Optional[float] = None
        self._watchdog_fired = False
        # 当前运行中的任务名（看门狗事件归属）。start 时设置。
        self._spec_name: str = ""
        # 每次 start 递增；后台线程只能写入自己的运行结果和事件。
        self._run_generation = 0
        self._active_run_id = 0
        self._results: Dict[int, Any] = {}

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
        self._watchdog_fired = False
        self._spec_name = spec.name
        self._run_generation += 1
        run_id = self._run_generation
        self._active_run_id = run_id
        timeout = spec.timeout_seconds
        if timeout is not None and timeout > 0:
            import time as _time

            self._watchdog_deadline = _time.monotonic() + float(timeout)
        else:
            self._watchdog_deadline = None
        self._event_queue.put(
            TaskEvent(kind="started", stage=spec.name, run_id=run_id)
        )

        self._thread = threading.Thread(
            target=self._run,
            args=(spec, self._token, run_id),
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
        # 先看是否有队列终态事件；若后台线程卡死不发事件，则由看门狗兜底。
        drained_terminal = False
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if event.run_id != self._active_run_id:
                # 超时线程可能在新任务启动后才返回；其事件不得污染当前运行。
                self._results.pop(event.run_id, None)
                continue
            if self._on_event is not None:
                self._on_event(event)
            if event.kind in ("succeeded", "failed", "cancelled"):
                self._is_running = False
                self._watchdog_deadline = None
                drained_terminal = True
                self._result = self._results.pop(event.run_id, None)
                if self._on_done is not None:
                    self._on_done(self._result)
                break
        if not drained_terminal and self._is_running and self._watchdog_deadline is not None:
            import time as _time

            if _time.monotonic() >= self._watchdog_deadline and not self._watchdog_fired:
                self._watchdog_fired = True
                self._is_running = False
                self._watchdog_deadline = None
                # 请求取消（对支持阶段边界取消的任务友好）。
                if self._token is not None:
                    self._token.request_cancel()
                event = TaskEvent(
                    kind="failed",
                    stage=self._spec_name,
                    detail="任务运行超时，已强制结束 UI 跟踪。",
                    error_code=ERR_WATCHDOG_TIMEOUT,
                    run_id=self._active_run_id,
                )
                if self._on_event is not None:
                    self._on_event(event)
                if self._on_done is not None:
                    self._on_done(None)
                # 立即切换到一个无工作线程的代际，使超时线程随后返回的终态
                # 被视为旧事件；否则它会再次触发 on_done。
                self._run_generation += 1
                self._active_run_id = self._run_generation
        # 当未设置看门狗且后台无事件时，没有任何兜底；这是无 timeout 时的预期行为。

    def _run(
        self,
        spec: TaskSpec,
        token: CancellationToken,
        run_id: int,
    ) -> None:
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
            if "on_event" in sig.parameters and "on_event" not in kwargs:
                def _push_event(ev):
                    self._event_queue.put(
                        TaskEvent(
                            kind="stage",
                            stage=getattr(ev, "stage", str(ev)),
                            status=getattr(ev, "status", ""),
                            detail=getattr(ev, "detail", ""),
                            metrics=getattr(ev, "metrics", {}),
                            run_id=run_id,
                        )
                    )
                kwargs["on_event"] = _push_event

            result = spec.target(*spec.args, **kwargs)
            self._results[run_id] = result
            terminal = TaskEvent(
                kind="succeeded", stage=spec.name, run_id=run_id
            )
            if result is False:
                terminal = TaskEvent(
                    kind="failed",
                    stage=spec.name,
                    detail="操作返回未通过。",
                    run_id=run_id,
                )
            elif hasattr(result, "success") and not bool(result.success):
                last = getattr(result, "last_stage", None)
                error_code = getattr(result, "error_code", None)
                kind = "cancelled" if error_code == "E5003" else "failed"
                terminal = TaskEvent(
                    kind=kind,
                    stage=spec.name,
                    detail=getattr(last, "detail", "") if last is not None else "",
                    error_code=error_code,
                    run_id=run_id,
                )
            self._event_queue.put(terminal)
        except CancelledError as exc:
            self._results[run_id] = None
            self._event_queue.put(TaskEvent(
                kind="cancelled", stage=spec.name,
                detail=exc.user_message, error_code=exc.code,
                run_id=run_id,
            ))
        except Exception as exc:
            self._results[run_id] = None
            detail = str(exc)[:200]
            self._event_queue.put(TaskEvent(
                kind="failed", stage=spec.name,
                detail=detail,
                error_code=getattr(exc, "code", "E9000"),
                run_id=run_id,
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
