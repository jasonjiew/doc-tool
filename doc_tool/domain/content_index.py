# -*- coding: utf-8 -*-
"""内容索引数据模型。

内容操作能力（全文搜索/引用分析/术语检查）共用的内存索引模型。
打开项目后对 ``content/<类型>`` 下全部 .md 做一次扫描构建，之后增量维护。

三类结构：
- 文件与行索引（``FileEntry``/``lines``）：供全文搜索按行扫描与定位。
- 标题清单（``HeadingEntry``）：供锚点解析与重复标题/术语检查。
- 引用索引（``FileReference``）：供反向引用与悬空引用检测，由引用解析模块填充。

所有 ``rel_path`` 统一使用相对 contentRoot 的 POSIX 风格字符串作为键，
避免 Windows 路径分隔符差异导致索引键漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

# 引用类型常量。
REF_LINK = "link"  # markdown 链接 [文本](目标)
REF_SECTION = "section"  # 章节号引用，如 3.7.10
REF_ANCHOR = "anchor"  # 文件内标题锚点引用
REF_IMAGE = "image"  # markdown 图片链接，指向资源图片

# 悬空引用确定性分类。
DANGLING_CONFIRMED = "confirmed"  # 确定缺失（路径/章节号在索引中不存在）
DANGLING_SUSPECT = "suspect"  # 疑似（无法可靠判定，不阻断操作）


@dataclass(frozen=True)
class FileEntry:
    """内容文件条目：contentRoot 下的一个 .md 文件。"""

    rel_path: str  # 相对 contentRoot 的 POSIX 路径，如 requirement/第1章 引言/1.1 目的.md
    document_type: str  # requirement | design | general
    line_count: int

    @property
    def name(self) -> str:
        """文件名（含扩展名）。"""
        return Path(self.rel_path).name

    @property
    def parent(self) -> str:
        """所在目录（相对 contentRoot，POSIX）。根目录为 "."。"""
        return Path(self.rel_path).parent.as_posix()

    @property
    def stem(self) -> str:
        """不带扩展名的文件名。"""
        return Path(self.rel_path).stem


@dataclass(frozen=True)
class LineHit:
    """单行命中：全文搜索与引用定位的原子单位。"""

    rel_path: str  # 相对 contentRoot
    line_no: int  # 1-based
    text: str  # 命中行原文


@dataclass(frozen=True)
class FileReference:
    """一条从某文件指向某目标的引用记录。"""

    kind: str  # REF_LINK | REF_SECTION | REF_ANCHOR
    source: str  # 引用来源文件（相对 contentRoot）
    source_line: int  # 引用所在行号（1-based）
    source_text: str  # 引用所在行原文
    target: str  # 目标描述：链接目标 / 章节号 / 锚点 id
    target_rel_path: Optional[str] = None  # 解析到的目标文件（相对 contentRoot），未命中为 None
    dangling: bool = False  # 是否悬空
    dangling_kind: str = ""  # DANGLING_CONFIRMED | DANGLING_SUSPECT


@dataclass
class HeadingEntry:
    """文件内标题：用于锚点解析与重复标题检查。"""

    rel_path: str
    line_no: int  # 1-based
    level: int  # 1-6
    text: str
    anchor_id: str  # slug 化锚点 id

    @property
    def key(self) -> str:
        """重复标题判定的键：同文件内按（level, 规范化文本）比较。"""
        return "{0}:{1}".format(self.level, _normalize_heading_text(self.text))


def _normalize_heading_text(text: str) -> str:
    """标题文本规范化：去首尾空白、折叠内部空白，用于重复判定。"""
    return " ".join(text.split())


@dataclass
class ContentIndex:
    """内容索引聚合：一次扫描构建，服务搜索/引用/术语三处消费。"""

    # rel_path -> FileEntry
    files: Dict[str, FileEntry] = field(default_factory=dict)
    # rel_path -> [行文本, ...]（保留原始行，供搜索与引用定位）
    lines: Dict[str, List[str]] = field(default_factory=dict)
    # source rel_path -> [FileReference, ...]（由引用解析模块填充）
    references: Dict[str, List[FileReference]] = field(default_factory=dict)
    # rel_path -> [HeadingEntry, ...]
    headings: Dict[str, List[HeadingEntry]] = field(default_factory=dict)
    # 失效待重建的 rel_path 集合
    invalid_files: Set[str] = field(default_factory=set)
    # contentRoot 下的文档类型集合（如 {"requirement", "design"}）
    document_types: Set[str] = field(default_factory=set)

    # --- 失效管理 ---

    def invalidate(self, rel_path: str) -> None:
        """标记某文件索引失效，下次搜索/引用前重建。"""
        self.invalid_files.add(rel_path)

    def is_valid(self, rel_path: str) -> bool:
        """某文件索引是否有效（未被标记失效）。"""
        return rel_path not in self.invalid_files

    def refresh(self, rel_path: str) -> None:
        """文件重建完成后清除失效标记。"""
        self.invalid_files.discard(rel_path)

    def all_files(self) -> List[str]:
        """全部已索引文件的 rel_path（稳定排序）。"""
        return sorted(self.files.keys())

    def find_file(self, rel_path: str) -> Optional[FileEntry]:
        """按 rel_path 查文件条目；不存在返回 None。"""
        return self.files.get(rel_path)

    def find_by_name(self, name: str) -> List[str]:
        """按文件名（含扩展名）反查 rel_path；用于章节号/链接目标解析。"""
        matches = [
            rel_path
            for rel_path, entry in self.files.items()
            if entry.name == name
        ]
        return sorted(matches)
