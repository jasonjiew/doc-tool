# -*- coding: utf-8 -*-
"""\u63a5\u7ba1\u5df2\u6709 Word \u5efa\u9879\uff08V2.8 28-E / 5.2\uff09\u3002

\u76ee\u6807\uff1a\u628a\u300c\u9009\u5b9a\u89c4\u8303\u5305 + \u73b0\u6709 Word\u300d\u8fd9\u6761\u8def\u5f84\u505a\u6210**\u670d\u52a1\u5c42**\uff0c\u590d\u7528\u5df2\u6709\u9884\u68c0\u3001\u6837\u5f0f\u6620\u5c04
\u4e0e\u5f80\u8fd4\u95e8\u7981\uff08``import_first_time``\uff09\uff0c\u5e76**\u660e\u786e\u8bf4\u51fa**\u9009\u5b9a\u89c4\u8303\u4e0e\u6e90\u6587\u6863\u7684\u5339\u914d\u5dee\u5f02\u3002

\u4e0d\u91cd\u5efa\u4efb\u4f55\u5bfc\u5165\u5f15\u64ce\uff1a\u672c\u6a21\u5757\u53ea\u505a\uff081\uff09\u89c4\u8303\u5305\u51c6\u5907\u3001\uff082\uff09\u5dee\u5f02\u8bf4\u660e\u3001
\uff083\uff09\u8c03\u7528\u73b0\u6709\u5bfc\u5165\u5e76\u56de\u586b\u89c4\u8303\u5305\u5f15\u7528\u3002
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

from doc_tool.application.standard_pack import (
    PackManifest,
    install_pack,
    load_project_pack,
    pack_fingerprint,
    pack_skeleton_files,
    validate_pack_dir,
)


@dataclass
class IntakeDifference:
    """\u9009\u5b9a\u89c4\u8303\u4e0e\u6e90\u6587\u6863/\u9879\u76ee\u7684\u5dee\u5f02\u8bf4\u660e\u3002"""

    kind: str
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class IntakePreview:
    """\u63a5\u7ba1\u524d\u7684\u5339\u914d\u4e0e\u5dee\u5f02\u9884\u89c8\uff08\u53ea\u8bfb\uff09\u3002"""

    pack: Optional[PackManifest] = None
    pack_errors: List[str] = field(default_factory=list)
    pack_warnings: List[str] = field(default_factory=list)
    differences: List[IntakeDifference] = field(default_factory=list)
    heading_style_map: dict = field(default_factory=dict)
    skeleton_count: int = 0
    #: 是否显式传入了规范包。未传入时“无包”是合法状态，不算失败。
    pack_requested: bool = False

    @property
    def ok(self) -> bool:
        if not self.pack_requested:
            return not self.pack_errors
        return self.pack is not None and not self.pack_errors

    def to_dict(self) -> dict:
        return {
            "packId": self.pack.pack_id if self.pack else "",
            "packVersion": self.pack.version if self.pack else "",
            "documentKind": self.pack.document_kind if self.pack else "",
            "ok": self.ok,
            "packErrors": list(self.pack_errors),
            "packWarnings": list(self.pack_warnings),
            "differences": [item.to_dict() for item in self.differences],
            "headingStyleMap": dict(self.heading_style_map),
            "skeletonCount": self.skeleton_count,
        }

    def markdown_text(self) -> str:
        lines = [
            "## \u63a5\u7ba1 Word \u9884\u89c8",
            "",
            "- \u89c4\u8303\u5305\uff1a{0} {1}".format(
                self.pack.pack_id if self.pack else "\uff08\u65e0\uff09",
                self.pack.version if self.pack else "",
            ),
            "- \u53ef\u63a5\u7ba1\uff1a{0}".format("\u662f" if self.ok else "\u5426"),
        ]
        if self.skeleton_count:
            lines.append("- \u89c4\u8303\u5305\u7ae0\u8282\u9aa8\u67b6\uff1a{0} \u4e2a".format(self.skeleton_count))
        if self.heading_style_map:
            lines.append(
                "- \u6807\u9898\u6837\u5f0f\u6620\u5c04\uff1a{0}".format(
                    "\u3001".join("{0}\u2192{1}".format(k, v) for k, v in sorted(self.heading_style_map.items()))
                )
            )
        if self.differences:
            lines.append("")
            lines.append("| \u5dee\u5f02 | \u8bf4\u660e |")
            lines.append("|------|------|")
            for item in self.differences:
                lines.append("| {0} | {1} |".format(item.kind, item.detail))
        else:
            lines.append("")
            lines.append("\u672a\u53d1\u73b0\u9700\u4eba\u5de5\u786e\u8ba4\u7684\u5dee\u5f02\u3002")
        if self.pack_errors:
            lines.append("")
            lines.append("**\u5305\u9519\u8bef\uff1a**")
            lines.extend("- {0}".format(item) for item in self.pack_errors)
        return "\n".join(lines)


def preview_intake(
    docx_path: Union[str, Path],
    pack_source: Optional[Union[str, Path]] = None,
    *,
    project_root: Optional[Union[str, Path]] = None,
) -> IntakePreview:
    """\u63a5\u7ba1\u524d\u9884\u89c8\uff1a\u590d\u7528\u73b0\u6709\u9884\u68c0\u5f97\u5230\u6837\u5f0f\u6620\u5c04\uff0c\u5e76\u7ed9\u51fa\u4e0e\u9009\u5b9a\u89c4\u8303\u7684\u5dee\u5f02\u3002

    \u9884\u68c0\u5931\u8d25\u4e0d\u963b\u65ad\u9884\u89c8\uff08\u5dee\u5f02\u91cc\u8bb0\u4e00\u6761\uff09\uff0c\u4f46\u5305\u4e0d\u5408\u6cd5\u4f1a\u660e\u786e\u62a5\u9519\u3002
    """
    preview = IntakePreview(pack_requested=pack_source is not None)
    if pack_source is not None:
        validation = validate_pack_dir(pack_source)
        preview.pack = validation.pack
        preview.pack_errors = list(validation.errors)
        preview.pack_warnings = list(validation.warnings)
        if preview.pack is not None:
            preview.skeleton_count = len(pack_skeleton_files(preview.pack))
    if project_root is not None and preview.pack is not None:
        installed, warnings = load_project_pack(project_root, {"id": preview.pack.pack_id, "version": preview.pack.version})
        if installed is not None:
            preview.differences.append(
                IntakeDifference("\u9879\u76ee\u5185\u5df2\u6709\u540c\u7248\u672c\u89c4\u8303\u5305", installed.version)
            )
        preview.pack_warnings.extend(item for item in warnings if item not in preview.pack_warnings)

    _fill_preflight(preview, docx_path)
    return preview


def _fill_preflight(preview: IntakePreview, docx_path: Union[str, Path]) -> None:
    """\u590d\u7528\u73b0\u6709 ``preflight`` \u586b\u5145\u6837\u5f0f\u6620\u5c04\u4e0e\u5dee\u5f02\u8bf4\u660e\u3002"""
    from doc_tool.adapters import preflight as preflight_module

    source = Path(docx_path)
    if not source.is_file():
        preview.differences.append(IntakeDifference("\u6e90\u6587\u6863\u7f3a\u5931", str(source)))
        return
    try:
        result = preflight_module.preflight(str(source), allow_missing_headings=True)
    except Exception as exc:  # noqa: BLE001 - \u9884\u89c8\u4e0d\u5e94\u56e0\u9884\u68c0\u5931\u8d25\u800c\u6574\u4f53\u62a5\u9519
        preview.differences.append(IntakeDifference("\u9884\u68c0\u672a\u901a\u8fc7", str(exc)))
        return
    preview.heading_style_map = {
        str(level): str(style_id) for level, style_id in (result.heading_style_map or {}).items()
    }
    if not preview.heading_style_map:
        preview.differences.append(
            IntakeDifference("\u672a\u8bc6\u522b\u5230\u6807\u9898\u6837\u5f0f", "\u5bfc\u5165\u540e\u5c06\u4f7f\u7528\u901a\u7528\u6807\u9898\u6837\u5f0f\u6620\u5c04")
        )
    if result.import_report is not None and result.import_report.lossy:
        for finding in list(result.import_report.degraded) + list(result.import_report.blocked):
            preview.differences.append(
                IntakeDifference(
                    "\u5bfc\u5165\u4fdd\u771f\u964d\u7ea7" if finding.severity != "BLOCK" else "\u5bfc\u5165\u4fdd\u771f\u963b\u65ad",
                    "{0}\uff1a{1} \u5904".format(finding.label, finding.count),
                )
            )
    if preview.pack is not None and preview.pack.document_kind:
        preview.differences.append(
            IntakeDifference(
                "\u89c4\u8303\u6587\u6863\u7c7b\u522b",
                "{0}\uff08\u6e90\u6587\u6863\u4e0d\u643a\u5e26\u7c7b\u522b\uff0c\u4ee5\u89c4\u8303\u5305\u4e3a\u51c6\uff09".format(preview.pack.document_kind),
            )
        )


def intake_word_project(
    docx_path: Union[str, Path],
    project_root: Union[str, Path],
    *,
    pack_source: Optional[Union[str, Path]] = None,
    document_type: str = "general",
    document_no: str = "",
    document_name: str = "",
    document_version: str = "1.0",
    require_exact_roundtrip: bool = False,
    cancel_token=None,
) -> Tuple[Optional[object], IntakePreview]:
    """\u63a5\u7ba1\u73b0\u6709 Word\uff1a\u5148\u9884\u89c8\uff0c\u518d\u8c03\u7528**\u73b0\u6709** ``import_first_time``\u3002

    \u6210\u529f\u540e\u628a\u89c4\u8303\u5305\u5f15\u7528\u56de\u586b\u5230\u6e05\u5355\uff08\u4e0d\u6539\u53d8\u5bfc\u5165\u5f97\u5230\u7684\u6b63\u6587\uff09\u3002
    \u5305\u4e0d\u5408\u6cd5\u65f6\u4e0d\u5bfc\u5165\uff0c\u76f4\u63a5\u8fd4\u56de\u9884\u89c8\uff08\u542b\u9519\u8bef\uff09\u3002
    """
    preview = preview_intake(docx_path, pack_source, project_root=None)
    if not preview.ok:
        return None, preview
    from doc_tool.application.import_project import ImportRequest, import_first_time

    request = ImportRequest(
        source_docx=Path(docx_path),
        target_project_root=Path(project_root),
        document_type=document_type,
        document_no=document_no,
        document_name=document_name or "Word \u63a5\u7ba1\u9879\u76ee",
        document_version=document_version,
        require_exact_roundtrip=require_exact_roundtrip,
        heading_style_map=(
            {int(level): style for level, style in preview.heading_style_map.items()}
            if preview.heading_style_map
            else None
        ),
    )
    result = import_first_time(request, cancel_token=cancel_token) if cancel_token is not None else import_first_time(request)
    if getattr(result, "success", False) and pack_source is not None:
        _attach_pack(Path(project_root), preview)
    return result, preview


def _attach_pack(project_root: Path, preview: IntakePreview) -> None:
    """\u628a\u89c4\u8303\u5305\u5f15\u7528\u4e0e\u53d8\u91cf\u5199\u5165\u5df2\u5bfc\u5165\u7684\u6e05\u5355\uff08\u4e0d\u52a8\u6b63\u6587\uff09\u3002"""
    from doc_tool.domain.manifest import ProjectManifest

    if preview.pack is None:
        return
    target, _install = install_pack(preview.pack.root or "", project_root)
    manifest = ProjectManifest.load(project_root)
    manifest.schemaVersion = max(int(manifest.schemaVersion), 2)
    manifest.standardPack = {
        "id": preview.pack.pack_id,
        "version": preview.pack.version,
        "hash": pack_fingerprint(preview.pack),
    }
    if preview.pack.document_kind and not manifest.documentKind:
        manifest.documentKind = preview.pack.document_kind
    if not manifest.chapters:
        manifest.chapters = [item.name for item in pack_skeleton_files(preview.pack)]
    if not manifest.qualitySource:
        manifest.qualitySource = "pack"
    manifest.save(project_root)
    del target