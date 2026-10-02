# -*- coding: utf-8 -*-
"""统一出稿：一次请求多格式、同轮重试与聚合索引（CORE-F 6.1-6.6）。

- 一次 :func:`run_project_export` 捕获一份 :class:`EffectiveSnapshot`，DOCX/HTML/
  PDF/源码包都从这**同一轮内容**生成；空范围回退整份并展示实际范围。
- 可读 DOCX 一旦形成稳定副本就登记为可打开结果（待刷新状态），字段刷新/PDF
  转换随后进行；单格式失败或取消不删除其它已完成产物。
- 输出索引 ``export-result.json``（schema 1）记录 captureId、范围/来源、各格式
  path/hash/status/backend/warnings 与失败尝试，供“仅补失败格式”复用同一轮输入。
- 正式状态仍只由既有 :mod:`doc_tool.domain.output_state` 判定；本模块不提升任何
  正式状态，也不推进全项目评审。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.effective_snapshot import (
    EffectiveSnapshot,
    capture_snapshot,
    mark_source_updated,
)
from doc_tool.domain.version import APP_VERSION
from doc_tool.application.intake_contract import (
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_PDF,
    FORMAT_SOURCE_ZIP,
    FORMATS,
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING_CONVERT,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
    STATUS_SKIPPED,
    ExportRequest,
    ExportScope,
    FormatResult,
    format_label,
    fresh_output_path,
    new_round_id,
    normalize_formats,
    resolve_export_directory,
    sha256_file,
    utc_now_iso,
)
from doc_tool.domain.cancellation import CancellationToken

#: 聚合索引文件名（写在导出目录）。
INDEX_NAME = "export-result.json"
INDEX_SCHEMA_VERSION = 1


@dataclass
class ExportReport:
    """一轮出稿结果（含各格式状态与同轮输入位置）。"""

    roundId: str = field(default_factory=new_round_id)
    captureId: str = ""
    createdAt: str = field(default_factory=utc_now_iso)
    scope: ExportScope = field(default_factory=ExportScope)
    sourceMode: str = SOURCE_MODE_SAVED
    destination: str = ""
    outputName: str = ""
    #: V3.2 4.2：本轮出稿使用的变体（空=当前内容）。
    variantId: str = ""
    variantApplied: bool = False
    projectRoot: str = ""
    strict: bool = False
    documentVersion: str = ""
    documentType: str = "general"
    results: List[FormatResult] = field(default_factory=list)
    snapshotWorkDir: str = ""
    docxPath: str = ""
    indexPath: str = ""
    warnings: List[str] = field(default_factory=list)
    unsavedChapters: List[str] = field(default_factory=list)
    omittedChapters: List[str] = field(default_factory=list)
    sourceUpdated: bool = False
    readonlyProject: bool = False

    # --- 查询 ---

    def result_for(self, fmt: str) -> Optional[FormatResult]:
        for item in self.results:
            if item.format == fmt:
                return item
        return None

    def usable_results(self) -> List[FormatResult]:
        return [item for item in self.results if item.usable]

    def failed_formats(self) -> List[str]:
        return [
            item.format for item in self.results
            if item.status in (STATUS_FAILED, STATUS_PENDING_CONVERT)
        ]

    def strict_violations(self) -> List[str]:
        """严格模式下的未达标格式：失败、待转换与未正式刷新。"""
        return [
            item.format for item in self.results
            if item.status in (STATUS_FAILED, STATUS_PENDING_CONVERT, STATUS_PENDING_REFRESH)
        ]

    def all_failed(self) -> bool:
        return not self.usable_results()

    # --- 展示 ---

    def summary_lines(self, limit: int = 3) -> List[str]:
        lines: List[str] = ["本轮范围：{0}（{1}）".format(
            self.scope.describe(len(self.scope.chapters) or 0),
            "当前编辑内容" if self.sourceMode == SOURCE_MODE_CURRENT_BUFFER else "已保存版本",
        )]
        for item in self.results:
            label = format_label(item.format)
            if item.usable:
                lines.append("{0}{1}".format(label, item.label()))
            else:
                lines.append("{0}{1}{2}".format(
                    label, item.label(), ("（" + item.message + "）") if item.message else ""
                ))
        if self.destination:
            lines.append("输出位置：{0}".format(self.destination))
        if self.unsavedChapters:
            lines.append("包含 {0} 章未保存修改（源文件未被改写）".format(len(self.unsavedChapters)))
        if self.omittedChapters:
            lines.append("范围外 {0} 章未纳入本次出稿".format(len(self.omittedChapters)))
        if self.sourceUpdated:
            lines.append("源内容已更新：本轮结果仍对应捕获时版本，可再次生成新轮")
        for warning in self.warnings[:limit]:
            lines.append("提醒：{0}".format(warning))
        if len(self.warnings) > limit:
            lines.append("其余 {0} 项见技术详情".format(len(self.warnings) - limit))
        return lines

    def machine_report(self) -> Dict[str, object]:
        """CLI 单一机器报告（状态/路径/hash/错误码，不含正文）。"""
        return {
            "roundId": self.roundId,
            "captureId": self.captureId,
            "createdAt": self.createdAt,
            "scope": self.scope.to_dict(),
            "sourceMode": self.sourceMode,
            "destination": self.destination,
            "outputName": self.outputName,
            "projectRoot": self.projectRoot,
            "variantId": self.variantId,
            "variantApplied": self.variantApplied,
            "strict": self.strict,
            "documentType": self.documentType,
            "documentVersion": self.documentVersion,
            "results": [item.to_dict() for item in self.results],
            "usable": [item.format for item in self.usable_results()],
            "failed": self.failed_formats(),
            "strictViolations": self.strict_violations(),
            "warnings": list(self.warnings),
            "unsavedChapters": list(self.unsavedChapters),
            "omittedChapters": list(self.omittedChapters),
            "sourceUpdated": self.sourceUpdated,
            "readonlyProject": self.readonlyProject,
            "snapshotWorkDir": self.snapshotWorkDir,
            "docxPath": self.docxPath,
            "indexPath": self.indexPath,
        }

    def to_dict(self) -> Dict[str, object]:
        data = self.machine_report()
        data["schemaVersion"] = INDEX_SCHEMA_VERSION
        return data


# --- 索引读写 ---


def write_export_index(report: ExportReport, destination: Optional[Path] = None) -> Path:
    target_dir = Path(destination or report.destination)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / INDEX_NAME
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(str(tmp), str(target))
    except OSError:
        shutil.move(str(tmp), str(target))
    report.indexPath = str(target)
    return target


def read_export_index(path) -> Optional[ExportReport]:
    target = Path(path)
    if target.is_dir():
        target = target / INDEX_NAME
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schemaVersion") != INDEX_SCHEMA_VERSION:
        return None
    report = ExportReport(
        variantId=str(data.get("variantId") or ""),
        variantApplied=bool(data.get("variantApplied", False)),
        roundId=str(data.get("roundId") or new_round_id()),
        captureId=str(data.get("captureId") or ""),
        createdAt=str(data.get("createdAt") or utc_now_iso()),
        scope=ExportScope.from_dict(data.get("scope")),
        sourceMode=str(data.get("sourceMode") or SOURCE_MODE_SAVED),
        destination=str(data.get("destination") or ""),
        outputName=str(data.get("outputName") or ""),
        projectRoot=str(data.get("projectRoot") or ""),
        strict=bool(data.get("strict", False)),
        documentType=str(data.get("documentType") or "general"),
        documentVersion=str(data.get("documentVersion") or ""),
        results=[FormatResult.from_dict(item) for item in data.get("results") or []],
        snapshotWorkDir=str(data.get("snapshotWorkDir") or ""),
        docxPath=str(data.get("docxPath") or ""),
        indexPath=str(target),
        warnings=[str(item) for item in data.get("warnings") or []],
        unsavedChapters=[str(item) for item in data.get("unsavedChapters") or []],
        omittedChapters=[str(item) for item in data.get("omittedChapters") or []],
        sourceUpdated=bool(data.get("sourceUpdated", False)),
        readonlyProject=bool(data.get("readonlyProject", False)),
    )
    return report


# --- 单格式实现 ---


#: 单项目出稿/正式化的 Word 探测超时（慢机器兜底；批量队列仍用默认 10 s）。
CORE_WORD_PROBE_SECONDS = 30.0


def _word_available() -> bool:
    try:
        from doc_tool.application.word_check import check_word_available

        return bool(
            check_word_available(dispatch_timeout_seconds=CORE_WORD_PROBE_SECONDS).available
        )
    except Exception:  # noqa: BLE001 - 探测失败按不可用走待刷新兜底
        return False


def _default_user_export_dir() -> Optional[Path]:
    try:
        from doc_tool.application.project_service import _config_dir

        return Path(_config_dir()).parent / "exports"
    except Exception:  # noqa: BLE001
        return None


def _output_stem(manifest, request: ExportRequest, snapshot: EffectiveSnapshot) -> str:
    if request.output_name.strip():
        from doc_tool.application.intake_contract import sanitize_name_part

        cleaned = sanitize_name_part(request.output_name)
        if cleaned:
            return cleaned
    try:
        from doc_tool.domain.paths import build_output_filename

        return Path(build_output_filename(
            manifest.document_no, manifest.document_name,
            manifest.document_version, manifest.documentType,
        )).stem
    except Exception:  # noqa: BLE001 - 清单非法时退回文档名
        return manifest.documentName or "导出文档"


def _export_commit_id() -> str:
    """当前提交号（冻结态/异常时为空，不阻断出稿）。"""
    try:
        from doc_tool.application.pipeline import get_commit_id

        return str(get_commit_id() or "")
    except Exception:  # noqa: BLE001
        return ""


def _run_docx(
    snapshot: EffectiveSnapshot,
    request: ExportRequest,
    destination: Path,
    stem: str,
    *,
    refresh: bool,
    cancel_token: Optional[CancellationToken],
    progress,
    word_available: Optional[bool] = None,
) -> Tuple[FormatResult, str]:
    """在快照工作目录构建 DOCX，并把稳定副本复制到导出目录。"""
    from doc_tool.application.pipeline import run_pipeline
    from doc_tool.domain.manifest import ProjectManifest
    from doc_tool.domain.paths import ProjectPaths
    from doc_tool.domain.output_state import is_formal_success

    work = Path(snapshot.workDir)
    paths = ProjectPaths(work)
    manifest = ProjectManifest.load(work)
    # 调用方已确定 Word 可用性时直接采用，避免重复探测（10s 超时会被误判为无 Word）。
    resolved_word = (_word_available() if word_available is None else bool(word_available)) if refresh else False
    use_refresh = bool(refresh) and resolved_word
    if progress is not None:
        progress("docx", "开始生成 Word")
    result = run_pipeline(
        manifest, paths, skip_word_refresh=not use_refresh,
        word_available=resolved_word if use_refresh else None,
        cancel_token=cancel_token, progress=None,
    )
    source_output = None
    pending = False
    if result.success and result.output_path and Path(result.output_path).is_file():
        source_output = Path(result.output_path)
    elif result.pending_output_path and Path(result.pending_output_path).is_file():
        source_output = Path(result.pending_output_path)
        pending = True
    elif result.output_path and Path(result.output_path).is_file():
        source_output = Path(result.output_path)
        pending = not is_formal_success(source_output)
    if source_output is None:
        detail = result.last_stage.detail if result.last_stage else "构建未产出可用文件"
        return FormatResult(
            format=FORMAT_DOCX, status=STATUS_FAILED, error_code=result.error_code or "",
            message=detail or "构建失败", backend="kernel",
        ), ""
    target = fresh_output_path(destination / "{0}.docx".format(stem))
    try:
        shutil.copy2(str(source_output), str(target))
    except OSError as exc:
        return FormatResult(
            format=FORMAT_DOCX, status=STATUS_FAILED, error_code="E8001",
            message="无法写入导出目录：{0}".format(exc), backend="kernel",
        ), ""
    formal = bool(use_refresh and is_formal_success(source_output))
    if formal:
        # 正式状态记录随源文件在快照项目目录；目标目录需要自己的记录，
        # 否则下游（按包正式化/复核）会把已刷新的正式稿误判为待刷新。
        try:
            from doc_tool.domain.output_state import write_state

            write_state(
                str(target), formal=True, diagnostic=False,
                app_version=APP_VERSION,
                commit=_export_commit_id(),
                schema_version=int(getattr(manifest, "schemaVersion", 0) or 0),
                stages=None, compute_hash=True,
            )
        except Exception:  # noqa: BLE001 - 状态写入失败不推翻已生成的正式稿
            pass
    status = STATUS_READY if formal else STATUS_PENDING_REFRESH
    warnings: List[str] = []
    if pending or not formal:
        warnings.append("Word 字段/页码待刷新（可读稿已可打开）")
    if snapshot.unsavedChapters:
        warnings.append("本轮包含未保存编辑 {0} 章".format(len(snapshot.unsavedChapters)))

    # CORE-G：有限排版（默认沿用底模；正文自适应才调整）。
    layout_outcome = _apply_layout(target, request, snapshot)
    if layout_outcome is not None:
        # 结果页要能看到“这次排版做了什么”（沿用底模时也会有一行说明）。
        warnings.extend(layout_outcome.summary_lines()[:5])
        warnings.extend(layout_outcome.warnings[:5])
        if layout_outcome.oversized:
            warnings.append("超宽内容已保留并定位：{0} 处".format(len(layout_outcome.oversized)))
        if not layout_outcome.ok and layout_outcome.message:
            warnings.append(layout_outcome.message)
    return FormatResult(
        format=FORMAT_DOCX, status=status, path=str(target),
        sha256=sha256_file(target), backend="kernel", formal=formal,
        warnings=warnings,
        message="" if formal else "目录/页码待刷新",
    ), str(target)


def _apply_layout(target: Path, request: ExportRequest, snapshot: EffectiveSnapshot):
    """按请求把有限排版应用到本轮 DOCX；沿用底模时不改写产物。"""
    from doc_tool.application.export.layout_profile import LayoutProfile, apply_layout_to_docx

    profile = LayoutProfile.from_dict(request.layout)
    if request.layout_profile == "body-adaptive" and profile.is_template:
        profile = LayoutProfile.body_adaptive()
    if profile.is_template and not profile.landscape_chapters and not profile.page_break_before_chapter:
        return None
    titles = [item.title for item in snapshot.chapters if item.title]
    try:
        return apply_layout_to_docx(target, profile, chapter_titles=titles)
    except Exception as exc:  # noqa: BLE001 - 排版失败保留原产物
        from doc_tool.application.export.layout_profile import LayoutOutcome

        return LayoutOutcome(ok=False, message="排版未应用，已保留原产物：{0}".format(exc))


def _run_html(
    snapshot: EffectiveSnapshot,
    destination: Path,
    *,
    cancel_token: Optional[CancellationToken],
    progress,
) -> FormatResult:
    from doc_tool.application.export.readonly_html import export_readonly_html

    work = Path(snapshot.workDir)
    content_root = work / "content"
    assets_root = work / "assets"
    if progress is not None:
        progress("html", "开始生成离线 HTML")
    try:
        result = export_readonly_html(
            content_root, assets_root, destination / "html", "",
            omitted_unsaved=tuple(snapshot.unsavedChapters), cancel_token=cancel_token,
            document_assets=True,
        )
    except Exception as exc:  # noqa: BLE001 - 单格式失败不影响其它成果
        return FormatResult(
            format=FORMAT_HTML, status=STATUS_FAILED, backend="offline-html",
            message=str(exc) or type(exc).__name__,
        )
    index = Path(result.directory) / "index.html"
    warnings = ["离线 HTML 为静态快照，版式与 Word 不完全一致"]
    for item in list(result.warnings)[:5]:
        message = item.get("message") if isinstance(item, dict) else str(item)
        if message:
            warnings.append(str(message))
    return FormatResult(
        format=FORMAT_HTML, status=STATUS_READY, path=str(index),
        sha256=sha256_file(index), backend="offline-html", warnings=warnings,
    )


def _run_pdf(
    docx_path: str,
    destination: Path,
    stem: str,
    *,
    cancel_token: Optional[CancellationToken],
    progress,
) -> FormatResult:
    if not docx_path or not Path(docx_path).is_file():
        return FormatResult(
            format=FORMAT_PDF, status=STATUS_PENDING_CONVERT,
            message="缺少本轮 DOCX，PDF 待转换（可稍后补）",
        )
    if not _word_available():
        return FormatResult(
            format=FORMAT_PDF, status=STATUS_PENDING_CONVERT,
            message="本机没有可用的 Microsoft Word，PDF 待转换（Word/HTML 已可用）",
        )
    if progress is not None:
        progress("pdf", "开始由本轮 Word 转换 PDF")
    from doc_tool.application.convert import convert_paths

    batch = convert_paths(
        [Path(docx_path)], target_format="pdf", output_dir=destination,
        cancel_token=cancel_token,
    )
    for record in getattr(batch, "records", []) or []:
        if getattr(record, "ok", False) and getattr(record, "target", None):
            target = Path(record.target)
            if target.is_file():
                return FormatResult(
                    format=FORMAT_PDF, status=STATUS_READY, path=str(target),
                    sha256=sha256_file(target), backend="word-com",
                )
        return FormatResult(
            format=FORMAT_PDF, status=STATUS_PENDING_CONVERT,
            error_code=getattr(record, "error_code", "") or "",
            message=getattr(record, "detail", "") or "PDF 转换未完成（可稍后补）",
            backend="word-com",
        )
    return FormatResult(
        format=FORMAT_PDF, status=STATUS_PENDING_CONVERT,
        message="PDF 转换不可用（可稍后补）", backend="word-com",
    )


def _run_source_zip(
    snapshot: EffectiveSnapshot,
    request: ExportRequest,
    destination: Path,
    stem: str,
) -> FormatResult:
    try:
        from doc_tool.application.source_package import build_source_package
    except Exception as exc:  # noqa: BLE001 - 未实现时明确未执行
        return FormatResult(
            format=FORMAT_SOURCE_ZIP, status=STATUS_SKIPPED,
            message="源码包能力不可用：{0}".format(exc),
        )
    target = fresh_output_path(destination / "{0}-源码包.zip".format(stem))
    outcome = build_source_package(
        Path(snapshot.workDir), target,
        scope=snapshot.scope, include_original=bool(request.include_original),
        chapters=[item.rel_path for item in snapshot.chapters],
    )
    if not outcome.ok:
        return FormatResult(
            format=FORMAT_SOURCE_ZIP, status=STATUS_FAILED,
            message=outcome.message or "源码包生成失败",
            warnings=list(outcome.warnings)[:5],
        )
    return FormatResult(
        format=FORMAT_SOURCE_ZIP, status=STATUS_READY, path=str(outcome.path),
        sha256=sha256_file(outcome.path), backend="zip",
        warnings=list(outcome.warnings)[:5],
    )


# --- 主入口 ---


def run_project_export(
    request: ExportRequest,
    *,
    buffer_texts: Optional[Dict[str, str]] = None,
    cancel_token: Optional[CancellationToken] = None,
    progress: Optional[Callable[[str, str], None]] = None,
    skip_word_refresh: bool = False,
    prior: Optional[ExportReport] = None,
    only_formats: Optional[Sequence[str]] = None,
    word_available: Optional[bool] = None,
) -> ExportReport:
    """执行一次统一出稿（多格式、同源、部分成功保留）。

    ``skip_word_refresh=True`` 时即使本机有 Word 也只做诊断构建（CLI/测试用）。
    ``prior`` 提供上一轮报告时复用其快照工作目录与 DOCX 做“只补失败格式”。
    """
    project_root = Path(request.project_root)
    from doc_tool.domain.manifest import ProjectManifest
    from doc_tool.domain.paths import ProjectPaths

    manifest = ProjectManifest.load(project_root)
    paths = ProjectPaths(project_root)

    preferred = Path(request.destination) if request.destination else paths.output_dir
    destination, fallback_note = resolve_export_directory(
        preferred, [paths.output_dir, _default_user_export_dir()],
    )
    snapshot: Optional[EffectiveSnapshot] = None
    if prior is not None and prior.snapshotWorkDir and Path(prior.snapshotWorkDir).is_dir():
        snapshot = _snapshot_from_prior(prior, request)
    if snapshot is None:
        snapshot = capture_snapshot(
            project_root,
            scope=request.scope,
            source_mode=request.source_mode,
            buffer_texts=buffer_texts,
            external_destination=str(destination) if request.destination else "",
            cancel_token=cancel_token,
            variant_id=str(getattr(request, "variant_id", "") or ""),
        )
    else:
        mark_source_updated(snapshot)

    report = ExportReport(
        captureId=snapshot.captureId,
        variantId=str(getattr(snapshot, "variantId", "") or ""),
        variantApplied=bool(getattr(snapshot, "variantApplied", False)),
        scope=snapshot.scope,
        sourceMode=snapshot.sourceMode,
        destination=str(destination),
        projectRoot=str(project_root),
        strict=bool(request.strict),
        documentType=manifest.documentType,
        documentVersion=manifest.documentVersion,
        snapshotWorkDir=snapshot.workDir,
        unsavedChapters=list(snapshot.unsavedChapters),
        omittedChapters=list(snapshot.omittedChapters),
        sourceUpdated=snapshot.sourceUpdated,
        readonlyProject=snapshot.readonlyProject,
        warnings=list(snapshot.warnings) + list(getattr(snapshot, "variantWarnings", []) or []),
    )
    if fallback_note:
        report.warnings.append(fallback_note)
    report.outputName = _output_stem(manifest, request, snapshot)

    formats = normalize_formats(only_formats if only_formats is not None else request.formats)
    if prior is not None and only_formats is not None:
        # 只补失败格式：保留上一轮其它可用结果，不重生成
        for item in prior.results:
            if item.format not in formats:
                report.results.append(item)
    docx_path = report_docx_path(prior) if prior is not None else ""

    for fmt in formats:
        if cancel_token is not None:
            try:
                cancel_token.check_cancel()
            except Exception:  # noqa: BLE001 - 取消保留已完成格式
                report.results.append(FormatResult(
                    format=fmt, status=STATUS_CANCELLED, message="已取消，其它已完成格式保留",
                ))
                continue
        if fmt == FORMAT_DOCX:
            result, docx_path = _run_docx(
                snapshot, request, destination, report.outputName,
                refresh=bool(request.refresh) and not skip_word_refresh,
                cancel_token=cancel_token, progress=progress,
                word_available=word_available,
            )
        elif fmt == FORMAT_HTML:
            result = _run_html(snapshot, destination, cancel_token=cancel_token, progress=progress)
        elif fmt == FORMAT_PDF:
            result = _run_pdf(
                docx_path, destination, report.outputName,
                cancel_token=cancel_token, progress=progress,
            )
        elif fmt == FORMAT_SOURCE_ZIP:
            result = _run_source_zip(snapshot, request, destination, report.outputName)
        else:
            result = FormatResult(
                format=fmt, status=STATUS_SKIPPED, message="未知格式：{0}".format(fmt),
            )
        existing = report.result_for(fmt)
        if existing is not None:
            report.results = [item for item in report.results if item.format != fmt]
        report.results.append(result)

    report.docxPath = docx_path
    if report.strict and report.strict_violations():
        report.warnings.append("严格模式：{0} 未达到正式要求".format(
            "、".join(format_label(item) for item in report.strict_violations())
        ))
    write_export_index(report, destination)
    return report


def report_docx_path(report: Optional[ExportReport]) -> str:
    if report is None:
        return ""
    if report.docxPath and Path(report.docxPath).is_file():
        return report.docxPath
    result = report.result_for(FORMAT_DOCX)
    if result is not None and result.path and Path(result.path).is_file():
        return result.path
    return ""


def _snapshot_from_prior(prior: ExportReport, request: ExportRequest) -> Optional[EffectiveSnapshot]:
    """复用上一轮快照工作目录（补格式时保证仍用原轮内容）。"""
    work = Path(prior.snapshotWorkDir)
    if not work.is_dir():
        return None
    snapshot = EffectiveSnapshot(
        captureId=prior.captureId,
        scope=prior.scope,
        sourceMode=prior.sourceMode,
        documentType=prior.documentType,
        projectRoot=request.project_root,
        workDir=str(work),
        omittedChapters=list(prior.omittedChapters),
        unsavedChapters=list(prior.unsavedChapters),
        readonlyProject=prior.readonlyProject,
        warnings=[],
    )
    from doc_tool.application.effective_snapshot import discover_chapters

    content_root = work / "content"
    for rel_path, path in discover_chapters(content_root):
        snapshot.chapters.append(_chapter_stub(rel_path, path))
    return snapshot


def _chapter_stub(rel_path: str, path: Path):
    from doc_tool.application.effective_snapshot import SnapshotChapter
    from doc_tool.application.intake_contract import sha256_text

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    digest = sha256_text(text)
    return SnapshotChapter(
        rel_path=rel_path, title=Path(rel_path).stem, contentHash=digest,
        diskHash=digest, source=SOURCE_MODE_SAVED, location={"relPath": rel_path},
    )


def retry_export_formats(
    report: ExportReport,
    formats: Sequence[str],
    *,
    request: Optional[ExportRequest] = None,
    buffer_texts: Optional[Dict[str, str]] = None,
    cancel_token: Optional[CancellationToken] = None,
    progress: Optional[Callable[[str, str], None]] = None,
    skip_word_refresh: bool = False,
) -> ExportReport:
    """仅补失败/待转换格式：使用原轮快照与 DOCX，不混入当前新正文。"""
    effective = request or ExportRequest(
        project_root=report.projectRoot, formats=list(formats), scope=report.scope,
        source_mode=report.sourceMode, destination=report.destination,
        output_name=report.outputName, strict=report.strict,
    )
    if not effective.project_root:
        raise ValueError("补格式需要原轮项目位置：请从结果页或索引文件恢复报告。")
    return run_project_export(
        effective, buffer_texts=buffer_texts, cancel_token=cancel_token,
        progress=progress, skip_word_refresh=skip_word_refresh,
        prior=report, only_formats=list(formats),
    )


__all__ = [
    "INDEX_NAME", "INDEX_SCHEMA_VERSION", "ExportReport", "write_export_index",
    "read_export_index", "run_project_export", "retry_export_formats",
    "report_docx_path",
]
