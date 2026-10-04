# -*- coding: utf-8 -*-
"""声明式文档规范包（V2.8 28-C / 3.1、3.2、3.3）。

规范包是**声明式文件集合**，不执行任何脚本：

    pack.yml          schemaVersion / packId / version / documentKind / 文件清单与 hash
    template.docx     底模（可选，缺失回退通用底模）
    skeleton/*.md     章节骨架（可选，缺失回退内置骨架）
    rules.yml         检查规则（可选）
    terms.yml         术语表（可选）
    variables.yml     变量声明与默认值（可选）

安全边界：不接受 Python/JS 插件；ZIP 安全提取（拒绝路径穿越/绝对路径/符号链接/超限）；
hash 不匹配只报告“包已变化”，默认仍用合法可解析内容，严格策略才要求完全一致。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml

from doc_tool.domain.errors import ValidationError

#: 包格式版本。
PACK_SCHEMA_VERSION = 1
#: 容许的包内文件（声明式，无可执行代码）。
ALLOWED_ENTRY_SUFFIXES = (".yml", ".yaml", ".docx", ".md", ".txt", ".csv", ".json", ".png", ".jpg", ".jpeg")
#: 绝对禁止的扩展名（插件/可执行）。
FORBIDDEN_ENTRY_SUFFIXES = (".py", ".pyc", ".js", ".mjs", ".cjs", ".dll", ".exe", ".bat", ".cmd", ".ps1", ".sh", ".so", ".pyd")
#: 解压集合限制。
MAX_ENTRY_COUNT = 512
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_SINGLE_BYTES = 64 * 1024 * 1024
#: 项目内固定版本目录。
STANDARDS_DIR = "standards"


@dataclass
class PackManifest:
    """``pack.yml`` 解析结果。"""

    schema_version: int
    pack_id: str
    version: str
    document_kind: str = ""
    entries: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    root: Optional[Path] = None

    def entry(self, name: str) -> Optional[Path]:
        if self.root is None:
            return None
        target = self.root / name
        return target if target.is_file() else None


@dataclass
class PackValidation:
    """验证结果（含非致命性提醒）。"""

    pack: Optional[PackManifest] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.pack is not None and not self.errors


def validate_pack_dir(root: Union[str, Path]) -> PackValidation:
    """验证规范包目录（不写盘）。"""
    base = Path(root)
    result = PackValidation()
    if not base.is_dir():
        result.errors.append("规范包目录不存在：{0}".format(base))
        return result
    pack_file = base / "pack.yml"
    if not pack_file.is_file():
        result.errors.append("规范包缺少 pack.yml。")
        return result
    try:
        data = yaml.safe_load(pack_file.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError, OSError) as exc:
        result.errors.append("pack.yml 解析失败：{0}".format(exc))
        return result
    if not isinstance(data, dict):
        result.errors.append("pack.yml 根节点应为映射。")
        return result
    try:
        schema_version = int(data.get("schemaVersion", 0))
    except (TypeError, ValueError):
        result.errors.append("pack.yml 的 schemaVersion 必须是整数。")
        return result
    if schema_version != PACK_SCHEMA_VERSION:
        result.errors.append(
            "不支持的规范包格式版本：{0}".format(schema_version)
        )
        return result
    pack_id = str(data.get("packId", "") or "").strip()
    version = str(data.get("version", "") or "").strip()
    if not pack_id:
        result.errors.append("pack.yml 缺少 packId。")
    if not version:
        result.errors.append("pack.yml 缺少 version。")
    if result.errors:
        return result

    entries: Dict[str, str] = {}
    raw_entries = data.get("files") or {}
    if raw_entries and not isinstance(raw_entries, dict):
        result.errors.append("pack.yml 的 files 应为「路径 -> hash」映射。")
        return result
    declared_names: List[str] = []
    for name, digest in (raw_entries or {}).items():
        rel = _safe_relative(str(name))
        if rel is None:
            result.errors.append("包内路径越界或非法：{0}".format(name))
            continue
        if rel.lower().endswith(FORBIDDEN_ENTRY_SUFFIXES):
            result.errors.append("规范包不允许可执行或插件文件：{0}".format(rel))
            continue
        declared_names.append(rel)
        entries[rel] = str(digest or "")

    for name in declared_names:
        target = base / name
        if not target.is_file():
            result.errors.append("声明的包内文件不存在：{0}".format(name))
            continue
        expected = entries.get(name, "")
        if expected:
            actual = sha256_file(target)
            if actual != expected:
                result.warnings.append(
                    "规范包已发生变化（hash 不匹配）：{0}".format(name)
                )

    pack = PackManifest(
        schema_version=schema_version,
        pack_id=pack_id,
        version=version,
        document_kind=str(data.get("documentKind", "") or "").strip(),
        entries=entries,
        description=str(data.get("description", "") or ""),
        root=base,
    )
    result.pack = pack
    return result


def extract_pack_zip(zip_path: Union[str, Path], destination: Union[str, Path]) -> PackValidation:
    """安全提取规范包 ZIP：拒绝路径穿越、绝对路径、符号链接与超限内容。"""
    result = PackValidation()
    archive = Path(zip_path)
    target_root = Path(destination)
    if not archive.is_file():
        result.errors.append("ZIP 不存在：{0}".format(archive))
        return result
    try:
        with zipfile.ZipFile(archive) as package:
            infos = package.infolist()
            if len(infos) > MAX_ENTRY_COUNT:
                result.errors.append("包内文件数超限：{0}".format(len(infos)))
                return result
            total = 0
            planned: List[Tuple[zipfile.ZipInfo, Path]] = []
            for info in infos:
                name = info.filename.replace("\\\\", "/")
                if name.endswith("/"):
                    continue
                relative = _safe_relative(name)
                if relative is None:
                    result.errors.append("ZIP 包含越界或绝对路径：{0}".format(name))
                    return result
                if relative.lower().endswith(FORBIDDEN_ENTRY_SUFFIXES):
                    result.errors.append("ZIP 包含不允许的可执行文件：{0}".format(relative))
                    return result
                if info.file_size > MAX_SINGLE_BYTES:
                    result.errors.append("单文件过大：{0}".format(relative))
                    return result
                total += int(info.file_size)
                if total > MAX_TOTAL_BYTES:
                    result.errors.append("ZIP 解压总量超限。")
                    return result
                # 符号链接：ZIP 规范用外部属性高位标记，仅在非 Windows 上生效，一律拒绝。
                mode = (info.external_attr >> 16) & 0xF000
                if mode == 0xA000:
                    result.errors.append("ZIP 包含符号链接：{0}".format(relative))
                    return result
                planned.append((info, target_root / relative))
            target_root.mkdir(parents=True, exist_ok=True)
            for info, destination_path in planned:
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, open(destination_path, "wb") as sink:
                    shutil.copyfileobj(source, sink)
    except zipfile.BadZipFile as exc:
        result.errors.append("ZIP 文件损坏：{0}".format(exc))
        return result
    inner = validate_pack_dir(target_root)
    result.errors.extend(inner.errors)
    result.warnings.extend(inner.warnings)
    result.pack = inner.pack
    return result


def install_pack(
    source: Union[str, Path],
    project_root: Union[str, Path],
    *,
    pack_id: str = "",
    version: str = "",
) -> Tuple[Optional[Path], PackValidation]:
    """把规范包固定到项目内 ``standards/<packId>/<version>/``。

    写入前先验证；目标已存在时**不覆盖**，直接复用已有版本（保持可复现）。
    """
    validation = validate_pack_dir(source)
    result = PackValidation(pack=validation.pack, errors=list(validation.errors), warnings=list(validation.warnings))
    if not validation.ok or validation.pack is None:
        return None, result
    pack = validation.pack
    resolved_id = pack_id or pack.pack_id
    resolved_version = version or pack.version
    target = Path(project_root) / STANDARDS_DIR / resolved_id / resolved_version
    if target.is_dir():
        result.warnings.append("该版本已在项目内固定，未重复写入。")
        return target, result
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / (target.name + ".staging")
    try:
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging)
        if target.exists():
            shutil.rmtree(target)
        try:
            os.replace(str(staging), str(target))
        except OSError:
            # 部分企业 PC 的 DLP/文件过滤驱动拒绝目录级原子重命名；
            # 回退为移动（先尝试重命名，失败则复制后删除暂存目录）。
            shutil.move(str(staging), str(target))
    except OSError as exc:
        result.errors.append("规范包固定失败：{0}".format(exc))
        shutil.rmtree(staging, ignore_errors=True)
        return None, result
    result.pack = PackManifest(
        schema_version=pack.schema_version,
        pack_id=resolved_id,
        version=resolved_version,
        document_kind=pack.document_kind,
        entries=dict(pack.entries),
        description=pack.description,
        root=target,
    )
    return target, result


def load_project_pack(project_root: Union[str, Path], pack_ref: Dict[str, str]) -> Tuple[Optional[PackManifest], List[str]]:
    """按清单的 ``standardPack`` 引用加载项目内已固定的规范包。

    缺失或 hash 不匹配时返回可读说明而不抛异常，由调用方决定回退策略。
    """
    warnings: List[str] = []
    pack_id = str((pack_ref or {}).get("id", "") or "").strip()
    version = str((pack_ref or {}).get("version", "") or "").strip()
    if not pack_id or not version:
        return None, ["清单未声明完整的规范包引用（缺 id 或 version）。"]
    root = Path(project_root) / STANDARDS_DIR / pack_id / version
    validation = validate_pack_dir(root)
    if not validation.ok or validation.pack is None:
        warnings.extend(validation.errors or ["规范包不可用：{0}".format(pack_id)])
        warnings.append("已回退内置默认策略继续。")
        return None, warnings
    expected = str((pack_ref or {}).get("hash", "") or "")
    if expected and expected != pack_fingerprint(validation.pack):
        warnings.append("规范包已发生变化（hash 不匹配），默认使用合法可解析内容。")
    warnings.extend(validation.warnings)
    return validation.pack, warnings


def pack_fingerprint(pack: PackManifest) -> str:
    """包指纹：按声明清单与文件 hash 计算（不依赖绝对路径）。"""
    digest = hashlib.sha256()
    digest.update(str(pack.pack_id).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(str(pack.version).encode("utf-8"))
    for name in sorted(pack.entries):
        digest.update(b"\x00")
        digest.update(name.encode("utf-8"))
        digest.update(b"=")
        digest.update(str(pack.entries[name]).encode("utf-8"))
    return digest.hexdigest()


def pack_resources(pack: PackManifest) -> Dict[str, Optional[Path]]:
    """返回各可选资源的实际路径（缺失为 None，由调用方回退）。"""
    return {
        "template": pack.entry("template.docx"),
        "rules": pack.entry("rules.yml"),
        "terms": pack.entry("terms.yml"),
        "variables": pack.entry("variables.yml"),
    }


def pack_skeleton_files(pack: PackManifest) -> List[Path]:
    """骨架文件（``skeleton/`` 下按名称排序）。"""
    if pack.root is None:
        return []
    skeleton = pack.root / "skeleton"
    if not skeleton.is_dir():
        return []
    return sorted(
        item for item in skeleton.rglob("*.md") if item.is_file()
    )


def diff_packs(current: Optional[PackManifest], candidate: PackManifest) -> List[str]:
    """升级差异说明（底模、骨架与声明清单）。"""
    lines: List[str] = []
    if current is None:
        lines.append("项目当前无规范包，将新增 {0} {1}。".format(candidate.pack_id, candidate.version))
        return lines
    if current.version == candidate.version:
        lines.append("版本相同：{0}。".format(candidate.version))
    else:
        lines.append("版本变化：{0} → {1}。".format(current.version, candidate.version))
    current_files = set(current.entries)
    candidate_files = set(candidate.entries)
    for name in sorted(candidate_files - current_files):
        lines.append("新增文件：{0}".format(name))
    for name in sorted(current_files - candidate_files):
        lines.append("移除文件：{0}".format(name))
    for name in sorted(current_files & candidate_files):
        if current.entries.get(name) != candidate.entries.get(name):
            lines.append("内容变化：{0}".format(name))
    current_skeleton = {item.name for item in pack_skeleton_files(current)}
    candidate_skeleton = {item.name for item in pack_skeleton_files(candidate)}
    for name in sorted(candidate_skeleton - current_skeleton):
        lines.append("新增章节：{0}".format(name))
    for name in sorted(current_skeleton - candidate_skeleton):
        lines.append("移除章节：{0}".format(name))
    lines.append("已编辑正文不会被自动覆盖；是否合并由用户选择。")
    return lines


def backup_pack(project_root: Union[str, Path], pack_ref: Dict[str, str]) -> Optional[Path]:
    """升级前备份当前固定版本（失败时可回退）。"""
    pack_id = str((pack_ref or {}).get("id", "") or "")
    version = str((pack_ref or {}).get("version", "") or "")
    if not pack_id or not version:
        return None
    source = Path(project_root) / STANDARDS_DIR / pack_id / version
    if not source.is_dir():
        return None
    target = Path(project_root) / STANDARDS_DIR / ".backup" / "{0}-{1}".format(pack_id, version)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    return target


def sha256_file(path: Union[str, Path]) -> str:
    """包内文件摘要：按归一化换行（CRLF 转 LF）后的字节计算。

    同一文本文件在不同检出配置下可能是 CRLF（开发机）或 LF（全新克隆）；
    若按原始字节记摘要，两者必然不一致，校验会整体误报「包已变化」。
    归一化后摘要与检出配置无关；逐块读取并保留跨块的尾部 CR。
    """
    digest = hashlib.sha256()
    carry = b""
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            chunk = carry + chunk
            if chunk.endswith(b"\r"):
                carry, chunk = chunk[-1:], chunk[:-1]
            else:
                carry = b""
            digest.update(chunk.replace(b"\r\n", b"\n"))
    if carry:
        digest.update(carry)
    return digest.hexdigest()


def _safe_relative(name: str) -> Optional[str]:
    """把包内路径归一为安全相对路径；越界返回 None。"""
    text = str(name or "").replace("\\\\", "/").strip()
    if not text or text.startswith("/") or text.startswith("~"):
        return None
    if ":" in text.split("/")[0]:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        return None
    if not parts:
        return None
    return "/".join(parts)


def bundled_standards_root() -> Optional[Path]:
    """返回随应用发布的通用规范包根目录（找不到返回 None）。

    - 源码态：仓库根 ``standards/``；
    - 冻结态：``doc_tool/resources/standards``（由打包脚本随包）。

    两者都不存在时返回 None，由调用方（界面）提示用户手动选择包目录，
    而不是静默失败。
    """
    from doc_tool.resources import resource_path

    candidates = [
        Path(resource_path("standards")),
        Path(__file__).resolve().parents[2] / "standards",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def list_bundled_packs() -> List[str]:
    """列出随应用发布的包标识（按名称排序）。"""
    root = bundled_standards_root()
    if root is None:
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "pack.yml").is_file()
    )
