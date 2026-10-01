# -*- coding: utf-8 -*-
"""\u6761\u76ee\u52a8\u4f5c\uff1a\u521b\u5efa\u4e0e\u590d\u5236\uff08V2.9 29-B / 2.2 \u670d\u52a1\u5c42\uff09\u3002

\u7f16\u8f91\u5668\u4e0e\u7ae0\u8282\u9762\u677f\u53ea\u9700\u8c03\u7528\u672c\u6a21\u5757\uff1a

- ``insert_item``\uff1a\u5728\u6307\u5b9a\u884c\u672b\u8ffd\u52a0**\u65b0\u6761\u76ee**\uff08\u65b0 ID\uff09\u5e76\u8fd4\u56de\u65b0\u6587\u672c\uff1b
- ``duplicate_item``\uff1a\u590d\u5236\u73b0\u6709\u6761\u76ee\u4e3a**\u65b0 ID**\uff0c\u6807\u8bb0\u53ea\u51fa\u73b0\u5728\u65b0\u884c\uff1b
- ``renumber_item``\uff1a\u53ea\u6539\u5199\u884c\u9996\u7f16\u53f7\uff0c**ID \u4e0d\u53d8**\uff1b
- \u5199\u5165\u901a\u8fc7 ``ContentWriter``\u4e8b\u52a1\uff08\u4e0e\u5176\u4ed6\u7f16\u8f91\u5171\u7528\uff09\uff0c\u5931\u8d25\u4e0d\u7559\u90e8\u5206\u5199\u5165\u3002
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from doc_tool.application.content.traceable_items import (
    DOC_ITEM_RE,
    ItemRef,
    append_marker,
    copy_ref,
    new_ref,
    parse_marker,
)


@dataclass
class ItemActionResult:
    """\u6761\u76ee\u52a8\u4f5c\u7ed3\u679c\u3002"""

    ok: bool
    text: str = ""
    item: Optional[ItemRef] = None
    line_no: int = 0
    message: str = ""
    written: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "text": self.text,
            "item": self.item.to_dict() if self.item else None,
            "lineNo": self.line_no,
            "message": self.message,
            "written": self.written,
        }


def insert_item(
    text: str,
    *,
    project_id: str,
    kind: str = "requirement",
    line_no: int = 0,
    alias: str = "",
    body: str = "",
    writer=None,
    rel_path: str = "",
) -> ItemActionResult:
    """\u5728 ``line_no`` \u884c\u672b\u63d2\u5165\u65b0\u6761\u76ee\uff1b``line_no=0`` \u65f6\u8ffd\u52a0\u5230\u6587\u672b\u3002

    ``body`` \u975e\u7a7a\u65f6\u5148\u65b0\u589e\u4e00\u884c\u6b63\u6587\u518d\u6302\u6807\u8bb0\uff0c\u4fdd\u8bc1\u6807\u8bb0\u4e0e\u6b63\u6587\u540c\u884c\u3002
    """
    content = str(text or "")
    try:
        item = new_ref(project_id, kind, alias)
    except ValueError as exc:
        return ItemActionResult(ok=False, message=str(exc))
    lines = content.splitlines()
    target_line = len(lines) if line_no <= 0 else line_no
    if target_line < 1:
        return ItemActionResult(ok=False, message="\u884c\u53f7\u5fc5\u987b \u2265 1\u3002")
    if body:
        if target_line > len(lines):
            lines.extend([""] * (target_line - len(lines)))
        lines.insert(target_line, str(body))
        target_line += 1
    if target_line > len(lines):
        lines.extend([""] * (target_line - len(lines)))
    updated_lines = lines[: target_line - 1] + [lines[target_line - 1].rstrip()] + lines[target_line:]
    updated = "\n".join(updated_lines)
    if content.endswith("\n"):
        updated += "\n"
    updated = append_marker(updated, item, line_no=target_line)
    result = ItemActionResult(ok=True, text=updated, item=item, line_no=target_line, message="\u5df2\u65b0\u589e\u6761\u76ee")
    if writer is not None and rel_path:
        writer.write(rel_path, updated)
        result.written = True
    return result


def duplicate_item(
    text: str,
    *,
    source_line: int,
    project_id: str = "",
    alias: str = "",
    writer=None,
    rel_path: str = "",
) -> ItemActionResult:
    """\u590d\u5236 ``source_line`` \u4e0a\u7684\u6761\u76ee\u4e3a**\u65b0 ID**\uff0c\u6807\u8bb0\u53ea\u51fa\u73b0\u5728\u65b0\u884c\u3002"""
    content = str(text or "")
    lines = content.splitlines()
    if source_line < 1 or source_line > len(lines):
        return ItemActionResult(ok=False, message="\u6e90\u884c\u53f7\u8d85\u51fa\u8303\u56f4\u3002")
    line = lines[source_line - 1]
    match = DOC_ITEM_RE.search(line)
    if match is None:
        return ItemActionResult(ok=False, message="\u8be5\u884c\u6ca1\u6709\u53ef\u590d\u5236\u7684\u6761\u76ee\u6807\u8bb0\u3002")
    ref, error = parse_marker(match.group(0))
    if ref is None:
        return ItemActionResult(ok=False, message=error or "\u6807\u8bb0\u65e0\u6548\u3002")
    duplicate = copy_ref(ref, project_id=project_id or ref.project_id)
    if alias:
        duplicate = ItemRef(
            project_id=duplicate.project_id, item_id=duplicate.item_id,
            kind=duplicate.kind, alias=alias,
        )
    # \u6e90\u884c\u53bb\u6389\u6807\u8bb0\u540e\u4f5c\u4e3a\u65b0\u884c\u6b63\u6587\uff0c\u907f\u514d\u4e24\u884c\u5171\u7528\u540c\u4e00 ID
    clean = DOC_ITEM_RE.sub("", line).rstrip()
    new_line = clean + " " + duplicate.render()
    updated_lines = lines[:source_line] + [new_line] + lines[source_line:]
    updated = "\n".join(updated_lines)
    if content.endswith("\n"):
        updated += "\n"
    result = ItemActionResult(
        ok=True, text=updated, item=duplicate, line_no=source_line + 1,
        message="\u5df2\u590d\u5236\u4e3a\u65b0\u6761\u76ee",
    )
    if writer is not None and rel_path:
        writer.write(rel_path, updated)
        result.written = True
    return result


def renumber_item(
    text: str,
    *,
    line_no: int,
    new_number: str,
    writer=None,
    rel_path: str = "",
) -> ItemActionResult:
    """\u53ea\u6539\u5199\u884c\u9996\u7f16\u53f7\uff1b**\u6761\u76ee ID \u4fdd\u6301\u4e0d\u53d8**\u3002"""
    content = str(text or "")
    lines = content.splitlines()
    if line_no < 1 or line_no > len(lines):
        return ItemActionResult(ok=False, message="\u884c\u53f7\u8d85\u51fa\u8303\u56f4\u3002")
    prefix = str(new_number or "").strip()
    if not prefix:
        return ItemActionResult(ok=False, message="\u65b0\u7f16\u53f7\u4e0d\u80fd\u4e3a\u7a7a\u3002")
    line = lines[line_no - 1]
    match = DOC_ITEM_RE.search(line)
    ref = None
    if match is not None:
        ref, _error = parse_marker(match.group(0))
    rewritten = re.sub(r"^(\s*)(?:\d+(?:\.\d+)*)?[.\u3001]?\s*", r"\g<1>" + prefix + " ", line, count=1)
    if rewritten == line and not line.startswith(prefix):
        rewritten = prefix + " " + line.lstrip()
    updated_lines = list(lines)
    updated_lines[line_no - 1] = rewritten
    updated = "\n".join(updated_lines)
    if content.endswith("\n"):
        updated += "\n"
    result = ItemActionResult(
        ok=True, text=updated, item=ref, line_no=line_no,
        message="\u5df2\u91cd\u7f16\u53f7\uff08ID \u4fdd\u6301\u4e0d\u53d8\uff09",
    )
    if writer is not None and rel_path:
        writer.write(rel_path, updated)
        result.written = True
    return result


def item_line_numbers(text: str, project_id: str = "") -> Sequence[Tuple[int, ItemRef]]:
    """\u5217\u51fa\u6587\u672c\u4e2d\u6240\u6709\u6761\u76ee\u884c\uff08\u4f9b\u9762\u677f\u5b9a\u4f4d\uff09\u3002"""
    found: list = []
    for index, line in enumerate(str(text or "").splitlines(), start=1):
        for match in DOC_ITEM_RE.finditer(line):
            ref, _error = parse_marker(match.group(0))
            if ref is None:
                continue
            if project_id and ref.project_id != project_id:
                continue
            found.append((index, ref))
    return found