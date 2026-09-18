# -*- coding: utf-8 -*-
"""事务化首次导入回归与端到端验收测试。

任务 4.8：父正文 ``_index.md``、普通/复杂表格、图片与事件顺序的导入回归。
任务 4.9：两份基线风格 + 改名 DOCX 的端到端首次导入验收。

测试用最小化但结构完整的合成 DOCX（直接构造 ZIP + XML）覆盖导入全流程，不依赖
真实公司文档：含封面字段表、Heading 1~3 树、父正文、图片、普通表格与复杂表格。
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)

from doc_tool.adapters.importer import (  # noqa: E402
    extract_content,
    generate_template,
    split_into_tree,
)
from doc_tool.application.import_project import (  # noqa: E402
    ImportRequest,
    import_first_time,
)
from doc_tool.domain.cancellation import CancellationToken  # noqa: E402
from doc_tool.domain.errors import BuildError, TargetProjectExistsError  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --- OOXML 命名空间 ---

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

PNG_1x1 = (
    b'\x89PNG\r\n\x1a\n'
    b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
    b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01'
    b'\x00\x05\xfe\xd4\x00\x00\x00\x00IEND\xaeB`\x82'
)


def _valid_png_bytes():
    """用 PIL 生成可解码的有效 2x2 PNG（试构建会通过 PIL 解码图片尺寸）。"""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


PNG_VALID = _valid_png_bytes()

CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="{ct}">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/settings.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
    '<Override PartName="/word/numbering.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    '</Types>'
).format(ct=CT_NS)


def _styles_xml(
    localized=False, include_character_heading_styles=False,
    derived_heading1_style_id=None,
) -> bytes:
    styles = []
    for level in range(1, 7):
        style_name = "标题 {0}".format(level) if localized else "heading {0}".format(level)
        styles.append(
            '<w:style w:type="paragraph" w:styleId="{0}"><w:name w:val="{1}"/></w:style>'.format(
                level, style_name
            )
        )
        if include_character_heading_styles:
            styles.append(
                '<w:style w:type="character" w:styleId="{0}"><w:name w:val="标题 {1} Char"/></w:style>'.format(
                    54 + level, level
                )
            )
    if derived_heading1_style_id is not None:
        # 复刻真实设计模板的冲突：基于内置 heading 1 派生的自定义「标题1」，
        # customStyle=1、basedOn=1、无 outlineLvl，名字同样命中级别 1。
        styles.append(
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="{0}">'
            '<w:name w:val="标题1"/><w:basedOn w:val="1"/></w:style>'.format(
                derived_heading1_style_id
            )
        )
    styles.append('<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="{ns}">{body}</w:styles>'
    ).format(ns=W_NS, body="".join(styles)).encode("utf-8")


def _settings_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:settings xmlns:w="{ns}"/>'
    ).format(ns=W_NS).encode("utf-8")


def _numbering_xml() -> bytes:
    """最小 numbering.xml（构建前置校验要求该部件存在且良构）。"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:numbering xmlns:w="{ns}"/>'
    ).format(ns=W_NS).encode("utf-8")


def _p(style_id, text):
    return '<w:p><w:pPr><w:pStyle w:val="{0}"/></w:pPr><w:r><w:t>{1}</w:t></w:r></w:p>'.format(style_id, text)


def _body_p(text):
    return '<w:p><w:r><w:t>{0}</w:t></w:r></w:p>'.format(text)


def _cover_table(doc_no, version):
    """封面字段表：文件编号/版本号/页数 三行两列。"""
    rows = [
        ("文件编号", doc_no),
        ("版本号", version),
        ("页数", "1"),
    ]
    trs = []
    for label, value in rows:
        trs.append(
            "<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>{0}</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:tcPr/><w:p><w:r><w:t>{1}</w:t></w:r></w:p></w:tc></w:tr>".format(label, value)
        )
    return (
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="4000"/></w:tblGrid>{rows}</w:tbl>'
    ).format(rows="".join(trs))


def _simple_table():
    return (
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="3000"/><w:gridCol w:w="3000"/></w:tblGrid>'
        '<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>列A</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:tcPr/><w:p><w:r><w:t>列B</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:tcPr/><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl>'
    )


def _complex_table():
    """含 gridSpan 的复杂表格（应作为 XML 资源提取）。"""
    return (
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="3000"/><w:gridCol w:w="3000"/></w:tblGrid>'
        '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
        '<w:p><w:r><w:t>合并表头</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:tcPr/><w:p><w:r><w:t>y</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl>'
    )


def _image_paragraph(rid="rId1", cx=190500, cy=190500):
    return (
        '<w:p><w:r><w:drawing>'
        '<wp:inline xmlns:wp="{wp}">'
        '<wp:extent cx="{cx}" cy="{cy}"/>'
        '<a:graphic xmlns:a="{a}"><a:graphicData>'
        '<pic:pic xmlns:pic="{pic}"><pic:blipFill>'
        '<a:blip r:embed="{rid}"/>'
        '</pic:blipFill></pic:pic></a:graphicData></a:graphic>'
        '</wp:inline></w:drawing></w:r></w:p>'
    ).format(wp=WP_NS, a=A_NS, pic=PIC_NS, rid=rid, cx=cx, cy=cy)


def _build_body_xml(with_cover=True, with_image=True, with_tables=True, with_comment=False):
    """构造正文：封面 + H1/H2/H3 树 + 父正文 + 图片 + 普通/复杂表格。"""
    parts = []
    if with_cover:
        parts.append(_cover_table("GX-TEST-001", "1.0"))
    # 第1章 引言：父正文 + H2 叶子
    parts.append(_p("1", "引言"))
    parts.append(_body_p("本章父正文，应写入 _index.md 且位于子章节之前。"))
    parts.append(_p("2", "目的"))
    parts.append(_body_p("说明项目目的。"))
    if with_comment:
        # 批注特性：正文段落含 commentRangeStart（保真扫描应识别）。
        parts.append(
            '<w:p><w:commentRangeStart w:id="1"/><w:comment w:id="1"/>'
            '<w:r><w:t>有批注的正文</w:t></w:r></w:p>'
        )
    if with_image:
        parts.append(_image_paragraph())
    if with_tables:
        parts.append(_body_p("以下是普通表格："))
        parts.append(_simple_table())
        parts.append(_body_p("以下是复杂表格："))
        parts.append(_complex_table())
    # 第2章 详细设计：H2 目录（含 H3 子节点）
    parts.append(_p("1", "详细设计"))
    parts.append(_body_p("第二章父正文。"))
    parts.append(_p("2", "接口设计"))
    parts.append(_p("3", "接口契约"))
    parts.append(_body_p("接口契约正文。"))
    return "".join(parts)


def _document_xml(body_xml):
    sect_pr = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{w}" xmlns:r="{r}" xmlns:a="{a}" xmlns:wp="{wp}" xmlns:pic="{pic}">'
        '<w:body>{body}{sect}</w:body></w:document>'
    ).format(w=W_NS, r=R_NS, a=A_NS, wp=WP_NS, pic=PIC_NS, body=body_xml, sect=sect_pr).encode("utf-8")


def _rels_xml(with_image=True):
    rels = []
    if with_image:
        rels.append('<Relationship Id="rId1" Type="{pr}/image" Target="media/image1.png"/>'.format(pr=PR_NS))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{pr}">{body}</Relationships>'
    ).format(pr=PR_NS, body="".join(rels)).encode("utf-8")


def write_synthetic_docx(
    path,
    with_cover=True,
    with_image=True,
    with_tables=True,
    with_numbering=True,
    localized_styles=False,
    include_character_heading_styles=False,
    with_comment=False,
    derived_heading1_style_id=None,
):
    """写入结构完整的合成 DOCX，可往返通过导入与试构建。"""
    body = _build_body_xml(
        with_cover=with_cover,
        with_image=with_image,
        with_tables=with_tables,
        with_comment=with_comment,
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("word/document.xml", _document_xml(body))
        zf.writestr(
            "word/styles.xml",
            _styles_xml(
                localized=localized_styles,
                include_character_heading_styles=include_character_heading_styles,
                derived_heading1_style_id=derived_heading1_style_id,
            ),
        )
        zf.writestr("word/settings.xml", _settings_xml())
        if with_numbering:
            zf.writestr("word/numbering.xml", _numbering_xml())
        zf.writestr("word/_rels/document.xml.rels", _rels_xml(with_image=with_image))
        if with_image:
            zf.writestr("word/media/image1.png", PNG_VALID)
    return path


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- 4.8 导入回归：提取与拆分 ---


class ExtractionRegressionTests(unittest.TestCase):
    """任务 4.8：父正文 _index.md、普通/复杂表格、图片与事件顺序回归。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-import-reg-")
        self._docx = os.path.join(self._tmp, "source.docx")
        write_synthetic_docx(self._docx)
        self._content = os.path.join(self._tmp, "content", "general")
        self._images = os.path.join(self._tmp, "assets", "general", "images")
        self._tables = os.path.join(self._tmp, "assets", "general", "tables")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_parent_body_writes_index_md_before_children(self):
        """父章节自身正文写入 _index.md 且目录树在子章节之前。"""
        extract_content(self._docx, self._content, self._images, self._tables, "general")
        split_into_tree(self._content)
        chapter1 = os.path.join(self._content, "第1章 引言")
        self.assertTrue(os.path.isdir(chapter1), "第1章应为目录")
        index_md = os.path.join(chapter1, "_index.md")
        self.assertTrue(os.path.isfile(index_md), "父正文应写入 _index.md")
        text = Path(index_md).read_text(encoding="utf-8")
        self.assertIn("本章父正文", text)
        # 子章节存在
        self.assertTrue(os.path.isfile(os.path.join(chapter1, "1.1 目的.md")))

    def test_simple_table_extracted_as_markdown(self):
        """普通表格提取为 Markdown 表格（带 TBL 头）。"""
        result = extract_content(self._docx, self._content, self._images, self._tables, "general")
        self.assertGreaterEqual(result.simple_table_count, 1)
        found = False
        for name in os.listdir(self._content):
            text = Path(self._content, name).read_text(encoding="utf-8")
            if "<!-- TBL:" in text and "| 列A | 列B |" in text:
                found = True
                break
        self.assertTrue(found, "应存在普通表格 Markdown")

    def test_complex_table_extracted_as_xml(self):
        """复杂表格（gridSpan）提取为 XML 资源。"""
        result = extract_content(self._docx, self._content, self._images, self._tables, "general")
        self.assertGreaterEqual(result.complex_table_count, 1)
        xmls = [f for f in os.listdir(self._tables) if f.endswith(".xml")]
        self.assertGreaterEqual(len(xmls), 1, "应生成复杂表格 XML 文件")
        # Markdown 中应引用该 XML
        referenced = False
        for name in os.listdir(self._content):
            text = Path(self._content, name).read_text(encoding="utf-8")
            if "<!-- TABLE:" in text and ".xml -->" in text:
                referenced = True
                break
        self.assertTrue(referenced, "Markdown 应引用复杂表格 XML")

    def test_image_extracted_with_dimensions(self):
        """图片提取并保留尺寸标注。"""
        result = extract_content(self._docx, self._content, self._images, self._tables, "general")
        self.assertEqual(result.image_count, 1)
        imgs = os.listdir(self._images)
        self.assertEqual(len(imgs), 1)
        text = Path(self._content, os.listdir(self._content)[0]).read_text(encoding="utf-8")
        self.assertIn("images/", text)
        self.assertIn("=20x20", text, "应保留图片像素尺寸标注")

    def test_event_order_preserved(self):
        """正文/图片/表格按源文档顺序提取，事件顺序保持一致。"""
        result = extract_content(self._docx, self._content, self._images, self._tables, "general")
        # 第1章 Markdown 中应按顺序出现：父正文 -> H2 -> 图片 -> 普通表格 -> 复杂表格
        names = sorted(os.listdir(self._content))
        chap1 = [n for n in names if n.startswith("01-")][0]
        text = Path(self._content, chap1).read_text(encoding="utf-8")
        pos_body = text.find("本章父正文")
        pos_h2 = text.find("## 目的")
        pos_img = text.find("![")
        pos_simple = text.find("列A")
        pos_complex = text.find("<!-- TABLE:")
        self.assertLess(pos_body, pos_h2, "父正文应在 H2 之前")
        self.assertLess(pos_h2, pos_img, "H2 应在图片之前")
        self.assertLess(pos_img, pos_simple, "图片应在普通表格之前")
        self.assertLess(pos_simple, pos_complex, "普通表格应在复杂表格之前")

    def test_paragraph_with_soft_break_extracted_as_br_and_roundtrips(self):
        """段落内含软换行（<w:br/>）提取为 <br>，且完整导入能通过往返门禁。"""
        src = os.path.join(self._tmp, "soft_break.docx")
        body = (
            _cover_table("GX-TEST-002", "1.0")
            + _p("1", "引言")
            + '<w:p><w:r><w:t>第一行</w:t><w:br/><w:t>第二行</w:t></w:r></w:p>'
        )
        with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
            zf.writestr("word/document.xml", _document_xml(body))
            zf.writestr("word/styles.xml", _styles_xml())
            zf.writestr("word/settings.xml", _settings_xml())
            zf.writestr("word/numbering.xml", _numbering_xml())
            zf.writestr("word/_rels/document.xml.rels", _rels_xml(with_image=False))

        # 1. 提取验证：Markdown 文件中包含第一行<br>第二行，且未被拆分成多行
        content_dir = os.path.join(self._tmp, "sb_content")
        extract_content(src, content_dir, self._images, self._tables, "general")
        md_file = os.path.join(content_dir, "01-引言.md")
        self.assertTrue(os.path.isfile(md_file))
        text = Path(md_file).read_text(encoding="utf-8")
        self.assertIn("第一行<br>第二行", text)
        self.assertNotIn("第一行\n第二行", text)

        # 2. 端到端首次导入验证：往返差异门禁必须通过，不能报 E2004
        target = os.path.join(self._tmp, "sb_proj")
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type="general",
            document_no="GX-TEST-002",
            document_name="软换行测试",
            document_version="1.0",
        )
        result = import_first_time(request)
        self.assertTrue(result.success, "含软换行段落导入应成功且通过往返门禁：{0}".format(
            [(e.stage, e.status, e.detail) for e in result.events]
        ))



# --- 4.9 端到端首次导入验收 ---


class ImportEndToEndTests(unittest.TestCase):
    """任务 4.9：两份基线风格 + 改名 DOCX 端到端首次导入验收。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-import-e2e-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _import(self, docx_name="GX-TEST-001 测试文档(1.0).docx", doc_type="general",
                with_cover=True, with_image=True, with_tables=True,
                project_name="测试项目"):
        src = os.path.join(self._tmp, docx_name)
        write_synthetic_docx(src, with_cover=with_cover, with_image=with_image, with_tables=with_tables)
        src_sha = _sha256(src)
        target = os.path.join(self._tmp, project_name)
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type=doc_type,
            document_no="GX-TEST-001",
            document_name="测试文档",
            document_version="1.0",
        )
        return src, src_sha, target, import_first_time(request)

    def test_general_docx_full_import(self):
        """通用大文档完整首次导入：预检->提取->拆分->结构校验->试构建->原子发布。"""
        src, src_sha, target, result = self._import()
        self.assertTrue(result.success, "导入应成功；失败事件: {0}".format(
            [(e.stage, e.status, e.detail) for e in result.events]))
        self.assertEqual(result.source_sha256, src_sha)
        self.assertTrue(os.path.isdir(target), "项目目录应已发布")
        # 项目结构完整性
        self.assertTrue(os.path.isfile(os.path.join(target, "project.yml")))
        self.assertTrue(os.path.isfile(os.path.join(target, "original", "source.docx")))
        self.assertTrue(os.path.isfile(os.path.join(target, "template", "template.docx")))
        self.assertTrue(os.path.isdir(os.path.join(target, "content", "general")))
        self.assertTrue(os.path.isdir(os.path.join(target, "assets", "general", "images")))
        self.assertTrue(os.path.isdir(os.path.join(target, "assets", "general", "tables")))
        # 章节目录树已生成
        self.assertTrue(os.path.isdir(os.path.join(target, "content", "general", "第1章 引言")))
        self.assertTrue(os.path.isdir(os.path.join(target, "content", "general", "第2章 详细设计")))
        # 所有阶段成功
        stages = {e.stage: e.status for e in result.events}
        self.assertEqual(stages.get("publish"), "succeeded")

    def test_legacy_document_type_import_rejected(self):
        """任务 4.4：公共版拒绝新建 requirement/design 项目且不创建目录。"""
        for legacy_type in ("requirement", "design"):
            src = os.path.join(self._tmp, "legacy-{0}.docx".format(legacy_type))
            write_synthetic_docx(src)
            target = os.path.join(self._tmp, "legacy-{0}-项目".format(legacy_type))
            request = ImportRequest(
                source_docx=Path(src),
                target_project_root=Path(target),
                document_type=legacy_type,
                document_no="LEG-1",
                document_name="旧类型文档",
                document_version="1.0",
            )
            result = import_first_time(request)
            self.assertFalse(result.success, "legacy {0} 导入应被拒绝".format(legacy_type))
            self.assertEqual(result.error_code, "E1001")
            self.assertFalse(os.path.exists(target), "不应创建半成品目录")
            self.assertIn("通用", result.events[-1].detail)

    def test_derived_heading1_style_does_not_win_collision(self):
        """派生自定义「标题1」不得顶掉内置 heading 1（真实设计模板缺陷）。

        源文档同时定义内置 heading 1（styleId 1）与基于它派生的自定义
        「标题1」（styleId 140）。清单必须记住内置样式，否则构建出的全部
        一级章会写成自定义样式，丢掉大纲级别与编号关联。
        """
        src = os.path.join(self._tmp, "冲突样式.docx")
        write_synthetic_docx(src, derived_heading1_style_id="140")
        target = os.path.join(self._tmp, "冲突样式项目")
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type="general",
            document_no="GX-TEST-003",
            document_name="冲突样式文档",
            document_version="1.0",
        )
        result = import_first_time(request)
        self.assertTrue(result.success, "导入应成功：{0}".format(
            [(e.stage, e.status, e.detail) for e in result.events]
        ))
        from doc_tool.domain.manifest import ProjectManifest

        loaded = ProjectManifest.load(target)
        self.assertEqual(loaded.headingStyles[1], "1")
        self.assertNotEqual(loaded.headingStyles[1], "140")
        self.assertEqual(
            loaded.headingStyles, {level: str(level) for level in range(1, 7)}
        )

    def test_general_docx_without_company_cover_full_import(self):
        """通用大文档不要求星河封面、文档编号或版本。"""
        src = os.path.join(self._tmp, "运维手册.docx")
        write_synthetic_docx(
            src,
            with_cover=False,
            with_numbering=False,
            localized_styles=True,
            include_character_heading_styles=True,
        )
        target = os.path.join(self._tmp, "通用大文档项目")
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type="general",
            document_no="",
            document_name="运维手册",
            document_version="",
        )
        result = import_first_time(request)
        self.assertTrue(result.success, "通用文档导入应成功：{0}".format(
            [(e.stage, e.status, e.detail) for e in result.events]
        ))
        self.assertTrue(os.path.isdir(os.path.join(target, "content", "general")))
        self.assertTrue(os.path.isdir(os.path.join(target, "assets", "general")))
        import yaml
        manifest = yaml.safe_load(Path(target, "project.yml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["documentType"], "general")
        self.assertEqual(manifest["documentNo"], "")
        from doc_tool.adapters.kernel import build_with_project, validate_with_project
        from doc_tool.domain.manifest import ProjectManifest

        loaded = ProjectManifest.load(target)
        self.assertEqual(loaded.headingStyles, {level: str(level) for level in range(1, 7)})
        paths = loaded.resolve_paths(target)
        output = build_with_project(loaded, paths)
        self.assertEqual(Path(output).name, "运维手册.docx")
        self.assertTrue(validate_with_project(loaded, paths))
        self.assertTrue(
            validate_with_project(loaded, paths, require_refreshed=True),
            "通用模式的后校验不应强制星河 TOC/NUMPAGES 规则",
        )

        # 兼容早期导入器生成的清单：55..60 是“标题 N Char”字符样式，
        # 构建时应依据模板自动恢复为真正的 paragraph Heading 样式。
        loaded.headingStyles = {level: str(54 + level) for level in range(1, 7)}
        build_with_project(loaded, paths)
        self.assertEqual(loaded.headingStyles, {level: str(level) for level in range(1, 7)})
        self.assertTrue(validate_with_project(loaded, paths))

    def test_renamed_docx_import(self):
        """改名 DOCX（文件名与基线不同）仍能完整导入。"""
        renamed = "公司内部文档-需求说明书(v9).docx"
        src, src_sha, target, result = self._import(docx_name=renamed, project_name="改名项目")
        self.assertTrue(result.success, "改名 DOCX 应能导入；失败: {0}".format(
            [(e.stage, e.detail) for e in result.events if e.status == "failed"]))
        self.assertTrue(os.path.isdir(target))

    def test_target_exists_rejected(self):
        """任务 4.6：目标项目已存在时预写入拒绝，不修改已有项目。"""
        src, src_sha, target, _ = self._import(project_name="已有项目A")
        # 第二次导入到已存在的目标
        src2 = os.path.join(self._tmp, "second.docx")
        write_synthetic_docx(src2)
        request = ImportRequest(
            source_docx=Path(src2),
            target_project_root=Path(os.path.join(self._tmp, "已有项目A")),
            document_type="general", document_no="", document_name="二", document_version="2.0",
        )
        result = import_first_time(request)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, TargetProjectExistsError.code)
        # 原项目未被破坏
        self.assertTrue(os.path.isfile(os.path.join(target, "project.yml")))
        # 不应留下暂存目录
        staging = [d for d in os.listdir(self._tmp) if d.startswith(".已有项目A.import-staging")]
        self.assertEqual(staging, [], "拒绝后不应残留暂存目录")

    def test_failure_isolation_cleans_staging_and_logs(self):
        """任务 4.7：试构建失败后暂存隔离清理并写诊断日志，源文档与正式项目不受影响。"""
        from unittest import mock

        src = os.path.join(self._tmp, "buildfail.docx")
        write_synthetic_docx(src)
        src_sha = _sha256(src)
        target = os.path.join(self._tmp, "构建失败项目")
        request = ImportRequest(
            source_docx=Path(src), target_project_root=Path(target),
            document_type="general", document_no="", document_name="构建失败", document_version="1.0",
        )
        # 模拟内核构建后端失败，触发试构建阶段的隔离清理。
        with mock.patch(
            "doc_tool.application.import_project._trial_build",
            side_effect=BuildError("试构建失败：模拟"),
        ):
            result = import_first_time(request)
        self.assertFalse(result.success, "试构建失败应导致导入失败")
        self.assertEqual(result.error_code, "E2001")
        # 暂存目录已清理
        staging = [d for d in os.listdir(self._tmp) if d.startswith(".构建失败项目.import-staging")]
        self.assertEqual(staging, [], "失败后暂存目录应被清理")
        # 正式项目未创建
        self.assertFalse(os.path.exists(target), "失败时正式项目不应被创建")
        # 诊断日志已写入
        logs = [f for f in os.listdir(self._tmp) if f.startswith(".构建失败项目.import-failed")]
        self.assertEqual(len(logs), 1, "应写入一份诊断日志")
        import json
        log_data = json.loads(Path(self._tmp, logs[0]).read_text(encoding="utf-8"))
        self.assertEqual(log_data["errorCode"], "E2001")
        self.assertTrue(log_data["stagingExisted"])
        self.assertTrue(log_data["stagingCleaned"])
        self.assertIn("trial_build", [e["stage"] for e in log_data["events"] if e["status"] == "failed"])
        # 源文档未被修改（哈希不变）
        self.assertEqual(_sha256(src), src_sha)

    def test_cancelled_import_does_not_publish_project(self):
        src = os.path.join(self._tmp, "cancel.docx")
        write_synthetic_docx(src)
        target = os.path.join(self._tmp, "取消项目")
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type="general",
            document_no="",
            document_name="取消测试",
            document_version="1.0",
        )
        token = CancellationToken()
        token.request_cancel()
        result = import_first_time(request, cancel_token=token)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E5003")
        self.assertFalse(os.path.exists(target))
        self.assertTrue(any(event.status == "cancelled" for event in result.events))

    def test_source_docx_not_modified(self):
        """任务 4.4：成功导入后源 DOCX 字节不变。"""
        src, src_sha, target, result = self._import()
        self.assertTrue(result.success)
        self.assertEqual(_sha256(src), src_sha, "源 DOCX 不应被修改")

    def test_manifest_portability(self):
        """清单使用相对路径且记录源哈希，复制到另一路径仍可加载。"""
        src, src_sha, target, result = self._import()
        self.assertTrue(result.success)
        import yaml
        manifest = yaml.safe_load(Path(target, "project.yml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sourceSha256"], src_sha)
        self.assertEqual(manifest["documentType"], "general")
        for key, rel in manifest["paths"].items():
            self.assertFalse(os.path.isabs(rel), "{0} 应为相对路径".format(key))
            self.assertFalse(rel.startswith(".."), "{0} 不应越界".format(key))
        # 复制到另一路径仍可加载
        from doc_tool.domain.manifest import ProjectManifest
        copy_to = os.path.join(self._tmp, "copied-project")
        import shutil
        shutil.copytree(target, copy_to)
        loaded = ProjectManifest.load(copy_to)
        self.assertEqual(loaded.documentNo, "GX-TEST-001")

    def test_manifest_heading_styles_float_key_rejected(self):
        """headingStyles 的浮点键（1.5）必须被拒绝，而非静默截断成级别 1。"""
        from doc_tool.domain.errors import ProjectManifestError
        from doc_tool.domain.manifest import ProjectManifest

        base = {
            "schemaVersion": 1,
            "documentType": "general",
            "documentNo": "",
            "documentName": "测试",
            "documentVersion": "1.0",
            "sourceSha256": "",
            "paths": {
                "sourceDocx": "original/source.docx",
                "templateDocx": "template/template.docx",
                "contentRoot": "content/general",
                "assetRoot": "assets/general",
                "tableRoot": "assets/general/tables",
            },
        }
        with self.assertRaises(ProjectManifestError):
            ProjectManifest.from_dict(dict(base, headingStyles={"1.5": "Heading1"}))
        with self.assertRaises(ProjectManifestError):
            ProjectManifest.from_dict(dict(base, headingStyles={0: "Heading1"}))
        # 合法字符串/整数键仍可加载，级别不丢失。
        manifest = ProjectManifest.from_dict(
            dict(base, headingStyles={"1": "Heading1", "2": "Heading2"})
        )
        self.assertEqual(manifest.headingStyles, {1: "Heading1", 2: "Heading2"})

    def test_atomic_publish_no_partial_project_on_failure(self):
        """任务 4.5：失败时不会留下半成品项目目录。"""
        from unittest import mock

        src = os.path.join(self._tmp, "atomic-fail.docx")
        write_synthetic_docx(src)
        target = os.path.join(self._tmp, "原子性项目")
        request = ImportRequest(
            source_docx=Path(src), target_project_root=Path(target),
            document_type="general", document_no="", document_name="原子", document_version="1.0",
        )
        with mock.patch(
            "doc_tool.application.import_project._trial_build",
            side_effect=BuildError("试构建失败：模拟"),
        ):
            result = import_first_time(request)
        self.assertFalse(result.success)
        self.assertFalse(os.path.exists(target), "失败时不应创建半成品项目目录")


# --- 2.5/4.5 往返差异门禁 ---


def _blocking_report():
    from doc_tool.adapters.roundtrip import RoundtripIssue, RoundtripReport, SEVERITY_BLOCK

    return RoundtripReport(
        3, 2, (RoundtripIssue(SEVERITY_BLOCK, "正文段落丢失：源 P=正文", "#1"),)
    )


def _warn_report():
    from doc_tool.adapters.roundtrip import RoundtripIssue, RoundtripReport, SEVERITY_WARN

    return RoundtripReport(
        2, 2, (RoundtripIssue(SEVERITY_WARN, "表格表示差异：源 单元格A，重建 单元格B", "#0"),)
    )


def _clean_report():
    from doc_tool.adapters.roundtrip import RoundtripReport

    return RoundtripReport(2, 2, ())


class RoundtripGateTests(unittest.TestCase):
    """任务 2.5/4.5：BLOCK 阻止发布且暂存清理、仅 WARN 放行、严格开关、诊断日志摘要。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-roundtrip-gate-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _import(self, report, *, require_exact=False, with_comment=False):
        src = os.path.join(self._tmp, "gate.docx")
        write_synthetic_docx(src, with_comment=with_comment)
        target = os.path.join(self._tmp, "门禁项目")
        request = ImportRequest(
            source_docx=Path(src),
            target_project_root=Path(target),
            document_type="general",
            document_no="",
            document_name="门禁",
            document_version="1.0",
            require_exact_roundtrip=require_exact,
        )
        from unittest import mock

        with mock.patch(
            "doc_tool.application.import_project._run_roundtrip_check", return_value=report
        ):
            result = import_first_time(request)
        return src, target, result

    def test_block_diff_blocks_publish_and_cleans_staging(self):
        src, target, result = self._import(_blocking_report())
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E2004")
        self.assertFalse(os.path.exists(target), "BLOCK 差异时不得发布项目")
        staging = [d for d in os.listdir(self._tmp) if d.startswith(".门禁项目.import-staging")]
        self.assertEqual(staging, [], "BLOCK 差异后暂存目录应被清理")
        roundtrip_events = [e for e in result.events if e.stage == "roundtrip_check"]
        self.assertEqual(roundtrip_events[-1].status, "failed")
        self.assertIn("BLOCK", roundtrip_events[-1].detail)

    def test_warn_diff_allowed_by_default(self):
        src, target, result = self._import(_warn_report())
        self.assertTrue(result.success, "仅 WARN 差异默认放行")
        self.assertTrue(os.path.isdir(target))
        roundtrip_events = [e for e in result.events if e.stage == "roundtrip_check"]
        self.assertEqual(roundtrip_events[-1].status, "succeeded")
        self.assertEqual(roundtrip_events[-1].metrics.get("warn"), 1)

    def test_require_exact_roundtrip_blocks_warn(self):
        src, target, result = self._import(_warn_report(), require_exact=True)
        self.assertFalse(result.success, "严格往返要求下 WARN 也应阻止")
        self.assertEqual(result.error_code, "E2004")
        self.assertFalse(os.path.exists(target))

    def test_diagnostic_log_contains_fidelity_and_roundtrip_summary(self):
        src, target, result = self._import(_blocking_report(), with_comment=True)
        self.assertFalse(result.success)
        logs = [f for f in os.listdir(self._tmp) if f.startswith(".门禁项目.import-failed")]
        self.assertEqual(len(logs), 1, "失败应写入诊断日志")
        import json
        log_data = json.loads(Path(self._tmp, logs[0]).read_text(encoding="utf-8"))
        # 预检阶段成功事件含保真扫描摘要（含批注）
        preflight = [e for e in log_data["events"]
                     if e["stage"] == "preflight" and e["status"] == "succeeded"][-1]
        self.assertIn("批注", preflight["metrics"]["fidelity"])
        # 往返阶段 failed 且含差异摘要
        roundtrip = [e for e in log_data["events"] if e["stage"] == "roundtrip_check"][-1]
        self.assertEqual(roundtrip["status"], "failed")
        self.assertIn("BLOCK", roundtrip["detail"])

    def test_success_persists_fidelity_and_roundtrip_reports(self):
        src, target, result = self._import(_clean_report(), with_comment=True)
        self.assertTrue(result.success)
        self.assertTrue(os.path.isfile(os.path.join(target, "logs", "fidelity.md")),
                        "成功项目应保存保真报告")
        self.assertTrue(os.path.isfile(os.path.join(target, "logs", "roundtrip.md")),
                        "成功项目应保存往返差异摘要")
        text = Path(target, "logs", "fidelity.md").read_text(encoding="utf-8")
        self.assertIn("批注", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
