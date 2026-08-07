# -*- coding: utf-8 -*-
"""诊断: 统计 Word 文档中相邻 <w:tbl> 对的数量(两个表格之间无 <w:p>), 用于解释 Word COM Tables.Count 差异"""
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def count_tables_and_adjacent(docx_path):
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(W_NS + "body")
    total = 0
    adjacent_pairs = 0
    prev_was_tbl = False
    # 递归统计(含嵌套表格), 但相邻判断只针对 body 直接子元素
    for child in body:
        tag = child.tag
        if tag == W_NS + "tbl":
            total += 1
            if prev_was_tbl:
                adjacent_pairs += 1
            prev_was_tbl = True
        elif tag == W_NS + "p":
            prev_was_tbl = False
        elif tag == W_NS + "sdt":
            # 可能包含表格, 视为间隔
            prev_was_tbl = False
    return total, adjacent_pairs


if __name__ == "__main__":
    for p in sys.argv[1:]:
        t, a = count_tables_and_adjacent(p)
        print("{0}\n  tables(直接子级)= {1}  相邻表格对 = {2}".format(p, t, a))
