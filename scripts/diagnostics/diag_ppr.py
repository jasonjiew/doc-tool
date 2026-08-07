# -*- coding: utf-8 -*-
"""统计正文段落(非标题/非表格/非空)的 pPr 直接格式分布"""
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
    try:
        styles_xml = z.read("word/styles.xml")
    except KeyError:
        styles_xml = b""

hmap = {}
sroot = etree.fromstring(styles_xml)
for s in sroot.iter(qn("style")):
    nm = s.find(qn("name"))
    if nm is None:
        continue
    m = re.match(r"(?i)heading\s*(\d+)", nm.get(qn("val")) or "")
    if m:
        hmap[s.get(qn("styleId"))] = int(m.group(1))

body = root.find(qn("body"))
spacing_cnt = Counter()
ind_cnt = Counter()
jc_cnt = Counter()
has_rpr = 0
total = 0
for el in body:
    if el.tag != qn("p"):
        continue
    txt = "".join(t.text or "" for t in el.iter(qn("t"))).strip()
    if not txt:
        continue
    pPr = el.find(qn("pPr"))
    st = None
    if pPr is not None:
        ps = pPr.find(qn("pStyle"))
        if ps is not None:
            st = ps.get(qn("val"))
    if st and hmap.get(st):
        continue
    total += 1
    if pPr is None:
        continue
    sp = pPr.find(qn("spacing"))
    if sp is not None:
        spacing_cnt[tuple(sorted(sp.attrib.items()))] += 1
    ind = pPr.find(qn("ind"))
    if ind is not None:
        ind_cnt[tuple(sorted(ind.attrib.items()))] += 1
    jc = pPr.find(qn("jc"))
    if jc is not None:
        jc_cnt[jc.get(qn("val"))] += 1

print("正文段落总数: %d" % total)
print("spacing 分布(top10):")
for k, v in spacing_cnt.most_common(10):
    print("   %s -> %d" % (k, v))
print("ind 分布(top10):")
for k, v in ind_cnt.most_common(10):
    print("   %s -> %d" % (k, v))
print("jc 分布:")
for k, v in jc_cnt.most_common():
    print("   %s -> %d" % (k, v))
