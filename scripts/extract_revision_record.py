# -*- coding: utf-8 -*-
"""从模板 DOCX 中提取修订记录表到 Markdown 文件。

用法：
    python scripts/extract_revision_record.py design
    python scripts/extract_revision_record.py requirement
    python scripts/extract_revision_record.py --project <项目路径>

从模板中定位修订记录表（版本 | 修改摘要 | 修改时间 | 修改人），
提取数据行并保存为 Markdown 表格到 content/<doc_type>/_revision_record.md。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence

from lxml import etree

from docx_common import (
    AutomationError,
    discover_document_types,
    encode_markdown_cell,
    load_config,
    parse_xml_safe,
    read_docx_package,
)

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def qn(tag: str) -> str:
    return W_NS + tag


def _cell_text(cell) -> str:
    r"""提取单元格纯文本，保留段落与手动换行（``w:br``）的换行结构。

    模板里的修订摘要通常一段写一条改动（部分还带 ``w:br``），旧实现把所有
    ``w:t`` 直接拼接，段落边界全部丢失——提取出来的 Markdown 挤成一行，回填
    Word 后自然也只有一行。这里段落之间与 ``w:br``/``w:cr`` 处都插入 ``\n``，
    由 ``rows_to_markdown`` 编码成 ``<br>``（表格单元格不能跨行）。

    域指令（``w:instrText``）不是正文，不参与提取；空段落丢弃，避免把
    Word 里作间距用的空行变成连续 ``<br>``。
    """
    lines: List[str] = []
    for paragraph in cell.iter(qn("p")):
        parts: List[str] = []
        for node in paragraph.iter():
            if node.tag == qn("t"):
                parts.append(node.text or "")
            elif node.tag in (qn("br"), qn("cr")):
                parts.append("\n")
            elif node.tag == qn("tab"):
                parts.append("\t")
        for line in "".join(parts).split("\n"):
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return "\n".join(lines)


def find_revision_table(doc_root) -> Optional[object]:
    """在文档正文中查找修订记录表。

    修订记录表的特征：第二行包含"版本"、"修改摘要"（或"修改"）、"修改时间"、"修改人"。
    """
    body = doc_root.find(qn("body"))
    if body is None:
        return None

    for tbl in body.iter(qn("tbl")):
        rows = tbl.findall(qn("tr"))
        if len(rows) < 2:
            continue
        # 检查第二行（列名行）
        header_row = rows[1]
        header_texts = [_cell_text(cell) for cell in header_row.findall(qn("tc"))]
        combined = "".join(header_texts)
        if "版本" in combined and ("修订" in combined or "更新摘要" in combined):
            # 至少需要 版本、修改摘要/修改 两列
            col_count = len(header_texts)
            if col_count >= 2:
                return tbl
    return None


def extract_revision_rows(template_path: str) -> List[List[str]]:
    """从模板中提取修订记录表数据行。

    Returns:
        数据行列表，每行为 [版本, 修改摘要, 修改时间, 修改人]。
    """
    with read_docx_package(template_path) as package:
        items = package.read_all()

    doc_root = parse_xml_safe(
        items.get("word/document.xml", b""), "word/document.xml"
    )
    tbl = find_revision_table(doc_root)
    if tbl is None:
        return []

    rows = tbl.findall(qn("tr"))
    if len(rows) < 2:
        return []

    data_rows: List[List[str]] = []
    for row in rows[2:]:  # 跳过前两行（标题行+列名行）
        cells = row.findall(qn("tc"))
        row_texts = [_cell_text(cell) for cell in cells]
        if any(row_texts):  # 跳过空行
            data_rows.append(row_texts)

    return data_rows


def rows_to_markdown(rows: List[List[str]], doc_type: str) -> str:
    r"""将数据行转换为 Markdown 表格。

    格式：
        | 版本 | 修改摘要 | 修改时间 | 修改人 |
        |------|----------|----------|--------|
        | V1.0 | 内容     | 日期     | 作者   |

    单元格内容按构建侧 ``docx_common.split_markdown_table_row`` 的规则编码：
    先转义 ``\`` 再转义 ``|``，换行写成 ``<br>``（表格单元格不能跨行，构建侧
    会把 ``<br>`` 解回换行并生成 ``w:br``）。
    """
    lines = [
        "<!-- 修订记录（自动提取自模板，可手动编辑） -->",
        "",
        "# 修订记录 - {0}".format(doc_type),
        "",
        "| 版本 | 修改摘要 | 修改时间 | 修改人 |",
        "|------|----------|----------|--------|",
    ]
    for row in rows:
        # 补齐到 4 列
        while len(row) < 4:
            row.append("")
        escaped = [encode_markdown_cell(cell) for cell in row[:4]]
        lines.append("| {0} | {1} | {2} | {3} |".format(*escaped))
    lines.append("")
    return "\n".join(lines)


def save_to_content(rows: List[List[str]], doc_type: str, config: Dict) -> str:
    """将修订记录保存到内容目录下的 _revision_record.md。"""
    content_root = config["paths"]["content_root"]
    output_path = os.path.join(content_root, "_revision_record.md")
    markdown = rows_to_markdown(rows, doc_type)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return output_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="从模板 DOCX 提取修订记录表到 Markdown"
    )
    available = discover_document_types()
    if not available:
        print("[FAIL] 未在 config/ 目录发现任何 .yml 配置", file=sys.stderr)
        return 1
    choices = tuple(available) + ("all",)
    parser.add_argument("document", choices=choices, nargs="?", default="all")
    parser.add_argument(
        "--project",
        help="项目路径（使用项目 manifest 而非仓库配置，此时 document 参数无效）",
    )
    args = parser.parse_args(argv)

    if args.project:
        # 项目模式：从项目 manifest 加载配置
        try:
            from doc_tool.domain.manifest import ProjectManifest
            from doc_tool.domain.paths import ProjectPaths

            project_root = os.path.abspath(args.project)
            manifest = ProjectManifest.load(project_root)
            paths = ProjectPaths(project_root)
            from doc_tool.adapters.kernel import config_from_project

            config = config_from_project(manifest, paths)
            template_path = config["paths"]["template"]
            doc_type = config["documentType"]
        except Exception as exc:
            print("[FAIL] 加载项目配置失败: {0}".format(exc), file=sys.stderr)
            return 1
    else:
        targets = tuple(available) if args.document == "all" else (args.document,)
        for doc_type in targets:
            config = load_config(doc_type)
            template_path = config["paths"]["template"]
            try:
                rows = extract_revision_rows(template_path)
                if not rows:
                    print("[{0}] 模板中未找到修订记录表".format(doc_type))
                    continue
                output_path = save_to_content(rows, doc_type, config)
                print(
                    "[{0}] 已提取 {1} 条修订记录到: {2}".format(
                        doc_type, len(rows), output_path
                    )
                )
            except Exception as exc:
                print("[{0}] [FAIL] 提取失败: {1}".format(doc_type, exc), file=sys.stderr)
                return 1
        return 0

    # 单项目模式
    try:
        rows = extract_revision_rows(template_path)
        if not rows:
            print("[{0}] 模板中未找到修订记录表".format(doc_type))
            return 1
        output_path = save_to_content(rows, doc_type, config)
        print(
            "[{0}] 已提取 {1} 条修订记录到: {2}".format(
                doc_type, len(rows), output_path
            )
        )
    except Exception as exc:
        print("[FAIL] 提取失败: {0}".format(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())