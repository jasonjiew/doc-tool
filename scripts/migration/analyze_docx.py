# -*- coding: utf-8 -*-
"""
Phase 1: 分析原始 Word 文档结构
用法:
    python scripts/migration/analyze_docx.py requirement
    python scripts/migration/analyze_docx.py design
输出:
    analysis/requirement-analysis.md
    analysis/design-analysis.md
"""
import os
import sys
import zipfile
import re
from collections import Counter, OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.dirname(BASE)  # 原始文档所在目录（doc-automation 的上级）

DOCS = {
    "requirement": "KF-2090-1-001 康尚健康云软件需求说明书(3.8).docx",
    "design": "KF-2090-1-006 康尚健康云系统详细设计说明书(2.5).docx",
}

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def qn(tag):
    # tag 不带前缀，例如 qn("p") -> {ns}p
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
    return "".join(t.text or "" for t in p.iter(qn("t"))).strip()


def is_heading(style):
    return style and re.match(r"(heading\s*[1-9]|标题\s*[1-9]|^\d+$|^h[1-9]$)", style, re.I) is not None


def heading_level(style):
    if not style:
        return None
    m = re.search(r"(\d)", style)
    return int(m.group(1)) if m else None


def analyze(doc_key):
    src = os.path.join(SRC_DIR, DOCS[doc_key])
    if not os.path.exists(src):
        print("MISSING:", src)
        return
    print("Analyzing:", src)
    lines = []
    add = lines.append
    add("# {0} 结构分析报告".format(DOCS[doc_key]))
    add("")
    add("> 由 scripts/migration/analyze_docx.py 自动生成")
    add("")
    size_mb = os.path.getsize(src) / 1024 / 1024
    add("## 0. 文件基本信息")
    add("")
    add("- 文件路径: `{0}`".format(src))
    add("- 文件大小: {0:.2f} MB".format(size_mb))
    add("")

    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        total = sum(i.file_size for i in z.infolist())
        add("## 1. OOXML 包结构")
        add("")
        add("- 包内文件数: {0}".format(len(names)))
        add("- 包解压总大小: {0:.2f} MB".format(total / 1024 / 1024))
        media = [n for n in names if n.startswith("word/media/")]
        media_size = sum(z.getinfo(n).file_size for n in media)
        add("- media 文件数: {0} (共 {1:.2f} MB)".format(len(media), media_size / 1024 / 1024))
        add("")
        add("### 1.1 media 文件清单")
        add("")
        add("| # | 文件 | 大小(KB) |")
        add("|---|------|---------|")
        for i, n in enumerate(sorted(media), 1):
            add("| {0} | {1} | {2:.1f} |".format(i, n, z.getinfo(n).file_size / 1024))
        add("")

        try:
            xml = z.read("word/document.xml").decode("utf-8")
        except KeyError:
            xml = ""
        try:
            rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
        except KeyError:
            rels = ""
        try:
            styles_xml = z.read("word/styles.xml").decode("utf-8")
        except KeyError:
            styles_xml = ""

    # ---- 通过 styles.xml 建立 styleId -> heading 级别映射 ----
    from lxml import etree
    heading_style_map = {}  # styleId -> level
    if styles_xml:
        sroot = etree.fromstring(styles_xml.encode("utf-8"))
        for s in sroot.iter(qn("style")):
            sid = s.get(qn("styleId"))
            nm = s.find(qn("name"))
            if nm is None:
                continue
            nmv = nm.get(qn("val")) or ""
            m = re.match(r"(?i)heading\s*(\d+)", nmv)
            if m:
                heading_style_map[sid] = int(m.group(1))
    add("标题样式映射 (styleId -> heading level): `{0}`".format(heading_style_map))
    add("")

    # ---- 直接统计 document.xml ----
    para_count = xml.count("<w:p ") + xml.count("<w:p>")
    tbl_count = xml.count("<w:tbl>")
    sect_count = xml.count("<w:sectPr>")
    page_break = len(re.findall(r"<w:br[^>]*w:type=\"page\"", xml))
    field_count = len(re.findall(r"<w:fldChar", xml))
    instr_count = len(re.findall(r"<w:instrText", xml))
    hyperlink_count = len(re.findall(r"<w:hyperlink", xml))
    drawing_count = len(re.findall(r"<w:drawing>", xml))
    pict_count = len(re.findall(r"<w:pict>", xml))
    textbox_count = len(re.findall(r"<w:txbxContent>", xml))
    ole_count = len(re.findall(r"<o:OLEObject|<o:oleObject", xml))
    bookmark_count = len(re.findall(r"<w:bookmarkStart", xml))
    sdt_count = len(re.findall(r"<w:sdt>", xml))

    add("## 2. 主体结构统计 (document.xml)")
    add("")
    add("| 项目 | 数量 |")
    add("|------|-----|")
    add("| 段落 <w:p> | {0} |".format(para_count))
    add("| 表格 <w:tbl> | {0} |".format(tbl_count))
    add("| Section <w:sectPr> | {0} |".format(sect_count))
    add("| 分页符 (page break) | {0} |".format(page_break))
    add("| 域标记 (fldChar) | {0} |".format(field_count))
    add("| 域指令 (instrText) | {0} |".format(instr_count))
    add("| 超链接 | {0} |".format(hyperlink_count))
    add("| 图片绘制 (drawing) | {0} |".format(drawing_count))
    add("| 旧式图片 (pict) | {0} |".format(pict_count))
    add("| 文本框 (txbxContent) | {0} |".format(textbox_count))
    add("| OLE 对象 | {0} |".format(ole_count))
    add("| 书签 (bookmarkStart) | {0} |".format(bookmark_count))
    add("| 内容控件 (sdt) | {0} |".format(sdt_count))
    add("")

    # ---- 图片关系 ----
    add("## 3. 图片 Relationship 分析")
    add("")
    img_rel = re.findall(r'Id="([^"]+)"[^>]*Target="(media/[^"]+)"', rels)
    img_rel += re.findall(r'Target="(media/[^"]+)"[^>]*Id="([^"]+)"', rels)
    add("- Relationship 中 media 引用数量: {0}".format(len(img_rel)))
    add("")

    # ---- 标题结构 ----
    add("## 4. Heading 结构分析")
    add("")
    root = etree.fromstring(xml.encode("utf-8"))
    style_counter = Counter()
    heading_tree = []
    for p in root.iter(qn("p")):
        st = para_style(p)
        txt = para_text(p)
        style_counter[st or "(none)"] += 1
        lvl = heading_style_map.get(st) if st else None
        if txt and lvl:
            heading_tree.append((lvl, st, txt))
    add("### 4.1 标题统计")
    add("")
    lvl_counter = Counter(h[0] for h in heading_tree)
    for lvl in sorted(lvl_counter):
        add("- 级别 {0}: {1} 个".format(lvl, lvl_counter[lvl]))
    add("")
    add("### 4.2 章节树（前 200 条）")
    add("")
    add("```text")
    for lvl, st, txt in heading_tree[:200]:
        add("{0}{1} [{2}] {3}".format("  " * (lvl or 1), lvl, st, txt[:80]))
    add("```")
    add("")

    # ---- 样式 ----
    add("## 5. 段落样式分布 (Top 30)")
    add("")
    add("| 样式 | 段落数 |")
    add("|------|-------|")
    for st, cnt in style_counter.most_common(30):
        add("| {0} | {1} |".format(st, cnt))
    add("")

    # ---- 表格 ----
    add("## 6. 表格分析")
    add("")
    tbls = list(root.iter(qn("tbl")))
    add("- 表格总数: {0}".format(len(tbls)))
    row_counts = []
    for t in tbls:
        trs = list(t.iter(qn("tr")))
        row_counts.append(len(trs))
    if row_counts:
        add("- 行数统计: min={0} max={1} avg={2:.1f}".format(min(row_counts), max(row_counts), sum(row_counts) / len(row_counts)))
    add("")
    tbl_style_counter = Counter()
    for t in tbls:
        tblPr = t.find(qn("tblPr"))
        if tblPr is not None:
            st = tblPr.find(qn("tblStyle"))
            if st is not None:
                tbl_style_counter[st.get(qn("val"))] += 1
    if tbl_style_counter:
        add("| 表格样式 | 数量 |")
        add("|---------|-----|")
        for st, cnt in tbl_style_counter.most_common():
            add("| {0} | {1} |".format(st, cnt))
        add("")

    # ---- 特殊对象风险提示 ----
    add("## 7. 风险点提示")
    add("")
    risks = []
    if ole_count:
        risks.append("- 存在 OLE 对象 {0} 个，python-docx 无法重建，必须保留在模板中".format(ole_count))
    if textbox_count:
        risks.append("- 存在文本框 {0} 个，python-docx 无法直接创建，需 lxml 处理或保留在模板".format(textbox_count))
    if sdt_count:
        risks.append("- 存在内容控件 {0} 个".format(sdt_count))
    if field_count:
        risks.append("- 存在域 {0} 处（含 TOC），生成后需刷新域".format(field_count))
    if pict_count:
        risks.append("- 存在旧式图片 {0} 处".format(pict_count))
    if not risks:
        risks.append("- 未发现明显高风险特殊对象")
    add("\n".join(risks))
    add("")

    # ---- 结论 ----
    add("## 8. 结论")
    add("")
    add("- 适合 Markdown 化的内容：正文段落、普通列表、普通表格、标题。")
    add("- 必须保留在 Word 模板中的内容：封面、页眉页脚、TOC 域、修订记录表、固定声明、特殊对象（文本框/OLE/内容控件）。")
    add("- 详细设计体积主要来源：media 图片（见 1.1 清单）。")
    add("")

    out = os.path.join(BASE, "analysis", "{0}-analysis.md".format(doc_key))
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("WROTE:", out)
    print("paragraphs={0} tables={1} images={2} headings={3}".format(para_count, tbl_count, len(media), len(heading_tree)))


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "all"
    if key == "all":
        for k in DOCS:
            analyze(k)
    else:
        analyze(key)
