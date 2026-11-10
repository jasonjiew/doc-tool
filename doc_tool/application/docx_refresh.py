# -*- coding: utf-8 -*-
"""对已导出的 DOCX 就地刷新目录/页码字段。

与出稿管线共用 ``scripts/refresh_fields.py`` 的监督器：专用 Word 实例、
按预算超时、只清理本次进程，不碰用户已打开的 Word。界面在「成果」页对
待刷新稿提供入口，避免用户只能手动 Ctrl+A → F9。
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

#: 默认刷新预算（秒）。调用方可用 manifest.refreshTimeoutSeconds 覆盖。
DEFAULT_TIMEOUT_SECONDS = 300

#: 目标文件不存在（不进入 Word）。
REASON_MISSING = "missing"


def refresh_docx_fields(
    path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Tuple[bool, str]:
    """刷新任意 DOCX 的目录/页码并保存。

    Returns:
        ``(是否成功, 原因键)``，原因键与 ``refresh_fields.supervise`` 一致
        （``ok / timeout / word_unavailable / save_failed / refresh_failed``），
        文件不存在时为 ``missing``。
    """
    target = Path(str(path or ""))
    if not target.is_file():
        return False, REASON_MISSING

    from doc_tool.adapters.kernel import ensure_kernel_importable

    ensure_kernel_importable()
    from refresh_fields import supervise

    ok, reason = supervise(output_path=str(target), timeout=int(timeout))
    return bool(ok), str(reason)


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "REASON_MISSING", "refresh_docx_fields"]
