# -*- coding: utf-8 -*-
"""Safe, chapter-level reimport of an updated source DOCX."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.traceability import TraceabilityService
from doc_tool.application.content.writer import ContentWriter, atomic_write
from doc_tool.domain.errors import DocToolError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_REVISION_RECORD_NAMES = ("_revision_record.md", "_revision_record.markdown")


def _is_revision_record(rel_path: str) -> bool:
    name = Path(rel_path).name
    return name in _REVISION_RECORD_NAMES or name.startswith(".")


def _text_hash(path: Path) -> str:
    """章节内容哈希（sha1，与内容快照基线 ``content_baseline.json`` 同口径）。

    重导入基线（``reimport_base.json`` / 回退到快照基线）都用同一算法，避免
    新旧基线对比口径不一致导致冲突误判。
    """
    return hashlib.sha1(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class BlockUnit:
    """Markdown 块级切分单元（用于三方块级合并）。"""

    index: int
    kind: str
    raw_core: str
    trailing_sep: str
    norm_key: str
    start_line: int
    end_line: int
    was_last: bool = False

    @property
    def raw_text(self) -> str:
        return self.raw_core + self.trailing_sep


@dataclass(frozen=True)
class BlockConflict:
    """同一章节内同一语义块的双方冲突详情。"""

    rel_path: str
    block_kind: str
    base_lines: Tuple[int, int]
    local_lines: Tuple[int, int]
    incoming_lines: Tuple[int, int]
    base_text: str
    local_text: str
    incoming_text: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "relPath": self.rel_path,
            "blockKind": self.block_kind,
            "baseLines": list(self.base_lines),
            "localLines": list(self.local_lines),
            "incomingLines": list(self.incoming_lines),
            "baseText": self.base_text,
            "localText": self.local_text,
            "incomingText": self.incoming_text,
        }


@dataclass
class BlockMergeResult:
    """单章节三方块级合并结果。"""

    merged_text: str
    conflicts: List[BlockConflict] = field(default_factory=list)
    auto_merged: bool = False
    local_blocks_kept: int = 0
    incoming_blocks_applied: int = 0

    @property
    def clean(self) -> bool:
        return len(self.conflicts) == 0


@dataclass(frozen=True)
class ChapterChange:
    rel_path: str
    status: str
    conflict: bool = False
    use_new: bool = True
    auto_merged: bool = False
    merged_content: Optional[str] = None
    block_conflicts: Tuple[BlockConflict, ...] = ()
    renamed_from: Optional[str] = None


@dataclass
class ReimportResult:
    success: bool
    changes: List[ChapterChange] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    error_code: str = ""
    message: str = ""
    block_conflicts: Dict[str, List[BlockConflict]] = field(default_factory=dict)


def segment_markdown_blocks(text: str, rel_path: str = "") -> List[BlockUnit]:
    """将 Markdown 文本按共享块模型（``parse_blocks``）切分为无损覆盖全文的 ``BlockUnit`` 序列。"""
    if not text:
        return []
    from doc_tool.domain.blocks import KIND_EMPTY_PARAGRAPH, parse_blocks

    doc = parse_blocks(text, rel_path or "<memory>")
    semantic = [b for b in doc.blocks if b.kind != KIND_EMPTY_PARAGRAPH]
    lines = text.splitlines(keepends=True)
    if not semantic:
        raw_core = text.rstrip("\r\n")
        sep = text[len(raw_core):]
        return [
            BlockUnit(
                index=0,
                kind="paragraph",
                raw_core=raw_core,
                trailing_sep=sep,
                norm_key="paragraph:" + raw_core.strip(),
                start_line=1,
                end_line=max(1, len(lines)),
                was_last=True,
            )
        ]

    starts: List[int] = []
    for block in semantic:
        candidates = [
            block.location.start_line,
            getattr(block, "meta_line", None),
            getattr(block, "caption_line", None),
        ]
        valid = [int(c) for c in candidates if c is not None and int(c) >= 1]
        starts.append(min(valid) if valid else 1)

    units: List[BlockUnit] = []
    total_blocks = len(semantic)
    for idx, block in enumerate(semantic):
        slice_start = 0 if idx == 0 else max(0, starts[idx] - 1)
        slice_end = len(lines) if idx == total_blocks - 1 else max(slice_start, starts[idx + 1] - 1)
        raw_slice = "".join(lines[slice_start:slice_end])
        raw_core = raw_slice.rstrip("\r\n")
        trailing_sep = raw_slice[len(raw_core):]
        norm_key = "{0}:{1}".format(block.kind, raw_core.strip())
        units.append(
            BlockUnit(
                index=idx,
                kind=block.kind,
                raw_core=raw_core,
                trailing_sep=trailing_sep,
                norm_key=norm_key,
                start_line=slice_start + 1,
                end_line=max(slice_start + 1, block.location.end_line),
                was_last=(idx == total_blocks - 1),
            )
        )
    return units


def _assemble_block_units(units: Sequence[BlockUnit], trailing_newline: bool = True) -> str:
    """将合并后的 ``BlockUnit`` 序列无损组装回 Markdown 文本。"""
    if not units:
        return ""
    parts: List[str] = []
    total = len(units)
    for idx, unit in enumerate(units):
        is_last = idx == total - 1
        if not is_last:
            next_unit = units[idx + 1]
            sep = unit.trailing_sep
            if not sep:
                sep = "\n" if (unit.kind == "list_item" and next_unit.kind == "list_item") else "\n\n"
            elif unit.was_last and sep in ("\n", "\r\n") and not (
                unit.kind == "list_item" and next_unit.kind == "list_item"
            ):
                sep = "\n\n"
            parts.append(unit.raw_core + sep)
        else:
            sep = unit.trailing_sep if unit.trailing_sep else ("\n" if trailing_newline else "")
            if sep.startswith("\n\n"):
                sep = "\n"
            parts.append(unit.raw_core + sep)
    return "".join(parts)


def _parse_table_block_structure(
    raw_core: str,
) -> Optional[Tuple[List[str], List[str], str, List[List[str]], List[str]]]:
    """拆分表格块的 (前置行, 表头格列表, 分隔行原文, 数据行矩阵, 后置行)。"""
    from doc_tool.domain.markdown_structure import is_separator_row, split_table_row

    lines = raw_core.splitlines()
    if not lines:
        return None
    first_pipe = -1
    last_pipe = -1
    for idx, line in enumerate(lines):
        if line.strip().startswith("|"):
            if first_pipe < 0:
                first_pipe = idx
            last_pipe = idx
    if first_pipe < 0 or last_pipe < first_pipe:
        return None
    prefix_lines = lines[:first_pipe]
    pipe_lines = lines[first_pipe : last_pipe + 1]
    suffix_lines = lines[last_pipe + 1 :]
    if any(not ln.strip().startswith("|") for ln in pipe_lines):
        return None
    try:
        parsed_rows = [split_table_row(ln) for ln in pipe_lines]
    except Exception:
        return None
    if len(parsed_rows) < 2 or not is_separator_row(parsed_rows[1]):
        return None
    header = parsed_rows[0]
    sep_line = pipe_lines[1]
    data_rows = parsed_rows[2:]
    ncols = len(header)
    if ncols == 0:
        return None
    # Never make an unsafe/ragged table appear clean by discarding cells.
    if len(parsed_rows[1]) != ncols or any(len(row) > ncols for row in data_rows):
        return None
    norm_data = [row + [""] * (ncols - len(row)) for row in data_rows]
    return prefix_lines, header, sep_line, norm_data, suffix_lines


def _format_pipe_row(cells: Sequence[str]) -> str:
    escaped = [
        str(c).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
        for c in cells
    ]
    return "| " + " | ".join(escaped) + " |"


def _merge_row_cells_three_way(
    b_row: Sequence[str], l_row: Sequence[str], i_row: Sequence[str]
) -> Optional[List[str]]:
    """对同一行的单元格执行逐列三方合并；若同一单元格双方改成不同值则返回 None。"""
    if not (len(b_row) == len(l_row) == len(i_row)):
        return None
    merged: List[str] = []
    for b_cell, l_cell, i_cell in zip(b_row, l_row, i_row):
        if l_cell == i_cell:
            merged.append(l_cell)
        elif l_cell == b_cell:
            merged.append(i_cell)
        elif i_cell == b_cell:
            merged.append(l_cell)
        else:
            return None
    return merged


def merge_table_block_three_way(
    base_core: str, local_core: str, incoming_core: str
) -> Tuple[str, bool]:
    """Merge table metadata and cells without losing row identity or content.

    A unique, nonempty first column is the row identity. Ambiguous two-sided
    edits remain conflicts rather than applying an edit to the wrong row.
    """
    parsed = [_parse_table_block_structure(text) for text in (base_core, local_core, incoming_core)]
    if any(item is None for item in parsed):
        return "", False
    b_pre, b_hdr, b_sep, b_rows, b_suf = parsed[0]
    l_pre, l_hdr, l_sep, l_rows, l_suf = parsed[1]
    i_pre, i_hdr, i_sep, i_rows, i_suf = parsed[2]
    if not (len(b_hdr) == len(l_hdr) == len(i_hdr)):
        return "", False

    # Safe single-sided changes need no reformatting or row-identity heuristic.
    if local_core == incoming_core:
        return local_core, True
    if local_core == base_core:
        return incoming_core, True
    if incoming_core == base_core:
        return local_core, True

    metadata = []
    for base, local, incoming in ((b_pre, l_pre, i_pre), (b_sep, l_sep, i_sep), (b_suf, l_suf, i_suf)):
        if local == incoming or incoming == base:
            metadata.append(local)
        elif local == base:
            metadata.append(incoming)
        else:
            return "", False
    prefix, separator, suffix = metadata
    merged_header = _merge_row_cells_three_way(b_hdr, l_hdr, i_hdr)
    if merged_header is None:
        return "", False

    def unique_rows(rows):
        result = {}
        for row in rows:
            key = row[0].strip()
            if not key or key in result:
                return None
            result[key] = row
        return result

    b_map, l_map, i_map = (unique_rows(rows) for rows in (b_rows, l_rows, i_rows))
    if any(mapping is None for mapping in (b_map, l_map, i_map)):
        return "", False

    merged = {}
    for key in dict.fromkeys([*b_map, *l_map, *i_map]):
        base, local, incoming = b_map.get(key), l_map.get(key), i_map.get(key)
        if local == incoming or incoming == base:
            row = local
        elif local == base:
            row = incoming
        elif base is None or local is None or incoming is None:
            return "", False  # Conflicting addition, or deletion versus edit.
        else:
            row = _merge_row_cells_three_way(base, local, incoming)
            if row is None:
                return "", False
        if row is not None:
            merged[key] = row

    # Respect a unilateral reorder; contradictory reorders are not clean merges.
    common = set(b_map) & set(l_map) & set(i_map)
    b_order, l_order, i_order = ([key for key in mapping if key in common] for mapping in (b_map, l_map, i_map))
    if l_order != b_order and i_order != b_order and l_order != i_order:
        return "", False
    primary, secondary = (i_map, l_map) if l_order == b_order and i_order != b_order else (l_map, i_map)
    order = [key for key in primary if key in merged]
    secondary_order = [key for key in secondary if key in merged]
    for index, key in enumerate(secondary_order):
        if key not in order:
            following = next((anchor for anchor in secondary_order[index + 1:] if anchor in order), None)
            order.insert(order.index(following) if following is not None else len(order), key)

    out = [*prefix, _format_pipe_row(merged_header), separator]
    out.extend(_format_pipe_row(merged[key]) for key in order)
    return "\n".join([*out, *suffix]), True


def _expand_unit_opcodes(
    base_keys: Sequence[str], target_keys: Sequence[str]
) -> Tuple[Dict[int, Tuple[int, int]], Dict[int, Tuple[str, int, int, int]]]:
    """将 SequenceMatcher 的 equal 拆为单块粒度，返回 ``(inserts_at_b, step_at_b)``。"""
    import difflib

    matcher = difflib.SequenceMatcher(None, list(base_keys), list(target_keys), autojunk=False)
    inserts: Dict[int, Tuple[int, int]] = {}
    steps: Dict[int, Tuple[str, int, int, int]] = {}
    for tag, b1, b2, t1, t2 in matcher.get_opcodes():
        if tag == "insert":
            inserts[b1] = (t1, t2)
        elif tag == "equal":
            for offset in range(b2 - b1):
                steps[b1 + offset] = ("equal", b1 + offset + 1, t1 + offset, t1 + offset + 1)
        else:
            steps[b1] = (tag, b2, t1, t2)
    return inserts, steps


def merge_markdown_blocks_three_way(
    base_text: str,
    local_text: str,
    incoming_text: str,
    *,
    rel_path: str = "",
) -> BlockMergeResult:
    """对同一章节的基线（base）、本地修改（local）与外部重导入（incoming）执行块级三方合并。

    - 若本地修改第 M 块、外部修改第 N 块（M != N），自动合入双方修改，``clean=True``；
    - 若双方修改同一语义块且内容不同，保留本地块并记录 ``BlockConflict``，``clean=False``。
    """
    base_units = segment_markdown_blocks(base_text, rel_path)
    local_units = segment_markdown_blocks(local_text, rel_path)
    incoming_units = segment_markdown_blocks(incoming_text, rel_path)

    base_keys = [u.norm_key for u in base_units]
    local_keys = [u.norm_key for u in local_units]
    incoming_keys = [u.norm_key for u in incoming_units]

    l_inserts, l_steps = _expand_unit_opcodes(base_keys, local_keys)
    i_inserts, i_steps = _expand_unit_opcodes(base_keys, incoming_keys)

    merged_units: List[BlockUnit] = []
    conflicts: List[BlockConflict] = []
    local_kept = 0
    incoming_applied = 0
    n_base = len(base_units)
    b = 0

    def _lines_span(slice_units: Sequence[BlockUnit], fallback_line: int) -> Tuple[int, int]:
        if not slice_units:
            return (fallback_line, fallback_line)
        return (slice_units[0].start_line, slice_units[-1].end_line)

    while b <= n_base:
        # 1. 处理在边界 b 处的纯插入
        l_ins = l_inserts.get(b)
        i_ins = i_inserts.get(b)
        if l_ins is not None and i_ins is None:
            merged_units.extend(local_units[l_ins[0]:l_ins[1]])
            local_kept += l_ins[1] - l_ins[0]
        elif i_ins is not None and l_ins is None:
            merged_units.extend(incoming_units[i_ins[0]:i_ins[1]])
            incoming_applied += i_ins[1] - i_ins[0]
        elif l_ins is not None and i_ins is not None:
            l_slice = local_units[l_ins[0]:l_ins[1]]
            i_slice = incoming_units[i_ins[0]:i_ins[1]]
            if [u.norm_key for u in l_slice] == [u.norm_key for u in i_slice]:
                merged_units.extend(l_slice)
                local_kept += len(l_slice)
            else:
                merged_units.extend(l_slice)
                fb_line = base_units[b].start_line if b < n_base else (base_units[-1].end_line if base_units else 1)
                conflicts.append(
                    BlockConflict(
                        rel_path=rel_path,
                        block_kind=l_slice[0].kind if l_slice else (i_slice[0].kind if i_slice else "paragraph"),
                        base_lines=(fb_line, fb_line),
                        local_lines=_lines_span(l_slice, fb_line),
                        incoming_lines=_lines_span(i_slice, fb_line),
                        base_text="",
                        local_text=_assemble_block_units(l_slice, trailing_newline=False),
                        incoming_text=_assemble_block_units(i_slice, trailing_newline=False),
                    )
                )

        if b == n_base:
            break

        l_tag, lb2, l1, l2 = l_steps[b]
        i_tag, ib2, i1, i2 = i_steps[b]

        # 2. 双方在该块均未修改
        if l_tag == "equal" and i_tag == "equal":
            merged_units.extend(local_units[l1:l2])
            b += 1
            continue

        # 3. 仅本地修改了 [b, lb2)，且外部在 [b, lb2) 全部为 equal 且内部无插入
        if l_tag != "equal":
            incoming_untouched = all(
                (k in i_steps and i_steps[k][0] == "equal") for k in range(b, lb2)
            ) and all(k not in i_inserts for k in range(b + 1, lb2))
            if incoming_untouched:
                merged_units.extend(local_units[l1:l2])
                local_kept += max(1, l2 - l1)
                b = lb2
                continue

        # 4. 仅外部修改了 [b, ib2)，且本地在 [b, ib2) 全部为 equal 且内部无插入
        if i_tag != "equal":
            local_untouched = all(
                (k in l_steps and l_steps[k][0] == "equal") for k in range(b, ib2)
            ) and all(k not in l_inserts for k in range(b + 1, ib2))
            if local_untouched:
                merged_units.extend(incoming_units[i1:i2])
                incoming_applied += max(1, i2 - i1)
                b = ib2
                continue

        # 5. 双方修改区间重叠：向右扩展直到两侧在同一 base 边界对齐
        end_b = max(lb2, ib2)
        cur_lb = lb2
        cur_ib = ib2
        cur_l2 = l2
        cur_i2 = i2
        while cur_lb < end_b or cur_ib < end_b:
            while cur_lb < end_b:
                _t, next_lb, _s, next_l2 = l_steps[cur_lb]
                cur_lb = next_lb
                cur_l2 = next_l2
                if cur_lb > end_b:
                    end_b = cur_lb
            while cur_ib < end_b:
                _t, next_ib, _s, next_i2 = i_steps[cur_ib]
                cur_ib = next_ib
                cur_i2 = next_i2
                if cur_ib > end_b:
                    end_b = cur_ib

        b_slice = base_units[b:end_b]
        l_slice = local_units[l1:cur_l2]
        i_slice = incoming_units[i1:cur_i2]
        if [u.norm_key for u in l_slice] == [u.norm_key for u in i_slice]:
            merged_units.extend(l_slice)
            local_kept += len(l_slice)
        elif (
            len(b_slice) == 1
            and len(l_slice) == 1
            and len(i_slice) == 1
            and b_slice[0].kind == "table"
            and l_slice[0].kind == "table"
            and i_slice[0].kind == "table"
        ):
            tbl_merged, tbl_ok = merge_table_block_three_way(
                b_slice[0].raw_core, l_slice[0].raw_core, i_slice[0].raw_core
            )
            if tbl_ok:
                lu = l_slice[0]
                merged_units.append(
                    BlockUnit(
                        index=lu.index,
                        kind="table",
                        raw_core=tbl_merged,
                        trailing_sep=lu.trailing_sep,
                        norm_key="table:" + tbl_merged.strip(),
                        start_line=lu.start_line,
                        end_line=lu.end_line,
                        was_last=lu.was_last,
                    )
                )
                local_kept += 1
                incoming_applied += 1
            else:
                merged_units.extend(l_slice)
                fb_line = b_slice[0].start_line
                conflicts.append(
                    BlockConflict(
                        rel_path=rel_path,
                        block_kind="table",
                        base_lines=_lines_span(b_slice, fb_line),
                        local_lines=_lines_span(l_slice, fb_line),
                        incoming_lines=_lines_span(i_slice, fb_line),
                        base_text=_assemble_block_units(b_slice, trailing_newline=False),
                        local_text=_assemble_block_units(l_slice, trailing_newline=False),
                        incoming_text=_assemble_block_units(i_slice, trailing_newline=False),
                    )
                )
        else:
            merged_units.extend(l_slice)
            fb_line = b_slice[0].start_line if b_slice else 1
            conflicts.append(
                BlockConflict(
                    rel_path=rel_path,
                    block_kind=(
                        b_slice[0].kind
                        if b_slice
                        else (l_slice[0].kind if l_slice else "paragraph")
                    ),
                    base_lines=_lines_span(b_slice, fb_line),
                    local_lines=_lines_span(l_slice, fb_line),
                    incoming_lines=_lines_span(i_slice, fb_line),
                    base_text=_assemble_block_units(b_slice, trailing_newline=False),
                    local_text=_assemble_block_units(l_slice, trailing_newline=False),
                    incoming_text=_assemble_block_units(i_slice, trailing_newline=False),
                )
            )
        b = end_b

    trailing_nl = local_text.endswith(("\n", "\r")) or incoming_text.endswith(("\n", "\r"))
    merged_text = _assemble_block_units(merged_units, trailing_newline=trailing_nl)
    return BlockMergeResult(
        merged_text=merged_text,
        conflicts=conflicts,
        auto_merged=(len(conflicts) == 0 and (local_kept > 0 or incoming_applied > 0)),
        local_blocks_kept=local_kept,
        incoming_blocks_applied=incoming_applied,
    )


def _discover_base_texts(
    current_root: Path, base_hashes: Dict[str, str]
) -> Dict[str, str]:
    """从项目 ``.state/reimport_base.json`` 或 ``.state/baseline/`` 自动加载与 ``base_hashes`` 匹配的基线文本。"""
    if not base_hashes:
        return {}
    texts: Dict[str, str] = {}
    root = Path(current_root).resolve()
    # content/<doc_type> -> 项目根目录通常在 parent.parent 或 parent
    candidate_states = [
        root.parent.parent / ".state",
        root.parent / ".state",
    ]
    for state_dir in candidate_states:
        if not state_dir.is_dir():
            continue
        reimport_base_file = state_dir / "reimport_base.json"
        if reimport_base_file.is_file():
            try:
                payload = json.loads(reimport_base_file.read_text(encoding="utf-8"))
                raw_contents = payload.get("contents")
                if isinstance(raw_contents, dict):
                    for rel, content in raw_contents.items():
                        if rel in base_hashes and isinstance(content, str):
                            expected = base_hashes[rel]
                            lf_text = content.replace("\r\n", "\n")
                            crlf_text = lf_text.replace("\n", "\r\n")
                            if (
                                hashlib.sha1(content.encode("utf-8")).hexdigest() == expected
                                or hashlib.sha1(lf_text.encode("utf-8")).hexdigest() == expected
                                or hashlib.sha1(crlf_text.encode("utf-8")).hexdigest() == expected
                            ):
                                texts[rel] = content
            except Exception:
                pass
        baseline_dir = state_dir / "baseline"
        if baseline_dir.is_dir():
            for rel, expected_sha1 in base_hashes.items():
                if rel in texts:
                    continue
                candidate = baseline_dir / rel
                if candidate.is_file():
                    try:
                        raw = candidate.read_bytes()
                        if hashlib.sha1(raw).hexdigest() == expected_sha1:
                            texts[rel] = raw.decode("utf-8")
                    except Exception:
                        continue
    return texts


def compare_chapters(
    current_root: Path,
    incoming_root: Path,
    base_hashes: Optional[Dict[str, str]] = None,
    base_texts: Optional[Dict[str, str]] = None,
    *,
    enable_block_merge: bool = True,
) -> List[ChapterChange]:
    """章节级对比 + 块级三方合并（Block-Level 3-Way Merge）：

    冲突语义（「不覆盖已有 Markdown 修改」）：
    - 基线缺失（首次重导入无基线）→ 保守判冲突，默认保留本地。
    - 仅源变更、本地未动 → 自动合入。
    - 源未变、本地已改 → 保留本地（不算冲突，也不写回旧源内容）。
    - 双方均变更且不同：
      - 若存在基线全文且启用块级合并（``enable_block_merge=True``）：
        执行 ``merge_markdown_blocks_three_way``；若双方改动位于同一章的不同块（非重叠），
        自动合入双方块修改（``conflict=False, use_new=True, auto_merged=True``）；
        若同一块发生重叠冲突，标记 ``conflict=True, use_new=False`` 并附带 ``block_conflicts``。
      - 若无基线全文：整章判冲突，默认保留本地。
    - 本地删除（基线有、当前缺、新源有）→ 冲突，默认保留删除。
    """
    base_hashes = base_hashes or {}
    resolved_base_texts = (
        dict(base_texts)
        if base_texts is not None
        else (_discover_base_texts(current_root, base_hashes) if enable_block_merge else {})
    )
    current = {
        path.relative_to(current_root).as_posix(): _text_hash(path)
        for path in Path(current_root).rglob("*.md")
        if path.is_file() and not _is_revision_record(path.name)
    }
    incoming = {
        path.relative_to(incoming_root).as_posix(): _text_hash(path)
        for path in Path(incoming_root).rglob("*.md")
        if path.is_file() and not _is_revision_record(path.name)
    }
    # 智能对齐：识别跨文件章节改名（Rename）与编号顺延移位（Shift）
    only_current = sorted(set(current) - set(incoming))
    only_incoming = sorted(set(incoming) - set(current))
    renamed_old_to_new: Dict[str, str] = {}
    renamed_new_to_old: Dict[str, str] = {}
    if enable_block_merge and only_current and only_incoming:
        import difflib

        def _strip_chapter_num_from_rel(rel_p: str) -> Tuple[str, str]:
            p = Path(rel_p)
            stem = p.stem
            if stem == "_index" and p.parent.name:
                stem = p.parent.name
            core = re.sub(
                r"^(?:第[0-9一二三四五六七八九十百]+[章节篇部]\s*|\d+(?:\.\d+)*[\s.、_-]*)",
                "",
                stem,
            ).strip()
            parent_core = re.sub(
                r"^(?:第[0-9一二三四五六七八九十百]+[章节篇部]\s*|\d+(?:\.\d+)*[\s.、_-]*)",
                "",
                p.parent.name,
            ).strip()
            return parent_core, core or stem

        candidate_pairs: List[Tuple[float, str, str]] = []
        for old_rel in only_current:
            old_parent, old_core = _strip_chapter_num_from_rel(old_rel)
            try:
                old_ref_txt = resolved_base_texts.get(old_rel) or (Path(current_root) / old_rel).read_text(encoding="utf-8")
            except Exception:
                continue
            for new_rel in only_incoming:
                new_parent, new_core = _strip_chapter_num_from_rel(new_rel)
                try:
                    new_inc_txt = (Path(incoming_root) / new_rel).read_text(encoding="utf-8")
                except Exception:
                    continue
                sim = difflib.SequenceMatcher(
                    None, old_ref_txt.strip(), new_inc_txt.strip(), autojunk=False
                ).ratio()
                same_core_title = bool(old_core and old_core == new_core)
                same_parent = (old_parent == new_parent)
                if same_core_title and sim >= 0.35:
                    score = sim + 0.5 + (0.1 if same_parent else 0.0)
                    candidate_pairs.append((score, old_rel, new_rel))
                elif sim >= 0.65:
                    score = sim + (0.15 if same_parent else 0.0)
                    candidate_pairs.append((score, old_rel, new_rel))

        candidate_pairs.sort(key=lambda item: item[0], reverse=True)
        for _score, old_rel, new_rel in candidate_pairs:
            if old_rel in renamed_old_to_new or new_rel in renamed_new_to_old:
                continue
            renamed_old_to_new[old_rel] = new_rel
            renamed_new_to_old[new_rel] = old_rel

    changes: List[ChapterChange] = []
    for rel_path in sorted(set(current) | set(incoming)):
        if rel_path in renamed_old_to_new:
            # 已被识别为改名/移位源路径，由目标新路径统一承接合并与旧文件清理
            continue
        if rel_path in renamed_new_to_old:
            old_rel = renamed_new_to_old[rel_path]
            base = base_hashes.get(old_rel)
            old_sha = current[old_rel]
            new_sha = incoming[rel_path]
            local_text = (Path(current_root) / old_rel).read_text(encoding="utf-8")
            incoming_text = (Path(incoming_root) / rel_path).read_text(encoding="utf-8")
            if old_sha == new_sha:
                changes.append(
                    ChapterChange(
                        rel_path,
                        "modified",
                        conflict=False,
                        use_new=True,
                        auto_merged=True,
                        merged_content=incoming_text,
                        renamed_from=old_rel,
                    )
                )
            elif base is not None and old_sha == base:
                changes.append(
                    ChapterChange(
                        rel_path,
                        "modified",
                        conflict=False,
                        use_new=True,
                        auto_merged=True,
                        merged_content=incoming_text,
                        renamed_from=old_rel,
                    )
                )
            elif base is not None and new_sha == base:
                changes.append(
                    ChapterChange(
                        rel_path,
                        "modified",
                        conflict=False,
                        use_new=True,
                        auto_merged=True,
                        merged_content=local_text,
                        renamed_from=old_rel,
                    )
                )
            else:
                base_text = resolved_base_texts.get(old_rel)
                if base_text is not None:
                    b_merge = merge_markdown_blocks_three_way(
                        base_text, local_text, incoming_text, rel_path=rel_path
                    )
                    if b_merge.clean:
                        changes.append(
                            ChapterChange(
                                rel_path,
                                "modified",
                                conflict=False,
                                use_new=True,
                                auto_merged=True,
                                merged_content=b_merge.merged_text,
                                block_conflicts=(),
                                renamed_from=old_rel,
                            )
                        )
                    else:
                        changes.append(
                            ChapterChange(
                                rel_path,
                                "modified",
                                conflict=True,
                                use_new=False,
                                auto_merged=False,
                                merged_content=b_merge.merged_text,
                                block_conflicts=tuple(b_merge.conflicts),
                                renamed_from=old_rel,
                            )
                        )
                else:
                    changes.append(
                        ChapterChange(
                            rel_path,
                            "modified",
                            conflict=True,
                            use_new=False,
                            renamed_from=old_rel,
                        )
                    )
            continue
        if rel_path not in current:
            # 基线存在而当前缺失 = 用户本地删除：冲突，默认保留删除。
            in_base = rel_path in base_hashes
            changes.append(ChapterChange(rel_path, "added", in_base, not in_base))
        elif rel_path not in incoming:
            local_modified = rel_path not in base_hashes or current[rel_path] != base_hashes[rel_path]
            changes.append(ChapterChange(rel_path, "deleted", local_modified, not local_modified))
        elif current[rel_path] == incoming[rel_path]:
            changes.append(ChapterChange(rel_path, "unchanged"))
        else:
            base = base_hashes.get(rel_path)
            if base is None:
                changes.append(ChapterChange(rel_path, "modified", True, False))
            elif incoming[rel_path] == base:
                # 源未变、本地已改：保留本地，避免用旧源内容覆盖本地编辑。
                changes.append(ChapterChange(rel_path, "modified", False, False))
            elif current[rel_path] == base:
                # 仅源变更、本地未动：自动合入。
                changes.append(ChapterChange(rel_path, "modified", False, True))
            else:
                base_text = resolved_base_texts.get(rel_path)
                if enable_block_merge and base_text is not None:
                    try:
                        local_text = (Path(current_root) / rel_path).read_text(encoding="utf-8")
                        incoming_text = (Path(incoming_root) / rel_path).read_text(encoding="utf-8")
                        b_merge = merge_markdown_blocks_three_way(
                            base_text, local_text, incoming_text, rel_path=rel_path
                        )
                        if b_merge.clean:
                            changes.append(
                                ChapterChange(
                                    rel_path,
                                    "modified",
                                    conflict=False,
                                    use_new=True,
                                    auto_merged=True,
                                    merged_content=b_merge.merged_text,
                                    block_conflicts=(),
                                )
                            )
                        else:
                            changes.append(
                                ChapterChange(
                                    rel_path,
                                    "modified",
                                    conflict=True,
                                    use_new=False,
                                    auto_merged=False,
                                    merged_content=b_merge.merged_text,
                                    block_conflicts=tuple(b_merge.conflicts),
                                )
                            )
                        continue
                    except Exception:
                        pass
                changes.append(ChapterChange(rel_path, "modified", True, False))
    return changes


class ReimportService:
    def __init__(self, manifest: ProjectManifest, paths: ProjectPaths) -> None:
        self.manifest = manifest
        self.paths = paths
        self.transaction_file = paths.state_dir / "reimport_last.json"

    def source_changed(self) -> bool:
        source = self.paths.resolve(self.manifest.relative_source_docx())
        return not source.is_file() or file_sha256(source) != self.manifest.sourceSha256

    def source_missing(self) -> bool:
        """源文档是否存在（区别于「存在但指纹变化」）。"""
        source = self.paths.resolve(self.manifest.relative_source_docx())
        return not source.is_file()

    def _base_hashes(self) -> Dict[str, str]:
        """重导入基线哈希；缺文件时回退到内容快照基线（sha1 同口径）。

        首次导入已播种 ``reimport_base.json``；旧项目（升级前导入）没有该文件
        时回退 ``content_baseline.json``，保证首次重导入的自动合入仍可用。
        """
        try:
            payload = json.loads((self.paths.state_dir / "reimport_base.json").read_text(encoding="utf-8"))
            files = {rel: h for rel, h in dict(payload.get("files", {})).items() if not _is_revision_record(rel)}
            if files:
                return files
        except (OSError, ValueError, TypeError):
            pass
        try:
            from doc_tool.application.content.snapshot import ContentSnapshot

            snapshot = ContentSnapshot(self.paths.state_dir)
            snapshot.load()
            return {
                rel_path: entry.sha1
                for rel_path, entry in snapshot.entries.items()
            }
        except Exception:
            return {}

    def _writer(self) -> ContentWriter:
        return ContentWriter(
            self.paths.resolve(self.manifest.relative_content_root()),
            self.paths.state_dir,
            self.paths.resolve(self.manifest.relative_asset_root()),
        )

    def _merge_incoming_assets(
        self, staging_images: Path, staging_tables: Path, *, copy_assets: bool = True
    ) -> Dict[str, str]:
        """Plan collision-free resource names; previews never write project assets.

        Reuse identical bytes even after a previous rename so repeated imports
        have stable references. Reserve all names before copying any resource.
        """
        from doc_tool.application.content.asset_manager import next_image_name

        mapping: Dict[str, str] = {}
        copies: List[Tuple[Path, Path]] = []
        images_root = self.paths.images_dir(self.manifest.documentType)
        tables_root = self.paths.tables_dir(self.manifest.documentType)
        for staging, target, prefix in (
            (Path(staging_images), images_root, "img"),
            (Path(staging_tables), tables_root, "tbl"),
        ):
            if not staging.is_dir():
                continue
            existing = sorted(path for path in target.iterdir() if path.is_file()) if target.is_dir() else []
            existing_hashes = {path.name: file_sha256(path) for path in existing}
            names_by_hash = {}
            for name, digest in existing_hashes.items():
                names_by_hash.setdefault(digest, name)
            if prefix == "img":
                # next_image_name expects the parent assets directory, not
                # assets/<documentType> (which would scan the wrong directory).
                seed = next_image_name(images_root.parent.parent, self.manifest.documentType)
            else:
                seed = self._next_table_name()
            sequence = int(Path(seed).stem.split("_")[1])
            for source in sorted(staging.iterdir()):
                if not source.is_file():
                    continue
                digest = file_sha256(source)
                if existing_hashes.get(source.name) == digest:
                    name = source.name
                else:
                    name = names_by_hash.get(digest)
                if name is None:
                    extension = source.suffix or (".png" if prefix == "img" else ".xml")
                    name = "{0}_{1:04d}{2}".format(prefix, sequence, extension)
                    sequence += 1
                    names_by_hash[digest] = name
                    copies.append((source, target / name))
                mapping[source.name] = "images/" + name if prefix == "img" else name
        if copy_assets:
            for source, target in copies:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Fail closed if another writer claimed the allocated name.
                with source.open("rb") as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
        return mapping

    def _next_table_name(self) -> str:
        """分配下一个 ``tbl_NNNN.xml``（避开既有复杂表格文件）。"""
        maximum = 0
        try:
            for child in self.paths.tables_dir(self.manifest.documentType).glob("tbl_*.xml"):
                match = re.match(r"^tbl_(\d+)\.xml$", child.name)
                if match is not None:
                    maximum = max(maximum, int(match.group(1)))
        except OSError:
            pass
        return "tbl_{0:04d}.xml".format(maximum + 1)

    @staticmethod
    def _rewrite_incoming_refs(text: str, mapping: Dict[str, str]) -> str:
        """Rewrite source-side references only, preserving fenced code literally."""
        if not mapping:
            return text
        from doc_tool.domain.blocks import KIND_CODE, parse_blocks

        protected = {
            number
            for block in parse_blocks(text).blocks if block.kind == KIND_CODE
            for number in range(block.location.start_line, block.location.end_line + 1)
        }
        lines = text.splitlines(keepends=True)
        for number, line in enumerate(lines, 1):
            if number in protected:
                continue
            line = re.sub(
                r"!\[([^\]]*)\]\(images/([^\s)]+)((?:\s[^)]*)?)\)",
                lambda match: "![{0}]({1}{2})".format(
                    match.group(1), mapping.get(match.group(2), "images/" + match.group(2)), match.group(3) or ""
                ),
                line,
            )
            lines[number - 1] = re.sub(
                r"<!--\s*TABLE:(\d+):([^\s>]+)\s*-->",
                lambda match: "<!-- TABLE:{0}:{1} -->".format(match.group(1), mapping.get(match.group(2), match.group(2))),
                line,
            )
        return "".join(lines)

    def _rewrite_incoming_contents(self, incoming: Path, mapping: Dict[str, str]) -> None:
        """Normalize isolated incoming files before comparison, never merged local text."""
        for path in incoming.rglob("*.md"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            rewritten = self._rewrite_incoming_refs(text, mapping)
            if rewritten != text:
                path.write_text(rewritten, encoding="utf-8")

    def _base_texts(self) -> Dict[str, str]:
        """读取重导入基线全文（优先 ``reimport_base.json`` 的 ``contents``，回退 ``.state/baseline/``）。"""
        return _discover_base_texts(
            self.paths.resolve(self.manifest.relative_content_root()),
            self._base_hashes(),
        )

    def _rebuild_after_merge(self, writer: ContentWriter) -> None:
        """Rebuild local indexes without changing the source-side merge ancestor."""
        index = ContentIndexService(writer.content_root).build()
        ReferenceScanner(index, writer.assets_root).scan_all()
        TraceabilityService(index, self.paths.state_dir).rebuild()

    def _save_reimport_base(self, source_root: Path) -> None:
        """The next three-way ancestor is the incoming source, not merged local edits."""
        hashes: Dict[str, str] = {}
        contents: Dict[str, str] = {}
        for path in source_root.rglob("*.md"):
            if not path.is_file() or _is_revision_record(path.name):
                continue
            rel = path.relative_to(source_root).as_posix()
            hashes[rel] = _text_hash(path)
            try:
                contents[rel] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                pass
        atomic_write(
            self.paths.state_dir / "reimport_base.json",
            json.dumps({"files": hashes, "contents": contents}, ensure_ascii=False, indent=2),
        )

    def _rollback_reimport(self, writer: ContentWriter, touched: List[Tuple[str, str]]) -> None:
        """失败回滚：内容、源文件、清单指纹、基线哈希一起恢复。

        回滚为尽力而为：任何一步失败都不能让回滚逻辑自身抛异常，否则会破坏
        ``reimport`` 「失败也返回结构化 ReimportResult」的契约。

        仅当本次重导入确实已把新源替换到源路径（``_source_replaced``）才从备份
        恢复源文件；替换前的失败意味着源文件仍是用户当前版本，绝不能拿上一次
        重导入留存的过期备份覆盖用户对源文档的新编辑，也不能把指纹重置为旧值
        （否则 ``source_changed`` 会因指纹与文件不符而恒为真）。
        """
        try:
            writer.rollback_keys(touched)
        except Exception:
            pass
        if getattr(self, "_source_replaced", False):
            try:
                backup = self.paths.state_dir / "reimport_last_source.docx"
                source = self.paths.resolve(self.manifest.relative_source_docx())
                if backup.is_file():
                    shutil.copy2(backup, source)
                    self.manifest.sourceSha256 = getattr(
                        self, "_rollback_sha", self.manifest.sourceSha256
                    )
                elif not getattr(self, "_source_existed", True):
                    # 源原本不存在且无备份（从未复制成功）：删除新源，
                    # 恢复「无源文档」原状，避免磁盘新 DOCX + 清单旧指纹
                    # 的永久不一致（source_changed 恒为真）。
                    source.unlink(missing_ok=True)
                    self.manifest.sourceSha256 = getattr(
                        self, "_rollback_sha", self.manifest.sourceSha256
                    )
                else:
                    # 源原本存在但备份缺失（复制失败）：无法恢复旧内容，
                    # 至少把指纹更新为新文件真实哈希；保存失败时保持现状。
                    if source.is_file():
                        self.manifest.sourceSha256 = file_sha256(source)
                self.manifest.save(self.paths.root, backup=True)
            except Exception:
                pass
        if getattr(self, "_baseline_replaced", False):
            try:
                baseline = self.paths.state_dir / "reimport_base.json"
                if self._base_existed:
                    shutil.copy2(self.paths.state_dir / "reimport_last_base.json", baseline)
                else:
                    baseline.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            self._rebuild_after_merge(writer)
        except Exception:
            pass

    def _heading_style_map(self, new_source: Path) -> Optional[Dict[str, int]]:
        """新源文档的 styleId -> 级别识别映射（清单映射 ∪ 新源自身名称启发式）。

        清单里的 styleId 属于旧源/模板；换源后 Word 可能重编号，仅按清单识别
        会让标题树整章漏掉。并集保证两套 styleId 都能被认出来。仅作识别用途，
        不改变清单里「构建时写哪个 styleId」的决策。
        """
        from doc_tool.domain.ooxml import (
            OOXMLSecurityError,
            parse_heading_styles,
            read_docx_package,
        )

        merged: Dict[str, int] = {}
        try:
            with read_docx_package(new_source) as package:
                merged.update(parse_heading_styles(package.read("word/styles.xml")))
        except (OSError, KeyError, OOXMLSecurityError):
            pass
        for level, style_id in self.manifest.headingStyles.items():
            merged.setdefault(str(style_id), int(level))
        return merged or None

    def _extract_incoming(
        self, new_source: Path, incoming: Path, staging: Path,
        extractor: Optional[Callable[[Path, Path], None]] = None,
    ) -> None:
        """把新源抽取到隔离目录（不触碰正式正文）。

        ``reimport`` 与 :meth:`preview` 共用同一段抽取逻辑：两边看到的新增/修改/
        删除必然一致，不会出现“预览说改了 A、应用却改了 B”。
        """
        if extractor is not None:
            extractor(new_source, incoming)
            return
        from doc_tool.adapters.importer import extract_content, split_into_tree
        from doc_tool.adapters.preflight import preflight

        heading_map = self._heading_style_map(new_source)
        preflight(new_source, heading_style_map=heading_map)
        extract_content(
            new_source,
            incoming,
            staging / "images",
            staging / "tables",
            self.manifest.documentType,
            heading_style_map=heading_map,
        )
        split_into_tree(incoming)

    def preview(
        self,
        new_source: Path,
        *,
        dirty_paths: Optional[Sequence[str]] = None,
        local_contents: Optional[Dict[str, str]] = None,
        selected: Optional[Sequence[str]] = None,
        extractor: Optional[Callable[[Path, Path], None]] = None,
    ):
        """后台生成隔离差异会话（**不写正式正文，也不改源记录**）。

        复用 :mod:`reimport_preview` 的 ``open_preview``：差异条目带新增/修改/删除、
        冲突/脏项标记与逐项 diff；脏章（未保存编辑）默认不参与应用。
        """
        import shutil
        import tempfile

        from doc_tool.application.content.reimport_preview import open_preview

        new_source = Path(new_source)
        # 上一轮预览的隔离副本不再需要：新会话会重建，先释放避免 .state 无限增长。
        self._release_preview_staging()
        staging = Path(tempfile.mkdtemp(
            prefix="doc-tool-reimport-preview-", dir=str(self.paths.state_dir)
        ))
        incoming = staging / "content"
        incoming.mkdir(parents=True)
        try:
            try:
                self._extract_incoming(new_source, incoming, staging, extractor)
            except Exception as exc:  # noqa: BLE001 - 预览失败不改变项目状态
                shutil.rmtree(staging, ignore_errors=True)
                return None, "新源文档无法解析：{0}".format(exc)
            mapping = self._merge_incoming_assets(staging / "images", staging / "tables", copy_assets=False)
            self._rewrite_incoming_contents(incoming, mapping)
            changes = compare_chapters(
                self._writer().content_root,
                incoming,
                self._base_hashes(),
                self._base_texts(),
            )
            incoming_contents = self._read_incoming_contents(
                incoming, changes, selected
            )
            self._preview_root = incoming
            self._preview_staging = staging
            session = open_preview(
                changes,
                service=self,
                source_path=new_source,
                baseline_available=bool(self._base_hashes()),
                selected=selected,
                dirty_paths=dirty_paths,
                local_contents=local_contents,
                incoming_contents=incoming_contents,
            )
            return session, ""
        except Exception as exc:  # noqa: BLE001 - 预览失败保留原项目状态
            shutil.rmtree(staging, ignore_errors=True)
            return None, "生成差异预览失败：{0}".format(exc)

    def _read_incoming_contents(
        self, incoming: Path, changes, selected: Optional[Sequence[str]] = None,
    ) -> Dict[str, str]:
        """读取新源侧章节正文（若触发块级三方自动合并则优先展示合并后正文）。"""
        by_rel = {getattr(item, "rel_path", ""): item for item in changes}
        wanted = (
            {str(item) for item in selected}
            if selected else set(by_rel.keys())
        )
        contents: Dict[str, str] = {}
        for rel_path in wanted:
            if not rel_path:
                continue
            change_obj = by_rel.get(rel_path)
            if (
                change_obj is not None
                and getattr(change_obj, "auto_merged", False)
                and getattr(change_obj, "merged_content", None) is not None
            ):
                contents[rel_path] = change_obj.merged_content
                continue
            target = incoming / rel_path
            if not target.is_file():
                continue
            try:
                contents[rel_path] = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
        return contents

    def _release_preview_staging(self) -> None:
        """删除上一轮预览的隔离目录（不影响正式正文与源记录）。"""
        import shutil

        staging = getattr(self, "_preview_staging", None)
        if staging:
            shutil.rmtree(str(staging), ignore_errors=True)
        self._preview_staging = None
        self._preview_root = None

    def preview_source_path(self) -> str:
        """最近一次预览的隔离新源目录（供无冲突项应用时复制资源）。"""
        return str(getattr(self, "_preview_root", "") or "")

    def reimport(
        self,
        new_source: Path,
        *,
        choices: Optional[Dict[str, bool]] = None,
        extractor: Optional[Callable[[Path, Path], None]] = None,
    ) -> ReimportResult:
        choices = choices or {}
        new_source = Path(new_source)
        staging = Path(tempfile.mkdtemp(prefix="doc-tool-reimport-", dir=str(self.paths.state_dir)))
        incoming = staging / "content"
        incoming.mkdir(parents=True)
        writer = self._writer()
        touched: List[Tuple[str, str]] = []
        old_sha = self.manifest.sourceSha256
        self._rollback_sha = old_sha
        self._source_replaced = False
        self._baseline_replaced = False
        source_path = self.paths.resolve(self.manifest.relative_source_docx())
        source_existed = source_path.is_file()
        self._source_existed = source_existed
        source_backup = self.paths.state_dir / "reimport_last_source.docx"
        try:
            if extractor is None:
                from doc_tool.adapters.importer import extract_content, split_into_tree
                from doc_tool.adapters.preflight import preflight

                heading_map = self._heading_style_map(new_source)
                preflight(new_source, heading_style_map=heading_map)
                extract_content(
                    new_source,
                    incoming,
                    staging / "images",
                    staging / "tables",
                    self.manifest.documentType,
                    heading_style_map=heading_map,
                )
                split_into_tree(incoming)
            else:
                extractor(new_source, incoming)
            # 合并暂存图片/复杂表格进项目资源，并取引用改写映射；随后清理
            # extract_content 在重导入暂存路径下误写到 ``.state/assets/`` 的
            # image-map/table-map（状态目录不该有资产，且永不清理）。
            asset_mapping = self._merge_incoming_assets(
                staging / "images", staging / "tables"
            )
            shutil.rmtree(self.paths.state_dir / "assets", ignore_errors=True)
            self._rewrite_incoming_contents(incoming, asset_mapping)
            changes = compare_chapters(
                writer.content_root,
                incoming,
                self._base_hashes(),
                self._base_texts(),
            )
            conflicts = [item.rel_path for item in changes if item.conflict]
            block_conflicts_map = {
                item.rel_path: list(item.block_conflicts)
                for item in changes
                if item.block_conflicts
            }
            for item in changes:
                if _is_revision_record(item.rel_path):
                    continue
                use_new = choices.get(item.rel_path, item.use_new)
                if item.status == "unchanged" or not use_new:
                    continue
                if item.status == "added":
                    text = (incoming / item.rel_path).read_text(encoding="utf-8")
                    result = writer.create_file(item.rel_path, text)
                    if result.written:
                        touched.append(("create", item.rel_path))
                elif item.status == "modified":
                    raw_source_text = (
                        item.merged_content
                        if (item.auto_merged and item.merged_content is not None)
                        else (incoming / item.rel_path).read_text(encoding="utf-8")
                    )
                    text = raw_source_text
                    if getattr(item, "renamed_from", None):
                        result = writer.create_file(item.rel_path, text)
                        if result.written:
                            touched.append(("create", item.rel_path))
                        if result.written and item.renamed_from != item.rel_path:
                            del_res = writer.delete_file(item.renamed_from)
                            if not del_res.written:
                                raise OSError(del_res.error or "Renamed chapter could not be removed")
                            touched.append(("delete", item.renamed_from))
                    else:
                        result = writer.write_text(item.rel_path, text)
                        if result.written:
                            touched.append(("edit", item.rel_path))
                else:
                    result = writer.delete_file(item.rel_path)
                    if result.written:
                        touched.append(("delete", item.rel_path))
                if not result.written:
                    raise OSError(result.error or "章节合并失败")
            self._rebuild_after_merge(writer)
            baseline = self.paths.state_dir / "reimport_base.json"
            baseline_backup = self.paths.state_dir / "reimport_last_base.json"
            self._base_existed = baseline.is_file()
            if self._base_existed:
                shutil.copy2(baseline, baseline_backup)
            else:
                baseline_backup.unlink(missing_ok=True)
            self._baseline_replaced = True
            self._save_reimport_base(incoming)
            # 先落事务记录，保证 rollback_last 始终可恢复；再做源替换与清单保存。
            atomic_write(self.transaction_file, json.dumps({
                "touched": [list(item) for item in touched],
                "oldSourceSha256": old_sha,
                "sourceBackup": str(source_backup),
                "sourceExisted": source_existed,
                "baseExisted": self._base_existed,
            }, ensure_ascii=False, indent=2))
            if source_path.is_file():
                shutil.copy2(source_path, source_backup)
            source_tmp = source_path.with_suffix(".docx.tmp")
            shutil.copy2(new_source, source_tmp)
            try:
                os.replace(str(source_tmp), str(source_path))
            except OSError:
                shutil.move(str(source_tmp), str(source_path))
            self._source_replaced = True
            self.manifest.sourceSha256 = file_sha256(source_path)
            self.manifest.save(self.paths.root, backup=True)
            # CORE-C 3.4：再次导入保存新的来源版本，旧原件（版本副本）不被覆盖。
            self._record_source_version(new_source)
            return ReimportResult(
                True,
                changes,
                conflicts,
                block_conflicts=block_conflicts_map,
            )
        except DocToolError as exc:
            self._rollback_reimport(writer, touched)
            return ReimportResult(False, error_code=exc.code, message=exc.user_message)
        except Exception as exc:
            self._rollback_reimport(writer, touched)
            return ReimportResult(False, error_code="E_REIMPORT", message=str(exc))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            # 源替换临时文件在 os.replace/shutil.move 双失败时残留：
            # 一律清理，避免 .docx.tmp 遗留在项目 original/ 目录。
            try:
                source_path.with_suffix(".docx.tmp").unlink(missing_ok=True)
            except OSError:
                pass

    def _record_source_version(self, new_source) -> None:
        """把本轮再次导入的源登记为新的来源版本（尽力而为，不影响导入结果）。

        写 ``original/versions/<sha8>-<文件名>`` 并追加到
        ``original/import-record.json``；旧占位仍能查到自己的原出处。
        """
        try:
            from doc_tool.application.import_record import (
                ImportRecord,
                append_source_version,
                archive_source_version,
                read_import_record,
                write_import_record,
            )

            record = read_import_record(self.paths.root)
            if record is None:
                record = ImportRecord(
                    sourceSha256=self.manifest.sourceSha256,
                    sourceFile=self.paths.source_docx.name,
                    actualPolicy="normal",
                    documentType=self.manifest.documentType,
                    documentName=self.manifest.documentName,
                    documentNo=self.manifest.documentNo,
                    documentVersion=self.manifest.documentVersion,
                )
            source = Path(new_source)
            if not source.is_file():
                source = self.paths.source_docx
            version = archive_source_version(
                self.paths.root, source, self.manifest.sourceSha256,
                note="再次导入来源版本",
            )
            append_source_version(record, version)
            record.sourceSha256 = self.manifest.sourceSha256
            record.sourceFile = source.name
            write_import_record(self.paths.root, record)
        except Exception:  # noqa: BLE001 - 账本记录失败不改变重导入结果
            pass

    def rollback_last(self) -> List[str]:
        payload = json.loads(self.transaction_file.read_text(encoding="utf-8"))
        writer = self._writer()
        touched = [tuple(item) for item in payload.get("touched", [])]
        failures = writer.rollback_keys(touched)
        backup = Path(str(payload.get("sourceBackup", "")))
        source = self.paths.resolve(self.manifest.relative_source_docx())
        if backup.is_file():
            shutil.copy2(backup, source)
        elif not payload.get("sourceExisted", True):
            # 源原本不存在且无备份：删除新源，恢复「无源文档」原状。
            source.unlink(missing_ok=True)
        self.manifest.sourceSha256 = str(payload.get("oldSourceSha256", ""))
        self.manifest.save(self.paths.root, backup=True)
        if "baseExisted" in payload:
            baseline = self.paths.state_dir / "reimport_base.json"
            if payload["baseExisted"]:
                shutil.copy2(self.paths.state_dir / "reimport_last_base.json", baseline)
            else:
                baseline.unlink(missing_ok=True)
        else:
            # Compatibility with transactions created before source baselines
            # were backed up independently from local content.
            self._save_reimport_base(writer.content_root)
        self._rebuild_after_merge(writer)
        return failures
