# -*- coding: utf-8 -*-
"""统计每个表格的行高众数与行内 trHeight 一致性"""
import os
import sys
import zipfile
from collections import Counter
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t

p = os.path.abspath(sys.argv[1])
with zipfile.ZipFile(p) as z:
    root = etree.fromstring(z.read("word/document.xml"))
body = root.find(qn("body"))

tbls = [el for el in body if el.tag == qn("tbl")]
n_uniform = 0  # 表格内所有行 trHeight 一致(或无)
n_uniform485 = 0
stats = []
for ti, tbl in enumerate(tbls):
    trs = tbl.findall(qn("tr"))
    hs = []
    for tr in trs:
        h = None
        trPr = tr.find(qn("trPr"))
        if trPr is not None:
            th = trPr.find(qn("trHeight"))
            if th is not None:
                h = th.get(qn("val"))
        hs.append(h)
    cnt = Counter(hs)
    mode, mode_n = cnt.most_common(1)[0]
    uniq = len(cnt)
    stats.append((ti, len(trs), uniq, mode, mode_n, mode_n / max(len(trs), 1)))
    if uniq == 1:
        n_uniform += 1
        if mode == "485":
            n_uniform485 += 1

print("表格数: %d" % len(tbls))
print("表格内行高完全一致(或全无): %d, 其中全为485: %d" % (n_uniform, n_uniform485))
print("表格内行高<=2种: %d" % sum(1 for s in stats if s[2] <= 2))
print("众数占比>=80%%的表格: %d" % sum(1 for s in stats if s[5] >= 0.8))
# 样本
print("前 20 个表格 (idx, 行数, 种类数, 众数, 众数行数, 占比):")
for s in stats[:20]:
    print("  %s" % (s,))
