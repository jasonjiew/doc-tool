# -*- coding: utf-8 -*-
"""诊断: 查看原文档表格边界处的分隔段落样式"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def show_boundaries(docx_path, limit=10):
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(W_NS + "body")
    children = list(body)
    shown = 0
    for i, child in enumerate(children):
        if child.tag == W_NS + "tbl" and i + 1 < len(children) and children[i + 1].tag == W_NS + "tbl":
            print("== 相邻表格对 #%d (index %d): ==" % (shown + 1, i))
            # 打印第一个表格前一个元素
            if i > 0:
                prev = children[i - 1]
                print("前一个元素:", etree.tostring(prev, pretty_print=True).decode()[:600])
            print("表格1 tblPr:", etree.tostring(child.find(W_NS + "tblPr"), pretty_print=True).decode()[:300])
            shown += 1
            if shown >= limit:
                break


def show_separator_after_tables(docx_path, limit=5):
    """查看原文档表格后紧跟的段落样式(非相邻对, 是正常 table->p 情况)"""
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(W_NS + "body")
    children = list(body)
    shown = 0
    for i, child in enumerate(children):
        if child.tag == W_NS + "tbl" and i + 1 < len(children):
            nxt = children[i + 1]
            if nxt.tag == W_NS + "p":
                txt = "".join(nxt.itertext()).strip()
                ppr = nxt.find(W_NS + "pPr")
                style = ""
                if ppr is not None:
                    ps = ppr.find(W_NS + "pStyle")
                    if ps is not None:
                        style = ps.get(W_NS + "val")
                print("table idx %d -> 后随段落 style=%s text=%r" % (i, style, txt[:20]))
                shown += 1
                if shown >= limit:
                    break


if __name__ == "__main__":
    p = os.path.abspath(sys.argv[1])
    show_boundaries(p)
    print("---- 正常分隔段落 ----")
    show_separator_after_tables(p)
