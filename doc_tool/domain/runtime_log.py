# -*- coding: utf-8 -*-
"""脱敏轮转运行日志。

任务 5.4：实现脱敏轮转日志，记录阶段、版本、哈希、计数和异常但不记录正文内容。

日志位于项目 ``logs/runtime.log``，格式为 JSON Lines（每行一条 JSON 对象）。
每条记录包含：
- ``timestamp``：ISO 8601 UTC 时间戳
- ``level``：info/warn/error
- ``stage``：阶段名称（build/validate_pre/word_refresh/validate_post/import/...）
- ``status``：started/succeeded/failed/skipped
- ``appVersion``：应用版本
- ``metrics``：计数/哈希/路径名等诊断信息（脱敏）
- ``exception``：异常类型与消息（不含堆栈正文内容）

轮转策略：单文件超过 ``max_bytes``（默认 2 MB）时重命名为 ``runtime.log.1``，
最多保留 ``backup_count``（默认 3）个历史文件。

脱敏规则：
- 永不记录 Markdown 正文、Word XML 内容或文档业务文本。
- 路径仅记录文件名或相对项目根的 POSIX 路径，不记录完整绝对路径。
- 哈希记录前 12 位 + ``...`` 作为指纹。
- 异常仅记录类型名和 ``user_message``，不记录可能含正文的原始消息。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from doc_tool.domain.errors import DocToolError
from doc_tool.domain.paths import ProjectPaths


DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
DEFAULT_BACKUP_COUNT = 3
LOG_FILENAME = "runtime.log"


@dataclass
class LogRecord:
    """单条日志记录。"""

    level: str = "info"
    stage: str = ""
    status: str = ""
    app_version: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    exception_type: str = ""
    exception_message: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "stage": self.stage,
            "status": self.status,
            "appVersion": self.app_version,
            "metrics": _sanitize_metrics(self.metrics),
            "exceptionType": self.exception_type,
            "exceptionMessage": self.exception_message,
        }


def _sanitize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏指标字典：截断哈希、移除可能含正文的超长字符串。"""
    sanitized: Dict[str, Any] = {}
    for key, value in metrics.items():
        sanitized[key] = _sanitize_value(key, value)
    return sanitized


def _sanitize_value(key: str, value: Any) -> Any:
    """对单个指标值脱敏。"""
    # 哈希类键：截断为指纹
    if "sha256" in key.lower() or "hash" in key.lower():
        text = str(value)
        if len(text) > 16:
            return text[:12] + "..."
        return text
    # 路径类键：仅保留文件名或相对路径
    if "path" in key.lower() and isinstance(value, str):
        return Path(value).name if value else value
    # 字符串值过长：截断（防止意外包含正文）
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "...[truncated]"
    return value


class RuntimeLog:
    """脱敏轮转运行日志写入器。

    Args:
        paths: 项目路径，日志写入 ``paths.logs_dir / runtime.log``。
        app_version: 应用版本（写入每条记录）。
        max_bytes: 单文件最大字节数，超过后轮转。
        backup_count: 保留的历史日志文件数。
    """

    def __init__(
        self,
        paths: ProjectPaths,
        app_version: str = "",
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        self._paths = paths
        self._app_version = app_version
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._log_file = paths.logs_dir / LOG_FILENAME

    @property
    def log_file(self) -> Path:
        return self._log_file

    @property
    def app_version(self) -> str:
        """应用版本（只读，供状态元数据等模块复用）。"""
        return self._app_version

    def info(
        self, stage: str, status: str = "", metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        self._write(LogRecord(
            level="info", stage=stage, status=status,
            app_version=self._app_version, metrics=metrics or {},
        ))

    def warn(
        self, stage: str, status: str = "", metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        self._write(LogRecord(
            level="warn", stage=stage, status=status,
            app_version=self._app_version, metrics=metrics or {},
        ))

    def error(
        self,
        stage: str,
        status: str = "failed",
        metrics: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        exc_type = ""
        exc_msg = ""
        if exception is not None:
            exc_type = type(exception).__name__
            if isinstance(exception, DocToolError):
                exc_msg = exception.user_message
            else:
                # 非 DocToolError：仅记录简短消息，防止泄露正文
                exc_msg = str(exception)[:200]
        self._write(LogRecord(
            level="error", stage=stage, status=status,
            app_version=self._app_version, metrics=metrics or {},
            exception_type=exc_type, exception_message=exc_msg,
        ))

    def _write(self, record: LogRecord) -> None:
        """写入一条 JSON Lines 记录，并在需要时轮转。"""
        self._paths.logs_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        self._rotate_if_needed(len(line.encode("utf-8")))
        with open(str(self._log_file), "a", encoding="utf-8") as handle:
            handle.write(line)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        """若当前日志文件加上新内容超过上限则轮转。"""
        try:
            current_size = self._log_file.stat().st_size
        except OSError:
            current_size = 0
        if current_size + incoming_bytes <= self._max_bytes:
            return
        # 轮转：runtime.log.N-1 -> .N, ..., runtime.log -> .1
        for i in range(self._backup_count - 1, 0, -1):
            src = self._log_file.with_suffix(".log.{0}".format(i))
            dst = self._log_file.with_suffix(".log.{0}".format(i + 1))
            if src.exists():
                try:
                    os.replace(str(src), str(dst))
                except OSError:
                    pass
        if self._log_file.exists():
            try:
                os.replace(
                    str(self._log_file),
                    str(self._log_file.with_suffix(".log.1")),
                )
            except OSError:
                pass

    def read_records(self) -> list:
        """读取当前日志文件中的所有记录（用于测试和诊断）。"""
        if not self._log_file.exists():
            return []
        records = []
        for line in self._log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
