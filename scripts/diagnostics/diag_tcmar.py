# -*- coding: utf-8 -*-
"""统计每个表格 tcMar/vAlign 的分布(按表), 判断是否可用众数近似"""
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
    n_tbl = 0
    n_mixed_tcmar = 0
    n_mixed_va = 0
    tcmar_modes = Counter()
    va_modes = Counter()
    for tbl in body.iter(qn("tbl")):
        n_tbl += 1
        tm = Counter()
        va = Counter()
        for tc in tbl.iter(qn("tc")):
            tcPr = tc.find(qn("tcPr"))
            if tcPr is None:
                continue
            t = tcPr.find(qn("tcMar"))
            if t is not None:
                vals = tuple((tag, (t.find(qn(tag)).get(qn("w")) if t.find(qn(tag)) is not None else None)) for tag in ("top", "left", "bottom", "right"))
                tm[vals] += 1
            v = tcPr.find(qn("vAlign"))
            if v is not None:
                va[v.get(qn("val"))] += 1
        if len(tm) > 1:
            n_mixed_tcmar += 1
        if len(va) > 1:
            n_mixed_va += 1
        if tm:
            tcmar_modes[tm.most_common(1)[0][0]] += 1
        if va:
            va_modes[va.most_common(1)[0][0]] += 1
    print(os.path.basename(p))
    print("  表格 %d, 含tcMar表格的众数分布(多值表%d):" % (n_tbl, n_mixed_tcmar))
    for k, v in tcmar_modes.most_common(6):
        print("    %s -> %d" % (k, v))
    print("  含vAlign表格的众数分布(多值表%d): %s" % (n_mixed_va, dict(va_modes)))
