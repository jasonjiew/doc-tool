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
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

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
    def from_dict(cls, data: dict) -> "ProjectLock":
        return cls(
            host=str(data.get("host", "")),
            pid=int(data.get("pid", 0)),
            start_time=str(data.get("startTime", "")),
            task_type=str(data.get("taskType", "")),
            app_version=str(data.get("appVersion", "")),
        )

    def is_alive(self) -> bool:
        """判断持有锁的进程是否仍在本机存活。

        不同主机视为陈旧（无法跨主机验证 PID）。
        """
        if self.host != _current_host():
            return False
        if self.pid <= 0:
            return False
        return _pid_alive(self.pid)


_CACHED_HOST: Optional[str] = None


def _current_host() -> str:
    """获取当前主机名（缓存，失败时返回空字符串）。

    ``socket.gethostname()`` 在某些 Windows 配置上可能因 DNS 解析而极慢，
    因此在进程生命周期内缓存结果。
    """
    global _CACHED_HOST
    if _CACHED_HOST is not None:
        return _CACHED_HOST
    try:
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
    """
    lock_file = paths.lock_file
    if not lock_file.exists():
        return False
    existing = _read_lock(lock_file)
    if existing is None:
        # 锁文件损坏，安全删除
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
