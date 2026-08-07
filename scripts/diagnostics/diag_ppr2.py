# -*- coding: utf-8 -*-
"""对比原/重建文档的段落 pPr 分布 + Normal 样式定义 + 单元格段落 pPr"""
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
    # Normal 样式
    sroot = etree.fromstring(styles_xml)
    for s in sroot.iter(qn("style")):
        if s.get(qn("default")) == "1" and s.get(qn("type")) == "paragraph":
            nm = s.find(qn("name"))
            print(os.path.basename(p), "默认段落样式:", nm.get(qn("val")) if nm is not None else "?",
                  "styleId:", s.get(qn("styleId")))
            pPr = s.find(qn("pPr"))
            if pPr is not None:
                print("  Normal pPr:", etree.tostring(pPr).decode()[:400])
            break
    # 正文段落 pPr 分布(表格外)
    body_ppr = Counter()
    cell_ppr = Counter()
    n_body = 0
    n_cell = 0
    for p_el in body.iter(qn("p")):
        is_tbl = in_tbl(p_el)
        pPr = p_el.find(qn("pPr"))
        if pPr is None:
            key = "NO_PPR"
        else:
            parts = []
            sp = pPr.find(qn("spacing"))
            if sp is not None:
                parts.append("spacing(b=%s,a=%s,line=%s,lineRule=%s)" % (
                    sp.get(qn("before")), sp.get(qn("after")),
                    sp.get(qn("line")), sp.get(qn("lineRule"))))
            ps = pPr.find(qn("pStyle"))
            if ps is not None:
                parts.append("pStyle=" + ps.get(qn("val")))
            ind = pPr.find(qn("ind"))
            if ind is not None:
                parts.append("ind(first=%s,left=%s)" % (ind.get(qn("firstLine")), ind.get(qn("left"))))
            jc = pPr.find(qn("jc"))
            if jc is not None:
                parts.append("jc=" + jc.get(qn("val")))
            if not parts:
                parts.append("OTHER")
            key = " | ".join(parts)
        if is_tbl:
            n_cell += 1
            cell_ppr[key] += 1
        else:
            n_body += 1
            body_ppr[key] += 1
    print("  正文段落 %d, pPr top5:" % n_body)
    for k, v in body_ppr.most_common(5):
        print("    %s -> %d" % (k, v))
    print("  单元格段落 %d, pPr top5:" % n_cell)
    for k, v in cell_ppr.most_common(5):
        print("    %s -> %d" % (k, v))
