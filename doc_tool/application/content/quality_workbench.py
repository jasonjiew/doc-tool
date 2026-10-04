# -*- coding: utf-8 -*-
"""V4.2 42-C：问题工作台的服务层事实（分组、时点、过期与基线比较）。

只做纯数据整理，不建第二套问题模型：

- ``group_issues()``：按章节 / 规则 / 严重度分组，**统计保持实际总量**；
- ``IssueSnapshot``：一次检查的真实时点（范围、正文摘要、时刻、规则签名）；
- ``staleness()``：正文变化后把相关结果标「待重检」，未知显示未知；
- ``compare_snapshots()``：新增 / 消失 / 保留，缺基线显示「未知」。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: 分组维度。
GROUP_BY_CHAPTER = "chapter"
GROUP_BY_RULE = "rule"
GROUP_BY_SEVERITY = "severity"
GROUPS = (GROUP_BY_CHAPTER, GROUP_BY_RULE, GROUP_BY_SEVERITY)

#: 时点状态。
FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"


def rule_of(issue) -> str:
    """问题归属的规则/来源标识（IssueRecord 用 ``source``）。"""
    for attr in ("rule_id", "rule", "source"):
        value = getattr(issue, attr, "")
        if value:
            return str(value)
    return ""


def issue_key(issue) -> Tuple[str, int, str]:
    """问题的稳定身份：来源路径 + 行号 + 规则（用于基线比较）。"""
    return _issue_key(issue)


def compare_issues(baseline, current) -> "IssueComparison":
    """比较两个真实问题集合（``IssueRecord`` 或 ``LintIssue`` 均可）。

    缺基线（``baseline is None``）时返回未知——**不得把“本轮过滤零条”当成
    “整份工程无问题”**。
    """
    if baseline is None or current is None:
        return IssueComparison(known=False, reason="缺少上一轮结果，无法比较")
    before = set(_issue_key(item) for item in baseline)
    after = set(_issue_key(item) for item in current)
    return IssueComparison(
        known=True,
        added=sorted(after - before),
        removed=sorted(before - after),
        retained=sorted(before & after),
    )


def _issue_key(issue) -> Tuple[str, int, str]:
    rule = rule_of(issue)
    return (
        str(getattr(issue, "rel_path", "") or ""),
        int(getattr(issue, "line_no", 0) or 0),
        rule,
    )


def group_issues(issues: Iterable[object], *, by: str = GROUP_BY_CHAPTER) -> Dict[str, List[object]]:
    """按键分组（不改变条目本身，也不丢任何一条）。"""
    if by not in GROUPS:
        raise ValueError("未知分组维度：{0}（支持 {1}）".format(by, "/".join(GROUPS)))
    grouped: Dict[str, List[object]] = {}
    for issue in issues or ():
        if by == GROUP_BY_CHAPTER:
            key = str(getattr(issue, "rel_path", "") or "未定位")
        elif by == GROUP_BY_RULE:
            key = rule_of(issue) or "未命名规则"
        else:
            key = str(getattr(issue, "severity", "") or "未分级")
        grouped.setdefault(key, []).append(issue)
    return grouped


def group_summary(issues: Iterable[object], *, by: str = GROUP_BY_CHAPTER) -> List[Tuple[str, int]]:
    """分组计数：按数量降序，同数量按键名排序（稳定可比）。"""
    grouped = group_issues(issues, by=by)
    return sorted(
        ((key, len(value)) for key, value in grouped.items()),
        key=lambda item: (-item[1], item[0]),
    )


def severity_totals(issues: Iterable[object]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for issue in issues or ():
        key = str(getattr(issue, "severity", "") or "未分级")
        totals[key] = totals.get(key, 0) + 1
    return totals


def content_digest(index) -> str:
    """正文摘要：路径 + 行数 + 行文本 sha256（与检查缓存同口径）。"""
    lines = getattr(index, "lines", {}) or {}
    hasher = hashlib.sha256()
    for rel_path in sorted(lines):
        hasher.update(str(rel_path).encode("utf-8"))
        body = lines[rel_path] or []
        hasher.update(str(len(body)).encode("utf-8"))
        for line in body:
            hasher.update(str(line).encode("utf-8"))
            hasher.update(b"\n")
    return hasher.hexdigest()


@dataclass
class IssueSnapshot:
    """一次检查的真实时点事实（用于过期判断与基线比较）。"""

    scopeText: str = "整份"
    scopeKind: str = ""
    scopeChapters: List[str] = dataclass_field(default_factory=list)
    checkedAt: str = ""
    contentDigest: str = ""
    ruleSignature: str = ""
    issues: List[object] = dataclass_field(default_factory=list)
    unavailable: List[str] = dataclass_field(default_factory=list)

    @classmethod
    def build(cls, issues, *, index=None, scope=None, rules_signature="") -> "IssueSnapshot":
        scope_kind = str(getattr(scope, "kind", "") or "") if scope is not None else ""
        chapters = list(getattr(scope, "chapters", None) or []) if scope is not None else []
        if scope_kind == "project" or not scope_kind:
            scope_text = "整份"
        elif scope_kind == "chapters":
            scope_text = "所选 {0} 章".format(len(chapters))
        else:
            scope_text = "当前章"
        return cls(
            scopeText=scope_text,
            scopeKind=scope_kind or "project",
            scopeChapters=[str(item) for item in chapters],
            checkedAt=datetime.now(timezone.utc).isoformat(),
            contentDigest=content_digest(index) if index is not None else "",
            ruleSignature=str(rules_signature or ""),
            issues=list(issues or []),
        )

    def keys(self) -> List[Tuple[str, int, str]]:
        return sorted(_issue_key(issue) for issue in self.issues)

    def to_dict(self) -> Dict[str, object]:
        return {
            "scopeText": self.scopeText, "scopeKind": self.scopeKind,
            "scopeChapters": list(self.scopeChapters), "checkedAt": self.checkedAt,
            "contentDigest": self.contentDigest, "ruleSignature": self.ruleSignature,
            "count": len(self.issues),
            "unavailable": list(self.unavailable),
        }


def staleness(snapshot: Optional[IssueSnapshot], *, index=None, rules_signature="") -> str:
    """时点状态：``fresh`` / ``stale`` / ``unknown``（缺证据即未知）。"""
    if snapshot is None:
        return UNKNOWN
    if index is None:
        return UNKNOWN
    if not snapshot.contentDigest:
        return UNKNOWN
    if snapshot.contentDigest != content_digest(index):
        return STALE
    if rules_signature and snapshot.ruleSignature and snapshot.ruleSignature != str(rules_signature):
        return STALE
    return FRESH


@dataclass
class IssueComparison:
    """两个真实结果集的比较（缺基线时为未知，不冒充“无变化”）。"""

    known: bool = False
    added: List[Tuple[str, int, str]] = dataclass_field(default_factory=list)
    removed: List[Tuple[str, int, str]] = dataclass_field(default_factory=list)
    retained: List[Tuple[str, int, str]] = dataclass_field(default_factory=list)
    reason: str = ""

    def summary_lines(self) -> List[str]:
        if not self.known:
            return ["与基线比较：未知（{0}）".format(self.reason or "缺上一轮结果")]
        return [
            "与基线比较：新增 {0}｜消失 {1}｜保留 {2}".format(
                len(self.added), len(self.removed), len(self.retained)
            ),
        ]

    def to_dict(self) -> Dict[str, object]:
        return {
            "known": self.known, "reason": self.reason,
            "added": [list(item) for item in self.added],
            "removed": [list(item) for item in self.removed],
            "retained": [list(item) for item in self.retained],
        }


def compare_snapshots(
    baseline: Optional[IssueSnapshot], current: Optional[IssueSnapshot],
) -> IssueComparison:
    """新增/消失/保留；任一侧缺失时返回未知。"""
    if baseline is None or current is None:
        return IssueComparison(known=False, reason="缺少上一轮结果，无法比较")
    before, after = set(baseline.keys()), set(current.keys())
    return IssueComparison(
        known=True,
        added=sorted(after - before),
        removed=sorted(before - after),
        retained=sorted(before & after),
    )


def current_view_note(hidden: int, total: int) -> str:
    """个人「暂不处理」只改当前版本视图：报告保留真实问题。"""
    if hidden <= 0:
        return "当前视图显示全部 {0} 条问题".format(total)
    return "当前视图隐藏 {0} 条（仅本次查看；正式报告仍保留全部 {1} 条）".format(hidden, total)


# --- V4.2 42-D：规则试跑、成组修正与个人视图 -------------------------------


@dataclass
class RuleTrial:
    """一次规则试跑的真实结果（**不隐式保存**）。"""

    known: bool = False
    ruleId: str = ""
    #: 注意：字段名不能叫 ``field``，否则会遮蔽 dataclasses.field 工厂函数。
    fieldName: str = ""
    beforeValue: str = ""
    afterValue: str = ""
    comparison: Optional[IssueComparison] = None
    unsupported: List[str] = dataclass_field(default_factory=list)
    executed: bool = True
    reason: str = ""

    @property
    def field(self) -> str:
        return self.fieldName

    def summary_lines(self) -> List[str]:
        if not self.executed:
            return ["规则试跑未执行：{0}".format(self.reason or "该规则暂不支持试跑")]
        if not self.known:
            return ["规则试跑：未知（{0}）".format(self.reason or "缺少试跑前结果")]
        lines = ["规则试跑 {0}（{1}：{2} → {3}）".format(
            self.ruleId, self.field, self.beforeValue or "—", self.afterValue or "—",
        )]
        lines.extend(self.comparison.summary_lines() if self.comparison else [])
        if self.unsupported:
            lines.append("未支持字段（保留原文，未参与试跑）：{0}".format(
                "、".join(self.unsupported)
            ))
        lines.append("试跑只在内存中生效；未保存设置前不会改变正式规则")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "known": self.known, "ruleId": self.ruleId, "field": self.field,
            "beforeValue": self.beforeValue, "afterValue": self.afterValue,
            "executed": self.executed, "reason": self.reason,
            "unsupported": list(self.unsupported),
            "comparison": self.comparison.to_dict() if self.comparison else None,
        }


#: 支持在界面上试跑的规则字段（其余字段保留原文、不声称可编辑）。
SUPPORTED_RULE_FIELDS = ("enabled", "severity")


def unsupported_rule_fields(rule) -> List[str]:
    """规则里不属于受支持字段的声明（保留原文，不参与试跑）。"""
    known = {"rule_id", "enabled", "severity", "params"}
    data = dict(getattr(rule, "__dict__", {}) or {})
    flat = dict(getattr(rule, "params", None) or {})
    return sorted(key for key in set(data) | set(flat) if key not in known)


def trial_rule(
    linter_factory,
    *,
    rule_id: str,
    field: str,
    value,
    before_value="",
    baseline_issues=None,
) -> RuleTrial:
    """试跑一条规则的字段变化并比较真实问题集合（不写任何配置）。

    ``linter_factory()`` 由调用方提供，返回一个**已按试跑值构建好的临时
    linter**；本函数不碰磁盘、不碰正式规则，也不做隐式保存。
    """
    trial = RuleTrial(
        ruleId=str(rule_id), fieldName=str(field),
        beforeValue=str(before_value), afterValue=str(value),
    )
    if str(field) not in SUPPORTED_RULE_FIELDS:
        trial.executed = False
        trial.reason = "该字段不支持试跑：{0}".format(field)
        return trial
    try:
        linter = linter_factory()
    except Exception as exc:  # noqa: BLE001 - 试跑失败不改变正式规则
        trial.executed = False
        trial.reason = "试跑未执行：{0}".format(exc)
        return trial
    issues = linter.check_all([])
    if baseline_issues is None:
        trial.known = False
        trial.reason = "缺少试跑前结果"
        return trial
    trial.known = True
    trial.comparison = compare_issues(baseline_issues, issues)
    return trial


@dataclass
class GroupedFixItem:
    """一条确定性修正（差异 + 归属章 + 是否可选）。"""

    rel_path: str
    line_no: int
    before: str
    after: str
    ruleId: str = ""
    applicable: bool = True
    reason: str = ""

    def diff_lines(self) -> List[str]:
        return ["- {0}".format(self.before), "+ {0}".format(self.after)]

    def to_dict(self) -> Dict[str, object]:
        return {
            "relPath": self.rel_path, "lineNo": self.line_no,
            "before": self.before, "after": self.after, "ruleId": self.ruleId,
            "applicable": self.applicable, "reason": self.reason,
        }


@dataclass
class GroupedFixPlan:
    """成组修正计划：按章可选应用；冲突项局部跳过。"""

    items: List[GroupedFixItem] = dataclass_field(default_factory=list)
    skipped: List[GroupedFixItem] = dataclass_field(default_factory=list)
    applied: List[str] = dataclass_field(default_factory=list)
    undone: bool = False

    def by_chapter(self) -> Dict[str, List[GroupedFixItem]]:
        grouped: Dict[str, List[GroupedFixItem]] = {}
        for item in self.items:
            grouped.setdefault(item.rel_path, []).append(item)
        return grouped

    def summary_lines(self) -> List[str]:
        lines = ["成组修正：可应用 {0} 项，跳过 {1} 项".format(
            len(self.items), len(self.skipped),
        )]
        for rel_path, items in sorted(self.by_chapter().items()):
            lines.append("· {0}：{1} 项".format(rel_path, len(items)))
        for item in self.skipped:
            lines.append("· 跳过 {0}:{1}（{2}）".format(
                item.rel_path, item.line_no, item.reason,
            ))
        if self.undone:
            lines.append("已按原范围撤销本次修正")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "skipped": [item.to_dict() for item in self.skipped],
            "applied": list(self.applied),
            "undone": self.undone,
        }


def personal_view(issues, hidden_keys) -> Dict[str, object]:
    """个人「暂不处理」：只改当前版本视图，正式报告保留真实问题。"""
    hidden = {
        tuple(item) if isinstance(item, (list, tuple)) else item
        for item in (hidden_keys or ())
    }
    visible, suppressed = [], []
    for issue in issues or ():
        key = _issue_key(issue)
        if key in hidden:
            suppressed.append(issue)
        else:
            visible.append(issue)
    return {
        "visible": visible,
        "suppressed": suppressed,
        "total": len(visible) + len(suppressed),
        "note": current_view_note(len(suppressed), len(visible) + len(suppressed)),
    }


__all__ = [
    "GROUP_BY_CHAPTER", "GROUP_BY_RULE", "GROUP_BY_SEVERITY", "GROUPS",
    "FRESH", "STALE", "UNKNOWN",
    "rule_of", "issue_key", "compare_issues",
    "group_issues", "group_summary", "severity_totals", "content_digest",
    "IssueSnapshot", "staleness", "IssueComparison", "compare_snapshots",
    "current_view_note",
    "RuleTrial", "trial_rule", "SUPPORTED_RULE_FIELDS", "unsupported_rule_fields",
    "GroupedFixItem", "GroupedFixPlan", "personal_view",
]