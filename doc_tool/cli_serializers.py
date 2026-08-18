# -*- coding: utf-8 -*-
"""CLI 结构化结果的 human/JSON/SARIF/JUnit 序列化。"""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from doc_tool.application.cli_commands import CommandResult


def _sarif_driver_name() -> str:
    """SARIF 工具驱动名（公共显示名）。"""
    from doc_tool.domain.branding import APP_DISPLAY_NAME

    return APP_DISPLAY_NAME


def serialize_json(result: CommandResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def serialize_human(result: CommandResult) -> str:
    lines = []
    for item in result.results:
        marker = "成功" if item.success else "失败"
        line = "[{0}] {1}".format(marker, item.project)
        if item.error_code:
            line += " ({0})".format(item.error_code)
        lines.append(line)
        data = item.data
        if isinstance(data, dict) and data.get("message"):
            lines.append("  {0}".format(data["message"]))
        # 搜索命中：human 模式必须能看到命中内容，否则 ``doc-tool search``
        # 只打印一行成功、命中不可见。
        hits = getattr(data, "hits", None) if not isinstance(data, dict) else data.get("hits")
        if hits is not None:
            total = getattr(data, "total", len(hits)) if not isinstance(data, dict) else data.get("total", len(hits))
            truncated = getattr(data, "truncated", False) if not isinstance(data, dict) else data.get("truncated", False)
            shown = 0
            for hit in hits[:20]:
                rel_path = getattr(hit, "rel_path", None) if not isinstance(hit, dict) else hit.get("rel_path")
                line_no = getattr(hit, "line_no", None) if not isinstance(hit, dict) else hit.get("line_no")
                text = getattr(hit, "text", "") if not isinstance(hit, dict) else hit.get("text", "")
                lines.append("  {0}:{1}  {2}".format(rel_path, line_no, text))
                shown += 1
            if truncated or len(hits) > shown:
                lines.append("  … 共 {0} 条命中（仅显示前 {1} 条，加 --limit 提高上限）".format(total, shown))
            elif total:
                lines.append("  （共 {0} 条命中）".format(total))
        # 重编号预览/结果：human 模式必须能看到 old → new 清单。
        preview = data.get("preview") if isinstance(data, dict) else None
        if preview is not None:
            applied = data.get("applied") if isinstance(data, dict) else False
            lines.append(
                "{0} {1} 项：".format(
                    "已重编号" if applied else "将重编号", len(preview)
                )
            )
            for entry in preview[:50]:
                lines.append("  {0} → {1}".format(entry.get("old"), entry.get("new")))
            if len(preview) > 50:
                lines.append("  … 共 {0} 项".format(len(preview)))
        if item.suggested_action:
            lines.append("  建议：{0}".format(item.suggested_action))
        if item.issues:
            lines.append("  问题：{0} 项".format(len(item.issues)))
    return "\n".join(lines)


def _sarif_uri(project: str, rel_path: str) -> str:
    if not rel_path:
        return Path(project).as_uri()
    candidate = Path(rel_path)
    if not candidate.is_absolute():
        candidate = Path(project) / rel_path
    return candidate.resolve().as_uri()


def serialize_sarif(result: CommandResult) -> str:
    rules = {}
    findings = []
    for item in result.results:
        for issue in item.issues:
            rule_id = issue.error_code or issue.issue_type
            rules.setdefault(rule_id, {
                "id": rule_id,
                "name": issue.issue_type,
                "shortDescription": {"text": issue.message},
                "help": {"text": issue.suggested_action or issue.message},
            })
            sarif_result = {
                "ruleId": rule_id,
                "level": {"error": "error", "warning": "warning", "info": "note"}.get(issue.severity, "note"),
                "message": {"text": issue.message},
            }
            if issue.rel_path:
                location = {
                    "physicalLocation": {
                        "artifactLocation": {"uri": _sarif_uri(item.project, issue.rel_path)},
                    }
                }
                if issue.line_no is not None:
                    location["physicalLocation"]["region"] = {"startLine": issue.line_no}
                sarif_result["locations"] = [location]
            findings.append(sarif_result)
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": _sarif_driver_name(), "rules": list(rules.values())}},
            "results": findings,
        }],
    }
    return json.dumps(document, ensure_ascii=False, indent=2)


def serialize_junit(result: CommandResult) -> str:
    suites = ET.Element("testsuites")
    total_tests = total_failures = 0
    for item in result.results:
        document_type = "project"
        if isinstance(item.data, dict):
            document_type = str(item.data.get("documentType") or document_type)
        failures = item.issues or ([] if item.success else [None])
        tests = max(1, len(failures))
        suite = ET.SubElement(suites, "testsuite", {
            "name": "{0}:{1}".format(Path(item.project).name, document_type),
            "tests": str(tests),
            "failures": str(len(failures)),
        })
        total_tests += tests
        total_failures += len(failures)
        if not failures:
            ET.SubElement(suite, "testcase", {"name": document_type, "classname": item.project})
        else:
            for index, issue in enumerate(failures, start=1):
                name = issue.issue_type if issue is not None else document_type
                case = ET.SubElement(suite, "testcase", {
                    "name": "{0}-{1}".format(name, index), "classname": item.project,
                })
                message = issue.message if issue is not None else item.error_code or "validation failed"
                failure = ET.SubElement(case, "failure", {
                    "message": message,
                    "type": issue.error_code if issue is not None and issue.error_code else item.error_code,
                })
                failure.text = issue.suggested_action if issue is not None else item.suggested_action
    suites.set("tests", str(total_tests))
    suites.set("failures", str(total_failures))
    return ET.tostring(suites, encoding="unicode", xml_declaration=True)
