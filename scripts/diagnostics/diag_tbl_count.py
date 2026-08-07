# -*- coding: utf-8 -*-
"""统计: body 直接子级表格总数 / 第一个H1前的表格数 / 嵌套表格数"""
import os
import sys
import zipfile
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

# heading map
hmap = {}
sroot = etree.fromstring(styles_xml)
import re
for s in sroot.iter(qn("style")):
    nm = s.find(qn("name"))
    if nm is None:
        continue
    m = re.match(r"(?i)heading\s*(\d+)", nm.get(qn("val")) or "")
    if m:
        hmap[s.get(qn("styleId"))] = int(m.group(1))

body = root.find(qn("body"))
children = list(body)
total_direct = sum(1 for c in children if c.tag == qn("tbl"))
nested = 0
for c in children:
    if c.tag == qn("tbl"):
        nested += len(c.findall(".//" + qn("tbl")))

start_idx = None
for i, el in enumerate(children):
    if el.tag != qn("p"):
        continue
    pPr = el.find(qn("pPr"))
    if pPr is None:
        continue
    ps = pPr.find(qn("pStyle"))
    if ps is None:
        continue
    if hmap.get(ps.get(qn("val"))) == 1:
        start_idx = i
        break

tbl_before = sum(1 for c in children[:start_idx] if c.tag == qn("tbl"))
tbl_after = sum(1 for c in children[start_idx:] if c.tag == qn("tbl"))
print("body 直接子级表格: %d (H1前: %d, H1后: %d), 嵌套表格(额外): %d" % (total_direct, tbl_before, tbl_after, nested))
print("第一个 H1 位置 index=%s" % start_idx)
