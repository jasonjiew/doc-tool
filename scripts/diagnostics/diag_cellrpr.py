# -*- coding: utf-8 -*-
"""对比原/重建: 正文总字符数 + 单元格 rPr 字体大小分布 + Normal 字体"""
import os
import sys
import zipfile
from collections import Counter
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
        styles_xml = z.read("word/styles.xml")
    body = root.find(qn("body"))
    # 总字符数
    n_chars = 0
    for t in root.iter(qn("t")):
        n_chars += len(t.text or "")
    # 单元格 rPr sz 分布
    sz_cnt = Counter()
    n_cellp = 0
    for p_el in body.iter(qn("p")):
        if not in_tbl(p_el):
            continue
        n_cellp += 1
        for r in p_el.findall(qn("r")):
            rPr = r.find(qn("rPr"))
            if rPr is None:
                continue
            sz = rPr.find(qn("sz"))
            if sz is not None:
                sz_cnt[sz.get(qn("val"))] += 1
    # Normal 字体
    sroot = etree.fromstring(styles_xml)
    normal_rpr = None
    for s in sroot.iter(qn("style")):
        if s.get(qn("type")) == "paragraph" and s.get(qn("default")) == "1":
            rPr = s.find(qn("rPr"))
            if rPr is not None:
                normal_rpr = etree.tostring(rPr).decode()
            break
    print(os.path.basename(p))
    print("  总字符数: %d, 单元格段落: %d" % (n_chars, n_cellp))
    print("  单元格 rPr sz 分布(top8): %s" % dict(sz_cnt.most_common(8)))
    print("  Normal rPr:", (normal_rpr or "")[:200].replace("\n", " "))
