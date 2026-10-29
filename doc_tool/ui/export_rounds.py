# -*- coding: utf-8 -*-
"""成果轮次视图模型：把真实 ExportReport / 交付报告转成可显示的逐文件结果。

UI 包 UI-C 的纯逻辑层（无 Qt 依赖，可直接单测）：

- :class:`RoundFormatView` / :class:`ExportRoundView`：一次出稿轮的逐格式状态、
  真实路径、是否可立即打开、失败原因与恢复动作。
- :class:`RoundStore`：只保留**引用**（不复制文件）的按轮历史，供「关闭后找回」
  与「旧轮不被新轮覆盖」使用；权威状态仍由既有 OutputState/报告索引判定。
- :func:`load_round_from_index`：重开项目时从既有 ``export-result.json`` 恢复最近
  一轮（沿用报告索引，不新建第二套状态文件）。

设计约束：不把「文件存在」当作正式完成，只用报告里的真实状态；失效路径必须
保留路径并标记为不可打开，交给界面给「重新定位/重新生成」。
"""

from __future__ import annotations

from doc_tool.domain.export_diagnostics import ExportDiagnostics

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from doc_tool.application.intake_contract import (
    FORMAT_DOCX,
    ExportScope,
    FORMAT_LABELS,
    FORMAT_STATUS_LABELS,
    STATUS_READY,
    format_label,
)

#: 单项目保留的历史轮次上限（足够回看，不无限增长）。
DEFAULT_ROUND_LIMIT = 12


def _status_label(status: str) -> str:
    return FORMAT_STATUS_LABELS.get(status, status or "未知")


@dataclass(frozen=True)
class RoundFormatView:
    """一轮里单个格式的真实状态。"""

    format: str
    status: str
    path: str = ""
    usable: bool = False
    message: str = ""
    formal: bool = False
    failed_stage: str = ""
    error_code: str = ""
    locations: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return format_label(self.format)

    @property
    def status_text(self) -> str:
        return _status_label(self.status)

    @property
    def can_open(self) -> bool:
        """是否可立即打开：状态可用且路径仍是真实文件。"""
        return bool(self.usable and self.path and Path(self.path).is_file())

    @property
    def is_stale(self) -> bool:
        """曾经可用但路径已失效（被移动/删除）：需要重新定位或重新生成。"""
        return bool(self.usable and self.path and not Path(self.path).is_file())

    def describe(self) -> str:
        if self.can_open:
            return "{0}：{1}".format(self.label, self.status_text)
        if self.is_stale:
            return "{0}：{1}（文件已失效，可重新定位或重新生成）".format(
                self.label, self.status_text
            )
        detail = "：{0}".format(self.message) if self.message else ""
        return "{0}：{1}{2}".format(self.label, self.status_text, detail)


@dataclass(frozen=True)
class ExportRoundView:
    """一轮出稿的显示模型（来源/范围/轮次都来自真实报告）。"""

    round_id: str
    capture_id: str = ""
    created_at: str = ""
    project_root: str = ""
    source_mode: str = ""
    scope_text: str = ""
    destination: str = ""
    formats: List[RoundFormatView] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unsaved_chapters: List[str] = field(default_factory=list)
    index_path: str = ""
    docx_path: str = ""
    #: V4.0 40-D：本轮 Word 刷新的真实阶段与清理事实（缺项表示未知）。
    word_stages: List[str] = field(default_factory=list)
    # 仅供新轮设置预填；补原轮仍读取真实报告并核对身份。
    scope: Optional[ExportScope] = None
    execution_id: str = ""
    diagnostics: Optional[Dict[str, Any]] = None
    diagnostics_path: str = ""
    diagnostics_md_path: str = ""
    failed_stage: str = ""
    error_code: str = ""
    locations: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def diagnostics_markdown(self) -> str:
        if self.diagnostics:
            diag_obj = ExportDiagnostics.from_dict(self.diagnostics)
            if diag_obj:
                return diag_obj.to_markdown(self.project_root)
        return "# 导出诊断记录\n\n该导出记录未附带详细诊断数据（可能是早期历史导出或未记录诊断）。\n"


    @property
    def has_usable_docx(self) -> bool:
        """是否有可直接打开的 Word 成果文件。"""
        return any(
            item.format == FORMAT_DOCX and item.can_open
            for item in self.formats
        )

    @property
    def has_pending_refresh(self) -> bool:
        """是否处于待 Word 刷新状态。"""
        return any(
            item.status == "pending-refresh"
            for item in self.formats
        )

    @property
    def primary_location(self) -> Optional[Dict[str, Any]]:
        """首个可验证的源 Markdown 定位。"""
        for loc in self.locations:
            if loc.get("path") and loc.get("line"):
                return loc
        for f in self.formats:
            for loc in f.locations:
                if loc.get("path") and loc.get("line"):
                    return loc
        return None

    @property
    def usable_formats(self) -> List[RoundFormatView]:
        return [item for item in self.formats if item.usable]

    @property
    def failed_formats(self) -> List[RoundFormatView]:
        return [item for item in self.formats if not item.usable]

    @property
    def pending_formats(self) -> List[RoundFormatView]:
        return [
            item for item in self.formats
            if item.status in ("pending-refresh", "pending-convert", "pending-registration")
        ]

    @property
    def has_retryable(self) -> bool:
        """是否还有可补的格式（失败或待刷新/待转换）。"""
        return any(
            item.status in ("failed", "pending-convert", "pending-refresh", "pending-registration")
            for item in self.formats
        )

    def summary_line(self) -> str:
        return "第 {0} 轮 · {1} · {2}".format(
            self.round_id[-6:] if self.round_id else "-",
            self.scope_text or "整份文档",
            "当前编辑内容" if self.source_mode == "current-buffer" else "已保存版本",
        )


def round_view_from_report(report) -> ExportRoundView:
    """把 ``ExportReport``（或交付报告）转成显示模型；不改变任何正式状态。"""
    formats = []
    for item in getattr(report, "results", None) or []:
        usable = bool(getattr(item, "usable", False))
        formats.append(
            RoundFormatView(
                format=str(getattr(item, "format", "") or ""),
                status=str(getattr(item, "status", "") or ""),
                path=str(getattr(item, "path", "") or ""),
                usable=usable,
                message=str(getattr(item, "message", "") or ""),
                formal=bool(getattr(item, "formal", False)),
                failed_stage=str(getattr(item, "failed_stage", "") or ""),
                error_code=str(getattr(item, "error_code", "") or ""),
                locations=list(getattr(item, "locations", []) or []),
            )
        )
    scope = getattr(report, "scope", None)
    if not getattr(report, "scopeKnown", True):
        scope = None
    scope_text = ""
    if scope is not None and hasattr(scope, "describe"):
        try:
            scope_text = scope.describe(len(getattr(scope, "chapters", None) or 0))
        except Exception:  # noqa: BLE001 - 范围描述失败不影响结果展示
            scope_text = ""
    elif not getattr(report, "scopeKnown", True):
        scope_text = "范围记录缺失"
    return ExportRoundView(
        round_id=str(getattr(report, "roundId", "") or ""),
        capture_id=str(getattr(report, "captureId", "") or ""),
        created_at=str(getattr(report, "createdAt", "") or ""),
        project_root=str(getattr(report, "projectRoot", "") or ""),
        source_mode=str(getattr(report, "sourceMode", "") or ""),
        scope_text=scope_text,
        destination=str(getattr(report, "destination", "") or ""),
        formats=formats,
        warnings=[str(w) for w in getattr(report, "warnings", None) or []],
        word_stages=[str(item) for item in getattr(report, "wordStages", None) or []],
        unsaved_chapters=[
            str(item) for item in getattr(report, "unsavedChapters", None) or []
        ],
        index_path=str(getattr(report, "indexPath", "") or ""),
        docx_path=str(getattr(report, "docxPath", "") or ""),
        scope=ExportScope.from_dict(scope.to_dict()) if scope is not None and hasattr(scope, "to_dict") else None,
        execution_id=str(getattr(report, "executionId", "") or ""),
        diagnostics=getattr(report, "diagnostics", None),
        diagnostics_path=str(getattr(report, "diagnosticsPath", "") or ""),
        diagnostics_md_path=str(getattr(report, "diagnosticsMdPath", "") or ""),
        failed_stage=getattr(getattr(report, "diagnostics", None) or {}, "get", lambda *a: "")("failedStage", ""),
        error_code=getattr(getattr(report, "diagnostics", None) or {}, "get", lambda *a: "")("errorCode", ""),
        locations=list(getattr(getattr(report, "diagnostics", None) or {}, "get", lambda *a: [])("locations", []) or []),
    )


def load_round_from_index(output_dir) -> Optional[ExportRoundView]:
    """从既有出稿索引恢复最近一轮；缺失/损坏返回 None（不改任何状态）。"""
    if not output_dir:
        return None
    from doc_tool.application.project_export import read_export_index

    report = read_export_index(Path(output_dir))
    if report is None:
        return None
    return round_view_from_report(report)


class RoundStore:
    """按项目保留最近若干轮的**引用**（不复制文件，不提升正式状态）。

    - ``record`` 新轮入栈（同 roundId 覆盖，保证幂等）；
    - ``latest``/``rounds`` 供「成果」入口与关闭后找回；
    - 切换项目只展示本项目：``for_project`` 过滤；
    - 迟到结果按其 ``project_root`` 归位，不覆盖其它项目的列表。
    """

    def __init__(self, limit: int = DEFAULT_ROUND_LIMIT) -> None:
        self._limit = max(1, int(limit))
        self._by_project: Dict[str, List[ExportRoundView]] = {}

    def record(self, view: ExportRoundView) -> None:
        key = view.project_root or ""
        rounds = [item for item in self._by_project.get(key, []) if item.round_id != view.round_id]
        rounds.append(view)
        self._by_project[key] = rounds[-self._limit:]

    def for_project(self, project_root) -> List[ExportRoundView]:
        return list(self._by_project.get(str(project_root or ""), []))

    def latest(self, project_root) -> Optional[ExportRoundView]:
        rounds = self.for_project(project_root)
        return rounds[-1] if rounds else None

    def find(self, project_root, round_id: str) -> Optional[ExportRoundView]:
        for item in self.for_project(project_root):
            if item.round_id == round_id:
                return item
        return None

    def clear(self, project_root=None) -> None:
        if project_root is None:
            self._by_project.clear()
            return
        self._by_project.pop(str(project_root or ""), None)


__all__ = [
    "DEFAULT_ROUND_LIMIT",
    "ExportRoundView",
    "FORMAT_LABELS",
    "RoundFormatView",
    "RoundStore",
    "STATUS_READY",
    "load_round_from_index",
    "round_view_from_report",
]
