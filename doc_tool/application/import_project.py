# -*- coding: utf-8 -*-
"""事务化首次导入应用服务。

任务 4.4-4.7：把预检、模板生成、正文/资源提取、章节拆分、结构校验、试构建
组合为原子化的首次导入用例，保证「全部成功才发布正式项目，任一失败不修改源
文档与正式项目」。

流程（同卷暂存 + 原子重命名发布）：
1. ``validate_target`` (4.6)：目标项目目录已存在时预写入拒绝。
2. ``preflight``：对源 DOCX 重新执行结构预检（fail-closed）。
3. ``create_staging``：在目标父目录的同卷创建唯一暂存目录，建立标准子目录。
4. ``copy_source`` (4.4)：只读复制源 DOCX 到 ``original/source.docx``，计算 SHA-256。
5. ``generate_template`` (4.1)：从源副本生成项目模板，记录标题/正文样式。
6. ``extract_content`` (4.2)：提取正文、图片、普通/复杂表格到暂存。
7. ``split_content`` (4.3)：拆分为章节目录树。
8. ``validate_structure`` (4.5 结构校验)：清单路径合法、资源引用可解析。
9. ``save_manifest`` (4.4)：写入 ``project.yml``（相对路径、源哈希、样式）。
10. ``trial_build`` (4.5 试构建)：在暂存输出试构建并校验产物为合法 DOCX 包。
11. ``publish`` (4.5 原子发布)：同卷 ``os.replace`` 暂存目录为最终项目目录。

失败/取消 (4.7)：隔离并清理暂存目录，把脱敏诊断日志写到目标父目录（不写入尚
不存在的正式项目），源文档与任何已有正式项目均不被触碰。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from doc_tool.adapters.importer import (
    TemplateMeta,
    extract_content,
    generate_template,
    split_into_tree,
)
from doc_tool.adapters.preflight import preflight
from doc_tool.domain.cancellation import CancellationToken
from doc_tool.domain.errors import (
    CancelledError,
    DocToolError,
    InvalidDocxError,
    RoundtripCheckError,
    TargetProjectExistsError,
)
from doc_tool.domain.manifest import (
    ProjectManifest,
    READABLE_DOCUMENT_TYPES,
    is_creatable_document_type,
)
from doc_tool.application.content.reimport import _is_revision_record
from doc_tool.domain.paths import ProjectPaths


STAGE_VALIDATE_TARGET = "validate_target"
STAGE_PREFLIGHT = "preflight"
STAGE_CREATE_STAGING = "create_staging"
STAGE_COPY_SOURCE = "copy_source"
STAGE_GENERATE_TEMPLATE = "generate_template"
STAGE_EXTRACT_CONTENT = "extract_content"
STAGE_SPLIT_CONTENT = "split_content"
STAGE_VALIDATE_STRUCTURE = "validate_structure"
STAGE_SAVE_MANIFEST = "save_manifest"
STAGE_TRIAL_BUILD = "trial_build"
STAGE_ROUNDTRIP_CHECK = "roundtrip_check"
STAGE_PUBLISH = "publish"


@dataclass
class ImportRequest:
    """首次导入请求。

    Attributes:
        source_docx: 用户选择的源 DOCX 路径，文件名任意。
        target_project_root: 最终项目目录路径（尚不存在）。
        document_type: 文档类型 general/requirement/design。
        document_no: 文档编号（通用大文档可留空）。
        document_name: 文档名称。
        document_version: 文档版本字符串。
        refresh_timeout_seconds: Word 刷新超时，默认 900。
        require_exact_roundtrip: 往返门禁要求完全一致；开启时非关键（WARN）
            差异也阻止发布，默认 False（仅 BLOCK 差异阻止）。
        heading_style_map: 可选的用户样式映射覆盖（styleId -> 级别 1~6）。
            传入时预检/模板生成/内容提取均按该映射识别标题，清单写入
            ``headingStyles``（级别 -> styleId）；缺省时按自动识别结果。
    """

    source_docx: Path
    target_project_root: Path
    document_type: str
    document_no: str
    document_name: str
    document_version: str
    refresh_timeout_seconds: int = 900
    require_exact_roundtrip: bool = False
    heading_style_map: Optional[Dict[str, int]] = None
    allow_missing_headings: bool = False
    ignore_roundtrip_block: bool = False
    #: CORE 2.3：按大纲整理计划压平跳级标题（保留标题文本与正文顺序）。
    normalize_heading_levels: bool = False
    #: CORE 2.2：自动判断标题前正文范围；为 False 时保持旧行为（不额外建章）。
    decide_pre_title_body: bool = False
    #: CORE R5：应用的命名导入映射预设（未命中项回退自动识别）。
    intakePresetName: str = ""
    #: CORE R5：导入成功后把本次使用的映射保存为该名称的预设。
    intakeSavePreset: str = ""
    #: 标题前正文章节名（仅在决定“保留”时使用）。
    pre_title_chapter_title: str = "前言"
    #: CORE 2.4：试构建失败时用通用底模做一次有界回退重试。
    bounded_template_retry: bool = True
    #: CORE 3.1：写入 ``original/import-record.json`` 导入记录。
    write_intake_record: bool = True
    #: CORE 4.1：只接管这些章节（按标题匹配，空表示整份）；祖先结构自动保留。
    selected_section_titles: List[str] = field(default_factory=list)


@dataclass
class ImportStageEvent:
    stage: str
    status: str  # started/succeeded/failed
    detail: str = ""
    metrics: Dict[str, object] = field(default_factory=dict)


@dataclass
class ImportResult:
    success: bool
    project_root: Optional[Path] = None
    source_sha256: Optional[str] = None
    events: List[ImportStageEvent] = field(default_factory=list)
    error_code: Optional[str] = None
    diagnostic_log: Optional[Path] = None
    suggested_action: Optional[str] = None
    #: CORE R5：预设解析等非阻断提醒（如实带出，不冒充成功/失败）。
    warnings: List[str] = field(default_factory=list)
    #: CORE R5：本次保存的预设名称（空表示未保存）。
    savedPreset: str = ""

    @property
    def last_stage(self) -> Optional[ImportStageEvent]:
        return self.events[-1] if self.events else None


def import_first_time(
    request: ImportRequest,
    cancel_token: Optional[CancellationToken] = None,
    on_event: Optional[Callable[[ImportStageEvent], None]] = None,
) -> ImportResult:
    """执行事务化首次导入，返回结构化结果（不向调用方抛出异常）。

    任一阶段失败时：清理暂存目录、写入诊断日志、返回失败结果。源文档与已有
    正式项目永不被修改。
    """
    result = ImportResult(success=False)
    result._on_event = on_event
    source_path = Path(request.source_docx)
    target = Path(request.target_project_root).resolve()
    staging: Optional[Path] = None
    token = cancel_token or CancellationToken()

    def _check_cancel() -> None:
        token.check_cancel()

    try:
        # 1. 目标预写入拒绝 (4.6)
        _check_cancel()
        _record(result, STAGE_VALIDATE_TARGET, "started")
        if target.exists():
            raise TargetProjectExistsError(
                "目标项目目录已存在：{0}".format(target.name),
                suggested_action="首次导入不会覆盖已有项目，请选择新的项目名称或目录。",
                details={"target": target.name},
            )
        target_parent = target.parent
        target_parent.mkdir(parents=True, exist_ok=True)
        _record(result, STAGE_VALIDATE_TARGET, "succeeded",
                detail="目标目录可用", metrics={"target": target.name})

        from doc_tool.adapters.word_convert import ensure_docx_source
        actual_source, orig_doc = ensure_docx_source(source_path)

        # 2. 预检（fail-closed 重新校验；样式映射优先于自动识别）
        _check_cancel()
        _record(result, STAGE_PREFLIGHT, "started")
        allow_missing = bool(request.allow_missing_headings)
        # 严格模式（require_exact_roundtrip 且未忽略阻断）保留 fail-closed；
        # 普通模式把“缺资源”等可定位缺口转成告警，正文用占位继续（CORE 2.4）。
        strict_mode = bool(request.require_exact_roundtrip) and not bool(
            request.ignore_roundtrip_block
        )
        # CORE R5：命名映射预设（唯一实现在 intake_presets；未命中项回退自动识别）
        effective_heading_map = request.heading_style_map
        resolved_preset = None
        if request.intakePresetName:
            from doc_tool.application.intake_presets import resolve_for_source

            resolved_preset, _preset_info, preset_warnings = resolve_for_source(
                request.intakePresetName, actual_source,
            )
            result.warnings.extend(preset_warnings)
            if effective_heading_map is None and resolved_preset is not None and resolved_preset.mapping:
                effective_heading_map = dict(resolved_preset.mapping)
        preview = preflight(
            str(actual_source),
            heading_style_map=effective_heading_map,
            allow_missing_headings=allow_missing,
            tolerate_missing_resources=not strict_mode,
        )
        fidelity_report = getattr(preview, "fidelity", None)
        if request.document_type not in READABLE_DOCUMENT_TYPES:
            raise InvalidDocxError(
                "未知的文档类型：{0}".format(request.document_type),
                details={"documentType": request.document_type},
            )
        if not is_creatable_document_type(request.document_type):
            # 公共版不再新建 requirement/design 项目；旧项目请走兼容读取或迁移。
            raise InvalidDocxError(
                "公共版只能创建通用大文档项目（documentType=general）。",
                suggested_action=(
                    "旧的需求/详细设计项目可继续读取与构建；如需改为通用项目，"
                    "请使用项目迁移功能。"
                ),
                details={"documentType": request.document_type},
            )
        preflight_metrics = {
            "headings": len(preview.headings),
            "images": preview.image_count,
            "tables": preview.table_count,
        }
        if fidelity_report is not None:
            preflight_metrics["fidelity"] = fidelity_report.summary_text()

        # --- 大纲整理计划（CORE 2.2/2.3）：预览与提取共用同一份决定 ---
        from doc_tool.application.intake_contract import IntakePolicy, PlannedTarget
        from doc_tool.application.intake_outline import (
            PRE_TITLE_RETAIN,
            build_plan,
            decision_style_map,
        )

        effective_heading_map = request.heading_style_map
        outline_plan = None
        intake_plan = None
        retain_pre_title = False
        if request.normalize_heading_levels or request.decide_pre_title_body:
            policy = IntakePolicy.strict() if strict_mode else IntakePolicy.normal()
            _plan, outline_plan = build_plan(
                preview,
                source=source_path,
                target=PlannedTarget(
                    directory=str(target),
                    document_name=request.document_name,
                    document_no=request.document_no,
                    document_version=request.document_version,
                ),
                policy=policy,
                document_type=request.document_type,
                pre_title_blocks=getattr(preview, "pre_title_blocks", []) or [],
                normalize=bool(request.normalize_heading_levels),
            )
            if request.normalize_heading_levels and outline_plan.remapped_count:
                # 只调整需要整理的样式级别，保留其余自动识别结果。
                base_map = dict(preview.heading_style_map or {})
                normalized = decision_style_map(outline_plan.decisions)
                effective_heading_map = {
                    style_id: int(normalized.get(style_id, level))
                    for style_id, level in base_map.items()
                } or request.heading_style_map
                preflight_metrics["levelAdjustments"] = outline_plan.remapped_count
            if request.decide_pre_title_body:
                retain_pre_title = outline_plan.pre_title_mode == PRE_TITLE_RETAIN
                preflight_metrics["preTitleMode"] = outline_plan.pre_title_mode
            intake_plan = _plan
        if preview.warnings:
            preflight_metrics["warnings"] = list(preview.warnings)
        _record(result, STAGE_PREFLIGHT, "succeeded", metrics=preflight_metrics)

        # 3. 创建同卷暂存目录
        _check_cancel()
        _record(result, STAGE_CREATE_STAGING, "started")
        staging = _create_staging(target)
        paths = ProjectPaths(staging)
        paths.ensure_directories(request.document_type)
        _record(result, STAGE_CREATE_STAGING, "succeeded",
                metrics={"staging": staging.name})

        # 4. 只读复制源文档 + SHA-256 (4.4)
        _check_cancel()
        _record(result, STAGE_COPY_SOURCE, "started")
        sha256 = _copy_and_hash(actual_source, paths.source_docx)
        result.source_sha256 = sha256
        if orig_doc is not None:
            try:
                shutil.copy2(str(orig_doc), str(paths.original_dir / orig_doc.name))
            except Exception:
                pass
        _record(result, STAGE_COPY_SOURCE, "succeeded", metrics={"sha256": sha256[:12] + "..."})

        # 5. 生成模板 (4.1)
        _check_cancel()
        _record(result, STAGE_GENERATE_TEMPLATE, "started")
        template_meta = generate_template(
            paths.source_docx,
            paths.template_docx,
            heading_style_map=effective_heading_map,
            allow_missing_headings=allow_missing,
        )
        _record(result, STAGE_GENERATE_TEMPLATE, "succeeded", metrics={
            "headingStyles": len(template_meta.heading_styles),
            "bodyStyle": template_meta.body_style,
        })

        # 6. 提取内容/资源 (4.2)
        _check_cancel()
        _record(result, STAGE_EXTRACT_CONTENT, "started")
        extraction = extract_content(
            paths.source_docx,
            paths.content_dir(request.document_type),
            paths.images_dir(request.document_type),
            paths.tables_dir(request.document_type),
            request.document_type,
            heading_style_map=effective_heading_map,
            allow_missing_headings=allow_missing,
            retain_pre_title_body=retain_pre_title,
            pre_title_title=request.pre_title_chapter_title,
        )
        _record(result, STAGE_EXTRACT_CONTENT, "succeeded", metrics={
            "chapters": extraction.chapter_count,
            "images": extraction.image_count,
            "tables": extraction.table_count,
            "complexTables": extraction.complex_table_count,
        })

        # 7. 章节拆分 (4.3)
        _check_cancel()
        _record(result, STAGE_SPLIT_CONTENT, "started")
        split_result = split_into_tree(paths.content_dir(request.document_type))
        _record(result, STAGE_SPLIT_CONTENT, "succeeded", metrics={
            "dirs": split_result.dirs,
            "mds": split_result.mds,
            "indexes": split_result.indexes,
        })

        # CORE 4.1：按勾选范围裁剪章节树；未选正文不加入，范围外引用集中说明。
        selection_notes: List[str] = []
        if request.selected_section_titles:
            from doc_tool.application.intake_scope import (
                prune_content_tree, selection_from_titles,
            )

            scope_plan = intake_plan or _fallback_scope_plan(preview, request)
            selection = selection_from_titles(scope_plan, request.selected_section_titles)
            prune = prune_content_tree(
                paths.content_dir(request.document_type), selection,
                document_type=request.document_type,
                assets_root=paths.assets_dir(request.document_type),
            )
            selection_notes = prune.summary_lines()
            for line in selection_notes:
                _record(result, STAGE_SPLIT_CONTENT, "warning", detail=line)
            _record(result, STAGE_SPLIT_CONTENT, "succeeded", metrics={
                "kept": len(prune.kept), "removed": len(prune.removed),
                "danglingReferences": len(prune.dangling_references),
            })

        # 7.5 初始化修订记录（从模板/源文档提取，无修订表时生成标准表头）
        try:
            from doc_tool.application.content.revision_record import ensure_revision_record
            content_dir = paths.content_dir(request.document_type)
            md_path = content_dir / "_revision_record.md"
            ensure_revision_record(
                md_path=md_path,
                template_path=paths.template_docx,
                document_type=request.document_type,
                source_path=paths.source_docx,
                allow_empty=True,
            )
        except Exception:
            pass

        # 8. 结构校验 (4.5)
        _check_cancel()
        _record(result, STAGE_VALIDATE_STRUCTURE, "started")
        manifest = _build_manifest(request, paths, template_meta, sha256, is_headless=(not any(h.level == 1 for h in preview.headings)), allow_missing_headings=allow_missing)
        _validate_structure(manifest, paths)
        _record(result, STAGE_VALIDATE_STRUCTURE, "succeeded")

        # 9. 保存清单 (4.4)
        _check_cancel()
        _record(result, STAGE_SAVE_MANIFEST, "started")
        manifest.save(staging)
        _record(result, STAGE_SAVE_MANIFEST, "succeeded",
                metrics={"manifest": "project.yml"})

        # 10. 试构建 (4.5)
        _check_cancel()
        _record(result, STAGE_TRIAL_BUILD, "started")
        fallback_note = ""
        try:
            trial_output = _trial_build(manifest, paths)
        except Exception as first_error:  # noqa: BLE001 - 有界回退后再决定失败
            if not request.bounded_template_retry or strict_mode:
                raise
            fallback_note = _apply_generic_template_fallback(paths, manifest)
            if not fallback_note:
                raise
            _record(result, STAGE_TRIAL_BUILD, "warning", detail=fallback_note)
            trial_output = _trial_build(manifest, paths)
        _record(result, STAGE_TRIAL_BUILD, "succeeded", metrics={
            "output": Path(trial_output).name,
            "fallback": fallback_note,
        })

        # 10b. 往返差异门禁 (2.5)：trial_build 后、publish 前，fail-closed。
        _check_cancel()
        _record(result, STAGE_ROUNDTRIP_CHECK, "started")
        roundtrip_report = None
        roundtrip_error: Optional[BaseException] = None
        try:
            roundtrip_report = _run_roundtrip_check(
                request, paths.source_docx, trial_output, manifest.headingStyles,
                heading_style_map_override=effective_heading_map,
            )
        except RoundtripCheckError as exc:
            if strict_mode:
                raise
            # 对照未完成：记录原因，不毁掉已验证可用的项目（CORE 2.4/D4）。
            roundtrip_error = exc
            _record(result, STAGE_ROUNDTRIP_CHECK, "warning",
                    detail="往返对照未完成：{0}".format(exc.user_message))
        if roundtrip_report is None:
            _remove_trial_output(trial_output)
            _record(result, STAGE_ROUNDTRIP_CHECK, "succeeded", metrics={
                "comparison": "unavailable",
                "reason": str(roundtrip_error or ""),
            })
        if roundtrip_report is not None:
            should_block = (
                (request.require_exact_roundtrip and roundtrip_report.issues)
                or (roundtrip_report.has_block and not request.ignore_roundtrip_block)
            )
            if should_block:
                raise RoundtripCheckError.from_report(
                    roundtrip_report,
                    require_exact=request.require_exact_roundtrip,
                )
            _remove_trial_output(trial_output)
            _record(result, STAGE_ROUNDTRIP_CHECK, "succeeded", metrics={
                "sourceElements": roundtrip_report.source_count,
                "rebuiltElements": roundtrip_report.rebuilt_count,
                "issues": len(roundtrip_report.issues),
                "block": len(roundtrip_report.block_issues),
                "warn": len(roundtrip_report.warn_issues),
            })
        else:
            should_block = False

        # 2.7 保真报告与往返差异摘要持久化到成功项目 logs/（尽力而为）。
        _persist_reports(paths, fidelity_report, roundtrip_report)

        # CORE 3.1-3.4：写导入记录（原件/哈希/决定/处理事实/来源版本）。
        if selection_notes:
            preflight_metrics.setdefault("selectionNotes", list(selection_notes))
        intake_record = None
        if request.write_intake_record:
            try:
                intake_record = _write_intake_record(
                    paths, request, staging_paths_root=staging,
                    source_docx=paths.source_docx, sha256=sha256,
                    preview=preview, extraction=extraction,
                    outline_plan=outline_plan, strict_mode=strict_mode,
                    roundtrip_error=roundtrip_error, target=target,
                    fallback_note=fallback_note,
                )
            except Exception as exc:  # noqa: BLE001 - 账本失败不阻断可用项目
                _record(result, STAGE_SAVE_MANIFEST, "warning",
                        detail="导入记录写入失败：{0}".format(exc))

        # 严格模式：按声明的阈值在发布前拒绝新项目（普通模式不阻断）。
        if strict_mode and intake_record is not None and intake_record.to_fix_count():
            raise RoundtripCheckError(
                "严格模式命中 {0} 项内容问题，已拒绝发布此新项目。".format(
                    intake_record.to_fix_count()
                ),
                suggested_action=(
                    "改用普通模式导入得到可用项目，或在 Word 中处理这些问题后重试；"
                    "源文件与诊断结果已保留。"
                ),
                details={"findings": str(intake_record.to_fix_count())},
            )

        # 2.8 播种重导入基线：首次导入的正文哈希作为后续重导入冲突判定基线。
        _seed_reimport_base(paths, request.document_type)

        # 11. 原子发布 (4.5)
        _check_cancel()
        _record(result, STAGE_PUBLISH, "started")
        with token.critical_section():
            _publish(staging, target)
        staging = None  # 已发布，不再清理
        result.project_root = target
        _record(result, STAGE_PUBLISH, "succeeded", metrics={"project": target.name})

        result.success = True
        # CORE R5：导入成功后按请求保存命名预设（唯一实现在 intake_presets）
        if request.intakeSavePreset:
            from doc_tool.application.intake_presets import save_from_import

            mapping = dict(effective_heading_map or {})
            if not mapping and resolved_preset is not None:
                mapping = dict(getattr(resolved_preset, "mapping", None) or {})
            if not mapping:
                mapping = {
                    str(k): int(v)
                    for k, v in dict(getattr(preview, "heading_style_map", None) or {}).items()
                }
            census = getattr(preview, "style_census", None) or {}
            names = {
                str(key): str(getattr(value, "name", "") or "") for key, value in census.items()
            }
            saved, save_warnings = save_from_import(
                request.intakeSavePreset, actual_source, mapping, style_names=names,
            )
            result.warnings.extend(save_warnings)
            if saved:
                result.savedPreset = saved
        return result

    except Exception as exc:
        err = _map_exception(exc)
        # 受限环境（透明加密/杀软）会把写入与读取变成笼统错误：补一次自检给出可执行建议
        probe = None
        try:
            from doc_tool.application.env_probe import diagnose_environment

            probe = diagnose_environment(
                directory=str(target.parent),
                docx=str(source_path) if source_path.is_file() else None,
            )
        except Exception:  # noqa: BLE001 - 自检失败不影响原始错误
            probe = None
        if probe is not None and not probe.ok:
            result.warnings.extend(probe.advice[:3])
            if probe.advice:
                # 环境自检的建议一定比“联系支持”更可执行：优先采用
                err.suggested_action = probe.advice[0]
        result.error_code = err.code
        result.suggested_action = err.suggested_action
        status = "cancelled" if isinstance(err, CancelledError) else "failed"
        _record(result, _current_stage(result), status,
                detail=err.user_message, error_code=err.code)
        # 失败隔离 (4.7)：先清理暂存，再把真实清理结果写入诊断日志。
        staging_existed = staging is not None and staging.exists()
        if staging is not None and staging.exists():
            shutil.rmtree(str(staging), ignore_errors=True)
        staging_cleaned = staging is None or not staging.exists()
        try:
            result.diagnostic_log = _write_diagnostic_log(
                target, result, err, staging_existed, staging_cleaned
            )
        except OSError:
            # 诊断目录本身不可写时仍返回结构化失败，不让异常处理再次抛异常。
            result.diagnostic_log = None
        return result


# --- 阶段辅助 ---


def _record(
    result: ImportResult,
    stage: str,
    status: str,
    detail: str = "",
    error_code: Optional[str] = None,
    metrics: Optional[Dict[str, object]] = None,
) -> None:
    event = ImportStageEvent(stage, status, detail, metrics or {})
    if error_code:
        event.metrics["errorCode"] = error_code
    result.events.append(event)
    cb = getattr(result, "_on_event", None)
    if cb is not None:
        try:
            cb(event)
        except Exception:
            pass


def _current_stage(result: ImportResult) -> str:
    started = [e for e in result.events if e.status == "started"]
    return started[-1].stage if started else STAGE_VALIDATE_TARGET


def _create_staging(target: Path) -> Path:
    """在目标父目录同卷创建唯一暂存目录（兄弟位置，保证同卷原子重命名）。"""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    prefix = ".{0}.import-staging-{1}-".format(target.name, os.getpid())
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent)))


def _copy_and_hash(source: Path, dest: Path) -> str:
    """只读复制源文件到 dest 并计算 SHA-256。源文件永不被修改。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with open(str(source), "rb") as src, open(str(dest), "wb") as dst:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(
    request: ImportRequest,
    paths: ProjectPaths,
    template_meta: TemplateMeta,
    sha256: str,
    is_headless: bool = False,
    allow_missing_headings: bool = False,
) -> ProjectManifest:
    doc_type = request.document_type
    if request.heading_style_map:
        # 用户映射（styleId -> 级别）写入清单的 headingStyles（级别 -> styleId）。
        # 两个 styleId 被映射到同一级别时不能让「靠后的」静默胜出：映射由样式
        # 映射页按候选优先级（已识别 > 疑似标题 > 使用次数）生成，取先出现者
        # 才符合界面呈现的优先次序。
        heading_styles = {}
        for style_id, level in request.heading_style_map.items():
            heading_styles.setdefault(int(level), str(style_id))
    else:
        # 优先使用模板生成阶段已消解同级冲突的决策映射。直接反查识别映射会
        # 让 styles.xml 中靠后的自定义样式（如基于 heading 1 派生的「标题1」）
        # 顶掉真正的内置 Heading，章节标题随之丢掉大纲级别与编号关联。
        decisions = getattr(template_meta, "heading_style_decisions", None) or {}
        if decisions:
            heading_styles = {int(level): sid for level, sid in decisions.items()}
        else:
            heading_styles = {
                level: sid for sid, level in template_meta.heading_styles.items()
            }
    doc_ver = str(request.document_version or "").strip()
    if not doc_ver:
        from doc_tool.application.content.revision_record import document_version_from_record
        rec_ver = document_version_from_record(paths.content_dir(doc_type) / "_revision_record.md")
        if rec_ver:
            doc_ver = rec_ver
        elif doc_type == "general":
            doc_ver = ""
        else:
            doc_ver = "1.0"
    manifest = ProjectManifest(
        documentType=doc_type,
        documentNo=str(request.document_no or ""),
        documentName=str(request.document_name or ""),
        documentVersion=doc_ver,
        sourceSha256=sha256,
        refreshTimeoutSeconds=request.refresh_timeout_seconds,
        headingStyles=heading_styles,
        bodyStyle=template_meta.body_style,
        is_headless=is_headless,
        allow_missing_headings=allow_missing_headings,
    )
    manifest.paths = {
        "sourceDocx": paths.to_relative(paths.source_docx),
        "templateDocx": paths.to_relative(paths.template_docx),
        "contentRoot": paths.to_relative(paths.content_dir(doc_type)),
        "assetRoot": paths.to_relative(paths.assets_dir(doc_type)),
        "tableRoot": paths.to_relative(paths.tables_dir(doc_type)),
    }
    return manifest


def _validate_structure(manifest: ProjectManifest, paths: ProjectPaths) -> None:
    """结构校验：清单路径合法、模板/内容/资源目录存在、资源引用可解析。"""
    manifest.resolve_paths(paths.root)
    required = [
        paths.source_docx,
        paths.template_docx,
        paths.content_dir(manifest.documentType),
        paths.images_dir(manifest.documentType),
        paths.tables_dir(manifest.documentType),
    ]
    for p in required:
        if not p.exists():
            raise DocToolError(
                "导入产物缺失：{0}".format(p.name),
                details={"missing": str(p.relative_to(paths.root))},
            )
    _check_resource_references(paths, manifest.documentType)


def _check_resource_references(paths: ProjectPaths, doc_type: str) -> None:
    """校验 Markdown 中引用的图片与复杂表格资源均存在。"""
    import re

    content_root = paths.content_dir(doc_type)
    images_root = paths.images_dir(doc_type)
    tables_root = paths.tables_dir(doc_type)
    img_re = re.compile(r"!\[[^\]]*\]\(images/([^\s)]+)\)")
    tbl_re = re.compile(r"<!--\s*TABLE:\d+:([^\s>]+)\s*-->")

    for md_path in content_root.rglob("*.md"):
        text = md_path.read_text(encoding="utf-8")
        for m in img_re.finditer(text):
            if not (images_root / m.group(1)).exists():
                raise DocToolError(
                    "导入产物引用的图片不存在：{0}".format(m.group(1)),
                    details={"image": m.group(1), "from": md_path.name},
                )
        for m in tbl_re.finditer(text):
            if not (tables_root / m.group(1)).exists():
                raise DocToolError(
                    "导入产物引用的复杂表格不存在：{0}".format(m.group(1)),
                    details={"table": m.group(1), "from": md_path.name},
                )


def _trial_build(manifest: ProjectManifest, paths: ProjectPaths) -> str:
    """试构建：在暂存输出目录构建 DOCX，并校验产物为合法 OOXML 包。

    试构建产物保留到往返差异门禁完成后再清理（``_remove_trial_output``），
    供 ``roundtrip_diff`` 对比源 Word 与重建 Word。
    """
    from doc_tool.adapters.kernel import build_with_project, ensure_kernel_importable

    ensure_kernel_importable()
    trial_output = paths.output_dir / ".trial-build.docx"
    try:
        output_path = build_with_project(manifest, paths, output_override=trial_output)
    except Exception as exc:
        # 内核抛 docx_common.AutomationError；映射为结构化构建错误
        from doc_tool.domain.errors import BuildError

        raise BuildError(
            "试构建失败：{0}".format(exc),
            suggested_action="源文档结构无法构建，请检查标题编号连续性与资源引用。",
            details={"errorType": type(exc).__name__},
        )
    _verify_valid_docx(Path(output_path))
    return str(trial_output)


def _fallback_scope_plan(preview, request: ImportRequest):
    """范围裁剪在没有大纲计划时的最小计划（按预检标题直接构造章节候选）。"""
    from doc_tool.application.intake_contract import (
        IntakePlan, IntakePolicy, PlannedTarget,
    )
    from doc_tool.application.intake_outline import build_plan

    plan, _outline = build_plan(
        preview,
        source=Path(request.source_docx),
        target=PlannedTarget(document_name=request.document_name),
        policy=IntakePolicy.strict() if request.require_exact_roundtrip else IntakePolicy.normal(),
        document_type=request.document_type,
        pre_title_blocks=getattr(preview, "pre_title_blocks", []) or [],
    )
    return plan


def _generic_template_path() -> Optional[Path]:
    """仓库/打包内的通用底模（缺失时返回 None）。"""
    candidate = Path(__file__).resolve().parent.parent / "resources" / "generic-template.docx"
    if candidate.is_file():
        return candidate
    try:
        from doc_tool.application.template_fill_plan import resource_root

        root = Path(resource_root())
        fallback = root / "generic-template.docx"
        if fallback.is_file():
            return fallback
    except Exception:  # noqa: BLE001 - 打包环境缺少该模块时按无底模处理
        pass
    return None


def _apply_generic_template_fallback(paths: ProjectPaths, manifest: ProjectManifest) -> str:
    """试构建失败后的**一次**有界回退：改用通用底模并保留原有正文。

    返回一行说明（供结果页展示实际采用的底模）；无可用底模时返回空串，
    调用方据此把该输入判为失败（不宣告导入完成）。
    """
    generic = _generic_template_path()
    if generic is None:
        return ""
    try:
        shutil.copy2(str(generic), str(paths.template_docx))
    except OSError:
        return ""
    return "试构建失败：已改用通用底模重试一次（原底模留在原件中，可再调整）"


def _fidelity_findings_without_extraction(fidelity_findings, extraction_findings):
    """去掉已被“带章节定位的提取事实”覆盖的文档级保真事实（CORE 3.2）。

    同一 feature（如 textbox）在文档级统计里没有章节/元素序号；提取阶段已经给出
    可定位、可替换的事实，保留两条只会让结果页出现重复项。
    """
    covered_features = {
        item.feature for item in extraction_findings if item.target_chapter
    }
    return [
        item for item in fidelity_findings
        if not (item.feature in covered_features and not item.target_chapter)
    ]


def _write_intake_record(
    paths: ProjectPaths,
    request: ImportRequest,
    *,
    staging_paths_root: Optional[Path],
    source_docx: Path,
    sha256: str,
    preview,
    extraction,
    outline_plan,
    strict_mode: bool,
    roundtrip_error: Optional[BaseException],
    target: Path,
    fallback_note: str = "",
):
    """把本轮导入的来源、决定与处理事实写入 ``original/import-record.json``。

    返回写入的 :class:`ImportRecord`（供严格模式发布前按阈值判断）。
    """
    from doc_tool.application.import_record import (
        ImportRecord,
        append_source_version,
        archive_source_version,
        findings_from_extraction,
        findings_from_fidelity,
        merge_findings,
        placeholder_lines,
        unavailable_from_roundtrip,
        write_import_record,
    )

    root = Path(staging_paths_root) if staging_paths_root is not None else paths.root
    retained_rel = "original/source.docx"
    record = ImportRecord(
        sourceSha256=sha256,
        sourceFile=Path(request.source_docx).name,
        actualPolicy="strict" if strict_mode else "normal",
        documentType=request.document_type,
        documentName=request.document_name,
        documentNo=request.document_no,
        documentVersion=request.document_version,
        selectedSections=list(request.selected_section_titles),
        headingDecisions=(
            [item.to_dict() for item in outline_plan.decisions] if outline_plan else []
        ),
        findings=merge_findings(
            _fidelity_findings_without_extraction(
                findings_from_fidelity(getattr(preview, "fidelity", None), retained_path=retained_rel),
                findings_from_extraction(extraction, retained_path=retained_rel),
            ),
            findings_from_extraction(extraction, retained_path=retained_rel),
        ),
        # 正文里实际写入的占位清单（CORE 3.2）：与占位行同一来源，便于结果页/导出核对。
        placeholderLines=placeholder_lines(merge_findings(
            findings_from_extraction(extraction, retained_path=retained_rel),
        )),
        unavailableComparisons=unavailable_from_roundtrip(roundtrip_error),
        retainedPath=retained_rel,
    )
    for warning in list(getattr(preview, "warnings", None) or [])[:10]:
        text_warning = str(warning)
        if "缺" in text_warning or "未找到" in text_warning:
            record.unavailableComparisons.append(text_warning)
    if fallback_note:
        record.unavailableComparisons.append(fallback_note)
    append_source_version(
        record,
        archive_source_version(root, source_docx, sha256, note="首次导入原件"),
    )
    write_import_record(root, record)
    return record


def _remove_trial_output(trial_output: str) -> None:
    """往返门禁完成后清理试构建临时产物。"""
    try:
        os.remove(trial_output)
    except OSError:
        pass


def _run_roundtrip_check(
    request: ImportRequest,
    source_docx: Path,
    trial_output: str,
    manifest_heading_styles: Optional[Dict[int, str]] = None,
    heading_style_map_override: Optional[Dict[str, int]] = None,
):
    """执行源 Word 与试构建重建 Word 的往返差异对比。

    标题识别必须与试构建实际写入的样式一致：试构建用的是清单里的
    ``headingStyles``，比对时若只靠样式名启发式，遇到名称不匹配
    ``Heading N`` 的自定义样式就会认不出标题、把整章误判成正文差异。
    """
    from doc_tool.adapters.roundtrip import roundtrip_diff

    # 用户映射（styleId -> 级别）优先；否则用清单已消解冲突的决策映射
    # （级别 -> styleId），两者都是「试构建实际用的样式」。
    heading_styles: Optional[Dict[int, str]] = None
    effective_map = heading_style_map_override or request.heading_style_map
    if effective_map:
        heading_styles = {
            level: style_id for style_id, level in effective_map.items()
        }
    elif manifest_heading_styles:
        heading_styles = {int(level): str(sid) for level, sid in manifest_heading_styles.items()}
    try:
        return roundtrip_diff(source_docx, trial_output, heading_styles=heading_styles, allow_missing_headings=bool(request.allow_missing_headings))
    except Exception as exc:
        raise RoundtripCheckError(
            "往返对比失败：{0}".format(exc),
            suggested_action="无法对试构建产物执行往返对比，请检查源文档后重试。",
            details={"errorType": type(exc).__name__},
        ) from exc


def _persist_reports(paths: ProjectPaths, fidelity_report, roundtrip_report) -> None:
    """把保真报告与往返差异摘要写入成功项目 ``logs/``（尽力而为）。"""
    try:
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        if fidelity_report is not None:
            (paths.logs_dir / "fidelity.md").write_text(
                fidelity_report.markdown_text() + "\n", encoding="utf-8"
            )
        if roundtrip_report is not None:
            (paths.logs_dir / "roundtrip.md").write_text(
                roundtrip_report.markdown_text() + "\n", encoding="utf-8"
            )
        else:
            (paths.logs_dir / "roundtrip.md").write_text(
                "## 往返对照\n\n对照未完成，未得出差异结论（不视为对照通过）。\n",
                encoding="utf-8",
            )
    except OSError:
        # 日志写入失败不中止导入。
        pass


def _seed_reimport_base(paths: ProjectPaths, doc_type: str) -> None:
    """首次导入成功时播种 ``reimport_base.json``（sha1 正文哈希）。

    重导入用「上次导入后的内容」作为冲突判定基线；首次导入不播种会导致第一次
    重导入无基线、全部章节被判冲突、自动合入失效。本函数在原子发布前写入
    暂存项目，随发布一起进入正式项目。
    """
    content_root = paths.content_dir(doc_type)
    files = {}
    for path in content_root.rglob("*.md"):
        if not path.is_file() or _is_revision_record(path.name):
            continue
        rel = path.relative_to(content_root).as_posix()
        files[rel] = hashlib.sha1(path.read_bytes()).hexdigest()
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    (paths.state_dir / "reimport_base.json").write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _verify_valid_docx(path: Path) -> None:
    """校验产物为合法 OOXML 包：ZIP CRC、核心部件、XML 良构（统一安全入口）。"""
    from doc_tool.domain.ooxml import (
        OOXMLSecurityError,
        parse_xml_safe,
        read_docx_package,
    )

    if not path.exists() or path.stat().st_size == 0:
        raise DocToolError("试构建未生成有效 DOCX 产物。")
    try:
        with read_docx_package(path) as package:
            parse_xml_safe(package.read("word/document.xml"), "word/document.xml")
    except OOXMLSecurityError as exc:
        raise DocToolError(
            "试构建产物校验失败：{0}".format(exc),
            details={"part": exc.part_name, "reason": exc.reason},
        ) from exc


def _publish(staging: Path, target: Path) -> None:
    """同卷原子重命名暂存目录为最终项目目录。"""
    # 发布前再次确认目标未被并发创建
    if target.exists():
        raise TargetProjectExistsError(
            "发布前发现目标项目已被创建，已中止以避免覆盖。",
            details={"target": target.name},
        )
    try:
        os.replace(str(staging), str(target))
    except OSError as exc:
        # 跨卷回退（理论上不会发生，因 staging 与 target 同卷）
        raise DocToolError(
            "原子发布失败：无法重命名暂存目录。",
            suggested_action="请确认目标目录所在卷可写。",
            details={"error": str(exc)},
        )


def _write_diagnostic_log(
    target: Path,
    result: ImportResult,
    err: DocToolError,
    staging_existed: bool,
    staging_cleaned: bool,
) -> Path:
    """失败诊断日志（脱敏）：写入目标父目录，不写入正式项目，不含正文。"""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    log_path = parent / ".{0}.import-failed-{1}.log".format(target.name, stamp)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target.name,
        "errorCode": err.code,
        "errorMessage": err.user_message,
        "suggestedAction": err.suggested_action,
        "sourceSha256": result.source_sha256,
        "stagingExisted": staging_existed,
        "stagingCleaned": staging_cleaned,
        "events": [
            {
                "stage": e.stage,
                "status": e.status,
                "detail": e.detail,
                "metrics": {k: str(v) for k, v in e.metrics.items()},
            }
            for e in result.events
        ],
        "details": {
            k: (v if isinstance(v, (int, float, bool, list, dict)) else str(v))
            for k, v in (err.details or {}).items()
        },
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def _safe_traceback(exc: Exception) -> str:
    """截断的堆栈文本（诊断日志使用；不包含正文或凭据）。"""
    import traceback

    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    text = "".join(lines)
    return text[-2000:]


def _map_exception(exc: Exception) -> DocToolError:
    """把任意异常映射为结构化错误类型。"""
    if isinstance(exc, DocToolError):
        return exc
    # 统一安全解析入口的中性异常 → 导入侧 InvalidDocxError（带稳定错误码）。
    from doc_tool.domain.ooxml import OOXMLSecurityError

    if isinstance(exc, OOXMLSecurityError):
        return InvalidDocxError(
            str(exc),
            suggested_action="源文档无法通过安全解析校验，请确认文件完整后重新导入。",
            details={"part": exc.part_name, "reason": exc.reason},
        )
    # 导入纯函数使用 ValueError 表示结构问题
    if isinstance(exc, ValueError):
        return InvalidDocxError(
            str(exc),
            suggested_action="源文档结构不符合导入要求，请检查 Word 标题样式后重试。",
        )
    return DocToolError(
        "导入过程中发生意外错误。",
        details={
            "errorType": type(exc).__name__,
            # 保留原始异常消息与截断堆栈，便于诊断（诊断日志已整体脱敏）。
            "error": str(exc)[:500],
            "traceback": _safe_traceback(exc),
        },
    )
