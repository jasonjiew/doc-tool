# -*- coding: utf-8 -*-
"""通过 Word COM 统计文档表格数与页数(不保存)"""
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
        n = doc.Tables.Count
        # 计算页数需强制重新分页
        pages = doc.ComputeStatistics(2)  # wdStatisticPages = 2
        print("{0}\n  COM Tables.Count = {1}  页数 = {2}".format(p, n, pages))
        doc.Close(False)
    finally:
        word.Quit()
