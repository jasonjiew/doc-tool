# -*- coding: utf-8 -*-
"""细查 requirement 单元格段落 pPr 具体内容(OTHER 桶)"""
import os
import sys
import zipfile
from collections import Counter
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t


def ppr_key(pPr):
    if pPr is None:
        return "NO_PPR"
    parts = []
    for c in pPr:
        parts.append(etree.QName(c).localname)
    return "+".join(sorted(parts))


def in_tbl(p_el):
    anc = p_el.getparent()
    while anc is not None and anc.tag != qn("body"):
        if anc.tag == qn("tbl"):
            return True
        anc = anc.getparent()
    return False


for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    cnt = Counter()
    for p_el in body.iter(qn("p")):
        if not in_tbl(p_el):
            continue
        cnt[ppr_key(p_el.find(qn("pPr")))] += 1
    print(os.path.basename(p))
    for k, v in cnt.most_common(15):
        print("  %-40s -> %d" % (k, v))
