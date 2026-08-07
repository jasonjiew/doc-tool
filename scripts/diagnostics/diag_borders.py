# -*- coding: utf-8 -*-
"""统计 tblBorders 值是否统一; tcMar/vAlign 分布"""
import os
import sys
import zipfile
from collections import Counter
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t


def border_key(e):
    return (e.get(qn("val")), e.get(qn("color")), e.get(qn("sz")), e.get(qn("space")))


for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    bd_set = Counter()
    tcmar = Counter()
    valign = Counter()
    n_tbl = 0
    n_tc = 0
    for tbl in body.iter(qn("tbl")):
        n_tbl += 1
        tblPr = tbl.find(qn("tblPr"))
        if tblPr is not None:
            tb = tblPr.find(qn("tblBorders"))
            if tb is not None:
                key = tuple(sorted(
                    (etree.QName(c).localname, border_key(c))
                    for c in tb
                ))
                bd_set[key] += 1
        for tc in tbl.iter(qn("tc")):
            n_tc += 1
            tcPr = tc.find(qn("tcPr"))
            if tcPr is None:
                continue
            tm = tcPr.find(qn("tcMar"))
            if tm is not None:
                vals = {}
                for tag in ("top", "left", "bottom", "right"):
                    e = tm.find(qn(tag))
                    if e is not None:
                        vals[tag] = e.get(qn("w"))
                tcmar[tuple(sorted(vals.items()))] += 1
            va = tcPr.find(qn("vAlign"))
            if va is not None:
                valign[va.get(qn("val"))] += 1
    print(os.path.basename(p))
    print("  表格数 %d, tblBorders 种类: %d" % (n_tbl, len(bd_set)))
    for k, v in bd_set.most_common(3):
        print("    %s -> %d" % (str(k)[:120], v))
    print("  tcMar 分布(每格):")
    for k, v in tcmar.most_common(4):
        print("    %s -> %d" % (k, v))
    print("  vAlign 分布: %s" % dict(valign))
