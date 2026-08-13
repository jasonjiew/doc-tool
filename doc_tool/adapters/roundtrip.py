# -*- coding: utf-8 -*-
"""往返差异门禁适配器。

任务 2.4-2.5：自动执行「源 Word → Markdown → 重建 Word」往返构建后，对重建
产物与源 Word 做业务元素对比，复用 ``validate_docx.body_events``（正文业务事件
提取）与 ``compare_baseline_events``（顺序/文本基线比较），并按损失类型分级：

- BLOCK：业务元素数量不一致、正文段落丢失/变化、标题层级或文本变化、图片缺失。
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
    source_events = source.body_events()
    rebuilt_events = rebuilt.body_events()
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
        return RoundtripIssue(SEVERITY_BLOCK, error, "#count")
    match = re.match(r"^#(\d+)\s+基线内容/位置不一致:\s*(.+)$", error)
    if not match:
        return RoundtripIssue(SEVERITY_WARN, error, "#?")
    index = int(match.group(1))
    detail = match.group(2)
    left_kind = source_events[index].kind
    right_kind = rebuilt_events[index].kind
    position = "#{0}".format(index)
    if left_kind == "H" or right_kind == "H":
        return RoundtripIssue(SEVERITY_BLOCK, "标题层级或文本变化：{0}".format(detail), position)
    if left_kind == "I" or right_kind == "I":
        return RoundtripIssue(SEVERITY_BLOCK, "图片对象缺失或变化：{0}".format(detail), position)
    if left_kind == "P" or right_kind == "P":
        # 纯文本段落与列表项的表示差异：源 Word 里以字面编号开头（如 ``1. 概述``、
        # 无 numPr）的段落，迁移成 markdown ``1. x`` 后会被重建为自动编号列表。
        # 去掉 P 端字面编号前缀后文本一致 → 内容并未丢失，降级 WARN 放行，避免
        # 合法文档在默认导入门禁被 BLOCK。文本确实不一致才按内容丢失 BLOCK。
        if {left_kind, right_kind} == {"P", "L"}:
            left_text = _event_text(source_events[index])
            right_text = _event_text(rebuilt_events[index])
            if _without_manual_number(left_text) == _without_manual_number(right_text):
                return RoundtripIssue(
                    SEVERITY_WARN,
                    "正文段落以自动编号列表重建（内容保留）：{0}".format(detail),
                    position,
                )
        return RoundtripIssue(SEVERITY_BLOCK, "正文段落丢失或文本变化：{0}".format(detail), position)
    return RoundtripIssue(SEVERITY_WARN, "表格或元素表示差异：{0}".format(detail), position)


def _event_text(event) -> str:
    """事件比较文本：L 事件 value 是 (text, ilvl, ...) 元组，其余是字符串。"""
    value = event.value
    return str(value[0]) if event.kind == "L" and isinstance(value, tuple) and value else str(value)


_MANUAL_NUM_RE = re.compile(r"^\d{1,3}[.、．]\s*")


def _without_manual_number(text: str) -> str:
    """去掉开头的字面编号（``1. 概述`` → ``概述``），用于 P/L 文本对齐。"""
    return _MANUAL_NUM_RE.sub("", text)
