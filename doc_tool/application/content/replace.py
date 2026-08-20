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
from doc_tool.application.content.writer import WriteResult
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

    def find_in_file(
        self,
        rel_path: str,
        query: str,
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> List[ReplaceMatch]:
        """重新扫描单个文件的当前命中（供逐项替换后刷新剩余命中）。

        逐项替换每次只应用一条缓存命中，写回后其余命中仍基于旧内容的列
        偏移；调用方在写回并刷新索引后用本方法重建该文件的命中，避免把
        陈旧的 start/end 应用到新内容上。
        """
        query = query.strip()
        if not query or rel_path not in self._index.files:
            return []
        pattern = compile_pattern(
            query,
            regex=regex,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
        )
        return [
            ReplaceMatch(
                rel_path=rel_path,
                line_no=line_no,
                line_text=line,
                start=m.start(),
                end=m.end(),
            )
            for line_no, line in enumerate(
                self._index.lines.get(rel_path, []), start=1
            )
            for m in pattern.finditer(line)
        ]

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
            try:
                new_text = self._rewrite_file(rel_path, file_matches, replacement, writer)
            except (OSError, UnicodeError, IndexError, KeyError, ValueError) as exc:
                # 预览后文件被外部改动/删除（行数变化 → 陈旧行号越界、
                # 文件消失 → 读取失败）：该文件本次不写回并计入失败，
                # 不再把异常抛到 Qt 槽中造成「部分写回 + 无提示」，也避免
                # 用户用陈旧偏移重试导致替换错位。
                results.append(
                    WriteResult(
                        rel_path=rel_path,
                        backup_path=None,
                        written=False,
                        error="文件已变化或不可读：{0}".format(exc),
                    )
                )
                continue
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
            index = line_no - 1
            if not (0 <= index < len(lines)):
                # 预览时的行号在写回前已失效（文件被外部编辑/删除）：
                # 抛出以拒绝本次写回，绝不按陈旧偏移切片写入损坏内容。
                raise ValueError(
                    "命中行号 {0} 超出当前文件行数（{1}），文件已变化".format(
                        line_no, len(lines)
                    )
                )
            line = lines[index]
            for match in sorted(line_matches, key=lambda m: m.start, reverse=True):
                line = (
                    line[: match.start]
                    + replacement
                    + line[match.end :]
                )
            lines[line_no - 1] = line
        return "".join(lines)
