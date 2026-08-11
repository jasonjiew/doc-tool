# -*- coding: utf-8 -*-
"""md 结构渲染：把 .md 文本解析为可渲染块。

预览复用 build 合并链路所依据的同一类结构（标题分级/段落/表格/图片占位），
但以轻量自包含方式解析，不依赖 Word COM 内核，供编辑器侧边即时预览。

解析块：
- ``heading``：`#`~`######` 标题，含级别。
- ``paragraph``：普通文本行。
- ``table``：`|` 管道表格，rows 为单元格二维列表。
- ``image``：`![alt](path)`，含 alt 与路径。
- ``blank``：空段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# 表格指令注释（如 <!-- TBL:style=... -->），预览时跳过。
_HTML_COMMENT_RE = re.compile(r"^\s*<!--")
# 空段落标记（构建链路插入），预览时跳过。
_EMPTY_PAR_RE = re.compile(r"^\s*<EMPTY_PAR/>\s*$")
# 标题。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# 图片。
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+=(\d+)x(\d+))?")


@dataclass
class PreviewBlock:
    """渲染块。"""

    kind: str  # heading | paragraph | table | image | blank
    level: int = 0  # heading 级别 1-6
    text: str = ""
    rows: List[List[str]] = field(default_factory=list)  # table
    image_path: str = ""
    image_size: Optional[str] = None


def render_preview_blocks(md_text: str) -> List[PreviewBlock]:
    """把 md 文本解析为渲染块列表。"""
    blocks: List[PreviewBlock] = []
    table_rows: List[List[str]] = []
    in_table = False

    def flush_table() -> None:
        nonlocal table_rows, in_table
        if in_table:
            # 去掉表头分隔行（-- | --）
            body = [
                row
                for row in table_rows
                if not all(re.fullmatch(r":?-+:?", cell) for cell in row)
            ]
            if body:
                blocks.append(PreviewBlock(kind="table", rows=body))
        table_rows = []
        in_table = False

    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped or _EMPTY_PAR_RE.match(line) or _HTML_COMMENT_RE.match(line):
            flush_table()
            continue
        heading_match = _HEADING_RE.match(stripped)
        if heading_match is not None:
            flush_table()
            blocks.append(
                PreviewBlock(
                    kind="heading",
                    level=len(heading_match.group(1)),
                    text=heading_match.group(2),
                )
            )
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            table_rows.append(cells)
            in_table = True
            continue
        if in_table:
            flush_table()
        image_match = _IMAGE_RE.match(stripped)
        if image_match is not None:
            alt = image_match.group(1)
            path = image_match.group(2)
            size = None
            if image_match.group(3):
                size = "{0}x{1}".format(image_match.group(3), image_match.group(4))
            blocks.append(
                PreviewBlock(
                    kind="image",
                    text=alt,
                    image_path=path,
                    image_size=size,
                )
            )
            continue
        blocks.append(PreviewBlock(kind="paragraph", text=stripped))

    flush_table()
    return blocks


def preview_summary(md_text: str) -> str:
    """给出一段 md 的结构摘要（用于编辑器状态栏提示）。"""
    blocks = render_preview_blocks(md_text)
    counts = {"heading": 0, "paragraph": 0, "table": 0, "image": 0}
    for block in blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    return "标题 {0} · 段落 {1} · 表格 {2} · 图片 {3}".format(
        counts["heading"],
        counts["paragraph"],
        counts["table"],
        counts["image"],
    )
