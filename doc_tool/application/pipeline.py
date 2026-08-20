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
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# 进度回调类型：(stage, status, detail) -> None。后台线程内调用，
# 实现方需自行线程安全地转发到 UI 线程（例如经队列）。可选参数：
# 调用方不传则不产生进度事件，行为与改造前一致。
ProgressCallback = Callable[[str, str, str], None]


def _noop_progress(stage: str, status: str, detail: str) -> None:
    """默认进度回调：空操作，保持改造前行为。"""
    return None

from doc_tool.domain.cancellation import CancellationToken
from doc_tool.domain.errors import (
    BuildError,
    CancelledError,
    DocToolError,
    IncompatibleSchemaError,
    ProjectLockBusyError,
    ValidationError,
    WordNotAvailableError,
    WordRefreshTimeoutError,
    WordSaveFailedError,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths, build_output_filename
from doc_tool.domain.project_lock import TASK_BUILD, acquire_lock, release_lock
from doc_tool.domain.runtime_log import RuntimeLog


STAGE_REVISION = "revision"
STAGE_BUILD = "build"
STAGE_VALIDATE_PRE = "validate_pre"
STAGE_WORD_REFRESH = "word_refresh"
STAGE_VALIDATE_POST = "validate_post"
STAGE_PUBLISH = "publish"

# 管线阶段顺序：用于把阶段名映射为确定性进度百分比。修订记录（同步文档
# 版本号）在正式合并与诊断构建下都会执行；诊断模式跳过 word_refresh 和
# validate_post。
PIPELINE_STAGE_ORDER = (
    STAGE_REVISION,
    STAGE_BUILD,
    STAGE_VALIDATE_PRE,
    STAGE_WORD_REFRESH,
    STAGE_VALIDATE_POST,
    STAGE_PUBLISH,
)

# 阶段中文标签：用于进度文本与日志。
PIPELINE_STAGE_LABELS = {
    STAGE_REVISION: "修订记录",
    STAGE_BUILD: "构建",
    STAGE_VALIDATE_PRE: "前校验",
    STAGE_WORD_REFRESH: "Word 刷新",
    STAGE_VALIDATE_POST: "后校验",
    STAGE_PUBLISH: "发布",
}


def stage_percent_table() -> "Dict[str, tuple]":
    """返回 ``{stage: (start_pct, end_pct)}``，由阶段顺序自动均匀分段。

    供 UI 进度条把阶段名映射为确定性百分比。UI 不再手写百分比映射，
    避免与 ``PIPELINE_STAGE_ORDER`` 漂移。两端各预留 5%/100% 的边距，
    让进度条在 started 即有可见推进、在 publish 终态到达 100。
    """
    n = len(PIPELINE_STAGE_ORDER)
    if n == 0:
        return {}
    table: "Dict[str, tuple]" = {}
    # 进度区间 [5, 100]，每阶段占 (100-5)/n。
    span = (100 - 5) / n
    for idx, stage in enumerate(PIPELINE_STAGE_ORDER):
        start = round(5 + idx * span)
        end = round(5 + (idx + 1) * span)
        table[stage] = (start, end)
    # 保证最后一段收口在 100。
    table[PIPELINE_STAGE_ORDER[-1]] = (table[PIPELINE_STAGE_ORDER[-1]][0], 100)
    return table


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


def _refresh_error(reason: str, timeout_seconds: int) -> DocToolError:
    """把 Word 刷新结果的原因键映射为稳定错误类型。

    旧实现把 ``refresh`` 返回 False 一律映射为 ``WordNotAvailableError``
    （E3001「未检测到可用的 Microsoft Word」）：真实超时/保存失败被误报为
    Word 不可用，误导排障。现在按 supervise 透传的原因键区分
    E3002（超时）/ E3003（保存失败）/ E3001（其余）。
    """
    if reason == "timeout":
        return WordRefreshTimeoutError(
            user_message="Word 刷新超过 {0} 秒，已终止本次专用进程。".format(
                timeout_seconds
            ),
        )
    if reason == "save_failed":
        return WordSaveFailedError(
            user_message="Word 刷新过程中保存文档失败。",
            suggested_action="请关闭其他 Word 进程后重试；上次有效输出已保留。",
        )
    return WordNotAvailableError(
        user_message="Word 刷新失败，请查看日志中的详细错误",
        suggested_action="请确认 Microsoft Word 可用且文档未损坏后重试。",
    )


def _current_stage(result: PipelineResult) -> str:
    """返回最近一个 started 阶段的名称（用于取消事件归属）。"""
    started = [e for e in result.events if e.status == "started"]
    return started[-1].stage if started else STAGE_BUILD


def _prepare_revision_sync(
    manifest: ProjectManifest,
    paths: ProjectPaths,
) -> Optional[dict]:
    """按 ``_revision_record.md`` 末行版本号算出文档版本号同步计划（锁内只读）。

    修订记录是作者手工维护的唯一维护点：表格末行就是本次要发布的版本，构建
    内核 ``update_revision_record`` 会用该文件的数据行整表覆盖 Word 修订记录表。
    这里只把末行版本号取出来，写清单由 ``_sync_revision_version`` 负责。

    旧项目缺少 ``_revision_record.md`` 时先从项目模板初始化（仅在缺失时创建，
    从不覆盖用户内容）。取不到版本号（无修订记录表 / 表里还没有数据行 / 末行
    版本号写坏）时 ``new_version`` 为 None：沿用清单现有版本号，合并照常进行。
    读取整体失败返回 None，绝不阻断合并。
    """
    try:
        from doc_tool.application.content.revision_record import (
            document_version_from_record,
            ensure_revision_record,
            has_revision_table,
        )

        md_path = paths.resolve(manifest.relative_content_root()) / "_revision_record.md"
        ensure_revision_record(
            md_path=md_path,
            template_path=paths.resolve(manifest.relative_template_docx()),
            document_type=manifest.documentType,
        )
        return {
            "md_path": md_path,
            "new_version": document_version_from_record(md_path),
            "original_version": manifest.documentVersion,
            "has_table": has_revision_table(md_path),
            "applied": False,
        }
    except Exception:  # noqa: BLE001
        return None


def _revision_skip_detail(revision_sync: Optional[dict]) -> str:
    """修订记录阶段跳过原因（沿用清单版本号时给出可排障的说明）。"""
    if revision_sync is None:
        return "修订记录读取失败，沿用项目版本号"
    if not revision_sync.get("has_table"):
        return "_revision_record.md 中没有修订记录表，沿用项目版本号"
    return "_revision_record.md 修订记录表还没有数据行，沿用项目版本号"


def _sync_revision_version(
    revision_sync: Optional[dict],
    manifest: ProjectManifest,
    result: PipelineResult,
    log: RuntimeLog,
) -> str:
    """把修订记录末行版本号同步到清单版本号（锁内执行），返回阶段状态。

    版本号决定封面「版本号」与输出文件名，因此必须在构建之前完成。取不到
    版本号只降级为 skipped：修订记录同步不了不影响本次构建本身。
    """
    version = (revision_sync or {}).get("new_version")
    if not version:
        detail = _revision_skip_detail(revision_sync)
        result.events.append(StageEvent(STAGE_REVISION, "skipped", detail=detail))
        log.info(STAGE_REVISION, "skipped")
        return "skipped"
    result.events.append(StageEvent(STAGE_REVISION, "started"))
    log.info(STAGE_REVISION, "started")
    original = str(revision_sync.get("original_version") or "")
    if version == original:
        detail = "文档版本号已与 _revision_record.md 末行一致：{0}".format(version)
    else:
        manifest.documentVersion = version
        revision_sync["applied"] = True
        detail = "已按 _revision_record.md 末行同步文档版本号：{0} → {1}".format(
            original or "（空）", version
        )
    result.events.append(StageEvent(STAGE_REVISION, "succeeded", detail=detail))
    log.info(STAGE_REVISION, "succeeded", {"version": version})
    return "succeeded"


def _rollback_revision_sync(
    revision_sync: Optional[dict],
    manifest: ProjectManifest,
    log: RuntimeLog,
) -> None:
    """构建失败时还原同步过的文档版本号（锁内调用）。

    修订记录文件本身从未被改写，只需回退内存中的清单版本号；清单只在发布
    成功后落盘，因此回退后不会有中途版本号进入 ``project.yml``。
    """
    if not (revision_sync or {}).get("applied"):
        return
    try:
        manifest.documentVersion = revision_sync["original_version"]
        revision_sync["applied"] = False
        log.info(STAGE_REVISION, "rollback", {
            "version": revision_sync["original_version"],
        })
    except Exception as exc:  # noqa: BLE001
        log.warn(STAGE_REVISION, "rollback_failed", {
            "errorType": type(exc).__name__,
        })


def _refresh_content_baseline(paths: ProjectPaths) -> int:
    """正式发布成功后，以当前 content/ 重新建立会话基线。

    基线必须与内容工作区使用同一根目录和 rel_path 规则，否则下一次合并
    会把整棵 ``design/`` 或 ``requirement/`` 目录误判为新增/删除。
    """
    from doc_tool.application.content.index import ContentIndexService
    from doc_tool.application.content.snapshot import ContentSnapshot

    files = [rel for rel, _ in ContentIndexService(paths.content_root).discover_files()]
    snapshot = ContentSnapshot(paths.state_dir)
    snapshot.take(paths.content_root, files)
    snapshot.save()
    return len(files)


def run_pipeline(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    skip_word_refresh: bool = False,
    baseline: bool = False,
    cancel_token: Optional[CancellationToken] = None,
    app_version: str = "",
    progress: Optional[ProgressCallback] = None,
) -> PipelineResult:
    """执行构建→前校验→Word 刷新→后校验管线，返回结构化结果。

    不向调用方抛出异常；所有错误被捕获并映射为 ``StageEvent``。
    Word 刷新阶段需要本机安装 Microsoft Word；无 Word 环境应传
    ``skip_word_refresh=True`` 进行诊断构建。

    ``progress`` 用于把阶段状态实时回传调用方（典型：GUI 进度条）。
    回调在后台线程内触发，实现方需自行转发到 UI 线程；不传则不发进度。

    任务 5.1/5.4/5.5：管线自动获取/释放项目锁，写入脱敏轮转日志，
    并在阶段边界检查取消令牌。Word 保存与构建原子写入受临界区保护。

    任务 7.1：正式模式（``skip_word_refresh=False``）在启动前再次确认 Word
    可用，避免锁已获取后才发现 Word 缺失。
    任务 7.3：构建产物先写入临时文件，前校验、Word 刷新、后校验全部在
    临时文件上进行；只有后校验通过后才原子发布到正式输出路径。
    任务 7.4：发布完成后写入输出状态元数据，标注是否为正式成功。

    修订记录由作者手工维护 ``_revision_record.md``：管线开始处只把该文件的末行
    版本号同步到 ``manifest.documentVersion``（决定封面「版本号」与输出文件名），
    表格内容由构建内核整表覆盖进 Word 修订记录表。工具不再生成修订内容。
    """
    from doc_tool.adapters.kernel import (
        build_with_project,
        refresh_with_project,
        validate_with_project,
    )

    on_progress: ProgressCallback = progress or _noop_progress
    result = PipelineResult(success=False)
    from doc_tool.domain.version import APP_VERSION

    effective_app_version = app_version or APP_VERSION
    log = RuntimeLog(paths, app_version=effective_app_version)

    # 高模式版本只能查看，任何构建都会写 output/、状态和清单，必须在 Word
    # 探测及锁获取之前阻断。
    if not manifest.is_writable():
        err = IncompatibleSchemaError(
            "当前应用不能写入项目模式版本 {0}。".format(manifest.schemaVersion),
            details={"schemaVersion": str(manifest.schemaVersion)},
        )
        result.error_code = err.code
        result.events.append(StageEvent(
            STAGE_BUILD, "failed", detail=err.user_message, error_code=err.code,
        ))
        log.error(STAGE_BUILD, exception=err)
        return result

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

    # --- 修订记录 → 文档版本号同步计划（锁内计算） ---
    revision_sync = None

    # --- 获取项目锁 ---
    try:
        acquire_lock(paths, TASK_BUILD, effective_app_version)
    except ProjectLockBusyError as exc:
        result.error_code = exc.code
        result.events.append(StageEvent(
            STAGE_BUILD, "failed", detail=exc.user_message, error_code=exc.code,
        ))
        log.error(STAGE_BUILD, exception=exc)
        return result

    try:
        # 诊断构建也同步：版本号是 _revision_record.md 的派生值，预览产物的
        # 封面与文件名必须和正式合并一致，否则改完修订记录先诊断一次会看到
        # 旧版本号。清单只在发布成功后落盘。
        revision_sync = _prepare_revision_sync(manifest, paths)
        result = _run_pipeline_inner(
            manifest, paths, skip_word_refresh, baseline, cancel_token,
            result, log, build_with_project, refresh_with_project,
            validate_with_project, on_progress, revision_sync,
        )
        if not result.success:
            _rollback_revision_sync(revision_sync, manifest, log)
        return result
    except CancelledError as exc:
        result.error_code = exc.code
        result.events.append(StageEvent(
            _current_stage(result), "cancelled",
            detail=exc.user_message, error_code=exc.code,
        ))
        log.error(_current_stage(result), status="cancelled", exception=exc)
        _rollback_revision_sync(revision_sync, manifest, log)
        return result
    except Exception as exc:
        err = _map_exception(exc)
        result.error_code = err.code
        result.events.append(StageEvent(
            _current_stage(result), "failed",
            detail=err.user_message, error_code=err.code,
        ))
        log.error(_current_stage(result), exception=exc)
        _rollback_revision_sync(revision_sync, manifest, log)
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
    on_progress: ProgressCallback = _noop_progress,
    revision_sync: Optional[dict] = None,
) -> PipelineResult:
    """管线内部执行（锁已获取），分离以便 finally 释放锁。

    ``on_progress`` 在每个阶段状态变更（started/succeeded/skipped/failed）
    时被调用一次，把进度实时回传给调用方。

    任务 7.3：构建产物先写入临时文件（与正式输出同目录，保证 ``os.replace``
    原子）。前校验、Word 刷新、后校验全部在临时文件上进行。只有后校验
    通过后才原子发布到正式输出路径，并写入状态元数据。任意阶段失败都
    不修改正式输出，仅清理临时文件。
    """
    from doc_tool.domain.output_state import state_file_for, write_state as _write_state
    from doc_tool.domain.version import get_commit_id

    token = cancel_token or CancellationToken()

    def write_state(*args, **kwargs):
        """成功状态写入失败需触发发布回滚；失败诊断写入失败只记日志。"""
        try:
            return _write_state(*args, **kwargs)
        except Exception as exc:
            if kwargs.get("failure_code"):
                log.warn(STAGE_PUBLISH, "failure_state_write_failed", {
                    "errorType": type(exc).__name__,
                })
                return None
            raise

    def _emit(stage: str, status: str, detail: str = "") -> None:
        """把阶段状态实时转发给进度回调（线程安全由调用方保证）。"""
        try:
            on_progress(stage, status, detail)
        except Exception:
            # 进度回调失败不得影响管线主流程
            pass

    class _EmitList(list):
        """``result.events`` 的发出式列表：每次 append 同步转发进度。"""

        def append(self, event: StageEvent) -> None:  # type: ignore[override]
            super().append(event)
            _emit(event.stage, event.status, event.detail)

    result.events = _EmitList()

    # 用于状态元数据的阶段摘要
    stage_summary: list = []

    def _record_stage(stage: str, status: str) -> None:
        stage_summary.append({"stage": stage, "status": status})

    # --- 阶段 0：按 _revision_record.md 末行同步文档版本号（锁内执行） ---
    # 必须在构建之前：版本号决定封面「版本号」与输出文件名。
    _record_stage(
        STAGE_REVISION,
        _sync_revision_version(revision_sync, manifest, result, log),
    )

    # --- 计算正式输出路径与临时输出路径 ---
    output_name = build_output_filename(
        manifest.documentNo,
        manifest.documentName,
        manifest.documentVersion,
        manifest.documentType,
    )
    formal_output = paths.output_dir / output_name
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    # 临时文件与正式输出同目录，保证 os.replace 在同一卷上原子。
    # 必须以 ``.docx`` 结尾：validate_pre/post 会经统一安全入口
    # ``read_docx_package`` 打开它做严格校验，该入口硬校验扩展名（拒绝非
    # ``.docx``），旧命名 ``.<名>.tmp`` 会让每次校验都报「文件扩展名不是
    # .docx」，管线永远无法发布。隐藏点前缀 + ``.tmp-`` 标记仍标示临时性。
    temp_output = paths.output_dir / (".tmp-" + output_name)

    def _cleanup_temp() -> None:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except OSError:
            pass

    def _check_cancel() -> None:
        """阶段边界取消，并保证任何已生成的临时 DOCX 被清理。"""
        try:
            token.check_cancel()
        except CancelledError:
            _cleanup_temp()
            raise

    # --- 阶段 1：构建到临时文件 ---
    _check_cancel()
    result.events.append(StageEvent(STAGE_BUILD, "started"))
    log.info(STAGE_BUILD, "started")
    try:
        # 先删除可能残留的临时文件，避免上次失败遗留
        _cleanup_temp()
        expression_warnings: List[str] = []
        built_path = build_with_project(
            manifest, paths, output_override=str(temp_output),
            on_warning=expression_warnings.append,
        )
        if Path(built_path).resolve() != temp_output.resolve() or not temp_output.is_file():
            raise BuildError(
                "构建内核未按约定生成项目临时输出。",
                details={"returnedFile": Path(built_path).name},
            )
        # 不阻断构建的表达式警告（缺失链接目标/未定义脚注）记录并透出到日志。
        for warning in expression_warnings:
            log.warn(STAGE_BUILD, "expression_warning", {"message": warning})
            # 与 _emit 一致：进度回调异常不得影响管线主流程（否则 UI 桥在
            # 窗口销毁/任务取消竞态下抛异常会被误判为构建失败 E2001）。
            _emit(STAGE_BUILD, "warning", warning)
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
            schema_version=manifest.schemaVersion,
            stages=stage_summary,
            failure_code=err.code,
            compute_hash=False,
        )
        return result

    # --- 阶段 2：刷新前严格校验（临时文件） ---
    _check_cancel()
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
                schema_version=manifest.schemaVersion,
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
            schema_version=manifest.schemaVersion,
            stages=stage_summary,
            failure_code=err.code,
            compute_hash=False,
        )
        return result

    # --- 阶段 3：Word 实机刷新（可选，临时文件） ---
    _check_cancel()
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
                ok, refresh_reason = refresh_with_project(
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
                err = _refresh_error(refresh_reason, manifest.refreshTimeoutSeconds)
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
                    schema_version=manifest.schemaVersion,
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
                schema_version=manifest.schemaVersion,
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
        _check_cancel()
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
                schema_version=manifest.schemaVersion,
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
            schema_version=manifest.schemaVersion,
            stages=stage_summary,
            failure_code=ValidationError.code,
            compute_hash=False,
        )
        return result

    _check_cancel()
    result.events.append(StageEvent(STAGE_PUBLISH, "started"))
    log.info(STAGE_PUBLISH, "started")
    formal_state = state_file_for(formal_output)
    previous_output = paths.output_dir / ("." + output_name + ".previous.bak")
    previous_state = paths.output_dir / ("." + formal_state.name + ".previous.bak")
    had_previous_output = formal_output.exists()
    had_previous_state = formal_state.exists()
    # 发布回滚失败时保留上一版快照：否则 finally 会清掉唯一可恢复的
    # 上一版状态元数据（旧 DOCX + 新/无状态的不一致就永久固化了）。
    publish_restore_failed = False

    def _cleanup_publish_backups() -> None:
        for backup in (previous_output, previous_state):
            try:
                backup.unlink()
            except FileNotFoundError:
                pass

    def _restore_previous_publish() -> None:
        """状态写入失败时恢复发布前的 DOCX 与状态文件。"""
        if had_previous_output and previous_output.exists():
            os.replace(str(previous_output), str(formal_output))
        elif not had_previous_output:
            try:
                formal_output.unlink()
            except FileNotFoundError:
                pass
        if had_previous_state and previous_state.exists():
            os.replace(str(previous_state), str(formal_state))
        elif not had_previous_state:
            try:
                formal_state.unlink()
            except FileNotFoundError:
                pass

    try:
        with token.critical_section():
            _cleanup_publish_backups()
            if had_previous_output:
                shutil.copy2(str(formal_output), str(previous_output))
            if had_previous_state:
                shutil.copy2(str(formal_state), str(previous_state))

            # DOCX 与状态是两个文件，不能用一次 rename 同时提交。先保留上一版
            # 快照，任一后续步骤失败时回滚二者，避免“新 DOCX + 旧/无状态”。
            os.replace(str(temp_output), str(formal_output))
            is_formal = not skip_word_refresh
            write_state(
                str(formal_output),
                formal=is_formal,
                diagnostic=skip_word_refresh,
                app_version=log.app_version,
                commit=get_commit_id(),
                schema_version=manifest.schemaVersion,
                stages=stage_summary + [{"stage": STAGE_PUBLISH, "status": "succeeded"}],
                failure_code="",
                compute_hash=True,
            )

        _cleanup_publish_backups()
        result.events.append(StageEvent(
            STAGE_PUBLISH, "succeeded",
            detail="已原子发布到：{0}".format(formal_output.name),
        ))
        log.info(STAGE_PUBLISH, "succeeded", {"output": formal_output.name})
        _record_stage(STAGE_PUBLISH, "succeeded")
        result.success = True
        result.output_path = str(formal_output)

        # 成功版本写回清单。输出与状态已经一致提交，清单备份/写入失败只记录
        # 警告，不把有效产物误报为失败。
        manifest.mark_successful_build(log.app_version)
        try:
            manifest.save(paths.root)
        except Exception as exc:
            log.warn(STAGE_PUBLISH, "manifest_update_failed", {
                "errorType": type(exc).__name__,
            })
        log.info(STAGE_PUBLISH, "state_written", {
            "formal": is_formal,
            "diagnostic": skip_word_refresh,
        })
        if not skip_word_refresh:
            try:
                baseline_count = _refresh_content_baseline(paths)
                log.info(STAGE_PUBLISH, "content_baseline_refreshed", {
                    "files": baseline_count,
                })
            except Exception as exc:
                log.warn(STAGE_PUBLISH, "content_baseline_refresh_failed", {
                    "errorType": type(exc).__name__,
                })
                result.events.append(StageEvent(
                    STAGE_PUBLISH, "warning",
                    detail="内容基线刷新失败（不影响本次发布）：{0}".format(
                        type(exc).__name__
                    ),
                ))
        try:
            from doc_tool.application.content.history import BuildHistoryStore

            BuildHistoryStore(paths.state_dir).archive(
                manifest,
                paths.resolve(manifest.relative_content_root()),
                paths.resolve(manifest.relative_template_docx()),
                paths.resolve(manifest.relative_asset_root()),
                formal_output,
                diagnostic=skip_word_refresh,
            )
        except Exception as exc:
            log.warn(STAGE_PUBLISH, "history_archive_failed", {
                "errorType": type(exc).__name__,
            })
            # 归档失败不阻断发布，但必须对用户可见，否则追溯链断裂无提示。
            result.events.append(StageEvent(
                STAGE_PUBLISH, "warning",
                detail="历史归档失败（不影响本次发布）：{0}".format(type(exc).__name__),
            ))
    except CancelledError:
        # 临界区内取消不中断，但这里已经是发布临界区
        _cleanup_temp()
        raise
    except Exception as exc:
        try:
            with token.critical_section():
                _restore_previous_publish()
        except OSError as restore_exc:
            publish_restore_failed = True
            log.error(STAGE_PUBLISH, status="rollback_failed", exception=restore_exc)
            # 恢复失败时保留 .previous.bak 快照（finally 不再清理），
            # 并透出可见提示，供用户手动恢复上一版状态元数据。
            result.events.append(StageEvent(
                STAGE_PUBLISH, "warning",
                detail=(
                    "发布回滚失败，已保留上一版快照：{0} / {1}。".format(
                        previous_output.name, previous_state.name
                    )
                ),
            ))
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
            schema_version=manifest.schemaVersion,
            stages=stage_summary,
            failure_code=err.code,
            compute_hash=False,
        )
    finally:
        if not publish_restore_failed:
            _cleanup_publish_backups()

    return result
