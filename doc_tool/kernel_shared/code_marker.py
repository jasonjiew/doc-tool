# -*- coding: utf-8 -*-
"""代码容器标记与识别（V2.7 任务 2.2 / 设计 D1）。

正式稿的代码块输出为一个单格浅底表格。构建侧给容器内的第一段打上扩展
命名空间标记 ``dtc:code="1"``（其它 Office 扩展也这样标注，Word 会原样
保留未知命名空间），校验侧据此把「代码容器」与「用户表格」区分开：
两者在事件序列里都是表格事件，但代码容器只按代码文本比较，不能按普通
表格矩阵比较，否则设计文档里的代码示例会被当成表格误判。
"""

from __future__ import annotations

from typing import List, Optional

from lxml import etree


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
#: 代码容器标记命名空间（doc tool code）。
DTC_NS = "urn:doc-tool:code:v1"
CODE_MARKER = "{urn:doc-tool:code:v1}code"
#: 代码容器底色；供识别与生成两侧共用。
CODE_SHADING = "F8FAFC"


def qn(tag: str) -> str:
    return W_NS + tag


def _single_cell(table) -> Optional[etree._Element]:
    rows = table.findall(qn("tr"))
    if len(rows) != 1:
        return None
    cells = rows[0].findall(qn("tc"))
    if len(cells) != 1:
        return None
    return cells[0]


def mark_code_paragraph(paragraph) -> None:
    """给容器内段落打上代码标记（幂等）。"""
    ppr = paragraph.find(qn("pPr"))
    if ppr is None:
        ppr = etree.Element(qn("pPr"))
        paragraph.insert(0, ppr)
    if ppr.get(CODE_MARKER) is None:
        ppr.set(CODE_MARKER, "1")


def is_code_container(table) -> bool:
    """判断一个 w:tbl 是否为代码容器。"""
    if not isinstance(table.tag, str) or etree.QName(table).localname != "tbl":
        return False
    cell = _single_cell(table)
    if cell is None:
        return False
    cell_properties = cell.find(qn("tcPr"))
    if cell_properties is None:
        return False
    shading = cell_properties.find(qn("shd"))
    if shading is None or (shading.get(qn("fill")) or "").upper() != CODE_SHADING:
        return False
    for paragraph in cell.findall(qn("p")):
        ppr = paragraph.find(qn("pPr"))
        if ppr is not None and ppr.get(CODE_MARKER):
            return True
    return False


def code_container_lines(table) -> List[str]:
    """取回代码容器的文本行（保留空行；制表符与换行按 Word 语义还原）。"""
    cell = _single_cell(table)
    if cell is None:
        return []
    lines: List[str] = []
    for paragraph in cell.findall(qn("p")):
        parts: List[str] = []
        for node in paragraph.iter():
            if node.tag == qn("t"):
                parts.append(node.text or "")
            elif node.tag in (qn("br"), qn("cr")):
                parts.append("\n")
            elif node.tag == qn("tab"):
                parts.append("\t")
        text = "".join(parts)
        # 生成侧用单个空格占位空行；还原时按空行语义处理。
        if text == " ":
            text = ""
        lines.append(text.rstrip("\n"))
    while lines and lines[-1] == "":
        # 生成侧不会追加尾随空行（源码末尾换行不算代码行）。
        lines.pop()
    return lines