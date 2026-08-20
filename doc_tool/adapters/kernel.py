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
from typing import Callable, Dict, Optional, Tuple, Union

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


def _effective_heading_styles(
    manifest: ProjectManifest,
    template_path: Path,
) -> Dict[int, str]:
    """返回可用于段落 ``pStyle`` 的 Heading 样式。

    早期导入器会把“标题 1 Char”等字符样式误写进清单。这类
    styleId 在构建后可暂时存在，但 Word 保存时会删除无效的段落样式
    引用，导致标题和 TOC 全部丢失。构建时从项目模板发现真正的
    paragraph Heading 样式，仅对明确非段落/缺失的旧值自动修复。

    用户/清单显式配置且模板中存在对应段落样式的 styleId 一律保留
    （即使其名字不匹配 ``Heading N`` 命名）——样式映射导入依赖该映射
    驱动往返门禁比对，擅自替换会让试构建用别的 styleId、而门禁仍按
    原映射识别，误报关键差异并阻断导入。
    """
    from doc_tool.adapters.importer import _parse_heading_styles
    from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

    try:
        with read_docx_package(template_path) as package:
            styles_xml = package.read("word/styles.xml")
    except (OSError, KeyError, OOXMLSecurityError):
        return dict(manifest.headingStyles)

    style_to_level = _parse_heading_styles(styles_xml)
    discovered = {level: style_id for style_id, level in style_to_level.items()}
    paragraph_ids = _paragraph_style_ids(styles_xml)
    effective: Dict[int, str] = {}
    changed = False
    for level, configured_style in manifest.headingStyles.items():
        level = int(level)
        configured_style = str(configured_style)
        if style_to_level.get(configured_style) == level:
            effective[level] = configured_style
            continue
        if configured_style in paragraph_ids:
            # 配置的 styleId 是模板中的真实段落样式：保留，不擅自替换。
            effective[level] = configured_style
            continue
        replacement = discovered.get(level)
        if replacement:
            effective[level] = replacement
            changed = True
        else:
            effective[level] = configured_style

    # 旧清单可能缺少模板中已定义的层级，一并补全。
    for level, style_id in discovered.items():
        if level not in effective:
            effective[level] = style_id
            changed = True

    if changed:
        # 同一 Pipeline 成功发布后会保存 manifest，从而完成旧项目
        # 的无损自修复；发布失败时不会写回 project.yml。
        manifest.headingStyles = dict(sorted(effective.items()))
    return dict(sorted(effective.items()))


def _paragraph_style_ids(styles_xml: bytes) -> set:
    """返回模板 styles.xml 中全部段落样式的 styleId 集合。"""
    from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe

    try:
        sroot = parse_xml_safe(styles_xml, "word/styles.xml")
    except OOXMLSecurityError:
        return set()
    from lxml import etree

    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return {
        style.get(w + "styleId")
        for style in sroot.iter(w + "style")
        if style.get(w + "type") == "paragraph" and style.get(w + "styleId")
    }


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
    template_path = paths.resolve(manifest.relative_template_docx())
    heading_styles = _effective_heading_styles(manifest, template_path)
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
            "template": str(template_path),
            "content_root": str(paths.resolve(manifest.relative_content_root())),
            "asset_root": str(paths.resolve(manifest.relative_asset_root())),
            "table_root": str(paths.resolve(manifest.relative_table_root())),
            "revision_record": str(paths.resolve(manifest.relative_content_root()) / "_revision_record.md"),
            "output": str(output_path),
        },
        "headingStyles": heading_styles,
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
    on_warning: Optional[Callable[[str], None]] = None,
) -> str:
    """以项目上下文调用 ``build_docx.build``，返回输出 DOCX 路径。

    ``on_warning`` 可选：构建不阻断的表达式警告（缺失链接目标、未定义脚注等，
    形如 ``源文件:行号 描述``）逐条回调，供上层透出（CLI stderr / 管线日志）。
    """
    ensure_kernel_importable()
    from build_docx import build  # noqa: E402

    config = config_from_project(manifest, paths, output_override)
    output = build(config=config)
    if on_warning is not None:
        for warning in config.get("_expressionWarnings", []):
            on_warning(warning)
    return output


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
) -> Tuple[bool, str]:
    """以项目上下文调用 ``refresh_fields.supervise``。

    返回 ``(是否成功, 原因键)``（``ok/timeout/word_unavailable/save_failed/
    refresh_failed``），由管线按原因映射稳定错误码——旧实现只返回 bool，
    超时/保存失败被上层一律当作「Word 不可用」（E3001）误报。

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
