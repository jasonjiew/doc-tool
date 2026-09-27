# -*- coding: utf-8 -*-
"""模板填充测试（Word 底模 + Markdown → 格式一致的 DOCX）。

纯离线：样式解析、映射校验、章节拆分、填充构建（标准模板/自定义样式模板/
前置正文/图片内嵌与告警/代码块降级）、互转层路由与 CLI 参数门禁。
亿赛通 DocGuard 环境注意：本文件由受信任进程读写，产物只断言 OOXML 结构。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO_ROOT)

from lxml import etree  # noqa: E402

from doc_tool.adapters.kernel import ensure_kernel_importable  # noqa: E402

ensure_kernel_importable()

from docx_common import parse_image_reference  # noqa: E402

from doc_tool.application.convert import (  # noqa: E402
    KIND_DOCX_TO_PDF,
    KIND_MARKDOWN_TO_DOCX,
    TARGET_DOCX,
    build_plan,
    convert_paths,
    heading_level_counts,
)
from doc_tool.application.template_fill import (  # noqa: E402
    TemplateFillError,
    _pad_heading_styles,
    fill_markdown_with_template,
    parse_template_styles,
    validate_style_map,
)
from doc_tool.domain.errors import UnsupportedConversionError  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from doc_tool.domain.ooxml import parse_heading_styles, parse_xml_safe  # noqa: E402

TEMPLATE = Path(REPO_ROOT) / "templates" / "requirement-template.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"stub")
    return path


def _write_md(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 60, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _rewrite_docx_part(source: Path, dest: Path, part: str, data: bytes) -> None:
    """复制 DOCX 并替换其中某个部件（构造自定义模板夹具用）。"""
    with zipfile.ZipFile(source) as package:
        entries = [(item.filename, package.read(item.filename)) for item in package.infolist()]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as target:
        for name, original in entries:
            target.writestr(name, data if name == part else original)


def _custom_style_template(dest: Path) -> None:
    """去掉模板全部可识别标题样式，另加自定义样式 ZhangTitle。"""
    with zipfile.ZipFile(TEMPLATE) as package:
        styles_root = parse_xml_safe(package.read("word/styles.xml"), "word/styles.xml")
    removed = 0
    for style in list(styles_root.iter(W + "style")):
        if style.get(W + "type") != "paragraph":
            continue
        name_elem = style.find(W + "name")
        name = (name_elem.get(W + "val") if name_elem is not None else "") or ""
        style_id = style.get(W + "styleId") or ""
        looks_heading = name.lower().startswith("heading") or name.startswith("标题")
        has_outline = style.find(W + "pPr/" + W + "outlineLvl") is not None or (
            style.find(W + "pPr") is not None
            and style.find(W + "pPr").find(W + "outlineLvl") is not None
        )
        if looks_heading or has_outline:
            styles_root.remove(style)
            removed += 1
    custom = etree.fromstring(
        '<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' w:type="paragraph" w:styleId="ZhangTitle" w:customStyle="1">'
        '<w:name w:val="ZhangTitle"/><w:basedOn w:val="Normal"/></w:style>'
    )
    styles_root.append(custom)
    _rewrite_docx_part(
        TEMPLATE, dest, "word/styles.xml",
        etree.tostring(styles_root, xml_declaration=True, encoding="UTF-8", standalone=True),
    )


def read_docx_texts(docx_path: Path) -> list:
    """离线读取产物 document.xml 的全部文本（不依赖 Word）。"""
    from doc_tool.domain.ooxml import read_docx_package as _read

    package = _read(docx_path)
    root = parse_xml_safe(package.read("word/document.xml"), "word/document.xml")
    package.close()
    return [node.text or "" for node in root.iter(W + "t")]


class PadHeadingStylesTests(unittest.TestCase):
    """级别补齐：validate_content_tree 要求 max(headingStyles) 覆盖章节深度。"""

    def test_missing_levels_borrow_nearest_shallower(self):
        padded, warnings = _pad_heading_styles({1: "A", 3: "B"})
        self.assertEqual(
            padded,
            {1: "A", 2: "A", 3: "B", 4: "B", 5: "B", 6: "B"},
        )
        self.assertTrue(warnings)

    def test_empty_map_falls_back_to_builtin(self):
        padded, warnings = _pad_heading_styles({})
        self.assertEqual(padded[1], "Heading1")
        self.assertEqual(set(padded), set(range(1, 7)))
        self.assertIn("内置", warnings[0])


class ValidateStyleMapTests(unittest.TestCase):
    def test_valid_mapping_passes(self):
        self.assertEqual(validate_style_map({"A": 1, "B": 2}), [])

    def test_missing_level_one_rejected(self):
        errors = validate_style_map({"A": 2})
        self.assertTrue(any("级别 1" in item for item in errors))

    def test_level_jump_rejected(self):
        errors = validate_style_map({"A": 1, "B": 3})
        self.assertTrue(any("跳跃" in item for item in errors))

    def test_duplicate_level_rejected(self):
        errors = validate_style_map({"A": 1, "B": 1})
        self.assertTrue(any("只能对应一个样式" in item for item in errors))

    def test_out_of_range_level_rejected(self):
        errors = validate_style_map({"A": 7})
        self.assertTrue(any("无效" in item for item in errors))

    def test_empty_mapping_rejected(self):
        self.assertTrue(validate_style_map({}))


class ParseTemplateStylesTests(unittest.TestCase):
    def test_standard_template_resolves_headings_and_body(self):
        styles = parse_template_styles(TEMPLATE)
        self.assertIn(1, styles.raw_heading_styles)
        self.assertEqual(set(styles.heading_styles), set(range(1, 7)))
        self.assertTrue(styles.body_style)
        self.assertTrue(styles.paragraph_styles)

    def test_custom_style_template_has_no_auto_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "custom.docx"
            _custom_style_template(template)
            styles = parse_template_styles(template)
            self.assertEqual(styles.raw_heading_styles, {})
            self.assertIn(1, styles.heading_styles)  # 回退内置 Heading1
            ids = {info.style_id for info in styles.paragraph_styles}
            self.assertIn("ZhangTitle", ids)


class FillTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def _fill(self, md_text: str, template: Path = TEMPLATE, **kwargs):
        source = _write_md(self.root, "样品.md", md_text)
        output = self.root / "out" / "样品.docx"
        return fill_markdown_with_template([source], template, output, **kwargs), output

    def test_headings_paras_table_list_filled_with_template_styles(self):
        md = (
            "# 第一章 总体要求\n\n"
            "开头段落，含 **加粗** 与 `code` 文本。\n\n"
            "- 要点一\n- 要点二\n\n"
            "| 列A | 列B |\n| :--- | ---: |\n| 1 | 2 |\n\n"
            "## 1.1 背景说明\n\n背景正文。\n\n"
            "### 1.1.1 目标\n\n目标正文。\n"
        )
        result, output = self._fill(md)
        self.assertTrue(output.is_file())
        self.assertGreaterEqual(result.chapters, 3)  # H1 目录 + H2 目录 + H3 文件
        texts = read_docx_texts(output)
        joined = "".join(texts)
        for expected in ("第一章 总体要求", "开头段落", "要点一", "列A", "背景说明", "目标"):
            self.assertIn(expected, joined)
        # 产物标题样式必须引用模板自己的 styleId（heading_level_counts 走
        # 产物 styles.xml 的识别映射，等价于「格式与模板一致」的结构核验）。
        counts = heading_level_counts(output)
        self.assertGreaterEqual(counts.get(1, 0), 1)
        self.assertGreaterEqual(counts.get(2, 0), 1)
        self.assertGreaterEqual(counts.get(3, 0), 1)

    def test_two_h1_become_two_chapters(self):
        md = "# 第一章 概述\n\n内容一。\n\n# 第二章 设计\n\n内容二。\n"
        result, output = self._fill(md)
        self.assertGreaterEqual(result.chapters, 2)
        counts = heading_level_counts(output)
        self.assertEqual(counts.get(1), 2)
        joined = "".join(read_docx_texts(output))
        self.assertIn("第一章 概述", joined)
        self.assertIn("第二章 设计", joined)

    def test_preamble_becomes_headless_intro(self):
        md = "这段说明出现在第一个标题之前。\n\n# 第一章 正文\n\n内容。\n"
        result, output = self._fill(md)
        self.assertTrue(result.headless_intro)
        joined = "".join(read_docx_texts(output))
        self.assertIn("这段说明出现在第一个标题之前", joined)
        self.assertIn("第一章 正文", joined)

    def test_document_without_headings_single_chapter(self):
        md = "只有正文没有标题的一篇短文。\n第二段。\n"
        result, output = self._fill(md)
        self.assertGreaterEqual(result.chapters, 1)
        joined = "".join(read_docx_texts(output))
        self.assertIn("只有正文没有标题的一篇短文", joined)
        self.assertIn("第二段", joined)

    def test_image_embedded_and_missing_warns(self):
        (self.root / "pic.png").write_bytes(_png_bytes())
        md = "# 第一章 图文\n\n![截图](pic.png)\n\n![缺失](不存在.png)\n"
        warnings = []
        result, output = self._fill(md, on_warning=warnings.append)
        self.assertEqual(result.images, 1)
        with zipfile.ZipFile(output) as package:
            media = [name for name in package.namelist() if name.startswith("word/media/")]
        self.assertTrue(media, "相对路径图片必须内嵌进产物")
        self.assertTrue(any("图片文件不存在" in item for item in warnings))
        joined = "".join(read_docx_texts(output))
        self.assertIn("【图片缺失", joined)

    def test_remote_image_degrades_to_placeholder(self):
        md = "# 第一章 图文\n\n![网图](https://example.com/a.png)\n"
        result, output = self._fill(md)
        joined = "".join(read_docx_texts(output))
        self.assertIn("【图片缺失", joined)
        self.assertEqual(result.images, 0)

    def test_code_fence_downgraded_to_monospace_paragraphs(self):
        md = "# 第一章 代码\n\n```python\nprint('hi')\n# 注释行\n```\n\n后续段落。\n"
        result, output = self._fill(md)
        self.assertTrue(any("代码块" in item for item in result.warnings))
        joined = "".join(read_docx_texts(output))
        self.assertIn("print('hi')", joined)
        self.assertIn("# 注释行", joined, "代码内的 # 行不得被当成标题")
        self.assertNotIn("```", joined)
        counts = heading_level_counts(output)
        self.assertEqual(counts.get(1), 1, "代码块内注释不得增加标题数量")

    def test_fidelity_end_to_end_inline_image_quote_frontmatter(self):
        """行内图片 + 引用块 + front matter 的端到端：图片内嵌、无字面语法残留。"""
        (self.root / "pic.png").write_bytes(_png_bytes())
        nl = chr(10)
        md = (
            "---" + nl + "title: 项目建议书" + nl + "---" + nl + nl
            + "前置说明，含行内 ![图](pic.png) 图片。" + nl + nl
            + "> 这是一段引用内容。" + nl + nl
            + "# 第一章 内容" + nl + nl
            + "## 标题带闭合 ##" + nl + nl
            + "分隔线如下" + nl + nl + "---" + nl + nl + "结尾段落。" + nl
        )
        result, output = self._fill(md)
        self.assertTrue(output.is_file())
        self.assertEqual(result.images, 1)
        joined = "".join(read_docx_texts(output))
        for expected in ("前置说明，含行内", "图片。", "这是一段引用内容。", "标题带闭合", "结尾段落。"):
            self.assertIn(expected, joined)
        # 降级不得残留字面 Markdown 语法
        self.assertNotIn("> 这是一段", joined)
        self.assertNotIn("## 标题", joined)
        self.assertNotIn("![图]", joined)
        self.assertNotIn("---", joined)
        with zipfile.ZipFile(output) as package:
            media = [n for n in package.namelist() if n.startswith("word/media/")]
            custom = package.read("docProps/custom.xml").decode("utf-8")
        self.assertTrue(media, "行内图片必须内嵌")
        self.assertIn("项目建议书", custom, "front matter 的 title 应写入文档属性")

    def test_user_style_map_drives_heading_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "custom.docx"
            _custom_style_template(template)
            md = "# 第一章 映射\n\n正文。\n"
            source = _write_md(self.root, "map.md", md)
            output = self.root / "out" / "map.docx"
            result = fill_markdown_with_template(
                [source], template, output, heading_style_map={"ZhangTitle": 1}
            )
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as package:
                root = parse_xml_safe(
                    package.read("word/document.xml"), "word/document.xml"
                )
            style_refs = {
                node.get(W + "val")
                for node in root.iter(W + "pStyle")
            }
            self.assertIn("ZhangTitle", style_refs)

    def test_user_style_map_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "custom.docx"
            _custom_style_template(template)
            source = _write_md(self.root, "bad.md", "# 第一章 映射\n\n正文。\n")
            output = self.root / "out" / "bad.docx"
            with self.assertRaises(TemplateFillError) as ctx:
                fill_markdown_with_template(
                    [source], template, output, heading_style_map={"ZhangTitle": 2}
                )
            self.assertIn("级别 1", str(ctx.exception.user_message))
            with self.assertRaises(TemplateFillError) as ctx2:
                fill_markdown_with_template(
                    [source], template, output, heading_style_map={"不存在的样式": 1}
                )
            self.assertIn("不存在", str(ctx2.exception.user_message))

    def test_undecodable_markdown_maps_to_e6009(self):
        source = self.root / "bad.md"
        source.write_bytes(b"\xff\xff\xff\xff")
        with self.assertRaises(TemplateFillError):
            fill_markdown_with_template([source], TEMPLATE, self.root / "bad.docx")

    def test_broken_template_maps_to_e6009(self):
        source = _write_md(self.root, "ok.md", "# 标题\n\n正文。\n")
        junk = _touch(self.root / "junk.docx")
        with self.assertRaises(TemplateFillError):
            fill_markdown_with_template([source], junk, self.root / "out.docx")

    def test_multiple_files_merge_in_order(self):
        first = _write_md(self.root, "01-总述.md", "# 第一章 总述\n\n总述正文。\n")
        second = _write_md(self.root, "02-细节.md", "# 第二章 细节\n\n细节正文。\n")
        output = self.root / "out" / "合并.docx"
        result = fill_markdown_with_template([first, second], TEMPLATE, output)
        self.assertGreaterEqual(result.chapters, 2)
        joined = "".join(read_docx_texts(output))
        self.assertIn("第一章 总述", joined)
        self.assertIn("第二章 细节", joined)


class PreprocessFidelityTests(unittest.TestCase):
    """内容保真降级：行内图片/引用块/水平线/闭合井号/代码空行/front matter。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.root / "pic.png").write_bytes(_png_bytes())

    def tearDown(self):
        self._tmp.cleanup()

    def _pre(self, md: str):
        from doc_tool.application.template_fill import _Preprocessed, _preprocess_markdown

        state = _Preprocessed()
        warnings = []
        lines = _preprocess_markdown(
            md, self.root, self.assets, state, warnings, None
        )
        return lines, state, warnings

    def test_front_matter_stripped_with_title(self):
        from doc_tool.application.template_fill import _strip_front_matter

        body, title = _strip_front_matter(
            "---" + chr(10) + "title: 项目建议书" + chr(10) + "author: 王" + chr(10)
            + "---" + chr(10) + chr(10) + "# 正文标题" + chr(10)
        )
        self.assertEqual(title, "项目建议书")
        self.assertIn("# 正文标题", body)
        self.assertNotIn("title:", body)
        # 无 front matter / 未闭合：原样返回
        text2 = "# 标题" + chr(10) + "正文"
        body2, title2 = _strip_front_matter(text2)
        self.assertEqual((body2, title2), (text2, None))
        body3, title3 = _strip_front_matter("---" + chr(10) + "没有闭合")
        self.assertEqual(title3, None)

    def test_inline_image_extracted_to_own_line(self):
        lines, state, warnings = self._pre(
            "文字前 ![截图](pic.png) 文字后" + chr(10)
        )
        self.assertEqual(state.images, 1)
        self.assertEqual(lines[0], "文字前")
        self.assertEqual(lines[1], "![截图](img_001_pic.png)")
        self.assertEqual(lines[2], "文字后")

    def test_blockquote_becomes_indent_marker(self):
        lines, state, warnings = self._pre("> 引用内容" + chr(10) + chr(10) + "正文" + chr(10))
        self.assertEqual(lines[0], "<!-- P:left=720 -->")
        self.assertEqual(lines[1], "引用内容")
        # 空行不产出内容，正文段紧随其后
        self.assertEqual(lines[2], "正文")

    def test_hr_becomes_empty_paragraph(self):
        lines, state, warnings = self._pre("---" + chr(10))
        self.assertEqual(lines, ["<EMPTY_PAR/>"])

    def test_closing_hashes_stripped(self):
        lines, state, warnings = self._pre("## 带井号标题 ##" + chr(10))
        self.assertEqual(lines, ["## 带井号标题"])

    def test_code_fence_blank_line_kept_as_empty_paragraph(self):
        lines, state, warnings = self._pre(
            "```" + chr(10) + "line1" + chr(10) + chr(10) + "line2" + chr(10) + "```" + chr(10)
        )
        self.assertEqual(lines, ["`line1`", "<EMPTY_PAR/>", "`line2`"])

    def test_nested_list_indent_preserved(self):
        lines, state, warnings = self._pre("- 顶层" + chr(10) + "  - 子项" + chr(10))
        self.assertEqual(lines, ["- 顶层", "  - 子项"])


class ConvertLayerTests(unittest.TestCase):
    """互转层路由：build_plan 校验、批量行级下发与混合批次隔离。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def test_build_plan_carries_template_for_markdown(self):
        source = _write_md(self.root, "a.md", "# 标题\n\n正文。\n")
        plan = build_plan(source, template_path=TEMPLATE)
        self.assertEqual(plan.kind, KIND_MARKDOWN_TO_DOCX)
        self.assertEqual(plan.template_path, TEMPLATE)

    def test_build_plan_rejects_template_for_other_directions(self):
        source = _touch(self.root / "a.docx")
        with self.assertRaises(UnsupportedConversionError):
            build_plan(source, template_path=TEMPLATE)
        self.assertEqual(
            build_plan(source).kind, KIND_DOCX_TO_PDF, "不带模板参数时行为不变"
        )

    def test_build_plan_rejects_missing_template(self):
        # 计划阶段只做轻校验（存在 + 扩展名）；伪 docx 的深度校验
        # 在服务层落地为 E6009（见 test_convert_paths_template_failure_lands_e6009）。
        source = _write_md(self.root, "a.md", "# 标题\n")
        with self.assertRaises(UnsupportedConversionError):
            build_plan(source, template_path=self.root / "missing.docx")
        with self.assertRaises(UnsupportedConversionError):
            build_plan(source, template_path=self.root / "noext.bin")

    def test_convert_paths_template_fill_is_offline(self):
        source = _write_md(self.root, "手册.md", "# 第一章 模板填充\n\n正文。\n")
        result = convert_paths([source], template_path=TEMPLATE)
        self.assertTrue(result.success, result.summary())
        record = result.records[0]
        self.assertEqual(record.kind, KIND_MARKDOWN_TO_DOCX)
        self.assertIn("模板填充完成", record.detail)
        self.assertTrue(record.target.is_file())
        self.assertTrue(record.note, "产物标题结构核验说明应进 note")

    def test_convert_paths_template_ignored_for_non_markdown_rows(self):
        docx = _touch(self.root / "a.docx")
        md = _write_md(self.root, "b.md", "# 第一章 标题\n\n正文。\n")

        # Word 行走假转换器；md 行离线模板填充成功——两行互不影响。
        def _word_stub(source, target, kind, timeout, with_toc=False):
            Path(target).write_bytes(b"stub-pdf")
            return _SimpleOutcome()

        result = convert_paths([docx, md], template_path=TEMPLATE, converter=_word_stub)
        self.assertEqual(result.succeeded, 2, result.summary())
        self.assertEqual(result.records[0].kind, KIND_DOCX_TO_PDF)
        self.assertEqual(result.records[1].kind, KIND_MARKDOWN_TO_DOCX)
        self.assertIn("模板填充完成", result.records[1].detail)

    def test_convert_paths_template_failure_lands_e6009(self):
        source = _write_md(self.root, "a.md", "# 标题\n\n正文。\n")
        junk = _touch(self.root / "junk.docx")
        result = convert_paths([source], template_path=junk)
        self.assertFalse(result.success)
        self.assertEqual(result.records[0].error_code, "E6009")


class _SimpleOutcome:
    ok = True
    reason = "ok"
    detail = "PDF 已生成"
    elapsed_seconds = 0.5
    error_code = None
    images = 0
    complex_tables = 0


class CliTests(unittest.TestCase):
    """CLI --template：离线出稿端到端 + 参数门禁。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def test_convert_with_template_end_to_end(self):
        from doc_tool.cli import main as cli_main

        source = _write_md(self.root, "手册.md", "# 第一章 CLI 模板填充\n\n正文。\n")
        out_dir = self.root / "out"
        code = cli_main([
            "convert", str(source), "--template", str(TEMPLATE),
            "--target-dir", str(out_dir), "--overwrite",
        ])
        self.assertEqual(code, 0)
        self.assertTrue((out_dir / "手册.docx").is_file())

    def test_template_without_markdown_source_rejected(self):
        from doc_tool.cli import main as cli_main

        docx = _touch(self.root / "a.docx")
        code = cli_main([
            "convert", str(docx), "--template", str(TEMPLATE),
            "--target-dir", str(self.root / "out"),
        ])
        self.assertEqual(code, 2)

    def test_no_template_keeps_legacy_behavior(self):
        from doc_tool.cli import main as cli_main

        # 无 Word 环境时 md→docx 走 HTML+Word 会失败，但错误码必须是 Word 类；
        # 有 Word 时成功。这里只验证参数解析不把 --template 缺省当模板。
        source = _write_md(self.root, "legacy.md", "# 标题\n\n正文。\n")
        code = cli_main([
            "convert", str(source), "--to", "html",
            "--target-dir", str(self.root / "out"),
        ])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "out" / "legacy.html").is_file())


class PreprocessRound3Tests(unittest.TestCase):
    """第三轮保真：Setext 标题、GFM 任务列表。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "assets").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _pre(self, md: str):
        from doc_tool.application.template_fill import _Preprocessed, _preprocess_markdown

        state = _Preprocessed()
        return _preprocess_markdown(md, self.root, self.root / "assets", state, [], None)

    def test_setext_h1_and_h2_become_atx(self):
        lines = self._pre("大标题" + chr(10) + "===" + chr(10) + chr(10) + "小标题" + chr(10) + "---" + chr(10))
        self.assertEqual(lines, ["# 大标题", "## 小标题"])  # 空行不产出内容

    def test_setext_not_applied_after_blank(self):
        # 前面是空行时 --- 是水平线，不是 Setext 下划线
        lines = self._pre("段落。" + chr(10) + chr(10) + "---" + chr(10))
        self.assertEqual(lines, ["段落。", "<EMPTY_PAR/>"])

    def test_setext_not_applied_after_list(self):
        lines = self._pre("- 列表项" + chr(10) + "---" + chr(10))
        self.assertEqual(lines, ["- 列表项", "<EMPTY_PAR/>"])

    def test_task_list_symbols(self):
        lines = self._pre("- [ ] 待办" + chr(10) + "- [x] 已办" + chr(10) + "  - [ ] 子任务" + chr(10))
        self.assertEqual(lines, ["- ☐ 待办", "- ☑ 已办", "  - ☐ 子任务"])


class CleanBodyTests(unittest.TestCase):
    """拿现成文档当底模：正文检测与从第一个标题 1 起清理。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def _write_md(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def _fill(self, md: str, name: str, **kwargs):
        source = self.root / name
        source.write_text(md, encoding="utf-8")
        output = self.root / ("out_" + name + ".docx")
        return fill_markdown_with_template([source], TEMPLATE, output, **kwargs), output

    def test_body_heading_count_signals_full_document(self):
        # 纯底模（requirement-template）正文无标题段落
        self.assertEqual(parse_template_styles(TEMPLATE).body_heading_count, 0)
        # 填充产物是一份完整文档：正文含标题
        result, product = self._fill("# 第一章 源文档内容" + chr(10) + chr(10) + "旧正文。" + chr(10), "a.md")
        self.assertTrue(product.is_file())
        self.assertGreater(parse_template_styles(product).body_heading_count, 0)

    def test_clean_body_removes_old_content(self):
        _, full_doc = self._fill("# 第一章 源文档内容" + chr(10) + chr(10) + "旧正文独有内容。" + chr(10), "a.md")
        self._write_md("b.md", "# 第一章 新内容" + chr(10) + chr(10) + "新正文。" + chr(10))
        # 不清理：旧正文混进产物
        fill_markdown_with_template(
            [self.root / "b.md"], full_doc, self.root / "dirty.docx"
        )
        dirty_joined = "".join(read_docx_texts(self.root / "dirty.docx"))
        self.assertIn("旧正文独有内容", dirty_joined)
        # 清理：旧正文被移除
        result_clean = fill_markdown_with_template(
            [self.root / "b.md"], full_doc, self.root / "clean.docx",
            clean_body_from_first_heading=True,
        )
        self.assertTrue(any("清理" in w for w in result_clean.warnings))
        clean_joined = "".join(read_docx_texts(self.root / "clean.docx"))
        self.assertIn("新正文", clean_joined)
        self.assertNotIn("旧正文独有内容", clean_joined)

    def test_clean_body_skipped_for_pure_template(self):
        # 纯底模（无正文标题）请求清理：不报错、无清理告警
        result, _ = self._fill("# 第一章 内容" + chr(10) + chr(10) + "正文。" + chr(10), "c.md", clean_body_from_first_heading=True)
        self.assertFalse(any("清理" in w for w in result.warnings))


class LastTemplateMemoryTests(unittest.TestCase):
    """底模记忆：~/.doctool/template_fill.json 读写。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_load_roundtrip(self):
        from doc_tool.application import template_fill

        original = template_fill._last_template_file
        template_fill._last_template_file = lambda: Path(self._tmp.name) / "template_fill.json"
        try:
            self.assertIsNone(template_fill.load_last_template())
            template_fill.save_last_template("D:" + chr(92) + "tpl" + chr(92) + "底模.docx")
            self.assertEqual(
                template_fill.load_last_template(),
                "D:" + chr(92) + "tpl" + chr(92) + "底模.docx",
            )
        finally:
            template_fill._last_template_file = original


class TemplateFillCommandTests(unittest.TestCase):
    """CLI template-fill 子命令。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def _write_md(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_template_fill_happy_path(self):
        from doc_tool.cli import main as cli_main

        first = self._write_md("01-总述.md", "# 第一章 总述" + chr(10) + chr(10) + "内容一。" + chr(10))
        second = self._write_md("02-细节.md", "# 第二章 细节" + chr(10) + chr(10) + "内容二。" + chr(10))
        output = self.root / "out" / "合并.docx"
        code = cli_main([
            "template-fill", str(first), str(second),
            "--template", str(TEMPLATE), "--output", str(output),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        joined = "".join(read_docx_texts(output))
        self.assertIn("第一章 总述", joined)
        self.assertIn("第二章 细节", joined)

    def test_template_fill_rejects_non_markdown(self):
        from doc_tool.cli import main as cli_main

        docx = self.root / "a.docx"
        docx.write_bytes(b"stub")
        code = cli_main([
            "template-fill", str(docx),
            "--template", str(TEMPLATE), "--output", str(self.root / "o.docx"),
        ])
        self.assertEqual(code, 2)

    def test_template_fill_rejects_bad_style_map(self):
        from doc_tool.cli import main as cli_main

        source = self._write_md("a.md", "# 标题" + chr(10))
        code = cli_main([
            "template-fill", str(source),
            "--template", str(TEMPLATE), "--output", str(self.root / "o.docx"),
            "--map", "样式=级别",
        ])
        self.assertEqual(code, 2)

    def test_template_fill_error_returns_one(self):
        from doc_tool.cli import main as cli_main

        source = self._write_md("a.md", "# 标题" + chr(10))
        junk = self.root / "junk.docx"
        junk.write_bytes(b"stub")
        code = cli_main([
            "template-fill", str(source),
            "--template", str(junk), "--output", str(self.root / "o.docx"),
        ])
        self.assertEqual(code, 1)


class _UiTestCase(unittest.TestCase):
    """UI 测试基类：确保 QApplication 存在，并隔离底模记忆文件。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.application import template_fill

        self._original_last_file = template_fill._last_template_file
        self._memory_tmp = tempfile.TemporaryDirectory()
        template_fill._last_template_file = (
            lambda: Path(self._memory_tmp.name) / "template_fill.json"
        )

    def tearDown(self):
        from doc_tool.application import template_fill

        template_fill._last_template_file = self._original_last_file
        self._memory_tmp.cleanup()


class TemplateStyleMapDialogTests(_UiTestCase):
    """样式映射兜底对话框：预填、校验与结果映射。"""

    def _dialog(self, current=None):
        from doc_tool.application.template_fill import StyleInfo
        from doc_tool.ui.template_style_map_dialog import TemplateStyleMapDialog

        styles = [
            StyleInfo(style_id="ZhangTitle", name="ZhangTitle"),
            StyleInfo(style_id="JieTitle", name="JieTitle"),
            StyleInfo(style_id="Normal", name="Normal"),
        ]
        return TemplateStyleMapDialog(styles, current)

    def test_mapping_roundtrip(self):
        dialog = self._dialog(current={"ZhangTitle": 1, "JieTitle": 2})
        self.assertEqual(dialog._mapping(), {"ZhangTitle": 1, "JieTitle": 2})
        self.assertTrue(dialog._ok_button.isEnabled())

    def test_missing_level_one_blocks_accept(self):
        dialog = self._dialog(current={"JieTitle": 2})
        self.assertFalse(dialog._ok_button.isEnabled())
        dialog._mapping()  # 不抛错
        self.assertEqual(dialog.mapping(), {})

    def test_default_all_ignore_blocks_accept(self):
        dialog = self._dialog()
        self.assertFalse(dialog._ok_button.isEnabled())


class TemplateFillDialogTests(_UiTestCase):
    """模板填充向导：文件列表顺序、输出默认名与运行状态。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def _write_md(self, name: str) -> Path:
        path = self.root / name
        path.write_text("# 标题" + chr(10) + chr(10) + "正文。", encoding="utf-8")
        return path

    def test_add_files_sets_default_output_name_in_order(self):
        from doc_tool.ui.template_fill_dialog import TemplateFillDialog

        first = self._write_md("01-总述.md")
        second = self._write_md("02-细节.md")
        dialog = TemplateFillDialog(paths=[first, second])
        self.assertEqual(
            [item.text() for item in dialog._file_list.findItems("", Qt.MatchContains)],
            [str(first), str(second)],
        )
        self.assertEqual(dialog._name_edit.text(), "01-总述.docx")
        self.assertFalse(dialog._run_btn.isEnabled(), "未选底模时不能开始")

    def test_run_enabled_after_template_selected(self):
        from doc_tool.ui.template_fill_dialog import TemplateFillDialog

        first = self._write_md("手册.md")
        dialog = TemplateFillDialog(paths=[first])
        dialog._template_edit.setText(str(TEMPLATE))
        self.assertTrue(dialog._run_btn.isEnabled())

    def test_move_reorders_list(self):
        from doc_tool.ui.template_fill_dialog import TemplateFillDialog

        first = self._write_md("a.md")
        second = self._write_md("b.md")
        dialog = TemplateFillDialog(paths=[first, second])
        dialog._file_list.setCurrentRow(1)
        dialog._on_move(-1)
        self.assertEqual(
            [dialog._file_list.item(i).text() for i in range(dialog._file_list.count())],
            [str(second), str(first)],
        )


class ConvertDialogTemplateLabelTests(_UiTestCase):
    """互转对话框：选底模后 Markdown→Word 行显示模板填充标识。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def test_row_label_switches_with_template(self):
        from doc_tool.ui.convert_dialog import ConvertDialog

        source = self.root / "手册.md"
        source.write_text("# 标题" + chr(10), encoding="utf-8")
        dialog = ConvertDialog()
        dialog._append([str(source)])
        combo = dialog._row_combos[str(source)]
        index = combo.findData(TARGET_DOCX)
        self.assertEqual(combo.itemText(index), "转为 Word 文档")
        dialog._template_edit.setText(str(TEMPLATE))
        self.assertEqual(combo.itemText(index), "转为 Word 文档（模板填充）")
        dialog._template_edit.clear()
        self.assertEqual(combo.itemText(index), "转为 Word 文档")


if __name__ == "__main__":
    unittest.main()
