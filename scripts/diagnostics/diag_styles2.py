# -*- coding: utf-8 -*-
"""输出原文档常用段落样式的 pPr 定义(styleId -> 名称 + pPr)"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t

for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        styles_xml = z.read("word/styles.xml")
    sroot = etree.fromstring(styles_xml)
    print("=" * 70)
    print(os.path.basename(p))
    want = {"1", "2", "3", "4", "5", "6", "7", "8", "21", "141", "142"}
    for s in sroot.iter(qn("style")):
        sid = s.get(qn("styleId"))
        if sid not in want:
            continue
        nm = s.find(qn("name"))
        print("-" * 50)
        print("styleId=%s name=%s type=%s" % (sid, nm.get(qn("val")) if nm is not None else "?", s.get(qn("type"))))
        pPr = s.find(qn("pPr"))
        if pPr is not None:
            print(etree.tostring(pPr).decode()[:500])
