# -*- coding: utf-8 -*-
"""术语/一致性检查：重复标题、术语大小写不一致、TODO/TBD 残留。

- 重复标题：索引中完全相同的标题文本（规范化后）出现在多处。
- 术语大小写：术语清单中的规范拼写（如 ``KSHC``），正文出现非规范大小写时标记。
- 待办残留：``TODO``/``TBD``/``FIXME``/``XXX``/``待补充`` 等标记。

术语清单存储于项目 ``.state/terms.json``（``TermStore``），可在结果面板
增删，变更后立即生效并重跑相关检查。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from doc_tool.domain.content_index import ContentIndex

TERMS_FILE_NAME = "terms.json"

# 待办/占位残留标记。
_TODO_RE = re.compile(
    r"TODO|TBD|FIXME|XXX|待补充|待完善|待定|占位|placeholder",
    re.IGNORECASE,
)


@dataclass
class LintIssue:
    """一致性检查结果。"""

    rule: str  # duplicate_title | term_case | todo_residual
    rel_path: str
    line_no: int
    message: str


class ContentLinter:
    """一致性检查器（纯服务）。"""

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def check_all(self, terms: List[str]) -> List[LintIssue]:
        """运行全部检查，返回按文件与行排序的结果。"""
        issues = (
            self.check_duplicate_titles()
            + self.check_todo()
            + self.check_terms(terms)
        )
        issues.sort(key=lambda i: (i.rel_path, i.line_no))
        return issues

    def check_duplicate_titles(self) -> List[LintIssue]:
        """完全相同的标题文本（规范化后）出现在多处时标记。"""
        by_key: "defaultdict[str, list]" = defaultdict(list)
        for rel_path, headings in self._index.headings.items():
            for heading in headings:
                by_key[heading.key].append((rel_path, heading.line_no, heading.text))

        issues: List[LintIssue] = []
        for key, occurrences in by_key.items():
            if len(occurrences) < 2:
                continue
            # 只保留首个以外的重复出现
            for rel_path, line_no, text in occurrences[1:]:
                issues.append(
                    LintIssue(
                        rule="duplicate_title",
                        rel_path=rel_path,
                        line_no=line_no,
                        message="重复标题：{0}".format(text),
                    )
                )
        return issues

    def check_todo(self) -> List[LintIssue]:
        """TODO/TBD 等残留标记。"""
        issues: List[LintIssue] = []
        for rel_path, lines in self._index.lines.items():
            for line_no, line in enumerate(lines, start=1):
                if _TODO_RE.search(line):
                    issues.append(
                        LintIssue(
                            rule="todo_residual",
                            rel_path=rel_path,
                            line_no=line_no,
                            message="发现待办/占位标记：{0}".format(
                                line.strip()[:60]
                            ),
                        )
                    )
        return issues

    def check_terms(self, terms: List[str]) -> List[LintIssue]:
        """术语大小写不一致（规范拼写 vs 非规范大小写出现）。"""
        issues: List[LintIssue] = []
        for term in terms:
            canonical = term.strip()
            if not canonical:
                continue
            pattern = re.compile(
                re.escape(canonical), re.IGNORECASE
            )
            for rel_path, lines in self._index.lines.items():
                for line_no, line in enumerate(lines, start=1):
                    for match in pattern.finditer(line):
                        if match.group(0) == canonical:
                            continue
                        issues.append(
                            LintIssue(
                                rule="term_case",
                                rel_path=rel_path,
                                line_no=line_no,
                                message="术语大小写不一致：{0}（应为 {1}）".format(
                                    match.group(0), canonical
                                ),
                            )
                        )
        return issues


class TermStore:
    """术语清单持久化（项目 .state/terms.json）。"""

    def __init__(self, state_dir: Path) -> None:
        self._file: Path = Path(state_dir) / TERMS_FILE_NAME

    @property
    def file(self) -> Path:
        return self._file

    def load(self) -> List[str]:
        """读取术语清单；缺失或损坏返回空。"""
        if not self._file.exists():
            return []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
            terms = data.get("terms", []) if isinstance(data, dict) else []
            return [str(item).strip() for item in terms if str(item).strip()]
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, terms: List[str]) -> None:
        """写入术语清单（去重、去空）。"""
        cleaned: List[str] = []
        seen = set()
        for term in terms:
            value = str(term).strip()
            if value and value not in seen:
                seen.add(value)
                cleaned.append(value)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import os

        try:
            os.replace(str(tmp), str(self._file))
        except OSError:
            import shutil

            shutil.move(str(tmp), str(self._file))
