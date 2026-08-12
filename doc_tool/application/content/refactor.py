# -*- coding: utf-8 -*-
"""章节重命名/重编号联动服务。

基于引用索引扫描受影响引用，生成 dry-run 清单（文件内位置 × 旧→新），
确认后批量更新引用文本并重命名文件。写回经 ``ContentWriter``
（备份 + 改动清单 + 回滚），完成后由调用方触发校验检悬空引用。

联动更新范围（保守，避免误改正文自由文本）：
- 指向该文件的**章节号引用**：``旧编号`` -> ``新编号``（重编号时）。
- 指向该文件的**链接**：链接目标中的旧文件名 -> 新文件名。
- 文件自身**标题行**：``# 旧编号 ...`` -> ``# 新编号 ...``（重编号时）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from doc_tool.application.content.references import section_no_of_file
from doc_tool.domain.content_index import ContentIndex, REF_LINK, REF_SECTION


@dataclass
class EditOp:
    """单处文本替换（文件内位置 × 旧→新）。"""

    rel_path: str  # 待编辑文件（重命名前路径）
    line_no: int
    old_substr: str
    new_substr: str


@dataclass
class RenamePlan:
    """重命名/重编号 dry-run 清单。"""

    old_rel_path: str
    new_rel_path: str
    edits: List[EditOp] = field(default_factory=list)  # 引用更新（不含自身标题）

    @property
    def total(self) -> int:
        return len(self.edits)

    @property
    def affected_files(self) -> List[str]:
        files = sorted({edit.rel_path for edit in self.edits})
        if self.old_rel_path in files:
            files.remove(self.old_rel_path)
            files.append(self.old_rel_path)  # 保持排序的稳定性
            files.sort()
        return files


def _replace_all_boundary(line: str, old: str, new: str) -> str:
    """整行替换全部独立出现（不误伤作为其它编号前缀/后缀的相同数字）。

    章节号是数值层级，直接 ``str.replace`` 会把 ``3.1`` 一并改写进
    ``3.10``/``13.1`` 等更长编号（重编号 ``3.1`` -> ``3.2`` 会把另一处
    引用 ``3.10`` 错改成 ``3.20``）。用词边界（字母数字）限制替换目标，
    既保留同一行多处独立引用的全部更新，又避免前缀误伤。
    """
    pattern = r"(?<![0-9A-Za-z])(?:{0})(?![0-9A-Za-z])".format(re.escape(old))
    return re.sub(pattern, new, line)


class RefactorService:
    """重命名/重编号联动服务。"""

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def compute_rename_plan(
        self,
        old_rel_path: str,
        new_name: str,
    ) -> Optional[RenamePlan]:
        """生成 dry-run 清单；目标不可用返回 None。

        ``new_name`` 为新文件名（含扩展名），如 ``3.7.11 设备管理.md``。
        """
        old_entry = self._index.files.get(old_rel_path)
        if old_entry is None:
            return None
        parent = Path(old_rel_path).parent.as_posix()
        new_rel_path = (
            new_name if parent == "." else "{0}/{1}".format(parent, new_name)
        )

        old_number = section_no_of_file(old_rel_path)
        new_number = section_no_of_file(new_rel_path)
        renumbering = bool(old_number and new_number and old_number != new_number)
        old_basename = Path(old_rel_path).name
        new_basename = Path(new_rel_path).name

        edits: List[EditOp] = []
        for source, refs in self._index.references.items():
            for ref in refs:
                if ref.target_rel_path != old_rel_path:
                    continue
                if ref.kind == REF_SECTION and renumbering:
                    edits.append(
                        EditOp(
                            rel_path=source,
                            line_no=ref.source_line,
                            old_substr=old_number,
                            new_substr=new_number,
                        )
                    )
                elif ref.kind == REF_LINK:
                    if old_basename in ref.source_text:
                        edits.append(
                            EditOp(
                                rel_path=source,
                                line_no=ref.source_line,
                                old_substr=old_basename,
                                new_substr=new_basename,
                            )
                        )

        # 重编号时更新文件自身标题行
        if renumbering:
            title_edit = self._title_edit(old_rel_path, old_number, new_number)
            if title_edit is not None:
                edits.append(title_edit)

        # 去重（同一文件同一行多处同文本替换合并为一次，避免重复替换同一子串）
        edits = self._dedupe(edits)
        return RenamePlan(
            old_rel_path=old_rel_path,
            new_rel_path=new_rel_path,
            edits=edits,
        )

    def apply_rename_plan(self, plan: RenamePlan, writer) -> List:
        """应用 dry-run 清单：先更新引用文本，再重命名文件。

        返回写回结果；每文件 .md.bak + 改动清单，可回滚。
        """
        # 1) 引用文本更新（old 路径下）
        from collections import defaultdict

        by_file: Dict[str, List[EditOp]] = defaultdict(list)
        for edit in plan.edits:
            by_file[edit.rel_path].append(edit)

        results = []
        for rel_path in sorted(by_file):
            new_text = self._rewrite_file(rel_path, by_file[rel_path], writer)
            results.append(writer.write_text(rel_path, new_text))
        # 2) 重命名文件
        results.append(writer.rename(plan.old_rel_path, plan.new_rel_path))
        return results

    # --- 内部 ---

    def _title_edit(
        self, rel_path: str, old_number: str, new_number: str
    ) -> Optional[EditOp]:
        """文件自身标题行：``# 旧编号 ...`` -> ``# 新编号 ...``。"""
        headings = self._index.headings.get(rel_path, [])
        if not headings:
            return None
        first = headings[0]
        if not first.text.startswith(old_number):
            return None
        return EditOp(
            rel_path=rel_path,
            line_no=first.line_no,
            old_substr=old_number,
            new_substr=new_number,
        )

    def _rewrite_file(
        self, rel_path: str, edits: List[EditOp], writer
    ) -> str:
        """对单个文件按行应用替换，保留换行。"""
        target = writer.resolve(rel_path)
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        for edit in edits:
            index = edit.line_no - 1
            if 0 <= index < len(lines):
                lines[index] = _replace_all_boundary(
                    lines[index], edit.old_substr, edit.new_substr
                )
        return "".join(lines)

    @staticmethod
    def _dedupe(edits: List[EditOp]) -> List[EditOp]:
        """同一文件同一行且旧子串相同的替换合并为一条。"""
        seen = {}
        for edit in edits:
            key = (edit.rel_path, edit.line_no, edit.old_substr)
            if key not in seen:
                seen[key] = edit
        return sorted(seen.values(), key=lambda e: (e.rel_path, e.line_no))
