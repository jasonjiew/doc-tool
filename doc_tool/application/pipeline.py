# -*- coding: utf-8 -*-
"""结构化构建管线应用服务。

任务 2.4：将日常管线重构为可返回结构化阶段事件和稳定错误码的应用服务。

管线阶段：``build`` → ``validate_pre`` → ``word_refresh``（可选）→ ``validate_post``。
每个阶段产生 ``StageEvent``，最终返回 ``PipelineResult``。错误被捕获并映射到
``doc_tool.domain.errors`` 中的稳定错误码，不向调用方抛出异常。

旧入口 ``scripts/run_pipeline.py`` 继续可用；新入口通过本服务调用同一内核，
并在 ``doc_tool.cli`` 中以 ``--project`` 参数暴露。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from doc_tool.domain.errors import (
    BuildError,
    CancelledError,
    DocToolError,
    ValidationError,
    WordNotAvailableError,
    WordRefreshTimeoutError,
    WordSaveFailedError,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths


STAGE_BUILD = "build"
STAGE_VALIDATE_PRE = "validate_pre"
STAGE_WORD_REFRESH = "word_refresh"
STAGE_VALIDATE_POST = "validate_post"


@dataclass
class StageEvent:
    """管线阶段事件。

    Attributes:
        stage: 阶段名称（build/validate_pre/word_refresh/validate_post）。
        status: 阶段状态（started/succeeded/failed/skipped）。
        detail: 面向用户的简明说明。
        metrics: 阶段产出的计数/路径等诊断信息（脱敏，不含正文）。
        error_code: 失败时的稳定错误码（``E<区域><序号>``），成功时为 None。
    """

    stage: str
    status: str
    detail: str = ""
    metrics: Dict[str, object] = field(default_factory=dict)
    error_code: Optional[str] = None


@dataclass
class PipelineResult:
    """管线执行结果。"""

    success: bool
    events: List[StageEvent] = field(default_factory=list)
    output_path: Optional[str] = None
    error_code: Optional[str] = None

    @property
    def last_stage(self) -> Optional[StageEvent]:
        return self.events[-1] if self.events else None


def _map_exception(exc: Exception) -> DocToolError:
    """将内核异常映射到结构化错误类型。

    内核使用 ``docx_common.AutomationError``（``RuntimeError`` 子类），不是
    ``DocToolError``。本函数通过消息关键词映射到最接近的稳定错误类型。
    任务 5.3 会用更完整的错误分层替换此映射。
    """
    if isinstance(exc, DocToolError):
        return exc
    msg = str(exc)
    lower = msg.lower()
    if "word" in lower and ("超时" in msg or "timeout" in lower or "超过" in msg):
        return WordRefreshTimeoutError(user_message=msg)
    if "word" in lower and ("保存" in msg or "save" in lower):
        return WordSaveFailedError(user_message=msg)
    if "pywin32" in lower or "win32com" in lower or "word.application" in lower:
        return WordNotAvailableError(user_message=msg)
    if "取消" in msg or "cancel" in lower:
        return CancelledError(user_message=msg)
    if "校验" in msg or "不一致" in msg or "validate" in lower:
        return ValidationError(user_message=msg)
    return BuildError(user_message=msg)


def run_pipeline(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    skip_word_refresh: bool = False,
    baseline: bool = False,
) -> PipelineResult:
    """执行构建→前校验→Word 刷新→后校验管线，返回结构化结果。

    不向调用方抛出异常；所有错误被捕获并映射为 ``StageEvent``。
    Word 刷新阶段需要本机安装 Microsoft Word；无 Word 环境应传
    ``skip_word_refresh=True`` 进行诊断构建。
    """
    from doc_tool.adapters.kernel import (
        build_with_project,
        refresh_with_project,
        validate_with_project,
    )

    result = PipelineResult(success=False)

    # --- 阶段 1：构建 ---
    result.events.append(StageEvent(STAGE_BUILD, "started"))
    try:
        output_path = build_with_project(manifest, paths)
        result.output_path = output_path
        result.events.append(StageEvent(STAGE_BUILD, "succeeded", detail=output_path))
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_BUILD, "failed", detail=err.user_message, error_code=err.code,
        ))
        result.error_code = err.code
        return result

    # --- 阶段 2：刷新前严格校验 ---
    result.events.append(StageEvent(STAGE_VALIDATE_PRE, "started"))
    try:
        ok = validate_with_project(manifest, paths, baseline=baseline)
        result.events.append(StageEvent(
            STAGE_VALIDATE_PRE,
            "succeeded" if ok else "failed",
            detail="校验通过" if ok else "校验未通过",
        ))
        if not ok:
            result.error_code = ValidationError.code
            return result
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_VALIDATE_PRE, "failed", detail=err.user_message, error_code=err.code,
        ))
        result.error_code = err.code
        return result

    # --- 阶段 3：Word 实机刷新（可选） ---
    if skip_word_refresh:
        result.events.append(StageEvent(
            STAGE_WORD_REFRESH, "skipped", detail="已显式跳过 Word 实机刷新",
        ))
        result.success = True
        return result

    result.events.append(StageEvent(STAGE_WORD_REFRESH, "started"))
    try:
        ok = refresh_with_project(manifest, paths)
        if ok:
            result.events.append(StageEvent(
                STAGE_WORD_REFRESH, "succeeded",
                detail="TOC、NUMPAGES 与全部 story 域刷新完成",
            ))
        else:
            # supervise 返回 False 时具体原因已由 worker 输出到 stderr。
            result.events.append(StageEvent(
                STAGE_WORD_REFRESH, "failed",
                detail="Word 刷新失败，请查看日志中的详细错误",
                error_code=WordNotAvailableError.code,
            ))
            result.error_code = WordNotAvailableError.code
            return result
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_WORD_REFRESH, "failed", detail=err.user_message, error_code=err.code,
        ))
        result.error_code = err.code
        return result

    # --- 阶段 4：刷新后严格校验 ---
    result.events.append(StageEvent(STAGE_VALIDATE_POST, "started"))
    try:
        ok = validate_with_project(
            manifest, paths, baseline=baseline, require_refreshed=True
        )
        result.events.append(StageEvent(
            STAGE_VALIDATE_POST,
            "succeeded" if ok else "failed",
            detail="刷新后校验通过" if ok else "刷新后校验未通过",
        ))
        result.success = ok
        if not ok:
            result.error_code = ValidationError.code
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_VALIDATE_POST, "failed", detail=err.user_message, error_code=err.code,
        ))
        result.error_code = err.code

    return result
