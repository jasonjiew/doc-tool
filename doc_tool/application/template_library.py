# -*- coding: utf-8 -*-
"""本地企业模板目录（V4.1 41-A）。

把已有的规范包、DOCX 底模与导出预设（recipe）收成一份**可重建的本地引用目录**，
用真实来源与内容摘要区分同名条目，并按用途分开：

- ``skeleton`` 骨架建项：``standards/<id>/``（schema 1 规范包，``pack.yml``）；
- ``fill``     模板填充：``templates/*.docx``（可配 recipe）；
- ``export``   项目出稿：规范包自带的 ``template.docx`` 或独立底模。

目录只保存**引用**（真实路径 + 摘要 + 版本），不是第二份规范数据库：

- 同名条目按 ``source``（真实路径）与 ``summary``（内容摘要）区分，不按显示名合并；
- ``index.json`` 坏掉时可从目录重建；
- 固定包（内置 standards）需要编辑时不原地改写，交给调用方生成制作副本。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

#: 用途（三者严格分开，不互相冒充）。
USE_SKELETON = "skeleton"      # 骨架建项
USE_FILL = "fill"              # 模板填充
USE_EXPORT = "export"          # 项目出稿

USE_LABELS = {
    USE_SKELETON: "骨架建项",
    USE_FILL: "模板填充",
    USE_EXPORT: "项目出稿",
}

#: 目录索引文件名（可重建的缓存，不是权威数据）。
INDEX_NAME = "template-library.json"
INDEX_SCHEMA_VERSION = 1

#: 内置固定包：需要编辑时生成制作副本，不原地改写。
FIXED_SOURCES = ("bundled-standards",)


def _sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _load_yaml_like(path: Path) -> Dict[str, object]:
    """读取 pack.yml/recipe（优先 PyYAML，失败返回空字典，不猜字段）。"""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return dict(data) if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 坏索引/坏声明不损坏原资源
        return {}


@dataclass
class TemplateEntry:
    """目录中的一条模板/规范引用。"""

    entryId: str
    name: str
    use: str
    source: str
    sourceKind: str = ""
    version: str = ""
    documentKind: str = ""
    description: str = ""
    summary: str = ""
    templatePath: str = ""
    recipePath: str = ""
    packRoot: str = ""
    fixed: bool = False
    missing: bool = False
    unknown: Dict[str, object] = field(default_factory=dict)

    @property
    def useLabel(self) -> str:
        return USE_LABELS.get(self.use, self.use)

    @property
    def identity(self) -> str:
        """真实身份：来源路径 + 内容摘要（同名不同来源不合并）。"""
        return "{0}#{1}".format(self.source, self.summary[:12])

    def to_dict(self) -> Dict[str, object]:
        return {
            "entryId": self.entryId, "name": self.name, "use": self.use,
            "useLabel": self.useLabel, "source": self.source,
            "sourceKind": self.sourceKind, "version": self.version,
            "documentKind": self.documentKind, "description": self.description,
            "summary": self.summary, "templatePath": self.templatePath,
            "recipePath": self.recipePath, "packRoot": self.packRoot,
            "fixed": self.fixed, "missing": self.missing,
            "identity": self.identity, "unknown": dict(self.unknown),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "TemplateEntry":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        payload = {k: v for k, v in (data or {}).items() if k in known}
        payload.pop("useLabel", None)
        payload.pop("identity", None)
        return cls(**payload)  # type: ignore[arg-type]


@dataclass
class TemplateLibrary:
    """目录内容（条目 + 工作区事实）。"""

    roots: List[str] = field(default_factory=list)
    entries: List[TemplateEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    builtAt: str = ""
    fromIndex: bool = False

    def by_use(self, use: str) -> List[TemplateEntry]:
        return [item for item in self.entries if item.use == use]

    def search(self, keyword: str, *, use: str = "") -> List[TemplateEntry]:
        needle = str(keyword or "").strip().lower()
        result = []
        for item in self.entries:
            if use and item.use != use:
                continue
            if not needle:
                result.append(item)
                continue
            haystack = " ".join([
                item.name, item.useLabel, item.documentKind, item.description,
                item.version, item.source,
            ]).lower()
            if needle in haystack:
                result.append(item)
        return result

    def get(self, entry_id: str) -> Optional[TemplateEntry]:
        for item in self.entries:
            if item.entryId == entry_id:
                return item
        return None

    def summary_line(self) -> str:
        counts = {}
        for item in self.entries:
            counts[item.use] = counts.get(item.use, 0) + 1
        parts = [
            "{0} {1}".format(USE_LABELS.get(key, key), counts[key])
            for key in (USE_SKELETON, USE_FILL, USE_EXPORT) if counts.get(key)
        ]
        return "本地模板目录：{0}".format("；".join(parts) if parts else "暂无可用模板")

# --- 扫描（可重建） ---------------------------------------------------------


def _entry_id(use: str, source: str) -> str:
    return "{0}:{1}".format(use, hashlib.sha1(source.encode("utf-8")).hexdigest()[:12])


def _pack_entries(pack_root: Path, *, fixed: bool, source_kind: str) -> List[TemplateEntry]:
    """一个规范包目录 → 骨架建项 + （若有 template.docx）项目出稿。"""
    manifest_path = pack_root / "pack.yml"
    manifest = _load_yaml_like(manifest_path)
    pack_id = str(manifest.get("packId") or pack_root.name)
    version = str(manifest.get("version") or "")
    kind = str(manifest.get("documentKind") or "")
    description = str(manifest.get("description") or "")
    template = pack_root / "template.docx"
    known = {"schemaVersion", "packId", "version", "documentKind", "description", "files"}
    unknown = {k: v for k, v in manifest.items() if k not in known}
    entries: List[TemplateEntry] = []
    skeleton_dir = pack_root / "skeleton"
    if skeleton_dir.is_dir():
        entries.append(TemplateEntry(
            entryId=_entry_id(USE_SKELETON, str(pack_root)),
            name=pack_id, use=USE_SKELETON, source=str(pack_root),
            sourceKind=source_kind, version=version, documentKind=kind,
            description=description, summary=_sha256_file(manifest_path),
            packRoot=str(pack_root), fixed=fixed, unknown=unknown,
        ))
    if template.is_file():
        entries.append(TemplateEntry(
            entryId=_entry_id(USE_EXPORT, str(template)),
            name=pack_id + " 底模", use=USE_EXPORT, source=str(template),
            sourceKind=source_kind, version=version, documentKind=kind,
            description=description or "规范包自带底模",
            summary=_sha256_file(template), templatePath=str(template),
            packRoot=str(pack_root), fixed=fixed, unknown=unknown,
        ))
    return entries


def _template_entries(templates_root: Path) -> List[TemplateEntry]:
    """独立 DOCX 底模 → 模板填充（有 recipe 时一并挂上）。"""
    entries: List[TemplateEntry] = []
    if not templates_root.is_dir():
        return entries
    for path in sorted(templates_root.glob("*.docx")):
        recipe = path.with_suffix(".recipe.json")
        entries.append(TemplateEntry(
            entryId=_entry_id(USE_FILL, str(path)),
            name=path.stem, use=USE_FILL, source=str(path),
            sourceKind="file", summary=_sha256_file(path),
            templatePath=str(path),
            recipePath=str(recipe) if recipe.is_file() else "",
            description="可填充的 Word 底模",
        ))
    return entries


def scan_roots(
    roots: Sequence[object],
    *,
    warnings: Optional[List[str]] = None,
    templates_root: Optional[object] = None,
) -> List[TemplateEntry]:
    """扫描配置的本地目录，产出条目（每个目录包含骨架建项；``templates`` 另算）。

    坏 ``pack.yml`` 只跳过该条目并记提醒，不影响其它条目与原资源。
    """
    entries: List[TemplateEntry] = []
    for raw in roots or ():
        root = Path(raw)
        if not root.is_dir():
            if warnings is not None:
                warnings.append("目录不存在：{0}".format(root))
            continue
        source_kind = "bundled-standards" if root.name == "standards" else "local-dir"
        fixed = source_kind in FIXED_SOURCES
        for pack_root in sorted(
            path for path in root.iterdir() if path.is_dir() and (path / "pack.yml").is_file()
        ):
            manifest = _load_yaml_like(pack_root / "pack.yml")
            if not manifest.get("packId"):
                if warnings is not None:
                    warnings.append("忽略无法解析的规范包：{0}".format(pack_root))
                continue
            entries.extend(_pack_entries(pack_root, fixed=fixed, source_kind=source_kind))
        # 目录本身直接就是规范包
        if (root / "pack.yml").is_file():
            entries.extend(_pack_entries(root, fixed=fixed, source_kind=source_kind))
    if templates_root is not None:
        entries.extend(_template_entries(Path(templates_root)))
    return entries


def index_path(state_dir) -> Path:
    return Path(state_dir) / INDEX_NAME


def build_library(
    roots: Sequence[object],
    *,
    templates_root: Optional[object] = None,
    state_dir: Optional[object] = None,
) -> TemplateLibrary:
    """重建本地目录（扫描真实目录，不回读坏索引）。"""
    warnings: List[str] = []
    entries = scan_roots(roots, warnings=warnings, templates_root=templates_root)
    library = TemplateLibrary(
        roots=[str(item) for item in roots or ()],
        entries=entries, warnings=warnings,
        builtAt=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    if state_dir is not None:
        write_index(library, state_dir)
    return library


def write_index(library: TemplateLibrary, state_dir) -> Path:
    target = index_path(state_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "builtAt": library.builtAt,
        "roots": list(library.roots),
        "entries": [item.to_dict() for item in library.entries],
        "warnings": list(library.warnings),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def read_index(state_dir) -> Optional[TemplateLibrary]:
    """读取索引缓存；坏/旧/不存在返回 None（由调用方重建）。"""
    target = index_path(state_dir)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schemaVersion") != INDEX_SCHEMA_VERSION:
        return None
    entries = []
    for item in payload.get("entries") or []:
        if not isinstance(item, dict) or not item.get("entryId"):
            continue
        try:
            entries.append(TemplateEntry.from_dict(item))
        except TypeError:
            continue
    library = TemplateLibrary(
        roots=[str(x) for x in payload.get("roots") or []],
        entries=entries,
        warnings=[str(x) for x in payload.get("warnings") or []],
        builtAt=str(payload.get("builtAt") or ""),
        fromIndex=True,
    )
    # 索引只是缓存：检查引用是否仍然存在，缺失的标出来（不静默当作可用）。
    for item in library.entries:
        target_path = Path(item.templatePath or item.packRoot or item.source)
        if str(target_path) and not target_path.exists():
            item.missing = True
    return library


def load_library(
    roots: Sequence[object],
    *,
    templates_root: Optional[object] = None,
    state_dir: Optional[object] = None,
) -> TemplateLibrary:
    """优先用索引（可重建缓存）；索引坏/不可用则扫描真实目录。"""
    if state_dir is not None:
        cached = read_index(state_dir)
        if cached is not None and cached.entries:
            return cached
    return build_library(roots, templates_root=templates_root, state_dir=state_dir)


def relocate_warning(library: TemplateLibrary) -> List[str]:
    """缺路径条目的可执行下一步（重定位提示）。"""
    return [
        "{0}（{1}）的来源已不存在，请重新定位或从目录移除".format(item.name, item.source)
        for item in library.entries if item.missing
    ]


def recipe_for(entry: TemplateEntry) -> str:
    """该条目的 recipe 路径（空表示按受支持字段默认）。"""
    return str(entry.recipePath or "")
