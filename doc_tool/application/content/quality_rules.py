# -*- coding: utf-8 -*-
"""质量规则唯一入口：共享配置优先、旧配置兼容，诊断不再静默丢失。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

QUALITY_RULES_FILE = "quality_rules.json"
VALID_SEVERITIES = ("error", "warning", "info")


@dataclass
class QualityRule:
    rule_id: str
    enabled: bool = True
    severity: str = "warning"
    params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            self.severity = "warning"

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "enabled": self.enabled, "severity": self.severity, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict) -> "QualityRule":
        severity = str(data.get("severity", "warning"))
        return cls(
            rule_id=str(data.get("rule_id", data.get("ruleId", ""))),
            enabled=bool(data.get("enabled", True)),
            severity=severity if severity in VALID_SEVERITIES else "warning",
            params=dict(data.get("params") or {}),
        )


def default_rules(document_type: str) -> List[QualityRule]:
    common = [
        QualityRule("duplicate_title", True, "warning"),
        QualityRule("term_case", True, "info"),
        QualityRule("todo_residual", True, "warning"),
        # 表格结构契约：阻断类问题按 error（不修必定合并失败），
        # 不阻断的排版偏差由检查器内部固定为 warning。
        QualityRule("markdown_structure", True, "error"),
        # Mermaid 流程图与图表语法：错误语法阻断合并。
        QualityRule("mermaid_syntax", True, "error"),
        # Markdown 标题格式：# 后面缺少空格导致无法被 Word 识别为标题。
        QualityRule("heading_format", True, "warning"),
        QualityRule("sensitive_info", True, "warning", {"patterns": [
            {"name": "手机号", "regex": r"(?<!\d)1[3-9]\d{9}(?!\d)"},
            {"name": "身份证号", "regex": r"(?<!\d)\d{17}[0-9Xx](?!\d)"},
            {"name": "明文口令", "regex": r"(?i)(?:密码|口令|password)\s*[:：=]\s*\S+"},
        ]}),
    ]
    if document_type == "requirement":
        common.extend([
            QualityRule("required_section", True, "error", {"titles": ["范围", "总体描述"]}),
            QualityRule("field_completeness", True, "warning", {"fields": {}}),
            QualityRule("numbering_uniqueness", True, "error"),
            QualityRule("interface_table_structure", True, "warning"),
        ])
    elif document_type == "design":
        common.extend([
            QualityRule("required_section", True, "warning", {"titles": ["功能描述", "核心逻辑"]}),
            QualityRule("numbering_uniqueness", True, "error"),
        ])
    else:
        common.append(QualityRule("numbering_uniqueness", True, "warning"))
    # 新契约必须显式选范围并启用，不改变旧文档的默认检查口径。
    common.extend([
        QualityRule("module_sections", False, "warning", {"paths": [], "sections": [], "mode": "file", "section_level": 4}),
        QualityRule("table_schema", False, "warning", {"paths": [], "schemas": []}),
    ])
    return common


@dataclass(frozen=True)
class RuleConfigDiagnostic:
    code: str
    message: str
    severity: str = "error"
    rule_id: str = ""
    entry_index: int = -1
    line_no: int = 0

    def to_dict(self):
        return {"code": self.code, "message": self.message, "severity": self.severity,
                "ruleId": self.rule_id, "entryIndex": self.entry_index, "line": self.line_no}


@dataclass
class RulesLoadResult:
    rules: List[QualityRule]
    source: str
    path: str
    fingerprint: str
    diagnostics: List[RuleConfigDiagnostic] = field(default_factory=list)
    raw_rules: Optional[list] = None
    fallback: bool = False

    @property
    def valid(self):
        return not any(x.severity == "error" for x in self.diagnostics)

    def to_dict(self):
        return {"source": self.source, "path": self.path, "fingerprint": self.fingerprint,
                "valid": self.valid, "fallbackToDefaults": self.fallback,
                "diagnostics": [x.to_dict() for x in self.diagnostics]}


def supported_rule_ids():
    return {rule.rule_id for kind in ("general", "requirement", "design") for rule in default_rules(kind)}


def validate_rule_payload(items):
    """在反序列化为宽容的旧 QualityRule 之前验证原值；保存与运行共用。"""
    diagnostics = []
    if not isinstance(items, list):
        return [RuleConfigDiagnostic("rules_type", "rules 应为列表。")]
    seen = set()
    supported = supported_rule_ids()
    for i, value in enumerate(items):
        if not isinstance(value, dict):
            diagnostics.append(RuleConfigDiagnostic("rule_type", "rules[{0}] 应为对象。".format(i), entry_index=i))
            continue
        rid = value.get("rule_id", value.get("ruleId", ""))
        def issue(code, message, severity="error"):
            diagnostics.append(RuleConfigDiagnostic(code, "rules[{0}] {1}：{2}".format(i, rid, message), severity, str(rid), i))
        if not isinstance(rid, str) or not rid.strip():
            issue("rule_id", "rule_id 应为非空字符串")
            continue
        if "rule_id" in value and "ruleId" in value and value["rule_id"] != value["ruleId"]:
            issue("rule_id_conflict", "rule_id 与 ruleId 不一致，不能静默选择")
        if rid in seen:
            issue("duplicate_rule", "规则重复，不能使用最后一项静默覆盖")
        seen.add(rid)
        enabled = value.get("enabled", True)
        if type(enabled) is not bool:
            issue("enabled_type", "enabled 应为布尔值，不接受字符串或数字")
        if value.get("severity", "warning") not in VALID_SEVERITIES:
            issue("severity", "severity 只能是 error/warning/info")
        params = value.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            issue("params_type", "params 应为对象")
            continue
        if rid not in supported:
            issue("unknown_rule", "当前版本不支持此规则，未执行", "info" if enabled is False else "error")
            continue
        if enabled is not True:
            continue  # 已关闭项不执行语义参数，不擅自把关闭恢复成启用。
        if rid == "required_section":
            titles = params.get("titles", [])
            if not isinstance(titles, list) or any(not isinstance(x, str) or not x.strip() for x in titles):
                issue("titles_type", "titles 应为非空标题的列表")
        if rid == "field_completeness":
            fields = params.get("fields", {})
            if not isinstance(fields, dict):
                issue("fields_type", "fields 应为字段配置映射")
            else:
                for name, config in fields.items():
                    if not isinstance(name, str) or not name.strip():
                        issue("field_name", "字段名应为非空字符串")
                        continue
                    if not isinstance(config, (str, dict)):
                        issue("field_type", "字段「{0}」应为正则字符串或对象".format(name))
                        continue
                    data = config if isinstance(config, dict) else {"regex": config}
                    expression = data.get("regex", re.escape(name))
                    _validate_regex(expression, "字段「{0}」".format(name), issue)
                    count = data.get("count", 1)
                    try:
                        if isinstance(count, bool) or not isinstance(count, (int, str)) or int(count) < 1:
                            raise ValueError("not a positive integer")
                    except (TypeError, ValueError, OverflowError):
                        issue("field_count", "字段「{0}」count 应为正整数".format(name))
        if rid == "sensitive_info":
            patterns = params.get("patterns", [])
            if not isinstance(patterns, list):
                issue("patterns_type", "patterns 应为列表")
            else:
                for pattern in patterns:
                    if not isinstance(pattern, dict):
                        issue("pattern_type", "敏感信息模式应为对象")
                    else:
                        _validate_regex(pattern.get("regex"), "敏感信息模式", issue)
        if rid in ("module_sections", "table_schema"):
            from doc_tool.application.content.document_contracts import validate_contract_params
            for message in validate_contract_params(rid, params):
                issue("contract_params", message)
    return diagnostics


def _validate_regex(expression, label, issue):
    if not isinstance(expression, str) or not expression:
        issue("regex_type", label + " regex 应为非空字符串")
        return
    try:
        re.compile(expression)
    except re.error as exc:
        issue("invalid_regex", label + "正则无效（{0}），该规则未执行".format(exc))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 字段重复：{0}".format(key))
        result[key] = value
    return result


class QualityRulesConfig:
    def __init__(self, state_dir: Path, document_type: str, *, writable: bool = True) -> None:
        self.state_dir = Path(state_dir)
        self.document_type = document_type
        self.writable = writable
        # 标准项目使用现有共享位置；旧的独立 state_dir 调用保持原路径语义。
        self.project_root = self.state_dir.parent if self.state_dir.name == ".state" else None
        if self.project_root is not None:
            from doc_tool.application.quality_location import QUALITY_DIR, QUALITY_RULES_NAME
            self.file = self.project_root / QUALITY_DIR / QUALITY_RULES_NAME
        else:
            self.file = self.state_dir / QUALITY_RULES_FILE

    def defaults(self) -> List[QualityRule]:
        return default_rules(self.document_type)

    def _location(self):
        from doc_tool.application.quality_location import QualityLocation, resolve_quality_location, QUALITY_RULES_NAME
        if self.project_root is not None:
            return resolve_quality_location(self.project_root, QUALITY_RULES_NAME, legacy_name=QUALITY_RULES_FILE)
        return QualityLocation(self.file, "legacy" if self.file.is_file() else "none")

    def load_result(self) -> RulesLoadResult:
        """一次读取返回规则、实际来源及诊断；不迁移、不修改文件。"""
        location = self._location()
        path = location.path
        label = path.relative_to(self.project_root).as_posix() if self.project_root is not None else path.name
        if location.source == "none":
            return RulesLoadResult(self.defaults(), "builtin", label, "builtin:" + self.document_type)
        fingerprint = "unreadable"
        try:
            raw = path.read_bytes()
            fingerprint = hashlib.sha256(raw).hexdigest()
            data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
                raise ValueError("配置应为包含 rules 列表的对象")
        except (OSError, UnicodeError, ValueError) as exc:
            diagnostic = RuleConfigDiagnostic("config_unavailable", "{0} 配置不可用，回退默认仅供继续诊断；不能认定配置检查通过：{1}".format(label, exc), line_no=getattr(exc, "lineno", 0))
            return RulesLoadResult(self.defaults(), location.source, label, fingerprint, [diagnostic], fallback=True)
        diagnostics = validate_rule_payload(data["rules"])
        if data.get("documentType") not in (None, "", self.document_type):
            diagnostics.append(RuleConfigDiagnostic("document_type", "配置 documentType 与目标项目不一致。"))
        invalid = {x.entry_index for x in diagnostics if x.severity == "error" and x.entry_index >= 0}
        rules = [QualityRule.from_dict(value) for i, value in enumerate(data["rules"]) if i not in invalid]
        return RulesLoadResult(rules, location.source, label, fingerprint, diagnostics, data["rules"])

    def load(self) -> List[QualityRule]:
        """兼容旧列表接口；主流程应读取 load_result 的配置诊断。"""
        return self.load_result().rules

    def save(self, rules: List[QualityRule]) -> None:
        self.save_payload([rule.to_dict() for rule in rules])

    def save_payload(self, payload) -> None:
        """资源设置按原输入字段风格保存，兼容规范包 ruleId，避免丢扩展字段。"""
        if not self.writable:
            raise PermissionError("只读项目不可保存质量规则配置")
        if self.file.exists() and not self.file.is_file():
            raise ValueError("规则保存目标不是文件，未写入配置")
        errors = [x.message for x in validate_rule_payload(payload) if x.severity == "error"]
        if errors:
            raise ValueError("；".join(errors))
        data = {}
        if self.file.is_file():
            try:
                previous = json.loads(self.file.read_text(encoding="utf-8-sig"))
                if isinstance(previous, dict):
                    data.update(previous)
            except (OSError, UnicodeError, ValueError):
                pass  # 显式保存才可修复损坏；load_result 本身永不写回。
        data.update({"documentType": self.document_type, "rules": payload})
        encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".json.tmp")
        try:
            tmp.write_text(encoded, encoding="utf-8")
            try:
                os.replace(str(tmp), str(self.file))
            except OSError:
                shutil.move(str(tmp), str(self.file))
        finally:
            if tmp.exists():
                tmp.unlink()

    def rule_map(self) -> Dict[str, QualityRule]:
        return {rule.rule_id: rule for rule in self.load()}

    def get(self, rule_id: str) -> Optional[QualityRule]:
        return self.rule_map().get(rule_id)
