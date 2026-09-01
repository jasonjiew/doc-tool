# -*- coding: utf-8 -*-
"""Word(.docx) → 单文件 Markdown + assets 目录。

复用导入链路的 ``adapters.importer.extract_content``（它已经会把标题层级、表格、
图片、加粗/斜体等正确还原成 Markdown），但它产出的是「按一级章节拆分的多文件 +
构建方言注记」，面向的是本项目的工作台。本模块负责把它折成一份读者可直接使用的
单文件 Markdown：

- 章节按源文档顺序合并，不再拆文件；
- 丢弃只对构建有意义的注记（``<!-- P: -->`` 行距注记、``<!-- TBL: -->`` 表宽注记、
  ``<EMPTY_PAR/>`` 空段占位）；
- 复杂表格无法用 Markdown 表达，原样导出为 assets 下的 OOXML 资源并在正文留提示；
- 图片落到 ``<输出名>_assets/images/``，链接改写为标准 Markdown——因此
  ``![alt](images/x.png =96x96)`` 的显示尺寸后缀会被去掉（那是本项目的方言，
  通用 Markdown 渲染器会把它当成 URL 的一部分）。
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_CHAPTER_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()images/([^)\s]+)(?:\s+=[\dxX]+)?(\))")
_COMPLEX_TABLE_RE = re.compile(r"^<!--\s*TABLE:(\d+)(?::([\w.\-]+))?\s*-->\s*$")
_BUILD_NOTE_RE = re.compile(r"^\s*<!--\s*(?:P|TBL):.*-->\s*$")
_EMPTY_PAR_RE = re.compile(r"^\s*<EMPTY_PAR/>\s*$")


@dataclass
class MarkdownExportOutcome:
    """一次 Word→Markdown 的结果。"""

    ok: bool
    reason: str
    detail: str = ""
    error_code: Optional[str] = None
    chapters: int = 0
    images: int = 0
    tables: int = 0
    complex_tables: int = 0
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "detail": self.detail,
            "errorCode": self.error_code,
            "chapters": self.chapters,
            "images": self.images,
            "tables": self.tables,
            "complexTables": self.complex_tables,
            "elapsedSeconds": round(self.elapsed_seconds, 2),
        }


def _rewrite_line(line: str, assets_name: str) -> List[str]:
    """把一行提取结果改写为面向读者的 Markdown 行；返回要写出的行列表。"""
    if _BUILD_NOTE_RE.match(line) or _EMPTY_PAR_RE.match(line):
        return []
    complex_match = _COMPLEX_TABLE_RE.match(line)
    if complex_match:
        index, resource = complex_match.group(1), complex_match.group(2)
        if resource:
            return [
                "> ⚠ 第 {0} 个表格是复杂表格（合并单元格、嵌套等），Markdown 无法表达，"
                "已原样导出为 [{1}]({2}/tables/{1})".format(index, resource, assets_name)
            ]
        return ["> ⚠ 第 {0} 个表格无法用 Markdown 表示，未导出".format(index)]
    return [_CHAPTER_IMAGE_RE.sub(
        lambda m: "{0}{1}/images/{2})".format(m.group(1), assets_name, m.group(2)), line
    )]


def _merge_chapters(content_dir: Path, chapters: List[dict], assets_name: str) -> List[str]:
    lines: List[str] = []
    for chapter in chapters:
        path = content_dir / chapter["file"]
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in text:
            lines.extend(_rewrite_line(line, assets_name))
        lines.append("")
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def docx_to_markdown(
    source: Path,
    target: Path,
    assets_dir: Optional[Path] = None,
) -> MarkdownExportOutcome:
    """把 ``source``(.docx) 转成单文件 ``target``(.md) + 同级 assets 目录。

    ``assets_dir`` 缺省为 ``<target.stem>_assets``，与 target 同目录。
    """
    from time import monotonic

    from doc_tool.domain.errors import MissingHeading1Error, WordConvertError

    source = Path(source)
    target = Path(target)
    started = monotonic()
    assets = Path(assets_dir) if assets_dir else target.parent / (target.stem + "_assets")
    assets_name = assets.name

    from doc_tool.adapters.importer import extract_content

    with tempfile.TemporaryDirectory(prefix="doc-tool-md-") as staging:
        stage = Path(staging)
        content_dir = stage / "proj" / "content" / "general"
        content_dir.mkdir(parents=True, exist_ok=True)
        images_dir = stage / "images"
        tables_dir = stage / "tables"
        images_dir.mkdir(parents=True, exist_ok=True)
        tables_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = extract_content(source, content_dir, images_dir, tables_dir, "general")
        except ValueError as exc:
            text = str(exc)
            if "Heading 1" in text:
                return MarkdownExportOutcome(
                    ok=False, reason="no_headings", error_code=MissingHeading1Error.code,
                    detail=MissingHeading1Error().user_message + " " + text,
                    elapsed_seconds=monotonic() - started,
                )
            return MarkdownExportOutcome(
                ok=False, reason="markdown_failed", error_code=WordConvertError.code,
                detail=text[:300], elapsed_seconds=monotonic() - started,
            )
        except Exception as exc:  # 压缩包损坏、XML 非法等：结构化报出，不抛裸异常
            return MarkdownExportOutcome(
                ok=False, reason="markdown_failed", error_code=WordConvertError.code,
                detail=repr(exc)[:300], elapsed_seconds=monotonic() - started,
            )

        lines = _merge_chapters(content_dir, result.chapters, assets_name)
        if not lines:
            return MarkdownExportOutcome(
                ok=False, reason="markdown_failed", error_code=WordConvertError.code,
                detail="提取结果为空：源文档没有可导出的正文章节。",
                elapsed_seconds=monotonic() - started,
            )
        copied_images = _mirror_dir(images_dir, assets / "images")
        copied_tables = _mirror_dir(tables_dir, assets / "tables")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")

    detail = "{0} 章、图片 {1} 张、表格 {2} 个".format(
        result.chapter_count, copied_images, result.simple_table_count + copied_tables
    )
    complex_count = copied_tables
    if complex_count:
        detail += "，其中 {0} 个复杂表格已另存为 assets 资源".format(complex_count)
    return MarkdownExportOutcome(
        ok=True,
        reason="ok",
        detail=detail,
        chapters=result.chapter_count,
        images=copied_images,
        tables=result.table_count,
        complex_tables=complex_count,
        elapsed_seconds=monotonic() - started,
    )


def _mirror_dir(src: Path, dst: Path) -> int:
    """把暂存目录里的资源拷到目标 assets 子目录，返回拷贝数量。"""
    if not src.is_dir():
        return 0
    files = [path for path in sorted(src.rglob("*")) if path.is_file()]
    if not files:
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy(str(path), str(dst / path.name))
    return len(files)
