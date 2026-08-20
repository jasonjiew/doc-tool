# -*- coding: utf-8 -*-
"""术语/一致性检查：重复标题、术语大小写不一致、TODO/TBD 残留。

- 重复标题：索引中完全相同的标题文本（规范化后）出现在多处。
- 术语大小写：术语清单中的规范拼写（如 ``WiFi``），正文出现非规范大小写时标记。
- 待办残留：``TODO``/``TBD``/``FIXME``/``XXX``/``待补充`` 等标记。

术语清单存储于项目 ``.state/terms.json``（``TermStore``），可在结果面板
增删，变更后立即生效并重跑相关检查。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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


class ContentLinter:
    """一致性检查器（纯服务）。"""

    def __init__(self, index: ContentIndex, rules_config=None) -> None:
        self._index = index
        self._rules_config = rules_config

    def _rules(self):
        if self._rules_config is not None:
            return self._rules_config.rule_map()
        from doc_tool.application.content.quality_rules import default_rules
        doc_type = next(iter(self._index.document_types), "general")
        return {rule.rule_id: rule for rule in default_rules(doc_type)}

    def check_all(self, terms: List[str]) -> List[LintIssue]:
        """运行全部检查，返回按文件与行排序的结果。"""
        issues = []
        dispatch = {
            "duplicate_title": lambda rule: self.check_duplicate_titles(rule.severity),
            "todo_residual": lambda rule: self.check_todo(rule.severity),
            "term_case": lambda rule: self.check_terms(terms, rule.severity),
            "required_section": self.check_required_sections,
            "field_completeness": self.check_field_completeness,
            "numbering_uniqueness": self.check_numbering_uniqueness,
            "sensitive_info": self.check_sensitive_info,
            "interface_table_structure": self.check_interface_table_structure,
        }
        for rule in self._rules().values():
            if rule.enabled and rule.rule_id in dispatch:
                issues.extend(dispatch[rule.rule_id](rule))
        issues.sort(key=lambda i: (i.rel_path, i.line_no))
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
        # 标题锚点唯一性：跨文件重复的 slug 锚点同样报告（同文件内重复也报告，
        # 因 slug 冲突会让锚点链接定位歧义）。
        seen_anchors = {}
        for rel_path in self._index.all_files():
            for heading in self._index.headings.get(rel_path, []):
                if heading.anchor_id in seen_anchors:
                    issues.append(LintIssue(
                        "numbering_uniqueness", rel_path, heading.line_no,
                        "标题锚点重复：{0}（首次位于 {1}:{2}）。".format(heading.text, *seen_anchors[heading.anchor_id]),
                        "numbering_uniqueness", rule.severity,
                    ))
                else:
                    seen_anchors[heading.anchor_id] = (rel_path, heading.line_no)
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


class TermStore:
    """术语清单持久化（项目 .state/terms.json）。"""

    def __init__(self, state_dir: Path) -> None:
        self._file: Path = Path(state_dir) / TERMS_FILE_NAME

    @property
    def file(self) -> Path:
        return self._file

    def load(self) -> List[str]:
        """读取术语清单；缺失或损坏返回空。"""
        if not self._file.exists():
            return []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
            terms = data.get("terms", []) if isinstance(data, dict) else []
            return [str(item).strip() for item in terms if str(item).strip()]
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, terms: List[str]) -> Optional[str]:
        """写入术语清单（去重、去空）。

        Returns:
            None 成功；写盘失败（目录不可写/磁盘满/杀软拦截 tmp 写入）返回
            错误文本而不是抛异常——面板据此提示「术语未持久化」，避免术语
            「看似已添加」实际重启后消失、且检查结果表因槽异常中断。
        """
        cleaned: List[str] = []
        seen = set()
        for term in terms:
            value = str(term).strip()
            if value and value not in seen:
                seen.add(value)
                cleaned.append(value)
        import os

        tmp = None
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                os.replace(str(tmp), str(self._file))
            except OSError:
                import shutil

                shutil.move(str(tmp), str(self._file))
        except OSError as exc:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            return "无法写入术语清单（{0}）".format(exc)
        return None
