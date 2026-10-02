# -*- coding: utf-8 -*-
"""运行环境自检：把「写不进去 / 读到密文」这类受限环境问题变成可执行的提示。

背景（父会话第二十九轮实测）：本机透明加密/杀软策略下，未受信任的冻结 exe 写文件会得到
``PermissionError(13)``、读仓库路径的 docx 会得到密文，而 CLI 只报出 E9000/E1001 这类
笼统错误。本模块提供不依赖 Qt 的探测，供 CLI ``env-check`` 与导入失败路径复用。
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ZIP_MAGIC = b"PK\x03\x04"

ADVICE_WRITE_DENIED = (
    "当前环境不允许本程序写入该目录：请把 DocTool.exe 加入透明加密/杀软信任列表，"
    "或改选用户目录下的其它位置"
)
ADVICE_READ_ENCRYPTED = (
    "读取到的是密文而不是 OOXML 内容：该路径的文件被透明加密客户端保护，"
    "请把 DocTool.exe 加入信任列表（或从受信任目录运行）后重试"
)
ADVICE_TARGET_EXISTS = "目标目录已存在：首次导入不会覆盖，请改项目名或目录"


@dataclass
class EnvProbeResult:
    """一次环境自检结果（机器可读，不含正文）。"""

    ok: bool = True
    checks: List[Dict[str, object]] = field(default_factory=list)
    advice: List[str] = field(default_factory=list)

    def add(self, kind: str, ok: bool, detail: str = "", advice: str = "") -> None:
        self.checks.append({"kind": kind, "ok": bool(ok), "detail": detail})
        if not ok:
            self.ok = False
            if advice and advice not in self.advice:
                self.advice.append(advice)

    def to_dict(self) -> Dict[str, object]:
        return {"ok": self.ok, "checks": list(self.checks), "advice": list(self.advice)}


def probe_write(directory: Optional[Path], *, result: Optional[EnvProbeResult] = None) -> EnvProbeResult:
    """探测目录可写性（真写一个临时文件再删除）。"""
    probe = result or EnvProbeResult()
    if directory is None:
        return probe
    target = Path(directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        probe.add("write", False, "{0}: {1}".format(type(exc).__name__, exc), ADVICE_WRITE_DENIED)
        return probe
    handle = None
    path = None
    try:
        fd, name = tempfile.mkstemp(prefix=".doc-tool-env-probe-", dir=str(target))
        handle = os.fdopen(fd, "wb")
        handle.write(b"doc-tool-env-probe")
        handle.close()
        handle = None
        path = Path(name)
        probe.add("write", True, "目录可写：{0}".format(target))
    except OSError as exc:
        probe.add("write", False, "{0}: {1}".format(type(exc).__name__, exc), ADVICE_WRITE_DENIED)
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass
    return probe


def probe_docx_read(path) -> EnvProbeResult:
    """探测 docx 是否可按 OOXML（ZIP）读取；密文会在这里被识别。"""
    probe = EnvProbeResult()
    if not path:
        return probe
    target = Path(path)
    if not target.is_file():
        probe.add("docx-read", False, "文件不存在：{0}".format(target))
        return probe
    try:
        with target.open("rb") as stream:
            head = stream.read(4)
    except OSError as exc:
        probe.add("docx-read", False, "{0}: {1}".format(type(exc).__name__, exc), ADVICE_READ_ENCRYPTED)
        return probe
    if head[:4] != ZIP_MAGIC:
        probe.add(
            "docx-read", False,
            "前 4 字节非 ZIP 签名（{0!r}），疑似被透明加密：" .format(head),
            ADVICE_READ_ENCRYPTED,
        )
        return probe
    probe.add("docx-read", True, "docx 可按 OOXML 读取")
    return probe


def diagnose_environment(*, directory=None, docx=None, target_exists=None) -> EnvProbeResult:
    """聚合自检：目标目录可写性 + docx 可读性 + 目标是否已存在。"""
    probe = EnvProbeResult()
    result = probe_write(directory, result=probe)
    if docx:
        docx_probe = probe_docx_read(docx)
        for item in docx_probe.checks:
            result.checks.append(item)
        for item in docx_probe.advice:
            if item not in result.advice:
                result.advice.append(item)
        if not docx_probe.ok:
            result.ok = False
    if target_exists:
        result.add("target", False, "目标目录已存在：{0}".format(target_exists), ADVICE_TARGET_EXISTS)
    return result


__all__ = [
    "ADVICE_READ_ENCRYPTED", "ADVICE_TARGET_EXISTS", "ADVICE_WRITE_DENIED",
    "EnvProbeResult", "diagnose_environment", "probe_docx_read", "probe_write",
]