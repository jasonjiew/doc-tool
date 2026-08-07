# -*- coding: utf-8 -*-
"""对比原文档与重建文档: 图片extent总量 / 表格宽度 / 段落数 / 空段落数"""
import os
import sys
import zipfile
from lxml import etree

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP_NS = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
qn = lambda t: W_NS + t


def stats(path):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
        try:
            styles_xml = z.read("word/styles.xml")
        except KeyError:
            styles_xml = b""

    import re
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
    n_p = 0
    n_empty_p = 0
    n_body_p = 0
    img_cx = 0
    img_cy = 0
    n_img = 0
    tbl_w = 0
    n_tbl = 0
    # 图片尺寸
    for ext in root.iter(WP_NS + "extent"):
        cx = int(ext.get("cx") or 0)
        cy = int(ext.get("cy") or 0)
        img_cx += cx
        img_cy += cy
        n_img += 1
    for el in body:
        tag = etree.QName(el).localname
        if tag == "p":
            n_p += 1
            txt = "".join(t.text or "" for t in el.iter(qn("t"))).strip()
            pPr = el.find(qn("pPr"))
            st = None
            if pPr is not None:
                ps = pPr.find(qn("pStyle"))
                if ps is not None:
                    st = ps.get(qn("val"))
            if not txt:
                n_empty_p += 1
            elif hmap.get(st) is None:
                n_body_p += 1
        elif tag == "tbl":
            n_tbl += 1
            tblPr = el.find(qn("tblPr"))
            if tblPr is not None:
                tw = tblPr.find(qn("tblW"))
                if tw is not None:
                    try:
                        tbl_w += int(tw.get(qn("w")) or 0)
                    except ValueError:
                        pass
    print("%s" % os.path.basename(path))
    print("  段落: %d (空: %d, 正文: %d)" % (n_p, n_empty_p, n_body_p))
    print("  图片: %d, extent 总和 cx=%d cm=%.1f, cy=%d cm=%.1f" % (n_img, img_cx, img_cx / 360000, img_cy, img_cy / 360000))
    print("  表格: %d, tblW 总和: %d" % (n_tbl, tbl_w))


for p in sys.argv[1:]:
    stats(os.path.abspath(p))
    print()
