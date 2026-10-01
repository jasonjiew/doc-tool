# -*- coding: utf-8 -*-
"""V2.7 共享表达契约回归（任务 27-A/27-B/27-D）。

覆盖共享块解析（代码块、题注、横向节、分页）、题注注册表与引用解析，
并用真实模板对共享夹具执行一次完整构建 + 严格校验，确认代码容器、
题注编号、横向节与分页都真实落到 DOCX 里。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from doc_tool.domain.blocks import (
    KIND_CODE,
    KIND_IMAGE,
    KIND_PAGEBREAK,
    KIND_SECTION,
    KIND_TABLE,
    parse_blocks,
)
from doc_tool.domain.captions import (
    KIND_FIGURE,
    KIND_TABLE_CAPTION,
    build_registry,
    resolve_inline_references,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for candidate in (str(SCRIPTS_DIR), str(REPO_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v27" / "expression-sample.md"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NL = chr(10)


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class SharedParserTests(unittest.TestCase):
    """共享块解析：代码围栏、题注、分节与分页。"""

    def test_fixture_blocks_cover_declared_kinds(self):
        document = parse_blocks(fixture_text(), str(FIXTURE))
        kinds = {block.kind for block in document.blocks}
        self.assertIn(KIND_CODE, kinds)
        self.assertIn(KIND_IMAGE, kinds)
        self.assertIn(KIND_TABLE, kinds)
        self.assertIn(KIND_SECTION, kinds)
        self.assertIn(KIND_PAGEBREAK, kinds)

    def test_code_block_preserves_indent_tab_blank_and_backticks(self):
        document = parse_blocks(fixture_text(), str(FIXTURE))
        code = [block for block in document.blocks if block.kind == KIND_CODE]
        self.assertTrue(code)
        python_block = next(block for block in code if block.language == "python")
        self.assertIn("    if ", python_block.text)
        self.assertIn("\treturn", python_block.text)
        self.assertIn("\n\n", python_block.text)
        self.assertIn("`", python_block.text)

    def test_mermaid_fence_is_a_code_block_with_language(self):
        document = parse_blocks(fixture_text(), str(FIXTURE))
        mermaid = [
            block
            for block in document.blocks
            if block.kind == KIND_CODE and block.is_mermaid
        ]
        self.assertGreaterEqual(len(mermaid), 2)
        self.assertIn("flowchart", mermaid[0].text)

    def test_unclosed_fence_closes_at_end_with_warning(self):
        document = parse_blocks("# 标题\n\n```python\nprint(1)\n", "unclosed.md")
        code = [block for block in document.blocks if block.kind == KIND_CODE]
        self.assertEqual(len(code), 1)
        self.assertFalse(code[0].closed)
        self.assertIn(
            "code_fence_unclosed", {warning.rule for warning in document.warnings}
        )

    def test_landscape_section_and_pagebreak_detected(self):
        document = parse_blocks(fixture_text(), str(FIXTURE))
        markers = [
            block.marker for block in document.blocks if block.kind == KIND_SECTION
        ]
        self.assertIn("landscape", markers)
        self.assertIn("end", markers)
        self.assertTrue(any(block.kind == KIND_PAGEBREAK for block in document.blocks))

    def test_unclosed_landscape_closes_with_warning(self):
        document = parse_blocks("<!-- LANDSCAPE -->\n\n| A |\n| --- |\n| 1 |\n", "x.md")
        self.assertIn(
            "landscape_unclosed", {warning.rule for warning in document.warnings}
        )
        self.assertTrue(
            any(
                block.kind == KIND_SECTION
                and block.marker == "end"
                and block.implicit
                for block in document.blocks
            )
        )

    def test_nested_landscape_keeps_first_level(self):
        text = (
            "<!-- LANDSCAPE -->\n<!-- LANDSCAPE -->\n"
            "| A |\n| --- |\n| 1 |\n<!-- END_LANDSCAPE -->\n"
        )
        document = parse_blocks(text, "nested.md")
        self.assertIn(
            "landscape_nested", {warning.rule for warning in document.warnings}
        )
        starts = [
            block
            for block in document.blocks
            if block.kind == KIND_SECTION and block.marker == "landscape"
        ]
        self.assertEqual(len(starts), 1)

    def test_orphan_landscape_end_warns(self):
        document = parse_blocks("<!-- END_LANDSCAPE -->\n", "orphan.md")
        self.assertIn(
            "landscape_orphan_end", {warning.rule for warning in document.warnings}
        )

    def test_same_markdown_yields_identical_blocks(self):
        first = parse_blocks(fixture_text(), str(FIXTURE))
        second = parse_blocks(fixture_text(), str(FIXTURE))
        self.assertEqual(
            [(block.kind, block.location.start_line) for block in first.blocks],
            [(block.kind, block.location.start_line) for block in second.blocks],
        )


class CaptionRegistryTests(unittest.TestCase):
    """题注编号与引用解析（共享注册表）。"""

    def _registry(self):
        document = parse_blocks(fixture_text(), str(FIXTURE))
        return build_registry([document])

    def test_figures_and_tables_number_independently_in_order(self):
        registry = self._registry()
        # order 保留每一次登记（含重复标识），entries 只保留首次登记的目标。
        figures = [entry for entry in registry.order_entries() if entry.kind == KIND_FIGURE]
        tables = [entry for entry in registry.order_entries() if entry.kind == KIND_TABLE_CAPTION]
        self.assertEqual([entry.number for entry in figures], [1])
        self.assertEqual([entry.number for entry in tables], [1, 2, 3, 4])

    def test_reference_resolves_to_display_text(self):
        registry = self._registry()
        text = resolve_inline_references("见 @fig-flow 与 @tbl-sequence。", registry)
        self.assertNotIn("@fig-flow", text)
        self.assertNotIn("@tbl-sequence", text)
        self.assertIn("图 1", text)
        self.assertIn("表 2", text)

    def test_duplicate_reference_keeps_first_target(self):
        document = parse_blocks(
            "![a](x.png){#fig-dup}\n\n![b](y.png){#fig-dup}\n", "dup.md"
        )
        registry = build_registry([document])
        text = resolve_inline_references("见 @fig-dup。", registry)
        self.assertIn("图 1", text)

    def test_unknown_reference_keeps_readable_placeholder(self):
        registry = self._registry()
        text = resolve_inline_references("见 @fig-missing。", registry)
        self.assertIn("引用待确认", text)
        self.assertIn("@fig-missing", text)

    def test_reference_without_registry_is_unchanged(self):
        self.assertEqual(
            resolve_inline_references("见 @fig-flow。", None), "见 @fig-flow。"
        )

    def test_duplicate_identifier_is_reported_and_output_renamed(self):
        document = parse_blocks(
            "![a](x.png){#fig-dup}\n\n![b](y.png){#fig-dup}\n", "dup.md"
        )
        registry = build_registry([document])
        self.assertEqual(len(registry.duplicates), 1)
        renamed = [
            entry.output_ident
            for entry in registry.order_entries()
            if entry.output_ident != entry.ident
        ]
        self.assertTrue(renamed)

class PreviewRegistryTests(unittest.TestCase):
    """预览必须与出稿共用同一题注注册表（编号一致）。"""

    def _registry(self):
        from doc_tool.application.content.preview import build_caption_registry

        text = (
            "## 1.1 图\n\n"
            "![a](a.png)\n\n"
            "Figure: 登录流程 {#fig-flow}\n\n"
            "Table: 参数表 {#tbl-params}\n\n"
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "见 @fig-flow 与 @tbl-params。\n"
        )
        return build_caption_registry([("preview.md", text)])

    def test_preview_blocks_resolve_references(self):
        from doc_tool.application.content.preview import render_preview_blocks

        registry = self._registry()
        text = "见 @fig-flow 与 @tbl-params。"
        resolved = render_preview_blocks(text, registry=registry)
        self.assertEqual(len(resolved), 1)
        self.assertIn("图 1", resolved[0].text)
        self.assertIn("表 1", resolved[0].text)
        self.assertNotIn("@fig-flow", resolved[0].text)

        plain = render_preview_blocks(text)
        self.assertIn("@fig-flow", plain[0].text, "不传注册表时保持原文")

    def test_preview_html_resolves_references(self):
        from doc_tool.application.content.preview import render_markdown_html

        registry = self._registry()
        html_text = render_markdown_html("见 @fig-flow。", registry=registry)
        self.assertIn("图 1", html_text)
        self.assertNotIn("@fig-flow", html_text)
        # 不传注册表时保持原文（两者必须不同）。
        plain = render_markdown_html("见 @fig-flow。")
        self.assertIn("@fig-flow", plain)
        self.assertNotEqual(html_text, plain)

    def test_preview_table_cells_resolve_references(self):
        from doc_tool.application.content.preview import render_preview_blocks

        registry = self._registry()
        md = "| 引用 |" + NL + "| --- |" + NL + "| @tbl-params |" + NL
        blocks = render_preview_blocks(md, registry=registry)
        table = [block for block in blocks if block.kind == "table"]
        self.assertTrue(table)
        cells = [cell for row in table[0].rows for cell in row]
        self.assertTrue(
            any("表 1" in cell for cell in cells),
            "预览表格单元格应解析为可读引用：{0}".format(cells),
        )
        # 不传注册表时单元格保持原文。
        plain = render_preview_blocks(md)
        plain_table = [block for block in plain if block.kind == "table"]
        plain_cells = [cell for row in plain_table[0].rows for cell in row]
        self.assertTrue(any("@tbl-params" in cell for cell in plain_cells))


class ImportFidelityReportTests(unittest.TestCase):
    """导入保真报告（V2.7 5.5）：有损报告不得被标为无差异。"""

    def _finding(self, feature, label, severity, count, samples=()):
        from doc_tool.adapters.fidelity import FidelityFinding

        return FidelityFinding(
            feature=feature, label=label, severity=severity, count=count, samples=samples
        )

    def _report(self, findings):
        from doc_tool.adapters.fidelity import FidelityReport, build_import_report

        return build_import_report(FidelityReport(tuple(findings)))

    def test_clean_import_reports_no_difference(self):
        report = self._report([])
        self.assertFalse(report.lossy)
        self.assertEqual(report.status, "ok")
        self.assertIn("未发现差异", report.markdown_text())

    def test_degraded_feature_is_not_reported_as_clean(self):
        report = self._report(
            [
                self._finding("warn_x", "列表层级", "WARN", 2, ("body[3]",)),
                self._finding("info_y", "行内格式", "INFO", 5, ("body[1]",)),
            ]
        )
        self.assertTrue(report.lossy, "有降级时不得标为无差异")
        self.assertEqual(report.status, "warning")
        text = report.markdown_text()
        self.assertNotIn("未发现差异", text)
        self.assertIn("列表层级", text)
        self.assertIn("保留特性", text)

    def test_blocked_feature_wins_status(self):
        report = self._report(
            [
                self._finding("block_z", "图表对象", "BLOCK", 1, ("body[9]",)),
                self._finding("warn_x", "引用", "WARN", 1),
            ]
        )
        self.assertEqual(report.status, "blocked")

    def test_roundtrip_warn_becomes_degradation_note(self):
        from doc_tool.adapters.fidelity import FidelityReport, build_import_report
        from doc_tool.adapters.roundtrip import RoundtripIssue, RoundtripReport

        roundtrip = RoundtripReport(
            2,
            2,
            (
                RoundtripIssue(
                    severity="WARN",
                    message="段落格式降级",
                    position="body[2]",
                ),
            ),
        )
        report = build_import_report(FidelityReport(()), roundtrip)
        self.assertTrue(report.lossy)
        self.assertIn("段落格式降级", report.markdown_text())

    def test_issue_records_carry_location_and_severity(self):
        from doc_tool.application.issues import issues_from_import_report

        report = self._report(
            [
                self._finding("warn_x", "列表层级", "WARN", 2, ("word/footnotes.xml",)),
                self._finding("block_z", "图表对象", "BLOCK", 1, ("body[4]",)),
            ]
        )
        records = issues_from_import_report(report, document_type="general")
        severities = {record.severity for record in records}
        self.assertIn("error", severities)
        self.assertIn("warning", severities)
        messages = " ".join(record.message for record in records)
        self.assertIn("列表层级", messages)
        self.assertIn("图表对象", messages)

    def test_preflight_exposes_import_report(self):
        """预检结果必须带导入保真报告（供结果页与问题中心复用）。"""
        import shutil
        import tempfile

        from doc_tool.adapters import preflight as preflight_module

        root = Path(tempfile.mkdtemp(prefix="v27-preflight-report-"))
        try:
            source = root / "source.docx"
            shutil.copy2(TEMPLATE, source)
            # 极简模板无标题：导入预检用 allow_missing_headings（参数包容方式）。
            preview = preflight_module.preflight(
                str(source), allow_missing_headings=True
            )
            self.assertIsNotNone(preview.import_report)
            self.assertIn(preview.import_report.status, ("ok", "warning", "blocked"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_wizard_summary_shows_lossy_import_report(self):
        """向导摘要必须在有损时显示降级/阻断，不得只说“无告警”。"""
        from doc_tool.ui.wizard import format_preview_summary

        class _Preview:
            heading_level_counts = {1: 1}
            image_count = 0
            table_count = 0
            warnings = []
            fidelity = None
            import_report = None

        report = self._report(
            [self._finding("warn_x", "列表层级", "WARN", 2, ("body[3]",))]
        )
        preview = _Preview()
        preview.import_report = report
        text = format_preview_summary(preview)
        self.assertIn("带提醒导入", text)
        self.assertIn("列表层级", text)

        clean = _Preview()
        clean.import_report = self._report([])
        clean_text = format_preview_summary(clean)
        self.assertNotIn("带提醒导入", clean_text)

    def test_clean_report_produces_no_issue_records(self):
        from doc_tool.application.issues import issues_from_import_report

        self.assertEqual(issues_from_import_report(self._report([])), [])


class PreviewFidelityTests(unittest.TestCase):
    """内置预览必须保留代码高亮与长表全部行（V2.7 5.2）。

    回归：编辑器已统一走内置预览（不再依赖 WebEngine），
    因此代码高亮与长表不能因此退化。
    """

    def test_code_block_highlighted_and_not_parsed_as_heading(self):
        from doc_tool.application.content.preview import render_markdown_html

        md = "```python" + NL + "def f():" + NL + "# 注释" + NL + "```" + NL
        rendered = render_markdown_html(md)
        # 代码块输出为 <pre class="code-block language-python">，关键字染色。
        self.assertIn("code-block language-python", rendered)
        self.assertIn("注释", rendered)
        self.assertIn("color: #0550ae", rendered)
        # 围栏内的 # 行不得变成标题。
        self.assertNotIn("<h1", rendered.lower())

    def test_long_table_keeps_all_rows(self):
        from doc_tool.application.content.preview import render_preview_blocks

        lines = ["| 列A | 列B |", "| --- | --- |"]
        for index in range(1, 61):
            lines.append("| 行{0} | 值{0} |".format(index))
        blocks = render_preview_blocks(NL.join(lines))
        tables = [block for block in blocks if block.kind == "table"]
        self.assertEqual(len(tables), 1)
        # 1 行表头 + 60 行数据（分隔行已剔除）。
        self.assertEqual(len(tables[0].rows), 61)
        self.assertIn("行60", "".join(tables[0].rows[-1]))

    def test_preview_summary_counts_blocks(self):
        from doc_tool.application.content.preview import preview_summary

        summary = preview_summary("# 标题" + NL + NL + "正文。" + NL)
        self.assertIn("标题 1", summary)
        self.assertIn("段落 1", summary)


class ReferenceWarningTests(unittest.TestCase):
    """歧义/缺失引用必须带源文件与行号（不猜目标）。"""

    def test_missing_and_ambiguous_references_carry_locations(self):
        from doc_tool.domain.captions import (
            build_registry,
            reference_warnings,
        )

        text = (
            "## 1.1 图\n\n"
            "Table: 参数表 {#tbl-params}\n\n"
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "Table: 参数表二 {#tbl-params-a}\n\n"
            "| A | B |\n| --- | --- |\n| 3 | 4 |\n\n"
            "见 @tbl-params 与 @tbl-missing。\n"
        )
        document = parse_blocks(text, "refs.md")
        registry = build_registry([document])
        warnings = reference_warnings([document], registry)
        rules = {item["rule"] for item in warnings}
        self.assertIn("caption_reference_missing", rules)
        for item in warnings:
            self.assertEqual(item["path"], "refs.md")
            self.assertGreaterEqual(item["line"], 1)
        missing = [item for item in warnings if item["rule"] == "caption_reference_missing"]
        self.assertTrue(any("@tbl-missing" in item["message"] for item in missing))

    def test_resolved_reference_produces_no_warning(self):
        from doc_tool.domain.captions import build_registry, reference_warnings

        text = (
            "Table: 参数表 {#tbl-params}\n\n"
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "见 @tbl-params。\n"
        )
        document = parse_blocks(text, "ok.md")
        registry = build_registry([document])
        self.assertEqual(reference_warnings([document], registry), [])

    def test_build_surfaces_reference_warning(self):
        import shutil
        import tempfile

        from build_docx import build

        root = Path(tempfile.mkdtemp(prefix="v27-refwarn-"))
        try:
            project = root / "project"
            (project / "content").mkdir(parents=True)
            (project / "assets" / "tables").mkdir(parents=True)
            (project / "template").mkdir(parents=True)
            shutil.copy2(TEMPLATE, project / "template" / "template.docx")
            (project / "content" / "1 引用.md").write_text(
                "## 1.1 引用\n\n见 @fig-missing。\n", encoding="utf-8"
            )
            config = {
                "documentType": "general",
                "documentNo": "GX-V27-004",
                "documentName": "引用警告",
                "documentVersion": "1.0",
                "paths": {
                    "template": str(project / "template" / "template.docx"),
                    "content_root": str(project / "content"),
                    "asset_root": str(project / "assets"),
                    "table_root": str(project / "assets" / "tables"),
                    "output": str(project / "output" / "o.docx"),
                },
                "headingStyles": {1: "1", 2: "2", 3: "3"},
                "bodyStyle": "a",
            }
            build(config=config)
            warnings = config.get("_expressionWarnings") or []
            self.assertTrue(
                any("@fig-missing" in item for item in warnings),
                "歧义/缺失引用应在表达式警告里透出：{0}".format(warnings),
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


class RefreshedSectionPreservationTests(unittest.TestCase):
    """Word 刷新后的节保留检查必须与刷新前一致。

    回归：刷新后只检查了“节数量/纸张/方向/页边距”的前缀，而实际
    多出的樫向节会让比较失败，与刷新前的结论不一致。
    """

    def test_refreshed_geometry_check_accepts_landscape_addition(self):
        import shutil
        import tempfile

        from build_docx import build
        from validate_docx import (
            DocxPackage,
            _geometry_errors,
            _section_geometry,
            _section_errors,
        )

        # 复用与 BuildIntegrationTests 同一份布局（二级章节目录 + H2 小节）。
        root = Path(tempfile.mkdtemp(prefix="v27-refreshed-"))
        try:
            project = root / "project"
            # 与 BuildIntegrationTests 保持同一布局：内容根下一级章节 + H2 小节。
            (project / "content").mkdir(parents=True)
            (project / "assets" / "tables").mkdir(parents=True)
            (project / "template").mkdir(parents=True)
            shutil.copy2(TEMPLATE, project / "template" / "template.docx")
            _write_test_image(project / "assets" / "figure.png")
            (project / "content" / "1 表达契约.md").write_text(
                fixture_text(), encoding="utf-8"
            )
            config = {
                "documentType": "requirement",
                "documentNo": "GX-V27-003",
                "documentName": "刷新节检查",
                "documentVersion": "1.0",
                "paths": {
                    "template": str(project / "template" / "template.docx"),
                    "content_root": str(project / "content"),
                    "asset_root": str(project / "assets"),
                    "table_root": str(project / "assets" / "tables"),
                    "output": str(project / "output" / "o.docx"),
                },
                "headingStyles": {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"},
                "bodyStyle": "a",
            }
            output = build(config=dict(config))
            template_package = DocxPackage(
                config["paths"]["template"], heading_styles=config["headingStyles"]
            )
            output_package = DocxPackage(output, heading_styles=config["headingStyles"])
            self.assertFalse(
                _section_errors(
                    template_package.section_signatures(),
                    output_package.section_signatures(),
                )
            )
            self.assertFalse(
                _geometry_errors(
                    _section_geometry(template_package),
                    _section_geometry(output_package),
                )
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


class CrossEntryCodeBlockTests(unittest.TestCase):
    """共享代码块容器：三个入口必须得到相同的文本与空白语义。

    评审稿与项目出稿共用
    ``doc_tool.kernel_shared.docx_blocks.make_code_container``；模板填充不再把
    围栏降级为等宽段落。这里直接比较两条路径的容器文本。
    """

    # 代码块正文不包含收尾换行（与共享解析器一致：
    # 围栏末行的换行不算代码行）。
    CODE = "def f():\n    return 1\n\tprint('t')\n\n|中文|"

    def test_review_and_kernel_containers_agree(self):
        from doc_tool.kernel_shared.code_marker import (
            code_container_lines,
            is_code_container,
        )
        from doc_tool.kernel_shared.docx_blocks import make_code_container

        kernel = make_code_container(self.CODE.split("\n"))
        self.assertTrue(is_code_container(kernel))
        kernel_lines = code_container_lines(kernel)

        from doc_tool.application.review.review_docx import _create_code_block_box

        review = _create_code_block_box(self.CODE.split("\n"))
        self.assertTrue(is_code_container(review))
        review_lines = code_container_lines(review)

        self.assertEqual(kernel_lines, review_lines)
        self.assertEqual(kernel_lines, self.CODE.split("\n"))
        joined = "\n".join(kernel_lines)
        self.assertIn("    return 1", joined)
        self.assertIn("\t", joined)
        self.assertIn("\n\n", joined)

    def test_template_fill_preprocess_keeps_fence_markers(self):
        import tempfile
        from pathlib import Path

        from doc_tool.application.template_fill import (
            _Preprocessed,
            _preprocess_markdown,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "assets"
            assets.mkdir()
            state = _Preprocessed()
            lines = _preprocess_markdown(
                "正文。\n\n```python\nprint(1)\n```\n", root, assets, state, [], None
            )
        self.assertEqual(lines, ["正文。", "```python", "print(1)", "```"])
        self.assertEqual(state.code_blocks, 1)


class BuildIntegrationTests(unittest.TestCase):
    """真实构建：同一夹具出稿并通过严格校验。"""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="v27-expression-"))
        cls.project = cls.root / "project"
        # 夹具使用 H2 小节：按构建前契约，文件章节层级 depth=1、
        # 内部标题需深于该层级，因此文件直接放在内容根下。
        (cls.project / "content").mkdir(parents=True)
        (cls.project / "assets" / "tables").mkdir(parents=True)
        (cls.project / "assets" / "images").mkdir(parents=True)
        (cls.project / "template").mkdir(parents=True)
        shutil.copy2(TEMPLATE, cls.project / "template" / "template.docx")
        _write_test_image(cls.project / "assets" / "figure.png")
        (cls.project / "content" / "1 表达契约.md").write_text(
            fixture_text(),
            encoding="utf-8",
        )
        cls.config = {
            "documentType": "requirement",
            "documentNo": "GX-V27-001",
            "documentName": "表达契约夹具",
            "documentVersion": "1.0",
            "paths": {
                "template": str(cls.project / "template" / "template.docx"),
                "content_root": str(cls.project / "content"),
                "asset_root": str(cls.project / "assets"),
                "table_root": str(cls.project / "assets" / "tables"),
                "output": str(cls.project / "output" / "表达契约(1.0).docx"),
            },
            "headingStyles": {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"},
            "bodyStyle": "a",
            "_base": str(cls.project),
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_build_outputs_code_container_captions_and_landscape(self):
        from build_docx import build
        from docx_common import parse_xml_safe, read_docx_package
        from doc_tool.kernel_shared.code_marker import (
            code_container_lines,
            is_code_container,
        )

        output = build(config=dict(self.config))
        self.assertTrue(os.path.isfile(output))
        with read_docx_package(output) as package:
            document = parse_xml_safe(package.read("word/document.xml"), "document.xml")
        body = document.find(W_NS + "body")
        self.assertIsNotNone(body)

        containers = [node for node in body if is_code_container(node)]
        self.assertTrue(containers, "应输出代码容器")
        joined = "\n".join(code_container_lines(containers[0]))
        self.assertIn("    if ", joined)

        paragraphs = [
            "".join(node.text or "" for node in item.iter(W_NS + "t"))
            for item in body.findall(W_NS + "p")
        ]
        self.assertTrue(any(text.startswith("图 1") for text in paragraphs))
        self.assertTrue(any(text.startswith("表 1") for text in paragraphs))
        reference_paragraphs = [
            text for text in paragraphs if "REF" not in text and "图 1" in text
        ]
        self.assertTrue(reference_paragraphs)

        # 生成侧只在横向节写 orient="landscape"；纵向节沿用模板写法（不写
        # orient 即 Word 默认纵向），因此这里按"缺失即 portrait"判定。
        page_sizes = list(document.iter(W_NS + "pgSz"))
        orientations = [node.get(W_NS + "orient") or "portrait" for node in page_sizes]
        self.assertIn("landscape", orientations)
        self.assertIn("portrait", orientations)
        self.assertEqual(
            orientations[-1], "portrait", "末节必须回到纵向：{0}".format(orientations)
        )

        page_breaks = [
            node
            for node in document.iter(W_NS + "br")
            if node.get(W_NS + "type") == "page"
        ]
        self.assertTrue(page_breaks, "分页标记应产出分页断点")

        # 已登记的引用必须解析为可读文本；不存在的引用只能
        # 保留可读占位文本（不猜目标），但不能把 `@fig-`/`@tbl-`
        # 当成普通文本原样输出。
        reference_texts = [text for text in paragraphs if "@fig-" in text or "@tbl-" in text]
        self.assertEqual(len(reference_texts), 1, reference_texts)
        self.assertIn("引用待确认", reference_texts[0])
        resolved_texts = [text for text in paragraphs if "图 1" in text and "REF" not in text]
        self.assertTrue(resolved_texts, "已登记引用应输出可读编号")

    def test_wide_table_sits_in_a_real_landscape_section(self):
        """横向节必须真的是横向，且后续内容恢复纵向。

        回归：多节模板（封面节 + 正文节）下，切分出的横向节
        曾经仍是纵向属性（误用了首节/上一节属性），
        导致宽表实际落在纵向页上。
        """
        from build_docx import build
        from docx_common import parse_xml_safe, read_docx_package

        output = build(config=dict(self.config))
        with read_docx_package(output) as package:
            document = parse_xml_safe(package.read("word/document.xml"), "document.xml")
        body = document.find(W_NS + "body")
        self.assertIsNotNone(body)

        # 按正文顺序收集"每个节实际生效的方向"，最后一个是 body 末尾 sectPr。
        order = []
        for element in body:
            if element.tag == W_NS + "p":
                ppr = element.find(W_NS + "pPr")
                sect = ppr.find(W_NS + "sectPr") if ppr is not None else None
            elif element.tag == W_NS + "sectPr":
                sect = element
            else:
                sect = None
            if sect is None:
                continue
            page_size = sect.find(W_NS + "pgSz")
            order.append(
                (page_size.get(W_NS + "orient") if page_size is not None else None)
                or "portrait"
            )

        self.assertIn("landscape", order, "应存在显式横向节")
        landscape_index = order.index("landscape")
        self.assertTrue(
            any(item == "portrait" for item in order[landscape_index + 1:]),
            "横向节之后必须恢复纵向，方向不能泄漏到后续章节：{0}".format(order),
        )
        self.assertEqual(
            order[0], "portrait", "首节必须保持模板纵向：{0}".format(order)
        )

        # 横向节必须承接正文节的页眉页脚关系，不能把封面节的
        # 首页页眉（通常为空）带到正文里。
        reference_type = (
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        sections = []
        for element in body:
            if element.tag == W_NS + "p":
                ppr = element.find(W_NS + "pPr")
                sect = ppr.find(W_NS + "sectPr") if ppr is not None else None
            elif element.tag == W_NS + "sectPr":
                sect = element
            else:
                sect = None
            if sect is None:
                continue
            sections.append(
                (
                    (sect.find(W_NS + "pgSz").get(W_NS + "orient") or "portrait")
                    if sect.find(W_NS + "pgSz") is not None
                    else "portrait",
                    tuple(
                        sorted(
                            (item.get(W_NS + "type"), item.get(reference_type))
                            for item in sect.findall(W_NS + "headerReference")
                        )
                    ),
                )
            )
        landscape_headers = [
            headers for orient, headers in sections if orient == "landscape"
        ][0]
        # 横向节必须带上模板已有的页眉引用（不能丢失页眉页脚），
        # 且必须能在模板的节里找到同一组引用；正文节自身保持不变。
        template_header_sets = {
            headers for _orient, headers in TemplateSectionProbe(TEMPLATE).sections()
        }
        self.assertIn(
            landscape_headers,
            template_header_sets,
            "横向节页眉必须来自模板节：{0}".format(landscape_headers),
        )
        body_headers = sections[-1][1]
        self.assertIn(
            body_headers,
            template_header_sets,
            "正文节页眉必须保持模板原样：{0}".format(body_headers),
        )

    def test_validation_passes_for_fixture(self):
        from build_docx import build
        from validate_docx import validate

        output = build(config=dict(self.config))
        report = self.project / "logs" / "v27-validation.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        detail = ""
        ok = validate(
            config=dict(self.config),
            baseline=False,
            require_refreshed=False,
            report_override=report,
        )
        if report.is_file():
            detail = report.read_text(encoding="utf-8")
        self.assertTrue(ok, detail)
        self.assertTrue(os.path.isfile(output))


class TemplateSectionProbe:
    """读取模板的节属性（方向 + 页眉引用集），供回归断言复用。"""

    def __init__(self, path):
        self.path = path

    def sections(self):
        from docx_common import parse_xml_safe, read_docx_package

        reference_type = (
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        with read_docx_package(str(self.path)) as package:
            document = parse_xml_safe(package.read("word/document.xml"), "document.xml")
        body = document.find(W_NS + "body")
        result = []
        for element in body:
            if element.tag == W_NS + "p":
                ppr = element.find(W_NS + "pPr")
                sect = ppr.find(W_NS + "sectPr") if ppr is not None else None
            elif element.tag == W_NS + "sectPr":
                sect = element
            else:
                sect = None
            if sect is None:
                continue
            page_size = sect.find(W_NS + "pgSz")
            orient = "portrait"
            if page_size is not None and page_size.get(W_NS + "orient"):
                orient = page_size.get(W_NS + "orient")
            headers = tuple(
                sorted(
                    (item.get(W_NS + "type"), item.get(reference_type))
                    for item in sect.findall(W_NS + "headerReference")
                )
            )
            result.append((orient, headers))
        return result


def _write_test_image(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 80), (240, 240, 240)).save(path)


if __name__ == "__main__":
    unittest.main()