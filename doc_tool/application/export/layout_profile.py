# -*- coding: utf-8 -*-
"""有限 Word 排版策略（CORE-G 7.1-7.3）。

默认遵循底模；「正文自适应」只做有确定性规则的三件事，绝不隐藏列、裁剪图片
或任意缩小字号：

1. 普通图片按**当前节正文宽度**等比缩小（小图不放大）；
2. 普通表格（无合并单元格）设置列宽与重复表头，并可按设置允许/禁止跨页断行；
3. 显式章级横向与章前分页：只作用于选定章；该章未形成独立节时按章前分页处理
   并记录事实，不改动其它章。

超宽内容保留并定位提醒（:class:`LayoutOutcome.warnings`）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

MODE_TEMPLATE = "template"
MODE_BODY_ADAPTIVE = "body-adaptive"

TABLE_EQUAL = "equal"
TABLE_PROPORTIONAL = "proportional"
TABLE_KEEP = "keep"

_EMU_PER_MM = 36000


@dataclass
class LayoutProfile:
    """一次出稿的排版设置（缺省=完全遵循底模）。"""

    mode: str = MODE_TEMPLATE
    image_width: str = "auto-width"      #: auto-width / keep
    table_width: str = TABLE_KEEP        #: equal / proportional / keep
    repeat_header: bool = False
    allow_row_split: bool = True
    landscape_chapters: List[str] = field(default_factory=list)
    page_break_before_chapter: bool = False

    @classmethod
    def body_adaptive(cls, **kwargs) -> "LayoutProfile":
        payload = dict(
            mode=MODE_BODY_ADAPTIVE, image_width="auto-width",
            table_width=TABLE_EQUAL, repeat_header=True,
        )
        payload.update(kwargs)
        return cls(**payload)

    @property
    def is_template(self) -> bool:
        return self.mode == MODE_TEMPLATE

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, object]]) -> "LayoutProfile":
        data = dict(data or {})
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        if "landscape_chapters" in payload:
            payload["landscape_chapters"] = [str(item) for item in payload["landscape_chapters"] or []]
        return cls(**payload)


@dataclass
class LayoutOutcome:
    """排版执行事实。"""

    ok: bool = False
    images_scaled: int = 0
    images_kept: int = 0
    tables_formatted: int = 0
    tables_skipped_complex: int = 0
    headers_repeated: int = 0
    page_breaks: int = 0
    landscape_applied: List[str] = field(default_factory=list)
    landscape_skipped: List[str] = field(default_factory=list)
    oversized: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    message: str = ""
    #: MAIN2-E 5.2：本轮是否真的改写了 DOCX 字节（用于决定是否再次刷新/标待刷新）。
    rewritten: bool = False

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        if self.images_scaled:
            lines.append("已按正文宽度等比缩小 {0} 张图片".format(self.images_scaled))
        if self.tables_formatted:
            lines.append("已设置 {0} 个普通表格列宽/表头".format(self.tables_formatted))
        if self.tables_skipped_complex:
            lines.append("{0} 个复杂表格按原样保留".format(self.tables_skipped_complex))
        if self.page_breaks:
            lines.append("已为 {0} 章设置章前分页".format(self.page_breaks))
        if self.landscape_applied:
            lines.append("已横向：{0}".format("、".join(self.landscape_applied)))
        if self.landscape_skipped:
            lines.append("未形成独立节，改为章前分页：{0}".format("、".join(self.landscape_skipped)))
        if self.oversized:
            lines.append("{0} 处内容超宽（已保留并定位，未隐藏列或缩小字号）".format(len(self.oversized)))
        lines.extend("提醒：{0}".format(item) for item in self.warnings)
        if not lines:
            lines.append("排版沿用底模，未做自动调整")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _section_text_width_emu(section) -> int:
    try:
        return int(section.page_width) - int(section.left_margin) - int(section.right_margin)
    except Exception:  # noqa: BLE001 - 缺少节属性时按 A4 正文宽度估算
        return int(210 * _EMU_PER_MM) - int(2 * 25 * _EMU_PER_MM)


def _scale_images(document, profile: LayoutProfile, outcome: LayoutOutcome) -> None:
    from docx.shared import Emu

    for section in document.sections:
        limit = _section_text_width_emu(section)
        for shape in document.inline_shapes:
            try:
                width = int(shape.width)
                height = int(shape.height)
            except Exception:  # noqa: BLE001 - 非图片图形跳过
                continue
            if width <= limit:
                outcome.images_kept += 1
                continue
            ratio = limit / float(width)
            try:
                shape.width = Emu(limit)
                shape.height = Emu(int(height * ratio))
                outcome.images_scaled += 1
            except Exception as exc:  # noqa: BLE001 - 单张失败不影响其它
                outcome.warnings.append("图片缩放失败：{0}".format(exc))
        break  # 同一文档通常只有一种正文宽度；多节时按第一节宽度为准


def _format_tables(document, profile: LayoutProfile, outcome: LayoutOutcome) -> None:
    from docx.oxml.ns import qn

    for table in document.tables:
        if _table_is_complex(table):
            outcome.tables_skipped_complex += 1
            continue
        try:
            if profile.table_width in (TABLE_EQUAL, TABLE_PROPORTIONAL):
                column_count = max(len(table.columns), 1)
                width = int(_section_text_width_emu(document.sections[0]) / column_count)
                for row in table.rows:
                    for index, cell in enumerate(row.cells):
                        cell.width = width if profile.table_width == TABLE_EQUAL else cell.width
            if profile.repeat_header and table.rows:
                header = table.rows[0]
                tr_pr = header._tr.get_or_add_trPr()
                if tr_pr.find(qn("w:tblHeader")) is None:
                    element = tr_pr.makeelement(qn("w:tblHeader"), {})
                    tr_pr.append(element)
                    outcome.headers_repeated += 1
            if not profile.allow_row_split:
                for row in table.rows:
                    tr_pr = row._tr.get_or_add_trPr()
                    if tr_pr.find(qn("w:cantSplit")) is None:
                        tr_pr.append(tr_pr.makeelement(qn("w:cantSplit"), {}))
            outcome.tables_formatted += 1
        except Exception as exc:  # noqa: BLE001 - 单个表格失败不影响其它
            outcome.warnings.append("表格排版失败：{0}".format(exc))


def _table_is_complex(table) -> bool:
    """存在合并单元格即视为复杂表格：默认原样保留，不做自动列宽。"""
    try:
        for row in table.rows:
            seen = set()
            for cell in row.cells:
                key = cell._tc
                if key in seen:
                    return True
                seen.add(key)
        for column in table.columns:
            seen = set()
            for cell in column.cells:
                key = cell._tc
                if key in seen:
                    return True
                seen.add(key)
    except Exception:  # noqa: BLE001 - 结构不可判定时按复杂处理
        return True
    return False


def _chapter_paragraphs(document, title: str):
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        if title in text:
            yield paragraph


def apply_layout_to_docx(
    docx_path,
    profile: LayoutProfile,
    *,
    chapter_titles: Sequence[str] = (),
) -> LayoutOutcome:
    """把排版策略应用到已生成的 DOCX（原地重写，失败保留原文件）。"""
    from docx import Document
    from docx.enum.text import WD_BREAK

    path = Path(docx_path)
    outcome = LayoutOutcome()
    if not path.is_file():
        outcome.message = "DOCX 不存在：{0}".format(path)
        return outcome
    if profile.is_template and not profile.landscape_chapters and not profile.page_break_before_chapter:
        outcome.ok = True
        outcome.message = "沿用底模，未做自动调整"
        return outcome
    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001 - 打不开就保留原产物
        outcome.message = "无法打开 DOCX 进行排版：{0}".format(exc)
        return outcome

    if profile.image_width == "auto-width":
        _scale_images(document, profile, outcome)
    if profile.table_width != TABLE_KEEP or profile.repeat_header or not profile.allow_row_split:
        _format_tables(document, profile, outcome)

    if profile.page_break_before_chapter:
        for title in chapter_titles or profile.landscape_chapters:
            for paragraph in _chapter_paragraphs(document, title):
                if paragraph.runs and paragraph.runs[0].text.startswith("\f"):
                    break
                run = paragraph.insert_paragraph_before().add_run()
                run.add_break(WD_BREAK.PAGE)
                outcome.page_breaks += 1
                break

    if profile.landscape_chapters:
        _apply_landscape(document, profile, outcome)

    try:
        document.save(str(path))
        outcome.ok = True
        outcome.rewritten = True
        outcome.message = "排版已应用"
    except Exception as exc:  # noqa: BLE001
        outcome.message = "排版保存失败，已保留原产物：{0}".format(exc)
    return outcome


def _apply_landscape(document, profile: LayoutProfile, outcome: LayoutOutcome) -> None:
    """显式章级横向：仅当该章已有独立节时切换方向，否则记录并保留模板方向。"""
    from docx.enum.section import WD_ORIENT

    for title in profile.landscape_chapters:
        paragraphs = list(_chapter_paragraphs(document, title))
        if not paragraphs:
            outcome.landscape_skipped.append(title)
            outcome.warnings.append("未找到章节「{0}」，横向未应用".format(title))
            continue
        paragraph = paragraphs[0]
        section = _owning_section(document, paragraph)
        if section is None or not _section_starts_at(document, section, paragraph):
            outcome.landscape_skipped.append(title)
            outcome.warnings.append(
                "章节「{0}」未形成独立节：已保留模板方向，可按章前分页处理".format(title)
            )
            continue
        try:
            width, height = section.page_width, section.page_height
            section.orientation = WD_ORIENT.LANDSCAPE
            section.page_width, section.page_height = max(width, height), min(width, height)
            outcome.landscape_applied.append(title)
        except Exception as exc:  # noqa: BLE001
            outcome.landscape_skipped.append(title)
            outcome.warnings.append("章节「{0}」横向设置失败：{1}".format(title, exc))


def _body_children(document):
    return list(document.element.body)


def _owning_section(document, paragraph):
    """按 body 顺序判断段落属于哪个节（节在 sectPr 处结束）。"""
    try:
        body = _body_children(document)
        target = paragraph._p
        section_index = 0
        for child in body:
            if child is target:
                break
            if child.tag.endswith("}sectPr"):
                section_index += 1
        sections = list(document.sections)
        return sections[min(section_index, len(sections) - 1)] if sections else None
    except Exception:  # noqa: BLE001
        return None


def _section_starts_at(document, section, paragraph) -> bool:
    """该段是否紧跟在节分隔之后（即该节的第一段）——用于判断能否安全横向。"""
    try:
        body = _body_children(document)
        target = paragraph._p
        index = body.index(target)
        if index == 0:
            return True
        previous = body[index - 1]
        if previous.tag.endswith("}sectPr"):
            return True
        # 段落自身携带 sectPr（节结束标记）不算“节开始”
        return False
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "MODE_TEMPLATE", "MODE_BODY_ADAPTIVE", "TABLE_EQUAL", "TABLE_PROPORTIONAL",
    "TABLE_KEEP", "LayoutProfile", "LayoutOutcome", "apply_layout_to_docx",
]