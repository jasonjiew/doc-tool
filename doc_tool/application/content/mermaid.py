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
from typing import Callable, List, Optional, Tuple

_QT_APP_REF = None

_KIND_RE = re.compile(r"^\s*(flowchart|sequenceDiagram)\b")
_FENCE_OPEN_RE = re.compile(r"^(?:`{3,}|~{3,})\s*mermaid\s*$", re.I)
_FENCE_CHAR_RE = re.compile(r"^(?P<char>`{3,}|~{3,})")
_FLOW_HEADER_RE = re.compile(r"^flowchart\s+(TD|TB|BT|LR|RL)\s*$", re.I)
_SEQ_HEADER_RE = re.compile(r"^sequenceDiagram\s*$")
_NODE_RE = re.compile(
    r"(?P<id>[A-Za-z_][\w-]*)"
    r"(?:\[\[(?P<sub>.*?)\]\]"
    r"|\(\((?P<circle>.*?)\)\)"
    r"|\[\((?P<cyl>.*?)\)\]"
    r"|\[(?P<box>.*?)\]"
    r"|\((?P<round>.*?)\)"
    r"|\{(?P<diamond>.*?)\})?"
)
_EDGE_RE = re.compile(
    r"^(?P<left>.+?)\s*(?:--(?:\|(?P<label>.*?)\|)?>|---|-.->|==>)"
    r"(?:\|(?P<label2>.*?)\|)?\s*(?P<right>.+?)\s*$"
)
_SEQ_MESSAGE_RE = re.compile(
    r"^\s*([A-Za-z_][\w-]*)\s*(-->>|->>|-->|->|-x|--x|-\)|--\))\s*"
    r"([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$"
)


@dataclass(frozen=True)
class MermaidBlock:
    start_line: int
    end_line: int
    source: str
    kind: str
    fenced: bool = False


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


def detect_kind(source: str) -> str:
    match = _KIND_RE.match(source or "")
    return match.group(1) if match else ""


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
            source = "\n".join(body).strip("\n")
            blocks.append(
                MermaidBlock(start + 1, end + 1, source, detect_kind(source), True)
            )
            index = end + 1
            continue
        kind_match = _KIND_RE.match(lines[index])
        if kind_match:
            start = index
            body = [lines[index]]
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if not candidate.strip() or _FENCE_CHAR_RE.match(candidate.strip()):
                    break
                if candidate.lstrip().startswith("#"):
                    break
                body.append(candidate)
                index += 1
            blocks.append(
                MermaidBlock(
                    start + 1,
                    start + len(body),
                    "\n".join(body),
                    kind_match.group(1),
                    False,
                )
            )
            continue
        index += 1
    return blocks


def _balanced_error(line: str) -> Optional[str]:
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
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != pairs[char]:
                return "括号不匹配"
    if quote:
        return "引号未闭合"
    if stack:
        return "括号未闭合"
    return None


def validate(source: str, kind: Optional[str] = None) -> List[MermaidError]:
    """校验 flowchart/sequenceDiagram 子集，错误行相对源码从 1 开始。"""
    lines = source.splitlines()
    actual = kind or detect_kind(source)
    if not lines or not source.strip():
        return [MermaidError(1, "Mermaid 源码为空")]
    if actual not in ("flowchart", "sequenceDiagram"):
        return [MermaidError(1, "不支持的图类型；当前支持 flowchart 与 sequenceDiagram")]
    header_ok = _FLOW_HEADER_RE.match(lines[0].strip()) if actual == "flowchart" else _SEQ_HEADER_RE.match(lines[0].strip())
    errors: List[MermaidError] = []
    if not header_ok:
        expected = "flowchart TD/LR/RL/BT/TB" if actual == "flowchart" else "sequenceDiagram"
        errors.append(MermaidError(1, "图类型声明无效，应为 {0}".format(expected)))
    for number, raw in enumerate(lines[1:], start=2):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        balance = _balanced_error(line)
        if balance:
            errors.append(MermaidError(number, balance))
            continue
        if actual == "flowchart":
            if re.match(r"^(subgraph\b|end$|direction\b|classDef\b|class\b|style\b|linkStyle\b|click\b)", line):
                continue
            edge = _EDGE_RE.match(line)
            if edge:
                if _NODE_RE.fullmatch(edge.group("left").strip()) is None or _NODE_RE.fullmatch(edge.group("right").strip()) is None:
                    errors.append(MermaidError(number, "边定义的节点语法无效"))
                continue
            if _NODE_RE.fullmatch(line) is None:
                errors.append(MermaidError(number, "无法识别的 flowchart 节点或边定义"))
        else:
            if _SEQ_MESSAGE_RE.match(line):
                continue
            if re.match(r"^(participant|actor)\s+[A-Za-z_][\w-]*(?:\s+as\s+.+)?$", line):
                continue
            if re.match(r"^(activate|deactivate)\s+[A-Za-z_][\w-]*$", line):
                continue
            if re.match(r"^(Note\s+(?:left of|right of|over)\s+.+:.+|alt\b.*|else\b.*|opt\b.*|loop\b.*|par\b.*|and\b.*|rect\b.*|end$|autonumber$)", line):
                continue
            errors.append(MermaidError(number, "无法识别的 sequenceDiagram 语句"))
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
    return match.group("id"), label, shape


_FONT_SIZE = 14
_LABEL_FONT_SIZE = 12
_NODE_PAD_X = 14
_NODE_PAD_Y = 10
_LINE_HEIGHT = 17
_RANK_GAP = 80
_NODE_GAP = 26
_TEXT_MAX_WIDTH = 230


def _text_width(text: str, size: int = _FONT_SIZE) -> float:
    """估算文本宽度：CJK 全宽，ASCII/数字约半宽。"""
    return sum(size if ord(ch) > 0x2E7F else size * 0.58 for ch in text)


def _wrap_text(text: str, max_width: float, size: int = _FONT_SIZE) -> List[str]:
    """按估算宽度折行，返回行列表。"""
    lines: List[str] = []
    current = ""
    current_w = 0.0
    for ch in text:
        w = _text_width(ch, size)
        if current and current_w + w > max_width:
            lines.append(current)
            current = ch
            current_w = w
        else:
            current += ch
            current_w += w
    if current:
        lines.append(current)
    return lines or [""]


def _node_size(label: str, shape: str) -> Tuple[float, float]:
    """根据文本内容与形状计算节点尺寸。"""
    target = min(_text_width(label), _TEXT_MAX_WIDTH)
    lines = _wrap_text(label, target)
    text_w = max(_text_width(line) for line in lines)
    width = max(120.0, text_w + 2 * _NODE_PAD_X)
    height = len(lines) * _LINE_HEIGHT + 2 * _NODE_PAD_Y
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
        points = "{0},{1} {2},{3} {0},{4} {5},{3}".format(
            x + w / 2, y, x + w, y + h / 2, x + w / 2, y + h, x, y + h / 2
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


def _render_flowchart_svg(source: str) -> Tuple[bytes, int, int]:
    lines = source.splitlines()
    direction = _FLOW_HEADER_RE.match(lines[0].strip()).group(1).upper()
    nodes = {}
    edges = []
    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        edge = _EDGE_RE.match(line)
        if edge:
            left = _parse_node(edge.group("left"))
            right = _parse_node(edge.group("right"))
            if left and right:
                nodes[left[0]] = left
                nodes[right[0]] = right
                edges.append((left[0], right[0], edge.group("label") or edge.group("label2") or ""))
        else:
            node = _parse_node(line)
            if node:
                nodes[node[0]] = node
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
    for raw in source.splitlines()[1:]:
        line = raw.strip()
        participant = re.match(r"^(?:participant|actor)\s+([A-Za-z_][\w-]*)(?:\s+as\s+(.+))?$", line)
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


def svg_to_png(svg: bytes, width: int, height: int) -> bytes:
    """用 PySide6.QtSvg 把 SVG 栅格化为 PNG。"""
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    # 桌面应用中已有 QApplication；纯服务/测试进程可能没有，QtSvg 在此状态
    # 下创建绘制设备会原生崩溃，因此建立并持有最小 QGuiApplication。
    global _QT_APP_REF
    if QGuiApplication.instance() is None:
        _QT_APP_REF = QGuiApplication([])

    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        raise ValueError("SVG 渲染结果无效")
    image = QImage(max(1, width), max(1, height), QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
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


def _render_with_cli(source: str) -> Optional[RenderResult]:
    executable = _find_mmdc()
    if not executable:
        return None
    with tempfile.TemporaryDirectory(prefix="doc-tool-mermaid-") as temp:
        input_path = Path(temp) / "diagram.mmd"
        output_path = Path(temp) / "diagram.svg"
        input_path.write_text(source, encoding="utf-8")
        command = [executable, "-i", str(input_path), "-o", str(output_path), "-b", "white"]
        puppeteer_config = _cli_puppeteer_config()
        if puppeteer_config:
            command += ["-p", puppeteer_config]
        # Windows 上 npm 安装的 mmdc 是 .cmd 脚本，须经 cmd.exe 启动。
        if executable.lower().endswith((".cmd", ".bat")):
            command = [os.environ.get("COMSPEC", "cmd.exe"), "/c"] + command
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0 or not output_path.exists():
            return None
        svg = output_path.read_bytes()
        size = re.search(rb'<svg[^>]*viewBox="[^\"]*\s([\d.]+)\s([\d.]+)"', svg)
        width, height = (int(float(size.group(1))), int(float(size.group(2)))) if size else (960, 540)
        try:
            png = svg_to_png(svg, width, height)
        except (ImportError, ValueError, RuntimeError):
            png = None
        return RenderResult(True, svg, png, width, height, "mermaid-cli", None)


def render(source: str, kind: Optional[str] = None, *, use_cli: bool = True, use_web: bool = False) -> RenderResult:
    """渲染 Mermaid；后端优先级 CLI > web(官方 mermaid.js) > 内置子集渲染器。

    - ``use_cli=True``（默认）：mermaid-cli 可用时优先用之（官方渲染，适合导出）。
    - ``use_web=False``（默认）：进程内 QtWebEngine 跑官方 mermaid.min.js，单帧
      几十~几百 ms，适合实时预览。web 不可用（无 bundle / 无 QtWebEngine /
      初始化失败 / 永久禁用）时静默回退，永不抛异常。
    - 两者都关或都不可用时走内置子集 SVG 渲染器（永远可用，alt/loop/Note 等
      结构不渲染）。

    语法先用项目子集校验器把关：不支持的图类型在进任何后端前即报错，确保
    回退路径行为可预测（web/CLI 不被子集外的输入拖入不可控分支）。
    """
    actual = kind or detect_kind(source)
    errors = validate(source, actual)
    if errors:
        first = errors[0]
        return RenderResult(False, error="第 {0} 行：{1}".format(first.line, first.message))
    if use_cli:
        cli_result = _render_with_cli(source)
        if cli_result is not None:
            return cli_result
    if use_web:
        from doc_tool.application.content.mermaid_web import render_web

        web_result = render_web(source)
        if web_result is not None:
            # web 端 ok 或编译错误都直接回传（编译错误信息更准，便于用户改源码）。
            return web_result
    try:
        if actual == "flowchart":
            svg, width, height = _render_flowchart_svg(source)
        elif actual == "sequenceDiagram":
            svg, width, height = _render_sequence_svg(source)
        else:
            return RenderResult(False, error="无可用渲染后端：请安装 mermaid-cli 或改用受支持图类型")
        try:
            png = svg_to_png(svg, width, height)
        except (ImportError, ValueError, RuntimeError) as exc:
            return RenderResult(False, svg=svg, width=width, height=height, backend="builtin-svg", error="QtSvg PNG 栅格化失败：{0}".format(exc))
        return RenderResult(True, svg, png, width, height, "builtin", None)
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
        newline = "\n" if lines and any(line.endswith("\n") for line in lines) else ""
        replacements.append((block.start_line - 1, block.end_line, reference + newline))
    for start, end, reference in reversed(replacements):
        lines[start:end] = [reference]
    return BatchConversionResult("".join(lines), len(replacements), tuple(failures))
