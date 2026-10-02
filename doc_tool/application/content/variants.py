# -*- coding: utf-8 -*-
"""V3.0 产品变体与展开兼容副本（批次 30-E）。

``variants.yml``（schema 1，可选 sidecar）保存命名变体：显式章节 include/exclude、
文本变量覆盖、slot 版本/参数覆盖。首版只支持显式列表，不支持脚本或布尔表达式。

设计要点（对齐 design.md D5 与「旧项目与展开副本」需求）：

- 无 ``variants.yml`` 时用默认项目行为（有效章节＝项目顺序），旧项目不受影响；
- 坏可选项（越界路径、未知 slot、空名）回退项目值并集中提示；
- 输出按 ``variantId`` 独立目录，报告记录项目版本、variantId、有效章节/模块/hashes；
- 追踪范围只算变体包含且明确纳入的实例，范围外关系显示未纳入；
- 展开兼容副本 = 普通 Markdown 项目副本（已展开正文 + 资源 + 来源说明），
  不依赖新标记即可打开，可在任意目录读取。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.chapter_order import resolve_chapter_order
from doc_tool.application.content import module_refs as refs
from doc_tool.application.content import modules as module_lib
from doc_tool.application.content.writer import atomic_write, atomic_write_bytes
from doc_tool.application.intake_contract import sha256_text

#: variants sidecar schema 版本。
SCHEMA_VERSION = 1

#: 项目内 sidecar 相对路径。
VARIANTS_RELATIVE = "variants.yml"

#: 变体输出根目录名（相对导出目录）。
COPY_MODULE_DIR = "modules"
#: 展开副本清单文件名。
COPY_MANIFEST_NAME = "_copy.yml"
#: 展开副本说明文件名。
COPY_README_NAME = "README-展开副本.md"
#: 展开副本索引文件名。
COPY_INDEX_NAME = "_index.md"

#: 有效范围未纳入时的展示用语。
EXCLUDED_NOTE = "范围外（未纳入覆盖率）"


@dataclass
class Variant:
    """一个命名产品变体：显式章节列表 + 文本覆盖。"""

    variantId: str
    name: str = ""
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    slots: Dict[str, Dict[str, object]] = field(default_factory=dict)
    modules: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.variantId = str(self.variantId or "").strip()
        self.name = str(self.name or self.variantId)
        self.include = [_normalize_section(item) for item in (self.include or []) if str(item or "").strip()]
        self.exclude = [_normalize_section(item) for item in (self.exclude or []) if str(item or "").strip()]
        self.variables = {str(k): ("" if v is None else str(v)) for k, v in (self.variables or {}).items()}
        cleaned_slots: Dict[str, Dict[str, object]] = {}
        for key, value in (self.slots or {}).items():
            row = dict(value or {}) if isinstance(value, dict) else {"version": value}
            cleaned_slots[str(key)] = row
        self.slots = cleaned_slots
        self.modules = {str(k): str(v) for k, v in (self.modules or {}).items()}

    # --- 序列化 ---

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {"variantId": self.variantId, "name": self.name}
        if self.include:
            data["include"] = list(self.include)
        if self.exclude:
            data["exclude"] = list(self.exclude)
        if self.variables:
            data["variables"] = dict(self.variables)
        if self.slots:
            data["slots"] = {key: dict(value) for key, value in self.slots.items()}
        if self.modules:
            data["modules"] = dict(self.modules)
        return data

    # --- 覆盖查询 ---

    def slot_override(self, slot_id: str, module_id: str) -> Dict[str, object]:
        """取该 slot 的生效覆盖：slot 精确键 → 模块键 → 通配 ``*``。"""
        merged: Dict[str, object] = {}
        wildcard = self.slots.get("*")
        if isinstance(wildcard, dict):
            merged.update(wildcard)
        module_row = self.slots.get("module:" + module_id)
        if isinstance(module_row, dict):
            merged.update(module_row)
        exact = self.slots.get(slot_id)
        if isinstance(exact, dict):
            merged.update(exact)
        if module_id in self.modules:
            merged["version"] = self.modules[module_id]
        return merged

    def module_version(self, module_id: str, default: str = "") -> str:
        return str(self.modules.get(module_id, default))


@dataclass
class VariantScope:
    """变体的有效范围证据：章节、变量、模块版本与实际提示。"""

    variantId: str
    chapters: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    moduleVersions: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "variantId": self.variantId,
            "chapters": list(self.chapters),
            "excluded": list(self.excluded),
            "variables": dict(self.variables),
            "moduleVersions": dict(self.moduleVersions),
            "warnings": list(self.warnings),
        }


@dataclass
class VariantRun:
    """一次变体构建的记录：独立输出目录 + 有效范围 + 模块 hashes。"""

    variantId: str
    name: str
    outputDir: str
    chapters: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    moduleVersions: Dict[str, str] = field(default_factory=dict)
    moduleHashes: Dict[str, str] = field(default_factory=dict)
    hostPaths: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    index: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "variantId": self.variantId,
            "name": self.name,
            "outputDir": self.outputDir,
            "chapters": list(self.chapters),
            "excluded": list(self.excluded),
            "variables": dict(self.variables),
            "moduleVersions": dict(self.moduleVersions),
            "moduleHashes": dict(self.moduleHashes),
            "hostPaths": dict(self.hostPaths),
            "warnings": list(self.warnings),
            "assets": list(self.assets),
            "index": self.index,
        }

# --------------------------------------------------------------------------
# 配置读写
# --------------------------------------------------------------------------


@dataclass
class VariantsConfig:
    """``variants.yml``：命名变体集合（schema 1）。"""

    variants: List[Variant] = field(default_factory=list)
    schemaVersion: int = SCHEMA_VERSION

    def get(self, variant_id: str) -> Optional[Variant]:
        for variant in self.variants:
            if variant.variantId == variant_id:
                return variant
        return None

    def ids(self) -> List[str]:
        return [variant.variantId for variant in self.variants]

    def names(self) -> List[str]:
        return [variant.name for variant in self.variants]

    def describe(self) -> str:
        return "、".join(
            "{0}({1})".format(variant.variantId, variant.name) for variant in self.variants
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "schemaVersion": self.schemaVersion,
            "variants": [variant.to_dict() for variant in self.variants],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "VariantsConfig":
        if not isinstance(data, dict) or int(data.get("schemaVersion", 0) or 0) != SCHEMA_VERSION:
            return cls()
        variants: List[Variant] = []
        seen = set()
        for row in data.get("variants") or []:
            if not isinstance(row, dict):
                continue
            variant_id = str(row.get("variantId", "")).strip()
            if not variant_id or variant_id in seen:
                continue
            seen.add(variant_id)
            variants.append(
                Variant(
                    variantId=variant_id,
                    name=str(row.get("name", "")),
                    include=list(row.get("include") or []),
                    exclude=list(row.get("exclude") or []),
                    variables=dict(row.get("variables") or {}),
                    slots=dict(row.get("slots") or {}),
                    modules=dict(row.get("modules") or {}),
                )
            )
        return cls(variants=variants)

    @classmethod
    def load(cls, project_root) -> "VariantsConfig":
        """读取变体配置；缺失/损坏回退空配置（等同默认项目，不阻断出稿）。"""
        import yaml

        path = Path(project_root) / VARIANTS_RELATIVE
        if not path.is_file():
            return cls()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return cls()
        except Exception:  # noqa: BLE001 - YAML 异常类型随版本变化
            return cls()
        return cls.from_dict(data if isinstance(data, dict) else {})


class VariantsStore:
    """变体配置存储：项目内 ``variants.yml`` 原子读写。"""

    def __init__(self, project_root=None) -> None:
        self._root = Path(project_root) if project_root is not None else None
        self._config = VariantsConfig.load(self._root) if self._root is not None else VariantsConfig()
        self._load_error = False

    @property
    def config(self) -> VariantsConfig:
        return self._config

    def variants(self) -> List[Variant]:
        return list(self._config.variants)

    def get(self, variant_id: str) -> Optional[Variant]:
        return self._config.get(variant_id)

    def upsert(self, variant: Variant) -> Variant:
        for index, existing in enumerate(self._config.variants):
            if existing.variantId == variant.variantId:
                self._config.variants[index] = variant
                return variant
        self._config.variants.append(variant)
        return variant

    def remove(self, variant_id: str) -> bool:
        kept = [item for item in self._config.variants if item.variantId != variant_id]
        if len(kept) == len(self._config.variants):
            return False
        self._config.variants = kept
        return True

    def save(self, project_root=None) -> Path:
        import yaml

        root = Path(project_root) if project_root is not None else self._root
        if root is None:
            raise ValueError("缺少项目根，无法保存变体配置")
        path = root / VARIANTS_RELATIVE
        atomic_write(path, yaml.safe_dump(self._config.to_dict(), allow_unicode=True, sort_keys=False))
        return path


# --------------------------------------------------------------------------
# 有效内容解析
# --------------------------------------------------------------------------


def _normalize_section(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _section_matches(section: str, item: str) -> bool:
    """章节是否命中声明项：全路径、目录名或路径前缀（大小写不敏感）。"""
    text = _normalize_section(item).casefold()
    if not text:
        return False
    key = _normalize_section(section).casefold()
    if key == text:
        return True
    if key.rsplit("/", 1)[-1] == text:
        return True
    if key.rsplit(".", 1)[0] == text.rsplit(".", 1)[0]:
        return True
    return key.startswith(text.rstrip("/") + "/")


def effective_chapters(
    discovered: Sequence[str],
    declared: Optional[Sequence[str]] = None,
    variant: Optional[Variant] = None,
) -> Tuple[List[str], List[str], List[str]]:
    """按「项目顺序筛选 → 变体 include/exclude」得到有效章节。

    返回 ``(有效章节, 被排除章节, warnings)``。声明但不存在/越界的项回退项目值并提示。
    """
    order = resolve_chapter_order(discovered, declared)
    warnings = list(order.warnings)
    base = list(order.ordered)
    if variant is None:
        return base, [], warnings

    kept: List[str] = []
    excluded: List[str] = []
    include = list(variant.include)
    exclude = list(variant.exclude)
    if include:
        for section in include:
            if not any(_section_matches(item, section) for item in base):
                warnings.append(
                    "变体 {0} 的章节项未找到，已忽略：{1}".format(variant.variantId, section)
                )
    if exclude:
        for section in exclude:
            if not any(_section_matches(item, section) for item in base):
                warnings.append(
                    "变体 {0} 的排除项未找到，已忽略：{1}".format(variant.variantId, section)
                )
    for item in base:
        matched_include = (not include) or any(_section_matches(item, section) for section in include)
        matched_exclude = any(_section_matches(item, section) for section in exclude)
        if matched_include and not matched_exclude:
            kept.append(item)
        else:
            excluded.append(item)
    if not kept and base:
        warnings.append(
            "变体 {0} 的有效章节为空，已回退为项目全部章节".format(variant.variantId)
        )
        return base, [], warnings
    return kept, excluded, warnings


def effective_variables(
    project_variables: Optional[Dict[str, str]] = None,
    variant: Optional[Variant] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """有效变量＝项目变量 + 变体文本覆盖（空名回退项目值并提示）。"""
    values = {
        str(key): ("" if value is None else str(value))
        for key, value in (project_variables or {}).items()
    }
    if variant is None:
        return values, []
    warnings: List[str] = []
    for name, value in variant.variables.items():
        if not str(name).strip():
            warnings.append("变体 {0} 存在空变量名，已忽略".format(variant.variantId))
            continue
        values[str(name)] = "" if value is None else str(value)
    return values, warnings


def effective_slot_overrides(
    assembly: refs.Assembly,
    variant: Optional[Variant] = None,
) -> Tuple[Dict[str, Dict[str, object]], List[str]]:
    """把变体 slot/module 覆盖转成 resolver 可用的 ``{slotId: 覆盖}``。"""
    if variant is None:
        return {}, []
    warnings: List[str] = []
    known = {slot.slotId for slot in assembly.slots}
    overrides: Dict[str, Dict[str, object]] = {}
    for slot_id, row in variant.slots.items():
        if slot_id in ("*",) or slot_id.startswith("module:"):
            continue
        if slot_id not in known:
            warnings.append(
                "变体 {0} 的 slot 覆盖未匹配到项目引用，已忽略：{1}".format(variant.variantId, slot_id)
            )
            continue
        overrides[slot_id] = dict(row)
    for slot in assembly.slots:
        merged = variant.slot_override(slot.slotId, slot.moduleId)
        if merged:
            current = overrides.setdefault(slot.slotId, {})
            for key, value in merged.items():
                current.setdefault(key, value)
    return overrides, warnings


def variant_scope(
    variant: Variant,
    *,
    discovered: Sequence[str],
    declared: Optional[Sequence[str]] = None,
    project_variables: Optional[Dict[str, str]] = None,
    assembly: Optional[refs.Assembly] = None,
) -> VariantScope:
    """汇总一个变体的实际有效范围（章节/变量/模块版本/提示）。"""
    chapters, excluded, warnings = effective_chapters(discovered, declared, variant)
    variables, variable_warnings = effective_variables(project_variables, variant)
    warnings.extend(variable_warnings)
    module_versions: Dict[str, str] = {}
    if assembly is not None:
        overrides, slot_warnings = effective_slot_overrides(assembly, variant)
        warnings.extend(slot_warnings)
        for slot in assembly.slots:
            row = variant.slot_override(slot.slotId, slot.moduleId)
            overridden = row.get("version")
            module_versions[slot.moduleId] = str(
                overridden or variant.module_version(slot.moduleId, slot.version)
            )
    for module_id, version in variant.modules.items():
        module_versions.setdefault(module_id, version)
    return VariantScope(
        variantId=variant.variantId,
        chapters=chapters,
        excluded=excluded,
        variables=variables,
        moduleVersions=module_versions,
        warnings=warnings,
    )


def unknown_variant_message(config: VariantsConfig, requested: str) -> str:
    """明确指定不存在的变体时的可读提示（列出可选项，不偷偷构建别的型号）。"""
    options = config.describe() or "（无）"
    return "未找到变体 {0}；可选变体：{1}".format(requested, options)

# --------------------------------------------------------------------------
# 展开兼容副本
# --------------------------------------------------------------------------


def _host_output_relative(host_path: str, document_type: str = "general") -> str:
    """把宿主章节相对路径映射到副本内输出路径（缺省带类型目录）。"""
    text = _normalize_section(host_path)
    if not text:
        return "chapters/未命名章节.md"
    if text.startswith("content/"):
        return text
    return "content/{0}/{1}".format(document_type or "general", text)


def _provenance_note(variant: Optional[Variant]) -> str:
    if variant is None:
        return "> 来源：本项目固定模块展开出的普通正文；原项目正文未被修改。"
    return "> 来源：变体 {0}（{1}）展开出的普通正文；原项目正文与公共模块未被修改。".format(
        variant.variantId, variant.name
    )


_LINK_TARGET_RE = re.compile(r"(\]\(|<)(?P<target>[^)\s>]+)")


def _rewrite_reference(text: str, old_ref: str, new_ref: str) -> str:
    """把正文里的某个资源目标改写为副本内相对路径（只匹配引用括号内目标）。"""

    def _replace(match: re.Match) -> str:
        if match.group("target") == old_ref:
            return "{0}{1}".format(match.group(1), new_ref)
        return match.group(0)

    return _LINK_TARGET_RE.sub(_replace, str(text or ""))


def expand_document_variant(
    project_root,
    *,
    discovered: Sequence[str],
    document_type: str = "general",
    declared: Optional[Sequence[str]] = None,
    project_variables: Optional[Dict[str, str]] = None,
    assembly: Optional[refs.Assembly] = None,
    variant: Optional[Variant] = None,
    library: Optional[module_lib.ModuleLibrary] = None,
    cache: Optional[refs.ResolutionCache] = None,
    output_dir=None,
    copy_assets: bool = True,
    write: bool = True,
) -> Tuple[VariantRun, Dict[str, str]]:
    """展开项目正文（可选变体范围），返回 ``(运行记录, {宿主路径: 展开文本})``。

    展开结果与预览/Word/HTML/检查同源；图片资源按模块来源改写为副本内可用路径。
    """
    project_root = Path(project_root)
    content_root = project_root / "content" / (document_type or "general")
    chapters, excluded, warnings = effective_chapters(discovered, declared, variant)
    variables, variable_warnings = effective_variables(project_variables, variant)
    warnings.extend(variable_warnings)
    assembly = assembly if assembly is not None else refs.Assembly.load(project_root)
    overrides, slot_warnings = effective_slot_overrides(assembly, variant)
    warnings.extend(slot_warnings)
    if library is None:
        library = module_lib.ModuleLibrary(module_lib.project_module_root(project_root))
    target_root = Path(output_dir) if output_dir is not None else None

    bodies: Dict[str, str] = {}
    replacements: Dict[str, Dict[str, str]] = {}
    chapter_assets: Dict[str, Dict[str, Path]] = {}
    module_versions: Dict[str, str] = {}
    module_hashes: Dict[str, str] = {}
    host_paths: Dict[str, str] = {}
    sources: Dict[str, Path] = {}
    for chapter in chapters:
        source_path = content_root / chapter
        if not source_path.is_file():
            warnings.append("章节文件缺失，已跳过：{0}".format(chapter))
            continue
        try:
            text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            warnings.append("章节读取失败，已跳过：{0}".format(chapter))
            continue
        resolution = refs.resolve_body(
            text,
            project_root=project_root,
            library=library,
            variables=variables,
            host_path=chapter,
            asset_root=project_root,
            cache=cache,
            slot_overrides=overrides,
        )
        resolved_text = resolution.text
        for segment in resolution.module_segments():
            module_versions[segment.slotId or segment.moduleId] = "{0}@{1}".format(
                segment.moduleId, segment.version
            )
            module_hashes.update(segment.dependencyHashes)
            if segment.slotId:
                host_paths[segment.slotId] = chapter
        resolved_refs = {path.as_posix(): path for path in resolution.resources().values()}
        for target, source_path in resolution.resources().items():
            try:
                source_path.resolve().relative_to(project_root.resolve())
            except (ValueError, OSError):
                continue
            chapter_assets.setdefault(chapter, {})[target] = source_path
            try:
                display = source_path.resolve().relative_to(project_root.resolve()).as_posix()
            except (ValueError, OSError):
                display = target
            if display != target:
                replacements.setdefault(chapter, {})[display] = target
        sources.update(resolution.resources())
        del resolved_refs
        warnings.extend(
            "章节 {0}：{1}".format(chapter, warning) for warning in resolution.warnings
        )
        if resolution.changed:
            note = _provenance_note(variant)
            if not resolved_text.rstrip("\n").endswith(note):
                resolved_text = resolved_text.rstrip("\n") + "\n\n" + note + "\n"
        bodies[chapter] = resolved_text

    run = VariantRun(
        variantId=variant.variantId if variant is not None else "",
        name=variant.name if variant is not None else "",
        outputDir=str(target_root) if target_root is not None else "",
        chapters=list(bodies.keys()),
        excluded=list(excluded),
        variables=dict(variables),
        moduleVersions=dict(module_versions),
        moduleHashes=dict(module_hashes),
        hostPaths=dict(host_paths),
        warnings=warnings,
    )
    if write and target_root is not None:
        _write_copy_tree(
            target_root,
            bodies,
            document_type=document_type,
            variant=variant,
            run=run,
            sources=sources,
            copy_assets=copy_assets,
            project_root=project_root,
            replacements=replacements,
            chapter_assets=chapter_assets,
        )
    return run, bodies


def _write_copy_tree(
    target_root: Path,
    bodies: Dict[str, str],
    *,
    document_type: str,
    variant: Optional[Variant],
    run: VariantRun,
    sources: Dict[str, Path],
    copy_assets: bool,
    project_root: Optional[Path] = None,
    replacements: Optional[Dict[str, Dict[str, str]]] = None,
    chapter_assets: Optional[Dict[str, Dict[str, Path]]] = None,
) -> None:
    """写出普通 Markdown 副本：正文 + 资源 + 清单 + 说明。

    资源按**项目内相对布局**复制，正文里的相对引用在副本内保持可用（可搬目录打开）。
    """
    target_root = Path(target_root)
    replacements = replacements or {}
    chapter_assets = chapter_assets or {}
    copied: List[str] = []
    for chapter, text in bodies.items():
        output = text
        for old_ref, new_ref in (replacements.get(chapter) or {}).items():
            output = _rewrite_reference(output, old_ref, new_ref)
        output_path = target_root / _host_output_relative(chapter, document_type)
        atomic_write(output_path, output)
        for target, source_path in sorted((chapter_assets.get(chapter) or {}).items()):
            source_file = Path(source_path)
            if not source_file.is_file():
                continue
            destination = output_path.parent / str(target).replace("\\", "/")
            atomic_write_bytes(destination, source_file.read_bytes())
            copied.append(destination.relative_to(target_root).as_posix())
    placed = {
        str(key).replace("\\", "/")
        for assets in chapter_assets.values()
        for key in assets.keys()
    }
    if copy_assets:
        for target, source in sorted(sources.items()):
            if str(target).replace("\\", "/") in placed:
                continue
            source_path = Path(source)
            if not source_path.is_file():
                continue
            reference = str(target).replace("\\", "/")
            destination = None
            if project_root is not None:
                try:
                    destination = target_root / source_path.resolve().relative_to(
                        Path(project_root).resolve()
                    )
                except (ValueError, OSError):
                    destination = None
            if destination is None:
                if Path(reference).parts[:1] == ("reuse",):
                    destination = target_root / reference
                else:
                    destination = target_root / "assets" / Path(reference)
            if destination.relative_to(target_root).as_posix() in copied:
                continue
            atomic_write_bytes(destination, source_path.read_bytes())
            copied.append(destination.relative_to(target_root).as_posix())
    run.assets = copied
    index_lines = ["# 展开副本索引", ""]
    index_lines.append(
        "本副本是普通 Markdown 项目，已展开全部固定引用，旧应用无需识别新标记。"
    )
    index_lines.append("")
    if variant is not None:
        index_lines.append("- 变体：{0}（{1}）".format(variant.variantId, variant.name))
    index_lines.append("- 文档类型：{0}".format(document_type))
    index_lines.append("- 有效章节：{0}".format("、".join(run.chapters) or "（无）"))
    if run.excluded:
        index_lines.append("- 未纳入本副本：{0}".format("、".join(run.excluded)))
    if run.moduleVersions:
        index_lines.append("")
        index_lines.append("## 固定模块")
        for key, value in sorted(run.moduleVersions.items()):
            index_lines.append("- {0}：{1}".format(key or "（未命名）", value))
    index_path = target_root / COPY_INDEX_NAME
    atomic_write(index_path, "\n".join(index_lines) + "\n")
    run.index = index_path.relative_to(target_root).as_posix()

    readme_lines = [
        "# 展开副本说明",
        "",
        "本目录由文档工具生成，用于交给旧版应用或外部作者：内容是已展开的**普通 Markdown**，",
        "不包含 ``doc-module`` 引用标记；图片等资源已复制到本目录内，可整体搬走后在任意路径打开。",
        "",
        "- 原项目正文与公共模块未被修改；本副本是独立快照。",
        "- 副本清单见 ``{0}``，记录来源项目、变体、有效章节与模块版本。".format(COPY_MANIFEST_NAME),
        "- 需要继续使用模块升级/变体能力时，请回到原项目，不要在此副本上编辑。",
        "",
    ]
    atomic_write(target_root / COPY_README_NAME, "\n".join(readme_lines))
    import yaml

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "expanded-copy",
        "variantId": run.variantId,
        "variantName": run.name,
        "documentType": document_type,
        "chapters": list(run.chapters),
        "excluded": list(run.excluded),
        "moduleVersions": dict(run.moduleVersions),
        "moduleHashes": dict(run.moduleHashes),
        "assets": list(copied),
    }
    atomic_write(
        target_root / COPY_MANIFEST_NAME,
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
    )


def write_expanded_copy(
    project_root,
    target_dir,
    *,
    discovered: Sequence[str],
    document_type: str = "general",
    declared: Optional[Sequence[str]] = None,
    project_variables: Optional[Dict[str, str]] = None,
    assembly: Optional[refs.Assembly] = None,
    variant: Optional[Variant] = None,
    library: Optional[module_lib.ModuleLibrary] = None,
    cache: Optional[refs.ResolutionCache] = None,
    copy_assets: bool = True,
) -> VariantRun:
    """生成展开兼容副本（普通 Markdown 项目副本，可搬目录打开）。"""
    run, _bodies = expand_document_variant(
        project_root,
        discovered=discovered,
        document_type=document_type,
        declared=declared,
        project_variables=project_variables,
        assembly=assembly,
        variant=variant,
        library=library,
        cache=cache,
        output_dir=Path(target_dir),
        copy_assets=copy_assets,
        write=True,
    )
    return run


def variant_output_dir(base_dir, variant_id: str) -> Path:
    """变体独立输出目录：``<base>/<variantId>``（同名不覆盖，追加 -2）。"""
    base = Path(base_dir)
    name = module_lib.slugify(variant_id or "default")
    candidate = base / name
    index = 2
    while candidate.exists():
        candidate = base / "{0}-{1}".format(name, index)
        index += 1
    return candidate


def build_variant_outputs(
    project_root,
    base_dir,
    *,
    discovered: Sequence[str],
    document_type: str = "general",
    declared: Optional[Sequence[str]] = None,
    project_variables: Optional[Dict[str, str]] = None,
    assembly: Optional[refs.Assembly] = None,
    config: Optional[VariantsConfig] = None,
    variant_ids: Optional[Iterable[str]] = None,
    library: Optional[module_lib.ModuleLibrary] = None,
    cache: Optional[refs.ResolutionCache] = None,
    copy_assets: bool = True,
) -> Tuple[List[VariantRun], List[str]]:
    """按 variantId 逐个生成独立目录出稿，返回 ``(运行记录, 错误/提示)``。

    明确指定不存在的变体只报错，不偷偷构建别的型号；无变体配置时等价于默认项目。
    """
    project_root = Path(project_root)
    config = config if config is not None else VariantsConfig.load(project_root)
    assembly = assembly if assembly is not None else refs.Assembly.load(project_root)
    problems: List[str] = []
    runs: List[VariantRun] = []
    if variant_ids:
        selected: List[Optional[Variant]] = []
        for variant_id in variant_ids:
            variant = config.get(str(variant_id))
            if variant is None:
                problems.append(unknown_variant_message(config, str(variant_id)))
                continue
            selected.append(variant)
    elif config.variants:
        selected = list(config.variants)
    else:
        selected = [None]
    for variant in selected:
        directory = variant_output_dir(base_dir, variant.variantId if variant else "default")
        run, _bodies = expand_document_variant(
            project_root,
            discovered=discovered,
            document_type=document_type,
            declared=declared,
            project_variables=project_variables,
            assembly=assembly,
            variant=variant,
            library=library,
            cache=cache,
            output_dir=directory,
            copy_assets=copy_assets,
            write=True,
        )
        runs.append(run)
    return runs, problems

# --------------------------------------------------------------------------
# 副本自检与报告
# --------------------------------------------------------------------------


@dataclass
class PortableIssue:
    """副本自检发现的一处问题：文件 + 行号 + 目标。"""

    file: str
    line: int
    target: str
    message: str


def verify_portable_copy(root) -> List[PortableIssue]:
    """自检展开副本：所有本地资源/链接在副本内可用（可搬目录打开）。"""
    root = Path(root).resolve()
    issues: List[PortableIssue] = []
    pattern = re.compile(r"!?\[[^\]\n]*\]\((?P<target>[^)\s]+)")
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            issues.append(PortableIssue(relative, 0, "", "文件不可读"))
            continue
        for line_no, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                target = match.group("target")
                if module_lib.is_external_target(target):
                    continue
                cleaned = target.split("#", 1)[0]
                if not cleaned:
                    continue
                candidate = (path.parent / cleaned).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    issues.append(
                        PortableIssue(relative, line_no, target, "目标越出副本目录，搬走后不可用")
                    )
                    continue
                if not candidate.is_file():
                    issues.append(PortableIssue(relative, line_no, target, "副本内目标缺失"))
    return issues


def variant_report(run: VariantRun) -> Dict[str, object]:
    """把一次变体运行的记录整理为机器可读报告。"""
    return {
        "variantId": run.variantId,
        "name": run.name,
        "outputDir": run.outputDir,
        "scope": {
            "chapters": list(run.chapters),
            "excluded": list(run.excluded),
            "variables": dict(run.variables),
            "moduleVersions": dict(run.moduleVersions),
            "moduleHashes": dict(run.moduleHashes),
        },
        "excludedNote": EXCLUDED_NOTE if run.excluded else "",
        "warnings": list(run.warnings),
        "assets": list(run.assets),
    }


def coverage_note(run: VariantRun, tracked_host_paths: Iterable[str]) -> Dict[str, object]:
    """解释追踪分母：只算变体包含且明确纳入的宿主章节。"""
    included = list(run.chapters)
    inside = [item for item in tracked_host_paths if item in included]
    outside = [item for item in tracked_host_paths if item not in included]
    return {
        "variantId": run.variantId,
        "included": included,
        "counted": inside,
        "excluded": outside,
        "note": EXCLUDED_NOTE if outside else "",
    }


__all__ = [
    "SCHEMA_VERSION", "VARIANTS_RELATIVE", "COPY_MODULE_DIR", "COPY_MANIFEST_NAME",
    "COPY_README_NAME", "COPY_INDEX_NAME", "EXCLUDED_NOTE",
    "Variant", "VariantScope", "VariantRun", "VariantsConfig", "VariantsStore",
    "effective_chapters", "effective_variables", "effective_slot_overrides",
    "variant_scope", "unknown_variant_message",
    "expand_document_variant", "write_expanded_copy", "variant_output_dir",
    "build_variant_outputs", "verify_portable_copy", "variant_report", "coverage_note",
    "PortableIssue",
]