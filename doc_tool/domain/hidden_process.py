# -*- coding: utf-8 -*-
"""Windows 静默子进程：避免 GUI 反复弹出黑色控制台窗口。

PyInstaller ``--windowed`` 构建没有控制台，直接 ``subprocess.run(["git", ...])``
会为每条命令创建一个可见的 conhost 窗口。打开项目时检测改动、读取分支、取基线
会连续执行多条 git 命令，表现为“一直弹黑窗”。

用法：在 GUI 入口调用一次 :func:`install_windows_no_window_defaults`，之后所有
``subprocess`` 子进程默认带 ``CREATE_NO_WINDOW``；调用方显式传入
``creationflags`` 时以调用方为准（例如升级器的 DETACHED_PROCESS）。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

#: Win32 ``CREATE_NO_WINDOW``；3.7+ 的 ``subprocess`` 也有同名常量。
CREATE_NO_WINDOW = 0x08000000

_installed = False
_original_popen = None


def with_no_window(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """给 kwargs 补上静默参数（不覆盖调用方已显式给出的 ``creationflags``）。"""
    merged = dict(kwargs)
    if os.name != "nt":
        return merged
    merged.setdefault("creationflags", CREATE_NO_WINDOW)
    return merged


def install_windows_no_window_defaults() -> bool:
    """包装 ``subprocess.Popen``，让本进程创建的控制台子进程不再弹窗。

    只包装一次；``subprocess.run``/``call``/``check_output`` 都以 ``Popen`` 为
    底层，因此一处包装即可覆盖全部调用点（含第三方库）。
    """
    global _installed, _original_popen
    if _installed or os.name != "nt":
        return False
    _installed = True
    _original_popen = subprocess.Popen

    original_popen = _original_popen

    def popen(*args, **kwargs):
        return original_popen(*args, **with_no_window(kwargs))

    subprocess.Popen = popen  # type: ignore[assignment]
    return True


def uninstall_no_window_defaults() -> None:
    """撤销安装（供测试隔离使用；应用运行时不需要调用）。"""
    global _installed, _original_popen
    if _original_popen is not None:
        subprocess.Popen = _original_popen  # type: ignore[assignment]
    _installed = False
    _original_popen = None


__all__ = [
    "CREATE_NO_WINDOW",
    "install_windows_no_window_defaults",
    "uninstall_no_window_defaults",
    "with_no_window",
]
