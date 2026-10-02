# -*- coding: utf-8 -*-
"""导入范围：章节勾选、祖先结构保留与范围外引用说明（CORE-D 4.1）。

预览（:mod:`intake_outline` 的章节候选）与最终提取使用同一份决定：本模块把
选中的标题落到实际的章节目录树上，并集中说明三件事：

- 哪些章节被纳入（按源文档顺序，不按点击顺序）；
- 为保持结构自动补入的祖先章节；
- 范围外引用与依赖资源是否可用（不偷偷把未选正文加回来）。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from doc_tool.application.intake_contract import IntakePlan


@dataclass
class ScopeSelection:
    """一次范围选择的落地结果。"""

    selected_ids: List[str] = field(default_factory=list)
    selected_titles: List[str] = field(default_factory=list)
    added_ancestor_ids: List[str] = field(default_factory=list)
    is_full: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "selectedIds": list(self.selected_ids),
            "selectedTitles": list(self.selected_titles),
            "addedAncestors": list(self.added_ancestor_ids),
            "isFull": self.is_full,
        }


@dataclass
class PruneResult:
    """章节树裁剪结果。"""

    kept: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    missing_resources: List[str] = field(default_factory=list)
    dangling_references: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        if self.removed:
            lines.append("未纳入范围 {0} 个章节（正文未加入本项目）".format(len(self.removed)))
        if self.dangling_references:
            lines.append("{0} 处引用指向范围外章节（已在结果中说明）".format(len(self.dangling_references)))
        if self.missing_resources:
            lines.append("{0} 个依赖资源缺失，正文保留占位".format(len(self.missing_resources)))
        lines.extend("提醒：{0}".format(item) for item in self.notes)
        return lines


def selection_from_ids(
    plan: IntakePlan,
    selected_ids: Iterable[str],
    *,
    include_ancestors: bool = True,
) -> ScopeSelection:
    """在导入计划上应用章节勾选，返回落地结果（含祖先补入）。"""
    ids = [str(item) for item in selected_ids]
    added = plan.apply_selection(ids, include_ancestors=include_ancestors)
    selected = plan.selected_sections()
    return ScopeSelection(
        selected_ids=[item.chapter_id for item in selected],
        selected_titles=[item.title for item in selected],
        added_ancestor_ids=list(added),
        is_full=plan.scope_is_full(),
    )


def selection_from_titles(
    plan: IntakePlan,
    titles: Iterable[str],
    *,
    include_ancestors: bool = True,
) -> ScopeSelection:
    """按标题勾选（界面/CLI 常用）：标题匹配不到的项会被忽略并记录。"""
    wanted = {str(item).strip() for item in titles if str(item).strip()}
    ids: List[str] = []
    missed: List[str] = []
    for section in plan.ordered_sections():
        if section.title in wanted:
            ids.append(section.chapter_id)
        elif any(section.title and title in section.title for title in wanted):
            ids.append(section.chapter_id)
    for title in wanted:
        if not any(title in section.title for section in plan.ordered_sections()):
            missed.append(title)
    selection = selection_from_ids(plan, ids, include_ancestors=include_ancestors)
    if missed:
        selection.selected_ids = list(selection.selected_ids)
        plan.warnings.append("未匹配到章节：{0}".format("、".join(missed)))
    return selection


_BOOKMARK_RE = re.compile(r"第\s*(\d+)\s*章")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
_TABLE_RE = re.compile(r"<!--\s*TABLE:\d+:([^\s]+)\s*-->")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def chapter_dir_matches(dir_name: str, title: str) -> bool:
    """章节目录名与标题匹配（目录名形如 ``第1章 引言``）。"""
    name = _norm(dir_name)
    wanted = _norm(title)
    if not wanted:
        return False
    return name == wanted or name.endswith(wanted) or wanted in name


def prune_content_tree(
    content_root: Path,
    selection: ScopeSelection,
    *,
    document_type: str = "general",
    assets_root: Optional[Path] = None,
) -> PruneResult:
    """按范围裁剪 ``contentRoot`` 下的章节树，保留祖先结构。

    只处理一级章节目录与其内部文件；未选章节目录整体移出（删除的是暂存内容，
    源 Word 不受影响），并集中记录范围外引用与缺失资源。
    """
    content_root = Path(content_root)
    result = PruneResult()
    if selection.is_full:
        result.kept = sorted(p.name for p in content_root.iterdir() if p.is_dir())
        return result

    kept_titles = list(selection.selected_titles)
    dirs = sorted(p for p in content_root.iterdir() if p.is_dir())
    removed_titles: List[str] = []
    for directory in dirs:
        if any(chapter_dir_matches(directory.name, title) for title in kept_titles):
            result.kept.append(directory.name)
        else:
            removed_titles.append(directory.name)
            shutil.rmtree(str(directory), ignore_errors=True)
            result.removed.append(directory.name)

    # 范围外引用与依赖资源说明
    for directory in dirs:
        if directory.name not in result.kept:
            continue
        for path in directory.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in _BOOKMARK_RE.finditer(text):
                marker = "第{0}章".format(match.group(1))
                if any(marker in name for name in removed_titles):
                    note = "{0} 引用范围外章节 {1}".format(path.name, marker)
                    if note not in result.dangling_references:
                        result.dangling_references.append(note)
            for target in _IMAGE_RE.findall(text):
                cleaned = target.split(" =", 1)[0].strip()
                if cleaned.startswith(("http://", "https://")):
                    continue
                if "[[待完善" in cleaned:
                    continue
                base_assets = Path(assets_root) if assets_root is not None else (
                    content_root.parent / "assets" / document_type
                )
                candidate = base_assets / cleaned
                if not candidate.is_file():
                    if cleaned not in result.missing_resources:
                        result.missing_resources.append(cleaned)
            for table in _TABLE_RE.findall(text):
                base_assets = Path(assets_root) if assets_root is not None else (
                    content_root.parent / "assets" / document_type
                )
                candidate = base_assets / "tables" / table
                if not candidate.is_file() and table not in result.missing_resources:
                    result.missing_resources.append(table)
    if result.removed:
        renumber_after_prune(content_root, result.kept)
        result.notes.append("已按新范围重排章号，保持编号连续")
    if selection.added_ancestor_ids:
        result.notes.append("为保持结构补入 {0} 个上级章节".format(len(selection.added_ancestor_ids)))
    return result


_CHAPTER_DIR_RE = re.compile(r"^第\s*(\d+)\s*章(.*)$")
_NUMBERED_RE = re.compile(r"^(\d+)((?:\.\d+)*)(\s+.*|\.md|$)")


def renumber_after_prune(content_root: Path, kept_names: Sequence[str]) -> List[str]:
    """范围裁剪后重排章号：一级章按新顺序变为 第1章…，内部编号首段同步。

    内核按目录名/文件名编号校验层级与顺序，裁剪后若保留原编号会被判为
    “编号与层级/顺序不一致”；这里重排到连续编号，标题文本保持不变。
    """
    content_root = Path(content_root)
    renamed: List[str] = []
    dirs = []
    for name in kept_names:
        directory = content_root / name
        if not directory.is_dir():
            continue
        match = _CHAPTER_DIR_RE.match(name)
        old_number = int(match.group(1)) if match else 10 ** 6
        dirs.append((old_number, directory, bool(match)))
    dirs.sort(key=lambda item: (item[0], item[1].name))
    for index, (old_number, directory, matched) in enumerate(dirs, start=1):
        if not matched:
            continue
        title = _CHAPTER_DIR_RE.match(directory.name).group(2)
        new_name = "第{0}章{1}".format(index, title)
        _renumber_descendants(directory, index)
        if new_name != directory.name:
            target = content_root / new_name
            try:
                directory.rename(target)
                renamed.append(new_name)
            except OSError:
                continue
    return renamed


def _renumber_descendants(directory: Path, chapter_number: int) -> None:
    """把章节目录内的 ``3.1`` / ``3.1.2`` 首段改成新的章号。"""
    for path in sorted(directory.rglob("*"), key=lambda item: -len(item.parts)):
        match = _NUMBERED_RE.match(path.name)
        if match is None:
            continue
        suffix = match.group(3) or ""
        if suffix == ".md" and path.stem.split()[0].count(".") == 0:
            continue
        new_name = "{0}{1}{2}".format(chapter_number, match.group(2), suffix)
        if new_name == path.name:
            continue
        try:
            path.rename(path.with_name(new_name))
        except OSError:
            continue


__all__ = [
    "ScopeSelection", "PruneResult", "selection_from_ids", "selection_from_titles",
    "chapter_dir_matches", "prune_content_tree", "renumber_after_prune",
]