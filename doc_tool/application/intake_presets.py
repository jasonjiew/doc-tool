# -*- coding: utf-8 -*-
"""命名导入映射预设（CORE-D 4.2）。

与 ``template_fill_presets`` 的**填充配方**分开存储、分开语义：这里保存的是
“样式 → 标题级别 + 入口设置”的导入映射，用于同类文档少配一次参数。失效项
保留可匹配部分，其余回退自动识别/单章，并在结果中记录实际决定。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import uuid4

from doc_tool.application.content.writer import atomic_write, atomic_write_bytes

PRESET_FILE_NAME = "intake-presets.json"
PRESET_SCHEMA_VERSION = 1


def preset_file(root: Optional[Path] = None) -> Path:
    """预设文件位置（用户配置目录，与模板填充配方同一约定但不同文件）。"""
    if root is not None:
        return Path(root) / PRESET_FILE_NAME
    try:
        from doc_tool.application.project_service import _config_dir

        return Path(_config_dir()) / PRESET_FILE_NAME
    except Exception:  # noqa: BLE001 - 配置目录不可用时退回用户主目录
        return Path.home() / ".doctool" / PRESET_FILE_NAME


@dataclass
class ResolvedPreset:
    """一次预设解析结果：实际采用的映射 + 未匹配项 + 说明。"""

    presetId: str = ""
    name: str = ""
    mapping: Dict[str, int] = field(default_factory=dict)
    unmatched: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    settings: Dict[str, object] = field(default_factory=dict)
    used_fallback: bool = False

    @property
    def has_mapping(self) -> bool:
        return bool(self.mapping)

    def summary_line(self) -> str:
        if not self.name:
            return "未使用映射预设（自动识别）"
        if self.used_fallback:
            return "预设「{0}」失效，已回退自动识别/单章".format(self.name)
        if self.unmatched:
            return "预设「{0}」：匹配 {1} 项，未匹配 {2} 项".format(
                self.name, len(self.mapping), len(self.unmatched)
            )
        return "预设「{0}」：全部 {1} 项匹配".format(self.name, len(self.mapping))


@dataclass
class IntakePreset:
    """一个命名导入映射预设。"""

    presetId: str
    name: str
    mapping: Dict[str, int] = field(default_factory=dict)
    styleNames: Dict[str, str] = field(default_factory=dict)
    settings: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "presetId": self.presetId,
            "name": self.name,
            "mapping": {str(k): int(v) for k, v in self.mapping.items()},
            "styleNames": {str(k): str(v) for k, v in self.styleNames.items()},
            "settings": dict(self.settings),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "IntakePreset":
        mapping = {
            str(k): int(v) for k, v in dict(data.get("mapping") or {}).items()
            if isinstance(v, int) and 1 <= int(v) <= 6
        }
        return cls(
            presetId=str(data.get("presetId") or uuid4().hex),
            name=str(data.get("name") or ""),
            mapping=mapping,
            styleNames={str(k): str(v) for k, v in dict(data.get("styleNames") or {}).items()},
            settings=dict(data.get("settings") or {}),
        )


class IntakePresets:
    """预设仓库：损坏文件隔离后使用内置默认（不阻止建项）。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.path = preset_file(root)
        self.warnings: List[str] = []
        self.presets: List[IntakePreset] = self._load()

    # --- 存储 ---

    def _load(self) -> List[IntakePreset]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schemaVersion") != PRESET_SCHEMA_VERSION:
                raise ValueError("schema 版本不受支持")
            items = data.get("presets")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("presets 必须是对象列表")
            return [IntakePreset.from_dict(item) for item in items]
        except (OSError, ValueError, AttributeError) as exc:
            self.warnings.append("导入预设配置损坏，已保留原文件并使用默认值：{0}".format(exc))
            try:
                atomic_write_bytes(
                    self.path.with_name(self.path.name + ".damaged-" + uuid4().hex),
                    self.path.read_bytes(),
                )
            except OSError:
                pass
            return []

    def _save(self, presets: Sequence[IntakePreset]) -> None:
        payload = {
            "schemaVersion": PRESET_SCHEMA_VERSION,
            "presets": [item.to_dict() for item in presets],
        }
        atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))
        self.presets = list(presets)

    def save(
        self,
        name: str,
        mapping: Dict[str, int],
        *,
        style_names: Optional[Dict[str, str]] = None,
        settings: Optional[Dict[str, object]] = None,
        preset_id: str = "",
    ) -> IntakePreset:
        cleaned = str(name or "").strip()
        if not cleaned:
            raise ValueError("预设名称不能为空")
        preset = IntakePreset(
            presetId=preset_id or uuid4().hex,
            name=cleaned,
            mapping={str(k): int(v) for k, v in (mapping or {}).items()},
            styleNames={str(k): str(v) for k, v in (style_names or {}).items()},
            settings=dict(settings or {}),
        )
        values = [item for item in self.presets if item.presetId != preset.presetId]
        values.append(preset)
        self._save(values)
        return preset

    def delete(self, preset_id: str) -> None:
        self._save([item for item in self.presets if item.presetId != preset_id])

    def find(self, name: str) -> Optional[IntakePreset]:
        for item in self.presets:
            if item.name == name or item.presetId == name:
                return item
        return None

    # --- 解析 ---

    def resolve(
        self,
        preset: Optional[IntakePreset],
        available_styles: Dict[str, str],
    ) -> ResolvedPreset:
        """把预设适配到当前源文档：保留可匹配项，其余回退自动识别。

        ``available_styles`` 为 ``{styleId: 样式名}``（来自预检普查）。
        """
        if preset is None:
            return ResolvedPreset()
        resolved = ResolvedPreset(
            presetId=preset.presetId, name=preset.name, settings=dict(preset.settings),
        )
        known = set(available_styles)
        for style_id, level in preset.mapping.items():
            if style_id in known:
                resolved.mapping[style_id] = int(level)
                continue
            name = preset.styleNames.get(style_id, "")
            matched = next(
                (sid for sid, style_name in available_styles.items()
                 if name and style_name == name),
                None,
            )
            if matched is not None:
                resolved.mapping[matched] = int(level)
            else:
                resolved.unmatched.append(style_id)
        if resolved.unmatched:
            resolved.warnings.append(
                "预设中 {0} 项样式在当前文档不存在，已回退自动识别".format(len(resolved.unmatched))
            )
        if not resolved.mapping:
            resolved.used_fallback = True
            resolved.warnings.append("预设完全失配，按自动识别/单章继续")
        return resolved




# --- 生产入口的唯一实现（CLI / 首次导入 / 服务层共用，避免三处各写一遍） ---


def source_style_names(src) -> Dict[str, str]:
    """读取源文档的 ``{styleId: 样式名}``（失败返回空，不阻断导入）。"""
    from pathlib import Path as _Path

    path = _Path(src)
    parts = None
    try:
        import zipfile

        with zipfile.ZipFile(path) as archive:
            parts = {
                name: archive.read(name) for name in archive.namelist()
                if name.startswith("word/")
            }
    except Exception:  # noqa: BLE001 - 读不到部件时按“无样式名”继续
        return {}
    try:
        from doc_tool.adapters.preflight import census_paragraph_styles

        census = census_paragraph_styles(parts)
        return {str(key): str(getattr(value, "name", "") or "") for key, value in census.items()}
    except Exception:  # noqa: BLE001
        return {}


def resolve_for_source(preset_name: str, src) -> tuple:
    """把命名预设适配到源文档。

    返回 ``(resolved|None, preset_info: dict, warnings: list[str])``：
    未知预设只产生提醒（不抛错、不阻断导入）。
    """
    warnings: List[str] = []
    name = str(preset_name or "").strip()
    if not name:
        return None, {}, warnings
    try:
        presets = IntakePresets()
        preset = presets.find(name)
        if preset is None:
            names = "、".join(item.name for item in presets.presets[:8]) or "（暂无）"
            warnings.append(
                "未找到导入预设「{0}」：按自动识别继续（可用预设：{1}）".format(name, names)
            )
            return None, {}, warnings
        resolved = presets.resolve(preset, source_style_names(src))
    except Exception as exc:  # noqa: BLE001 - 预设不可用不阻断导入
        warnings.append("导入预设不可用（{0}）：按自动识别继续".format(exc))
        return None, {}, warnings
    info = {
        "presetId": resolved.presetId,
        "name": resolved.name,
        "mapping": {str(k): int(v) for k, v in resolved.mapping.items()},
        "unmatched": list(resolved.unmatched),
        "warnings": list(resolved.warnings),
        "settings": dict(resolved.settings),
        "usedFallback": bool(resolved.used_fallback),
    }
    warnings.extend(list(resolved.warnings or [])[:5])
    if resolved.used_fallback:
        warnings.append(resolved.summary_line())
    elif resolved.mapping:
        warnings.append(
            "已应用导入预设「{0}」：{1} 个样式".format(resolved.name, len(resolved.mapping))
        )
    return resolved, info, warnings


def save_from_import(name: str, src, mapping=None, *, style_names=None) -> tuple:
    """把本次导入实际使用的映射保存为命名预设（按名称更新，不重复）。

    返回 ``(saved_name, warnings)``；没有可用映射时如实提醒且不写空预设。
    """
    warnings: List[str] = []
    target = str(name or "").strip()
    if not target:
        return "", warnings
    resolved_mapping = {str(k): int(v) for k, v in dict(mapping or {}).items()}
    if not resolved_mapping:
        try:
            from doc_tool.adapters.preflight import preflight as _auto_preflight

            auto = _auto_preflight(str(src), allow_missing_headings=True, heading_style_map=None)
            resolved_mapping = {
                str(k): int(v)
                for k, v in dict(getattr(auto, "heading_style_map", None) or {}).items()
            }
            if resolved_mapping and not style_names:
                census = getattr(auto, "style_census", None) or {}
                style_names = {
                    str(key): str(getattr(value, "name", "") or "")
                    for key, value in census.items()
                }
        except Exception:  # noqa: BLE001
            resolved_mapping = {}
    if not resolved_mapping:
        warnings.append(
            "未保存预设「{0}」：本次为自动识别，没有可保存的样式映射".format(target)
        )
        return "", warnings
    names = style_names if style_names else source_style_names(src)
    names = {str(k): str(v) for k, v in dict(names or {}).items() if str(k) in resolved_mapping}
    try:
        presets = IntakePresets()
        existing = presets.find(target)
        saved = presets.save(
            target, resolved_mapping, style_names=names,
            preset_id=getattr(existing, "presetId", "") or "",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append("保存导入预设失败：{0}".format(exc))
        return "", warnings
    warnings.append("已保存导入预设「{0}」（{1} 个样式）".format(saved.name, len(resolved_mapping)))
    return saved.name, warnings



__all__ = [
    "IntakePreset", "IntakePresets", "ResolvedPreset", "preset_file",
    "resolve_for_source", "save_from_import", "source_style_names",
]