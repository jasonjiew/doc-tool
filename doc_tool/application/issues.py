# -*- coding: utf-8 -*-
"""统一问题记录及管线、校验报告、lint 来源归一。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from doc_tool.domain.errors import DocToolError


SOURCE_PIPELINE = "pipeline"
SOURCE_VALIDATION = "validation"
SOURCE_LINT = "lint"

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_LINT_SEVERITIES = {
    "duplicate_title": SEVERITY_WARNING,
    "todo_residual": SEVERITY_WARNING,
    "term_case": SEVERITY_INFO,
}

# 校验报告 detail 里的路径可含空格与中文（如 ``第1章 概述/_index.md:3``）。
# 仅用「非空格字符类」会在空格处截断路径（得到 ``概述/_index.md`` 而非完整
# 目录）；先试行首锚定的空格友好模式（detail 通常以路径开头），再退回原
# 无空格模式定位行中间的路径，避免把前置说明文字并入路径。
_LOCATION_PATTERNS = (
    # 行首锚定、路径允许空格与中文（``content/requirement/第1章 概述/_index.md:3``），
    # 但路径内不允许冒号——避免把行首的「检查名:」前缀并入 rel_path。
    re.compile(r"^(?P<path>[^:：]+?\.(?:md|markdown))[:：](?P<line>\d+)", re.I),
    # 非锚定：detail 形如「检查名: 路径:行」时（validate_docx 报告为
    # ``[FAIL] {check.name}: {detail}``），从冒号后定位路径；路径允许空格中文。
    re.compile(r"(?:^|[:：]\s*)(?P<path>[^:：]+?\.(?:md|markdown))[:：](?P<line>\d+)", re.I),
    # 中文「第 N 行」说明格式。
    re.compile(r"(?P<path>[^\s，,]+\.(?:md|markdown)).{0,8}?第\s*(?P<line>\d+)\s*行", re.I),
)


@dataclass(frozen=True)
class IssueRecord:
    """问题中心与机器可读输出共用的稳定记录模型。"""

    source: str
    issue_type: str
    document_type: str
    severity: str
    rel_path: str
    line_no: Optional[int]
    error_code: Optional[str]
    message: str
    suggested_action: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        return {
            "source": data["source"],
            "type": data["issue_type"],
            "documentType": data["document_type"],
            "severity": data["severity"],
            "file": data["rel_path"],
            "line": data["line_no"],
            "errorCode": data["error_code"],
            "message": data["message"],
            "suggestedAction": data["suggested_action"],
            "generatedAt": data["generated_at"],
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _error_catalog() -> dict:
    catalog = {}
    pending = list(DocToolError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        code = getattr(cls, "code", None)
        if code:
            catalog[code] = cls
    return catalog


def severity_for_error_code(error_code: Optional[str]) -> str:
    """已登记错误均为阻断错误；未知/空错误码降级为 warning（保留可见性，
    避免生产未知错误在 UI 按 info 过滤后丢失）。"""
    return SEVERITY_ERROR if error_code in _error_catalog() else SEVERITY_WARNING


def error_metadata(error_code: Optional[str]) -> tuple[str, str]:
    cls = _error_catalog().get(error_code or "")
    if cls is None:
        return "", "请查看任务日志获取更多信息。"
    return cls.user_message, cls.suggested_action


def issue_type_for_stage(stage: str) -> str:
    # Word 刷新失败本质是「刷新后校验」类问题：归入 validation，否则 UI
    # 过滤「校验类问题」时刷新失败会被漏掉（旧逻辑统一归 build）。
    if "validate" in (stage or ""):
        return "validation"
    if "refresh" in (stage or ""):
        return "validation"
    return "build"


def issues_from_pipeline(
    events: Iterable[object], document_type: str, generated_at: str = ""
) -> List[IssueRecord]:
    generated = generated_at or utc_now()
    records: List[IssueRecord] = []
    for event in events:
        if getattr(event, "status", "") not in ("failed", "cancelled"):
            continue
        code = getattr(event, "error_code", None)
        default_message, advice = error_metadata(code)
        detail = str(getattr(event, "detail", "") or default_message or "任务失败")
        metrics = getattr(event, "metrics", {}) or {}
        line_value = metrics.get("line")
        if line_value is None:
            line_value = metrics.get("lineNo")
        try:
            line_no = int(line_value) if line_value is not None else None
        except (TypeError, ValueError):
            line_no = None
        records.append(IssueRecord(
            source=SOURCE_PIPELINE,
            issue_type=issue_type_for_stage(str(getattr(event, "stage", ""))),
            document_type=document_type,
            severity=severity_for_error_code(code),
            rel_path=str(metrics.get("rel_path") or metrics.get("file") or ""),
            line_no=line_no,
            error_code=code,
            message=detail,
            suggested_action=advice,
            generated_at=generated,
        ))
    return records


def _parse_location(detail: str) -> tuple[str, Optional[int]]:
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(detail)
        if match:
            return match.group("path").replace("\\", "/"), int(match.group("line"))
    return "", None


def issues_from_validation_report(
    report_path: Path, document_type: str, generated_at: str = ""
) -> List[IssueRecord]:
    path = Path(report_path)
    try:
        text = path.read_text(encoding="utf-8")
        generated = generated_at or datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
    except (OSError, UnicodeError):
        return []
    records: List[IssueRecord] = []
    for raw_line in text.splitlines():
        match = re.match(r"^\s*-\s*\[FAIL\]\s*(.*)$", raw_line, re.I)
        if not match:
            continue
        detail = match.group(1).strip() or "校验失败（报告条目缺少说明）"
        rel_path, line_no = _parse_location(detail)
        records.append(IssueRecord(
            source=SOURCE_VALIDATION,
            issue_type="validation",
            document_type=document_type,
            severity=SEVERITY_ERROR,
            rel_path=rel_path,
            line_no=line_no,
            error_code="E2002",
            message=detail,
            suggested_action="请根据校验报告修正对应章节或资源后重试。",
            generated_at=generated,
        ))
    return records


def issues_from_lint(
    issues: Iterable[object], document_type: str = "", generated_at: str = ""
) -> List[IssueRecord]:
    generated = generated_at or utc_now()
    records: List[IssueRecord] = []
    for issue in issues:
        rule = str(getattr(issue, "rule", "lint") or "lint")
        rel_path = str(getattr(issue, "rel_path", "") or "")
        inferred_type = document_type
        if not inferred_type:
            first = rel_path.replace("\\", "/").split("/", 1)[0]
            inferred_type = first if first in ("general", "requirement", "design") else "general"
        records.append(IssueRecord(
            source=SOURCE_LINT,
            issue_type=rule,
            document_type=inferred_type,
            severity=str(getattr(issue, "severity", "") or _LINT_SEVERITIES.get(rule, SEVERITY_INFO)),
            rel_path=rel_path,
            line_no=getattr(issue, "line_no", None),
            error_code=None,
            message=str(getattr(issue, "message", "") or rule),
            suggested_action="请修改对应内容后重新运行检查。",
            generated_at=generated,
        ))
    return records


def filter_issues(
    issues: Iterable[IssueRecord], *, issue_type: str = "", document_type: str = "",
    severity: str = "", rel_path: str = ""
) -> List[IssueRecord]:
    return [
        issue for issue in issues
        if (not issue_type or issue.issue_type == issue_type)
        and (not document_type or issue.document_type == document_type)
        and (not severity or issue.severity == severity)
        and (not rel_path or issue.rel_path == rel_path)
    ]


def severity_summary(issues: Iterable[IssueRecord]) -> dict:
    summary = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 0, SEVERITY_INFO: 0}
    for issue in issues:
        summary[issue.severity if issue.severity in summary else SEVERITY_INFO] += 1
    return summary
