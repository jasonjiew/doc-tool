# -*- coding: utf-8 -*-
"""统计文档 sectPr 数量/页面设置 + 空段落数量(原 vs 重建)"""
import os
import sys
import zipfile
from collections import Counter
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t

for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    sectprs = body.findall(qn("sectPr"))
    print(os.path.basename(p))
    print("  sectPr 总数: %d" % len(sectprs))
    for i, sp in enumerate(sectprs[:6]):
        pgSz = sp.find(qn("pgSz"))
        pgMar = sp.find(qn("pgMar"))
        orient = pgSz.get(qn("orient")) if pgSz is not None else None
        w = pgSz.get(qn("w")) if pgSz is not None else None
        h = pgSz.get(qn("h")) if pgSz is not None else None
        top = pgMar.get(qn("top")) if pgMar is not None else None
        print("    sect[%d] orient=%s size=%sx%s top=%s" % (i, orient, w, h, top))
    # 空段落统计
    n_para = 0
    n_empty = 0
    for p_el in body.iter(qn("p")):
        n_para += 1
        texts = [t.text or "" for t in p_el.iter(qn("t"))]
        if not any(texts):
            n_empty += 1
    print("  段落总数 %d, 空段落 %d" % (n_para, n_empty))
