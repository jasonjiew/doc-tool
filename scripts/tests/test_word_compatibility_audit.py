# -*- coding: utf-8 -*-
"""Word 文档兼容性全场景审计与边缘用例回归测试套件。

覆盖：
1. OOXML 标题样式模式（中文层级、数字层级、styleId 回退）
2. 预检门禁（.doc 引导提示、outlineLvl 识别、缺省 H1 层级平移归一化、无标题文档宽松扫描）
3. 内容提取（无标题文档正文回落、空标题过滤、表格反斜杠与管道符转义、外部图片外链转换、多级列表缩进）
4. 文档构建（无标题文档跳过假标题、缺省样式平滑降级、斜体/粗体/公式星号/通配符/脱敏掩码解析与排版）
5. 往返校验（无标题文档事件提取、outlineLvl 事件映射、VML 图片哈希比对、反引号规范化）
6. 端到端项目导入（无标题文档端到端导入、构建与往返闭环）
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

from doc_tool.adapters.importer import extract_content  # noqa: E402
from doc_tool.adapters.preflight import preflight  # noqa: E402
from doc_tool.adapters.roundtrip import roundtrip_diff  # noqa: E402
from doc_tool.application.import_project import (  # noqa: E402
    ImportRequest,
    import_first_time,
)
from doc_tool.domain.errors import (  # noqa: E402
    InvalidDocxError,
    MissingHeading1Error,
    HeadingHierarchyError,
)
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.ooxml import heading_style_candidates  # noqa: E402
from build_docx import (  # noqa: E402
    make_heading,
    make_paragraph,
    parse_inline_runs,
)
from validate_docx import DocxPackage  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

W = "{" + W_NS + "}"
R = "{" + R_NS + "}"
A = "{" + A_NS + "}"
V = "{" + V_NS + "}"

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\x00\x05\xfe\xd4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_minimal_docx(
    file_path: Path,
    body_xml: str,
    styles_xml: str = "",
    rels_xml: str = "",
    media_files: dict = None,
) -> Path:
    """构建用于测试的规范 DOCX 文件。"""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Default Extension="png" ContentType="image/png"/>\n'
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n'
        '  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>\n'
        '</Types>'
    )
    if not styles_xml:
        styles_xml = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:styles xmlns:w="{W_NS}">\n'
            f'  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>\n'
            f'  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>\n'
            f'  <w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>\n'
            f'</w:styles>'
        )
    settings_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:settings xmlns:w="{W_NS}"/>'
    )
    if not rels_xml:
        rels_xml = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{PR_NS}">\n'
            f'  <Relationship Id="rIdStyles" Type="{PR_NS}/styles" Target="styles.xml"/>\n'
            f'  <Relationship Id="rIdSettings" Type="{PR_NS}/settings" Target="settings.xml"/>\n'
            f'</Relationships>'
        )

    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:a="{A_NS}" xmlns:v="{V_NS}">\n'
        f'  <w:body>\n'
        f'    {body_xml}\n'
        f'    <w:sectPr/>\n'
        f'  </w:body>\n'
        f'</w:document>'
    )

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
        zf.writestr("word/styles.xml", styles_xml.encode("utf-8"))
        zf.writestr("word/settings.xml", settings_xml.encode("utf-8"))
        zf.writestr("word/_rels/document.xml.rels", rels_xml.encode("utf-8"))
        if media_files:
            for part, data in media_files.items():
                zf.writestr(part, data)
    return file_path


class TestOoxmlChineseHeadings(unittest.TestCase):
    """验证 heading_style_candidates 对各种中英文标题样式的精准识别。"""

    def test_chinese_heading_names_matching(self):
        xml_content = f"""<w:styles xmlns:w="{W_NS}">
            <w:style w:type="paragraph" w:styleId="h1"><w:name w:val="一级标题"/></w:style>
            <w:style w:type="paragraph" w:styleId="h2"><w:name w:val="2级标题"/></w:style>
            <w:style w:type="paragraph" w:styleId="h3"><w:name w:val="三级"/></w:style>
            <w:style w:type="paragraph" w:styleId="h4"><w:name w:val="4级"/></w:style>
            <w:style w:type="paragraph" w:styleId="h5"><w:name w:val="五级目录"/></w:style>
            <w:style w:type="paragraph" w:styleId="h6"><w:name w:val="6级 标题"/></w:style>
            <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="正文"/></w:style>
        </w:styles>"""
        root = etree.fromstring(xml_content.encode("utf-8"))
        candidates = heading_style_candidates(root)
        lvl_map = {c.style_id: c.level for c in candidates}
        self.assertEqual(lvl_map.get("h1"), 1)
        self.assertEqual(lvl_map.get("h2"), 2)
        self.assertEqual(lvl_map.get("h3"), 3)
        self.assertEqual(lvl_map.get("h4"), 4)
        self.assertEqual(lvl_map.get("h5"), 5)
        self.assertEqual(lvl_map.get("h6"), 6)
        self.assertNotIn("Normal", lvl_map)

    def test_match_by_style_id_when_name_arbitrary(self):
        xml_content = f"""<w:styles xmlns:w="{W_NS}">
            <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="MyCustomTitle"/></w:style>
            <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="SubTitleCustom"/></w:style>
        </w:styles>"""
        root = etree.fromstring(xml_content.encode("utf-8"))
        candidates = heading_style_candidates(root)
        lvl_map = {c.style_id: c.level for c in candidates}
        self.assertEqual(lvl_map.get("Heading1"), 1)
        self.assertEqual(lvl_map.get("Heading2"), 2)


class TestPreflightEdgeCases(unittest.TestCase):
    """验证预检门禁的格式提示、outlineLvl 识别及缺省层级自愈。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_preflight_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_doc_extension_rejection_suggests_save_as(self):
        doc_path = Path(self.temp_dir) / "test.doc"
        doc_path.write_bytes(b"dummy")
        with self.assertRaises(InvalidDocxError) as ctx:
            preflight(str(doc_path))
        self.assertIn("另存为「Word 文档 (*.docx)」", ctx.exception.suggested_action)

    def test_outline_lvl_heading_detection(self):
        docx_path = Path(self.temp_dir) / "outline.docx"
        body = """
            <w:p>
                <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
                <w:r><w:t>第一章 大纲一</w:t></w:r>
            </w:p>
            <w:p>
                <w:r><w:t>正文内容</w:t></w:r>
            </w:p>
            <w:p>
                <w:pPr><w:outlineLvl w:val="1"/></w:pPr>
                <w:r><w:t>1.1 大纲二</w:t></w:r>
            </w:p>
        """
        _make_minimal_docx(docx_path, body)
        preview = preflight(str(docx_path))
        self.assertEqual(len(preview.headings), 2)
        self.assertEqual(preview.headings[0].level, 1)
        self.assertEqual(preview.headings[0].text, "第一章 大纲一")
        self.assertEqual(preview.headings[1].level, 2)
        self.assertEqual(preview.headings[1].text, "1.1 大纲二")

    def test_level_shift_when_no_h1_and_allow_missing(self):
        docx_path = Path(self.temp_dir) / "starts_with_h2.docx"
        body = """
            <w:p>
                <w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
                <w:r><w:t>二级标题当作章标题</w:t></w:r>
            </w:p>
            <w:p><w:r><w:t>正文内容</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx_path, body)
        # 不允许宽松扫描时应报错（层级跳跃，必须以 Level 1 开始）
        with self.assertRaises(MissingHeading1Error):
            preflight(str(docx_path), allow_missing_headings=False)

        # 允许宽松扫描时，自动将最小层级 Level 2 偏移归一化为 Level 1
        preview = preflight(str(docx_path), allow_missing_headings=True)
        self.assertEqual(len(preview.headings), 1)
        self.assertEqual(preview.headings[0].level, 1)

    def test_headless_document_passes_with_allow_missing(self):
        docx_path = Path(self.temp_dir) / "headless.docx"
        body = """
            <w:p><w:r><w:t>这是一篇没有设置任何标题样式的 Word 文档。</w:t></w:r></w:p>
            <w:p><w:r><w:t>第二段正文。</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx_path, body)
        with self.assertRaises(MissingHeading1Error):
            preflight(str(docx_path), allow_missing_headings=False)

        preview = preflight(str(docx_path), allow_missing_headings=True)
        self.assertEqual(len(preview.headings), 0)


class TestImporterAndExtractorEdgeCases(unittest.TestCase):
    """验证内容提取器对无标题正文、表格转义、外链图片与缩进列表的处理。"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_importer_"))
        self.content_dir = self.temp_dir / "content"
        self.images_dir = self.temp_dir / "images"
        self.tables_dir = self.temp_dir / "tables"
        self.content_dir.mkdir(parents=True)
        self.images_dir.mkdir(parents=True)
        self.tables_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_headless_document_extracts_into_default_chapter(self):
        docx_path = self.temp_dir / "headless.docx"
        body = """
            <w:p><w:r><w:t>第一段独立正文。</w:t></w:r></w:p>
            <w:p><w:r><w:t>第二段独立正文。</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx_path, body)
        res = extract_content(
            docx_path,
            self.content_dir,
            self.images_dir,
            self.tables_dir,
            "general",
            heading_style_map={},
            allow_missing_headings=True,
        )
        self.assertEqual(res.chapter_count, 1)
        chapter_files = list(self.content_dir.glob("*.md"))
        self.assertEqual(len(chapter_files), 1)
        content = chapter_files[0].read_text(encoding="utf-8")
        self.assertIn("# 正文", content)
        self.assertIn("第一段独立正文。", content)
        self.assertIn("第二段独立正文。", content)

    def test_empty_headings_are_skipped(self):
        docx_path = self.temp_dir / "empty_headings.docx"
        body = """
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr></w:p>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>真实第一章</w:t></w:r></w:p>
            <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr></w:p>
            <w:p><w:r><w:t>正文段落</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx_path, body)
        res = extract_content(
            docx_path,
            self.content_dir,
            self.images_dir,
            self.tables_dir,
            "general",
            heading_style_map={"Heading1": 1, "Heading2": 2},
        )
        self.assertEqual(res.chapter_count, 1)
        chapter_files = list(self.content_dir.glob("*.md"))
        content = chapter_files[0].read_text(encoding="utf-8")
        self.assertIn("# 真实第一章", content)
        self.assertNotIn("## \n", content)
        self.assertNotIn("## \r", content)

    def test_table_escaping_pipe_and_backslash(self):
        docx_path = self.temp_dir / "table_esc.docx"
        body = """
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>表格测试章</w:t></w:r></w:p>
            <w:tbl>
                <w:tr>
                    <w:tc><w:p><w:r><w:t>路径</w:t></w:r></w:p></w:tc>
                    <w:tc><w:p><w:r><w:t>条件 | 规则</w:t></w:r></w:p></w:tc>
                </w:tr>
                <w:tr>
                    <w:tc><w:p><w:r><w:t>C:\\data\\test.txt</w:t></w:r></w:p></w:tc>
                    <w:tc><w:p><w:r><w:t>A | B</w:t></w:r></w:p></w:tc>
                </w:tr>
            </w:tbl>
        """
        _make_minimal_docx(docx_path, body)
        res = extract_content(
            docx_path,
            self.content_dir,
            self.images_dir,
            self.tables_dir,
            "general",
            heading_style_map={"Heading1": 1},
        )
        self.assertEqual(res.table_count, 1)
        md_file = list(self.content_dir.glob("*.md"))[0]
        content = md_file.read_text(encoding="utf-8")
        self.assertIn(r"C:\\data\\test.txt", content)
        self.assertIn(r"A \| B", content)

    def test_external_image_link_conversion(self):
        docx_path = self.temp_dir / "external_img.docx"
        body = """
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>图片章</w:t></w:r></w:p>
            <w:p>
                <w:r>
                    <w:drawing>
                        <wp:inline xmlns:wp="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                            <a:blip xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" r:embed="rIdExternal"/>
                        </wp:inline>
                    </w:drawing>
                </w:r>
            </w:p>
        """
        rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="{PR_NS}">
            <Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.com/assets/logo.png" TargetMode="External"/>
        </Relationships>"""
        _make_minimal_docx(docx_path, body, rels_xml=rels)
        extract_content(
            docx_path,
            self.content_dir,
            self.images_dir,
            self.tables_dir,
            "general",
            heading_style_map={"Heading1": 1},
        )
        md_file = list(self.content_dir.glob("*.md"))[0]
        content = md_file.read_text(encoding="utf-8")
        self.assertIn("![图片](https://example.com/assets/logo.png)", content)


class TestBuilderFormattingEdgeCases(unittest.TestCase):
    """验证文档构建排版器中星号、公式乘号、脱敏掩码及标题降级逻辑。"""

    def test_paragraph_starting_with_italic_not_rejected_as_multiplication(self):
        text = "*开头即为斜体* 后续普通文本"
        res = parse_inline_runs(text)
        self.assertEqual(res, [("开头即为斜体", "italic"), (" 后续普通文本", "")])

    def test_bold_italic_three_asterisks(self):
        text = "***加粗斜体文本***"
        self.assertEqual(parse_inline_runs(text), [("加粗斜体文本", "bold_italic")])
        text_mixed = "前缀 ***重点提示*** 后缀"
        self.assertEqual(parse_inline_runs(text_mixed), [("前缀 ", ""), ("重点提示", "bold_italic"), (" 后缀", "")])

    def test_formula_multiplications_preserved_plain(self):
        cases = [
            "2*3",
            "1.5*10",
            "(a+b)*(c+d)",
            "2*x",
            "x*2",
            "长度*0.5",
        ]
        for c in cases:
            res = parse_inline_runs(c)
            self.assertEqual(res, [(c, "")], f"Formula {c} was unexpectedly formatted: {res}")

    def test_wildcards_and_redaction_masks_preserved_plain(self):
        cases = [
            "DATALOG/***.edf",
            "dir/**/file",
            "*.tmp",
            "****脱敏****",
            "******密码掩码******",
        ]
        for c in cases:
            res = parse_inline_runs(c)
            self.assertEqual(res, [(c, "")], f"Pattern {c} was unexpectedly formatted: {res}")

    def test_bold_with_punctuation(self):
        text = "**注意：必须按照步骤执行；否则会导致失败。**"
        self.assertEqual(parse_inline_runs(text), [("注意：必须按照步骤执行；否则会导致失败。", "bold")])

    def test_italic_with_chinese_comma_and_period(self):
        text = "*带有逗号，的斜体*"
        self.assertEqual(parse_inline_runs(text), [("带有逗号，的斜体", "italic")])
        text2 = "*带有句号。的斜体*"
        self.assertEqual(parse_inline_runs(text2), [("带有句号。的斜体", "italic")])

    def test_make_heading_fallback_when_level_missing(self):
        style_map = {1: "Heading1"}
        p = make_heading(style_map, "三级标题内容", 3)
        style_val = p.find(f".//{W}pStyle").get(f"{W}val")
        self.assertEqual(style_val, "Heading1")


class TestRoundtripAndValidatorEdgeCases(unittest.TestCase):
    """验证往返对比与校验器对无标题文档、VML 图片与反引号的健壮处理。"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_roundtrip_audit_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_headless_docx_events_and_roundtrip_diff(self):
        source_docx = self.temp_dir / "source_headless.docx"
        rebuilt_docx = self.temp_dir / "rebuilt_headless.docx"
        body = """
            <w:p><w:r><w:t>正文第一行</w:t></w:r></w:p>
            <w:p><w:r><w:t>正文第二行</w:t></w:r></w:p>
        """
        _make_minimal_docx(source_docx, body)
        _make_minimal_docx(rebuilt_docx, body)

        report = roundtrip_diff(source_docx, rebuilt_docx, allow_missing_headings=True)
        self.assertFalse(report.has_block)
        self.assertEqual(len(report.warn_issues), 0)

    def test_vml_imagedata_extracted_in_validator(self):
        docx_path = self.temp_dir / "vml_img.docx"
        body = """
            <w:p>
                <w:r>
                    <w:pict>
                        <v:shape id="shape1">
                            <v:imagedata r:id="rIdVmlImg"/>
                        </v:shape>
                    </w:pict>
                </w:r>
            </w:p>
        """
        rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="{PR_NS}">
            <Relationship Id="rIdVmlImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
            <Relationship Id="rIdSettings" Type="{PR_NS}/settings" Target="settings.xml"/>
            <Relationship Id="rIdStyles" Type="{PR_NS}/styles" Target="styles.xml"/>
        </Relationships>"""
        media = {"word/media/image1.png": PNG_1X1}
        _make_minimal_docx(docx_path, body, rels_xml=rels, media_files=media)

        pkg = DocxPackage(str(docx_path))
        events = pkg.body_events(allow_missing_headings=True)
        img_events = [e for e in events if e.kind == "I"]
        self.assertEqual(len(img_events), 1)
        self.assertEqual(len(img_events[0].value), 1)


class TestEndToEndHeadlessImport(unittest.TestCase):
    """验证无标题文档端到端导入、元数据标记与构建往返完整闭环。"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_e2e_headless_"))
        self.source_docx = self.temp_dir / "source.docx"
        body = """
            <w:p><w:r><w:t>无任何 Heading 的纯文本正文 1</w:t></w:r></w:p>
            <w:p><w:r><w:t>无任何 Heading 的纯文本正文 2</w:t></w:r></w:p>
        """
        _make_minimal_docx(self.source_docx, body)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_headless_import_and_manifest(self):
        project_dir = self.temp_dir / "output_project"
        request = ImportRequest(
            source_docx=str(self.source_docx),
            target_project_root=str(project_dir),
            document_type="general",
            document_name="无标题兼容文档",
            document_no="TEST-HL-001",
            document_version="1.0",
            allow_missing_headings=True,
        )
        result = import_first_time(request)
        self.assertTrue(result.success)

        manifest = ProjectManifest.load(project_dir / "project.yml")
        self.assertTrue(manifest.allow_missing_headings)
        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.adapters.kernel import build_with_project, validate_with_project
        paths = ProjectPaths(project_dir)
        build_with_project(manifest, paths)
        val_res = validate_with_project(manifest, paths, baseline=True)
        self.assertTrue(val_res, "大纲级别无H1文档构建后执行 baseline 校验应通过")
        manifest_path = project_dir / "project.yml"
        self.assertTrue(manifest_path.exists())
        manifest = ProjectManifest.load(manifest_path)
        self.assertTrue(manifest.is_headless)

        # 检查正文文件是否成功生成
        content_files = [p for p in (project_dir / "content" / "general").rglob("*.md") if not p.name.startswith("_revision")]
        self.assertEqual(len(content_files), 1)
        md_text = content_files[0].read_text(encoding="utf-8")
        self.assertIn("无任何 Heading 的纯文本正文 1", md_text)
        self.assertIn("无任何 Heading 的纯文本正文 2", md_text)

        # 进一步验证：无标题文档构建与 baseline 校验全流程通过
        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.adapters.kernel import build_with_project, validate_with_project
        paths = ProjectPaths(project_dir)
        build_with_project(manifest, paths)
        val_res = validate_with_project(manifest, paths, baseline=True)
        self.assertTrue(val_res, "无标题文档项目构建后执行全项 baseline 校验应通过")


class TestEndToEndShiftedHeadingsImport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_e2e_shifted_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_import_starting_with_h3(self):
        docx = self.temp_dir / "h3_doc.docx"
        body = """
            <w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>第3级标题作为首级</w:t></w:r></w:p>
            <w:p><w:r><w:t>段落文字内容</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx, body)
        project_dir = self.temp_dir / "proj_h3"
        request = ImportRequest(
            source_docx=str(docx),
            target_project_root=str(project_dir),
            document_type="general",
            document_name="H3开始的文档",
            document_no="TEST-H3-001",
            document_version="1.0",
            allow_missing_headings=True,
        )
        result = import_first_time(request)
        self.assertTrue(result.success)
        manifest = ProjectManifest.load(project_dir / "project.yml")
        self.assertEqual(manifest.headingStyles.get(1), "Heading3")

        chapter_items = list((project_dir / "content" / "general").iterdir())
        self.assertTrue(any("第3级标题作为首级" in p.name for p in chapter_items))

    def test_subtitle_not_misidentified_as_heading(self):
        """副标题（Subtitle）不应被启发式识别为 Heading 标题。"""
        from doc_tool.domain.ooxml import infer_heading_level_from_style_id
        self.assertIsNone(infer_heading_level_from_style_id("副标题"))
        self.assertIsNone(infer_heading_level_from_style_id("副标题 1"))
        self.assertIsNone(infer_heading_level_from_style_id("副标题1"))
        self.assertIsNone(infer_heading_level_from_style_id("Subtitle"))
        self.assertIsNone(infer_heading_level_from_style_id("subtitle 1"))

    def test_strikethrough_inline_markdown(self):
        """支持 ~~删除线~~ 行内语法并在 Word 中生成 w:strike 属性。"""
        from build_docx import parse_inline_runs, make_paragraph, qn
        runs = parse_inline_runs("这是 ~~已作废条款~~ 的说明")
        self.assertIn(("已作废条款", "strike"), runs)
        p = make_paragraph(None, "这是 ~~已作废条款~~ 的说明")
        strikes = p.findall(".//" + qn("strike"))
        self.assertEqual(len(strikes), 1)

    def test_table_col_widths_partial_padding(self):
        """表格列宽信息不足时，保留已有宽度并对缺失列安全补足默认宽度。"""
        from build_docx import make_table_from_md, qn
        tbl = make_table_from_md([["A", "B", "C"]], col_widths=[1200])
        cols = [int(gc.get(qn("w"))) for gc in tbl.findall(".//" + qn("gridCol"))]
        self.assertEqual(cols, [1200, 2400, 2400])

    def test_vml_imagedata_in_table_preserved_as_xml(self):
        """表格单元格内包含 VML imagedata 图片时，判定为复杂表格转为 XML 存储，避免图片丢失。"""
        from doc_tool.adapters.importer import _table_is_simple
        xml = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:v="urn:schemas-microsoft-com:vml" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:tr><w:tc><w:p><w:r><v:imagedata r:id="rId10"/></w:r></w:p></w:tc></w:tr></w:tbl>'
        )
        tbl_el = etree.fromstring(xml.encode("utf-8"))
        self.assertFalse(_table_is_simple(tbl_el))

    def test_preflight_ignores_empty_headings(self):
        """预检分析阶段应忽略无文本无图片的空标题段落，避免层级虚假跳跃。"""
        docx_path = self.temp_dir / "preflight_empty_h.docx"
        body = """
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr></w:p>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>真实章节标题</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx_path, body)
        preview = preflight(str(docx_path))
        self.assertEqual(len(preview.headings), 1)
        self.assertEqual(preview.headings[0].text, "真实章节标题")

    def test_end_to_end_import_with_outline_lvl_heading(self):
        docx = self.temp_dir / "outline_doc.docx"
        body = """
            <w:p><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>大纲级别2作为标题</w:t></w:r></w:p>
            <w:p><w:r><w:t>普通正文段落</w:t></w:r></w:p>
        """
        _make_minimal_docx(docx, body)
        project_dir = self.temp_dir / "proj_outline"
        request = ImportRequest(
            source_docx=str(docx),
            target_project_root=str(project_dir),
            document_type="general",
            document_name="大纲级别文档",
            document_no="TEST-OTL-001",
            document_version="1.0",
            allow_missing_headings=True,
        )
        result = import_first_time(request)
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main(verbosity=2)
