# -*- coding: utf-8 -*-
"""UI Export Orchestrator.

解耦 MainWindow 的导出协调逻辑：
- 版本号提取与同步 (_revision_record.md <-> manifest)
- 快速/默认导出请求构建 (自动判定本机 Word 刷新支持)
- 导出设置上下文收集 (供 GUI 弹窗及 CLI 探测复用)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def resolve_effective_export_version(manifest: Any, paths: Any) -> Optional[str]:
    """从 ``_revision_record.md`` 末行提取版本号；若不存在或无有效版本则返回 None。"""
    if manifest is None or paths is None:
        return None
    try:
        from doc_tool.application.content.revision_record import (
            document_version_from_record,
        )

        content_root = paths.resolve(manifest.relative_content_root())
        md_path = content_root / "_revision_record.md"
        if not md_path.exists():
            return None
        return document_version_from_record(md_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_effective_export_version failed: %s", exc)
        return None


def build_default_export_request(
    summary: Any,
    buffers: Optional[Dict[str, str]] = None,
    word_available: Optional[bool] = None,
) -> Any:
    """构建快速/默认导出请求（全量范围 + 脏缓冲判定 + 输出目录 + Word 刷新探针）。"""
    from doc_tool.application.intake_contract import (
        FORMAT_DOCX,
        SCOPE_PROJECT,
        SOURCE_MODE_CURRENT_BUFFER,
        SOURCE_MODE_SAVED,
        ExportRequest,
        ExportScope,
    )

    if word_available is None:
        try:
            from doc_tool.application.word_check import check_word_available

            word_available = bool(check_word_available(dispatch_check=False).available)
        except Exception:
            word_available = False

    buffers_dict = buffers or {}
    return ExportRequest(
        project_root=str(summary.project_root),
        formats=[FORMAT_DOCX],
        scope=ExportScope(kind=SCOPE_PROJECT),
        source_mode=SOURCE_MODE_CURRENT_BUFFER if buffers_dict else SOURCE_MODE_SAVED,
        destination=str(summary.paths.output_dir),
        refresh=bool(word_available),
    )


def collect_export_settings_context(
    summary: Any,
    buffers: Optional[Dict[str, str]] = None,
    active_chapter: Optional[str] = None,
) -> Dict[str, Any]:
    """收集导出设置对话框与 CLI 检查所需的完整上下文。"""
    from doc_tool.application.effective_snapshot import discover_chapters

    chapters = []
    variants = []
    document_properties = {}
    property_notice = ""
    doc_no = ""
    doc_name = ""
    saved_ver = ""
    doc_type = "general"

    if summary is not None:
        manifest = summary.manifest
        doc_no = getattr(manifest, "documentNo", "") or ""
        doc_name = getattr(manifest, "documentName", "") or ""
        doc_type = getattr(manifest, "documentType", "general") or "general"
        saved_ver = getattr(manifest, "documentVersion", "") or ""
        doc_ver = resolve_effective_export_version(manifest, summary.paths) or saved_ver

        template_path = summary.paths.template_docx
        if template_path.exists():
            try:
                from doc_tool.application.export.document_properties import (
                    inspect_document_properties,
                    read_template_reserved_properties,
                )

                document_properties = inspect_document_properties(template_path)
                reserved_props = read_template_reserved_properties(template_path)
                if not doc_no:
                    doc_no = reserved_props.get("文档编号") or reserved_props.get("文件编号") or ""
                if not doc_name:
                    doc_name = reserved_props.get("文件名称") or reserved_props.get("文档名称") or ""
            except Exception as exc:  # noqa: BLE001
                property_notice = "读取模板文档属性提示：{0}".format(exc)

        try:
            content_root = summary.paths.resolve(
                summary.manifest.relative_content_root()
            )
            chapters = [rel for rel, _path in discover_chapters(content_root)]
        except Exception:  # noqa: BLE001
            chapters = []

        try:
            from doc_tool.application.content.variants import VariantsConfig

            variants = list(VariantsConfig.load(summary.project_root).ids())
        except Exception:  # noqa: BLE001
            variants = []
    else:
        doc_ver = ""

    buf_count = len(buffers) if buffers is not None else 0

    return {
        "project_root": str(getattr(summary, "project_root", "") or ""),
        "destination": str(summary.paths.output_dir) if summary is not None else "",
        "chapters": chapters,
        "current_chapter": active_chapter or "",
        "unsaved_count": buf_count,
        "variants": variants,
        "document_no": doc_no,
        "document_name": doc_name,
        "document_version": doc_ver,
        "saved_document_version": saved_ver,
        "document_type": doc_type,
        "document_properties": document_properties,
        "property_notice": property_notice,
    }


class ExportOrchestrator:
    """MainWindow 导出协调器，解耦版本同步、请求组装与上下文提取逻辑。"""

    def __init__(self, window: Any = None) -> None:
        self._window = window

    def revision_record_version(self, summary: Any) -> Optional[str]:
        if summary is None:
            return None
        return resolve_effective_export_version(summary.manifest, summary.paths)

    def flush_unsaved_and_sync_version(self, window: Any = None) -> None:
        win = window or self._window
        if win is None:
            return
        try:
            if getattr(win, "_workspace", None) is not None and win._workspace.has_unsaved_changes():
                win._workspace.save_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto save_all before export failed: %s", exc)

        summary = getattr(win, "_project_summary", None)
        if summary is None:
            return

        rev_ver = (
            win._revision_record_version()
            if hasattr(win, "_revision_record_version") and callable(win._revision_record_version)
            else self.revision_record_version(summary)
        )
        if rev_ver and rev_ver != getattr(summary.manifest, "documentVersion", ""):
            try:
                summary.manifest.documentVersion = rev_ver
                summary.manifest.save(summary.paths.root)
                bar = getattr(win, "_project_bar", None)
                if bar is not None:
                    if hasattr(bar, "update_version"):
                        bar.update_version(rev_ver)
                    elif hasattr(bar, "_version_label"):
                        bar._version_label.setText("v{0}".format(rev_ver))
            except Exception as exc:  # noqa: BLE001
                logger.warning("sync revision version to manifest failed: %s", exc)

    def quick_export_defaults(
        self,
        summary: Any,
        buffers: Optional[Dict[str, str]] = None,
        word_available: Optional[bool] = None,
    ) -> Any:
        return build_default_export_request(summary, buffers, word_available)

    def export_settings_context(
        self,
        summary: Any,
        buffers: Optional[Dict[str, str]] = None,
        active_chapter: Optional[str] = None,
    ) -> Dict[str, Any]:
        return collect_export_settings_context(summary, buffers, active_chapter)
