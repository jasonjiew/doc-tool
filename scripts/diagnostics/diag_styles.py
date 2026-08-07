# -*- coding: utf-8 -*-
"""查询 docx styles.xml 中指定 styleId 的样式名称"""
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t

p = sys.argv[1]
want = set(sys.argv[2:]) if len(sys.argv) > 2 else None
with zipfile.ZipFile(p) as z:
    styles_xml = z.read("word/styles.xml")
sroot = etree.fromstring(styles_xml)
for s in sroot.iter(qn("style")):
    sid = s.get(qn("styleId"))
    nm = s.find(qn("name"))
    name = nm.get(qn("val")) if nm is not None else ""
    typ = s.get(qn("type"))
    if want is None or sid in want:
        print("%-8s %-20s %s" % (sid, typ, name))
