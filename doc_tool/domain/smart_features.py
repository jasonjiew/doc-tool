# -*- coding: utf-8 -*-
"""主流程智能化增强核心算法模块（Smart Mainflow Features）。

集中提供 6 大智能化能力所需的纯领域规则与 XML/Markdown 转换算法：
1. 导入提取智能还原：图表题注自动识别与绑定、行内富文本格式还原、连续代码段聚合；
2. 自然语言题注与中文交叉引用：免 ``{#id}`` 自然题注生成确定性 ID、按标题名与自然中文引用解析；
3. 重导入智能对齐与表格单元格级三方合并：跨文件章节改名/移位指纹对齐、Markdown 表格行/单元格级三方合并；
4. 复杂表格可读代理与单元格回填：从 ``<w:tbl>`` 提取 Markdown 代理表，并在构建/校验时将单元格文字修改回填至 ``<w:tc>``；
5. 智能排版自适应：手写无元数据表格智能列宽计算与超宽自动横版、无尺寸图片物理尺寸智能缩放；
6. 智能修订摘要与版本演进：基于基线快照与当前章节差异自动生成结构化修订说明。
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple
from xml.etree import ElementTree as ET

from doc_tool.domain.markdown_structure import prose_lines

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

CODE_FONTS: Set[str] = {
    "consolas",
    "courier new",
    "courier",
    "source code pro",
    "fira code",
    "jetbrains mono",
    "monaco",
    "menlo",
    "lucida console",
    "dejavu sans mono",
    "ubuntu mono",
}

CODE_STYLE_KEYWORDS: Tuple[str, ...] = (
    "code",
    "sourcecode",
    "preformatted",
    "htmlpreformatted",
    "代码",
    "源码",
)


def _qn(tag: str) -> str:
    return "{%s}%s" % (W_NS, tag)


def stable_auto_ident(prefix: str, label: str, num_hint: str = "") -> str:
    """为未写 ``{#id}`` 的自然题注生成稳定、可读的标识符。"""
    clean_num = re.sub(r"[^0-9A-Za-z]+", "-", (num_hint or "").strip()).strip("-")
    if clean_num:
        return "{0}-{1}".format(prefix, clean_num)
    ascii_slug = re.sub(r"[^0-9A-Za-z]+", "-", (label or "").strip()).strip("-").lower()
    if ascii_slug and len(ascii_slug) >= 2:
        return "{0}-{1}".format(prefix, ascii_slug[:24].strip("-"))
    digest = hashlib.sha1((label or "").strip().encode("utf-8")).hexdigest()[:8]
    return "{0}-auto-{1}".format(prefix, digest)


def normalize_caption_label(label: str) -> str:
    """归一化题注标题以供自然语言引用匹配（忽略首尾空白、书名号/引号与多余空格）。"""
    text = (label or "").strip()
    text = re.sub(r"^[《「“\"'（(]+|[》」”\"'）)]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# 1. 导入提取阶段：行内富文本、代码块识别与图表题注自动绑定
# ---------------------------------------------------------------------------


def _run_font_names(rPr: Optional[ET.Element]) -> List[str]:
    if rPr is None:
        return []
    names: List[str] = []
    rFonts = rPr.find(_qn("rFonts"))
    if rFonts is not None:
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            val = rFonts.get(_qn(attr)) or rFonts.get(attr)
            if val:
                names.append(val.strip().lower())
    return names


def _is_run_monospace(rPr: Optional[ET.Element]) -> bool:
    return any(name in CODE_FONTS for name in _run_font_names(rPr))


def _is_flag_enabled(rPr: Optional[ET.Element], tag_name: str) -> bool:
    if rPr is None:
        return False
    el = rPr.find(_qn(tag_name))
    if el is None:
        return False
    val = (el.get(_qn("val")) or el.get("val") or "true").strip().lower()
    return val not in ("0", "false", "off", "none")


def _extract_run_raw_text(r_elem: ET.Element) -> str:
    parts: List[str] = []
    for child in r_elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "t" and child.text:
            parts.append(child.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            btype = child.get(_qn("type")) or child.get("type")
            if btype not in ("page", "column"):
                parts.append("<br>")
    return "".join(parts)


def is_code_like_paragraph(
    p_elem: ET.Element,
    styles_map: Optional[Dict[str, Tuple[str, Optional[int], Optional[str]]]] = None,
) -> bool:
    """判断 Word 段落是否为代码行（基于代码块样式或全段落等宽代码字体）。"""
    pPr = p_elem.find(_qn("pPr"))
    if pPr is not None:
        pStyle = pPr.find(_qn("pStyle"))
        if pStyle is not None:
            sid = (pStyle.get(_qn("val")) or pStyle.get("val") or "").strip()
            s_lower = sid.lower()
            if any(k in s_lower for k in CODE_STYLE_KEYWORDS):
                return True
            if styles_map and sid in styles_map:
                sname = (styles_map[sid][0] or "").lower()
                if any(k in sname for k in CODE_STYLE_KEYWORDS):
                    return True
    runs = p_elem.findall(_qn("r"))
    if not runs:
        return False
    non_empty_runs = 0
    for r in runs:
        txt = _extract_run_raw_text(r)
        if not txt.strip():
            continue
        non_empty_runs += 1
        if not _is_run_monospace(r.find(_qn("rPr"))):
            return False
    return non_empty_runs > 0


def infer_code_language(lines: Sequence[str]) -> str:
    """根据代码行内容启发式推断代码块语言标识。"""
    joined = "\n".join(lines).strip()
    if not joined:
        return ""
    if (joined.startswith("{") and joined.endswith("}")) or (
        joined.startswith("[") and joined.endswith("]")
    ):
        if ":" in joined and '"' in joined:
            return "json"
    first_upper = joined.splitlines()[0].strip().upper()
    if re.match(r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH)\b", first_upper):
        return "sql"
    if re.search(r"^\s*(def |class |import |from .+ import |if __name__ ==)", joined, re.M):
        return "python"
    if joined.startswith("<") and joined.endswith(">") and ("</" in joined or "/>" in joined):
        return "xml"
    if re.search(r"^\s*(#!/bin/|curl |docker |kubectl |git |npm |pip )", joined, re.M):
        return "bash"
    return ""


def extract_paragraph_smart_text(
    p_elem: ET.Element,
    rel_map: Optional[Dict[str, str]] = None,
    *,
    smart_inline: bool = False,
) -> str:
    """提取段落文本，可选保留外链 ``[文字](url)`` 与行内混合加粗/斜体/等宽代码。"""
    rel_map = rel_map or {}
    segments: List[Tuple[str, bool, bool, bool, str]] = []
    for child in p_elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "r":
            txt = _extract_run_raw_text(child)
            if not txt:
                continue
            rPr = child.find(_qn("rPr"))
            segments.append((
                txt,
                _is_flag_enabled(rPr, "b"),
                _is_flag_enabled(rPr, "i"),
                _is_run_monospace(rPr),
                "",
            ))
        elif tag == "hyperlink":
            rid = child.get("{%s}id" % R_NS) or child.get("r:id") or ""
            anchor = child.get(_qn("anchor")) or child.get("anchor") or ""
            target = rel_map.get(rid, "") if rid else ""
            link_url = ""
            if target and re.match(r"^(https?://|mailto:)", target, re.I):
                link_url = target
            elif smart_inline and anchor and not rid:
                link_url = "#" + anchor
            h_parts: List[str] = []
            for sub in child.iter(_qn("r")):
                h_parts.append(_extract_run_raw_text(sub))
            h_txt = "".join(h_parts)
            if h_txt:
                segments.append((h_txt, False, False, False, link_url))
        elif tag == "br":
            btype = child.get(_qn("type")) or child.get("type")
            if btype not in ("page", "column"):
                segments.append(("<br>", False, False, False, ""))
        elif tag in ("smartTag", "sdt", "ins"):
            for sub in child.iter(_qn("r")):
                txt = _extract_run_raw_text(sub)
                if txt:
                    rPr = sub.find(_qn("rPr"))
                    segments.append((
                        txt,
                        _is_flag_enabled(rPr, "b"),
                        _is_flag_enabled(rPr, "i"),
                        _is_run_monospace(rPr),
                        "",
                    ))

    if not segments:
        return ""

    if not smart_inline:
        return "".join(seg[0] for seg in segments)

    merged: List[Tuple[str, bool, bool, bool, str]] = []
    for txt, b, it, code, link in segments:
        if merged and merged[-1][1:] == (b, it, code, link) and not link:
            prev_txt = merged[-1][0]
            merged[-1] = (prev_txt + txt, b, it, code, link)
        else:
            merged.append((txt, b, it, code, link))

    non_ws = [seg for seg in merged if seg[0].strip() and seg[0] != "<br>"]
    has_plain = any(not seg[1] and not seg[2] and not seg[3] for seg in non_ws)
    allow_emphasis = has_plain and len(non_ws) >= 2

    out: List[str] = []
    for txt, b, it, code, link in merged:
        if link and txt.strip():
            out.append("[{0}]({1})".format(txt.strip(), link))
            continue
        if not allow_emphasis or not txt.strip() or txt == "<br>":
            out.append(txt)
            continue
        lead_ws = txt[: len(txt) - len(txt.lstrip())]
        trail_ws = txt[len(txt.rstrip()) :]
        core = txt.strip()
        if code and "`" not in core and "<br>" not in core:
            core = "`{0}`".format(core)
        elif b and it and "**" not in core and "<br>" not in core:
            core = "***{0}***".format(core)
        elif b and "**" not in core and "<br>" not in core:
            core = "**{0}**".format(core)
        elif it and "*" not in core and "<br>" not in core:
            core = "*{0}*".format(core)
        out.append("{0}{1}{2}".format(lead_ws, core, trail_ws))
    return "".join(out)


_IMPORTED_FIG_CAPTION_RE = re.compile(
    r"^\s*(?:图|插图|Figure|Fig\.?)\s*(?P<num>\d+(?:[-.]\d+)*)?\s*[:：.\s]\s*(?P<label>[^\s{#][^{#]{0,78}?)\s*$",
    re.I,
)
_IMPORTED_TBL_CAPTION_RE = re.compile(
    r"^\s*(?:表|表格|Table|Tbl\.?)\s*(?P<num>\d+(?:[-.]\d+)*)?\s*[:：.\s]\s*(?P<label>[^\s{#][^{#]{0,78}?)\s*$",
    re.I,
)
_IMAGE_LINE_RE = re.compile(
    r"^!\[(?P<alt>[^\]]*)\]\((?P<path>[^)\s]+)(?P<tail>[^)]*)\)\s*$"
)


def bind_imported_captions_and_references(lines: List[str]) -> Dict[str, str]:
    """在提取出的章节行列表上原位识别图表题注并重写正文交叉引用（不改变总行数与行号）。

    Returns:
        ``{"fig:1-1": "fig-1-1", "tbl:2-1": "tbl-2-1", ...}`` 映射字典。
    """
    ref_map: Dict[str, str] = {}
    used_ids: Set[str] = set()
    total = len(lines)
    # Entries can contain an entire multi-line table. Translate physical prose
    # line numbers back to entry indices instead of indexing the list directly.
    prose_numbers = {number for number, _ in prose_lines("\n".join(lines))}
    prose_indices = []
    physical_line = 1
    for index, line in enumerate(lines):
        if physical_line in prose_numbers:
            prose_indices.append(index)
        physical_line += line.count("\n") + 1
    prose_index_set = set(prose_indices)

    def _unique_id(base: str) -> str:
        candidate = base
        seq = 2
        while candidate in used_ids:
            candidate = "{0}-{1}".format(base, seq)
            seq += 1
        used_ids.add(candidate)
        return candidate

    for idx in prose_indices:
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith(("#", "<!--", "|", "```", "~~~")):
            continue
        if stripped.endswith(("。", "；", "！", "？")):
            continue

        # 1) 检查是否紧跟在图片行之后的图题注（忽略中间最多 1 个空行）
        prev_idx = idx - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx in prose_index_set and (idx - prev_idx) <= 2:
            img_m = _IMAGE_LINE_RE.match(lines[prev_idx].strip())
            fig_m = _IMPORTED_FIG_CAPTION_RE.match(stripped)
            if img_m and fig_m:
                num = (fig_m.group("num") or "").strip()
                label = fig_m.group("label").strip()
                if label and not label.startswith("{#"):
                    ident = _unique_id(stable_auto_ident("fig", label, num))
                    lines[idx] = "Figure: {0} {{#{1}}}".format(label, ident)
                    if num:
                        ref_map["fig:" + num] = ident
                    ref_map["fig:" + normalize_caption_label(label)] = ident
                    old_alt = img_m.group("alt").strip()
                    if not old_alt or re.match(r"^img_\d+$", old_alt, re.I):
                        lines[prev_idx] = "![{0}]({1}{2})".format(
                            label, img_m.group("path"), img_m.group("tail")
                        )
                    continue

        # 2) 检查是否紧邻在表格（<!-- TBL: / <!-- TABLE: / |）之前的表题注
        next_idx = idx + 1
        while next_idx < total and not lines[next_idx].strip():
            next_idx += 1
        if next_idx < total and (next_idx - idx) <= 2:
            next_line = lines[next_idx].strip()
            is_before_table = (
                next_line.startswith("<!-- TBL:")
                or next_line.startswith("<!-- TABLE:")
                or next_line.startswith("|")
            )
            tbl_m = _IMPORTED_TBL_CAPTION_RE.match(stripped)
            if is_before_table and tbl_m:
                num = (tbl_m.group("num") or "").strip()
                label = tbl_m.group("label").strip()
                if label and not label.startswith("{#"):
                    ident = _unique_id(stable_auto_ident("tbl", label, num))
                    lines[idx] = "Table: {0} {{#{1}}}".format(label, ident)
                    if num:
                        ref_map["tbl:" + num] = ident
                    ref_map["tbl:" + normalize_caption_label(label)] = ident
                    continue

    if not ref_map:
        return ref_map

    # 3) 在普通正文行中将「如图 1-1」「见表 2-1」原位替换为动态引用 @fig-1-1 / @tbl-2-1
    prose_ref_re = re.compile(
        r"(?P<lead>见|如|参见|详见|参看)?(?P<kind>图|表|表格)\s*(?P<num>\d+(?:[-.]\d+)*)"
    )

    def _replace_prose_ref(match: re.Match) -> str:
        lead = match.group("lead") or ""
        kind_word = match.group("kind")
        num = match.group("num")
        key = ("fig:" if kind_word == "图" else "tbl:") + num
        ident = ref_map.get(key)
        if not ident:
            return match.group(0)
        return "{0}@{1}".format(lead, ident)

    for idx in prose_indices:
        line = lines[idx]
        s = line.strip()
        if (
            not s
            or s.startswith(("Figure:", "Table:", "表:", "表：", "图:", "图：", "<!--", "|", "![", "#"))
        ):
            continue
        lines[idx] = prose_ref_re.sub(_replace_prose_ref, line)

    return ref_map


# ---------------------------------------------------------------------------
# 2. 复杂表格（XML Table）可读 Markdown 代理提取与单元格精准回填
# ---------------------------------------------------------------------------

TABLE_PROXY_BEGIN = "<!-- TABLE_PROXY_BEGIN -->"
TABLE_PROXY_END = "<!-- TABLE_PROXY_END -->"


def _cell_visible_text(tc: ET.Element) -> str:
    paragraphs: List[str] = []
    for p in tc.findall(_qn("p")):
        parts: List[str] = []
        for child in p.iter():
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "t" and child.text:
                parts.append(child.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag in ("br", "cr"):
                btype = child.get(_qn("type")) or child.get("type")
                if btype not in ("page", "column"):
                    parts.append("<br>")
        p_txt = "".join(parts).strip()
        if p_txt:
            paragraphs.append(p_txt)
    return "<br>".join(paragraphs)


def _cell_grid_span(tc: ET.Element) -> int:
    tcPr = tc.find(_qn("tcPr"))
    if tcPr is None:
        return 1
    gs = tcPr.find(_qn("gridSpan"))
    if gs is None:
        return 1
    val = gs.get(_qn("val")) or gs.get("val") or "1"
    try:
        return max(1, int(val))
    except ValueError:
        return 1


def _is_vmerge_continue(tc: ET.Element) -> bool:
    tcPr = tc.find(_qn("tcPr"))
    if tcPr is None:
        return False
    vm = tcPr.find(_qn("vMerge"))
    if vm is None:
        return False
    val = (vm.get(_qn("val")) or vm.get("val") or "").strip().lower()
    return val != "restart"


def extract_complex_table_proxy_rows(tbl_elem: ET.Element) -> Tuple[List[List[str]], List[List[Optional[ET.Element]]]]:
    """从复杂 ``<w:tbl>`` 提取对齐后的二维文本矩阵及每个逻辑格对应的主导 ``<w:tc>``。

    合并续格（横向 ``gridSpan > 1`` 的展开格或纵向 ``vMerge=continue`` 格）在
    ``tc_matrix`` 中记录为 ``None``，文本矩阵中填充空串，确保列数规整。
    """
    raw_rows: List[List[str]] = []
    tc_rows: List[List[Optional[ET.Element]]] = []
    max_cols = 0

    for tr in tbl_elem.findall(_qn("tr")):
        row_texts: List[str] = []
        row_tcs: List[Optional[ET.Element]] = []
        for tc in tr.findall(_qn("tc")):
            span = _cell_grid_span(tc)
            is_vcont = _is_vmerge_continue(tc)
            txt = "" if is_vcont else _cell_visible_text(tc)
            row_texts.append(txt)
            row_tcs.append(None if is_vcont else tc)
            for _ in range(span - 1):
                row_texts.append("")
                row_tcs.append(None)
        if row_texts:
            max_cols = max(max_cols, len(row_texts))
            raw_rows.append(row_texts)
            tc_rows.append(row_tcs)

    if max_cols == 0:
        return [], []

    for r_idx in range(len(raw_rows)):
        while len(raw_rows[r_idx]) < max_cols:
            raw_rows[r_idx].append("")
            tc_rows[r_idx].append(None)

    return raw_rows, tc_rows


def format_complex_table_proxy_lines(tbl_elem: ET.Element) -> List[str]:
    """生成紧跟 ``<!-- TABLE:N:tbl_xxxx.xml -->`` 的可读可编辑 Markdown 代理块。"""
    rows, _ = extract_complex_table_proxy_rows(tbl_elem)
    if not rows:
        return []
    cols = len(rows[0])
    out = [TABLE_PROXY_BEGIN]
    header = [c.replace("\\", "\\\\").replace("|", r"\|").replace("\n", "<br>") for c in rows[0]]
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * cols) + " |")
    for row in rows[1:]:
        escaped = [c.replace("\\", "\\\\").replace("|", r"\|").replace("\n", "<br>") for c in row]
        out.append("| " + " | ".join(escaped) + " |")
    out.append(TABLE_PROXY_END)
    return out


def _update_tc_text_preserving_style(tc: ET.Element, new_text: str) -> None:
    """将 ``new_text``（含可选 ``<br>``）写入 ``<w:tc>``，保留首个段落及首个 run 的样式属性。"""
    paragraphs = tc.findall(_qn("p"))
    lines = re.split(r"<br\s*/?>|\n", new_text, flags=re.I)
    if not paragraphs:
        p = ET.SubElement(tc, _qn("p"))
        r = ET.SubElement(p, _qn("r"))
        t = ET.SubElement(r, _qn("t"))
        t.text = lines[0] if lines else ""
        return

    first_p = paragraphs[0]
    first_rPr: Optional[ET.Element] = None
    for r in first_p.findall(_qn("r")):
        rPr = r.find(_qn("rPr"))
        if rPr is not None:
            first_rPr = ET.fromstring(ET.tostring(rPr, encoding="utf-8"))
            break

    keep_children = []
    for child in list(first_p):
        ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if ctag in ("pPr", "bookmarkStart", "bookmarkEnd"):
            keep_children.append(child)
        first_p.remove(child)
    for child in keep_children:
        first_p.append(child)

    r_new = ET.SubElement(first_p, _qn("r"))
    if first_rPr is not None:
        r_new.append(first_rPr)
    for idx, part in enumerate(lines):
        if idx > 0:
            ET.SubElement(r_new, _qn("br"))
        t_el = ET.SubElement(r_new, _qn("t"))
        if part.startswith(" ") or part.endswith(" "):
            t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t_el.text = part

    for extra_p in paragraphs[1:]:
        tc.remove(extra_p)


def apply_complex_table_proxy_edits(
    tbl_elem: ET.Element,
    proxy_rows: Optional[Sequence[Sequence[str]]],
) -> bool:
    """Apply text edits only; unedited cells retain their original XML.

    Shape changes and merged continuation edits cannot be represented losslessly
    by the proxy, so validate the whole grid before mutating any cell.
    """
    if not proxy_rows:
        return False
    orig_rows, tc_matrix = extract_complex_table_proxy_rows(tbl_elem)
    if len(proxy_rows) != len(orig_rows) or any(
        len(new) != len(old) for old, new in zip(orig_rows, proxy_rows)
    ):
        raise ValueError("Complex-table proxy dimensions differ from the original XML")

    def normalized(value):
        return re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.I).replace("\r\n", "\n").strip()

    edits = []
    for row_index, (original, edited) in enumerate(zip(orig_rows, proxy_rows)):
        for column_index, (old, new) in enumerate(zip(original, edited)):
            if normalized(old) == normalized(new):
                continue
            cell = tc_matrix[row_index][column_index]
            if cell is None:
                raise ValueError("Merged continuation cells cannot be edited through the table proxy")
            edits.append((cell, normalized(new)))
    for cell, text in edits:
        _update_tc_text_preserving_style(cell, text)
    return bool(edits)


# ---------------------------------------------------------------------------
# 5. 智能排版：无元数据手写表格自适应列宽与图片 DPI 智能缩放
# ---------------------------------------------------------------------------


def compute_smart_column_widths(
    rows: Sequence[Sequence[str]],
    total_width_dxa: int = 9000,
    min_col_dxa: int = 840,
) -> List[int]:
    """根据每列内容的视觉字符宽度分布计算自适应列宽（单位 dxa/twips）。

    兼顾表头不折行与长文本列按平方根压缩权重分配，避免手写无元数据表格被死板均分。
    """
    if not rows:
        return []
    col_count = max((len(r) for r in rows), default=0)
    if col_count <= 0:
        return []
    if total_width_dxa < col_count:
        raise ValueError("Table width must allow at least one twip per column")
    if col_count == 1:
        return [total_width_dxa]

    def _visual_len(text: str) -> float:
        parts = re.split(r"<br\s*/?>|\n", text or "")
        best = 1.0
        for part in parts:
            score = 0.0
            for ch in part:
                score += 2.0 if ord(ch) > 127 else 1.0
            if score > best:
                best = score
        return best

    header_weights: List[float] = [2.0] * col_count
    max_weights: List[float] = [2.0] * col_count
    for r_idx, row in enumerate(rows):
        for c_idx in range(min(col_count, len(row))):
            vlen = _visual_len(row[c_idx])
            if r_idx == 0:
                header_weights[c_idx] = max(header_weights[c_idx], vlen * 1.15)
            max_weights[c_idx] = max(max_weights[c_idx], vlen)

    weights: List[float] = []
    for c_idx in range(col_count):
        hw = min(header_weights[c_idx], 24.0)
        mw = max_weights[c_idx]
        effective = max(hw, (mw ** 0.68) * 2.2, 3.0)
        weights.append(effective)

    # Reserve a feasible positive floor first, then apportion the remainder.
    # A fixed 360-twip floor can exceed the page width on wide tables.
    minimum = max(1, min(min_col_dxa, total_width_dxa // (col_count * 2)))
    remaining = total_width_dxa - minimum * col_count
    weight_sum = sum(weights) or float(col_count)
    shares = [remaining * weight / weight_sum for weight in weights]
    widths = [minimum + int(share) for share in shares]
    remainder = total_width_dxa - sum(widths)
    ranked = sorted(range(col_count), key=lambda index: shares[index] - int(shares[index]), reverse=True)
    for index in ranked[:remainder]:
        widths[index] += 1
    return widths


def estimate_unannotated_table_natural_width(rows: Sequence[Sequence[str]]) -> int:
    """估算无元数据手写表格在不强行挤压时的自然总宽度（dxa），用于判断是否需要自动横版。"""
    if not rows:
        return 0
    col_count = max((len(r) for r in rows), default=0)
    if col_count <= 5:
        return col_count * 1500
    col_max: List[float] = [4.0] * col_count
    for row in rows:
        for c_idx, cell in enumerate(row):
            for line in re.split(r"<br\s*/?>|\n", cell or ""):
                vlen = sum(2.0 if ord(ch) > 127 else 1.0 for ch in line)
                if vlen > col_max[c_idx]:
                    col_max[c_idx] = min(vlen, 30.0)
    natural = sum(int(m * 105 + 220) for m in col_max)
    return max(natural, col_count * 1350)
