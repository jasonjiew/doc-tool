# -*- coding: utf-8 -*-
"""Regression tests for Patrol 5.2: Markdown 与复杂表格编辑还原极限压测."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
from lxml import etree
from doc_tool.domain.blocks import parse_blocks, CodeBlock, TableBlock, ComplexTable, Paragraph
from doc_tool.domain.smart_features import (
    extract_complex_table_proxy_rows,
    apply_complex_table_proxy_edits,
    format_complex_table_proxy_lines,
)
from doc_tool.application.content.revision_record import (
    document_version_from_record,
    last_revision_version,
    normalize_revision_version,
)
from scripts.build_docx import _set_revision_cell_text, qn


class TestPatrol52MarkdownAndTableEdgeCases:
    def test_complex_table_proxy_with_vmerge_and_gridspan_rich_text(self):
        """测试用例：同时包含跨行合并 (vMerge) 与跨列合并 (gridSpan) 的表格，
        编辑包含 <br>、管道符、加粗及超链接，写回保持合法 OOXML 结构。"""
        tbl_xml = """<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:tr>
            <w:tc>
              <w:tcPr><w:gridSpan w:val="2"/></w:tcPr>
              <w:p><w:r><w:t>跨两列标题</w:t></w:r></w:p>
            </w:tc>
          </w:tr>
          <w:tr>
            <w:tc>
              <w:tcPr><w:vMerge w:val="restart"/></w:tcPr>
              <w:p><w:r><w:t>左列合并项</w:t></w:r></w:p>
            </w:tc>
            <w:tc>
              <w:p><w:r><w:t>右列数据1</w:t></w:r></w:p>
            </w:tc>
          </w:tr>
          <w:tr>
            <w:tc>
              <w:tcPr><w:vMerge w:val="continue"/></w:tcPr>
              <w:p/>
            </w:tc>
            <w:tc>
              <w:p><w:r><w:t>右列数据2</w:t></w:r></w:p>
            </w:tc>
          </w:tr>
        </w:tbl>"""
        tbl_el = etree.fromstring(tbl_xml.encode("utf-8"))
        orig_rows, tc_matrix = extract_complex_table_proxy_rows(tbl_el)
        assert len(orig_rows) == 3

        # 模拟用户在 Markdown 代理表中修改：
        # 行0: 修改首个单元格为多行文本含 <br> 与加粗标记
        # 行1: 修改普通数据行
        # 行2: 在合并续格中填入说明文本（应当自动归并至主单元格，不崩溃）
        proxy_edits = [
            ["新首标题<br>**加粗强调**", ""],
            ["左列主单元格修改", "[详情链接](http://example.com)"],
            ["⟦合并⟧", "右列数据2修改"],
        ]
        ok = apply_complex_table_proxy_edits(tbl_el, proxy_edits)
        assert ok is True

        # 检查写回后的 OOXML 是否依然具备合法结构
        trs = tbl_el.findall(qn("tr"))
        assert len(trs) == 3
        # 首行应包含 <w:br/> 节点
        tcs_0 = trs[0].findall(qn("tc"))
        assert len(tcs_0) == 1
        assert tcs_0[0].find(".//" + qn("br")) is not None

    def test_markdown_code_fences_with_fake_headings_and_tables(self):
        """测试用例：代码块内部如果出现 # 伪标题或 | 伪表格 |，不被误拆解为标题或表格。"""
        md_text = """# 真实一级标题

正文段落。

```bash
# 这是一个伪标题注释
git commit -m "feat: init"
| 不应当 | 解析为表格 |
| --- | --- |
| 1 | 2 |
```

<!-- HTML 注释行 -->

| 真实表格表头 | 第二列 |
| --- | --- |
| A | B |
"""
        doc = parse_blocks(md_text)
        block_types = [type(b).__name__ for b in doc.blocks]
        # 应该包含 1个标题，1个正文，1个代码块，1个注释段落，1个表格块
        assert "CodeBlock" in block_types
        assert "TableBlock" in block_types
        code_block = [b for b in doc.blocks if isinstance(b, CodeBlock)][0]
        assert "# 这是一个伪标题注释" in code_block.text
        assert "| 不应当 | 解析为表格 |" in code_block.text

    def test_complex_proxy_with_blank_lines_tolerance(self):
        """测试用例：复杂表格标记与代理表之间包含 1~2 个空行时能够正确消费。"""
        md_text = """<!-- TABLE:1:tbl_0001.xml -->

<!-- TABLE_PROXY_BEGIN -->
| 列1 | 列2 |
| --- | --- |
| 数据A | 数据B |
<!-- TABLE_PROXY_END -->
"""
        doc = parse_blocks(md_text)
        assert len(doc.blocks) == 1
        assert isinstance(doc.blocks[0], ComplexTable)
        # 包含表头与数据行共 2 行
        assert len(doc.blocks[0].proxy_rows) == 2
        assert doc.blocks[0].proxy_rows[0] == ["列1", "列2"]
        assert doc.blocks[0].proxy_rows[1] == ["数据A", "数据B"]

    def test_revision_record_version_extraction_and_formatting(self, tmp_path):
        """测试用例：修订记录表为空表、仅表头、版本号带前缀 v/V/空格及多行备注时的鲁棒性。"""
        # 1. 只有表头的表 -> 返回 None
        header_only_file = tmp_path / "header_only.md"
        header_only_file.write_text(
            "| 版本 | 日期 | 变更内容 | 作者 |\n| --- | --- | --- | --- |\n",
            encoding="utf-8"
        )
        assert last_revision_version(header_only_file) is None
        assert document_version_from_record(header_only_file) is None

        # 2. 版本号带前缀 V / v / 空格，末尾带备注审批行 -> 准确提取版本号并归一化
        rich_rev_file = tmp_path / "rich_rev.md"
        rich_rev_file.write_text("""# 修订记录

| 序号 | 版本 | 发布日期 | 修改摘要 | 编制 | 审批 |
| :---: | :---: | :---: | :--- | :---: | :---: |
| 1 | V 1.0 | 2026-01-01 | 初稿编制 | 张三 | 李四 |
| 2 |  v2.5.1  | 2026-03-15 | 补充第二章接口规范<br>修复表格缺陷 | 王五 | 赵六 |
| 注 | 部门 | 研发部 | 本文档受控发放 | - | - |
""", encoding="utf-8")

        raw_ver = last_revision_version(rich_rev_file)
        assert raw_ver == "v2.5.1"
        norm_ver = document_version_from_record(rich_rev_file)
        assert norm_ver == "2.5.1"

        # 3. 写回单元格支持多行与 <br>
        tc_el = etree.Element(qn("tc"))
        _set_revision_cell_text(tc_el, "第一行说明<br>第二行说明\n第三行说明")
        br_nodes = tc_el.findall(".//" + qn("br"))
        assert len(br_nodes) == 2
        t_nodes = tc_el.findall(".//" + qn("t"))
        assert len(t_nodes) == 3
        assert t_nodes[0].text == "第一行说明"
        assert t_nodes[1].text == "第二行说明"
        assert t_nodes[2].text == "第三行说明"

    def test_missing_image_and_empty_table_graceful_degradation(self):
        """测试用例：缺失图片链接或空表格在渲染时优雅降级，不抛裸异常阻断构建。"""
        from scripts.build_docx import _render_image_block, _render_table_block
        from doc_tool.domain.blocks import Figure, TableBlock

        # 1. 缺失图片块测试
        fake_img_block = Figure(
            location=None,
            alt="架构概览图",
            relative_path="non_existent_folder/missing_image_404.png",
            width_px=None,
            height_px=None,
        )
        body = etree.Element(qn("body"))
        anchor_p = etree.SubElement(body, qn("p"))
        items = {}
        config = {"paths": {"asset_root": "."}}

        # 渲染缺失图片：应当优雅捕获异常并生成占位段落，不抛出 AutomationError
        inserted, captioned = _render_image_block(
            fake_img_block,
            insert_before=anchor_p,
            items=items,
            image_manager=None,
            config=config,
            max_image_width=9000,
            next_object_id=lambda: 1,
            registry={},
        )
        assert inserted == 1
        assert len(body) == 2
        placeholder_p = body[0]
        text_content = etree.tostring(placeholder_p, encoding="utf-8").decode("utf-8")
        assert "图片缺失或损坏" in text_content
        assert "架构概览图" in text_content

        # 2. 空表格块测试
        empty_tbl_block = TableBlock(
            location=None,
            rows=[],
            meta=None,
        )
        tbl_inserted = _render_table_block(
            empty_tbl_block,
            insert_before=anchor_p,
            config=config,
            registry={},
        )
        assert tbl_inserted == 0
