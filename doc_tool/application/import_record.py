# -*- coding: utf-8 -*-
"""原件留存与正文缺口账本（CORE-C 3.1-3.4）。

`original/import-record.json`（schema 1）记录一次导入的源哈希、实际策略、
所选章节、标题决定与逐项处理事实。三种状态分别表达，互不冒充：

- ``editable``：可编辑保留（已进入正文）；
- ``text-fallback``：参考文本降级（读到文本、丢了结构）；
- ``original-only``：原件留存（正文只有占位，原件可查）。

再次导入保存新的来源版本（``original/versions/<sha8>/``），不覆盖仍被引用的
旧原件；缺口按类型/章节归并，默认最多展开 3 项有行动价值的问题。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.intake_contract import (
    DEFAULT_ACTIONABLE_LIMIT,
    FEATURE_LABELS,
    HANDLING_EDITABLE,
    HANDLING_LABELS,
    HANDLING_ORIGINAL_ONLY,
    HANDLING_PLACEHOLDER,
    HANDLING_SKIPPED,
    HANDLING_TEXT_FALLBACK,
    PLACEHOLDER_PREFIX,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    PreservationFinding,
    placeholder_text,
    utc_now_iso,
)

#: 导入记录文件名（相对项目 ``original/``）。
RECORD_NAME = "import-record.json"
RECORD_SCHEMA_VERSION = 1

#: 再次导入的来源版本目录（相对项目 ``original/``）。
VERSIONS_DIR = "versions"

#: 保真特性 -> (处理方式, 是否可编辑, 严重程度, 直接动作)。
_FEATURE_HANDLING: Dict[str, Tuple[str, bool, str, str]] = {
    "formula": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "定位正文／查看原件"),
    "textbox": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "定位正文／查看原件"),
    "chart": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "定位正文／查看原件"),
    "ole": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "定位正文／查看原件"),
    "footnote": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "查看原件"),
    "endnote": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "查看原件"),
    "comment": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "查看原件（不自动处理批注）"),
    "revision": (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "查看原件（不自动接受/拒绝修订）"),
    "sdt": (HANDLING_TEXT_FALLBACK, False, SEVERITY_WARNING, "定位正文"),
    "hyperlink": (HANDLING_EDITABLE, True, SEVERITY_INFO, ""),
    "bookmark": (HANDLING_EDITABLE, True, SEVERITY_INFO, ""),
    "field": (HANDLING_EDITABLE, True, SEVERITY_INFO, ""),
}


@dataclass
class SourceVersion:
    """一次导入的来源版本记录。"""

    sha256: str = ""
    file: str = ""
    retained: str = ""
    importedAt: str = field(default_factory=utc_now_iso)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceVersion":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class ImportRecord:
    """导入记录（schema 1）。"""

    sourceSha256: str = ""
    #: 正文里写入的可见占位行（CORE 3.2，便于结果页/导出核对）。
    placeholderLines: List[str] = field(default_factory=list)
    sourceFile: str = ""
    actualPolicy: str = "normal"
    documentType: str = "general"
    documentName: str = ""
    documentNo: str = ""
    documentVersion: str = ""
    selectedSections: List[str] = field(default_factory=list)
    headingDecisions: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[PreservationFinding] = field(default_factory=list)
    unavailableComparisons: List[str] = field(default_factory=list)
    sourceVersions: List[SourceVersion] = field(default_factory=list)
    retainedPath: str = "original/source.docx"
    schemaVersion: int = RECORD_SCHEMA_VERSION
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)

    # --- 汇总 ---

    def counts_by_handling(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.findings:
            counts[item.handling] = counts.get(item.handling, 0) + 1
        return counts

    def to_fix_count(self) -> int:
        return sum(
            1 for item in self.findings
            if item.handling in (
                HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER,
                HANDLING_TEXT_FALLBACK, HANDLING_SKIPPED,
            )
        )

    def auto_handled_count(self) -> int:
        return sum(1 for item in self.findings if item.handling == HANDLING_EDITABLE)

    def result_actions(self, limit: int = DEFAULT_ACTIONABLE_LIMIT) -> List[Dict[str, object]]:
        """结果页可直接执行的补救动作（定位正文/查看原件/替换图片）。

        与 :meth:`action_items` 的展示文本不同，这里给出结构化动作，界面据此
        连线既有资源修复、章节定位与原件查看，不必让用户从长日志里找步骤。
        """
        actions: List[Dict[str, object]] = []
        for item in self.action_items(limit):
            kind = "locate"
            if item.handling == HANDLING_PLACEHOLDER:
                kind = "replace-image"
            elif item.handling == HANDLING_ORIGINAL_ONLY:
                kind = "view-original"
            actions.append({
                "kind": kind,
                "feature": item.feature,
                "label": "{0}：{1}".format(item.kind_label, item.handling_label),
                "chapter": item.target_chapter,
                "line": item.target_line,
                "retainedPath": item.retained_path,
                "action": item.action or {
                    "locate": "定位正文", "replace-image": "选择替代图片",
                    "view-original": "查看原件",
                }[kind],
            })
        return actions

    def grouped(self) -> Dict[str, List[PreservationFinding]]:
        """按类型/章节归并，供结果页展示与定位。"""
        groups: Dict[str, List[PreservationFinding]] = {}
        for item in self.findings:
            key = "{0}｜{1}".format(item.feature, item.target_chapter or "未定位")
            groups.setdefault(key, []).append(item)
        return groups

    def action_items(self, limit: int = DEFAULT_ACTIONABLE_LIMIT) -> List[PreservationFinding]:
        ordered = sorted(
            self.findings,
            key=lambda item: (
                -{"block": 2, "warning": 1, "info": 0}.get(item.severity, 0),
                item.data_sort_key(),
            ),
        )
        return ordered[: max(0, int(limit))]

    def summary_lines(self, limit: int = DEFAULT_ACTIONABLE_LIMIT) -> List[str]:
        lines: List[str] = []
        counts = self.counts_by_handling()
        lines.append("原件已保留：{0}".format(self.retainedPath or "original/source.docx"))
        if self.findings:
            lines.append("{0} 处内容待完善，{1} 项已自动处理".format(
                self.to_fix_count(), self.auto_handled_count(),
            ))
        for handling, count in sorted(counts.items()):
            lines.append("· {0}：{1} 项".format(HANDLING_LABELS.get(handling, handling), count))
        actions = self.action_items(limit)
        for item in actions:
            where = item.target_chapter or item.source_part or "正文"
            lines.append("· {0}：{1}（{2}）{3}".format(
                item.kind_label, item.handling_label, where,
                ("｜" + item.action) if item.action else "",
            ))
        remaining = len(self.findings) - len(actions)
        if remaining > 0:
            lines.append("其余 {0} 项见详情".format(remaining))
        for item in self.unavailableComparisons:
            lines.append("对照未完成：{0}".format(item))
        return lines

    # --- 序列化 ---

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "sourceSha256": self.sourceSha256,
            "sourceFile": self.sourceFile,
            "actualPolicy": self.actualPolicy,
            "documentType": self.documentType,
            "documentName": self.documentName,
            "documentNo": self.documentNo,
            "documentVersion": self.documentVersion,
            "selectedSections": list(self.selectedSections),
            "headingDecisions": list(self.headingDecisions),
            "findings": [item.to_dict() for item in self.findings],
            "placeholderLines": list(self.placeholderLines),
            "unavailableComparisons": list(self.unavailableComparisons),
            "sourceVersions": [item.to_dict() for item in self.sourceVersions],
            "retainedPath": self.retainedPath,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportRecord":
        data = data or {}
        return cls(
            sourceSha256=str(data.get("sourceSha256") or ""),
            sourceFile=str(data.get("sourceFile") or ""),
            actualPolicy=str(data.get("actualPolicy") or "normal"),
            documentType=str(data.get("documentType") or "general"),
            documentName=str(data.get("documentName") or ""),
            documentNo=str(data.get("documentNo") or ""),
            documentVersion=str(data.get("documentVersion") or ""),
            selectedSections=[str(item) for item in data.get("selectedSections") or []],
            headingDecisions=[item for item in data.get("headingDecisions") or [] if isinstance(item, dict)],
            findings=[PreservationFinding.from_dict(item) for item in data.get("findings") or []],
            placeholderLines=[str(item) for item in data.get("placeholderLines") or []],
            unavailableComparisons=[str(item) for item in data.get("unavailableComparisons") or []],
            sourceVersions=[SourceVersion.from_dict(item) for item in data.get("sourceVersions") or []],
            retainedPath=str(data.get("retainedPath") or "original/source.docx"),
            schemaVersion=int(data.get("schemaVersion") or RECORD_SCHEMA_VERSION),
            createdAt=str(data.get("createdAt") or utc_now_iso()),
            updatedAt=str(data.get("updatedAt") or utc_now_iso()),
        )


# --- 读写 ---


def record_path(project_root: Path) -> Path:
    return Path(project_root) / "original" / RECORD_NAME


def write_import_record(project_root: Path, record: ImportRecord) -> Path:
    """写入导入记录；损坏的旧记录先另存为 ``.damaged-<ts>``。"""
    project_root = Path(project_root)
    target = record_path(project_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            backup = target.with_name(
                "{0}.damaged-{1}".format(target.name, utc_now_iso().replace(":", ""))
            )
            try:
                shutil.copy2(str(target), str(backup))
            except OSError:
                pass
    record.updatedAt = utc_now_iso()
    payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(str(tmp), str(target))
    except OSError:
        shutil.move(str(tmp), str(target))
    return target


def read_import_record(project_root: Path) -> Optional[ImportRecord]:
    """读取导入记录；缺失或损坏返回 ``None``（旧项目无此文件仍可用）。"""
    target = record_path(project_root)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return ImportRecord.from_dict(data)


# --- 处理事实构造 ---


def _finding(
    feature: str,
    *,
    handling: str,
    editable: bool,
    severity: str,
    count: int = 1,
    samples: Sequence[str] = (),
    retained_path: str,
    target_chapter: str = "",
    detail: str = "",
    action: str = "",
) -> PreservationFinding:
    source_part = ""
    element_index: Optional[int] = None
    for sample in samples or ():
        text = str(sample)
        if text.startswith("body["):
            try:
                element_index = int(text[5:-1])
            except ValueError:
                element_index = None
            source_part = source_part or "word/document.xml"
        elif source_part == "":
            source_part = text
    return PreservationFinding(
        feature=feature,
        handling=handling,
        editable=editable,
        severity=severity,
        source_part=source_part,
        element_index=element_index,
        retained_path=retained_path,
        target_chapter=target_chapter,
        detail=detail or "共 {0} 处".format(count),
        action=action,
    )


def findings_from_fidelity(
    report,
    *,
    retained_path: str = "original/source.docx",
    target_chapter: str = "",
) -> List[PreservationFinding]:
    """把保真扫描结论转成分项处理事实（原件留存/文本降级/可编辑分别标注）。"""
    findings: List[PreservationFinding] = []
    for item in getattr(report, "findings", ()) or ():
        feature = str(getattr(item, "feature", "") or "")
        handling, editable, severity, action = _FEATURE_HANDLING.get(
            feature, (HANDLING_ORIGINAL_ONLY, False, SEVERITY_WARNING, "查看原件")
        )
        detail = "共 {0} 处".format(getattr(item, "count", 1))
        if feature == "revision":
            detail += "；不自动接受/拒绝修订，原件保留原意"
        elif feature == "comment":
            detail += "；批注保留在原件，正文不自动处理"
        findings.append(_finding(
            feature,
            handling=handling,
            editable=editable,
            severity=severity,
            count=int(getattr(item, "count", 1) or 1),
            samples=tuple(getattr(item, "samples", ()) or ()),
            retained_path=retained_path,
            target_chapter=target_chapter,
            detail=detail,
            action=action,
        ))
    return findings


def findings_from_extraction(
    extraction,
    *,
    retained_path: str = "original/source.docx",
) -> List[PreservationFinding]:
    """正文提取阶段的事实：缺图占位、复杂表格原样保留。"""
    findings: List[PreservationFinding] = []
    for entry in getattr(extraction, "image_map", ()) or ():
        if not entry.get("missing"):
            continue
        findings.append(PreservationFinding(
            feature="image",
            handling=HANDLING_PLACEHOLDER,
            editable=False,
            severity=SEVERITY_WARNING,
            source_part=str(entry.get("source_part") or "word/document.xml"),
            element_index=entry.get("source_index"),
            retained_path=retained_path,
            target_chapter=str(entry.get("chapter") or ""),
            detail="图片资源不可读，正文保留占位（来源：{0}）".format(
                entry.get("original_rid") or entry.get("target") or "原件"
            ),
            action="定位此处 → 选择替代图片",
        ))
    for entry in getattr(extraction, "unsupported_map", ()) or []:
        feature = str(entry.get("feature") or "")
        label = str(entry.get("label") or feature)
        has_text = bool(entry.get("has_text"))
        findings.append(PreservationFinding(
            feature=feature,
            # 已读到文本但丢了结构 → 文本降级（结构不可编辑）；未读到文本 → 原件留存 + 正文可见占位
            handling=HANDLING_TEXT_FALLBACK if has_text else HANDLING_PLACEHOLDER,
            editable=False,
            severity=SEVERITY_INFO if has_text else SEVERITY_WARNING,
            source_part=str(entry.get("source_part") or "word/document.xml"),
            element_index=entry.get("source_index"),
            retained_path=retained_path,
            target_chapter=str(entry.get("chapter") or ""),
            detail=(
                "{0}已降级为纯文本保留（可编辑），原对象仍在原件：{1}".format(
                    label, entry.get("sample") or ""
                )
                if has_text
                else "{0}暂不支持回写，正文保留可见占位（原件留存，位置 {1}）".format(
                    label, entry.get("sample") or ""
                )
            ),
            action="" if has_text else "定位此处 → 查看原件对应位置",
        ))
    for entry in getattr(extraction, "table_map", ()) or ():
        if entry.get("kind") != "xml":
            continue
        findings.append(PreservationFinding(
            feature="table",
            handling=HANDLING_EDITABLE,
            editable=True,
            severity=SEVERITY_INFO,
            source_part="word/document.xml",
            retained_path=retained_path,
            target_chapter=str(entry.get("chapter") or ""),
            detail="复杂表格以原有 OOXML 资源保留，可原样出稿",
            action="",
        ))
    return findings


def unavailable_from_roundtrip(error: Optional[BaseException]) -> List[str]:
    """往返对照不可用时记录原因（不静默视为对照通过）。"""
    if error is None:
        return []
    return ["往返对照未完成：{0}".format(str(error) or type(error).__name__)]


def merge_findings(*groups: Iterable[PreservationFinding]) -> List[PreservationFinding]:
    """合并同类同位置的处理事实（避免重复计数）。"""
    merged: Dict[Tuple[str, str, str, Optional[int]], PreservationFinding] = {}
    for group in groups:
        for item in group or ():
            key = (item.feature, item.handling, item.target_chapter, item.element_index)
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                continue
            if item.detail and item.detail not in (existing.detail or ""):
                existing.detail = "{0}；{1}".format(existing.detail, item.detail) if existing.detail else item.detail
    return list(merged.values())


# --- 正文占位 ---


def placeholder_lines(findings: Sequence[PreservationFinding]) -> List[str]:
    """为“原件留存/缺资源”事实生成正文可见占位行（可识别、可定位）。"""
    lines: List[str] = []
    for item in findings:
        if item.handling not in (HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER):
            continue
        source = item.retained_path or item.source_part or "原件"
        lines.append(placeholder_text(item.feature, source))
    return lines


def placeholder_in_text(text: str) -> bool:
    return PLACEHOLDER_PREFIX in (text or "")


# --- 来源版本 ---


def archive_source_version(
    project_root: Path,
    source: Path,
    sha256: str,
    *,
    note: str = "",
) -> SourceVersion:
    """把本轮源另存为来源版本（同一哈希只保留一份）。"""
    project_root = Path(project_root)
    source = Path(source)
    digest = (sha256 or "")[:8] or "unknown"
    target_dir = project_root / "original" / VERSIONS_DIR
    target = target_dir / "{0}-{1}".format(digest, source.name)
    retained = ""
    if source.is_file():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(str(source), str(target))
            retained = target.relative_to(project_root).as_posix()
        except OSError:
            retained = ""
    return SourceVersion(
        sha256=sha256, file=source.name, retained=retained, note=note,
    )


def append_source_version(record: ImportRecord, version: SourceVersion) -> None:
    """追加来源版本；同哈希同文件不重复登记。"""
    for existing in record.sourceVersions:
        if existing.sha256 and existing.sha256 == version.sha256 and existing.file == version.file:
            return
    record.sourceVersions.append(version)


__all__ = [
    "RECORD_NAME", "RECORD_SCHEMA_VERSION", "VERSIONS_DIR",
    "SourceVersion", "ImportRecord", "record_path", "write_import_record",
    "read_import_record", "findings_from_fidelity", "findings_from_extraction",
    "unavailable_from_roundtrip", "merge_findings", "placeholder_lines",
    "placeholder_in_text", "archive_source_version", "append_source_version",
]