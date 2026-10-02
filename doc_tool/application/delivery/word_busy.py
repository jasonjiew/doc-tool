# -*- coding: utf-8 -*-
"""跨进程 Word 占用标识（V3.2 32-B / 2.3）。

同一台机器上可能有多个本应用进程；Word 只能被一个进程稳定驱动。这里用一个
**用户级标记文件**记录“本应用某进程正在使用 Word”，其它进程据此把批次项转为
待刷新（可读结果照常保留），而不是等 Word 探测失败或互相抢占用。

标记带 TTL 与进程存活校验：过期或进程已退出的标记视为陈旧并可被接管，避免
崩溃后永久阻塞批次。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from doc_tool.application.content.writer import atomic_write

MARKER_NAME = "word-busy.json"
MARKER_SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 1800


def marker_path(root: Optional[Path] = None) -> Path:
    """标记文件位置（用户配置目录；可注入目录以便测试）。"""
    if root is not None:
        return Path(root) / MARKER_NAME
    try:
        from doc_tool.application.project_service import _config_dir

        return Path(_config_dir()) / MARKER_NAME
    except Exception:  # noqa: BLE001 - 配置目录不可用时退回用户主目录
        return Path.home() / ".doctool" / MARKER_NAME


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


@dataclass
class BusyState:
    """当前跨进程 Word 占用状态。"""

    busy: bool = False
    owner: str = ""
    pid: int = 0
    since: str = ""
    stale: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "busy": self.busy, "owner": self.owner, "pid": self.pid,
            "since": self.since, "stale": self.stale, "reason": self.reason,
        }


def _read(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = marker_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schemaVersion") != MARKER_SCHEMA_VERSION:
        return None
    return data


def status(root: Optional[Path] = None, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> BusyState:
    """读取当前占用状态；过期或进程已退出视为陈旧（可接管）。"""
    data = _read(root)
    if data is None:
        return BusyState()
    state = BusyState(
        busy=True,
        owner=str(data.get("owner") or ""),
        pid=int(data.get("pid") or 0),
        since=str(data.get("since") or ""),
    )
    try:
        started = datetime.fromisoformat(state.since) if state.since else _now()
    except ValueError:
        started = _now()
    expired = (_now() - started) > timedelta(seconds=max(1, int(ttl_seconds)))
    if expired or not _pid_alive(state.pid):
        state.busy = False
        state.stale = True
        state.reason = "标记已过期或持有进程已退出（可接管）"
    else:
        state.reason = "本应用另一进程正在使用 Word（{0}，pid {1}）".format(
            state.owner or "未命名进程", state.pid,
        )
    return state


def acquire(
    owner: str = "",
    *,
    root: Optional[Path] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    pid: Optional[int] = None,
) -> Tuple[bool, str]:
    """登记占用；已被其它存活进程占用时返回 ``(False, 原因)``。"""
    current = status(root, ttl_seconds=ttl_seconds)
    if current.busy and current.pid != (pid if pid is not None else os.getpid()):
        return False, current.reason
    payload = {
        "schemaVersion": MARKER_SCHEMA_VERSION,
        "owner": str(owner or "本应用进程"),
        "pid": int(pid if pid is not None else os.getpid()),
        "since": _now().isoformat(timespec="seconds"),
    }
    try:
        atomic_write(marker_path(root), json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError as exc:
        return False, "无法写入 Word 占用标记：{0}".format(exc)
    return True, ""


def release(*, root: Optional[Path] = None, owner: str = "") -> bool:
    """释放占用；标记属于其它进程且未失效时不删除。"""
    path = marker_path(root)
    data = _read(root)
    if data is None:
        return True
    current = status(root)
    if current.busy and current.pid != os.getpid():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def word_busy_probe(
    root: Optional[Path] = None,
    *,
    local_probe: Optional[Callable[[], Tuple[bool, str]]] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Callable[[], Tuple[bool, str]]:
    """构造 Word 探测：先看跨进程标记，再看本机 Word 是否可用。"""

    def _probe() -> Tuple[bool, str]:
        state = status(root, ttl_seconds=ttl_seconds)
        if state.busy:
            return False, state.reason
        probe = local_probe
        if probe is None:
            from doc_tool.application.delivery.queue import _default_word_probe

            probe = _default_word_probe
        return probe()

    return _probe


__all__ = [
    "MARKER_NAME", "MARKER_SCHEMA_VERSION", "DEFAULT_TTL_SECONDS", "BusyState",
    "marker_path", "status", "acquire", "release", "word_busy_probe",
]