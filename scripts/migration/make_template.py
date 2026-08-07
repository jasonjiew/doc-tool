# -*- coding: utf-8 -*-
"""
Phase 2: 建立 Word 模板骨架
用法:
    python scripts/migration/make_template.py requirement
    python scripts/migration/make_template.py design
    python scripts/migration/make_template.py all
输出:
    templates/requirement-template.docx
    templates/design-template.docx

策略:
    复制原始 Word -> 删除正文可变内容(从第一个 Heading1 起) -> 保留封面/TOC/修订记录/页眉页脚/Section/样式
    原始 Word 永不被修改。
"""
import os
import re
import shutil
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.dirname(BASE)

DOCS = {
    "requirement": {
        "src": "KF-2090-1-001 康尚健康云软件需求说明书(3.8).docx",
        "out": os.path.join(BASE, "templates", "requirement-template.docx"),
    },
    "design": {
        "src": "KF-2090-1-006 康尚健康云系统详细设计说明书(2.5).docx",
        "out": os.path.join(BASE, "templates", "design-template.docx"),
    },
}

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def qn(tag):
    return W_NS + tag


def build_template(key):
    cfg = DOCS[key]
    src = os.path.join(SRC_DIR, cfg["src"])
    out = cfg["out"]
    if not os.path.exists(src):
        print("MISSING:", src)
        return False

    print("[%s] 源文档: %s" % (key, src))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.copy2(src, out)

    from lxml import etree

    with zipfile.ZipFile(out, "r") as z:
        names = z.namelist()
        xml = z.read("word/document.xml")
        try:
            styles_xml = z.read("word/styles.xml")
        except KeyError:
            styles_xml = b""
        rels_name = "word/_rels/document.xml.rels"
        has_rels = rels_name in names
        rels_xml = z.read(rels_name) if has_rels else b""

    root = etree.fromstring(xml)
    body = root.find(qn("body"))
    if body is None:
        print("ERROR: no body")
        return False

    # 1) 建立 styleId -> heading level 映射
    heading_style_map = {}
    if styles_xml:
        sroot = etree.fromstring(styles_xml)
        for s in sroot.iter(qn("style")):
            nm = s.find(qn("name"))
            if nm is None:
                continue
            m = re.match(r"(?i)heading\s*(\d+)", nm.get(qn("val")) or "")
            if m:
                heading_style_map[s.get(qn("styleId"))] = int(m.group(1))

    # 2) 定位第一个 Heading 1 元素索引
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
        print("ERROR: 未找到第一个 Heading 1")
        return False
    print("[%s] 正文起点: body 子元素索引 %d" % (key, start_idx))

    # 3) 收集被正文引用的关系 Id (图片/超链接等)，用于清理
    used_rids = set()
    for el in children[start_idx:]:
        # 图片关系 r:embed / r:link
        for attr in ("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed",
                     "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}link"):
            for node in el.iter():
                v = node.get(attr)
                if v:
                    used_rids.add(v)
        # 超链接 r:id
        for node in el.iter(qn("hyperlink")):
            v = node.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if v:
                used_rids.add(v)
        # 脚注/尾注引用
        for node in el.iter(qn("footnoteReference")):
            v = node.get(qn("id"))
            if v:
                used_rids.add(v)

    # 4) 删除正文元素（保留 sectPr）
    removed = 0
    for el in children[start_idx:]:
        if etree.QName(el).localname == "sectPr":
            continue
        body.remove(el)
        removed += 1
    print("[%s] 删除正文元素: %d" % (key, removed))

    # 5) 关系处理: 保留全部原始 rels 与 media
    #    目的: 复杂表格 XML 内嵌图片引用 r:embed=rIdX 在重建时必须仍然有效。
    #    因此模板不清理任何 Relationship,不删除任何 media 文件。
    #    (Word 对未使用的关系是容忍的,不会产生修复提示)

    # 6) 写回
    new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(out, "r") as z:
        items = {n: z.read(n) for n in z.namelist()}
    items["word/document.xml"] = new_xml
    if has_rels:
        items[rels_name] = rels_xml
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)

    print("[%s] 模板已生成: %s (%.2f MB)" % (key, out, os.path.getsize(out) / 1024 / 1024))
    return True


def verify(key):
    """用 python-docx 尝试打开，确认无结构损坏"""
    import docx
    cfg = DOCS[key]
    out = cfg["out"]
    d = docx.Document(out)
    print("[%s] 校验通过: python-docx 可打开, 段落=%d 表格=%d" % (key, len(d.paragraphs), len(d.tables)))
    # 检查 XML 是否良构
    with zipfile.ZipFile(out) as z:
        from lxml import etree
        etree.fromstring(z.read("word/document.xml"))
    print("[%s] XML 良构校验通过" % key)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    keys = list(DOCS) if arg == "all" else [arg]
    for k in keys:
        if build_template(k):
            verify(k)
