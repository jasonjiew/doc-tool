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
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from lxml import etree

from doc_tool.adapters.importer import (
    ExtractionResult,
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
    TargetProjectExistsError,
)
from doc_tool.domain.manifest import ProjectManifest, DOCUMENT_TYPES
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
    """

    source_docx: Path
    target_project_root: Path
    document_type: str
    document_no: str
    document_name: str
    document_version: str
    refresh_timeout_seconds: int = 900


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

    @property
    def last_stage(self) -> Optional[ImportStageEvent]:
        return self.events[-1] if self.events else None


def import_first_time(
    request: ImportRequest,
    cancel_token: Optional[CancellationToken] = None,
) -> ImportResult:
    """执行事务化首次导入，返回结构化结果（不向调用方抛出异常）。

    任一阶段失败时：清理暂存目录、写入诊断日志、返回失败结果。源文档与已有
    正式项目永不被修改。
    """
    result = ImportResult(success=False)
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

        # 2. 预检（fail-closed 重新校验）
        _check_cancel()
        _record(result, STAGE_PREFLIGHT, "started")
        preview = preflight(str(source_path))
        if request.document_type not in DOCUMENT_TYPES:
            raise InvalidDocxError(
                "未知的文档类型：{0}".format(request.document_type),
                details={"documentType": request.document_type},
            )
        _record(result, STAGE_PREFLIGHT, "succeeded", metrics={
            "headings": len(preview.headings),
            "images": preview.image_count,
            "tables": preview.table_count,
        })

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
        sha256 = _copy_and_hash(source_path, paths.source_docx)
        result.source_sha256 = sha256
        _record(result, STAGE_COPY_SOURCE, "succeeded", metrics={"sha256": sha256[:12] + "..."})

        # 5. 生成模板 (4.1)
        _check_cancel()
        _record(result, STAGE_GENERATE_TEMPLATE, "started")
        template_meta = generate_template(paths.source_docx, paths.template_docx)
        _record(result, STAGE_GENERATE_TEMPLATE, "succeeded", metrics={
            "headingStyles": len(template_meta.heading_styles),
            "bodyStyle": template_meta.body_style,
        })

        # 6. 提取正文/资源 (4.2)
        _check_cancel()
        _record(result, STAGE_EXTRACT_CONTENT, "started")
        extraction = extract_content(
            paths.source_docx,
            paths.content_dir(request.document_type),
            paths.images_dir(request.document_type),
            paths.tables_dir(request.document_type),
            request.document_type,
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

        # 8. 结构校验 (4.5)
        _check_cancel()
        _record(result, STAGE_VALIDATE_STRUCTURE, "started")
        manifest = _build_manifest(request, paths, template_meta, sha256)
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
        trial_output = _trial_build(manifest, paths)
        _record(result, STAGE_TRIAL_BUILD, "succeeded", metrics={
            "output": Path(trial_output).name,
        })

        # 11. 原子发布 (4.5)
        _check_cancel()
        _record(result, STAGE_PUBLISH, "started")
        with token.critical_section():
            _publish(staging, target)
        staging = None  # 已发布，不再清理
        result.project_root = target
        _record(result, STAGE_PUBLISH, "succeeded", metrics={"project": target.name})

        result.success = True
        return result

    except Exception as exc:
        err = _map_exception(exc)
        result.error_code = err.code
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
    request: ImportRequest, paths: ProjectPaths, template_meta: TemplateMeta, sha256: str
) -> ProjectManifest:
    doc_type = request.document_type
    manifest = ProjectManifest(
        documentType=doc_type,
        documentNo=request.document_no,
        documentName=request.document_name,
        documentVersion=request.document_version,
        sourceSha256=sha256,
        refreshTimeoutSeconds=request.refresh_timeout_seconds,
        headingStyles={level: sid for sid, level in template_meta.heading_styles.items()},
        bodyStyle=template_meta.body_style,
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
    """试构建：在暂存输出目录构建 DOCX，并校验产物为合法 OOXML 包。"""
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
    # 试构建产物为临时诊断文件，发布后由正式构建重新生成；清理以免污染项目。
    try:
        os.remove(str(output_path))
    except OSError:
        pass
    return str(trial_output)


def _verify_valid_docx(path: Path) -> None:
    """校验产物为合法 OOXML 包：ZIP CRC、核心部件、XML 良构。"""
    if not path.exists() or path.stat().st_size == 0:
        raise DocToolError("试构建未生成有效 DOCX 产物。")
    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise DocToolError("试构建产物 ZIP 校验失败：{0}".format(bad))
            names = set(zf.namelist())
            for part in ("word/document.xml", "word/_rels/document.xml.rels"):
                if part not in names:
                    raise DocToolError("试构建产物缺少核心部件：{0}".format(part))
            etree.fromstring(zf.read("word/document.xml"))
    except zipfile.BadZipFile as exc:
        raise DocToolError("试构建产物不是合法 ZIP 包。", details={"error": str(exc)})
    except etree.XMLSyntaxError as exc:
        raise DocToolError("试构建产物 document.xml 解析失败。", details={"error": str(exc)})


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
        "details": {k: str(v) for k, v in err.details.items()},
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def _map_exception(exc: Exception) -> DocToolError:
    """把任意异常映射为结构化错误类型。"""
    if isinstance(exc, DocToolError):
        return exc
    # 导入纯函数使用 ValueError 表示结构问题
    if isinstance(exc, ValueError):
        return InvalidDocxError(
            str(exc),
            suggested_action="源文档结构不符合导入要求，请检查 Word 标题样式后重试。",
        )
    return DocToolError(
        "导入过程中发生意外错误。",
        details={"errorType": type(exc).__name__},
    )
