# -*- coding: utf-8 -*-
"""冻结启动自愈：扩展模块导入失败时给出可见报错与日志（不再迁移到 %TEMP%）。

背景（2026-08 实测闭环总结，1.4.4 修订）
---------------------------------------
公司终端安全软件（火绒企业版、亿赛通 DocGuard 等）对未签名 exe 的加载拦截，
曾导致 ``PySide6`` 扩展模块（``.pyd``）加载失败，报
``DLL load failed while importing Shiboken: %1 不是有效的 Win32 应用程序``，
或 PyInstaller 引导程序报 ``Failed to start embedded python interpreter!``。

1.4.2 起采用「复制到 %TEMP% 全新随机目录再启动」的迁移自愈；实测发现该方案
在装有透明加密客户端（如 EsafeNet Cobra DocGuard）的机器上适得其反：
复制写入 %TEMP% 的 ``.pyd`` 会被加密客户端加密（典型症状：一批 .pyd 文件头
从 ``MZ`` 变为统一加密魔数、体积 +4096 字节），迁移副本同样损坏，
启动反而更不可靠。

1.4.4 起改为：
1. 分发产物全部经公司代码签名（随包 codesign.cer + 安装证书.cmd 导入信任），
   已签名 exe 原地启动不再被安全软件拦截，因此不再需要复制迁移；
2. 检测到 PySide6 导入失败且处于冻结态时：把诊断写入 ``DocTool-startup.log``
   （应用目录/候选根目录），并弹出系统消息框给出可执行处置指引
   （白名单 / 代码签名 / 回传日志），退出码 2——启动失败**不再静默**；
3. 非冻结态（源码运行）不介入，保持原有行为。

本模块只允许依赖标准库，绝不能 import Qt——它正是为了在 Qt 无法导入时工作。
"""

from __future__ import annotations

import os
import sys
import time
import traceback


def _message_box(title, text):
    """弹出阻塞式系统消息框；任何失败都静默降级（比如无桌面会话）。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def _is_ascii(path):
    try:
        path.encode("ascii")
        return True
    except (UnicodeEncodeError, AttributeError):
        return False


def _candidate_bases():
    """写日志的 ASCII 目录候选：%TEMP% 优先，中文用户名退回 Public。"""
    candidates = []
    temp = os.environ.get("TEMP")
    if temp and _is_ascii(temp):
        candidates.append(temp)
    public = os.environ.get("PUBLIC") or r"C:\Users\Public"
    if _is_ascii(public):
        candidates.append(public)
    home = os.path.expanduser("~")
    if _is_ascii(home):
        candidates.append(os.path.join(home, ".doctool_runtime"))
    return candidates


def _app_dir():
    """冻结态应用目录（onedir：DocTool.exe 所在目录，其与 _internal 同级）。"""
    return os.path.dirname(os.path.abspath(sys.executable))


def _versions():
    try:
        from doc_tool.domain.version import APP_VERSION

        return APP_VERSION
    except Exception:
        return "dev"


def _log_lines(lines, *paths):
    """把诊断日志尽力写入多个候选位置（忽略一切写入失败）。"""
    text = "\r\n".join(lines) + "\r\n"
    for path in paths:
        if not path:
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            continue


def _write_log(log):
    candidates = [os.path.join(_app_dir(), "DocTool-startup.log")]
    for base in _candidate_bases():
        candidates.append(os.path.join(base, "DocTool-startup.log"))
    _log_lines(log, *candidates)
    return candidates


def _failure_message(extra_lines):
    return (
        "Doc Tool 启动失败。\n\n"
        "本机安全软件拦截了程序组件的加载。\n"
        "请将 DocTool-startup.log 发给维护人员，并请 IT 在安全管理平台\n"
        "（如火绒终端安全管理中心）对 Doc Tool 加入信任/白名单，或联系维护\n"
        "人员获取经代码签名的版本。\n\n"
        "--- 详细 ---\n" + "\n".join(extra_lines)
    )


def handle_blocked_import(import_error):
    """PySide6 等扩展模块导入失败时的兜底：可见报错 + 日志。返回进程退出码。"""
    log = [
        "==== DocTool 启动诊断 {0} ====".format(time.strftime("%Y-%m-%d %H:%M:%S")),
        "version: {0}".format(_versions()),
        "executable: {0}".format(sys.executable),
        "frozen: {0}".format(getattr(sys, "frozen", False)),
        "cwd: {0}".format(os.getcwd()),
        "TEMP: {0}".format(os.environ.get("TEMP")),
        "import error: {0!r}".format(import_error),
    ]
    paths = _write_log(log)
    _message_box(
        "Doc Tool 启动失败",
        _failure_message(
            [
                "日志位置：",
                *[p for p in paths],
                "",
                "原始错误: {0}".format(import_error),
            ]
        ),
    )
    return 2


def report_startup_failure(exc):
    """冻结态 GUI 其它启动异常的兜底：可见报错 + 日志，返回退出码。"""
    detail = traceback.format_exception_only(type(exc), exc)[-1].strip()
    log = [
        "==== DocTool 启动诊断 {0} ====".format(time.strftime("%Y-%m-%d %H:%M:%S")),
        "version: {0}".format(_versions()),
        "executable: {0}".format(sys.executable),
        "",
        traceback.format_exc(),
    ]
    paths = _write_log(log)
    _message_box(
        "Doc Tool 启动失败",
        "Doc Tool 启动时发生异常。\n\n{0}\n\n日志位置：\n{1}\n\n请将日志发给维护人员。".format(
            detail, "\n".join(p for p in paths)
        ),
    )
    return 2
