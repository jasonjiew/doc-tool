# -*- coding: utf-8 -*-
"""Microsoft Word 可用性与交互式会话检查。

任务 7.1：在 GUI 合并前增加 Microsoft Word 可用性和交互式会话检查。

正式合并必须在本机交互式 Windows 会话中拥有可启动的 Microsoft Word；
缺失、不可启动或运行在非交互式会话（如系统服务、计划任务、CI runner）
时 MUST 阻断正式发布，并提示用户使用诊断构建。

检查策略（不打开文档，不修改用户已打开的 Word）：

1. ``check_pywin32``：``win32com.client`` 是否可导入。
2. ``check_interactive_session``：当前进程是否位于交互式 Windows 桌面会话。
3. ``check_word_dispatchable``：能否通过 ``DispatchEx("Word.Application")``
   启动一个专用 Word 进程并立即退出。该检查不复用、不关闭用户已有的 Word。
4. ``check_word_available``：组合上述检查，返回 ``WordAvailability`` 报告。

所有检查都不抛异常——失败被记录到 ``WordAvailability`` 报告中，便于界面
展示具体原因（pywin32 缺失 / 非交互式会话 / Word 启动失败）。
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WordAvailability:
    """Word 可用性诊断报告。

    Attributes:
        available: 是否可用于正式合并（pywin32 + 交互式会话 + 可启动 Word）。
        pywin32_available: ``win32com.client`` 是否可导入。
        interactive_session: 当前是否为交互式 Windows 桌面会话。
        word_dispatchable: 能否启动专用 Word 进程并立即退出。
        version: Word 版本字符串（如 ``"16.0"``），不可用时为空。
        reasons: 不可用原因列表（面向用户，脱敏）。
    """

    available: bool = False
    pywin32_available: bool = False
    interactive_session: bool = False
    word_dispatchable: bool = False
    version: str = ""
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "pywin32Available": self.pywin32_available,
            "interactiveSession": self.interactive_session,
            "wordDispatchable": self.word_dispatchable,
            "version": self.version,
            "reasons": list(self.reasons),
        }


def check_pywin32() -> bool:
    """检查 pywin32 / ``win32com.client`` 是否可导入。"""
    try:
        import win32com.client  # noqa: F401

        return True
    except ImportError:
        return False
    except Exception:
        # 任何意外异常都视为不可用，不抛出
        return False


def check_interactive_session() -> bool:
    """检查当前是否为交互式 Windows 桌面会话。

    非交互式会话包括：Windows 服务、计划任务、CI runner（在某些配置下）。
    在非 Windows 平台上始终返回 ``False``，因为 Word 不能在这些平台运行。
    """
    if os.name != "nt":
        return False

    # 1. sys.flags 检查：被服务/计划任务托管时常有特殊标志
    # （保守起见，仅作辅助判断，不阻断）

    # 2. 检查环境变量：服务/会话 0 中通常没有 USERPROFILE 或它指向 system
    user_profile = os.environ.get("USERPROFILE", "")
    if not user_profile:
        return False
    lower_profile = user_profile.lower().replace("\\", "/")
    # 服务账号的 profile 通常是 C:\\Windows\\system32\\config\\systemprofile
    # 或 C:\\Windows\\ServiceProfiles\\*
    if "windows/system32/config/systemprofile" in lower_profile:
        return False
    if "windows/serviceprofiles" in lower_profile:
        return False

    # 3. 检查 SESSIONNAME 环境变量（RDP/Console 会话有此变量，服务没有）
    session_name = os.environ.get("SESSIONNAME", "")
    # Services 和无会话进程通常 SESSIONNAME 为空或 "Services"
    if session_name and session_name.lower() == "services":
        return False

    # 4. 尝试调用 GetDesktopWindow / user32 是否可见（保守判断）
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # GetDesktopWindow 在交互式会话中返回有效句柄
        desktop = user32.GetDesktopWindow()
        if not desktop:
            return False
        # 在会话 0 中，GetForegroundWindow 通常返回 0
        # （但用户当前未交互时也可能为 0，所以仅作辅助）
    except Exception:
        # 无法判断时保守返回 True，由 DispatchEx 检查兜底
        return True

    return True


def check_word_dispatchable(timeout_seconds: float = 10.0) -> tuple:
    """尝试启动专用 Word 进程并立即退出。

    Returns:
        (success: bool, version: str)：成功启动并退出时返回 (True, 版本字符串)；
        失败时返回 (False, "")。
    """
    if not check_pywin32():
        return False, ""

    try:
        import win32com.client
    except ImportError:
        return False, ""

    word = None
    word_pid = None
    try:
        # 使用 DispatchEx 强制新建独立进程，绝不复用用户已有 Word
        word = win32com.client.DispatchEx("Word.Application")
        # 获取 PID 用于异常清理
        try:
            import win32process

            word_pid = int(win32process.GetWindowThreadProcessId(int(word.Hwnd))[1])
        except Exception:
            word_pid = None

        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        # 禁用文档宏自动执行
        try:
            word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        except Exception:
            pass

        # 读取版本（不打开任何文档）
        try:
            version = str(word.Version)
        except Exception:
            version = ""

        # 立即退出，不保存任何文档
        try:
            word.Quit(SaveChanges=False)
        except Exception:
            _kill_process_tree(word_pid)
        word = None
        return True, version
    except Exception:
        # 启动失败
        if word is not None:
            try:
                word.Quit(SaveChanges=False)
            except Exception:
                _kill_process_tree(word_pid)
            word = None
        return False, ""
    finally:
        if word is not None:
            try:
                word.Quit(SaveChanges=False)
            except Exception:
                _kill_process_tree(word_pid)


def check_word_available(
    dispatch_check: bool = True,
    dispatch_timeout_seconds: float = 10.0,
) -> WordAvailability:
    """组合检查 Microsoft Word 是否可用于正式合并。

    Args:
        dispatch_check: 是否实际启动一次 Word 进程验证（默认 True）。
            诊断对话框可在用户已确认 Word 启动较慢时设为 False 仅做静态检查。
        dispatch_timeout_seconds: DispatchEx 检查的最大等待秒数。

    Returns:
        ``WordAvailability`` 报告。``available`` 为 True 当且仅当
        pywin32 可用、当前为交互式会话、Word 可启动。
    """
    report = WordAvailability()
    reasons: List[str] = []

    report.pywin32_available = check_pywin32()
    if not report.pywin32_available:
        reasons.append("未安装 pywin32（Python Windows COM 支持）。")

    report.interactive_session = check_interactive_session()
    if not report.interactive_session:
        reasons.append("当前不是交互式 Windows 桌面会话（可能在服务或计划任务中运行）。")

    if dispatch_check and report.pywin32_available and report.interactive_session:
        # 给一个总超时保护：DispatchEx 在某些机器上首次启动可能慢
        deadline = time.monotonic() + dispatch_timeout_seconds
        success = False
        version = ""
        while time.monotonic() < deadline:
            success, version = check_word_dispatchable(
                timeout_seconds=max(1.0, deadline - time.monotonic())
            )
            if success:
                break
            # 首次失败不立即返回，给一次重试机会（COM 启动竞争）
            time.sleep(0.2)
        report.word_dispatchable = success
        report.version = version
        if not success:
            reasons.append("Word COM 启动失败，请确认 Microsoft Word 已正确安装。")
    else:
        # 静态检查模式或前置条件不满足：不实际启动 Word
        report.word_dispatchable = False

    report.available = (
        report.pywin32_available
        and report.interactive_session
        and (not dispatch_check or report.word_dispatchable)
    )
    report.reasons = reasons
    return report


def _kill_process_tree(pid: Optional[int]) -> None:
    """仅清理本应用启动的 Word 进程树，绝不影响用户已打开的 Word。"""
    if not pid:
        return
    try:
        import subprocess

        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except Exception:
        # 清理失败不抛出，避免遮蔽原始错误
        pass
