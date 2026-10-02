# -*- coding: utf-8 -*-
"""自足快照交付包与换机补刷新/正式化（V3.2 32-C / 32-D）。

**32-C 自足快照包**：把一轮统一出稿的结果与固定输入打成 schema 1 的独立包：

- 包内清单（``delivery-manifest.json``）只记相对路径、hash、来源版本/变体、
  格式状态、待处理阶段与完整性；不含原机器绝对路径、凭据、Git 或无关缓存。
- 内容含该轮可读 DOCX、其他可用格式产物、构建必需正文/底模/资源快照、报告
  （``reports/export-result.json``，路径已改写为包内相对路径）。
- 包可搬目录/换机器后阅读；缺个别可选资源时仍可读并在完整性中列出。

**32-D 换机补刷新/正式化**：:func:`formalize_package` 校验清单/hashes，准备包内
工作副本，基于**包内原快照**补缺失阶段（Word 刷新/PDF 转换）：

- 不依赖原电脑项目路径，也不追逐当前源；源项目后来变化只提示捕获时点。
- 无 Word/刷新失败保持 ``waiting-refresh`` 并保留可读 DOCX，原包不删除。
- 本地登记键 = packageId + 输入 digest + 目标位置，重复处理直接打开已有结果；
  登记写入失败保留新 DOCX 安全副本，原正式记录不变。
- 正式状态只用 :mod:`doc_tool.domain.output_state` 的既有定义判定，本模块不自行提升。
"""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.writer import atomic_write
from doc_tool.application.intake_contract import (
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_PDF,
    FORMAT_SOURCE_ZIP,
    STATUS_FAILED,
    STATUS_PENDING_CONVERT,
    STATUS_PENDING_REFRESH,
    ExportRequest,
    FormatResult,
    format_label,
    normalize_format,
    normalize_formats,
    sha256_file,
    sha256_text,
    utc_now_iso,
)
from doc_tool.application.project_export import (
    ExportReport,
    read_export_index,
    report_docx_path,
    run_project_export,
)

#: 包清单与说明文件名（schema 1，独立于项目 schema）。
PACKAGE_MANIFEST_NAME = "delivery-manifest.json"
PACKAGE_README_NAME = "DELIVERY_PACKAGE.md"
PACKAGE_KIND = "doc-tool-delivery-package"
PACKAGE_SCHEMA_VERSION = 1

#: 本地登记文件名（可参数注入，便于测试与自定义位置）。
REGISTRY_NAME = "delivery-registry.json"
REGISTRY_SCHEMA_VERSION = 1

#: 包内固定相对目录。
DOCX_DIR = "docx"
REPORTS_DIR = "reports"
SNAPSHOT_DIR = "snapshot"
SAFE_COPY_DIR = "待登记"

#: 不进入包的快照内容（缓存/日志/中间产物/无关历史）。
EXCLUDED_PARTS = (
    "logs", ".state", "output", "__pycache__", ".git", ".hg", ".svn",
    "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache",
)
EXCLUDED_NAMES = ("user.yml", "user.yaml", "credentials.json", "token.json", "recent.json")
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".bak")

#: 待处理阶段到格式名的前缀映射（``docx-refresh`` → ``docx``）。
STAGE_SEPARATOR = "-"

@dataclass
class PackageOutcome:
    """交付包生成结果。"""

    ok: bool = False
    path: Optional[Path] = None
    packageId: str = ""
    manifest: Dict[str, object] = field(default_factory=dict)
    included: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    message: str = ""

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        if self.ok and self.path is not None:
            lines.append("交付包已生成：{0}".format(Path(self.path).name))
            lines.append("包含 {0} 个文件，包内为相对路径".format(len(self.included)))
            pending = self.manifest.get("pendingStages") or []
            if pending:
                lines.append("待处理阶段：{0}".format("、".join(str(item) for item in pending)))
        else:
            lines.append("交付包未生成：{0}".format(self.message or "未知原因"))
        if self.missing:
            lines.append("包内缺少 {0} 项（已在完整性清单列出）".format(len(self.missing)))
        for item in self.warnings[:3]:
            lines.append("提醒：{0}".format(item))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "path": str(self.path) if self.path else "",
            "packageId": self.packageId,
            "included": list(self.included),
            "missing": list(self.missing),
            "excluded": list(self.excluded),
            "warnings": list(self.warnings),
            "message": self.message,
            "manifest": dict(self.manifest),
        }


@dataclass
class PackageCheck:
    """包校验结果：必需项问题才算不通过，可选缺失只提示。"""

    ok: bool = False
    problems: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    missingOptional: List[str] = field(default_factory=list)
    #: V3.2 3.4：包版本不符但可回退阅读/导出可读产物。
    readableOnly: bool = False
    versionNote: str = ""

    def summary_lines(self) -> List[str]:
        if self.ok:
            lines = ["包校验通过"]
        else:
            lines = ["包校验未通过：{0} 项问题".format(len(self.problems))]
        lines.extend("· " + item for item in self.problems[:5])
        if self.missingOptional:
            lines.append("可选内容缺失 {0} 项（仍可阅读/补刷新）".format(len(self.missingOptional)))
        return lines


@dataclass
class FormalizeOutcome:
    """换机补刷新/正式化结果（状态词见模块头）。"""

    ok: bool = False
    status: str = ""
    packageId: str = ""
    inputDigest: str = ""
    workRoot: str = ""
    projectRoot: str = ""
    destination: str = ""
    results: List[FormatResult] = field(default_factory=list)
    readableDocx: str = ""
    registeredPath: str = ""
    pendingFormats: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sourceUpdated: bool = False
    registryKey: str = ""
    message: str = ""
    manifest: Dict[str, object] = field(default_factory=dict)

    def usable_results(self) -> List[FormatResult]:
        return [item for item in self.results if item.usable]

    def summary_lines(self) -> List[str]:
        labels = {
            "registered": "已补刷新并登记",
            "already-registered": "已有同一登记，直接打开（不重复建历史）",
            "waiting-refresh": "保持待刷新（可读 DOCX 保留，原包不删除）",
            "registration-failed": "刷新完成但登记失败（已保留安全副本，原记录不变）",
            "nothing-pending": "包内已无待处理阶段",
            "invalid": "包非法或校验未通过",
        }
        lines = ["交付包 {0}：{1}".format(
            self.packageId or "（未知）", labels.get(self.status, self.status or "未知"),
        )]
        if self.message:
            lines.append(self.message)
        if self.registeredPath:
            lines.append("正式结果：{0}".format(self.registeredPath))
        elif self.readableDocx:
            lines.append("可读稿：{0}".format(self.readableDocx))
        for item in self.results:
            lines.append("· {0}{1}".format(format_label(item.format), item.label()))
        for item in self.warnings[:3]:
            lines.append("提醒：{0}".format(item))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "packageId": self.packageId,
            "inputDigest": self.inputDigest,
            "registryKey": self.registryKey,
            "workRoot": self.workRoot,
            "projectRoot": self.projectRoot,
            "destination": self.destination,
            "results": [item.to_dict() for item in self.results],
            "readableDocx": self.readableDocx,
            "registeredPath": self.registeredPath,
            "pendingFormats": list(self.pendingFormats),
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "sourceUpdated": self.sourceUpdated,
            "message": self.message,
        }


# --- 通用工具 ---


def _excluded(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    if any(part in EXCLUDED_PARTS for part in parts):
        return True
    name = parts[-1]
    if name in EXCLUDED_NAMES:
        return True
    return name.lower().endswith(EXCLUDED_SUFFIXES)


def _file_entry(rel: str, role: str, path: Path, *, required: bool = False) -> Dict[str, object]:
    size = 0
    try:
        size = Path(path).stat().st_size
    except OSError:
        size = 0
    return {
        "path": rel,
        "role": role,
        "sha256": sha256_file(Path(path)),
        "size": size,
        "required": bool(required),
    }


def _copy_file(
    source: Path,
    target: Path,
    rel: str,
    role: str,
    files: List[Dict[str, object]],
    *,
    required: bool,
) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
    except OSError:
        return False
    files.append(_file_entry(rel, role, target, required=required))
    return True

def _coerce_report(source) -> Optional[ExportReport]:
    if isinstance(source, ExportReport):
        return source
    return read_export_index(source)


def _pending_stages(report: ExportReport) -> List[str]:
    """本轮还需处理的阶段（待刷新/待转换/失败），供接收机按需补做。"""
    stages: List[str] = []
    for item in report.results:
        stage = ""
        if item.status == STATUS_PENDING_REFRESH:
            stage = "{0}-refresh".format(item.format)
        elif item.status == STATUS_PENDING_CONVERT:
            stage = "{0}-convert".format(item.format)
        elif item.status == STATUS_FAILED:
            stage = "{0}-failed".format(item.format)
        if stage and stage not in stages:
            stages.append(stage)
    return stages


def _formats_from_stages(stages: Sequence[str]) -> List[str]:
    formats: List[str] = []
    for stage in stages or ():
        head = str(stage).split(STAGE_SEPARATOR, 1)[0]
        name = normalize_format(head)
        if name and name not in formats:
            formats.append(name)
    return formats


def _packaged_pending_formats(report: Optional[ExportReport], manifest: Dict[str, object]) -> List[str]:
    formats: List[str] = []
    if report is not None:
        for item in report.results:
            if item.status in (STATUS_FAILED, STATUS_PENDING_CONVERT, STATUS_PENDING_REFRESH):
                if item.format not in formats:
                    formats.append(item.format)
    for name in _formats_from_stages(manifest.get("pendingStages") or []):
        if name not in formats:
            formats.append(name)
    return formats


def _probe_word() -> bool:
    try:
        from doc_tool.application.word_check import check_word_available

        # 换机正式化是显式动作：慢启动多等一会儿，避免把可用 Word 误判为不可用。
        return bool(check_word_available(dispatch_timeout_seconds=30.0).available)
    except Exception:  # noqa: BLE001 - 探测失败按不可用兜底
        return False


def _manifest_doc_meta(snapshot_dir: Path) -> Dict[str, str]:
    try:
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(Path(snapshot_dir))
    except Exception:  # noqa: BLE001 - 清单不可读时用报告字段兜底
        return {}
    return {
        "projectId": str(getattr(manifest, "projectId", "") or ""),
        "documentType": str(getattr(manifest, "documentType", "") or ""),
        "documentNo": str(getattr(manifest, "documentNo", "") or ""),
        "documentName": str(getattr(manifest, "documentName", "") or ""),
        "documentVersion": str(getattr(manifest, "documentVersion", "") or ""),
    }


def _copy_snapshot(
    snapshot_dir: Path,
    root: Path,
    files: List[Dict[str, object]],
    excluded: List[str],
    *,
    include_original: bool,
) -> int:
    """收必要正文/底模/资源；不带 Git/凭据/缓存/中间产物/原机器绝对路径。"""
    snapshot_dir = Path(snapshot_dir)
    count = 0
    for path in sorted(snapshot_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(snapshot_dir).as_posix()
        if rel.startswith("original/source.docx") and not include_original:
            excluded.append(rel)
            continue
        if _excluded(rel):
            excluded.append(rel)
            continue
        role = "snapshot"
        if rel.startswith("content/"):
            role = "content"
        elif rel.startswith("template/"):
            role = "template"
        elif rel.startswith("assets/"):
            role = "asset"
        elif rel.startswith("original/"):
            role = "source-record"
        target_rel = "{0}/{1}".format(SNAPSHOT_DIR, rel)
        required = rel == "project.yml" or rel.startswith("content/") or rel.startswith("template/")
        if _copy_file(path, root / target_rel, target_rel, role, files, required=required):
            count += 1
    return count


def _ensure_snapshot_dirs(root: Path) -> None:
    """补齐标准目录（空目录 ZIP 不保存，需显式建目录项，构建内核要求其存在）。"""
    for rel in (
        SNAPSHOT_DIR,
        "{0}/content".format(SNAPSHOT_DIR),
        "{0}/assets".format(SNAPSHOT_DIR),
        "{0}/assets/images".format(SNAPSHOT_DIR),
        "{0}/assets/tables".format(SNAPSHOT_DIR),
        "{0}/template".format(SNAPSHOT_DIR),
    ):
        try:
            (Path(root) / rel).mkdir(parents=True, exist_ok=True)
        except OSError:
            continue


def _copy_result_artifacts(
    root: Path,
    item: FormatResult,
    files: List[Dict[str, object]],
) -> str:
    """把该格式的可用产物收进包；返回包内相对路径（不可用为空串）。"""
    if not item.path:
        return ""
    source = Path(item.path)
    if item.format == FORMAT_DOCX:
        if not source.is_file():
            return ""
        rel = "{0}/{1}".format(DOCX_DIR, source.name)
        _copy_file(source, root / rel, rel, "readable-docx", files, required=True)
        return rel
    if item.format == FORMAT_PDF:
        if not source.is_file():
            return ""
        rel = "pdf/{0}".format(source.name)
        _copy_file(source, root / rel, rel, "pdf", files, required=False)
        return rel
    if item.format == FORMAT_SOURCE_ZIP:
        if not source.is_file():
            return ""
        rel = "source/{0}".format(source.name)
        _copy_file(source, root / rel, rel, "source-package", files, required=False)
        return rel
    if item.format == FORMAT_HTML:
        base = source.parent if source.is_file() else source
        if not base.is_dir():
            return ""
        index_rel = ""
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = "html/" + path.relative_to(base).as_posix()
            _copy_file(path, root / rel, rel, "offline-html", files, required=False)
            if path.name == source.name and not index_rel:
                index_rel = rel
        return index_rel
    if source.is_file():
        rel = "artifacts/{0}".format(source.name)
        _copy_file(source, root / rel, rel, "artifact", files, required=False)
        return rel
    return ""


def _input_digest(files: Sequence[Dict[str, object]]) -> str:
    """固定输入 digest：正文/底模/资源/来源记录的内容哈希。"""
    build_roles = ("content", "template", "asset", "source-record", "snapshot")
    lines = sorted(
        "{0}:{1}".format(entry.get("path"), entry.get("sha256") or "")
        for entry in files or ()
        if entry.get("role") in build_roles
    )
    return sha256_text("\n".join(lines))


def _chapter_digests(snapshot_dir: Path) -> Dict[str, str]:
    """只记包内固定正文的 hash（不记缓存/日志/历史副本），供比对捕获时点。"""
    digests: Dict[str, str] = {}
    for path in sorted(Path(snapshot_dir).rglob("*.md")):
        rel = path.relative_to(snapshot_dir).as_posix()
        if not rel.startswith("content/") or _excluded(rel):
            continue
        try:
            digests[rel] = sha256_text(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return digests


def _package_report_dict(
    report: ExportReport,
    *,
    docx_rel: str,
    results_meta: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    """改写报告为包内相对路径（原机器绝对路径不进入包）。"""
    data = report.to_dict()
    data["projectRoot"] = "."
    data["destination"] = "."
    data["snapshotWorkDir"] = SNAPSHOT_DIR
    data["indexPath"] = "{0}/export-result.json".format(REPORTS_DIR)
    data["docxPath"] = docx_rel
    mapped = {str(item.get("format")): item for item in results_meta}
    for entry in data.get("results") or []:
        meta = mapped.get(str(entry.get("format") or ""))
        entry["path"] = str(meta.get("path") or "") if meta else ""
        entry["sha256"] = str(meta.get("sha256") or "") if meta else ""
    return data


def _readme_text(manifest: Dict[str, object]) -> str:
    origin = manifest.get("origin") or {}
    integrity = manifest.get("integrity") or {}
    lines = [
        "# 待刷新交付包（自足快照）",
        "",
        "本包固定了一轮出稿的内容与产物，可复制到任意目录/机器上阅读，",
        "并在有 Microsoft Word 的机器上补刷新/正式化；包内不使用原机器绝对路径。",
        "",
        "## 来源",
        "",
        "- 文档：{0}（{1}）".format(origin.get("documentName", ""), origin.get("documentVersion", "")),
        "- 变体：{0}".format(origin.get("variantId") or "（无）"),
        "- 捕获时点：{0}".format(origin.get("capturedAt", "")),
        "- 范围：{0}".format(origin.get("scope", {})),
        "- 来源模式：{0}".format(origin.get("sourceMode", "")),
        "",
        "## 内容",
        "",
        "- `docx/`：本轮可读 DOCX（可打开）",
        "- `snapshot/`：固定正文/底模/资源快照（相对路径）",
        "- `reports/export-result.json`：本轮各格式状态与路径（包内相对）",
        "- `delivery-manifest.json`：清单（来源/版本/变体/digest/hashes/待处理阶段）",
        "",
        "## 待处理阶段",
        "",
        "- {0}".format("、".join(str(item) for item in manifest.get("pendingStages") or []) or "（无）"),
        "- 自足：{0}".format("是" if integrity.get("selfContained") else "否（见 integrity.missing）"),
        "",
    ]
    return "\n".join(lines)

# --- 32-C：生成自足快照包 ---


def build_delivery_package(
    source,
    *,
    target=None,
    variant_id: str = "",
    include_original: bool = False,
    notes: Sequence[str] = (),
) -> PackageOutcome:
    """把一轮出稿结果与固定快照打成自足交付包（``.zip`` 或目录）。

    ``source`` 为 :class:`ExportReport`、导出目录或 ``export-result.json`` 路径。
    """
    outcome = PackageOutcome()
    report = _coerce_report(source)
    if report is None:
        outcome.message = "无法读取本轮出稿报告（export-result.json）：请先生成一轮再打包"
        return outcome
    snapshot_dir = Path(report.snapshotWorkDir) if report.snapshotWorkDir else None
    if snapshot_dir is None or not snapshot_dir.is_dir():
        outcome.message = "本轮快照目录不可用，无法形成自足包：{0}".format(
            report.snapshotWorkDir or "（未记录）"
        )
        return outcome

    if target is None:
        base = Path(report.destination) if report.destination and Path(report.destination).is_dir() else snapshot_dir
        target = base / "delivery-{0}.zip".format(report.captureId or uuid.uuid4().hex[:8])
    target = Path(target)
    as_zip = target.suffix.lower() == ".zip"
    staging = (target.parent / (".delivery-build-" + uuid.uuid4().hex[:8])) if as_zip else target
    if staging.exists():
        shutil.rmtree(str(staging), ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    files: List[Dict[str, object]] = []
    excluded: List[str] = []
    try:
        _copy_snapshot(
            snapshot_dir, staging, files, excluded, include_original=include_original,
        )
        _ensure_snapshot_dirs(staging)
        for warning in report.warnings:
            text = str(warning)
            if text.startswith("资源缺失："):
                missing = text.split("：", 1)[1].split("（", 1)[0].strip()
                if missing and missing not in outcome.missing:
                    outcome.missing.append(missing)

        results_meta: List[Dict[str, object]] = []
        docx_rel = ""
        for item in report.results:
            rel = _copy_result_artifacts(staging, item, files)
            meta: Dict[str, object] = {
                "format": item.format,
                "label": format_label(item.format),
                "status": item.status,
                "path": rel,
                "sha256": str(item.sha256 or ""),
                "formal": bool(item.formal),
                "usable": bool(item.usable),
                "message": item.message,
            }
            if rel:
                meta["sha256"] = sha256_file(staging / rel)
                outcome.included.append(rel)
            results_meta.append(meta)
            if item.format == FORMAT_DOCX and rel:
                docx_rel = rel
        if not docx_rel:
            outcome.message = (
                "本轮没有可打开 DOCX，无法形成自足可读包："
                "请先在无 Word 机器得到可读稿，再生成待刷新包"
            )
            return outcome

        reports_dir = staging / REPORTS_DIR
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_rel = "{0}/export-result.json".format(REPORTS_DIR)
        atomic_write(
            reports_dir / "export-result.json",
            json.dumps(
                _package_report_dict(report, docx_rel=docx_rel, results_meta=results_meta),
                ensure_ascii=False, indent=2,
            ),
        )
        files.append(_file_entry(report_rel, "report", reports_dir / "export-result.json", required=True))
        outcome.included.append(report_rel)

        # V3.2 3.2：复用 V2.9 集合文件包装（收集规则/分类/清单一套），
        # 在包内落一份集合格式清单，便于接收方按集合基线核对与再次登记。
        collection_summary: Dict[str, object] = {}
        try:
            from doc_tool.application.delivery.collection_bridge import (
                collection_manifest_for, manifest_summary,
            )

            collection_manifest, collection_path = collection_manifest_for(
                staging, label="delivery-package",
            )
            categories, missing_files, complete = manifest_summary(collection_manifest)
            collection_summary = {
                "manifest": str(Path(collection_path).name) if collection_path else "",
                "fileCount": len(getattr(collection_manifest, "files", []) or []),
                "categories": categories,
                "complete": complete,
                "missing": missing_files[:10],
                "collectionId": str(getattr(collection_manifest, "collectionId", "")),
            }
            if collection_path is not None:
                rel = Path(collection_path).relative_to(staging).as_posix()
                files.append(_file_entry(rel, "manifest", Path(collection_path), required=False))
                outcome.included.append(rel)
        except Exception as exc:  # noqa: BLE001 - 集合包装不可用不阻断打包
            collection_summary = {"error": str(exc) or type(exc).__name__}

        doc_meta = _manifest_doc_meta(snapshot_dir)
        package_id = "pkg-" + uuid.uuid4().hex[:10]
        integrity = {
            "selfContained": not outcome.missing,
            "missing": list(outcome.missing),
            "excluded": list(excluded),
            "fileCount": len(files),
            "totalBytes": sum(int(entry.get("size") or 0) for entry in files),
        }
        manifest: Dict[str, object] = {
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "kind": PACKAGE_KIND,
            "packageId": package_id,
            "createdAt": utc_now_iso(),
            "origin": {
                "projectId": doc_meta.get("projectId", ""),
                "projectName": Path(report.projectRoot).name if report.projectRoot else "",
                "documentType": doc_meta.get("documentType") or report.documentType,
                "documentNo": doc_meta.get("documentNo", ""),
                "documentName": doc_meta.get("documentName", ""),
                "documentVersion": doc_meta.get("documentVersion") or report.documentVersion,
                "variantId": str(variant_id or getattr(report, "variantId", "") or ""),
                "variantApplied": bool(getattr(report, "variantApplied", False)),
                "capturedAt": report.createdAt,
                "roundId": report.roundId,
                "captureId": report.captureId,
                "sourceMode": report.sourceMode,
                "scope": report.scope.to_dict(),
            },
            "formats": results_meta,
            "pendingStages": _pending_stages(report),
            "files": files,
            "inputDigest": _input_digest(files),
            "chapterDigests": _chapter_digests(snapshot_dir),
            "reports": [report_rel],
            "collection": collection_summary,
            "integrity": integrity,
            "notes": list(notes) + [
                "包内一律相对路径；不含凭据、Git 与无关缓存。",
                "源项目后来变化只提示捕获时点，不影响本包继续处理。",
            ],
        }
        atomic_write(
            staging / PACKAGE_MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        atomic_write(staging / PACKAGE_README_NAME, _readme_text(manifest))
        outcome.included.append(PACKAGE_MANIFEST_NAME)
        outcome.included.append(PACKAGE_README_NAME)
        outcome.excluded = list(excluded)

        if as_zip:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(staging.rglob("*")):
                    rel = path.relative_to(staging).as_posix()
                    if path.is_dir() and not _excluded(rel):
                        archive.writestr(rel + "/", "")
                for path in sorted(staging.rglob("*")):
                    if path.is_file():
                        archive.write(str(path), path.relative_to(staging).as_posix())
        outcome.ok = True
        outcome.path = target
        outcome.packageId = package_id
        outcome.manifest = manifest
        outcome.message = "交付包已生成"
        if outcome.missing:
            outcome.warnings.append(
                "包内缺少 {0} 项可选资源，已保留占位并在完整性清单列出".format(len(outcome.missing))
            )
        return outcome
    except OSError as exc:
        outcome.ok = False
        outcome.message = "写入交付包失败：{0}".format(exc)
        return outcome
    finally:
        if as_zip or not outcome.ok:
            shutil.rmtree(str(staging), ignore_errors=True)

# --- 读取与校验 ---


def _bytes_digest(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def read_delivery_package(package) -> Optional[Dict[str, object]]:
    """读取包清单（目录或 ZIP）；不是本应用的 schema 1 包时返回 ``None``。"""
    path = Path(package)
    try:
        if path.is_dir():
            manifest_file = path / PACKAGE_MANIFEST_NAME
            if not manifest_file.is_file():
                return None
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        elif path.is_file() and zipfile.is_zipfile(str(path)):
            with zipfile.ZipFile(str(path)) as archive:
                if PACKAGE_MANIFEST_NAME not in archive.namelist():
                    return None
                data = json.loads(archive.read(PACKAGE_MANIFEST_NAME).decode("utf-8"))
        else:
            return None
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schemaVersion") != PACKAGE_SCHEMA_VERSION or str(data.get("kind") or "") != PACKAGE_KIND:
        return None
    return data


def verify_delivery_package(package, *, check_hashes: bool = True) -> PackageCheck:
    """校验清单与 hashes；必需项问题才算不通过，可选缺失只提示。"""
    check = PackageCheck()
    path = Path(package)
    manifest = read_delivery_package(package)
    if manifest is None:
        # V3.2 3.4：版本不符时回退为“只读/可导出可读产物”，而不是一律不可用。
        from doc_tool.application.delivery.package_version import (
            readable_artifacts, version_fallback,
        )

        fallback = version_fallback(path)
        if fallback.readableOnly:
            check.ok = True
            check.readableOnly = True
            check.versionNote = fallback.reason
            check.missingOptional.extend(
                "{0}（可导出可读产物）".format(item.get("path"))
                for item in readable_artifacts(path)[:10]
            )
            return check
        check.problems.append("包清单不可读，或不是本应用的交付包（schema 1）")
        return check
    files = manifest.get("files") or []
    if not files:
        check.problems.append("包清单没有文件记录（files 为空）")
    # 非法附件/越界路径：不允许绝对路径、盘符或 .. 片段（V3.2 3.5）
    for entry in files:
        rel = str(entry.get("path") or "")
        if not rel:
            continue
        normalized = rel.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if normalized.startswith("/") or ".." in parts or (":" in parts[0] if parts else False):
            check.problems.append("非法附件路径（越出包内）：{0}".format(rel))
    if check.problems:
        return check

    if path.is_dir():
        for entry in files:
            rel = str(entry.get("path") or "")
            if not rel:
                continue
            target = path / rel
            if not target.is_file():
                if entry.get("required"):
                    check.problems.append(rel)
                    check.missing.append(rel)
                else:
                    check.missingOptional.append(rel)
                continue
            if check_hashes and entry.get("sha256") and sha256_file(target) != entry.get("sha256"):
                check.problems.append("内容哈希不符：{0}".format(rel))
    elif path.is_file() and zipfile.is_zipfile(str(path)):
        with zipfile.ZipFile(str(path)) as archive:
            names = set(archive.namelist())
            for entry in files:
                rel = str(entry.get("path") or "")
                if not rel:
                    continue
                if rel not in names:
                    if entry.get("required"):
                        check.problems.append(rel)
                        check.missing.append(rel)
                    else:
                        check.missingOptional.append(rel)
                    continue
                if check_hashes and entry.get("sha256"):
                    digest = _bytes_digest(archive.read(rel))
                    if digest != entry.get("sha256"):
                        check.problems.append("内容哈希不符：{0}".format(rel))
    else:
        check.problems.append("包既不是目录也不是可读 ZIP：{0}".format(path))
        return check

    check.ok = not check.problems
    return check

# --- 32-D：换机补刷新/正式化 ---


def _registration_key(package_id: str, input_digest: str, destination) -> str:
    """本地登记键：packageId + 输入 digest + 目标位置（不承诺跨机器全局唯一）。"""
    target = str(Path(destination).resolve()).casefold() if destination else ""
    return sha256_text("|".join((str(package_id or ""), str(input_digest or ""), target)))


def _read_registry(registry_path: Path) -> Dict[str, object]:
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "entries": []}
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    return data


def _registry_lookup(registry_path: Path, key: str) -> Optional[Dict[str, object]]:
    """已登记且结果文件仍在时返回记录（重复处理直接打开，不新增记录）。"""
    for entry in _read_registry(registry_path).get("entries") or []:
        if not isinstance(entry, dict) or entry.get("key") != key:
            continue
        target = str(entry.get("path") or "")
        if target and Path(target).is_file():
            return entry
    return None


def _registry_write(registry_path: Path, entry: Dict[str, object], *, writer=None) -> None:
    if writer is not None:
        writer(Path(registry_path), dict(entry))
        return
    data = _read_registry(registry_path)
    entries = [
        item for item in data.get("entries") or []
        if isinstance(item, dict) and item.get("key") != entry.get("key")
    ]
    entries.append(dict(entry))
    atomic_write(
        Path(registry_path),
        json.dumps(
            {"schemaVersion": REGISTRY_SCHEMA_VERSION, "updatedAt": utc_now_iso(), "entries": entries},
            ensure_ascii=False, indent=2,
        ),
    )


def _source_changed(manifest: Dict[str, object], source_root: Path) -> bool:
    """源项目是否在捕获后变化（只提示，不拒绝历史快照正式化）。

    快照内章节是 ``content/<章>.md``，源项目是 ``content/<类型>/<章>.md``，
    因此按包内记录的相对后缀在源项目里找同名章节比较。
    """
    digests = manifest.get("chapterDigests") or {}
    if not isinstance(digests, dict) or not digests:
        return False
    root = Path(source_root)
    if not root.is_dir():
        return False
    local: List[str] = [
        rel for rel in (
            path.relative_to(root).as_posix() for path in sorted(root.rglob("*.md"))
        )
        if not _excluded(rel)
    ]
    for rel, digest in digests.items():
        wanted = str(rel)
        suffix = wanted.split("content/", 1)[1] if "content/" in wanted else wanted
        matches = [item for item in local if item.endswith(suffix)]
        if not matches:
            continue
        try:
            text = (root / matches[0]).read_text(encoding="utf-8")
        except OSError:
            continue
        if sha256_text(text) != str(digest):
            return True
    return False


def _safe_members(archive: zipfile.ZipFile) -> List[str]:
    """拒绝越界成员（绝对路径或 ..）。"""
    safe: List[str] = []
    for name in archive.namelist():
        cleaned = str(name).replace("\\", "/")
        if cleaned.startswith("/") or ".." in cleaned.split("/"):
            continue
        safe.append(name)
    return safe


def _prepare_work_copy(package: Path, work_root: Path) -> Optional[Path]:
    """准备包工作副本：不改动原包，也不依赖原电脑项目路径。"""
    work = Path(work_root)
    if work.exists():
        shutil.rmtree(str(work), ignore_errors=True)
    try:
        if package.is_dir():
            shutil.copytree(str(package), str(work))
            return work
        if package.is_file() and zipfile.is_zipfile(str(package)):
            work.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(str(package)) as archive:
                archive.extractall(str(work), members=_safe_members(archive))
            return work
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _load_packaged_report(work: Path, destination: Path) -> Optional[ExportReport]:
    """读包内报告，并把相对路径解析到包工作副本内（不引用原机器路径）。"""
    index_path = Path(work) / REPORTS_DIR / "export-result.json"
    report = read_export_index(index_path)
    if report is None:
        return None
    base = Path(work)
    report.projectRoot = str(base / SNAPSHOT_DIR)
    report.snapshotWorkDir = str(base / SNAPSHOT_DIR)
    report.indexPath = str(index_path)
    if destination:
        report.destination = str(destination)
    for item in report.results:
        if item.path and not Path(item.path).is_absolute():
            item.path = str((base / item.path).resolve())
    if report.docxPath and not Path(report.docxPath).is_absolute():
        report.docxPath = str((base / report.docxPath).resolve())
    return report


def formalize_package(
    package,
    *,
    destination=None,
    word_available=None,
    refresh_adapter=None,
    registry_path=None,
    registry_writer=None,
    work_root=None,
    source_project_root=None,
    skip_word_refresh=None,
) -> FormalizeOutcome:
    """基于包内固定快照补刷新/正式化（换机或换目录均可）。

    ``word_available`` 显式给出本机 Word 可用性（默认按既有可用性检查探测）；
    ``refresh_adapter`` 为刷新适配器替身（测试用），签名
    ``(project_root, prior, destination, manifest) -> 刷新后 DOCX 路径``。
    ``registry_writer`` 可注入登记写入实现（用于失败路径验证）。
    """
    package_path = Path(package)
    outcome = FormalizeOutcome()
    manifest = read_delivery_package(package_path)
    if manifest is None:
        # 版本不符：允许阅读/导出可读产物，但不在此包内执行正式化。
        from doc_tool.application.delivery.package_version import version_fallback

        fallback = version_fallback(package_path)
        if fallback.readableOnly:
            outcome.status = "readable-only"
            outcome.message = fallback.reason
            outcome.warnings.append(
                "可打开并导出包内可读产物；正式化请回到生成该包的机器或升级应用后重试"
            )
            return outcome
        outcome.status = "invalid"
        outcome.message = "不是可读的交付包（schema 1）：{0}".format(package_path)
        return outcome
    origin = manifest.get("origin") or {}
    outcome.packageId = str(manifest.get("packageId") or "")
    outcome.inputDigest = str(manifest.get("inputDigest") or "")
    outcome.manifest = manifest

    check = verify_delivery_package(package_path)
    outcome.missing = list(check.missingOptional)
    if not check.ok:
        outcome.status = "invalid"
        outcome.message = "包校验未通过：{0}".format("；".join(check.problems[:3]))
        outcome.warnings.extend(check.problems[:5])
        return outcome
    if check.missingOptional:
        outcome.warnings.append(
            "包内可选内容缺失 {0} 项（仍可阅读/补刷新）".format(len(check.missingOptional))
        )

    if destination:
        dest = Path(destination)
    else:
        stem = package_path.stem if package_path.is_file() else package_path.name
        dest = package_path.parent / (stem + "-formalized")
    dest.mkdir(parents=True, exist_ok=True)
    outcome.destination = str(dest)

    work = Path(work_root) if work_root else (dest.parent / ".delivery-work" / (outcome.packageId or "package"))
    prepared = _prepare_work_copy(package_path, work)
    if prepared is None:
        outcome.status = "invalid"
        outcome.message = "无法准备包内工作副本：{0}".format(work)
        return outcome
    outcome.workRoot = str(prepared)
    outcome.projectRoot = str(prepared / SNAPSHOT_DIR)

    if source_project_root:
        outcome.sourceUpdated = _source_changed(manifest, Path(source_project_root))
        if outcome.sourceUpdated:
            outcome.warnings.append(
                "源项目在捕获后已更新：本次仍按包内捕获快照（{0}）处理，历史包不失效，"
                "也不改写当前项目修订记录".format(origin.get("capturedAt") or "未知时点")
            )

    registry = Path(registry_path) if registry_path else (dest / REGISTRY_NAME)
    key = _registration_key(outcome.packageId, outcome.inputDigest, dest)
    outcome.registryKey = key
    existing = _registry_lookup(registry, key)
    if existing is not None:
        outcome.ok = True
        outcome.status = "already-registered"
        outcome.registeredPath = str(existing.get("path") or "")
        outcome.message = "该包+输入+目标位置已登记过，直接打开已有结果（不重复建历史）"
        return outcome

    prior = _load_packaged_report(prepared, dest)
    if prior is None:
        outcome.status = "invalid"
        outcome.message = "包内报告不可读（reports/export-result.json），无法按原快照继续"
        return outcome
    pending = _packaged_pending_formats(prior, manifest)
    outcome.pendingFormats = pending
    if not pending:
        outcome.ok = True
        outcome.status = "nothing-pending"
        outcome.results = list(prior.results)
        outcome.readableDocx = report_docx_path(prior)
        outcome.message = "包内已无待处理阶段，可直接使用包内产物"
        return outcome

    if skip_word_refresh is True:
        available = False
    elif word_available is not None:
        available = bool(word_available)
    else:
        available = _probe_word()

    request = ExportRequest(
        project_root=outcome.projectRoot,
        formats=list(pending),
        scope=prior.scope,
        source_mode=prior.sourceMode,
        destination=str(dest),
        output_name=prior.outputName,
        strict=bool(prior.strict),
        refresh=available,
    )

    refreshed_report: Optional[ExportReport] = prior
    refreshed_docx = report_docx_path(prior)
    refresh_error = ""
    if available and refresh_adapter is not None:
        try:
            refreshed_docx = str(refresh_adapter(
                project_root=Path(outcome.projectRoot), prior=prior,
                destination=dest, manifest=manifest,
            ) or "")
        except Exception as exc:  # noqa: BLE001 - 刷新失败保持待刷新
            refresh_error = str(exc) or type(exc).__name__
    elif available:
        try:
            refreshed_report = run_project_export(
                request, prior=prior, only_formats=pending, skip_word_refresh=False,
                word_available=True,  # 本函数已探测过，避免二次探测超时被误判为无 Word
            )
            refreshed_docx = report_docx_path(refreshed_report)
        except Exception as exc:  # noqa: BLE001
            refresh_error = str(exc) or type(exc).__name__
    else:
        # 无 Word：仍补可离线完成的阶段，DOCX 保留为待刷新可读稿。
        try:
            refreshed_report = run_project_export(
                request, prior=prior, only_formats=pending, skip_word_refresh=True,
                word_available=False,
            )
            refreshed_docx = report_docx_path(refreshed_report)
        except Exception as exc:  # noqa: BLE001
            refresh_error = str(exc) or type(exc).__name__

    outcome.readableDocx = refreshed_docx or report_docx_path(prior)
    results = list(refreshed_report.results) if refreshed_report is not None else list(prior.results)
    outcome.results = results
    if refresh_error:
        outcome.warnings.append("刷新阶段未完成：{0}".format(refresh_error))

    formal = False
    if refreshed_docx:
        from doc_tool.domain.output_state import is_formal_success

        try:
            formal = bool(is_formal_success(refreshed_docx))
        except Exception:  # noqa: BLE001 - 状态判定失败按非正式处理
            formal = False
    if not formal:
        outcome.ok = bool(outcome.readableDocx)
        outcome.status = "waiting-refresh"
        outcome.message = (
            "未形成正式结果：可读 DOCX 已保留（待刷新），原包不删除，可在有 Word 的环境继续"
        )
        return outcome

    results = [item for item in results if item.format != FORMAT_DOCX]
    results.append(FormatResult(
        format=FORMAT_DOCX, status="ready", path=str(refreshed_docx),
        sha256=sha256_file(refreshed_docx), backend="word-com", formal=True,
    ))
    outcome.results = results

    entry: Dict[str, object] = {
        "key": key,
        "packageId": outcome.packageId,
        "inputDigest": outcome.inputDigest,
        "destination": str(dest),
        "path": str(refreshed_docx),
        "sha256": sha256_file(refreshed_docx),
        "documentVersion": str(origin.get("documentVersion") or ""),
        "variantId": str(origin.get("variantId") or ""),
        "capturedAt": str(origin.get("capturedAt") or ""),
        "registeredAt": utc_now_iso(),
    }
    try:
        _registry_write(registry, entry, writer=registry_writer)
    except Exception as exc:  # noqa: BLE001 - 登记失败保留安全副本，旧记录不变
        safe_path = str(refreshed_docx)
        try:
            safe_dir = dest / SAFE_COPY_DIR
            safe_dir.mkdir(parents=True, exist_ok=True)
            safe_path = str(safe_dir / Path(refreshed_docx).name)
            shutil.copy2(str(refreshed_docx), safe_path)
        except OSError:
            safe_path = str(refreshed_docx)
        outcome.ok = True
        outcome.status = "registration-failed"
        outcome.readableDocx = safe_path
        outcome.warnings.append(
            "登记写入失败：{0}；已保留新 DOCX 安全副本，原正式记录未改动".format(exc)
        )
        return outcome

    outcome.ok = True
    outcome.status = "registered"
    outcome.registeredPath = str(refreshed_docx)
    outcome.message = "已按包内固定快照补刷新并完成本地登记"
    return outcome


__all__ = [
    "PACKAGE_MANIFEST_NAME", "PACKAGE_README_NAME", "PACKAGE_KIND", "PACKAGE_SCHEMA_VERSION",
    "REGISTRY_NAME", "REGISTRY_SCHEMA_VERSION", "DOCX_DIR", "REPORTS_DIR", "SNAPSHOT_DIR",
    "SAFE_COPY_DIR", "PackageOutcome", "PackageCheck", "FormalizeOutcome",
    "build_delivery_package", "read_delivery_package", "verify_delivery_package",
    "formalize_package",
]
