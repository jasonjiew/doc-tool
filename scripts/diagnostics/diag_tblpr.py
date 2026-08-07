# -*- coding: utf-8 -*-
"""统计表格 tblPr 子元素分布(判断 rebuild 缺失的格式属性)"""
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
        try:
            styles_xml = z.read("word/styles.xml")
        except KeyError:
            styles_xml = b""
    body = root.find(qn("body"))
    cnt = Counter()
    tblpr_elems = Counter()
    trpr_elems = Counter()
    for tbl in body.iter(qn("tbl")):
        tblPr = tbl.find(qn("tblPr"))
        if tblPr is not None:
            for c in tblPr:
                tblpr_elems[etree.QName(c).localname] += 1
        for tr in tbl.findall(qn("tr")):
            trPr = tr.find(qn("trPr"))
            if trPr is not None:
                for c in trPr:
                    trpr_elems[etree.QName(c).localname] += 1

    # 样式中的表格定义(42/43/143 等)
    sroot = etree.fromstring(styles_xml)
    style_tblpr = Counter()
    for s in sroot.iter(qn("style")):
        st = s.get(qn("type"))
        if st == "table":
            pPr = s.find(qn("tblPr"))
            if pPr is not None:
                for c in pPr:
                    style_tblpr[etree.QName(c).localname] += 1

    print(os.path.basename(p))
    print("  tblPr 子元素分布: %s" % dict(tblpr_elems))
    print("  trPr 子元素分布: %s" % dict(trpr_elems))
    print("  表格样式 tblPr 子元素分布: %s" % dict(style_tblpr))
