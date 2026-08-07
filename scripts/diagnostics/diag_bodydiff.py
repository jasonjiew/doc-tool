# -*- coding: utf-8 -*-
"""定位正文文本差异: 滑动窗口找丢失/多余块"""
import os
import sys
import zipfile
import re
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t


def in_tbl(p_el):
    anc = p_el.getparent()
    while anc is not None and anc.tag != qn("body"):
        if anc.tag == qn("tbl"):
            return True
        anc = anc.getparent()
    return False


def norm(s):
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043\uf0d8\uF0B2\uF0A0\uF0A8\uF0D9\uF0A1]", "", s)
    return s


def body_texts(p):
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    texts = []
    for el in body.iter(qn("p")):
        if in_tbl(el):
            continue
        t = "".join(x.text or "" for x in el.iter(qn("t")))
        if t.strip():
            texts.append(t)
    return texts


a = body_texts(os.path.abspath(sys.argv[1]))
b = body_texts(os.path.abspath(sys.argv[2]))
na = norm("".join(a))
nb = norm("".join(b))
print("原正文段落: %d, 字符: %d" % (len(a), len(na)))
print("重建正文段落: %d, 字符: %d" % (len(b), len(nb)))

# 原文档中不在重建的块
step = 60
lost = []
for i in range(0, len(na) - step, step):
    win = na[i:i + step]
    if win and win not in nb:
        lost.append(win)
# 重建中不在原文档的块
extra = []
for i in range(0, len(nb) - step, step):
    win = nb[i:i + step]
    if win and win not in na:
        extra.append(win)
print("丢失块数: %d, 示例:" % len(lost))
for x in lost[:10]:
    print("  LOST: %s..." % x[:60])
print("多余块数: %d, 示例:" % len(extra))
for x in extra[:10]:
    print("  EXTRA: %s..." % x[:60])
