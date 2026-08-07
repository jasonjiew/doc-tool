# -*- coding: utf-8 -*-
"""统计表格 tblCellMar / tblInd / tblLayout 值分布"""
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
    mar = Counter()
    ind = Counter()
    layout = Counter()
    borders = Counter()
    n_tbl = 0
    for tbl in body.iter(qn("tbl")):
        n_tbl += 1
        tblPr = tbl.find(qn("tblPr"))
        if tblPr is None:
            continue
        cm = tblPr.find(qn("tblCellMar"))
        if cm is not None:
            vals = {}
            for tag in ("top", "left", "bottom", "right"):
                e = cm.find(qn(tag))
                if e is not None:
                    vals[tag] = e.get(qn("w"))
            mar[tuple(sorted(vals.items()))] += 1
        ti = tblPr.find(qn("tblInd"))
        if ti is not None:
            ind[(ti.get(qn("w")), ti.get(qn("type")))] += 1
        tl = tblPr.find(qn("tblLayout"))
        if tl is not None:
            layout[tl.get(qn("type"))] += 1
        tb = tblPr.find(qn("tblBorders"))
        if tb is not None:
            borders["present"] += 1
    print(os.path.basename(p))
    print("  表格数: %d" % n_tbl)
    print("  tblCellMar 分布:")
    for k, v in mar.most_common(5):
        print("    %s -> %d" % (k, v))
    print("  tblInd 分布(top5):")
    for k, v in ind.most_common(5):
        print("    %s -> %d" % (k, v))
    print("  tblLayout: %s" % dict(layout))
    print("  tblBorders 存在: %d" % borders["present"])
