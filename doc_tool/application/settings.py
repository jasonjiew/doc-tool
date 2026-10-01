# -*- coding: utf-8 -*-
"""项目设置服务（V2.8 28-D / 4.3）。

设置页只需渲染本模块返回的**表单模型**，并把修改交回 ``save_settings``：

- 基本信息与样式（来自清单，样式枚举复用现有推导）；
- **变量 / 术语 / 规则 / 门禁**：写入项目 ``quality/``；
- 保存前**校验**，非法值定位到字段名；只读项目拒绝写入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from doc_tool.application.quality_location import (
    QUALITY_DIR,
    QUALITY_RULES_NAME,
    QUALITY_TERMS_NAME,
    resolve_quality_location,
)

#: 变量文件名（项目内）。
QUALITY_VARIABLES_NAME = "variables.json"


@dataclass
class FieldSpec:
    """一个可编辑字段（供界面直接渲染）。"""

    key: str
    label: str
    value: object = ""
    kind: str = "text"
    options: List[str] = field(default_factory=list)
    editable: bool = True
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "kind": self.kind,
            "options": list(self.options),
            "editable": self.editable,
            "hint": self.hint,
        }


@dataclass
class SettingsModel:
    """设置页模型（只读）。"""

    sections: Dict[str, List[FieldSpec]] = field(default_factory=dict)
    writable: bool = True
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "writable": self.writable,
            "warnings": list(self.warnings),
            "sections": {
                name: [item.to_dict() for item in items]
                for name, items in self.sections.items()
            },
        }

    def field(self, section: str, key: str) -> Optional[FieldSpec]:
        for item in self.sections.get(section, []):
            if item.key == key:
                return item
        return None


@dataclass
class SaveOutcome:
    """保存结果。"""

    ok: bool = False
    written: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "written": list(self.written),
            "errors": dict(self.errors),
            "message": self.message,
        }


def load_settings(project_root: Union[str, Path]) -> SettingsModel:
    """构造设置页模型：基本信息 + 样式 + 变量/术语/规则/门禁。"""
    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root)
    manifest = ProjectManifest.load(root)
    model = SettingsModel(writable=manifest.is_writable())
    model.sections[基本信息] = [
        FieldSpec("documentName", "文档名称", manifest.documentName),
        FieldSpec("documentNo", "文档编号", manifest.documentNo),
        FieldSpec("documentVersion", "文档版本", manifest.documentVersion),
        FieldSpec("documentKind", "文档类别", manifest.documentKind, hint="来自规范包，留空表示未声明"),
        FieldSpec("schemaVersion", "模式版本", manifest.schemaVersion, editable=False),
    ]
    model.sections[样式] = [
        FieldSpec("bodyStyle", "正文样式", manifest.bodyStyle),
    ] + [
        FieldSpec("heading{0}".format(level), "标题 {0} 级样式".format(level), style)
        for level, style in sorted((manifest.headingStyles or {}).items())
    ]
    model.sections[变量] = [
        FieldSpec(key, key, value)
        for key, value in sorted((manifest.variables or {}).items())
    ]
    terms = _read_json(_quality_file(root, QUALITY_TERMS_NAME, "terms")) or {}
    model.sections[术语] = [
        FieldSpec("terms", "术语表", terms.get("terms", []), kind="list")
    ]
    rules = _read_json(_quality_file(root, QUALITY_RULES_NAME, "rules")) or {}
    model.sections[规则] = [
        FieldSpec("rules", "检查规则", rules.get("rules", []), kind="list")
    ]
    model.sections[门禁] = [
        FieldSpec("qualitySource", "检查策略来源", manifest.qualitySource, kind="choice", options=["", "pack", "project", "builtin"]),
    ]
    if not model.writable:
        model.warnings.append("当前项目为只读，不可保存设置。")
    return model


def save_settings(
    project_root: Union[str, Path],
    changes: Dict[str, object],
    *,
    writable: Optional[bool] = None,
) -> SaveOutcome:
    """保存设置：先**校验**，非法值定位到字段名；只读项目拒绝写入。

    只写入项目内 ``quality/`` 与清单可写字段；任何校验失败都**不写任何文件**。
    """
    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root)
    manifest = ProjectManifest.load(root)
    outcome = SaveOutcome()
    allowed = manifest.is_writable() if writable is None else bool(writable)
    if not allowed:
        outcome.message = "只读项目不可保存设置。"
        outcome.errors["__project__"] = outcome.message
        return outcome

    payload = dict(changes or {})
    errors: Dict[str, str] = {}
    version = payload.get("documentVersion")
    if version is not None and not str(version).strip():
        errors["documentVersion"] = "版本号不能为空"
    source = payload.get("qualitySource")
    if source is not None and str(source) not in ("", "pack", "project", "builtin"):
        errors["qualitySource"] = "检查策略来源只能是 pack/project/builtin 或留空"
    for key, value in payload.items():
        if key.startswith("heading"):
            if not str(value).strip():
                errors[key] = "标题样式不能为空"
        if key == "bodyStyle" and not str(value).strip():
            errors["bodyStyle"] = "正文样式不能为空"
    terms = payload.get("terms")
    if terms is not None and not _is_string_list(terms):
        errors["terms"] = "术语表应为字符串列表"
    rules = payload.get("rules")
    if rules is not None and not isinstance(rules, list):
        errors["rules"] = "规则表应为列表"
    variables = payload.get("variables")
    if variables is not None and not isinstance(variables, dict):
        errors["variables"] = "变量应为「名称 -> 值」映射"
    outcome.errors = errors
    if errors:
        outcome.message = "有 {0} 项参数需修正，未写入任何文件。".format(len(errors))
        return outcome

    # 先改内存清单并校验，通过后再写入
    if version is not None:
        manifest.documentVersion = str(version)
    if source is not None:
        manifest.qualitySource = str(source) or ""
    if "documentKind" in payload:
        manifest.documentKind = str(payload.get("documentKind") or "")
    if "bodyStyle" in payload:
        manifest.bodyStyle = str(payload.get("bodyStyle") or "")
    for level in list(manifest.headingStyles or {}):
        key = "heading{0}".format(level)
        if key in payload:
            manifest.headingStyles[level] = str(payload[key])
    if isinstance(variables, dict):
        manifest.variables = {str(k): str(v) for k, v in variables.items()}
    try:
        manifest.save(root)
    except Exception as exc:  # noqa: BLE001 - 清单校验失败必须作为字段错误返回
        outcome.errors["__manifest__"] = str(exc)
        outcome.message = "清单校验失败，未保存：{0}".format(exc)
        return outcome
    outcome.written.append(str(root / "project.yml"))

    quality = root / QUALITY_DIR
    quality.mkdir(parents=True, exist_ok=True)
    if terms is not None:
        target = quality / QUALITY_TERMS_NAME
        target.write_text(json.dumps({"terms": list(terms)}, ensure_ascii=False, indent=2), encoding="utf-8")
        outcome.written.append(str(target))
    if rules is not None:
        target = quality / QUALITY_RULES_NAME
        target.write_text(json.dumps({"rules": list(rules)}, ensure_ascii=False, indent=2), encoding="utf-8")
        outcome.written.append(str(target))
    outcome.ok = True
    outcome.message = "已保存 {0} 个文件。".format(len(outcome.written))
    return outcome


def _quality_file(root: Path, name: str, legacy_name: str) -> Path:
    location = resolve_quality_location(root, name, legacy_name="{0}.json".format(legacy_name))
    return location.path


def _read_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_string_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


#: 分区名（中文，界面直接使用）。
基本信息 = "基本信息"
样式 = "样式"
变量 = "变量"
术语 = "术语"
规则 = "规则"
门禁 = "门禁"