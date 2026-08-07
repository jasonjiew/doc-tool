# -*- coding: utf-8 -*-
"""统计原文档表格 tblW type/w 分布, 对比 gridCol 总和"""
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
tbls = [el for el in body if el.tag == qn("tbl")]

auto_ws = []
dxa_ws = []
pct_ws = []
for el in tbls:
    tblPr = el.find(qn("tblPr"))
    tw = tblPr.find(qn("tblW")) if tblPr is not None else None
    ttype = tw.get(qn("type")) if tw is not None else None
    w = 0
    if tw is not None:
        try:
            w = int(tw.get(qn("w")) or 0)
        except ValueError:
            w = -1
    if ttype == "auto":
        auto_ws.append(w)
    elif ttype == "pct":
        pct_ws.append(w)
    else:
        dxa_ws.append((ttype, w))

print("auto 表格数: %d, w 分布: min=%s max=%s, 非零数=%d" % (len(auto_ws), min(auto_ws), max(auto_ws), sum(1 for x in auto_ws if x)))
print("pct 表格数: %d, w 值: %s" % (len(pct_ws), sorted(set(pct_ws))[:10]))
print("其它(dxa) 表格数: %d, w min=%d max=%d 平均=%d" % (len(dxa_ws), min(w for _, w in dxa_ws), max(w for _, w in dxa_ws), sum(w for _, w in dxa_ws) // max(len(dxa_ws), 1)))
print("  type 种类:", sorted(set(t for t, _ in dxa_ws)))
