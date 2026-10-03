# -*- coding: utf-8 -*-
"""规范包制作后端（V3.5 35-A～35-D）。

沿用既有 ``pack.yml`` schema 1 与加载/安装契约，不发行第二种包格式：

- 草稿（``pack-draft.json`` + 资源文件）与可安装产物分离，允许不完整草稿；
- 资源映射以现有消费者为准：``variables.yml``/``terms.yml``/``rules.yml``/``template.docx``/``skeleton/*.md``；
- 冻结时按实际内容生成文件摘要；同版本不同内容另存新目录，不覆盖既有产物；
- 样例在隔离目录用既有建项、检查与 CORE 出稿接口执行，结果绑定草稿摘要与 captureId。

本模块只读写用户选择的制作目录与样例子目录，不修改源项目、已固定安装包或未保存缓冲。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

from doc_tool.application.standard_pack import (
    PACK_SCHEMA_VERSION,
    sha256_file,
    validate_pack_dir,
)

#: 草稿状态文件名与格式版本。
DRAFT_NAME = "pack-draft.json"
DRAFT_SCHEMA_VERSION = 1
#: 冻结产物默认子目录。
FROZEN_DIR = "pack"
#: 导出/打包时必须排除的目录与文件名。
EXCLUDED_DIRS = {
    ".git", ".svn", "__pycache__", ".venv", ".vendor", "node_modules",
    "output", "logs", ".state", "history", ".history", "dist", "build",
}
EXCLUDED_NAMES = {".env", "credentials.json", "id_rsa", "id_rsa.pub", ".DS_Store"}
#: 资源映射说明：包内文件 ↔ 项目配置，界面与文档共用。
RESOURCE_MAPPING = {
    "pack.yml": "包身份与文件摘要（schemaVersion 1，packId/version/documentKind/files）",
    "template.docx": "来源项目的 template/template.docx；封面/页眉属于底模，正文变量不改变它们",
    "skeleton/*.md": "章节骨架：来源项目选定章节或顶层章节说明",
    "variables.yml": "项目 project.yml 的 variables（名称 → 默认值）",
    "terms.yml": "项目 quality/terms.json 的 terms 列表",
    "rules.yml": "项目 quality/rules.json 的 rules 列表",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def file_digest(path: Path) -> str:
    """内容摘要（文件不存在返回空串）。"""
    target = Path(path)
    return sha256_file(target) if target.is_file() else ""


@dataclass
class PackDraft:
    """本地制作草稿：元数据 + 资源声明，可保存/重开，不等于可安装包。"""

    root: Path
    pack_id: str = ""
    version: str = ""
    document_kind: str = ""
    description: str = ""
    template: str = "template.docx"
    skeleton: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    terms: List[object] = field(default_factory=list)
    rules: List[object] = field(default_factory=list)
    #: 未知声明式内容按原文保留，界面可高级查看，不执行任何脚本。
    extra: Dict[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    sample: Dict[str, object] = field(default_factory=dict)

    # --- 序列化 ---

    def to_dict(self) -> dict:
        return {
            "draftSchemaVersion": DRAFT_SCHEMA_VERSION,
            "packId": self.pack_id,
            "version": self.version,
            "documentKind": self.document_kind,
            "description": self.description,
            "template": self.template,
            "skeleton": list(self.skeleton),
            "variables": dict(self.variables),
            "terms": list(self.terms),
            "rules": list(self.rules),
            "extra": dict(self.extra),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "sample": dict(self.sample),
        }

    @classmethod
    def from_dict(cls, data: dict, root: Path) -> "PackDraft":
        extra = data.get("extra")
        return cls(
            root=Path(root),
            pack_id=str(data.get("packId", "") or ""),
            version=str(data.get("version", "") or ""),
            document_kind=str(data.get("documentKind", "") or ""),
            description=str(data.get("description", "") or ""),
            template=str(data.get("template", "template.docx") or ""),
            skeleton=[str(item) for item in (data.get("skeleton") or [])],
            variables={str(k): str(v) for k, v in (data.get("variables") or {}).items()},
            terms=list(data.get("terms") or []),
            rules=list(data.get("rules") or []),
            extra=dict(extra) if isinstance(extra, dict) else {},
            created_at=str(data.get("createdAt", "") or _now()),
            updated_at=str(data.get("updatedAt", "") or _now()),
            sample=dict(data.get("sample") or {}),
        )

    # --- 持久化 ---

    @property
    def file(self) -> Path:
        return Path(self.root) / DRAFT_NAME

    def resource_files(self) -> List[str]:
        """草稿声明的资源相对路径（按包内约定）。"""
        names: List[str] = []
        if self.template and (Path(self.root) / self.template).is_file():
            names.append(self.template)
        for item in self.skeleton:
            if (Path(self.root) / item).is_file():
                names.append(item)
        for name in ("variables.yml", "terms.yml", "rules.yml"):
            if (Path(self.root) / name).is_file():
                names.append(name)
        for name in self.extra.get("additionalResources", []) or []:
            if isinstance(name, str) and name not in names and (Path(self.root) / name).is_file():
                names.append(name)
        return names

    def save(self) -> Path:
        self.updated_at = _now()
        target = self.file
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8",
        )
        try:
            tmp.replace(target)
        except OSError:
            # 部分企业 PC 的 DLP/文件过滤驱动会拒绝同目录原子重命名。
            shutil.move(str(tmp), str(target))
        return target

    @classmethod
    def load(cls, root) -> "PackDraft":
        base = Path(root)
        target = base / DRAFT_NAME
        if not target.is_file():
            return cls(root=base)
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("草稿文件格式不正确：根节点应为映射。")
        return cls.from_dict(data, base)


def draft_digest(draft: PackDraft) -> str:
    """草稿摘要：元数据 + 资源文件内容摘要（用于样例过期判定）。"""
    payload = draft.to_dict()
    payload.pop("sample", None)
    payload.pop("updatedAt", None)
    hashes = {
        name: file_digest(Path(draft.root) / name) for name in draft.resource_files()
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True) + json.dumps(
        hashes, ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_draft_resources(draft: PackDraft) -> List[Path]:
    """把草稿的变量/术语/规则写成包消费者期望的 YAML。"""
    written: List[Path] = []
    base = Path(draft.root)
    base.mkdir(parents=True, exist_ok=True)
    if draft.variables or (base / "variables.yml").is_file():
        target = base / "variables.yml"
        target.write_text(
            yaml.safe_dump(dict(draft.variables), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(target)
    if draft.terms or (base / "terms.yml").is_file():
        target = base / "terms.yml"
        target.write_text(
            yaml.safe_dump({"terms": list(draft.terms)}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(target)
    if draft.rules or (base / "rules.yml").is_file():
        target = base / "rules.yml"
        target.write_text(
            yaml.safe_dump({"rules": list(draft.rules)}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(target)
    return written


def read_project_resources(project_root) -> dict:
    """读取来源项目可映射到包资源的真实配置（变量/术语/规则）。"""
    from doc_tool.application.settings import load_settings

    root = Path(project_root)
    resources: Dict[str, object] = {"variables": {}, "terms": [], "rules": []}
    try:
        model = load_settings(root)
    except Exception:  # noqa: BLE001 - 坏配置只影响对应资源，不阻断草稿
        return resources
    variables = {}
    for item in model.sections.get("变量", []):
        variables[str(item.key)] = str(item.value)
    resources["variables"] = variables
    terms_field = model.field("术语", "terms")
    if terms_field is not None and isinstance(terms_field.value, list):
        resources["terms"] = list(terms_field.value)
    rules_field = model.field("规则", "rules")
    if rules_field is not None and isinstance(rules_field.value, list):
        resources["rules"] = list(rules_field.value)
    return resources


def create_draft(directory, *, pack_id: str = "", version: str = "",
                 document_kind: str = "", description: str = "") -> PackDraft:
    """在指定目录创建空草稿（不覆盖已有草稿，除非目录为空）。"""
    draft = PackDraft(
        root=Path(directory), pack_id=pack_id, version=version,
        document_kind=document_kind, description=description,
    )
    draft.root.mkdir(parents=True, exist_ok=True)
    return draft


def draft_from_pack(source, directory) -> PackDraft:
    """从已有规范包复制成草稿（不修改源包/已安装固定版本）。"""
    validation = validate_pack_dir(source)
    if not validation.ok or validation.pack is None:
        raise ValueError("来源规范包不可用：{0}".format("；".join(validation.errors) or "未知原因"))
    pack = validation.pack
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    draft = PackDraft(
        root=target, pack_id=pack.pack_id, version=pack.version,
        document_kind=pack.document_kind, description=pack.description,
    )
    for name in pack.entries:
        source_file = Path(pack.root) / name
        if not source_file.is_file():
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)
    draft.template = "template.docx" if (target / "template.docx").is_file() else ""
    draft.skeleton = sorted(
        path.relative_to(target).as_posix() for path in target.glob("skeleton/*.md")
    )
    resources = _read_draft_resources(target)
    draft.variables = resources["variables"]
    draft.terms = resources["terms"]
    draft.rules = resources["rules"]
    original_metadata = yaml.safe_load((Path(pack.root) / "pack.yml").read_text(encoding="utf-8"))
    known = {"schemaVersion", "packId", "version", "documentKind", "description", "files"}
    draft.extra["packMetadata"] = {key: value for key, value in original_metadata.items() if key not in known}
    mapped = set(draft.resource_files())
    draft.extra["additionalResources"] = [name for name in pack.entries if name not in mapped]
    draft.save()
    return draft


def _read_draft_resources(base: Path) -> dict:
    result: Dict[str, object] = {"variables": {}, "terms": [], "rules": []}
    variables = base / "variables.yml"
    if variables.is_file():
        try:
            data = yaml.safe_load(variables.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                result["variables"] = {str(k): str(v) for k, v in data.items()}
        except (yaml.YAMLError, UnicodeError, OSError):
            result["variables"] = {}
    terms = base / "terms.yml"
    if terms.is_file():
        try:
            data = yaml.safe_load(terms.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and isinstance(data.get("terms"), list):
                result["terms"] = list(data["terms"])
        except (yaml.YAMLError, UnicodeError, OSError):
            result["terms"] = []
    rules = base / "rules.yml"
    if rules.is_file():
        try:
            data = yaml.safe_load(rules.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and isinstance(data.get("rules"), list):
                result["rules"] = list(data["rules"])
        except (yaml.YAMLError, UnicodeError, OSError):
            result["rules"] = []
    return result


def draft_from_project(project_root, directory, *, chapters: Optional[Sequence[str]] = None,
                       pack_id: str = "", version: str = "", document_kind: str = "") -> PackDraft:
    """从用户选定项目资源复制草稿：底模、章节骨架、变量/术语/规则。"""
    from doc_tool.domain.manifest import ProjectManifest

    source = Path(project_root)
    manifest = ProjectManifest.load(source)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    draft = PackDraft(
        root=target,
        pack_id=pack_id or manifest.documentType or "local-standard",
        version=version,
        document_kind=document_kind or manifest.documentKind or "",
        description="由项目「{0}」制作的本地规范包草稿".format(manifest.documentName or source.name),
    )
    template = source / "template" / "template.docx"
    if template.is_file():
        destination = target / "template.docx"
        shutil.copy2(template, destination)
        draft.template = "template.docx"
    else:
        draft.template = ""
        draft.extra["templateMissing"] = "来源项目没有底模文件，草稿可先保存；底模可选。"
    content_root = source / manifest.relative_content_root()
    selected = list(chapters or [])
    if not selected and content_root.is_dir():
        selected = sorted(
            path.relative_to(content_root).as_posix()
            for path in content_root.glob("*/_index.md")
        )
    for rel_path in selected:
        origin = content_root / rel_path
        if not origin.is_file():
            continue
        name = "skeleton/{0}".format(Path(rel_path).parent.name or Path(rel_path).stem)
        destination = target / (name + ".md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(origin.read_text(encoding="utf-8"), encoding="utf-8")
        draft.skeleton.append(destination.relative_to(target).as_posix())
    resources = read_project_resources(source)
    draft.variables = dict(resources["variables"])
    draft.terms = list(resources["terms"])
    draft.rules = list(resources["rules"])
    write_draft_resources(draft)
    draft.save()
    return draft


def file_listing(draft: PackDraft, *, frozen_dir: Optional[Path] = None) -> dict:
    """导出前的文件清单：声明资源 + 被排除的敏感/无关目录说明。"""
    base = Path(frozen_dir) if frozen_dir is not None else Path(draft.root)
    included: List[str] = []
    if frozen_dir is not None and (base / "pack.yml").is_file():
        included.append("pack.yml")
    for name in draft.resource_files():
        if (base / name).is_file() and name not in included:
            included.append(name)
    excluded: List[str] = []
    if Path(draft.root).is_dir():
        for item in Path(draft.root).iterdir():
            if item.name in EXCLUDED_DIRS or item.name in EXCLUDED_NAMES:
                excluded.append(item.name + ("/" if item.is_dir() else ""))
    return {"included": sorted(included), "excluded": sorted(excluded)}


def validate_draft(draft: PackDraft) -> dict:
    """草稿当前是否具备导出条件；缺身份只阻止“可安装产物”，不阻止保存草稿。"""
    errors: List[str] = []
    warnings: List[str] = []
    if not str(draft.pack_id or "").strip():
        errors.append("缺少 packId：请填写包标识后导出（草稿仍可保存）")
    if not str(draft.version or "").strip():
        errors.append("缺少 version：请填写版本号后导出（草稿仍可保存）")
    if not draft.resource_files():
        warnings.append("草稿还没有任何资源文件：至少选择底模、骨架或变量/术语/规则之一")
    if draft.template and not (Path(draft.root) / draft.template).is_file():
        warnings.append("声明的底模不存在：导出时会跳过并提示")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def freeze_draft(draft: PackDraft, *, destination=None, version: str = "") -> dict:
    """按 schema 1 生成 ``pack.yml`` 与实际文件摘要；不覆盖已有产物。"""
    resolved_version = str(version or draft.version or "").strip()
    resolved_id = str(draft.pack_id or "").strip()
    if not resolved_id or not resolved_version:
        return {
            "ok": False, "reused": False, "packDir": "", "errors": validate_draft(draft)["errors"],
            "warnings": [], "message": "草稿缺少包身份，未生成可安装包；草稿已保留。",
        }
    write_draft_resources(draft)
    base = Path(destination) if destination else Path(draft.root) / FROZEN_DIR
    target = base
    if (target / "pack.yml").is_file():
        existing = validate_pack_dir(target)
        same_identity = bool(
            existing.pack is not None
            and existing.pack.pack_id == resolved_id
            and existing.pack.version == resolved_version
        )
        if same_identity:
            current = _current_hashes(draft)
            recorded = yaml.safe_load((target / "pack.yml").read_text(encoding="utf-8"))
            if (existing.ok and current == dict(existing.pack.entries)
                    and existing.pack.document_kind == draft.document_kind
                    and existing.pack.description == draft.description
                    and all(file_digest(target / name) == digest for name, digest in existing.pack.entries.items())
                    and recorded == _pack_payload(draft, resolved_id, resolved_version, current)):
                return {
                    "ok": True, "reused": True, "packDir": str(target), "errors": [],
                    "warnings": list(existing.warnings),
                    "message": "同版本同摘要：复用已冻结产物，未重复写入。",
                }
        stamp = time.strftime("%Y%m%d%H%M%S")
        target = base.parent / "{0}-{1}-{2}-{3}".format(base.name, resolved_version, stamp, uuid.uuid4().hex[:12])
        note = "同版本内容不同：已另存新目录 {0}，未覆盖既有产物；当前项目固定包不变。".format(target.name)
    else:
        note = ""
    target.mkdir(parents=True, exist_ok=True)
    entries: Dict[str, str] = {}
    warnings: List[str] = []
    for name in draft.resource_files():
        source = Path(draft.root) / name
        if not source.is_file():
            warnings.append("跳过的缺失资源：{0}".format(name))
            continue
        destination_file = target / name
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination_file)
        entries[name] = sha256_file(destination_file)
    payload = _pack_payload(draft, resolved_id, resolved_version, entries)
    (target / "pack.yml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    validation = validate_pack_dir(target)
    return {
        "ok": validation.ok, "reused": False, "packDir": str(target),
        "errors": list(validation.errors), "warnings": list(validation.warnings) + warnings,
        "files": sorted(entries),
        "message": note or ("已冻结规范包：{0}".format(target)),
    }


def _pack_payload(draft: PackDraft, resolved_id: str, resolved_version: str, entries: dict) -> dict:
    """未知声明保留，正式身份与摘要始终由本次冻结覆盖。"""
    metadata = draft.extra.get("packMetadata") or {}
    payload = dict(metadata) if isinstance(metadata, dict) else {}
    payload.update({
        "schemaVersion": PACK_SCHEMA_VERSION,
        "packId": resolved_id,
        "version": resolved_version,
        "documentKind": draft.document_kind,
        "description": draft.description,
        "files": entries,
    })
    return payload


def _current_hashes(draft: PackDraft) -> Dict[str, str]:
    return {name: file_digest(Path(draft.root) / name) for name in draft.resource_files()}


def export_zip(frozen_dir, destination) -> dict:
    """把已冻结包导出为 ZIP：只含声明资源，排除 Git/凭证/缓存/历史/产物。"""
    base = Path(frozen_dir)
    destination_file = Path(destination)
    validation = validate_pack_dir(base)
    if not validation.ok or validation.pack is None:
        return {
            "ok": False, "path": "", "errors": list(validation.errors), "warnings": [],
            "files": [], "message": "包结构不可消费，未生成 ZIP（草稿与文件已保留）。",
        }
    if destination_file.is_dir():
        destination_file = destination_file / "{0}-{1}.zip".format(
            validation.pack.pack_id or "standard-pack", validation.pack.version or "0",
        )
    if destination_file.exists():
        destination_file = destination_file.with_name(
            "{0}-{1}{2}".format(destination_file.stem, uuid.uuid4().hex[:12], destination_file.suffix)
        )
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    skipped: List[str] = []
    with zipfile.ZipFile(destination_file, "w", zipfile.ZIP_DEFLATED) as package:
        written.append("pack.yml")
        exported_entries = {}
        for name in validation.pack.entries:
            source = base / name
            if not source.is_file():
                skipped.append("缺失：{0}".format(name))
                continue
            parts = Path(name).parts
            if any(part in EXCLUDED_DIRS for part in parts) or Path(name).name in EXCLUDED_NAMES:
                skipped.append("排除：{0}".format(name))
                continue
            package.write(source, name)
            exported_entries[name] = validation.pack.entries[name]
            written.append(name)
        # 排除资源后同步声明；否则 ZIP 虽导出成功，原消费者却因缺声明文件拒绝。
        manifest = yaml.safe_load((base / "pack.yml").read_text(encoding="utf-8"))
        manifest["files"] = exported_entries
        package.writestr("pack.yml", yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    return {
        "ok": True, "path": str(destination_file), "errors": [], "warnings": list(validation.warnings),
        "files": written, "skipped": skipped,
        "message": "已导出规范包 ZIP：{0}（{1} 个文件）".format(destination_file, len(written)),
    }


def run_sample(draft: PackDraft, *, sample_root, document_name: str = "规范包样例",
               skip_word_refresh: bool = True, cancel_token=None) -> dict:
    """在隔离目录用既有建项、检查与 CORE 出稿接口试用草稿资源。"""
    from doc_tool.application.check import run_check
    from doc_tool.application.intake_contract import (
        FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
    )
    from doc_tool.application.project_export import run_project_export
    from doc_tool.application.project_from_pack import create_project_from_pack

    if cancel_token is not None:
        cancel_token.check_cancel()
    # 每轮独立建项/出稿；旧轮的源码、捕获、成果都留在原目录供重试与核对。
    run_id = uuid.uuid4().hex
    base = Path(sample_root) / ("round-" + run_id)
    base.mkdir(parents=True, exist_ok=False)
    pack_dir = base / "pack-preview"
    frozen = freeze_draft(draft, destination=pack_dir)
    result: Dict[str, object] = {
        "draftDigest": draft_digest(draft),
        "sampleRunId": run_id,
        "captureId": "",
        "packDir": frozen.get("packDir", ""),
        "structureOk": bool(frozen.get("ok")),
        "structureErrors": list(frozen.get("errors") or []),
        "structureWarnings": list(frozen.get("warnings") or []),
        "projectRoot": "",
        "ruleIssues": 0,
        "ruleStatus": "",
        "readable": "",
        "htmlPath": "",
        "wordStatus": "",
        "wordPath": "",
        "formal": False,
        "unverified": ["真实 Word 视觉与人工版面验收"],
        "message": "",
    }
    if not frozen.get("ok"):
        result["message"] = "包结构不可消费：草稿与文件已保留，请修正后重试。"
        draft.sample = dict(result)
        draft.save()
        return result
    project_root = base / "sample-project"
    if cancel_token is not None:
        cancel_token.check_cancel()
    created = create_project_from_pack(
        frozen["packDir"], project_root, document_name=document_name,
        document_type=draft.document_kind or "general",
    )
    result["projectRoot"] = str(created.project_root or "")
    if not created.ok:
        result["structureOk"] = False
        result["structureErrors"] = list(created.errors)
        result["message"] = "样例建项失败：草稿与包保留，可修正后重试。"
        draft.sample = dict(result)
        draft.save()
        return result
    if cancel_token is not None:
        cancel_token.check_cancel()
    check = run_check(created.project_root)
    result["ruleIssues"] = len(check.issues)
    result["ruleStatus"] = check.status
    report = run_project_export(
        ExportRequest(
            project_root=str(created.project_root), formats=[FORMAT_HTML, FORMAT_DOCX],
            source_mode=SOURCE_MODE_SAVED, destination=str(base / "output"),
        ),
        skip_word_refresh=skip_word_refresh,
        cancel_token=cancel_token,
    )
    result["captureId"] = report.captureId
    result["roundId"] = report.roundId
    from doc_tool.application.project_export import INDEX_NAME
    result["reportPath"] = str(Path(report.destination) / INDEX_NAME)
    html_result = report.result_for(FORMAT_HTML)
    word_result = report.result_for(FORMAT_DOCX)
    if html_result is not None and html_result.usable:
        result["readable"] = html_result.path
        result["htmlPath"] = html_result.path
    if word_result is not None:
        result["wordStatus"] = word_result.status
        result["wordPath"] = word_result.path
        result["formal"] = bool(getattr(word_result, "formal", False))
    if skip_word_refresh:
        result["unverified"] = ["Word 刷新与视觉验收（本轮为诊断构建）"]
    result["message"] = "样例已生成：结构合法；可读成果 {0}；Word 状态 {1}。".format(
        "有" if result["readable"] else "无", result["wordStatus"] or "未执行",
    )
    draft.sample = dict(result)
    draft.save()
    return result


def retry_sample_word(draft: PackDraft, *, skip_word_refresh: bool = False, cancel_token=None) -> dict:
    """补原样例 Word：复用原轮捕获，不读取最新草稿或重新建项。"""
    from doc_tool.application.intake_contract import FORMAT_DOCX
    from doc_tool.application.project_export import read_export_index, retry_export_formats

    result = dict(draft.sample)
    path = str(result.get("reportPath") or "")
    report = read_export_index(path) if path else None
    if (report is None or not result.get("captureId")
            or report.captureId != result["captureId"]
            or (result.get("roundId") and report.roundId != result["roundId"])):
        result["message"] = "原样例记录缺失或身份不匹配，无法补原轮；可生成最新样例，旧成果保留。"
        return result
    retried = retry_export_formats(
        report, [FORMAT_DOCX], skip_word_refresh=skip_word_refresh, cancel_token=cancel_token,
    )
    word = retried.result_for(FORMAT_DOCX)
    if word is not None:
        result["wordStatus"] = word.status
        result["wordPath"] = word.path
        result["formal"] = bool(word.formal)
    result["message"] = "已补原样例 Word：{0}；其他成果及原捕获保持。".format(result.get("wordStatus", "未执行"))
    if result.get("formal"):
        result["unverified"] = ["真实 Word 视觉与人工版面验收"]
    draft.sample = result
    draft.save()
    return result


def sample_is_stale(draft: PackDraft) -> bool:
    """草稿在样例之后变化时，旧样例证据标为过期（仍可打开）。"""
    if not draft.sample:
        return False
    recorded = str(draft.sample.get("draftDigest", "") or "")
    return bool(recorded) and recorded != draft_digest(draft)


def list_pack_drafts(root) -> List[Path]:
    """列出制作目录下已有的草稿（便于“管理/重开”）。"""
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(path.parent for path in base.glob("*/{0}".format(DRAFT_NAME)))
