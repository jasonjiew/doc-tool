# -*- coding: utf-8 -*-
"""Versioned PDF/HTML review exports and page image comparison."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.content.preview import render_markdown_html


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _review_dir(output_dir: Path) -> Path:
    target = Path(output_dir) / "review"
    target.mkdir(parents=True, exist_ok=True)
    return target


def export_html(chapters: Sequence[Tuple[str, str]], output_dir: Path, version: str) -> Path:
    import html as _html

    navigation = []
    sections = []
    for index, (title, markdown) in enumerate(chapters, start=1):
        anchor = "chapter-{0}".format(index)
        safe_title = _html.escape(str(title), quote=True)
        navigation.append('<li><a href="#{0}">{1}</a></li>'.format(anchor, safe_title))
        sections.append(
            '<section id="{0}" data-rel-path="{1}"><h1>{1}</h1>{2}</section>'.format(
                anchor, safe_title, render_markdown_html(markdown, use_cli=True)
            )
        )
    document = """<!doctype html><html><head><meta charset="utf-8"><title>Review {0}</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:1100px;margin:auto;display:grid;grid-template-columns:230px 1fr;gap:24px}}nav{{position:sticky;top:0;height:100vh}}section{{border-bottom:1px solid #ddd;padding-bottom:24px}}table{{border-collapse:collapse}}</style>
</head><body><nav><h2>章节导航</h2><ul>{1}</ul></nav><main>{2}</main></body></html>""".format(version, "".join(navigation), "".join(sections))
    target = _review_dir(output_dir) / "review-{0}-{1}.html".format(version, _stamp())
    target.write_text(document, encoding="utf-8")
    return target


def export_pdf(
    chapters: Sequence[Tuple[str, str]],
    output_dir: Path,
    version: str,
    *,
    word_exporter: Optional[Callable[[Path], bool]] = None,
) -> Path:
    target = _review_dir(output_dir) / "review-{0}-{1}.pdf".format(version, _stamp())
    if word_exporter is not None and word_exporter(target):
        return target
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    font_name = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font_name
    story = [Paragraph("非 Word 导出 - 版式仅供评审", styles["Heading2"]), Spacer(1, 12)]
    for index, (title, markdown) in enumerate(chapters):
        story.append(Paragraph(title, styles["Heading1"]))
        for line in markdown.splitlines():
            plain = re.sub(r"^#{1,6}\s*", "", line).strip()
            if plain:
                story.append(Paragraph(plain.replace("&", "&amp;").replace("<", "&lt;"), styles["BodyText"]))
                story.append(Spacer(1, 5))
        if index + 1 < len(chapters):
            story.append(PageBreak())
    SimpleDocTemplate(str(target), pagesize=A4, title="Review " + version).build(story)
    return target


@dataclass
class DiffRegion:
    page: int
    box: Tuple[int, int, int, int]
    rel_path: str = ""
    line_no: int = 1
    viewed: bool = False

    def mark_viewed(self) -> Tuple[str, int]:
        self.viewed = True
        return self.rel_path, self.line_no


def pixel_diff_regions(old_image, new_image, *, page: int = 1, rel_path: str = "") -> List[DiffRegion]:
    from PIL import ImageChops
    if old_image.size != new_image.size:
        return [DiffRegion(page, (0, 0, max(old_image.width, new_image.width), max(old_image.height, new_image.height)), rel_path)]
    diff = ImageChops.difference(old_image.convert("RGB"), new_image.convert("RGB"))
    box = diff.getbbox()
    return [DiffRegion(page, box, rel_path)] if box else []


class VisualDiffService:
    def compare(
        self,
        old_pages: Sequence,
        new_pages: Sequence,
        *,
        old_snapshot_hash: str,
        new_snapshot_hash: str,
        rel_paths: Optional[Sequence[str]] = None,
    ) -> List[DiffRegion]:
        if not old_snapshot_hash or not new_snapshot_hash:
            raise ValueError("无对比基线")
        if old_snapshot_hash == new_snapshot_hash:
            return []
        regions: List[DiffRegion] = []
        count = max(len(old_pages), len(new_pages))
        for index in range(count):
            rel_path = rel_paths[index] if rel_paths and index < len(rel_paths) else ""
            if index >= len(old_pages) or index >= len(new_pages):
                # 仅存在于新版或旧版的页：取实际存在那一页的尺寸做差异区域。
                # 不能取拼接后第 0 页——那总是旧版首页，页尺寸会取错。
                page = new_pages[index] if index < len(new_pages) else old_pages[index]
                regions.append(DiffRegion(index + 1, (0, 0, page.width, page.height), rel_path))
            else:
                regions.extend(pixel_diff_regions(old_pages[index], new_pages[index], page=index + 1, rel_path=rel_path))
        return regions
