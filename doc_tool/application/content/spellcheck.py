# -*- coding: utf-8 -*-
"""英文拼写检查纯服务（无运行时依赖）。

``SpellChecker`` 对一段 Markdown 文本执行英文单词拼写检查：

- 英文词 token 用正则 ``\b[a-zA-Z][a-zA-Z'-]{1,}\b`` 识别。CJK 字符被 Python
  视为单词字符，因此紧贴中文（无空格分隔）的英文不产生词边界、不会被检查；
  这天然满足「中文文本不参与检查」的约定。
- 跳过 ``` 围栏代码块（```mermaid 等一律跳过）与围栏起始行本身。
- 命中判定：词的小写归一化（去除撇号）不在 内置词典 ∪ 用户词典 中即视为拼写错误。
- 建议：编辑距离（Damerau-Levenshtein）≤2 且共同前缀更长的候选优先。

词典数据打包在 ``resources/dict/en_words.txt``（约 5 万常用词，按频率取），
用户词典读写 ``QStandardPaths.AppDataLocation/user_dict.txt``（可注入目录供测试）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

# 英文词 token：至少一个字母开头，后续可含字母、撇号、连字符（≥2 字符）。
_TOKEN_RE = re.compile(r"\b[a-zA-Z][a-zA-Z'-]{1,}\b")
# 围栏代码块起始/结束行。
_FENCE_RE = re.compile(r"^```")
# 有效词典词（小写）。
_VALID_DICT_WORD_RE = re.compile(r"^[a-z][a-z'-]*$")


def _normalize(word: str) -> str:
    """小写并去除撇号（don't -> dont），用于词典命中判定。"""
    return word.lower().replace("'", "").replace("’", "")


@dataclass(frozen=True)
class Misspelling:
    """一处拼写错误：词原文与其在源文本中的起止位置。"""

    word: str
    start: int
    end: int  # 半开区间，指向词尾后一位置


class SpellChecker:
    """拼写检查器：内置词典 + 用户词典 + 建议候选。"""

    def __init__(
        self,
        builtin_words: Optional[Set[str]] = None,
        user_words: Optional[Set[str]] = None,
    ) -> None:
        self._builtin: Set[str] = set(builtin_words or ())
        self._user: Set[str] = set(user_words or ())
        self._prefix_index: Dict[str, List[str]] = self._build_index(self._builtin)

    # --- 词典 ---

    @property
    def user_words(self) -> Set[str]:
        return set(self._user)

    def add_user_word(self, word: str) -> None:
        """把词加入用户词典（归一化后存储）。"""
        normalized = _normalize(word.strip())
        if not normalized or not _VALID_DICT_WORD_RE.match(normalized):
            return
        self._user.add(normalized)

    def contains(self, word: str) -> bool:
        return _normalize(word) in self._builtin or _normalize(word) in self._user

    # --- 检查 ---

    def check(self, text: str) -> List[Misspelling]:
        """扫描整段文本返回拼写错误；start/end 为相对 ``text`` 起点的绝对偏移。

        跳过 ``` 围栏代码块。供全文档检查与单测使用；编辑器按可见行增量
        检查使用 ``check_range``。
        """
        misspellings: List[Misspelling] = []
        in_code = False
        offset = 0
        # 用 keepends=True 按真实行长（含 \n 或 \r\n 分隔符）累计偏移：
        # ``splitlines()`` 会剥掉 \r，CRLF 文件从第二行起 start/end 整体偏小，
        # 编辑器高亮/定位会错位。
        for raw_line in text.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")
            if _FENCE_RE.match(line.strip()):
                in_code = not in_code
                offset += len(raw_line)
                continue
            if not in_code:
                for match in _TOKEN_RE.finditer(line):
                    token = match.group(0)
                    if not self.contains(token):
                        misspellings.append(
                            Misspelling(
                                word=token,
                                start=offset + match.start(),
                                end=offset + match.end(),
                            )
                        )
            offset += len(raw_line)
        return misspellings

    def check_line(self, line: str, base_offset: int = 0) -> List[Misspelling]:
        """检查单行文本；start/end 为 ``base_offset`` 起算的绝对偏移。

        编辑器可见行增量扫描使用：避免大文档每次击键全量重扫。
        """
        return [
            Misspelling(word=match.group(0), start=base_offset + match.start(), end=base_offset + match.end())
            for match in _TOKEN_RE.finditer(line)
            if not self.contains(match.group(0))
        ]

    # --- 建议 ---

    def suggest(self, word: str, limit: int = 8) -> List[str]:
        """返回编辑距离 ≤2 的候选建议，距离与共同前缀共同排序。

        只在首字母相同的词典词上计算距离，避免对 5 万词全量做 O(n·m)。
        """
        normalized = _normalize(word)
        if not normalized:
            return []
        first = normalized[0]
        if first not in self._prefix_index:
            return []
        scored: List[tuple] = []
        for candidate in self._prefix_index[first]:
            if abs(len(candidate) - len(normalized)) > 2:
                continue  # 长度差剪枝：编辑距离不可能 ≤2
            distance = _damerau_levenshtein(normalized, candidate)
            if distance > 2:
                continue
            prefix_len = _common_prefix_length(normalized, candidate)
            scored.append((distance, -prefix_len, candidate))
        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[2] for item in scored[:limit]]

    # --- 内部 ---

    @staticmethod
    def _build_index(words: Set[str]) -> Dict[str, List[str]]:
        index: Dict[str, List[str]] = {}
        for word in words:
            index.setdefault(word[0], []).append(word)
        return index


def _damerau_levenshtein(a: str, b: str, max_distance: int = 2) -> int:
    """受限 Damerau-Levenshtein 距离（超过 max_distance 提前返回大值）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    len_a, len_b = len(a), len(b)
    if abs(len_a - len_b) > max_distance:
        return max_distance + 1
    prev_prev = list(range(len_b + 1))
    prev = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        curr = [i] + [0] * len_b
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,        # 删除
                curr[j - 1] + 1,    # 插入
                prev[j - 1] + cost, # 替换
            )
            if (
                i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                curr[j] = min(curr[j], prev_prev[j - 2] + cost)  # 换位
        if min(curr[1:]) > max_distance and i == len_a:
            return max_distance + 1
        prev_prev, prev = prev, curr
    return prev[len_b]


def _common_prefix_length(a: str, b: str) -> int:
    length = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        length += 1
    return length


def load_builtin_words() -> Set[str]:
    """从打包资源 ``resources/dict/en_words.txt`` 加载内置词典。

    开发态读取仓库资源，PyInstaller 打包态读取 ``sys._MEIPASS`` 下的资源；
    文件缺失/损坏时返回空集（拼写检查退化为仅用户词典，不影响编辑）。
    """
    from doc_tool.resources import resource_path

    path = resource_path("dict", "en_words.txt")
    words: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                word = line.strip()
                if word and _VALID_DICT_WORD_RE.match(word):
                    words.add(word)
    except OSError:
        pass
    return words


class UserDictionary:
    """用户词典：读写 ``<AppData>/user_dict.txt``，每行一词。"""

    def __init__(self, path=None) -> None:
        if path is None:
            from PySide6.QtCore import QStandardPaths

            base = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            path = base + "/user_dict.txt"
        self._path = path
        self._words: Set[str] = set()
        self.load()

    @property
    def path(self) -> str:
        return self._path

    @property
    def words(self) -> Set[str]:
        """当前用户词典词（小写归一化）。"""
        return set(self._words)

    def load(self) -> None:
        """从磁盘加载用户词（文件缺失视为空；损坏行忽略）。"""
        self._words = set()
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                for line in handle:
                    word = _normalize(line.strip())
                    if word and _VALID_DICT_WORD_RE.match(word):
                        self._words.add(word)
        except OSError:
            pass

    def save(self) -> None:
        """写回磁盘（排序稳定；写入失败静默，不影响编辑）。"""
        import os

        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as handle:
                for word in sorted(self._words):
                    handle.write(word + "\n")
        except OSError:
            pass

    def contains(self, word: str) -> bool:
        return _normalize(word) in self._words

    def add(self, word: str) -> bool:
        """加入并立即持久化；返回是否发生了新增。"""
        normalized = _normalize(word.strip())
        if not normalized or not _VALID_DICT_WORD_RE.match(normalized):
            return False
        if normalized in self._words:
            return False
        self._words.add(normalized)
        self.save()
        return True
