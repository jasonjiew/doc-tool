# -*- coding: utf-8 -*-
"""Mermaid 图形工作台纯服务。

支持反引号/波浪号围栏 `````mermaid``/``~~~mermaid`` 与历史裸 ``flowchart``/``sequenceDiagram`` 段落，
提供带源行号的子集校验、可选 mermaid-cli + 内置 SVG 渲染、QtSvg PNG
栅格化，以及将裸源码批量替换成图片引用的纯函数编排。
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_QT_APP_REF = None

_HTML_COMMENT_RE = re.compile(r"^\s*(?:<!--[\s\S]*?-->|<EMPTY_PAR\s*/?>)\s*$", re.I)

# 所有受支持的 Mermaid 标准图表类型字典（归一化为标准小驼峰/小写名）。
_ALL_DIAGRAM_KINDS: Dict[str, str] = {
    "flowchart": "flowchart",
    "graph": "flowchart",
    "sequencediagram": "sequenceDiagram",
    "classdiagram": "classDiagram",
    "classdiagram-v2": "classDiagram",
    "statediagram": "stateDiagram",
    "statediagram-v2": "stateDiagram",
    "erdiagram": "erDiagram",
    "gantt": "gantt",
    "pie": "pie",
    "gitgraph": "gitGraph",
    "mindmap": "mindmap",
    "timeline": "timeline",
    "quadrantchart": "quadrantChart",
    "requirementdiagram": "requirementDiagram",
    "journey": "journey",
    "zenuml": "zenuml",
    "sankey-beta": "sankey",
    "sankey": "sankey",
    "xychart-beta": "xychart",
    "xychart": "xychart",
    "block-beta": "block",
    "block": "block",
    "packet-beta": "packet",
    "kanban": "kanban",
    "architecture-beta": "architecture",
    "c4context": "c4",
    "c4container": "c4",
    "c4component": "c4",
    "c4dynamic": "c4",
    "c4deployment": "c4",
}

_KIND_RE = re.compile(
    r"^\s*("
    r"flowchart\b|graph\b|sequenceDiagram\b|classDiagram(?:-v2)?\b|"
    r"stateDiagram(?:-v2)?\b|erDiagram\b|gantt\b|pie\b|gitGraph\b|"
    r"mindmap\b|timeline\b|quadrantChart\b|requirementDiagram\b|"
    r"journey\b|zenuml\b|sankey(?:-beta)?\b|xychart(?:-beta)?\b|"
    r"block(?:-beta)?\b|packet(?:-beta)?\b|kanban\b|architecture(?:-beta)?\b|"
    r"c4context\b|c4container\b|c4component\b|c4dynamic\b|c4deployment\b"
    r")",
    re.I,
)
_FENCE_OPEN_RE = re.compile(r"^(?:`{3,}|~{3,})\s*mermaid\s*$", re.I)
_FENCE_CHAR_RE = re.compile(r"^(?P<char>`{3,}|~{3,})")
_FLOW_HEADER_RE = re.compile(r"^(?:flowchart|graph)(?:\s+(TD|TB|BT|LR|RL))?\s*;?$", re.I)
_SEQ_HEADER_RE = re.compile(r"^sequenceDiagram\s*;?$", re.I)
_PIE_HEADER_RE = re.compile(r"^pie(?:\s+showData)?(?:\s+title\s+.+)?\s*;?$", re.I)
_PIE_LINE_RE = re.compile(r"^(?:title\s+.+|showData|(?:\".+?\"|[^:\n]+?)\s*:\s*[\d.]+\s*;?)$", re.I)
_GIT_GRAPH_HEADER_RE = re.compile(r"^gitGraph(?:\s*:\s*)?$", re.I)
_GIT_GRAPH_LINE_RE = re.compile(r"^(?:commit\b|branch\b|checkout\b|merge\b|cherry-pick\b)", re.I)
_FLOW_KEYWORDS_RE = re.compile(
    r"^(?:subgraph\b|end$|direction\b|classDef\b|class\b|style\b|linkStyle\b|click\b)",
    re.I,
)
_SEQ_KEYWORDS_RE = re.compile(
    r"^(?:participant|actor|activate|deactivate|Note\b|alt\b|else\b|opt\b|loop\b|par\b|and\b|rect\b|end$|autonumber$)",
    re.I,
)
_NODE_RE = re.compile(
    r"(?P<id>\w[\w/.-]*)"
    r"(?:(?:\*\*)?\[\[(?:\*\*)?(?P<sub>.*?)(?:\*\*)?\]\](?:\*\*)?"
    r"|(?:\*\*)?\(\((?:\*\*)?(?P<circle>.*?)(?:\*\*)?\)\)(?:\*\*)?"
    r"|(?:\*\*)?\[\((?:\*\*)?(?P<cyl>.*?)(?:\*\*)?\)\](?:\*\*)?"
    r"|(?:\*\*)?\[(?:\*\*)?(?P<box>.*?)(?:\*\*)?\](?:\*\*)?"
    r"|(?:\*\*)?\((?:\*\*)?(?P<round>.*?)(?:\*\*)?\)(?:\*\*)?"
    r"|(?:\*\*)?\{(?:\*\*)?(?P<diamond>.*?)(?:\*\*)?\}(?:\*\*)?)?"
)
_EDGE_RE = re.compile(
    r"^(?P<left>.+?)\s*"
    r"(?:"
    r"--\s*(?:\|(?P<label>.*?)\|\s*)?-*>"
    r"|--\s*(?P<txt>[^-|>][^|>]*?)\s*-->"
    r"|--\s*(?P<txt2>[^-|>][^|>]*?)\s*---"
    r"|-\.\s*(?P<txt3>[^-|>][^|>]*?)\s*\.->"
    r"|==\s*(?P<txt4>[^-|>][^|>]*?)\s*==>"
    r"|---|-.->|==>)"
    r"(?:\s*\|(?P<label2>.*?)\|)?\s*(?P<right>.+?)\s*;?$"
)
_CHAIN_LINK_RE = re.compile(
    r"\s*(?:"
    r"(?:-->|---|-.->|==>)\s*\|(?P<label1>.*?)\|\s*"
    r"|--\s*\|(?P<label2>.*?)\|\s*-*>?"
    r"|--\s*(?P<label3>[^-|>][^|>]*?)\s*-->"
    r"|--\s*(?P<label4>[^-|>][^|>]*?)\s*---"
    r"|-\.\s*(?P<label5>[^-|>][^|>]*?)\s*\.->"
    r"|==\s*(?P<label6>[^-|>][^|>]*?)\s*==>"
    r"|-->|---|-.->|==>"
    r")\s*"
)


def _split_chain_edges(line: str):
    """链式边切分 [(左节点, 右节点, 标签)] 列表。

    支持无标签链式连线：``A --> B --> C``，
    以及带标签链式连线：``A -->|text| B --> C`` 或 ``A -- text --> B --> C``。
    若不是有效的链式边（例如单条边或节点语法无效），返回 None 交给单条边逻辑处理。
    """
    line_clean = line.rstrip(";").strip()
    matches = list(_CHAIN_LINK_RE.finditer(line_clean))
    if len(matches) < 2:
        return None
    segs = []
    labels = []
    last_end = 0
    for m in matches:
        seg = line_clean[last_end:m.start()].strip()
        if not seg:
            return None
        segs.append(seg)
        lbl = (
            m.group("label1")
            or m.group("label2")
            or m.group("label3")
            or m.group("label4")
            or m.group("label5")
            or m.group("label6")
            or ""
        ).strip()
        labels.append(lbl)
        last_end = m.end()
    final_seg = line_clean[last_end:].strip()
    if not final_seg:
        return None
    segs.append(final_seg)
    if any(_NODE_RE.fullmatch(seg) is None for seg in segs):
        return None
    return [(segs[i], segs[i + 1], labels[i]) for i in range(len(segs) - 1)]
_SEQ_MESSAGE_RE = re.compile(
    r"^\s*(\w[\w/.-]*)\s*(-->>|->>|-->|->|-x|--x|-\)|--\))\s*"
    r"(\w[\w/.-]*)\s*:\s*(.+?)\s*$"
)


def _is_flowchart_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("%%") or _HTML_COMMENT_RE.match(s):
        return True
    if _FLOW_KEYWORDS_RE.match(s):
        return True
    if _split_chain_edges(s) is not None:
        return True
    if _EDGE_RE.match(s):
        return True
    m = _NODE_RE.fullmatch(s.rstrip(";").strip())
    if m is not None and any(
        m.group(g) is not None
        for g in ("sub", "circle", "cyl", "box", "round", "diamond")
    ):
        return True
    return False


def _is_sequence_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("%%") or _HTML_COMMENT_RE.match(s):
        return True
    if _SEQ_MESSAGE_RE.match(s):
        return True
    if _SEQ_KEYWORDS_RE.match(s):
        return True
    return False


def _find_header_line(lines: Sequence[str]) -> Tuple[int, str]:
    """寻找跳过 frontmatter、指令、注释后的 Mermaid 图表声明行；返回 (行下标, 去空白行内容)。"""
    idx = 0
    # 检查是否以 YAML frontmatter (---) 开头
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue
        if line == "---":
            # 找到 frontmatter 结束
            idx += 1
            while idx < len(lines):
                if lines[idx].strip() == "---":
                    idx += 1
                    break
                idx += 1
            continue
        break

    while idx < len(lines):
        s = lines[idx].strip()
        if not s or s.startswith("%%") or _HTML_COMMENT_RE.match(s):
            idx += 1
            continue
        return idx, s
    return -1, ""


@dataclass(frozen=True)
class MermaidBlock:
    start_line: int
    end_line: int
    source: str
    kind: str
    fenced: bool = False
    content_start_line: int = 0


@dataclass(frozen=True)
class MermaidError:
    line: int
    message: str


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    svg: Optional[bytes] = None
    png: Optional[bytes] = None
    width: Optional[int] = None
    height: Optional[int] = None
    backend: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class BatchFailure:
    line: int
    message: str


@dataclass(frozen=True)
class BatchConversionResult:
    text: str
    success_count: int
    failures: Tuple[BatchFailure, ...]


# 渲染结果内存缓存：避免编辑器敲字时频繁重复启动子进程渲染相同内容。
_RENDER_CACHE: Dict[Tuple[str, str, bool], RenderResult] = {}
_MAX_RENDER_CACHE = 128


def detect_kind(source: str) -> str:
    """检测 Mermaid 源码对应的图表类型（如 flowchart、sequenceDiagram、classDiagram 等）。"""
    lines = (source or "").splitlines()
    _, header_line = _find_header_line(lines)
    if not header_line:
        return ""
    match = _KIND_RE.match(header_line)
    if match:
        token = match.group(1).split()[0].lower()
        return _ALL_DIAGRAM_KINDS.get(token, token)
    return ""


def extract_blocks(md_text: str) -> List[MermaidBlock]:
    """识别 Mermaid 围栏块与裸源码段落，行号为 1-based、首尾均含。"""
    lines = md_text.splitlines()
    blocks: List[MermaidBlock] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if _FENCE_OPEN_RE.match(stripped):
            start = index
            fence_char = stripped[0]
            body: List[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index].strip()
                if candidate.startswith(fence_char * 3):
                    break
                body.append(lines[index])
                index += 1
            end = index if index < len(lines) else max(start, len(lines) - 1)
            source = "\n".join(body).rstrip()
            blocks.append(
                MermaidBlock(
                    start + 1,
                    end + 1,
                    source,
                    detect_kind(source),
                    True,
                    content_start_line=start + 2,
                )
            )
            index = end + 1
            continue
        kind_match = _KIND_RE.match(lines[index])
        if kind_match:
            raw_kind = kind_match.group(1).split()[0].lower()
            kind = _ALL_DIAGRAM_KINDS.get(raw_kind, raw_kind)
            if kind == "flowchart":
                is_stmt = _is_flowchart_line
            elif kind == "sequenceDiagram":
                is_stmt = _is_sequence_line
            elif kind == "pie":
                is_stmt = lambda s: bool(not s or s.startswith("%%") or _HTML_COMMENT_RE.match(s) or _PIE_LINE_RE.match(s))
            elif kind == "gitGraph":
                is_stmt = lambda s: bool(not s or s.startswith("%%") or _HTML_COMMENT_RE.match(s) or _GIT_GRAPH_LINE_RE.match(s))
            else:
                is_stmt = lambda s: bool(
                    not s
                    or s.startswith("%%")
                    or _HTML_COMMENT_RE.match(s)
                    or (
                        not s.startswith("#")
                        and not s.startswith("|")
                        and not s.startswith("<!-- TBL:")
                        and not s.startswith("![")
                        and not _KIND_RE.match(s)
                    )
                )

            block_start = index
            if index > 0 and _HTML_COMMENT_RE.match(lines[index - 1].strip()):
                if index == 1 or not lines[index - 2].strip():
                    block_start = index - 1

            clean_body: List[str] = [lines[index].strip()]
            last_content_idx = index
            scan = index + 1

            while scan < len(lines):
                candidate = lines[scan]
                cand_strip = candidate.strip()
                if (
                    _FENCE_CHAR_RE.match(cand_strip)
                    or cand_strip.startswith("#")
                    or cand_strip.startswith("|")
                    or cand_strip.startswith("<!-- TBL:")
                    or cand_strip.startswith("![")
                    or _KIND_RE.match(cand_strip)
                ):
                    break

                if not cand_strip or _HTML_COMMENT_RE.match(cand_strip):
                    # 向前探测后续是否有属于本图的有效语句
                    peek = scan + 1
                    found_next = False
                    while peek < len(lines):
                        p_strip = lines[peek].strip()
                        if not p_strip or _HTML_COMMENT_RE.match(p_strip):
                            peek += 1
                            continue
                        if (
                            _FENCE_CHAR_RE.match(p_strip)
                            or p_strip.startswith("#")
                            or p_strip.startswith("|")
                            or p_strip.startswith("<!-- TBL:")
                            or p_strip.startswith("![")
                            or _KIND_RE.match(p_strip)
                        ):
                            break
                        if is_stmt(p_strip):
                            found_next = True
                        break
                    if not found_next:
                        break
                    scan += 1
                    continue

                if is_stmt(cand_strip):
                    clean_body.append(cand_strip)
                    last_content_idx = scan
                    scan += 1
                else:
                    break

            source = "\n".join(clean_body)
            blocks.append(
                MermaidBlock(
                    block_start + 1,
                    last_content_idx + 1,
                    source,
                    kind,
                    False,
                    content_start_line=index + 1,
                )
            )
            index = last_content_idx + 1
            continue
        index += 1
    return blocks


def _balanced_error(line: str, kind: str = "") -> Optional[str]:
    # ER 关系图中的 cardinality 连线（如 ||--o{、}|..|{）将 {} 作为关系端点符，不作括号校验
    if kind == "erDiagram":
        return None
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: List[str] = []
    quote: Optional[str] = None
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char in "([{":
            # 类图的多行花括号由外部跨行栈管理，行内不报未闭合
            if kind == "classDiagram" and char == "{":
                continue
            stack.append(char)
        elif char in ")]}":
            if kind == "classDiagram" and char == "}":
                continue
            if not stack or stack.pop() != pairs[char]:
                return "括号不匹配"
    if quote:
        return "引号未闭合"
    if stack:
        return "括号未闭合"
    return None


def validate(source: str, kind: Optional[str] = None) -> List[MermaidError]:
    """校验 Mermaid 语法（兼容全量 Mermaid 图表格式），错误行相对源码从 1 开始。"""
    lines = (source or "").splitlines()
    if not lines or not source.strip():
        return [MermaidError(1, "Mermaid 源码为空")]

    header_idx, header_line = _find_header_line(lines)
    if header_idx == -1 or not header_line:
        return [MermaidError(1, "Mermaid 源码为空")]

    match = _KIND_RE.match(header_line)
    if not match:
        return [MermaidError(header_idx + 1, "无法识别的 Mermaid 图类型声明: '{0}'".format(header_line))]

    raw_token = match.group(1).split()[0].lower()
    actual = kind or _ALL_DIAGRAM_KINDS.get(raw_token, raw_token)

    errors: List[MermaidError] = []

    # 针对各类型声明行的特定检查
    if actual == "flowchart":
        if not _FLOW_HEADER_RE.match(header_line):
            errors.append(MermaidError(header_idx + 1, "flowchart/graph 方向声明无效，应为 TD/TB/BT/LR/RL"))
    elif actual == "sequenceDiagram":
        if not _SEQ_HEADER_RE.match(header_line):
            errors.append(MermaidError(header_idx + 1, "sequenceDiagram 声明语法无效"))
    elif actual == "pie":
        if not _PIE_HEADER_RE.match(header_line):
            errors.append(MermaidError(header_idx + 1, "pie 声明语法无效，形如 pie 或 pie title 标题"))
    elif actual == "gitGraph":
        if not _GIT_GRAPH_HEADER_RE.match(header_line):
            errors.append(MermaidError(header_idx + 1, "gitGraph 声明语法无效，形如 gitGraph:"))

    # 类图跨行花括号栈
    class_brace_stack: List[int] = []

    for number, raw in enumerate(lines[header_idx + 1:], start=header_idx + 2):
        line = raw.strip()
        if not line or line.startswith("%%") or _HTML_COMMENT_RE.match(line):
            continue

        balance = _balanced_error(line, actual)
        if balance:
            errors.append(MermaidError(number, balance))
            continue

        if actual == "classDiagram":
            for ch in line:
                if ch == "{":
                    class_brace_stack.append(number)
                elif ch == "}":
                    if not class_brace_stack:
                        errors.append(MermaidError(number, "括号不匹配（有多余的 '}'）"))
                        break
                    class_brace_stack.pop()
        elif actual == "flowchart":
            if re.match(r"^(subgraph\b|end$|direction\b|classDef\b|class\b|style\b|linkStyle\b|click\b)", line):
                continue
            if _split_chain_edges(line) is not None:
                # 链式边（A --> B --> C）是合法 Mermaid 语法：按箭头拆成
                # 多条边校验，必须置于单边正则之前，避免右段被误判为单个节点。
                continue
            edge = _EDGE_RE.match(line)
            if edge:
                if _NODE_RE.fullmatch(edge.group("left").strip()) is None or _NODE_RE.fullmatch(edge.group("right").strip()) is None:
                    errors.append(MermaidError(number, "边定义的节点语法无效"))
                continue
            if _NODE_RE.fullmatch(line.rstrip(";").strip()) is None:
                errors.append(MermaidError(number, "无法识别的 flowchart 节点或边定义"))
        elif actual == "sequenceDiagram":
            if _SEQ_MESSAGE_RE.match(line):
                continue
            if re.match(r"^(?:participant|actor)\s+\w[\w/.-]*(?:\s+as\s+.+)?$", line, re.I):
                continue
            if re.match(r"^(?:activate|deactivate)\s+\w[\w/.-]*$", line, re.I):
                continue
            if re.match(r"^(?:Note\s+(?:left of|right of|over)\s+.+:.+|alt\b.*|else\b.*|opt\b.*|loop\b.*|par\b.*|and\b.*|rect\b.*|end$|autonumber$)", line, re.I):
                continue
            errors.append(MermaidError(number, "无法识别的 sequenceDiagram 语句"))
        elif actual == "pie":
            if not _PIE_LINE_RE.match(line):
                errors.append(MermaidError(number, "无法识别的 pie 数据项语法，格式应为 \"标签\" : 数值"))
        elif actual == "gitGraph":
            if not _GIT_GRAPH_LINE_RE.match(line):
                errors.append(MermaidError(number, "无法识别的 gitGraph 语句，支持 commit/branch/checkout/merge 等"))

    if actual == "classDiagram" and class_brace_stack:
        errors.append(MermaidError(class_brace_stack[-1], "类定义花括号 '{' 未闭合"))

    return errors


def _svg_document(width: int, height: int, body: str) -> bytes:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}" '
        'viewBox="0 0 {0} {1}"><defs><marker id="arrow" markerWidth="10" '
        'markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L0,6 L9,3 z" fill="#53657a"/></marker></defs>'
        '<rect width="100%" height="100%" fill="#ffffff"/>{2}</svg>'
    ).format(width, height, body)
    return svg.encode("utf-8")


def _parse_node(text: str):
    match = _NODE_RE.fullmatch(text.strip())
    if match is None:
        return None
    shape = "box"
    label = match.group("id")
    for name in ("sub", "circle", "cyl", "box", "round", "diamond"):
        value = match.group(name)
        if value is not None:
            label = value
            shape = name
            break
    label = label.strip()
    if label.startswith("**") and label.endswith("**") and len(label) >= 4:
        label = label[2:-2].strip()
    if (label.startswith('"') and label.endswith('"')) or (label.startswith("'") and label.endswith("'")):
        if len(label) >= 2:
            label = label[1:-1]
    if label.startswith("**") and label.endswith("**") and len(label) >= 4:
        label = label[2:-2].strip()
    return match.group("id"), label, shape


_FONT_SIZE = 14
_LABEL_FONT_SIZE = 12
_NODE_PAD_X = 14
_NODE_PAD_Y = 10
_LINE_HEIGHT = 18
_RANK_GAP = 80
_NODE_GAP = 26
_TEXT_MAX_WIDTH = 380


def _text_width(text: str, size: int = _FONT_SIZE) -> float:
    """估算文本宽度：CJK 全宽，ASCII/数字约半宽。"""
    return sum(size if ord(ch) > 0x2E7F else size * 0.58 for ch in text)


def _wrap_text(text: str, max_width: float, size: int = _FONT_SIZE) -> List[str]:
    """按估算宽度折行，返回行列表。

    支持 <br> / \\n 显式换行；优先在空白或英文/数字/标识符边界折行，
    避免将 DeviceUploadProto oneof 这种单词在中间尴尬劈断。
    """
    raw_paragraphs = re.split(r"<br\s*/?>|\n", text, flags=re.IGNORECASE)
    all_lines: List[str] = []

    for raw in raw_paragraphs:
        tokens = re.findall(r"\s+|[a-zA-Z0-9_\-\./:]+|[\u4e00-\u9fff]|.", raw)
        if not tokens:
            all_lines.append("")
            continue
        current = ""
        current_w = 0.0
        for token in tokens:
            if not current and token.isspace():
                continue
            w = _text_width(token, size)
            if current and current_w + w > max_width:
                all_lines.append(current.rstrip())
                current = token.lstrip()
                current_w = _text_width(current, size)
            elif not current and w > max_width:
                for ch in token:
                    cw = _text_width(ch, size)
                    if current and current_w + cw > max_width:
                        all_lines.append(current)
                        current = ch
                        current_w = cw
                    else:
                        current += ch
                        current_w += cw
            else:
                current += token
                current_w += w
        if current:
            all_lines.append(current.rstrip())

    return all_lines or [""]


def _node_size(label: str, shape: str) -> Tuple[float, float]:
    """根据文本内容与形状计算节点尺寸。"""
    target = min(_text_width(label), _TEXT_MAX_WIDTH)
    lines = _wrap_text(label, target)
    text_w = max(_text_width(line) for line in lines) if lines else 100.0
    width = max(120.0, text_w + 2 * _NODE_PAD_X)
    height = max(38.0, len(lines) * _LINE_HEIGHT + 2 * _NODE_PAD_Y)
    if shape == "diamond":
        width += 40
        height += 36
    elif shape == "cyl":
        width += 12
        height += 10
    elif shape == "circle":
        width = height = max(width, height)
    return width, height


def _shape_svg(shape: str, x: float, y: float, w: float, h: float) -> str:
    """绘制节点外框（矩形/圆角/菱形/圆柱/圆形），返回 SVG 片段。"""
    if shape == "diamond":
        # 顶点顺序：上(中心x, 顶y) 右(右x, 中心y) 下(中心x, 底y) 左(左x, 中心y)。
        # 注意 {4} 是中心 x、{5} 是底 y、{6} 是左 x：误用会把下/左顶点画到
        # (中心x, 中心x) 与 (底y, 中心y) 的错位坐标上。
        points = "{0},{1} {2},{3} {0},{4} {5},{3}".format(
            x + w / 2, y, x + w, y + h / 2, y + h, x
        )
        return '<polygon points="{0}" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(points)
    if shape == "cyl":
        rx = 8.0
        cx = x + w / 2
        top_y = y + rx
        bot_y = y + h - rx
        side = '<path d="M {0} {1} L {0} {2} A {3} {3} 0 0 0 {4} {2} L {4} {1} A {3} {3} 0 0 0 {0} {1} Z" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(
            x, top_y, bot_y, rx, x + w
        )
        top = '<ellipse cx="{0}" cy="{1}" rx="{2}" ry="{3}" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(
            cx, top_y, w / 2, rx
        )
        bottom = '<ellipse cx="{0}" cy="{1}" rx="{2}" ry="{3}" fill="#ffffff" stroke="#3b82b8" stroke-width="2"/>'.format(
            cx, bot_y, w / 2, rx
        )
        return side + top + bottom
    if shape == "circle":
        cx, cy = x + w / 2, y + h / 2
        return '<ellipse cx="{0}" cy="{1}" rx="{2}" ry="{3}" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(
            cx, cy, w / 2, h / 2
        )
    rx = h / 2 if shape == "round" else 5
    return '<rect x="{0}" y="{1}" width="{2}" height="{3}" rx="{4}" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(
        x, y, w, h, rx
    )


def _merge_node(nodes: Dict, parsed) -> None:
    """把解析出的节点并入节点表；已存在时不覆盖（保留首次定义的形状/标签）。

    后续边可能用裸 id 引用节点（``B --> C``），裸 id 解析为 shape=box 且
    标签=id，直接覆盖会把先前 ``B{校验通过?}`` 的菱形定义退化成方框、标签
    被改写成 ``B``。仅当既存节点是裸 id（box/标签=id）而新定义带形状时升级。
    """
    if parsed is None:
        return
    nid, label, shape = parsed
    existing = nodes.get(nid)
    if existing is None:
        nodes[nid] = parsed
    elif existing[2] == "box" and existing[1] == nid and (shape != "box" or label != nid):
        # 裸 id 先出现、带形状/真实标签后出现（``A --> B`` 在前、
        # ``B{...} --> C`` 或 ``B[真实标签]`` 在后）：升级为后出现的定义。
        nodes[nid] = parsed


def _render_flowchart_svg(source: str) -> Tuple[bytes, int, int]:
    lines = source.splitlines()
    header_idx, header_line = _find_header_line(lines)
    if header_idx == -1 or not header_line:
        raise ValueError("flowchart 源码为空")

    direction_match = _FLOW_HEADER_RE.match(header_line)
    direction = (
        direction_match.group(1).upper()
        if direction_match and direction_match.group(1)
        else "TD"
    )
    nodes = {}
    edges = []
    for raw in lines[header_idx + 1:]:
        line = raw.strip()
        if not line or line.startswith("%%") or _HTML_COMMENT_RE.match(line):
            continue
        if _FLOW_KEYWORDS_RE.match(line):
            continue
        chain = _split_chain_edges(line)
        if chain is not None:
            # 链式边：A --> B --> C 或 A -->|label| B --> C
            for left_text, right_text, label in chain:
                left = _parse_node(left_text)
                right = _parse_node(right_text)
                if left and right:
                    _merge_node(nodes, left)
                    _merge_node(nodes, right)
                    edges.append((left[0], right[0], label))
            continue
        edge = _EDGE_RE.match(line)
        if edge:
            left = _parse_node(edge.group("left"))
            right = _parse_node(edge.group("right"))
            if left and right:
                _merge_node(nodes, left)
                _merge_node(nodes, right)
                label = (
                    edge.group("label")
                    or edge.group("label2")
                    or edge.group("txt")
                    or edge.group("txt2")
                    or edge.group("txt3")
                    or edge.group("txt4")
                    or ""
                ).strip()
                edges.append((left[0], right[0], label))
            continue
        _merge_node(nodes, _parse_node(line.rstrip(";").strip()))
    if not nodes:
        raise ValueError("flowchart 中没有可渲染节点")

    # 1) 按最长路径分层（单调递增，天然防环）
    rank = {nid: 0 for nid in nodes}
    for _ in range(len(nodes)):
        changed = False
        for nid in nodes:
            best = rank[nid]
            for u, v, _ in edges:
                if v == nid and rank[u] + 1 > best:
                    best = rank[u] + 1
            if best != rank[nid]:
                rank[nid] = best
                changed = True
        if not changed:
            break
    ranks: Dict[int, List[str]] = {}
    for nid in nodes:
        ranks.setdefault(rank[nid], []).append(nid)
    rank_list = sorted(ranks)

    # 2) 层内排序：前驱中位数（barycenter）迭代，减少边交叉
    for _ in range(5):
        for r in rank_list:
            items = ranks[r]

            def _key(nid, items=items, r=r):
                pos = items.index(nid)
                preds = []
                for u, v, _ in edges:
                    if v == nid:
                        preds.append(ranks[rank[u]].index(u))
                if not preds:
                    return (0.0, pos)
                preds.sort()
                return (preds[len(preds) // 2], pos)

            ranks[r] = sorted(items, key=_key)

    # 3) 坐标：LR/RL 按列分层，TD/TB/BT 按行分层
    sizes = {nid: _node_size(label, shape) for nid, (_, label, shape) in nodes.items()}
    horizontal = direction in ("LR", "RL")
    positions = {}
    if horizontal:
        rank_widths = [max(sizes[n][0] for n in ranks[r]) for r in rank_list]
        x_offsets = {}
        x = 30.0
        for r, rw in zip(rank_list, rank_widths):
            x_offsets[r] = x
            x += rw + _RANK_GAP
        total_w = x - _RANK_GAP + 30
        max_col_h = max(
            sum(sizes[n][1] for n in ranks[r]) + _NODE_GAP * (len(ranks[r]) - 1)
            for r in rank_list
        )
        for r in rank_list:
            items = ranks[r]
            col_h = sum(sizes[n][1] for n in items) + _NODE_GAP * (len(items) - 1)
            y = (max_col_h - col_h) / 2 + 30
            rw = rank_widths[rank_list.index(r)]
            for nid in items:
                w, h = sizes[nid]
                positions[nid] = (x_offsets[r] + (rw - w) / 2, y)
                y += h + _NODE_GAP
        total_h = max_col_h + 60
    else:
        rank_heights = [max(sizes[n][1] for n in ranks[r]) for r in rank_list]
        y_offsets = {}
        y = 30.0
        for r, rh in zip(rank_list, rank_heights):
            y_offsets[r] = y
            y += rh + _RANK_GAP
        total_h = y - _RANK_GAP + 30
        max_row_w = max(
            sum(sizes[n][0] for n in ranks[r]) + _NODE_GAP * (len(ranks[r]) - 1)
            for r in rank_list
        )
        for r in rank_list:
            items = ranks[r]
            row_w = sum(sizes[n][0] for n in items) + _NODE_GAP * (len(items) - 1)
            x = (max_row_w - row_w) / 2 + 30
            rh = rank_heights[rank_list.index(r)]
            for nid in items:
                w, h = sizes[nid]
                positions[nid] = (x, y_offsets[r] + (rh - h) / 2)
                x += w + _NODE_GAP
        total_w = max_row_w + 60
    if direction == "RL":
        for nid in positions:
            px, py = positions[nid]
            positions[nid] = (total_w - px - sizes[nid][0], py)
    elif direction == "BT":
        for nid in positions:
            px, py = positions[nid]
            positions[nid] = (px, total_h - py - sizes[nid][1])

    body = []
    # 4) 先画边线，再画边标签（白底防压线、避让节点），最后画节点（覆盖穿越线）
    for left, right, label in edges:
        x1, y1 = positions[left]
        x2, y2 = positions[right]
        w1, h1 = sizes[left]
        w2, h2 = sizes[right]
        if horizontal:
            sx, sy = x1 + w1, y1 + h1 / 2
            tx, ty = x2, y2 + h2 / 2
        else:
            sx, sy = x1 + w1 / 2, y1 + h1
            tx, ty = x2 + w2 / 2, y2
        body.append(
            '<line x1="{0}" y1="{1}" x2="{2}" y2="{3}" stroke="#53657a" stroke-width="2" marker-end="url(#arrow)"/>'.format(
                sx, sy, tx, ty
            )
        )
        if label:
            lw = _text_width(label, _LABEL_FONT_SIZE)
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            offset = 0.0
            while offset < 90:
                lx0, ly0 = mx - lw / 2 - 5, my + offset - 9
                lx1, ly1 = lx0 + lw + 10, ly0 + 18
                hit = False
                for nid in positions:
                    px, py = positions[nid]
                    pw, ph = sizes[nid]
                    if lx0 < px + pw and lx1 > px and ly0 < py + ph and ly1 > py:
                        hit = True
                        break
                if not hit:
                    break
                offset += 18
            body.append(
                '<rect x="{0}" y="{1}" width="{2}" height="18" rx="3" fill="#ffffff" stroke="#d7dee8"/>'.format(
                    mx - lw / 2 - 5, my + offset - 9, lw + 10
                )
            )
            body.append(
                '<text x="{0}" y="{1}" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="12" fill="#334155">{2}</text>'.format(
                    mx, my + offset, html.escape(label)
                )
            )
    for nid, (_, label, shape) in nodes.items():
        x, y = positions[nid]
        w, h = sizes[nid]
        body.append(_shape_svg(shape, x, y, w, h))
        text_lines = _wrap_text(label, min(_text_width(label), _TEXT_MAX_WIDTH))
        ty = y + h / 2 - (len(text_lines) - 1) * _LINE_HEIGHT / 2
        for line in text_lines:
            body.append(
                '<text x="{0}" y="{1}" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="14" fill="#172033">{2}</text>'.format(
                    x + w / 2, ty, html.escape(line)
                )
            )
            ty += _LINE_HEIGHT
    width, height = int(round(total_w)), int(round(total_h))
    return _svg_document(width, height, "".join(body)), width, height


def _render_sequence_svg(source: str) -> Tuple[bytes, int, int]:
    participants: List[str] = []
    labels = {}
    messages = []
    lines = source.splitlines()
    header_idx, header_line = _find_header_line(lines)
    if header_idx == -1 or not header_line:
        raise ValueError("sequenceDiagram 源码为空")
    for raw in lines[header_idx + 1:]:
        line = raw.strip()
        if not line or line.startswith("%%") or _HTML_COMMENT_RE.match(line):
            continue
        participant = re.match(r"^(?:participant|actor)\s+(\w[\w/.-]*)(?:\s+as\s+(.+))?$", line)
        if participant:
            name = participant.group(1)
            if name not in participants:
                participants.append(name)
            labels[name] = participant.group(2) or name
            continue
        message = _SEQ_MESSAGE_RE.match(line)
        if message:
            left, arrow, right, label = message.groups()
            for name in (left, right):
                if name not in participants:
                    participants.append(name)
                    labels[name] = name
            messages.append((left, right, label, "--" in arrow))
    if not participants:
        raise ValueError("sequenceDiagram 中没有可渲染参与者")
    width = max(420, len(participants) * 180 + 80)
    height = max(240, len(messages) * 75 + 150)
    positions = {name: 70 + i * ((width - 140) / max(1, len(participants) - 1)) for i, name in enumerate(participants)}
    body = []
    for name in participants:
        x = positions[name]
        body.append('<rect x="{0}" y="20" width="120" height="42" rx="4" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(x-60))
        body.append('<text x="{0}" y="42" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="14">{1}</text>'.format(x, html.escape(labels[name])))
        body.append('<line x1="{0}" y1="62" x2="{0}" y2="{1}" stroke="#94a3b8" stroke-dasharray="5 4"/>'.format(x, height-25))
    for index, (left, right, label, dashed) in enumerate(messages):
        y = 100 + index * 70
        body.append('<line x1="{0}" y1="{2}" x2="{1}" y2="{2}" stroke="#53657a" stroke-width="2" {3} marker-end="url(#arrow)"/>'.format(positions[left], positions[right], y, 'stroke-dasharray="6 4"' if dashed else ""))
        body.append('<text x="{0}" y="{1}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#334155">{2}</text>'.format((positions[left]+positions[right])/2, y-8, html.escape(label)))
    return _svg_document(width, height, "".join(body)), width, height


def svg_to_png(svg: bytes, width: int, height: int, scale: float = 3.0) -> bytes:
    """用 PySide6.QtSvg 把 SVG 栅格化为高质量 PNG（默认 3x 超采样抗锯齿，写入物理 DPI）。"""
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    # 桌面应用中已有 QApplication；纯服务/测试进程可能没有，QtSvg 在此状态
    # 下创建绘制设备会原生崩溃，因此建立并持有最小 QGuiApplication。
    # QGuiApplication 只能在主线程创建：后台线程（如 TaskRunner）首次调用且
    # 无实例时给出明确错误而非原生崩溃；主线程已建 app 时后台线程仍可栅格化。
    global _QT_APP_REF
    if QGuiApplication.instance() is None:
        import threading

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("QtSvg PNG 栅格化首次调用必须在主线程执行")
        try:
            from PySide6.QtWidgets import QApplication
            _QT_APP_REF = QApplication([])
        except Exception:
            _QT_APP_REF = QGuiApplication([])

    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        raise ValueError("SVG 渲染结果无效")
    target_w = max(1, int(round(width * scale)))
    target_h = max(1, int(round(height * scale)))
    image = QImage(target_w, target_h, QImage.Format.Format_ARGB32)
    # 写入物理分辨率（DPI = 96 * scale），使 Word/看图软件按正确的物理尺寸展示高清图片，避免被模糊拉伸
    dpi = 96.0 * scale
    dpm = int(round(dpi / 0.0254))
    image.setDotsPerMeterX(dpm)
    image.setDotsPerMeterY(dpm)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("PNG 编码失败")
    return bytes(buffer.data())


def _repo_root() -> Path:
    """doc_tool/application/content/mermaid.py -> 仓库根目录。"""
    return Path(__file__).resolve().parents[3]


def _find_mmdc() -> Optional[str]:
    """定位 mermaid-cli：优先 PATH，其次项目本地 tools/mermaid-cli（免管理员安装）。"""
    executable = shutil.which("mmdc")
    if executable:
        return executable
    root = _repo_root()
    for candidate in (
        root / "tools" / "mermaid-cli" / "node_modules" / ".bin" / "mmdc.cmd",
        root / "tools" / "mermaid-cli" / "node_modules" / ".bin" / "mmdc",
        root / "node_modules" / ".bin" / "mmdc.cmd",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _cli_puppeteer_config() -> Optional[str]:
    """项目本地 mermaid-cli 的 puppeteer 配置（指向系统浏览器），供 mmdc -p 使用。"""
    candidate = _repo_root() / "tools" / "mermaid-cli" / "puppeteer-config.json"
    return str(candidate) if candidate.is_file() else None


def cli_available() -> bool:
    """mermaid-cli 是否可用（PATH 或项目本地）。"""
    return _find_mmdc() is not None


def _clean_source_for_cli(source: str) -> str:
    cleaned = []
    for line in source.splitlines():
        s = line.strip()
        if not s or _HTML_COMMENT_RE.match(s):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _render_with_cli(source: str, want_png: bool = True) -> Optional[RenderResult]:
    executable = _find_mmdc()
    if not executable:
        return None
    with tempfile.TemporaryDirectory(prefix="doc-tool-mermaid-") as temp:
        input_path = Path(temp) / "diagram.mmd"
        output_svg = Path(temp) / "diagram.svg"
        output_png = Path(temp) / "diagram.png"
        input_path.write_text(_clean_source_for_cli(source), encoding="utf-8")
        base_cmd = [executable, "-i", str(input_path), "-b", "white"]
        puppeteer_config = _cli_puppeteer_config()
        if puppeteer_config:
            base_cmd += ["-p", puppeteer_config]
        # Windows 上 npm 安装的 mmdc 是 .cmd 脚本，须经 cmd.exe 启动。
        if executable.lower().endswith((".cmd", ".bat")):
            base_cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c"] + base_cmd

        if not want_png:
            # 极速矢量预览模式：Chromium 仅渲染纯 SVG，跳过昂贵的 3x PNG 渲染
            svg_cmd = base_cmd + ["-o", str(output_svg)]
            try:
                completed_svg = subprocess.run(
                    svg_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if completed_svg.returncode != 0 or not output_svg.exists():
                err_text = completed_svg.stderr or completed_svg.stdout or ""
                m = re.search(r"Parse error on line \d+:[\s\S]*?(?=\n\s*at\b|\Z)", err_text)
                clean_err = m.group(0).strip() if m else (err_text.splitlines()[0] if err_text.strip() else "mermaid-cli 渲染失败")
                return RenderResult(False, error=clean_err)
            svg = output_svg.read_bytes()
            size = re.search(rb'<svg[^>]*viewBox="[^"]*\s([\d.]+)\s([\d.]+)"', svg)
            width, height = (int(float(size.group(1))), int(float(size.group(2)))) if size else (960, 540)
            return RenderResult(True, svg, None, width, height, "mermaid-cli", None)

        # 1. 优先直接由 Chromium 生成视网膜 3x 超清 PNG，确保 CSS/foreignObject 完美渲染且无单词截断
        png_cmd = base_cmd + ["-o", str(output_png), "-s", "3"]
        try:
            completed_png = subprocess.run(
                png_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        completed_svg = None
        err_png = completed_png.stderr or completed_png.stdout or ""
        is_syntax_err = "Parse error" in err_png or "Syntax error" in err_png
        if not is_syntax_err:
            # 2. 同时生成 SVG 供矢量图预览
            svg_cmd = base_cmd + ["-o", str(output_svg)]
            try:
                completed_svg = subprocess.run(
                    svg_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                completed_svg = None

        if (completed_png.returncode != 0 and (completed_svg is None or completed_svg.returncode != 0)) or (not output_png.exists() and not output_svg.exists()):
            err_text = completed_png.stderr or completed_png.stdout or (completed_svg.stderr if completed_svg else "") or ""
            m = re.search(r"Parse error on line \d+:[\s\S]*?(?=\n\s*at\b|\Z)", err_text)
            if m:
                clean_err = m.group(0).strip()
            else:
                lines_err = [
                    line.strip()
                    for line in err_text.splitlines()
                    if line.strip() and not line.strip().startswith("at ")
                ]
                clean_err = lines_err[0] if lines_err else "mermaid-cli 渲染失败"
            return RenderResult(False, error=clean_err)

        svg = output_svg.read_bytes() if output_svg.exists() else None
        width, height = 960, 540
        if svg:
            size = re.search(rb'<svg[^>]*viewBox="[^"]*\s([\d.]+)\s([\d.]+)"', svg)
            if size:
                width, height = int(float(size.group(1))), int(float(size.group(2)))

        png = None
        if output_png.exists():
            png = output_png.read_bytes()
        elif svg:
            try:
                png = svg_to_png(svg, width, height)
            except (ImportError, ValueError, RuntimeError):
                png = None

        return RenderResult(True, svg, png, width, height, "mermaid-cli", None)


def render(
    source: str,
    kind: Optional[str] = None,
    *,
    use_cli: bool = True,
    want_png: bool = True,
) -> RenderResult:
    """渲染 Mermaid：CLI 可用时优先，否则使用子集渲染器。
    
    ``want_png`` 为 False 时仅生成纯矢量 SVG，跳过昂贵的 CPU 软件光栅化，
    专用于极速毫秒级预览；导出到 Word 等需要物理位图的场景传 True。
    """
    actual = kind or detect_kind(source)
    errors = validate(source, actual)
    if errors:
        first = errors[0]
        return RenderResult(False, error="第 {0} 行：{1}".format(first.line, first.message))

    cache_key = (source.strip(), actual, use_cli, want_png)
    if cache_key in _RENDER_CACHE:
        return _RENDER_CACHE[cache_key]

    # CLI 优先策略：有 CLI，走 CLI 官方渲染
    if use_cli:
        cli_result = _render_with_cli(source, want_png=want_png)
        if cli_result is not None:
            if cli_result.ok:
                if len(_RENDER_CACHE) >= _MAX_RENDER_CACHE:
                    _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
                _RENDER_CACHE[cache_key] = cli_result
                return cli_result
            # 若 CLI 执行失败但图表是支持的 flowchart/sequenceDiagram，
            # 回退内置渲染器（避免环境问题导致渲染全挂）
            if actual not in ("flowchart", "sequenceDiagram"):
                return cli_result

    try:
        if actual == "flowchart":
            svg, width, height = _render_flowchart_svg(source)
        elif actual == "sequenceDiagram":
            svg, width, height = _render_sequence_svg(source)
        else:
            return RenderResult(False, error="内置渲染暂不支持此图表类型（{0}），需要启用 mermaid-cli 渲染".format(actual))

        # 预览场景仅需轻量矢量 SVG（耗时 1~2ms），彻底跳过极其昂贵的 3x PNG 软件光栅化（1200ms+）
        if not want_png:
            result = RenderResult(True, svg, None, width, height, "builtin", None)
            if len(_RENDER_CACHE) >= _MAX_RENDER_CACHE:
                _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
            _RENDER_CACHE[cache_key] = result
            return result

        try:
            png = svg_to_png(svg, width, height)
        except (ImportError, ValueError, RuntimeError) as exc:
            return RenderResult(False, svg=svg, width=width, height=height, backend="builtin-svg", error="QtSvg PNG 栅格化失败：{0}".format(exc))
        result = RenderResult(True, svg, png, width, height, "builtin", None)
        if len(_RENDER_CACHE) >= _MAX_RENDER_CACHE:
            _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
        _RENDER_CACHE[cache_key] = result
        return result
    except (ValueError, OSError) as exc:
        return RenderResult(False, error=str(exc))


def next_mermaid_name(assets_root, doc_type: str, ext: str = "png") -> str:
    folder = Path(assets_root) / doc_type / "images"
    pattern = re.compile(r"^mermaid_(\d+)\." + re.escape(ext) + r"$", re.I)
    maximum = 0
    if folder.is_dir():
        for child in folder.iterdir():
            match = pattern.match(child.name)
            if match:
                maximum = max(maximum, int(match.group(1)))
    return "mermaid_{0:04d}.{1}".format(maximum + 1, ext)


def export_png(result: RenderResult, assets_root, doc_type: str) -> str:
    """保存成功渲染结果，返回 ``images/mermaid_NNNN.png``。"""
    if not result.ok or not result.png:
        raise ValueError(result.error or "没有可导出的 PNG")
    folder = Path(assets_root) / doc_type / "images"
    folder.mkdir(parents=True, exist_ok=True)
    name = next_mermaid_name(assets_root, doc_type)
    (folder / name).write_bytes(result.png)
    return "images/{0}".format(name)


def image_reference(target: str, result: RenderResult, alt: str = "图") -> str:
    suffix = ""
    if result.width and result.height:
        suffix = " ={0}x{1}".format(result.width, result.height)
    return "![{0}]({1}{2})".format(alt, target, suffix)


def batch_convert(
    md_text: str,
    exporter: Callable[[MermaidBlock, RenderResult], str],
    *,
    include_fenced: bool = False,
    use_cli: bool = True,
) -> BatchConversionResult:
    """逐个渲染并替换 Mermaid 源码；exporter 返回完整 Markdown 引用。"""
    blocks = [block for block in extract_blocks(md_text) if include_fenced or not block.fenced]
    lines = md_text.splitlines(keepends=True)
    replacements = []
    failures: List[BatchFailure] = []
    for block in blocks:
        result = render(block.source, block.kind, use_cli=use_cli)
        if not result.ok:
            failures.append(BatchFailure(block.start_line, result.error or "渲染失败"))
            continue
        try:
            reference = exporter(block, result)
        except Exception as exc:  # noqa: BLE001
            failures.append(BatchFailure(block.start_line, str(exc)))
            continue
        newline = "\r\n" if "\r\n" in md_text else ("\n" if "\n" in md_text else "")
        replacements.append((block.start_line - 1, block.end_line, reference + newline))
    for start, end, reference in reversed(replacements):
        lines[start:end] = [reference]
    return BatchConversionResult("".join(lines), len(replacements), tuple(failures))
