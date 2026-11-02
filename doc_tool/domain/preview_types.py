# -*- coding: utf-8 -*-
"""纯配置、块注册表与预览结果数据模型（纯 Python 数据结构，无 Qt 依赖）。

满足 REQ-ED-01、REQ-MD-05、REQ-MD-06、REQ-MD-08、REQ-MM-01、REQ-MM-04、REQ-MM-06。
可在无 GUI 进程、CLI、单元测试及后台任务中安全导入和使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class PreviewMode(str, Enum):
    """侧边预览运行模式。"""
    FIDELITY = "fidelity"        # 高保真 Markdown 阅读预览（QWebEngine + markdown-it + 官方 Mermaid）
    LIGHTWEIGHT = "lightweight"  # 原生轻量近似预览（QTextBrowser，兜底与低开销模式）


@dataclass(frozen=True)
class BlockLocation:
    """Markdown 结构块与原始来源映射。"""
    block_id: str
    source_file: str
    start_line: int
    end_line: int
    kind: str  # heading, paragraph, list, table, mermaid, code, callout, module
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def contains_line(self, line_no: int) -> bool:
        return self.start_line <= line_no <= self.end_line


@dataclass
class BlockRegistry:
    """当前文档快照的结构化块注册表，防止来自页面的伪造路径或越界定位。"""
    snapshot_id: str
    source_file: str
    blocks: List[BlockLocation] = field(default_factory=list)
    _id_index: Dict[str, BlockLocation] = field(default_factory=dict, init=False)
    _heading_index: Dict[str, BlockLocation] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.rebuild_indices()

    def rebuild_indices(self) -> None:
        self._id_index = {b.block_id: b for b in self.blocks}
        self._heading_index = {b.title.strip(): b for b in self.blocks if b.kind == "heading" and b.title}

    def add_block(self, block: BlockLocation) -> None:
        self.blocks.append(block)
        self._id_index[block.block_id] = block
        if block.kind == "heading" and block.title:
            self._heading_index[block.title.strip()] = block

    def find_by_id(self, block_id: str) -> Optional[BlockLocation]:
        return self._id_index.get(block_id)

    def find_by_heading(self, heading_text: str) -> Optional[BlockLocation]:
        cleaned = heading_text.strip()
        if cleaned in self._heading_index:
            return self._heading_index[cleaned]
        for title, block in self._heading_index.items():
            if cleaned == title or cleaned in title or title in cleaned:
                return block
        return None

    def find_by_line(self, line_no: int) -> Optional[BlockLocation]:
        for block in self.blocks:
            if block.contains_line(line_no):
                return block
        return None


@dataclass
class DiagramIdentity:
    """图形身份元数据契约（D6）。"""
    block_id: str
    source_file: str
    start_line: int
    source_hash: str
    engine_version: str
    config_hash: str
    backend: str  # "official-webengine", "python-approximate", "official-cli"
    is_fidelity: bool = True
    logical_width: float = 0.0
    logical_height: float = 0.0
    has_foreign_object: bool = False
    svg_content: Optional[str] = None
    png_bytes: Optional[bytes] = None
    error: Optional[str] = None
    warning: Optional[str] = None


@dataclass
class PreviewSnapshot:
    """页面渲染快照，用于校验返回结果的版本一致性。"""
    session_id: str
    chapter_id: str
    buffer_version: int
    text_hash: str
    theme: str = "light"
    is_dark: bool = False
    block_registry: Optional[BlockRegistry] = None
    timestamp: float = 0.0

    def is_current(self, other_session: str, other_chapter: str, other_version: int) -> bool:
        return (
            self.session_id == other_session
            and self.chapter_id == other_chapter
            and self.buffer_version == other_version
        )


def build_block_registry(
    text: str,
    source_file: str = "",
    snapshot_id: str = "",
    prepared_line_map: Optional[Dict[int, Tuple[str, int]]] = None,
) -> BlockRegistry:
    """从 Markdown 源码或准备结果构建结构化块注册表（REQ-MD-04、REQ-MD-06）。
    
    能够准确映射重复标题、多段相同代码/图表及展开模块来源行。
    """
    import re
    registry = BlockRegistry(snapshot_id=snapshot_id, source_file=source_file)
    lines = (text or "").splitlines()
    total = len(lines)
    i = 0

    while i < total:
        line = lines[i]
        line_no = i + 1
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 1. 标题
        if stripped.startswith("#"):
            m = re.match(r"^(#{1,6})\s+(.*?)\s*$", stripped)
            if m:
                title = m.group(2)
                real_file = source_file
                real_line = line_no
                metadata = {}
                if prepared_line_map and line_no in prepared_line_map:
                    real_file, real_line = prepared_line_map[line_no]
                    metadata["mapped_from"] = f"{source_file}:{line_no}"
                registry.add_block(BlockLocation(
                    block_id=f"line-{line_no}",
                    source_file=real_file,
                    start_line=real_line,
                    end_line=real_line,
                    kind="heading",
                    title=title,
                    metadata=metadata,
                ))
                i += 1
                continue

        # 2. 围栏代码块 / Mermaid
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            info = stripped[3:].strip()
            start_l = line_no
            end_l = line_no
            code_lines = []
            i += 1
            while i < total:
                cur = lines[i]
                if cur.strip().startswith(fence):
                    end_l = i + 1
                    i += 1
                    break
                code_lines.append(cur)
                end_l = i + 1
                i += 1
            kind = "mermaid" if info.lower() == "mermaid" else "code"
            real_file = source_file
            real_start = start_l
            real_end = end_l
            metadata = {"info": info, "code": "\n".join(code_lines)}
            if prepared_line_map and start_l in prepared_line_map:
                real_file, real_start = prepared_line_map[start_l]
                if end_l in prepared_line_map:
                    _, real_end = prepared_line_map[end_l]
                else:
                    real_end = real_start + (end_l - start_l)
            registry.add_block(BlockLocation(
                block_id=f"line-{start_l}",
                source_file=real_file,
                start_line=real_start,
                end_line=real_end,
                kind=kind,
                metadata=metadata,
            ))
            continue

        # 3. 提示块
        if stripped.startswith(">"):
            start_l = line_no
            end_l = line_no
            is_callout = bool(re.search(r">\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", stripped, re.I))
            i += 1
            while i < total and lines[i].strip().startswith(">"):
                end_l = i + 1
                i += 1
            real_file = source_file
            real_start = start_l
            real_end = end_l
            metadata = {}
            if prepared_line_map and start_l in prepared_line_map:
                real_file, real_start = prepared_line_map[start_l]
                if end_l in prepared_line_map:
                    _, real_end = prepared_line_map[end_l]
                else:
                    real_end = real_start + (end_l - start_l)
            registry.add_block(BlockLocation(
                block_id=f"line-{start_l}",
                source_file=real_file,
                start_line=real_start,
                end_line=real_end,
                kind="callout" if is_callout else "quote",
                metadata=metadata,
            ))
            continue

        # 4. 表格
        if stripped.startswith("|") and stripped.endswith("|"):
            start_l = line_no
            end_l = line_no
            i += 1
            while i < total and lines[i].strip().startswith("|"):
                end_l = i + 1
                i += 1
            real_file = source_file
            real_start = start_l
            real_end = end_l
            if prepared_line_map and start_l in prepared_line_map:
                real_file, real_start = prepared_line_map[start_l]
                if end_l in prepared_line_map:
                    _, real_end = prepared_line_map[end_l]
                else:
                    real_end = real_start + (end_l - start_l)
            registry.add_block(BlockLocation(
                block_id=f"line-{start_l}",
                source_file=real_file,
                start_line=real_start,
                end_line=real_end,
                kind="table",
            ))
            continue

        # 5. 普通段落或列表
        start_l = line_no
        end_l = line_no
        is_list = bool(re.match(r"^(\*|-|\+|\d+\.)\s+", stripped))
        i += 1
        while i < total and lines[i].strip() and not lines[i].strip().startswith(("#", "```", "~~~", ">", "|")):
            end_l = i + 1
            i += 1
        real_file = source_file
        real_start = start_l
        real_end = end_l
        if prepared_line_map and start_l in prepared_line_map:
            real_file, real_start = prepared_line_map[start_l]
            if end_l in prepared_line_map:
                _, real_end = prepared_line_map[end_l]
            else:
                real_end = real_start + (end_l - start_l)
        registry.add_block(BlockLocation(
            block_id=f"line-{start_l}",
            source_file=real_file,
            start_line=real_start,
            end_line=real_end,
            kind="list" if is_list else "paragraph",
        ))

    return registry
