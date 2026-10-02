# -*- coding: utf-8 -*-
"""结果索引与选择归档（V3.2 32-E）。

用一个只读视图汇总三类既有事实，不复制业务状态：

- 统一出稿索引（``export-result.json``）：成员/格式/状态/路径；
- 交付包清单（``delivery-manifest.json``）：成员/变体/格式/状态/包内相对路径；
- 批次队列 store（``delivery-queue.json``）：批次内逐项状态与路径。

:func:`archive_selection` 把选定结果打成归档 ZIP：部分范围、被略过的可用结果与
不存在的路径都在归档清单里明确标注；汇总状态不会把 partial 标成 complete。
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from doc_tool.application.delivery.queue import (
    JOB_STATUS_LABELS,
    STORE_NAME,
    STORE_SCHEMA_VERSION,
)
from doc_tool.application.delivery.snapshot_package import (
    PACKAGE_MANIFEST_NAME,
    read_delivery_package,
)
from doc_tool.application.intake_contract import (
    FORMAT_STATUS_LABELS,
    USABLE_STATUSES,
    format_label,
    sanitize_name_part,
    sha256_file,
    utc_now_iso,
)
from doc_tool.application.project_export import INDEX_NAME, read_export_index

#: 归档清单 schema（独立于包/队列 schema）。
INDEX_SCHEMA_VERSION = 1
ARCHIVE_MANIFEST_NAME = "selection-manifest.json"
ARCHIVE_KIND = "doc-tool-delivery-selection"

ENTRY_STATUS_LABELS = dict(FORMAT_STATUS_LABELS)
ENTRY_STATUS_LABELS.update(JOB_STATUS_LABELS)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


@dataclass
class ResultEntry:
    """结果索引中的一条：成员/变体/格式/状态/路径。"""

    member: str = ""
    variantId: str = ""
    format: str = ""
    status: str = ""
    path: str = ""
    sourceKind: str = ""
    sourceRef: str = ""
    message: str = ""
    documentVersion: str = ""
    formal: bool = False
    exists: bool = False
    usable: bool = False

    @property
    def label(self) -> str:
        return format_label(self.format)

    @property
    def statusLabel(self) -> str:
        return ENTRY_STATUS_LABELS.get(self.status, self.status or "未知")

    def key(self) -> str:
        return "|".join((self.member, self.variantId, self.format))

    def summary_line(self) -> str:
        where = self.path or "（无产物路径）"
        return "{0}{1}｜{2}｜{3}｜{4}{5}".format(
            self.member or "（未命名成员）",
            "｜变体 {0}".format(self.variantId) if self.variantId else "",
            self.label or self.format,
            self.statusLabel,
            where,
            "" if self.exists else "（文件不存在）",
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "member": self.member,
            "variantId": self.variantId,
            "format": self.format,
            "formatLabel": self.label,
            "status": self.status,
            "statusLabel": self.statusLabel,
            "path": self.path,
            "sourceKind": self.sourceKind,
            "sourceRef": self.sourceRef,
            "message": self.message,
            "documentVersion": self.documentVersion,
            "formal": bool(self.formal),
            "exists": bool(self.exists),
            "usable": bool(self.usable),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ResultEntry":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class ResultIndex:
    """成员/变体/格式/状态/路径的只读汇总视图。"""

    entries: List[ResultEntry] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    generatedAt: str = field(default_factory=utc_now_iso)

    # --- 查询 ---

    def usable_entries(self) -> List[ResultEntry]:
        return [item for item in self.entries if item.usable]

    def existing_entries(self) -> List[ResultEntry]:
        return [item for item in self.entries if item.path and item.exists]

    def missing_entries(self) -> List[ResultEntry]:
        return [item for item in self.entries if item.path and not item.exists]

    def missing_paths(self) -> List[str]:
        return [item.path for item in self.missing_entries()]

    def by_member(self) -> Dict[str, List[ResultEntry]]:
        grouped: Dict[str, List[ResultEntry]] = {}
        for item in self.entries:
            grouped.setdefault(item.member or "（未命名成员）", []).append(item)
        return grouped

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.entries:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    def find(self, *, member: Optional[str] = None, variant: Optional[str] = None, fmt: Optional[str] = None) -> List[ResultEntry]:
        found = []
        for item in self.entries:
            if member is not None and item.member != member:
                continue
            if variant is not None and item.variantId != variant:
                continue
            if fmt is not None and item.format != fmt:
                continue
            found.append(item)
        return found

    def overall_status(self) -> str:
        """complete 只在全部条目均已生成且文件存在时给出；partial 不冒充 complete。"""
        if not self.entries:
            return "empty"
        if not self.usable_entries():
            return "failed"
        usable_existing = [item for item in self.usable_entries() if item.exists]
        if (
            len(usable_existing) == len(self.entries)
            and not self.missing_entries()
            and all(item.status == "ready" for item in self.entries)
        ):
            return "complete"
        return "partial"

    def summary_lines(self, limit: int = 10) -> List[str]:
        counts = self.status_counts()
        lines = ["结果索引：{0} 条｜整体状态 {1}｜来源 {2} 个".format(
            len(self.entries), self.overall_status(), len(self.sources),
        )]
        for status, count in sorted(counts.items()):
            lines.append("· {0}：{1}".format(ENTRY_STATUS_LABELS.get(status, status), count))
        for item in self.entries[: max(0, int(limit))]:
            lines.append("· " + item.summary_line())
        if len(self.entries) > limit:
            lines.append("其余 {0} 条见机器报告".format(len(self.entries) - limit))
        missing = self.missing_entries()
        if missing:
            lines.append("缺失 {0} 条路径（未找到产物，不伪造）".format(len(missing)))
        for note in self.warnings:
            lines.append("提醒：" + note)
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "schemaVersion": INDEX_SCHEMA_VERSION,
            "generatedAt": self.generatedAt,
            "overallStatus": self.overall_status(),
            "statusCounts": self.status_counts(),
            "sources": list(self.sources),
            "entries": [item.to_dict() for item in self.entries],
            "missing": self.missing_paths(),
            "warnings": list(self.warnings),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

# --- 构建视图 ---


def build_result_index(sources) -> ResultIndex:
    """从导出索引/交付包/批次 store 汇总结果视图（只读，不复制业务状态）。"""
    index = ResultIndex()
    if sources is None:
        return index
    if isinstance(sources, (str, Path)):
        sources = [sources]
    for source in sources:
        path = Path(source)
        index.sources.append(str(path))
        kind = _detect_kind(path)
        if kind == "export-index":
            _collect_export_index(path, index)
        elif kind == "package":
            _collect_package(path, index)
        elif kind == "queue-store":
            _collect_queue_store(path, index)
        else:
            index.warnings.append("无法识别的来源（已跳过）：{0}".format(path))
    return index


def _detect_kind(path: Path) -> str:
    if path.is_dir():
        if (path / PACKAGE_MANIFEST_NAME).is_file():
            return "package"
        if (path / INDEX_NAME).is_file():
            return "export-index"
        if (path / STORE_NAME).is_file():
            return "queue-store"
        return ""
    if not path.is_file():
        return ""
    if path.suffix.lower() == ".zip":
        return "package" if read_delivery_package(path) is not None else ""
    if path.name == STORE_NAME:
        return "queue-store"
    if path.name == INDEX_NAME:
        return "export-index"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict):
        if "jobs" in data and data.get("schemaVersion") == STORE_SCHEMA_VERSION:
            return "queue-store"
        if "results" in data and data.get("schemaVersion") == INDEX_SCHEMA_VERSION:
            return "export-index"
    return ""


def _collect_export_index(index_path: Path, index: ResultIndex) -> None:
    report = read_export_index(index_path)
    if report is None:
        index.warnings.append("导出索引不可读：{0}".format(index_path))
        return
    base = index_path if index_path.is_dir() else index_path.parent
    member = Path(report.projectRoot).name if report.projectRoot else base.name
    for item in report.results:
        raw = str(item.path or "")
        resolved = raw
        if raw and not Path(raw).is_absolute():
            resolved = str((base / raw).resolve())
        exists = bool(resolved) and Path(resolved).is_file()
        index.entries.append(ResultEntry(
            member=member,
            variantId="",
            format=item.format,
            status=item.status,
            path=resolved,
            sourceKind="export-index",
            sourceRef=str(index_path),
            message=item.message,
            documentVersion=report.documentVersion,
            formal=bool(item.formal),
            exists=exists,
            usable=bool(item.usable) and exists,
        ))


def _zip_has_member(package: Path, rel: str) -> bool:
    try:
        with zipfile.ZipFile(str(package)) as archive:
            return rel in set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def _collect_package(package: Path, index: ResultIndex) -> None:
    manifest = read_delivery_package(package)
    if manifest is None:
        index.warnings.append("交付包清单不可读：{0}".format(package))
        return
    origin = manifest.get("origin") or {}
    member = str(origin.get("documentName") or origin.get("projectName") or package.name)
    variant = str(origin.get("variantId") or "")
    for item in manifest.get("formats") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "")
        if not rel:
            resolved = ""
            exists = False
        elif package.is_dir():
            resolved = str(package / rel)
            exists = (package / rel).is_file()
        else:
            resolved = "{0}::{1}".format(package, rel)
            exists = _zip_has_member(package, rel)
        index.entries.append(ResultEntry(
            member=member,
            variantId=variant,
            format=str(item.get("format") or ""),
            status=str(item.get("status") or ""),
            path=resolved,
            sourceKind="delivery-package",
            sourceRef=str(package),
            message=str(item.get("message") or ""),
            documentVersion=str(origin.get("documentVersion") or ""),
            formal=bool(item.get("formal")),
            exists=exists,
            usable=bool(item.get("usable")) and exists,
        ))


def _collect_queue_store(store_path: Path, index: ResultIndex) -> None:
    try:
        data = json.loads(Path(store_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index.warnings.append("批次队列不可读：{0}".format(store_path))
        return
    if not isinstance(data, dict) or data.get("schemaVersion") != STORE_SCHEMA_VERSION:
        index.warnings.append("批次队列 schema 不兼容：{0}".format(store_path))
        return
    for job in data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        member = Path(str(job.get("projectRoot") or "")).name or str(job.get("jobId") or "")
        variant = str(job.get("variantId") or "")
        message = str(job.get("error") or job.get("waitingReason") or "")
        results = [item for item in job.get("results") or [] if isinstance(item, dict)]
        if not results:
            for fmt in job.get("formats") or []:
                index.entries.append(ResultEntry(
                    member=member, variantId=variant, format=str(fmt),
                    status=str(job.get("status") or ""), path="",
                    sourceKind="delivery-queue", sourceRef=str(store_path),
                    message=message, exists=False, usable=False,
                ))
            continue
        for item in results:
            raw = str(item.get("path") or "")
            exists = bool(raw) and Path(raw).is_file()
            index.entries.append(ResultEntry(
                member=member, variantId=variant, format=str(item.get("format") or ""),
                status=str(item.get("status") or ""), path=raw,
                sourceKind="delivery-queue", sourceRef=str(store_path),
                message=str(item.get("message") or "") or message,
                formal=bool(item.get("formal")), exists=exists,
                usable=exists and str(item.get("status") or "") in USABLE_STATUSES,
            ))

# --- 选择归档 ---


@dataclass
class ArchiveOutcome:
    """选择归档结果：部分范围与缺失清单明确标注。"""

    ok: bool = False
    path: Optional[Path] = None
    included: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    omitted: List[str] = field(default_factory=list)
    partial: bool = False
    complete: bool = False
    message: str = ""
    manifest: Dict[str, object] = field(default_factory=dict)

    def summary_lines(self) -> List[str]:
        if self.ok and self.path is not None:
            lines = ["选择归档已生成：{0}（{1} 个文件）".format(Path(self.path).name, len(self.included))]
        else:
            lines = ["选择归档未生成：{0}".format(self.message or "没有可归档的产物")]
        if self.partial:
            lines.append("部分范围：未包含 {0} 项可用结果（见归档清单 omitted）".format(len(self.omitted)))
        else:
            lines.append("已包含全部可用结果")
        if self.missing:
            lines.append("缺失 {0} 条路径（已列入归档清单 missing）".format(len(self.missing)))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "path": str(self.path) if self.path else "",
            "included": list(self.included),
            "missing": list(self.missing),
            "omitted": list(self.omitted),
            "partial": bool(self.partial),
            "complete": bool(self.complete),
            "message": self.message,
            "manifest": dict(self.manifest),
        }


def _safe_part(value: str, fallback: str = "result") -> str:
    cleaned = sanitize_name_part(str(value or ""))
    return cleaned or fallback


def _archive_name(entry: ResultEntry) -> str:
    raw = entry.path.split("::")[-1]
    filename = _safe_part(Path(raw).name, "result")
    parts = [_safe_part(item) for item in (entry.member, entry.variantId, entry.format) if item]
    return "/".join(parts + [filename])


def _select(index: ResultIndex, selection) -> List[ResultEntry]:
    """按选择挑条目；未给选择时用全部可用且存在的条目。"""
    if selection is None:
        return [item for item in index.usable_entries() if item.exists]
    if isinstance(selection, (str, ResultEntry)):
        selection = [selection]
    wanted_keys: Set[str] = set()
    wanted_paths: Set[str] = set()
    for item in selection:
        if isinstance(item, ResultEntry):
            wanted_keys.add(item.key())
            continue
        text = str(item)
        if "|" in text:
            wanted_keys.add(text)
        else:
            wanted_paths.add(text)
    chosen: List[ResultEntry] = []
    seen: Set[str] = set()
    for entry in index.entries:
        if entry.key() in seen:
            continue
        if entry.key() in wanted_keys or (entry.path and entry.path in wanted_paths):
            chosen.append(entry)
            seen.add(entry.key())
    return chosen


def archive_selection(index: ResultIndex, target_zip, *, selection=None) -> ArchiveOutcome:
    """把选定结果打成归档 ZIP，并写入选择清单（部分范围/缺失明确）。"""
    target = Path(target_zip)
    outcome = ArchiveOutcome(path=target)
    usable_existing = [item for item in index.usable_entries() if item.exists]
    chosen = _select(index, selection)
    chosen_existing = [item for item in chosen if item.exists]
    chosen_keys = {item.key() for item in chosen_existing}
    omitted = [item for item in usable_existing if item.key() not in chosen_keys]
    missing = [item for item in chosen if not item.exists]
    outcome.omitted = [item.key() for item in omitted]
    outcome.missing = [item.path or item.key() for item in missing]
    outcome.partial = bool(omitted) or bool(missing)
    outcome.complete = not outcome.partial

    if not chosen_existing:
        outcome.message = "没有可归档的可用结果（缺失项已列入 missing）"
        outcome.manifest = {
            "schemaVersion": INDEX_SCHEMA_VERSION,
            "kind": ARCHIVE_KIND,
            "createdAt": utc_now_iso(),
            "partial": True,
            "complete": False,
            "included": [],
            "omitted": list(outcome.omitted),
            "missing": list(outcome.missing),
        }
        return outcome

    target.parent.mkdir(parents=True, exist_ok=True)
    entries_meta: List[Dict[str, object]] = []
    try:
        with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as archive:
            for entry in chosen_existing:
                arcname = _archive_name(entry)
                digest = ""
                if "::" in entry.path:
                    source_zip, member = entry.path.split("::", 1)
                    try:
                        with zipfile.ZipFile(source_zip) as source:
                            data = source.read(member)
                    except (OSError, KeyError, zipfile.BadZipFile):
                        outcome.missing.append(entry.path)
                        continue
                    archive.writestr(arcname, data)
                    digest = _sha256_bytes(data)
                else:
                    try:
                        archive.write(entry.path, arcname)
                    except OSError:
                        outcome.missing.append(entry.path)
                        continue
                    digest = sha256_file(entry.path)
                meta = entry.to_dict()
                meta["archivePath"] = arcname
                meta["sha256"] = digest
                entries_meta.append(meta)
                outcome.included.append(arcname)
            manifest: Dict[str, object] = {
                "schemaVersion": INDEX_SCHEMA_VERSION,
                "kind": ARCHIVE_KIND,
                "createdAt": utc_now_iso(),
                "partial": outcome.partial,
                "complete": outcome.complete,
                "selection": "部分范围：仅包含所选结果" if outcome.partial else "全部可用结果",
                "included": entries_meta,
                "omitted": list(outcome.omitted),
                "missing": list(outcome.missing),
                "sources": list(index.sources),
                "notes": [
                    (
                        "部分范围：未包含 {0} 项可用结果，逐项见 omitted。".format(len(outcome.omitted))
                        if outcome.omitted else "已包含全部可用结果。"
                    ),
                    "不存在的路径列入 missing，不伪造产物。",
                ],
            }
            archive.writestr(
                ARCHIVE_MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
    except OSError as exc:
        outcome.ok = False
        outcome.message = "写入选择归档失败：{0}".format(exc)
        return outcome

    outcome.ok = bool(outcome.included)
    # V3.2 5.3：完整集合登记复用 V2.9（部分范围只标注，不冒充完整基线）。
    registration_note = ""
    try:
        import shutil
        import tempfile

        from doc_tool.application.delivery.collection_bridge import bridge_directory

        work_dir = Path(tempfile.mkdtemp(prefix="delivery-archive-"))
        try:
            with zipfile.ZipFile(str(target)) as archive:
                archive.extractall(work_dir)
            bridged = bridge_directory(
                work_dir,
                version=str(manifest.get("createdAt") or "1.0")[:10] or "1.0",
                label="delivery-selection",
                register=bool(outcome.complete),
            )
            collection_summary = bridged.to_dict()
            # 归档内部文件集合可能“自洽完整”，但交付选择若为部分范围，
            # 不得据此登记/声称完整基线（V3.2 5.3）。
            collection_summary["archiveContentsComplete"] = bool(collection_summary.get("complete"))
            collection_summary["complete"] = bool(outcome.complete)
            collection_summary["registered"] = bool(
                outcome.complete and collection_summary.get("registrationPath")
            )
            if not outcome.complete:
                collection_summary["registrationPath"] = ""
                collection_summary["registrationNote"] = "部分范围：未登记完整集合基线"
            manifest["collection"] = collection_summary
            if outcome.complete and bridged.registrationPath:
                registration_note = "完整集合已登记：{0}".format(
                    Path(bridged.registrationPath).name,
                )
            elif outcome.complete:
                registration_note = "完整集合登记未完成（成果仍保留）"
            else:
                registration_note = "部分范围：按选择归档清单处理，未登记完整集合基线"
            # 把集合摘要写回归档清单（保持单一事实来源）
            with zipfile.ZipFile(str(target), "a", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    ARCHIVE_MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
        finally:
            shutil.rmtree(str(work_dir), ignore_errors=True)
    except Exception as exc:  # noqa: BLE001 - 登记失败不删除已生成归档
        registration_note = "集合登记未完成（归档仍可用）：{0}".format(exc)
        manifest.setdefault("collection", {})["error"] = str(exc) or type(exc).__name__

    outcome.manifest = manifest
    outcome.message = "选择归档已生成（含 {0} 个结果{1}）{2}".format(
        len(outcome.included), "，部分范围" if outcome.partial else "",
        "；" + registration_note if registration_note else "",
    )
    return outcome


__all__ = [
    "INDEX_SCHEMA_VERSION", "ARCHIVE_MANIFEST_NAME", "ARCHIVE_KIND", "ENTRY_STATUS_LABELS",
    "ResultEntry", "ResultIndex", "ArchiveOutcome", "build_result_index", "archive_selection",
]