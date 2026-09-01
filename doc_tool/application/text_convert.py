# -*- coding: utf-8 -*-
"""文本转换后端：TXT 读取（编码探测）、TXT → Word-HTML、DOCX → 纯文本。

纯 Python，不需要本机 Word；HTML 形态供 TXT → PDF 链路写临时文件后交 Word
导出。``docx_to_text`` 服务于 RTF → TXT 组合方向：RTF 先由 Word 转成 DOCX
（真机实测 Word 写出的 .docx 在本机明文落盘，Python 可直接读），再在这里
离线抽文本。

编码探测按内网实况取舍：优先 UTF-8（含 BOM），失败回退 GBK（gb18030 超集），
两者都解不出才报 E6007——绝不 ``errors="replace"`` 静默产出乱码。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from doc_tool.domain.errors import TextEncodingError, WordConvertError


@dataclass
class TextOutcome:
    """纯文本方向的结果对象，字段与批量层读取的鸭子类型协议对齐。"""

    ok: bool
    reason: str = "ok"
    detail: str = ""
    error_code: Optional[str] = None
    elapsed_seconds: float = 0.0
    images: int = 0
    complex_tables: int = 0


def read_text_file(path: Path) -> str:
    """读取文本文件：UTF-8（含 BOM）优先，失败回退 GBK，仍失败报 E6007。

    返回前统一换行（``\\r\\n``、``\\r`` → ``\\n``），与 Python 文本模式的默认
    行为一致——调用方（Markdown 渲染、CSV 解析、行计数）不必各自处理 ``\\r``。
    """
    raw = Path(path).read_bytes()
    encodings = ("utf-8-sig", "gb18030") if raw.startswith(b"\xef\xbb\xbf") else ("utf-8", "gb18030")
    for encoding in encodings:
        try:
            return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise TextEncodingError(details={"source": Path(path).name})


def plain_text_to_word_html(text: str, title: str = "") -> str:
    """纯文本 → 供 Word 导入的 HTML：空行分段、段内换行保留为 <br/>。"""
    import html as _html

    from doc_tool.application.markdown_word import WORD_STYLE_CSS

    blocks: List[str] = []
    paragraph: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped:
            paragraph.append(_html.escape(stripped, quote=False))
        elif paragraph:
            blocks.append("<p>{0}</p>".format("<br/>".join(paragraph)))
            del paragraph[:]
    if paragraph:
        blocks.append("<p>{0}</p>".format("<br/>".join(paragraph)))
    head = "<title>{0}</title>".format(_html.escape(title, quote=True)) if title else ""
    return (
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:w="urn:schemas-microsoft-com:office:word" '
        'xmlns="http://www.w3.org/TR/REC-html40">'
        '<head>{head}<meta charset="utf-8"/>'
        "<style>{css}</style></head><body>{body}</body></html>"
    ).format(head=head, css=WORD_STYLE_CSS, body="".join(blocks))


def docx_to_text(source: Path, target: Path) -> TextOutcome:
    """DOCX → 纯文本：按正文顺序抽段落与表格（表格行内用「 | 」连接）。"""
    from time import monotonic

    source = Path(source)
    target = Path(target)
    started = monotonic()
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        return TextOutcome(
            ok=False, reason="python_docx_missing", error_code=WordConvertError.code,
            detail="未安装 python-docx，无法抽取文本：{0}".format(exc),
            elapsed_seconds=monotonic() - started,
        )
    try:
        document = Document(str(source))
    except Exception as exc:
        return TextOutcome(
            ok=False, reason="docx_unreadable", error_code=WordConvertError.code,
            detail=repr(exc)[:300],
            elapsed_seconds=monotonic() - started,
        )

    lines: List[str] = []
    paragraphs = 0
    tables = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                lines.append(text)
                paragraphs += 1
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
            lines.append("")
            tables += 1
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return TextOutcome(
            ok=False, reason="empty_document", error_code=WordConvertError.code,
            detail="源文档没有可提取的正文内容。",
            elapsed_seconds=monotonic() - started,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return TextOutcome(
        ok=True, reason="ok",
        detail="段落 {0}、表格 {1} 个已导出为纯文本".format(paragraphs, tables),
        elapsed_seconds=monotonic() - started,
    )
