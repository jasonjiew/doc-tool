# -*- coding: utf-8 -*-
"""Mermaid 图形工作台纯服务。

支持围栏 `````mermaid`` 与历史裸 ``flowchart``/``sequenceDiagram`` 段落，
提供带源行号的子集校验、可选 mermaid-cli + 内置 SVG 渲染、QtSvg PNG
栅格化，以及将裸源码批量替换成图片引用的纯函数编排。
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

_QT_APP_REF = None

_KIND_RE = re.compile(r"^\s*(flowchart|sequenceDiagram)\b")
_FLOW_HEADER_RE = re.compile(r"^flowchart\s+(TD|TB|BT|LR|RL)\s*$", re.I)
_SEQ_HEADER_RE = re.compile(r"^sequenceDiagram\s*$")
_NODE_RE = re.compile(
    r"(?P<id>[A-Za-z_][\w-]*)(?:\[\[(?P<sub>.*?)\]\]|\[(?P<box>.*?)\]|\((?P<round>.*?)\)|\{(?P<diamond>.*?)\})?"
)
_EDGE_RE = re.compile(
    r"^(?P<left>.+?)\s*(?:--(?:\|(?P<label>.*?)\|)?>|---|-.->|==>)\s*(?P<right>.+?)\s*$"
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
        if stripped.lower().startswith("```mermaid"):
            start = index
            body: List[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
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
                if not candidate.strip() or candidate.strip().startswith("```"):
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
    label = next((value for value in (match.group("sub"), match.group("box"), match.group("round"), match.group("diamond")) if value is not None), match.group("id"))
    shape = "diamond" if match.group("diamond") is not None else "round" if match.group("round") is not None else "box"
    return match.group("id"), label, shape


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
                edges.append((left[0], right[0], edge.group("label") or ""))
        else:
            node = _parse_node(line)
            if node:
                nodes[node[0]] = node
    if not nodes:
        raise ValueError("flowchart 中没有可渲染节点")
    ordered = list(nodes.values())
    horizontal = direction in ("LR", "RL")
    width = max(360, (len(ordered) * 180 + 40) if horizontal else 520)
    height = max(220, 180 if horizontal else len(ordered) * 110 + 60)
    positions = {}
    for i, node in enumerate(ordered):
        x = 110 + i * 180 if horizontal else width // 2
        y = height // 2 if horizontal else 70 + i * 110
        if direction in ("RL", "BT"):
            x = width - x if horizontal else x
            y = height - y if not horizontal else y
        positions[node[0]] = (x, y)
    body = []
    for left, right, label in edges:
        x1, y1 = positions[left]
        x2, y2 = positions[right]
        body.append('<line x1="{0}" y1="{1}" x2="{2}" y2="{3}" stroke="#53657a" stroke-width="2" marker-end="url(#arrow)"/>'.format(x1, y1, x2, y2))
        if label:
            body.append('<text x="{0}" y="{1}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#334155">{2}</text>'.format((x1+x2)//2, (y1+y2)//2-7, html.escape(label)))
    for node_id, label, shape in ordered:
        x, y = positions[node_id]
        if shape == "diamond":
            points = "{0},{1} {2},{3} {0},{4} {5},{3}".format(x, y-35, x+65, y, y+35, x-65)
            body.append('<polygon points="{0}" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(points))
        else:
            rx = 18 if shape == "round" else 4
            body.append('<rect x="{0}" y="{1}" width="140" height="58" rx="{2}" fill="#eef6ff" stroke="#3b82b8" stroke-width="2"/>'.format(x-70, y-29, rx))
        body.append('<text x="{0}" y="{1}" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="14" fill="#172033">{2}</text>'.format(x, y, html.escape(label)))
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


def _render_with_cli(source: str) -> Optional[RenderResult]:
    executable = shutil.which("mmdc")
    if not executable:
        return None
    with tempfile.TemporaryDirectory(prefix="doc-tool-mermaid-") as temp:
        input_path = Path(temp) / "diagram.mmd"
        output_path = Path(temp) / "diagram.svg"
        input_path.write_text(source, encoding="utf-8")
        try:
            completed = subprocess.run(
                [executable, "-i", str(input_path), "-o", str(output_path), "-b", "white"],
                capture_output=True,
                text=True,
                timeout=30,
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


def render(source: str, kind: Optional[str] = None, *, use_cli: bool = True) -> RenderResult:
    """渲染 Mermaid；CLI 可用时优先，否则使用内置子集渲染器。"""
    actual = kind or detect_kind(source)
    errors = validate(source, actual)
    if errors:
        first = errors[0]
        return RenderResult(False, error="第 {0} 行：{1}".format(first.line, first.message))
    if use_cli:
        cli_result = _render_with_cli(source)
        if cli_result is not None:
            return cli_result
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
