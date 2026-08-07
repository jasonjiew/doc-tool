# -*- coding: utf-8 -*-
"""统计表格行 trHeight 与单元格段落 spacing 分布"""
import os
import re
import sys
import zipfile
from collections import Counter
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t

p = os.path.abspath(sys.argv[1])
with zipfile.ZipFile(p) as z:
    root = etree.fromstring(z.read("word/document.xml"))

body = root.find(qn("body"))
trh = Counter()
trh_exact = Counter()
cell_spacing = Counter()
cell_rpr_sz = Counter()
n_tr = 0
n_cell_p = 0
for tbl in body.iter(qn("tbl")):
    for tr in tbl.findall(qn("tr")):
        n_tr += 1
        trPr = tr.find(qn("trPr"))
        if trPr is not None:
            h = trPr.find(qn("trHeight"))
            if h is not None:
                trh[(h.get(qn("val")), h.get(qn("hRule")))] += 1
        for tc in tr.findall(qn("tc")):
            for pp in tc.findall(qn("p")):
                n_cell_p += 1
                pPr = pp.find(qn("pPr"))
                if pPr is not None:
                    sp = pPr.find(qn("spacing"))
                    if sp is not None:
                        attrs = {k.split("}")[-1]: v for k, v in sp.attrib.items()}
                        key = tuple(sorted(attrs.items()))
                        cell_spacing[key] += 1
                    rPr = pPr.find(qn("rPr"))
                    if rPr is not None:
                        sz = rPr.find(qn("sz"))
                        if sz is not None:
                            cell_rpr_sz[sz.get(qn("val"))] += 1

print("表格行总数: %d" % n_tr)
print("trHeight 分布(top10):")
for k, v in trh.most_common(10):
    print("   %s -> %d" % (k, v))
print("单元格段落: %d" % n_cell_p)
print("单元格段落 spacing 分布(top8):")
for k, v in cell_spacing.most_common(8):
    print("   %s -> %d" % (k, v))
print("单元格段落 rPr sz 分布:", dict(cell_rpr_sz))
