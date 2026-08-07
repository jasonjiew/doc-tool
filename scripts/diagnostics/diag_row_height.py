# -*- coding: utf-8 -*-
"""通过 Word COM 累加所有表格行高度(点), 对比原文档与重建文档"""
import os
import sys
import win32com.client

for p in sys.argv[1:]:
    p = os.path.abspath(p)
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(p, ReadOnly=True, AddToRecentFiles=False,
                                  Visible=False, OpenAndRepair=False,
                                  NoEncodingDialog=True)
        total_h = 0.0
        n = 0
        h0 = 0.0  # 高度<0.01 的行数(自适应)
        for i in range(1, doc.Tables.Count + 1):
            try:
                rows = doc.Tables(i).Rows
                for j in range(1, rows.Count + 1):
                    h = rows(j).Height
                    if h and h > 0.01:
                        total_h += h
                    else:
                        h0 += 1
                    n += 1
            except Exception:
                pass
        pages = doc.ComputeStatistics(2)
        print("{0}\n  行数=%d 固定高合计=%.1f(点) 自适应行=%d 页数=%d" % (n, total_h, h0, pages))
        doc.Close(False)
    finally:
        word.Quit()
