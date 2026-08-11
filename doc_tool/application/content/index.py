# -*- coding: utf-8 -*-
"""内容索引构建与增量维护服务。

一次扫描 ``content_root``（即 ``content/<类型>`` 的父目录）下全部 .md，
构建行索引、标题清单与文档类型集合。引用索引（``FileReference``）由
``doc_tool.application.content.references`` 在上层填充。

索引键统一为相对 contentRoot 的 POSIX 风格 rel_path。

增量维护：写路径（编辑器保存/全局替换/重命名联动）在改动后调用
``ContentIndex.invalidate(rel_path)``；搜索/引用/术语操作前调用
``refresh_dirty`` 重建失效文件，避免展示过期内容。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

from doc_tool.domain.content_index import ContentIndex, FileEntry, HeadingEntry
from doc_tool.domain.cancellation import CancellationToken

# 识别为内容文件的扩展名。
MD_SUFFIXES = (".md", ".markdown")

# 内容索引收录的文档类型目录（contentRoot 直接子目录）。
KNOWN_DOCUMENT_TYPES = ("requirement", "design", "general")

# 标题行匹配：行首 1-6 个 # 后跟空白。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# 锚点 slug 中允许保留的字符：ASCII 字母数字与 CJK 统一表意文字。
_KEEP_RE = re.compile(r"[^\w\s一-鿿]+", re.UNICODE)
_SPACES_RE = re.compile(r"\s+")


def slugify_heading(text: str) -> str:
    """标题文本生成 GitHub 风格锚点 id（CJK 保留、标点丢弃、空白折叠为连字符）。

    生成与匹配使用同一函数，保证工具内锚点链接自洽；不追求与
    GitHub/Word 完全一致的 slug（精确渲染属于 build 产物范畴）。
    """
    lowered = text.lower()
    kept = _KEEP_RE.sub("", lowered)
    slug = _SPACES_RE.sub("-", kept).strip("-")
    return slug or "section"


def infer_document_type(rel_path: str) -> str:
    """从 rel_path 首段推断文档类型；无法识别时回退 general。"""
    first = rel_path.split("/", 1)[0]
    if first in ("requirement", "design", "general"):
        return first
    return "general"


class ContentIndexService:
    """内容索引服务：构建、增量重建、失效刷新。"""

    def __init__(self, content_root: Path) -> None:
        self._content_root: Path = Path(content_root).resolve()

    @property
    def content_root(self) -> Path:
        return self._content_root

    # --- 发现与读取 ---

    def discover_files(self) -> List[Tuple[str, Path]]:
        """返回 [(rel_path, absolute_path)]，稳定排序。

        仅收录 contentRoot 下文档类型子目录（requirement/design/general）
        内的 .md，避免 assets 或其他非内容目录误入内容索引。
        """
        result: List[Tuple[str, Path]] = []
        if not self._content_root.exists():
            return result
        for document_dir in sorted(
            child
            for child in self._content_root.iterdir()
            if child.is_dir() and child.name in KNOWN_DOCUMENT_TYPES
        ):
            for suffix in MD_SUFFIXES:
                for file_path in document_dir.rglob("*" + suffix):
                    rel = file_path.relative_to(self._content_root).as_posix()
                    result.append((rel, file_path))
        result.sort(key=lambda item: item[0])
        return result

    def read_lines(self, file_path: Path) -> List[str]:
        """读取 .md 为行列表；读取失败视为空（由调用方决定是否保留索引）。"""
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return []
        return text.splitlines()

    # --- 构建 ---

    def build(self, cancel_token: Optional[CancellationToken] = None) -> ContentIndex:
        """全量扫描 contentRoot 构建索引。可传入取消令牌在文件边界安全中断。"""
        index = ContentIndex()
        for rel_path, file_path in self.discover_files():
            if cancel_token is not None:
                cancel_token.check_cancel()
            self._index_file(index, rel_path, file_path)
        index.document_types = {
            infer_document_type(rel) for rel in index.files.keys()
        }
        return index

    def rebuild_file(self, index: ContentIndex, rel_path: str) -> None:
        """重建单个文件索引（含删除场景：文件消失则移除条目）。"""
        file_path = self._resolve(rel_path)
        if not file_path or not file_path.exists():
            index.files.pop(rel_path, None)
            index.lines.pop(rel_path, None)
            index.headings.pop(rel_path, None)
            index.references.pop(rel_path, None)
        else:
            self._index_file(index, rel_path, file_path)
        index.refresh(rel_path)

    def refresh_dirty(self, index: ContentIndex) -> None:
        """重建全部失效文件；无效文件被移除条目。"""
        for rel_path in sorted(index.invalid_files):
            self.rebuild_file(index, rel_path)

    def refresh(self, index: ContentIndex) -> int:
        """全量重扫：新增/删除/变更文件，重建内容条目并返回文件总数。

        非破坏性：只更新 ContentIndex 内容，不影响引用索引（由调用方
        重扫 ReferenceScanner）。用于"刷新索引"等手动操作。
        """
        current = {rel for rel, _ in self.discover_files()}
        # 标记全部现有文件失效以便重建；新增文件直接加入
        for rel_path in index.all_files():
            index.invalidate(rel_path)
        for rel_path in current:
            if rel_path not in index.files:
                index.invalidate(rel_path)
        self.refresh_dirty(index)
        # refresh_dirty 已移除消失文件条目并刷新 document_types 无需额外处理
        index.document_types = {
            infer_document_type(rel) for rel in index.files.keys()
        }
        return len(index.files)

    def _resolve(self, rel_path: str) -> Optional[Path]:
        """把 rel_path 解析为绝对路径；越出 contentRoot 返回 None。"""
        target = (self._content_root / rel_path).resolve()
        try:
            target.relative_to(self._content_root)
        except ValueError:
            return None
        return target

    def _index_file(self, index: ContentIndex, rel_path: str, file_path: Path) -> None:
        """为单个文件构建 FileEntry + lines + headings，并入索引。"""
        lines = self.read_lines(file_path)
        entry = FileEntry(
            rel_path=rel_path,
            document_type=infer_document_type(rel_path),
            line_count=len(lines),
        )
        headings: List[HeadingEntry] = []
        for line_no, line in enumerate(lines, start=1):
            match = _HEADING_RE.match(line)
            if match is None:
                continue
            level = len(match.group(1))
            text = match.group(2)
            headings.append(
                HeadingEntry(
                    rel_path=rel_path,
                    line_no=line_no,
                    level=level,
                    text=text,
                    anchor_id=slugify_heading(text),
                )
            )
        index.files[rel_path] = entry
        index.lines[rel_path] = lines
        index.headings[rel_path] = headings
        index.refresh(rel_path)
        index.document_types.add(entry.document_type)
