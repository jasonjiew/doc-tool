# -*- coding: utf-8 -*-
"""生成虚构的公开示例项目（星河知识库用户手册）。

任务 8.3：公共示例 MUST 使用虚构主体与全新内容创建，不得复用真实公司章节、
系统代号、设备型号、截图或文档编号。本脚本从零生成一个可导入的示例项目：

- ``examples/galaxy-user-manual/source.docx``：虚构源 DOCX（合成 OOXML）。
- ``examples/galaxy-user-manual/``：章节 Markdown（含普通表格）、一张虚构图片、
  一个复杂表格 XML 与 project.yml。

用法：
    python scripts/create_example.py
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
PROJECT_DIR = EXAMPLES_DIR / "galaxy-user-manual"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

# 虚构主题：星河知识库（Galaxy Knowledge Base）用户手册。
DOCUMENT_NAME = "星河知识库用户手册"
DOCUMENT_NO = "GX-MANUAL-001"
DOCUMENT_VERSION = "1.0"

# 虚构章节（Markdown 内容，全部为虚构文本）。
CHAPTERS = {
    "第1章 简介/_index.md": "# 简介\n\n欢迎使用星河知识库用户手册。本手册介绍知识库的日常维护与内容管理流程。\n",
    "第1章 简介/1.1 系统概述.md": "# 1.1 系统概述\n\n星河知识库面向内容编辑团队，提供章节化的文档编辑、校验与发布能力。\n",
    "第1章 简介/1.2 术语表.md": (
        "# 1.2 术语表\n\n"
        "| 术语 | 说明 |\n"
        "| --- | --- |\n"
        "| 章节 | 文档的最小可维护单元 |\n"
        "| 基线 | 某版本内容的快照 |\n"
    ),
    "第2章 快速上手/_index.md": "# 快速上手\n\n本章演示从新建项目到发布 Word 的最小流程。\n",
    "第2章 快速上手/2.1 新建项目.md": (
        "# 2.1 新建项目\n\n"
        "在欢迎页点击「新建项目」，选择源 Word 文档并填写项目名称。\n\n"
        "![星河知识库示例截图](images/example-dashboard.png)\n"
    ),
    "第2章 快速上手/2.2 编辑与校验.md": (
        "# 2.2 编辑与校验\n\n"
        "编辑章节后，系统会执行标题编号、术语与待办残留检查。\n\n"
        "<!-- TABLE:1:example-table.xml -->\n"
    ),
    "第2章 快速上手/2.3 发布 Word.md": "# 2.3 发布 Word\n\n校验通过后即可执行正式合并，生成可交付的 Word 文档。\n",
}


def _cover_table_xml() -> str:
    """虚构封面字段表。"""
    rows = ""
    for label, value in (("文件编号", DOCUMENT_NO), ("版本号", DOCUMENT_VERSION), ("页数", "1")):
        rows += (
            '<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>{0}</w:t></w:r></w:p></w:tc>'
            '<w:tc><w:tcPr/><w:p><w:r><w:t>{1}</w:t></w:r></w:p></w:tc></w:tr>'
        ).format(label, value)
    return (
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="4000"/></w:tblGrid>'
        '{rows}</w:tbl>'
    ).format(rows=rows)


def _paragraph(style: str, text: str) -> str:
    return (
        '<w:p><w:pPr><w:pStyle w:val="{0}"/></w:pPr><w:r><w:t>{1}</w:t></w:r></w:p>'
    ).format(style, text)


def _build_source_docx() -> bytes:
    """构造虚构源 DOCX（与首次导入兼容的结构：封面 + H1~H3 树 + 表格 + 图片）。"""
    body = _cover_table_xml()
    body += _paragraph("1", "第1章 简介")
    body += _paragraph("2", "1.1 系统概述")
    body += _paragraph("3", "知识库采用章节化存储。")
    body += _paragraph("1", "第2章 快速上手")
    body += _paragraph("2", "2.1 新建项目")
    body += _paragraph("3", "从欢迎页新建项目。")
    body += (
        '<w:p><w:r><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<wp:extent cx="914400" cy="914400"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:blipFill><a:blip r:embed="rId1"/></pic:blipFill></pic:pic>'
        '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{w}" xmlns:r="{r}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    ).format(w=W_NS, r="http://schemas.openxmlformats.org/officeDocument/2006/relationships",
             body=body)
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="{ns}">'
        + "".join(
            '<w:style w:type="paragraph" w:styleId="{0}"><w:name w:val="heading {0}"/></w:style>'
            .format(level) for level in range(1, 7)
        )
        + '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        + "</w:styles>"
    ).format(ns=W_NS)
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="{pr}">'
        '<Relationship Id="rId1" Type="{pr}/image" Target="media/image1.png"/></Relationships>'
    ).format(pr="http://schemas.openxmlformats.org/package/2006/relationships")
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="{ct}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '</Types>'
    ).format(ct=CT_NS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("word/_rels/document.xml.rels", rels)
        zf.writestr("word/media/image1.png", _example_png_bytes())
    return buf.getvalue()


def _example_png_bytes() -> bytes:
    """生成一张虚构的占位截图（渐变方块，无任何真实界面内容）。"""
    buf = io.BytesIO()
    img = Image.new("RGB", (240, 160), (86, 156, 214))
    for x in range(240):
        for y in range(160):
            if (x // 40 + y // 40) % 2 == 0:
                img.putpixel((x, y), (255, 255, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_example(force: bool = False) -> Path:
    """生成虚构示例项目到 examples/。已存在时不覆盖（除非 force）。"""
    if PROJECT_DIR.exists() and not force:
        print("示例已存在（使用 --force 重新生成）: {0}".format(PROJECT_DIR))
        return PROJECT_DIR

    content_root = PROJECT_DIR / "content" / "general"
    images_dir = content_root / "images"
    tables_dir = content_root / "tables"
    images_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    for rel, text in CHAPTERS.items():
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    (content_root / "images" / "example-dashboard.png").write_bytes(_example_png_bytes())

    # 复杂表格 XML（虚构）
    (tables_dir / "example-table.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:tbl xmlns:w="{w}"><w:tblPr/><w:tblGrid><w:gridCol w:w="3000"/>'
        '<w:gridCol w:w="3000"/></w:tblGrid>'
        '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
        '<w:p><w:r><w:t>知识库操作权限</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>编辑</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:tcPr/><w:p><w:r><w:t>章节作者</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl>'.format(w=W_NS),
        encoding="utf-8",
    )

    # 虚构源 DOCX（通过导入向导生成项目）
    source_dir = PROJECT_DIR / "original"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source.docx").write_bytes(_build_source_docx())

    # 示例说明
    (PROJECT_DIR / "README.md").write_text(
        "# 星河知识库用户手册（虚构示例）\n\n"
        "本示例使用虚构的「星河知识库」主题，仅用于演示导入、编辑与构建流程。\n"
        "不含任何真实公司、客户、系统代号、设备型号、截图或文档编号。\n\n"
        "## 结构\n"
        "- `original/source.docx`：虚构源 Word 文档，可在「新建项目」向导中导入。\n"
        "- `content/general/`：导入后生成的 Markdown 章节（含普通表格与复杂表格引用）。\n"
        "- `content/general/images/`：虚构占位截图。\n"
        "- `content/general/tables/`：虚构复杂表格 XML。\n",
        encoding="utf-8",
    )
    print("已生成虚构示例: {0}".format(PROJECT_DIR))
    return PROJECT_DIR


if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    generate_example(force=force)
