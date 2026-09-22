# -*- coding: utf-8 -*-
"""往返差异门禁适配器。

任务 2.4-2.5：自动执行「源 Word → Markdown → 重建 Word」往返构建后，对重建
产物与源 Word 做业务元素对比，复用 ``validate_docx.body_events``（正文业务事件
提取）与 ``compare_baseline_events``（顺序/文本基线比较），并按损失类型分级：

- BLOCK：业务元素数量不一致、正文段落丢失/变化、标题层级或文本变化、图片缺失、
  元素类型变化及未识别的差异格式（fail-closed）。
- WARN：仅表示性差异（如表格文本矩阵差异），默认放行。

本模块不直接构建文档；试构建由 ``import_project`` 在往返阶段前完成。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from doc_tool.adapters.fidelity import SEVERITY_BLOCK, SEVERITY_WARN

# 往返对比最多展示的差异条数（与 validate_docx.compare_baseline_events 一致）。
_MAX_ISSUES = 20


@dataclass(frozen=True)
class RoundtripIssue:
    """一项往返差异。"""

    severity: str
    message: str
    position: str
    source_desc: str = ""
    rebuilt_desc: str = ""

    def to_dict(self) -> Dict[str, str]:
        src = self.source_desc
        reb = self.rebuilt_desc
        if not src or not reb:
            if "：源 " in self.message and "，重建 " in self.message:
                m = re.search(r"：源 (.+?)，重建 (.+)$", self.message)
                if m:
                    src = src or m.group(1)
                    reb = reb or m.group(2)
            elif "：源 " in self.message:
                m = re.search(r"：源 (.+)$", self.message)
                if m:
                    src = src or m.group(1)
            elif "source " in self.message and "rebuild " in self.message:
                m = re.search(r"source\s+([^;]+);\s*rebuild\s+(.+)$", self.message)
                if m:
                    src = src or m.group(1)
                    reb = reb or m.group(2)
            elif "expected=" in self.message and "actual=" in self.message:
                m = re.search(r"expected=([^,]+),\s*actual=(.+)$", self.message)
                if m:
                    src = src or m.group(1)
                    reb = reb or m.group(2)
        return {
            "severity": self.severity,
            "position": self.position,
            "message": self.message,
            "source": src,
            "rebuilt": reb,
        }


@dataclass(frozen=True)
class RoundtripReport:
    """往返对比报告。"""

    source_count: int
    rebuilt_count: int
    issues: Tuple[RoundtripIssue, ...] = field(default_factory=tuple)

    @property
    def has_block(self) -> bool:
        return any(issue.severity == SEVERITY_BLOCK for issue in self.issues)

    @property
    def block_issues(self) -> Tuple[RoundtripIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == SEVERITY_BLOCK)

    @property
    def warn_issues(self) -> Tuple[RoundtripIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == SEVERITY_WARN)

    def format_issues(self, max_count: int = 5, only_block: bool = True) -> List[str]:
        """格式化差异列表，用于可读日志与错误提示。"""
        pool = self.block_issues if only_block and self.has_block else self.issues
        lines = [
            "• [{0} {1}] {2}".format(issue.severity, issue.position, issue.message)
            for issue in pool[:max_count]
        ]
        if len(pool) > max_count:
            lines.append("• ... 另有 {0} 项差异未展示".format(len(pool) - max_count))
        return lines

    def summary_text(self) -> str:
        """一行摘要（用于日志与成功项目持久化）。"""
        if not self.issues:
            return "往返差异：一致（{0} 项业务元素）".format(self.source_count)
        block = sum(1 for issue in self.block_issues)
        warn = len(self.issues) - block
        return "往返差异：{0} 项（BLOCK {1} / WARN {2}，元素 源{3}=重建{4}）".format(
            len(self.issues), block, warn, self.source_count, self.rebuilt_count
        )

    def markdown_text(self) -> str:
        """Markdown 报告（写入成功项目 logs/）。"""
        lines = [
            "## 往返差异报告",
            "",
            "- 源业务元素：{0}".format(self.source_count),
            "- 重建业务元素：{0}".format(self.rebuilt_count),
            "",
        ]
        if not self.issues:
            lines.append("重建产物与源 Word 业务元素一致。")
            return "\n".join(lines)
        lines.append("| 级别 | 位置 | 差异 |")
        lines.append("|------|------|------|")
        for issue in self.issues:
            lines.append("| {0} | {1} | {2} |".format(issue.severity, issue.position, issue.message))
        return "\n".join(lines)


def roundtrip_diff(
    source_docx: Union[str, Path],
    rebuilt_docx: Union[str, Path],
    heading_styles: Optional[Dict[int, str]] = None,
    allow_missing_headings: bool = False,
) -> RoundtripReport:
    """对源 Word 与重建 Word 执行业务元素往返对比。

    Args:
        source_docx: 源 Word 路径（已预检通过）。
        rebuilt_docx: 试构建重建的 Word 路径。
        heading_styles: 可选的标题映射（级别 -> styleId）；样式映射导入的
            自定义标题样式需按此识别，缺省时按样式名启发式识别。

    Returns:
        ``RoundtripReport`` 分级差异报告。

    Raises:
        Exception: 任一输入不是合法 DOCX 时由校验器抛出（调用方应在往返
            阶段前已验证试构建产物合法）。
    """
    from doc_tool.adapters.kernel import ensure_kernel_importable

    ensure_kernel_importable()
    from validate_docx import DocxPackage, compare_baseline_events  # noqa: E402

    source = DocxPackage(str(source_docx), heading_styles=heading_styles)
    rebuilt = DocxPackage(str(rebuilt_docx), heading_styles=heading_styles)
    source_events = source.body_events(allow_missing_headings=allow_missing_headings)
    rebuilt_events = rebuilt.body_events(allow_missing_headings=allow_missing_headings)
    errors = compare_baseline_events(source_events, rebuilt_events)
    issues: List[RoundtripIssue] = []
    for error in errors:
        issues.append(_classify_error(error, source_events, rebuilt_events))
        if len(issues) >= _MAX_ISSUES:
            break
    return RoundtripReport(len(source_events), len(rebuilt_events), tuple(issues))


def _classify_error(
    error: str,
    source_events,
    rebuilt_events,
) -> RoundtripIssue:
    """把 ``compare_baseline_events`` 的差异串按损失类型分级。"""
    if error.startswith("业务元素数量不一致"):
        return RoundtripIssue(
            SEVERITY_BLOCK,
            error,
            "#count",
            source_desc="count={0}".format(len(source_events)),
            rebuilt_desc="count={0}".format(len(rebuilt_events)),
        )
    match = re.match(r"^#(\d+)\s+(?:基线)?(?:内容|类型)?(?:/位置)?不一致:\s*(.+)$", error)
    if not match:
        # 未识别的差异格式一律按内容丢失 BLOCK（fail-closed）：避免未来
        # compare_baseline_events 新增差异格式时被默认 WARN 静默放行。
        return RoundtripIssue(SEVERITY_BLOCK, error, "#?")
    index = int(match.group(1))
    detail = match.group(2)
    position = "#{0}".format(index)
    if index >= len(source_events) or index >= len(rebuilt_events):
        return RoundtripIssue(
            SEVERITY_BLOCK,
            error,
            position,
            source_desc="len={0}".format(len(source_events)),
            rebuilt_desc="len={0}".format(len(rebuilt_events)),
        )

    left_event = source_events[index]
    right_event = rebuilt_events[index]
    left_kind = left_event.kind
    right_kind = right_event.kind
    src_desc = "{0}={1!r}".format(left_kind, left_event.value)
    reb_desc = "{0}={1!r}".format(right_kind, right_event.value)

    if left_kind == "H" or right_kind == "H":
        return RoundtripIssue(
            SEVERITY_BLOCK,
            "标题层级或文本变化：{0}".format(detail),
            position,
            source_desc=src_desc,
            rebuilt_desc=reb_desc,
        )
    if left_kind == "I" or right_kind == "I":
        return RoundtripIssue(
            SEVERITY_BLOCK,
            "图片对象缺失或变化：{0}".format(detail),
            position,
            source_desc=src_desc,
            rebuilt_desc=reb_desc,
        )
    if left_kind in {"P", "L", "X"} and right_kind in {"P", "L", "X"}:
        left_text = _event_text(left_event)
        right_text = _event_text(right_event)
        from docx_common import _is_event_text_equivalent
        if _is_event_text_equivalent(_strip_manual_prefix(left_text), _strip_manual_prefix(right_text)):
            if {left_kind, right_kind} == {"P", "L"}:
                msg = "正文段落以自动编号列表重建（内容保留）：{0}".format(detail)
            elif "X" in {left_kind, right_kind}:
                msg = "超链接或注记段落表示差异（内容保留）：{0}".format(detail)
            elif left_kind == "L" and right_kind == "L":
                msg = "列表项层级或格式表示差异（内容保留）：{0}".format(detail)
            else:
                msg = "正文段落格式或表示差异（内容保留）：{0}".format(detail)
            return RoundtripIssue(
                SEVERITY_WARN,
                msg,
                position,
                source_desc=src_desc,
                rebuilt_desc=reb_desc,
            )
        return RoundtripIssue(
            SEVERITY_BLOCK,
            "正文段落丢失或文本变化：{0}".format(detail),
            position,
            source_desc=src_desc,
            rebuilt_desc=reb_desc,
        )
    if left_kind in {"T", "C"} and right_kind in {"T", "C"}:
        # 同 kind（T/C 表格）仅是文本矩阵表示差异，按 WARN 放行；
        # 元素类型不一致（如 T 变 P）按内容丢失 BLOCK。
        return RoundtripIssue(
            SEVERITY_WARN,
            "表格表示差异：{0}".format(detail),
            position,
            source_desc=src_desc,
            rebuilt_desc=reb_desc,
        )
    return RoundtripIssue(
        SEVERITY_BLOCK,
        "元素类型变化：{0}".format(detail),
        position,
        source_desc=src_desc,
        rebuilt_desc=reb_desc,
    )


def _event_text(event) -> str:
    """事件比较文本：L 事件 value 是 (text, ilvl, ...) 元组，其余是字符串。"""
    value = event.value
    return str(value[0]) if event.kind == "L" and isinstance(value, tuple) and value else str(value)


_MANUAL_PREFIX_RE = re.compile(
    r"^(?:(?:\d{1,3}、\s*)|(?:\d{1,3}[.．](?!\d)\s*)|(?:[-*•+]\s+)|(?:[\(（\[【](?:\d{1,3}|[一二三四五六七八九十]+|[a-zA-Z]|[ivxIVX]+)[\)）\]】]\s*)|(?:[\u2460-\u2473①②③④⑤⑥⑦⑧⑨⑩]\s*)|(?:[一二三四五六七八九十]+[、.．]\s*)|(?:(?:\d{1,3}|[一二三四五六七八九十]+|[a-zA-Z]|[ivxIVX]+)[\)）]\s*)|(?:[a-zA-Z][.．](?!\w)\s*))"
)


def _strip_manual_prefix(text: str) -> str:
    """去掉开头的字面编号或列表符号（如 ``1. 概述``、``1、概述``、``- 列表项``），用于段落文本对齐。"""
    stripped = text.strip()
    return _MANUAL_PREFIX_RE.sub("", stripped).strip()


def _without_manual_number(text: str) -> str:
    """向后兼容别名。"""
    return _strip_manual_prefix(text)
