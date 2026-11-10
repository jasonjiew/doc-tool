# -*- coding: utf-8 -*-
"""Qt 侧诊断钩子：Qt 告警入日志、未捕获异常提示、启动安装入口。

职责边界：
- 业务层（``doc_tool.application.app_logging``）只依赖标准库，负责落盘与钩子；
- 本模块负责“让组员看见”：把 Qt 的 qWarning/qCritical 转进同一份日志，并在
  未捕获异常时弹一次可读提示（日志路径 + 异常摘要），之后同类异常只记日志，
  避免异常风暴把界面弹满。

关闭提示的环境：``DOC_TOOL_HEADLESS_TEST`` / pytest / ``test_*.py`` 入口，
离屏自动化与 CI 不会因为弹窗阻塞。
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from PySide6.QtCore import QObject, QtMsgType, Signal, Slot, qInstallMessageHandler

from doc_tool.application import app_logging

_QT_LOGGER = logging.getLogger("qt")

_QT_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

_PREVIOUS_HANDLER = None
_NOTIFIER: Optional["_ExceptionNotifier"] = None


def _is_headless() -> bool:
    """是否处于自动化/离屏运行（不弹模态框）。"""
    if os.environ.get("DOC_TOOL_HEADLESS_TEST") or os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    argv0 = os.path.basename(sys.argv[0]).lower() if sys.argv else ""
    return "pytest" in argv0 or argv0.startswith("test_") or argv0.endswith("_test.py")


def _qt_message_handler(mode, context, message) -> None:  # noqa: ANN001 - Qt 回调签名
    """把 Qt 日志按级别写入 ``qt`` logger（默认不弹窗、不打断流程）。"""
    level = _QT_LEVELS.get(mode, logging.INFO)
    location = ""
    try:
        file_name = getattr(context, "file", "") or ""
        line_no = getattr(context, "line", 0) or 0
        if file_name:
            location = " ({0}:{1})".format(file_name, line_no)
    except Exception:  # noqa: BLE001 - 上下文对象不可用时只记录消息
        location = ""
    try:
        _QT_LOGGER.log(level, "%s%s", message, location)
    except Exception:  # noqa: BLE001 - 日志失败不得影响 Qt 事件循环
        pass


class _ExceptionNotifier(QObject):
    """跨线程安全的异常提示器：任意线程 emit，槽在主线程执行。"""

    triggered = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._shown = False
        # AutoConnection：从工作线程 emit 时自动排队到接收者（主线程）执行。
        self.triggered.connect(self._show_message)

    @Slot(str, str)
    def _show_message(self, title: str, text: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        try:
            QMessageBox.critical(None, title, text)
        except Exception:  # noqa: BLE001 - 提示失败不能再抛
            logging.getLogger("doc_tool.crash").exception("显示未捕获异常提示失败")


def _notify_unhandled(exc: BaseException, log_file) -> None:  # noqa: ANN001
    """异常钩子的通知回调：首次弹窗，后续只留日志。"""
    notifier = _NOTIFIER
    if notifier is None or _is_headless():
        return
    logger = logging.getLogger("doc_tool.crash")
    if notifier._shown:
        logger.info("未捕获异常再次出现，已只记录日志：%s", app_logging.format_exception_summary(exc))
        return
    notifier._shown = True

    location = str(log_file) if log_file else "（日志未启用）"
    summary = app_logging.format_exception_summary(exc)
    text = (
        "程序遇到未处理的异常，已把完整堆栈写入日志。\n\n"
        "异常：{0}\n\n"
        "日志文件：\n{1}\n\n"
        "请把日志文件（或「帮助 → 导出诊断日志包」生成的 ZIP）发给维护人员。"
    ).format(summary[:500], location)
    notifier.triggered.emit("Doc Tool 遇到未处理异常", text)


def install_qt_diagnostics(app=None) -> None:  # noqa: ANN001 - QApplication
    """安装 Qt 消息处理器与异常提示（在 QApplication 创建后调用）。"""
    global _PREVIOUS_HANDLER, _NOTIFIER

    if _PREVIOUS_HANDLER is None:
        try:
            _PREVIOUS_HANDLER = qInstallMessageHandler(_qt_message_handler) or True
        except Exception:  # noqa: BLE001 - 处理器安装失败不阻断启动
            _PREVIOUS_HANDLER = True

    if app is not None and _NOTIFIER is None:
        try:
            _NOTIFIER = _ExceptionNotifier()
        except Exception:  # noqa: BLE001 - 无 GUI 环境时仅落盘
            _NOTIFIER = None

    app_logging.install_exception_hooks(
        notify=_notify_unhandled if _NOTIFIER is not None else None
    )


def uninstall_qt_diagnostics() -> None:
    """恢复 Qt 消息处理器并卸载异常钩子（测试隔离用）。"""
    global _PREVIOUS_HANDLER, _NOTIFIER

    if _PREVIOUS_HANDLER not in (None, True):
        try:
            qInstallMessageHandler(_PREVIOUS_HANDLER)
        except Exception:  # noqa: BLE001
            pass
    _PREVIOUS_HANDLER = None
    _NOTIFIER = None
    app_logging.uninstall_exception_hooks()


__all__ = ["install_qt_diagnostics", "uninstall_qt_diagnostics"]
