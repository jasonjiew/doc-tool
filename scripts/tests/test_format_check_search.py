# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tempfile
import unittest
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from doc_tool.application.content.lint import (
    RULE_CATEGORIES,
    RULE_CATEGORY_GROUPS,
    RULE_LABELS,
    SEVERITY_LABELS,
    ContentLinter,
    LintIssue,
    TermStore,
    filter_lint_issues,
)
from doc_tool.application.content.quality_rules import QualityRulesConfig
from doc_tool.application.content.writer import ContentWriter
from doc_tool.application.issues import IssueRecord, filter_issues
from doc_tool.application.project_service import filter_validation_report_content
from doc_tool.domain.content_index import ContentIndex, FileEntry
from doc_tool.ui.content.issues_panel import IssuesPanel
from doc_tool.ui.content.lint_panel import LintPanel, LintTreeItem

_app = QApplication.instance() or QApplication([])


class FormatCheckSearchTests(unittest.TestCase):
    def setUp(self):
        self.issues = [
            LintIssue("heading_format", "ch01/intro.md", 1, "标题 '#' 缺少空格：'#1.1 简介'", "heading_format", "warning"),
            LintIssue("heading_format", "ch01/detail.md", 10, "标题 '#' 缺少空格：'##1.2 详情'", "heading_format", "warning"),
            LintIssue("markdown_structure", "ch02/table.md", 25, "表格缺少分隔行", "markdown_structure", "error"),
            LintIssue("mermaid_syntax", "ch03/flow.md", 40, "流程图语法错误：--> 无法识别", "mermaid_syntax", "error"),
            LintIssue("todo_residual", "ch04/spec.md", 15, "包含 TODO 残留", "todo_residual", "warning"),
            LintIssue("term_case", "ch04/spec.md", 30, "术语应为 'wifi'，规范应为 'WiFi'", "term_case", "info"),
            LintIssue("duplicate_title", "ch05/other.md", 5, "重复标题：'概述'", "duplicate_title", "warning"),
            LintIssue("sensitive_info", "ch06/security.md", 8, "可能泄露敏感信息", "sensitive_info", "warning"),
        ]

    # --- 1. 逻辑层：filter_lint_issues 检索测试 ---

    def test_filter_by_category_group(self):
        # 格式规范大类（含 heading_format, markdown_structure, mermaid_syntax）
        fmt_issues = filter_lint_issues(self.issues, category="格式规范")
        self.assertEqual(len(fmt_issues), 4)
        self.assertTrue(all(i.rule_id in ("heading_format", "markdown_structure", "mermaid_syntax") for i in fmt_issues))

        # 带 group: 前缀的大类筛选
        fmt_group = filter_lint_issues(self.issues, category="group:格式规范")
        self.assertEqual(len(fmt_group), 4)

        # 内容质量大类（todo_residual, term_case, duplicate_title）
        quality_issues = filter_lint_issues(self.issues, category="内容质量")
        self.assertEqual(len(quality_issues), 3)

        # 合规与安全大类（sensitive_info）
        sec_issues = filter_lint_issues(self.issues, category="合规与安全")
        self.assertEqual(len(sec_issues), 1)
        self.assertEqual(sec_issues[0].rule_id, "sensitive_info")

        # 不存在的类别大类应返回 0 项，不应全量漏出
        invalid_group = filter_lint_issues(self.issues, category="group:不存在的类别")
        self.assertEqual(len(invalid_group), 0)

    def test_filter_by_specific_rule_or_label(self):
        # 按规则 ID
        heading_issues = filter_lint_issues(self.issues, category="heading_format")
        self.assertEqual(len(heading_issues), 2)

        # 按规则中文标签
        table_issues = filter_lint_issues(self.issues, category="表格结构")
        self.assertEqual(len(table_issues), 1)
        self.assertEqual(table_issues[0].rule_id, "markdown_structure")

        # 按 rule_id 精确过滤
        mermaid = filter_lint_issues(self.issues, rule_id="mermaid_syntax")
        self.assertEqual(len(mermaid), 1)
        self.assertEqual(mermaid[0].rel_path, "ch03/flow.md")

    def test_filter_by_severity(self):
        errors = filter_lint_issues(self.issues, severity="error")
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(i.severity == "error" for i in errors))

        infos = filter_lint_issues(self.issues, severity="info")
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].rule_id, "term_case")

    def test_filter_by_quick_fixable(self):
        # heading_format（缺少空格）、term_case、markdown_structure（缺少分隔行）支持自动修复
        fixable = filter_lint_issues(self.issues, quick_fixable=True)
        self.assertTrue(len(fixable) >= 4)
        for item in fixable:
            self.assertIn(item.rule_id, ("heading_format", "term_case", "markdown_structure"))

        non_fixable = filter_lint_issues(self.issues, quick_fixable=False)
        self.assertTrue(any(i.rule_id == "mermaid_syntax" for i in non_fixable))
        self.assertTrue(any(i.rule_id == "todo_residual" for i in non_fixable))

    def test_filter_by_keyword_search(self):
        # 按文件路径
        by_file = filter_lint_issues(self.issues, keyword="ch01")
        self.assertEqual(len(by_file), 2)

        # 按说明中的关键词（不区分大小写）
        by_msg = filter_lint_issues(self.issues, keyword="wifi")
        self.assertEqual(len(by_msg), 1)
        self.assertEqual(by_msg[0].rule_id, "term_case")

        # 按行号
        by_line = filter_lint_issues(self.issues, keyword="25")
        self.assertEqual(len(by_line), 1)
        self.assertEqual(by_line[0].rel_path, "ch02/table.md")

        # 按规则中文标签
        by_label = filter_lint_issues(self.issues, keyword="流程图语法")
        self.assertEqual(len(by_label), 1)
        self.assertEqual(by_label[0].rule_id, "mermaid_syntax")

        # 多词联合检索（空格分隔）
        multi_word = filter_lint_issues(self.issues, keyword="ch01 intro")
        self.assertEqual(len(multi_word), 1)
        self.assertEqual(multi_word[0].rel_path, "ch01/intro.md")

        # 支持搜索“可修复”或“一键修复”
        by_fix_tag = filter_lint_issues(self.issues, keyword="可修复")
        self.assertTrue(len(by_fix_tag) >= 3)
        self.assertTrue(all(item.rule_id in ("heading_format", "term_case", "markdown_structure") for item in by_fix_tag))

        # 不匹配关键词返回空列表
        no_match = filter_lint_issues(self.issues, keyword="完全不存在的999")
        self.assertEqual(len(no_match), 0)

    def test_filter_combined_category_and_keyword(self):
        # 分类为格式规范 + 搜索 "简介"
        res = filter_lint_issues(self.issues, category="格式规范", keyword="简介")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].rel_path, "ch01/intro.md")

        # 分类为格式规范 + 搜索 "wifi"（应无匹配）
        res = filter_lint_issues(self.issues, category="格式规范", keyword="wifi")
        self.assertEqual(len(res), 0)

        # 分类为内容质量 + 搜索 "spec"
        res = filter_lint_issues(self.issues, category="内容质量", keyword="spec")
        self.assertEqual(len(res), 2)

        # 分类 + 严重度 + 关键词联合筛选
        res = filter_lint_issues(
            self.issues,
            category="group:格式规范",
            severity="error",
            keyword="table",
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].rel_path, "ch02/table.md")

    # --- 2. GUI 面板：LintPanel 分类搜索交互测试 ---

    def test_lint_panel_filter_interactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            content_dir = tmp_p / "content"
            content_dir.mkdir(parents=True)
            state_dir = tmp_p / ".state"
            state_dir.mkdir(parents=True)

            writer = ContentWriter(content_dir, state_dir)
            terms = TermStore(state_dir)
            index = ContentIndex()
            linter = ContentLinter(index, QualityRulesConfig(state_dir, "general"))

            opened = []
            panel = LintPanel(
                linter,
                terms,
                on_open=lambda rel, line: opened.append((rel, line)),
                writable=True,
                writer=writer,
            )

            # 注入测试问题集合（包含一项未映射标签的动态自定义规则）
            custom_issue = LintIssue("custom_unmapped_rule", "ch07/extra.md", 3, "自定义质量告警", "custom_unmapped_rule", "warning")
            panel._issues = list(self.issues) + [custom_issue]
            panel._refresh_category_combo()
            panel._render_results()

            # 验证控件初始状态
            self.assertTrue(hasattr(panel, "_category_combo"))
            self.assertTrue(hasattr(panel, "_severity_combo"))
            self.assertTrue(hasattr(panel, "_fixable_combo"))
            self.assertTrue(hasattr(panel, "_search_input"))
            self.assertTrue(hasattr(panel, "_reset_btn"))
            self.assertTrue(hasattr(panel, "_quick_fix_filtered_btn"))

            # 验证自定义动态规则也被纳如下拉框，不丢项
            idx_custom = panel._category_combo.findData("custom_unmapped_rule")
            self.assertTrue(idx_custom >= 0)

            # 初始应展示全部 9 项
            self.assertEqual(panel._tree.topLevelItemCount(), 9)
            self.assertIn("共 9 项", panel._status_label.text())
            # 未进行筛选时，底部“修复当前筛选”禁用
            self.assertFalse(panel._quick_fix_filtered_btn.isEnabled())

            # 1. 测试按大类筛选：选择「【格式规范】全部」
            idx = panel._category_combo.findData("group:格式规范")
            self.assertTrue(idx >= 0)
            panel._category_combo.setCurrentIndex(idx)
            self.assertEqual(panel._tree.topLevelItemCount(), 4)
            self.assertIn("已筛选显示 4 / 共 9 项", panel._status_label.text())
            # 筛选后包含可修复项，底部的“⚡ 修复当前筛选”应立即可用
            self.assertTrue(panel._quick_fix_filtered_btn.isEnabled())

            # 2. 测试在大类筛选基础上进行关键词搜索：输入 "简介"
            panel._search_input.setText("简介")
            self.assertEqual(panel._tree.topLevelItemCount(), 1)
            item = panel._tree.topLevelItem(0)
            self.assertEqual(item.text(0), "ch01/intro.md")

            # 验证点击筛选后的项目可以正确定位到原始文件及行号
            panel._on_activate(item)
            self.assertEqual(opened, [("ch01/intro.md", 1)])

            # 3. 搜索不匹配内容，验证状态栏无匹配提示
            panel._search_input.setText("不存在的词条XYZ")
            self.assertEqual(panel._tree.topLevelItemCount(), 0)
            self.assertIn("无匹配结果", panel._status_label.text())
            self.assertFalse(panel._quick_fix_filtered_btn.isEnabled())

            # 4. 测试重置功能：重置后应恢复全部 9 项
            panel.reset_filters()
            self.assertEqual(panel._category_combo.currentIndex(), 0)
            self.assertEqual(panel._search_input.text(), "")
            self.assertEqual(panel._tree.topLevelItemCount(), 9)

            # 5. 测试按严重度筛选：选择「阻断 (error)」
            sev_idx = panel._severity_combo.findData("error")
            panel._severity_combo.setCurrentIndex(sev_idx)
            self.assertEqual(panel._tree.topLevelItemCount(), 2)
            self.assertIn("已筛选显示 2 / 共 9 项", panel._status_label.text())

            # 6. 测试按修复状态筛选：选择「⚡ 仅可一键修复」
            panel._severity_combo.setCurrentIndex(0)
            fix_idx = panel._fixable_combo.findData("fixable")
            panel._fixable_combo.setCurrentIndex(fix_idx)
            self.assertTrue(panel._tree.topLevelItemCount() >= 4)
            for i in range(panel._tree.topLevelItemCount()):
                item_label = panel._tree.topLevelItem(i).text(2)
                self.assertIn("[⚡可修复]", item_label)

    def test_lint_panel_quick_fix_in_filtered_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            content_dir = tmp_p / "content"
            content_dir.mkdir(parents=True)
            state_dir = tmp_p / ".state"
            state_dir.mkdir(parents=True)

            md1 = content_dir / "1.1_test.md"
            md1.write_text("#1.1 第一节\n#1.2 第二节\n", encoding="utf-8")
            md2 = content_dir / "2.1_test.md"
            md2.write_text("#2.1 另一节\n", encoding="utf-8")

            index = ContentIndex()
            writer = ContentWriter(content_dir, state_dir)
            terms = TermStore(state_dir)
            linter = ContentLinter(index, QualityRulesConfig(state_dir, "general"))

            panel = LintPanel(linter, terms, writable=True, writer=writer)

            i1 = LintIssue("heading_format", "1.1_test.md", 1, "标题 '#' 缺少空格：'#1.1 第一节'", "heading_format")
            i2 = LintIssue("heading_format", "1.1_test.md", 2, "标题 '#' 缺少空格：'#1.2 第二节'", "heading_format")
            i3 = LintIssue("heading_format", "2.1_test.md", 1, "标题 '#' 缺少空格：'#2.1 另一节'", "heading_format")
            panel._issues = [i1, i2, i3]
            panel._refresh_category_combo()
            panel._render_results()

            # 筛选：仅搜索 1.1_test.md
            panel._search_input.setText("1.1_test")
            self.assertEqual(panel._tree.topLevelItemCount(), 2)
            self.assertTrue(panel._quick_fix_filtered_btn.isEnabled())

            # 调用 quick_fix_all_in_filtered 批量修复当前筛选结果
            fixed = panel.quick_fix_all_in_filtered()
            self.assertEqual(fixed, 2)
            self.assertEqual(md1.read_text(encoding="utf-8"), "# 1.1 第一节\n# 1.2 第二节\n")
            # 未在筛选范围内的 2.1_test.md 保持未修复
            self.assertEqual(md2.read_text(encoding="utf-8"), "#2.1 另一节\n")

    def test_lint_panel_filter_all_issues_still_allows_fix_filtered(self):
        """当项目内所有问题恰好全部命中筛选条件时，仍允许执行「修复当前筛选」与右键菜单。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            content_dir = tmp_p / "content"
            content_dir.mkdir(parents=True)
            state_dir = tmp_p / ".state"
            state_dir.mkdir(parents=True)

            md1 = content_dir / "1.1_test.md"
            md1.write_text("#1.1 第一节\n", encoding="utf-8")

            index = ContentIndex()
            writer = ContentWriter(content_dir, state_dir)
            terms = TermStore(state_dir)
            linter = ContentLinter(index, QualityRulesConfig(state_dir, "general"))

            panel = LintPanel(linter, terms, writable=True, writer=writer)

            i1 = LintIssue("heading_format", "1.1_test.md", 1, "标题 '#' 缺少空格：'#1.1 第一节'", "heading_format")
            panel._issues = [i1]
            panel._refresh_category_combo()
            panel._render_results()

            # 筛选：选择标题格式分类（此时 1/1 命中，filtered_indices == len(_issues)）
            idx = panel._category_combo.findData("heading_format")
            panel._category_combo.setCurrentIndex(idx)
            self.assertEqual(panel._tree.topLevelItemCount(), 1)
            # 因为存在筛选激活且存在可修复项，底部的“⚡ 修复当前筛选”应依然可用
            self.assertTrue(panel._quick_fix_filtered_btn.isEnabled())

    # --- 3. GUI 面板：IssuesPanel 搜索与重置测试 ---

    def test_issues_panel_search_and_reset(self):
        panel = IssuesPanel()
        records = [
            IssueRecord("lint", "heading_format", "general", "warning", "ch1/intro.md", 1, None, "标题缺少空格", "补空格"),
            IssueRecord("pipeline", "build", "general", "error", "ch2/build.md", 20, "E3001", "代码块未闭合", "闭合"),
            IssueRecord("validation", "validation", "general", "error", "ch3/val.md", 5, "E2002", "悬空引用", "修复"),
        ]
        panel.set_issues(records)
        self.assertEqual(panel._tree.topLevelItemCount(), 3)

        # 1. 搜索说明关键词
        panel._search_input.setText("代码块")
        self.assertEqual(panel._tree.topLevelItemCount(), 1)
        self.assertEqual(panel.filtered_issues()[0].rel_path, "ch2/build.md")

        # 2. 搜索规则中文标签
        panel._search_input.setText("标题格式")
        self.assertEqual(panel._tree.topLevelItemCount(), 1)
        self.assertEqual(panel.filtered_issues()[0].issue_type, "heading_format")

        # 3. 搜索严重度中文标签
        panel._search_input.setText("阻断")
        self.assertEqual(panel._tree.topLevelItemCount(), 2)

        # 4. 多词联合搜索
        panel._search_input.setText("ch1 缺少空格")
        self.assertEqual(panel._tree.topLevelItemCount(), 1)

        # 5. 重置
        panel.reset_filters()
        self.assertEqual(panel._search_input.text(), "")
        self.assertEqual(panel._tree.topLevelItemCount(), 3)

    # --- 4. 校验报告内容筛选测试 ---

    def test_filter_validation_report_content(self):
        report_text = """# requirement 严格校验报告

## 校验结果

- [PASS] DOCX ZIP 与全部 XML 可解析
- [PASS] 章节编号、层级与必需资源预检 — 章节条目 264
- [FAIL] chapters/3.7.md:12 编号不连续
- [FAIL] content/requirement/概述/_index.md:3 内部层级跳跃

## 关键指标

- Markdown: 216
- Heading: 660

## 总结

- PASS: 2
- FAIL: 2
- 结论: 失败
"""
        # 仅失败项：不保留空的指标与总结段落
        fail_text, fail_cnt = filter_validation_report_content(report_text, status_filter="FAIL")
        self.assertEqual(fail_cnt, 2)
        self.assertIn("[FAIL] chapters/3.7.md:12", fail_text)
        self.assertIn("[FAIL] content/requirement/概述", fail_text)
        self.assertNotIn("[PASS]", fail_text)
        self.assertNotIn("## 关键指标", fail_text)

        # 仅通过项
        pass_text, pass_cnt = filter_validation_report_content(report_text, status_filter="PASS")
        self.assertEqual(pass_cnt, 2)
        self.assertIn("[PASS] DOCX ZIP", pass_text)
        self.assertNotIn("[FAIL]", pass_text)
        self.assertNotIn("## 关键指标", pass_text)

        # 关键指标与统计（METRICS）：只保留指标与总结，不保留空的校验结果
        metrics_text, metrics_cnt = filter_validation_report_content(report_text, status_filter="METRICS")
        self.assertTrue(metrics_cnt >= 4)
        self.assertIn("## 关键指标", metrics_text)
        self.assertIn("- Markdown: 216", metrics_text)
        self.assertNotIn("## 校验结果", metrics_text)
        self.assertNotIn("[FAIL]", metrics_text)

        # 关键词检索
        kw_text, kw_cnt = filter_validation_report_content(report_text, keyword="编号不连续")
        self.assertEqual(kw_cnt, 1)
        self.assertIn("chapters/3.7.md:12 编号不连续", kw_text)

        # 多词检索
        multi_text, multi_cnt = filter_validation_report_content(report_text, keyword="FAIL 3.7.md")
        self.assertEqual(multi_cnt, 1)
        self.assertIn("chapters/3.7.md:12", multi_text)

        # 状态 + 关键词联合检索
        joint_text, joint_cnt = filter_validation_report_content(report_text, status_filter="FAIL", keyword="内部层级")
        self.assertEqual(joint_cnt, 1)
        self.assertIn("内部层级跳跃", joint_text)
        self.assertNotIn("3.7.md", joint_text)


if __name__ == "__main__":
    unittest.main()
