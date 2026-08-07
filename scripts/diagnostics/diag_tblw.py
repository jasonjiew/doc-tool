# -*- coding: utf-8 -*-
"""对比原文档与重建文档: 每个表格的 tblW 与 gridCol 总和"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t


def tbl_stats(path, limit=400):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    tbls = [el for el in body if el.tag == qn("tbl")]
    n_tblw = 0
    n_tblw_auto = 0
    n_tblw_dxa = 0
    n_notblw = 0
    grid_sum = 0
    tblw_sum = 0
    wide = []
    for i, el in enumerate(tbls):
        tblPr = el.find(qn("tblPr"))
        tw = None
        ttype = None
        if tblPr is not None:
            tw = tblPr.find(qn("tblW"))
            if tw is not None:
                ttype = tw.get(qn("type"))
                try:
                    w = int(tw.get(qn("w")) or 0)
                except ValueError:
                    w = 0
                tblw_sum += w
                if ttype == "auto":
                    n_tblw_auto += 1
                else:
                    n_tblw_dxa += 1
            else:
                n_notblw += 1
        if tw is not None:
            n_tblw += 1
        grid = el.find(qn("tblGrid"))
        gs = 0
        if grid is not None:
            gs = sum(int(gc.get(qn("w")) or 0) for gc in grid.findall(qn("gridCol")))
        grid_sum += gs
        if gs > 10000:  # 超过页面宽(11906-2268=9638 twips 可排版宽度)
            wide.append((i, gs, ttype))
    print("%s" % os.path.basename(path))
    print("  表格数: %d" % len(tbls))
    print("  tblW: 有=%d (auto=%d, dxa/其它=%d), 无=%d" % (n_tblw, n_tblw_auto, n_tblw_dxa, n_notblw))
    print("  tblW 总和: %d, gridCol 总和: %d" % (tblw_sum, grid_sum))
    print("  gridCol > 10000(超过排版宽度) 的表格数: %d" % len(wide))
    for i, gs, ttype in wide[:15]:
        print("    tbl[%d] grid=%d type=%s" % (i, gs, ttype))


for p in sys.argv[1:]:
    tbl_stats(os.path.abspath(p))
    print()
