# -*- coding: utf-8 -*-
"""术语/一致性检查：重复标题、术语大小写不一致、TODO/TBD 残留、表格结构。

- 重复标题：索引中完全相同的标题文本（规范化后）出现在多处。
- 术语大小写：术语清单中的规范拼写（如 ``WiFi``），正文出现非规范大小写时标记。
- 待办残留：``TODO``/``TBD``/``FIXME``/``XXX``/``待补充`` 等标记。
- 表格结构：与构建内核共用 ``doc_tool.domain.markdown_structure`` 契约，在合并前
  就报出会让构建失败的元数据问题，以及不阻断但改变排版的列数/分隔行问题。

术语清单存储于项目 ``quality/terms.json``，兼容旧 ``.state/terms.json``，可在结果面板
增删，变更后立即生效并重跑相关检查。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from doc_tool.domain.content_index import ContentIndex

TERMS_FILE_NAME = "terms.json"

# 待办/占位残留标记。
_TODO_RE = re.compile(
    r"TODO|TBD|FIXME|XXX|待补充|待完善|待定|占位|placeholder",
    re.IGNORECASE,
)


def _suggest_section_position(title: str) -> str:
    """必备章节缺失时的建议插入位置（轻量启发，非精确）。"""
    if "范围" in title or "概述" in title or "引言" in title:
        return "建议插入文档开头。"
    if "修订" in title or "记录" in title:
        return "建议插入文档头部（目录/标题之后）。"
    return "建议按章节顺序插入。"


@dataclass
class LintIssue:
    """一致性检查结果。"""

    rule: str  # duplicate_title | term_case | todo_residual
    rel_path: str
    line_no: int
    message: str
    rule_id: str = ""
    severity: str = "warning"

    def __post_init__(self) -> None:
        if not self.rule_id:
            self.rule_id = self.rule


@dataclass
class LintRunReport:
    """一次检查的事实：内容发现与检查是否真正执行分开表达。"""
    issues: List[LintIssue]
    configuration: dict = field(default_factory=dict)
    rules: List[dict] = field(default_factory=list)
    cache_hit: bool = False

    @property
    def configuration_failed(self):
        return not self.configuration.get("valid", True) or any(
            issue.rule_id == "rule_configuration" and issue.severity == "error" for issue in self.issues
        )

    def to_dict(self):
        executed = sum(x["status"] == "executed" for x in self.rules)
        enabled = sum(bool(x["enabled"]) for x in self.rules)
        complete = bool(executed) and not self.configuration_failed and all(
            not x["enabled"] or x["status"] in ("executed", "not-applicable") for x in self.rules
        )
        return {"configuration": dict(self.configuration), "rules": [dict(x) for x in self.rules],
                "enabledCount": enabled, "executedCount": executed,
                "disabledCount": sum(x["status"] == "disabled" for x in self.rules),
                "complete": complete, "cacheHit": self.cache_hit}


#: 进程内“检查结果复用”缓存（V4.2 42-B）。
#:
#: 键包含正文状态（每章路径 + 行数 + 内容摘要）、规则参数、解析器版本与范围，
#: 依赖摘要变化必然换键——因此不会拿旧结果冒充新正文。容量超限整体丢弃。
_LINT_RESULT_CACHE: "Dict[tuple, tuple]" = {}
_LINT_RESULT_CACHE_MAX = 64
#: 解析器版本参与键：解析逻辑变化必须使旧结果失效。
LINT_PARSER_VERSION = "lint-v2-quality-contracts"

#: 规则依赖分类（V4.2 42-B 2.3）。
#:
#: - ``local``：只看单章正文——单章变化时其它章的结果可以复用；
#: - ``cross-chapter``：依赖全项目正文（重复标题、术语一致性、跨章编号、链接/覆盖）。
#:
#: 未列出的规则按 ``unknown`` 处理：**一律退完整核对**，不做任何复用推断。
RULE_DEPENDENCIES = {
    "todo_residual": "local",
    "markdown_structure": "local",
    "mermaid_syntax": "local",
    "heading_format": "local",
    "field_completeness": "local",
    "sensitive_info": "local",
    "interface_table_structure": "local",
    "duplicate_title": "cross-chapter",
    "term_case": "cross-chapter",
    "required_section": "cross-chapter",
    "numbering_uniqueness": "cross-chapter",
    "module_sections": "local",
    "table_schema": "local",
    "rule_configuration": "cross-chapter",
}


def rule_dependency(rule_id: str) -> str:
    """规则的依赖范围：``local`` / ``cross-chapter`` / ``unknown``。"""
    return RULE_DEPENDENCIES.get(str(rule_id or ""), "unknown")


def requires_full_recheck(rule_ids) -> bool:
    """给定规则集合是否需要完整核对（含任何跨章或未知依赖规则时为真）。

    保守口径：只要有一条跨章或未知依赖规则启用，就不能只按“本章变化”复用结果，
    必须整份重算——避免把跨章规则（重复标题/术语/编号/链接覆盖）的结果算漏。
    """
    for rule_id in rule_ids or ():
        if rule_dependency(rule_id) in ("cross-chapter", "unknown"):
            return True
    return False


def reset_lint_result_cache() -> None:
    """清空检查结果复用缓存（测试/长驻进程释放内存用）。"""
    _LINT_RESULT_CACHE.clear()


def index_dependency_digest(index) -> tuple:
    """索引依赖摘要：正文（路径 + 行数 + 内容摘要）、解析器版本与文档类型集合。

    内容摘要优先用索引自带的 ``contentDigests``；没有时**按真实行文本**计算
    sha256——这正是“键必须包含正文”的落地方式：正文任何变化都会换键。
    """
    import hashlib

    digests = getattr(index, "contentDigests", None) or {}
    files = getattr(index, "files", {}) or {}
    lines = getattr(index, "lines", {}) or {}
    parts = []
    for rel_path in sorted(files):
        body_lines = lines.get(rel_path) or []
        digest = str(digests.get(rel_path) or "")
        if not digest:
            hasher = hashlib.sha256()
            for line in body_lines:
                hasher.update(str(line).encode("utf-8"))
                hasher.update(b"\n")
            digest = hasher.hexdigest()
        parts.append((
            rel_path,
            int(getattr(files[rel_path], "line_count", 0)),
            digest,
            len(body_lines),
        ))
    return (
        LINT_PARSER_VERSION,
        tuple(sorted(str(item) for item in (getattr(index, "document_types", None) or ()))),
        tuple(parts),
    )


class ContentLinter:
    """一致性检查器（纯服务）。"""

    def __init__(self, index: ContentIndex, rules_config=None, *, use_result_cache: bool = True) -> None:
        self._index = index
        self._rules_config = rules_config
        self._use_result_cache = bool(use_result_cache)

    @property
    def last_report(self):
        """最近一次真实检查的执行事实；不把关闭/无效项装成通过。"""
        return getattr(self, "_last_report", None)

    def _rules(self):
        if self._rules_config is not None:
            return self._rules_config.rule_map()
        from doc_tool.application.content.quality_rules import default_rules
        doc_type = next(iter(self._index.document_types), "general")
        return {rule.rule_id: rule for rule in default_rules(doc_type)}

    def _configuration(self):
        from doc_tool.application.content.quality_rules import (
            RuleConfigDiagnostic, RulesLoadResult, validate_rule_payload,
        )
        try:
            if self._rules_config is not None and hasattr(self._rules_config, "load_result"):
                return self._rules_config.load_result()
            rules = list(self._rules().values())
            diagnostics = validate_rule_payload([rule.to_dict() for rule in rules])
            return RulesLoadResult(rules, "builtin" if self._rules_config is None else "custom", "", "", diagnostics)
        except Exception as exc:  # 配置/索引错误必须成为失败事实，不可转成“零问题”。
            return RulesLoadResult([], "unavailable", "", "unavailable", [
                RuleConfigDiagnostic("config_read", "质量规则无法读取：{0}".format(exc)),
            ])

    def _rules_signature(self, rules=None, configuration=None) -> tuple:
        config = configuration if configuration is not None else self._configuration()
        items = rules if rules is not None else {rule.rule_id: rule for rule in config.rules}
        signature = tuple(
            (str(rid), bool(rule.enabled), str(rule.severity), json.dumps(rule.params, sort_keys=True, ensure_ascii=False, default=str))
            for rid, rule in sorted(items.items())
        )
        # 同样的默认回退规则不代表配置有效；来源/原始摘要/诊断也参与缓存键。
        return signature, json.dumps(config.to_dict(), sort_keys=True, ensure_ascii=False)

    def check_all(self, terms: List[str]) -> List[LintIssue]:
        """保留旧列表接口；check_report 同时提供来源和执行清单。"""
        return self.check_report(terms).issues

    def check_report(self, terms: List[str], *, term_warnings=()):
        from doc_tool.application.content.quality_rules import RuleConfigDiagnostic
        from doc_tool.domain.errors import CancelledError
        self._last_report = None
        config = self._configuration()
        if term_warnings and any(rule.rule_id == "term_case" and rule.enabled for rule in config.rules):
            config.diagnostics.extend(RuleConfigDiagnostic("terms_config", str(message), rule_id="term_case") for message in term_warnings)
        rules = {rule.rule_id: rule for rule in config.rules}
        cache_key = None
        if self._use_result_cache:
            cache_key = (index_dependency_digest(self._index), self._rules_signature(rules, config), tuple(sorted(str(x) for x in (terms or ()))))
            cached = _LINT_RESULT_CACHE.get(cache_key)
            if cached is not None:
                issues, executions = cached
                report = LintRunReport(list(issues), config.to_dict(), [dict(x) for x in executions], True)
                self._last_report = report
                return report
        issues = [LintIssue("rule_configuration", "", diagnostic.line_no,
                    "规则配置 {0}：{1}".format(config.path or config.source, diagnostic.message),
                    "rule_configuration", diagnostic.severity) for diagnostic in config.diagnostics]
        invalid_ids = {x.rule_id for x in config.diagnostics if x.severity == "error" and x.rule_id}
        dispatch = {
            "duplicate_title": lambda rule: self.check_duplicate_titles(rule.severity),
            "todo_residual": lambda rule: self.check_todo(rule.severity),
            "term_case": lambda rule: self.check_terms(terms, rule.severity),
            "required_section": self.check_required_sections,
            "field_completeness": self.check_field_completeness,
            "numbering_uniqueness": self.check_numbering_uniqueness,
            "sensitive_info": self.check_sensitive_info,
            "interface_table_structure": self.check_interface_table_structure,
            "markdown_structure": self.check_markdown_structure,
            "mermaid_syntax": self.check_mermaid_syntax,
            "heading_format": lambda rule: self.check_heading_format(rule.severity),
            "module_sections": self.check_document_contract,
            "table_schema": self.check_document_contract,
        }
        executions = []
        for rule in rules.values():
            item = {"ruleId": rule.rule_id, "enabled": rule.enabled, "status": "not-run", "reason": "", "findingCount": 0}
            if not rule.enabled:
                item.update(status="disabled", reason="配置中明确关闭，未执行")
            elif rule.rule_id in invalid_ids:
                item.update(status="invalid", reason="配置无效，未执行")
            elif rule.rule_id not in dispatch:
                item.update(status="unknown", reason="当前版本不支持，未执行")
            else:
                reason = self._not_applicable(rule, terms)
                if reason:
                    item.update(status="not-applicable", reason=reason)
                else:
                    try:
                        found = dispatch[rule.rule_id](rule)
                        issues.extend(found)
                        item.update(status="executed", findingCount=len(found))
                    except CancelledError:
                        raise
                    except Exception as exc:
                        item.update(status="failed", reason="执行失败：{0}".format(exc))
                        issues.append(LintIssue("rule_configuration", "", 0,
                            "规则「{0}」执行未完成：{1}".format(rule.rule_id, exc), "rule_configuration", "error"))
            executions.append(item)
        # 解析前已被拒绝的启用项也必须列出，不能因未进入 rule_map 而失踪。
        for diagnostic in config.diagnostics:
            if diagnostic.severity == "error" and diagnostic.rule_id and diagnostic.rule_id not in rules:
                if not any(x["ruleId"] == diagnostic.rule_id for x in executions):
                    executions.append({"ruleId": diagnostic.rule_id, "enabled": True, "status": "invalid", "reason": diagnostic.message, "findingCount": 0})
        from doc_tool.domain.content_index import path_natural_sort_key
        issues.sort(key=lambda i: (path_natural_sort_key(i.rel_path), i.line_no))
        report = LintRunReport(issues, config.to_dict(), executions)
        self._last_report = report
        if cache_key is not None:
            if len(_LINT_RESULT_CACHE) >= _LINT_RESULT_CACHE_MAX:
                _LINT_RESULT_CACHE.clear()
            _LINT_RESULT_CACHE[cache_key] = (list(issues), [dict(x) for x in executions])
        return report

    def _not_applicable(self, rule, terms):
        if not self._index.lines:
            return "本次检查范围没有正文"
        if rule.rule_id == "term_case" and not terms:
            return "未配置术语清单"
        if rule.rule_id == "required_section" and not rule.params.get("titles"):
            return "未配置必备标题"
        if rule.rule_id == "field_completeness" and not rule.params.get("fields"):
            return "未配置字段要求"
        if rule.rule_id == "sensitive_info" and not rule.params.get("patterns"):
            return "未配置匹配模式"
        if rule.rule_id in ("module_sections", "table_schema"):
            from doc_tool.application.content.document_contracts import matches_paths
            if not any(matches_paths(path, rule.params) for path in self._index.lines):
                return "本次范围没有匹配选择器的模块文件，未证明该规范通过"
        return ""

    def check_document_contract(self, rule):
        from doc_tool.application.content.document_contracts import (
            check_module_sections, check_table_schema, matches_paths,
        )
        checker = check_module_sections if rule.rule_id == "module_sections" else check_table_schema
        issues = []
        for path, lines in self._index.lines.items():
            if matches_paths(path, rule.params):
                for finding in checker("\n".join(lines), rule.params):
                    issues.append(LintIssue(rule.rule_id, path, finding.line_no, finding.message, rule.rule_id, rule.severity))
        return issues

    def check_duplicate_titles(self, severity: str = "warning") -> List[LintIssue]:
        """完全相同的标题文本（规范化后）出现在多处时标记。"""
        by_key: "defaultdict[str, list]" = defaultdict(list)
        for rel_path, headings in self._index.headings.items():
            for heading in headings:
                by_key[heading.key].append((rel_path, heading.line_no, heading.text))

        issues: List[LintIssue] = []
        for key, occurrences in by_key.items():
            if len(occurrences) < 2:
                continue
            # 只保留首个以外的重复出现
            for rel_path, line_no, text in occurrences[1:]:
                issues.append(
                    LintIssue(
                        rule="duplicate_title",
                        rel_path=rel_path,
                        line_no=line_no,
                        message="重复标题：{0}".format(text),
                        rule_id="duplicate_title", severity=severity,
                    )
                )
        return issues

    def check_todo(self, severity: str = "warning") -> List[LintIssue]:
        """TODO/TBD 等残留标记。"""
        issues: List[LintIssue] = []
        for rel_path, lines in self._index.lines.items():
            for line_no, line in enumerate(lines, start=1):
                if _TODO_RE.search(line):
                    issues.append(
                        LintIssue(
                            rule="todo_residual",
                            rel_path=rel_path,
                            line_no=line_no,
                            message="发现待办/占位标记：{0}".format(
                                line.strip()[:60]
                            ),
                            rule_id="todo_residual", severity=severity,
                        )
                    )
        return issues

    def check_terms(self, terms: List[str], severity: str = "info") -> List[LintIssue]:
        """术语大小写不一致（规范拼写 vs 非规范大小写出现）。"""
        issues: List[LintIssue] = []
        for term in terms:
            canonical = term.strip()
            if not canonical:
                continue
            pattern = re.compile(
                re.escape(canonical), re.IGNORECASE
            )
            for rel_path, lines in self._index.lines.items():
                for line_no, line in enumerate(lines, start=1):
                    for match in pattern.finditer(line):
                        if match.group(0) == canonical:
                            continue
                        issues.append(
                            LintIssue(
                                rule="term_case",
                                rel_path=rel_path,
                                line_no=line_no,
                                message="术语大小写不一致：{0}（应为 {1}）".format(
                                    match.group(0), canonical
                                ),
                                rule_id="term_case", severity=severity,
                            )
                        )
        return issues

    def check_required_sections(self, rule) -> List[LintIssue]:
        from doc_tool.application.content.tree import strip_number_prefix

        # 工具自身的重编号/章节树会为标题加编号前缀（如 ``1.2 范围``），
        # 必备章节按去掉编号前缀后的标题文本匹配，避免对合法文档误报。
        titles = {
            strip_number_prefix(heading.text.strip())
            for values in self._index.headings.values()
            for heading in values
        }
        issues = []
        for required in rule.params.get("titles", []):
            title = strip_number_prefix(str(required).strip())
            if title and title not in titles:
                issues.append(LintIssue(
                    "required_section", "", 0,
                    "缺少必备章节：{0}；{1}".format(title, _suggest_section_position(title)),
                    "required_section", rule.severity,
                ))
        return issues

    def check_field_completeness(self, rule) -> List[LintIssue]:
        issues = []
        for field_name, config in dict(rule.params.get("fields") or {}).items():
            data = config if isinstance(config, dict) else {"regex": str(config)}
            regex = str(data.get("regex") or re.escape(str(field_name)))
            try:
                pattern = re.compile(regex, re.MULTILINE)
            except re.error:
                # 配置了非法正则：不崩溃，按缺失处理并跳过该字段。
                continue
            count = 0
            first_hit: Optional[tuple] = None
            for rel_path, lines in self._index.lines.items():
                for line_no, line in enumerate(lines, start=1):
                    hits = pattern.findall(line)
                    if hits:
                        count += len(hits)
                        if first_hit is None:
                            first_hit = (rel_path, line_no)
            try:
                minimum = int(data.get("count", 1))
            except (TypeError, ValueError):
                minimum = 1
            if count < minimum:
                # 定位到最可能的章节：存在部分命中时指向首个命中位置，
                # 否则指向首个文件（消息中已说明期望格式）。
                rel_path, line_no = first_hit or (next(iter(self._index.all_files()), ""), 1)
                issues.append(LintIssue(
                    "field_completeness", rel_path, line_no,
                    "必填字段“{0}”缺失或格式不符（期望 {1}，至少 {2} 次）。".format(field_name, regex, minimum),
                    "field_completeness", rule.severity,
                ))
        return issues

    def check_numbering_uniqueness(self, rule) -> List[LintIssue]:
        from doc_tool.application.content.references import leading_number, section_no_of_file
        issues = []
        positions = []
        # 文件名章节号（如 ``3.1_概述.md`` -> ``3.1``）。
        file_numbers = {}
        for rel_path in self._index.all_files():
            number = section_no_of_file(rel_path)
            if number:
                file_numbers[rel_path] = number
                positions.append((number, rel_path, 1))
        # 文件名章节号与同文件首个同号标题（文件自身标题，如 ``# 3.1 概述``）
        # 合并为同一逻辑位置：H1 不在首行时若不合并，会与文件名位置自我误报
        # 「编号重复」。后续同号标题仍是真实重复，照常检出。
        title_covered: set = set()
        for rel_path in self._index.all_files():
            own_number = file_numbers.get(rel_path)
            for heading in self._index.headings.get(rel_path, []):
                number = leading_number(heading.text)
                if number:
                    if number == own_number and (number, rel_path) not in title_covered:
                        title_covered.add((number, rel_path))
                        continue
                    positions.append((number, rel_path, heading.line_no))
        # 去重完全相同的 (编号, 文件, 行)——文件自身章节号与其 H1 标题重合时
        # 不误报；同文件内不同行的重复编号仍会被检出。
        seen_positions = set()
        unique_positions = []
        for number, rel_path, line_no in positions:
            key = (number, rel_path, line_no)
            if key in seen_positions:
                continue
            seen_positions.add(key)
            unique_positions.append((number, rel_path, line_no))
        # 编号唯一性按文档类型作用域比较：requirement/3.1 与 design/3.1
        # 是各自独立文档的合法编号，跨类型比较会误报。索引根下无类型前缀的
        # 文件同属一个作用域，跨文件重复仍须检出。
        doc_types = set(self._index.document_types)

        def _scope(rel_path: str) -> str:
            head, _, _ = rel_path.partition("/")
            return head if head in doc_types else "<root>"

        seen = {}
        for number, rel_path, line_no in unique_positions:
            key = (_scope(rel_path), number)
            if key in seen:
                issues.append(LintIssue(
                    "numbering_uniqueness", rel_path, line_no,
                    "章节编号重复：{0}（首次位于 {1}:{2}）。".format(number, *seen[key]),
                    "numbering_uniqueness", rule.severity,
                ))
            else:
                seen[key] = (rel_path, line_no)
        # 标题锚点唯一性：
        # 1. 同文件内：检查同文件内的锚点重复（如同一文件中重复定义相同锚点）。
        # 2. 跨文件：仅对未带章节编号的顶层标题（level 1）检查全局唯一性（如跨文件重复的 # 范围），
        #    避免将不同章节下通用的子标题（如各章下的 ## 流程图、## 接口设计）误报为跨文件冲突。
        # 注意：标题锚点重复不属于编号冲突，严重级别固定为 warning，不阻断构建与发布。
        from doc_tool.application.content.references import leading_number, section_no_of_file

        seen_top_anchors = {}
        for rel_path in self._index.all_files():
            file_seen_anchors = {}
            for heading in self._index.headings.get(rel_path, []):
                # 1. 同文件内锚点重复检查（同一文件内重复定义相同锚点）
                if heading.anchor_id in file_seen_anchors:
                    issues.append(LintIssue(
                        "numbering_uniqueness", rel_path, heading.line_no,
                        "标题锚点重复：{0}（首次位于 {1}:{2}）。".format(heading.text, *file_seen_anchors[heading.anchor_id]),
                        "numbering_uniqueness", "warning",
                    ))
                else:
                    file_seen_anchors[heading.anchor_id] = (rel_path, heading.line_no)

                # 2. 跨文件锚点重复检查：仅针对无章节编号的顶层标题（避免子章节同名误报）
                if heading.level == 1 and not section_no_of_file(rel_path) and not leading_number(heading.text):
                    if heading.anchor_id in seen_top_anchors:
                        first_rel, first_line = seen_top_anchors[heading.anchor_id]
                        if first_rel != rel_path:
                            issues.append(LintIssue(
                                "numbering_uniqueness", rel_path, heading.line_no,
                                "标题锚点重复：{0}（首次位于 {1}:{2}）。".format(heading.text, first_rel, first_line),
                                "numbering_uniqueness", "warning",
                            ))
                    else:
                        seen_top_anchors[heading.anchor_id] = (rel_path, heading.line_no)

        return issues

    def check_interface_table_structure(self, rule) -> List[LintIssue]:
        """接口章节应包含接口表格（需求/设计文档默认开启）。

        扫描标题文本含「接口」的章节：其正文到下一个标题之间若没有任何
        以 ``|`` 开头的表格行，视为缺少接口表结构。
        """
        issues = []
        for rel_path, headings in self._index.headings.items():
            lines = self._index.lines.get(rel_path, [])
            for index, heading in enumerate(headings):
                if "接口" not in heading.text:
                    continue
                next_line = headings[index + 1].line_no if index + 1 < len(headings) else len(lines) + 1
                # heading.line_no 为 1-based；正文从其后一行（0-based 下标 =
                # line_no）到下一标题前一行（0-based 下标 = next_line - 1，开区间）。
                body = lines[heading.line_no:next_line - 1]
                has_table = any(str(line).lstrip().startswith("|") for line in body)
                if not has_table:
                    issues.append(LintIssue(
                        "interface_table_structure", rel_path, heading.line_no,
                        "接口章节「{0}」缺少接口表格（应包含表头与数据行）。".format(heading.text),
                        "interface_table_structure", rule.severity,
                    ))
        return issues

    def check_markdown_structure(self, rule) -> List[LintIssue]:
        """表格结构契约检查（与构建内核同一份规则）。

        阻断类结论（元数据语法无效、元数据后没有紧跟表格）按规则配置的严重度
        报告（默认 error）——这些问题不修就一定合并失败；不阻断的结论（声明列宽
        数与实际列数不符、行列不齐、缺少分隔行）固定为 warning：它们不会阻断构建，
        但会让列宽退回默认值或表头不被识别，与作者意图不符。
        """
        from doc_tool.domain.markdown_structure import check_table_structure

        issues: List[LintIssue] = []
        for rel_path, lines in self._index.lines.items():
            for finding in check_table_structure(lines):
                issues.append(LintIssue(
                    rule="markdown_structure",
                    rel_path=rel_path,
                    line_no=finding.line_no,
                    message=finding.text,
                    rule_id="markdown_structure",
                    severity=rule.severity if finding.blocking else "warning",
                ))
        return issues

    def check_mermaid_syntax(self, rule) -> List[LintIssue]:
        """Mermaid 流程图与图表语法检查（与构建前校验使用同一套规则）。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        issues: List[LintIssue] = []
        for rel_path, lines in self._index.lines.items():
            for finding in check_mermaid_structure(lines):
                issues.append(LintIssue(
                    rule="mermaid_syntax",
                    rel_path=rel_path,
                    line_no=finding.line_no,
                    message=finding.text,
                    rule_id="mermaid_syntax",
                    severity=rule.severity if finding.blocking else "warning",
                ))
        return issues

    def check_sensitive_info(self, rule) -> List[LintIssue]:
        issues = []
        for pattern_data in rule.params.get("patterns", []):
            data = pattern_data if isinstance(pattern_data, dict) else {"name": str(pattern_data), "regex": str(pattern_data)}
            try:
                pattern = re.compile(str(data.get("regex", "")))
            except re.error:
                continue
            for rel_path, lines in self._index.lines.items():
                for line_no, line in enumerate(lines, start=1):
                    if pattern.search(line):
                        issues.append(LintIssue(
                            "sensitive_info", rel_path, line_no,
                            "发现敏感信息模式：{0}".format(data.get("name", "自定义模式")),
                            "sensitive_info", rule.severity,
                        ))
        return issues

    def check_heading_format(self, severity: str = "warning") -> List[LintIssue]:
        """检查 Markdown 标题格式与基础语法（如 # 后缺少空格、空标题、未闭合代码块）。"""
        issues: List[LintIssue] = []
        for rel_path, lines in self._index.lines.items():
            in_code_block = False
            code_block_start = 0
            for line_no, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith("```"):
                    if not in_code_block:
                        in_code_block = True
                        code_block_start = line_no
                    else:
                        in_code_block = False
                    continue
                if in_code_block:
                    continue

                # 检查只有 # 号没有标题文本
                if re.match(r"^#{1,6}\s*$", stripped):
                    issues.append(
                        LintIssue(
                            rule="heading_format",
                            rel_path=rel_path,
                            line_no=line_no,
                            message="标题格式错误：标题文本为空。",
                            rule_id="heading_format",
                            severity=severity,
                        )
                    )
                    continue

                # 检查 # 后面缺少空格（例如 '#1.1' 或 '##功能说明'）
                m = re.match(r"^(#{1,6})([^\s#].*)$", stripped)
                if m:
                    prefix = m.group(1)
                    sample = stripped if len(stripped) <= 25 else stripped[:22] + "..."
                    issues.append(
                        LintIssue(
                            rule="heading_format",
                            rel_path=rel_path,
                            line_no=line_no,
                            message="标题格式错误：'{0}' 后面缺少空格（{1}），无法被识别为大纲标题。".format(prefix, sample),
                            rule_id="heading_format",
                            severity=severity,
                        )
                    )
            if in_code_block:
                issues.append(
                    LintIssue(
                        rule="heading_format",
                        rel_path=rel_path,
                        line_no=code_block_start,
                        message="代码块未闭合：以 '```' 开头的代码块缺少配对的结束标记。",
                        rule_id="heading_format",
                        severity=severity,
                    )
                )
        return issues


class TermStore:
    """术语清单：项目 quality/ 优先，旧 .state/ 只读兼容。"""

    def __init__(self, state_dir: Path, *, writable: bool = True) -> None:
        state = Path(state_dir)
        self._project_root = state.parent if state.name == ".state" else None
        self.writable = writable
        self.warnings: List[str] = []
        if self._project_root is not None:
            from doc_tool.application.quality_location import QUALITY_DIR, QUALITY_TERMS_NAME
            self._file = self._project_root / QUALITY_DIR / QUALITY_TERMS_NAME
        else:
            self._file = state / TERMS_FILE_NAME

    @property
    def file(self) -> Path:
        return self._file

    def load(self) -> List[str]:
        """只读取，不迁移；损坏的术语配置给出诊断。"""
        self.warnings = []
        if self._project_root is not None:
            from doc_tool.application.quality_location import load_terms_with_fallback
            terms, warnings = load_terms_with_fallback(self._project_root)
            self.warnings = ["术语配置：" + value for value in warnings]
            return terms
        if not self._file.exists():
            return []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8-sig"))
            items = data if isinstance(data, list) else data.get("terms", []) if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ValueError("terms 应为列表")
            return [str(item).strip() for item in items if str(item).strip()]
        except (ValueError, OSError, UnicodeError) as exc:
            self.warnings = ["术语配置不可用，未执行术语检查：{0}".format(exc)]
            return []

    def save(self, terms: List[str]) -> Optional[str]:
        """写入术语清单（去重、去空）。

        Returns:
            None 成功；写盘失败（目录不可写/磁盘满/杀软拦截 tmp 写入）返回
            错误文本而不是抛异常——面板据此提示「术语未持久化」，避免术语
            「看似已添加」实际重启后消失、且检查结果表因槽异常中断。
        """
        if not self.writable:
            return "只读项目不可保存术语清单"
        if self._file.exists() and not self._file.is_file():
            return "术语保存目标不是文件，未写入配置"
        cleaned: List[str] = []
        seen = set()
        for term in terms:
            value = str(term).strip()
            if value and value not in seen:
                seen.add(value)
                cleaned.append(value)
        # 添加一个词不能丢掉团队共享文件的说明及既有词条的 canonical/备注元数据。
        source = self._file
        if self._project_root is not None:
            from doc_tool.application.quality_location import resolve_quality_location, QUALITY_TERMS_NAME
            source = resolve_quality_location(self._project_root, QUALITY_TERMS_NAME, legacy_name=TERMS_FILE_NAME).path
        previous = None
        try:
            previous = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError):
            pass
        items = previous.get("terms", []) if isinstance(previous, dict) else previous if isinstance(previous, list) else []
        by_name = {}
        for item in items if isinstance(items, list) else []:
            name = str(item.get("canonical", "")).strip() if isinstance(item, dict) else str(item).strip()
            by_name.setdefault(name, item)
        preserved = [by_name.get(value, value) for value in cleaned]
        payload = dict(previous) if isinstance(previous, dict) else None
        if payload is not None:
            payload["terms"] = preserved
        else:
            payload = preserved
        return self._write_payload(payload)

    def save_entries(self, entries) -> Optional[str]:
        """设置页保存完整术语资源，与词库面板的字符串增删视图区分。"""
        if not self.writable:
            return "只读项目不可保存术语清单"
        from doc_tool.application.quality_location import parse_terms_payload, load_terms_resource
        _terms, warnings = parse_terms_payload(entries)
        if not isinstance(entries, list) or warnings:
            return "术语配置无效：{0}".format("；".join(warnings) or "条目应为列表")
        if self._project_root is not None:
            previous = load_terms_resource(self._project_root)["data"]
        else:
            try:
                previous = json.loads(self._file.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, ValueError):
                previous = None
        payload = dict(previous) if isinstance(previous, dict) else {}
        payload["terms"] = list(entries)
        return self._write_payload(payload)

    def _write_payload(self, payload) -> Optional[str]:
        if not self.writable:
            return "只读项目不可保存术语清单"
        if self._file.exists() and not self._file.is_file():
            return "术语保存目标不是文件，未写入配置"
        import os
        tmp = None
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                os.replace(str(tmp), str(self._file))
            except OSError:
                import shutil

                shutil.move(str(tmp), str(self._file))
        except (OSError, TypeError, ValueError) as exc:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            return "无法写入术语清单（{0}）".format(exc)
        return None


def can_quick_fix(issue: LintIssue) -> bool:
    """判断该检查问题是否支持一键自动修复。"""
    if issue.rule_id == "heading_format":
        if "缺少空格" in issue.message or "必须有空格" in issue.message or "代码块未闭合" in issue.message or "标题文本为空" in issue.message:
            return True
    elif issue.rule_id == "term_case":
        return True
    elif issue.rule_id == "markdown_structure":
        if "缺少分隔行" in issue.message:
            return True
    return False


def apply_quick_fix(content: str, issue: LintIssue) -> Tuple[str, bool, str]:
    """对文件内容应用指定 LintIssue 的自动修复。

    Returns:
        (修复后的文本, 是否成功, 操作说明文本)
    """
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines()
    line_idx = issue.line_no - 1  # 0-based

    if issue.rule_id == "heading_format":
        if "缺少空格" in issue.message or "必须有空格" in issue.message:
            if 0 <= line_idx < len(lines):
                orig = lines[line_idx]
                m = re.match(r"^(\s*#{1,6})([^\s#].*)$", orig)
                if m:
                    lines[line_idx] = "{0} {1}".format(m.group(1), m.group(2))
                    result = newline.join(lines)
                    if content.endswith("\r\n"):
                        result += "\r\n"
                    elif content.endswith("\n"):
                        result += "\n"
                    return result, True, "已在第 {0} 行标题标记后添加空格".format(issue.line_no)
        elif "代码块未闭合" in issue.message:
            lines.append("```")
            result = newline.join(lines) + newline
            return result, True, "已在文档末尾补全闭合代码块 '```'"
        elif "标题文本为空" in issue.message:
            if 0 <= line_idx < len(lines):
                del lines[line_idx]
                result = newline.join(lines)
                if content.endswith("\r\n"):
                    result += "\r\n"
                elif content.endswith("\n"):
                    result += "\n"
                return result, True, "已移除第 {0} 行的空标题".format(issue.line_no)

    elif issue.rule_id == "term_case":
        m = re.search(
            r"(?:术语大小写不一致：\s*([^（]+?)\s*（应为\s*([^）]+)）|正文为\s*['\"]([^'\"]+)['\"]\s*，规范应为\s*['\"]([^'\"]+)['\"])",
            issue.message,
        )
        if m and 0 <= line_idx < len(lines):
            bad_term = m.group(1) or m.group(3)
            good_term = m.group(2) or m.group(4)
            orig = lines[line_idx]
            if re.search(re.escape(bad_term), orig, flags=re.IGNORECASE):
                lines[line_idx] = re.sub(re.escape(bad_term), lambda _: good_term, orig, flags=re.IGNORECASE)
                result = newline.join(lines)
                if content.endswith("\r\n"):
                    result += "\r\n"
                elif content.endswith("\n"):
                    result += "\n"
                return result, True, "已在第 {0} 行将 '{1}' 修正为 '{2}'".format(issue.line_no, bad_term, good_term)

    elif issue.rule_id == "markdown_structure" and "缺少分隔行" in issue.message:
        if 0 <= line_idx < len(lines):
            header = lines[line_idx].strip()
            from doc_tool.application.content.table_format import split_table_cells
            cells = split_table_cells(header)
            col_count = max(1, len(cells))
            sep = "| " + " | ".join(["---"] * col_count) + " |"
            lines.insert(line_idx + 1, sep)
            result = newline.join(lines)
            if content.endswith("\r\n"):
                result += "\r\n"
            elif content.endswith("\n"):
                result += "\n"
            return result, True, "已在第 {0} 行表头下方插入标准分隔行".format(issue.line_no)

    return content, False, "该条目暂不支持自动修复"


def apply_all_quick_fixes(content: str, issues: List[LintIssue]) -> Tuple[str, int]:
    """批量应用所有支持自动修复的问题，按行号倒序应用以避免行号偏移。

    Returns:
        (修复后的文本, 成功修复的条目数)
    """
    fixable = [issue for issue in issues if can_quick_fix(issue)]
    # 按行号倒序处理
    fixable.sort(key=lambda i: i.line_no, reverse=True)
    fixed_count = 0
    current_content = content
    for issue in fixable:
        updated, success, _ = apply_quick_fix(current_content, issue)
        if success:
            current_content = updated
            fixed_count += 1
    return current_content, fixed_count

# --- 规则分类与标签定义 ---

RULE_CATEGORY_GROUPS: dict[str, list[str]] = {
    "格式规范": ["heading_format", "markdown_structure", "mermaid_syntax"],
    "内容质量": ["todo_residual", "term_case", "duplicate_title"],
    "结构完整": ["required_section", "field_completeness", "interface_table_structure", "module_sections", "table_schema"],
    "规则配置": ["rule_configuration"],
    "合规与安全": ["sensitive_info", "numbering_uniqueness"],
}

RULE_CATEGORIES: dict[str, str] = {
    rule: cat for cat, rules in RULE_CATEGORY_GROUPS.items() for rule in rules
}

RULE_LABELS: dict[str, str] = {
    "heading_format": "标题格式",
    "markdown_structure": "表格结构",
    "mermaid_syntax": "流程图语法",
    "todo_residual": "待办残留",
    "term_case": "术语大小写",
    "duplicate_title": "重复标题",
    "required_section": "必备章节",
    "field_completeness": "字段完整性",
    "interface_table_structure": "接口表结构",
    "numbering_uniqueness": "编号唯一性",
    "sensitive_info": "敏感信息",
    "module_sections": "模块章节契约",
    "table_schema": "需求表型契约",
    "rule_configuration": "规则配置与执行",
}

SEVERITY_LABELS: dict[str, str] = {
    "error": "阻断",
    "warning": "警告",
    "info": "提示",
}


def filter_lint_issues(
    issues,
    *,
    category: str = "",
    rule_id: str = "",
    severity: str = "",
    quick_fixable = None,
    keyword: str = "",
):
    """按分类大类/单规则、严重度、修复状态及关键词综合筛选格式检查问题。

    Args:
        issues: 原始问题列表。
        category: 分类大类（如 '格式规范'、'group:格式规范'）或单规则 ID / 规则中文名。
        rule_id: 指定单规则 ID（精确匹配）。
        severity: 严重度（如 'error', 'warning', 'info'）。
        quick_fixable: 是否支持一键自动修复过滤（True: 仅支持，False: 仅不支持，None: 全部）。
        keyword: 关键词搜索（不区分大小写，检索文件名、行号、问题描述、规则名称及中文分类）。

    Returns:
        筛选后的 LintIssue 列表。
    """
    kw = (keyword or "").strip().lower()
    cat = (category or "").strip()
    rule_filter = (rule_id or "").strip()
    sev_filter = (severity or "").strip().lower()

    filtered = []
    for issue in issues:
        rid = getattr(issue, "rule_id", "") or getattr(issue, "rule", "")

        # 1. 规则精确匹配
        if rule_filter and rid != rule_filter and getattr(issue, "rule", "") != rule_filter:
            continue

        # 2. 分类匹配
        if cat:
            if cat.startswith("group:"):
                grp = cat[len("group:"):].strip()
                allowed_rules = RULE_CATEGORY_GROUPS.get(grp)
                if allowed_rules is None or rid not in allowed_rules:
                    continue
            elif cat in RULE_CATEGORY_GROUPS:
                if rid not in RULE_CATEGORY_GROUPS[cat]:
                    continue
            else:
                expected_label = RULE_LABELS.get(rid, rid)
                if cat != rid and cat != expected_label:
                    continue

        # 3. 严重度匹配
        if sev_filter:
            issue_sev = str(getattr(issue, "severity", "") or "").lower()
            if issue_sev != sev_filter:
                continue

        # 4. 修复状态匹配
        if quick_fixable is not None:
            if can_quick_fix(issue) != quick_fixable:
                continue

        # 5. 关键词搜索
        if kw:
            rule_label = RULE_LABELS.get(rid, rid)
            cat_name = RULE_CATEGORIES.get(rid, "")
            sev_label = SEVERITY_LABELS.get(getattr(issue, "severity", ""), "")
            tokens = [
                str(getattr(issue, "rel_path", "") or ""),
                str(getattr(issue, "line_no", "") or ""),
                str(getattr(issue, "message", "") or ""),
                rid,
                str(getattr(issue, "rule", "") or ""),
                rule_label,
                cat_name,
                sev_label,
            ]
            if can_quick_fix(issue):
                tokens.extend(["可修复", "⚡可修复", "一键修复"])
            haystack = " ".join(tokens).lower()
            words = kw.split()
            if not all(w in haystack for w in words):
                continue

        filtered.append(issue)

    return filtered

