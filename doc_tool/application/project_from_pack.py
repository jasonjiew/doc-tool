# -*- coding: utf-8 -*-
"""\u4ece\u89c4\u8303\u5305\u8d77\u6b65\u5efa\u9879\uff08V2.8 28-E / 5.1\uff09\u3002

\u53ea\u8d1f\u8d23**\u670d\u52a1\u5c42**\uff1a\u6821\u9a8c\u5305 \u2192 \u56fa\u5b9a\u7248\u672c \u2192 \u751f\u6210\u6e05\u5355/\u7ae0\u8282/\u8d44\u6e90\u4e0e\u5171\u4eab\u914d\u7f6e\u3002
\u7ba1\u7406\u754c\u9762\u53ea\u9700\u8c03\u7528\u672c\u51fd\u6570\uff0c\u4e0d\u91cd\u590d\u5b9e\u73b0\u5305\u89e3\u6790\u4e0e\u6e05\u5355\u5199\u5165\u3002
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from doc_tool.application.standard_pack import (
    STANDARDS_DIR,
    PackManifest,
    install_pack,
    pack_fingerprint,
    pack_skeleton_files,
    validate_pack_dir,
)
from doc_tool.domain.errors import ProjectManifestError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.version import APP_VERSION, PROJECT_SCHEMA_VERSION


@dataclass
class PackProjectResult:
    """\u5efa\u9879\u7ed3\u679c\u3002"""

    project_root: Optional[Path] = None
    manifest_path: Optional[Path] = None
    chapters: List[str] = field(default_factory=list)
    created_assets: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.project_root is not None and not self.errors


def create_project_from_pack(
    pack_source: Union[str, Path],
    project_root: Union[str, Path],
    *,
    document_name: str = "",
    document_no: str = "",
    document_version: str = "1.0",
    document_type: str = "general",
) -> PackProjectResult:
    """\u4ece\u89c4\u8303\u5305\u521b\u5efa\u53ef\u7ef4\u62a4\u9879\u76ee\uff08\u7ae0\u8282\u9aa8\u67b6\u4e0e\u5171\u4eab\u914d\u7f6e\u4e00\u6b65\u5230\u4f4d\uff09\u3002

    - \u5e95\u6a21\u7f3a\u5931\u65f6\u53ea\u8b66\u544a\u5e76\u7ee7\u7eed\uff08\u56de\u9000\u901a\u7528\u5e95\u6a21\u7531\u8c03\u7528\u65b9\u5904\u7406\uff09\uff1b
    - \u9aa8\u67b6\u6309\u540d\u79f0\u6392\u5e8f\u5199\u5165 ``contentRoot``\uff0c\u5e76\u4f5c\u4e3a\u663e\u5f0f ``chapters``\uff1b
    - \u53d8\u91cf/\u672f\u8bed/\u89c4\u5219\u5199\u5165\u9879\u76ee ``quality/``\uff08\u4f9b\u56e2\u961f\u5171\u4eab\uff09\uff1b
    - \u4e0d\u5199\u5165\u4efb\u4f55\u7edd\u5bf9\u8def\u5f84\uff0c\u9879\u76ee\u6574\u4f53\u53ef\u590d\u5236\u3002
    """
    result = PackProjectResult()
    validation = validate_pack_dir(pack_source)
    if not validation.ok or validation.pack is None:
        result.errors.extend(validation.errors or ["\u89c4\u8303\u5305\u4e0d\u53ef\u7528\u3002"])
        return result
    pack = validation.pack
    result.warnings.extend(validation.warnings)

    root = Path(project_root)
    if (root / "project.yml").exists():
        result.errors.append("\u76ee\u6807\u76ee\u5f55\u5df2\u5b58\u5728\u9879\u76ee\u6e05\u5355\uff0c\u672a\u8986\u76d6\u3002")
        return result

    content_root = root / "content"
    asset_root = root / "assets"
    table_root = asset_root / "tables"
    template_dir = root / "template"
    for directory in (content_root, table_root, template_dir, root / "quality"):
        directory.mkdir(parents=True, exist_ok=True)

    target, install = install_pack(pack_source, root)
    result.warnings.extend(install.warnings)
    if not install.ok or target is None:
        result.errors.extend(install.errors or ["\u89c4\u8303\u5305\u56fa\u5b9a\u5931\u8d25\u3002"])
        return result
    installed = install.pack or pack

    template_source = installed.entry("template.docx")
    if template_source is not None:
        shutil.copy2(template_source, template_dir / "template.docx")
    else:
        result.warnings.append("\u89c4\u8303\u5305\u672a\u5305\u542b\u5e95\u6a21\uff0c\u8bf7\u5728\u9879\u76ee\u5185\u8865\u5145 template/template.docx\u3002")

    chapters: List[str] = []
    for skeleton in pack_skeleton_files(installed):
        relative = skeleton.relative_to(installed.root).as_posix()
        target_file = content_root / Path(relative).name
        text = skeleton.read_text(encoding="utf-8")
        target_file.write_text(text, encoding="utf-8")
        chapters.append(target_file.name)
        result.created_assets.append(relative)

    variables = _read_mapping(installed, "variables.yml", result)
    terms = _read_mapping(installed, "terms.yml", result)
    rules = _read_mapping(installed, "rules.yml", result)
    quality_dir = root / "quality"
    if variables:
        _write_yaml(quality_dir / "variables.json", variables)
    if terms:
        _write_yaml(quality_dir / "terms.json", terms)
    if rules:
        _write_yaml(quality_dir / "rules.json", rules)

    manifest = ProjectManifest(
        documentType=document_type,
        documentNo=document_no or "GX-NEW",
        documentName=document_name or (installed.description or installed.pack_id),
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
        documentKind=installed.document_kind,
        chapters=chapters,
        variables={key: str(value) for key, value in variables.items()},
        standardPack={
            "id": installed.pack_id,
            "version": installed.version,
            "hash": pack_fingerprint(installed),
        },
        qualitySource="pack",
        createdWithVersion=APP_VERSION,
    )
    try:
        manifest.save(root)
    except ProjectManifestError as exc:
        result.errors.append("\u6e05\u5355\u6821\u9a8c\u5931\u8d25\uff1a{0}".format(exc))
        return result
    result.project_root = root
    result.manifest_path = root / "project.yml"
    result.chapters = chapters
    if not chapters:
        result.warnings.append("\u89c4\u8303\u5305\u672a\u63d0\u4f9b\u7ae0\u8282\u9aa8\u67b6\uff0c\u9879\u76ee\u5c06\u4ee5\u7a7a\u5185\u5bb9\u8d77\u6b65\u3002")
    return result


def _read_mapping(pack: PackManifest, name: str, result: PackProjectResult) -> Dict[str, object]:
    """\u8bfb\u53d6\u53ef\u9009\u58f0\u660e\u6587\u4ef6\uff1b\u635f\u574f\u65f6\u53ea\u8b66\u544a\u5e76\u8df3\u8fc7\u3002"""
    import yaml

    target = pack.entry(name)
    if target is None:
        return {}
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError, OSError) as exc:
        result.warnings.append("{0} \u4e0d\u53ef\u7528\uff08{1}\uff09\uff0c\u5df2\u8df3\u8fc7\u3002".format(name, exc))
        return {}
    if not isinstance(data, dict):
        result.warnings.append("{0} \u683c\u5f0f\u4e0d\u6b63\u786e\uff0c\u5df2\u8df3\u8fc7\u3002".format(name))
        return {}
    if name == "terms.yml":
        items = data.get("terms") if "terms" in data else None
        return {"terms": items if isinstance(items, list) else []}
    if name == "rules.yml":
        items = data.get("rules") if "rules" in data else None
        return {"rules": items if isinstance(items, list) else []}
    return {str(key): value for key, value in data.items()}


def _write_yaml(path: Path, payload: Dict[str, object]) -> None:
    import json

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")