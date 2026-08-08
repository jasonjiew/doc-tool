# -*- coding: utf-8 -*-
"""阶段边界取消令牌。

任务 5.5：实现阶段边界取消令牌，并保护 Word 保存与原子发布临界区。

取消语义：
- 取消请求通过 ``CancellationToken.request_cancel()`` 发出（线程安全）。
- 取消仅在**阶段边界**（``check_cancel``）生效，不在阶段执行中途打断。
- **临界区保护**：Word 保存和原子发布是不可中断操作，进入临界区后
  ``check_cancel`` 不再抛出，直到临界区退出。这保证：
  - Word 进程不会因取消而留下损坏的临时文件或锁死的 DOCX。
  - 原子发布（``os.replace``）要么完整完成要么完全不执行，不会出现半发布状态。
- 取消后在下一个非临界区边界抛出 ``CancelledError``。

设计意图：用户点击「取消」后，管线在当前阶段完成后安全停止，而非粗暴杀死
正在进行 I/O 的内核调用。上次有效输出（若已构建成功）被保留。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

from doc_tool.domain.errors import CancelledError


class CancellationToken:
    """线程安全的取消令牌。

    使用方式::

        token = CancellationToken()
        # 另一个线程调用 token.request_cancel()
        token.check_cancel()  # 在阶段边界检查，若已取消则抛 CancelledError
        with token.critical_section():
            # 临界区内 check_cancel 不抛出
            do_atomic_publish()
        token.check_cancel()  # 临界区退出后若已取消则抛出
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._in_critical = threading.local()

    @property
    def is_cancelled(self) -> bool:
        """是否已收到取消请求。"""
        return self._cancelled.is_set()

    def request_cancel(self) -> None:
        """请求取消（线程安全，幂等）。

        取消不会立即中断当前阶段，而是在下一个非临界区边界生效。
        """
        self._cancelled.set()

    def check_cancel(self) -> None:
        """在阶段边界检查取消状态。

        若已取消且不在临界区内，抛出 ``CancelledError``。
        临界区内调用为空操作，保护 Word 保存与原子发布不被中断。
        """
        if not self._cancelled.is_set():
            return
        if getattr(self._in_critical, "depth", 0) > 0:
            return
        raise CancelledError(
            "任务已被取消。",
            suggested_action="可在安全阶段后重新启动任务；上次有效输出已保留。",
        )

    @contextmanager
    def critical_section(self) -> Generator[None, None, None]:
        """进入临界区，保护不可中断操作（Word 保存、原子发布）。

        临界区内 ``check_cancel`` 不抛出，确保操作完整执行。
        临界区退出后，若已取消则由调用方在下一个边界检查。
        """
        if not hasattr(self._in_critical, "depth"):
            self._in_critical.depth = 0
        self._in_critical.depth += 1
        try:
            yield
        finally:
            self._in_critical.depth -= 1

    def reset(self) -> None:
        """重置取消状态（用于令牌复用，通常不需要）。"""
        self._cancelled.clear()
