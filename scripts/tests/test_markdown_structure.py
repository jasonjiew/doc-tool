# -*- coding: utf-8 -*-
"""表格结构契约与出错定位测试。

覆盖三条链路，保证「合并前能查出来」与「合并失败时能定位」是同一套规则：

1. ``doc_tool.domain.markdown_structure``：结构契约本身（阻断/非阻断分类）。
2. 构建内核：``validate_content_tree`` 一次报出全部问题并携带结构化位置；
   正文插入阶段的表格错误同样带位置与修法建议。
3. 上层呈现：管线阶段事件 metrics → 问题记录（多条可定位）→ 失败摘要与
   lint 规则。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

from docx_common import (  # noqa: E402
    AutomationError,
    error_location,
    format_location,
    split_markdown_table_row,
    validate_content_tree,
)
from doc_tool.application.issues import issues_from_pipeline  # noqa: E402
from doc_tool.application.pipeline import (  # noqa: E402
    exception_locations,
    locations_summary,
)
from doc_tool.domain.markdown_structure import (  # noqa: E402
    check_table_structure,
    parse_table_meta,
)

META = "<!-- TBL:style=43 type=auto tw=0 cols=1967,2556 -->"


class TableStructureContractTests(unittest.TestCase):
    """结构契约：阻断项与非阻断项的分类必须与构建内核实际行为一致。"""

    def test_meta_followed_by_blank_line_is_blocking_with_gap_hint(self):
        findings = check_table_structure([
            META,
            "",
            "| 需求标识 | 描述 |",
            "| --- | --- |",
            "| REQ-1 | x |",
        ])
        orphan = [f for f in findings if f.rule == "table_meta_orphan"]
        self.assertEqual(len(orphan), 1)
        self.assertTrue(orphan[0].blocking)
        self.assertEqual(orphan[0].line_no, 1)
        # 空行是最常见成因：提示必须直接说「删掉这 N 个空行」而不是泛泛而谈。
        self.assertIn("空行", orphan[0].hint)
        self.assertIn("1 个空行", orphan[0].hint)

    def test_meta_with_no_table_at_all_hints_removing_meta(self):
        findings = check_table_structure([META, "", "普通段落。"])
        orphan = [f for f in findings if f.rule == "table_meta_orphan"]
        self.assertEqual(len(orphan), 1)
        self.assertIn("删除", orphan[0].hint)

    def test_invalid_meta_syntax_is_blocking_and_carries_example(self):
        findings = check_table_structure([
            "<!-- TBL:style=43 cols=abc -->",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
        ])
        syntax = [f for f in findings if f.rule == "table_meta_syntax"]
        self.assertEqual(len(syntax), 1)
        self.assertTrue(syntax[0].blocking)
        self.assertIn("TBL:style=", syntax[0].hint)

    def test_declared_column_count_mismatch_is_warning_with_actual_numbers(self):
        # 真实案例：cols 写了 5 个宽度，表格只有 4 列。构建不失败，但列宽全部
        # 退回默认值——必须报出来，且不能阻断合并。
        findings = check_table_structure([
            "<!-- TBL:style=43 type=auto tw=0 cols=1,2,3,4,5 -->",
            "| A | B | C | D |",
            "| --- | --- | --- | --- |",
            "| 1 | 2 | 3 | 4 |",
        ])
        mismatch = [f for f in findings if f.rule == "table_column_mismatch"]
        self.assertEqual(len(mismatch), 1)
        self.assertFalse(mismatch[0].blocking)
        self.assertIn("5", mismatch[0].message)
        self.assertIn("4", mismatch[0].message)
        self.assertIn("忽略", mismatch[0].message)

    def test_fewer_declared_widths_explains_widths_fall_back(self):
        findings = check_table_structure([
            "<!-- TBL:style=43 type=auto tw=0 cols=1,2 -->",
            "| A | B | C |",
            "| --- | --- | --- |",
            "| 1 | 2 | 3 |",
        ])
        mismatch = [f for f in findings if f.rule == "table_column_mismatch"]
        self.assertEqual(len(mismatch), 1)
        self.assertIn("默认值", mismatch[0].message)

    def test_missing_separator_and_ragged_rows_are_warnings(self):
        findings = check_table_structure([
            "| A | B | C |",
            "| 1 | 2 |",
        ])
        rules = {f.rule for f in findings}
        self.assertIn("table_missing_separator", rules)
        self.assertIn("table_ragged_rows", rules)
        self.assertTrue(all(not f.blocking for f in findings))
        separator = [f for f in findings if f.rule == "table_missing_separator"][0]
        # 建议里直接给出可照抄的分隔行。
        self.assertIn("| --- | --- | --- |", separator.hint)

    def test_wellformed_table_reports_nothing(self):
        self.assertEqual(check_table_structure([
            META,
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
            "普通段落。",
        ]), [])

    def test_escaped_pipe_is_not_a_column_separator(self):
        # 单元格里的 ``\|`` 是内容，不能让列数统计误判为不一致。
        findings = check_table_structure([
            "<!-- TBL:style=43 type=auto tw=0 cols=1,2 -->",
            r"| A | 左\|右 |",
            "| --- | --- |",
            r"| 1 | C:\\data |",
        ])
        self.assertEqual(findings, [])

    def test_meta_parsing_is_shared_with_kernel(self):
        # 内核构造 w:tbl 用的就是这个解析结果，契约必须在此单点定义。
        style, widths, width_type, table_width, row_height, extras = parse_table_meta(
            "<!-- TBL:style=43 type=dxa tw=9859 trh=553 cols=1810,8049 va=center -->"
        )
        self.assertEqual(style, "43")
        self.assertEqual(widths, [1810, 8049])
        self.assertEqual(width_type, "dxa")
        self.assertEqual(table_width, 9859)
        self.assertEqual(row_height, 553)
        self.assertEqual(extras["va"], "center")
        self.assertIsNone(parse_table_meta("<!-- TBL:bogus -->"))

    def test_split_row_still_raises_automation_error_for_kernel(self):
        # 内核对外的失败语义不变（收敛实现不得改变异常类型）。
        with self.assertRaises(AutomationError):
            split_markdown_table_row("A | B")


class StructuredLocationTests(unittest.TestCase):
    """构建内核：结构化出错位置贯通到异常，且消息保持 ``路径:行号`` 前缀。"""

    def _project(self, root: str, body: str) -> dict:
        content = os.path.join(root, "content")
        assets = os.path.join(root, "assets")
        tables = os.path.join(assets, "tables")
        os.makedirs(tables)
        template = os.path.join(root, "template.docx")
        open(template, "wb").close()
        chapter = os.path.join(content, "第1章 A")
        os.makedirs(chapter)
        target = os.path.join(chapter, "1.1 B.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(body)
        return {
            "paths": {
                "content_root": content,
                "asset_root": assets,
                "table_root": tables,
                "template": template,
            },
            "headingStyles": {1: "1", 2: "2", 3: "3"},
            "_target": target,
        }

    def test_orphan_meta_fails_prebuild_with_path_line_and_hint(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._project(root, "\n".join([
                "### 上传",
                "",
                META,
                "",
                "| A | B |",
                "| --- | --- |",
                "| 1 | 2 |",
            ]))
            with self.assertRaises(AutomationError) as ctx:
                validate_content_tree(config)
            exc = ctx.exception
            self.assertEqual(len(exc.locations), 1)
            entry = exc.locations[0]
            self.assertEqual(entry["path"], config["_target"])
            self.assertEqual(entry["line"], 3)
            self.assertEqual(entry["rule"], "table_meta_orphan")
            self.assertIn("空行", entry["hint"])
            # 消息仍以 ``路径:行号`` 开头（校验报告解析与旧日志依赖该形状）。
            self.assertIn("{0}:3".format(config["_target"]), str(exc))

    def test_prebuild_reports_every_problem_in_one_pass(self):
        # 一次构建就报全部位置：作者改一轮即可，不必反复触发构建逐个定位。
        with tempfile.TemporaryDirectory() as root:
            config = self._project(root, "\n".join([
                META,
                "",
                "| A | B |",
                "| --- | --- |",
                "| 1 | 2 |",
                "",
                "<!-- TBL:bogus -->",
                "| C | D |",
                "| --- | --- |",
                "| 3 | 4 |",
                "",
                "![缺图](missing.png)",
            ]))
            with self.assertRaises(AutomationError) as ctx:
                validate_content_tree(config)
            rules = [entry["rule"] for entry in ctx.exception.locations]
            self.assertIn("table_meta_orphan", rules)
            self.assertIn("table_meta_syntax", rules)
            self.assertIn("image_missing", rules)
            self.assertGreaterEqual(len(ctx.exception.locations), 3)
            # 行号必须逐条给出，而不是只指向文件。
            self.assertTrue(all(entry["line"] for entry in ctx.exception.locations))

    def test_non_blocking_findings_do_not_fail_the_build(self):
        # 列数不符/缺分隔行只影响排版，构建前检查不得因此阻断合并。
        with tempfile.TemporaryDirectory() as root:
            config = self._project(root, "\n".join([
                "<!-- TBL:style=43 type=auto tw=0 cols=1,2,3 -->",
                "| A | B |",
                "| --- | --- |",
                "| 1 | 2 |",
            ]))
            validate_content_tree(config)

    def test_format_location_renders_path_line_message_hint(self):
        entry = error_location("a.md", 12, "说明", "建议", "rule")
        self.assertEqual(format_location(entry), "a.md:12 说明 建议")
        self.assertEqual(
            format_location(error_location("a.md", None, "说明")), "a.md 说明"
        )


class FailurePresentationTests(unittest.TestCase):
    """上层呈现：位置归一为 rel_path、摘要可读、问题逐条可定位。"""

    def test_exception_locations_are_relative_to_content_root(self):
        with tempfile.TemporaryDirectory() as root:
            content_root = Path(root) / "content" / "requirement"
            target = content_root / "第3章 功能需求" / "3.5.3 上传SD卡.md"
            target.parent.mkdir(parents=True)
            target.write_text("x", encoding="utf-8")
            exc = AutomationError("boom", locations=[
                error_location(str(target), 12, "说明", "建议", "table_meta_orphan"),
            ])
            entries = exception_locations(exc, content_root)
            self.assertEqual(
                entries[0]["relPath"], "第3章 功能需求/3.5.3 上传SD卡.md"
            )
            self.assertEqual(entries[0]["line"], 12)

    def test_exception_locations_fall_back_to_file_name_outside_root(self):
        exc = AutomationError("boom", locations=[
            error_location(os.path.join("X:", "other", "a.md"), 3, "说明"),
        ])
        entries = exception_locations(exc, Path("Y:/project/content"))
        self.assertEqual(entries[0]["relPath"], "a.md")

    def test_plain_exception_yields_no_locations(self):
        self.assertEqual(exception_locations(ValueError("x"), None), [])

    def test_summary_leads_with_first_location_and_total_count(self):
        locations = [
            {"relPath": "a.md", "line": 12, "message": "说明1", "hint": "建议1"},
            {"relPath": "b.md", "line": 3, "message": "说明2", "hint": ""},
        ]
        summary = locations_summary(locations, "Word 文档构建失败。")
        self.assertIn("共 2 处", summary)
        self.assertIn("a.md:12", summary)
        self.assertIn("说明1", summary)
        # 没有结构化位置时退回内核消息，不得丢信息。
        self.assertEqual(
            locations_summary([], "Word 文档构建失败。"), "Word 文档构建失败。"
        )

    def test_single_location_summary_has_no_count_prefix(self):
        summary = locations_summary(
            [{"relPath": "a.md", "line": 12, "message": "说明", "hint": "建议"}], "x"
        )
        self.assertEqual(summary, "a.md:12 说明 建议")

    def test_pipeline_failure_expands_into_one_issue_per_location(self):
        event = SimpleNamespace(
            stage="build", status="failed", detail="共 2 处内容问题", error_code="E2001",
            metrics={"locations": [
                {"relPath": "a.md", "line": 12, "message": "说明1", "hint": "建议1"},
                {"relPath": "b.md", "line": 3, "message": "说明2", "hint": ""},
            ]},
        )
        records = issues_from_pipeline([event], "requirement")
        self.assertEqual(len(records), 2)
        self.assertEqual([(r.rel_path, r.line_no) for r in records],
                         [("a.md", 12), ("b.md", 3)])
        self.assertEqual(records[0].message, "说明1")
        self.assertEqual(records[0].suggested_action, "建议1")
        self.assertEqual(records[0].error_code, "E2001")
        self.assertEqual(records[0].severity, "error")
        # 没有 hint 时给出通用可执行建议，而不是空字符串。
        self.assertTrue(records[1].suggested_action)

    def test_pipeline_failure_without_locations_keeps_single_record(self):
        event = SimpleNamespace(
            stage="build", status="failed", detail="构建失败", error_code="E2001",
            metrics={},
        )
        records = issues_from_pipeline([event], "requirement")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].message, "构建失败")

    def test_error_presentation_prefers_concrete_detail(self):
        from doc_tool.ui.workbench_state import error_presentation

        reason, advice = error_presentation(
            "E2001", "3.5.3 上传SD卡.md:12 表格元数据的下一行不是表格"
        )
        # 旧行为只显示「Word 文档构建失败。」，用户无法知道改哪一行。
        self.assertIn("3.5.3 上传SD卡.md:12", reason)
        self.assertTrue(advice)
        # 没有具体原因时仍回落到错误类文案。
        self.assertEqual(error_presentation("E2001", "")[0], "Word 文档构建失败。")

    def test_format_stage_locations_renders_lines_for_result_card(self):
        from doc_tool.ui.workbench_state import format_stage_locations

        events = [
            SimpleNamespace(stage="build", status="succeeded", metrics={}),
            SimpleNamespace(stage="build", status="failed", metrics={"locations": [
                {"relPath": "a.md", "line": 12, "message": "说明", "hint": "建议"},
            ]}),
        ]
        self.assertEqual(format_stage_locations(events), ("a.md:12 说明 建议",))
        self.assertEqual(format_stage_locations([]), ())


class MarkdownStructureLintRuleTests(unittest.TestCase):
    """lint 规则：合并前就能查出会导致合并失败的表格问题。"""

    def _issues(self, body: str, severity: str = "error"):
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.lint import ContentLinter
        from doc_tool.application.content.quality_rules import (
            QualityRule,
            QualityRulesConfig,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "requirement"
            root.mkdir(parents=True)
            (root / "3.5.3 上传SD卡.md").write_text(body, encoding="utf-8")
            config = QualityRulesConfig(Path(tmp) / ".state", "requirement")
            config.save([QualityRule("markdown_structure", True, severity)])
            index = ContentIndexService(root).build()
            return [
                issue for issue in ContentLinter(index, config).check_all([])
                if issue.rule_id == "markdown_structure"
            ]

    def test_orphan_meta_is_reported_before_merging(self):
        issues = self._issues("\n".join([
            META,
            "",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
        ]))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].line_no, 1)
        self.assertEqual(issues[0].severity, "error")
        self.assertEqual(issues[0].rel_path, "3.5.3 上传SD卡.md")
        self.assertIn("空行", issues[0].message)

    def test_non_blocking_findings_stay_warning_even_when_rule_is_error(self):
        issues = self._issues("\n".join([
            "<!-- TBL:style=43 type=auto tw=0 cols=1,2,3 -->",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
        ]))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "warning")

    def test_rule_is_enabled_by_default_for_every_document_type(self):
        from doc_tool.application.content.quality_rules import default_rules

        for document_type in ("requirement", "design", "general"):
            rules = {rule.rule_id: rule for rule in default_rules(document_type)}
            self.assertIn("markdown_structure", rules, document_type)
            self.assertTrue(rules["markdown_structure"].enabled, document_type)

    def test_wellformed_document_is_clean(self):
        self.assertEqual(self._issues("\n".join([
            META,
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
        ])), [])

    def test_check_mermaid_structure_blocking_on_syntax_error(self):
        """Mermaid 语法错误在构建前契约中被标记为 blocking=True。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "# 1. 章节",
            "",
            "```mermaid",
            "flowchart TD",
            "  A[开始) --> B",
            "```",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "mermaid_syntax")
        self.assertEqual(findings[0].line_no, 5)
        self.assertTrue(findings[0].blocking)
        self.assertIn("括号不匹配", findings[0].message)

    def test_check_bare_mermaid_structure_with_preceding_comment(self):
        """裸 Mermaid 块前带注释时，行号精确指向错误代码行且 blocking=True。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "# 1. 章节",
            "",
            "<!-- EMPTY_PAR -->",
            "flowchart TD",
            "  A[开始) --> B",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "mermaid_syntax")
        self.assertEqual(findings[0].line_no, 5)  # 第 5 行是 A[开始) --> B
        self.assertTrue(findings[0].blocking)


    def test_check_mermaid_structure_tolerates_bold_delimiters(self):
        """Mermaid 节点若括号被 Markdown 加粗符号包裹时容错支持"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "```mermaid",
            "flowchart TD",
            '  ReturnResp --> EndStep2**(**"等待上传下一个日期的文件"**)**',
            '  AckMQ --> End**(**"单日解析流程结束"**)**',
            "```",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 0)

    def test_check_mermaid_structure_supports_dotted_text_edge(self):
        """Mermaid flowchart 支持虚线文字连线 A -. text .-> B"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "```mermaid",
            "flowchart LR",
            "  C1 -. TODO 单一URL .-> TEST[受控连通性测试客户端]",
            "  TEST -. 无业务载荷探测 .-> TARGET[客户URL]",
            "```",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 0)

    def test_check_mermaid_structure_supports_case_insensitive_sequence_notes(self):
        """Mermaid sequenceDiagram 支持小写 note over 语句"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "```mermaid",
            "sequenceDiagram",
            "  participant U as User",
            "  participant DB as Database",
            "  note over U, DB: 场景一：页面加载与多维组合查询",
            "  U->>DB: Query",
            "```",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 0)

    def test_check_mermaid_structure_supports_chained_edges_with_labels(self):
        """Mermaid flowchart 支持带标签的链式连线 A -->|label| B --> C"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "```mermaid",
            "flowchart LR",
            "  CacheRouter -->|查库| DbQueryEngine --> TblConfig",
            "```",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 0)

    def test_check_mermaid_structure_detects_broken_fence(self):
        """Mermaid 围栏反引号少于 3 个（如 ``mermaid）时应报告语法错误。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "## 章节标题",
            "",
            "``mermaid",
            "flowchart TD",
            "  A --> B",
            "``",
        ]
        findings = check_mermaid_structure(lines)
        self.assertTrue(any(f.rule == "mermaid_syntax" and "3 个反引号" in f.message for f in findings))

    def test_check_mermaid_structure_ignores_inline_code_span(self):
        """行首包含行内代码如 `mermaid` 语法时，不应被误报为残缺围栏。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "## 章节标题",
            "",
            "`mermaid` 是标准的图表画图语法。",
            "另外也支持 ``mermaid`` 这种双反引号行内标记。",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 0)


    def test_check_mermaid_structure_ignores_broken_mermaid_inside_fenced_code_block(self):
        """代码块内部引用残缺 mermaid 示例（如 ```markdown 块内）不应误报阻断错误。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "## 语法说明",
            "",
            "```markdown",
            "示例残缺代码块：",
            "``mermaid",
            "flowchart TD",
            "  A --> B",
            "``",
            "```",
            "",
            "正文描述继续。",
        ]
        findings = check_mermaid_structure(lines)
        self.assertEqual(len(findings), 0)

    def test_check_mermaid_structure_detects_mismatched_inline_backticks(self):
        """双反引号开头但单反引号闭合的残缺标记应被正确判定为未闭合。"""
        from doc_tool.domain.markdown_structure import check_mermaid_structure

        lines = [
            "## 章节标题",
            "",
            "``mermaid ` 未正确闭合",
        ]
        findings = check_mermaid_structure(lines)
        self.assertTrue(any(f.rule == "mermaid_syntax" for f in findings))


if __name__ == "__main__":
    unittest.main(verbosity=2)

