# -*- coding: utf-8 -*-
"""高保真预览诊断与兼容模式（不依赖 Qt 的诊断核心）。

背景：``QWebEngineView`` 初始化失败时，预览适配层只能捕获异常并降级为轻量
预览，用户既看不到原因，也没有修复入口。本模块把「缺什么」变成可核对的事实
和可执行的处置：

- 模块、离线资源、打包组件逐项实测，不靠猜；
- 区分源码运行与打包 EXE：前者可以 pip 补装，后者只能修复分发包或启用兼容
  模式（禁用 Chromium 沙箱/GPU 是企业管理终端上最常见的解法）；
- 兼容模式通过环境变量生效，必须在 ``QApplication`` 创建前设置，因此实现为
  「写配置 + 重启应用」，不能原地热切换。

本模块 MUST NOT 导入 Qt，便于在无界面环境下测试。
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.domain.branding import USER_CONFIG_DIR_NAME

#: 打包与 requirements.txt 锁定的 PySide6 版本（源码态补装用）。
PINNED_PYSIDE = "PySide6==6.8.3"

#: 高保真预览必需的 Qt 模块（任一缺失都会让构造直接失败）。
REQUIRED_MODULES: Tuple[str, ...] = (
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
)

#: 高保真预览必需的离线资源（相对 ``doc_tool/resources/web_preview``）。
REQUIRED_RESOURCES: Tuple[str, ...] = (
    "preview.html",
    "markdown-it.min.js",
    "mermaid.min.js",
)

#: 启用兼容模式时注入的环境变量。
COMPAT_ENV_KEY = "QTWEBENGINE_DISABLE_SANDBOX"
COMPAT_ENV: Dict[str, str] = {COMPAT_ENV_KEY: "1"}
COMPAT_FLAG = "--disable-gpu"
COMPAT_FLAGS_VAR = "QTWEBENGINE_CHROMIUM_FLAGS"

#: 测试可用 ``DOC_TOOL_HOME`` 覆盖用户配置目录，避免污染真实配置。
HOME_ENV_OVERRIDE = "DOC_TOOL_HOME"

_SETTINGS_FILENAME = "preview.json"


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------


def preview_settings_path() -> Path:
    """兼容模式配置文件的绝对路径。"""
    override = os.environ.get(HOME_ENV_OVERRIDE, "").strip()
    base = Path(override) if override else Path.home()
    config_dir = base / ".{0}".format(USER_CONFIG_DIR_NAME)
    return config_dir / _SETTINGS_FILENAME


def load_preview_settings(path: Optional[Path] = None) -> Dict[str, object]:
    """读取预览配置；文件缺失/损坏时返回空字典（不抛异常）。"""
    target = Path(path) if path is not None else preview_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_preview_settings(data: Dict[str, object], path: Optional[Path] = None) -> bool:
    """原子写入预览配置；失败返回 False（调用方按只读环境处理）。"""
    target = Path(path) if path is not None else preview_settings_path()
    payload = dict(data)
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    temporary = target.with_suffix(".json.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(str(temporary), str(target))
        return True
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        return False


def compat_mode_enabled(path: Optional[Path] = None) -> bool:
    """兼容模式是否已启用。"""
    return bool(load_preview_settings(path).get("compatMode"))


def set_compat_mode(enabled: bool, path: Optional[Path] = None) -> bool:
    """写入兼容模式开关。返回是否写入成功。"""
    data = dict(load_preview_settings(path))
    data["compatMode"] = bool(enabled)
    return save_preview_settings(data, path)


def compat_environment() -> Dict[str, str]:
    """兼容模式应注入的环境变量（保留用户已有 Chromium 参数）。"""
    values = dict(COMPAT_ENV)
    existing = os.environ.get(COMPAT_FLAGS_VAR, "").strip()
    flags = existing.split() if existing else []
    if COMPAT_FLAG not in flags:
        flags.append(COMPAT_FLAG)
    values[COMPAT_FLAGS_VAR] = " ".join(flags).strip()
    return values


def apply_compat_environment() -> Dict[str, str]:
    """在 QApplication 创建前注入兼容模式环境变量。

    返回实际写入的变量；兼容模式未启用时返回空字典。必须是幂等的：重复调用
    不会重复追加 Chromium 参数（见 :func:`compat_environment`）。
    """
    if not compat_mode_enabled():
        return {}
    applied = compat_environment()
    for key, value in applied.items():
        os.environ[key] = value
    return applied


# ---------------------------------------------------------------------------
# 诊断
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticReport:
    """一次高保真预览诊断的事实与建议。"""

    frozen: bool
    summary: str = ""
    checks: List[Tuple[str, str]] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    can_install: bool = False
    install_command: str = ""
    compat_mode: bool = False
    traceback_text: str = ""

    def to_text(self) -> str:
        """可复制、脱敏的诊断文本（不含正文与凭据）。"""
        lines = [
            "高保真预览诊断",
            "时间：{0}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "结论：{0}".format(self.summary),
            "",
            "检查项：",
        ]
        for name, status in self.checks:
            lines.append("- {0}：{1}".format(name, status))
        if self.actions:
            lines += ["", "建议处置："]
            lines.extend("- {0}".format(item) for item in self.actions)
        if self.install_command:
            lines += ["", "补装命令：", self.install_command]
        if self.traceback_text:
            lines += ["", "详细堆栈（供反馈）：", self.traceback_text.strip()]
        return "\n".join(lines)


def resource_directory() -> Path:
    """高保真预览离线资源目录。"""
    from doc_tool.resources import resource_root

    return Path(resource_root()) / "web_preview"


def _module_status(name: str) -> Tuple[bool, str]:
    """尝试导入一个 Qt 模块，返回 ``(是否成功, 说明)``。"""
    try:
        importlib.import_module(name)
        return True, "可导入"
    except Exception as exc:  # noqa: BLE001 - 诊断必须兜住一切导入错误
        text = "{0}: {1}".format(type(exc).__name__, str(exc)[:160])
        return False, "不可用（{0}）".format(text)


def _package_components(frozen: bool) -> List[Tuple[str, str]]:
    """打包态检查 Chromium 运行件是否齐全。"""
    if not frozen:
        return []
    candidates: List[Path] = []
    internal = Path(sys.executable).resolve().parent / "_internal" / "PySide6"
    candidates.append(internal)
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "PySide6")
    base = next((item for item in candidates if item.is_dir()), None)
    if base is None:
        return [("打包组件目录", "未找到 _internal/PySide6")]
    names = ("QtWebEngineProcess.exe", "Qt6WebEngineCore.dll")
    checks: List[Tuple[str, str]] = []
    for name in names:
        path = base / name
        checks.append(
            (
                "打包组件 {0}".format(name),
                "存在（{0:.1f} MB）".format(path.stat().st_size / (1024 * 1024))
                if path.is_file()
                else "缺失",
            )
        )
    resources = base / "resources"
    checks.append(
        (
            "Chromium 资源",
            "存在" if resources.is_dir() else "缺失（qtwebengine_resources.pak 等）",
        )
    )
    return checks


def _looks_like_module_error(error_text: str) -> bool:
    """原始异常是否属于模块/DLL 加载失败。"""
    text = str(error_text or "")
    lowered = text.lower()
    return (
        "importerror" in lowered
        or "modulenotfound" in lowered
        or "no module named" in lowered
        or "dll load failed" in lowered
        or "找不到指定的模块" in text
        or "不是有效的 win32" in lowered
    )


def collect_diagnostic(
    error_text: str = "",
    traceback_text: str = "",
) -> DiagnosticReport:
    """收集一次完整诊断。

    ``error_text`` 是预览适配层捕获到的原始异常文本；为空时按「未知原因」
    继续收集事实（仍能查出模块/资源/打包件状态）。
    """
    frozen = bool(getattr(sys, "frozen", False))
    report = DiagnosticReport(frozen=frozen, traceback_text=traceback_text or "")

    report.checks.append(("运行形态", "打包 EXE" if frozen else "源码运行"))
    report.checks.append(("Python", platform.python_version()))
    if error_text:
        report.checks.append(("原始异常", error_text[:300]))

    pyside_version = "未安装"
    try:
        import PySide6  # noqa: F401

        pyside_version = str(getattr(PySide6, "__version__", "未知"))
    except Exception as exc:  # noqa: BLE001 - 诊断兜底
        pyside_version = "导入失败（{0}）".format(type(exc).__name__)
    report.checks.append(("PySide6 版本", pyside_version))

    module_ok = True
    for name in REQUIRED_MODULES:
        ok, status = _module_status(name)
        module_ok = module_ok and ok
        report.checks.append(("模块 {0}".format(name.rsplit(".", 1)[-1]), status))

    resource_dir = resource_directory()
    resources_ok = True
    for name in REQUIRED_RESOURCES:
        path = resource_dir / name
        if path.is_file():
            report.checks.append(
                ("资源 {0}".format(name), "{0:.1f} KB".format(path.stat().st_size / 1024))
            )
        else:
            resources_ok = False
            report.checks.append(("资源 {0}".format(name), "缺失"))
    if not resources_ok:
        report.checks.append(("资源目录", str(resource_dir)))

    report.checks.extend(_package_components(frozen))

    report.compat_mode = compat_mode_enabled()
    report.checks.append(
        ("兼容模式", "已启用（禁用沙箱/GPU）" if report.compat_mode else "未启用")
    )

    # --- 给出结论与处置 ---
    report.actions = []
    if not module_ok and not frozen:
        report.summary = "缺少 QtWebEngine 组件：源码环境安装的是精简版 PySide6"
        report.can_install = True
        report.install_command = "{0} -m pip install {1}".format(
            sys.executable, PINNED_PYSIDE
        )
        report.actions.append("点击「一键安装」补装完整 PySide6，安装完成后重启应用")
        report.actions.append("公司内网无 pip 源时，改用离线安装包安装同一版本")
    elif not module_ok and frozen:
        report.summary = "分发包内的 QtWebEngine 组件不完整（解压中断或被安全软件隔离）"
        report.actions.append("重新完整解压安装包，确认 _internal/PySide6 下存在 QtWebEngineProcess.exe")
        report.actions.append("若文件存在仍报错，运行安装目录下的 diagnose.cmd 并把结果反馈")
    elif not resources_ok:
        report.summary = "离线预览资源缺失（preview.html / markdown-it / mermaid）"
        report.actions.append("重新完整解压或重新安装，不要只复制 DocTool.exe")
        report.actions.append("资源目录：{0}".format(resource_dir))
    elif _looks_like_module_error(error_text):
        # 初始化时确实报过模块/DLL 错误，但此刻复测已通过：多为临时占用或
        # 安全软件拦截，不能简单归因成"环境问题"。
        report.summary = "初始化时模块加载失败，当前复测已通过（可能是临时占用或被安全软件拦截）"
        report.actions.append("先完全退出并重新打开应用；仍失败再启用兼容模式")
        report.actions.append("把本诊断文本反馈给维护者，其中包含原始异常")
    else:
        report.summary = "组件齐全，失败发生在运行环境（沙箱/显卡/安全软件拦截子进程）"
        if report.compat_mode:
            report.actions.append("兼容模式已启用但仍失败：请把本诊断文本反馈给维护者")
            report.actions.append("可再用安装目录下的 diagnose.cmd 收集机器环境信息")
        else:
            report.actions.append("点击「启用兼容模式并重启」：禁用 Chromium 沙箱与 GPU 后重试")
            report.actions.append("若仍失败，确认不是以管理员身份运行，并检查 EDR 是否拦截 QtWebEngineProcess.exe")

    if traceback_text:
        report.actions.append("详细堆栈已附在诊断文本末尾，便于反馈")

    return report


__all__ = [
    "COMPAT_ENV",
    "COMPAT_ENV_KEY",
    "DiagnosticReport",
    "PINNED_PYSIDE",
    "REQUIRED_MODULES",
    "REQUIRED_RESOURCES",
    "apply_compat_environment",
    "collect_diagnostic",
    "compat_environment",
    "compat_mode_enabled",
    "load_preview_settings",
    "preview_settings_path",
    "resource_directory",
    "save_preview_settings",
    "set_compat_mode",
]
