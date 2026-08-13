# -*- coding: utf-8 -*-
"""项目级质量规则配置。"""

from __future__ import annotations

import json
import os
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
            rule_id=str(data.get("rule_id", "")),
            enabled=bool(data.get("enabled", True)),
            severity=severity if severity in VALID_SEVERITIES else "warning",
            params=dict(data.get("params") or {}),
        )


def default_rules(document_type: str) -> List[QualityRule]:
    common = [
        QualityRule("duplicate_title", True, "warning"),
        QualityRule("term_case", True, "info"),
        QualityRule("todo_residual", True, "warning"),
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
    return common


class QualityRulesConfig:
    def __init__(self, state_dir: Path, document_type: str, *, writable: bool = True) -> None:
        self.file = Path(state_dir) / QUALITY_RULES_FILE
        self.document_type = document_type
        self.writable = writable

    def defaults(self) -> List[QualityRule]:
        return default_rules(self.document_type)

    def load(self) -> List[QualityRule]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self.defaults()
        items = data.get("rules") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return self.defaults()
        parsed = [QualityRule.from_dict(item) for item in items if isinstance(item, dict)]
        parsed = [item for item in parsed if item.rule_id]
        # 「rules」键存在且为列表时按原样返回（允许空列表=全部关闭），
        # 仅缺键/损坏时回退默认配置。
        return parsed

    def save(self, rules: List[QualityRule]) -> None:
        if not self.writable:
            raise PermissionError("只读项目不可保存质量规则配置")
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"documentType": self.document_type, "rules": [r.to_dict() for r in rules]}, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.replace(str(tmp), str(self.file))
        except OSError:
            shutil.move(str(tmp), str(self.file))

    def rule_map(self) -> Dict[str, QualityRule]:
        return {rule.rule_id: rule for rule in self.load()}

    def get(self, rule_id: str) -> Optional[QualityRule]:
        return self.rule_map().get(rule_id)
