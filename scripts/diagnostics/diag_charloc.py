# -*- coding: utf-8 -*-
"""定位原/重建文本差异: 按段落位置统计字符(表格内/外)"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t


def in_tbl(p_el):
    anc = p_el.getparent()
    while anc is not None and anc.tag != qn("body"):
        if anc.tag == qn("tbl"):
            return True
        anc = anc.getparent()
    return False


for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    body_chars = 0
    tbl_chars = 0
    n_body = 0
    n_tbl = 0
    for p_el in body.iter(qn("p")):
        s = sum(len(t.text or "") for t in p_el.iter(qn("t")))
        if in_tbl(p_el):
            tbl_chars += s
            n_tbl += 1
        else:
            body_chars += s
            n_body += 1
    # 表格直接文本(含 cell 内)
    n_tbls = len(body.findall(qn("tbl")))
    print(os.path.basename(p))
    print("  表外段落: %d 段, %d 字符; 表内段落: %d 段, %d 字符; 表格数 %d" % (
        n_body, body_chars, n_tbl, tbl_chars, n_tbls))
