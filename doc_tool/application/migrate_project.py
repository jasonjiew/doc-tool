# -*- coding: utf-8 -*-
"""旧版专用项目迁移为通用大文档项目。

任务 5.3/5.4：把 schema v1 的 ``requirement`` / ``design`` 项目复制到新目录并
转换为 ``general``，在结构、资源与试构建全部验证通过后才原子提交。源项目全程
只读，不被修改。

迁移语义：
- 目标目录必须是新目录（同卷暂存 + 原子重命名发布，与首次导入一致）。
- 复制源项目全部内容（排除运行锁与运行时状态 ``.state``），保留源项目不变。
- 目录重写：``content/<legacy>`` → ``content/general``，``assets/<legacy>`` →
  ``assets/general``（含 ``tables``）。
- 清单重写：``documentType: general``；编号/版本作为可选元数据保留。
- Markdown 内部引用（``images/``、``TABLE:``）相对 content 根，目录重命名后
  仍然有效，无需逐文件改写。
- 结构校验 + 资源引用校验 + 试构建全部通过后才发布；任一失败清理暂存并返回
  失败报告，源项目保持可用。

迁移报告（``logs/migration.json``）记录来源、目标、时间、路径映射与校验结果。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from doc_tool.domain.errors import DocToolError, ProjectManifestError
from doc_tool.domain.manifest import (
    ProjectManifest,
    is_legacy_document_type,
)
from doc_tool.domain.paths import ProjectPaths

# 迁移过程中需要排除的顶层文件/目录。
# - project.lock：旧版遗留的根级运行锁。
# - .state：运行时状态目录（含真实运行锁 .state/project.lock、会话/草稿/基线），
#   其内容引用源项目旧路径，迁移到新项目后为过期状态，不应复制。
_MIGRATION_EXCLUDED = {"project.lock", ".state"}


@dataclass
class MigrationEvent:
    stage: str
    status: str  # started/succeeded/failed
    detail: str = ""


@dataclass
class MigrationResult:
    success: bool
    source: Path
    target: Path
    events: List[MigrationEvent] = field(default_factory=list)
    error_code: str = ""
    report_path: Optional[Path] = None

    @property
    def last_event(self) -> Optional[MigrationEvent]:
        return self.events[-1] if self.events else None


def _record(result: MigrationResult, stage: str, status: str, detail: str = "") -> None:
    result.events.append(MigrationEvent(stage, status, detail))


def _legacy_content_dir(paths: ProjectPaths, doc_type: str) -> Path:
    """返回旧版专用内容目录（``content/<type>``）。"""
    return paths.content_root / doc_type


def _legacy_assets_dir(paths: ProjectPaths, doc_type: str) -> Path:
    """返回旧版专用资源目录（``assets/<type>``）。"""
    return paths.assets_root / doc_type


def _copy_tree(source: Path, staging: Path) -> None:
    """复制项目树到暂存目录，排除运行锁与运行时状态（.state）。"""
    for item in source.iterdir():
        if item.name in _MIGRATION_EXCLUDED:
            continue
        dest = staging / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


def _rewrite_to_general(staging: Path, doc_type: str) -> ProjectManifest:
    """把暂存项目清单重写为 general，并重命名内容/资源目录。

    Returns:
        重写后的 ``ProjectManifest``（绑定到暂存根）。

    Raises:
        ProjectManifestError: 清单无法加载或重写后校验失败。
    """
    manifest = ProjectManifest.load(staging)
    if not is_legacy_document_type(manifest.documentType):
        raise ProjectManifestError(
            "源项目不是旧版专用项目：{0}".format(manifest.documentType),
            details={"documentType": manifest.documentType},
        )

    # 目录重命名：content/<legacy> -> content/general；assets/<legacy> -> assets/general
    paths = ProjectPaths(staging)
    old_content = _legacy_content_dir(paths, manifest.documentType)
    new_content = paths.content_root / "general"
    old_assets = _legacy_assets_dir(paths, manifest.documentType)
    new_assets = paths.assets_root / "general"
    for old, new in ((old_content, new_content), (old_assets, new_assets)):
        if old.exists() and old != new:
            new.parent.mkdir(parents=True, exist_ok=True)
            if new.exists():
                shutil.rmtree(str(new))
            old.rename(new)

    # 清单重写
    manifest.documentType = "general"
    manifest.paths = {
        "sourceDocx": manifest.paths.get("sourceDocx", "original/source.docx"),
        "templateDocx": manifest.paths.get("templateDocx", "template/template.docx"),
        "contentRoot": paths.to_relative(paths.content_root / "general"),
        "assetRoot": paths.to_relative(paths.assets_root / "general"),
        "tableRoot": paths.to_relative(paths.assets_root / "general" / "tables"),
    }
    manifest.save(staging)
    return ProjectManifest.load(staging)


def _validate_structure_and_resources(manifest: ProjectManifest, paths: ProjectPaths) -> None:
    """结构 + 资源引用校验（复用首次导入的校验语义）。"""
    from doc_tool.application.import_project import _check_resource_references

    manifest.resolve_paths(paths.root)
    required = [
        paths.source_docx,
        paths.template_docx,
        paths.content_root / "general",
        paths.assets_root / "general" / "images",
        paths.assets_root / "general" / "tables",
    ]
    for p in required:
        if not p.exists():
            raise DocToolError(
                "迁移产物缺失：{0}".format(p.name),
                details={"missing": str(p.relative_to(paths.root))},
            )
    _check_resource_references(paths, "general")


def _trial_build(manifest: ProjectManifest, paths: ProjectPaths) -> None:
    """试构建：在暂存输出构建并校验产物为合法 OOXML 包。"""
    from doc_tool.adapters.kernel import build_with_project, ensure_kernel_importable
    from doc_tool.application.import_project import _verify_valid_docx

    ensure_kernel_importable()
    trial_output = paths.output_dir / ".trial-build.docx"
    try:
        output_path = build_with_project(manifest, paths, output_override=trial_output)
    except Exception as exc:  # noqa: BLE001
        from doc_tool.domain.errors import BuildError

        raise BuildError(
            "迁移试构建失败：{0}".format(exc),
            suggested_action="源项目内容无法按通用项目构建，请检查内容与资源引用。",
            details={"errorType": type(exc).__name__},
        )
    _verify_valid_docx(Path(output_path))
    # 试构建产物仅用于合法性验证；发布前清理，避免迁移项目残留 output/.trial-build.docx。
    try:
        os.remove(trial_output)
    except OSError:
        pass


def _write_migration_report(
    target: Path, manifest: ProjectManifest, source: Path, doc_type: str
) -> Path:
    """把迁移报告写入目标项目 ``logs/migration.json``。"""
    paths = ProjectPaths(target)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = paths.logs_dir / "migration.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source.resolve()),
        "target": str(target.resolve()),
        "sourceDocumentType": doc_type,
        "targetDocumentType": "general",
        "pathRewrite": {
            "contentRoot": "content/{0}".format(doc_type) + " -> content/general",
            "assetRoot": "assets/{0}".format(doc_type) + " -> assets/general",
        },
        "notes": "源项目保持只读，未被修改。",
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_path


def migrate_legacy_project(
    source_root, target_project_root
) -> MigrationResult:
    """把旧版专用项目迁移为通用项目（复制到新目录 + 验证后原子发布）。

    Args:
        source_root: 源旧版项目根目录。
        target_project_root: 目标通用项目根目录（必须不存在）。

    Returns:
        ``MigrationResult``；失败时源项目保持可用，暂存目录被清理。
    """
    source = Path(source_root).resolve()
    target = Path(target_project_root).resolve()
    result = MigrationResult(success=False, source=source, target=target)
    staging: Optional[Path] = None

    try:
        # 1. 读取源清单并校验为旧版专用项目
        _record(result, "load_source", "started")
        source_manifest = ProjectManifest.load(source)
        if not is_legacy_document_type(source_manifest.documentType):
            raise ProjectManifestError(
                "源项目不是旧版专用项目：{0}".format(source_manifest.documentType),
                suggested_action="只有 requirement/design 项目需要迁移；general 项目已是通用类型。",
                details={"documentType": source_manifest.documentType},
            )
        legacy_type = source_manifest.documentType
        _record(result, "load_source", "succeeded",
                detail="sourceDocumentType={0}".format(legacy_type))

        # 2. 目标目录预写入拒绝
        if target.exists():
            raise DocToolError(
                "目标项目目录已存在：{0}".format(target.name),
                suggested_action="迁移不会覆盖已有项目，请选择新的目标目录。",
                details={"target": target.name},
            )
        target.parent.mkdir(parents=True, exist_ok=True)

        # 3. 同卷暂存 + 复制源项目（只读源）
        _record(result, "create_staging", "started")
        prefix = ".{0}.migrate-staging-{1}-".format(target.name, os.getpid())
        staging = Path(tempfile.mkdtemp(prefix=prefix, dir=str(target.parent)))
        _copy_tree(source, staging)
        _record(result, "create_staging", "succeeded", detail="copied source unchanged")

        # 4. 清单与目录重写为 general
        _record(result, "rewrite_general", "started")
        manifest = _rewrite_to_general(staging, legacy_type)
        _record(result, "rewrite_general", "succeeded",
                detail="documentType -> general")

        # 5. 结构 + 资源校验
        _record(result, "validate_structure", "started")
        paths = manifest.resolve_paths(staging)
        _validate_structure_and_resources(manifest, paths)
        _record(result, "validate_structure", "succeeded")

        # 6. 试构建
        _record(result, "trial_build", "started")
        _trial_build(manifest, paths)
        _record(result, "trial_build", "succeeded", detail="output=.trial-build.docx")

        # 7. 迁移报告
        _record(result, "write_report", "started")
        result.report_path = _write_migration_report(staging, manifest, source, legacy_type)
        _record(result, "write_report", "succeeded")

        # 8. 原子发布
        _record(result, "publish", "started")
        os.replace(str(staging), str(target))
        staging = None
        result.success = True
        result.report_path = target / "logs" / "migration.json"
        _record(result, "publish", "succeeded", detail="target=" + target.name)
        return result

    except Exception as exc:  # noqa: BLE001
        result.error_code = getattr(exc, "code", "E9000")
        status = "failed"
        _record(result, result.last_event.stage if result.last_event else "migrate",
                status, detail=getattr(exc, "user_message", str(exc)))
        if staging is not None and staging.exists():
            shutil.rmtree(str(staging), ignore_errors=True)
        return result
