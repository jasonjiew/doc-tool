# -*- coding: utf-8 -*-
"""通过 Word COM 对比文档表格总高度 / 总行数(不保存)"""
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
        total_h = 0
        total_rows = 0
        for i in range(1, doc.Tables.Count + 1):
            try:
                tbl = doc.Tables(i)
                total_rows += tbl.Rows.Count
                total_h += tbl.Height  # 表格整体高度(含行)
            except Exception:
                pass
        pages = doc.ComputeStatistics(2)
        print("{0}\n  COM Tables=%d 总行数=%d 总高度=%.0f(点) 页数=%d" % (
            doc.Tables.Count, total_rows, total_h, pages))
        doc.Close(False)
    finally:
        word.Quit()
