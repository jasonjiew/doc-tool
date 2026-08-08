# -*- coding: utf-8 -*-
"""正式/诊断输出状态元数据。

任务 7.4：实现正式/诊断输出状态元数据，禁止未刷新结果显示为正式成功。

每次构建/合并完成后在输出目录写入 ``<output-name>.state.json``，记录：

- ``formal``：是否为正式成功（Word 刷新 + 后校验通过）
- ``diagnostic``：是否为诊断构建（跳过 Word 刷新）
- ``appVersion``：构建时的应用版本
- ``commit``：构建时的提交标识
- ``schemaVersion``：项目模式版本
- ``completedAt``：ISO 8601 UTC 完成时间
- ``outputFile``：输出文件名（不含完整路径）
- ``outputSha256``：输出文件 SHA-256 完整指纹（用于发布追溯）
- ``stages``：各阶段状态摘要（仅阶段名 + 状态，不含正文）
- ``failureCode``：失败时的稳定错误码

正式合并只有在 ``formal=True`` 时才允许显示为「正式成功」；
诊断构建必须显示「非正式，字段未实机刷新」。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 状态文件后缀（与输出 DOCX 同名 + .state.json）
STATE_SUFFIX = ".state.json"
ATTEMPT_STATE_SUFFIX = ".last-attempt.json"


@dataclass
class OutputState:
    """输出状态元数据。"""

    formal: bool = False
    diagnostic: bool = False
    appVersion: str = ""
    commit: str = ""
    schemaVersion: int = 0
    completedAt: str = ""
    outputFile: str = ""
    outputSha256: str = ""
    stages: List[Dict[str, str]] = field(default_factory=list)
    failureCode: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def state_file_for(output_path: Union[str, Path]) -> Path:
    """返回输出 DOCX 对应的状态文件路径。"""
    p = Path(output_path)
    return p.with_name(p.name + STATE_SUFFIX)


def last_attempt_state_file_for(output_path: Union[str, Path]) -> Path:
    """返回最近一次失败尝试的状态文件路径。

    失败尝试与已发布产物状态分离，避免一次构建失败把上一份仍然有效的
    ``formal=True`` 状态覆盖掉。
    """
    p = Path(output_path)
    return p.with_name(p.name + ATTEMPT_STATE_SUFFIX)


def compute_sha256(path: Union[str, Path]) -> str:
    """计算文件 SHA-256 完整指纹（64 位十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_state(
    output_path: Union[str, Path],
    *,
    formal: bool,
    diagnostic: bool,
    app_version: str = "",
    commit: str = "",
    schema_version: int = 0,
    stages: Optional[List[Dict[str, str]]] = None,
    failure_code: str = "",
    compute_hash: bool = True,
) -> Path:
    """写入输出状态元数据。

    Args:
        output_path: 输出 DOCX 路径（状态文件与之同名 + .state.json）。
        formal: 是否为正式成功。
        diagnostic: 是否为诊断构建。
        compute_hash: 是否计算输出文件 SHA-256。失败/取消时可设为 False。

    Returns:
        状态文件路径。
    """
    p = Path(output_path)
    state = OutputState(
        formal=formal,
        diagnostic=diagnostic,
        appVersion=app_version,
        commit=commit,
        schemaVersion=schema_version,
        completedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        outputFile=p.name,
        outputSha256=compute_sha256(p) if (compute_hash and p.exists()) else "",
        stages=list(stages or []),
        failureCode=failure_code,
    )
    state_path = (
        last_attempt_state_file_for(p) if failure_code else state_file_for(p)
    )
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(state.to_json(), encoding="utf-8")
    try:
        os.replace(str(tmp), str(state_path))
    except OSError:
        import shutil

        shutil.move(str(tmp), str(state_path))
    if not failure_code:
        try:
            last_attempt_state_file_for(p).unlink()
        except FileNotFoundError:
            pass
    return state_path


def read_state(output_path: Union[str, Path]) -> Optional[OutputState]:
    """读取输出状态元数据，不存在或损坏时返回 ``None``。"""
    return _read_state_path(state_file_for(output_path))


def read_last_attempt_state(output_path: Union[str, Path]) -> Optional[OutputState]:
    """读取最近一次失败尝试状态，不影响已发布产物的正式状态。"""
    return _read_state_path(last_attempt_state_file_for(output_path))


def _read_state_path(state_path: Path) -> Optional[OutputState]:
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        formal = data.get("formal", False)
        diagnostic = data.get("diagnostic", False)
        stages = data.get("stages", [])
        if type(formal) is not bool or type(diagnostic) is not bool:
            return None
        if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
            return None
        output_sha256 = str(data.get("outputSha256", ""))
        if output_sha256 and re.fullmatch(r"[0-9a-fA-F]{64}", output_sha256) is None:
            return None
        if formal and diagnostic:
            return None
        return OutputState(
            formal=formal,
            diagnostic=diagnostic,
            appVersion=str(data.get("appVersion", "")),
            commit=str(data.get("commit", "")),
            schemaVersion=int(data.get("schemaVersion", 0)),
            completedAt=str(data.get("completedAt", "")),
            outputFile=str(data.get("outputFile", "")),
            outputSha256=output_sha256,
            stages=list(stages),
            failureCode=str(data.get("failureCode", "")),
        )
    except Exception:
        return None


def is_formal_success(output_path: Union[str, Path]) -> bool:
    """判断输出是否为正式成功（状态文件存在且 ``formal=True``）。

    任务 7.4：禁止未刷新结果显示为正式成功。即使 DOCX 文件存在，
    若状态文件不存在或 ``formal=False``，也视为非正式。
    """
    path = Path(output_path)
    state = read_state(path)
    if state is None or not state.formal or state.diagnostic or not path.is_file():
        return False
    if state.outputFile != path.name or not state.outputSha256:
        return False
    try:
        return compute_sha256(path).lower() == state.outputSha256.lower()
    except OSError:
        return False
