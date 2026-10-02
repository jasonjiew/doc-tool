# -*- coding: utf-8 -*-
"""\u4ee5 Markdown \u4e3a\u6e90\u5efa\u9879\uff08V2.8 28-E / 5.3\uff09\u3002

\u4e0e\u300c\u5373\u65f6\u6a21\u677f\u586b\u5145\u300d\u7684\u533a\u522b\uff1a

- \u672c\u6a21\u5757\u4ea7\u51fa\u7684\u662f**\u53ef\u6301\u7eed\u7ef4\u62a4\u7684\u9879\u76ee**\uff08``project.yml`` + ``content/`` + ``assets/``\uff09\uff1b
- \u5373\u65f6\u6a21\u677f\u586b\u5145\uff08``template_fill``\uff09\u53ea\u4ece\u4e00\u4efd\u6587\u6863\u76f4\u63a5\u751f\u6210 docx\uff0c**\u4e0d\u5efa\u9879\u76ee**\u3002
\u4e24\u8005\u5171\u4eab\u89e3\u6790\u4e0e\u6e32\u67d3\u80fd\u529b\uff0c\u4f46\u4e0d\u4e92\u76f8\u8c03\u7528\u4ee5\u907f\u514d\u53cc\u91cd\u5b9e\u73b0\u3002

\u5165\u53e3\uff1a\u6587\u4ef6\u6e05\u5355\uff08\u6309\u7ed9\u5b9a\u987a\u5e8f\uff09\u3001\u8d44\u6e90\u76ee\u5f55\u3001\u5e95\u6a21\u4e0e\u89c4\u8303\u5305\u9009\u62e9\u3002
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from doc_tool.application.chapter_order import resolve_chapter_order
from doc_tool.domain.errors import ProjectManifestError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.version import APP_VERSION, PROJECT_SCHEMA_VERSION


@dataclass
class MarkdownProjectResult:
    """\u4ee5 Markdown \u5efa\u9879\u7ed3\u679c\u3002"""

    project_root: Optional[Path] = None
    chapters: List[str] = field(default_factory=list)
    copied_resources: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.project_root is not None and not self.errors

    def to_dict(self) -> dict:
        return {
            "projectRoot": str(self.project_root) if self.project_root else "",
            "ok": self.ok,
            "chapters": list(self.chapters),
            "copiedResources": list(self.copied_resources),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def create_project_from_markdown(
    sources: Sequence[Union[str, Path]],
    project_root: Union[str, Path],
    *,
    asset_roots: Sequence[Union[str, Path]] = (),
    template_path: Optional[Union[str, Path]] = None,
    pack_source: Optional[Union[str, Path]] = None,
    document_name: str = "",
    document_no: str = "",
    document_version: str = "1.0",
    document_type: str = "general",
    chapter_order: Optional[Sequence[str]] = None,
) -> MarkdownProjectResult:
    """\u628a\u4e00\u6279 Markdown \u53d8\u6210\u53ef\u6301\u7eed\u7ef4\u62a4\u9879\u76ee\u3002

    - ``sources`` **\u987a\u5e8f\u5373\u7ae0\u8282\u987a\u5e8f**\uff1b\u4e0e ``chapter_order`` \u5408\u5e76\u540e\u5199\u5165\u663e\u5f0f ``chapters``\uff1b
    - \u8d44\u6e90\u6309\u540d\u5b57\u53bb\u91cd\u590d\u5236\u5230 ``assets/``\uff0c\u91cd\u540d\u51b2\u7a81\u4fdd\u7559\u5148\u5230\u8005\u5e76\u8bb0\u5f55\uff1b
    - \u5e95\u6a21\u4e0e\u89c4\u8303\u5305\u4e3a**\u53ef\u9009**\uff1a\u7f3a\u5931\u53ea\u8b66\u544a\uff0c\u4e0d\u963b\u65ad\u5efa\u9879\uff08\u9ed8\u8ba4\u515c\u5e95\uff09\u3002
    """
    result = MarkdownProjectResult()
    root = Path(project_root)
    if (root / "project.yml").exists():
        result.errors.append("\u76ee\u6807\u76ee\u5f55\u5df2\u5b58\u5728\u9879\u76ee\u6e05\u5355\uff0c\u672a\u8986\u76d6\u3002")
        return result

    content_root = root / "content"
    asset_root = root / "assets"
    table_root = asset_root / "tables"
    template_dir = root / "template"
    for directory in (content_root, table_root, template_dir):
        directory.mkdir(parents=True, exist_ok=True)

    produced: List[str] = []
    for index, item in enumerate(sources or []):
        source = Path(item)
        if not source.is_file():
            result.skipped.append("\u6e90\u6587\u4ef6\u4e0d\u5b58\u5728\uff1a{0}".format(item))
            continue
        name = source.name
        target = content_root / name
        if target.exists():
            suffix_index = index + 1
            while target.exists():
                stem = "{0}-{1}".format(source.stem, suffix_index)
                target = content_root / (stem + source.suffix)
                suffix_index += 1
            result.warnings.append("\u540c\u540d\u7ae0\u8282\u5df2\u5b58\u5728\uff0c\u5df2\u91cd\u547d\u540d\uff1a{0}".format(target.name))
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            result.skipped.append("\u590d\u5236\u5931\u8d25\uff1a{0}\uff08{1}\uff09".format(source, exc))
            continue
        produced.append(target.name)

    resources = _copy_resources(asset_roots, asset_root, result)
    result.copied_resources = resources

    if template_path is not None:
        template = Path(template_path)
        if template.is_file():
            shutil.copy2(template, template_dir / "template.docx")
        else:
            result.warnings.append("\u6307\u5b9a\u5e95\u6a21\u4e0d\u5b58\u5728\uff0c\u5df2\u8df3\u8fc7\uff1a{0}".format(template_path))
    else:
        result.warnings.append("\u672a\u6307\u5b9a\u5e95\u6a21\uff0c\u8bf7\u5728\u9879\u76ee\u5185\u8865\u5145 template/template.docx\u3002")

    pack_ref: Dict[str, str] = {}
    document_kind = ""
    if pack_source is not None:
        from doc_tool.application.standard_pack import (
            install_pack,
            pack_fingerprint,
            validate_pack_dir,
        )

        validation = validate_pack_dir(pack_source)
        if validation.ok and validation.pack is not None:
            target, install = install_pack(pack_source, root)
            result.warnings.extend(install.warnings)
            if target is not None:
                pack_ref = {
                    "id": validation.pack.pack_id,
                    "version": validation.pack.version,
                    "hash": pack_fingerprint(validation.pack),
                }
                document_kind = validation.pack.document_kind
                if not (template_dir / "template.docx").is_file():
                    pack_template = validation.pack.entry("template.docx")
                    if pack_template is not None:
                        shutil.copy2(pack_template, template_dir / "template.docx")
        else:
            result.warnings.extend(validation.errors or ["\u89c4\u8303\u5305\u4e0d\u53ef\u7528\uff0c\u5df2\u8df3\u8fc7\u3002"])

    order = resolve_chapter_order(produced, list(chapter_order or []))
    result.warnings.extend(order.warnings)
    result.chapters = list(order.ordered)

    try:
        manifest = ProjectManifest(
            documentType=document_type,
            documentNo=document_no or "GX-MD",
            documentName=document_name or root.name,
            documentVersion=document_version,
            sourceSha256="",
            schemaVersion=PROJECT_SCHEMA_VERSION,
            paths={
                "templateDocx": "template/template.docx",
                "contentRoot": "content",
                "assetRoot": "assets",
                "tableRoot": "assets/tables",
            },
            headingStyles={1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"},
            bodyStyle="a",
            documentKind=document_kind,
            chapters=result.chapters,
            standardPack=pack_ref,
            qualitySource="pack" if pack_ref else "",
            createdWithVersion=APP_VERSION,
        )
        manifest.save(root)
    except ProjectManifestError as exc:
        result.errors.append("\u6e05\u5355\u6821\u9a8c\u5931\u8d25\uff1a{0}".format(exc))
        return result
    result.project_root = root
    if not result.chapters:
        result.warnings.append("\u672a\u6536\u96c6\u5230\u7ae0\u8282\uff0c\u9879\u76ee\u5c06\u4ee5\u7a7a\u5185\u5bb9\u8d77\u6b65\u3002")
    return result


def _copy_resources(
    asset_roots: Sequence[Union[str, Path]],
    asset_root: Path,
    result: MarkdownProjectResult,
) -> List[str]:
    """\u628a\u8d44\u6e90\u76ee\u5f55\u4e0b\u7684\u6587\u4ef6\u590d\u5236\u5230 ``assets/``\uff08\u540c\u540d\u4fdd\u7559\u5148\u5230\u8005\uff09\u3002"""
    copied: List[str] = []
    seen: set = set()
    for item in asset_roots or []:
        base = Path(item)
        if not base.is_dir():
            result.warnings.append("\u8d44\u6e90\u76ee\u5f55\u4e0d\u5b58\u5728\uff0c\u5df2\u8df3\u8fc7\uff1a{0}".format(item))
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(base).as_posix()
            name = Path(relative).name
            if name in seen:
                result.warnings.append("\u540c\u540d\u8d44\u6e90\u5df2\u5b58\u5728\uff0c\u4fdd\u7559\u5148\u5230\u8005\uff1a{0}".format(name))
                continue
            seen.add(name)
            target = asset_root / relative
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            except OSError as exc:
                result.skipped.append("\u8d44\u6e90\u590d\u5236\u5931\u8d25\uff1a{0}\uff08{1}\uff09".format(relative, exc))
                continue
            copied.append(relative)
    return copied


def describe_entry_point() -> Dict[str, str]:
    """\u8bf4\u660e\u4e09\u6761\u5efa\u9879\u8def\u5f84\u7684\u5dee\u5f02\uff08\u4f9b\u754c\u9762\u4e0e\u6587\u6863\u590d\u7528\uff09\u3002"""
    return {
        "fromPack": "\u4ece\u89c4\u8303\u5305\u8d77\u6b65\uff1a\u5305\u63d0\u4f9b\u7ae0\u8282\u9aa8\u67b6\u4e0e\u914d\u7f6e\uff0c\u9002\u5408\u65b0\u6587\u6863\u3002",
        "fromWord": "\u63a5\u7ba1\u73b0\u6709 Word\uff1a\u590d\u7528\u9884\u68c0/\u6620\u5c04/\u5f80\u8fd4\u95e8\u7981\uff0c\u9002\u5408\u5df2\u6709\u6210\u6587\u3002",
        "fromMarkdown": "\u4ee5 Markdown \u8d77\u6b65\uff1a\u6309\u6587\u4ef6\u987a\u5e8f\u5efa\u7ae0\u8282\uff0c\u9002\u5408\u5df2\u6709 Docs-as-Code \u5185\u5bb9\u3002",
        "instantTemplateFill": "\u5373\u65f6\u6a21\u677f\u586b\u5145\uff1a\u76f4\u63a5\u4ece\u4e00\u4efd\u6587\u6863\u751f\u6210 docx\uff0c**\u4e0d\u5efa\u9879\u76ee**\uff0c\u4e0d\u53ef\u6301\u7eed\u7ef4\u62a4\u3002",
    }
