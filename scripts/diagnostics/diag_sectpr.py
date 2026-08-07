# -*- coding: utf-8 -*-
"""查看 body 中所有直接子级 sectPr 的位置与页面设置, 以及中间 sectPr 前后内容"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t

p = os.path.abspath(sys.argv[1])
with zipfile.ZipFile(p) as z:
    root = etree.fromstring(z.read("word/document.xml"))

body = root.find(qn("body"))
children = list(body)
for i, c in enumerate(children):
    if c.tag == qn("sectPr"):
        pgSz = c.find(qn("pgSz"))
        pgMar = c.find(qn("pgMar"))
        def g(el, k):
            return el.get(qn(k)) if el is not None else None
        print("sectPr at body index %d: pgSz(w=%s,h=%s,orient=%s) pgMar(t=%s,b=%s,l=%s,r=%s)" % (
            i,
            g(pgSz, "w"), g(pgSz, "h"), g(pgSz, "orient"),
            g(pgMar, "top"), g(pgMar, "bottom"), g(pgMar, "left"), g(pgMar, "right")))
        # 前面最近的内容类型
        if i > 0:
            prev = children[i - 1]
            print("  前一个元素: %s" % etree.QName(prev).localname)
        if i + 1 < len(children):
            nxt = children[i + 1]
            print("  后一个元素: %s" % etree.QName(nxt).localname)
