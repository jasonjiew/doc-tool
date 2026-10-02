# -*- coding: utf-8 -*-
"""可搬目录的源码交付包（CORE-G 7.4）。

把所选 Markdown、依赖资源、底模、必要项目设置、来源/结果索引打成 ZIP，形成
**可以在另一台电脑/另一个目录直接打开的普通项目副本**：

- 默认不含原件；``include_original=True`` 时才加入 ``original/source.docx``；
- 排除凭据、``.git``、缓存、日志、用户配置和无关历史；
- 包内路径一律相对且 POSIX 风格，缺资源保留占位并在清单中明示，不宣称自足。
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.intake_contract import (
    ExportScope,
    sha256_file,
    utc_now_iso,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths

#: 永不进入源码包的路径片段（凭据/版本控制/缓存/日志/用户配置/无关历史）。
EXCLUDED_PARTS = (
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    "logs", ".state", "output", "node_modules", ".venv", "venv",
)
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".bak")
EXCLUDED_NAMES = ("user.yml", "user.yaml", "credentials.json", "token.json", "recent.json")

#: 项目清单中的固定文件名。
PACKAGE_MANIFEST_NAME = "source-package.json"
PACKAGE_README_NAME = "SOURCE_PACKAGE.md"


@dataclass
class SourcePackageOutcome:
    """源码包结果。"""

    ok: bool = False
    path: Optional[Path] = None
    message: str = ""
    included: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        if self.ok and self.path is not None:
            lines.append("源码包已生成：{0}".format(Path(self.path).name))
            lines.append("包含 {0} 个条目".format(len(self.included)))
        else:
            lines.append("源码包未生成：{0}".format(self.message or "未知原因"))
        if self.missing:
            lines.append("缺少 {0} 个资源（包内保留占位与清单）".format(len(self.missing)))
        for item in self.warnings[:3]:
            lines.append("提醒：{0}".format(item))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "path": str(self.path) if self.path else "",
            "message": self.message,
            "included": list(self.included),
            "missing": list(self.missing),
            "excluded": list(self.excluded),
            "warnings": list(self.warnings),
        }


def _safe_rel(value: str) -> Optional[str]:
    """归一为包内安全相对路径；越界/绝对路径返回 None。"""
    text = str(value or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ":" in text.split("/")[0]:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _is_excluded(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if any(part in EXCLUDED_PARTS for part in parts):
        return True
    name = parts[-1]
    if name in EXCLUDED_NAMES:
        return True
    return name.lower().endswith(EXCLUDED_SUFFIXES)


def _select_chapters(
    chapters: Sequence[str],
    scope: Optional[ExportScope],
) -> Tuple[List[str], List[str]]:
    """按范围挑选章节；未给范围时用全部。"""
    ordered = [item for item in chapters]
    if scope is None or scope.kind == "project":
        return ordered, []
    wanted: List[str] = []
    if scope.kind == "current-chapter":
        wanted = [scope.current] if scope.current else []
    else:
        wanted = list(scope.chapters)
    selected = [item for item in ordered if item in set(wanted)]
    omitted = [item for item in ordered if item not in set(wanted)]
    if not selected:
        return ordered, []
    return selected, omitted


def _collect_resources(texts: Iterable[str]) -> List[str]:
    from doc_tool.application.effective_snapshot import collect_resource_paths

    return collect_resource_paths(texts)


def build_source_package(
    project_root,
    target_zip,
    *,
    scope: Optional[ExportScope] = None,
    chapters: Optional[Sequence[str]] = None,
    include_original: bool = False,
    extra_files: Sequence[Tuple[str, Path]] = (),
) -> SourcePackageOutcome:
    """生成源码 ZIP；缺资源保留占位并列出，不宣称完全自足。"""
    project_root = Path(project_root)
    target_zip = Path(target_zip)
    outcome = SourcePackageOutcome()
    paths = ProjectPaths(project_root)
    try:
        manifest = ProjectManifest.load(project_root)
    except Exception as exc:  # noqa: BLE001 - 清单不可读时不生成假包
        outcome.message = "项目清单不可读：{0}".format(exc)
        return outcome
    content_root = paths.resolve(manifest.relative_content_root())
    asset_root = paths.resolve(manifest.relative_asset_root())
    table_root = paths.resolve(manifest.relative_table_root())
    protected = [content_root.resolve(), asset_root.resolve(), paths.template_dir.resolve(), paths.original_dir.resolve()]
    destination = target_zip.resolve()
    if destination == (project_root / "project.yml").resolve() or any(
        destination == source or source in destination.parents for source in protected
    ):
        outcome.message = "源码包目标不能覆盖项目源文件。"
        return outcome

    all_chapters = [item for item in (chapters or [])]
    if not all_chapters:
        from doc_tool.application.effective_snapshot import discover_chapters

        all_chapters = [rel for rel, _path in discover_chapters(content_root)]
    selected, omitted = _select_chapters(all_chapters, scope)
    if any(_safe_rel(rel) is None for rel in selected):
        outcome.message = "章节路径必须是项目内相对路径。"
        return outcome
    if omitted:
        outcome.warnings.append("范围外 {0} 章未纳入源码包".format(len(omitted)))

    members = list(selected)
    for rel in selected:
        index = (Path(rel).parent / "_index.md").as_posix()
        if index not in members and (content_root / index).is_file():
            members.append(index)
    texts: List[str] = []
    for rel in members:
        try:
            texts.append((content_root / rel).read_text(encoding="utf-8"))
        except OSError:
            outcome.missing.append(rel)

    resources = _collect_resources(texts)
    resource_rel: List[str] = []
    for target in resources:
        cleaned = _safe_rel(target.split(" =", 1)[0])
        if cleaned is None:
            outcome.warnings.append("资源路径越界，已跳过：{0}".format(target))
            continue
        resource_root = table_root if cleaned.startswith("tables/") else asset_root
        candidate = (resource_root / (cleaned[7:] if cleaned.startswith("tables/") else cleaned)).resolve()
        try:
            candidate.relative_to(resource_root.resolve())
        except ValueError:
            outcome.warnings.append("资源越出项目根，已跳过：{0}".format(target))
            continue
        if candidate.is_file():
            resource_rel.append(cleaned)
        else:
            outcome.missing.append(cleaned)

    target_zip.parent.mkdir(parents=True, exist_ok=True)
    package_manifest = {
        "schemaVersion": 1,
        "kind": "doc-tool-source-package",
        "createdAt": utc_now_iso(),
        "documentType": manifest.documentType,
        "documentName": manifest.documentName,
        "documentNo": manifest.documentNo,
        "documentVersion": manifest.documentVersion,
        "scope": (scope.to_dict() if scope is not None else {"kind": "project"}),
        "chapters": list(selected),
        "omittedChapters": list(omitted),
        "resources": list(resource_rel),
        "missingResources": list(outcome.missing),
        "includeOriginal": bool(include_original),
        "selfContained": not outcome.missing,
        "notes": (
            "包内为可再打开的普通项目副本；相对路径、无绝对路径。"
            + ("" if not outcome.missing else "存在缺失资源，包不自足，清单已列出。")
        ),
    }

    try:
        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for rel in members:
                source = content_root / rel
                if not source.is_file():
                    continue
                _write_member(archive, "content/" + rel, source, outcome)
            for rel in resource_rel:
                source = table_root / rel[7:] if rel.startswith("tables/") else asset_root / rel
                _write_member(archive, "assets/" + rel, source, outcome)
            if paths.template_docx.is_file():
                _write_member(archive, "template/template.docx", paths.template_docx, outcome)
            quality_dir = project_root / "quality"
            if quality_dir.is_dir():
                for path in sorted(quality_dir.rglob("*")):
                    if path.is_file() and not _is_excluded(path.relative_to(project_root).as_posix()):
                        _write_member(archive, path.relative_to(project_root).as_posix(), path, outcome)
            record = paths.original_dir / "import-record.json"
            if record.is_file():
                _write_member(archive, "original/import-record.json", record, outcome)
            export_index = paths.output_dir / "export-result.json"
            if export_index.is_file():
                _write_member(archive, "output/export-result.json", export_index, outcome)
            if include_original and paths.source_docx.is_file():
                _write_member(archive, "original/source.docx", paths.source_docx, outcome)
            elif paths.source_docx.is_file():
                outcome.excluded.append("original/source.docx")
            for rel, path in extra_files or ():
                cleaned = _safe_rel(rel)
                if cleaned is None or not Path(path).is_file():
                    continue
                _write_member(archive, cleaned, Path(path), outcome)
            archive.writestr(
                "project.yml",
                _snapshot_manifest_text(manifest, selected),
            )
            archive.writestr(
                PACKAGE_MANIFEST_NAME,
                json.dumps(package_manifest, ensure_ascii=False, indent=2),
            )
            archive.writestr(PACKAGE_README_NAME, _readme_text(package_manifest))
            outcome.included.append("project.yml")
            outcome.included.append(PACKAGE_MANIFEST_NAME)
    except OSError as exc:
        outcome.ok = False
        outcome.message = "写入源码包失败：{0}".format(exc)
        return outcome

    outcome.ok = True
    outcome.path = target_zip
    outcome.message = "源码包已生成"
    return outcome


def _asset_relative(rel: str, content_root: Path, project_root: Path) -> str:
    """资源在包内的相对路径：保持项目内的相对结构（去掉类型前缀重复）。"""
    try:
        inside_content = (project_root / rel).resolve().relative_to(content_root.resolve()).as_posix()
        return inside_content
    except ValueError:
        return Path(rel).name


def _write_member(archive: zipfile.ZipFile, rel: str, source: Path, outcome: SourcePackageOutcome) -> None:
    cleaned = _safe_rel(rel)
    if cleaned is None or _is_excluded(cleaned):
        outcome.excluded.append(rel)
        return
    try:
        archive.write(str(source), cleaned)
        outcome.included.append(cleaned)
    except OSError as exc:
        outcome.warnings.append("写入失败：{0}（{1}）".format(cleaned, exc))


def _snapshot_manifest_text(manifest: ProjectManifest, chapters: Sequence[str]) -> str:
    """包内清单：固定相对路径、章节顺序为本次范围、含来源版本字段。"""
    import yaml

    payload = {
        "schemaVersion": manifest.schemaVersion,
        "isHeadless": manifest.is_headless,
        "allowMissingHeadings": manifest.allow_missing_headings,
        "projectId": manifest.projectId,
        "documentType": manifest.documentType,
        "documentNo": manifest.documentNo,
        "documentName": manifest.documentName,
        "documentVersion": manifest.documentVersion,
        "sourceSha256": manifest.sourceSha256,
        "createdWithVersion": manifest.createdWithVersion,
        "lastSuccessfulBuildVersion": manifest.lastSuccessfulBuildVersion,
        "paths": {
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content",
            "assetRoot": "assets",
            "tableRoot": "assets/tables",
        },
        "headingStyles": {int(k): str(v) for k, v in (manifest.headingStyles or {}).items()},
        "bodyStyle": manifest.bodyStyle,
        "documentKind": manifest.documentKind,
        "chapters": list(chapters),
        "variables": dict(manifest.variables or {}),
        "standardPack": dict(manifest.standardPack or {}),
        "qualitySource": manifest.qualitySource,
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _readme_text(package_manifest: Dict[str, object]) -> str:
    lines = [
        "# 源码交付包",
        "",
        "本包是文档项目的可再打开副本，解压到任意目录即可打开并再次生成。",
        "",
        "## 内容",
        "",
        "- `project.yml`：项目清单（相对路径，无机器绝对路径）",
        "- `content/`：本次范围的 Markdown 正文",
        "- `assets/`：正文引用的资源",
        "- `template/`：底模",
        "- `original/import-record.json`：来源与处理记录",
        "",
        "## 范围与来源",
        "",
        "- 文档：{0}（{1}）".format(package_manifest.get("documentName", ""), package_manifest.get("documentVersion", "")),
        "- 范围：{0}".format(package_manifest.get("scope", {})),
        "- 章节数：{0}".format(len(package_manifest.get("chapters") or [])),
        "- 包含原件：{0}".format("是" if package_manifest.get("includeOriginal") else "否"),
        "- 自足：{0}".format("是" if package_manifest.get("selfContained") else "否（见 missingResources）"),
        "",
    ]
    missing = package_manifest.get("missingResources") or []
    if missing:
        lines.append("## 缺失资源（包内保留占位）")
        lines.append("")
        for item in missing:
            lines.append("- {0}".format(item))
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "EXCLUDED_PARTS", "EXCLUDED_SUFFIXES", "PACKAGE_MANIFEST_NAME", "PACKAGE_README_NAME",
    "SourcePackageOutcome", "build_source_package",
]
