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
from typing import Callable, Collection, Dict, List, Optional, Tuple

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


def normalize_overrides(overrides: Optional[Dict[str, str]]) -> Dict[str, str]:
    """归一化「活缓冲文本」覆盖表（路径分隔符统一为 ``/``）。"""
    return {
        str(key).replace("\\", "/"): str(value)
        for key, value in (overrides or {}).items()
    }


class ReplaceService:
    """全局替换服务。"""

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def all_files(self) -> List[str]:
        """返回当前索引中的章节路径。"""
        return self._index.all_files()

    def lines_for(self, rel_path: str, overrides: Optional[Dict[str, str]] = None) -> List[str]:
        """取某文件的当前正文行：有活缓冲覆盖时用缓冲，否则用索引（磁盘）。

        MAIN-B 2.1：查找替换必须看到用户正在编辑但尚未保存的正文，否则
        「当前章替换」会漏掉刚敲进去的内容，或在保存后用陈旧的磁盘文本覆盖。
        """
        data = normalize_overrides(overrides)
        if rel_path in data:
            return data[rel_path].splitlines()
        return list(self._index.lines.get(rel_path, []))

    def find_matches(
        self,
        query: str,
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        whole_word: bool = False,
        document_types: Optional[List[str]] = None,
        cancel_token=None,
        scope_paths: Optional[Collection[str]] = None,
        text_overrides: Optional[Dict[str, str]] = None,
    ) -> List[ReplaceMatch]:
        """扫描全部命中（带列位置），按文档类型与显式范围过滤。"""
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
        scope = None if scope_paths is None else set(scope_paths)
        matches: List[ReplaceMatch] = []
        for rel_path in self._index.all_files():
            if cancel_token is not None:
                cancel_token.check_cancel()
            entry = self._index.files[rel_path]
            if allowed and entry.document_type not in allowed:
                continue
            if scope is not None and rel_path not in scope:
                continue
            for line_no, line in enumerate(
                self.lines_for(rel_path, text_overrides), start=1
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
        scope_paths: Optional[Collection[str]] = None,
        text_overrides: Optional[Dict[str, str]] = None,
    ) -> ReplacePreview:
        """构建全部命中汇总（用于"全部替换"前的确认）。"""
        matches = self.find_matches(
            query,
            regex=regex,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            document_types=document_types,
            cancel_token=cancel_token,
            scope_paths=scope_paths,
            text_overrides=text_overrides,
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
        text_overrides: Optional[Dict[str, str]] = None,
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
                self.lines_for(rel_path, text_overrides), start=1
            )
            for m in pattern.finditer(line)
        ]

    def apply_matches(
        self,
        matches: List[ReplaceMatch],
        replacement: str,
        writer,
        cancel_token=None,
        *,
        text_overrides: Optional[Dict[str, str]] = None,
        buffer_applier: Optional[Callable[[str, str], bool]] = None,
    ) -> List:
        """按命中列表写回（逐项确认/全部替换共用）。

        每个受影响文件写入一次（经 ContentWriter 备份 + 原子写），返回
        每个文件的写入结果列表。调用方随后触发校验管线。

        MAIN-B 2.1/2.4：

        - ``text_overrides`` 给出用户尚未保存的活缓冲正文：该文件的命中基于缓冲
          计算，写回也落在缓冲（经 ``buffer_applier``），不会为了替换隐式保存。
        - ``buffer_applier(rel_path, new_text) -> bool`` 返回 True 表示已写入活缓冲；
          缓冲不可写时报告失败，保留磁盘与未保存内容。这样替换与编辑器撤销栈一致，
          而其他已保存章节继续走 ``ContentWriter`` 的可回滚写回。
        - 预览后正文再次变化（命中行文本已不同）的文件整体跳过并计入失败，
          其余文件继续写回，避免按陈旧列偏移写错位置。
        """
        if not matches:
            return []
        overrides = normalize_overrides(text_overrides)
        by_file: Dict[str, List[ReplaceMatch]] = defaultdict(list)
        for match in matches:
            by_file[match.rel_path].append(match)

        results = []
        for rel_path in sorted(by_file):
            if cancel_token is not None:
                cancel_token.check_cancel()
            file_matches = by_file[rel_path]
            override = overrides.get(rel_path)
            try:
                new_text = self._rewrite_file(
                    rel_path, file_matches, replacement, writer, text_override=override
                )
            except (OSError, UnicodeError, IndexError, KeyError, ValueError) as exc:
                # 预览后文件被外部改动/删除（行数变化 → 陈旧行号越界、
                # 命中行文本变化 → 陈旧列偏移、文件消失 → 读取失败）：
                # 该文件本次不写回并计入失败，其余文件继续。
                results.append(
                    WriteResult(
                        rel_path=rel_path,
                        backup_path=None,
                        written=False,
                        error="文件已变化或不可读：{0}".format(exc),
                    )
                )
                continue
            if override is not None:
                error = "编辑缓冲不可写，请重新打开章节后查找替换"
                try:
                    applied = buffer_applier is not None and bool(buffer_applier(rel_path, new_text))
                except Exception as exc:  # noqa: BLE001 - 不可隐式保存未保存正文
                    applied = False
                    error = "编辑缓冲写入失败：{0}".format(exc)
                results.append(WriteResult(
                    rel_path=rel_path, backup_path=None, written=bool(applied),
                    error=None if applied else error,
                ))
                continue
            results.append(writer.write_text(rel_path, new_text, operation="replace"))
        return results

    def _rewrite_file(
        self,
        rel_path: str,
        file_matches: List[ReplaceMatch],
        replacement: str,
        writer,
        text_override: Optional[str] = None,
    ) -> str:
        """对单个文件应用全部命中，保留原有换行与其余内容。

        ``text_override`` 为活缓冲正文时以它为准（不读磁盘），并在写回前校验
        每处命中的行文本仍与预览一致，避免按陈旧列偏移写错位置。
        """
        if text_override is not None:
            text = str(text_override)
        else:
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
            if line.rstrip("\r\n") != line_matches[0].line_text:
                raise ValueError(
                    "第 {0} 行内容已变化，跳过该项（其余命中继续）".format(line_no)
                )
            for match in sorted(line_matches, key=lambda m: m.start, reverse=True):
                line = (
                    line[: match.start]
                    + replacement
                    + line[match.end :]
                )
            lines[line_no - 1] = line
        return "".join(lines)
