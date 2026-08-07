# -*- coding: utf-8 -*-
"""输出原文档 tblPr/tcPr 典型样本, 用于精确重建"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
qn = lambda t: W_NS + t


def fmt(el, indent=0):
    return etree.tostring(el, pretty_print=True).decode()


for p in sys.argv[1:]:
    p = os.path.abspath(p)
    with zipfile.ZipFile(p) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(qn("body"))
    tbls = list(body.iter(qn("tbl")))
    print("=" * 70)
    print(os.path.basename(p), "表格数:", len(tbls))
    # 样本: 第1个, 第10个, 中位数, 最后一个
    idxs = sorted(set([0, 9, len(tbls) // 2, len(tbls) - 1]))
    for i in idxs:
        tbl = tbls[i]
        print("-" * 60)
        print("## tbl[%d] (总%d行)" % (i, len(tbl.findall(qn("tr")))))
        tblPr = tbl.find(qn("tblPr"))
        if tblPr is not None:
            print("tblPr:\n" + fmt(tblPr))
        # 第一行 trPr/tcPr 样本
        trs = tbl.findall(qn("tr"))
        if trs:
            tr = trs[0]
            trPr = tr.find(qn("trPr"))
            if trPr is not None:
                print("tr[0] trPr:\n" + fmt(trPr))
            for j, tc in enumerate(tr.findall(qn("tc"))[:2]):
                tcPr = tc.find(qn("tcPr"))
                if tcPr is not None:
                    print("tr[0] tc[%d] tcPr:\n" % j + fmt(tcPr))
