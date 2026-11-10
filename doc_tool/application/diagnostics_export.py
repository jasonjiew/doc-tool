# -*- coding: utf-8 -*-
"""一键诊断日志包：把应用日志与环境快照打成一个 ZIP，交给维护人员定位。

包内结构（稳定，便于脚本与人工阅读）::

    DocTool-diagnostics-YYYYMMDD-HHMMSS.zip
    ├── README.txt          包内清单与发送说明
    ├── environment.txt     启动环境快照（系统/Python/Qt/Office/Git）
    ├── build-info.json     应用版本与构建元数据（机器可读）
    └── logs/
        ├── doc-tool.log    当前应用日志
        ├── doc-tool.log.1  历史备份（最多 3 份）
        └── doc-tool-crash.log  原生崩溃日志（若存在）

只打包“程序自己写下的诊断数据”，不读取项目正文；日志中可能包含项目路径、
文件名与错误堆栈，供维护人员定位，请只发给内部维护人员。
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from doc_tool.application import app_logging
from doc_tool.application.environment_snapshot import (
    collect_environment_snapshot,
    format_environment_snapshot,
)

#: 诊断包文件名前缀。
BUNDLE_PREFIX = "DocTool-diagnostics"


def default_bundle_directory() -> Path:
    """默认导出到桌面（兼容 OneDrive 重定向桌面），桌面不存在时退回用户主目录。"""
    candidates = []
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive:
        candidates.append(Path(onedrive) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return Path.home()


def bundle_filename(now: Optional[datetime] = None) -> str:
    """诊断包文件名（时间戳到秒，便于按报障时间对应）。"""
    moment = now or datetime.now()
    return "{0}-{1}.zip".format(BUNDLE_PREFIX, moment.strftime("%Y%m%d-%H%M%S"))


def _unique_path(path: Path) -> Path:
    """同名文件已存在时追加序号，绝不覆盖上一次的日志包。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 1000):
        candidate = path.with_name("{0}-{1}{2}".format(stem, index, suffix))
        if not candidate.exists():
            return candidate
    raise OSError("同名诊断包过多，请先清理：{0}".format(path.parent))


def _readme_text(
    *, created_at: datetime, app_version: str, log_names: list
) -> str:
    lines = [
        "Doc Tool 诊断日志包",
        "生成时间：{0}".format(created_at.strftime("%Y-%m-%d %H:%M:%S")),
        "应用版本：{0}".format(app_version or "unknown"),
        "",
        "包含内容：",
        "- environment.txt：启动环境快照（系统、Python、Qt/PySide6、Office、Git）",
        "- build-info.json：应用版本与构建元数据",
        "- logs/：应用运行日志（当前日志、历史备份、原生崩溃日志）",
    ]
    if log_names:
        lines.append("  本次打包日志：{0}".format("、".join(log_names)))
    else:
        lines.append("  本次没有找到应用日志文件（可能尚未启用全局日志）。")
    lines += [
        "",
        "使用方式：",
        "1. 把整个 ZIP 原样发送给维护人员，不要只截取其中一段；",
        "2. 说明“什么时候、点了哪个功能、看到什么现象”，与日志时间对应最快。",
        "",
        "隐私提示：",
        "- 日志记录程序路径、文件名、错误堆栈与异常信息，不主动记录文档正文；",
        "- 文档正文内容可能出现在用户自定义的异常消息里，请只发给内部维护人员。",
        "",
    ]
    return "\n".join(lines)


def export_diagnostic_bundle(
    *,
    destination_dir: Optional[Path] = None,
    log_directory: Optional[Path] = None,
    snapshot: Optional[Dict[str, Dict[str, str]]] = None,
    now: Optional[datetime] = None,
) -> Path:
    """生成诊断日志包并返回 ZIP 绝对路径。

    Args:
        destination_dir: 输出目录；缺省为桌面（见 :func:`default_bundle_directory`）。
        log_directory: 日志目录；缺省取当前全局日志目录。
        snapshot: 环境快照；缺省现采一次（约数百毫秒，含 Git/Office 探测）。
        now: 生成时间（测试固定时间戳用）。

    Raises:
        OSError: 输出目录不可写或 ZIP 写入失败。
    """
    moment = now or datetime.now()
    target_dir = Path(destination_dir) if destination_dir is not None else default_bundle_directory()
    target_dir.mkdir(parents=True, exist_ok=True)

    app_logging.flush_logging()
    log_files = app_logging.log_files(log_directory)

    data = snapshot if snapshot is not None else collect_environment_snapshot()
    environment_text = format_environment_snapshot(data, timestamp=moment)

    try:
        from doc_tool.domain.version import get_build_info

        build_info = get_build_info()
    except Exception as exc:  # noqa: BLE001 - 诊断包生成不得因版本信息失败
        build_info = {"error": "{0}: {1}".format(type(exc).__name__, exc)}

    target = _unique_path(target_dir / bundle_filename(moment))
    log_names = [path.name for path in log_files]
    readme = _readme_text(
        created_at=moment,
        app_version=str(build_info.get("appVersion", "")),
        log_names=log_names,
    )

    try:
        with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", readme)
            archive.writestr("environment.txt", environment_text)
            archive.writestr(
                "build-info.json",
                json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
            )
            for log_path in log_files:
                arcname = "logs/{0}".format(log_path.name)
                try:
                    archive.write(str(log_path), arcname)
                except OSError as exc:
                    archive.writestr(
                        "{0}.read-error.txt".format(arcname),
                        "读取日志失败：{0}: {1}\n".format(type(exc).__name__, exc),
                    )
    except Exception:
        # 半成品 ZIP 会误导维护人员，失败时清理后原样抛出。
        try:
            target.unlink()
        except OSError:
            pass
        raise

    return target


__all__ = [
    "BUNDLE_PREFIX",
    "bundle_filename",
    "default_bundle_directory",
    "export_diagnostic_bundle",
]
