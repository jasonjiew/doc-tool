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

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from doc_tool.domain.cancellation import CancellationToken
from doc_tool.domain.errors import (
    BuildError,
    CancelledError,
    DocToolError,
    ProjectLockBusyError,
    ValidationError,
    WordNotAvailableError,
    WordRefreshTimeoutError,
    WordSaveFailedError,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.project_lock import TASK_BUILD, acquire_lock, release_lock
from doc_tool.domain.runtime_log import RuntimeLog


STAGE_BUILD = "build"
STAGE_VALIDATE_PRE = "validate_pre"
STAGE_WORD_REFRESH = "word_refresh"
STAGE_VALIDATE_POST = "validate_post"
STAGE_PUBLISH = "publish"


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


def _current_stage(result: PipelineResult) -> str:
    """返回最近一个 started 阶段的名称（用于取消事件归属）。"""
    started = [e for e in result.events if e.status == "started"]
    return started[-1].stage if started else STAGE_BUILD


def run_pipeline(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    skip_word_refresh: bool = False,
    baseline: bool = False,
    cancel_token: Optional[CancellationToken] = None,
    app_version: str = "",
) -> PipelineResult:
    """执行构建→前校验→Word 刷新→后校验管线，返回结构化结果。

    不向调用方抛出异常；所有错误被捕获并映射为 ``StageEvent``。
    Word 刷新阶段需要本机安装 Microsoft Word；无 Word 环境应传
    ``skip_word_refresh=True`` 进行诊断构建。

    任务 5.1/5.4/5.5：管线自动获取/释放项目锁，写入脱敏轮转日志，
    并在阶段边界检查取消令牌。Word 保存与构建原子写入受临界区保护。

    任务 7.1：正式模式（``skip_word_refresh=False``）在启动前再次确认 Word
    可用，避免锁已获取后才发现 Word 缺失。
    任务 7.3：构建产物先写入临时文件，前校验、Word 刷新、后校验全部在
    临时文件上进行；只有后校验通过后才原子发布到正式输出路径。
    任务 7.4：发布完成后写入输出状态元数据，标注是否为正式成功。
    """
    from doc_tool.adapters.kernel import (
        build_with_project,
        refresh_with_project,
        validate_with_project,
    )

    result = PipelineResult(success=False)
    log = RuntimeLog(paths, app_version=app_version)

    # --- 任务 7.1：正式模式预检 Word 可用性 ---
    if not skip_word_refresh:
        from doc_tool.application.word_check import check_word_available

        report = check_word_available(dispatch_check=True)
        if not report.available:
            err = WordNotAvailableError(
                user_message="Microsoft Word 不可用：{0}".format(
                    "；".join(report.reasons) or "未知原因"
                ),
                suggested_action=(
                    "请改用「诊断构建（无 Word）」，或在安装 Microsoft Word 的电脑上执行正式合并。"
                ),
                details={
                    "pywin32": str(report.pywin32_available),
                    "interactive": str(report.interactive_session),
                    "dispatchable": str(report.word_dispatchable),
                },
            )
            result.error_code = err.code
            result.events.append(StageEvent(
                STAGE_BUILD, "failed", detail=err.user_message, error_code=err.code,
            ))
            log.error(STAGE_BUILD, exception=err, metrics={
                "pywin32": report.pywin32_available,
                "interactive": report.interactive_session,
                "dispatchable": report.word_dispatchable,
            })
            return result

    # --- 获取项目锁 ---
    try:
        acquire_lock(paths, TASK_BUILD, app_version)
    except ProjectLockBusyError as exc:
        result.error_code = exc.code
        result.events.append(StageEvent(
            STAGE_BUILD, "failed", detail=exc.user_message, error_code=exc.code,
        ))
        log.error(STAGE_BUILD, exception=exc)
        return result

    try:
        return _run_pipeline_inner(
            manifest, paths, skip_word_refresh, baseline, cancel_token,
            result, log, build_with_project, refresh_with_project,
            validate_with_project,
        )
    except CancelledError as exc:
        result.error_code = exc.code
        result.events.append(StageEvent(
            _current_stage(result), "cancelled",
            detail=exc.user_message, error_code=exc.code,
        ))
        log.error(_current_stage(result), status="cancelled", exception=exc)
        return result
    finally:
        release_lock(paths)


def _run_pipeline_inner(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    skip_word_refresh: bool,
    baseline: bool,
    cancel_token: Optional[CancellationToken],
    result: PipelineResult,
    log: RuntimeLog,
    build_with_project,
    refresh_with_project,
    validate_with_project,
) -> PipelineResult:
    """管线内部执行（锁已获取），分离以便 finally 释放锁。

    任务 7.3：构建产物先写入临时文件（与正式输出同目录，保证 ``os.replace``
    原子）。前校验、Word 刷新、后校验全部在临时文件上进行。只有后校验
    通过后才原子发布到正式输出路径，并写入状态元数据。任意阶段失败都
    不修改正式输出，仅清理临时文件。
    """
    from doc_tool.domain.output_state import write_state
    from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, get_commit_id

    token = cancel_token or CancellationToken()

    # --- 计算正式输出路径与临时输出路径 ---
    output_name = "{0} {1}({2}).docx".format(
        manifest.documentNo, manifest.documentName, manifest.documentVersion
    )
    formal_output = paths.output_dir / output_name
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    # 临时文件与正式输出同目录，保证 os.replace 在同一卷上原子
    temp_output = paths.output_dir / ("." + output_name + ".tmp")

    # 用于状态元数据的阶段摘要
    stage_summary: list = []

    def _record_stage(stage: str, status: str) -> None:
        stage_summary.append({"stage": stage, "status": status})

    def _cleanup_temp() -> None:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except OSError:
            pass

    # --- 阶段 1：构建到临时文件 ---
    token.check_cancel()
    result.events.append(StageEvent(STAGE_BUILD, "started"))
    log.info(STAGE_BUILD, "started")
    try:
        # 先删除可能残留的临时文件，避免上次失败遗留
        _cleanup_temp()
        built_path = build_with_project(manifest, paths, output_override=str(temp_output))
        result.output_path = str(formal_output)  # 返回正式路径，而非临时
        result.events.append(StageEvent(
            STAGE_BUILD, "succeeded",
            detail="构建到临时文件：{0}".format(temp_output.name),
        ))
        log.info(STAGE_BUILD, "succeeded", {"output": temp_output.name})
        _record_stage(STAGE_BUILD, "succeeded")
    except CancelledError:
        _cleanup_temp()
        raise
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_BUILD, "failed", detail=err.user_message, error_code=err.code,
        ))
        log.error(STAGE_BUILD, exception=exc)
        result.error_code = err.code
        _record_stage(STAGE_BUILD, "failed")
        _cleanup_temp()
        # 写入失败状态（不计算正式输出哈希，因为正式输出未更新）
        write_state(
            str(formal_output),
            formal=False,
            diagnostic=skip_word_refresh,
            app_version=log.app_version,
            commit=get_commit_id(),
            schema_version=PROJECT_SCHEMA_VERSION,
            stages=stage_summary,
            failure_code=err.code,
            compute_hash=False,
        )
        return result

    # --- 阶段 2：刷新前严格校验（临时文件） ---
    token.check_cancel()
    result.events.append(StageEvent(STAGE_VALIDATE_PRE, "started"))
    log.info(STAGE_VALIDATE_PRE, "started")
    try:
        ok = validate_with_project(
            manifest, paths, output_override=str(temp_output), baseline=baseline,
        )
        result.events.append(StageEvent(
            STAGE_VALIDATE_PRE,
            "succeeded" if ok else "failed",
            detail="校验通过" if ok else "校验未通过",
        ))
        log.info(STAGE_VALIDATE_PRE, "succeeded" if ok else "failed")
        _record_stage(STAGE_VALIDATE_PRE, "succeeded" if ok else "failed")
        if not ok:
            result.error_code = ValidationError.code
            _cleanup_temp()
            write_state(
                str(formal_output),
                formal=False,
                diagnostic=skip_word_refresh,
                app_version=log.app_version,
                commit=get_commit_id(),
                schema_version=PROJECT_SCHEMA_VERSION,
                stages=stage_summary,
                failure_code=ValidationError.code,
                compute_hash=False,
            )
            return result
    except CancelledError:
        _cleanup_temp()
        raise
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_VALIDATE_PRE, "failed", detail=err.user_message, error_code=err.code,
        ))
        log.error(STAGE_VALIDATE_PRE, exception=exc)
        result.error_code = err.code
        _record_stage(STAGE_VALIDATE_PRE, "failed")
        _cleanup_temp()
        write_state(
            str(formal_output),
            formal=False,
            diagnostic=skip_word_refresh,
            app_version=log.app_version,
            commit=get_commit_id(),
            schema_version=PROJECT_SCHEMA_VERSION,
            stages=stage_summary,
            failure_code=err.code,
            compute_hash=False,
        )
        return result

    # --- 阶段 3：Word 实机刷新（可选，临时文件） ---
    token.check_cancel()
    if skip_word_refresh:
        result.events.append(StageEvent(
            STAGE_WORD_REFRESH, "skipped", detail="已显式跳过 Word 实机刷新",
        ))
        log.info(STAGE_WORD_REFRESH, "skipped")
        _record_stage(STAGE_WORD_REFRESH, "skipped")
    else:
        result.events.append(StageEvent(STAGE_WORD_REFRESH, "started"))
        log.info(STAGE_WORD_REFRESH, "started")
        try:
            # Word 保存是临界区：取消在保存完成前不中断
            with token.critical_section():
                ok = refresh_with_project(
                    manifest, paths, output_override=str(temp_output),
                )
            if ok:
                result.events.append(StageEvent(
                    STAGE_WORD_REFRESH, "succeeded",
                    detail="TOC、NUMPAGES 与全部 story 域刷新完成",
                ))
                log.info(STAGE_WORD_REFRESH, "succeeded")
                _record_stage(STAGE_WORD_REFRESH, "succeeded")
            else:
                err = WordNotAvailableError(
                    user_message="Word 刷新失败，请查看日志中的详细错误",
                )
                result.events.append(StageEvent(
                    STAGE_WORD_REFRESH, "failed",
                    detail=err.user_message, error_code=err.code,
                ))
                log.error(STAGE_WORD_REFRESH, exception=err)
                result.error_code = err.code
                _record_stage(STAGE_WORD_REFRESH, "failed")
                _cleanup_temp()
                write_state(
                    str(formal_output),
                    formal=False,
                    diagnostic=False,
                    app_version=log.app_version,
                    commit=get_commit_id(),
                    schema_version=PROJECT_SCHEMA_VERSION,
                    stages=stage_summary,
                    failure_code=err.code,
                    compute_hash=False,
                )
                return result
        except CancelledError:
            _cleanup_temp()
            raise
        except Exception as exc:
            err = _map_exception(exc)
            result.events.append(StageEvent(
                STAGE_WORD_REFRESH, "failed", detail=err.user_message, error_code=err.code,
            ))
            log.error(STAGE_WORD_REFRESH, exception=exc)
            result.error_code = err.code
            _record_stage(STAGE_WORD_REFRESH, "failed")
            _cleanup_temp()
            write_state(
                str(formal_output),
                formal=False,
                diagnostic=False,
                app_version=log.app_version,
                commit=get_commit_id(),
                schema_version=PROJECT_SCHEMA_VERSION,
                stages=stage_summary,
                failure_code=err.code,
                compute_hash=False,
            )
            return result

    # --- 阶段 4：刷新后严格校验（临时文件） ---
    # 诊断模式跳过后校验（无 Word 刷新，require_refreshed 无意义）
    if skip_word_refresh:
        result.events.append(StageEvent(
            STAGE_VALIDATE_POST, "skipped",
            detail="诊断模式跳过刷新后校验",
        ))
        log.info(STAGE_VALIDATE_POST, "skipped")
        _record_stage(STAGE_VALIDATE_POST, "skipped")
        post_ok = True
    else:
        token.check_cancel()
        result.events.append(StageEvent(STAGE_VALIDATE_POST, "started"))
        log.info(STAGE_VALIDATE_POST, "started")
        try:
            ok = validate_with_project(
                manifest, paths, output_override=str(temp_output),
                baseline=baseline, require_refreshed=True,
            )
            result.events.append(StageEvent(
                STAGE_VALIDATE_POST,
                "succeeded" if ok else "failed",
                detail="刷新后校验通过" if ok else "刷新后校验未通过",
            ))
            log.info(STAGE_VALIDATE_POST, "succeeded" if ok else "failed")
            _record_stage(STAGE_VALIDATE_POST, "succeeded" if ok else "failed")
            post_ok = ok
            if not ok:
                result.error_code = ValidationError.code
        except CancelledError:
            _cleanup_temp()
            raise
        except Exception as exc:
            err = _map_exception(exc)
            result.events.append(StageEvent(
                STAGE_VALIDATE_POST, "failed", detail=err.user_message, error_code=err.code,
            ))
            log.error(STAGE_VALIDATE_POST, exception=exc)
            result.error_code = err.code
            _record_stage(STAGE_VALIDATE_POST, "failed")
            _cleanup_temp()
            write_state(
                str(formal_output),
                formal=False,
                diagnostic=False,
                app_version=log.app_version,
                commit=get_commit_id(),
                schema_version=PROJECT_SCHEMA_VERSION,
                stages=stage_summary,
                failure_code=err.code,
                compute_hash=False,
            )
            return result

    # --- 阶段 5：原子发布（临界区，不可取消） ---
    if not post_ok:
        _cleanup_temp()
        write_state(
            str(formal_output),
            formal=False,
            diagnostic=skip_word_refresh,
            app_version=log.app_version,
            commit=get_commit_id(),
            schema_version=PROJECT_SCHEMA_VERSION,
            stages=stage_summary,
            failure_code=ValidationError.code,
            compute_hash=False,
        )
        return result

    result.events.append(StageEvent(STAGE_PUBLISH, "started"))
    log.info(STAGE_PUBLISH, "started")
    try:
        with token.critical_section():
            # os.replace 在同一卷上原子：要么完全成功，要么正式输出不变
            os.replace(str(temp_output), str(formal_output))
        result.events.append(StageEvent(
            STAGE_PUBLISH, "succeeded",
            detail="已原子发布到：{0}".format(formal_output.name),
        ))
        log.info(STAGE_PUBLISH, "succeeded", {"output": formal_output.name})
        _record_stage(STAGE_PUBLISH, "succeeded")
        result.success = True
        result.output_path = str(formal_output)

        # 任务 7.4：写入输出状态元数据
        is_formal = not skip_word_refresh
        write_state(
            str(formal_output),
            formal=is_formal,
            diagnostic=skip_word_refresh,
            app_version=log.app_version,
            commit=get_commit_id(),
            schema_version=PROJECT_SCHEMA_VERSION,
            stages=stage_summary,
            failure_code="",
            compute_hash=True,
        )
        log.info(STAGE_PUBLISH, "state_written", {
            "formal": is_formal,
            "diagnostic": skip_word_refresh,
        })
    except CancelledError:
        # 临界区内取消不中断，但这里已经是发布临界区
        _cleanup_temp()
        raise
    except Exception as exc:
        err = _map_exception(exc)
        result.events.append(StageEvent(
            STAGE_PUBLISH, "failed", detail=err.user_message, error_code=err.code,
        ))
        log.error(STAGE_PUBLISH, exception=exc)
        result.error_code = err.code
        _record_stage(STAGE_PUBLISH, "failed")
        _cleanup_temp()
        write_state(
            str(formal_output),
            formal=False,
            diagnostic=skip_word_refresh,
            app_version=log.app_version,
            commit=get_commit_id(),
            schema_version=PROJECT_SCHEMA_VERSION,
            stages=stage_summary,
            failure_code=err.code,
            compute_hash=False,
        )

    return result
