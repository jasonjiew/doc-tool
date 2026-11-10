# -*- coding: utf-8 -*-
"""应用级全局日志：轮转文件、控制台回显与未捕获异常兜底。

定位与约束
----------
- 日志固定落盘 ``%APPDATA%\\DocTool\\logs\\doc-tool.log``（可用环境变量
  ``DOC_TOOL_LOG_DIR`` 覆盖目录，便于测试与便携分发）；单文件 5 MiB，
  保留 3 个历史备份（``doc-tool.log.1`` ～ ``.3``）。
- 本模块只依赖标准库：Qt 消息处理器与异常弹窗在
  ``doc_tool.ui.diagnostics_hooks``，避免业务层引入 Qt。
- 日志初始化失败绝不阻断启动：目录逐个回退（APPDATA → TEMP → 用户配置
  目录），全部不可写时退化为 ``NullHandler``，只影响“有没有日志”。

未捕获异常策略
--------------
``install_exception_hooks`` 覆盖 ``sys.excepthook``、``threading.excepthook``
和 ``sys.unraisablehook``：完整堆栈写入日志（含线程名与来源），然后调用
可选的 ``notify`` 回调（GUI 层用它弹窗）。日志记录本身失败也不会再抛出，
避免异常处理器把进程带崩。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from doc_tool.domain.branding import APP_PROGRAM_ID, USER_CONFIG_DIR_NAME

#: 当前应用日志文件名（与用户约定一致：%APPDATA%\DocTool\logs\doc-tool.log）。
LOG_FILENAME = "doc-tool.log"

#: 原生崩溃（QtWebEngine/显卡驱动等）记录文件，由 faulthandler 写入。
CRASH_LOG_FILENAME = "doc-tool-crash.log"

#: 单文件上限与备份数量：5 MiB × 3 份，绝不无限占用磁盘。
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3

#: 覆盖日志目录的环境变量（测试与便携分发使用）。
LOG_DIR_ENV = "DOC_TOOL_LOG_DIR"

_LOGGER = logging.getLogger(__name__)

_LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d [%(levelname)-7s] "
    "[pid:%(process)d %(threadName)s] %(name)s: %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class AppLoggingState:
    """一次日志初始化结果（供导出与诊断复用）。"""

    log_file: Optional[Path] = None
    level: int = logging.INFO
    max_bytes: int = DEFAULT_MAX_BYTES
    backup_count: int = DEFAULT_BACKUP_COUNT
    used_fallback_directory: bool = False
    handler: Optional[logging.Handler] = None
    console_handler: Optional[logging.Handler] = None
    crash_file: Optional[Path] = None

    @property
    def enabled(self) -> bool:
        return self.log_file is not None


_STATE: Optional[AppLoggingState] = None
_PREVIOUS_ROOT_LEVEL: Optional[int] = None
_CRASH_HANDLE = None
_CRASH_FILE: Optional[Path] = None

#: 未捕获异常通知回调：``notify(exception, log_file)``；GUI 层注入弹窗实现。
_NOTIFY: Optional[Callable[[BaseException, Optional[Path]], None]] = None

_HANDLING = threading.local()
_PREVIOUS_HOOKS: Dict[str, object] = {}


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------


def app_data_directory() -> Path:
    """应用数据目录：``%APPDATA%\\DocTool``（非 Windows 或缺失时按用户主目录推导）。"""
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / APP_PROGRAM_ID
    return Path.home() / "AppData" / "Roaming" / APP_PROGRAM_ID


def default_log_directory() -> Path:
    """默认日志目录（支持 ``DOC_TOOL_LOG_DIR`` 覆盖）。"""
    override = os.environ.get(LOG_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return app_data_directory() / "logs"


def default_log_file() -> Path:
    """默认日志文件绝对路径。"""
    return default_log_directory() / LOG_FILENAME


def _candidate_directories(explicit: Optional[Path] = None) -> List[Path]:
    """日志目录候选（按优先级去重）：显式参数 → 环境变量 → APPDATA → TEMP → 用户配置。"""
    candidates: List[Path] = []

    def add(path: Optional[Path]) -> None:
        if path is None:
            return
        try:
            resolved = Path(path)
        except (TypeError, ValueError):
            return
        if resolved not in candidates:
            candidates.append(resolved)

    add(Path(explicit) if explicit is not None else None)
    override = os.environ.get(LOG_DIR_ENV, "").strip()
    add(Path(override) if override else None)
    add(app_data_directory() / "logs")
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp:
        add(Path(temp) / APP_PROGRAM_ID / "logs")
    add(Path.home() / ".{0}".format(USER_CONFIG_DIR_NAME) / "logs")
    return candidates


def _probe_writable(directory: Path) -> bool:
    """真实写一个探针文件再删除，确认目录可用（企业终端常见“可建目录不可写”）。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".doc-tool-log-probe"
        with open(str(probe), "a", encoding="utf-8") as handle:
            handle.write("probe\n")
        probe.unlink()
        return True
    except OSError:
        return False


def ensure_log_directory(directory: Optional[Path] = None) -> Optional[Path]:
    """返回第一个真实可写的日志目录；都不可写时返回 ``None``（不抛异常）。"""
    for candidate in _candidate_directories(directory):
        if _probe_writable(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# 初始化 / 拆除
# ---------------------------------------------------------------------------


def _remove_installed_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if getattr(handler, "_doc_tool_app_handler", False):
            try:
                root.removeHandler(handler)
                handler.close()
            except Exception:  # noqa: BLE001 - 拆除旧 handler 不应阻断重新初始化
                pass


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)


def _default_console_enabled() -> bool:
    """源码运行且存在 stderr 时回显到控制台；冻结 GUI 没有控制台。"""
    if getattr(sys, "frozen", False):
        return False
    return sys.stderr is not None


def setup_app_logging(
    *,
    directory: Optional[Path] = None,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    console: Optional[bool] = None,
) -> AppLoggingState:
    """安装全局轮转文件日志；可重复调用（会替换上一轮安装的 handler）。

    Args:
        directory: 显式日志目录（测试用）；缺省按 :func:`_candidate_directories`
            逐个探测可写性。
        level: 根 logger 级别，默认 ``INFO``。
        max_bytes: 单文件上限，默认 5 MiB。
        backup_count: 历史备份数量，默认 3。
        console: 是否回显到控制台；``None`` 表示源码运行且 stderr 可用时开启。

    Returns:
        :class:`AppLoggingState`：即使目录不可写也会返回 ``enabled=False`` 的状态。
    """
    global _STATE, _PREVIOUS_ROOT_LEVEL

    root = logging.getLogger()
    _remove_installed_handlers(root)
    if _PREVIOUS_ROOT_LEVEL is None:
        _PREVIOUS_ROOT_LEVEL = root.level

    state = AppLoggingState(
        level=level, max_bytes=max_bytes, backup_count=backup_count
    )
    formatter = _build_formatter()

    chosen: Optional[Path] = None
    fallback_used = False
    candidates = _candidate_directories(directory)
    for index, candidate in enumerate(candidates):
        if not _probe_writable(candidate):
            continue
        chosen = candidate
        fallback_used = index > 0
        break

    if chosen is not None:
        try:
            handler = logging.handlers.RotatingFileHandler(
                str(chosen / LOG_FILENAME),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
                delay=False,
            )
            handler.setFormatter(formatter)
            handler.setLevel(level)
            handler._doc_tool_app_handler = True  # type: ignore[attr-defined]
            root.addHandler(handler)
            state.handler = handler
            state.log_file = chosen / LOG_FILENAME
            state.used_fallback_directory = bool(fallback_used)
        except OSError:
            chosen = None

    if chosen is None:
        # 全部候选不可写：挂 NullHandler，保证库代码里的 logger 调用不报错。
        null_handler = logging.NullHandler()
        null_handler._doc_tool_app_handler = True  # type: ignore[attr-defined]
        root.addHandler(null_handler)
        state.handler = null_handler

    if console if console is not None else _default_console_enabled():
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.setLevel(level)
        stream._doc_tool_app_handler = True  # type: ignore[attr-defined]
        root.addHandler(stream)
        state.console_handler = stream

    root.setLevel(level)
    logging.captureWarnings(True)

    _STATE = state

    if state.enabled:
        _LOGGER.info(
            "全局日志已启用：%s（%.1f MB × %d 份备份）",
            state.log_file,
            max_bytes / (1024 * 1024),
            backup_count,
        )
        if state.used_fallback_directory:
            _LOGGER.warning("默认日志目录不可写，已回退到：%s", state.log_file.parent)
    else:
        _LOGGER.error("所有候选日志目录均不可写，本次运行不落盘日志")
    return state


def uninstall_app_logging() -> None:
    """移除本模块安装的 handler 并恢复根 logger 级别（测试隔离用）。"""
    global _STATE, _PREVIOUS_ROOT_LEVEL

    root = logging.getLogger()
    _remove_installed_handlers(root)
    if _PREVIOUS_ROOT_LEVEL is not None:
        root.setLevel(_PREVIOUS_ROOT_LEVEL)
        _PREVIOUS_ROOT_LEVEL = None
    logging.captureWarnings(False)
    _STATE = None


def current_state() -> Optional[AppLoggingState]:
    """当前日志状态；未初始化时为 ``None``。"""
    return _STATE


def flush_logging() -> None:
    """刷新全部已安装 handler（导出日志包前调用，保证内存缓冲落盘）。"""
    for handler in list(logging.getLogger().handlers):
        try:
            handler.flush()
        except Exception:  # noqa: BLE001 - 刷新失败不影响导出
            pass


def log_files(directory: Optional[Path] = None) -> List[Path]:
    """按“当前 → 备份”顺序列出应用日志文件（导出诊断包用）。"""
    base = Path(directory) if directory is not None else (
        _STATE.log_file.parent if _STATE and _STATE.log_file else default_log_directory()
    )
    result: List[Path] = []
    current = base / LOG_FILENAME
    if current.is_file():
        result.append(current)
    backups: List[tuple] = []
    try:
        for item in base.glob(LOG_FILENAME + ".*"):
            suffix = item.name[len(LOG_FILENAME) + 1:]
            if suffix.isdigit():
                backups.append((int(suffix), item))
    except OSError:
        backups = []
    result.extend(item for _index, item in sorted(backups))
    crash = base / CRASH_LOG_FILENAME
    if crash.is_file():
        result.append(crash)
    return result


# ---------------------------------------------------------------------------
# 启动横幅与原生崩溃日志
# ---------------------------------------------------------------------------


def log_startup_banner() -> None:
    """记录启动横幅：版本、运行形态、进程、日志位置。"""
    try:
        from doc_tool.domain.version import get_build_info

        info = get_build_info()
    except Exception:  # noqa: BLE001 - 版本信息异常不得阻断启动
        info = {}

    logger = logging.getLogger("doc_tool.startup")
    logger.info("=" * 78)
    logger.info(
        "Doc Tool 启动 | 版本 %s | 提交 %s | %s | pid=%s",
        info.get("appVersion", "unknown"),
        info.get("commit", "unknown"),
        "打包 EXE" if info.get("frozen") == "true" else "源码运行",
        os.getpid(),
    )
    logger.info("可执行文件：%s", _sanitize_path(sys.executable))
    logger.info("工作目录：%s", _sanitize_path(os.getcwd()))
    if _STATE is not None and _STATE.log_file is not None:
        logger.info("日志文件：%s", _STATE.log_file)
    else:
        logger.warning("日志文件：未启用（目录不可写）")
    logger.info("=" * 78)


def enable_faulthandler(directory: Optional[Path] = None) -> Optional[Path]:
    """把原生崩溃（访问违例、栈溢出等）的堆栈写入 ``doc-tool-crash.log``。

    Python 层未捕获异常由 :func:`install_exception_hooks` 记录；QtWebEngine、
    显卡驱动造成的静默闪退只能靠 faulthandler。失败时静默返回 ``None``。
    """
    global _CRASH_HANDLE, _CRASH_FILE

    try:
        import faulthandler
    except ImportError:  # pragma: no cover - 标准库在常规构建中始终可用
        return None

    base = Path(directory) if directory is not None else (
        _STATE.log_file.parent if _STATE and _STATE.log_file else default_log_directory()
    )
    target = base / CRASH_LOG_FILENAME
    if _CRASH_HANDLE is not None:
        try:
            _CRASH_HANDLE.close()
        except OSError:
            pass
    try:
        base.mkdir(parents=True, exist_ok=True)
        handle = open(str(target), "a", encoding="utf-8", buffering=1)
    except OSError:
        return None

    try:
        faulthandler.enable(file=handle, all_threads=True)
    except Exception:  # noqa: BLE001 - 部分受限环境不支持
        try:
            handle.close()
        except OSError:
            pass
        return None

    _CRASH_HANDLE = handle
    _CRASH_FILE = target
    if _STATE is not None:
        _STATE.crash_file = target
    logging.getLogger("doc_tool.startup").info("原生崩溃日志：%s", target)
    return target


def disable_faulthandler() -> None:
    """关闭 faulthandler 并释放文件句柄（测试隔离用）。"""
    global _CRASH_HANDLE, _CRASH_FILE

    try:
        import faulthandler

        faulthandler.disable()
    except Exception:  # noqa: BLE001
        pass
    if _CRASH_HANDLE is not None:
        try:
            _CRASH_HANDLE.close()
        except OSError:
            pass
    _CRASH_HANDLE = None
    _CRASH_FILE = None


# ---------------------------------------------------------------------------
# 未捕获异常
# ---------------------------------------------------------------------------


def _sanitize_path(value: object) -> str:
    """把用户主目录替换为 ``~``，便于把日志发给他人时少暴露用户名。"""
    text = str(value or "")
    try:
        home = str(Path.home())
    except Exception:  # noqa: BLE001
        return text
    if home and text.lower().startswith(home.lower()):
        return "~" + text[len(home):]
    return text


def _record_unhandled(
    exc: BaseException,
    tb,
    *,
    source: str,
    thread_name: str = "",
) -> None:
    """把未捕获异常写入日志，并调用一次通知回调。"""
    if getattr(_HANDLING, "active", False):
        # 日志/通知自身又抛异常：绝不再递归。
        return
    _HANDLING.active = True
    log_file = _STATE.log_file if _STATE is not None else None
    try:
        logger = logging.getLogger("doc_tool.crash")
        logger.critical(
            "未捕获异常（%s%s）",
            source,
            " / 线程 {0}".format(thread_name) if thread_name else "",
            exc_info=(type(exc), exc, tb) if tb is not None else None,
        )
        if tb is None:
            # 某些 hook（如 unraisable）没有 traceback 对象，补一行异常类型即可。
            logger.critical("%s: %s", type(exc).__name__, exc)
        flush_logging()
        notify = _NOTIFY
        if notify is not None:
            try:
                notify(exc, log_file)
            except Exception:  # noqa: BLE001 - 通知失败不得再抛
                pass
    finally:
        _HANDLING.active = False


def _sys_excepthook(exc_type, exc, tb) -> None:  # noqa: ANN001 - 保持标准签名
    previous = _PREVIOUS_HOOKS.get("sys")
    if issubclass(exc_type, KeyboardInterrupt):
        if callable(previous):
            previous(exc_type, exc, tb)
        return
    _record_unhandled(exc, tb, source="主线程")


def _threading_excepthook(args) -> None:  # noqa: ANN001 - 标准 ExceptHookArgs
    exc = getattr(args, "exc_value", None)
    tb = getattr(args, "exc_traceback", None)
    thread_name = ""
    thread = getattr(args, "thread", None)
    if thread is not None:
        thread_name = getattr(thread, "name", "") or ""
    if exc is None:
        return
    _record_unhandled(exc, tb, source="后台线程", thread_name=thread_name)


def _unraisablehook(unraisable) -> None:  # noqa: ANN001 - 标准 UnraisableHookArgs
    exc = getattr(unraisable, "exc_value", None)
    if exc is None:
        return
    _record_unhandled(exc, getattr(unraisable, "exc_traceback", None), source="不可捕获异常")


def install_exception_hooks(
    notify: Optional[Callable[[BaseException, Optional[Path]], None]] = None,
) -> None:
    """安装全局未捕获异常钩子；``notify`` 供 GUI 层弹窗（可为 ``None``）。"""
    global _NOTIFY

    _NOTIFY = notify
    if "sys" not in _PREVIOUS_HOOKS:
        _PREVIOUS_HOOKS["sys"] = sys.excepthook
        _PREVIOUS_HOOKS["threading"] = threading.excepthook
        _PREVIOUS_HOOKS["unraisable"] = getattr(sys, "unraisablehook", None)
    sys.excepthook = _sys_excepthook
    threading.excepthook = _threading_excepthook
    setattr(sys, "unraisablehook", _unraisablehook)


def uninstall_exception_hooks() -> None:
    """恢复安装前的钩子（测试隔离用）。"""
    global _NOTIFY

    _NOTIFY = None
    if "sys" in _PREVIOUS_HOOKS:
        sys.excepthook = _PREVIOUS_HOOKS["sys"]  # type: ignore[assignment]
        threading.excepthook = _PREVIOUS_HOOKS["threading"]  # type: ignore[assignment]
        previous_unraisable = _PREVIOUS_HOOKS.get("unraisable")
        if previous_unraisable is not None:
            setattr(sys, "unraisablehook", previous_unraisable)
    _PREVIOUS_HOOKS.clear()


def format_exception_summary(exc: BaseException) -> str:
    """异常的一行摘要（弹窗与日志副标题用）。"""
    text = traceback.format_exception_only(type(exc), exc)
    return text[-1].strip() if text else type(exc).__name__


__all__ = [
    "AppLoggingState",
    "CRASH_LOG_FILENAME",
    "DEFAULT_BACKUP_COUNT",
    "DEFAULT_MAX_BYTES",
    "LOG_DIR_ENV",
    "LOG_FILENAME",
    "app_data_directory",
    "current_state",
    "default_log_directory",
    "default_log_file",
    "disable_faulthandler",
    "enable_faulthandler",
    "ensure_log_directory",
    "flush_logging",
    "format_exception_summary",
    "install_exception_hooks",
    "log_files",
    "log_startup_banner",
    "setup_app_logging",
    "uninstall_app_logging",
    "uninstall_exception_hooks",
]
