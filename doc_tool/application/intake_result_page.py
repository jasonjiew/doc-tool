# -*- coding: utf-8 -*-
"""导入结果页模型与就地补救（CORE-C 3.3 / U-7）。

先给可打开项目与“待完善数量”，再按类型/章节归并缺口，默认最多 3 项有直接
行动价值的问题；完整处理事实与自动处理项放在详情里。每个行动都连接一个
**现有服务**，不要求用户从长日志里找步骤：

- ``locate``：解析到具体章节相对路径，交给编辑器定位；
- ``view-original``：打开 ``original/source.docx``（原件留存）；
- ``replace-image``：把用户选择的图片复制进项目资源目录并改写正文占位
  （复用 ``ContentWriter`` 备份/原子写与既有图片命名服务）。

替换成功后该处理事实转为“可编辑保留”，导入记录与结果页数量同步更新。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.application.import_record import (
    HANDLING_EDITABLE,
    ImportRecord,
    read_import_record,
    write_import_record,
)
from doc_tool.application.intake_contract import (
    DEFAULT_ACTIONABLE_LIMIT,
    HANDLING_ORIGINAL_ONLY,
    HANDLING_PLACEHOLDER,
    PLACEHOLDER_PREFIX,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths

#: 行动类型。
ACTION_LOCATE = "locate"
ACTION_VIEW_ORIGINAL = "view-original"
ACTION_REPLACE_IMAGE = "replace-image"


@dataclass
class ResultAction:
    """一条可直接执行的补救动作。"""

    kind: str
    label: str
    detail: str = ""
    relPath: str = ""
    line: Optional[int] = None
    feature: str = ""
    retainedPath: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind, "label": self.label, "detail": self.detail,
            "relPath": self.relPath, "line": self.line, "feature": self.feature,
            "retainedPath": self.retainedPath,
        }


@dataclass
class IntakeResultPage:
    """导入结果页模型（服务层，界面只负责渲染）。"""

    projectRoot: str = ""
    retainedPath: str = ""
    summary: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    groups: Dict[str, int] = field(default_factory=dict)
    actions: List[ResultAction] = field(default_factory=list)
    details: List[Dict[str, object]] = field(default_factory=list)
    autoHandled: int = 0
    toFix: int = 0
    unavailableComparisons: List[str] = field(default_factory=list)
    hasRecord: bool = False

    @property
    def needsAttention(self) -> bool:
        return bool(self.actions) or self.toFix > 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "projectRoot": self.projectRoot,
            "retainedPath": self.retainedPath,
            "summary": list(self.summary),
            "counts": dict(self.counts),
            "groups": dict(self.groups),
            "actions": [item.to_dict() for item in self.actions],
            "details": list(self.details),
            "autoHandled": self.autoHandled,
            "toFix": self.toFix,
            "unavailableComparisons": list(self.unavailableComparisons),
            "hasRecord": self.hasRecord,
        }


_LABELS = {
    ACTION_LOCATE: "定位正文",
    ACTION_VIEW_ORIGINAL: "查看原件",
    ACTION_REPLACE_IMAGE: "选择替代图片",
}


def resolve_chapter_rel_path(project_root, title: str) -> str:
    """把章节标题解析为 contentRoot 相对路径（找不到返回空串）。"""
    project_root = Path(project_root)
    try:
        manifest = ProjectManifest.load(project_root)
        paths = ProjectPaths(project_root)
        content_root = paths.resolve(manifest.relative_content_root())
    except Exception:  # noqa: BLE001 - 清单不可读时不猜路径
        return ""
    wanted = _norm(title)
    if not wanted:
        return ""
    from doc_tool.application.effective_snapshot import discover_chapters

    candidates = discover_chapters(content_root)
    for rel_path, _path in candidates:
        directory = _norm(Path(rel_path).parent.name)
        stem = _norm(Path(rel_path).stem)
        if wanted == directory or wanted == stem or wanted in directory:
            return rel_path
    # 章节正文写在目录 _index.md 时（单章项目常见），按目录名匹配该文件
    for directory in sorted(path for path in content_root.rglob("*") if path.is_dir()):
        name = _norm(directory.name)
        if wanted and (wanted in name or name in wanted):
            index_file = directory / "_index.md"
            if index_file.is_file():
                return index_file.relative_to(content_root).as_posix()
            siblings = sorted(directory.glob("*.md"))
            if siblings:
                return siblings[0].relative_to(content_root).as_posix()
    return ""


def _norm(value: str) -> str:
    import re

    return re.sub(r"\s+", "", str(value or ""))


def build_result_page(project_root, *, limit: int = DEFAULT_ACTIONABLE_LIMIT) -> IntakeResultPage:
    """读取导入记录，构造结果页模型（无记录时给最小页）。"""
    project_root = Path(project_root)
    record = read_import_record(project_root)
    page = IntakeResultPage(projectRoot=str(project_root), hasRecord=record is not None)
    if record is None:
        page.summary = ["项目已生成，可直接编辑"]
        return page
    page.retainedPath = record.retainedPath
    page.counts = record.counts_by_handling()
    page.autoHandled = record.auto_handled_count()
    page.toFix = record.to_fix_count()
    page.unavailableComparisons = list(record.unavailableComparisons)
    page.groups = {
        key: len(items) for key, items in record.grouped().items()
    }
    page.summary = record.summary_lines(limit=limit)
    for item in record.findings:
        page.details.append(item.to_dict())
    for action in record.result_actions(limit=limit):
        kind = str(action.get("kind") or ACTION_LOCATE)
        feature = str(action.get("feature") or "")
        if feature == "image" and str(action.get("handling") or "") == HANDLING_PLACEHOLDER:
            kind = ACTION_REPLACE_IMAGE
        elif kind == "view-original" and feature != "image":
            kind = ACTION_VIEW_ORIGINAL
        title = str(action.get("chapter") or "")
        rel_path = resolve_chapter_rel_path(project_root, title) if title else ""
        page.actions.append(ResultAction(
            kind=kind,
            label=str(action.get("action") or _LABELS.get(kind, kind)),
            detail=str(action.get("label") or ""),
            relPath=rel_path,
            line=action.get("line") if isinstance(action.get("line"), int) else None,
            feature=feature,
            retainedPath=str(action.get("retainedPath") or record.retainedPath),
        ))
    if not page.summary:
        page.summary = ["项目已生成，可直接编辑"]
    return page


@dataclass
class ReplaceImageOutcome:
    """替换占位图片的结果。"""

    ok: bool = False
    message: str = ""
    relPath: str = ""
    imageRelPath: str = ""
    line: Optional[int] = None
    updatedFindings: int = 0

    def summary_line(self) -> str:
        if not self.ok:
            return "替换未完成：{0}".format(self.message or "未知原因")
        return "已在 {0} 第 {1} 行替换为 {2}".format(
            self.relPath, self.line or 0, self.imageRelPath
        )


def replace_placeholder_image(
    project_root,
    rel_path: str,
    source_image,
    *,
    line: Optional[int] = None,
) -> ReplaceImageOutcome:
    """把一个正文占位替换为用户选择的图片（复用资源服务与写入安全）。"""
    from doc_tool.application.content.asset_manager import next_image_name
    from doc_tool.application.content.writer import ContentWriter

    outcome = ReplaceImageOutcome(relPath=str(rel_path))
    project_root = Path(project_root)
    source_image = Path(source_image)
    if not source_image.is_file():
        outcome.message = "选择的图片不存在"
        return outcome
    try:
        manifest = ProjectManifest.load(project_root)
        paths = ProjectPaths(project_root)
        content_root = paths.resolve(manifest.relative_content_root())
    except Exception as exc:  # noqa: BLE001
        outcome.message = "项目清单不可读：{0}".format(exc)
        return outcome
    target = (content_root / str(rel_path)).resolve()
    try:
        target.relative_to(content_root.resolve())
    except ValueError:
        outcome.message = "章节路径越出项目根"
        return outcome
    if not target.is_file():
        outcome.message = "章节文件不存在：{0}".format(rel_path)
        return outcome

    lines = target.read_text(encoding="utf-8").splitlines()
    index = _find_placeholder_line(lines, line)
    if index is None:
        outcome.message = "未找到可替换的占位行"
        return outcome

    ext = source_image.suffix.lstrip(".").lower() or "png"
    image_name = next_image_name(paths.assets_dir(manifest.documentType), manifest.documentType, ext)
    image_target = paths.images_dir(manifest.documentType) / image_name
    try:
        image_target.parent.mkdir(parents=True, exist_ok=True)
        image_target.write_bytes(source_image.read_bytes())
    except OSError as exc:
        outcome.message = "复制图片失败：{0}".format(exc)
        return outcome

    try:
        text = "".join(
            line + "\n" for line in _rewrite_placeholder(lines, index, image_name, source_image.stem)
        )
        writer = ContentWriter(content_root, paths.state_dir, paths.assets_dir(manifest.documentType))
        result = writer.write_text(str(rel_path), text)
        if not getattr(result, "written", False):
            outcome.message = getattr(result, "error", "") or "写入未完成（原文件保留）"
            return outcome
    except Exception as exc:  # noqa: BLE001 - 保留原文件，给出原因
        outcome.message = "写入失败：{0}".format(exc)
        return outcome

    outcome.ok = True
    outcome.imageRelPath = "images/" + image_name
    outcome.line = index + 1
    outcome.updatedFindings = _mark_finding_resolved(project_root, rel_path, target)
    return outcome


def _find_placeholder_line(lines: Sequence[str], line: Optional[int]) -> Optional[int]:
    if line is not None:
        position = int(line) - 1
        if 0 <= position < len(lines) and PLACEHOLDER_PREFIX in lines[position]:
            return position
    for position, text in enumerate(lines):
        if PLACEHOLDER_PREFIX in text and "图片" in text:
            return position
    for position, text in enumerate(lines):
        if PLACEHOLDER_PREFIX in text:
            return position
    return None


def _rewrite_placeholder(
    lines: Sequence[str], index: int, image_name: str, alt: str,
) -> List[str]:
    rewritten = list(lines)
    label = (alt or "替换图片").replace("]", "）").replace("[", "（")
    rewritten[index] = "![{0}](images/{1})".format(label, image_name)
    return rewritten


def _mark_finding_resolved(project_root: Path, rel_path: str, target: Path) -> int:
    """把该章节的图片占位事实改为“可编辑保留”，保持账本与界面数量一致。"""
    record = read_import_record(project_root)
    if record is None:
        return 0
    changed = 0
    chapter_title = Path(rel_path).parent.name
    for item in record.findings:
        if item.feature != "image" or item.handling != HANDLING_PLACEHOLDER:
            continue
        if item.target_chapter and _norm(item.target_chapter) not in _norm(chapter_title):
            continue
        item.handling = HANDLING_EDITABLE
        item.editable = True
        item.detail = (item.detail or "") + "；已由用户替换为项目内图片"
        changed += 1
    if changed:
        write_import_record(project_root, record)
    return changed


__all__ = [
    "ACTION_LOCATE", "ACTION_VIEW_ORIGINAL", "ACTION_REPLACE_IMAGE",
    "ResultAction", "IntakeResultPage", "ReplaceImageOutcome",
    "build_result_page", "resolve_chapter_rel_path", "replace_placeholder_image",
]