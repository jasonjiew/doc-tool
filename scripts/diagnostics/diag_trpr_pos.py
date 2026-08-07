# -*- coding: utf-8 -*-
"""统计 tblHeader/cantSplit 出现的行位置分布"""
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
    hdr_pos = Counter()
    cs_pos = Counter()
    hdr_first_only = 0
    cs_first_only = 0
    n_hdr_tbl = 0
    n_cs_tbl = 0
    for tbl in body.iter(qn("tbl")):
        rows = tbl.findall(qn("tr"))
        h_rows = []
        c_rows = []
        for i, tr in enumerate(rows):
            trPr = tr.find(qn("trPr"))
            if trPr is None:
                continue
            if trPr.find(qn("tblHeader")) is not None:
                h_rows.append(i)
            if trPr.find(qn("cantSplit")) is not None:
                c_rows.append(i)
        if h_rows:
            n_hdr_tbl += 1
            for i in h_rows:
                hdr_pos[i] += 1
            if h_rows == [0]:
                hdr_first_only += 1
        if c_rows:
            n_cs_tbl += 1
            for i in c_rows:
                cs_pos[i] += 1
            if c_rows == [0]:
                cs_first_only += 1
    print(os.path.basename(p))
    print("  tblHeader: %d 个表, 行位置分布 %s, 仅首行=%d" % (n_hdr_tbl, dict(hdr_pos), hdr_first_only))
    print("  cantSplit: %d 个表, 行位置分布 %s, 仅首行=%d" % (n_cs_tbl, dict(cs_pos), cs_first_only))
