# -*- coding: utf-8 -*-
"""本地项目锁：防止并发任务同时操作同一项目。

任务 5.1：实现带主机、PID、启动时间和任务类型的本地项目锁。
任务 5.2：实现活动锁拒绝、陈旧锁识别及受控清理流程。

锁文件位于项目 ``.state/project.lock``，格式为 JSON，包含：
- ``host``：持有锁的主机名
- ``pid``：持有锁的进程 PID
- ``startTime``：锁获取时间（ISO 8601 UTC）
- ``taskType``：任务类型（build/validate/import/refresh）
- ``appVersion``：应用版本（诊断用）

锁语义：
- 活动锁：同一主机且 PID 仍存活 → 拒绝新任务（``ProjectLockBusyError``）。
- 陈旧锁：PID 已不存在或不同主机 → 可受控清理后获取。
- 释放锁：任务完成后删除锁文件（不删除 ``.state`` 目录）。
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from doc_tool.domain.errors import ProjectLockBusyError
from doc_tool.domain.paths import ProjectPaths


# 任务类型常量
TASK_BUILD = "build"
TASK_VALIDATE = "validate"
TASK_IMPORT = "import"
TASK_REFRESH = "refresh"


@dataclass
class ProjectLock:
    """项目锁数据模型。

    Attributes:
        host: 持有锁的主机名。
        pid: 持有锁的进程 PID。
        start_time: 锁获取时间（ISO 8601 UTC 字符串）。
        task_type: 任务类型（build/validate/import/refresh）。
        app_version: 获取锁时的应用版本（诊断用）。
    """

    host: str
    pid: int
    start_time: str
    task_type: str
    app_version: str = ""

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "pid": self.pid,
            "startTime": self.start_time,
            "taskType": self.task_type,
            "appVersion": self.app_version,
        }

    @classmethod
    def from_dict(cls, data) -> "ProjectLock":
        # 锁文件被外部写成非对象 JSON（[]/"str"/42）时拒绝而非 AttributeError：
        # _read_lock 只捕获 TypeError/ValueError，裸 AttributeError 会让
        # acquire/release/inspect/force_clean 全部崩溃。
        if not isinstance(data, dict):
            raise ValueError("锁文件内容不是对象")
        return cls(
            host=str(data.get("host", "")),
            pid=int(data.get("pid", 0)),
            start_time=str(data.get("startTime", "")),
            task_type=str(data.get("taskType", "")),
            app_version=str(data.get("appVersion", "")),
        )

    def is_alive(self) -> bool:
        """判断持有锁的进程是否仍在本机存活。

        不同主机视为陈旧（无法跨主机验证 PID）。能取得进程创建时间时再与
        锁记录时间比对：持有进程退出后 PID 被系统回收给无关进程（PID 复用）
        时，进程仍"存活"但创建时间晚于锁获取时间 → 视为陈旧，避免项目
        永久 busy 只能手工清理。
        """
        if self.host != _current_host():
            return False
        if self.pid <= 0:
            return False
        if not _pid_alive(self.pid):
            return False
        created = _pid_start_time(self.pid)
        if created is None:
            return True  # 无法取得创建时间时保守视为存活
        locked_at = _parse_iso_time(self.start_time)
        if locked_at is None:
            return True
        # start_time is recorded with 1-second precision and is captured
        # before the lock file is written, while _pid_start_time is exact.
        # A live holder can therefore look like it was created slightly
        # AFTER its own lock timestamp (slow interpreter start, coarse
        # clock). Only treat a clearly later creation time as PID reuse,
        # otherwise two processes would both consider the lock stale and
        # both acquire it, breaking mutual exclusion.
        return (created - locked_at) <= _PID_REUSE_TOLERANCE_SECONDS


_CACHED_HOST: Optional[str] = None

# Tolerance (seconds) for PID-reuse detection. The lock timestamp has
# only 1-second precision and is taken before the lock file is written,
# so a live holder can look slightly newer than its own lock record.

_PID_REUSE_TOLERANCE_SECONDS = 5.0


def _current_host() -> str:
    """获取当前主机名（缓存，失败时返回空字符串）。

    ``socket.gethostname()`` 在某些 Windows 配置上可能因 DNS 解析而极慢，
    因此在进程生命周期内缓存结果。
    """
    global _CACHED_HOST
    if _CACHED_HOST is not None:
        return _CACHED_HOST
    _CACHED_HOST = os.environ.get("COMPUTERNAME", "")
    if not _CACHED_HOST:
        try:
            import socket  # 延迟导入：仅 COMPUTERNAME 不可用时才加载可能被拦的 _socket

            _CACHED_HOST = socket.gethostname()
        except OSError:
            _CACHED_HOST = ""
    return _CACHED_HOST


def _pid_alive(pid: int) -> bool:
    """判断指定 PID 的进程是否存活（跨平台 best-effort）。

    Windows 上 ``os.kill(pid, 0)`` 会调用 ``TerminateProcess``，可能误杀进程，
    因此改用 ``OpenProcess`` 仅查询进程句柄是否存在。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但无权限发信号 → 仍视为存活
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    """Windows 平台进程存活检查：用 OpenProcess 查询，不发送任何信号。"""
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        # 显式声明返回类型/参数类型：ctypes 默认把返回值当 32 位 c_int，
        # 64 位句柄会被截断（可能误判为 0 → 把活动锁当陈旧锁清理）。
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            # OpenProcess 返回 0 表示失败（进程不存在或无权限）
            # 区分：ERROR_ACCESS_DENIED 表示进程存在但无权限
            last_error = kernel32.GetLastError()
            if last_error == 5:  # ERROR_ACCESS_DENIED
                return True
            return False
        try:
            # 句柄获取成功 → 进程存在
            return True
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError):
        # ctypes 不可用或调用失败 → 回退到保守策略：视为存活
        return True


def _pid_start_time(pid: int) -> Optional[float]:
    """返回进程创建时间（epoch 秒）；Windows 无法查询时返回 None。

    供 ``is_alive`` 做 PID 复用防护：锁记录 startTime 之后创建的进程不是
    当初持锁的进程。非 Windows 平台无可靠跨进程创建时间来源，返回 None。
    """
    if os.name != "nt" or pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_t = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_t),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            if not ok:
                return None
            # FILETIME（100ns 自 1601-01-01）→ epoch 秒。
            ft = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return ft / 10_000_000.0 - 11644473600.0
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError):
        return None


def _parse_iso_time(value: str) -> Optional[float]:
    """把锁记录的时间戳（ISO 8601）解析为 epoch 秒；无法解析返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def acquire_lock(
    paths: ProjectPaths,
    task_type: str,
    app_version: str = "",
) -> ProjectLock:
    """获取项目锁，若存在活动锁则拒绝。

    若锁文件存在但持有进程已死亡（陈旧锁），则受控清理后获取新锁。

    Args:
        paths: 项目路径。
        task_type: 任务类型（build/validate/import/refresh）。
        app_version: 应用版本（诊断用）。

    Returns:
        新获取的 ``ProjectLock``。

    Raises:
        ProjectLockBusyError: 存在活动锁（同主机且 PID 存活）时。
    """
    lock_file = paths.lock_file
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    lock = ProjectLock(
        host=_current_host(),
        pid=os.getpid(),
        start_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        task_type=task_type,
        app_version=app_version,
    )

    # O_EXCL 保证全新锁只有一个创建者；操作系统级 guard 进一步串行化
    # “读取陈旧锁 -> 删除 -> 重建”。否则两个接管者可能都读到旧内容，
    # 后删除者会误删先接管者刚写入的新锁。
    with _acquire_guard(lock_file):
        try:
            _create_lock_exclusive(lock_file, lock)
            return lock
        except FileExistsError:
            existing = _read_lock(lock_file)
            if existing is not None and existing.is_alive():
                raise ProjectLockBusyError(
                    "项目正被另一个任务占用：{0}（PID {1}，任务 {2}）".format(
                        existing.host, existing.pid, existing.task_type or "未知"
                    ),
                    suggested_action="请等待当前任务完成，或确认该进程已退出后清理锁文件。",
                    details={
                        "lockHost": existing.host,
                        "lockPid": str(existing.pid),
                        "lockTask": existing.task_type,
                        "lockStartTime": existing.start_time,
                        "currentHost": _current_host(),
                        "currentPid": str(os.getpid()),
                    },
                )
            _remove_lock(lock_file)
            _create_lock_exclusive(lock_file, lock)
            return lock


def release_lock(paths: ProjectPaths) -> bool:
    """释放项目锁（删除锁文件）。

    仅当锁文件的 PID 与当前进程一致时才删除，防止误删他人持有的锁。
    返回是否成功释放。

    删除必须与 acquire/force_clean 一样在 ``_acquire_guard`` 内完成：
    否则并发 acquire 写入锁文件时，release 可能读到半截内容（existing
    None → 误删正在写入的锁，互斥失效，两个任务并发操作同一项目），
    或读后删掉他人刚接管的新锁。
    """
    lock_file = paths.lock_file
    with _acquire_guard(lock_file):
        if not lock_file.exists():
            return False
        existing = _read_lock(lock_file)
        if existing is None:
            # guard 已串行化写锁进程，此处读到损坏内容即文件确实损坏：
            # 清理后由后续 acquire 重建。
            _remove_lock(lock_file)
            return True
        if existing.pid == os.getpid() and existing.host == _current_host():
            _remove_lock(lock_file)
            return True
        # 锁不属于当前进程，不删除
        return False


def inspect_lock(paths: ProjectPaths) -> Optional[ProjectLock]:
    """读取当前锁状态（不获取也不释放），用于界面诊断。"""
    if not paths.lock_file.exists():
        return None
    return _read_lock(paths.lock_file)


def force_clean_stale_lock(paths: ProjectPaths) -> bool:
    """强制清理陈旧锁（仅在持有进程已死亡时）。

    用于界面「清理锁」操作。返回是否实际清理。
    """
    lock_file = paths.lock_file
    with _acquire_guard(lock_file):
        if not lock_file.exists():
            return False
        existing = _read_lock(lock_file)
        if existing is None:
            _remove_lock(lock_file)
            return True
        if not existing.is_alive():
            _remove_lock(lock_file)
            return True
        return False


# --- 锁文件读写（原子写入） ---


@contextmanager
def _acquire_guard(lock_file: Path):
    """串行化锁文件的检查/接管过程，进程退出时由 OS 自动释放。"""
    guard_file = lock_file.with_name(lock_file.name + ".guard")
    guard_file.parent.mkdir(parents=True, exist_ok=True)
    handle = open(guard_file, "a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        for _ in range(40):
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(0.025)
        if not acquired:
            raise ProjectLockBusyError(
                "项目锁正在发生并发变更，请稍后重试。",
                suggested_action="请等待当前任务完成后重试。",
                details={"currentPid": str(os.getpid())},
            )
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _create_lock_exclusive(lock_file: Path, lock: ProjectLock) -> None:
    """以排他创建方式写入锁文件；文件已存在时抛 ``FileExistsError``。"""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(lock.to_dict(), ensure_ascii=False)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(lock_file), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        _remove_lock(lock_file)
        raise


def _read_lock(lock_file: Path) -> Optional[ProjectLock]:
    """读取锁文件，损坏时返回 None（视为可清理）。"""
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    try:
        return ProjectLock.from_dict(data)
    except (TypeError, ValueError):
        return None


def _remove_lock(lock_file: Path) -> None:
    """删除锁文件（忽略不存在错误）。"""
    try:
        lock_file.unlink()
    except FileNotFoundError:
        pass
