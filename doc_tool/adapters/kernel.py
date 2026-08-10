# -*- coding: utf-8 -*-
"""内核适配器：将项目上下文桥接到现有 ``scripts/`` 内核。

任务 2.1-2.4 的适配层。现有构建/校验/刷新内核位于 ``scripts/`` 目录，通过
``docx_common.load_config`` 加载仓库内 ``config/<doc>.yml``。本适配器提供：

1. ``config_from_project``：从 ``ProjectManifest`` + ``ProjectPaths`` 构造与
   ``load_config`` 相同结构的配置字典，让内核函数无需修改即可由项目上下文驱动。
2. ``ensure_kernel_importable``：将 ``scripts/`` 加入 ``sys.path``，使应用层
   可直接导入 ``build_docx``/``validate_docx``/``refresh_fields``。
3. ``build_with_project``/``validate_with_project``/``refresh_with_project``：
   以项目上下文调用内核函数的便捷封装。

旧入口（``scripts/build_docx.py requirement`` 等）继续可用；新入口通过本适配器
调用同一内核，确保事件流、模板语义和最终正文一致。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Optional, Union

from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths, build_output_filename


# doc_tool/adapters/kernel.py -> doc_tool/adapters/ -> doc_tool/ -> doc-automation/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"


def ensure_kernel_importable() -> None:
    """将 ``scripts/`` 加入 ``sys.path``，使内核模块可被导入（幂等）。"""
    scripts = str(_SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def config_from_project(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    output_override: Optional[Union[str, Path]] = None,
) -> Dict:
    """从项目清单和路径构造内核期望的配置字典。

    返回的字典结构与 ``docx_common.load_config`` 一致，可直接传给
    ``build_docx.build(config=...)`` 和 ``validate_docx.validate(config=...)``。
    """
    doc_type = manifest.documentType
    output_name = build_output_filename(
        manifest.documentNo,
        manifest.documentName,
        manifest.documentVersion,
        manifest.documentType,
    )
    output_path = (
        Path(output_override) if output_override else paths.output_dir / output_name
    )
    if not paths.is_inside(output_path):
        from doc_tool.domain.errors import PathEscapeError

        raise PathEscapeError(
            "构建输出路径越出项目根目录。",
            details={"output": output_path.name},
        )
    config: Dict = {
        "documentType": doc_type,
        "documentNo": manifest.documentNo,
        "documentName": manifest.documentName,
        "documentVersion": str(manifest.documentVersion),
        "paths": {
            "template": str(paths.resolve(manifest.relative_template_docx())),
            "content_root": str(paths.resolve(manifest.relative_content_root())),
            "asset_root": str(paths.resolve(manifest.relative_asset_root())),
            "table_root": str(paths.resolve(manifest.relative_table_root())),
            "output": str(output_path),
        },
        "headingStyles": dict(manifest.headingStyles),
        "bodyStyle": manifest.bodyStyle,
        "_base": str(paths.root),
        "_config_path": str(paths.manifest_file),
        "refresh": {"timeoutSeconds": manifest.refreshTimeoutSeconds},
    }
    # 源 DOCX 存在时作为基线，供 validate --baseline 使用。
    source_docx = paths.resolve(manifest.relative_source_docx())
    if source_docx.exists():
        config["paths"]["baseline"] = str(source_docx)
    return config


def build_with_project(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    output_override: Optional[Union[str, Path]] = None,
) -> str:
    """以项目上下文调用 ``build_docx.build``，返回输出 DOCX 路径。"""
    ensure_kernel_importable()
    from build_docx import build  # noqa: E402

    config = config_from_project(manifest, paths, output_override)
    return build(config=config)


def validate_with_project(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    output_override: Optional[Union[str, Path]] = None,
    baseline: bool = False,
    require_refreshed: bool = False,
    report_override: Optional[Union[str, Path]] = None,
) -> bool:
    """以项目上下文调用 ``validate_docx.validate``，返回是否通过。"""
    ensure_kernel_importable()
    from validate_docx import validate  # noqa: E402

    config = config_from_project(manifest, paths, output_override)
    if report_override is None:
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        report_override = paths.logs_dir / (
            manifest.documentType + "-validation.md"
        )
    return validate(
        config=config,
        baseline=baseline,
        require_refreshed=require_refreshed,
        report_override=report_override,
    )


def refresh_with_project(
    manifest: ProjectManifest,
    paths: ProjectPaths,
    output_override: Optional[Union[str, Path]] = None,
) -> bool:
    """以项目上下文调用 ``refresh_fields.supervise``，返回是否刷新成功。

    任务 7.2：刷新由专用 ``DispatchEx("Word.Application")`` 进程完成，
    不复用、不关闭、不终止用户已打开的 Word。超时只 kill 本次专用进程树。
    """
    ensure_kernel_importable()
    from refresh_fields import supervise  # noqa: E402

    config = config_from_project(manifest, paths, output_override)
    output_path = config["paths"]["output"]
    return supervise(
        output_path=output_path,
        timeout=manifest.refreshTimeoutSeconds,
    )
