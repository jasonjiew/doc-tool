# -*- coding: utf-8 -*-
"""全局替换服务：基于搜索索引定位命中，按文件批量写回。

匹配带列位置（start/end），供"逐项确认"与"全部替换"两种流共用：
- 逐项：面板选中单个 match 调用 ``apply_matches([match])``。
- 全部：先 ``build_preview`` 汇总，再 ``apply_matches(all)``。

写回经 ``ContentWriter``（每文件 .md.bak + 原子写 + 改动清单回滚）。
写回后由调用方（主窗口）触发校验管线检测悬空引用。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from doc_tool.application.content.search import compile_pattern
from doc_tool.domain.content_index import ContentIndex


@dataclass
class ReplaceMatch:
    """单条命中（带列位置）。"""

    rel_path: str
    line_no: int  # 1-based
    line_text: str  # 命中行原文（不含换行）
    start: int  # 命中起点列
    end: int  # 命中终点列


@dataclass
class ReplacePreview:
    """全部命中预览（"全部替换"前的汇总）。"""

    query: str
    matches: List[ReplaceMatch] = field(default_factory=list)
    file_count: int = 0

    @property
    def total(self) -> int:
        return len(self.matches)


def diff_line(match: ReplaceMatch, replacement: str) -> tuple:
    """返回 (before, after) 行文本对，供面板展示前后差异。"""
    before = match.line_text
    after = match.line_text[: match.start] + replacement + match.line_text[match.end :]
    return before, after


class ReplaceService:
    """全局替换服务。"""

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def find_matches(
        self,
        query: str,
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        whole_word: bool = False,
        document_types: Optional[List[str]] = None,
        cancel_token=None,
    ) -> List[ReplaceMatch]:
        """扫描全部命中（带列位置），按文档类型过滤。"""
        query = query.strip()
        if not query:
            return []
        pattern = compile_pattern(
            query,
            regex=regex,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
        )
        allowed = set(document_types or [])
        matches: List[ReplaceMatch] = []
        for rel_path in self._index.all_files():
            if cancel_token is not None:
                cancel_token.check_cancel()
            entry = self._index.files[rel_path]
            if allowed and entry.document_type not in allowed:
                continue
            for line_no, line in enumerate(
                self._index.lines.get(rel_path, []), start=1
            ):
                for m in pattern.finditer(line):
                    matches.append(
                        ReplaceMatch(
                            rel_path=rel_path,
                            line_no=line_no,
                            line_text=line,
                            start=m.start(),
                            end=m.end(),
                        )
                    )
        return matches

    def build_preview(
        self,
        query: str,
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        whole_word: bool = False,
        document_types: Optional[List[str]] = None,
        cancel_token=None,
    ) -> ReplacePreview:
        """构建全部命中汇总（用于"全部替换"前的确认）。"""
        matches = self.find_matches(
            query,
            regex=regex,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            document_types=document_types,
            cancel_token=cancel_token,
        )
        files = {m.rel_path for m in matches}
        return ReplacePreview(
            query=query,
            matches=matches,
            file_count=len(files),
        )

    def apply_matches(
        self,
        matches: List[ReplaceMatch],
        replacement: str,
        writer,
        cancel_token=None,
    ) -> List:
        """按命中列表写回（逐项确认/全部替换共用）。

        每个受影响文件写入一次（经 ContentWriter 备份 + 原子写），返回
        每个文件的写入结果列表。调用方随后触发校验管线。
        """
        if not matches:
            return []
        by_file: Dict[str, List[ReplaceMatch]] = defaultdict(list)
        for match in matches:
            by_file[match.rel_path].append(match)

        results = []
        for rel_path in sorted(by_file):
            if cancel_token is not None:
                cancel_token.check_cancel()
            file_matches = by_file[rel_path]
            new_text = self._rewrite_file(rel_path, file_matches, replacement, writer)
            results.append(writer.write_text(rel_path, new_text))
        return results

    def _rewrite_file(
        self,
        rel_path: str,
        file_matches: List[ReplaceMatch],
        replacement: str,
        writer,
    ) -> str:
        """对单个文件应用全部命中，保留原有换行与其余内容。"""
        target = writer.resolve(rel_path)
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        by_line: Dict[int, List[ReplaceMatch]] = defaultdict(list)
        for match in file_matches:
            by_line[match.line_no].append(match)
        for line_no, line_matches in by_line.items():
            line = lines[line_no - 1]
            for match in sorted(line_matches, key=lambda m: m.start, reverse=True):
                line = (
                    line[: match.start]
                    + replacement
                    + line[match.end :]
                )
            lines[line_no - 1] = line
        return "".join(lines)
