# -*- coding: utf-8 -*-
"""统计表格单元格内段落样式分布"""
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
    cnt = Counter()
    no_style = 0
    for tbl in body.iter(qn("tbl")):
        for tc in tbl.findall(qn("tr") + "/" + qn("tc")):
            for pp in tc.findall(qn("p")):
                pPr = pp.find(qn("pPr"))
                st = None
                if pPr is not None:
                    ps = pPr.find(qn("pStyle"))
                    if ps is not None:
                        st = ps.get(qn("val"))
                if st:
                    cnt[st] += 1
                else:
                    no_style += 1
    print(os.path.basename(p))
    print("  单元格段落: 无样式=%d, 有样式=%s" % (no_style, dict(sorted(cnt.items()))))
