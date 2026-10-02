# -*- coding: utf-8 -*-
"""正文模块引用在共享管线中的统一展开点（V3.0 30-A/3.4）。

同一份解析入口同时服务：

- 构建：``prepared_source.prepare_markdown`` 在 Mermaid/资源预处理**之前**调用本
  resolver，因此 Word/校验/检查看到的是展开后的正文；
- 出稿与预览：``effective_snapshot`` 在把章节写进快照工作目录时展开，因此离线
  HTML/预览与 Word 使用同一份内容。

没有模块标记的项目不做任何额外解析（零开销、行为不变）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

#: 固定引用与复制编辑的代码块开头（与 module_refs 的语法一致）。
MODULE_MARKERS = ("```doc-module", "```doc-module-copy")

Resolver = Callable[[str, str], str]


def has_module_markers(text: str) -> bool:
    """正文里是否出现模块引用标记（用于跳过无引用章节）。"""
    return any(marker in (text or "") for marker in MODULE_MARKERS)


def project_has_module_declarations(project_root) -> bool:
    """项目是否声明了正文复用（assembly 或任意章节含标记）。"""
    root = Path(project_root)
    try:
        if (root / "reuse").is_dir():
            return True
    except OSError:
        return False
    try:
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(root)
        content_root = ProjectPaths(root).resolve(manifest.relative_content_root())
    except Exception:  # noqa: BLE001 - 清单不可读时按无声明处理
        return False
    for path in content_root.rglob("*.md"):
        try:
            if has_module_markers(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def build_project_resolver(
    project_root,
    *,
    strict: bool = False,
    strict_override: Optional[bool] = None,
) -> Optional[Resolver]:
    """构造 ``(rel_path, text) -> 展开后文本`` 的 resolver；无声明时返回 None。"""
    root = Path(project_root)
    if not project_has_module_declarations(root):
        return None
    try:
        from doc_tool.application.content import reuse_commands as reuse

        context = reuse.load_context(root)
    except Exception:  # noqa: BLE001 - 复用能力不可用时保持原文，不阻断构建
        return None
    effective_strict = strict if strict_override is None else bool(strict_override)
    notes: Dict[str, str] = {}
    resources: Dict[str, Path] = {}

    def _resolve(rel_path: str, text: str) -> str:
        if not has_module_markers(text):
            return text
        try:
            resolution = reuse.resolve_text(
                text, context, host_path=str(rel_path or ""), strict=effective_strict,
            )
        except Exception as exc:  # noqa: BLE001 - 展开失败保留原文并把原因记在 notes
            notes[str(rel_path)] = str(exc) or type(exc).__name__
            return text
        resolved = getattr(resolution, "text", None)
        if isinstance(resolved, str) and resolved:
            from doc_tool.application.content.modules import rewrite_resource_paths, relative_asset_display
            from doc_tool.application.intake_contract import sha256_file
            aliases = {}
            for source in resolution.resources().values():
                source = Path(source).resolve()
                if not source.is_file():
                    continue
                alias = "modules/{0}/{1}".format(sha256_file(source), source.name)
                resources[alias] = source
                aliases[relative_asset_display(source, root)] = alias
            if aliases:
                resolved, _missing = rewrite_resource_paths(resolved, lambda target: aliases.get(target, target))
            return resolved
        warnings = list(getattr(resolution, "warnings", []) or [])
        if warnings:
            notes[str(rel_path)] = str(warnings[0])
        return text

    _resolve.notes = notes  # type: ignore[attr-defined]
    _resolve.context = context  # type: ignore[attr-defined]
    _resolve.resources = resources  # type: ignore[attr-defined]
    return _resolve


__all__ = [
    "MODULE_MARKERS", "Resolver", "has_module_markers",
    "project_has_module_declarations", "build_project_resolver",
]
