# -*- coding: utf-8 -*-
"""输出样式 pPr 核心属性(去命名空间噪声) + 文档图片尺寸对比"""
import os
import sys
import zipfile
from lxml import etree
from collections import Counter

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
qn = lambda t: W_NS + t


def ppr_brief(pPr):
    parts = []
    for c in pPr:
        ln = etree.QName(c).localname
        if ln == "spacing":
            parts.append("spacing(b=%s,a=%s,line=%s,lr=%s,bl=%s)" % (
                c.get(qn("before")), c.get(qn("after")), c.get(qn("line")),
                c.get(qn("lineRule")), c.get(qn("beforeLines"))))
        elif ln == "ind":
            parts.append("ind(first=%s,left=%s,hanging=%s)" % (
                c.get(qn("firstLine")), c.get(qn("left")), c.get(qn("hanging"))))
        elif ln == "pStyle":
            parts.append("pStyle=" + c.get(qn("val")))
        elif ln == "jc":
            parts.append("jc=" + c.get(qn("val")))
        elif ln == "keepNext" or ln == "keepLines":
            parts.append(ln)
        elif ln == "numPr":
            parts.append("numPr")
        elif ln == "rPr":
            parts.append("rPr")
        elif ln == "widowControl":
            parts.append("widowControl=" + c.get(qn("val")))
        else:
            parts.append(ln)
    return " | ".join(parts)


for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
        styles_xml = z.read("word/styles.xml")
    sroot = etree.fromstring(styles_xml)
    print("=" * 70)
    print(os.path.basename(p))
    print("-- 样式定义:")
    for s in sroot.iter(qn("style")):
        sid = s.get(qn("styleId"))
        if sid not in {"1", "3", "7", "141"}:
            continue
        nm = s.find(qn("name"))
        pPr = s.find(qn("pPr"))
        print("  %s(%s): %s" % (sid, nm.get(qn("val")) if nm is not None else "?", ppr_brief(pPr) if pPr is not None else "-"))
    # 图片尺寸对比(extent cx/cy)
    print("-- 图片尺寸(emu, cx x cy):")
    sizes = Counter()
    for drawing in root.iter(qn("drawing")):
        ext = drawing.find(".//" + A_NS + "ext")
        if ext is not None:
            sizes[(ext.get("cx"), ext.get("cy"))] += 1
    for k, v in sizes.most_common(10):
        print("  %s x %s -> %d" % (k[0], k[1], v))
