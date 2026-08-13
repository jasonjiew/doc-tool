# -*- coding: utf-8 -*-
"""引用解析：markdown 链接、章节号、标题锚点与悬空检测。

在 ``ContentIndex`` 之上扫描每个 .md 文件，识别三类引用：
- 链接：``[文本](目标)`` 指向 content 文件（REF_LINK）、指向资源的图片链接
  （REF_IMAGE）、指向文件内标题的锚点链接（REF_ANCHOR）。
- 章节号：``X.Y`` / ``X.Y.Z`` 等，匹配文件级章节前缀或文件内标题编号
  （如 ``3.5.1.6.4.1`` 对应文件内 ``###`` 标题），未命中时按"确定缺失/
  疑似"分类。
- 标题锚点：``[文本](#标题)`` 的 ``#`` 目标在文件标题清单内匹配。

解析保守优先：无法可靠判定的形态（如版本号 ``2.3.0``、纯数字）不强行
判定为悬空引用，避免误报。
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from doc_tool.application.content.index import slugify_heading
from doc_tool.domain.content_index import (
    DANGLING_CONFIRMED,
    DANGLING_SUSPECT,
    REF_ANCHOR,
    REF_IMAGE,
    REF_LINK,
    REF_SECTION,
    ContentIndex,
    FileReference,
)

# 行内链接：普通链接与图片链接分别匹配，避免图片被当作内容文件引用。
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\n]+)\)")
_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)")

# 章节号 token：至少一个点。用 (?<!\d)/(?![\d.]) 做手动边界，而非 \b——
# Python 的 \b 把 CJK 当词字符，"见3.7.9.6" 在 "3" 前无边界会错配成 "7.9.6"。
_SECTION_TOKEN_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)+)(?![\d.])")

# 章节号前缀：文件名 stem 或标题文本开头的编号（如 3.1 / 3.1.4 / 3.5.1.6.4.1）。
_SECTION_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)+)")

# 疑似章节引用的上下文关键词（出现在 token 前的小窗口内，未命中章节时判定"疑似"）。
# 故意不含"章/节/说明"——"章节""说明"等词太常见（如表格列头"说明"），
# 会导致版本号/小数误报。
_SECTION_CONTEXT_RE = re.compile(r"(第|见|参见|详见|参考|详情|如上|目录)")

# 判定"疑似"时向前检查的窗口字符数。
_CONTEXT_WINDOW = 20

_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "ftp://", "data:")


def leading_number(text: str) -> Optional[str]:
    """取文本开头的编号（如 3.1、3.1.4）；无编号返回 None。"""
    match = _SECTION_PREFIX_RE.match(text.strip())
    return match.group(1) if match else None


def section_no_of_file(rel_path: str) -> Optional[str]:
    """从文件名 stem 提取章节号（如 ``3.1.4 居民信息.md`` -> ``3.1.4``）。"""
    return leading_number(Path(rel_path).stem)


def _is_external(target: str) -> bool:
    stripped = target.lstrip()
    return stripped.startswith(_EXTERNAL_SCHEMES)


class ReferenceScanner:
    """在 ContentIndex 之上扫描引用，填充 ``index.references``。

    ``assets_root`` 为项目 ``assets`` 目录（可选）；提供时图片链接按
    ``assets/<类型>/[images/]<目标>`` 解析并做悬空检测，否则仅记录不判定。
    """

    def __init__(
        self,
        index: ContentIndex,
        assets_root: Optional[Path] = None,
    ) -> None:
        self._index = index
        self._assets_root = Path(assets_root) if assets_root is not None else None
        # 文件级章节号 -> rel_path
        self._section_files: Dict[str, str] = {}
        # 章节号 -> [(rel_path, anchor_id)]（文件内标题编号）
        self._heading_sections: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        # rel_path -> [(anchor_id, text)]
        self._anchors: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self._build_maps()

    # --- 索引内建图 ---

    def _build_maps(self) -> None:
        for rel_path in self._index.all_files():
            number = section_no_of_file(rel_path)
            if number is not None and number not in self._section_files:
                self._section_files[number] = rel_path
            for heading in self._index.headings.get(rel_path, []):
                self._anchors[rel_path].append((heading.anchor_id, heading.text))
                number = leading_number(heading.text)
                if number is not None:
                    self._heading_sections[number].append(
                        (rel_path, heading.anchor_id)
                    )

    # --- 对外入口 ---

    def scan_all(self) -> None:
        """扫描全部文件并填充引用索引。"""
        for rel_path in self._index.all_files():
            self.scan_file(rel_path)

    def scan_file(self, rel_path: str) -> List[FileReference]:
        """扫描单个文件，返回其引用列表并写入索引。"""
        refs: List[FileReference] = []
        for line_no, text in enumerate(
            self._index.lines.get(rel_path, []), start=1
        ):
            refs.extend(self._scan_line(rel_path, line_no, text))
        self._index.references[rel_path] = refs
        return refs

    # --- 行扫描 ---

    def _scan_line(
        self, rel_path: str, line_no: int, text: str
    ) -> List[FileReference]:
        refs: List[FileReference] = []
        # 记录链接目标区间，避免章节号扫描重复命中链接目标内的数字。
        link_spans: List[Tuple[int, int]] = []

        for match in _IMAGE_LINK_RE.finditer(text):
            link_spans.append((match.start(2), match.end(2)))
            ref = self._resolve_image(rel_path, line_no, text, match.group(2))
            if ref is not None:
                refs.append(ref)

        for match in _LINK_RE.finditer(text):
            link_spans.append((match.start(2), match.end(2)))
            target = match.group(2)
            if _is_external(target):
                continue
            link, _, anchor = target.partition("#")
            link = link.strip()
            anchor = anchor.strip()
            if not link and not anchor:
                continue
            if not link:
                ref = self._resolve_anchor(rel_path, line_no, text, anchor)
            else:
                ref = self._resolve_file_link(
                    rel_path, line_no, text, link, anchor or None
                )
            if ref is not None:
                refs.append(ref)

        for match in _SECTION_TOKEN_RE.finditer(text):
            if any(start <= match.start(1) < end for start, end in link_spans):
                continue
            ref = self._resolve_section(
                rel_path, line_no, text, match.group(1), match.start(1)
            )
            if ref is not None:
                refs.append(ref)

        return refs

    # --- 各类引用解析 ---

    def _resolve_image(
        self, rel_path: str, line_no: int, text: str, target: str
    ) -> Optional[FileReference]:
        """图片链接：资产路径解析与悬空检测（提供 assets_root 时）。"""
        image_path = target.split()[0]  # 去掉 `=642x269` 尺寸后缀
        if self._assets_root is None:
            return FileReference(
                kind=REF_IMAGE,
                source=rel_path,
                source_line=line_no,
                source_text=text,
                target=image_path,
            )
        document_type = self._document_type(rel_path)
        candidates = (
            self._assets_root / document_type / image_path,
            self._assets_root / document_type / "images" / image_path,
        )
        exists = any(candidate.exists() for candidate in candidates)
        return FileReference(
            kind=REF_IMAGE,
            source=rel_path,
            source_line=line_no,
            source_text=text,
            target=image_path,
            dangling=not exists,
            dangling_kind=DANGLING_CONFIRMED if not exists else "",
        )

    def _resolve_file_link(
        self,
        rel_path: str,
        line_no: int,
        text: str,
        link: str,
        anchor: Optional[str],
    ) -> FileReference:
        """普通链接：解析到 content 文件，可选带锚点。"""
        target_rel = self._resolve_content_file(link)
        ref = FileReference(
            kind=REF_LINK,
            source=rel_path,
            source_line=line_no,
            source_text=text,
            target=link,
            target_rel_path=target_rel,
            dangling=target_rel is None,
            dangling_kind=DANGLING_CONFIRMED if target_rel is None else "",
        )
        if target_rel is not None and anchor is not None:
            if not self._anchor_exists(target_rel, anchor):
                ref.dangling = True
                ref.dangling_kind = DANGLING_CONFIRMED
        return ref

    def _resolve_anchor(
        self, rel_path: str, line_no: int, text: str, anchor: str
    ) -> FileReference:
        """纯锚点链接：匹配当前文件内标题。"""
        exists = self._anchor_exists(rel_path, anchor)
        return FileReference(
            kind=REF_ANCHOR,
            source=rel_path,
            source_line=line_no,
            source_text=text,
            target=anchor,
            target_rel_path=rel_path if exists else None,
            dangling=not exists,
            dangling_kind=DANGLING_CONFIRMED if not exists else "",
        )

    def _resolve_section(
        self, rel_path: str, line_no: int, text: str, token: str, token_start: int
    ) -> Optional[FileReference]:
        """章节号引用：先匹配文件级章节，再匹配文件内标题编号。

        文件自身的顶层章节号（如文件 ``3.1.4`` 内出现 ``3.1.4``）多为标题
        行自述，不构成有用引用，予以抑制；文件内更深编号（如 ``3.5.1``
        文件内 ``3.5.1.6.4.1``）保留。
        """
        # 自身顶层章节号抑制（标题行噪声）
        if token == section_no_of_file(rel_path):
            return None
        # 文件级章节
        file_target = self._section_files.get(token)
        if file_target is not None:
            return FileReference(
                kind=REF_SECTION,
                source=rel_path,
                source_line=line_no,
                source_text=text,
                target=token,
                target_rel_path=file_target,
            )
        # 文件内标题编号（优先本文件）
        heading_matches = self._heading_sections.get(token, [])
        if heading_matches:
            target_rel, _anchor = next(
                (item for item in heading_matches if item[0] == rel_path),
                heading_matches[0],
            )
            return FileReference(
                kind=REF_SECTION,
                source=rel_path,
                source_line=line_no,
                source_text=text,
                target=token,
                target_rel_path=target_rel,
            )
        # 未命中：token 前小窗口内有关键词判定"疑似"，否则忽略避免误报
        before = text[max(0, token_start - _CONTEXT_WINDOW):token_start]
        if _SECTION_CONTEXT_RE.search(before):
            return FileReference(
                kind=REF_SECTION,
                source=rel_path,
                source_line=line_no,
                source_text=text,
                target=token,
                dangling=True,
                dangling_kind=DANGLING_SUSPECT,
            )
        return None

    # --- 辅助 ---

    def _resolve_content_file(self, link: str) -> Optional[str]:
        """把链接目标解析为 content 文件的 rel_path；解析不到返回 None。"""
        normalized = link.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized in self._index.files:
            return normalized
        # 按文件名反查（处理带路径前缀的链接）
        name = Path(normalized).name
        if not name:
            return None
        matches = self._index.find_by_name(name)
        return matches[0] if matches else None

    def _anchor_exists(self, rel_path: str, anchor: str) -> bool:
        """锚点目标是否存在于某文件的标题清单。"""
        slug = slugify_heading(anchor)
        raw = anchor.strip()
        for anchor_id, text in self._anchors.get(rel_path, []):
            if (
                anchor_id == slug
                or slugify_heading(text) == slug
                or text == raw
            ):
                return True
        return False

    def _document_type(self, rel_path: str) -> str:
        entry = self._index.files.get(rel_path)
        return entry.document_type if entry is not None else "general"
