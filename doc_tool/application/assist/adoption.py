# -*- coding: utf-8 -*-
"""V3.3 33-C 差异采纳与撤销：只改编辑缓冲的一次事务。

语义（design.md D3、specs 差异采纳与撤销）：

- 收件区展示 before/after、来源与范围；用户选择采纳/忽略。
- 采纳只修改目标**编辑缓冲**，整批改动合成一个事务，支持**一次撤销**；
  保存仍走既有 ``ContentWriter``（本模块不写正文）。
- 目标自建议产生后变化：能唯一定位就按当前内容重算后应用，出现零/多处匹配
  则标冲突并跳过，保留用户内容；其余已选合法建议继续应用。
- 修订摘要类建议只填"原修订框候选"，不自动追加修订记录。
- 只读项目可查看/导出建议文字，不能写原文。
- ``side_effects`` 恒为空：不自动改复核状态、追踪关系、门禁或版本号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from doc_tool.application.content.changes import render_unified_diff
from doc_tool.application.assist.models import (
    APPLY_INSERT, APPLY_NONE, APPLY_REPLACE,
    KIND_LABELS, KIND_REVISION_SUMMARY,
    STATUS_ACCEPTED, STATUS_CONFLICT, STATUS_IGNORED, STATUS_UNAVAILABLE, display_path,
)
from doc_tool.application.assist.suggestions import Suggestion

#: 应用结果内部状态词。
RESULT_OK = "ok"
RESULT_CONFLICT = "conflict"
RESULT_STALE = "stale"


@dataclass
class AppliedChange:
    """一条已应用到缓冲的改动（含 before/after 与差异）。"""

    suggestion_id: str
    kind: str
    title: str
    rel_path: str
    start_line: int = 0
    before: str = ""
    after: str = ""
    mode: str = APPLY_REPLACE
    refreshed: bool = False
    evidence: List[dict] = field(default_factory=list)

    @property
    def diff_text(self) -> str:
        return render_unified_diff(self.before, self.after)

    def to_dict(self) -> dict:
        return {
            "suggestionId": self.suggestion_id,
            "kind": self.kind,
            "kindLabel": KIND_LABELS.get(self.kind, self.kind),
            "title": self.title,
            "relPath": display_path(self.rel_path),
            "startLine": self.start_line,
            "before": self.before,
            "after": self.after,
            "mode": self.mode,
            "refreshed": self.refreshed,
            "diff": self.diff_text,
            "evidence": list(self.evidence),
        }


@dataclass
class AdoptionTransaction:
    """一次采纳事务：记录采纳前缓冲文本，支持一次撤销。"""

    transaction_id: str
    before_texts: Dict[str, str] = field(default_factory=dict)
    applied_ids: List[str] = field(default_factory=list)
    undone: bool = False

    def undo(self) -> Tuple[bool, Dict[str, str], str]:
        """撤销一次；第二次调用不再改动缓冲。"""
        if self.undone:
            return False, {}, "本次采纳已经撤销过（一次撤销已完成），缓冲未再次改动。"
        self.undone = True
        return True, dict(self.before_texts), "已恢复到采纳前的缓冲内容（未保存，未改变评审/版本状态）。"

    def to_dict(self) -> dict:
        return {
            "transactionId": self.transaction_id,
            "appliedIds": list(self.applied_ids),
            "paths": sorted(self.before_texts),
            "undone": self.undone,
        }


@dataclass
class AdoptionOutcome:
    """一次采纳的结果（先给可用改动，再集中说明冲突/未执行）。"""

    applied: List[AppliedChange] = field(default_factory=list)
    conflicts: List[Tuple[str, str]] = field(default_factory=list)
    stale: List[Tuple[str, str]] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)
    not_applicable: List[Tuple[str, str]] = field(default_factory=list)
    unknown_ids: List[str] = field(default_factory=list)
    buffer_updates: Dict[str, str] = field(default_factory=dict)
    summary_candidates: Dict[str, str] = field(default_factory=dict)
    read_only: bool = False
    read_only_reason: str = ""
    side_effects: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    transaction: Optional[AdoptionTransaction] = None

    @property
    def changed_paths(self) -> List[str]:
        return sorted(self.buffer_updates)

    @property
    def changed_review_state(self) -> bool:
        """是否改动了复核/关系/版本状态（始终 False）。"""
        return bool([item for item in self.side_effects if item])

    def diff_text(self) -> str:
        parts = [item.diff_text for item in self.applied if item.diff_text]
        return "\n".join(parts)

    def summary_lines(self) -> List[str]:
        lines = ["已采纳 {0} 条建议，改动 {1} 个缓冲文件（未保存）".format(
            len(self.applied), len(self.changed_paths)
        )]
        if self.summary_candidates:
            lines.append("收到 {0} 条修订摘要候选（只填原修订框，不自动追加）。".format(
                len(self.summary_candidates)
            ))
        if self.ignored:
            lines.append("{0} 条已忽略。".format(len(self.ignored)))
        if self.conflicts:
            lines.append("{0} 条目标冲突已跳过，保留用户内容。".format(len(self.conflicts)))
        if self.stale:
            lines.append("{0} 条目标不可用已跳过。".format(len(self.stale)))
        if self.not_applicable:
            lines.append("{0} 条仅提示，不改正文。".format(len(self.not_applicable)))
        if self.unknown_ids:
            lines.append("{0} 条选择已失效（不在当前建议集）。".format(len(self.unknown_ids)))
        lines.extend(self.notes)
        return lines

    def to_dict(self) -> dict:
        return {
            "applied": [item.to_dict() for item in self.applied],
            "conflicts": [{"suggestionId": sid, "reason": reason} for sid, reason in self.conflicts],
            "stale": [{"suggestionId": sid, "reason": reason} for sid, reason in self.stale],
            "ignored": list(self.ignored),
            "notApplicable": [
                {"suggestionId": sid, "reason": reason} for sid, reason in self.not_applicable
            ],
            "unknownIds": list(self.unknown_ids),
            "changedPaths": self.changed_paths,
            "summaryCandidates": dict(self.summary_candidates),
            "readOnly": self.read_only,
            "readOnlyReason": self.read_only_reason,
            "sideEffects": list(self.side_effects),
            "notes": list(self.notes),
            "summary": self.summary_lines(),
            "diff": self.diff_text(),
            "transaction": self.transaction.to_dict() if self.transaction else None,
        }


class AdoptionSession:
    """建议收件区的采纳/忽略/撤销会话（纯缓冲操作，不写盘）。"""

    def __init__(self, *, read_only: bool = False, read_only_reason: str = "") -> None:
        self._read_only = bool(read_only)
        self._read_only_reason = read_only_reason or "只读项目：可查看/导出建议文字，不写原文。"
        self._ignored: List[str] = []
        self._transactions: List[AdoptionTransaction] = []

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def ignored(self) -> List[str]:
        return list(self._ignored)

    @property
    def transactions(self) -> List[AdoptionTransaction]:
        return list(self._transactions)

    def ignore(self, suggestion_id: str) -> str:
        """忽略一条建议（不记入采纳事务）。"""
        if suggestion_id and suggestion_id not in self._ignored:
            self._ignored.append(suggestion_id)
        return STATUS_IGNORED

    def adopt(
        self,
        suggestions: Sequence[Suggestion],
        selected_ids: Sequence[str],
        texts: Dict[str, str],
        *,
        include_ignored: bool = False,
    ) -> AdoptionOutcome:
        """采纳所选建议：返回缓冲更新与一个可撤销事务。"""
        outcome = AdoptionOutcome(
            read_only=self._read_only,
            read_only_reason=self._read_only_reason if self._read_only else "",
        )
        by_id = {item.suggestion_id: item for item in suggestions or ()}
        selected: List[Suggestion] = []
        for suggestion_id in selected_ids or ():
            item = by_id.get(suggestion_id)
            if item is None:
                outcome.unknown_ids.append(suggestion_id)
                continue
            if suggestion_id in self._ignored and not include_ignored:
                outcome.ignored.append(suggestion_id)
                continue
            selected.append(item)
        if self._read_only:
            for item in selected:
                outcome.not_applicable.append(
                    (item.suggestion_id, "只读项目：不写原文，可查看或导出文字。")
                )
            outcome.notes.append(self._read_only_reason)
            return outcome

        working: Dict[str, str] = {display_path(key): value for key, value in (texts or {}).items()}
        before_texts: Dict[str, str] = {}
        for item in selected:
            if item.kind == KIND_REVISION_SUMMARY or item.apply_mode == APPLY_NONE:
                if item.after:
                    outcome.summary_candidates[item.suggestion_id] = item.after
                    outcome.not_applicable.append(
                        (item.suggestion_id, "只填候选框/提示，不改正文。")
                    )
                else:
                    outcome.not_applicable.append(
                        (item.suggestion_id, "范围不足或缺少依据，仅提示。")
                    )

        groups: Dict[str, List[Suggestion]] = {}
        for item in selected:
            if item.apply_mode not in (APPLY_REPLACE, APPLY_INSERT):
                continue
            rel_path = display_path(item.target_rel_path)
            if rel_path not in working:
                outcome.stale.append(
                    (item.suggestion_id, "目标不在当前编辑缓冲范围内，未改动。")
                )
                continue
            groups.setdefault(rel_path, []).append(item)

        applied_changes: List[AppliedChange] = []
        for rel_path, items in sorted(groups.items()):
            current = working[rel_path]
            baseline = current
            ordered = sorted(items, key=lambda item: (-(item.start_line or 0), item.suggestion_id))
            for item in ordered:
                if item.status in (STATUS_CONFLICT, STATUS_UNAVAILABLE):
                    outcome.conflicts.append((item.suggestion_id, "建议已标记不可用/冲突，已跳过。"))
                    continue
                if item.apply_mode == APPLY_REPLACE:
                    new_text, result, detail, line_no, refreshed = self._apply_replace(current, item)
                else:
                    new_text, result, detail, line_no, refreshed = self._apply_insert(current, item)
                if result == RESULT_CONFLICT:
                    outcome.conflicts.append((item.suggestion_id, detail))
                    continue
                if result != RESULT_OK:
                    outcome.stale.append((item.suggestion_id, detail))
                    continue
                item.mark(STATUS_ACCEPTED, "已采纳到编辑缓冲（未保存）。")
                current = new_text
                applied_changes.append(AppliedChange(
                    suggestion_id=item.suggestion_id,
                    kind=item.kind,
                    title=item.title,
                    rel_path=rel_path,
                    start_line=line_no,
                    before=item.before,
                    after=item.after,
                    mode=item.apply_mode,
                    refreshed=refreshed,
                    evidence=[entry.to_dict() for entry in item.evidence],
                ))
            if current != baseline:
                before_texts[rel_path] = baseline
                working[rel_path] = current

        outcome.applied = applied_changes
        outcome.side_effects = []  # 不自动改复核/关系/门禁/版本
        if before_texts:
            outcome.buffer_updates = {rel: working[rel] for rel in before_texts}
            transaction = AdoptionTransaction(
                transaction_id="adopt-" + uuid4().hex[:10],
                before_texts=before_texts,
                applied_ids=[item.suggestion_id for item in applied_changes],
            )
            self._transactions.append(transaction)
            outcome.transaction = transaction
            outcome.notes.append("采纳只修改编辑缓冲；保存仍走既有 ContentWriter。")
        else:
            outcome.notes.append("没有可应用的改动，编辑缓冲保持不变。")
        if not outcome.applied and not outcome.summary_candidates:
            outcome.notes.append("未执行任何正文改动。")
        return outcome

    def undo(self, outcome: AdoptionOutcome) -> Tuple[bool, Dict[str, str], str]:
        """撤销某次采纳（一次）；返回 (是否执行, 恢复的缓冲, 说明)。"""
        transaction = outcome.transaction if outcome is not None else None
        if transaction is None:
            return False, {}, "本次没有可撤销的采纳改动。"
        return transaction.undo()

    # --- 统一 diff / 只读导出 ---

    def preview_diff(self, suggestions: Sequence[Suggestion], selected_ids: Sequence[str]) -> str:
        """采纳前预览 before/after 差异（复用既有 diff 渲染）。"""
        parts: List[str] = []
        by_id = {item.suggestion_id: item for item in suggestions or ()}
        for suggestion_id in selected_ids or ():
            item = by_id.get(suggestion_id)
            if item is None:
                continue
            diff = render_unified_diff(item.before, item.after)
            header = "## {0}（{1}）".format(item.title, item.status_label)
            parts.append(header)
            parts.append(diff or "（无文本差异：仅提示或填写候选）")
        return "\n".join(parts)

    def export_text(
        self, suggestions: Sequence[Suggestion], selected_ids: Optional[Sequence[str]] = None
    ) -> str:
        """只读查看/导出建议文字（含 before/after 与依据）。"""
        wanted = set(selected_ids or ())
        lines: List[str] = ["# 写作建议导出（只读）", ""]
        for item in suggestions or ():
            if wanted and item.suggestion_id not in wanted:
                continue
            lines.append("- [{0}] {1}｜{2}｜{3}".format(
                item.kind_label, item.title, item.status_label, item.coverage_label
            ))
            if item.target_rel_path:
                lines.append("  目标：{0}:{1}".format(
                    display_path(item.target_rel_path), item.start_line
                ))
            if item.before:
                lines.append("  before：{0}".format(item.before.replace("\n", " ")[:200]))
            if item.after:
                lines.append("  after：{0}".format(item.after.replace("\n", " ")[:400]))
            for evidence in item.evidence:
                lines.append("  依据：{0}｜{1}".format(
                    evidence.label, evidence.detail or evidence.locator
                ))
        return "\n".join(lines)

    # --- 内部：单条应用 ---

    @staticmethod
    def _apply_replace(text: str, item: Suggestion) -> Tuple[str, str, str, int, bool]:
        needle = item.before
        if not needle:
            return text, RESULT_STALE, "建议缺少可替换文本，已跳过。", 0, False
        lines = text.split("\n")
        total_matches = text.count(needle)
        if not total_matches:
            return text, RESULT_CONFLICT, "目标文本已变化，未找到待替换内容，保留用户内容。", 0, False
        prefer = item.start_line or 0
        target_line = 0
        if 1 <= prefer <= len(lines) and needle in lines[prefer - 1]:
            target_line = prefer
        elif total_matches == 1:
            candidates = [index for index, line in enumerate(lines, start=1) if needle in line]
            target_line = candidates[0] if candidates else 0
        if not target_line:
            return text, RESULT_CONFLICT, "目标存在多处匹配，保留用户内容并跳过。", 0, False
        refreshed = target_line != (item.start_line or 0)
        new_lines = list(lines)
        new_lines[target_line - 1] = new_lines[target_line - 1].replace(needle, item.after, 1)
        return "\n".join(new_lines), RESULT_OK, "", target_line, refreshed

    @staticmethod
    def _apply_insert(text: str, item: Suggestion) -> Tuple[str, str, str, int, bool]:
        block = (item.after or "").rstrip("\n")
        if not block:
            return text, RESULT_STALE, "建议没有可插入内容，已跳过。", 0, False
        if item.after.strip() and item.after.strip() in text:
            return text, RESULT_CONFLICT, "目标中已存在同名内容，保留用户内容并跳过。", 0, False
        if not text:
            separator = ""
        elif text.endswith("\n\n"):
            separator = ""
        elif text.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        new_text = text + separator + block + "\n"
        return new_text, RESULT_OK, "", len(text.split("\n")), False