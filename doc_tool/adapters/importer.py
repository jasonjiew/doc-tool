# -*- coding: utf-8 -*-
"""Word 导入纯函数适配器。

任务 4.1-4.3：把 ``scripts/migration/`` 中的 ``make_template.py``、
``extract_docx.py`` 和 ``split_content.py`` 重构为接收显式路径、无全局副作用、
不依赖固定文件名的纯函数，供事务化首次导入服务（``import_project``）调用。

- 4.1 ``generate_template``：接收源 DOCX 与目标模板路径，复制源文件后删除自第一
  个 Heading 1 起的正文可变内容（保留 ``sectPr``、封面、样式、关系与媒体），
  返回模板元数据（标题样式映射与正文样式）。
- 4.2 ``extract_content``：接收源 DOCX 与暂存工作区的内容/图片/表格目录，按源
  文档顺序提取正文、图片、普通表格与复杂表格，不依赖固定文件名。
- 4.3 ``split_into_tree``：接收输入内容目录，按 Word 标题层级拆分为章节目录树，
  父章节自身正文写入 ``_index.md`` 且位于子章节之前；只处理给定目录中的大章节
  Markdown，不触碰正式项目内容。

源文档永不被修改；所有写入只发生在调用方提供的暂存目录内。
"""

from __future__ import annotations

import os
import posixpath
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml
from lxml import etree


# --- OOXML 命名空间 ---

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

W = "{" + W_NS + "}"
R = "{" + R_NS + "}"
A = "{" + A_NS + "}"
WP = "{" + WP_NS + "}"


def _qn(tag: str) -> str:
    return W + tag


# Windows 非法文件名字符 -> 全角替代（可逆，build 时还原为标题文本）。
_BAD_CHAR_MAP = {
    "/": "\uff0f",
    ":": "\uff1a",
    "*": "\uff0a",
    "?": "\uff1f",
    '"': "\u201d",
    "<": "\uff1c",
    ">": "\uff1e",
    "|": "\uff5c",
    "\\": "\uff3c",
}


def _sanitize(name: str) -> str:
    value = "".join(_BAD_CHAR_MAP.get(c, c) for c in name)
    value = re.sub(r"[\x00-\x1f]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(" .")
    # 为中文长路径预留项目父目录空间，避免单个标题组件逼近 Windows 上限。
    return value[:120].rstrip(" .") or "未命名章节"


def _safe_name(txt: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", txt)
    s = s.strip(".-")
    return s[:40] or "chapter"


def _safe_alt(name: str) -> str:
    return os.path.splitext(name)[0]


# --- 4.1 模板生成 ---


@dataclass(frozen=True)
class TemplateMeta:
    """模板生成结果。

    Attributes:
        heading_styles: styleId -> Heading 级别（1~6），写入清单的 headingStyles。
        body_style: 正文（Normal）样式的 styleId，写入清单的 bodyStyle。
        body_start_index: 第一个 Heading 1 在 body 中的子元素索引（诊断用）。
    """

    heading_styles: Dict[str, int]
    body_style: str
    body_start_index: int


def generate_template(
    source_docx: Union[str, Path], target_template: Union[str, Path]
) -> TemplateMeta:
    """从源 DOCX 生成项目模板（任务 4.1）。

    复制源文件到 ``target_template``，删除自第一个 Heading 1 起的正文可变内容
    （保留 ``sectPr``），保留全部关系与媒体（复杂表格内嵌图片引用在重建时仍需
    有效）。源文件永不被修改。

    Args:
        source_docx: 用户选择的源 DOCX 路径，文件名任意。
        target_template: 目标模板路径，由调用方提供（通常位于暂存工作区）。

    Returns:
        模板元数据，含标题样式映射与正文样式。

    Raises:
        ValueError: 源文档缺少 body、Heading 1 或正文样式。
    """
    src = Path(source_docx)
    out = Path(target_template)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(out))

    with zipfile.ZipFile(str(out), "r") as z:
        names = z.namelist()
        document_xml = z.read("word/document.xml")
        styles_xml = z.read("word/styles.xml") if "word/styles.xml" in names else b""
        rels_name = "word/_rels/document.xml.rels"
        has_rels = rels_name in names
        rels_xml = z.read(rels_name) if has_rels else b""

    root = etree.fromstring(document_xml)
    body = root.find(_qn("body"))
    if body is None:
        raise ValueError("源文档 document.xml 缺少 w:body，无法生成模板。")

    heading_style_map = _parse_heading_styles(styles_xml)
    if not heading_style_map:
        raise ValueError("源文档 styles.xml 未定义任何 Heading 样式，无法生成模板。")
    body_style = _find_body_style(styles_xml)

    children = list(body)
    start_idx = _find_first_heading1(children, heading_style_map)
    if start_idx is None:
        raise ValueError("源文档未找到第一个 Heading 1，无法确定正文起点。")

    # 删除正文元素（保留 sectPr）
    removed = 0
    for el in children[start_idx:]:
        if etree.QName(el).localname == "sectPr":
            continue
        body.remove(el)
        removed += 1

    new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(str(out), "r") as z:
        items = {n: z.read(n) for n in z.namelist()}
    items["word/document.xml"] = new_xml
    if has_rels:
        items[rels_name] = rels_xml
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)

    return TemplateMeta(
        heading_styles=dict(heading_style_map),
        body_style=body_style,
        body_start_index=start_idx,
    )


def _parse_heading_styles(styles_xml: bytes) -> Dict[str, int]:
    """从 styles.xml 建立 styleId -> Heading 级别（1~6）映射。"""
    if not styles_xml:
        return {}
    sroot = etree.fromstring(styles_xml)
    heading_map: Dict[str, int] = {}
    for style in sroot.iter(_qn("style")):
        if style.get(_qn("type")) != "paragraph":
            continue
        style_id = style.get(_qn("styleId"))
        name_elem = style.find(_qn("name"))
        if name_elem is None or not style_id:
            continue
        name_val = name_elem.get(_qn("val")) or ""
        m = re.match(r"(?i)heading\s*(\d+)", name_val)
        if not m:
            m = re.match(r"标题\s*(\d+)", name_val)
        if m:
            level = int(m.group(1))
            if 1 <= level <= 6:
                heading_map[style_id] = level
    return heading_map


def _find_body_style(styles_xml: bytes) -> str:
    """定位正文（Normal）样式的 styleId，找不到时返回空字符串。"""
    if not styles_xml:
        return ""
    sroot = etree.fromstring(styles_xml)
    for style in sroot.iter(_qn("style")):
        style_id = style.get(_qn("styleId"))
        name_elem = style.find(_qn("name"))
        if name_elem is None or not style_id:
            continue
        name_val = (name_elem.get(_qn("val")) or "").strip()
        if name_val.lower() == "normal" or name_val == "正文":
            return style_id
    return ""


def _find_first_heading1(
    children: List, heading_style_map: Dict[str, int]
) -> Optional[int]:
    """定位第一个 Heading 1 元素在 body 子元素中的索引。"""
    for i, el in enumerate(children):
        if etree.QName(el).localname != "p":
            continue
        pPr = el.find(_qn("pPr"))
        if pPr is None:
            continue
        pStyle = pPr.find(_qn("pStyle"))
        if pStyle is None:
            continue
        if heading_style_map.get(pStyle.get(_qn("val"))) == 1:
            return i
    return None


# --- 4.2 正文/资源提取 ---


@dataclass
class ExtractionResult:
    """内容提取结果。"""

    document_type: str
    chapter_count: int
    image_count: int
    table_count: int
    simple_table_count: int = 0
    complex_table_count: int = 0
    chapters: List[Dict] = field(default_factory=list)
    image_map: List[Dict] = field(default_factory=list)
    table_map: List[Dict] = field(default_factory=list)


def extract_content(
    source_docx: Union[str, Path],
    content_dir: Union[str, Path],
    images_dir: Union[str, Path],
    tables_dir: Union[str, Path],
    document_type: str,
) -> ExtractionResult:
    """从源 DOCX 提取正文 Markdown、图片与复杂表格（任务 4.2）。

    按源文档顺序遍历自第一个 Heading 1 起的正文，生成按一级章节拆分的 Markdown
    文件、图片文件与复杂表格 OOXML 资源，以及 ``image-map.yml``、
    ``table-map.yml`` 和 ``_meta.yml``。不依赖固定文件名，所有输出写入调用方
    提供的暂存目录。

    Args:
        source_docx: 源 DOCX 路径。
        content_dir: 暂存内容输出目录（章节 Markdown 根）。
        images_dir: 暂存图片输出目录。
        tables_dir: 暂存复杂表格 XML 输出目录。
        document_type: 文档类型（general/requirement/design），用于资源映射前缀。

    Returns:
        提取结果统计。
    """
    src = Path(source_docx)
    content_dir = Path(content_dir)
    images_dir = Path(images_dir)
    tables_dir = Path(tables_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(src), "r") as z:
        document_xml = z.read("word/document.xml")
        styles_xml = z.read("word/styles.xml") if "word/styles.xml" in z.namelist() else b""
        rels_xml = z.read("word/_rels/document.xml.rels")
        media_files = {n: z.read(n) for n in z.namelist() if n.startswith("word/media/")}

    root = etree.fromstring(document_xml)
    body = root.find(_qn("body"))

    heading_style_map = _parse_heading_styles(styles_xml)
    rel_map = _parse_rel_map(rels_xml)

    children = list(body)
    start_idx = _find_first_heading1(children, heading_style_map)
    if start_idx is None:
        raise ValueError("源文档未找到第一个 Heading 1，无法提取正文。")

    img_map: List[Dict] = []
    tbl_map: List[Dict] = []
    img_counter = 0
    tbl_counter = 0
    chapter_order: List[Dict] = []

    cur_chapter: Optional[str] = None
    cur_file: Optional[Path] = None
    cur_lines: Optional[List[str]] = None

    for el in children[start_idx:]:
        tag = etree.QName(el).localname
        if tag == "sectPr":
            continue
        if tag == "p":
            st = _para_style(el)
            txt = _para_text(el)
            lvl = heading_style_map.get(st) if st else None
            has_img = _para_has_image(el)

            if lvl == 1:
                if cur_file is not None and cur_lines is not None:
                    _write_chapter(cur_file, cur_lines)
                cur_chapter = txt
                fname = "{0:02d}-{1}.md".format(len(chapter_order) + 1, _safe_name(txt))
                cur_file = content_dir / fname
                cur_lines = []
                chapter_order.append({"chapter": txt, "file": fname})
                cur_lines.append("# " + txt)
                cur_lines.append("")
                if has_img:
                    img_counter, img_map = _emit_images(
                        el, rel_map, media_files, images_dir,
                        img_counter, img_map, cur_chapter, document_type, cur_lines,
                    )
                continue
            if cur_file is None:
                continue  # 正文起点之前，跳过

            if lvl and 2 <= lvl <= 6:
                cur_lines.append("#" * lvl + " " + txt)
                cur_lines.append("")
                if has_img:
                    img_counter, img_map = _emit_images(
                        el, rel_map, media_files, images_dir,
                        img_counter, img_map, cur_chapter, document_type, cur_lines,
                    )
            elif has_img:
                # 同一段落同时含文本和图片时，至少保留全部业务文本；图片仍按
                # 源段落中的关系顺序紧随其后，禁止因 ``elif`` 静默丢掉文本。
                if txt:
                    _emit_paragraph(el, txt, cur_lines)
                    cur_lines.append("")
                img_counter, img_map = _emit_images(
                    el, rel_map, media_files, images_dir,
                    img_counter, img_map, cur_chapter, document_type, cur_lines,
                )
            elif txt == "":
                if cur_lines and cur_lines[-1] != "<EMPTY_PAR/>":
                    cur_lines.append("<EMPTY_PAR/>")
            else:
                _emit_paragraph(el, txt, cur_lines)
                cur_lines.append("")
        elif tag == "tbl":
            tbl_counter, tbl_map, cur_lines = _emit_table(
                el, tables_dir, tbl_counter, tbl_map,
                cur_chapter, document_type, cur_lines,
            )

    if cur_file is not None and cur_lines is not None:
        _write_chapter(cur_file, cur_lines)

    # 写资源映射与元数据
    _write_yaml(content_dir.parent.parent / "assets" / document_type / "image-map.yml",
                {"document": document_type, "count": len(img_map), "images": img_map})
    _write_yaml(content_dir.parent.parent / "assets" / document_type / "table-map.yml",
                {"document": document_type, "count": len(tbl_map), "tables": tbl_map})
    _write_yaml(content_dir / "_meta.yml",
                {"document": document_type, "chapters": chapter_order})

    return ExtractionResult(
        document_type=document_type,
        chapter_count=len(chapter_order),
        image_count=img_counter,
        table_count=tbl_counter,
        simple_table_count=sum(1 for t in tbl_map if t["kind"] == "markdown"),
        complex_table_count=sum(1 for t in tbl_map if t["kind"] == "xml"),
        chapters=chapter_order,
        image_map=img_map,
        table_map=tbl_map,
    )


def _parse_rel_map(rels_xml: bytes) -> Dict[str, Dict[str, str]]:
    rroot = etree.fromstring(rels_xml)
    rel_map: Dict[str, Dict[str, str]] = {}
    for rel in rroot:
        rid = rel.get("Id")
        target = rel.get("Target")
        rtype = rel.get("Type", "")
        target_mode = rel.get("TargetMode", "")
        if rid and target:
            rel_map[rid] = {
                "target": target,
                "type": rtype,
                "targetMode": target_mode,
            }
    return rel_map


def _para_style(p) -> Optional[str]:
    pPr = p.find(_qn("pPr"))
    if pPr is None:
        return None
    pStyle = pPr.find(_qn("pStyle"))
    if pStyle is None:
        return None
    return pStyle.get(_qn("val"))


def _para_text(p) -> str:
    parts: List[str] = []
    for node in p.iter():
        tag = etree.QName(node).localname
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _para_has_image(p) -> bool:
    return p.find(".//" + _qn("drawing")) is not None or p.find(".//" + _qn("pict")) is not None


def _para_image_info(p) -> List[Dict]:
    infos: List[Dict] = []
    for blip in p.iter(A + "blip"):
        rid = blip.get(R + "embed") or blip.get(R + "link")
        if not rid:
            continue
        info: Dict = {"rid": rid, "cx": None, "cy": None}
        ext = blip.getparent().getparent().find(WP + "extent")
        if ext is None:
            node = blip
            while node is not None:
                e = node.find(WP + "extent")
                if e is not None:
                    ext = e
                    break
                node = node.getparent()
        if ext is not None:
            info["cx"] = int(ext.get("cx"))
            info["cy"] = int(ext.get("cy"))
        infos.append(info)
    # 旧版 Word/VML 图片：<v:imagedata r:id="..."/>。
    for node in p.iter():
        if etree.QName(node).localname != "imagedata":
            continue
        rid = node.get(R + "id")
        if rid:
            infos.append({"rid": rid, "cx": None, "cy": None})
    return infos


def _emit_images(
    el, rel_map, media_files, images_dir, img_counter, img_map,
    cur_chapter, document_type, cur_lines,
):
    image_infos = _para_image_info(el)
    if not image_infos:
        raise ValueError("检测到图片节点，但没有可提取的图片关系。")
    for info in image_infos:
        img_counter += 1
        relation = rel_map.get(info["rid"])
        if relation is None:
            raise ValueError("图片关系不存在：{0}".format(info["rid"]))
        target = relation.get("target", "")
        if relation.get("targetMode", "").lower() == "external" or target.lstrip().lower().startswith(
            ("http://", "https://", "file:", "ftp://")
        ):
            raise ValueError("不支持外部链接图片：{0}".format(info["rid"]))
        media_key = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath("word/" + target.replace("\\", "/"))
        )
        if media_key not in media_files:
            raise ValueError("图片关系目标不存在：{0}".format(info["rid"]))
        media_data = media_files[media_key]
        ext = os.path.splitext(media_key)[1].lstrip(".") or "png"
        img_name = "img_{0:04d}.{1}".format(img_counter, ext)
        (images_dir / img_name).write_bytes(media_data)
        w_px = round((info["cx"] or 0) / 9525) if info["cx"] else None
        h_px = round((info["cy"] or 0) / 9525) if info["cy"] else None
        rel_img = "images/" + img_name
        if w_px and h_px:
            cur_lines.append("![{0}]({1} ={2}x{3})".format(_safe_alt(img_name), rel_img, w_px, h_px))
        else:
            cur_lines.append("![{0}]({1})".format(_safe_alt(img_name), rel_img))
        cur_lines.append("")
        img_map.append({
            "original_rid": info["rid"],
            "file": document_type + "/images/" + img_name,
            "chapter": cur_chapter or "",
            "source_index": img_counter,
            "width_px": w_px,
            "height_px": h_px,
        })
    return img_counter, img_map


def _emit_paragraph(el, txt, cur_lines) -> None:
    numPr = el.find(_qn("pPr") + "/" + _qn("numPr"))
    is_bullet = numPr is not None or (
        txt and txt[0] in "\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043\uf0d8\uF0B2\uF0A0"
    )
    if is_bullet:
        txt_clean = re.sub(
            r"^[\uF0B7\uF0A7\uF0D8\u2022\u25CF\u25A0\u25AA\u00B7\u2023\u2043\uf0d8\uF0B2\uF0A0]+[\s\u3000]*",
            "", txt)
        m_num = re.match(r"^(\d{1,3})[.、．]\s*", txt_clean)
        if m_num:
            cur_lines.append("{0}. {1}".format(m_num.group(1), txt_clean[m_num.end():]))
        else:
            cur_lines.append("- " + txt_clean)
    else:
        pf = _para_fmt_marker(el)
        if pf:
            cur_lines.append(pf)
        cur_lines.append(txt)


def _para_fmt_marker(el) -> Optional[str]:
    pPr = el.find(_qn("pPr"))
    if pPr is None:
        return None
    parts: List[str] = []
    sp = pPr.find(_qn("spacing"))
    if sp is not None:
        for attr, key in ((qn_attr("line"), "line"), (qn_attr("lineRule"), "lr"),
                          (qn_attr("before"), "b"), (qn_attr("after"), "a")):
            v = sp.get(attr)
            if v is not None:
                parts.append("{0}={1}".format(key, v))
    ind = pPr.find(_qn("ind"))
    if ind is not None:
        for attr, key in ((qn_attr("firstLine"), "first"), (qn_attr("left"), "left"),
                          (qn_attr("hanging"), "hang"), (qn_attr("right"), "right")):
            v = ind.get(attr)
            if v is not None and v not in ("0",):
                parts.append("{0}={1}".format(key, v))
    if not parts:
        return None
    return "<!-- P:" + ";".join(parts) + " -->"


def qn_attr(tag: str) -> str:
    return _qn(tag)


def _emit_table(el, tables_dir, tbl_counter, tbl_map, cur_chapter, document_type, cur_lines):
    tbl_counter += 1
    if _table_is_simple(el):
        md = _table_to_md(el)
        if md:
            style, widths, tw_type, tw_w = _table_meta(el)
            trh = _table_trh_mode(el)
            fm = _table_fmt_meta(el)
            w_str = ",".join(str(w) for w in widths)
            trh_str = " trh={0}".format(trh) if trh else ""
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
            cur_lines.append("<!-- TABLE:{0} -->".format(tbl_counter))
            cur_lines.append("")
    else:
        xml_name = "tbl_{0:04d}.xml".format(tbl_counter)
        (tables_dir / xml_name).write_bytes(
            etree.tostring(el, encoding="UTF-8", xml_declaration=True))
        cur_lines.append("<!-- TABLE:{0}:{1} -->".format(tbl_counter, xml_name))
        cur_lines.append("")
        tbl_map.append({
            "source_index": tbl_counter,
            "kind": "xml",
            "file": document_type + "/tables/" + xml_name,
            "chapter": cur_chapter or "",
        })
    return tbl_counter, tbl_map, cur_lines


def _table_is_simple(tbl) -> bool:
    if tbl.find(".//" + _qn("gridSpan")) is not None:
        return False
    if tbl.find(".//" + _qn("vMerge")) is not None:
        return False
    if tbl.find(".//" + _qn("drawing")) is not None or tbl.find(".//" + _qn("pict")) is not None:
        return False
    if tbl.find(".//" + _qn("tbl")) is not None:
        return False
    return True


def _table_to_md(tbl) -> Optional[str]:
    rows: List[List[str]] = []
    for tr in tbl.findall(_qn("tr")):
        cells: List[str] = []
        for tc in tr.findall(_qn("tc")):
            cell_txt: List[str] = []
            for p in tc.findall(_qn("p")):
                txt = _para_text(p)
                if txt:
                    cell_txt.append(txt)
            cells.append(" ".join(cell_txt))
        rows.append(cells)
    if not rows:
        return None
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]

    def esc(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", "<br>")

    lines: List[str] = []
    lines.append("| " + " | ".join(esc(c) for c in rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(ncols)) + " |")
    for r in rows[1:]:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)


def _table_trh_mode(el):
    from collections import Counter
    cnt: Counter = Counter()
    for tr in el.findall(_qn("tr")):
        trPr = tr.find(_qn("trPr"))
        if trPr is None:
            continue
        th = trPr.find(_qn("trHeight"))
        if th is not None:
            cnt[th.get(_qn("val"))] += 1
    if not cnt:
        return None
    return cnt.most_common(1)[0][0]


def _table_meta(el) -> Tuple[Optional[str], List[int], str, int]:
    tblPr = el.find(_qn("tblPr"))
    style = None
    tw_type = None
    tw_w = 0
    if tblPr is not None:
        s = tblPr.find(_qn("tblStyle"))
        if s is not None:
            style = s.get(_qn("val"))
        tw = tblPr.find(_qn("tblW"))
        if tw is not None:
            tw_type = tw.get(_qn("type"))
            try:
                tw_w = int(tw.get(_qn("w")) or 0)
            except (ValueError, TypeError):
                tw_w = 0
    widths: List[int] = []
    grid = el.find(_qn("tblGrid"))
    if grid is not None:
        for gc in grid.findall(_qn("gridCol")):
            v = gc.get(_qn("w"))
            widths.append(int(v) if v else 0)
    return style, widths, tw_type or "dxa", tw_w


def _cm_tuple(cm):
    vals = []
    for tag in ("top", "left", "bottom", "right"):
        e = cm.find(_qn(tag))
        if e is None or e.get(_qn("w")) is None:
            return None
        vals.append(e.get(_qn("w")))
    return tuple(vals)


def _table_fmt_meta(el) -> Dict:
    from collections import Counter
    out: Dict = {"ind": None, "lay": None, "cm": None, "bd": None,
                 "hdr": [], "cs": [], "tcm": None, "va": None}
    tblPr = el.find(_qn("tblPr"))
    if tblPr is not None:
        ti = tblPr.find(_qn("tblInd"))
        if ti is not None:
            out["ind"] = (ti.get(_qn("w")), ti.get(_qn("type")))
        tl = tblPr.find(_qn("tblLayout"))
        if tl is not None:
            out["lay"] = tl.get(_qn("type"))
        cm = tblPr.find(_qn("tblCellMar"))
        if cm is not None:
            out["cm"] = _cm_tuple(cm)
        tb = tblPr.find(_qn("tblBorders"))
        if tb is not None:
            vals = set()
            for e in tb:
                vals.add((e.get(_qn("val")), e.get(_qn("color")),
                          e.get(_qn("sz")), e.get(_qn("space"))))
            if len(vals) == 1:
                v = vals.pop()
                out["bd"] = "{0}:{1}:{2}:{3}".format(v[0], v[1], v[2], v[3])
    for i, tr in enumerate(el.findall(_qn("tr"))):
        trPr = tr.find(_qn("trPr"))
        if trPr is None:
            continue
        if trPr.find(_qn("tblHeader")) is not None:
            out["hdr"].append(i)
        if trPr.find(_qn("cantSplit")) is not None:
            out["cs"].append(i)
    tm_cnt: Counter = Counter()
    va_cnt: Counter = Counter()
    for tc in el.iter(_qn("tc")):
        tcPr = tc.find(_qn("tcPr"))
        if tcPr is None:
            continue
        t = tcPr.find(_qn("tcMar"))
        if t is not None:
            v = _cm_tuple(t)
            if v is not None:
                tm_cnt[v] += 1
        va = tcPr.find(_qn("vAlign"))
        if va is not None:
            va_cnt[va.get(_qn("val"))] += 1
    if tm_cnt:
        out["tcm"] = tm_cnt.most_common(1)[0][0]
    if va_cnt:
        out["va"] = va_cnt.most_common(1)[0][0]
    return out


def _write_chapter(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _write_yaml(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# --- 4.3 章节目录树拆分 ---


@dataclass
class SplitResult:
    """章节拆分结果。"""

    dirs: int = 0
    mds: int = 0
    indexes: int = 0


class _Node:
    """章节树节点。"""

    def __init__(self, depth: int, title: str, line_idx: int) -> None:
        self.depth = depth
        self.title = title
        self.line_idx = line_idx
        self.content: List[str] = []
        self.children: List[_Node] = []
        self.num: List[int] = []

    def is_dir(self) -> bool:
        if self.depth == 1:
            return True
        if self.depth == 2:
            return len(self.children) > 0
        return False

    def display_name(self) -> str:
        if self.depth == 1:
            return "第{0}章 {1}".format(self.num[0], self.title)
        return ".".join(str(x) for x in self.num) + " " + self.title

    def full_name(self) -> str:
        return _sanitize(self.display_name())


def split_into_tree(content_dir: Union[str, Path]) -> SplitResult:
    """把大章节 Markdown 拆分为章节目录树（任务 4.3）。

    拆分规则（以原 Word 标题层级为最终依据）：
    - 一级标题 -> 文件夹 ``第N章 标题/``
    - 二级标题 -> 有三级子节点则文件夹，否则独立 MD
    - 三级标题 -> 独立 MD ``N.M.K 标题.md``
    - 四级及以上 -> 保留在所属三级/二级 MD 内（标题行原样）

    父章节自身正文写入同目录 ``_index.md`` 且位于子章节之前。只处理
    ``content_dir`` 中的顶层大章节 Markdown；迁移完成后删除这些大章节文件。
    不会删除或修改 ``content_dir`` 以外的任何正式项目内容。

    Args:
        content_dir: 待拆分的内容目录（暂存工作区）。

    Returns:
        拆分统计。
    """
    src_dir = Path(content_dir)
    if not src_dir.is_dir():
        return SplitResult()

    md_files = sorted(f for f in os.listdir(str(src_dir)) if f.endswith(".md"))
    if not md_files:
        return SplitResult()

    stats = SplitResult()
    chapter_count = 0
    for f in md_files:
        roots = _parse_file(src_dir / f)
        _assign_numbers(roots, chapter_count)
        for r in roots:
            _emit(r, src_dir, stats)
        chapter_count += len(roots)

    # 删除已迁移进目录树的大章节 Markdown（仅本目录顶层文件）
    for f in md_files:
        os.remove(str(src_dir / f))
    return stats


def _parse_file(path: Path) -> List[_Node]:
    lines = path.read_text(encoding="utf-8").split("\n")
    roots: List[_Node] = []
    stack: List[_Node] = []
    for idx, raw in enumerate(lines):
        s = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            depth = len(m.group(1))
            title = m.group(2).strip()
            if depth <= 3:
                node = _Node(depth, title, idx)
                while stack and depth <= stack[-1].depth:
                    stack.pop()
                if stack:
                    stack[-1].children.append(node)
                else:
                    roots.append(node)
                stack.append(node)
            else:
                if stack:
                    stack[-1].content.append(raw)
        else:
            if stack:
                stack[-1].content.append(raw)
            elif s and roots:
                roots[0].content.append(raw)
    return roots


def _assign_numbers(roots: List[_Node], chapter_start: int = 0) -> None:
    def walk(nodes: List[_Node], parent_num: List[int]) -> None:
        for j, n in enumerate(nodes, start=1):
            n.num = parent_num + [j]
            walk(n.children, n.num)

    for i, r in enumerate(roots, start=1):
        r.num = [chapter_start + i]
        walk(r.children, r.num)


def _emit(node: _Node, out_dir: Path, stats: SplitResult) -> None:
    name = node.full_name()
    node_path = out_dir / name
    if node.is_dir():
        node_path.mkdir(parents=True, exist_ok=True)
        stats.dirs += 1
        body = list(node.content)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if body:
            (node_path / "_index.md").write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")
            stats.indexes += 1
        for c in node.children:
            _emit(c, node_path, stats)
    else:
        # 注意：章节编号含点（如 "1.1 目的"），不能用 Path.with_suffix，
        # 否则 pathlib 会把 ".1 目的" 当作扩展名剥离，得到错误的 "1.md"。
        md_path = out_dir / (name + ".md")
        body = list(node.content)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        if body:
            md_path.write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")
        else:
            md_path.write_text("", encoding="utf-8")
        stats.mds += 1
