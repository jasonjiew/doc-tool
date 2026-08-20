# -*- coding: utf-8 -*-
"""全文搜索服务：基于内容索引按行扫描。

支持正则/大小写/整词开关、按文档类型范围过滤、命中上限（默认 500，
超限截断并标记 truncated 供 UI 提供"显示更多"）。

整词边界按"词字符"定义（ASCII 字母数字下划线 + CJK），保证搜索
``管理`` 时不匹配 ``管理员``/``管理台`` 等复合词；正则查询由用户
自行控制边界。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from doc_tool.domain.content_index import ContentIndex

# 默认命中上限：超大文档集下保证结果面板与 UI 响应。
DEFAULT_LIMIT = 500

# 词字符集合：ASCII 字母数字下划线 + CJK 统一表意文字。
_WORD_CHAR = r"A-Za-z0-9_一-鿿"


class SearchQueryError(ValueError):
    """搜索查询无法编译（非法正则）。"""


@dataclass
class SearchOptions:
    """搜索选项。"""

    query: str
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False
    document_types: Optional[Sequence[str]] = None  # None 表示全部
    limit: int = DEFAULT_LIMIT


@dataclass
class SearchHit:
    """单条命中。"""

    rel_path: str
    line_no: int  # 1-based
    text: str  # 命中行原文（作为上下文预览）


@dataclass
class SearchResult:
    """搜索结果集。"""

    query: str
    total: int  # 实际命中总数（含截断部分）
    hits: List[SearchHit] = field(default_factory=list)
    truncated: bool = False
    file_count: int = 0


def compile_pattern(
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> "re.Pattern":
    """按选项编译搜索模式；非法正则抛出 SearchQueryError。"""
    flags = 0 if case_sensitive else re.IGNORECASE
    body = query if regex else re.escape(query)
    if whole_word:
        body = r"(?<![{0}])(?:{1})(?![{0}])".format(_WORD_CHAR, body)
    try:
        return re.compile(body, flags)
    except re.error as exc:
        raise SearchQueryError(
            "搜索模式无效：{0}".format(exc),
        ) from exc


class SearchService:
    """在 ContentIndex 之上执行全文搜索。"""

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def search(
        self,
        options: SearchOptions,
        cancel_token=None,
    ) -> SearchResult:
        """执行搜索，按文档类型过滤并应用命中上限。

        ``cancel_token`` 为可选 ``CancellationToken``，在文件边界检查，
        供后台任务在搜索中途安全取消。
        """
        query = options.query.strip()
        if not query:
            return SearchResult(query=query)
        pattern = compile_pattern(
            query,
            regex=options.regex,
            case_sensitive=options.case_sensitive,
            whole_word=options.whole_word,
        )
        allowed = set(options.document_types or [])

        hits: List[SearchHit] = []
        file_count = 0
        for rel_path in self._index.all_files():
            if cancel_token is not None:
                cancel_token.check_cancel()
            entry = self._index.files.get(rel_path)
            if entry is None:
                # 搜索在后台线程遍历索引快照，UI 线程可能同时删除文件并
                # 从索引移除条目：跳过缺失项而非抛 KeyError 误报「搜索失败」。
                continue
            if allowed and entry.document_type not in allowed:
                continue
            lines = self._index.lines.get(rel_path, [])
            file_hits = [
                SearchHit(rel_path=rel_path, line_no=index, text=line)
                for index, line in enumerate(lines, start=1)
                if pattern.search(line)
            ]
            if file_hits:
                file_count += 1
                hits.extend(file_hits)

        total = len(hits)
        truncated = total > options.limit
        return SearchResult(
            query=query,
            total=total,
            hits=hits[: options.limit],
            truncated=truncated,
            file_count=file_count,
        )


def run_search(
    service: SearchService,
    options: SearchOptions,
    cancel_token=None,
) -> SearchResult:
    """后台任务包装：供 TaskRunner 执行，接受取消令牌注入。"""
    return service.search(options, cancel_token=cancel_token)
