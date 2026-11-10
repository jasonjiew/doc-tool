# -*- coding: utf-8 -*-
"""启动环境快照：把“组员机器到底是什么环境”变成日志第一页可核对的事实。

覆盖范围（对应报障时最常缺的信息）：

- 应用：版本、提交、运行形态（源码/打包）、进程、路径、工作目录；
- 系统：Windows 版本、位数、CPU、是否管理员、是否交互式桌面会话；
- Python：解释器版本与路径、文件系统编码；
- Qt/PySide6：PySide6/Qt 版本、QtWebEngine 模块与运行件、离线预览资源、
  兼容模式开关；
- Office：Microsoft Word 可用性、Word.Application CLSID（是否被 WPS 接管）、
  WPS 安装痕迹、pywin32；
- Git：可用性、版本、全局凭据助手。

本模块不在导入期引入 Qt（``find_spec`` 只探测、不加载 QtWebEngine），
所有采集项独立兜底：任何一项探测失败只影响该行，不会抛到调用方。
"""

from __future__ import annotations

import importlib.util
import locale
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


#: 快照章节顺序（格式化与日志阅读顺序一致）。
SECTION_ORDER: Tuple[str, ...] = ("应用", "系统", "Python", "Qt/PySide6", "Office", "Git")

#: 与 preview_diagnostic 保持一致的必需离线资源。
_PREVIEW_RESOURCES: Tuple[str, ...] = (
    "preview.html",
    "markdown-it.min.js",
    "mermaid.min.js",
)


def _safe(callable_obj, default: str = "未知") -> str:
    """执行单项探测；异常转成可读的一行，避免快照整体失败。"""
    try:
        value = callable_obj()
    except Exception as exc:  # noqa: BLE001 - 诊断必须兜住一切
        text = "{0}: {1}".format(type(exc).__name__, exc)
        return text[:200]
    if value is None:
        return default
    return str(value)


def _sanitize_path(value: object) -> str:
    """把用户主目录替换为 ``~``（日志外发时少暴露用户名）。"""
    text = str(value or "")
    try:
        home = str(Path.home())
    except Exception:  # noqa: BLE001
        return text
    if home and text.lower().startswith(home.lower()):
        return "~" + text[len(home):]
    return text


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _is_admin() -> str:
    if os.name != "nt":
        return "否（非 Windows）"
    try:
        import ctypes

        return "是" if ctypes.windll.shell32.IsUserAnAdmin() else "否"
    except Exception as exc:  # noqa: BLE001
        return "未知（{0}）".format(type(exc).__name__)


def _windows_version() -> str:
    if os.name != "nt":
        return platform.platform()
    try:
        info = sys.getwindowsversion()
        return "Windows {0}.{1}.{2}".format(info.major, info.minor, info.build)
    except Exception:  # noqa: BLE001
        return platform.platform()


def _interactive_session() -> str:
    try:
        from doc_tool.application.word_check import check_interactive_session

        return "是" if check_interactive_session() else "否"
    except Exception as exc:  # noqa: BLE001
        return "未知（{0}）".format(type(exc).__name__)


# ---------------------------------------------------------------------------
# 各章节
# ---------------------------------------------------------------------------


def _app_section() -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        from doc_tool.domain.version import get_build_info

        info = get_build_info()
    except Exception as exc:  # noqa: BLE001
        info = {"error": "{0}: {1}".format(type(exc).__name__, exc)}
    return {
        "版本": info.get("appVersion", "unknown"),
        "提交": info.get("commit", "unknown"),
        "构建来源": info.get("buildSource", "unknown"),
        "构建时间": info.get("buildTime", "unknown"),
        "运行形态": "打包 EXE" if _is_frozen() else "源码运行",
        "进程 ID": str(os.getpid()),
        "可执行文件": _sanitize_path(sys.executable),
        "工作目录": _sanitize_path(os.getcwd()),
    }


def _system_section() -> Dict[str, str]:
    return {
        "Windows": _windows_version(),
        "平台": platform.platform(),
        "64 位": "是" if sys.maxsize > 2 ** 32 else "否",
        "架构": platform.machine() or "未知",
        "CPU 核数": str(os.cpu_count() or "未知"),
        "管理员权限": _is_admin(),
        "交互式会话": _interactive_session(),
        "默认编码": locale.getpreferredencoding(False),
    }


def _python_section() -> Dict[str, str]:
    return {
        "版本": platform.python_version(),
        "实现": platform.python_implementation(),
        "解释器": _sanitize_path(sys.executable),
        "文件系统编码": sys.getfilesystemencoding(),
    }


def _webengine_process_path() -> Optional[Path]:
    """定位 QtWebEngineProcess.exe（源码态在 PySide6/Qt/bin，打包态在 _internal）。"""
    candidates: List[Path] = []
    try:
        import PySide6

        base = Path(getattr(PySide6, "__file__", "") or "").parent
        candidates.append(base / "Qt" / "bin" / "QtWebEngineProcess.exe")
        candidates.append(base / "QtWebEngineProcess.exe")
    except Exception:  # noqa: BLE001
        pass
    candidates.append(Path(sys.executable).resolve().parent / "_internal" / "PySide6" / "QtWebEngineProcess.exe")
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "PySide6" / "QtWebEngineProcess.exe")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _module_available(name: str) -> str:
    """只探测、不导入：避免启动阶段把 QtWebEngine 整套加载进来。"""
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:  # noqa: BLE001 - 父包缺失等
        return "不可用（{0}）".format(type(exc).__name__)
    return "可导入" if spec is not None else "缺失"


def _qt_section() -> Dict[str, str]:
    section: Dict[str, str] = {}
    try:
        import PySide6

        section["PySide6"] = str(getattr(PySide6, "__version__", "未知"))
    except Exception:  # noqa: BLE001
        section["PySide6"] = "未安装"
    try:
        from PySide6.QtCore import qVersion

        section["Qt"] = str(qVersion())
    except Exception:  # noqa: BLE001
        section["Qt"] = "未知"
    for module in (
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
    ):
        section[module.rsplit(".", 1)[-1]] = _module_available(module)

    process_path = _webengine_process_path()
    section["WebEngine 进程"] = (
        "存在（{0}）".format(_sanitize_path(process_path)) if process_path else "缺失"
    )

    try:
        from doc_tool.application.preview_diagnostic import (
            compat_mode_enabled,
            resource_directory,
        )

        resource_dir = resource_directory()
        missing = [name for name in _PREVIEW_RESOURCES if not (resource_dir / name).is_file()]
        section["离线预览资源"] = "齐全" if not missing else "缺失：{0}".format("、".join(missing))
        section["兼容模式"] = "已启用" if compat_mode_enabled() else "未启用"
    except Exception as exc:  # noqa: BLE001
        section["离线预览资源"] = "未知（{0}）".format(type(exc).__name__)
    return section


def _wps_installed() -> str:
    if os.name != "nt":
        return "未知（非 Windows）"
    try:
        import winreg

        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Kingsoft\Office"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Kingsoft\Office"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Kingsoft\Office"),
        )
        for root, path in locations:
            try:
                with winreg.OpenKey(root, path):
                    return "已安装（注册表存在）"
            except OSError:
                continue
    except Exception as exc:  # noqa: BLE001
        return "未知（{0}）".format(type(exc).__name__)
    return "未检测到"


def _office_section() -> Dict[str, str]:
    section: Dict[str, str] = {}
    try:
        from doc_tool.application.word_check import (
            check_word_available,
            word_progid_clsid,
        )

        report = check_word_available(dispatch_check=False)
        if report.available:
            section["Microsoft Word"] = "可用（版本 {0}）".format(report.version) if report.version else "可用"
        else:
            section["Microsoft Word"] = "不可用"
        section["pywin32"] = "已安装" if report.pywin32_available else "未安装"
        section["WPS 接管 Word.Application"] = "是" if report.wps_replacing_word else "否"
        clsid = word_progid_clsid()
        section["Word.Application CLSID"] = clsid or "未注册"
        if report.reasons:
            section["不可用原因"] = "；".join(str(reason) for reason in report.reasons)[:300]
    except Exception as exc:  # noqa: BLE001
        section["Office 检测"] = "失败（{0}: {1}）".format(type(exc).__name__, str(exc)[:160])
    section["WPS 安装痕迹"] = _safe(_wps_installed)
    return section


def _run_command(args: List[str], timeout: float = 6.0) -> Tuple[int, str]:
    """执行诊断命令；带超时与静默窗口，失败返回 ``(-1, 原因)``。"""
    from doc_tool.domain.hidden_process import with_no_window

    kwargs: Dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    try:
        completed = subprocess.run(args, **with_no_window(kwargs))
        return int(completed.returncode), str(completed.stdout or "").strip()
    except FileNotFoundError:
        return -1, "未找到命令（未安装或不在 PATH）"
    except subprocess.TimeoutExpired:
        return -1, "执行超时（>{0:.0f}s）".format(timeout)
    except OSError as exc:
        return -1, "{0}: {1}".format(type(exc).__name__, exc)


def _git_section() -> Dict[str, str]:
    code, output = _run_command(["git", "--version"])
    if code != 0:
        return {"Git": "不可用（{0}）".format(output or "未知原因")}

    section = {"Git": output.splitlines()[0] if output else "可用"}
    helper_code, helper = _run_command(
        ["git", "config", "--global", "--get", "credential.helper"]
    )
    if helper_code == 0 and helper:
        section["凭据助手"] = helper
    elif helper_code == 1:
        section["凭据助手"] = "未配置"
    else:
        section["凭据助手"] = "读取失败（{0}）".format(helper or "未知")
    return section


# ---------------------------------------------------------------------------
# 汇总与输出
# ---------------------------------------------------------------------------


def collect_environment_snapshot(
    *,
    include_office: bool = True,
    include_git: bool = True,
    include_qt: bool = True,
) -> Dict[str, Dict[str, str]]:
    """采集完整环境快照；每项独立兜底，任何环境都能返回可读结果。"""
    snapshot: Dict[str, Dict[str, str]] = {
        "应用": _app_section(),
        "系统": _system_section(),
        "Python": _python_section(),
    }
    if include_qt:
        snapshot["Qt/PySide6"] = _qt_section()
    if include_office:
        snapshot["Office"] = _office_section()
    if include_git:
        snapshot["Git"] = _git_section()
    return snapshot


def format_environment_snapshot(
    snapshot: Optional[Dict[str, Dict[str, str]]] = None,
    *,
    timestamp: Optional[datetime] = None,
) -> str:
    """把快照渲染成“章节 + 键值”纯文本（日志、诊断包、剪贴板共用）。"""
    data = snapshot if snapshot is not None else collect_environment_snapshot()
    moment = timestamp or datetime.now()
    lines: List[str] = [
        "Doc Tool 环境快照",
        "生成时间：{0}".format(moment.strftime("%Y-%m-%d %H:%M:%S")),
        "",
    ]
    for section in SECTION_ORDER:
        if section not in data:
            continue
        lines.append("[{0}]".format(section))
        for key, value in data[section].items():
            lines.append("  {0}：{1}".format(key, value))
        lines.append("")
    for section, items in data.items():
        if section in SECTION_ORDER:
            continue
        lines.append("[{0}]".format(section))
        for key, value in items.items():
            lines.append("  {0}：{1}".format(key, value))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def log_environment_snapshot(
    snapshot: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict[str, str]]:
    """把环境快照写入全局日志（启动时调用一次，作为日志第一页）。"""
    import logging

    data = snapshot if snapshot is not None else collect_environment_snapshot()
    text = format_environment_snapshot(data)
    logging.getLogger("doc_tool.env").info("启动环境快照：\n%s", text)
    return data


__all__ = [
    "SECTION_ORDER",
    "collect_environment_snapshot",
    "format_environment_snapshot",
    "log_environment_snapshot",
]
