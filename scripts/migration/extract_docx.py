# -*- coding: utf-8 -*-
"""
Phase 3/4/5: 拆分 Word -> Markdown + 图片 + 复杂表格
用法:
    python scripts/migration/extract_docx.py requirement
    python scripts/migration/extract_docx.py design

输出:
    content/<type>/*.md          正文 Markdown(按一级章节拆分)
    assets/<type>/images/*       图片文件
    assets/<type>/tables/*.xml   复杂表格原始 XML(占位标记引用)
    assets/<type>/image-map.yml  图片映射
    assets/<type>/table-map.yml  表格映射
    content/<type>/_meta.yml     章节元数据
"""
import os
import re
import shutil
import sys
import zipfile

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.dirname(BASE)

DOCS = {
    "requirement": {
        "src": "KF-2090-1-001 康尚健康云软件需求说明书(3.8).docx",
        "type": "requirement",
    },
    "design": {
        "src": "KF-2090-1-006 康尚健康云系统详细设计说明书(2.5).docx",
        "type": "design",
    },
}

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP_NS = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def qn(tag):
    return W_NS + tag


def para_style(p):
    pPr = p.find(qn("pPr"))
    if pPr is None:
        return None
    pStyle = pPr.find(qn("pStyle"))
    if pStyle is None:
        return None
    return pStyle.get(qn("val"))


def para_text(p):
    """段落纯文本(含 tab)"""
    parts = []
    for node in p.iter():
        tag = etree.QName(node).localname
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
        elif tag == "cr":
            parts.append("\n")
    return "".join(parts).strip()


def para_has_image(p):
    return p.find(".//" + qn("drawing")) is not None or p.find(".//" + qn("pict")) is not None


def para_image_info(p):
    """返回该段落的图片信息列表: [{rid, cx(emu), cy(emu), name}]"""
    infos = []
    for blip in p.iter(A_NS + "blip"):
        rid = blip.get(R_NS + "embed") or blip.get(R_NS + "link")
        if not rid:
            continue
        info = {"rid": rid, "cx": None, "cy": None, "name": None}
        # 找最近的 extent (wp:extent)
        ext = blip.getparent().getparent().find(WP_NS + "extent")
        if ext is None:
            # 往上找
            node = blip
            while node is not None:
                e = node.find(WP_NS + "extent")
                if e is not None:
                    ext = e
                    break
                node = node.getparent()
        if ext is not None:
            info["cx"] = int(ext.get("cx"))
            info["cy"] = int(ext.get("cy"))
        infos.append(info)
    return infos


def table_is_simple(tbl):
    """简单表格: 无合并、无图片、无嵌套、列数<=8"""
    if tbl.find(".//" + qn("gridSpan")) is not None:
        return False
    if tbl.find(".//" + qn("vMerge")) is not None:
        return False
    if tbl.find(".//" + qn("drawing")) is not None or tbl.find(".//" + qn("pict")) is not None:
        return False
    if tbl.find(".//" + qn("tbl")) is not None:
        return False
    return True


def table_to_md(tbl):
    """简单表格 -> Markdown 表格"""
    rows = []
    for tr in tbl.findall(qn("tr")):
        cells = []
        for tc in tr.findall(qn("tc")):
            # 单元格文本(可能含多段)
            cell_txt = []
            for p in tc.findall(qn("p")):
                txt = para_text(p)
                if txt:
                    cell_txt.append(txt)
            cells.append(" ".join(cell_txt))
        rows.append(cells)
    if not rows:
        return None
    ncols = max(len(r) for r in rows)
    # 补全行
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    # 转义 | 和换行
    def esc(s):
        return s.replace("|", "\\|").replace("\n", "<br>")
    lines = []
    header = rows[0]
    lines.append("| " + " | ".join(esc(c) for c in header) + " |")
    lines.append("| " + " | ".join("---" for _ in range(ncols)) + " |")
    for r in rows[1:]:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)


def cell_in_table_has_image(tbl):
    return tbl.find(".//" + qn("drawing")) is not None or tbl.find(".//" + qn("pict")) is not None


def para_fmt_marker(el):
    """提取正文段落显式格式(行距/段前段后/缩进), 返回压缩标记 <!-- P:key=val;... --> 或 None"""
    pPr = el.find(qn("pPr"))
    if pPr is None:
        return None
    parts = []
    sp = pPr.find(qn("spacing"))
    if sp is not None:
        for attr, key in ((qn("line"), "line"), (qn("lineRule"), "lr"),
                          (qn("before"), "b"), (qn("after"), "a")):
            v = sp.get(attr)
            if v is not None:
                parts.append("{0}={1}".format(key, v))
    ind = pPr.find(qn("ind"))
    if ind is not None:
        for attr, key in ((qn("firstLine"), "first"), (qn("left"), "left"),
                          (qn("hanging"), "hang"), (qn("right"), "right")):
            v = ind.get(attr)
            if v is not None and v not in ("0",):
                parts.append("{0}={1}".format(key, v))
    if not parts:
        return None
    return "<!-- P:" + ";".join(parts) + " -->"


def table_trh_mode(el):
    """返回表格行 trHeight 值的众数(None 表示该表格行无最小行高)"""
    from collections import Counter
    cnt = Counter()
    for tr in el.findall(qn("tr")):
        trPr = tr.find(qn("trPr"))
        if trPr is None:
            continue
        th = trPr.find(qn("trHeight"))
        if th is not None:
            cnt[th.get(qn("val"))] += 1
    if not cnt:
        return None
    return cnt.most_common(1)[0][0]


def table_meta(el):
    """返回简单表格的 (样式, 列宽列表, tblW type, tblW w)"""
    tblPr = el.find(qn("tblPr"))
    style = None
    tw_type = None
    tw_w = 0
    if tblPr is not None:
        s = tblPr.find(qn("tblStyle"))
        if s is not None:
            style = s.get(qn("val"))
        tw = tblPr.find(qn("tblW"))
        if tw is not None:
            tw_type = tw.get(qn("type"))
            try:
                tw_w = int(tw.get(qn("w")) or 0)
            except (ValueError, TypeError):
                tw_w = 0
    widths = []
    grid = el.find(qn("tblGrid"))
    if grid is not None:
        for gc in grid.findall(qn("gridCol")):
            v = gc.get(qn("w"))
            widths.append(int(v) if v else 0)
    return style, widths, tw_type or "dxa", tw_w


def _cm_tuple(cm):
    """tblCellMar/tcMar -> (top,left,bottom,right) w 值元组或 None"""
    vals = []
    for tag in ("top", "left", "bottom", "right"):
        e = cm.find(qn(tag))
        if e is None or e.get(qn("w")) is None:
            return None
        vals.append(e.get(qn("w")))
    return tuple(vals)


def table_fmt_meta(el):
    """提取简单表格的完整格式元数据(表格级/行级/单元格级), 供 TBL 注释与重建:
    {
      ind: (w, type)         tblInd
      lay: type               tblLayout
      cm:  (t,l,b,r)          tblCellMar
      bd:  "val:color:sz:space"  tblBorders(六边一致时单值; 否则 None)
      hdr: [行号]             行级 tblHeader
      cs:  [行号]             行级 cantSplit
      tcm: (t,l,b,r)          单元格 tcMar 众数
      va:  val                单元格 vAlign 众数
    }
    """
    from collections import Counter
    out = {"ind": None, "lay": None, "cm": None, "bd": None,
           "hdr": [], "cs": [], "tcm": None, "va": None}
    tblPr = el.find(qn("tblPr"))
    if tblPr is not None:
        ti = tblPr.find(qn("tblInd"))
        if ti is not None:
            out["ind"] = (ti.get(qn("w")), ti.get(qn("type")))
        tl = tblPr.find(qn("tblLayout"))
        if tl is not None:
            out["lay"] = tl.get(qn("type"))
        cm = tblPr.find(qn("tblCellMar"))
        if cm is not None:
            out["cm"] = _cm_tuple(cm)
        tb = tblPr.find(qn("tblBorders"))
        if tb is not None:
            vals = set()
            for e in tb:
                vals.add((e.get(qn("val")), e.get(qn("color")),
                          e.get(qn("sz")), e.get(qn("space"))))
            if len(vals) == 1:
                v = vals.pop()
                out["bd"] = "{0}:{1}:{2}:{3}".format(v[0], v[1], v[2], v[3])
    # 行级 tblHeader/cantSplit
    for i, tr in enumerate(el.findall(qn("tr"))):
        trPr = tr.find(qn("trPr"))
        if trPr is None:
            continue
        if trPr.find(qn("tblHeader")) is not None:
            out["hdr"].append(i)
        if trPr.find(qn("cantSplit")) is not None:
            out["cs"].append(i)
    # 单元格级 tcMar/vAlign 众数
    tm_cnt = Counter()
    va_cnt = Counter()
    for tc in el.iter(qn("tc")):
        tcPr = tc.find(qn("tcPr"))
        if tcPr is None:
            continue
        t = tcPr.find(qn("tcMar"))
        if t is not None:
            v = _cm_tuple(t)
            if v is not None:
                tm_cnt[v] += 1
        va = tcPr.find(qn("vAlign"))
        if va is not None:
            va_cnt[va.get(qn("val"))] += 1
    if tm_cnt:
        out["tcm"] = tm_cnt.most_common(1)[0][0]
    if va_cnt:
        out["va"] = va_cnt.most_common(1)[0][0]
    return out


def extract(key):
    cfg = DOCS[key]
    src = os.path.join(SRC_DIR, cfg["src"])
    if not os.path.exists(src):
        print("MISSING:", src)
        return False

    from lxml import etree

    with zipfile.ZipFile(src) as z:
        xml = z.read("word/document.xml")
        try:
            styles_xml = z.read("word/styles.xml")
        except KeyError:
            styles_xml = b""
        rels_xml = z.read("word/_rels/document.xml.rels")
        media_files = {n: z.read(n) for n in z.namelist() if n.startswith("word/media/")}

    root = etree.fromstring(xml)
    body = root.find(qn("body"))

    # styleId -> heading level
    heading_style_map = {}
    sroot = etree.fromstring(styles_xml)
    for s in sroot.iter(qn("style")):
        nm = s.find(qn("name"))
        if nm is None:
            continue
        m = re.match(r"(?i)heading\s*(\d+)", nm.get(qn("val")) or "")
        if m:
            heading_style_map[s.get(qn("styleId"))] = int(m.group(1))

    # 关系: rid -> target
    rroot = etree.fromstring(rels_xml)
    rel_map = {}
    for rel in rroot:
        rid = rel.get("Id")
        target = rel.get("Target")
        rtype = rel.get("Type", "")
        if target and not target.startswith("http"):
            # 相对 word/ 目录
            full = "word/" + target if not target.startswith("/") else target.lstrip("/")
            rel_map[rid] = {"target": full, "type": rtype}

    # 找正文起点
    children = list(body)
    start_idx = None
    for i, el in enumerate(children):
        if etree.QName(el).localname != "p":
            continue
        pPr = el.find(qn("pPr"))
        if pPr is None:
            continue
        pStyle = pPr.find(qn("pStyle"))
        if pStyle is None:
            continue
        st = pStyle.get(qn("val"))
        if heading_style_map.get(st) == 1:
            start_idx = i
            break
    if start_idx is None:
        print("ERROR: no Heading1 found")
        return False

    # 输出目录
    content_dir = os.path.join(BASE, "content", key)
    images_dir = os.path.join(BASE, "assets", key, "images")
    tables_dir = os.path.join(BASE, "assets", key, "tables")
    os.makedirs(content_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)

    # 清理旧文件(仅本类型目录)
    for d in (content_dir, images_dir, tables_dir):
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                os.remove(p)

    img_map = []
    tbl_map = []
    img_counter = 0
    tbl_counter = 0
    chapter_order = []

    # 遍历正文
    cur_chapter = None       # 当前一级章节序号
    cur_file = None          # 当前章节输出文件
    cur_lines = None
    chapter_files = {}       # 章节名 -> 文件名

    for el in children[start_idx:]:
        tag = etree.QName(el).localname
        if tag == "sectPr":
            continue
        if tag == "p":
            p = el
            st = para_style(p)
            txt = para_text(p)
            lvl = heading_style_map.get(st) if st else None
            has_img = para_has_image(p)

            if lvl == 1:
                # 新章节: 先落盘上一章节
                if cur_file is not None and cur_lines is not None:
                    with open(cur_file, "w", encoding="utf-8") as f:
                        f.write("\n".join(cur_lines).strip() + "\n")
                cur_chapter = txt
                fname = "{0:02d}-{1}.md".format(len(chapter_order) + 1, safe_name(txt))
                cur_file = os.path.join(content_dir, fname)
                cur_lines = []
                chapter_files[txt] = fname
                chapter_order.append({"chapter": txt, "file": fname})
                cur_lines.append("# " + txt)
                cur_lines.append("")
                continue
            if cur_file is None:
                continue  # 正文起点之前,跳过

            if lvl == 2:
                cur_lines.append("## " + txt)
                cur_lines.append("")
            elif lvl == 3:
                cur_lines.append("### " + txt)
                cur_lines.append("")
            elif lvl == 4:
                cur_lines.append("#### " + txt)
                cur_lines.append("")
            elif lvl == 5:
                cur_lines.append("##### " + txt)
                cur_lines.append("")
            elif lvl == 6:
                cur_lines.append("###### " + txt)
                cur_lines.append("")
            elif has_img:
                # 图片段落
                for info in para_image_info(p):
                    img_counter += 1
                    target = rel_map.get(info["rid"], {}).get("target")
                    if not target or target not in media_files:
                        # 处理可能的前缀
                        tgt = rel_map.get(info["rid"], {}).get("target", "")
                        basename = os.path.basename(tgt)
                        match = [n for n in media_files if n.endswith(basename)]
                        if not match:
                            print("WARN: 图片关系未找到 rid=%s target=%s" % (info["rid"], tgt))
                            continue
                        media_data = media_files[match[0]]
                        ext = os.path.splitext(match[0])[1].lstrip(".") or "png"
                    else:
                        media_data = media_files[target]
                        ext = os.path.splitext(target)[1].lstrip(".") or "png"
                    img_name = "img_{0:04d}.{1}".format(img_counter, ext)
                    img_path = os.path.join(images_dir, img_name)
                    with open(img_path, "wb") as f:
                        f.write(media_data)
                    # 尺寸 emu -> px (96dpi: 1px = 9525 emu)
                    w_px = round((info["cx"] or 0) / 9525) if info["cx"] else None
                    h_px = round((info["cy"] or 0) / 9525) if info["cy"] else None
                    rel_img = "images/" + img_name
                    if w_px and h_px:
                        cur_lines.append("![{0}]({1} ={2}x{3})".format(safe_alt(img_name), rel_img, w_px, h_px))
                    else:
                        cur_lines.append("![{0}]({1})".format(safe_alt(img_name), rel_img))
                    cur_lines.append("")
                    img_map.append({
                        "original_rid": info["rid"],
                        "file": key + "/images/" + img_name,
                        "chapter": cur_chapter or "",
                        "source_index": img_counter,
                        "width_px": w_px,
                        "height_px": h_px,
                    })
            elif txt == "":
                # 原文档真实空段落 -> 显式占位(与 Markdown 结构空行区分)
                if cur_lines and cur_lines[-1] != "<EMPTY_PAR/>":
                    cur_lines.append("<EMPTY_PAR/>")
            else:
                # 普通正文: 检测列表样式
                numPr = el.find(qn("pPr") + "/" + qn("numPr"))
                # 项目符号前缀(Word 符号字体 \uf0b7 等)
                is_bullet = numPr is not None or (
                    txt and txt[0] in "\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043\uf0d8\uF0B2\uF0A0"
                )
                if is_bullet:
                    # 简单列表项(带项目符号字符)
                    txt_clean = re.sub(r"^[\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043\uf0d8\uF0B2\uF0A0]+[\s\u3000]*", "", txt)
                    # 检测编号列表(如 "1. " "1、")
                    m_num = re.match(r"^(\d{1,3})[.、．]\s*", txt_clean)
                    if m_num:
                        cur_lines.append("{0}. {1}".format(m_num.group(1), txt_clean[m_num.end():]))
                    else:
                        cur_lines.append("- " + txt_clean)
                else:
                    # 段落格式标记: 显式行距/段前段后/缩进(与默认样式不同的)
                    pf = para_fmt_marker(el)
                    if pf:
                        cur_lines.append(pf)
                    cur_lines.append(txt)
                cur_lines.append("")

        elif tag == "tbl":
            # 表格
            tbl_counter += 1
            if table_is_simple(el):
                md = table_to_md(el)
                if md:
                    style, widths, tw_type, tw_w = table_meta(el)
                    trh = table_trh_mode(el)
                    fm = table_fmt_meta(el)
                    w_str = ",".join(str(w) for w in widths)
                    trh_str = " trh={0}".format(trh) if trh else ""
                    # 表格级/行级/单元格级格式元数据(可选)
                    extra = []
                    if fm["cm"] is not None:
                        extra.append("cm=" + ",".join(fm["cm"]))
                    if fm["ind"] is not None:
                        extra.append("ind={0}:{1}".format(fm["ind"][0], fm["ind"][1]))
                    if fm["lay"] is not None:
                        extra.append("lay=" + fm["lay"])
                    if fm["bd"] is not None:
                        extra.append("bd=" + fm["bd"])
                    if fm["hdr"]:
                        extra.append("hdr=" + ",".join(str(i) for i in fm["hdr"]))
                    if fm["cs"]:
                        extra.append("cs=" + ",".join(str(i) for i in fm["cs"]))
                    if fm["tcm"] is not None:
                        extra.append("tcm=" + ",".join(fm["tcm"]))
                    if fm["va"] is not None:
                        extra.append("va=" + fm["va"])
                    extra_str = (" " + " ".join(extra)) if extra else ""
                    cur_lines.append("<!-- TBL:style={0} type={1} tw={2}{3} cols={4}{5} -->".format(
                        style or "", tw_type, tw_w, trh_str, w_str, extra_str))
                    cur_lines.append(md)
                    cur_lines.append("")
                    tbl_map.append({
                        "source_index": tbl_counter,
                        "kind": "markdown",
                        "style": style,
                        "col_widths": widths,
                        "tblw_type": tw_type,
                        "tblw_w": tw_w,
                        "trh": trh,
                        "fmt": {k: v for k, v in fm.items() if v not in (None, [], "")},
                        "chapter": cur_chapter or "",
                    })
                else:
                    # 空表格,保留占位
                    cur_lines.append("<!-- TABLE:{0} -->".format(tbl_counter))
                    cur_lines.append("")
            else:
                # 复杂表格 -> 保存 XML + 占位
                xml_name = "tbl_{0:04d}.xml".format(tbl_counter)
                with open(os.path.join(tables_dir, xml_name), "wb") as f:
                    f.write(etree.tostring(el, encoding="UTF-8", xml_declaration=True))
                cur_lines.append("<!-- TABLE:{0}:{1} -->".format(tbl_counter, xml_name))
                cur_lines.append("")
                tbl_map.append({
                    "source_index": tbl_counter,
                    "kind": "xml",
                    "file": key + "/tables/" + xml_name,
                    "chapter": cur_chapter or "",
                })

    # 落盘最后一个章节
    if cur_file is not None and cur_lines is not None:
        with open(cur_file, "w", encoding="utf-8") as f:
            f.write("\n".join(cur_lines).strip() + "\n")

    # 写 image-map / table-map / _meta
    img_map_path = os.path.join(BASE, "assets", key, "image-map.yml")
    with open(img_map_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"document": key, "count": len(img_map), "images": img_map}, f, allow_unicode=True, sort_keys=False)

    tbl_map_path = os.path.join(BASE, "assets", key, "table-map.yml")
    with open(tbl_map_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"document": key, "count": len(tbl_map), "tables": tbl_map}, f, allow_unicode=True, sort_keys=False)

    meta_path = os.path.join(content_dir, "_meta.yml")
    with open(meta_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"document": key, "chapters": chapter_order}, f, allow_unicode=True, sort_keys=False)

    # 统计
    total_md = 0
    for f in os.listdir(content_dir):
        if f.endswith(".md"):
            total_md += os.path.getsize(os.path.join(content_dir, f))
    print("=" * 50)
    print("[%s] 章节数: %d" % (key, len(chapter_order)))
    print("[%s] 图片: %d" % (key, img_counter))
    print("[%s] 表格: %d (简单=%d 复杂=%d)" % (key, tbl_counter,
          sum(1 for t in tbl_map if t["kind"] == "markdown"),
          sum(1 for t in tbl_map if t["kind"] == "xml")))
    print("[%s] Markdown 总大小: %.2f KB" % (key, total_md / 1024))
    return True


def safe_name(txt):
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", txt)
    s = s.strip(".-")
    return s[:40] or "chapter"


def safe_alt(name):
    return os.path.splitext(name)[0]


if __name__ == "__main__":
    from lxml import etree  # noqa
    arg = sys.argv[1] if len(sys.argv) > 1 else "requirement"
    extract(arg)
