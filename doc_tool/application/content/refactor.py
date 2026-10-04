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
import posixpath
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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
    renames: List[Tuple[str, str]] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.renames and self.old_rel_path and self.new_rel_path:
            self.renames = [(self.old_rel_path, self.new_rel_path)]

    @property
    def total(self) -> int:
        return len(self.edits)

    @property
    def affected_files(self) -> List[str]:
        return sorted(
            {edit.rel_path for edit in self.edits}
            | {old for old, _new in self.renames}
        )

    @property
    def can_apply(self) -> bool:
        return not self.conflicts


@dataclass
class ChapterCopyResult:
    """章节复制结果（MAIN-B 2.3）。"""

    ok: bool
    source: str = ""
    target: str = ""
    #: 旧条目 ID -> 新条目 ID（复制出的章节必须是独立身份）
    item_ids: Dict[str, str] = field(default_factory=dict)
    message: str = ""
    written: bool = False

    def summary_line(self) -> str:
        if not self.ok:
            return "复制未完成：{0}".format(self.message or "未知原因")
        return "已复制为 {0}（{1} 个条目重新生成身份）".format(
            self.target, len(self.item_ids)
        )


def copy_chapter_markdown(text: str, *, title: str = "", project_id: str = "") -> Tuple[str, Dict[str, str]]:
    """生成章节副本的 Markdown：标题可换，条目标记全部换成新 ID。

    身份契约（``traceable_items``）：移动/重命名保持原 ID，**复制**必须产生新 ID，
    否则两份正文共用同一 ``(projectId, itemId)``，追溯矩阵与关系端点会把它们当成
    同一个条目。``project_id`` 非空时可同时把条目标记迁到目标项目。
    """
    from doc_tool.application.content.traceable_items import (
        DOC_ITEM_RE, ItemRef, parse_marker,
    )

    mapping: Dict[str, str] = {}
    content = str(text or "")

    def _rebuild(match: "re.Match") -> str:
        ref, _error = parse_marker(match.group(0))
        if ref is None:
            return match.group(0)
        new_ref = ItemRef(
            project_id=project_id or ref.project_id,
            item_id=str(uuid.uuid4()),
            kind=ref.kind,
            alias=ref.alias,
        )
        mapping[ref.item_id] = new_ref.item_id
        return new_ref.render()

    content = DOC_ITEM_RE.sub(_rebuild, content)
    if title:
        lines = content.splitlines()
        replaced = False
        for index, line in enumerate(lines):
            match = re.match(r"^(\s{0,3}#{1,6}\s+)(\S.*?)\s*$", line)
            if match:
                lines[index] = match.group(1) + title
                replaced = True
                break
        if replaced:
            content = "\n".join(lines) + ("\n" if str(text or "").endswith("\n") else "")
    return content, mapping


def copy_chapter(
    index: ContentIndex,
    rel_path: str,
    writer,
    *,
    title: str = "",
    source_text: Optional[str] = None,
) -> ChapterCopyResult:
    """把一章复制为同目录下的新章节：新路径 + 新条目身份 + 不覆盖任何现有文件。

    ``source_text``（MAIN2-C 3.1）传入**当前有效正文**（编辑器活缓冲）时以它为准，
    不再读 ``index.lines``：否则未保存的编辑会被旧索引内容顶替。不传时保持原行为。
    """
    rel_path = str(rel_path or "").replace("\\", "/")
    if not rel_path:
        return ChapterCopyResult(ok=False, message="未指定要复制的章节。")
    files = list(index.all_files())
    current = None if source_text is None else str(source_text)
    if rel_path not in files:
        return ChapterCopyResult(ok=False, source=rel_path, message="章节不在当前索引中。")
    if current is not None:
        body = current
    else:
        body = "\n".join(index.lines.get(rel_path, []))
    if body and not body.endswith("\n"):
        body += "\n"
    source_text = body
    stem = Path(rel_path).stem
    new_title = str(title or "").strip() or (stem + "（副本）")
    from doc_tool.application.content.tree import next_chapter_rel_path

    directory = Path(rel_path).parent.as_posix()
    directory = "" if directory == "." else directory
    # 顶层目录（contentRoot 根）时目录前缀为空，next_chapter_rel_path 会带出
    # 前导 "/"，这里归一成真实相对路径。
    target = next_chapter_rel_path(directory, files, new_title).lstrip("/")
    new_text, mapping = copy_chapter_markdown(source_text, title=new_title)
    result = writer.create_file(target, new_text)
    if not result.written:
        return ChapterCopyResult(
            ok=False, source=rel_path, target=target,
            message=result.error or "写入失败",
        )
    return ChapterCopyResult(
        ok=True, source=rel_path, target=target, item_ids=mapping, written=True,
    )


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
        parent = Path(old_rel_path).parent.as_posix()
        new_rel_path = (
            new_name if parent == "." else "{0}/{1}".format(parent, new_name)
        )

        return self.compute_batch_rename_plan([(old_rel_path, new_rel_path)])

    def compute_batch_rename_plan(
        self, renames: Sequence[Tuple[str, str]]
    ) -> Optional[RenamePlan]:
        """聚合多文件路径变更与引用编辑，执行跨文件冲突检测。"""
        normalized = [(old.replace("\\", "/"), new.replace("\\", "/")) for old, new in renames]
        normalized = [(old, new) for old, new in normalized if old != new]
        if any(old not in self._index.files for old, _new in normalized):
            return None
        old_paths = [old for old, _new in normalized]
        new_paths = [new for _old, new in normalized]
        conflicts: List[str] = []
        if len(old_paths) != len(set(old_paths)):
            conflicts.append("批量计划包含重复源路径")
        if len(new_paths) != len(set(new_paths)):
            conflicts.append("批量计划包含重复目标路径")
        occupied = set(self._index.files) - set(old_paths)
        for target in sorted(set(new_paths) & occupied):
            conflicts.append("目标文件已存在：{0}".format(target))

        edits: List[EditOp] = []
        for old_rel_path, new_rel_path in normalized:
            old_number = section_no_of_file(old_rel_path)
            new_number = section_no_of_file(new_rel_path)
            renumbering = bool(old_number and new_number and old_number != new_number)
            old_basename = Path(old_rel_path).name
            new_basename = Path(new_rel_path).name
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
            if renumbering:
                title_edit = self._title_edit(old_rel_path, old_number, new_number)
                if title_edit is not None:
                    edits.append(title_edit)

        # 同时考虑链接来源章和目标章的新位置，跨目录移动后仍使用有效相对路径。
        path_map = dict(normalized)
        for source, refs in self._index.references.items():
            new_source = path_map.get(source, source)
            for ref in refs:
                if ref.kind != REF_LINK or not ref.target or not ref.target_rel_path:
                    continue
                target = ref.target_rel_path
                new_target = path_map.get(target, target)
                if new_source == source and new_target == target:
                    continue
                relative = posixpath.relpath(new_target, posixpath.dirname(new_source) or ".")
                old_link = str(ref.target)
                # 既有链接采用百分号编码时保持相同形式；锚点由解析器留在原行中。
                if urllib.parse.unquote(old_link) != old_link:
                    relative = urllib.parse.quote(relative, safe="/.-_")
                if old_link != relative:
                    edits.append(EditOp(source, ref.source_line, old_link, relative))

        # 去重（同一文件同一行多处同文本替换合并为一次，避免重复替换同一子串）
        edits, edit_conflicts = self._dedupe(edits)
        conflicts.extend(edit_conflicts)
        return RenamePlan(
            old_rel_path=normalized[0][0] if normalized else "",
            new_rel_path=normalized[0][1] if normalized else "",
            edits=edits,
            renames=normalized,
            conflicts=conflicts,
        )

    def apply_rename_plan(self, plan: RenamePlan, writer) -> List:
        """应用 dry-run 清单：先更新引用文本，再重命名文件。

        返回写回结果；每文件 .md.bak + 改动清单，可回滚。
        """
        if not plan.can_apply:
            raise ValueError("；".join(plan.conflicts))
        # 1) 引用文本更新（old 路径下）
        from collections import defaultdict

        by_file: Dict[str, List[EditOp]] = defaultdict(list)
        for edit in plan.edits:
            by_file[edit.rel_path].append(edit)

        writer.manifest.load()
        checkpoint = len(writer.manifest.entries)
        results = []
        try:
            for rel_path in sorted(by_file):
                new_text = self._rewrite_file(rel_path, by_file[rel_path], writer)
                result = writer.write_text(rel_path, new_text, operation="refactor")
                results.append(result)
                if not result.written:
                    raise OSError(result.error or "引用写回失败")
            # 2) 全部源文件先移到事务临时路径，交换/轮转也不会互相占位。
            staged = []
            for order, (old_path, new_path) in enumerate(plan.renames):
                temp_path = self._temporary_rel_path(old_path, order, writer)
                result = writer.rename(old_path, temp_path, create_backup=False)
                results.append(result)
                if not result.written:
                    raise OSError(result.error or "临时移动失败")
                staged.append((temp_path, new_path))
            for temp_path, new_path in staged:
                result = writer.rename(temp_path, new_path, create_backup=False)
                results.append(result)
                if not result.written:
                    raise OSError(result.error or "目标移动失败")
        except Exception:
            writer.rollback(since=checkpoint)
            # record() deduplicates an already-edited file, so its entry can remain
            # before checkpoint. Roll back the writes by key as well as new moves.
            from doc_tool.application.content.writer import OP_EDIT
            writer.rollback_keys({(OP_EDIT, result.rel_path) for result in results
                                  if result.written and result.rel_path in by_file})
            raise
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
        by_line: Dict[int, List[EditOp]] = {}
        for edit in edits:
            by_line.setdefault(edit.line_no, []).append(edit)
        for line_no, line_edits in by_line.items():
            index = line_no - 1
            if not (0 <= index < len(lines)):
                continue
            line = lines[index]
            placeholders = {}
            for order, edit in enumerate(sorted(line_edits, key=lambda item: -len(item.old_substr))):
                placeholder = "\x00DOC_TOOL_MOVE_{0}\x00".format(order)
                updated = _replace_all_boundary(line, edit.old_substr, placeholder)
                if updated != line:
                    placeholders[placeholder] = edit.new_substr
                    line = updated
            for placeholder, replacement in placeholders.items():
                line = line.replace(placeholder, replacement)
            lines[index] = line
        return "".join(lines)

    @staticmethod
    def _dedupe(edits: List[EditOp]):
        """同一文件同一行且旧子串相同的替换合并为一条。"""
        seen = {}
        conflicts = []
        for edit in edits:
            key = (edit.rel_path, edit.line_no, edit.old_substr)
            existing = seen.get(key)
            if existing is not None and existing.new_substr != edit.new_substr:
                conflicts.append(
                    "同一引用存在多个目标：{0}:{1} {2}".format(
                        edit.rel_path, edit.line_no, edit.old_substr
                    )
                )
            elif existing is None:
                seen[key] = edit
        return sorted(seen.values(), key=lambda e: (e.rel_path, e.line_no)), conflicts

    @staticmethod
    def _temporary_rel_path(old_path: str, order: int, writer) -> str:
        parent = Path(old_path).parent.as_posix()
        name = ".doc-tool-move-{0}-{1}.tmp".format(order, Path(old_path).name)
        candidate = name if parent == "." else parent + "/" + name
        suffix = 1
        while writer.resolve(candidate).exists():
            candidate = (name + "-{0}".format(suffix)) if parent == "." else parent + "/" + name + "-{0}".format(suffix)
            suffix += 1
        return candidate
